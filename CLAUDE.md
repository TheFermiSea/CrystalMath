# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CRYSTAL-TOOLS is a unified monorepo containing complementary tools for CRYSTAL23 quantum chemistry DFT calculations:

1. **CLI** (`cli/`) - Production-ready Bash tool for executing calculations
2. **TUI** (`tui/`) - Python terminal UI for interactive job management with remote execution

**Design Philosophy:** CLI for execution, TUI for management. Both tools work independently but share CRYSTAL23 environment.

## Core Commands

### CLI Tool (Execution)

```bash
cd cli/

# Run calculation (serial mode with auto-threading)
bin/runcrystal my_calculation

# Run with MPI parallelism (14 ranks)
bin/runcrystal my_calculation 14

# Educational mode (show execution plan without running)
bin/runcrystal --explain my_calculation

# Run unit tests
bats tests/unit/*.bats

# Run integration tests
bats tests/integration/*.bats
```

### TUI Tool (Interactive Management)

```bash
cd tui/

# Setup development environment with uv (recommended)
uv venv
source .venv/bin/activate  # or: .venv/bin/activate.fish (fish shell)
uv pip install -e ".[dev]"

# Or use pip if uv not available
# python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"

# Launch interactive interface
crystal-tui

# Run tests
pytest

# Code quality checks
black src/ tests/           # Format code
ruff check src/ tests/      # Lint
mypy src/                   # Type check

# With coverage
pytest --cov=src --cov-report=html
```

### Issue Tracking (bd/beads)

```bash
# From monorepo root
bd list                     # Show open issues
bd list --all              # Show all issues
bd list --status=closed    # Show completed issues
bd show <issue-id>         # Show details
bd create "Issue title"    # Create new issue
```

**Current Status:** 66 total issues (3 open, 63 closed)

## Architecture

### CLI Architecture (Bash, Modular)

**Main Script:** `bin/runcrystal` (130 lines, thin orchestrator)

**9 Library Modules:**
- `cry-config.sh` - Configuration & environment
- `cry-logging.sh` - Logging infrastructure
- `core.sh` - Module loader system
- `cry-ui.sh` - Visual components (gum wrappers)
- `cry-parallel.sh` - MPI/OpenMP parallelism logic
- `cry-scratch.sh` - Scratch space management
- `cry-stage.sh` - File staging utilities
- `cry-exec.sh` - Calculation execution
- `cry-help.sh` - Help system

**Key Patterns:**
- State via `CRY_JOB` associative array (Bash 4.0+ required)
- Trap-based cleanup guarantee (`trap 'scratch_cleanup' EXIT`)
- Module return exit codes (0 = success)
- Mock external commands in tests

**See `cli/CLAUDE.md` for detailed module architecture and development patterns.**

### TUI Architecture (Python, Async)

**Entry Point:** `src/main.py` → `src/tui/app.py`

**Package Structure:**
- `src/core/` - Business logic (database, environment, orchestration, templates, workflows, connection management, queue management)
- `src/tui/` - Textual UI components (app, screens, widgets)
- `src/runners/` - Job execution backends (local, SSH, SLURM)

**Key Technologies:**
- Textual framework (async TUI)
- SQLite for job history
- asyncssh for remote execution
- Jinja2 for input templates
- Async/await architecture

**Runners (Phase 2 Complete):**
- `local.py` - Local subprocess execution
- `ssh_runner.py` - Remote SSH execution
- `slurm_runner.py` - HPC batch scheduling

**Core Components (Phase 2 Complete):**
- `orchestrator.py` - Multi-job workflow coordination
- `queue_manager.py` - Job queue with priority scheduling
- `connection_manager.py` - Connection pooling for remote clusters
- `templates.py` - Input file template system
- `workflow.py` - DAG-based workflow engine

**Data Model:**
```python
Job {
    id: int
    name: str
    status: pending|running|completed|failed
    runner_type: local|ssh|slurm
    cluster_id: int (optional)
    input_content: str (d12 file)
    results_json: str (parsed results)
    work_dir: Path
}

Cluster {
    id: int
    name: str
    hostname: str
    username: str
    queue_type: slurm|pbs|sge
    max_concurrent: int
}
```

## Development Guidelines

### CLI Development (Bash)

**When adding features:**
1. Identify which module to modify (see `cli/CLAUDE.md` Module Responsibilities)
2. Follow module template pattern (source modules explicitly, use `local`, return exit codes)
3. Write unit tests in `cli/tests/unit/<module>_test.bats`
4. Ensure >80% test coverage

**Testing:**
```bash
cd cli/
bats tests/unit/cry-parallel_test.bats  # Test specific module
bats tests/unit/*.bats                  # All unit tests
```

**Module dependency rules:**
- Never create circular dependencies
- `cry-config.sh` and `cry-logging.sh` have no dependencies
- `core.sh` depends only on config and logging
- All other modules can depend on config, logging, core

### TUI Development (Python)

**When adding features:**
1. UI components → `src/tui/screens/` or `src/tui/widgets/`
2. Business logic → `src/core/`
3. Execution backends → `src/runners/`
4. Update database schema if needed (see `src/core/database.py:migrate_*` methods)
5. Write tests in `tests/`

**Code style (from pyproject.toml):**
- Black (100 char line length)
- Ruff (E, F, W, I, N, UP, B, A, C4, SIM)
- MyPy type checking enabled
- Python 3.10+ required

**Testing:**
```bash
cd tui/
pytest                              # Run all tests
pytest --cov=src --cov-report=html  # With coverage
```

**Security considerations:**
- Always sandbox Jinja2 templates (use `jinja2.sandbox.SandboxedEnvironment`)
- Enable SSH host key verification (never use `known_hosts=None`)
- Escape shell commands when building SLURM scripts or remote commands
- Use parameterized SQL queries (already enforced by ORM)

## Environment Setup

Both tools share the CRYSTAL23 environment:

```bash
# Required environment variables (typically in ~/CRYSTAL23/cry23.bashrc)
export CRY23_ROOT=~/CRYSTAL23
export CRY23_EXEDIR=$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1
export CRY_SCRATCH_BASE=~/tmp_crystal

# Optional: Add CLI to PATH
export PATH="$HOME/CRYSTAL23/crystalmath/cli/bin:$PATH"
```

**Scratch Directory Convention:**
- Shared location: `~/tmp_crystal/`
- CLI: `cry_<job>_<pid>/`
- TUI: `crystal_tui_<job>_<pid>/`

## Project Status

### CLI: Production Ready ✅
- **Completion:** 27/27 beads issues closed (100%)
- **Architecture:** Modular (9 library modules)
- **Testing:** 76 tests, 74% pass rate
- **Features:** Serial/parallel execution, scratch management, auto file staging, --explain mode

### TUI: Phase 2 Complete ⚠️
- **Completion:** 63/66 beads issues closed (95%)
- **Architecture:** Textual + SQLite + asyncssh
- **Implemented:** Three-panel UI, job database, local/SSH/SLURM runners, orchestration, templates, workflows
- **Known Issues:** 3 critical security/functional issues require immediate attention before production use

**⚠️ IMPORTANT:** Phase 2 implementation is complete but **NOT production-ready**. See `CODE_REVIEW_FINDINGS.md` for critical security issues that must be fixed:
1. SSH host key verification disabled (MITM vulnerability)
2. Unsandboxed Jinja2 templates (code execution vulnerability)
3. Command injection in SSH/SLURM runners
4. Orchestrator workflow submission not functional
5. Database migration and concurrency issues

## Common Development Tasks

### Running CLI Calculations

```bash
cd cli/

# Educational mode (dry run)
bin/runcrystal --explain my_job

# Serial execution (uses all cores with OpenMP)
bin/runcrystal my_job

# Parallel execution (14 MPI ranks × auto threads)
bin/runcrystal my_job 14
```

### Testing TUI Modules

```bash
cd tui/

# Test imports
python3 -c "from src.core.database import Database; print('✅ Database')"
python3 -c "from src.core.environment import load_crystal_environment; print('✅ Environment')"
python3 -c "from src.runners.local import LocalRunner; print('✅ LocalRunner')"

# Launch TUI
crystal-tui
```

### Git Workflow

```bash
# Create feature branch
git checkout -b feature/my-feature

# Make changes (CLI or TUI)
# ... edit files ...

# Test changes
cd cli/ && bats tests/unit/*.bats     # CLI tests
cd tui/ && pytest                     # TUI tests

# Commit (reference beads issue IDs)
git add .
git commit -m "feat: Add feature description

Detailed explanation of changes.

Closes: crystalmath-xyz
"
```

## Key Technical Details

### CLI Parallelism

**System Support:** Intel Xeon w9-3495X (56 cores)

**Modes:**
- **Serial:** 1 process × 56 threads (OpenMP), uses `crystalOMP`
- **Hybrid:** N ranks × (56/N) threads (MPI+OpenMP), uses `PcrystalOMP`

**Auto-configuration:**
- Detects system cores via `nproc` or `sysctl`
- Sets `OMP_NUM_THREADS`, `I_MPI_PIN_DOMAIN`, `KMP_AFFINITY`
- Selects appropriate binary
- Populates `CRY_JOB` associative array

### TUI Database Schema

**Core Tables:**
```sql
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    runner_type TEXT DEFAULT 'local',
    cluster_id INTEGER,
    input_content TEXT,
    results_json TEXT,
    work_dir TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY (cluster_id) REFERENCES clusters (id)
);

CREATE TABLE clusters (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    hostname TEXT NOT NULL,
    username TEXT NOT NULL,
    queue_type TEXT,
    max_concurrent INTEGER DEFAULT 10,
    created_at TIMESTAMP
);

CREATE TABLE workflows (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    dag_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMP
);
```

**Async architecture:**
- Worker system for background tasks
- Message-driven UI updates
- Connection pooling for remote clusters
- Priority-based job queue

### TUI Remote Execution

**SSH Runner:**
- Direct SSH connection to remote hosts
- Real-time output streaming via SFTP
- Automatic scratch directory creation
- Environment preservation

**SLURM Runner:**
- Batch job script generation
- Queue status monitoring (squeue)
- Job array support
- Configurable queue/partition/time limits

**Connection Manager:**
- Connection pooling (max 5 concurrent per cluster)
- Automatic cleanup on shutdown
- Credential caching via keyring
- Health checking and reconnection

## Troubleshooting

### CLI Issues

**"associative array: bad array subscript"**
- Cause: Bash < 4.0
- Fix: `brew install bash` (macOS) or use system bash 4.0+

**"crystalOMP: not found"**
- Cause: `CRY23_ROOT` not set
- Fix: `export CRY23_ROOT=~/CRYSTAL23` or source `cry23.bashrc`

### TUI Issues

**"ModuleNotFoundError: No module named 'textual'"**
- Cause: Dependencies not installed
- Fix: `pip install -e ".[dev]"` from `tui/` directory

**"Connection refused" when using SSH runner**
- Cause: SSH host key not in known_hosts OR asyncssh version mismatch
- Fix: Manually SSH to host first, OR check asyncssh>=2.14.0 installed

**"No module named 'CRYSTALpytools'"**
- Cause: Optional analysis dependencies not installed
- Fix: `pip install -e ".[analysis]"` from `tui/` directory (optional - has fallback)

**Path calculation errors**
- Cause: Monorepo structure changed
- Fix: Check `src/core/environment.py` has correct `.parent` levels (6 levels to monorepo root)

## Documentation

**Quick Links:**
- CLI Architecture: `cli/docs/ARCHITECTURE.md`
- CLI Module Details: `cli/CLAUDE.md`
- TUI Project Status: `tui/docs/PROJECT_STATUS.md`
- Security Review: `CODE_REVIEW_FINDINGS.md`
- Integration: `docs/integration.md`
- Installation: `docs/installation.md`
- Contributing: `docs/CONTRIBUTING.md`

## Testing Strategy

### CLI Testing (bats-core)

**Unit tests** mock external commands (gum, mpirun, crystalOMP) to test modules in isolation.

**Integration tests** use mock binaries in `tests/mocks/` for full workflow validation.

**Run tests:**
```bash
cd cli/
bats tests/unit/*.bats              # All unit tests
bats tests/integration/*.bats       # Integration tests
bats tests/unit/cry-parallel_test.bats  # Specific module
```

### TUI Testing (pytest)

**Unit tests** mock database operations and test state transitions.

**Integration tests** test full workflows with mock runners.

**Run tests:**
```bash
cd tui/
pytest                              # All tests
pytest --cov=src --cov-report=html  # With coverage
pytest tests/test_environment.py    # Specific test
```

## Common Patterns

### CLI: Adding a Module

```bash
# 1. Create module file
cat > cli/lib/cry-newmodule.sh << 'EOF'
#!/bin/bash
# Module: cry-newmodule
# Description: What this does
# Dependencies: cry-config, cry-logging

newmodule_function() {
    local arg="$1"
    # Implementation
    return 0
}
EOF

# 2. Write tests
cat > cli/tests/unit/cry-newmodule_test.bats << 'EOF'
#!/usr/bin/env bats
load helpers

@test "newmodule_function works" {
    source "$LIB_DIR/cry-newmodule.sh"
    result=$(newmodule_function "test")
    [ "$result" = "expected" ]
}
EOF

# 3. Load in main script
# Add to bin/runcrystal: cry_require cry-newmodule
```

### TUI: Adding a Screen

```python
# 1. Create screen: src/tui/screens/my_screen.py
from textual.screen import Screen
from textual.widgets import Button

class MyScreen(Screen):
    def compose(self):
        yield Button("Click me", id="my_button")

    def on_button_pressed(self, event):
        self.dismiss()

# 2. Use in app: src/tui/app.py
async def action_show_my_screen(self):
    await self.push_screen(MyScreen())
```

### TUI: Adding a Runner

```python
# 1. Create runner: src/runners/my_runner.py
from src.runners.base import BaseRunner, JobStatus

class MyRunner(BaseRunner):
    async def submit(self, job_id: int, input_file: str, work_dir: Path) -> str:
        # Submit job and return job handle
        return "job_handle"

    async def get_status(self, job_handle: str) -> JobStatus:
        # Query job status
        return JobStatus.RUNNING

    async def get_output(self, job_handle: str) -> str:
        # Retrieve job output
        return "output content"

# 2. Register in database.py runner_types
# 3. Add UI selection in new job modal
```

## Additional Resources

- **Monorepo migration complete:** See `MONOREPO_MIGRATION_COMPLETE.md`
- **Agent workflows:** See `AGENTS.md` for bd/beads integration patterns
- **Tutorial mirror:** `cli/share/tutorials/` (CRYSTAL Solutions documentation)
- **Phase 2 implementation:** See `tui/docs/PHASE2_*.md` for design documents

---

**Remember:** This is a monorepo with two independent tools. CLI is production-ready (100% complete), TUI Phase 2 is feature-complete but has critical security issues that must be addressed before production use. Both share CRYSTAL23 environment but can operate standalone.
