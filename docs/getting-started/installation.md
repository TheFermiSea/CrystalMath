# Installation Guide

This guide covers installation of both the CLI and TUI tools in the CRYSTAL-TOOLS monorepo.

## Prerequisites

### Common Requirements

1. **CRYSTAL23 Installation**
   - Set `CRY23_ROOT` to your CRYSTAL23 installation directory
   - Ensure `crystalOMP` (and optionally `PcrystalOMP`) are available
   - Typical location: `$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1/`

2. **Environment Setup**
   ```bash
   # Add to your ~/.bashrc or ~/.zshrc
   export CRY23_ROOT=~/CRYSTAL23
   export CRY_BIN_DIR=$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1
   export PATH=$CRY_BIN_DIR:$PATH

   # Optional: Custom scratch location (default: ~/tmp_crystal)
   export CRY_SCRATCH_BASE=/fast/scratch/crystal
   ```

3. **Clone the Repository**
   ```bash
   git clone <repository-url> crystalmath
   cd crystalmath
   ```

## CLI Tool Installation

### Requirements

- **Bash 4.0+** (for associative arrays)
  - Check version: `bash --version`
  - macOS users: Install bash 5.x via Homebrew: `brew install bash`
- **Optional:** gum for visual feedback (auto-installs on first run)
- **Optional:** MPI runtime (Intel MPI, OpenMPI) for parallel execution

### Installation Steps

1. **Navigate to CLI directory**
   ```bash
   cd cli/
   ```

2. **Make runcrystal executable** (if needed)
   ```bash
   chmod +x bin/runcrystal
   ```

3. **Add to PATH** (optional, for convenience)
   ```bash
   # Add to ~/.bashrc or ~/.zshrc
   export PATH="$HOME/CRYSTAL23/crystalmath/cli/bin:$PATH"
   ```

4. **Verify installation**
   ```bash
   bin/runcrystal --help
   ```

### Testing the CLI

Run a simple test calculation:

```bash
# Create a test input file
cat > test.d12 << 'EOF'
test calculation
CRYSTAL
0 0 0
1
1.0
1 1
END
8 3
END
SHRINK
8 8
TOLDEE
8
END
END
EOF

# Test in dry-run mode first
bin/runcrystal test --explain

# Run the calculation (if CRYSTAL23 is properly configured)
bin/runcrystal test
```

Expected output: Visual feedback, scratch directory creation, file staging, and calculation execution.

## Python Packages (uv workspace)

This project uses **uv workspaces** for unified Python dependency management. This is the
recommended installation method for both the core library and TUI.

### Requirements

- **Python 3.10+** — Check version: `python3 --version`
- **uv** — Install from [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/)

### Installation Steps

1. **From the repository root** (`crystalmath/`):
   ```bash
   # Install core + TUI packages
   uv sync

   # Include optional extras (AiiDA, Materials Project, dev tools)
   uv sync --all-extras
   ```

2. **Verify installation**:
   ```bash
   # Check Python API
   uv run python -c "from crystalmath.api import CrystalController; print('OK')"

   # Check CLI
   uv run crystal --help

   # Launch TUI
   uv run crystal-tui
   ```

3. **Run tests**:
   ```bash
   uv run pytest python/tests/    # Core package tests
   uv run pytest tui/tests/       # TUI tests
   ```

### Workspace Packages

| Package | Location | Description |
|---------|----------|-------------|
| `crystalmath` | `python/` | Core library (models, API, templates, workflows, VASP tools) |
| `crystal-tui` | `tui/` | Textual-based TUI application (depends on crystalmath) |

### Legacy pip Installation

If you prefer pip over uv:

```bash
cd crystalmath/
pip install -e "python/[dev]"    # Core package
pip install -e "tui/[dev]"       # TUI (after core)
```

### Testing the TUI

Launch the interactive interface:

```bash
uv run crystal-tui
```

Expected behavior:
- Multi-tab interface (Jobs, Editor, Results, Log)
- Empty job list on first run
- Press `q` to quit

## Installation Verification

### CLI Verification

Run the built-in tests:

```bash
cd cli/

# Install bats-core if not already installed
# macOS: brew install bats-core
# Linux: Check your package manager or install from GitHub

# Run unit tests
bats tests/unit/*.bats

# Expected: 56/76 tests passing (74%)
```

### Python Package Verification

Check package installation:

```bash
# From repository root
uv run python -c "from crystalmath.api import CrystalController; print('Core OK')"
uv run python -c "from crystalmath.models import JobSubmission; print('Models OK')"
uv run pytest python/tests/ -x -q     # Core tests
uv run pytest tui/tests/ -x -q        # TUI tests
```

## Troubleshooting

### CLI Issues

**Problem:** "bash: associative array: bad array subscript"
- **Cause:** Bash version < 4.0
- **Solution:** Install bash 4.0+ (macOS: `brew install bash`)

**Problem:** "gum: command not found"
- **Cause:** gum not installed
- **Solution:** Let runcrystal auto-install it, or install manually:
  ```bash
  # macOS
  brew install gum

  # Linux (using go)
  go install github.com/charmbracelet/gum@latest
  ```

**Problem:** "crystalOMP: not found"
- **Cause:** CRYSTAL23 not in PATH or CRY23_ROOT not set
- **Solution:** Set environment variables correctly (see Prerequisites)

**Problem:** Tests fail with "set: unbound variable"
- **Cause:** Mock system needs bash 4.0+ features
- **Solution:** Use bash 4.0+ for running tests

### Python / TUI Issues

**Problem:** "ModuleNotFoundError: No module named 'textual'"
- **Cause:** Dependencies not installed
- **Solution:** Run `uv sync` from the repository root

**Problem:** "No module named 'crystalmath'"
- **Cause:** Package not installed in current environment
- **Solution:** Run `uv sync` from the repository root, then use `uv run`

**Problem:** Database permission errors
- **Cause:** Incorrect file permissions
- **Solution:** Check permissions on `.crystal_tui.db` and parent directory

**Problem:** TUI crashes on startup
- **Cause:** Terminal incompatibility or Python version
- **Solution:**
  - Ensure Python 3.10+
  - Try different terminal emulator
  - Check `uv run textual diagnose` for compatibility info

## Optional: System-Wide Installation

### CLI System-Wide

```bash
# Copy to /usr/local/bin (requires sudo)
cd cli/
sudo cp -r lib/ /usr/local/lib/crystal-cli/
sudo cp bin/runcrystal /usr/local/bin/

# Or create symlink (preferred)
sudo ln -s $(pwd)/bin/runcrystal /usr/local/bin/runcrystal
```

### Python Packages System-Wide

```bash
# Install from repository root
cd crystalmath/
pip install "python/"
pip install "tui/"

# Now crystal-tui and crystal CLI available system-wide
crystal --help
crystal-tui
```

## Development Setup

### CLI Development

```bash
cd cli/

# Install bats-core for testing
brew install bats-core  # macOS
# or see https://github.com/bats-core/bats-core#installation

# Install shellcheck for linting
brew install shellcheck  # macOS
```

### Python Development

```bash
# From repository root - installs everything including dev tools
uv sync --all-extras

# Run linting and formatting
uv run ruff check python/ tui/
uv run ruff format python/ tui/

# Run all tests
uv run pytest
```

## Next Steps

- **CLI:** Read `cli/docs/ARCHITECTURE.md` to understand the modular design
- **TUI:** Read `tui/docs/PROJECT_STATUS.md` to see the development roadmap
- **Integration:** Read `docs/integration.md` to learn how CLI and TUI work together
- **Contributing:** Read `docs/CONTRIBUTING.md` if you want to contribute

## Environment Template

Copy this to your `~/.bashrc` or `~/.zshrc`:

```bash
# CRYSTAL-TOOLS Environment
export CRY23_ROOT=~/CRYSTAL23
export CRY_BIN_DIR=$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1
export CRY_SCRATCH_BASE=~/tmp_crystal

# Add to PATH
export PATH="$CRY23_ROOT/crystalmath/cli/bin:$CRY_BIN_DIR:$PATH"

# Python tools (using uv from the crystalmath directory)
# uv sync && uv run crystal-tui
```

Reload your shell:
```bash
source ~/.bashrc  # or source ~/.zshrc
```

---

**Installation complete!** Proceed to the [Quick Start](../README.md#quick-start) section to begin using the tools.
