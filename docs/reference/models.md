# Data Models Reference

All data models are defined in `crystalmath.models` using Pydantic for validation and serialization.

## Import

```python
from crystalmath.models import (
    JobState,
    DftCode,
    RunnerType,
    JobSubmission,
    JobStatus,
    JobDetails,
    ClusterConfig,
    SchedulerOptions,
    StructureData,
)
```

## Enumerations

### JobState

Job execution state enum.

**Values:**
- `CREATED` - Job created but not yet submitted
- `SUBMITTED` - Job submitted to execution backend
- `QUEUED` - Job waiting in queue (SLURM/SSH)
- `RUNNING` - Job actively executing
- `COMPLETED` - Job finished successfully
- `FAILED` - Job terminated with error
- `CANCELLED` - Job cancelled by user

**Example:**
```python
from crystalmath.models import JobState

if job.state == JobState.COMPLETED:
    print("Job finished successfully")
elif job.state == JobState.FAILED:
    print("Job failed - check logs")
```

### DftCode

Supported DFT calculation codes.

**Values:**
- `CRYSTAL` - CRYSTAL23 quantum chemistry code
- `VASP` - Vienna Ab initio Simulation Package
- `QUANTUM_ESPRESSO` - Quantum Espresso plane-wave DFT

**Example:**
```python
from crystalmath.models import DftCode

submission = JobSubmission(
    name="mgo_vasp",
    dft_code=DftCode.VASP,
    ...
)
```

### RunnerType

Job execution backend types.

**Values:**
- `LOCAL` - Local subprocess execution
- `SSH` - Remote execution via SSH
- `SLURM` - HPC batch scheduler
- `AIIDA` - AiiDA workflow engine

**Example:**
```python
from crystalmath.models import RunnerType

submission = JobSubmission(
    name="mgo_hpc",
    runner_type=RunnerType.SLURM,
    cluster_id=1,
    ...
)
```

## Job Submission

### JobSubmission

Data required to submit a new calculation job.

**Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | *required* | Job display name (3-100 chars, filesystem-safe) |
| `dft_code` | `DftCode` | `CRYSTAL` | DFT code to use |
| `workflow_id` | `Optional[str]` | `None` | Parent workflow ID (for workflow-linked jobs) |
| `cluster_id` | `Optional[int]` | `None` | Target cluster ID (None for local) |
| `runner_type` | `RunnerType` | `LOCAL` | Execution backend |
| `parameters` | `Dict[str, Any]` | `{}` | DFT input parameters |
| `structure_path` | `Optional[str]` | `None` | Path to structure file (.cif, .xyz) |
| `input_content` | `Optional[str]` | `None` | Raw input file content (.d12, INCAR) |
| `auxiliary_files` | `Optional[Dict[str, str]]` | `None` | Auxiliary files map (type -> source_path) |
| `scheduler_options` | `Optional[SchedulerOptions]` | `None` | SLURM resource settings |
| `mpi_ranks` | `Optional[int]` | `None` | Number of MPI ranks |
| `parallel_mode` | `Optional[str]` | `None` | Parallel mode ('serial' or 'parallel') |

**Validation:**
- Name must be 3-100 characters and filesystem-safe (no `/\:*?"<>|`)
- Either `parameters` or `input_content` must be provided
- MPI ranks must be positive if specified

**Example:**
```python
from crystalmath.models import JobSubmission, DftCode, RunnerType

# Simple local job
submission = JobSubmission(
    name="mgo_scf",
    dft_code=DftCode.CRYSTAL,
    input_content=Path("mgo.d12").read_text(),
)

# HPC job with SLURM
from crystalmath.models import SchedulerOptions

submission = JobSubmission(
    name="mgo_hpc",
    dft_code=DftCode.CRYSTAL,
    runner_type=RunnerType.SLURM,
    cluster_id=1,
    input_content=input_text,
    mpi_ranks=16,
    scheduler_options=SchedulerOptions(
        walltime="48:00:00",
        memory_gb="64",
        cpus_per_task=16,
        nodes=1,
        partition="compute",
    ),
)
```

### SchedulerOptions

SLURM scheduler resource configuration.

**Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `walltime` | `str` | `"24:00:00"` | Walltime limit (HH:MM:SS format) |
| `memory_gb` | `str` | `"32"` | Memory per node in GB |
| `cpus_per_task` | `int` | `4` | CPUs per task (must be > 0) |
| `nodes` | `int` | `1` | Number of nodes (must be > 0) |
| `partition` | `Optional[str]` | `None` | SLURM partition/queue name |

**Example:**
```python
from crystalmath.models import SchedulerOptions

opts = SchedulerOptions(
    walltime="72:00:00",
    memory_gb="128",
    cpus_per_task=32,
    nodes=2,
    partition="bigmem",
)
```

## Job Status

### JobStatus

Lightweight job status for list views. Optimized for frequent polling.

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `pk` | `int` | Primary key (database ID) |
| `uuid` | `str` | Unique identifier |
| `name` | `str` | Job display name |
| `state` | `JobState` | Current execution state |
| `dft_code` | `DftCode` | DFT code type |
| `runner_type` | `RunnerType` | Execution backend |
| `workflow_id` | `Optional[str]` | Parent workflow identifier |
| `progress_percent` | `float` | Completion progress (0-100) |
| `wall_time_seconds` | `Optional[float]` | Elapsed wall time |
| `created_at` | `Optional[datetime]` | Job creation timestamp |

**Example:**
```python
from crystalmath.api import CrystalController

ctrl = CrystalController(db_path="jobs.db")
jobs = ctrl.get_jobs(limit=10)

for job in jobs:
    print(f"{job.pk:4d} {job.name:20s} {job.state.value:12s} {job.progress_percent:5.1f}%")
```

### JobDetails

Full job details including computed results and logs.

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `pk` | `int` | Primary key (database ID) |
| `uuid` | `Optional[str]` | Unique identifier |
| `name` | `str` | Job display name |
| `state` | `JobState` | Current execution state |
| `dft_code` | `DftCode` | DFT code type |
| `final_energy` | `Optional[float]` | Final total energy (Hartree) |
| `bandgap_ev` | `Optional[float]` | Band gap (eV, must be >= 0) |
| `convergence_met` | `bool` | SCF convergence achieved |
| `scf_cycles` | `Optional[int]` | Number of SCF cycles |
| `cpu_time_seconds` | `Optional[float]` | CPU time |
| `wall_time_seconds` | `Optional[float]` | Wall clock time |
| `warnings` | `List[str]` | Warning messages |
| `errors` | `List[str]` | Error messages |
| `stdout_tail` | `List[str]` | Last N lines of stdout |
| `key_results` | `Optional[Dict[str, Any]]` | Full results dictionary |
| `work_dir` | `Optional[str]` | Working directory path |
| `input_file` | `Optional[str]` | Input file content |

**Example:**
```python
details = ctrl.get_job_details(pk=42)

if details:
    print(f"Job: {details.name}")
    print(f"State: {details.state.value}")

    if details.final_energy:
        print(f"Energy: {details.final_energy:.6f} Ha")

    if details.bandgap_ev is not None:
        print(f"Bandgap: {details.bandgap_ev:.3f} eV")

    print(f"Converged: {details.convergence_met}")
    print(f"SCF cycles: {details.scf_cycles}")

    if details.errors:
        print("\nErrors:")
        for err in details.errors:
            print(f"  - {err}")
```

## Cluster Configuration

### ClusterConfig

Remote cluster configuration for SSH and SLURM execution.

**Fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `Optional[int]` | `None` | Database ID |
| `name` | `str` | *required* | Cluster display name (1-50 chars) |
| `cluster_type` | `Literal["ssh", "slurm"]` | *required* | Cluster type |
| `hostname` | `str` | *required* | Hostname or IP address |
| `port` | `int` | `22` | SSH port (1-65535) |
| `username` | `str` | *required* | SSH username |
| `key_file` | `Optional[str]` | `None` | Path to SSH private key |
| `remote_workdir` | `Optional[str]` | `None` | Remote working directory |
| `queue_name` | `Optional[str]` | `None` | SLURM queue/partition name |
| `max_concurrent` | `int` | `4` | Max concurrent jobs (>= 1) |
| `cry23_root` | `Optional[str]` | `None` | Path to CRYSTAL23 installation |
| `vasp_root` | `Optional[str]` | `None` | Path to VASP installation |
| `setup_commands` | `List[str]` | `[]` | Setup commands (e.g., module load) |
| `status` | `Literal["active", "inactive", "error"]` | `"active"` | Cluster status |

**Hostname Validation:** Must match pattern `[a-zA-Z0-9]([a-zA-Z0-9\-\.]*[a-zA-Z0-9])?`

**Example:**
```python
from crystalmath.models import ClusterConfig

cluster = ClusterConfig(
    name="beefcake2",
    cluster_type="slurm",
    hostname="beefcake2.university.edu",
    port=22,
    username="user",
    key_file="~/.ssh/id_rsa",
    remote_workdir="/scratch/user/crystalmath",
    queue_name="compute",
    max_concurrent=8,
    cry23_root="/opt/crystal23",
    setup_commands=[
        "module load intel/2023",
        "module load openmpi/4.1",
    ],
)
```

## Structure Data

### StructureData

Crystal structure data for input generation.

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `formula` | `str` | Chemical formula |
| `lattice_a` | `float` | Lattice parameter a (Angstrom, > 0) |
| `lattice_b` | `float` | Lattice parameter b (Angstrom, > 0) |
| `lattice_c` | `float` | Lattice parameter c (Angstrom, > 0) |
| `alpha` | `float` | Angle alpha (degrees, 0-180, default: 90) |
| `beta` | `float` | Angle beta (degrees, 0-180, default: 90) |
| `gamma` | `float` | Angle gamma (degrees, 0-180, default: 90) |
| `space_group` | `Optional[int]` | Space group number (1-230) |
| `layer_group` | `Optional[int]` | Layer group for SLAB (1-80) |
| `atoms` | `List[Dict[str, Any]]` | Atomic positions |
| `source` | `Optional[str]` | Data source (mp, cif, manual) |
| `material_id` | `Optional[str]` | Materials Project ID |

**Example:**
```python
from crystalmath.models import StructureData

structure = StructureData(
    formula="MgO",
    lattice_a=4.211,
    lattice_b=4.211,
    lattice_c=4.211,
    alpha=90.0,
    beta=90.0,
    gamma=90.0,
    space_group=225,  # Fm-3m
    atoms=[
        {"element": "Mg", "x": 0.0, "y": 0.0, "z": 0.0},
        {"element": "O", "x": 0.5, "y": 0.5, "z": 0.5},
    ],
    source="mp",
    material_id="mp-1265",
)
```

## See Also

- [API Reference](api.md) - CrystalController methods
- [CLI Reference](cli.md) - Command-line interface
- [Template System](templates.md) - Input templates
