# Getting Started with CrystalMath

This guide will help you install CrystalMath and run your first materials analysis workflow in under 5 minutes.

## Prerequisites

- **Python 3.10+** - CrystalMath requires Python 3.10 or later
- **pip or uv** - Package manager for installation
- **pymatgen** - Required for structure handling (installed automatically)

### Optional Dependencies

Depending on your use case, you may also want:

- **AiiDA** - For provenance-tracked workflow execution
- **atomate2/jobflow** - For atomate2 workflow integration
- **mp-api** - For Materials Project structure fetching
- **matplotlib/plotly** - For visualization

## Installation

### Using pip (recommended)

```bash
# Basic installation
pip install crystalmath

# With VASP support
pip install crystalmath[vasp]

# With Quantum ESPRESSO support
pip install crystalmath[qe]

# Full installation with all optional dependencies
pip install crystalmath[all]
```

### Using uv (faster)

```bash
# Basic installation
uv pip install crystalmath

# With all features
uv pip install crystalmath[all]
```

### From Source (development)

```bash
git clone https://github.com/your-org/crystalmath.git
cd crystalmath
pip install -e ".[dev]"
```

## Quick Start Example

Here is a complete example that loads a structure and calculates its electronic properties:

```python
from crystalmath.high_level import HighThroughput

# One-liner analysis from a CIF file
results = HighThroughput.run_standard_analysis(
    structure="NbOCl2.cif",
    properties=["bands", "dos"],
    codes={"dft": "vasp"},
    cluster="beefcake2"
)

# Access computed properties
print(f"Band gap: {results.band_gap_ev:.2f} eV")
print(f"Direct gap: {results.is_direct_gap}")
print(f"Metal: {results.is_metal}")

# Export to CSV
results.to_dataframe().to_csv("results.csv")

# Generate publication-quality plot
fig = results.plot_bands_dos()
fig.savefig("electronic_structure.png", dpi=300)
```

## Your First Workflow in 5 Minutes

### Step 1: Import the Module

```python
from crystalmath.high_level import HighThroughput, WorkflowBuilder
```

### Step 2: Load a Structure

CrystalMath supports multiple structure input formats:

```python
# From a local file (CIF, POSCAR, XYZ, etc.)
results = HighThroughput.run_standard_analysis(
    structure="my_structure.cif",
    properties=["scf"]
)

# From Materials Project
results = HighThroughput.from_mp(
    "mp-149",  # Silicon
    properties=["bands", "dos"]
)

# From a POSCAR file
results = HighThroughput.from_poscar(
    "POSCAR",
    properties=["relax", "bands"]
)

# From a pymatgen Structure object
from pymatgen.core import Structure
struct = Structure.from_file("POSCAR")
results = HighThroughput.from_structure(struct, properties=["scf"])
```

### Step 3: Choose Properties to Calculate

Available properties include:

| Property | Description | Default Code |
|----------|-------------|--------------|
| `scf` | Self-consistent field (single point) | VASP |
| `relax` | Geometry optimization | VASP |
| `bands` | Band structure | VASP |
| `dos` | Density of states | VASP |
| `phonon` | Phonon dispersion | VASP |
| `elastic` | Elastic constants | VASP |
| `dielectric` | Dielectric tensor | VASP |
| `gw` | GW quasiparticle corrections | YAMBO |
| `bse` | BSE optical properties | YAMBO |

### Step 4: Run the Workflow

```python
# Simple calculation
results = HighThroughput.run_standard_analysis(
    structure="Si.cif",
    properties=["relax", "bands", "dos"],
    protocol="moderate"
)
```

### Step 5: Access and Export Results

```python
# Scalar properties
print(f"Formula: {results.formula}")
print(f"Band gap: {results.band_gap_ev:.3f} eV")
print(f"Space group: {results.space_group}")

# Export to various formats
df = results.to_dataframe()           # pandas DataFrame
json_str = results.to_json()           # JSON string
results.to_json("results.json")        # JSON file
latex = results.to_latex_table()       # LaTeX table

# Plotting
fig = results.plot_bands()             # Band structure
fig = results.plot_dos()               # Density of states
fig = results.plot_bands_dos()         # Combined plot
fig = results.plot_phonons()           # Phonon dispersion

# Interactive plots (Jupyter)
fig = results.iplot_bands()            # Plotly interactive
fig.show()
```

## Protocol Levels

CrystalMath uses protocol levels to control calculation accuracy:

| Protocol | k-density | Energy Convergence | Use Case |
|----------|-----------|-------------------|----------|
| `fast` | 0.08 /A | 10^-4 eV | Quick screening |
| `moderate` | 0.04 /A | 10^-5 eV | Production (default) |
| `precise` | 0.02 /A | 10^-6 eV | Publication quality |

```python
# Fast screening
results = HighThroughput.run_standard_analysis(
    structure="struct.cif",
    properties=["bands"],
    protocol="fast"
)

# Publication quality
results = HighThroughput.run_standard_analysis(
    structure="struct.cif",
    properties=["bands"],
    protocol="precise"
)
```

## Cluster Configuration

For HPC execution, specify a cluster profile:

```python
# Run on beefcake2 cluster
results = HighThroughput.run_standard_analysis(
    structure="struct.cif",
    properties=["bands", "dos"],
    cluster="beefcake2"
)

# Local execution (development/testing)
results = HighThroughput.run_standard_analysis(
    structure="struct.cif",
    properties=["scf"],
    cluster="local"
)
```

## Using the Fluent Builder API

For more control over workflow construction, use `WorkflowBuilder`:

```python
from crystalmath.high_level import WorkflowBuilder

workflow = (
    WorkflowBuilder()
    .from_file("NbOCl2.cif")
    .relax(code="vasp", protocol="moderate")
    .then_bands(kpath="auto", kpoints_per_segment=50)
    .then_dos(mesh=[12, 12, 12], projected=True)
    .on_cluster("beefcake2")
    .with_progress()
    .build()
)

result = workflow.run()
```

## Checking Supported Properties

```python
# List all supported properties
properties = HighThroughput.get_supported_properties()
print(properties)
# ['scf', 'relax', 'bands', 'dos', 'phonon', 'elastic', 'dielectric', 'gw', 'bse', 'eos', 'neb']

# Get info about a specific property
info = HighThroughput.get_property_info("gw")
print(info)
# {'name': 'gw', 'workflow_type': 'gw', 'default_code': 'yambo', 'dependencies': ['scf']}
```

## Common Workflows

### Electronic Structure

```python
results = HighThroughput.run_standard_analysis(
    structure="Si.cif",
    properties=["relax", "bands", "dos"],
    protocol="moderate",
    cluster="beefcake2"
)
```

### Optical Properties (GW+BSE)

```python
results = HighThroughput.run_standard_analysis(
    structure="NbOCl2.cif",
    properties=["bands", "gw", "bse"],
    codes={"dft": "vasp", "gw": "yambo"},
    cluster="beefcake2"
)

print(f"DFT gap: {results.band_gap_ev:.2f} eV")
print(f"GW gap: {results.gw_gap_ev:.2f} eV")
print(f"Optical gap: {results.optical_gap_ev:.2f} eV")
print(f"Exciton binding: {results.exciton_binding_ev:.3f} eV")
```

### Mechanical Properties

```python
results = HighThroughput.run_standard_analysis(
    structure="TiO2.cif",
    properties=["relax", "elastic"],
    cluster="beefcake2"
)

print(f"Bulk modulus: {results.bulk_modulus_gpa:.1f} GPa")
print(f"Shear modulus: {results.shear_modulus_gpa:.1f} GPa")
print(f"Young's modulus: {results.youngs_modulus_gpa:.1f} GPa")
```

## Next Steps

- **[High-Level API Guide](high-level-api.md)** - Deep dive into the HighThroughput class and WorkflowBuilder
- **[Cluster Setup](cluster-setup.md)** - Configure the beefcake2 cluster and AiiDA integration
- **[Advanced Workflows](advanced-workflows.md)** - Multi-code workflows and error recovery
- **[atomate2 Integration](atomate2-integration.md)** - Using atomate2 Makers with CrystalMath

## Troubleshooting

### ImportError: No module named 'crystalmath'

Ensure CrystalMath is installed in your active Python environment:

```bash
pip install crystalmath
# or
uv pip install crystalmath
```

### Materials Project API Error

Set your Materials Project API key:

```bash
export MP_API_KEY="your-api-key"
```

Or in Python:

```python
import os
os.environ["MP_API_KEY"] = "your-api-key"
```

### Cluster Connection Failed

Verify SSH connectivity to the cluster:

```bash
ssh ubuntu@10.0.0.10  # For QE nodes
ssh root@10.0.0.20    # For VASP nodes (with password)
```

See [Cluster Setup](cluster-setup.md) for detailed configuration.
