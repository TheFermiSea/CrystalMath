# CLAUDE.md - CRYSTAL-TOOLS Monorepo

This file provides guidance to Claude Code when working with the CRYSTAL-TOOLS monorepo.

## Monorepo Overview

This is a **unified repository** containing two complementary tools for CRYSTAL23 DFT calculations:

1. **CLI** (`cli/`) - Production-ready Bash tool for executing calculations
2. **TUI** (`tui/`) - Python terminal UI for interactive job management

**Design Philosophy:** CLI for execution, TUI for management. Both tools work independently but share common resources.

## Quick Navigation

- **CLI Details:** See `cli/CLAUDE.md` for complete CLI documentation
- **TUI Details:** See `tui/docs/PROJECT_STATUS.md` for TUI roadmap
- **Installation:** See `docs/installation.md`
- **Integration:** See `docs/integration.md`
- **Architecture:** See `docs/architecture.md`

## Directory Structure

```
crystalmath/                    # Monorepo root
├── cli/                        # Bash CLI tool (production-ready)
│   ├── bin/runcrystal         # Main executable
│   ├── lib/                   # 9 modular libraries
│   ├── tests/                 # Unit & integration tests
│   ├── docs/                  # CLI documentation
│   └── CLAUDE.md              # Detailed CLI guidance
│
├── tui/                       # Python TUI (Phase 1 MVP)
│   ├── src/                   # Application source
│   │   ├── core/             # Business logic
│   │   ├── tui/              # Textual UI components
│   │   └── runners/          # Job execution backends
│   ├── tests/                 # Test suite
│   ├── pyproject.toml         # Python package config
│   └── docs/                  # TUI documentation
│
├── docs/                      # Shared documentation
│   ├── installation.md
│   ├── integration.md
│   ├── architecture.md
│   └── CONTRIBUTING.md
│
├── .beads/                    # Unified issue tracker
│   └── beads.db              # 34 issues (24 closed)
│
├── examples/                  # Example calculations
└── README.md                  # Project overview
```

## Working with the Monorepo

### When Working on CLI

```bash
cd ~/CRYSTAL23/crystalmath/cli

# Read detailed CLI guidance
cat CLAUDE.md

# Run tests
bats tests/unit/*.bats

# Test execution
bin/runcrystal --explain test_job

# Key files:
# - bin/runcrystal (main script)
# - lib/*.sh (9 modules)
# - tests/ (bats tests)
```

**Important:** CLI is a modular bash system. Read `cli/CLAUDE.md` for module architecture, testing patterns, and development guidelines.

### When Working on TUI

```bash
cd ~/CRYSTAL23/crystalmath/tui

# Install development environment
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Run TUI
crystal-tui

# Run tests (when implemented)
pytest

# Key files:
# - src/tui/app.py (main application)
# - src/core/ (database, environment)
# - src/runners/ (job execution)
# - pyproject.toml (package config)
```

**Important:** TUI uses Textual framework with async/await. See `tui/docs/PROJECT_STATUS.md` for MVP roadmap.

## Development Guidelines

### CLI Development

**Language:** Bash 4.0+ (modular architecture)

**Key Principles:**
- Modules return exit codes (0 = success)
- State managed via CRY_JOB associative array
- Trap-based cleanup guarantees resource cleanup
- Mock external commands in tests

**Adding Features:**
1. Identify which module to modify (see `cli/CLAUDE.md` Module Responsibilities)
2. Follow module template pattern
3. Write unit tests in `cli/tests/unit/`
4. Ensure >80% test coverage

**Testing:**
```bash
cd cli/
bats tests/unit/cry-parallel_test.bats  # Test specific module
bats tests/unit/*.bats                  # Run all unit tests
```

### TUI Development

**Language:** Python 3.10+ (Textual framework)

**Key Principles:**
- Async-first architecture (asyncio)
- Message-driven UI (Textual messages)
- SQLite for persistent job history
- CRYSTALpytools for output parsing

**Adding Features:**
1. UI components → `src/tui/widgets/` or `src/tui/screens/`
2. Business logic → `src/core/`
3. Execution backends → `src/runners/`
4. Update database schema if needed
5. Write tests in `tests/`

**Testing:**
```bash
cd tui/
pytest                              # Run all tests
pytest --cov=src --cov-report=html  # With coverage
black src/ tests/                   # Format code
ruff check src/ tests/              # Lint
mypy src/                           # Type check
```

### Shared Resources

**Environment Configuration:**
- Both tools source `~/CRYSTAL23/cry23.bashrc`
- Common variables: `CRY23_ROOT`, `CRY23_EXEDIR`, `CRY23_SCRDIR`

**Scratch Directory:**
- Shared location: `~/tmp_crystal/`
- CLI: `cry_<job>_<pid>/`
- TUI: `crystal_tui_<job>_<pid>/`

**Issue Tracking:**
```bash
# From monorepo root
bd list                  # Show open issues
bd list --all           # Show all issues (34 total)
bd list --status=closed # Show completed issues (24)
bd show <issue-id>      # Show issue details
bd create "New issue"   # Create issue
```

## Project Status

### CLI: Production Ready ✅

- **Completion:** 24/27 issues closed (89%)
- **Architecture:** Modular (9 library modules)
- **Testing:** 76 tests, 74% pass rate
- **Features:**
  - ✅ Serial/parallel execution
  - ✅ Scratch space management
  - ✅ Auto file staging
  - ✅ Educational --explain mode
  - ⏳ Integration tests
  - ⏳ Documentation polish

### TUI: Phase 1 MVP ⏳

- **Completion:** 0/7 issues closed
- **Architecture:** Textual + SQLite
- **Testing:** Framework ready, tests pending
- **Features:**
  - ✅ Three-panel UI layout
  - ✅ Job database schema
  - ✅ Async execution framework
  - ⏳ Real job runner
  - ⏳ CRYSTALpytools integration
  - ⏳ New job modal
  - ⏳ Environment integration

## Common Development Tasks

### Running CLI Calculations

```bash
cd cli/

# Educational mode (dry run)
bin/runcrystal --explain my_job

# Serial execution
bin/runcrystal my_job

# Parallel execution (14 MPI ranks)
bin/runcrystal my_job 14
```

### Testing TUI Modules

```bash
cd tui/

# Test database
python3 -c "from src.core.database import Database; print('✅ Database imports')"

# Test environment
python3 -c "from src.core.environment import load_crystal_environment; print('✅ Environment imports')"

# Launch TUI (when ready)
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

# Commit
git add .
git commit -m "feat: Add feature description

Detailed explanation of changes.

Closes: crystalmath-xyz
"

# Push
git push origin feature/my-feature
```

## Key Technical Details

### CLI Architecture

**Modular Design:**
- **Main script:** 130 lines (orchestrator only)
- **9 Modules:** config, logging, core, ui, parallel, scratch, stage, exec, help
- **State:** CRY_JOB associative array passed by reference
- **Cleanup:** Trap-based guarantee (`trap 'scratch_cleanup' EXIT`)

**Parallelism:**
- Serial: 1 process × N threads (OpenMP only)
- Hybrid: N ranks × (cores/N) threads (MPI + OpenMP)
- Auto-configured based on system cores

**See `cli/CLAUDE.md` for:**
- Module responsibilities
- Design patterns
- Testing strategies
- Development templates

### TUI Architecture

**Async-First Design:**
- Built on Textual (modern TUI framework)
- Message-driven communication
- Worker system for background tasks
- SQLite for persistence

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

**See `tui/docs/PROJECT_STATUS.md` for:**
- MVP features
- Implementation plan
- Phase 2/3 roadmap

## Testing Strategy

### CLI Testing (bats-core)

**Unit Tests:**
- Mock external commands (gum, mpirun, crystalOMP)
- Test modules in isolation
- Coverage: 76 tests, 74% pass rate

**Integration Tests:**
- Full workflow with mock binaries
- Verify scratch cleanup
- Test error handling

### TUI Testing (pytest)

**Unit Tests (planned):**
- Mock database operations
- Test job state transitions
- Test CRYSTALpytools integration

**UI Tests (planned):**
- Textual snapshot testing
- Event handling verification
- Message flow testing

## Environment Setup

```bash
# Required environment variables
export CRY23_ROOT=~/CRYSTAL23
export CRY23_EXEDIR=$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1
export CRY_SCRATCH_BASE=~/tmp_crystal

# Optional: Add to PATH
export PATH="$HOME/CRYSTAL23/crystalmath/cli/bin:$PATH"
```

## Contributing

See `docs/CONTRIBUTING.md` for:
- Code style guidelines (Bash and Python)
- Testing requirements
- Pull request process
- Issue tracking workflow

## Documentation

**Quick Links:**
- CLI Architecture: `cli/docs/ARCHITECTURE.md`
- TUI Status: `tui/docs/PROJECT_STATUS.md`
- Integration Guide: `docs/integration.md`
- Installation: `docs/installation.md`

## Common Patterns

### CLI: Adding a New Module

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
# Add: cry_require cry-newmodule
```

### TUI: Adding a New Screen

```python
# 1. Create screen file: src/tui/screens/my_screen.py
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

## Troubleshooting

### CLI Issues

**Problem:** "associative array: bad array subscript"
- **Cause:** Bash < 4.0
- **Fix:** Install bash 4.0+ (`brew install bash` on macOS)

**Problem:** "crystalOMP: not found"
- **Cause:** CRY23_ROOT not set
- **Fix:** `export CRY23_ROOT=~/CRYSTAL23`

### TUI Issues

**Problem:** "ModuleNotFoundError: No module named 'textual'"
- **Cause:** Dependencies not installed
- **Fix:** `pip install -e ".[dev]"`

**Problem:** Path calculation errors
- **Cause:** Monorepo structure change
- **Fix:** Check environment.py has 6 `.parent` levels

## Next Steps

**For CLI:**
1. Complete remaining 3 issues
2. Write integration tests
3. Polish documentation
4. Consider cry-docs implementation

**For TUI:**
1. Implement real job runner (Phase 1)
2. Integrate CRYSTALpytools
3. Create new job modal
4. Environment integration
5. Write comprehensive tests

**For Monorepo:**
1. Set up GitHub repository
2. Configure CI/CD workflows
3. Implement CLI → TUI integration
4. Create example calculations

---

**Remember:** CLI is production-ready bash tool, TUI is Python MVP in progress. Both are independent but can integrate via subprocess or shared library patterns. See `docs/integration.md` for integration strategies.
