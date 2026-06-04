# CrystalMath

Domain language for managing **multi-code DFT calculations** (CRYSTAL23, VASP, Quantum
ESPRESSO, YAMBO, phonopy) from structure to results. This glossary is the source of truth for
terminology; code, issues, and docs should use these words and avoid the listed synonyms.

> Created lazily during a `/improve-codebase-architecture` grilling of the SLURM-runner deepening
> (candidate 1: extract a deep input-deck generator). Extend it as terms get resolved.

## Language

### Calculations

**DFT code**:
A simulation engine that runs one calculation — CRYSTAL23, VASP, Quantum ESPRESSO, or YAMBO.
_Avoid_: backend, engine (for the simulator), solver.

**Input deck**:
The complete set of code-specific input files for one calculation (e.g. INCAR/POSCAR/KPOINTS/POTCAR
for VASP; the `.d12` for CRYSTAL23). Singular even though it is several files.
_Avoid_: input files, input set, job inputs.

**Workflow type**:
The kind of calculation requested — `relax`, `scf`, `bands`, `dos`, `gw`, `bse`, `phonon`, etc. It
determines deck keywords (e.g. `relax` → CRYSTAL `OPTGEOM`) and how steps chain.
_Avoid_: calculation type, mode, task.

### Input-deck generation (deepened in this review)

**InputDeck**:
The value object returned by deck generation — the deck's file *contents* as strings, plus the
POTCAR *symbols* (not the POTCAR file itself), plus metadata. Pure data; carries no I/O. Staging
turns it into files on disk.
_Avoid_: input bundle, deck files, generated inputs.

**CodeDeckGenerator**:
The per-DFT-code seam: an adapter that maps `(structure, workflow type, parameters)` → an
`InputDeck`. One adapter per code (Vasp/Crystal/Qe/Yambo), looked up by DFT code in a registry.
The existing `vasp/generator.py` and the vendored `crystal_d12` become adapters behind it.
_Avoid_: deck builder, input generator (too generic), code handler.

**Stage / staging**:
Writing an `InputDeck` to a work directory and assembling the POTCAR from the pseudopotential
library (`VASP_PP_PATH`). The only I/O step; it fails fast when pseudopotentials are missing.
_Avoid_: materialize, write inputs, prepare.
