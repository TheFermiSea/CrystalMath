# Advanced Workflows & Orchestration

This guide covers advanced CrystalMath features including multi-step workflows, VASP input generation, template-based workflows, and remote execution patterns.

## Multi-Step Workflow Pattern

Chain workflow classes together using `CrystalController` to orchestrate complex calculations.

### Example: Convergence → Band Structure Pipeline

```python
from crystalmath.api import CrystalController
from crystalmath.models import JobSubmission, DftCode
from crystalmath.workflows.convergence import (
    ConvergenceStudy, ConvergenceStudyConfig, ConvergenceParameter
)
from crystalmath.workflows.bands import (
    BandStructureWorkflow, BandStructureConfig, BandPathPreset
)

# Initialize controller
ctrl = CrystalController(db_path="project.db")

# Step 1: Convergence study for k-points
conv_config = ConvergenceStudyConfig(
    parameter=ConvergenceParameter.SHRINK,
    values=[4, 6, 8, 10, 12],
    base_input=open("si.d12").read(),
    energy_threshold=0.001,
    dft_code="crystal",
)

study = ConvergenceStudy(conv_config)
inputs = study.generate_inputs()

# Submit convergence jobs
conv_pks = []
for name, content in inputs:
    job = JobSubmission(
        name=name,
        input_content=content,
        dft_code=DftCode.CRYSTAL,
    )
    conv_pks.append(ctrl.submit_job(job))

print(f"Submitted {len(conv_pks)} convergence jobs")

# ... wait for completion (polling or callback) ...

# Collect results and determine best k-point setting
energies = []
for pk in conv_pks:
    details = ctrl.get_job_details(pk)
    if details.state == "finished":
        energies.append(details.results.get("energy"))

result = study.analyze_results(energies)
print(f"Converged at SHRINK={result.converged_value}")

# Step 2: Band structure with converged parameters
best_pk = conv_pks[result.converged_at_index]
bands_config = BandStructureConfig(
    source_job_pk=best_pk,
    band_path=BandPathPreset.AUTO,
    kpoints_per_segment=50,
    compute_dos=True,
    dos_mesh=[12, 12, 12],
)

bands_wf = BandStructureWorkflow(bands_config)
# ... generate and submit band structure jobs ...
```

### Polling for Completion

```python
import time

def wait_for_jobs(ctrl, pks, timeout=3600, poll_interval=10):
    """Wait for jobs to complete with timeout."""
    start = time.time()
    while time.time() - start < timeout:
        states = [ctrl.get_job_details(pk).state for pk in pks]

        if all(s in ("finished", "failed") for s in states):
            finished = sum(1 for s in states if s == "finished")
            failed = sum(1 for s in states if s == "failed")
            print(f"Complete: {finished} finished, {failed} failed")
            return True

        print(f"Status: {states.count('running')} running, {states.count('pending')} pending")
        time.sleep(poll_interval)

    print("Timeout reached")
    return False

# Usage
if wait_for_jobs(ctrl, conv_pks):
    # Proceed to next step
    pass
```

## VASP Input Generation

CrystalMath provides utilities for generating complete VASP input file sets.

### From pymatgen Structure

```python
from crystalmath.vasp.generator import VaspInputGenerator, IncarPreset
from pymatgen.core import Structure

# Load structure
structure = Structure.from_file("POSCAR")

# Generate inputs with preset
gen = VaspInputGenerator()
inputs = gen.generate_from_structure(
    structure,
    preset=IncarPreset.RELAX,
    kpoints_density=0.04,  # 1/A
)

# Access generated files
print(inputs.poscar)
print(inputs.incar)
print(inputs.kpoints)
print(inputs.potcar_symbols)

# Write to directory
inputs.write_to_directory("vasp_relax/")
```

### Available IncarPreset Values

| Preset | Description | Use Case |
|--------|-------------|----------|
| `RELAX` | Geometry optimization | Structure relaxation |
| `STATIC` | Single-point SCF | Energy, DOS |
| `BANDS` | Band structure | Electronic structure |
| `MD` | Molecular dynamics | AIMD simulation |
| `HSE` | Hybrid functional (HSE06) | Accurate band gaps |

### Custom INCAR Parameters

```python
from crystalmath.vasp.incar import IncarBuilder

# Build custom INCAR
incar = (
    IncarBuilder()
    .set_preset(IncarPreset.RELAX)
    .set_electronic_structure(
        prec="Accurate",
        algo="Normal",
        nelm=100,
    )
    .set_ionic_relaxation(
        ibrion=2,
        isif=3,
        nsw=200,
        ediffg=-0.01,
    )
    .set_magnetic(
        ispin=2,
        magmom=[5.0, 5.0, -5.0, -5.0],  # Per atom
    )
    .build()
)

print(incar.to_string())
```

### KPOINTS Generation

```python
from crystalmath.vasp.kpoints import KpointsBuilder, KpointsMesh

# Gamma-centered mesh
kpoints = KpointsBuilder.gamma_centered_mesh(
    kpoints=[8, 8, 8],
    shift=[0, 0, 0],
)

# Monkhorst-Pack mesh
kpoints = KpointsBuilder.monkhorst_pack_mesh(
    kpoints=[6, 6, 4],
)

# From k-point density
kpoints = KpointsBuilder.from_density(
    structure=structure,
    density=0.04,  # 1/A
    gamma_centered=True,
)

print(kpoints.to_string())
```

### From Materials Project

```python
from crystalmath.vasp.generator import generate_vasp_inputs_from_mp

# Generate VASP inputs directly from MP ID
inputs = generate_vasp_inputs_from_mp(
    mp_id="mp-149",  # Silicon
    preset=IncarPreset.RELAX,
    api_key="your-api-key",  # Or set MP_API_KEY env var
)

inputs.write_to_directory("si_relax/")
```

## EOS Workflow - Complete Example

Determine bulk modulus and equilibrium volume via equation of state fitting.

```python
from crystalmath.api import CrystalController
from crystalmath.models import JobSubmission, DftCode
from crystalmath.workflows.eos import EOSWorkflow, EOSConfig

ctrl = CrystalController(db_path="eos_study.db")

# Step 1: Submit relaxation job for reference structure
relax_job = JobSubmission(
    name="mgo_relax",
    input_content=open("mgo_relax.d12").read(),
    dft_code=DftCode.CRYSTAL,
)
relax_pk = ctrl.submit_job(relax_job)

# ... wait for relaxation to complete ...

# Step 2: Extract optimized structure
relax_details = ctrl.get_job_details(relax_pk)
cell = relax_details.results.get("final_cell")
positions = relax_details.results.get("final_positions")
symbols = relax_details.results.get("symbols", ["Mg", "O"])

# Step 3: Create EOS workflow
config = EOSConfig(
    source_job_pk=relax_pk,
    volume_range=(0.90, 1.10),
    num_points=7,
    eos_type="birch_murnaghan",
)

workflow = EOSWorkflow(config)

# Step 4: Generate volume-scaled structures
structures = workflow.generate_volume_points(cell, positions, symbols)
print(f"Generated {len(structures)} volume points")

# Step 5: Submit SCF calculations
for i, struct in enumerate(structures):
    job = JobSubmission(
        name=f"eos_vol_{i}",
        input_content=struct["input_content"],
        dft_code=DftCode.CRYSTAL,
    )
    workflow.result.points[i].job_pk = ctrl.submit_job(job)

# ... wait for all EOS jobs to complete ...

# Step 6: Collect energies and fit EOS
for i, point in enumerate(workflow.result.points):
    details = ctrl.get_job_details(point.job_pk)
    if details.state == "finished":
        point.energy = details.results.get("energy")
        point.status = "completed"

# Step 7: Fit equation of state
result = workflow.fit_eos()

print(f"Equilibrium volume: {result.v0:.2f} A^3")
print(f"Bulk modulus: {result.b0:.1f} GPa")
print(f"B' (pressure derivative): {result.bp:.2f}")
print(f"Fitting residual: {result.residual:.6f}")

# Save results
import json
with open("eos_results.json", "w") as f:
    json.dump(result.to_dict(), f, indent=2)
```

## Template-Based Workflows

Use the template library for standardized input generation.

### Listing Templates

```python
from crystalmath.templates import list_templates, get_template_dir

# List all templates
for template in list_templates():
    print(f"{template.category}/{template.name}")
    print(f"  Code: {template.dft_code}")
    print(f"  Description: {template.description}")
    print(f"  Tags: {template.tags}")

# Filter by category
for template in list_templates(category="advanced"):
    print(f"{template.name}: {template.description}")

# Filter by DFT code
for template in list_templates(dft_code="vasp"):
    print(f"{template.category}/{template.name}")
```

### Template Directory Structure

```
templates/
├── basic/           # Single-point, optimization
│   ├── scf.d12
│   ├── relax.d12
│   └── ...
├── advanced/        # Band structure, DOS, elastic
│   ├── bands.d12
│   ├── dos.d12
│   └── ...
├── workflows/       # Multi-step workflows
│   ├── convergence.yaml
│   └── ...
├── vasp/            # VASP-specific
│   ├── INCAR_relax
│   └── ...
├── qe/              # Quantum Espresso
│   └── ...
└── slurm/           # SLURM batch scripts
    └── ...
```

### Using Templates

```python
from pathlib import Path
from crystalmath.templates import get_template_dir

templates_dir = get_template_dir()

# Load a template
template_path = templates_dir / "basic" / "scf.d12"
with open(template_path) as f:
    template_content = f.read()

# Customize for your structure
input_content = template_content.replace("{{SHRINK}}", "8")

# Submit job
job = JobSubmission(
    name="custom_scf",
    input_content=input_content,
    dft_code=DftCode.CRYSTAL,
)
ctrl.submit_job(job)
```

## Remote Execution Patterns

### SSH Runner

Execute jobs on remote machines via SSH.

```python
from crystalmath.models import JobSubmission, RunnerType, ClusterConfig, ClusterType

# Configure SSH cluster
cluster = ClusterConfig(
    name="beefcake2",
    hostname="10.0.0.10",
    username="ubuntu",
    cluster_type=ClusterType.SSH,
    max_concurrent_jobs=4,
)

cluster_id = ctrl.create_cluster(cluster)

# Submit job to SSH runner
job = JobSubmission(
    name="remote_scf",
    input_content=open("input.d12").read(),
    dft_code=DftCode.CRYSTAL,
    runner_type=RunnerType.SSH,
    cluster_id=cluster_id,
)

pk = ctrl.submit_job(job)
```

### SLURM Runner

Submit batch jobs to SLURM clusters.

```python
# Configure SLURM cluster
cluster = ClusterConfig(
    name="hpc_cluster",
    hostname="login.hpc.university.edu",
    username="myuser",
    cluster_type=ClusterType.SLURM,
    max_concurrent_jobs=10,
)

cluster_id = ctrl.create_cluster(cluster)

# Submit SLURM batch job
job = JobSubmission(
    name="slurm_calc",
    input_content=open("large_calc.d12").read(),
    dft_code=DftCode.CRYSTAL,
    runner_type=RunnerType.SLURM,
    cluster_id=cluster_id,
    slurm_options={
        "partition": "general",
        "nodes": 2,
        "ntasks_per_node": 20,
        "time": "24:00:00",
        "mem": "64G",
    },
)

pk = ctrl.submit_job(job)
```

## Phonon Workflow - Complete Example

Calculate phonon dispersion and thermodynamic properties.

```python
from crystalmath.workflows.phonon import (
    PhononWorkflow, PhononConfig, PhononMethod, PhononDFTCode
)

# Step 1: Optimize structure (prerequisite)
relax_pk = ctrl.submit_job(
    JobSubmission(
        name="si_relax",
        input_content=open("si_relax.d12").read(),
        dft_code=DftCode.CRYSTAL,
    )
)

# ... wait for optimization ...

# Step 2: Configure phonon workflow
config = PhononConfig(
    source_job_pk=relax_pk,
    method=PhononMethod.PHONOPY,
    supercell_dim=[2, 2, 2],
    displacement_distance=0.01,
    use_symmetry=True,
    mesh=[20, 20, 20],
    band_path="AUTO",
    compute_thermal=True,
    tmin=0.0,
    tmax=1000.0,
    tstep=10.0,
    dft_code=PhononDFTCode.CRYSTAL,
)

workflow = PhononWorkflow(config)

# Step 3: Generate displacements
displacements = workflow.generate_displacements()
print(f"Phonopy generated {len(displacements)} displacements")

# Step 4: Submit force calculations
for disp in displacements:
    job = JobSubmission(
        name=f"phonon_disp_{disp.index}",
        input_content=disp.input_content,
        dft_code=DftCode.CRYSTAL,
    )
    disp.job_pk = ctrl.submit_job(job)

# ... wait for all force calculations ...

# Step 5: Collect forces and analyze
for disp in displacements:
    details = ctrl.get_job_details(disp.job_pk)
    if details.state == "finished":
        disp.forces = details.results.get("forces")
        disp.status = "completed"

result = workflow.collect_forces_and_analyze()

# Step 6: Check stability
if result.has_imaginary:
    print("WARNING: Imaginary frequencies detected!")
    print(f"Minimum frequency: {result.min_frequency:.2f} cm^-1")
    print("Structure may be dynamically unstable")
else:
    print("Structure is dynamically stable")
    print(f"Acoustic mode frequencies at Gamma: {result.frequencies_at_gamma[:3]}")

# Step 7: Analyze thermal properties
if result.thermal_properties:
    temps = result.thermal_properties["temperatures"]
    free_energy = result.thermal_properties["free_energy"]
    heat_capacity = result.thermal_properties["heat_capacity"]

    print(f"Zero-point energy: {result.zero_point_energy_ev:.4f} eV")
    print(f"Free energy at 300 K: {free_energy[30]:.4f} eV")
    print(f"Heat capacity at 300 K: {heat_capacity[30]:.2f} J/mol·K")
```

## Error Handling and Recovery

### Robust Job Submission

```python
def submit_with_retry(ctrl, job, max_retries=3):
    """Submit job with automatic retry on failure."""
    for attempt in range(max_retries):
        try:
            pk = ctrl.submit_job(job)
            print(f"Job submitted: PK={pk}")
            return pk
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                raise
            time.sleep(5)

# Usage
pk = submit_with_retry(ctrl, job)
```

### Job Status Monitoring

```python
def monitor_job(ctrl, pk, max_wait=3600, poll_interval=10):
    """Monitor job until completion."""
    start = time.time()
    while time.time() - start < max_wait:
        details = ctrl.get_job_details(pk)
        print(f"Job {pk}: {details.state}")

        if details.state == "finished":
            return details.results
        elif details.state == "failed":
            print(f"Job failed: {details.error_message}")
            return None

        time.sleep(poll_interval)

    print(f"Job {pk} timed out after {max_wait}s")
    return None

# Usage
results = monitor_job(ctrl, pk)
if results:
    print(f"Energy: {results.get('energy')} eV")
```

## Next Steps

- **[Workflow Classes Reference](high-level-api.md)** - Detailed API documentation
- **[Cluster Setup](cluster-setup.md)** - SSH and SLURM configuration
- **[Getting Started](getting-started.md)** - Installation and basics
