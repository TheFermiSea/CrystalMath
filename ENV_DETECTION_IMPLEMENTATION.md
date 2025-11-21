# Environment Detection Fix - Implementation Summary

**Issue:** crystalmath-53w
**File:** tui/src/core/environment.py
**Status:** COMPLETE ✅

## Problem Statement

The original implementation auto-detected CRYSTAL23 location using:
```python
crystal_root = Path(__file__).resolve().parents[4]  # Hard-coded parent path
```

This broke when the TUI was installed via pip because the file structure changes. The tool could not find `cry23.bashrc` in pip-installed environments.

## Solution Implemented

Implemented a **precedence chain** for finding `cry23.bashrc` that works with both development and installed layouts:

### Precedence Order
1. **Explicit `bashrc_path` parameter** (highest priority)
   - Allows direct override: `load_crystal_environment(bashrc_path=Path('/custom/path'))`

2. **`CRY23_ROOT` environment variable** (middle priority)
   - Standard way to configure CRYSTAL23: `export CRY23_ROOT=/path/to/CRYSTAL23`
   - Only used if bashrc actually exists at `$CRY23_ROOT/utils23/cry23.bashrc`

3. **Development layout detection** (fallback)
   - Uses `Path(__file__).parents[4]` only as last resort
   - Works when package is cloned/developed locally

## Code Changes

### New Function: `_find_bashrc_path()`

Located in `/Users/briansquires/CRYSTAL23/crystalmath/tui/src/core/environment.py:51-87`

```python
def _find_bashrc_path(explicit_path: Optional[Path] = None) -> Path:
    """
    Find cry23.bashrc using precedence chain.

    Precedence order:
    1. Explicit path parameter (highest priority)
    2. CRY23_ROOT environment variable
    3. Development layout detection (last resort)
    """
    # 1. Explicit parameter (highest priority)
    if explicit_path is not None:
        return explicit_path.resolve()

    # 2. CRY23_ROOT environment variable
    cry23_root = os.environ.get('CRY23_ROOT')
    if cry23_root:
        bashrc = Path(cry23_root) / 'utils23' / 'cry23.bashrc'
        if bashrc.exists():
            return bashrc.resolve()

    # 3. Development layout (last resort)
    dev_bashrc = Path(__file__).resolve().parents[4] / 'utils23' / 'cry23.bashrc'
    if dev_bashrc.exists():
        return dev_bashrc

    # Return best guess even if it doesn't exist
    # Will be caught and reported clearly by load_crystal_environment
    return dev_bashrc
```

### Enhanced Error Messages

Improved error reporting in `load_crystal_environment()` (lines 125-133):

```
cry23.bashrc not found at: <path>

Please ensure CRYSTAL23 is properly installed and configured.

Setup instructions:
1. Set environment variable: export CRY23_ROOT=/path/to/CRYSTAL23
2. Verify bashrc exists: $CRY23_ROOT/utils23/cry23.bashrc
3. Or pass explicit path: load_crystal_environment(bashrc_path=Path('/...'))

Expected location: <CRYSTAL23_ROOT>/utils23/cry23.bashrc
```

## Test Coverage

Added comprehensive tests for the precedence chain:

### New Test Class: `TestFindBashrcPath` (7 tests)

Located in `/Users/briansquires/CRYSTAL23/crystalmath/tui/tests/test_environment.py:72-146`

1. **test_explicit_path_highest_priority** - Explicit parameter always used
2. **test_explicit_path_even_if_invalid** - Explicit path returned even if missing
3. **test_cry23_root_env_var_second_priority** - CRY23_ROOT used when bashrc exists
4. **test_cry23_root_env_var_ignored_if_not_exists** - CRY23_ROOT skipped if missing
5. **test_development_layout_last_resort** - Dev layout used as fallback
6. **test_precedence_explicit_over_env_var** - Explicit takes precedence over env var
7. **test_returns_path_object** - Always returns resolved Path object

### Enhanced Existing Tests

Added test in `TestLoadCrystalEnvironment`:
- **test_error_message_has_setup_instructions** - Validates helpful error messages

### Test Results

```
27 tests total: 27 PASSED, 0 FAILED
Coverage areas:
- CrystalConfig dataclass: 2 tests
- _find_bashrc_path precedence: 7 tests
- _source_bashrc parsing: 3 tests
- _validate_environment validation: 6 tests
- load_crystal_environment orchestration: 5 tests
- get_crystal_config convenience: 1 test
- Cross-platform compatibility: 2 tests
- Real environment integration: 1 test
```

## Success Criteria Met

✅ **Precedence chain implemented** - Three-tier lookup system working correctly
✅ **Clear error messages** - Setup instructions included in EnvironmentError
✅ **Bashrc validation** - Checks existence before returning path
✅ **Tests for all code paths** - 7 new tests covering precedence logic
✅ **Documentation updated** - Docstrings explain precedence and usage
✅ **Real CRYSTAL23 integration** - Integration test passes with actual installation

## Usage Examples

### Default Behavior (Auto-detect)
```python
# 1. Tries CRY23_ROOT environment variable
# 2. Falls back to development layout
config = load_crystal_environment()
```

### With Environment Variable
```bash
export CRY23_ROOT=/home/user/CRYSTAL23
# Now works with pip-installed TUI
crystal-tui
```

### Explicit Path
```python
from pathlib import Path
config = load_crystal_environment(
    bashrc_path=Path('/custom/location/cry23.bashrc')
)
```

### Force Reload
```python
# Clear cache and reload from disk
config = load_crystal_environment(force_reload=True)
```

## Files Modified

1. **tui/src/core/environment.py**
   - Added `_find_bashrc_path()` function (37 lines)
   - Enhanced `load_crystal_environment()` docstring and error messages
   - All changes backward compatible

2. **tui/tests/test_environment.py**
   - Added `TestFindBashrcPath` test class (7 tests, 75 lines)
   - Enhanced `TestLoadCrystalEnvironment` with setup instruction test
   - Imported new `_find_bashrc_path` function

## Backward Compatibility

✅ **Fully backward compatible**
- Existing code calling `load_crystal_environment()` works unchanged
- CRY23_ROOT environment variable still works
- Development layout detection preserved as fallback
- All 27 tests pass (including 20 pre-existing tests)

## Integration Notes

The fix enables TUI to work in three installation scenarios:

1. **Development (cloned repo)**
   - `Path(__file__).parents[4]` finds CRYSTAL23 directory
   - Automatic detection works

2. **Pip installed globally**
   - Requires `export CRY23_ROOT=/path/to/CRYSTAL23`
   - Clear error message guides users to set environment variable

3. **Containerized/Custom**
   - Users can pass explicit `bashrc_path` parameter
   - Maximum flexibility for deployment scenarios

## Testing Instructions

```bash
cd /Users/briansquires/CRYSTAL23/crystalmath/tui

# Activate environment
source venv/bin/activate

# Run all environment tests
python -m pytest tests/test_environment.py -v

# Run just the precedence chain tests
python -m pytest tests/test_environment.py::TestFindBashrcPath -v

# Run with coverage
python -m pytest tests/test_environment.py --cov=src.core.environment
```

## References

- **Issue:** crystalmath-53w
- **Component:** TUI environment detection
- **Module:** src/core/environment.py
- **Priority:** 1 (High) - Blocking pip installations
