# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CRYSTAL-TOOLS is a unified monorepo containing complementary tools for CRYSTAL23 quantum chemistry DFT calculations:

1. **CLI** (`cli/`) - Production-ready Bash tool for executing calculations
2. **Python TUI** (`tui/`) - **Primary** Textual-based UI for job creation, configuration, and workflows ("Workshop")
3. **Rust TUI** (`src/`) - **Secondary/experimental** Ratatui-based UI for high-performance monitoring ("Cockpit")

**Design Philosophy: "Workshop Primary, Cockpit Optional"**
- **Python TUI (Workshop)**: Primary UI for workflows, templates, cluster config, and job submission.
- **Rust TUI (Cockpit)**: Secondary/experimental UI focused on high-performance monitoring.
- **Shared Database**: Both TUIs share `.crystal_tui.db`. Rust should consume data via a stable IPC boundary rather than expanding PyO3 usage.

## Core Commands

### CLI Tool

```bash
cd cli/

# Run calculation (serial mode with auto-threading)
bin/runcrystal my_calculation

# Run with MPI parallelism (14 ranks)
bin/runcrystal my_calculation 14

# Educational mode (show execution plan without running)
bin/runcrystal --explain my_calculation

# Run tests
bats tests/unit/*.bats                  # Unit tests
bats tests/integration/*.bats           # Integration tests
bats tests/unit/cry-parallel_test.bats  # Single module
```

### Python TUI (Workshop)

```bash
cd tui/

# Setup with uv (recommended)
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Launch (use for job creation, cluster config, templates)
crystal-tui

# Run tests
pytest                              # All tests
pytest tests/test_database.py       # Single file
pytest -k "test_job_create"         # Single test

# Code quality
black src/ tests/ && ruff check src/ tests/ && mypy src/
```

### Rust TUI (Cockpit - Secondary)

```bash
# From crystalmath/ root (IMPORTANT: must be in root, not tui/)

# Build with correct Python version (REQUIRED - see note below)
./scripts/build-tui.sh          # Uses venv Python for PyO3
./scripts/build-tui.sh --clean  # Force clean rebuild (use after Python updates)

# Or manually:
PYO3_PYTHON=/path/to/crystalmath/.venv/bin/python cargo build --release

# Run tests
cargo test                    # All tests (~103 tests)
cargo test lsp                # LSP module tests only
cargo test models             # Model tests only

# Run TUI (optional monitoring UI)
./target/release/crystalmath

# Check code quality
cargo clippy
cargo fmt --check
```

**CRITICAL: Python Version Mismatch (PyO3)**
PyO3 must be compiled against the **exact same Python version** used at runtime.
- The venv uses Python 3.12 (check with `.venv/bin/python --version`)
- System Python may be 3.14+ (incompatible)
- Always use `./scripts/build-tui.sh` or set `PYO3_PYTHON` explicitly
- If you see "SRE module mismatch" errors, run `./scripts/build-tui.sh --clean`

### Issue Tracking (bd/beads)

```bash
bd list                    # Open issues
bd list --all              # All issues
bd show <issue-id>         # Details
bd create "Title"          # New issue
```

## Architecture

### CLI (Bash, Modular)

**Main Script:** `bin/runcrystal` - Thin orchestrator loading 9 library modules:

| Module | Purpose |
|--------|---------|
| `cry-config.sh` | Configuration & environment (no deps) |
| `cry-logging.sh` | Logging infrastructure (no deps) |
| `core.sh` | Module loader `cry_require` (deps: config, logging) |
| `cry-ui.sh` | Visual components via gum |
| `cry-parallel.sh` | MPI/OpenMP resource allocation |
| `cry-scratch.sh` | Scratch directory lifecycle |
| `cry-stage.sh` | File staging (input/output) |
| `cry-exec.sh` | CRYSTAL23 binary execution |
| `cry-help.sh` | Help system |

**Key Patterns:**
- State via `CRY_JOB` associative array (Bash 4.0+ required)
- Trap-based cleanup: `trap 'scratch_cleanup' EXIT`
- Modules return exit codes; main script handles errors

### Python TUI - "Workshop" (Textual, Async)

**Entry Point:** `tui/src/main.py` → `tui/src/tui/app.py`

**Package Structure:**
- `src/core/` - Business logic (database, orchestrator, queue, templates, workflow, connection manager)
- `src/core/materials_api/` - Materials Project API integration (Phase 4)
- `src/tui/` - Textual UI components (app, screens, widgets)
- `src/runners/` - Job backends (local, SSH, SLURM)
- `src/aiida/` - AiiDA integration (Phase 3, optional)

**Key Technologies:**
- Textual (async TUI framework)
- SQLite (job persistence)
- asyncssh (remote execution)
- Jinja2 (input templates - sandboxed)

**Runners:**
- `local.py` - Local subprocess with per-job result isolation and proper cleanup (SIGTERM→SIGKILL)
- `ssh_runner.py` - Remote SSH execution with JobStatus enum consistency
- `slurm_runner.py` - HPC batch scheduling

**Orchestrator Features:**
- DAG-based workflow execution with dependency resolution
- Safe atexit cleanup (only removes terminal-state workflow directories)
- Custom output parser registry with built-in parsers (energy, bandgap, lattice)
- Sandboxed Jinja2 template rendering for input generation

**Core Tables:**
```sql
jobs (id, name, status, runner_type, cluster_id, input_content, results_json, work_dir)
clusters (id, name, hostname, username, queue_type, max_concurrent)
workflows (id, name, dag_json, status)
```

### Rust TUI - "Cockpit" (Ratatui, PyO3)

**Entry Point:** `src/main.rs` → `src/app.rs`

**Module Structure:**
| Module | Purpose |
|--------|---------|
| `main.rs` | Entry point, terminal setup, 60fps event loop, Python env config |
| `app.rs` | Application state, tab navigation, dirty-flag rendering |
| `models.rs` | Data models matching Python Pydantic (serde), ClusterType enum, VaspInputFiles |
| `bridge.rs` | PyO3 FFI to Python backend, async request/response via channels |
| `lsp.rs` | LSP client for dft-language-server (JSON-RPC over stdio) |
| `ui/` | Ratatui view components (jobs, editor, results, log, materials, cluster_manager, slurm_queue, vasp_input) |

**Key Data Models (`models.rs`):**
- `ClusterType` enum: `Ssh`/`Slurm` with serde serialization (`#[serde(rename_all = "lowercase")]`)
- `VaspInputFiles`: VASP multi-file input (POSCAR, INCAR, KPOINTS, POTCAR config) for `JobSubmission.parameters`
- `ClusterConfig`: Cluster configuration with typed `cluster_type: ClusterType`
- `JobSubmission`: Job creation with `with_parameters()` builder for DFT-specific data

**Key Technologies:**
- Ratatui (TUI rendering framework, 60fps)
- PyO3 (Rust-Python FFI bridge)
- Crossterm (terminal events)
- tui-textarea (editor widget with line numbers)
- serde (JSON serialization for bridge)
- tracing (structured logging)

**Database Sharing:**
The Rust TUI finds the shared `.crystal_tui.db` via `find_database_path()` in `bridge.rs`:
1. `CRYSTAL_TUI_DB` environment variable (highest priority)
2. `.crystal_tui.db` in project root (where Cargo.toml is)
3. `.crystal_tui.db` in `tui/` subdirectory
4. XDG/platform data directories (fallback)

**LSP Integration:**
- Spawns `dft-language-server` as subprocess
- JSON-RPC 2.0 over stdio with Content-Length framing
- Async diagnostics via `mpsc` channel
- 200ms debounce on editor changes
- Graceful degradation if server unavailable

**Architecture Pattern:**
```
┌─────────────────────────────────────────────────────┐
│                   Rust TUI (60fps)                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────┐  │
│  │   Jobs   │  │  Editor  │  │ Results  │  │ Log │  │
│  │  Table   │  │  +LSP    │  │  Detail  │  │View │  │
│  └──────────┘  └──────────┘  └──────────┘  └─────┘  │
└───────────────────────┬─────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
        ▼               ▼               ▼
┌──────────────┐ ┌─────────────┐ ┌─────────────┐
│ Python Bridge│ │ LSP Server  │ │   Shared    │
│   (PyO3)     │ │  (Node.js)  │ │  Database   │
│ Worker Thread│ │ JSON-RPC    │ │ .crystal_   │
└──────┬───────┘ └─────────────┘ │  tui.db     │
       │                         └─────────────┘
       ▼
┌─────────────────────┐
│  crystalmath.api    │
│  (Python Backend)   │
│  - SQLite queries   │
│  - Materials API    │
│  - AiiDA (optional) │
└─────────────────────┘
```

## Development Guidelines

### CLI Development

1. Identify module to modify (see Module table above)
2. Follow pattern: accept `CRY_JOB` by reference, return exit codes, use `local` variables
3. Write tests in `tests/unit/<module>_test.bats`
4. Dependencies: config/logging have none; core depends on them; others can depend on all three

### TUI Development (Python)

1. UI → `tui/src/tui/screens/` or `tui/src/tui/widgets/`
2. Business logic → `tui/src/core/`
3. Execution backends → `tui/src/runners/`
4. Database changes → `tui/src/core/database.py` (add `migrate_*` methods)

**Code style:** Black (100 chars), Ruff (E, F, W, I, N, UP, B, A, C4, SIM), MyPy, Python 3.10+

**Security requirements:**
- Jinja2: Use `jinja2.sandbox.SandboxedEnvironment`
- SSH: Enable host key verification (never `known_hosts=None`)
- Commands: Escape shell when building SLURM scripts or remote commands
- Workflow conditions: Use `_safe_eval_condition()` with AST whitelisting (never raw `eval()`)
- Stub execution: Require explicit `metadata["allow_stub_execution"] = True` for test workflows

### Rust TUI Development

1. UI components → `src/ui/` (ratatui widgets)
2. State management → `src/app.rs` (central `App` struct)
3. Data models → `src/models.rs` (must match Python Pydantic)
4. Python FFI → `src/bridge.rs` (PyO3 calls)
5. LSP client → `src/lsp.rs` (JSON-RPC over stdio)

**Code style:** `cargo fmt`, `cargo clippy` (no warnings)

**Key patterns:**
- Dirty-flag rendering: only redraw when `app.needs_redraw()` is true
- Non-fatal errors: use `app.set_error()` instead of propagating
- LSP async: poll `lsp_receiver` in event loop, handle events without blocking

## Environment Setup

```bash
# Required (typically in ~/CRYSTAL23/cry23.bashrc)
export CRY23_ROOT=~/CRYSTAL23
export CRY23_EXEDIR=$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1
export CRY_SCRATCH_BASE=~/tmp_crystal

# Optional: Add CLI to PATH
export PATH="$HOME/CRYSTAL23/crystalmath/cli/bin:$PATH"
```

**Scratch Convention:**
- CLI: `~/tmp_crystal/cry_<job>_<pid>/`
- TUI: `~/tmp_crystal/crystal_tui_<job>_<pid>/`

## Project Status

| Component | Status | Notes |
|-----------|--------|-------|
| CLI | ✅ Production | 100% complete, 76 tests |
| Python TUI Phase 2 | ✅ Complete | SSH/SLURM/orchestration working |
| Python TUI Runner Safety | ✅ Complete | Race conditions fixed, proper cleanup |
| Python TUI Phase 3 | ✅ Complete | AiiDA integration (optional PostgreSQL) |
| Python TUI Phase 4 | 🔨 In Progress | Materials Project API integration |
| **Rust TUI (Cockpit)** | | |
| Phase 1-4: Core TUI | ✅ Complete | Event loop, app state, bridge, UI |
| Phase 5: LSP | ✅ Complete | JSON-RPC client, diagnostics display |
| Phase 6: Testing | ✅ Complete | ~103 unit tests, documentation |
| **Feature Parity (lo7)** | 🔨 In Progress | lo7.5-7 remaining |
| **Security Hardening** | ✅ Complete | AST-based safe eval, API contract fixes |

**Recent Fixes (Dec 2024):**
- ✅ crystalmath-obqk: Fixed eval() code injection in workflow conditions (AST whitelisting)
- ✅ crystalmath-6sf7: Fixed Rust-Python JSON contract mismatch (ApiResponse wrapper)
- ✅ crystalmath-z539: Fixed silent stub execution (explicit allow_stub_execution flag)
- ✅ crystalmath-0ib/ilp: Fixed LSP unwrap() panics on non-UTF8/None
- ✅ All Gemini code review P1 issues closed

**Open Feature Parity (lo7):**
- 🔲 lo7.5: Template Browser
- 🔲 lo7.6: Materials Search
- 🔲 lo7.7: Batch Submission

**Feature Roadmap (P1-P3 Epics):**

| Epic | Priority | Description | Tasks |
|------|----------|-------------|-------|
| crystalmath-7r8 | P1 | Workflow Automation | Convergence studies, phonons, band structure, EOS |
| crystalmath-5uy | P1 | Analytics & Monitoring | Live dashboards, trends, mobile alerts |
| crystalmath-7k7 | P2 | Structure Engineering | Slab builder, defects, matching, nanostructures |
| crystalmath-8dm | P2 | AI-Powered Features | LLM diagnosis, NL input, literature params |
| crystalmath-dgg | P3 | Cloud & Scale | AWS Batch, Kubernetes orchestration |
| crystalmath-gh8 | P3 | Collaboration & Sharing | Workspaces, CIF export, web dashboard |

**Open P2 Tasks:**
- wf1.1-1.5: Workflow automation (convergence, phonons, bands, EOS, restart)
- se2.1-2.4: Structure engineering (slabs, defects, matching, nanostructures)
- am3.1-3.4: Analytics (live SCF, trends, mobile alerts, checksums)
- ai4.1-4.3: AI features (error diagnosis, NL input, literature params)
- lo7.5-7: Rust TUI parity (templates, materials, batch)
- dyu.5-6: DFT code UI (syntax validation, environment paths)
- AiiDA parser migration (CRYSTAL, VASP, QE)

## Troubleshooting

### CLI Issues

**"associative array: bad array subscript"** → Bash < 4.0. Fix: `brew install bash`

**"crystalOMP: not found"** → `CRY23_ROOT` not set. Fix: `source ~/CRYSTAL23/utils23/cry23.bashrc`

### Python TUI Issues

**"No module named 'textual'"** → Run `pip install -e ".[dev]"` from `tui/`

**SSH "Connection refused"** → SSH manually first to add host key, or check asyncssh version

### Rust TUI Issues

**"SRE module mismatch"** → Python version conflict between build time and runtime.
```bash
# Fix: Force clean rebuild with correct Python
./scripts/build-tui.sh --clean
```

**"No module named 'crystalmath'"** → Python path not configured correctly.
```bash
# The build script handles this, but you can also set manually:
export PYTHONPATH=/path/to/crystalmath/python:$PYTHONPATH
```

**"AssertionError: SRE module mismatch"** → PyO3 was compiled with wrong Python.
```bash
# Check venv Python version:
.venv/bin/python --version  # Should be 3.12.x

# Check system Python (may be incompatible):
python3 --version  # May be 3.14+

# Fix:
./scripts/build-tui.sh --clean
```

**Empty job list / "Running in demo mode"** → Database not found.
```bash
# Check if database exists:
ls -la .crystal_tui.db

# If not, run Python TUI first to create jobs:
cd tui && crystal-tui

# Or specify path explicitly:
export CRYSTAL_TUI_DB=/path/to/.crystal_tui.db
```

**"LSP server not found"** → dft-language-server not built.
```bash
cd dft-language-server && npm install && npm run build
```

**No diagnostics in editor** → LSP server unavailable (graceful degradation). Check:
```bash
# Test LSP server directly:
node dft-language-server/out/server.js --stdio
```

## Key Files

### CLI
- Architecture: `cli/docs/ARCHITECTURE.md`
- Module Details: `cli/CLAUDE.md`

### Python TUI (Workshop)
- Entry Point: `tui/src/main.py`
- Materials API: `tui/src/core/materials_api/`
- AiiDA Integration: `tui/src/aiida/`

### Rust TUI (Cockpit)
- Entry Point: `src/main.rs` (Python env config, event loop)
- App State: `src/app.rs` (tabs, state management, dirty-flag rendering)
- Python Bridge: `src/bridge.rs` (PyO3 FFI, database discovery)
- LSP Client: `src/lsp.rs` (JSON-RPC, diagnostics)
- UI Components: `src/ui/` (jobs, editor, results, log, materials)
- Python API: `python/crystalmath/api.py` (backend for Rust TUI)
- Build Script: `scripts/build-tui.sh` (handles Python version)

### Shared
- Database: `.crystal_tui.db` (SQLite, shared between TUIs)
- Issue Tracking: `.beads/issues.jsonl`
