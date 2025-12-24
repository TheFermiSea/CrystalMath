# CRY_CLI Documentation

Comprehensive documentation for the CRY_CLI modular architecture.

## Quick Links

### For Users

- **[Quick Start Guide](tutorials/usage.md)** - Get started with runcrystal
- **[Understanding Parallelism](tutorials/parallelism.md)** - MPI/OpenMP hybrid execution
- **[Troubleshooting](TROUBLESHOOTING.md)** - Common issues and solutions

### For Developers

- **[MODULES.md](MODULES.md)** - Complete API reference for all 9 modules
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - System design and architecture
- **[TESTING.md](TESTING.md)** - Testing strategy and guidelines
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Development workflow

## Documentation Structure

```
docs/
├── README.md                    # This file - documentation index
├── MODULES.md                   # ⭐ Complete module API reference (2257 lines)
├── ARCHITECTURE.md              # System architecture overview
├── TESTING.md                   # Testing framework and guidelines
├── CONTRIBUTING.md              # Development workflow
├── TROUBLESHOOTING.md           # Common issues
│
├── tutorials/                   # User guides
│   ├── usage.md
│   ├── parallelism.md
│   ├── scratch.md
│   └── intel_opts.md
│
└── implementation/              # Implementation notes
    ├── cry-config-implementation.md
    ├── CRY_PARALLEL_MODULE.md
    └── exec_crystal_run_implementation.md
```

## Module Documentation (MODULES.md)

The **MODULES.md** file is the primary API reference covering all 9 library modules:

1. **Configuration Module (cry-config.sh)** - Path management and theme colors
2. **Logging Module (cry-logging.sh)** - Structured logging with levels
3. **Core Module (core.sh)** - Module loading system
4. **UI Module (cry-ui.sh)** - Visual components and gum integration
5. **Parallel Module (cry-parallel.sh)** - MPI/OpenMP configuration
6. **Scratch Module (cry-scratch.sh)** - Scratch space management
7. **Stage Module (cry-stage.sh)** - File staging utilities
8. **Execution Module (cry-exec.sh)** - Calculation execution and error analysis
9. **Help Module (cry-help.sh)** - Interactive help system

### What's in MODULES.md

For each module:
- **Purpose** - What the module does
- **Dependencies** - Required modules
- **Public Functions** - Complete API with:
  - Function signature
  - Parameters and return values
  - Usage examples
  - Error conditions
  - Best practices
- **Configuration** - Environment variables and constants
- **Notes** - Implementation details and gotchas

## Quick API Reference

### Loading Modules

```bash
# Bootstrap
source lib/cry-config.sh
source lib/cry-logging.sh
source lib/core.sh

# Load all modules
cry_require_all

# Or load specific modules
cry_require cry-ui
cry_require cry-parallel
```

### Common Operations

**Configuration:**
```bash
cry_config_show              # Display configuration
cry_config_validate          # Validate paths
root=$(cry_config_get CRY23_ROOT)
```

**Logging:**
```bash
cry_info "Message"           # Info level
cry_warn "Warning"           # Warning level
cry_error "Error"            # Error level
cry_debug "Debug"            # Debug level (requires CRY_LOG_LEVEL=debug)
```

**UI Components:**
```bash
ui_banner                    # ASCII art banner
ui_card "Title" "Line1" "Line2"
ui_success "Success message"
ui_error "Error message"
ui_spin "Loading" "sleep 5"  # Spinner
```

**Parallelism:**
```bash
declare -A CRY_JOB
parallel_setup 14 CRY_JOB    # Configure for 14 MPI ranks
echo "${CRY_JOB[MODE]}"      # Hybrid MPI/OpenMP
echo "${CRY_JOB[MPI_RANKS]}" # 14
```

**Scratch Management:**
```bash
trap 'scratch_cleanup' EXIT  # Auto-cleanup
scratch_create "myjob"       # Create scratch
scratch_stage_main "input.d12"
scratch_stage_auxiliary "input"
scratch_retrieve_results "input"
```

**Execution:**
```bash
declare -A CRY_JOB=(
    [MODE]="Hybrid MPI/OpenMP"
    [EXE_PATH]="/path/to/PcrystalOMP"
    [MPI_RANKS]="14"
    [file_prefix]="myjob"
)

if exec_crystal_run CRY_JOB; then
    ui_success "Done"
else
    analyze_failure "myjob.out"
fi
```

## Development Guidelines

### Adding New Functionality

1. **Identify the Module** - Determine which module to modify:
   - Configuration → cry-config.sh
   - UI elements → cry-ui.sh
   - Parallelism → cry-parallel.sh
   - File handling → cry-stage.sh
   - Execution → cry-exec.sh
   - Help/docs → cry-help.sh

2. **Follow Patterns** - Use established patterns:
   - State management via CRY_JOB associative array
   - Return exit codes (0 = success)
   - Use cry_log/cry_warn/cry_error for logging
   - Use ui_* functions for user output

3. **Write Tests** - Add unit tests:
   - tests/unit/<module>_test.bats
   - Mock external dependencies
   - Test error conditions

4. **Document** - Update MODULES.md:
   - Function signature
   - Parameters and return values
   - Usage example

### Module Development Template

```bash
#!/bin/bash
# Module: module-name
# Description: What this module does
# Dependencies: list, of, dependencies

# Prevent multiple sourcing
[[ -n "${MODULE_NAME_LOADED:-}" ]] && return 0
declare -r MODULE_NAME_LOADED=1

# Module constants
MODULE_NAME="module-name"
MODULE_VERSION="1.0.0"

# Public functions
my_function() {
    # Brief description
    # Args: $1 - description
    # Returns: 0 on success, 1 on failure
    local arg="$1"
    
    # Implementation
    return 0
}
```

## Testing

Run module tests:
```bash
cd cli/

# All unit tests
bats tests/unit/*.bats

# Specific module
bats tests/unit/cry-parallel_test.bats

# Integration tests
bats tests/integration/full_workflow_test.bats
```

## Getting Help

### For Users

1. Interactive help: `runcrystal --help`
2. Tutorials: `docs/tutorials/`
3. Troubleshooting: `docs/TROUBLESHOOTING.md`

### For Developers

1. Module API: `docs/MODULES.md`
2. Architecture: `docs/ARCHITECTURE.md`
3. Testing: `docs/TESTING.md`
4. Contributing: `docs/CONTRIBUTING.md`

## Version History

- **1.0.0** (2025-01-15) - Initial modular architecture
  - 9 modules with clear responsibilities
  - Comprehensive testing framework (76 tests)
  - Complete API documentation (MODULES.md)

## See Also

- **Main Project**: [../README.md](../README.md) - CLI overview
- **Monorepo**: [../../README.md](../../README.md) - CRYSTAL-TOOLS project
- **TUI**: [../../tui/docs/](../../tui/docs/) - Python TUI documentation

---

**Note:** The module documentation (MODULES.md) is the authoritative API reference. All other documentation provides context and guidance.
