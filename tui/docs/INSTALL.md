# Installation Guide for CRYSTAL-TUI

## Prerequisites

1. **Python 3.10 or higher**
   ```bash
   python3 --version
   ```

2. **CRYSTAL23 Installation**
   - Your existing CRYSTAL23 installation at `/Users/briansquires/CRYSTAL23`
   - The `crystalOMP` executable should be accessible

3. **pip** (Python package installer)

## Installation Steps

### Step 1: Navigate to the project

```bash
cd /Users/briansquires/CRYSTAL23/bin/crystal-tui
```

### Step 2: Create a virtual environment (recommended)

```bash
python3 -m venv venv
source venv/bin/activate  # On macOS/Linux
```

### Step 3: Install the package

**For development (recommended for now):**
```bash
pip install -e ".[dev]"
```

**For regular use:**
```bash
pip install .
```

This will install:
- `textual` - The TUI framework
- `rich` - Enhanced terminal formatting
- `CRYSTALpytools` - CRYSTAL file I/O
- `pymatgen` - Structure manipulation
- `ase` - Atomic Simulation Environment
- All other dependencies

### Step 4: Verify installation

```bash
crystal-tui --help
```

If you see the help output, the installation was successful!

## Quick Test

1. Create a test project directory:
```bash
mkdir ~/test_crystal_project
cd ~/test_crystal_project
```

2. Launch CRYSTAL-TUI:
```bash
crystal-tui
```

You should see the TUI interface with:
- Job list panel (left)
- Log/Input/Results tabs (right)
- Keyboard shortcuts in the footer

## Troubleshooting

### Issue: `crystal-tui` command not found

**Solution**: Make sure you activated the virtual environment:
```bash
cd /Users/briansquires/CRYSTAL23/bin/crystal-tui
source venv/bin/activate
```

Or add the installation path to your PATH.

### Issue: Import errors for CRYSTALpytools

**Solution**: CRYSTALpytools may need to be installed separately:
```bash
pip install CRYSTALpytools
```

### Issue: Textual not found

**Solution**: Ensure all dependencies are installed:
```bash
pip install -r requirements.txt  # If you create one
# Or
pip install textual rich pymatgen ase
```

## Next Steps

Once installed, see the main [README.md](README.md) for usage instructions and keyboard shortcuts.

## Updating

To update to the latest version:

```bash
cd /Users/briansquires/CRYSTAL23/bin/crystal-tui
git pull  # If using git
pip install -e ".[dev]"  # Reinstall
```

## Uninstalling

```bash
pip uninstall crystal-tui
```

Or simply delete the virtual environment:
```bash
rm -rf venv
```
