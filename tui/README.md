# CRYSTAL-TUI: A Modern Terminal User Interface for CRYSTAL DFT

A powerful, user-friendly TUI workstation for managing CRYSTAL23 quantum chemistry calculations.

## Features

### Phase 1: MVP (Current)
- ✅ Local job execution and monitoring
- ✅ Real-time log streaming
- ✅ Job history with SQLite database
- ✅ Direct input file editing
- ✅ Automatic output parsing with CRYSTALpytools
- ✅ Keyboard-driven workflow

### Phase 2: Planned
- 🔄 Remote cluster execution (SSH/SLURM)
- 🔄 Batch job management
- 🔄 Basic visualization (band structure, DOS)
- 🔄 Job templates library

### Phase 3: Future
- 📋 Workflow chaining (geometry opt → properties)
- 📋 Advanced in-terminal visualization
- 📋 Multi-project management
- 📋 Integration with aiida-crystal-dft

## Installation

```bash
# Clone or navigate to the project
cd /path/to/crystal-tui

# Install in development mode
pip install -e ".[dev]"

# Or install for use
pip install .
```

## Quick Start

```bash
# Navigate to your project directory
mkdir my_calculations && cd my_calculations

# Launch the TUI
crystal-tui

# Keyboard shortcuts:
# n - Create new job
# r - Run selected job
# s - Stop running job
# q - Quit
# Tab - Navigate between panes
```

## Requirements

- Python 3.10+
- CRYSTAL23 executable (crystalOMP) in PATH or configured in cry23.bashrc
- CRYSTALpytools
- Textual

## Architecture

```
crystal-tui/
├── src/
│   ├── tui/          # Textual UI components
│   │   ├── app.py          # Main TUI application
│   │   ├── screens/        # Modal screens (new job, etc.)
│   │   └── widgets/        # Custom widgets
│   ├── core/         # Business logic
│   │   ├── database.py     # SQLite interface
│   │   ├── job.py          # Job state management
│   │   └── project.py      # Project management
│   └── runners/      # Job execution backends
│       ├── local.py        # Local subprocess runner
│       └── remote.py       # SSH/SLURM runner (Phase 2)
├── tests/
└── docs/
```

## Project Structure

When you run crystal-tui in a directory, it creates:

```
your_project/
├── .crystal_tui.db          # Job history database
├── calculations/
│   ├── 1_job_name/
│   │   ├── input.d12
│   │   └── output.out
│   └── 2_another_job/
│       ├── input.d12
│       └── output.out
└── templates/               # Input templates (Phase 2)
```

## Integration with Existing Tools

- **CRYSTALpytools**: Used for all input generation and output parsing
- **Pymatgen/ASE**: Structure manipulation and conversion
- **CRYSTAL23**: Direct integration with your existing installation

## Development

```bash
# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black src/ tests/
ruff check src/ tests/

# Type checking
mypy src/
```

## Contributing

This project is in active development. Contributions welcome!

## License

MIT License
