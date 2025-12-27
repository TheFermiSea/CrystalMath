# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CRYSTAL-TOOLS is a unified monorepo containing complementary tools for CRYSTAL23 quantum chemistry DFT calculations:

1. **CLI** (`cli/`) - Production-ready Bash tool for executing calculations
2. **TUI** (`tui/`) - Python terminal UI for interactive job management with remote execution

**Design Philosophy:** CLI for execution, TUI for management. Both tools work independently but share CRYSTAL23 environment.

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

### TUI Tool

```bash
cd tui/

# Setup with uv (recommended)
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Launch
crystal-tui

# Run tests
pytest                              # All tests
pytest tests/test_database.py       # Single file
pytest -k "test_job_create"         # Single test

# Code quality
black src/ tests/ && ruff check src/ tests/ && mypy src/
```

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

### TUI (Python, Async)

**Entry Point:** `src/main.py` → `src/tui/app.py`

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

## Development Guidelines

### CLI Development

1. Identify module to modify (see Module table above)
2. Follow pattern: accept `CRY_JOB` by reference, return exit codes, use `local` variables
3. Write tests in `tests/unit/<module>_test.bats`
4. Dependencies: config/logging have none; core depends on them; others can depend on all three

### TUI Development

1. UI → `src/tui/screens/` or `src/tui/widgets/`
2. Business logic → `src/core/`
3. Execution backends → `src/runners/`
4. Database changes → `src/core/database.py` (add `migrate_*` methods)

**Code style:** Black (100 chars), Ruff (E, F, W, I, N, UP, B, A, C4, SIM), MyPy, Python 3.10+

**Security requirements:**
- Jinja2: Use `jinja2.sandbox.SandboxedEnvironment`
- SSH: Enable host key verification (never `known_hosts=None`)
- Commands: Escape shell when building SLURM scripts or remote commands

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
| TUI Phase 2 | ✅ Complete | SSH/SLURM/orchestration working |
| TUI Runner Safety (ae6) | ✅ Complete | Race conditions fixed, proper cleanup |
| TUI Phase 3 | ✅ Complete | AiiDA integration (optional PostgreSQL) |
| TUI Phase 4 | 🔨 In Progress | Materials Project API integration |

**Current Sprint (Materials API - crystalmath-7mw):**
- ✅ MP API async client with `asyncio.to_thread()` wrapper
- ✅ MPContribs async client for user contributions
- ✅ OPTIMADE native async client (httpx) for cross-database queries
- ✅ SQLite cache with 30-day TTL (Migration V6)
- ✅ MaterialsService orchestrator with rate limiting
- ✅ pymatgen → CRYSTAL23 .d12 converter
- 🔲 TUI MaterialsSearchScreen component
- 🔲 Unit/integration tests

## Troubleshooting

**CLI: "associative array: bad array subscript"** → Bash < 4.0. Fix: `brew install bash`

**CLI: "crystalOMP: not found"** → `CRY23_ROOT` not set. Fix: source `cry23.bashrc`

**TUI: "No module named 'textual'"** → Run `pip install -e ".[dev]"` from `tui/`

**TUI: SSH "Connection refused"** → SSH manually first to add host key, or check asyncssh version

## Key Files

- CLI Architecture: `cli/docs/ARCHITECTURE.md`
- CLI Module Details: `cli/CLAUDE.md`
- TUI Project Status: `tui/docs/PROJECT_STATUS.md`
- Materials API Guide: `tui/docs/MATERIALS_API.md`
- AiiDA Setup: `tui/docs/AIIDA_SETUP.md`
- CRYSTAL23 Compilation: `docs/CRYSTAL23_COMPILATION_GUIDE.md`
