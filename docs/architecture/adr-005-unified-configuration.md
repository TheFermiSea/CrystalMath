# ADR-005: Unified Configuration Across CLI and Python Core

**Status:** Proposed
**Date:** 2026-01-06
**Deciders:** Project maintainers
**Depends on:** ADR-001

## Context

The project currently has three overlapping configuration approaches:

1. **CLI (cry-config.sh)**:
   - Environment variables: `CRY23_ROOT`, `CRY_VERSION`, `CRY_ARCH`, `CRY_SCRATCH_BASE`
   - Optional config file: `~/.config/cry/cry.conf`
   - File staging maps (STAGE_MAP, RETRIEVE_MAP)

2. **Python TUI (environment.py)**:
   - Sources `cry23.bashrc` via subprocess to extract env vars
   - Same variables: `CRY23_ROOT`, `CRY23_EXEDIR`, `CRY23_ARCH`, `VERSION`
   - `CrystalConfig` dataclass for validated config

3. **Python TUI (config_loader.py)**:
   - YAML-based cluster configurations
   - Separate from DFT environment config

This creates maintenance burden and potential drift between Bash and Python configuration.

## Decision

### 1. Unified Configuration Format: TOML

**Choice:** TOML as the single configuration format.

**Rationale:**
- Human-readable and editable
- Native Python support (`tomllib` in 3.11+, `tomli` for older)
- Easy to parse in Bash via simple grep/awk or Python helper
- Supports hierarchical structure for multiple DFT codes

### 2. Configuration Schema

**Location:** `~/.config/crystalmath/config.toml` (user) or `.crystalmath.toml` (project)

```toml
[crystalmath]
scratch_base = "~/tmp_crystal"
database_path = ".crystal_tui.db"

[crystal23]
root_dir = "~/CRYSTAL23"
version = "v1.0.1"
architecture = "MacOsx_ARM-gfortran_omp"
# Derived: executable_dir = root_dir/bin/architecture/version

[vasp]
potcar_dir = "~/VASP/POTENTIALS"
executable = "vasp_std"

[quantum_espresso]
pseudo_dir = "~/QE/pseudo"
executable = "pw.x"

[clusters]
# Inline or path to YAML files
config_dir = "~/.config/crystalmath/clusters"
```

### 3. Configuration Precedence

| Priority | Source | Use Case |
|----------|--------|----------|
| 1 | Environment variables | CI/CD, container override |
| 2 | Project `.crystalmath.toml` | Per-project settings |
| 3 | User `~/.config/crystalmath/config.toml` | User defaults |
| 4 | Package defaults | Fallback |

**Environment variable mapping:**
- `CRYSTALMATH_CONFIG` - Path to config file
- `CRY23_ROOT` - Override `crystal23.root_dir`
- `CRY_SCRATCH_BASE` - Override `crystalmath.scratch_base`

### 4. Python Core Config Module

**Location:** `python/crystalmath/config.py`

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import tomllib  # Python 3.11+

@dataclass
class CrystalMathConfig:
    scratch_base: Path
    database_path: Path
    crystal23: Optional[Crystal23Config]
    vasp: Optional[VaspConfig]
    quantum_espresso: Optional[QEConfig]

def load_config(
    config_path: Optional[Path] = None,
    env_override: bool = True
) -> CrystalMathConfig:
    """Load configuration with precedence chain."""
    ...
```

### 5. CLI Bash Shim

**Option A: Python helper** (recommended)
```bash
# In cry-config.sh
cry_load_config() {
    # Call Python to read TOML and export variables
    eval "$(python3 -m crystalmath.config --export-bash)"
}
```

**Option B: Direct TOML parsing** (fallback)
```bash
# Simple grep-based parsing for critical variables
CRY23_ROOT=$(grep -E '^root_dir\s*=' ~/.config/crystalmath/config.toml | cut -d'"' -f2)
```

### 6. Migration Path

**Phase 1: Add TOML support (non-breaking)**
- Create `python/crystalmath/config.py`
- Support both legacy env vars and new TOML
- Document new config format

**Phase 2: Update TUI**
- Refactor `environment.py` to use new config module
- Keep `cry23.bashrc` sourcing as fallback

**Phase 3: Update CLI**
- Add Python shim to `cry-config.sh`
- Deprecate `.config/cry/cry.conf` format
- Document migration from legacy config

**Phase 4: Remove legacy** (future)
- Remove `~/.config/cry/cry.conf` support
- Update all documentation

## Consequences

### Positive
- **Single source of truth**: One config format for all components
- **DRY**: No duplicate config parsing logic
- **Extensible**: Easy to add new DFT codes or options
- **Portable**: TOML is widely supported

### Negative / Tradeoffs
- **Migration effort**: Users with existing configs need to migrate
- **Python dependency for CLI**: Bash needs Python for full TOML support
- **Backward compatibility**: Must maintain legacy support during transition

### Mitigations
- Auto-migration script to convert `.config/cry/cry.conf` to TOML
- Keep simple env var support as escape hatch
- Document both old and new approaches during transition

## Implementation Checklist

- [ ] Create `python/crystalmath/config.py` with TOML loader
- [ ] Define `CrystalMathConfig` schema with Pydantic/dataclass
- [ ] Add `--export-bash` CLI for Bash integration
- [ ] Update `environment.py` to use new config module
- [ ] Add migration script for existing configs
- [ ] Update CLAUDE.md with config documentation
- [ ] Deprecation warnings for legacy config

## Related Issues

- crystalmath-as6l.17: Centralize configuration across CLI and Python core (this ADR)
