# Job Execution Backends

This package provides job execution backends for running CRYSTAL calculations in different environments.

## Available Runners

### LocalRunner

Execute CRYSTAL jobs on the local machine with real-time output streaming.

```python
from src.runners import LocalRunner

runner = LocalRunner()
async for line in runner.run_job(job_id, work_dir):
    print(line)  # Real-time output

result = runner.get_last_result()
print(f"Energy: {result.final_energy} Ha")
```

**Features:**
- Non-blocking async execution
- Real-time stdout/stderr streaming
- CRYSTALpytools integration
- Fallback parsing
- Process management
- OpenMP configuration

**Documentation:** See [docs/LOCAL_RUNNER.md](../../docs/LOCAL_RUNNER.md)

## Quick Start

```python
from pathlib import Path
from src.runners import run_crystal_job

# Simple one-liner
result = await run_crystal_job(Path("calculations/job_001"))
```

## Roadmap

### Phase 1 (Current) ✅
- [x] Local execution (LocalRunner)
- [x] Real-time streaming
- [x] CRYSTALpytools integration
- [x] Comprehensive testing

### Phase 2 (Next)
- [ ] Remote execution (SSHRunner)
- [ ] SLURM integration (SlurmRunner)
- [ ] File transfer optimization
- [ ] Queue management

### Phase 3 (Future)
- [ ] Cloud execution (CloudRunner)
- [ ] Container support (DockerRunner)
- [ ] Distributed execution
- [ ] Load balancing

## Architecture

```
runners/
├── __init__.py          # Public API
├── local.py             # Local execution ✅
├── ssh.py               # Remote via SSH (planned)
├── slurm.py             # HPC clusters (planned)
└── base.py              # Abstract base class (future)
```

## Testing

```bash
# Test local runner
pytest tests/test_local_runner.py -v

# Test with real CRYSTAL
export CRY23_EXEDIR=/path/to/crystal/bin
pytest tests/test_local_runner.py::TestRealIntegration -v
```

## Contributing

When adding a new runner:

1. Inherit from base runner class (when implemented)
2. Implement required methods:
   - `run_job(job_id, work_dir)` - Execute job
   - `stop_job(job_id)` - Stop running job
   - `is_job_running(job_id)` - Check status
3. Return `JobResult` with structured data
4. Add comprehensive tests
5. Update documentation

## See Also

- [LOCAL_RUNNER.md](../../docs/LOCAL_RUNNER.md) - Complete LocalRunner documentation
- [IMPLEMENTATION_SUMMARY.md](../../docs/IMPLEMENTATION_SUMMARY.md) - Implementation details
- [QUICK_START_RUNNER.md](../../docs/QUICK_START_RUNNER.md) - Quick start guide
- [run_simple_job.py](../../examples/run_simple_job.py) - Working example
