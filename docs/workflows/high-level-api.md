# Workflow Classes Reference

This document covers CrystalMath's workflow classes for automated multi-step calculations. These classes are production-ready and provide JSON-serializable interfaces.

## Overview

CrystalMath provides four working workflow classes:

| Workflow | Purpose | Key Features |
|----------|---------|-------------|
| `ConvergenceStudy` | Parameter convergence testing | k-points, basis sets, cutoffs |
| `BandStructureWorkflow` | Electronic structure | Band structure + DOS calculation |
| `PhononWorkflow` | Phonon properties | Phonopy integration, thermal properties |
| `EOSWorkflow` | Equation of state | Bulk modulus determination |

All workflow classes:
- Generate input files for job submission
- Track calculation status
- Analyze results when complete
- Return JSON-serializable result objects

## ConvergenceStudy

Test convergence of total energy with respect to computational parameters.

### Configuration

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
    cluster_id=None,  # Local execution
    name_prefix="conv",
)
```

### ConvergenceParameter Enum

| Parameter | Description | Applicable Codes |
|-----------|-------------|------------------|
| `KPOINTS` | K-point mesh density | VASP, QE |
| `SHRINK` | CRYSTAL SHRINK parameter | CRYSTAL |
| `BASIS` | Basis set quality | CRYSTAL |
| `ENCUT` | Plane-wave cutoff | VASP |
| `ECUTWFC` | Wavefunction cutoff | QE |

### Usage Example

```python
study = ConvergenceStudy(config)

# Generate input files
inputs = study.generate_inputs()  # List of (name, input_content) tuples

# Submit jobs (using CrystalController)
from crystalmath.api import CrystalController
from crystalmath.models import JobSubmission, DftCode

ctrl = CrystalController(db_path="convergence.db")
pks = []

for name, content in inputs:
    job = JobSubmission(
        name=name,
        input_content=content,
        dft_code=DftCode.CRYSTAL,
    )
    pks.append(ctrl.submit_job(job))

print(f"Submitted {len(pks)} convergence jobs")

# ... wait for jobs to complete ...

# Collect energies from completed jobs
energies = []
for pk in pks:
    details = ctrl.get_job_details(pk)
    if details.state == "finished":
        energies.append(details.results.get("energy"))

# Analyze convergence
result = study.analyze_results(energies)
print(f"Converged at {result.parameter.value}={result.converged_value}")
print(f"Recommendation: {result.recommendation}")
```

### ConvergenceStudyResult

```python
@dataclass
class ConvergenceStudyResult:
    parameter: ConvergenceParameter
    points: list[ConvergencePoint]
    converged_value: int | float | str | None
    converged_at_index: int | None
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
```

Each `ConvergencePoint` contains:
- `parameter_value`: The tested parameter value
- `energy`: Total energy (eV or Hartree)
- `energy_per_atom`: Energy per atom
- `wall_time_seconds`: Calculation time
- `job_pk`: Job primary key
- `status`: "pending", "running", "completed", "failed"

## BandStructureWorkflow

Calculate electronic band structure and density of states from a converged SCF wavefunction.

### Configuration

```python
from crystalmath.workflows.bands import (
    BandStructureWorkflow, BandStructureConfig, BandPathPreset
)

config = BandStructureConfig(
    source_job_pk=1,  # PK of converged SCF job
    band_path=BandPathPreset.AUTO,  # Auto-detect from structure
    custom_path=None,  # Or specify: "Gamma X M Gamma"
    kpoints_per_segment=50,
    compute_dos=True,
    dos_mesh=[12, 12, 12],
    first_band=1,
    last_band=-1,  # All bands
    dft_code="crystal",
    cluster_id=None,
    name_prefix="bands",
)
```

### BandPathPreset Enum

| Preset | Description | Path |
|--------|-------------|------|
| `AUTO` | Auto-detect from structure symmetry | Varies |
| `CUBIC` | Simple cubic lattice | Gamma-X-M-Gamma-R-X |
| `FCC` | Face-centered cubic | Gamma-X-W-K-Gamma-L-U-W-L-K |
| `BCC` | Body-centered cubic | Gamma-H-N-Gamma-P-H |
| `HEXAGONAL` | Hexagonal lattice | Gamma-M-K-Gamma-A-L-H-A |
| `TETRAGONAL` | Tetragonal lattice | Gamma-X-M-Gamma-Z-R-A-Z |
| `CUSTOM` | User-specified path | Set via `custom_path` |

### Usage Example

```python
workflow = BandStructureWorkflow(config)

# Generate band structure input
band_input = workflow.generate_band_input()
print(f"Band structure job: {band_input}")

# Generate DOS input (if compute_dos=True)
if config.compute_dos:
    dos_input = workflow.generate_dos_input()
    print(f"DOS job: {dos_input}")

# After jobs complete, analyze results
result = workflow.analyze_results(band_data, dos_data)
print(f"Band gap: {result.band_gap_ev:.3f} eV")
print(f"Gap type: {result.band_gap_type}")  # "direct" or "indirect"
print(f"Metal: {result.is_metal}")
```

### BandStructureResult

```python
@dataclass
class BandStructureResult:
    status: str  # "pending", "running", "completed", "failed"
    band_job_pk: int | None
    dos_job_pk: int | None
    fermi_energy_ev: float | None
    band_gap_ev: float | None
    band_gap_type: str | None  # "direct" or "indirect"
    is_metal: bool | None
    vbm_ev: float | None  # Valence band maximum
    cbm_ev: float | None  # Conduction band minimum
    n_bands: int | None
    kpath_labels: list[str]
    error_message: str | None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
```

## PhononWorkflow

Calculate phonon dispersion and thermodynamic properties using finite displacements.

### Configuration

```python
from crystalmath.workflows.phonon import (
    PhononWorkflow, PhononConfig, PhononMethod, PhononDFTCode
)

config = PhononConfig(
    source_job_pk=1,  # PK of optimized structure
    method=PhononMethod.PHONOPY,  # phonopy, crystal_fd, crystal_dfpt
    supercell_dim=[2, 2, 2],
    displacement_distance=0.01,  # Angstrom
    use_symmetry=True,
    mesh=[20, 20, 20],  # Q-point mesh for DOS
    band_path="AUTO",  # Or explicit path
    compute_thermal=True,
    tmin=0.0,
    tmax=1000.0,
    tstep=10.0,
    dft_code=PhononDFTCode.CRYSTAL,
    cluster_id=None,
    name_prefix="phonon",
)
```

### PhononMethod Enum

| Method | Description | Requirements |
|--------|-------------|--------------|
| `PHONOPY` | Phonopy with finite displacements | phonopy package |
| `CRYSTAL_FD` | CRYSTAL finite displacement | CRYSTAL23 |
| `CRYSTAL_DFPT` | CRYSTAL DFPT (linear response) | CRYSTAL23 |

### Usage Example

```python
workflow = PhononWorkflow(config)

# Generate supercell and displacements
displacements = workflow.generate_displacements()
print(f"Need {len(displacements)} displacement calculations")

# Submit force calculations for each displacement
for disp in displacements:
    job = JobSubmission(
        name=f"phonon_disp_{disp.index}",
        input_content=disp.input_content,
        dft_code=DftCode.CRYSTAL,
    )
    disp.job_pk = ctrl.submit_job(job)

# After all force calculations complete
result = workflow.collect_forces_and_analyze()

if result.has_imaginary:
    print("WARNING: Structure is dynamically unstable!")
    print(f"Minimum frequency: {result.min_frequency:.2f} cm^-1")
else:
    print("Structure is dynamically stable")
    print(f"Frequencies at Gamma: {result.frequencies_at_gamma}")

# Thermal properties
if result.thermal_properties:
    T = result.thermal_properties["temperatures"]
    F = result.thermal_properties["free_energy"]
    print(f"Free energy at 300 K: {F[30]:.3f} eV")
```

### PhononResult

```python
@dataclass
class PhononResult:
    status: str
    n_displacements: int
    displacements: list[DisplacementPoint]
    force_sets_ready: bool
    frequencies_at_gamma: list[float]  # cm^-1
    has_imaginary: bool
    min_frequency: float | None
    band_yaml: str | None  # Path to phonopy band.yaml
    thermal_properties: dict[str, Any] | None
    zero_point_energy_ev: float | None
    error_message: str | None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""

    @property
    def completed_count(self) -> int:
        """Number of completed displacement calculations."""

    @property
    def failed_count(self) -> int:
        """Number of failed displacement calculations."""
```

## EOSWorkflow

Fit equation of state (Birch-Murnaghan) to determine bulk modulus and equilibrium volume.

### Configuration

```python
from crystalmath.workflows.eos import EOSWorkflow, EOSConfig

config = EOSConfig(
    source_job_pk=1,  # PK of optimized structure
    volume_range=(0.90, 1.10),  # +/- 10% volume
    num_points=7,
    eos_type="birch_murnaghan",  # birch_murnaghan, murnaghan, vinet
    dft_code="crystal",
    cluster_id=None,
    name_prefix="eos",
)
```

### Usage Example

```python
workflow = EOSWorkflow(config)

# Get reference structure from source job
source_job = ctrl.get_job_details(config.source_job_pk)
# Extract cell, positions, symbols from source_job.results

# Generate volume-scaled structures
structures = workflow.generate_volume_points(
    cell=[[a, 0, 0], [0, b, 0], [0, 0, c]],
    positions=[[0, 0, 0], [0.5, 0.5, 0.5]],
    symbols=["Mg", "O"],
)

print(f"Generated {len(structures)} volume points")

# Submit SCF calculations for each volume
for i, struct in enumerate(structures):
    job = JobSubmission(
        name=f"eos_vol_{i}",
        input_content=struct["input_content"],
        dft_code=DftCode.CRYSTAL,
    )
    workflow.result.points[i].job_pk = ctrl.submit_job(job)

# After all calculations complete, fit EOS
result = workflow.fit_eos()
print(f"Equilibrium volume: {result.v0:.2f} A^3")
print(f"Bulk modulus: {result.b0:.1f} GPa")
print(f"B': {result.bp:.2f}")
print(f"Fitting residual: {result.residual:.6f}")
```

### EOSResult

```python
@dataclass
class EOSResult:
    status: str
    points: list[EOSPoint]
    v0: float | None  # Equilibrium volume (A^3)
    e0: float | None  # Equilibrium energy (eV)
    b0: float | None  # Bulk modulus (GPa)
    bp: float | None  # Bulk modulus pressure derivative
    eos_type: str  # birch_murnaghan, murnaghan, vinet
    residual: float | None
    error_message: str | None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
```

Each `EOSPoint` contains:
- `volume_scale`: V/V0 scaling factor
- `volume`: Absolute volume (A^3)
- `energy`: Total energy (eV or Hartree)
- `pressure`: Pressure (GPa)
- `job_pk`: Job primary key
- `status`: "pending", "running", "completed", "failed"

## Integration with CrystalController

All workflow classes integrate seamlessly with `CrystalController`:

```python
from crystalmath.api import CrystalController
from crystalmath.workflows.convergence import ConvergenceStudy, ConvergenceStudyConfig
from crystalmath.models import JobSubmission, DftCode

# Initialize controller
ctrl = CrystalController(db_path="workflows.db")

# Create convergence study
config = ConvergenceStudyConfig(...)
study = ConvergenceStudy(config)

# Submit jobs
for name, content in study.generate_inputs():
    job = JobSubmission(name=name, input_content=content, dft_code=DftCode.CRYSTAL)
    ctrl.submit_job(job)

# Monitor jobs
jobs = ctrl.get_jobs()
for job in jobs:
    print(f"{job.name}: {job.state}")
```

## JSON Serialization

All result classes provide `to_dict()` methods for JSON serialization:

```python
result = study.analyze_results(energies)

# Serialize to JSON
import json
json_data = json.dumps(result.to_dict(), indent=2)

# Save to file
with open("convergence_result.json", "w") as f:
    json.dump(result.to_dict(), f, indent=2)
```

## Next Steps

- **[Advanced Workflows](advanced-workflows.md)** - Multi-step workflow orchestration
- **[Cluster Setup](cluster-setup.md)** - Remote execution configuration
- **[Getting Started](getting-started.md)** - Installation and quick start
