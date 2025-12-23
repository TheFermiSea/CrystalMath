# CrystalMath: Multi-Code DFT Job Management

A unified toolkit for quantum chemistry DFT calculations, supporting **CRYSTAL23**, **Quantum Espresso**, and **VASP**. Combines a production-grade Bash CLI for execution with a modern Python TUI for interactive job management.

## Features

### Multi-Code DFT Support

| Code | Status | Input Style | Energy Unit |
|------|--------|-------------|-------------|
| **CRYSTAL23** | Full Support | `.d12` stdin | Hartree |
| **Quantum Espresso** | Full Support | `.in` flag | Rydberg |
| **VASP** | Full Support | Multi-file (POSCAR, INCAR, KPOINTS, POTCAR) | eV |

### CLI Tool (`cli/`)
- Production-grade modular Bash architecture
- Automatic MPI/OpenMP hybrid parallelism
- Scratch space management with cleanup
- Visual feedback with gum
- Educational `--explain` mode

### TUI Tool (`tui/`)
- Interactive three-panel Textual interface
- Real-time log streaming and job monitoring
- Multiple execution backends (Local, SSH, SLURM)
- Priority-based job queue with dependencies
- Workflow orchestration (DAG-based)
- Template system for input generation
- SQLite database for job history

## Quick Start

### CLI (Execution)

```bash
cd cli/

# Set environment
export CRY23_ROOT=~/CRYSTAL23
export CRY_SCRATCH_BASE=~/tmp_crystal

# Run CRYSTAL calculation
bin/runcrystal my_calculation

# Run with MPI (14 ranks)
bin/runcrystal my_calculation 14

# Show execution plan
bin/runcrystal my_calculation --explain
```

### TUI (Management)

```bash
cd tui/

# Install with uv (recommended)
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Or with pip
pip install -e ".[dev]"

# Launch
crystal-tui

# Keyboard shortcuts:
# n - New job    r - Run    s - Stop    q - Quit
# f - Filter     t - Sort
```

## Project Status

### CLI: Production Ready ✅
- 27/27 issues closed (100%)
- 9 modular library components
- 76 unit tests

### TUI: Phase 2 Complete ✅
- 63/66 issues closed (95%)
- Multi-runner architecture (Local, SSH, SLURM)
- QueueManager with priority scheduling
- WorkflowOrchestrator for job chains
- Template browser and input generation
- 880 tests passing

### Phase 3: AiiDA Integration (Planned)
- AiiDA backend for provenance tracking
- Production-tested parsers from AiiDA plugins
- WorkChain support for complex workflows

## Architecture

```
crystalmath/
├── cli/                         # Bash CLI
│   ├── bin/runcrystal          # Main executable
│   └── lib/                    # 9 modular components
│       ├── cry-config.sh       # Configuration
│       ├── cry-parallel.sh     # MPI/OpenMP logic
│       ├── cry-scratch.sh      # Scratch management
│       └── ...
│
├── tui/                        # Python TUI
│   ├── src/
│   │   ├── core/              # Business logic
│   │   │   ├── database.py    # SQLite ORM
│   │   │   ├── queue_manager.py    # Priority scheduling
│   │   │   ├── orchestrator.py     # Workflow coordination
│   │   │   ├── templates.py        # Input generation
│   │   │   └── codes/              # DFT code support
│   │   │       ├── crystal.py
│   │   │       ├── quantum_espresso.py
│   │   │       └── vasp.py
│   │   ├── runners/           # Execution backends
│   │   │   ├── local.py       # Local subprocess
│   │   │   ├── ssh_runner.py  # Remote SSH
│   │   │   └── slurm_runner.py # HPC batch
│   │   ├── tui/               # Textual UI
│   │   └── aiida/             # AiiDA integration (Phase 3)
│   ├── templates/             # Input templates
│   │   ├── qe/                # Quantum Espresso
│   │   ├── vasp/              # VASP
│   │   └── workflows/         # Multi-step chains
│   └── tests/                 # 880+ tests
│
├── docs/                      # Shared documentation
└── .beads/                    # Issue tracking (bd)
```

## DFT Code Support

### CRYSTAL23
- Native stdin invocation
- Environment from `cry23.bashrc`
- Full parser for energy, convergence, geometry

### Quantum Espresso
- Flag-based invocation (`pw.x -in input.in`)
- SCF, relaxation, vc-relax support
- K-point and convergence threshold templates

### VASP
- Multi-file handling (VASPInputFiles class)
- INCAR, KPOINTS, POSCAR, POTCAR management
- Relaxation → SCF workflow chains

## Templates & Workflows

### Single Calculations
```yaml
# templates/qe/scf.yml - Quantum Espresso SCF
# templates/vasp/relax.yml - VASP geometry optimization
```

### Workflow Chains
```yaml
# templates/workflows/vasp_relax_scf.yml
workflow:
  nodes:
    - id: "relax"
      template: "vasp/relax"
    - id: "transfer_structure"
      type: "data_transfer"
      file_renames: {"CONTCAR": "POSCAR"}
    - id: "scf"
      template: "vasp/scf"
```

## Requirements

### CLI
- Bash 4.0+
- CRYSTAL23 installation
- Optional: gum, mpirun

### TUI
- Python 3.10+
- DFT executables in PATH or configured
- See `tui/pyproject.toml` for dependencies

## Development

```bash
# CLI tests
cd cli/ && bats tests/unit/*.bats

# TUI tests
cd tui/
pytest                          # All tests
pytest --cov=src               # With coverage
black src/ tests/              # Format
ruff check src/ tests/         # Lint
mypy src/                      # Type check
```

## Issue Tracking

Uses [beads](https://github.com/beadsinc/beads) (`bd` command):

```bash
bd list              # Open issues
bd list --all        # All issues
bd show <issue-id>   # Details
bd create "Title"    # New issue
```

**Current:** 66 total issues (63 closed, 3 open core + AiiDA tasks)

## Documentation

| Document | Description |
|----------|-------------|
| `tui/docs/QE_VASP_SUPPORT.md` | Multi-code DFT support guide |
| `tui/docs/ARCHITECTURE_REALIGNMENT.md` | Architecture analysis and fixes |
| `cli/docs/ARCHITECTURE.md` | CLI module design |
| `tui/docs/PHASE2_DESIGN.md` | TUI Phase 2 architecture |

## Roadmap

- [x] **Phase 1**: Core TUI with local execution
- [x] **Phase 2**: Remote runners, queue management, templates
- [x] **v9i Epic**: Quantum Espresso & VASP support
- [ ] **Phase 3**: AiiDA integration for provenance
- [ ] **tai Epic**: Full QueueManager integration in TUI

## License

MIT License

---

**Repository:** [github.com/TheFermiSea/CrystalMath](https://github.com/TheFermiSea/CrystalMath) (private)
