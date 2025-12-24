# CRYSTAL23 Environment Integration

This document describes how the TUI integrates with the CRYSTAL23 environment configuration.

## Overview

The TUI uses the CRYSTAL23 environment configuration defined in `cry23.bashrc` to automatically discover and configure the CRYSTAL23 installation. This ensures consistency with other CRYSTAL23 tools and simplifies deployment.

## Architecture

### Environment Module (`src/core/environment.py`)

The environment module provides:
- **Automatic discovery**: Locates `cry23.bashrc` relative to the TUI installation
- **Environment parsing**: Sources the bashrc file and extracts configuration
- **Validation**: Ensures executables exist and are properly configured
- **Caching**: Loads configuration once and caches for performance
- **Cross-platform support**: Works on macOS and Linux

### Configuration Object

```python
@dataclass
class CrystalConfig:
    root_dir: Path              # CRYSTAL23 installation root
    executable_dir: Path        # Directory containing binaries
    scratch_dir: Path           # Temporary file directory
    utils_dir: Path             # Utility scripts directory
    architecture: str           # Platform/compiler string
    version: str                # Binary version
    executable_path: Path       # Full path to crystalOMP
```

## Environment Variables

The following variables are read from `cry23.bashrc`:

| Variable | Description | Example |
|----------|-------------|---------|
| `CRY23_ROOT` | CRYSTAL23 installation directory | `/Users/user/CRYSTAL23` |
| `CRY23_EXEDIR` | Directory containing executables | `$CRY23_ROOT/bin/MacOsx_ARM-gfortran_omp/v1.0.1` |
| `CRY23_SCRDIR` | Scratch directory for temporary files | `$HOME/tmp` |
| `CRY23_UTILS` | Utility scripts directory | `$CRY23_ROOT/utils23` |
| `CRY23_ARCH` | Platform/compiler architecture | `MacOsx_ARM-gfortran_omp` |
| `VERSION` | Binary version string | `v1.0.1` |

## Usage

### Loading Configuration

```python
from src.core.environment import load_crystal_environment, get_crystal_config

# Load configuration (first time)
config = load_crystal_environment()

# Get cached configuration (subsequent calls)
config = get_crystal_config()

# Access configuration
print(f"Executable: {config.executable_path}")
print(f"Scratch dir: {config.scratch_dir}")
print(f"Architecture: {config.architecture}")
```

### Custom bashrc Path

```python
from pathlib import Path

# Specify custom bashrc location
config = load_crystal_environment(
    bashrc_path=Path("/custom/path/cry23.bashrc")
)
```

### Force Reload

```python
# Force reload from bashrc (bypass cache)
config = load_crystal_environment(force_reload=True)
```

## Integration Points

### 1. TUI Application (`src/tui/app.py`)

The main TUI app loads the environment at startup:

```python
from ..core.environment import get_crystal_config

class CrystalTUI(App):
    def on_mount(self):
        # Load CRYSTAL23 environment
        self.config = get_crystal_config()
```

### 2. LocalRunner (`src/runners/local.py`)

The job runner uses the environment to locate executables:

```python
def _resolve_executable(self, executable_path: Optional[Path]) -> Path:
    # Priority order:
    # 1. Explicitly provided path
    # 2. CRYSTAL23 environment (via cry23.bashrc)
    # 3. CRY23_EXEDIR environment variable (legacy)
    # 4. PATH lookup

    try:
        config = get_crystal_config()
        return config.executable_path
    except EnvironmentError:
        # Fallback to other methods
        pass
```

## Path Resolution

### Auto-detection Algorithm

The environment module automatically locates `cry23.bashrc` using this logic:

```
TUI file location: CRYSTAL23/crystalmath/tui/src/core/environment.py
                                      ↓
                   Go up 5 parent levels
                                      ↓
              Target: CRYSTAL23/utils23/cry23.bashrc
```

This works because:
1. `environment.py` is at: `CRYSTAL23/crystalmath/tui/src/core/environment.py`
2. Parents: `core/ → src/ → tui/ → crystalmath/ → CRYSTAL23/`
3. Result: `CRYSTAL23/utils23/cry23.bashrc`

### Directory Structure

```
CRYSTAL23/                          # CRY23_ROOT
├── bin/
│   └── MacOsx_ARM-gfortran_omp/
│       └── v1.0.1/
│           └── crystalOMP          # executable_path
├── utils23/
│   └── cry23.bashrc                # Configuration file
└── crystalmath/
    └── tui/
        └── src/
            └── core/
                └── environment.py  # This file
```

## Error Handling

### Missing bashrc

```python
try:
    config = load_crystal_environment()
except EnvironmentError as e:
    print(f"CRYSTAL23 not found: {e}")
    # Error message includes expected location
```

### Missing Executable

```python
try:
    config = load_crystal_environment()
except EnvironmentError as e:
    if "executable not found" in str(e):
        print("Please compile CRYSTAL23 binaries")
```

### Invalid Configuration

The module validates:
- Executable directory exists
- crystalOMP exists and is executable
- Scratch directory can be created
- All required environment variables are present

## Cross-Platform Support

### macOS

```bash
# cry23.bashrc
export CRY23_ROOT="/Users/user/CRYSTAL23"
export CRY23_ARCH="MacOsx_ARM-gfortran_omp"
export CRY23_SCRDIR="$HOME/tmp"
```

### Linux

```bash
# cry23.bashrc
export CRY23_ROOT="/home/user/CRYSTAL23"
export CRY23_ARCH="Linux-ifort_i64_omp"
export CRY23_SCRDIR="/tmp/crystal"
```

The environment module handles both automatically.

## Testing

### Unit Tests

```bash
cd tui/
pytest tests/test_environment.py -v
```

Test coverage includes:
- Configuration object creation
- bashrc parsing with various formats
- Path validation
- Missing file handling
- Caching behavior
- Cross-platform paths

### Integration Test

```bash
cd tui/
pytest tests/test_environment.py::TestIntegration -v -s
```

This test loads the actual CRYSTAL23 environment and validates:
- All paths exist
- Executable is accessible
- Scratch directory is writable

## Troubleshooting

### Issue: "cry23.bashrc not found"

**Cause**: TUI installation not in expected location relative to CRYSTAL23.

**Solution**: Provide explicit path:
```python
config = load_crystal_environment(
    bashrc_path=Path("/path/to/CRYSTAL23/utils23/cry23.bashrc")
)
```

### Issue: "crystalOMP executable not found"

**Cause**: Binaries not compiled or wrong architecture.

**Solution**:
1. Check `$CRY23_EXEDIR` path exists
2. Verify `crystalOMP` file exists
3. Ensure executable permissions: `chmod +x $CRY23_EXEDIR/crystalOMP`

### Issue: "Failed to extract required environment variables"

**Cause**: `cry23.bashrc` missing required exports.

**Solution**: Ensure bashrc contains all required variables:
```bash
export CRY23_ROOT="..."
export CRY23_EXEDIR="..."
export CRY23_SCRDIR="..."
export CRY23_UTILS="..."
export CRY23_ARCH="..."
export VERSION="..."
```

## Best Practices

1. **Don't modify cry23.bashrc format**: The TUI expects standard variable names
2. **Use absolute paths**: Avoid relative paths in bashrc
3. **Test after changes**: Run integration tests after modifying environment
4. **Cache is global**: Restarting the TUI is needed after changing bashrc
5. **Check permissions**: Ensure scratch directory is writable

## Future Enhancements

Planned improvements:
- [ ] Support for multiple CRYSTAL versions
- [ ] Environment variable override mechanism
- [ ] Hot reload of configuration changes
- [ ] Configuration validation tool
- [ ] Environment setup wizard for new installations

## See Also

- `src/core/environment.py` - Implementation
- `tests/test_environment.py` - Test suite
- `~/CRYSTAL23/utils23/cry23.bashrc` - Configuration file
- `docs/PROJECT_STATUS.md` - TUI development status
