# BaseRunner Interface Documentation

## Overview

The `BaseRunner` abstract base class defines a unified interface for all CRYSTAL job execution backends (local, SSH, SLURM). This interface ensures consistent behavior across different execution environments and enables easy addition of new runner types.

## Key Components

### 1. BaseRunner Abstract Class

Located in `src/runners/base.py`, this class defines the core interface that all runners must implement.

**Required Abstract Methods:**

- `async def submit_job(...)` - Submit a job for execution
- `async def get_status(job_handle)` - Query job status
- `async def cancel_job(job_handle)` - Cancel a running job
- `async def get_output(job_handle)` - Stream job output in real-time
- `async def retrieve_results(job_handle, dest)` - Retrieve output files

**Optional Methods:**

- `async def get_job_info(job_handle)` - Get comprehensive job information
- `async def wait_for_completion(job_handle)` - Wait for job to finish
- `async def connect()` - Establish connection to execution environment
- `async def cleanup()` - Clean up resources and connections
- `def acquire_slot()` - Acquire execution slot (enforces max_concurrent_jobs)
- `def is_connected()` - Check if runner is ready

### 2. JobStatus Enum

Standard status values across all runners:

- `PENDING` - Job created but not submitted
- `QUEUED` - Waiting in queue
- `RUNNING` - Actively executing
- `COMPLETED` - Finished successfully
- `FAILED` - Finished with errors
- `CANCELLED` - Terminated by user
- `UNKNOWN` - Status cannot be determined

### 3. RunnerConfig Dataclass

Configuration options for runners:

```python
@dataclass
class RunnerConfig:
    name: str = "default"
    scratch_dir: Path = Path.home() / "tmp_crystal"
    executable_path: Optional[Path] = None
    default_threads: int = 4
    max_concurrent_jobs: int = 1
    timeout_seconds: float = 0.0
    cleanup_on_success: bool = False
    cleanup_on_failure: bool = False
    output_buffer_lines: int = 100
    extra_config: Dict[str, Any] = field(default_factory=dict)
```

### 4. JobHandle Type

Type alias for runner-specific job identifiers:

```python
JobHandle = NewType("JobHandle", str)
```

Format examples:
- Local: `"local_123"`
- SSH: `"ssh_hostname_456"`
- SLURM: `"slurm_789012"`

### 5. JobInfo Dataclass

Complete snapshot of job state:

```python
@dataclass
class JobInfo:
    job_handle: JobHandle
    status: JobStatus
    work_dir: Path
    scratch_dir: Optional[Path] = None
    pid: Optional[int] = None
    submit_time: Optional[float] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    exit_code: Optional[int] = None
    resource_usage: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### 6. Exception Hierarchy

All exceptions inherit from `RunnerError`:

- `ConnectionError` - Connection failures
- `ExecutionError` - Job execution failures
- `TimeoutError` - Operation timeouts
- `ConfigurationError` - Invalid configuration
- `ResourceError` - Resource unavailability
- `CancellationError` - Cancellation failures

## Usage Example

### Implementing a New Runner

```python
from src.runners.base import BaseRunner, JobHandle, JobStatus
from src.runners.exceptions import ConnectionError, ExecutionError

class CustomRunner(BaseRunner):
    async def submit_job(self, job_id, input_file, work_dir, threads=None, **kwargs):
        # Submit job to custom backend
        handle = JobHandle(f"custom_{job_id}")
        # ... implementation ...
        return handle

    async def get_status(self, job_handle):
        # Query backend for status
        return JobStatus.RUNNING

    async def cancel_job(self, job_handle):
        # Cancel job on backend
        return True

    async def get_output(self, job_handle):
        # Stream output from backend
        yield "Output line 1"
        yield "Output line 2"

    async def retrieve_results(self, job_handle, dest, cleanup=None):
        # Copy results from backend
        pass
```

### Using a Runner

```python
from src.runners import LocalRunner, RunnerConfig

# Configure runner
config = RunnerConfig(
    name="my_runner",
    scratch_dir=Path("/scratch"),
    default_threads=8,
    max_concurrent_jobs=4,
)

# Use runner as async context manager
async with LocalRunner(config=config) as runner:
    # Submit job
    handle = await runner.submit_job(
        job_id=1,
        input_file=Path("input.d12"),
        work_dir=Path("work_dir"),
        threads=8
    )

    # Monitor status
    while True:
        status = await runner.get_status(handle)
        if status in (JobStatus.COMPLETED, JobStatus.FAILED):
            break
        await asyncio.sleep(1)

    # Get results
    await runner.retrieve_results(handle, Path("results"))
```

## LocalRunner Implementation

The `LocalRunner` class (in `src/runners/local.py`) implements the `BaseRunner` interface for local execution:

**Key Features:**
- Inherits from `BaseRunner`
- Implements all required abstract methods
- Maintains backward compatibility with existing `run_job()` method
- Maps job IDs to `JobHandle` internally
- Provides both streaming and completion-based APIs

**Integration:**
```python
# Old API (still works)
async for line in runner.run_job(job_id, work_dir, threads):
    print(line)

# New BaseRunner API
handle = await runner.submit_job(job_id, input_file, work_dir, threads)
status = await runner.get_status(handle)
```

## Testing

Comprehensive unit tests in `tests/test_base_runner.py` cover:

- ✅ RunnerConfig validation and defaults
- ✅ JobStatus enum values
- ✅ JobInfo dataclass
- ✅ Exception hierarchy
- ✅ BaseRunner interface methods
- ✅ Job lifecycle (submit → status → cancel → results)
- ✅ Async context manager support
- ✅ Concurrency control (max_concurrent_jobs)
- ✅ Timeout handling

**Test Results:** 22/22 tests passing

## Design Principles

1. **Async/Await Throughout** - All I/O operations are asynchronous for non-blocking execution
2. **Generator-Based Output** - Real-time streaming via async generators
3. **Type Safety** - Comprehensive type hints with NewType and dataclasses
4. **Extensibility** - Easy to add new runner types
5. **Resource Management** - Automatic cleanup via context managers
6. **Concurrency Control** - Built-in semaphore for job slot management

## Future Runners

The interface is designed to support:

- **SSHRunner** - Remote execution via SSH (partially implemented in `ssh_runner.py`)
- **SLURMRunner** - HPC batch scheduling (partially implemented in `slurm_runner.py`)
- **PBSRunner** - PBS/Torque batch scheduling
- **KubernetesRunner** - Container orchestration
- **CloudRunner** - Cloud-based execution (AWS, Azure, GCP)

## Migration Guide

For existing code using the old interface:

**Before:**
```python
runner = LocalRunner()
async for line in runner.run_job(job_id, work_dir, threads):
    print(line)
```

**After (BaseRunner API):**
```python
runner = LocalRunner()
handle = await runner.submit_job(job_id, input_file, work_dir, threads)
async for line in runner.get_output(handle):
    print(line)
await runner.wait_for_completion(handle)
```

Both APIs are supported in `LocalRunner` for backward compatibility.

## Summary

The `BaseRunner` interface provides:

1. ✅ Abstract base class with well-defined interface
2. ✅ Standard job status enum
3. ✅ Configuration dataclass with validation
4. ✅ Type-safe job handles
5. ✅ Comprehensive exception hierarchy
6. ✅ LocalRunner implementation
7. ✅ Complete unit test coverage (22 tests)
8. ✅ Documentation and examples

The interface is ready for production use and future extensions (SSH, SLURM, PBS runners).
