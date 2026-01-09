# Advanced Workflows Guide

This guide covers advanced CrystalMath features including multi-code workflows, specialized runners, error recovery strategies, custom workflow creation, and PWD interoperability.

## Multi-Code Workflows

Many materials science calculations require multiple DFT codes. CrystalMath handles code handoffs automatically.

### VASP -> YAMBO Workflow

The most common multi-code workflow combines VASP ground-state calculations with YAMBO for GW/BSE:

```python
from crystalmath.high_level import WorkflowBuilder

workflow = (
    WorkflowBuilder()
    .from_file("NbOCl2.cif")
    .relax(code="vasp", protocol="moderate")
    .scf(code="vasp")
    .with_gw(code="yambo", protocol="gw0", n_bands=100)
    .with_bse(code="yambo", n_valence=4, n_conduction=4)
    .on_cluster("beefcake2", partition="gpu")
    .build()
)

results = workflow.run()

print(f"DFT gap: {results.band_gap_ev:.3f} eV")
print(f"GW gap: {results.gw_gap_ev:.3f} eV")
print(f"Optical gap: {results.optical_gap_ev:.3f} eV")
print(f"Exciton binding: {results.exciton_binding_ev:.3f} eV")
```

### Data Handoff Details

When switching between codes, CrystalMath handles:

1. **Wavefunction conversion:** VASP `WAVECAR` -> QE `save/` -> YAMBO database
2. **Structure transfer:** Consistent atomic positions and lattice
3. **k-point mapping:** Ensures consistent Brillouin zone sampling

### Quantum ESPRESSO -> YAMBO

```python
workflow = (
    WorkflowBuilder()
    .from_file("MoS2.cif")
    .relax(code="quantum_espresso")
    .scf(code="quantum_espresso")
    .with_gw(code="yambo", protocol="g0w0")
    .with_bse(code="yambo", n_valence=3, n_conduction=3)
    .on_cluster("beefcake2")
    .build()
)
```

### CRYSTAL23 -> Wannier90

```python
workflow = (
    WorkflowBuilder()
    .from_file("Si.cif")
    .relax(code="crystal23")
    .scf(code="crystal23")
    .then_bands(code="wannier90", n_wannier=8)
    .on_cluster("beefcake2")
    .build()
)
```

## Specialized Analysis Runners

CrystalMath provides specialized runner classes for different analysis types.

### StandardAnalysis

For electronic structure calculations (SCF, relax, bands, DOS):

```python
from crystalmath.high_level.runners import StandardAnalysis
from crystalmath.high_level.clusters import get_cluster_profile

cluster = get_cluster_profile("beefcake2")

runner = StandardAnalysis(
    cluster=cluster,
    protocol="moderate",
    include_relax=True,
    include_bands=True,
    include_dos=True,
    kpath="auto",
    dos_mesh=[12, 12, 12],
    dft_code="vasp",
    output_dir="./results/Si"
)

results = runner.run("mp-149")  # Silicon from Materials Project

print(f"Band gap: {results.band_gap_ev:.2f} eV")
fig = results.plot_bands_dos()
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include_relax` | bool | True | Relax structure before SCF |
| `include_bands` | bool | True | Calculate band structure |
| `include_dos` | bool | True | Calculate DOS |
| `kpath` | str/list | "auto" | K-point path specification |
| `dos_mesh` | list | None | DOS k-mesh (auto if None) |
| `dft_code` | str | None | DFT code preference |

### OpticalAnalysis

For many-body perturbation theory (GW, BSE):

```python
from crystalmath.high_level.runners import OpticalAnalysis

runner = OpticalAnalysis(
    cluster=get_cluster_profile("beefcake2"),
    protocol="moderate",
    dft_code="vasp",
    gw_code="yambo",
    gw_protocol="gw0",
    n_bands_gw=100,
    n_valence_bse=4,
    n_conduction_bse=4,
    include_bse=True,
)

results = runner.run("NbOCl2.cif")

print(f"GW gap: {results.gw_gap_ev:.2f} eV")
print(f"Optical gap: {results.optical_gap_ev:.2f} eV")
print(f"Exciton binding: {results.exciton_binding_ev:.3f} eV")
```

**GW Protocols:**

| Protocol | Method | Cost | Accuracy |
|----------|--------|------|----------|
| `g0w0` | Single-shot | Low | Good |
| `gw0` | Partial self-consistency | Medium | Better |
| `evgw` | Eigenvalue self-consistent | High | Best |

### PhononAnalysis

For phonon dispersion and thermodynamics:

```python
from crystalmath.high_level.runners import PhononAnalysis

runner = PhononAnalysis(
    cluster=get_cluster_profile("beefcake2"),
    protocol="moderate",
    supercell=[2, 2, 2],
    displacement=0.01,
    include_thermodynamics=True,
    temperature_range=(0, 1000, 10),
    dft_code="vasp",
)

results = runner.run("Si.cif")

if results.has_imaginary_modes:
    print("Structure is dynamically unstable!")
else:
    fig = results.plot_phonons()
```

### ElasticAnalysis

For elastic constants and mechanical properties:

```python
from crystalmath.high_level.runners import ElasticAnalysis

runner = ElasticAnalysis(
    cluster=get_cluster_profile("beefcake2"),
    protocol="moderate",
    strain_magnitude=0.01,
    num_strains=6,
    dft_code="vasp",
)

results = runner.run("TiO2.cif")

print(f"Bulk modulus: {results.bulk_modulus_gpa:.1f} GPa")
print(f"Shear modulus: {results.shear_modulus_gpa:.1f} GPa")
print(f"Young's modulus: {results.youngs_modulus_gpa:.1f} GPa")
print(f"Poisson ratio: {results.poisson_ratio:.3f}")
```

### TransportAnalysis

For BoltzTraP2 transport calculations:

```python
from crystalmath.high_level.runners import TransportAnalysis

runner = TransportAnalysis(
    cluster=get_cluster_profile("beefcake2"),
    protocol="moderate",
    doping_levels=[1e18, 1e19, 1e20],  # cm^-3
    temperature_range=(300, 800, 50),   # K
    interpolation_factor=5,
    dft_code="vasp",
)

results = runner.run("Bi2Te3.cif")

print(f"Seebeck: {results.seebeck_coefficient} uV/K")
```

## Error Recovery Strategies

CrystalMath implements multiple error recovery strategies to handle calculation failures gracefully.

### Available Strategies

```python
from crystalmath.protocols import ErrorRecoveryStrategy

# Stop immediately on error
ErrorRecoveryStrategy.FAIL_FAST

# Retry with same parameters
ErrorRecoveryStrategy.RETRY

# Self-healing parameter adjustment
ErrorRecoveryStrategy.ADAPTIVE

# Restart from last checkpoint
ErrorRecoveryStrategy.CHECKPOINT
```

### Using Recovery Strategies

```python
from crystalmath.high_level import WorkflowBuilder
from crystalmath.protocols import ErrorRecoveryStrategy

workflow = (
    WorkflowBuilder()
    .from_file("tricky_structure.cif")
    .relax()
    .then_bands()
    .with_recovery(ErrorRecoveryStrategy.ADAPTIVE)
    .build()
)
```

### Adaptive Recovery Behavior

When `ADAPTIVE` strategy is used, CrystalMath:

1. **Memory errors:** Reduces MPI parallelization
2. **Convergence failures:** Relaxes energy/force thresholds
3. **Timeout errors:** Increases walltime
4. **SLURM failures:** Adjusts partition/resources

Example:

```python
# Original parameters
# energy_convergence = 1e-5 eV

# After SCF convergence failure:
# energy_convergence = 1e-4 eV (10x relaxed)
```

### Custom Recovery Logic

```python
from crystalmath.high_level.runners import BaseAnalysisRunner

class MyRunner(BaseAnalysisRunner):
    def _attempt_adaptive_recovery(self, step, failed_result):
        error_text = " ".join(failed_result.errors).lower()

        if "memory" in error_text:
            # Reduce parallelization
            step.resources.num_mpi_ranks //= 2

        elif "convergence" in error_text:
            # Relax convergence criteria
            step.parameters["energy_convergence"] *= 10

        elif "timeout" in error_text:
            # Extend walltime
            step.resources.walltime_hours *= 1.5

        return self._execute_step(step)
```

## Custom Workflow Creation

### Subclassing BaseAnalysisRunner

Create custom runners by subclassing `BaseAnalysisRunner`:

```python
from crystalmath.high_level.runners import BaseAnalysisRunner
from crystalmath.protocols import (
    WorkflowStep,
    WorkflowType,
    ResourceRequirements,
)

class MyCustomRunner(BaseAnalysisRunner):
    """Custom workflow for specialized analysis."""

    def __init__(self, my_parameter=None, **kwargs):
        super().__init__(**kwargs)
        self._my_parameter = my_parameter

    def _build_workflow_steps(self):
        steps = []

        # Add relaxation
        steps.append(WorkflowStep(
            name="relax",
            workflow_type=WorkflowType.RELAX,
            code="vasp",
            parameters=self._get_parameters(WorkflowType.RELAX, "vasp"),
        ))

        # Add custom step
        steps.append(WorkflowStep(
            name="my_analysis",
            workflow_type=WorkflowType.SCF,  # Or custom type
            code="vasp",
            parameters={
                "custom_param": self._my_parameter,
                **self._get_parameters(WorkflowType.SCF, "vasp"),
            },
            depends_on=["relax"],
        ))

        return steps

    def _get_default_resources(self):
        return ResourceRequirements(
            num_nodes=1,
            num_mpi_ranks=20,
            walltime_hours=12,
        )

# Usage
runner = MyCustomRunner(
    cluster=get_cluster_profile("beefcake2"),
    my_parameter="value",
    protocol="moderate"
)
results = runner.run("structure.cif")
```

### Custom Parameter Generation

```python
class MyRunner(BaseAnalysisRunner):

    def _get_parameters(self, workflow_type, code, **overrides):
        # Get base parameters from protocol
        params = self._get_protocol_parameters(workflow_type)

        # Add code-specific parameters
        if code == "vasp":
            params.update({
                "prec": "Accurate",
                "algo": "Normal",
                "ismear": 0,
                "sigma": 0.05,
            })

        # Apply custom logic
        if self._structure_info and self._structure_info.is_magnetic:
            params["ispin"] = 2

        # Apply overrides
        params.update(overrides)

        return params
```

## Asynchronous Execution

### Progress Tracking in Jupyter

```python
from crystalmath.high_level import WorkflowBuilder

workflow = (
    WorkflowBuilder()
    .from_file("structure.cif")
    .relax()
    .then_bands()
    .on_cluster("beefcake2")
    .with_progress()
    .build()
)

# Async execution with progress updates
async for update in workflow.run_async():
    print(f"[{update.percent:.0f}%] {update.step_name}: {update.message}")

    if update.has_intermediate_result:
        # Access partial results for live plotting
        partial = update.intermediate_result
        display(partial.plot_bands())

    if update.status == "completed":
        final_results = update.intermediate_result
```

### Non-Blocking Submission

```python
import time

# Submit without waiting
workflow_id = workflow.submit()
print(f"Submitted: {workflow_id}")

# Poll for completion
from crystalmath.high_level.builder import Workflow

while True:
    status = Workflow.get_status(workflow_id)
    print(f"State: {status.state}, Progress: {status.progress_percent:.0f}%")

    if status.state in ("completed", "failed"):
        break

    time.sleep(60)

# Get result
if status.state == "completed":
    results = Workflow.get_result(workflow_id)
else:
    print(f"Workflow failed: {status.errors}")
```

## PWD Interoperability

PWD (Python Workflow Definition) enables workflow exchange with other engines (AiiDA, jobflow, pyiron).

### Exporting to PWD

```python
from crystalmath.integrations.pwd_bridge import PWDConverter, export_to_pwd
from crystalmath.protocols import WorkflowStep, WorkflowType

# Create workflow steps
steps = [
    WorkflowStep(
        name="relax",
        workflow_type=WorkflowType.RELAX,
        code="vasp",
        parameters={"force_threshold": 0.01},
    ),
    WorkflowStep(
        name="bands",
        workflow_type=WorkflowType.BANDS,
        code="vasp",
        depends_on=["relax"],
    ),
]

# Quick export
pwd_json = export_to_pwd(steps)
print(pwd_json)

# Export with CrystalMath extensions
converter = PWDConverter()
pwd_json, extensions = converter.to_pwd_with_extensions(steps)

# Save as PWD package
converter.save_pwd(steps, Path("./output"), "my_workflow")
# Creates:
#   ./output/my_workflow/
#     - workflow.json
#     - workflow.py
#     - environment.yml
#     - extensions.json
```

### Importing from PWD

```python
from crystalmath.integrations.pwd_bridge import PWDConverter, import_from_pwd

# From PWD directory
steps = import_from_pwd(Path("./my_workflow"))

# From JSON dict
pwd_json = {
    "nodes": [...],
    "edges": [...],
}
steps = import_from_pwd(pwd_json)

# Run imported workflow
from crystalmath.high_level.runners import StandardAnalysis

runner = StandardAnalysis(
    cluster=get_cluster_profile("beefcake2"),
)
# Configure runner with imported steps...
```

### PWD Extensions

CrystalMath extensions capture additional information:

```python
converter = PWDConverter()
pwd_json, extensions = converter.to_pwd_with_extensions(steps)

print(extensions)
# {
#     "crystalmath_version": "1.0.0",
#     "extensions": {
#         "func_relax": {
#             "resources": {
#                 "num_nodes": 1,
#                 "num_mpi_ranks": 20,
#                 ...
#             },
#             "code": "vasp",
#             "workflow_type": "relax",
#             "protocol_level": "moderate",
#             "error_recovery": "adaptive"
#         },
#         ...
#     }
# }
```

## Checkpointing and Recovery

### Automatic Checkpointing

```python
from crystalmath.high_level.runners import StandardAnalysis

runner = StandardAnalysis(
    cluster=get_cluster_profile("beefcake2"),
    checkpoint_interval=1,  # Checkpoint after each step
    preserve_intermediates=True,  # Keep intermediate files
)
```

### Resuming from Checkpoint

```python
from crystalmath.protocols import ErrorRecoveryStrategy

workflow = (
    WorkflowBuilder()
    .from_file("structure.cif")
    .relax()
    .then_phonon(supercell=[3, 3, 3])  # Long calculation
    .with_recovery(ErrorRecoveryStrategy.CHECKPOINT)
    .build()
)

# If interrupted, resume from last checkpoint
results = workflow.run()
```

## Complete Advanced Example

```python
from crystalmath.high_level import WorkflowBuilder
from crystalmath.high_level.runners import OpticalAnalysis
from crystalmath.high_level.clusters import get_cluster_profile, get_optimal_resources
from crystalmath.protocols import ErrorRecoveryStrategy
from crystalmath.integrations.pwd_bridge import PWDConverter

# Define material
structure_file = "NbOCl2.cif"
cluster = get_cluster_profile("beefcake2")

# Estimate resources
resources = get_optimal_resources(
    code="yambo",
    system_size=12,  # atoms
    calculation_type="gw",
    use_gpu=True
)

# Method 1: Using OpticalAnalysis runner
runner = OpticalAnalysis(
    cluster=cluster,
    protocol="moderate",
    dft_code="vasp",
    gw_code="yambo",
    gw_protocol="gw0",
    n_bands_gw=100,
    n_valence_bse=4,
    n_conduction_bse=4,
    output_dir="./results/NbOCl2",
    recovery_strategy=ErrorRecoveryStrategy.ADAPTIVE,
    preserve_intermediates=True,
)

results = runner.run(structure_file)

# Method 2: Using WorkflowBuilder for more control
workflow = (
    WorkflowBuilder()
    .from_file(structure_file)
    .relax(code="vasp", force_threshold=0.005)
    .scf(code="vasp")
    .then_bands(kpath="auto", kpoints_per_segment=100)
    .then_dos(mesh=[16, 16, 16], projected=True)
    .with_gw(code="yambo", protocol="gw0", n_bands=100)
    .with_bse(code="yambo", n_valence=6, n_conduction=6)
    .on_cluster("beefcake2", partition="gpu", resources=resources)
    .with_progress()
    .with_output("./results/NbOCl2_full")
    .with_recovery(ErrorRecoveryStrategy.ADAPTIVE)
    .build()
)

# Execute asynchronously
async for update in workflow.run_async():
    print(f"[{update.percent:.0f}%] {update.step_name}")

results = Workflow.get_result(workflow.workflow_id)

# Export results
results.to_dataframe().to_csv("properties.csv")
results.to_latex_table("table.tex")
results.to_json("results.json")

# Generate figures
fig = results.plot_bands_dos()
fig.savefig("electronic_structure.png", dpi=300)

fig = results.plot_optical()
fig.savefig("optical_absorption.png", dpi=300)

# Export workflow for sharing
converter = PWDConverter()
converter.save_pwd(runner.steps, Path("./exports"), "NbOCl2_workflow")

print(f"Formula: {results.formula}")
print(f"DFT gap: {results.band_gap_ev:.3f} eV")
print(f"GW gap: {results.gw_gap_ev:.3f} eV")
print(f"Optical gap: {results.optical_gap_ev:.3f} eV")
print(f"Exciton binding: {results.exciton_binding_ev:.3f} eV")
print(f"CPU hours: {results.total_cpu_hours:.1f}")
```
