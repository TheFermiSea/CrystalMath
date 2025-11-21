# SLURM Runner Documentation

## Overview

The `SLURMRunner` provides batch job submission to HPC clusters using the SLURM workload manager. It handles the complete lifecycle of remote CRYSTAL calculations:

- Dynamic SLURM script generation
- Job submission via `sbatch`
- Non-blocking status monitoring
- Automatic result retrieval
- Job arrays for parameter sweeps
- Dependency management for workflows

## Quick Start

### Basic Usage

```python
from pathlib import Path
from src.core.connection_manager import ConnectionManager
from src.runners import SLURMRunner, SLURMJobConfig

# Setup connection manager
conn_manager = ConnectionManager()
conn_manager.register_cluster(
    cluster_id=1,
    host="login.hpc.edu",
    username="user123",
    key_file=Path("~/.ssh/id_rsa")
)

# Create SLURM runner
runner = SLURMRunner(
    connection_manager=conn_manager,
    cluster_id=1
)

# Submit job
work_dir = Path("calculations/mgo_001")
async for line in runner.run_job(1, work_dir):
    print(line)
```

### Custom SLURM Configuration

```python
from src.runners import SLURMJobConfig

config = SLURMJobConfig(
    job_name="mgo_calculation",
    nodes=2,
    ntasks=28,
    cpus_per_task=2,
    time_limit="12:00:00",
    partition="compute",
    memory="64GB",
    account="myproject",
    email="user@example.com",
    email_type="BEGIN,END,FAIL"
)

async for line in runner.run_job(1, work_dir, config=config):
    print(line)
```

## Features

### 1. Dynamic SLURM Script Generation

The runner automatically generates SLURM submission scripts with proper directives:

```bash
#!/bin/bash
#SBATCH --job-name=mgo_calculation
#SBATCH --nodes=2
#SBATCH --ntasks=28
#SBATCH --cpus-per-task=2
#SBATCH --time=12:00:00
#SBATCH --partition=compute
#SBATCH --mem=64GB
#SBATCH --account=myproject
#SBATCH --output=slurm-%j.out
#SBATCH --error=slurm-%j.err

# Load modules
module load crystal23

# Set OpenMP threads
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

# Change to working directory
cd /scratch/crystal/1_mgo_001

# Run CRYSTAL calculation
srun PcrystalOMP < input.d12 > output.out 2>&1

exit_code=$?
echo "Job finished with exit code: $exit_code"
exit $exit_code
```

### 2. Execution Modes

**Serial/OpenMP Mode** (ntasks=1):
```python
config = SLURMJobConfig(
    job_name="serial_job",
    nodes=1,
    ntasks=1,
    cpus_per_task=16  # 16 OpenMP threads
)
```
Generates: `crystalOMP < input.d12 > output.out`

**Hybrid MPI+OpenMP Mode** (ntasks>1):
```python
config = SLURMJobConfig(
    job_name="hybrid_job",
    nodes=2,
    ntasks=28,  # 28 MPI ranks
    cpus_per_task=2  # 2 OpenMP threads per rank
)
```
Generates: `srun PcrystalOMP < input.d12 > output.out`

### 3. Non-blocking Status Monitoring

The runner polls job status every 30 seconds (configurable) without blocking:

```python
runner = SLURMRunner(
    connection_manager=conn_manager,
    cluster_id=1,
    poll_interval=60  # Check every 60 seconds
)

async for status_update in runner.run_job(1, work_dir):
    # Status: PENDING
    # Status: RUNNING
    # Status: COMPLETED
    print(status_update)
```

Recognized SLURM states:
- `PENDING` - Job waiting in queue
- `RUNNING` - Job is executing
- `COMPLETED` - Job finished successfully
- `FAILED` - Job failed
- `CANCELLED` - Job was cancelled
- `TIMEOUT` - Job exceeded time limit
- `OUT_OF_MEMORY` - Job ran out of memory
- `NODE_FAIL` - Node failure occurred

### 4. Automatic Result Retrieval

When a job completes, the runner automatically downloads:
- `output.out` - Main CRYSTAL output
- `*.f9`, `*.f98` - Wave function files
- `slurm-*.out`, `slurm-*.err` - SLURM logs
- `*.xyz`, `*.cif` - Structure files

```python
# Results automatically appear in work_dir after completion
async for line in runner.run_job(1, work_dir):
    pass

# Files now available locally
assert (work_dir / "output.out").exists()
assert (work_dir / "slurm-12345.out").exists()
```

### 5. Job Arrays

Submit multiple related jobs as a SLURM array:

```python
config = SLURMJobConfig(
    job_name="parameter_sweep",
    array="1-100",  # 100 array tasks
    cpus_per_task=4
)

# Each array task gets $SLURM_ARRAY_TASK_ID environment variable
# Use in input file or script to vary parameters
```

Common array specifications:
- `"1-10"` - Tasks 1 through 10
- `"1,3,5,7,9"` - Specific tasks
- `"1-100:10"` - Tasks 1, 11, 21, ..., 91 (step size 10)
- `"1-10%4"` - Limit to 4 concurrent tasks

### 6. Job Dependencies

Chain jobs together with dependencies:

```python
# Submit first job
config1 = SLURMJobConfig(job_name="geometry_opt")
async for line in runner.run_job(1, work_dir1, config=config1):
    pass
first_job_id = runner.get_slurm_job_id(1)

# Submit second job that depends on first
config2 = SLURMJobConfig(
    job_name="single_point",
    dependencies=[first_job_id]  # Wait for geometry_opt to complete
)
async for line in runner.run_job(2, work_dir2, config=config2):
    pass
```

## Configuration Reference

### SLURMJobConfig Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `job_name` | str | required | Name for the SLURM job |
| `nodes` | int | 1 | Number of compute nodes |
| `ntasks` | int | 1 | Number of MPI tasks |
| `cpus_per_task` | int | 4 | Cores per task (OpenMP threads) |
| `time_limit` | str | "24:00:00" | Maximum runtime (HH:MM:SS) |
| `partition` | str | None | SLURM partition/queue name |
| `memory` | str | None | Memory per node (e.g., "64GB") |
| `account` | str | None | Account to charge |
| `qos` | str | None | Quality of service |
| `email` | str | None | Email for notifications |
| `email_type` | str | None | When to email (e.g., "BEGIN,END,FAIL") |
| `dependencies` | list[str] | [] | Job IDs to wait for |
| `array` | str | None | Array specification (e.g., "1-10") |
| `constraint` | str | None | Node constraints |
| `exclusive` | bool | False | Request exclusive node access |
| `modules` | list[str] | ["crystal23"] | Modules to load |
| `environment_setup` | str | "" | Custom environment commands |

### Common Time Limits

- Short jobs: `"01:00:00"` (1 hour)
- Medium jobs: `"12:00:00"` (12 hours)
- Long jobs: `"48:00:00"` (48 hours)
- Maximum: Depends on cluster policy

### Memory Specifications

- Per node: `"64GB"`, `"128GB"`, `"256GB"`
- Per core: `"4GB"`, `"8GB"` (use with `--mem-per-cpu`)

## Error Handling

### SLURMSubmissionError

Raised when job submission fails:

```python
try:
    async for line in runner.run_job(1, work_dir):
        print(line)
except SLURMSubmissionError as e:
    print(f"Submission failed: {e}")
    # Check cluster configuration
    # Verify input files exist
    # Check partition/account settings
```

Common causes:
- Invalid partition name
- Missing account specification
- Input file not found
- SSH connection failure

### SLURMStatusError

Raised when status monitoring fails:

```python
try:
    async for line in runner.run_job(1, work_dir):
        print(line)
except SLURMStatusError as e:
    print(f"Status check failed: {e}")
    # Connection may have been lost
    # SLURM commands may not be available
```

### Job State Handling

```python
async for line in runner.run_job(1, work_dir):
    pass

final_state = runner.get_job_state(1)

if final_state == SLURMJobState.COMPLETED:
    print("Success!")
elif final_state == SLURMJobState.FAILED:
    print("Job failed - check output files")
elif final_state == SLURMJobState.TIMEOUT:
    print("Job timed out - increase time_limit")
elif final_state == SLURMJobState.OUT_OF_MEMORY:
    print("Out of memory - increase memory allocation")
```

## Job Control

### Cancelling Jobs

```python
# Cancel a running job
success = await runner.stop_job(job_id)

if success:
    print("Job cancelled")
else:
    print("Job not found or already completed")
```

### Checking Job Status

```python
# Check if job is still active
if runner.is_job_running(job_id):
    print("Job is pending or running")

# Get SLURM job ID
slurm_id = runner.get_slurm_job_id(job_id)
print(f"SLURM Job ID: {slurm_id}")

# Get current state
state = runner.get_job_state(job_id)
print(f"State: {state.value}")
```

## Integration with TUI

### Job Submission Screen

```python
from src.runners import SLURMRunner, SLURMJobConfig

class JobSubmissionScreen:
    async def submit_to_slurm(self, job_id: int):
        """Submit job to SLURM cluster."""
        # Get job details from database
        job = self.db.get_job(job_id)

        # Create configuration from user input
        config = SLURMJobConfig(
            job_name=job.name,
            nodes=self.nodes_input.value,
            cpus_per_task=self.cores_input.value,
            time_limit=self.time_input.value,
            partition=self.partition_select.value
        )

        # Submit job
        output_widget = self.query_one("#output", RichLog)
        async for line in self.runner.run_job(job_id, job.work_dir, config=config):
            output_widget.write(line)
```

### Job Monitoring

```python
class JobMonitorWidget:
    async def update_slurm_jobs(self):
        """Update status of running SLURM jobs."""
        for job_id in self.active_jobs:
            if self.runner.is_job_running(job_id):
                state = self.runner.get_job_state(job_id)
                self.update_job_status(job_id, state.value)
            else:
                # Job completed, update UI
                self.mark_job_complete(job_id)
```

## Advanced Usage

### Custom Modules

```python
config = SLURMJobConfig(
    job_name="custom_env",
    modules=[
        "intel/2023.1",
        "openmpi/4.1.5",
        "crystal/23.1.0"
    ]
)
```

### Custom Environment Setup

```python
config = SLURMJobConfig(
    job_name="with_setup",
    environment_setup="""
    source /opt/crystal/env.sh
    export CRYSTAL_TMPDIR=$SLURM_TMPDIR
    export OMP_STACKSIZE=256M
    ulimit -s unlimited
    """
)
```

### Node Constraints

```python
# Request specific CPU architecture
config = SLURMJobConfig(
    job_name="haswell_job",
    constraint="haswell"
)

# Request multiple constraints
config = SLURMJobConfig(
    job_name="gpu_job",
    constraint="[haswell|broadwell]&gpu"
)
```

### Exclusive Node Access

```python
# Request entire node
config = SLURMJobConfig(
    job_name="exclusive",
    exclusive=True,
    cpus_per_task=64  # Use all cores on node
)
```

## Performance Considerations

### Connection Pooling

The ConnectionManager reuses SSH connections:

```python
# Connections are automatically pooled
for job_id in range(1, 11):
    async for line in runner.run_job(job_id, work_dirs[job_id]):
        pass
# All jobs share same SSH connection
```

### Polling Interval

Adjust polling frequency based on job length:

```python
# Short jobs (< 1 hour) - poll frequently
runner = SLURMRunner(
    connection_manager=conn_manager,
    cluster_id=1,
    poll_interval=10  # Check every 10 seconds
)

# Long jobs (> 24 hours) - poll less frequently
runner = SLURMRunner(
    connection_manager=conn_manager,
    cluster_id=1,
    poll_interval=300  # Check every 5 minutes
)
```

### File Transfer Optimization

For large input files, consider:

1. Pre-staging files to cluster
2. Using persistent scratch space
3. Compressing large basis set files

## Troubleshooting

### Job Stays in PENDING

```
Status: PENDING (Resources)
Status: PENDING (Priority)
```

**Solutions:**
- Check available resources with `squeue -u $USER`
- Reduce resource requests (nodes, cores, memory)
- Use different partition
- Check account limits

### Job Fails Immediately

```
Status: FAILED
```

**Check:**
1. SLURM error file: `slurm-<jobid>.err`
2. Module availability: `module avail crystal`
3. Input file validity
4. Disk space in scratch directory

### Connection Timeouts

```
SSHConnectionError: Connection timeout
```

**Solutions:**
- Verify cluster is accessible
- Check SSH key permissions (chmod 600)
- Test connection: `ssh user@host`
- Check firewall/VPN settings

### Out of Memory

```
Status: OUT_OF_MEMORY
```

**Solutions:**
```python
config = SLURMJobConfig(
    job_name="large_job",
    memory="128GB",  # Increase memory
    cpus_per_task=32  # Use more cores
)
```

## Testing

Run the test suite:

```bash
# All SLURM runner tests
pytest tests/test_slurm_runner.py -v

# Specific test class
pytest tests/test_slurm_runner.py::TestSLURMScriptGeneration -v

# With coverage
pytest tests/test_slurm_runner.py --cov=src/runners/slurm_runner
```

## See Also

- [BaseRunner Documentation](BASE_RUNNER.md) - Runner interface
- [ConnectionManager Documentation](CONNECTION_MANAGER.md) - SSH connection pooling
- [Phase 2 Design](PHASE2_DESIGN.md) - Remote execution architecture
- [SLURM Documentation](https://slurm.schedmd.com/documentation.html) - Official SLURM docs
