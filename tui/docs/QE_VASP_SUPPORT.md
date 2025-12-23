# Quantum Espresso and VASP Support

This document describes the multi-code DFT support added to Crystal-TUI, enabling calculations with Quantum Espresso (QE) and VASP in addition to CRYSTAL23.

## Overview

Crystal-TUI now supports three DFT codes:

| Code | Input Style | Energy Unit | Parser |
|------|-------------|-------------|--------|
| CRYSTAL | `.d12` to stdin | Hartree | `CRYSTALParser` |
| Quantum Espresso | `.in` file via flag | Rydberg | `QEParser` |
| VASP | Multi-file (POSCAR, INCAR, KPOINTS, POTCAR) | eV | `VASPParser` |

## Architecture

### DFT Code Registry

All supported codes are defined in `src/core/codes/base.py`:

```python
from src.core.codes import DFTCode, get_config

# Available codes
DFTCode.CRYSTAL
DFTCode.QUANTUM_ESPRESSO
DFTCode.VASP

# Get configuration for a code
config = get_config(DFTCode.VASP)
```

### Configuration Structure

Each code has a `DFTCodeConfig` with:

- `name`: Human-readable name
- `executables`: List of possible executable names
- `input_extensions`: Valid input file extensions
- `output_extension`: Default output file extension
- `energy_unit`: Energy unit (Hartree, Rydberg, or eV)
- `convergence_patterns`: Regex patterns for success/failure detection
- `invocation_style`: How to invoke the executable
- `auxiliary_inputs`: Additional input files (VASP only)
- `auxiliary_outputs`: Output files to preserve

### Invocation Styles

```python
class InvocationStyle(Enum):
    STDIN = "stdin"   # CRYSTAL: crystal < input.d12 > output.out
    FLAG = "flag"     # QE: pw.x -i input.in > output.out
    CWD = "cwd"       # VASP: vasp (reads files from current directory)
```

## Quantum Espresso Support

### Configuration

Located in `src/core/codes/qe.py`:

```python
QE_CONFIG = DFTCodeConfig(
    name="Quantum Espresso",
    executables=["pw.x", "pw.x-serial", "mpirun pw.x"],
    input_extensions=[".in", ".pwi"],
    output_extension=".out",
    energy_unit="Ry",
    convergence_patterns={
        "success": [r"JOB DONE", r"convergence has been achieved"],
        "failure": [r"Error", r"NOT CONVERGED"],
    },
    invocation_style=InvocationStyle.FLAG,
)
```

### Parser

The `QEParser` (`src/core/codes/parsers/qe.py`) extracts:

- **Final energy**: Total energy in Rydberg
- **SCF cycles**: Number of iterations to convergence
- **Geometry convergence**: For relaxation calculations
- **Errors/warnings**: From output file

```python
from src.core.codes.parsers import get_parser, DFTCode

parser = get_parser(DFTCode.QUANTUM_ESPRESSO)
result = await parser.parse(Path("pwscf.out"))

print(f"Energy: {result.final_energy} {result.energy_unit}")
print(f"Converged: {result.convergence_status}")
```

### Templates

**SCF Template** (`templates/qe/scf.yml`):
- Basic SCF calculation
- Parameters: ecutwfc, k-points, smearing, convergence threshold

**Relaxation Template** (`templates/qe/relax.yml`):
- Geometry optimization (relax or vc-relax)
- Additional parameters: forc_conv_thr, ion_dynamics, cell_dynamics

## VASP Support

### Configuration

Located in `src/core/codes/vasp.py`:

```python
VASP_CONFIG = DFTCodeConfig(
    name="VASP",
    executables=["vasp_std", "vasp_gam", "vasp_ncl"],
    input_extensions=[".vasp", ".poscar"],
    output_extension="OUTCAR",
    energy_unit="eV",
    convergence_patterns={
        "success": [r"reached required accuracy", r"LOOP\+"],
        "failure": [r"Error", r"ZBRENT"],
    },
    invocation_style=InvocationStyle.CWD,
    auxiliary_inputs={
        "POSCAR": "structure",
        "INCAR": "parameters",
        "KPOINTS": "k-points",
        "POTCAR": "pseudopotentials",
        "WAVECAR": "wavefunction (optional)",
        "CHGCAR": "charge density (optional)",
    },
    auxiliary_outputs={
        "OUTCAR": "main output",
        "CONTCAR": "final structure",
        "OSZICAR": "convergence history",
        "WAVECAR": "wavefunction",
        "CHGCAR": "charge density",
        "vasprun.xml": "XML output",
    },
)
```

### Multi-File Input Handling

VASP requires multiple input files. The `VASPInputFiles` class manages this:

```python
from src.core.codes.vasp import VASPInputFiles

# Create from content
vasp_inputs = VASPInputFiles(
    poscar="Si\n1.0\n5.43 0.0 0.0\n...",
    incar="SYSTEM = Si\nENCUT = 400\n...",
    kpoints="Automatic mesh\n0\nGamma\n8 8 8\n...",
    potcar="PAW_PBE Si 05Jan2001\n...",
)

# Validate inputs
errors = vasp_inputs.validate()
if errors:
    raise ValueError(f"Invalid VASP inputs: {errors}")

# Write to directory
written_files = vasp_inputs.write_to_directory(work_dir)

# Load from existing directory
vasp_inputs = VASPInputFiles.from_directory(existing_dir)
```

### File Staging Helpers

```python
from src.core.codes.vasp import (
    get_vasp_files_to_stage,
    get_vasp_output_patterns,
    VASP_REQUIRED_FILES,
    VASP_OPTIONAL_INPUTS,
    VASP_OUTPUT_FILES,
)

# Get list of files to stage for a calculation
files = get_vasp_files_to_stage(work_dir)

# Get glob patterns for output collection
patterns = get_vasp_output_patterns()
```

### Parser

The `VASPParser` (`src/core/codes/parsers/vasp.py`) extracts:

- **Final energy**: TOTEN or energy without entropy
- **SCF cycles**: Electronic iterations
- **Geometry convergence**: For IBRION calculations
- **RMS force**: For optimization monitoring
- **Errors/warnings**: Including "VERY BAD NEWS" detection

```python
from src.core.codes.parsers import get_parser, DFTCode

parser = get_parser(DFTCode.VASP)

# Parse from OUTCAR file
result = await parser.parse(Path("OUTCAR"))

# Or from directory containing OUTCAR
result = await parser.parse(Path("/path/to/vasp/calculation/"))
```

### Templates

**SCF Template** (`templates/vasp/scf.yml`):
- Single-point energy calculation
- Generates INCAR, KPOINTS, POSCAR content
- Parameters: PREC, ENCUT, ISMEAR, SIGMA, EDIFF, etc.

**Relaxation Template** (`templates/vasp/relax.yml`):
- Geometry optimization
- Additional parameters: IBRION, ISIF, NSW, EDIFFG, POTIM

## Workflow Chains

Multi-step workflows are supported through the workflow template system.

### QE Relaxation + SCF Workflow

`templates/workflows/qe_relax_scf.yml`:

```yaml
workflow:
  nodes:
    - id: "relax"
      type: "calculation"
      template: "qe/relax"
      parameters:
        calculation: "vc-relax"
        # ... relaxation parameters

    - id: "transfer_structure"
      type: "data_transfer"
      source_node: "relax"
      source_files: ["*.xml"]
      target_node: "scf"

    - id: "scf"
      type: "calculation"
      template: "qe/scf"
      parameters:
        calculation: "scf"
        atomic_positions: "{{ relax.final_positions }}"
        # ... SCF parameters

  edges:
    - from: "relax"
      to: "transfer_structure"
    - from: "transfer_structure"
      to: "scf"
```

### VASP Relaxation + SCF Workflow

`templates/workflows/vasp_relax_scf.yml`:

```yaml
workflow:
  nodes:
    - id: "relax"
      type: "calculation"
      template: "vasp/relax"
      parameters:
        system: "{{ system }} - Relaxation"
        # ... relaxation parameters
        lwave: false
        lcharg: false

    - id: "transfer_structure"
      type: "data_transfer"
      source_node: "relax"
      source_files: ["CONTCAR", "POTCAR"]
      target_node: "scf"
      file_renames:
        "CONTCAR": "POSCAR"

    - id: "scf"
      type: "calculation"
      template: "vasp/scf"
      parameters:
        system: "{{ system }} - Final SCF"
        ismear: "-5"  # Tetrahedron for final energy
        lwave: true
        lcharg: true

  edges:
    - from: "relax"
      to: "transfer_structure"
    - from: "transfer_structure"
      to: "scf"

  conditions:
    - id: "check_convergence"
      after: "relax"
      expression: "relax.geometry_converged == True"
      true_branch: ["transfer_structure", "scf"]
      false_branch: []
```

## Energy Unit Conversion

When comparing energies across codes, use consistent units:

| From | To | Multiply by |
|------|-----|-------------|
| Hartree | eV | 27.2114 |
| Rydberg | eV | 13.6057 |
| Hartree | Rydberg | 2.0 |

## Testing

The test suite includes comprehensive tests for QE/VASP support:

```bash
# Run QE/VASP specific tests
pytest tests/test_codes_qe_vasp.py -v

# Run all tests
pytest
```

Test coverage includes:
- Parser accuracy (energy extraction, convergence detection)
- Error and warning handling
- VASP multi-file validation and I/O
- Template rendering
- Workflow chain execution

## Known Limitations

1. **VASP POTCAR**: Users must provide their own POTCAR files (license required)
2. **Parallel execution**: MPI settings are code-specific and may need manual configuration
3. **Output parsing**: Complex outputs (MD, NEB) may require custom parsing

## Future Enhancements

### AiiDA Parser Migration

When AiiDA integration is active (Phase 3), Crystal-TUI will transition to using production-tested AiiDA plugin parsers:

| Code | AiiDA Plugin | Parser Class |
|------|--------------|--------------|
| Quantum Espresso | `aiida-quantumespresso` | `PwParser` |
| VASP | `aiida-vasp` | `VaspParser` |
| CRYSTAL | `aiida-crystal17` | `CrystalParser` |

Benefits of AiiDA parsers:
- Production-tested with comprehensive error handling
- Full support for all output formats and calculation types
- Automatic data provenance tracking
- Active maintenance by the AiiDA community

The custom parsers implemented here serve as fallbacks when AiiDA is not available.

Related issues:
- `crystalmath-wco`: Migrate to AiiDA QE parsers
- `crystalmath-dpd`: Migrate to AiiDA VASP parsers
- `crystalmath-6fy`: Migrate to AiiDA CRYSTAL parsers

### Other Enhancements

- Additional codes (SIESTA, CP2K, ABINIT)
- Automatic POTCAR generation from PAW library
- Advanced workflow features (error recovery, checkpointing)
- Band structure and DOS analysis integration
