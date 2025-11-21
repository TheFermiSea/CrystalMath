# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CRYSTAL-TOOLS is a unified monorepo containing complementary tools for CRYSTAL23 quantum chemistry DFT calculations:

1. **CLI** (`cli/`) - Production-ready Bash tool for executing calculations (89% complete)
2. **TUI** (`tui/`) - Python terminal UI for interactive job management (Phase 1 MVP in progress)

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

# Setup development environment
python3 -m venv .venv
source .venv/bin/activate  # or: .venv/bin/activate.fish (fish shell)
pip install -e ".[dev]"

# Launch interactive interface
crystal-tui

# Run tests (when implemented)
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
bd list --all              # Show all issues (34 total)
bd list --status=closed    # Show completed (24)
bd show <issue-id>         # Show details
bd create "Issue title"    # Create new issue
```

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
- `src/core/` - Business logic (database, environment)
- `src/tui/` - Textual UI components (app, screens, widgets)
- `src/runners/` - Job execution backends (local, future: remote)

**Key Technologies:**
- Textual framework (async TUI)
- SQLite for job history
- CRYSTALpytools for output parsing
- Async/await architecture

**Data Model:**
```python
Job {
    id: int
    name: str
    status: pending|running|completed|failed
    input_content: str (d12 file)
    results_json: str (parsed results)
    work_dir: Path
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
4. Update database schema if needed
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
- **Completion:** 24/27 beads issues closed (89%)
- **Architecture:** Modular (9 library modules)
- **Testing:** 76 tests, 74% pass rate
- **Features:** Serial/parallel execution, scratch management, auto file staging, --explain mode

### TUI: Phase 1 MVP ⏳
- **Completion:** 0/7 beads issues closed
- **Architecture:** Textual + SQLite
- **Implemented:** Three-panel UI, job database, async framework
- **Planned:** Real job runner, CRYSTALpytools integration, new job modal

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

### TUI Job Database

**Schema:**
```sql
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    input_content TEXT,
    results_json TEXT,
    work_dir TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

**Async architecture:**
- Worker system for background tasks
- Message-driven UI updates
- Real-time log streaming (planned)

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

**Path calculation errors**
- Cause: Monorepo structure changed
- Fix: Check `src/core/environment.py` has correct `.parent` levels (6 levels to monorepo root)

## Documentation

**Quick Links:**
- CLI Architecture: `cli/docs/ARCHITECTURE.md`
- CLI Module Details: `cli/CLAUDE.md`
- TUI Roadmap: `tui/docs/PROJECT_STATUS.md`
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

**Unit tests** (planned) will mock database operations and test state transitions.

**UI tests** (planned) will use Textual snapshot testing for UI components.

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

## Additional Resources

- **Monorepo migration complete:** See `MONOREPO_MIGRATION_COMPLETE.md`
- **Agent workflows:** See `AGENTS.md` for bd/beads integration patterns
- **Tutorial mirror:** `cli/share/tutorials/` (CRYSTAL Solutions documentation)

---

**Remember:** This is a monorepo with two independent tools. CLI is production-ready Bash (89% complete), TUI is Python MVP in progress (Phase 1). Both share CRYSTAL23 environment but can operate standalone.
