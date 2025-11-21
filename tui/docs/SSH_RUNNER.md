# SSH Runner - Remote CRYSTAL23 Execution

## Overview

The SSH Runner enables execution of CRYSTAL23 calculations on remote machines via SSH. It provides a complete workflow including file transfer, remote execution, process monitoring, and result retrieval.

## Architecture

```
Local Machine                    Remote Machine
─────────────                    ──────────────
┌──────────────┐                ┌──────────────┐
│   TUI App    │                │              │
└──────┬───────┘                │              │
       │                        │              │
┌──────▼───────┐                │              │
│  SSHRunner   │                │              │
└──────┬───────┘                │              │
       │                        │              │
┌──────▼───────┐   SSH/SFTP    ┌▼─────────────▼┐
│ Connection   ├───────────────►│ CRYSTAL23    │
│  Manager     │                │  Executable  │
└──────────────┘                └──────────────┘
       │                        │              │
       │                        │              │
    asyncssh                    │  Job Output  │
       │                        │              │
       └────────────────────────┴──────────────┘
```

## Key Features

1. **File Transfer via SFTP**
   - Upload input files (.d12, .gui, .f9)
   - Download output files (.out, fort.9, fort.98)
   - Automatic handling of all CRYSTAL file types

2. **Remote Process Management**
   - Background job execution (nohup)
   - PID tracking and monitoring
   - Process status checks via `ps`
   - Graceful termination (SIGTERM/SIGKILL)

3. **Output Streaming**
   - Real-time output via `tail -f`
   - AsyncIterator interface for UI integration
   - Connection resilience

4. **Connection Pooling**
   - Reuse SSH connections across jobs
   - Automatic reconnection on failure
   - Health monitoring
   - Configurable connection limits

5. **Environment Setup**
   - Source cry23.bashrc automatically
   - Configure OpenMP threads
   - Support MPI execution
   - Custom environment variables

## Installation

### Requirements

```bash
pip install asyncssh>=2.14.0
```

### SSH Configuration

On the remote machine, ensure:
1. CRYSTAL23 is installed with `cry23.bashrc`
2. SSH key-based authentication is configured
3. Work directory is writable

```bash
# Setup SSH keys (if not already done)
ssh-keygen -t ed25519
ssh-copy-id user@remote-host

# Test connection
ssh user@remote-host "echo 'Connection successful'"
```

## Usage

### Basic Usage

```python
import asyncio
from pathlib import Path
from src.runners.ssh_runner import SSHRunner
from src.core.connection_manager import ConnectionManager

async def run_remote_job():
    # Setup connection manager
    manager = ConnectionManager()
    manager.register_cluster(
        cluster_id=1,
        host="remote.university.edu",
        port=22,
        username="myuser",
        key_file=Path.home() / ".ssh/id_ed25519"
    )

    # Create SSH runner
    runner = SSHRunner(
        connection_manager=manager,
        cluster_id=1,
        remote_crystal_root=Path("/home/myuser/CRYSTAL23"),
        remote_scratch_dir=Path("/scratch/myuser/crystal_jobs")
    )

    # Submit job
    job_handle = await runner.submit_job(
        job_id=1,
        work_dir=Path("./my_calculation"),
        input_file=Path("./my_calculation/input.d12"),
        threads=8
    )

    print(f"Job submitted: {job_handle}")

    # Stream output
    async for line in runner.get_output(job_handle):
        print(line)

    # Wait for completion
    while await runner.get_status(job_handle) == "running":
        await asyncio.sleep(5)

    # Retrieve results
    result = await runner.retrieve_results(
        job_handle,
        Path("./my_calculation")
    )

    if result.success:
        print(f"✓ Job completed successfully")
        print(f"  Final energy: {result.final_energy} Ha")
    else:
        print(f"✗ Job failed")
        for error in result.errors:
            print(f"  Error: {error}")

    # Cleanup
    await runner.cleanup(job_handle, remove_files=True)

# Run
asyncio.run(run_remote_job())
```

### With MPI

```python
# Submit job with MPI
job_handle = await runner.submit_job(
    job_id=1,
    work_dir=Path("./my_calculation"),
    input_file=Path("./my_calculation/input.d12"),
    threads=4,        # OpenMP threads per rank
    mpi_ranks=8       # MPI processes
)
```

### Connection Management

```python
# Setup connection manager with multiple clusters
manager = ConnectionManager(max_connections=10)

# Cluster 1: SSH key authentication
manager.register_cluster(
    cluster_id=1,
    host="cluster1.edu",
    username="user",
    key_file=Path.home() / ".ssh/id_ed25519"
)

# Cluster 2: Password authentication
manager.register_cluster(
    cluster_id=2,
    host="cluster2.edu",
    username="user",
    use_agent=False
)
manager.set_password(cluster_id=2, password="secret123")

# Test connectivity
is_healthy = await manager.health_check(cluster_id=1)
print(f"Cluster 1 healthy: {is_healthy}")

# Validate cluster configuration
validation = await manager.validate_cluster(cluster_id=1)
if validation["valid"]:
    print("✓ Cluster configuration is valid")
else:
    for error in validation["errors"]:
        print(f"✗ {error}")
```

### Advanced Configuration

```python
from src.core.connection_manager import ClusterConfig

# Create custom cluster configuration
config = ClusterConfig(
    name="HPC Cluster",
    hostname="hpc.university.edu",
    username="myuser",
    port=2222,  # Custom SSH port
    key_file=Path.home() / ".ssh/hpc_key",
    crystal_root=Path("/opt/crystal23"),
    crystal_exedir=Path("/opt/crystal23/bin/Linux-ifort/v1.0.1"),
    scratch_dir=Path("/scratch/users/myuser"),
    connect_timeout=60,
    keepalive_interval=30,
    max_concurrent_jobs=20,
    default_threads=8,
    default_mpi_ranks=None,
    options={
        "use_batch_system": False,
        "load_modules": ["intel/2023", "openmpi/4.1.4"]
    }
)

manager.register_cluster(config)
```

## Remote Execution Flow

### 1. Job Submission

```
1. Validate input file exists locally
2. Create remote work directory:
   ~/crystal_jobs/job_<id>_<timestamp>/
3. Upload files via SFTP:
   - input.d12 (required)
   - *.gui (geometry, if exists)
   - *.f9 (wave function, if exists)
   - *.f20, *.hessopt, etc.
4. Generate execution script (run_job.sh)
5. Upload and chmod +x execution script
6. Execute: nohup bash run_job.sh > output.log 2>&1 &
7. Capture PID
8. Return job handle: "cluster_id:PID:remote_work_dir"
```

### 2. Execution Script

The generated `run_job.sh` script:

```bash
#!/bin/bash
set -e  # Exit on error

# Change to work directory
cd /home/user/crystal_jobs/job_1_20231120_143022

# Source CRYSTAL environment
if [ -f /home/user/CRYSTAL23/cry23.bashrc ]; then
    source /home/user/CRYSTAL23/cry23.bashrc
fi

# Set OpenMP threads
export OMP_NUM_THREADS=8

# Print environment info
echo "=== CRYSTAL23 Job Starting ==="
echo "Date: $(date)"
echo "Host: $(hostname)"
echo "Work dir: $(pwd)"
echo "Executable: crystalOMP"
echo "OMP_NUM_THREADS: $OMP_NUM_THREADS"
echo "================================"

# Run CRYSTAL
/home/user/CRYSTAL23/bin/*/v*/crystalOMP < input.d12

# Capture exit code
EXIT_CODE=$?

echo ""
echo "=== CRYSTAL23 Job Finished ==="
echo "Date: $(date)"
echo "Exit code: $EXIT_CODE"
echo "================================"

exit $EXIT_CODE
```

### 3. Process Monitoring

```python
# Check if process is running
result = await conn.run(f"ps -p {pid} > /dev/null 2>&1 && echo running || echo stopped")

if "running" in result.stdout:
    status = "running"
else:
    # Check output file for errors
    result = await conn.run(
        f"grep -i 'error\\|failed\\|abort' {remote_work_dir}/output.log "
        f"> /dev/null 2>&1 && echo failed || echo completed"
    )
    status = "failed" if "failed" in result.stdout else "completed"
```

### 4. Output Streaming

```python
# Stream output using tail -f
tail_cmd = f"tail -f {remote_work_dir}/output.log"
async with conn.create_process(tail_cmd) as process:
    async for line in process.stdout:
        yield line.strip()

        # Check if job finished
        status = await self.get_status(job_handle)
        if status in ("completed", "failed", "cancelled"):
            break
```

### 5. Result Retrieval

```
1. Verify job is complete (not still running)
2. Download output files via SFTP:
   - output.log (main output)
   - fort.9, fort.98 (wave functions)
   - fort.25 (properties)
   - *.xyz, *.cif (structures)
3. Parse output.log using CRYSTALpytools
4. Extract:
   - Final energy
   - Convergence status
   - Errors and warnings
5. Return JobResult object
```

## Error Handling

### Connection Errors

```python
from src.runners.base import ConnectionError

try:
    job_handle = await runner.submit_job(...)
except ConnectionError as e:
    print(f"Connection failed: {e}")
    # Possible causes:
    # - SSH authentication failure
    # - Network unreachable
    # - Remote host down
    # - Firewall blocking connection
```

### Job Submission Errors

```python
from src.runners.base import JobSubmissionError

try:
    job_handle = await runner.submit_job(...)
except JobSubmissionError as e:
    print(f"Submission failed: {e}")
    # Possible causes:
    # - Input file missing
    # - Remote directory not writable
    # - CRYSTAL executable not found
    # - Insufficient permissions
```

### Job Not Found

```python
from src.runners.base import JobNotFoundError

try:
    status = await runner.get_status("invalid:handle")
except JobNotFoundError as e:
    print(f"Job not found: {e}")
    # Job handle is invalid or job was cleaned up
```

## Best Practices

### 1. Connection Pooling

Reuse ConnectionManager across multiple jobs:

```python
# ✓ GOOD: Reuse connection manager
manager = ConnectionManager()
runner1 = SSHRunner(manager, cluster_id=1)
runner2 = SSHRunner(manager, cluster_id=1)  # Reuses connections

# ✗ BAD: New manager for each runner
runner1 = SSHRunner(ConnectionManager(), cluster_id=1)
runner2 = SSHRunner(ConnectionManager(), cluster_id=1)  # New connections
```

### 2. Resource Cleanup

Always cleanup after job completion:

```python
try:
    job_handle = await runner.submit_job(...)
    result = await runner.retrieve_results(job_handle, work_dir)
finally:
    # Remove remote files if successful
    await runner.cleanup(job_handle, remove_files=result.success)
```

### 3. Error Recovery

Implement retry logic for transient failures:

```python
import asyncio
from src.runners.base import ConnectionError

MAX_RETRIES = 3

for attempt in range(MAX_RETRIES):
    try:
        job_handle = await runner.submit_job(...)
        break
    except ConnectionError as e:
        if attempt < MAX_RETRIES - 1:
            wait_time = 2 ** attempt  # Exponential backoff
            print(f"Connection failed, retrying in {wait_time}s...")
            await asyncio.sleep(wait_time)
        else:
            raise
```

### 4. Concurrent Jobs

Limit concurrent job submissions:

```python
import asyncio

async def submit_with_semaphore(runner, semaphore, *args, **kwargs):
    async with semaphore:
        return await runner.submit_job(*args, **kwargs)

# Limit to 5 concurrent submissions
semaphore = asyncio.Semaphore(5)

tasks = [
    submit_with_semaphore(runner, semaphore, job_id=i, ...)
    for i in range(20)
]

job_handles = await asyncio.gather(*tasks)
```

### 5. Health Monitoring

Periodically check cluster health:

```python
async def monitor_cluster_health(manager, cluster_id, interval=300):
    """Monitor cluster health every 5 minutes."""
    while True:
        is_healthy = await manager.health_check(cluster_id)
        if not is_healthy:
            print(f"⚠ Cluster {cluster_id} is unhealthy!")
            # Send notification, pause job submissions, etc.

        await asyncio.sleep(interval)

# Start monitoring in background
asyncio.create_task(monitor_cluster_health(manager, cluster_id=1))
```

## Performance Considerations

### File Transfer

- Use compression for large files
- Transfer only necessary files
- Implement rsync for incremental transfers

```python
# Consider implementing:
# - Selective file upload (only changed files)
# - Compression during transfer
# - Parallel file transfers for multiple jobs
```

### Connection Management

- Pool size: 5-10 connections per cluster
- Connection reuse: Significantly faster than creating new connections
- Health checks: Balance between frequency and overhead

```python
# Tune these parameters based on cluster characteristics
manager = ConnectionManager(
    pool_size=10,  # Max connections per cluster
)

# Adjust in ConnectionManager class:
MAX_CONNECTION_AGE = 3600     # 1 hour
MAX_IDLE_TIME = 300           # 5 minutes
MAX_HEALTH_CHECK_FAILURES = 3
```

### Output Streaming

- Buffer output lines before yielding
- Implement timeout for stalled jobs
- Use `tail -f` with line limits

## Testing

### Unit Tests

```bash
cd tui/
pytest tests/test_ssh_runner.py -v
```

### Integration Tests

Create a test cluster configuration:

```python
# tests/integration/test_ssh_integration.py
import pytest
from src.runners.ssh_runner import SSHRunner
from src.core.connection_manager import ConnectionManager

@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_ssh_submission():
    """Test actual SSH job submission (requires test cluster)."""
    manager = ConnectionManager()
    manager.register_cluster(
        cluster_id=1,
        host="test-cluster.local",
        username="testuser",
        key_file=Path.home() / ".ssh/test_key"
    )

    runner = SSHRunner(manager, cluster_id=1)

    # Run actual job
    job_handle = await runner.submit_job(...)
    # ... verify execution ...
```

Run integration tests:

```bash
pytest tests/integration/ -v --integration
```

## Troubleshooting

### Connection Refused

```
Error: Connection refused to remote-host:22
```

**Solutions:**
- Verify remote host is accessible: `ping remote-host`
- Check SSH service is running: `ssh user@remote-host`
- Verify firewall rules allow SSH (port 22)

### Authentication Failed

```
Error: Permission denied (publickey)
```

**Solutions:**
- Verify SSH key is added: `ssh-add ~/.ssh/id_ed25519`
- Check key permissions: `chmod 600 ~/.ssh/id_ed25519`
- Ensure key is on remote: `ssh-copy-id user@remote-host`

### CRYSTAL Executable Not Found

```
Error: CRYSTAL executable not found: /home/user/CRYSTAL23/bin/*/v*/crystalOMP
```

**Solutions:**
- Verify CRYSTAL is installed on remote machine
- Check `remote_crystal_root` path is correct
- Ensure `cry23.bashrc` exists and sources properly
- Test manually: `ssh user@remote-host "ls /home/user/CRYSTAL23/bin"`

### Job Stuck in Running State

```
Status: running (but actually completed)
```

**Solutions:**
- Check output file manually: `ssh user@remote-host "cat <remote_work_dir>/output.log"`
- Verify PID exists: `ssh user@remote-host "ps -p <pid>"`
- Possible causes: Zombie process, stale PID file

## Future Enhancements

1. **Batch System Integration**
   - SLURM support via sbatch
   - PBS/Torque support
   - Job queue management

2. **Advanced File Transfer**
   - Rsync for incremental transfers
   - Compression during transfer
   - Selective file download

3. **Resource Monitoring**
   - CPU usage tracking
   - Memory usage tracking
   - Disk space monitoring

4. **Job Templates**
   - Pre-configured job scripts
   - Environment modules
   - Custom SBATCH directives

## Related Documentation

- [BaseRunner Interface](./BASE_RUNNER.md)
- [ConnectionManager](./CONNECTION_MANAGER.md)
- [LocalRunner](./LOCAL_RUNNER.md)
- [SLURM Runner](./SLURM_RUNNER.md) (planned)

## References

- [asyncssh Documentation](https://asyncssh.readthedocs.io/)
- [CRYSTAL23 Documentation](https://www.crystal.unito.it/)
- [SSH Best Practices](https://www.ssh.com/academy/ssh/best-practices)
