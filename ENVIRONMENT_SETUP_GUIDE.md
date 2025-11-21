# CRYSTAL23 Environment Setup Guide

This guide helps you configure the TUI to work with CRYSTAL23 in different installation scenarios.

## Quick Setup (3 Options)

### Option 1: Development Installation (Default)
If you cloned the repository directly:

```bash
cd ~/CRYSTAL23/crystalmath/tui
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
crystal-tui
```

**How it works:** Auto-detects CRYSTAL23 at `../../` (4 directories up)

---

### Option 2: Pip Installation (Requires Environment Variable)
If you installed the TUI via pip:

```bash
# Step 1: Set environment variable
export CRY23_ROOT=/path/to/CRYSTAL23

# Step 2: Verify it points to correct location
ls $CRY23_ROOT/utils23/cry23.bashrc

# Step 3: Launch TUI
crystal-tui
```

**How it works:** TUI looks for `$CRY23_ROOT/utils23/cry23.bashrc`

---

### Option 3: Custom Path (Programmatic)
For advanced users with custom CRYSTAL23 locations:

```python
from pathlib import Path
from src.core.environment import load_crystal_environment

# Explicit path to cry23.bashrc
config = load_crystal_environment(
    bashrc_path=Path('/custom/path/to/cry23.bashrc')
)
```

---

## Troubleshooting

### Error: "cry23.bashrc not found"

**Solution:** Set the `CRY23_ROOT` environment variable

```bash
# Find where CRYSTAL23 is installed
which crystalOMP          # or locate it manually
ls -la /path/to/CRYSTAL23/utils23/cry23.bashrc

# Set environment variable permanently (add to ~/.bashrc or ~/.zshrc)
export CRY23_ROOT=/path/to/CRYSTAL23

# Test it
echo $CRY23_ROOT/utils23/cry23.bashrc  # Should exist
```

### Error: "crystalOMP executable not found"

**Cause:** CRYSTAL23 binaries not built or incorrect architecture

**Solution:**
1. Verify CRYSTAL23 installation: `ls $CRY23_ROOT/bin/`
2. Check architecture: `uname -m` (arm64, x86_64, etc.)
3. Ensure binaries exist for your platform
4. Rebuild if needed: See CRYSTAL23 documentation

### Error: "Scratch directory is not writable"

**Solution:** Fix permissions or set custom scratch directory

```bash
# Option 1: Fix permissions
chmod 755 ~/tmp_crystal

# Option 2: Set custom scratch directory in cry23.bashrc
export CRY23_SCRDIR=/tmp/crystal_scratch
```

---

## Environment Variables Reference

These are automatically detected from `cry23.bashrc`:

| Variable | Purpose | Example |
|----------|---------|---------|
| `CRY23_ROOT` | CRYSTAL23 installation directory | `/home/user/CRYSTAL23` |
| `CRY23_EXEDIR` | Binary directory | `.../bin/Linux-ifort_i64_omp/v1.0.1` |
| `CRY23_SCRDIR` | Scratch space for calculations | `~/tmp_crystal` |
| `CRY23_UTILS` | Utility scripts directory | `$CRY23_ROOT/utils23` |
| `CRY23_ARCH` | Platform architecture | `Linux-ifort_i64_omp` |
| `VERSION` | CRYSTAL23 version | `v1.0.1` |

---

## Detection Priority

The TUI searches for `cry23.bashrc` in this order:

1. **Explicit Path** (if passed to function)
   ```python
   load_crystal_environment(bashrc_path=Path('/path/to/cry23.bashrc'))
   ```

2. **CRY23_ROOT Environment Variable**
   ```bash
   export CRY23_ROOT=/path/to/CRYSTAL23
   ```

3. **Development Layout** (if cloned locally)
   - Auto-detects: `../../../CRYSTAL23/utils23/cry23.bashrc`

If none are found, you get a clear error with setup instructions.

---

## Permanent Setup

### For bash/zsh Users

Add to `~/.bashrc` or `~/.zshrc`:

```bash
# CRYSTAL23 Configuration
export CRY23_ROOT=/path/to/CRYSTAL23
export PATH="$CRY23_ROOT/crystalmath/cli/bin:$PATH"  # Optional: add CLI to PATH
```

Then reload:
```bash
source ~/.bashrc  # or ~/.zshrc
```

### For Fish Shell Users

Add to `~/.config/fish/config.fish`:

```fish
# CRYSTAL23 Configuration
set -gx CRY23_ROOT /path/to/CRYSTAL23
set -gx PATH "$CRY23_ROOT/crystalmath/cli/bin" $PATH  # Optional
```

---

## Verification

Check that everything is configured correctly:

```bash
# Verify environment variables
echo "CRY23_ROOT: $CRY23_ROOT"
echo "CRY23_EXEDIR: $CRY23_EXEDIR"
echo "CRY23_SCRDIR: $CRY23_SCRDIR"

# Check bashrc can be sourced
bash -c "source $CRY23_ROOT/utils23/cry23.bashrc && echo 'SUCCESS'"

# List available CRYSTAL23 binaries
ls -la $CRY23_EXEDIR/

# Test TUI launch
crystal-tui --help  # Should show help without errors
```

---

## Docker/Container Setup

For containerized deployments, pass the explicit path at runtime:

```python
from pathlib import Path
from src.core.environment import load_crystal_environment

# Load from mounted volume
config = load_crystal_environment(
    bashrc_path=Path('/mnt/crystal23/utils23/cry23.bashrc')
)
```

Or set environment variable in Dockerfile:

```dockerfile
ENV CRY23_ROOT=/opt/CRYSTAL23
```

---

## Questions?

Refer to:
- CRYSTAL23 documentation: See main CRYSTAL23 installation guide
- TUI documentation: `/Users/briansquires/CRYSTAL23/crystalmath/tui/docs/`
- Issue tracker: Check beads issues (bd list)

For technical details on environment detection, see:
`/Users/briansquires/CRYSTAL23/crystalmath/tui/src/core/environment.py`
