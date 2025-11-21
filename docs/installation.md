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

## TUI Tool Installation

### Requirements

- **Python 3.10+**
  - Check version: `python3 --version`
- **pip** (Python package installer)
- **CRYSTALpytools** (for output parsing)
- **Textual** (TUI framework)

### Installation Steps

1. **Navigate to TUI directory**
   ```bash
   cd tui/
   ```

2. **Create virtual environment** (recommended)
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install package**

   **Development mode** (recommended for contributors):
   ```bash
   pip install -e ".[dev]"
   ```

   **Production mode**:
   ```bash
   pip install .
   ```

4. **Verify installation**
   ```bash
   crystal-tui --version  # (when --version is implemented)
   which crystal-tui
   ```

### Testing the TUI

Launch the interactive interface:

```bash
# Make sure you're in a directory where you want to create calculations
mkdir -p ~/crystal_projects/test_project
cd ~/crystal_projects/test_project

# Launch TUI
crystal-tui
```

Expected behavior:
- Three-panel interface (Jobs, Log, Results)
- Empty job list (no calculations yet)
- Press `n` to create a new job (when implemented)
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

### TUI Verification

Check package installation:

```bash
cd tui/

# Verify Python package is installed
pip show crystal-tui

# Run tests (when implemented)
pytest

# Check database creation
ls ~/.crystal_tui.db  # Should exist after first run
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

### TUI Issues

**Problem:** "ModuleNotFoundError: No module named 'textual'"
- **Cause:** Dependencies not installed
- **Solution:** Run `pip install -e ".[dev]"` or `pip install textual`

**Problem:** "No module named 'CRYSTALpytools'"
- **Cause:** CRYSTALpytools not installed
- **Solution:** `pip install CRYSTALpytools`

**Problem:** Database permission errors
- **Cause:** Incorrect file permissions
- **Solution:** Check permissions on `.crystal_tui.db` and parent directory

**Problem:** TUI crashes on startup
- **Cause:** Terminal incompatibility or Python version
- **Solution:**
  - Ensure Python 3.10+
  - Try different terminal emulator
  - Check `textual diagnose` for compatibility info

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

### TUI System-Wide

```bash
# Install without virtual environment
cd tui/
sudo pip install .

# Now crystal-tui available system-wide
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

### TUI Development

```bash
cd tui/

# Install with development dependencies
pip install -e ".[dev]"

# Install pre-commit hooks (if configured)
pre-commit install

# Install additional dev tools
pip install black ruff mypy pytest-cov
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

# Optional: Python virtual environment for TUI
alias crystal-tui-dev='source ~/CRYSTAL23/crystalmath/tui/venv/bin/activate && crystal-tui'
```

Reload your shell:
```bash
source ~/.bashrc  # or source ~/.zshrc
```

---

**Installation complete!** Proceed to the [Quick Start](../README.md#quick-start) section to begin using the tools.
