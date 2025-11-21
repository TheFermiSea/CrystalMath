# Dependency Cleanup Analysis (crystalmath-3q8)

## Summary

Removed unused hard dependencies and reorganized pyproject.toml to reduce installation size by ~500MB and improve security by eliminating unnecessary packages.

**Result:** 6 core dependencies (down from 10), with 3 analysis packages moved to optional extras.

## Changes Made

### Core Dependencies (Required)
```toml
dependencies = [
    "textual>=0.50.0",      # Terminal UI framework
    "rich>=13.0.0",         # Rich text and tables
    "jinja2>=3.1.0",        # Template engine (used in templates.py)
    "pyyaml>=6.0.0",        # YAML parsing (used in templates.py)
    "asyncssh>=2.14.0",     # SSH/SFTP for remote execution (Phase 2)
    "keyring>=24.0.0",      # Secure credential storage (Phase 2)
]
```

### Optional Dependencies (Analysis)
```toml
[project.optional-dependencies]
analysis = [
    "CRYSTALpytools>=2023.0.0",
    "pymatgen>=2023.0.0",
    "ase>=3.22.0",
]
```

## Detailed Analysis

### Packages Removed from Core Dependencies

#### 1. CRYSTALpytools (~200MB)
- **Status:** OPTIONAL (not imported in 2 out of 3 locations)
- **Usage:** Imported in `src/runners/local.py` and `src/tui/widgets/results_summary.py`
- **Finding:** Code implements graceful fallback parser (lines 355-369 of local.py)
- **Decision:** Move to optional `[analysis]` extras
- **Impact:** Minimal - fallback parser works without it

**Fallback Implementation Example:**
```python
try:
    from CRYSTALpytools.crystal_io import Crystal_output
    cry_out = Crystal_output(str(output_file))
    # ... parse with CRYSTALpytools
except ImportError:
    # Fallback: Manual parsing if CRYSTALpytools not available
    warnings.append("CRYSTALpytools not available, using fallback parser")
    final_energy, convergence_status, parse_errors = self._fallback_parse(output_file)
```

#### 2. pymatgen (~150MB)
- **Status:** COMPLETELY UNUSED
- **Grep Results:** No imports found in src/ or tests/
- **Decision:** Move to optional `[analysis]` extras
- **Impact:** None - can be installed separately if needed

#### 3. ase (~150MB)
- **Status:** COMPLETELY UNUSED
- **Grep Results:** No imports found in src/ or tests/
- **Decision:** Move to optional `[analysis]` extras
- **Impact:** None - can be installed separately if needed

#### 4. toml (~5MB)
- **Status:** COMPLETELY UNUSED
- **Grep Results:** No imports found in src/ or tests/
- **Note:** Python 3.11+ has built-in `tomllib` module
- **Decision:** REMOVED (not needed for this project)
- **Impact:** None - no functionality lost

### Packages Retained (Required)

#### 1. textual (TUI Framework)
- **Used in:** All UI screens, main app
- **Status:** REQUIRED

#### 2. rich (Text Formatting)
- **Used in:** TUI widgets, logging, output formatting
- **Status:** REQUIRED

#### 3. jinja2 (Template Engine)
- **Used in:** `src/core/templates.py` (lines 15-17)
- **Status:** REQUIRED for Phase 2 template system
- **Imports:**
  ```python
  from jinja2 import FileSystemLoader, Template as Jinja2Template, TemplateSyntaxError
  from jinja2.sandbox import SandboxedEnvironment
  ```

#### 4. pyyaml (YAML Parser)
- **Used in:** `src/core/templates.py` (line 15)
- **Status:** REQUIRED for YAML configuration files
- **Import:** `import yaml`

#### 5. asyncssh (SSH Client)
- **Used in:**
  - `src/core/connection_manager.py` (lines 20, 45, 201, 216, 222, 262, 272, 280, 293)
  - `src/runners/ssh_runner.py` (lines 14, 204, 393, 618, 661)
- **Status:** REQUIRED for Phase 2 remote execution
- **Phase:** Currently in development (Phase 2)

#### 6. keyring (Credential Storage)
- **Used in:** `src/core/connection_manager.py` (line 21)
- **Status:** REQUIRED for Phase 2 secure credential storage
- **Phase:** Currently in development (Phase 2)

## Installation Size Impact

### Before Cleanup
```
textual          ~30MB
rich             ~5MB
CRYSTALpytools   ~200MB (includes numpy, scipy)
pymatgen         ~150MB (includes numpy, pandas, spglib)
ase              ~150MB (includes numpy, scipy)
asyncssh         ~5MB
jinja2           ~3MB
pyyaml           ~2MB
keyring          ~1MB
toml             ~1MB
────────────────
Total            ~547MB
```

### After Cleanup
```
textual          ~30MB
rich             ~5MB
asyncssh         ~5MB
jinja2           ~3MB
pyyaml           ~2MB
keyring          ~1MB
────────────────
Total            ~46MB (core installation)

Optional [analysis]:
CRYSTALpytools   ~200MB
pymatgen         ~150MB
ase              ~150MB
────────────────
Total            ~500MB (if analysis extras installed)
```

**Savings:** 91% smaller core installation (46MB vs 547MB)

## Migration Guide for Users

### Existing Users

#### Option 1: Minimal Installation (Recommended for new users)
```bash
pip install crystal-tui
```
- Core features work perfectly
- Output parsing uses built-in fallback
- ~46MB total size
- Can add analysis tools later

#### Option 2: Full Installation (For analysis workflows)
```bash
pip install crystal-tui[analysis]
```
- Includes all optional tools
- CRYSTALpytools for enhanced parsing
- Pymatgen/ASE for structure manipulation
- ~500MB total size (plus numpy, scipy, pandas)

#### Option 3: Development Installation
```bash
pip install -e ".[dev]"
```
- Includes test dependencies
- Code quality tools (black, ruff, mypy)
- For developers only

#### Option 4: Customized Installation
```bash
# Just the analysis tools you need
pip install crystal-tui
pip install CRYSTALpytools  # Or pymatgen, or ase separately
```

### Upgrading Existing Installations

If you already have crystal-tui installed with all dependencies:

1. **Option A:** Clean reinstall (recommended)
   ```bash
   pip uninstall crystal-tui
   pip install crystal-tui[analysis]  # If you want analysis extras
   ```

2. **Option B:** Remove unused packages manually
   ```bash
   pip uninstall pymatgen ase toml  # If not needed
   ```

## Testing

All existing tests pass with the new dependency structure:

- Tests that use CRYSTALpytools import it conditionally
- Tests for fallback parser work without CRYSTALpytools
- No functionality broken by removing unused packages

## Security Benefits

1. **Reduced Attack Surface:** Fewer transitive dependencies = fewer potential vulnerabilities
2. **Cleaner Updates:** Don't need to update pymatgen/ase if not using them
3. **No Unused Code:** Eliminates unnecessary code in dependency tree

## Future Considerations

- If future features need pymatgen/ase, they'll be installed as optional extras
- CRYSTALpytools stays optional with fallback support
- Phase 2 remote execution (asyncssh/keyring) are properly sized for that phase

## Files Modified

1. **tui/pyproject.toml** - Updated dependencies and added [analysis] extras
2. **tui/README.md** - Updated installation and requirements documentation

## References

- Issue: crystalmath-3q8 (High Priority)
- Affected File: tui/pyproject.toml
- No code changes required - graceful fallbacks already in place
