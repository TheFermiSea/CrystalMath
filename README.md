# CRYSTAL-TOOLS: CLI + TUI for CRYSTAL23 DFT

A unified toolkit for CRYSTAL23 quantum chemistry calculations, combining a production-grade bash CLI for execution with a modern Python TUI for interactive management.

## Overview

**Philosophy:** CLI for execution, TUI for management.

This monorepo contains two complementary tools:

1. **CLI** (`cli/`) - Bash tool for running CRYSTAL23 calculations
   - Production-grade modular architecture
   - Automatic parallelism (MPI/OpenMP hybrid)
   - Scratch space management
   - Visual feedback with gum
   - Educational `--explain` mode

2. **TUI** (`tui/`) - Python terminal UI for job management
   - Interactive job monitoring
   - Real-time log streaming
   - Database-backed job history
   - Integration with CRYSTALpytools
   - Built on Textual framework

## Quick Start

### CLI Tool (Execution)

```bash
# Navigate to cli directory
cd cli/

# Set environment (if not already set)
export CRY23_ROOT=~/CRYSTAL23
export CRY_SCRATCH_BASE=~/tmp_crystal

# Run a calculation (serial mode with auto-threading)
bin/runcrystal my_calculation

# Run with MPI parallelism (14 ranks)
bin/runcrystal my_calculation 14

# Educational mode (show plan without running)
bin/runcrystal my_calculation --explain

# Show help
bin/runcrystal --help
```

### TUI Tool (Management)

```bash
# Navigate to tui directory
cd tui/

# Install (development mode)
pip install -e ".[dev]"

# Launch interactive interface
crystal-tui

# Keyboard shortcuts:
# n - Create new job
# r - Run selected job
# s - Stop running job
# q - Quit
```

## Project Status

### CLI Tool: Production Ready ✅

**Completion:** 24/27 beads issues closed (89%)

**Features:**
- ✅ Modular architecture (9 library modules)
- ✅ Hybrid MPI/OpenMP parallelism
- ✅ Scratch space management with automatic cleanup
- ✅ File staging (input + auxiliary files)
- ✅ Visual UI with gum integration
- ✅ Educational `--explain` mode
- ✅ Comprehensive unit tests (76 tests, 74% pass rate)
- ⏳ Integration tests (planned)
- ⏳ Final documentation polish

**Architecture:** Refactored from 372-line monolith to thin 130-line orchestrator with 9 specialized modules.

### TUI Tool: MVP Phase ⏳

**Completion:** 0/7 beads issues closed (Phase 1 in progress)

**Implemented:**
- ✅ Complete project structure
- ✅ SQLite database with ORM
- ✅ Three-panel Textual layout
- ✅ Job list with cursor navigation
- ✅ Real-time log streaming
- ✅ Worker system for async execution
- ✅ Message-based architecture

**Planned (Phase 1):**
- ⏳ Real CRYSTAL job runner
- ⏳ CRYSTALpytools integration
- ⏳ New job modal screen
- ⏳ Environment integration (cry23.bashrc)
- ⏳ Enhanced status display
- ⏳ Results summary view
- ⏳ Comprehensive unit tests

**Future (Phase 2-3):**
- Remote execution (SSH/SLURM)
- Batch job management
- Visualization (band structure, DOS)
- Workflow chaining
- Template library

## Repository Structure

```
crystalmath/
├── README.md                    # This file
├── cli/                         # Bash CLI tool
│   ├── bin/runcrystal          # Main executable
│   ├── lib/                    # Modular library
│   │   ├── cry-config.sh       # Configuration
│   │   ├── cry-parallel.sh     # Parallelism logic
│   │   ├── cry-scratch.sh      # Scratch management
│   │   ├── cry-stage.sh        # File staging
│   │   ├── cry-exec.sh         # Execution
│   │   └── ...
│   ├── tests/                  # Unit & integration tests
│   ├── share/tutorials/        # Documentation mirror
│   └── docs/                   # Architecture docs
│
├── tui/                        # Python TUI
│   ├── src/crystal_tui/        # Application source
│   │   ├── tui/               # Textual components
│   │   ├── core/              # Business logic
│   │   └── runners/           # Job execution
│   ├── tests/                  # Test suite
│   ├── pyproject.toml          # Python package config
│   └── docs/                   # TUI documentation
│
├── .beads/                     # Unified issue tracker
│   └── beads.db               # 34 issues (24 closed)
│
├── docs/                       # Shared documentation
├── examples/                   # Example calculations
└── .github/workflows/          # CI/CD pipelines
```

## Key Benefits of Monorepo

- **Single `git clone`** gets both tools
- **Unified issue tracking** with beads (34 issues across both projects)
- **Shared CI/CD** and documentation
- **CLI and TUI remain independent** - each can be used separately
- **Coordinated development** - changes tested together

## Requirements

### CLI Tool

- Bash 4.0+ (associative arrays)
- CRYSTAL23 installation (`CRY23_ROOT`)
- Optional: gum for visual feedback (auto-installs)
- Optional: mpirun for parallel execution

### TUI Tool

- Python 3.10+
- CRYSTAL23 executable in PATH
- CRYSTALpytools
- Textual
- SQLite (included with Python)

## Documentation

- **CLI:** See `cli/docs/ARCHITECTURE.md` for detailed design
- **TUI:** See `tui/docs/PROJECT_STATUS.md` for roadmap
- **Tutorials:** See `cli/share/tutorials/` for CRYSTAL documentation

## Integration

The TUI can optionally use the CLI as its execution backend:
- TUI manages jobs, history, and visualization
- CLI handles the actual CRYSTAL execution
- Both share the same CRYSTAL23 environment

## Development

```bash
# CLI development
cd cli/
bats tests/unit/*.bats          # Run unit tests
bats tests/integration/*.bats   # Run integration tests

# TUI development
cd tui/
pip install -e ".[dev]"         # Install dev dependencies
pytest                          # Run tests (when implemented)
black src/ tests/               # Format code
ruff check src/ tests/          # Linting
mypy src/                       # Type checking
```

## Contributing

Both tools accept contributions! See:
- `cli/docs/CONTRIBUTING.md` for CLI contribution guidelines
- `tui/README.md` for TUI development info

## Issue Tracking

This repository uses [beads](https://github.com/beadsinc/beads) for issue tracking:

```bash
# List all issues
bd list --all

# Show open issues
bd list

# Show closed issues
bd list --status=closed

# Create new issue
bd create "Issue title"

# View issue details
bd show <issue-id>
```

**Current Stats:** 34 total issues (24 closed, 10 open)

## License

MIT License

## Support

- **CLI Issues:** Tagged with source_repo="." (original CRY_CLI)
- **TUI Issues:** Tagged with labels=[mvp, phase-1, ...]
- **GitHub Issues:** (Coming soon after git repository setup)

---

**Status:** Monorepo migration complete ✅ | CLI production-ready ✅ | TUI Phase 1 in progress ⏳
