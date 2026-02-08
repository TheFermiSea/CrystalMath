# VASP Input Generation Reference

The VASP module provides tools for generating complete VASP input file sets (POSCAR, INCAR, KPOINTS) with sensible defaults and Materials Project integration.

## Import

```python
from crystalmath.vasp.generator import VaspInputGenerator, VaspInputs, generate_vasp_inputs_from_mp
from crystalmath.vasp.incar import IncarBuilder, IncarPreset
from crystalmath.vasp.kpoints import KpointsBuilder, KpointsMesh
```

## VaspInputGenerator

High-level generator for complete VASP input sets.

### Constructor

```python
VaspInputGenerator(
    structure: Structure,
    preset: IncarPreset = IncarPreset.STATIC,
    encut: Optional[float] = None,
    kppra: int = 1000,
    kpoints_mesh: Optional[KpointsMesh] = None,
    **incar_overrides,
)
```

**Parameters:**
- `structure` - pymatgen Structure object
- `preset` - INCAR preset configuration (RELAX, STATIC, BANDS, DOS, CONVERGENCE)
- `encut` - Plane-wave cutoff energy (eV). If None, estimated from elements
- `kppra` - k-points per reciprocal atom (default: 1000)
- `kpoints_mesh` - Explicit k-point mesh (overrides kppra)
- `**incar_overrides` - Additional INCAR parameters to override

**Example:**

```python
from pymatgen.core import Structure
from crystalmath.vasp.generator import VaspInputGenerator
from crystalmath.vasp.incar import IncarPreset

# Load structure
structure = Structure.from_file("POSCAR")

# Generate inputs
generator = VaspInputGenerator(
    structure,
    preset=IncarPreset.RELAX,
    encut=520.0,
    kppra=2000,
    # Additional INCAR overrides
    ncore=4,
    ediffg=-0.005,
)

inputs = generator.generate()

# Write to files
Path("POSCAR").write_text(inputs.poscar)
Path("INCAR").write_text(inputs.incar)
Path("KPOINTS").write_text(inputs.kpoints)

print(f"POTCAR symbols: {inputs.potcar_symbols}")
```

### generate

```python
generate() -> VaspInputs
```

Generate complete VASP input file set.

**Returns:** `VaspInputs` dataclass with poscar, incar, kpoints, and potcar_symbols

## VaspInputs Dataclass

Complete VASP input file set.

**Fields:**
- `poscar` (str) - POSCAR file content (atomic structure)
- `incar` (str) - INCAR file content (calculation parameters)
- `kpoints` (str) - KPOINTS file content (k-point mesh)
- `potcar_symbols` (List[str]) - Element symbols for POTCAR (user must provide actual files)

**Example:**

```python
inputs = generator.generate()

# Access individual files
print("=== POSCAR ===")
print(inputs.poscar)

print("\n=== INCAR ===")
print(inputs.incar)

print("\n=== KPOINTS ===")
print(inputs.kpoints)

print(f"\nRequired POTCAR files: {inputs.potcar_symbols}")
# e.g., ['Mg_pv', 'O']
```

## IncarPreset Enum

Standard INCAR preset configurations.

**Values:**

| Preset | Description | Use Case |
|--------|-------------|----------|
| `RELAX` | Geometry optimization | Structure relaxation (ions only) |
| `STATIC` | Single-point energy | Static energy calculation |
| `BANDS` | Band structure | Non-SCF band structure (after SCF) |
| `DOS` | Density of states | DOS calculation with denser k-mesh |
| `CONVERGENCE` | Convergence testing | Testing cutoff/k-point convergence |

**Preset Configurations:**

```python
# RELAX - Geometry optimization
RELAX:
  ibrion: 2        # Conjugate gradient
  isif: 2          # Ions only (cell fixed)
  nsw: 100         # Max ionic steps
  ediffg: -0.01    # Force convergence (eV/Å)

# STATIC - Single point
STATIC:
  ibrion: -1       # No ionic motion
  nsw: 0           # No ionic steps

# BANDS - Band structure
BANDS:
  ibrion: -1
  icharg: 11       # Read CHGCAR (non-SCF)
  lorbit: 11       # Projected DOS

# DOS - Density of states
DOS:
  ibrion: -1
  ismear: -5       # Tetrahedron method
  lorbit: 11

# CONVERGENCE - Testing
CONVERGENCE:
  ibrion: -1
  ediff: 1e-7      # Tight convergence
```

**Example:**

```python
from crystalmath.vasp.incar import IncarPreset

# Use preset
generator = VaspInputGenerator(
    structure,
    preset=IncarPreset.RELAX,
)

# Override preset values
generator = VaspInputGenerator(
    structure,
    preset=IncarPreset.RELAX,
    nsw=200,          # Override max ionic steps
    ediffg=-0.005,    # Tighter force convergence
)
```

## IncarBuilder

Low-level INCAR file builder with fine-grained control.

### from_preset

```python
IncarBuilder.from_preset(
    preset: IncarPreset,
    **overrides
) -> IncarBuilder
```

Create builder from preset configuration.

**Parameters:**
- `preset` - Standard calculation preset
- `**overrides` - Parameters to override from preset defaults

**Returns:** Configured `IncarBuilder` instance

**Example:**

```python
from crystalmath.vasp.incar import IncarBuilder, IncarPreset

# Create from preset
builder = IncarBuilder.from_preset(
    IncarPreset.RELAX,
    encut=520,
    ncore=4,
)

# Generate INCAR content
incar_str = builder.to_string()
print(incar_str)
```

### to_string

```python
to_string() -> str
```

Generate INCAR file content as string.

**Returns:** Formatted INCAR file content

### Attributes

All INCAR parameters are exposed as attributes:

**Electronic Convergence:**
- `encut` (float) - Plane-wave cutoff energy (eV)
- `ediff` (float) - SCF energy convergence (eV, default: 1e-5)
- `nelm` (int) - Maximum SCF iterations (default: 100)

**Smearing:**
- `ismear` (int) - Smearing method (0=Gaussian, 1=Methfessel-Paxton, -5=tetrahedron)
- `sigma` (float) - Smearing width (eV, default: 0.05)

**Ionic Relaxation:**
- `ibrion` (int) - Algorithm (-1=static, 2=CG, 1=quasi-Newton)
- `isif` (int) - Stress tensor (2=ions only, 3=ions+cell)
- `nsw` (int) - Maximum ionic steps (0=static)
- `ediffg` (float) - Ionic convergence (negative=force in eV/Å)

**I/O:**
- `lwave` (bool) - Write WAVECAR (default: True)
- `lcharg` (bool) - Write CHGCAR (default: True)

**Parallelization:**
- `ncore` (int) - Cores per orbital (default: 4)

**Extra Parameters:**
- `extra` (dict) - Additional INCAR parameters

**Example:**

```python
builder = IncarBuilder.from_preset(IncarPreset.STATIC)
builder.encut = 600.0
builder.ismear = -5  # Tetrahedron method
builder.extra = {"ALGO": "Normal", "PREC": "Accurate"}

incar = builder.to_string()
```

## KpointsBuilder

K-point mesh generation with automatic density calculation.

### from_density

```python
KpointsBuilder.from_density(
    structure: Structure,
    kppra: int = 1000
) -> KpointsMesh
```

Generate mesh from k-point density.

Uses k-points per reciprocal atom (KPPRA) to determine appropriate mesh density.

**Parameters:**
- `structure` - pymatgen Structure object
- `kppra` - k-points per reciprocal atom
  - 500: Fast/coarse
  - 1000: Standard (default)
  - 2000+: Accurate/dense

**Returns:** `KpointsMesh` with appropriate density

**Example:**

```python
from crystalmath.vasp.kpoints import KpointsBuilder

# Generate mesh from density
mesh = KpointsBuilder.from_density(structure, kppra=2000)
print(f"K-point mesh: {mesh.mesh}")  # e.g., (8, 8, 8)
kpoints_str = mesh.to_string()
```

### gamma_centered

```python
KpointsBuilder.gamma_centered(ka: int, kb: int, kc: int) -> KpointsMesh
```

Create Gamma-centered mesh with explicit dimensions.

**Parameters:**
- `ka` - k-points along a* direction
- `kb` - k-points along b* direction
- `kc` - k-points along c* direction

**Returns:** Gamma-centered `KpointsMesh`

**Example:**

```python
# Explicit mesh
mesh = KpointsBuilder.gamma_centered(6, 6, 6)
print(mesh.to_string())
```

### monkhorst_pack

```python
KpointsBuilder.monkhorst_pack(ka: int, kb: int, kc: int) -> KpointsMesh
```

Create shifted Monkhorst-Pack mesh.

Uses standard (0.5, 0.5, 0.5) shift.

**Example:**

```python
mesh = KpointsBuilder.monkhorst_pack(6, 6, 6)
```

### for_slab

```python
KpointsBuilder.for_slab(
    structure: Structure,
    kppra: int = 1000
) -> KpointsMesh
```

Generate mesh appropriate for slab calculations.

Uses only 1 k-point perpendicular to surface (assumes c-axis is surface normal).

**Parameters:**
- `structure` - pymatgen Structure (slab geometry)
- `kppra` - k-points per reciprocal atom for in-plane directions

**Returns:** `KpointsMesh` with 1 k-point in c direction

**Example:**

```python
# Slab calculation (e.g., surface)
mesh = KpointsBuilder.for_slab(slab_structure, kppra=1000)
print(f"Slab mesh: {mesh.mesh}")  # e.g., (8, 8, 1)
```

## KpointsMesh Dataclass

K-point mesh specification.

**Fields:**
- `mesh` (Tuple[int, int, int]) - K-point mesh dimensions
- `shift` (Tuple[float, float, float]) - Mesh shift (default: (0, 0, 0))

**Methods:**
- `to_string() -> str` - Generate KPOINTS file content

**Example:**

```python
from crystalmath.vasp.kpoints import KpointsMesh

mesh = KpointsMesh(mesh=(8, 8, 8), shift=(0.0, 0.0, 0.0))
kpoints_content = mesh.to_string()

print(kpoints_content)
# Output:
# Automatic mesh
# 0
# Gamma
# 8 8 8
# 0.0 0.0 0.0
```

## Materials Project Integration

### generate_vasp_inputs_from_mp

Generate VASP inputs directly from Materials Project ID.

```python
generate_vasp_inputs_from_mp(
    mp_id: str,
    preset: IncarPreset = IncarPreset.STATIC,
    encut: Optional[float] = None,
    kppra: int = 1000,
    **incar_overrides,
) -> VaspInputs
```

**Parameters:**
- `mp_id` - Materials Project ID (e.g., "mp-149")
- `preset` - INCAR preset configuration
- `encut` - Plane-wave cutoff (eV). If None, estimated from elements
- `kppra` - k-points per reciprocal atom
- `**incar_overrides` - Additional INCAR parameters

**Returns:** `VaspInputs` with generated files

**Requirements:** Requires Materials Project API key set in environment:

```bash
export MP_API_KEY="your_api_key_here"
```

**Example:**

```python
from crystalmath.vasp.generator import generate_vasp_inputs_from_mp
from crystalmath.vasp.incar import IncarPreset

# Generate inputs from Materials Project
inputs = generate_vasp_inputs_from_mp(
    "mp-1265",  # MgO
    preset=IncarPreset.RELAX,
    kppra=2000,
    ncore=8,
)

# Write to files
Path("POSCAR").write_text(inputs.poscar)
Path("INCAR").write_text(inputs.incar)
Path("KPOINTS").write_text(inputs.kpoints)

print(f"Structure: {inputs.poscar.split()[0]}")
print(f"POTCAR symbols: {inputs.potcar_symbols}")
```

## Complete Examples

### Example 1: Standard Relaxation

```python
from pymatgen.core import Structure
from crystalmath.vasp.generator import VaspInputGenerator
from crystalmath.vasp.incar import IncarPreset
from pathlib import Path

# Load structure
structure = Structure.from_file("initial.cif")

# Generate inputs for geometry optimization
generator = VaspInputGenerator(
    structure,
    preset=IncarPreset.RELAX,
    encut=520.0,
    kppra=1000,
    ncore=4,
)

inputs = generator.generate()

# Write files
Path("POSCAR").write_text(inputs.poscar)
Path("INCAR").write_text(inputs.incar)
Path("KPOINTS").write_text(inputs.kpoints)

print(f"Generated VASP inputs for {structure.composition.reduced_formula}")
print(f"K-point mesh: {inputs.kpoints.split()[4]}")  # Extract mesh line
```

### Example 2: Band Structure Workflow

```python
from crystalmath.vasp.generator import VaspInputGenerator
from crystalmath.vasp.incar import IncarPreset

# Step 1: SCF calculation
scf_gen = VaspInputGenerator(
    structure,
    preset=IncarPreset.STATIC,
    encut=520,
    kppra=2000,
)
scf_inputs = scf_gen.generate()

# Write SCF inputs to scf/ directory
Path("scf/POSCAR").write_text(scf_inputs.poscar)
Path("scf/INCAR").write_text(scf_inputs.incar)
Path("scf/KPOINTS").write_text(scf_inputs.kpoints)

# Step 2: Band structure (non-SCF)
bands_gen = VaspInputGenerator(
    structure,
    preset=IncarPreset.BANDS,
    encut=520,
    kppra=1000,  # Can use coarser for bands
)
bands_inputs = bands_gen.generate()

# Write bands inputs to bands/ directory
Path("bands/POSCAR").write_text(bands_inputs.poscar)
Path("bands/INCAR").write_text(bands_inputs.incar)
Path("bands/KPOINTS").write_text(bands_inputs.kpoints)

print("Workflow:")
print("1. Run SCF in scf/ directory")
print("2. Copy CHGCAR to bands/ directory")
print("3. Run bands in bands/ directory")
```

### Example 3: Materials Project Integration

```python
from crystalmath.vasp.generator import generate_vasp_inputs_from_mp
from crystalmath.vasp.incar import IncarPreset

# Search Materials Project and generate inputs
mp_ids = ["mp-149", "mp-1265", "mp-66"]  # GaN, MgO, Si

for mp_id in mp_ids:
    inputs = generate_vasp_inputs_from_mp(
        mp_id,
        preset=IncarPreset.RELAX,
        kppra=2000,
        ncore=8,
    )

    # Create directory for each material
    outdir = Path(mp_id)
    outdir.mkdir(exist_ok=True)

    # Write inputs
    (outdir / "POSCAR").write_text(inputs.poscar)
    (outdir / "INCAR").write_text(inputs.incar)
    (outdir / "KPOINTS").write_text(inputs.kpoints)

    formula = inputs.poscar.split('\n')[0].strip()
    print(f"{mp_id}: {formula}")
    print(f"  POTCAR: {', '.join(inputs.potcar_symbols)}")
```

### Example 4: Custom INCAR Parameters

```python
from crystalmath.vasp.incar import IncarBuilder, IncarPreset

# Fine-grained INCAR control
builder = IncarBuilder.from_preset(IncarPreset.RELAX)

# Electronic parameters
builder.encut = 600.0
builder.ediff = 1e-7  # Tight convergence
builder.ismear = -5   # Tetrahedron
builder.nelm = 200

# Ionic parameters
builder.nsw = 200
builder.ediffg = -0.005  # 5 meV/Å force convergence

# Parallelization
builder.ncore = 8

# Additional parameters
builder.extra = {
    "ALGO": "Fast",
    "PREC": "Accurate",
    "LASPH": True,
    "GGA": "PS",  # PBEsol
}

incar = builder.to_string()
Path("INCAR").write_text(incar)
```

### Example 5: Slab Calculation

```python
from pymatgen.core.surface import SlabGenerator
from crystalmath.vasp.generator import VaspInputGenerator
from crystalmath.vasp.kpoints import KpointsBuilder
from crystalmath.vasp.incar import IncarPreset

# Generate slab from bulk structure
slab_gen = SlabGenerator(bulk_structure, miller_index=(1, 1, 1), min_slab_size=10, min_vacuum_size=15)
slab = slab_gen.get_slab()

# Generate inputs with slab-appropriate k-points
kpoints = KpointsBuilder.for_slab(slab, kppra=1000)

generator = VaspInputGenerator(
    slab,
    preset=IncarPreset.RELAX,
    encut=520,
    kpoints_mesh=kpoints,  # Explicit slab k-points
    isif=2,  # Relax ions only (not cell)
)

inputs = generator.generate()
print(f"Slab k-points: {kpoints.mesh}")  # e.g., (8, 8, 1)
```

## Integration with CrystalMath API

VASP input generation is available through the Python API:

```python
from crystalmath.api import CrystalController

ctrl = CrystalController()

# Generate VASP inputs via JSON API
config_json = '''
{
  "structure": {
    "formula": "MgO",
    "lattice_a": 4.211,
    "lattice_b": 4.211,
    "lattice_c": 4.211,
    "atoms": [...]
  },
  "preset": "relax",
  "encut": 520,
  "kppra": 2000
}
'''

response = ctrl.generate_vasp_inputs_json(config_json)
inputs = json.loads(response)

print(inputs["poscar"])
print(inputs["incar"])
print(inputs["kpoints"])
```

## See Also

- [API Reference](api.md) - CrystalController methods
- [Models Reference](models.md) - Data structures
- [Templates](templates.md) - VASP templates
