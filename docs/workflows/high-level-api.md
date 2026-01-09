# High-Level API Reference

This guide covers the CrystalMath high-level API, including the `HighThroughput` class, `WorkflowBuilder` fluent API, and `AnalysisResults` export methods.

## HighThroughput Class

The `HighThroughput` class provides one-liner methods for complete materials analysis workflows.

### Basic Usage

```python
from crystalmath.high_level import HighThroughput

# Complete analysis from CIF file
results = HighThroughput.run_standard_analysis(
    structure="NbOCl2.cif",
    properties=["bands", "dos", "phonon", "bse"],
    codes={"dft": "vasp", "gw": "yambo"},
    cluster="beefcake2"
)
```

### run_standard_analysis()

The primary entry point for high-throughput analysis.

```python
results = HighThroughput.run_standard_analysis(
    structure,              # Input structure (file path, MP ID, or Structure)
    properties,             # List of properties to calculate
    codes=None,             # Code selection override
    cluster=None,           # Cluster profile name
    protocol="moderate",    # Accuracy level
    progress_callback=None, # Progress notification handler
    output_dir=None,        # Output directory
    **kwargs                # Additional workflow options
)
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `structure` | str, Path, Structure | Input structure source |
| `properties` | List[str] | Properties to calculate |
| `codes` | Dict[str, str] | Code overrides, e.g., `{"dft": "vasp", "gw": "yambo"}` |
| `cluster` | str | Cluster profile: "beefcake2", "local", or None |
| `protocol` | str | Accuracy: "fast", "moderate", "precise" |
| `progress_callback` | ProgressCallback | Progress handler |
| `output_dir` | str, Path | Output directory |

**Returns:** `AnalysisResults` with all computed properties

### Structure Input Methods

```python
# From Materials Project ID
results = HighThroughput.from_mp("mp-149", properties=["bands"])

# From POSCAR file
results = HighThroughput.from_poscar("POSCAR", properties=["relax"])

# From pymatgen Structure
from pymatgen.core import Structure
struct = Structure.from_file("struct.cif")
results = HighThroughput.from_structure(struct, properties=["scf"])

# From AiiDA database
results = HighThroughput.from_aiida(12345, properties=["bands"])
results = HighThroughput.from_aiida("a1b2c3d4-e5f6-...", properties=["bands"])
```

### Property Discovery

```python
# List all supported properties
props = HighThroughput.get_supported_properties()
# ['scf', 'relax', 'bands', 'dos', 'phonon', 'elastic', 'dielectric', 'gw', 'bse', 'eos', 'neb']

# Get details about a property
info = HighThroughput.get_property_info("gw")
# {
#     'name': 'gw',
#     'workflow_type': 'gw',
#     'default_code': 'yambo',
#     'dependencies': ['scf']
# }
```

## WorkflowBuilder Fluent API

For fine-grained control, use the `WorkflowBuilder` with method chaining.

### Basic Usage

```python
from crystalmath.high_level import WorkflowBuilder

workflow = (
    WorkflowBuilder()
    .from_file("NbOCl2.cif")
    .relax(code="vasp", protocol="moderate")
    .then_bands(kpath="auto", kpoints_per_segment=50)
    .then_dos(mesh=[12, 12, 12])
    .on_cluster("beefcake2")
    .build()
)

result = workflow.run()
```

### Structure Input Methods

```python
builder = WorkflowBuilder()

# From file
builder.from_file("structure.cif")
builder.from_file("POSCAR")
builder.from_file("/path/to/structure.xyz")

# From Materials Project
builder.from_mp("mp-149")      # Silicon
builder.from_mp("mp-2815")     # MoS2

# From pymatgen Structure
struct = Structure.from_file("POSCAR")
builder.from_structure(struct)

# From AiiDA
builder.from_aiida(12345)                  # By PK
builder.from_aiida("a1b2c3d4-e5f6-...")    # By UUID
```

### DFT Workflow Steps

#### relax() - Geometry Optimization

```python
builder.relax(
    code=None,              # DFT code (auto-selected if None)
    protocol="moderate",     # fast, moderate, precise
    force_threshold=0.01,    # eV/Angstrom
    stress_threshold=0.1,    # kbar
    max_steps=200,           # Maximum ionic steps
)
```

#### scf() - Single Point

```python
builder.scf(
    code=None,
    protocol="moderate",
)
```

#### then_bands() - Band Structure

```python
builder.then_bands(
    kpath="auto",              # "auto", "hexagonal", or custom list
    kpoints_per_segment=50,    # Points per path segment
)

# Custom k-path
builder.then_bands(
    kpath=[
        ("Gamma", [0, 0, 0]),
        ("X", [0.5, 0, 0]),
        ("M", [0.5, 0.5, 0]),
        ("Gamma", [0, 0, 0]),
    ]
)
```

#### then_dos() - Density of States

```python
builder.then_dos(
    mesh=None,          # K-point mesh (auto if None)
    smearing=0.05,      # Gaussian smearing (eV)
    projected=False,    # Orbital-projected DOS
)
```

#### then_phonon() - Phonon Dispersion

```python
builder.then_phonon(
    supercell=None,        # [nx, ny, nz] (auto if None)
    displacement=0.01,     # Angstrom
)
```

#### then_elastic() - Elastic Constants

```python
builder.then_elastic()
```

#### then_dielectric() - Dielectric Tensor

```python
builder.then_dielectric()
```

### Many-Body Methods

#### with_gw() - GW Corrections

```python
builder.with_gw(
    code="yambo",           # yambo or berkeleygw
    protocol="gw0",         # g0w0, gw0, evgw
    n_bands=None,           # Bands for GW (auto if None)
)
```

**GW Protocols:**

| Protocol | Description | Cost |
|----------|-------------|------|
| `g0w0` | Single-shot G0W0 | Lowest |
| `gw0` | Partially self-consistent | Moderate |
| `evgw` | Eigenvalue self-consistent | Highest |

#### with_bse() - BSE Optical

```python
builder.with_bse(
    code="yambo",
    n_valence=4,        # Valence bands to include
    n_conduction=4,     # Conduction bands to include
)
```

### Execution Configuration

#### on_cluster() - Cluster Selection

```python
builder.on_cluster(
    cluster="beefcake2",     # Cluster profile name
    partition=None,          # SLURM partition override
    resources=None,          # Custom ResourceRequirements
)
```

#### with_progress() - Progress Tracking

```python
# Console progress
builder.with_progress()

# Custom callback
builder.with_progress(callback=my_progress_handler)
```

#### with_output() - Output Directory

```python
builder.with_output("./results/NbOCl2")
```

#### with_recovery() - Error Recovery

```python
from crystalmath.protocols import ErrorRecoveryStrategy

builder.with_recovery(ErrorRecoveryStrategy.ADAPTIVE)
```

**Recovery Strategies:**

| Strategy | Behavior |
|----------|----------|
| `FAIL_FAST` | Stop on first error |
| `RETRY` | Retry with same parameters |
| `ADAPTIVE` | Self-healing parameter adjustment |
| `CHECKPOINT` | Restart from last checkpoint |

### Build and Validate

```python
# Validate without building
is_valid, issues = builder.validate()
if not is_valid:
    print("Issues:", issues)

# Build executable workflow
workflow = builder.build()
```

## Workflow Execution

### Synchronous Execution

```python
workflow = builder.build()
result = workflow.run()
```

### Asynchronous Execution (Jupyter)

```python
async for update in workflow.run_async():
    print(f"Step: {update.step_name}")
    print(f"Progress: {update.percent:.1f}%")

    if update.has_intermediate_result:
        # Access partial results for live plotting
        partial = update.intermediate_result
```

### Non-Blocking Submission

```python
# Submit and return immediately
workflow_id = workflow.submit()
print(f"Submitted: {workflow_id}")

# Check status later
from crystalmath.high_level import Workflow

status = Workflow.get_status(workflow_id)
print(f"State: {status.state}")
print(f"Progress: {status.progress_percent}%")

# Get result when complete
if status.state == "completed":
    result = Workflow.get_result(workflow_id)

# Cancel if needed
Workflow.cancel(workflow_id)
```

## AnalysisResults

The `AnalysisResults` class contains all computed properties with export methods.

### Scalar Properties

```python
# Electronic
results.band_gap_ev           # DFT band gap (eV)
results.is_direct_gap         # Direct or indirect
results.fermi_energy_ev       # Fermi energy (eV)
results.is_metal              # Metallic?

# GW/BSE
results.gw_gap_ev             # GW gap (eV)
results.optical_gap_ev        # BSE optical gap (eV)
results.exciton_binding_ev    # Exciton binding (eV)

# Mechanical
results.bulk_modulus_gpa      # Bulk modulus (GPa)
results.shear_modulus_gpa     # Shear modulus (GPa)
results.youngs_modulus_gpa    # Young's modulus (GPa)
results.poisson_ratio         # Poisson ratio

# Dielectric
results.static_dielectric     # Static dielectric constant
results.high_freq_dielectric  # High-freq dielectric constant

# Phonon
results.has_imaginary_modes   # Dynamically stable?

# Transport
results.seebeck_coefficient
results.electrical_conductivity
results.thermal_conductivity
```

### Data Containers

```python
# Band structure data
results.band_structure.energies     # [n_kpoints, n_bands]
results.band_structure.kpoints      # [n_kpoints, 3]
results.band_structure.kpoint_labels
results.band_structure.fermi_energy

# DOS data
results.dos.energies
results.dos.total_dos
results.dos.projected_dos

# Phonon data
results.phonon_dispersion.frequencies
results.phonon_dispersion.qpoints

# Elastic tensor
results.elastic_tensor.voigt        # [6, 6] GPa
results.elastic_tensor.compliance
```

### Export Methods

#### DataFrame Export

```python
# Single-row DataFrame with all scalar properties
df = results.to_dataframe()
df.to_csv("properties.csv", index=False)

# Combine multiple materials
all_results = []
for material in materials:
    result = HighThroughput.run_standard_analysis(material, ["bands"])
    all_results.append(result.to_dataframe())

combined = pd.concat(all_results, ignore_index=True)
combined.to_csv("screening.csv")
```

#### Dictionary Export

```python
# Nested dictionary including arrays
data = results.to_dict()

# JSON export
json_str = results.to_json()
results.to_json("results.json")
```

#### LaTeX Export

```python
# Standard booktabs table
latex = results.to_latex_table()

# Write to file
results.to_latex_table("table.tex")

# SI-formatted table
latex = results.to_latex_si_table("table_si.tex")
```

**Example LaTeX Output:**

```latex
\begin{table}[htbp]
\centering
\caption{Calculated properties of NbOCl2}
\label{tab:properties}
\begin{tabular}{lS[table-format=3.3]}
\toprule
Property & {Value} \\
\midrule
Band gap (DFT) & \SI{1.234}{\electronvolt} \\
Band gap (GW) & \SI{2.567}{\electronvolt} \\
Optical gap (BSE) & \SI{2.123}{\electronvolt} \\
Exciton binding & \SI{0.444}{\electronvolt} \\
\bottomrule
\end{tabular}
\end{table}
```

### Plotting Methods

#### Static Plots (Matplotlib)

```python
# Band structure
fig = results.plot_bands(color="blue", linewidth=1.0)
fig.savefig("bands.png", dpi=300)

# Density of states
fig = results.plot_dos(projected=True)
fig.savefig("dos.png", dpi=300)

# Combined band structure + DOS
fig = results.plot_bands_dos(figsize=(10, 6))
fig.savefig("electronic_structure.png", dpi=300)

# Phonon dispersion
fig = results.plot_phonons()
fig.savefig("phonons.png", dpi=300)

# Optical absorption
fig = results.plot_optical(component="xx")
fig.savefig("optical.png", dpi=300)
```

#### Interactive Plots (Plotly)

```python
# Interactive band structure (Jupyter)
fig = results.iplot_bands()
fig.show()

# Interactive DOS
fig = results.iplot_dos()
fig.show()
```

## Protocol Levels

Protocol levels control calculation accuracy throughout the workflow:

```python
results = HighThroughput.run_standard_analysis(
    structure="struct.cif",
    properties=["bands"],
    protocol="precise"   # fast, moderate, precise
)
```

### Protocol Parameters

| Parameter | Fast | Moderate | Precise |
|-----------|------|----------|---------|
| k-density | 0.08 /A | 0.04 /A | 0.02 /A |
| Energy conv. | 10^-4 eV | 10^-5 eV | 10^-6 eV |
| Force conv. | 0.05 eV/A | 0.01 eV/A | 0.001 eV/A |

## Progress Tracking

### Console Progress

```python
builder.with_progress()  # Uses ConsoleProgressCallback
```

### Custom Progress Handler

```python
from crystalmath.protocols import ProgressCallback

class MyProgressHandler(ProgressCallback):
    def on_started(self, workflow_id, workflow_type):
        print(f"Started: {workflow_id}")

    def on_progress(self, workflow_id, step, percent, message):
        print(f"[{percent:.0f}%] {step}: {message}")

    def on_completed(self, workflow_id, result):
        print(f"Completed: {workflow_id}")

    def on_failed(self, workflow_id, error, recoverable):
        print(f"Failed: {error}")

builder.with_progress(callback=MyProgressHandler())
```

### Jupyter Widget Progress

```python
from crystalmath.high_level.progress import JupyterProgressCallback

builder.with_progress(callback=JupyterProgressCallback())
```

## Complete Example

```python
from crystalmath.high_level import HighThroughput, WorkflowBuilder
from crystalmath.protocols import ErrorRecoveryStrategy

# Option 1: One-liner with HighThroughput
results = HighThroughput.run_standard_analysis(
    structure="NbOCl2.cif",
    properties=["relax", "bands", "dos", "gw", "bse"],
    codes={"dft": "vasp", "gw": "yambo"},
    cluster="beefcake2",
    protocol="moderate"
)

# Option 2: Fine-grained control with WorkflowBuilder
workflow = (
    WorkflowBuilder()
    .from_file("NbOCl2.cif")
    .relax(code="vasp", force_threshold=0.005)
    .then_bands(kpath="auto", kpoints_per_segment=100)
    .then_dos(mesh=[16, 16, 16], projected=True)
    .with_gw(code="yambo", protocol="gw0", n_bands=100)
    .with_bse(n_valence=6, n_conduction=6)
    .on_cluster("beefcake2", partition="gpu")
    .with_progress()
    .with_output("./results/NbOCl2")
    .with_recovery(ErrorRecoveryStrategy.ADAPTIVE)
    .build()
)

results = workflow.run()

# Access results
print(f"Formula: {results.formula}")
print(f"DFT gap: {results.band_gap_ev:.3f} eV")
print(f"GW gap: {results.gw_gap_ev:.3f} eV")
print(f"Optical gap: {results.optical_gap_ev:.3f} eV")
print(f"Exciton binding: {results.exciton_binding_ev:.3f} eV")

# Export
results.to_dataframe().to_csv("properties.csv")
results.to_latex_table("table.tex")

# Plot
fig = results.plot_bands_dos()
fig.savefig("electronic_structure.png", dpi=300)
```
