# CrystalMath: Multi-Code DFT Job Management

A unified toolkit for quantum chemistry DFT calculations, supporting **CRYSTAL23**, **Quantum Espresso**, **VASP**, **Yambo**, and **phonopy**. The project is unifying on a single primary Rust/Ratatui TUI (`src/`) that talks to the Python core over an IPC boundary; the legacy Python/Textual TUI (`tui/`) is deprecated and being phased out. See [ADR-006](docs/architecture/adr-006-unify-on-rust-tui.md).

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

### Rust TUI (`src/`) — Primary
- Primary UI for job creation, configuration, workflows, and high-performance monitoring (Ratatui, 60fps)
- Handles the full lifecycle: new jobs, editor + LSP, results, logs, clusters, SLURM queue, workflows, recipes, batch submission
- Talks to the Python core over an IPC boundary (currently still using the PyO3 bridge during cutover) — see [ADR-006](docs/architecture/adr-006-unify-on-rust-tui.md)

### Python TUI (`tui/`) — Deprecated
- Legacy Textual-based async interface, being phased out under ADR-006
- Retained for reference until the Rust TUI fully supersedes it
- Tight integration with the Python scientific stack (pymatgen/ASE, quacc/AiiDA backends)

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

### Rust TUI (Primary)

```bash
# From crystalmath/ root

# Build (first time or after Python version changes)
./scripts/build-tui.sh

# Launch the unified tool
./target/release/crystalmath

# Keyboard shortcuts:
# 1-4     - Switch tabs (Jobs, Editor, Results, Log)
# n       - Create new job
# c       - Cluster Manager
# s       - SLURM Queue
# v       - VASP Input Manager
# Tab     - Next tab
# j/k     - Navigate up/down
# Ctrl+R  - Refresh jobs
# Ctrl+I  - Import from Materials Project (Editor tab)
# Ctrl+Q  - Quit
```

### Python TUI (Deprecated)

```bash
cd tui/
crystal-tui
```

## Project Status

### CLI: Production Ready ✅
- 27/27 issues closed (100%)
- 9 modular library components
- 173 bats tests

### Rust TUI: Primary ✅
- **Primary UI** for job creation, configuration, workflows, and monitoring.
- **Backend**: Python scientific logic (parsers, runners, quacc/AiiDA backends) reached over IPC (PyO3 bridge during cutover).
- **Features**:
  - Multi-code support (CRYSTAL23, QE, VASP, Yambo, phonopy)
  - Remote execution (SSH, SLURM)
  - Materials Project integration
- **Direction** — see [ADR-006](docs/architecture/adr-006-unify-on-rust-tui.md) for the unification policy.

### Python TUI: Deprecated ⚠️
- Legacy Textual UI, being phased out under [ADR-006](docs/architecture/adr-006-unify-on-rust-tui.md).
- Retained for reference until the Rust TUI fully supersedes it.

## Architecture

```
crystalmath/
├── src/                        # Rust TUI (primary)
│   ├── main.rs                # Entry point, terminal setup, event loop
│   ├── app.rs                 # Application state, tab navigation
│   ├── bridge.rs              # PyO3 bridge (transport during IPC cutover)
│   ├── ipc.rs + ipc/          # IPC boundary (client.rs, framing.rs)
│   ├── lsp.rs                 # LSP client (JSON-RPC over stdio)
│   ├── models.rs              # Shared data models
│   ├── monitor.rs             # Monitoring data collection
│   ├── prometheus.rs          # Prometheus metrics export
│   ├── state/                 # State module (mod.rs, actions.rs, help.rs)
│   └── ui/                    # UI components, one file per screen
│                              #   (jobs, editor, results, log, materials,
│                              #    cluster_manager, slurm_queue, vasp_input,
│                              #    monitor, workflows, recipes, batch_submission, ...)
│
├── python/                    # Python Backend
│   └── crystalmath/
│       ├── api.py             # Facade for Rust
│       ├── backends/          # CRYSTAL23, VASP, QE, Yambo, phonopy
│       ├── server/            # IPC server (crystalmath-server)
│       └── models.py          # Pydantic models
│
├── cli/                       # Bash CLI tools
│
└── tui/                       # Python TUI (deprecated, being phased out)
```

### UI Architecture

The system is unifying on a single Rust TUI over an IPC boundary (see [ADR-006](docs/architecture/adr-006-unify-on-rust-tui.md)):
1.  **Primary UI (Rust/Ratatui)**: Handles all user interaction, job creation, configuration, workflows, and monitoring.
2.  **Backend (Python)**: Scientific logic, database access, and HPC communication, exposed over an IPC boundary (`python/crystalmath/server/`). The PyO3 bridge remains the live transport during cutover.
3.  **Legacy UI (Python/Textual)**: Deprecated, being phased out.
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

### Rust TUI (Primary)
- Rust 1.70+ (for cargo build)
- Python 3.12 venv (for PyO3)
- Node.js 18+ (for LSP server, optional)
- Optional: vendored `vasp-language-server` (provides `vasp-lsp` / `dft-lsp` CLI)
- See `Cargo.toml` for dependencies

### Python TUI (Deprecated)
- Python 3.10+
- DFT executables in PATH or configured
- See `tui/pyproject.toml` for dependencies

### LSP Setup (optional)

The LSP server (referred to in code as the "dft-language-server") is vendored at
`third_party/vasp-language-server/`. Build it from the bundled repo:

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

# Rust TUI tests (primary)
cd crystalmath/
cargo test                     # All tests (242)
cargo clippy                   # Lint
cargo fmt --check              # Format check
./scripts/build-tui.sh         # Build with correct Python

# Python TUI tests (deprecated)
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

**Current Epic:** `crystalmath-as6l` - TUI Unification (unify on the Rust TUI over an IPC boundary; Python TUI deprecated). Live status is tracked in beads.

## Documentation

Full documentation is available in the `docs/` directory:

*   **[Getting Started](docs/getting-started/installation.md)**: Installation and setup guides
*   **[User Guide](docs/user-guide/tui/overview.md)**: Manuals for TUI and CLI usage
*   **[Architecture](docs/architecture/overview.md)**: System design and module details
*   **[Development](docs/development/contributing.md)**: Contributing guidelines and testing

## Roadmap

### Completed
- [x] **CLI**: Production-ready with 173 bats tests
- [x] **Multi-Code Support**: CRYSTAL23, QE, VASP, Yambo, phonopy
- [x] **Workflow Backends**: quacc and AiiDA both supported (co-equal)
- [x] **Rust TUI Core**: 60fps UI, PyO3 bridge, LSP editor, job creation/config/workflows
- [x] **IPC Boundary**: built (`src/ipc/`, `python/crystalmath/server/`)

### In Progress
- [ ] **Epic `crystalmath-as6l`**: TUI Unification — cut the live transport over from the PyO3 bridge to the IPC client (keystone)
- [ ] **Phase 4**: Materials Project API integration
- [ ] Live log streaming and job status dashboard polish

### Planned
- [ ] Fully phase out the deprecated Python/Textual TUI once the Rust TUI supersedes it

## License

MIT License

---

**Repository:** [github.com/TheFermiSea/CrystalMath](https://github.com/TheFermiSea/CrystalMath) (private)
