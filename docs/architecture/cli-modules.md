# CRY_CLI Module API Reference

Complete documentation for all CRY_CLI library modules. This reference covers the 9 core modules that make up the modular architecture.

## Table of Contents

1. [Module Loading System](#module-loading-system)
2. [Configuration Module](#configuration-module-cry-configsh)
3. [Logging Module](#logging-module-cry-loggingsh)
4. [Core Module](#core-module-coresh)
5. [UI Module](#ui-module-cry-uish)
6. [Parallel Module](#parallel-module-cry-parallelsh)
7. [Scratch Module](#scratch-module-cry-scratchsh)
8. [Stage Module](#stage-module-cry-stagesh)
9. [Execution Module](#execution-module-cry-execsh)
10. [Help Module](#help-module-cry-helpsh)

---

## Module Loading System

### Loading Order

Modules must be loaded in dependency order:

```bash
1. cry-config.sh    # Bootstrap configuration (no dependencies)
2. cry-logging.sh   # Logging infrastructure (depends on config)
3. core.sh          # Module loader (depends on config, logging)
4. cry-ui.sh        # UI components (depends on config)
5. cry-parallel.sh  # Parallelism logic (depends on core, ui)
6. cry-scratch.sh   # Scratch management (depends on config)
7. cry-stage.sh     # File staging (depends on ui, scratch)
8. cry-exec.sh      # Execution engine (depends on ui, parallel, scratch, stage)
9. cry-help.sh      # Help system (depends on ui, config)
```

### Example Usage

```bash
#!/bin/bash

# Bootstrap
source "lib/cry-config.sh"
source "lib/cry-logging.sh"
source "lib/core.sh"

# Load remaining modules via cry_require
cry_require cry-ui
cry_require cry-parallel
cry_require cry-scratch
cry_require cry-stage
cry_require cry-exec
cry_require cry-help

# Now all modules are available
```

---

## Configuration Module (cry-config.sh)

**Purpose:** Central configuration management, path exports, theme colors, and file staging mappings.

**Dependencies:** None (bootstrap module)

**Source:** `lib/cry-config.sh` (311 lines)

### Public Functions

#### `cry_config_init()`

Initialize configuration system with environment variable detection and defaults.

**Parameters:** None

**Returns:** Always returns 0

**Exports:**
- `CRY23_ROOT` - CRYSTAL23 installation directory (default: `$HOME/CRYSTAL23`)
- `CRY_VERSION` - Binary version (default: `v1.0.1`)
- `CRY_ARCH` - Platform architecture (default: `Linux-ifort_i64_omp`)
- `CRY_BIN_DIR` - Binary directory path
- `CRY_SCRATCH_BASE` - Scratch directory base (default: `$HOME/tmp_crystal`)
- `CRY_USER_BIN` - User binary path (default: `$HOME/.local/bin`)
- `CRY_USER_MAN` - User manual path (default: `$HOME/.local/share/man/man1`)
- `CRY_TUTORIAL_DIR` - Tutorial directory (default: `$PROJECT_ROOT/share/tutorials`)

**Example:**
```bash
# Automatic initialization on source
source lib/cry-config.sh
# CRY23_ROOT and other variables are now set

# Override before sourcing
export CRY23_ROOT="/opt/CRYSTAL23"
source lib/cry-config.sh
echo "Using: $CRY23_ROOT"
```

#### `cry_config_get(VAR_NAME)`

Retrieve value of a configuration variable.

**Parameters:**
- `$1` - Variable name to retrieve

**Returns:** 0 on success, 1 if variable name missing

**Stdout:** Variable value

**Example:**
```bash
root_dir=$(cry_config_get CRY23_ROOT)
echo "CRYSTAL23 installed at: $root_dir"

# Output:
# CRYSTAL23 installed at: /home/user/CRYSTAL23
```

#### `cry_config_validate()`

Validate that configuration paths and executables exist.

**Parameters:** None

**Returns:**
- 0 if all validations pass
- Number of errors found (non-zero)

**Checks:**
- `CRY23_ROOT` directory exists
- `CRY_BIN_DIR` directory exists
- `crystal` executable exists and is executable

**Example:**
```bash
if ! cry_config_validate; then
    echo "Configuration validation failed!"
    exit 1
fi
```

#### `cry_config_show()`

Display current configuration in human-readable format.

**Parameters:** None

**Returns:** Always returns 0

**Stdout:** Configuration report including paths, theme colors, and file mappings

**Example:**
```bash
cry_config_show

# Output:
# CRY_CLI Configuration:
#   CRY23_ROOT:        /home/user/CRYSTAL23
#   CRY_VERSION:       v1.0.1
#   CRY_ARCH:          Linux-ifort_i64_omp
#   CRY_BIN_DIR:       /home/user/CRYSTAL23/bin/Linux-ifort_i64_omp/v1.0.1
#   CRY_SCRATCH_BASE:  /home/user/tmp_crystal
#   ...
```

#### `cry_stage_map_get(KEY)`

Retrieve destination filename from STAGE_MAP for auxiliary file staging.

**Parameters:**
- `$1` - File extension key (e.g., "gui", "f9", "hessopt")

**Returns:** 0 on success, 1 if key not found

**Stdout:** Destination filename (e.g., "fort.34", "fort.20", "HESSOPT.DAT")

**Example:**
```bash
# Get FORTRAN unit for .gui files
dest=$(cry_stage_map_get "gui")
echo "Stage myjob.gui to: $dest"

# Output:
# Stage myjob.gui to: fort.34
```

#### `cry_retrieve_map_get(KEY)`

Retrieve output file extension from RETRIEVE_MAP for result file retrieval.

**Parameters:**
- `$1` - Work file name (e.g., "fort.9", "HESSOPT.DAT")

**Returns:** 0 on success, 1 if key not found

**Stdout:** Output file extension (e.g., "f9", "hessopt")

**Example:**
```bash
# Get output extension for wave function
ext=$(cry_retrieve_map_get "fort.9")
echo "Save wave function as: myjob.$ext"

# Output:
# Save wave function as: myjob.f9
```

### Configuration Variables

#### Theme Colors (ANSI 256-color codes)

```bash
C_PRIMARY="39"   # Sapphire Blue - Primary branding
C_SEC="86"       # Teal - Secondary highlights
C_WARN="214"     # Orange - Warnings
C_ERR="196"      # Red - Errors
C_TEXT="255"     # White - Main text
C_DIM="240"      # Gray - Dimmed text
```

#### File Staging Maps

**STAGE_MAP:** Maps input file extensions to CRYSTAL23 FORTRAN unit numbers

```bash
gui     → fort.34      # External geometry
f9      → fort.20      # SCF guess (binary)
f98     → fort.98      # SCF guess (formatted)
hessopt → HESSOPT.DAT  # Hessian for optimization restart
born    → BORN.DAT     # Born effective charges
```

**RETRIEVE_MAP:** Maps work files to output file extensions

```bash
fort.9       → f9         # Binary wave function
fort.98      → f98        # Formatted wave function
HESSOPT.DAT  → hessopt    # Updated Hessian
OPTINFO.DAT  → optinfo    # Optimization state
FREQINFO.DAT → freqinfo   # Frequency calculation state
```

### Notes

- Auto-initializes on source unless `CRY_NO_AUTO_INIT=1` is set
- Configuration file support: `~/.config/cry/cry.conf` (optional)
- Shell compatibility: Works with bash 3.x+, bash 4.0+, and zsh
- Backward compatibility aliases: `BIN_DIR`, `SCRATCH_BASE`, `TUTORIAL_DIR`

---

## Logging Module (cry-logging.sh)

**Purpose:** Structured logging with levels, timestamps, and color output.

**Dependencies:** None

**Source:** `lib/cry-logging.sh` (128 lines)

### Public Functions

#### `cry_log(LEVEL, MESSAGE...)`

Main logging function with level filtering and timestamp.

**Parameters:**
- `$1` - Log level: `debug`, `info`, `warn`, `error`
- `$2+` - Message text (concatenated with spaces)

**Returns:** 0 on success, 1 if invalid level

**Stderr:** Formatted log message with timestamp and color

**Environment Variables:**
- `CRY_LOG_LEVEL` - Minimum log level (default: `info`)

**Example:**
```bash
cry_log info "Starting calculation"
cry_log warn "Memory usage is high"
cry_log error "Calculation failed"
cry_log debug "Variable x = $x"

# Output (colored in terminal):
# [2025-01-15T10:30:45Z] [INFO] Starting calculation
# [2025-01-15T10:30:46Z] [WARN] Memory usage is high
# [2025-01-15T10:30:47Z] [ERROR] Calculation failed
```

#### `cry_info(MESSAGE...)`

Convenience function for info-level logging.

**Parameters:**
- `$@` - Message text

**Returns:** Always returns 0

**Example:**
```bash
cry_info "Configuration loaded successfully"
```

#### `cry_warn(MESSAGE...)`

Convenience function for warning-level logging.

**Parameters:**
- `$@` - Message text

**Returns:** Always returns 0

**Example:**
```bash
cry_warn "Scratch directory size exceeds 10GB"
```

#### `cry_debug(MESSAGE...)`

Convenience function for debug-level logging.

**Parameters:**
- `$@` - Message text

**Returns:** Always returns 0

**Example:**
```bash
export CRY_LOG_LEVEL=debug
cry_debug "CRY_JOB state: MODE=${CRY_JOB[MODE]}, MPI_RANKS=${CRY_JOB[MPI_RANKS]}"
```

#### `cry_fatal(MESSAGE, [EXIT_CODE])`

Log fatal error and return error code (does NOT call exit).

**Parameters:**
- `$1` - Error message
- `$2` - Exit code (optional, default: 1)

**Returns:** Exit code specified in parameter

**Example:**
```bash
if [[ ! -f "input.d12" ]]; then
    cry_fatal "Input file not found: input.d12" 2
    return 2  # Caller must handle exit
fi
```

### Log Levels

1. **debug** (0) - Detailed diagnostic information
2. **info** (1) - General informational messages (default threshold)
3. **warn** (2) - Warning messages for non-critical issues
4. **error** (3) - Error messages for failures

Messages are filtered based on `CRY_LOG_LEVEL`:
- `debug` - Show all messages
- `info` - Show info, warn, error (default)
- `warn` - Show warn, error only
- `error` - Show error only

### Notes

- Color output automatic if terminal supports it (`-t 2`, `TERM != dumb`)
- Timestamps in ISO 8601 format (UTC)
- Thread-safe for parallel operations
- Functions exported for use in subshells

---

## Core Module (core.sh)

**Purpose:** Module loading system with dependency tracking and double-load prevention.

**Dependencies:** None (but expects cry-config and cry-logging to be sourced first)

**Source:** `lib/core.sh` (108 lines)

### Public Functions

#### `cry_require(MODULE_NAME)`

Load a module if not already loaded.

**Parameters:**
- `$1` - Module name without `.sh` extension (e.g., `cry-ui`, `cry-parallel`)

**Returns:**
- 0 if module loaded successfully
- 1 if module file not found
- 2 if module fails to load

**Example:**
```bash
# Load single module
cry_require cry-ui
if [[ $? -ne 0 ]]; then
    echo "Failed to load UI module"
    exit 1
fi

# Load multiple modules
cry_require cry-parallel
cry_require cry-scratch
cry_require cry-stage
```

#### `cry_require_all()`

Load all standard CRY_CLI modules in correct order.

**Parameters:** None

**Returns:** Number of failed module loads

**Modules Loaded:**
1. cry-ui
2. cry-parallel
3. cry-scratch
4. cry-stage
5. cry-exec
6. cry-help

**Example:**
```bash
# Load entire module suite
if ! cry_require_all; then
    echo "Some modules failed to load"
    exit 1
fi

# All modules now available
parallel_setup 4 CRY_JOB
scratch_create "myjob"
```

#### `cry_module_loaded(MODULE_NAME)`

Check if a module has been loaded.

**Parameters:**
- `$1` - Module name (e.g., `cry-ui`)

**Returns:** 0 if loaded, 1 if not loaded

**Example:**
```bash
if cry_module_loaded cry-ui; then
    ui_success "Module check passed"
else
    echo "UI module not loaded"
    cry_require cry-ui
fi
```

#### `cry_list_modules()`

List all currently loaded modules.

**Parameters:** None

**Returns:** Always returns 0

**Stdout:** List of loaded module names

**Example:**
```bash
cry_list_modules

# Output:
# Loaded modules:
#   - core
#   - cry-ui
#   - cry-parallel
#   - cry-scratch
```

### Implementation Details

- **Double-load prevention:** Tracks loaded modules in `_CRY_LOADED_MODULES` associative array
- **LIB_DIR detection:** Automatically detects library directory from `${BASH_SOURCE[0]}`
- **Error handling:** Clear error messages for missing or failed modules
- **No circular dependencies:** Module loading is linear, no cycles

### Notes

- Module files must be in `$LIB_DIR` (automatically detected)
- Module names must match filenames (e.g., `cry-ui` loads `cry-ui.sh`)
- Loading a module twice is safe (no-op on second call)
- Auto-initializes itself on source

---

## UI Module (cry-ui.sh)

**Purpose:** Visual components and terminal UI utilities with theme support and gum integration.

**Dependencies:** cry-config.sh (for theme colors)

**Source:** `lib/cry-ui.sh` (461 lines)

### Public Functions

#### `ui_init()`

Initialize UI module and bootstrap gum if missing.

**Parameters:** None

**Returns:** Always returns 0

**Side Effects:**
- Auto-installs gum to `$CRY_USER_BIN` if missing
- Adds user bin to PATH
- Sets `HAS_GUM` global flag

**Example:**
```bash
# Automatic initialization on source
source lib/cry-ui.sh
# gum now available if installation succeeded

# Check gum availability
if $HAS_GUM; then
    echo "UI features enabled"
fi
```

#### `ui_banner()`

Display ASCII art banner for CRYSTAL23.

**Parameters:** None

**Returns:** Always returns 0

**Example:**
```bash
ui_banner

# Output (colored):
#    ____________  ________________    __   ___  _____
#   / ____/ __ \ \/ / ___/_  __/   |  / /  |__ \|__  /
#  / /   / /_/ /\  /\__ \ / / / /| | / /   __/ / /_ <
# / /___/ _, _/ / /___/ // / / ___ |/ /___/ __/___/ /
# \____/_/ |_| /_//____//_/ /_/  |_/_____/____/____/
```

#### `ui_card(TITLE, BODY_LINES...)`

Display bordered card with title and content.

**Parameters:**
- `$1` - Card title
- `$2+` - Body lines (each parameter is a separate line)

**Returns:** Always returns 0

**Example:**
```bash
ui_card "Job Configuration" \
    "Mode: Hybrid MPI/OpenMP" \
    "MPI Ranks: 14" \
    "Threads per Rank: 4" \
    "Total Cores: 56"

# Output (bordered):
# ╭──────────────────────────────────╮
# │  Job Configuration               │
# │                                  │
# │  Mode: Hybrid MPI/OpenMP         │
# │  MPI Ranks: 14                   │
# │  Threads per Rank: 4             │
# │  Total Cores: 56                 │
# ╰──────────────────────────────────╯
```

#### `ui_status_line(LABEL, VALUE)`

Display label: value status line with color formatting.

**Parameters:**
- `$1` - Label text
- `$2` - Value text

**Returns:** Always returns 0

**Example:**
```bash
ui_status_line "Input File" "mgo.d12"
ui_status_line "Work Directory" "/tmp/cry_mgo_12345"

# Output (colored):
# Input File: mgo.d12
# Work Directory: /tmp/cry_mgo_12345
```

#### `ui_success(MESSAGE)`

Display success message with checkmark.

**Parameters:**
- `$1` - Success message

**Returns:** Always returns 0

**Example:**
```bash
ui_success "Calculation completed successfully"

# Output (green):
# ✓ Calculation completed successfully
```

#### `ui_error(MESSAGE)`

Display error message in red.

**Parameters:**
- `$1` - Error message

**Returns:** Always returns 0

**Stderr:** Formatted error message

**Example:**
```bash
ui_error "Failed to create scratch directory"

# Output (red, to stderr):
# ERROR: Failed to create scratch directory
```

#### `ui_warning(MESSAGE)`

Display warning message in orange.

**Parameters:**
- `$1` - Warning message

**Returns:** Always returns 0

**Example:**
```bash
ui_warning "Memory usage exceeds 80%"

# Output (orange):
# WARNING: Memory usage exceeds 80%
```

#### `ui_info(MESSAGE)`

Display informational message with arrow.

**Parameters:**
- `$1` - Info message

**Returns:** Always returns 0

**Example:**
```bash
ui_info "Staging auxiliary files..."

# Output (blue):
# → Staging auxiliary files...
```

#### `ui_file_found(FILE_PATH)`

Display "file found" message with checkmark.

**Parameters:**
- `$1` - File path

**Returns:** Always returns 0

**Example:**
```bash
ui_file_found "mgo.gui"
ui_file_found "mgo.f9"

# Output (teal):
# ✓ Found: mgo.gui
# ✓ Found: mgo.f9
```

#### `ui_spin(TITLE, COMMAND)`

Execute command with spinner or progress indicator.

**Parameters:**
- `$1` - Title/message for spinner
- `$2` - Command to execute (string)

**Returns:** Exit code of executed command

**Example:**
```bash
ui_spin "Staging files" "cp *.d12 $WORK_DIR/"
if [[ $? -eq 0 ]]; then
    ui_success "Files staged"
fi

# Output (while running):
# ⠋ Staging files...
# (spinner animates until command completes)
```

#### `ui_progress(CURRENT, TOTAL, DESCRIPTION)`

Display progress bar.

**Parameters:**
- `$1` - Current step number
- `$2` - Total step count
- `$3` - Description (optional)

**Returns:** Always returns 0

**Example:**
```bash
total=10
for i in $(seq 1 $total); do
    ui_progress $i $total "Processing file $i"
    sleep 0.5
done

# Output:
# [====                                    ]  25% Processing file 3
# [========================================] 100% Processing file 10
```

#### `ui_prompt(PROMPT_TEXT, [DEFAULT])`

Display prompt and get user input.

**Parameters:**
- `$1` - Prompt text
- `$2` - Default value (optional)

**Returns:** Always returns 0

**Stdout:** User input (or default if empty)

**Example:**
```bash
job_name=$(ui_prompt "Enter job name" "myjob")
echo "Job name: $job_name"

# Interaction:
# Enter job name [myjob]: ▊
```

#### `ui_confirm(PROMPT_TEXT, [DEFAULT])`

Display yes/no confirmation prompt.

**Parameters:**
- `$1` - Prompt text
- `$2` - Default (y/n, optional, default: n)

**Returns:** 0 for yes, 1 for no

**Example:**
```bash
if ui_confirm "Delete scratch directory?" "y"; then
    rm -rf "$WORK_DIR"
    ui_success "Scratch cleaned"
fi

# Interaction:
# ? Delete scratch directory? [Y/n]: ▊
```

#### `ui_list(ITEMS...)`

Display formatted bullet list.

**Parameters:**
- `$@` - List items

**Returns:** Always returns 0

**Example:**
```bash
ui_list "crystalOMP" "PcrystalOMP" "properties"

# Output:
#   • crystalOMP
#   • PcrystalOMP
#   • properties
```

#### `ui_table_header(COLUMNS...)`

Display table header with underline.

**Parameters:**
- `$@` - Column headers

**Returns:** Always returns 0

**Example:**
```bash
ui_table_header "File" "Size" "Status"
ui_table_row "input.d12" "2.5K" "OK"
ui_table_row "output.out" "450K" "OK"

# Output:
# File                Size                Status
# --------------------+-------------------+--------------------
# input.d12           2.5K                OK
# output.out          450K                OK
```

#### `ui_section_header(TEXT)`

Display bold section header (for explain mode).

**Parameters:**
- `$1` - Section text

**Returns:** Always returns 0

**Example:**
```bash
ui_section_header "PARALLEL CONFIGURATION"
echo "Mode: Hybrid MPI/OpenMP"
echo "Ranks: 14"
```

### UI Symbols

```bash
UI_SYMBOL_CHECK="✓"     # Success indicator
UI_SYMBOL_CROSS="✗"     # Failure indicator
UI_SYMBOL_ARROW="→"     # Info indicator
UI_SYMBOL_BULLET="•"    # List bullet
UI_SYMBOL_SPINNER=(...)  # Spinner animation frames
```

### Notes

- **Graceful degradation:** All functions work without gum (plain text fallback)
- **Automatic gum installation:** Uses either `go install` or prebuilt binary download
- **Theme integration:** Uses color codes from cry-config.sh
- **Network awareness:** Skips gum installation if no network connection
- **User-space installation:** Installs to `~/.local/bin` (no root required)

---

## Parallel Module (cry-parallel.sh)

**Purpose:** CRYSTAL23 hybrid MPI/OpenMP execution configuration with automatic core allocation.

**Dependencies:** core, cry-ui

**Source:** `lib/cry-parallel.sh` (188 lines)

### Public Functions

#### `parallel_setup(NPROCS, JOB_STATE_REF)`

Configure CRYSTAL23 hybrid MPI/OpenMP execution environment.

**Parameters:**
- `$1` - Number of MPI processes (1 = Serial/OpenMP mode)
- `$2` - Name reference to associative array (e.g., `CRY_JOB`)

**Returns:** 0 on success, 1 on validation failure

**Populates job state with:**
- `MODE` - "Serial/OpenMP" or "Hybrid MPI/OpenMP"
- `EXE_PATH` - Path to crystalOMP or PcrystalOMP
- `MPI_RANKS` - Number of MPI processes (empty for serial mode)
- `THREADS_PER_RANK` - OpenMP threads per MPI rank
- `TOTAL_CORES` - Total CPU cores available

**Environment variables set:**
- `OMP_NUM_THREADS` - OpenMP thread count
- `OMP_STACKSIZE` - OpenMP stack size (256M for CRYSTAL23)
- `I_MPI_PIN_DOMAIN` - Intel MPI thread pinning (omp for hybrid mode)
- `KMP_AFFINITY` - Intel OpenMP thread affinity (compact,1,0,granularity=fine)

**Example:**
```bash
declare -A CRY_JOB

# Serial execution (1 process × 56 threads)
parallel_setup 1 CRY_JOB
echo "Mode: ${CRY_JOB[MODE]}"
echo "Executable: ${CRY_JOB[EXE_PATH]}"
echo "Threads: ${CRY_JOB[THREADS_PER_RANK]}"

# Hybrid execution (14 ranks × 4 threads)
parallel_setup 14 CRY_JOB
echo "MPI Ranks: ${CRY_JOB[MPI_RANKS]}"
echo "Threads per Rank: ${CRY_JOB[THREADS_PER_RANK]}"
```

#### `parallel_validate_executables(EXE_PATH)`

Validate that CRYSTAL23 executable exists and is executable.

**Parameters:**
- `$1` - Full path to executable

**Returns:** 0 if valid, 1 if not found or not executable

**Example:**
```bash
if ! parallel_validate_executables "${CRY_JOB[EXE_PATH]}"; then
    cry_fatal "CRYSTAL23 executable validation failed"
    exit 1
fi
```

#### `parallel_print_config(JOB_STATE_REF)`

Print parallel execution configuration for debugging.

**Parameters:**
- `$1` - Name reference to associative array

**Returns:** Always returns 0

**Stdout:** Formatted configuration report

**Example:**
```bash
parallel_setup 14 CRY_JOB
parallel_print_config CRY_JOB

# Output:
# Parallel Configuration:
#   Mode: Hybrid MPI/OpenMP
#   Executable: /path/to/PcrystalOMP
#   Total Cores: 56
#   MPI Ranks: 14
#   Threads per Rank: 4
# Environment Variables:
#   OMP_NUM_THREADS=4
#   OMP_STACKSIZE=256M
#   I_MPI_PIN_DOMAIN=omp
#   KMP_AFFINITY=compact,1,0,granularity=fine
```

### Execution Modes

#### Serial/OpenMP Mode (NPROCS ≤ 1)

```
Binary:   crystalOMP
Resources: 1 process × N threads (all cores)
Usage:     runcrystal input
MPI:       Not used
```

**Environment:**
```bash
OMP_NUM_THREADS=56          # All cores as threads
OMP_STACKSIZE=256M
# I_MPI_PIN_DOMAIN not set
```

#### Hybrid MPI/OpenMP Mode (NPROCS > 1)

```
Binary:   PcrystalOMP
Resources: N ranks × (total_cores / N) threads
Usage:     runcrystal input 14
MPI:       Intel MPI or compatible
```

**Environment:**
```bash
OMP_NUM_THREADS=4                     # Threads per rank
OMP_STACKSIZE=256M
I_MPI_PIN_DOMAIN=omp                  # Pin ranks for OpenMP
KMP_AFFINITY=compact,1,0,granularity=fine  # Thread affinity
```

### Core Allocation Examples

System: 56 cores (Intel Xeon w9-3495X)

| NPROCS | MPI Ranks | Threads/Rank | Mode |
|--------|-----------|--------------|------|
| 1      | -         | 56           | Serial/OpenMP |
| 4      | 4         | 14           | Hybrid |
| 7      | 7         | 8            | Hybrid |
| 14     | 14        | 4            | Hybrid |
| 28     | 28        | 2            | Hybrid |
| 56     | 56        | 1            | Hybrid |

### Notes

- **Automatic core detection:** Uses `nproc` (Linux), `sysctl` (macOS), or `/proc/cpuinfo`
- **Intel MPI tuning:** Optimized for Intel Xeon with compact affinity
- **Stack size:** 256M required for CRYSTAL23 large integral arrays
- **Binary selection:** Automatic based on mode (crystalOMP vs PcrystalOMP)
- **Requires:** `BIN_DIR` environment variable (set by cry-config.sh)

---

## Scratch Module (cry-scratch.sh)

**Purpose:** Scratch space management for CRYSTAL23 calculations with unique directory creation and guaranteed cleanup.

**Dependencies:** cry-config.sh (for CRY_SCRATCH_BASE)

**Source:** `lib/cry-scratch.sh` (322 lines)

### Public Functions

#### `scratch_create(FILE_PREFIX)`

Create unique scratch directory for job execution.

**Parameters:**
- `$1` - File prefix (job name)

**Returns:** 0 on success, 1 on failure

**Exports:** `WORK_DIR` - Path to scratch directory

**Example:**
```bash
scratch_create "mgo_test"
echo "Scratch: $WORK_DIR"

# Output:
# Scratch: /home/user/tmp_crystal/cry_mgo_test_12345

# WORK_DIR is now globally available
cd "$WORK_DIR"
```

#### `scratch_cleanup()`

Remove scratch directory and unset WORK_DIR.

**Parameters:** None

**Returns:** Always returns 0 (idempotent)

**Safety Features:**
- Validates WORK_DIR is within CRY_SCRATCH_BASE
- Safe to call multiple times
- Safe if scratch_create was never called

**Example:**
```bash
# Set trap for automatic cleanup
trap 'scratch_cleanup' EXIT

scratch_create "myjob"
# ... do work ...
# Cleanup happens automatically on exit

# Or manual cleanup
scratch_cleanup
```

#### `scratch_info()`

Display information about current scratch directory.

**Parameters:** None

**Returns:** 0 if WORK_DIR set, 1 if not

**Stdout:** Scratch directory information including size and file count

**Example:**
```bash
scratch_info

# Output:
# Scratch Directory Information:
#   WORK_DIR:           /home/user/tmp_crystal/cry_mgo_12345
#   CRY_SCRATCH_BASE:   /home/user/tmp_crystal
#   Status:             EXISTS
#   Size:               2.3G
#   Files:              143
```

#### `scratch_stage_file(SOURCE_FILE, DEST_NAME)`

Stage a single file to scratch directory.

**Parameters:**
- `$1` - Source file path
- `$2` - Destination filename in scratch

**Returns:** 0 if file staged, 1 if source doesn't exist or staging fails

**Example:**
```bash
scratch_create "myjob"
scratch_stage_file "input.d12" "INPUT"
scratch_stage_file "geometry.gui" "fort.34"

# Files now in $WORK_DIR/INPUT and $WORK_DIR/fort.34
```

#### `scratch_stage_main(INPUT_FILE)`

Stage main input file (.d12) to scratch as INPUT.

**Parameters:**
- `$1` - Path to .d12 input file

**Returns:** 0 on success, 1 if file not found or staging fails

**Example:**
```bash
scratch_create "mgo"
scratch_stage_main "mgo.d12"

# $WORK_DIR/INPUT now contains mgo.d12
```

#### `scratch_stage_auxiliary(FILE_PREFIX)`

Stage auxiliary files using STAGE_MAP pattern.

**Parameters:**
- `$1` - File prefix (job name, without extension)

**Returns:** Number of files staged

**Stages (if present):**
- `PREFIX.gui` → `fort.34`
- `PREFIX.f9` → `fort.20`
- `PREFIX.f98` → `fort.98`
- `PREFIX.hessopt` → `HESSOPT.DAT`
- `PREFIX.born` → `BORN.DAT`

**Example:**
```bash
# Files in current directory:
# mgo.d12, mgo.gui, mgo.f9

scratch_create "mgo"
scratch_stage_main "mgo.d12"
count=$(scratch_stage_auxiliary "mgo")
echo "Staged $count auxiliary files"

# Output:
# Staged 2 auxiliary files
# (mgo.gui → fort.34, mgo.f9 → fort.20)
```

#### `scratch_retrieve_file(WORK_FILE, OUTPUT_FILE)`

Retrieve a single file from scratch directory.

**Parameters:**
- `$1` - Filename in scratch directory
- `$2` - Output filename in original directory

**Returns:** 0 if file retrieved, 1 if not found or retrieval fails

**Example:**
```bash
scratch_retrieve_file "OUTPUT" "mgo.out"
scratch_retrieve_file "fort.9" "mgo.f9"
```

#### `scratch_retrieve_results(FILE_PREFIX)`

Retrieve result files using RETRIEVE_MAP pattern.

**Parameters:**
- `$1` - File prefix (job name)

**Returns:** Number of files retrieved

**Retrieves (if present):**
- `PREFIX.out` (main output)
- `fort.9` → `PREFIX.f9`
- `fort.98` → `PREFIX.f98`
- `HESSOPT.DAT` → `PREFIX.hessopt`
- `OPTINFO.DAT` → `PREFIX.optinfo`
- `FREQINFO.DAT` → `PREFIX.freqinfo`

**Example:**
```bash
count=$(scratch_retrieve_results "mgo")
echo "Retrieved $count result files"

# Files now in original directory:
# mgo.out, mgo.f9, mgo.f98, etc.
```

#### `scratch_cd()`

Change directory to scratch workspace.

**Parameters:** None

**Returns:** 0 on success, 1 if WORK_DIR not set or doesn't exist

**Example:**
```bash
scratch_create "myjob"
scratch_cd
pwd

# Output:
# /home/user/tmp_crystal/cry_myjob_12345
```

#### `scratch_list()`

List files in scratch directory.

**Parameters:** None

**Returns:** 0 on success, 1 if WORK_DIR not set

**Stdout:** Directory listing with sizes

**Example:**
```bash
scratch_list

# Output:
# Contents of /home/user/tmp_crystal/cry_mgo_12345:
# -rw-r--r-- 1 user user  2.5K INPUT
# -rw-r--r-- 1 user user  1.2K fort.34
# -rw-r--r-- 1 user user  450K OUTPUT
```

#### `scratch_validate()`

Validate scratch directory state.

**Parameters:** None

**Returns:** 0 if valid, number of errors found

**Checks:**
- CRY_SCRATCH_BASE exists
- WORK_DIR is set
- WORK_DIR exists
- WORK_DIR is within CRY_SCRATCH_BASE (security check)

**Example:**
```bash
if ! scratch_validate; then
    cry_fatal "Scratch validation failed"
    exit 1
fi
```

### Directory Naming Convention

```
Format: $CRY_SCRATCH_BASE/cry_<prefix>_<pid>

Examples:
  ~/tmp_crystal/cry_mgo_12345
  ~/tmp_crystal/cry_optimization_67890
  ~/tmp_crystal/cry_test_54321
```

**Uniqueness guaranteed by:**
- Job prefix (user-specified)
- Process ID (automatic)

### Notes

- **Fast local storage:** CRY_SCRATCH_BASE should be on SSD, not network filesystem
- **Automatic cleanup:** Use trap-based cleanup in main scripts
- **Idempotent operations:** Safe to call cleanup multiple times
- **Security:** Path validation prevents deletion outside scratch base
- **Large files:** CRYSTAL23 writes GB-scale integral files to scratch

---

## Stage Module (cry-stage.sh)

**Purpose:** File staging and preparation for CRYSTAL23 calculations with automatic auxiliary file discovery.

**Dependencies:** core, cry-ui, cry-scratch

**Source:** `lib/cry-stage.sh` (452 lines)

### CRYSTAL23-Specific Functions

These are the primary functions for CRYSTAL23 workflows.

#### `stage_inputs(FILE_PREFIX, WORK_DIR, ORIGINAL_DIR)`

Stage CRYSTAL23 input files to scratch directory.

**Parameters:**
- `$1` - File prefix (job name)
- `$2` - Work directory (scratch)
- `$3` - Original directory (where input files are located)

**Returns:** 0 on success, 1 on failure

**Stages:**
- **Required:** `PREFIX.d12` → `WORK_DIR/INPUT`
- **Optional (auto-discovered):**
  - `PREFIX.gui` → `fort.34` (external geometry)
  - `PREFIX.f9` → `fort.20` (binary wave function guess)
  - `PREFIX.f98` → `fort.98` (formatted wave function guess)
  - `PREFIX.hessopt` → `HESSOPT.DAT` (Hessian for optimization)
  - `PREFIX.born` → `BORN.DAT` (Born charges)

**Example:**
```bash
WORK_DIR="$CRY_SCRATCH_BASE/cry_mgo_$$"
mkdir -p "$WORK_DIR"

stage_inputs "mgo" "$WORK_DIR" "$PWD"

# Files staged:
# mgo.d12 → $WORK_DIR/INPUT (required)
# mgo.gui → $WORK_DIR/fort.34 (if exists)
# mgo.f9  → $WORK_DIR/fort.20 (if exists)

# User feedback:
# ✓ Found: mgo.gui
# ✓ Found: mgo.f9
```

#### `stage_retrieve_results(FILE_PREFIX, WORK_DIR, ORIGINAL_DIR)`

Retrieve CRYSTAL23 result files from scratch directory.

**Parameters:**
- `$1` - File prefix (job name)
- `$2` - Work directory (scratch)
- `$3` - Original directory (destination for results)

**Returns:** Always returns 0

**Retrieves:**
- **Always:** `OUTPUT` → `PREFIX.out`
- **If exists:**
  - `fort.9` → `PREFIX.f9` (binary wave function)
  - `fort.98` → `PREFIX.f98` (formatted wave function)
  - `HESSOPT.DAT` → `PREFIX.hessopt` (updated Hessian)
  - `OPTINFO.DAT` → `PREFIX.optinfo` (optimization state)
  - `FREQINFO.DAT` → `PREFIX.freqinfo` (frequency state)

**Example:**
```bash
# After calculation completes
stage_retrieve_results "mgo" "$WORK_DIR" "$PWD"

# Results now in original directory:
# mgo.out      (main output, always)
# mgo.f9       (if generated)
# mgo.f98      (if generated)
# mgo.hessopt  (if optimization)
# mgo.optinfo  (if optimization)
```

### Generic Staging Functions

Advanced features for custom workflows.

#### `stage_init()`

Initialize generic staging area (separate from CRYSTAL23 workflow).

**Parameters:** None

**Returns:** 0 on success, 1 on failure

**Example:**
```bash
stage_init
echo "Staging root: $STAGE_ROOT"
```

#### `stage_add(FILE, [STAGE_NAME])`

Add file to generic staging area.

**Parameters:**
- `$1` - File path
- `$2` - Stage name (optional, defaults to basename)

**Returns:** 0 on success, 1 on failure

**Example:**
```bash
stage_init
stage_add "data.txt" "input1"
stage_add "config.json" "config"
stage_list
```

#### `stage_add_pattern(PATTERN, [BASE_DIR])`

Add files matching glob pattern to staging area.

**Parameters:**
- `$1` - Glob pattern (e.g., "*.d12", "*.out")
- `$2` - Base directory (optional, default: current directory)

**Returns:** Number of files added

**Example:**
```bash
stage_init
count=$(stage_add_pattern "*.d12" "/path/to/jobs")
echo "Staged $count input files"
```

#### `stage_list()`

List all files in staging area.

**Parameters:** None

**Returns:** 0 on success, 1 if not initialized

**Example:**
```bash
stage_list

# Output:
# Stage Name           Original Path                 Size
# -------------------- ----------------------------- ----------
# input1               /path/to/data.txt            2.5K
# config               /path/to/config.json         1.2K
```

#### `stage_get_path(STAGE_NAME)`

Get staged file path.

**Parameters:**
- `$1` - Stage name

**Returns:** 0 on success, 1 if not found

**Stdout:** Full path to staged file

**Example:**
```bash
file_path=$(stage_get_path "input1")
cat "$file_path"
```

#### `stage_count()`

Get number of staged files.

**Parameters:** None

**Returns:** Always returns 0

**Stdout:** File count

**Example:**
```bash
count=$(stage_count)
echo "Staged $count files"
```

#### `stage_clear()`

Clear all staged files.

**Parameters:** None

**Returns:** Always returns 0

**Example:**
```bash
stage_clear
```

#### `stage_validate()`

Validate all staged files exist and match metadata.

**Parameters:** None

**Returns:** 0 if valid, 1 if issues found

**Checks:**
- File existence
- File size matches original

**Example:**
```bash
if ! stage_validate; then
    cry_error "Stage validation failed"
    exit 1
fi
```

#### `stage_commit(OUTPUT_DIR)`

Commit staged files to output directory.

**Parameters:**
- `$1` - Output directory

**Returns:** 0 on success, 1 on failure

**Example:**
```bash
stage_init
stage_add "file1.txt"
stage_add "file2.txt"
stage_commit "/path/to/output"

# Files copied to /path/to/output/
```

### File Staging Maps

From cry-config.sh:

**Input Staging (STAGE_MAP):**
```
.gui     → fort.34       # EXTERNAL keyword
.f9      → fort.20       # GUESSP keyword
.f98     → fort.98       # GUESSF keyword
.hessopt → HESSOPT.DAT   # RESTART in FREQCALC/OPTGEOM
.born    → BORN.DAT      # Born effective charges
```

**Result Retrieval (RETRIEVE_MAP):**
```
fort.9       → .f9         # Binary wave function
fort.98      → .f98        # Formatted wave function
HESSOPT.DAT  → .hessopt    # Updated Hessian
OPTINFO.DAT  → .optinfo    # Optimization restart
FREQINFO.DAT → .freqinfo   # Frequency restart
```

### Notes

- **Auto-discovery:** Optional files are auto-detected, no error if missing
- **User feedback:** Reports which auxiliary files were found
- **Shell compatibility:** Works with bash 3.x, bash 4.0+, and zsh
- **Error handling:** Required file (.d12) missing causes fatal error
- **Metadata tracking:** Generic staging tracks size, mtime for validation

---

## Execution Module (cry-exec.sh)

**Purpose:** Execution engine for CRYSTAL23 calculations with error analysis and progress monitoring.

**Dependencies:** core, cry-ui, cry-parallel, cry-scratch, cry-stage

**Source:** `lib/cry-exec.sh` (511 lines)

### Primary Functions

#### `exec_crystal_run(JOB_STATE_REF)`

Execute CRYSTAL23 calculation based on job state.

**Parameters:**
- `$1` - Name reference to associative array (CRY_JOB)

**Returns:** Exit code from crystal/mpirun execution

**Required job_state keys:**
- `MODE` - "Serial/OpenMP" or "Hybrid MPI/OpenMP"
- `EXE_PATH` - Full path to crystal executable
- `MPI_RANKS` - Number of MPI ranks (for parallel mode)
- `file_prefix` - Base name for output file

**Features:**
- Automatic serial vs parallel execution
- Live progress spinner (gum)
- Error analysis on failure
- Log tail display on error

**Example:**
```bash
declare -A CRY_JOB=(
    [MODE]="Hybrid MPI/OpenMP"
    [EXE_PATH]="/path/to/PcrystalOMP"
    [MPI_RANKS]="14"
    [file_prefix]="mgo"
)

# Execute calculation
if exec_crystal_run CRY_JOB; then
    ui_success "Calculation completed"
else
    ui_error "Calculation failed"
    exit 1
fi
```

**Serial Execution:**
```bash
# Command built:
# /path/to/crystalOMP < INPUT > mgo.out

# Environment set:
# OMP_NUM_THREADS=56
# OMP_STACKSIZE=256M
```

**Parallel Execution:**
```bash
# Command built:
# mpirun -np 14 /path/to/PcrystalOMP < INPUT > mgo.out

# Environment set:
# OMP_NUM_THREADS=4
# OMP_STACKSIZE=256M
# I_MPI_PIN_DOMAIN=omp
# KMP_AFFINITY=compact,1,0,granularity=fine
```

#### `analyze_failure(OUTPUT_FILE)`

Analyze CRYSTAL23 output for common errors.

**Parameters:**
- `$1` - Path to output file

**Returns:** Always returns 0 (analysis is informational)

**Detects:**
- SCF divergence
- Memory errors / segmentation faults
- Basis set errors
- Generic failures

**Example:**
```bash
if [[ $exit_code -ne 0 ]]; then
    analyze_failure "mgo.out"
fi

# Output (if SCF divergence):
# ⚠️  Detected SCF Divergence
# The calculation is unstable. Try:
# 1. Check your geometry (atoms too close?)
# 2. Use a better initial guess (GUESSP)
# 3. Increase FMIXING (e.g., FMIXING 30)
```

**Error Patterns:**

1. **SCF Divergence:**
   - Pattern: "DIVERGENCE" or "SCF NOT CONVERGED"
   - Suggestions: Check geometry, use GUESSP, increase FMIXING

2. **Memory Error:**
   - Pattern: "insufficient memory", "SIGSEGV", "Segmentation fault"
   - Suggestion: Increase MPI ranks to distribute memory

3. **Basis Set Error:**
   - Pattern: "BASIS SET" + "ERROR"
   - Suggestions: Check BS syntax, verify atomic numbers, try standard basis

### Generic Execution Functions

#### `exec_init([DRY_RUN], [VERBOSE])`

Initialize execution engine.

**Parameters:**
- `$1` - Dry run mode (true/false, optional)
- `$2` - Verbose mode (true/false, optional)

**Returns:** Always returns 0

**Example:**
```bash
exec_init true false   # Dry run mode, not verbose
```

#### `exec_run(DESCRIPTION, COMMAND...)`

Execute command with tracking and logging.

**Parameters:**
- `$1` - Command description
- `$2+` - Command and arguments

**Returns:** Command exit code

**Example:**
```bash
exec_run "Copying files" cp input.d12 "$WORK_DIR/INPUT"
exec_run "Running calculation" ./run_crystal.sh

# Logged to exec log:
# [2025-01-15 10:30:45] [START] Copying files
#   Command: cp input.d12 /tmp/cry_test_123/INPUT
# [2025-01-15 10:30:45] [SUCCESS] Copying files
```

#### `exec_dry_run(ENABLE)`

Enable or disable dry run mode.

**Parameters:**
- `$1` - Enable flag (true/false)

**Returns:** Always returns 0

**Example:**
```bash
exec_dry_run true
exec_run "Would delete file" rm important.txt
# [DRY RUN] Would execute: rm important.txt
```

#### `exec_verbose(ENABLE)`

Enable or disable verbose mode.

**Parameters:**
- `$1` - Enable flag (true/false)

**Returns:** Always returns 0

**Example:**
```bash
exec_verbose true
exec_run "Copy file" cp src dst
# Executing: cp src dst
```

#### `exec_set_log(LOG_FILE)`

Set log file for execution tracking.

**Parameters:**
- `$1` - Log file path

**Returns:** Always returns 0

**Example:**
```bash
exec_set_log "/tmp/execution.log"
exec_run "Test command" echo "hello"

# /tmp/execution.log:
# === CRY Execution Log ===
# Started: 2025-01-15 10:30:00
#
# [2025-01-15 10:30:01] [START] Test command
#   Command: echo hello
# [2025-01-15 10:30:01] [SUCCESS] Test command
```

#### `exec_history()`

Show execution history.

**Parameters:** None

**Returns:** Always returns 0

**Example:**
```bash
exec_run "Task 1" echo "one"
exec_run "Task 2" echo "two"
exec_history

# Output:
# Execution History:
#   1. Task 1
#   2. Task 2
```

### Advanced Features

#### `exec_stage_transform(COMMAND_TEMPLATE)`

Execute transformation on staged files.

**Parameters:**
- `$1` - Command template (use `{}` for input, `{output}` for output)

**Returns:** Number of failed transformations

**Example:**
```bash
stage_init
stage_add "file1.txt"
stage_add "file2.txt"

exec_stage_transform "sed 's/old/new/g' {} > {output}"

# Transforms each staged file
```

#### `exec_pipeline(STAGES...)`

Execute pipeline of commands on staged files.

**Parameters:**
- `$@` - Pipeline stages (command templates)

**Returns:** 0 on success, 1 if any stage fails

**Example:**
```bash
exec_pipeline \
    "sed 's/foo/bar/g' {} > {output}" \
    "sort {} > {output}" \
    "uniq {} > {output}"
```

### Execution Tracking

**Global Variables:**
- `EXEC_DRY_RUN` - Dry run mode flag
- `EXEC_VERBOSE` - Verbose mode flag
- `EXEC_LOG_FILE` - Log file path
- `EXEC_HISTORY` - Array of executed command descriptions

### Notes

- **Progress monitoring:** Uses gum spinner for live feedback
- **Error analysis:** Automatic analysis of CRYSTAL23 output on failure
- **MPI detection:** Uses `$I_MPI_ROOT/bin/mpirun` if available, else `mpirun` in PATH
- **Background execution:** Runs calculation in background for progress monitoring
- **Command validation:** Basic safety checks for dangerous commands
- **Log format:** ISO 8601 timestamps, structured entries

---

## Help Module (cry-help.sh)

**Purpose:** Interactive help system with tutorial integration and knowledge base search.

**Dependencies:** cry-ui.sh, cry-config.sh (for TUTORIAL_DIR and theme colors)

**Source:** `lib/cry-help.sh` (85 lines)

### Public Functions

#### `help_show_main()`

Display main interactive help menu.

**Parameters:** None

**Returns:** Never returns (exits on "Exit" selection)

**Menu Options:**
1. Quick Start Guide
2. Understanding Parallelism
3. Automatic Scratch Management
4. Intel Xeon Optimizations
5. Common Issues
6. External Knowledge Base
7. Exit

**Example:**
```bash
# From runcrystal
if [[ "$1" == "--help" ]]; then
    help_show_main
fi

# Interactive menu appears:
# Select a topic below.
# > 1. Quick Start Guide
#   2. Understanding Parallelism
#   3. Automatic Scratch Management
#   ...
```

#### `show_tutorial(TOPIC)`

Display tutorial file with soft-wrap.

**Parameters:**
- `$1` - Tutorial filename (relative to TUTORIAL_DIR)

**Returns:** Nothing (displays tutorial in pager)

**Example:**
```bash
show_tutorial "usage.md"
show_tutorial "parallelism.md"

# Opens gum pager with tutorial content
```

### Tutorial Files

Expected in `$TUTORIAL_DIR` (default: `share/tutorials/`):

- `usage.md` - Quick start guide
- `parallelism.md` - Understanding hybrid MPI/OpenMP
- `scratch.md` - Automatic scratch management
- `intel_opts.md` - Intel Xeon optimizations
- `troubleshooting.md` - Common issues and solutions

### External Knowledge Base Integration

The "External Knowledge Base" menu option provides:
- Interactive search through markdown documentation
- File browser using `gum filter`
- Direct integration point for `cry-docs` tool (future)

**Example Interaction:**
```
6. External Knowledge Base
> Search Knowledge Base...
  type to filter: basis

  Results:
  > 3D/basis/sto3g.md
    3D/basis/pob-tzvp.md
    1D/basis/introduction.md

[Selected file opens in pager]
```

### Notes

- **Requires gum:** Falls back to error message if not available
- **Soft-wrap:** Uses `gum pager --soft-wrap` for readable text
- **Interactive:** Menu loops until user selects "Exit"
- **Extensible:** Easy integration point for additional help topics
- **Integration-ready:** Future `cry-docs` tool can hook into menu option 6

---

## Module Development Best Practices

### General Guidelines

1. **Module Header Template:**
```bash
#!/bin/bash
# Module: module-name
# Description: What this module does
# Dependencies: list, of, dependencies

# Prevent multiple sourcing
[[ -n "${MODULE_NAME_LOADED:-}" ]] && return 0
declare -r MODULE_NAME_LOADED=1

# Error handling
set -euo pipefail  # If appropriate for module

# Module-level constants
MODULE_NAME="module-name"
MODULE_VERSION="1.0.0"
```

2. **Function Documentation:**
```bash
function_name() {
    # Brief description
    # Args: $1 - description, $2 - description
    # Returns: 0 on success, 1 on failure
    # Example:
    #   function_name arg1 arg2

    local arg1="$1"
    local arg2="$2"

    # Implementation
    return 0
}
```

3. **State Management:**
   - Use associative arrays for complex state (CRY_JOB pattern)
   - Pass by name reference for large structures
   - Export only necessary variables
   - Document side effects clearly

4. **Error Handling:**
   - Return exit codes (0 = success)
   - Use cry_log/cry_fatal for errors
   - Validate inputs early
   - Provide helpful error messages

5. **Dependencies:**
   - Document dependencies in module header
   - Use cry_require for loading dependencies
   - Never create circular dependencies
   - Check for required environment variables

6. **Testing:**
   - Write unit tests for each public function
   - Use mocks for external commands
   - Test error conditions
   - Verify state changes

### Common Patterns

#### Name Reference Pattern

```bash
my_function() {
    local -n job_state=$1  # Name reference

    # Access associative array
    job_state[KEY]="value"
    echo "${job_state[ANOTHER_KEY]}"
}

# Usage
declare -A CRY_JOB
my_function CRY_JOB
```

#### Trap-Based Cleanup Pattern

```bash
# In main script
cleanup() {
    scratch_cleanup
    # Other cleanup
}

trap 'cleanup' EXIT

# Cleanup runs automatically on:
# - Normal exit
# - Error exit
# - Signal termination
```

#### Optional File Processing Pattern

```bash
for file in prefix.{gui,f9,hessopt}; do
    if [[ -f "$file" ]]; then
        process_file "$file"
    fi
done
```

#### Graceful Degradation Pattern

```bash
if command -v gum &>/dev/null; then
    # Use gum
    gum style --bold "Message"
else
    # Fallback
    echo "Message"
fi
```

### Module Dependency Graph

```
cry-config.sh (bootstrap)
    ↓
cry-logging.sh
    ↓
core.sh
    ↓
├─→ cry-ui.sh
│   ↓
├─→ cry-parallel.sh
│   ↓
├─→ cry-scratch.sh
│   ↓
├─→ cry-stage.sh
│   ↓
├─→ cry-exec.sh
│
└─→ cry-help.sh
```

**Loading Rules:**
1. Never load modules before their dependencies
2. Use cry_require to enforce correct order
3. cry-config and cry-logging have no dependencies
4. core.sh must be loaded after config and logging
5. All other modules require core.sh

---

## Quick Reference

### Module Loading

```bash
# Bootstrap
source lib/cry-config.sh
source lib/cry-logging.sh
source lib/core.sh

# Load all modules
cry_require_all

# Or load selectively
cry_require cry-ui
cry_require cry-parallel
```

### Configuration

```bash
# Show configuration
cry_config_show

# Validate paths
cry_config_validate

# Get value
root=$(cry_config_get CRY23_ROOT)
```

### Logging

```bash
cry_info "Information message"
cry_warn "Warning message"
cry_error "Error message"
cry_debug "Debug message"  # Requires CRY_LOG_LEVEL=debug
```

### UI

```bash
ui_banner
ui_card "Title" "Line 1" "Line 2"
ui_success "Operation succeeded"
ui_error "Operation failed"
ui_spin "Loading" "sleep 5"
```

### Parallelism

```bash
declare -A CRY_JOB
parallel_setup 14 CRY_JOB
echo "Mode: ${CRY_JOB[MODE]}"
echo "Ranks: ${CRY_JOB[MPI_RANKS]}"
```

### Scratch Management

```bash
trap 'scratch_cleanup' EXIT
scratch_create "myjob"
scratch_stage_main "input.d12"
scratch_stage_auxiliary "input"
# ... work ...
scratch_retrieve_results "input"
```

### File Staging

```bash
stage_inputs "myjob" "$WORK_DIR" "$PWD"
# ... calculation ...
stage_retrieve_results "myjob" "$WORK_DIR" "$PWD"
```

### Execution

```bash
declare -A CRY_JOB=(
    [MODE]="Hybrid MPI/OpenMP"
    [EXE_PATH]="/path/to/PcrystalOMP"
    [MPI_RANKS]="14"
    [file_prefix]="myjob"
)

if exec_crystal_run CRY_JOB; then
    ui_success "Calculation completed"
else
    analyze_failure "myjob.out"
    exit 1
fi
```

### Help System

```bash
# Show interactive help
help_show_main

# Show specific tutorial
show_tutorial "usage.md"
```

---

## Troubleshooting

### Module Not Found

```bash
# Error: Module not found: cry-ui
# Solution: Check LIB_DIR is correct
echo "LIB_DIR: $LIB_DIR"
ls -la "$LIB_DIR/cry-ui.sh"
```

### Circular Dependency

```bash
# Error: Module loading loop detected
# Solution: Review module dependencies, ensure no cycles
# Allowed: A → B → C
# Forbidden: A → B → C → A
```

### State Not Persisting

```bash
# Problem: CRY_JOB changes not visible
# Solution: Pass by name reference
parallel_setup 14 CRY_JOB  # Correct
# Not: parallel_setup 14 $CRY_JOB  # Wrong
```

### Cleanup Not Running

```bash
# Problem: Scratch directory not removed
# Solution: Set trap before creating scratch
trap 'scratch_cleanup' EXIT
scratch_create "myjob"
```

---

## Version History

- **1.0.0** (2025-01-15) - Initial modular refactoring
  - Split monolithic 372-line script into 9 modules
  - Comprehensive testing framework
  - Production-ready architecture

---

## See Also

- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture overview
- [TESTING.md](TESTING.md) - Testing strategy and guidelines
- [CONTRIBUTING.md](CONTRIBUTING.md) - Development workflow
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Common issues and solutions
