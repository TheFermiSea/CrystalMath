# CrystalMath: Multi-Code DFT Job Management

A unified toolkit for quantum chemistry DFT calculations, supporting **CRYSTAL23**, **Quantum Espresso**, and **VASP**. Uses a primary Python/Textual TUI ("Workshop") with an optional Rust/Ratatui TUI ("Cockpit") for high-performance monitoring.

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

### Python TUI - "Workshop" (`tui/`) — Primary
- Primary UI for job creation, configuration, and workflows
- Textual-based async interface
- Tight integration with the Python scientific stack (AiiDA/pymatgen/ASE)

### Rust TUI - "Cockpit" (`src/`) — Secondary / Experimental
- Optional high-performance monitoring UI (Ratatui)
- Great for dense job/log dashboards
- **No new feature work without a stable IPC boundary** (PyO3 embedding is being phased out)

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

### Python TUI (Primary)

```bash
cd tui/
crystal-tui
```

### Rust TUI (Secondary)

```bash
# From crystalmath/ root

# Build (first time or after Python version changes)
./scripts/build-tui.sh

# Launch the unified tool
./target/release/crystalmath

# Keyboard shortcuts:
# 1-4     - Switch tabs (Jobs, Editor, Results, Log)
# n       - Create new job (formerly Workshop feature)
# c       - Cluster Manager
# s       - SLURM Queue
# v       - VASP Input Manager
# Tab     - Next tab
# j/k     - Navigate up/down
# Ctrl+R  - Refresh jobs
# Ctrl+I  - Import from Materials Project (Editor tab)
# Ctrl+Q  - Quit
```

## Project Status

### CLI: Production Ready ✅
- 27/27 issues closed (100%)
- 9 modular library components
- 76 unit tests

### Python TUI: Primary ✅
- **Primary UI** for workflows and configuration.
- **Backend**: Python scientific logic (AiiDA, parsers, runners).
- **Features**:
  - Multi-code support (CRYSTAL23, QE, VASP)
  - Remote execution (SSH, SLURM)
  - Materials Project integration

### Rust TUI: Secondary / Experimental ⚠️
- Optional high-performance cockpit for monitoring.
- Feature work only after IPC boundary is defined.

## Architecture

```
crystalmath/
├── src/                        # Rust TUI (secondary/experimental)
│   ├── main.rs                # Entry point
│   ├── app.rs                 # State management & Tests
│   ├── bridge.rs              # PyO3 bridge
│   ├── models.rs              # Shared data models
│   └── ui/                    # UI Components (New Job, Results, etc.)
│
├── python/                    # Python Backend
│   └── crystalmath/
│       ├── api.py             # Facade for Rust
│       └── models.py          # Pydantic models
│
├── cli/                       # Bash CLI tools
│
└── tui/                       # Python TUI (primary)
```

### UI Architecture (Primary + Secondary)

The system follows a "Python-first UI with optional Rust cockpit" model:
1.  **Primary UI (Python/Textual)**: Handles user interaction and workflows.
2.  **Secondary UI (Rust/Ratatui)**: Optional high-performance cockpit. Should communicate via IPC rather than embedding Python.
3.  **Backend (Python)**: Scientific logic, database access, and HPC communication.
4.  **Database**: SQLite (`.crystal_tui.db`) shared source of truth.

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

### Python TUI
- Python 3.10+
- DFT executables in PATH or configured
- See `tui/pyproject.toml` for dependencies

### Rust TUI
- Rust 1.70+ (for cargo build)
- Python 3.12 venv (for PyO3)
- Node.js 18+ (for LSP server, optional)
- Optional: `dft-language-server` (provides `vasp-lsp` / `dft-lsp` CLI)
- See `Cargo.toml` for dependencies

### LSP Setup (optional)

```bash
npm install -g dft-language-server
```

To use the bundled upstream repo:

```bash
git submodule update --init --recursive
cd third_party/vasp-language-server
npm install
npm run build
```

The Rust TUI will prefer the bundled repo when built (looks for
`third_party/vasp-language-server/out/server.js`). It falls back to the
`vasp-lsp` command on PATH, and you can override either with
`CRYSTAL_TUI_LSP_PATH`.

## Development

```bash
# CLI tests
cd cli/ && bats tests/unit/*.bats

# Python TUI tests
cd tui/
pytest                          # All tests
pytest --cov=src               # With coverage
black src/ tests/              # Format
ruff check src/ tests/         # Lint
mypy src/                      # Type check

# Rust TUI tests
cd crystalmath/
cargo test                     # All tests (44)
cargo clippy                   # Lint
cargo fmt --check              # Format check
./scripts/build-tui.sh         # Build with correct Python
```

## Issue Tracking

Uses [beads](https://github.com/beadsinc/beads) (`bd` command):

```bash
bd list              # Open issues
bd list --all        # All issues
bd show <issue-id>   # Details
bd create "Title"    # New issue
```

**Current Epic:** `crystalmath-as6l` - TUI Unification (Python primary, Rust secondary)

## Documentation

Full documentation is available in the `docs/` directory:

*   **[Getting Started](docs/getting-started/installation.md)**: Installation and setup guides
*   **[User Guide](docs/user-guide/tui/overview.md)**: Manuals for TUI and CLI usage
*   **[Architecture](docs/architecture/overview.md)**: System design and module details
*   **[Development](docs/development/contributing.md)**: Contributing guidelines and testing

## Roadmap

### Completed
- [x] **CLI**: Production-ready with 76 tests
- [x] **Python TUI Phase 1-2**: Core TUI, remote runners, templates
- [x] **Multi-Code Support**: CRYSTAL23, QE, VASP
- [x] **Rust TUI Core**: 60fps monitoring, PyO3 bridge, LSP editor

### In Progress
- [ ] **Epic 5hh**: TUI UX Excellence ("Cockpit vs Workshop")
  - [x] Database unification
  - [x] Empty state UX
  - [ ] Live log streaming
  - [ ] Job status dashboard
- [ ] **Phase 4**: Materials Project API integration

### Planned
- [ ] **AiiDA**: Full provenance tracking
- [ ] **Rust TUI IPC**: Optional Rust cockpit via stable IPC boundary

## License

MIT License

---

**Repository:** [github.com/TheFermiSea/CrystalMath](https://github.com/TheFermiSea/CrystalMath) (private)
