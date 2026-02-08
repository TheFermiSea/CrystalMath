# Getting Started with CrystalMath

This guide will help you install CrystalMath and run your first calculation in under 5 minutes.

## Prerequisites

- **Python 3.10+** - CrystalMath requires Python 3.10 or later
- **uv** - Fast Python package manager (recommended) or pip

## Installation

CrystalMath uses **uv workspaces** for unified dependency management. The repository contains multiple packages that work together.

### Using uv (recommended)

```bash
# Clone the repository
git clone <repository-url> crystalmath
cd crystalmath

# Install core + TUI packages
uv sync

# Install with all extras (dev tools, AiiDA, Materials Project API)
uv sync --all-extras
```

### Available extras

```bash
uv sync --extra dev        # Development tools (pytest, ruff, black)
uv sync --extra aiida      # AiiDA integration (PostgreSQL workflow engine)
uv sync --extra materials  # Materials Project API integration
```

## Quick Start - Python API

The `CrystalController` class is the primary entry point for Python users.

### Basic Job Submission

```python
from crystalmath.api import CrystalController
from crystalmath.models import JobSubmission, DftCode, RunnerType

# Initialize controller (uses SQLite database)
ctrl = CrystalController(db_path="my_jobs.db")

# Submit a job
job = JobSubmission(
    name="mgo_scf",
    dft_code=DftCode.CRYSTAL,
    input_content=open("mgo.d12").read(),
)
pk = ctrl.submit_job(job)
print(f"Submitted job {pk}")

# Check status
details = ctrl.get_job_details(pk)
print(f"State: {details.state}")
print(f"Runner: {details.runner_type}")

# Get results when complete
if details.state == "finished":
    results = details.results
    print(f"Energy: {results.get('energy')} eV")
```

### Fetching Jobs

```python
# Get all jobs
jobs = ctrl.get_jobs(limit=10)
for job in jobs:
    print(f"{job.pk}: {job.name} - {job.state}")

# Filter by state
running_jobs = ctrl.get_jobs(state="running")
```

## Quick Start - CLI

The CLI tool provides a simple command-line interface for running calculations.

```bash
# From the cli/ directory
cd cli

# Run a calculation (serial mode with auto-threading)
bin/runcrystal mgo

# Run with MPI parallelism (14 ranks)
bin/runcrystal mgo 14

# See what would run without executing
bin/runcrystal --explain mgo
```

## Quick Start - TUI

The Textual-based TUI provides an interactive interface for job management.

```bash
# Launch the TUI
uv run crystal-tui
```

**TUI Features:**
- Visual job browser with status monitoring
- Template-based job creation
- Cluster configuration (SSH/SLURM)
- Workflow orchestration
- Materials Project structure search

## Workflow Classes

CrystalMath provides working workflow classes for common multi-step calculations. See the [Workflow Classes Reference](high-level-api.md) for detailed documentation.

### Convergence Studies

Test parameter convergence (k-points, basis sets, cutoffs):

```python
from crystalmath.workflows.convergence import (
    ConvergenceStudy, ConvergenceStudyConfig, ConvergenceParameter
)

config = ConvergenceStudyConfig(
    parameter=ConvergenceParameter.SHRINK,
    values=[4, 6, 8, 10, 12, 14],
    base_input=open("mgo.d12").read(),
    energy_threshold=0.001,  # eV/atom
    dft_code="crystal",
)

study = ConvergenceStudy(config)
inputs = study.generate_inputs()  # List of (name, input_content) tuples

# Submit each input to controller
for name, content in inputs:
    job = JobSubmission(name=name, input_content=content, dft_code=DftCode.CRYSTAL)
    ctrl.submit_job(job)
```

### Band Structure Calculations

```python
from crystalmath.workflows.bands import (
    BandStructureWorkflow, BandStructureConfig, BandPathPreset
)

config = BandStructureConfig(
    source_job_pk=1,  # PK of converged SCF job
    band_path=BandPathPreset.AUTO,
    kpoints_per_segment=50,
    compute_dos=True,
    dos_mesh=[12, 12, 12],
)

workflow = BandStructureWorkflow(config)
```

### VASP Input Generation

Generate complete VASP input files from structures:

```python
from crystalmath.vasp.generator import VaspInputGenerator, IncarPreset

gen = VaspInputGenerator()
inputs = gen.generate_from_structure(
    structure,  # pymatgen Structure object
    preset=IncarPreset.RELAX,
    kpoints_density=0.04,
)

print(inputs.poscar)
print(inputs.incar)
print(inputs.kpoints)
```

## Templates

CrystalMath includes a template library for common calculations:

```python
from crystalmath.templates import list_templates, get_template_dir

# List available templates
for template in list_templates(category="basic"):
    print(f"{template.category}/{template.name}: {template.description}")

# Get template directory path
templates_dir = get_template_dir()
print(f"Templates location: {templates_dir}")
```

## Cluster Configuration

For remote execution on HPC clusters, configure SSH or SLURM runners via the TUI or programmatically.

### Python API - Cluster Setup

```python
from crystalmath.models import ClusterConfig, ClusterType

# Create cluster configuration
cluster = ClusterConfig(
    name="beefcake2",
    hostname="10.0.0.10",
    username="ubuntu",
    cluster_type=ClusterType.SSH,
    max_concurrent_jobs=4,
)

# Submit to database (via controller)
cluster_id = ctrl.create_cluster(cluster)
```

See [Cluster Setup](cluster-setup.md) for detailed SSH and SLURM configuration.

## Next Steps

- **[Workflow Classes Reference](high-level-api.md)** - Convergence studies, band structure, phonons, EOS
- **[Cluster Setup](cluster-setup.md)** - Configure SSH/SLURM for remote execution
- **[Advanced Workflows](advanced-workflows.md)** - Multi-step workflow orchestration

## Troubleshooting

### Module Not Found

Ensure packages are installed in your active environment:

```bash
uv sync
```

### Database Path Issues

By default, the TUI creates `.crystal_tui.db` in the project root. The Rust TUI shares this database. To specify a custom path:

```python
ctrl = CrystalController(db_path="/path/to/custom.db")
```

Or set the environment variable:

```bash
export CRYSTAL_TUI_DB=/path/to/custom.db
```

### Cluster Connection Failed

Test SSH connectivity manually:

```bash
ssh ubuntu@10.0.0.10
```

Ensure host keys are added to `~/.ssh/known_hosts` before using the TUI.
