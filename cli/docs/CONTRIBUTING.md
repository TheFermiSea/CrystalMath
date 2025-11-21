# Contributing to CRY_CLI

Welcome! This guide will help you contribute to CRY_CLI, a modular Bash-based CLI tool for running CRYSTAL23 computational chemistry calculations.

## Table of Contents

- [Getting Started](#getting-started)
- [Code Organization](#code-organization)
- [Module Development](#module-development)
- [Testing Requirements](#testing-requirements)
- [Code Style](#code-style)
- [Pull Request Process](#pull-request-process)
- [Common Tasks](#common-tasks)

## Getting Started

### Prerequisites

Before contributing, ensure you have:

- **Bash 4.0 or higher** (required for associative arrays)
  - Check version: `bash --version`
  - macOS users: `brew install bash`
- **CRYSTAL23** installed (for integration testing)
  - Set `BIN_DIR` environment variable to CRYSTAL23 binary directory
- **bats-core** for testing
  - Install: `brew install bats-core` (macOS) or `npm install -g bats` (cross-platform)
- **shellcheck** (recommended)
  - Install: `brew install shellcheck` or via package manager
- **gum** (optional, for enhanced UI)
  - Install: `brew install gum` or `go install github.com/charmbracelet/gum@latest`

### Local Development Setup

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd CRY_CLI
   ```

2. **Set up development environment:**
   ```bash
   # Add bin/ to your PATH for testing
   export PATH="$PWD/bin:$PATH"

   # Set CRYSTAL23 binary directory (adjust to your installation)
   export BIN_DIR="/path/to/crystal23/bin"
   ```

3. **Verify installation:**
   ```bash
   # Check runcrystal can load modules
   runcrystal --help

   # Run test suite
   bats tests/test_cry-parallel.bats
   ```

### Running runcrystal from Source

During development, you can run runcrystal directly without installation:

```bash
# From the project root
./bin/runcrystal test_input 4

# Or after adding to PATH
runcrystal test_input 4
```

The modular design means changes to `lib/*.sh` files are immediately reflected when you run the script.

## Code Organization

### Directory Structure

```
CRY_CLI/
├── bin/
│   ├── runcrystal              # Main execution script (thin wrapper)
│   └── cry-docs                # Documentation browser (standalone)
├── lib/
│   ├── core.sh                 # Module loader and initialization
│   ├── cry-config.sh           # Configuration & environment setup
│   ├── cry-ui.sh               # Visual components (gum wrappers)
│   ├── cry-parallel.sh         # Parallelism logic & resource allocation
│   ├── cry-scratch.sh          # Scratch space management
│   ├── cry-stage.sh            # File staging utilities
│   ├── cry-exec.sh             # CRYSTAL23 execution wrapper
│   ├── cry-help.sh             # Help system & integration point
│   └── cry-logging.sh          # Logging infrastructure
├── tests/
│   ├── helpers.bash            # Common test utilities
│   ├── test_cry-parallel.bats  # Unit tests for cry-parallel module
│   └── mocks/                  # Mock executables for testing
├── docs/
│   └── ARCHITECTURE.md         # Design philosophy and architecture
└── share/
    └── tutorials/              # Converted markdown documentation
```

### Module Responsibilities

**bin/runcrystal** (Main Script)
- Argument parsing
- Module coordination via `cry_require()`
- Execute calculation workflow
- Keep under 100 lines by delegating to libraries

**lib/core.sh** (Module Loader)
- Provides `cry_require()` for dynamic module loading
- Tracks loaded modules to prevent re-sourcing
- No dependencies (base module)

**lib/cry-config.sh** (Configuration)
- Environment variable setup
- Path detection (CRYSTAL23 binaries)
- Theme configuration
- First module loaded (bootstrap)

**lib/cry-ui.sh** (UI Components)
- Banner, cards, status lines
- Color/theme management
- Gum integration for interactive elements
- Shared by both runcrystal and cry-docs

**lib/cry-parallel.sh** (Parallelism)
- MPI rank and OpenMP thread calculation
- Environment variable configuration (OMP_NUM_THREADS, I_MPI_PIN_DOMAIN)
- Execution mode determination (Serial vs Hybrid)

**lib/cry-scratch.sh** (Scratch Space)
- Temporary workspace creation
- Cleanup on exit
- Resource isolation

**lib/cry-stage.sh** (File Staging)
- Input file staging to scratch directory
- Result retrieval from scratch to working directory
- File type detection and handling

**lib/cry-exec.sh** (Execution)
- CRYSTAL23 process execution
- Output redirection
- Exit code handling

**lib/cry-help.sh** (Help System)
- Help menu display
- Integration with cry-docs
- Documentation launcher

## Module Development

### Creating a New Module

1. **Create the module file** in `lib/`:
   ```bash
   touch lib/cry-newfeature.sh
   chmod +x lib/cry-newfeature.sh
   ```

2. **Use the module template structure:**
   ```bash
   #!/bin/bash
   # Module: cry-newfeature
   # Description: Brief description of what this module does
   # Dependencies: core, cry-ui (list other required modules)

   # Error handling
   set -euo pipefail

   # Module-level constants
   MODULE_NAME="cry-newfeature"
   MODULE_VERSION="1.0.0"

   # Module-specific constants
   readonly FEATURE_DEFAULT_VALUE="example"

   # Public functions (called by other modules)

   newfeature_main_function() {
       # Function description
       #
       # Args:
       #   $1 - param1: Description of first parameter
       #   $2 - param2: Description of second parameter
       #
       # Returns: 0 on success, 1 on failure
       #
       # Example:
       #   newfeature_main_function "input" 42

       local param1="$1"
       local param2="$2"

       # Implementation here

       return 0
   }

   # Private functions (internal to module)

   _newfeature_helper() {
       # Private helper function
       # Use underscore prefix for private functions

       return 0
   }

   _newfeature_init() {
       # Module initialization (called automatically)
       # Returns: 0 on success
       return 0
   }

   # Auto-initialize
   _newfeature_init
   ```

3. **Load the module** in `bin/runcrystal`:
   ```bash
   cry_require cry-newfeature
   ```

### Naming Conventions

**Module Names:**
- Use `cry-` prefix for all module filenames: `cry-parallel.sh`
- Use lowercase with hyphens: `cry-multi-word.sh`

**Function Names:**
- **Public functions**: Use module prefix without `cry-`
  - Example: `parallel_setup()`, `stage_inputs()`, `ui_banner()`
- **Private functions**: Use underscore prefix
  - Example: `_parallel_get_cpu_count()`, `_stage_validate_file()`
- Use snake_case: `get_file_size()` not `getFileSize()`

**Variable Names:**
- **Module constants**: Use UPPER_CASE with readonly
  - Example: `readonly DEFAULT_OMP_STACKSIZE="256M"`
- **Local variables**: Use lowercase with underscores
  - Example: `local input_file="$1"`
- **Global job state**: Use associative array `CRY_JOB`
  - Example: `CRY_JOB[MODE]="Hybrid MPI/OpenMP"`

### Using cry_require()

The `cry_require()` function (from `lib/core.sh`) loads modules on-demand:

```bash
# In runcrystal or other modules
cry_require cry-parallel  # Loads lib/cry-parallel.sh
cry_require cry-ui        # Loads lib/cry-ui.sh

# Module is only loaded once, subsequent calls are no-ops
cry_require cry-parallel  # Returns immediately (already loaded)
```

**Benefits:**
- Prevents duplicate loading
- Explicit dependency tracking
- Faster startup (only load what you need)

## Testing Requirements

### Writing Unit Tests with bats

Create a test file for each module in `tests/`:

```bash
#!/usr/bin/env bats
# Test suite for cry-newfeature module

# Setup and teardown
setup() {
    # Load test helpers
    load helpers
    setup_test_env

    # Load the module under test
    export LIB_DIR="${BATS_TEST_DIRNAME}/../lib"
    source "${LIB_DIR}/cry-newfeature.sh"

    # Mock dependencies if needed
    export CRY_CMD_CRYSTAL="${BATS_TEST_DIRNAME}/mocks/crystal"
}

teardown() {
    teardown_test_env
}

# Test: Basic functionality
@test "newfeature_main_function: Returns success with valid input" {
    run newfeature_main_function "test_input" 42

    [ "$status" -eq 0 ]
    assert_output_contains "Expected output"
}

# Test: Error handling
@test "newfeature_main_function: Rejects invalid input" {
    run newfeature_main_function "" 0

    [ "$status" -eq 1 ]
    assert_output_contains "ERROR"
}

# Test: Edge cases
@test "newfeature_main_function: Handles edge case correctly" {
    run newfeature_main_function "edge_case" -1

    [ "$status" -eq 0 ]
    assert_output_contains "handled"
}
```

### Using Test Helpers (tests/helpers.bash)

The test helper library provides useful utilities:

**Environment Setup:**
```bash
setup_test_env          # Creates TEST_TEMP_DIR, sets up mocks
teardown_test_env       # Cleans up temporary files
```

**Mock Commands:**
```bash
# Mock a command with specific output and exit code
mock_command "mpirun" "MPI started" 0

# Use environment variables for mock paths
export CRY_CMD_MPIRUN="${BATS_TEST_DIRNAME}/mocks/mpirun"
```

**Assertions:**
```bash
assert_success                        # Exit code is 0
assert_failure                        # Exit code is non-zero
assert_status_equals 1                # Exit code equals specific value
assert_output_contains "expected"     # Output contains string
assert_output_not_contains "bad"      # Output does not contain string
assert_output_matches "^[0-9]+$"      # Output matches regex
assert_file_exists "/path/to/file"    # File exists
assert_file_not_exists "/path/to/file"# File does not exist
assert_dir_exists "/path/to/dir"      # Directory exists
```

**Test File Creation:**
```bash
# Create a test input file
local input_path=$(create_test_input "test.d12" "INPUT CONTENT")
```

### Mock System Usage (CRY_CMD_* Variables)

To test without requiring actual executables, use mock commands:

**In tests/mocks/mpirun:**
```bash
#!/usr/bin/env bash
# Mock: mpirun
echo "Mock MPI started with $# arguments"
exit 0
```

**In test setup:**
```bash
setup() {
    export CRY_CMD_MPIRUN="${BATS_TEST_DIRNAME}/mocks/mpirun"
    export CRY_CMD_GUM="${BATS_TEST_DIRNAME}/mocks/gum"
    export CRY_CMD_CRYSTALOMP="${BATS_TEST_DIRNAME}/mocks/crystalOMP"
}
```

**In module code:**
```bash
# Use CRY_CMD_* if set, otherwise use system command
local mpirun_cmd="${CRY_CMD_MPIRUN:-mpirun}"
"$mpirun_cmd" -n 4 ./crystal
```

### Running Tests Locally

```bash
# Run all tests
bats tests/

# Run specific test file
bats tests/test_cry-parallel.bats

# Run with verbose output
bats -t tests/test_cry-parallel.bats

# Run with debugging
CRY_TEST_DEBUG=1 bats tests/test_cry-parallel.bats
```

### Test Coverage Expectations

- **New modules**: Aim for 80%+ coverage
- **Critical modules** (cry-parallel, cry-exec): 90%+ coverage
- **Test categories required**:
  - Happy path (successful execution)
  - Error handling (invalid inputs)
  - Edge cases (boundary conditions)
  - Integration (module interactions)

## Code Style

### Bash Best Practices

**Always use strict error handling:**
```bash
set -euo pipefail
# -e: Exit on error
# -u: Exit on undefined variable
# -o pipefail: Exit on pipe failure
```

**Use local variables in functions:**
```bash
my_function() {
    local input="$1"        # Good: local scope
    output="$2"             # Bad: global scope
}
```

**Quote all variable expansions:**
```bash
local file_path="$1"        # Good: quoted
echo "$file_path"           # Good: quoted
cd $file_path               # Bad: unquoted (breaks with spaces)
```

**Use readonly for constants:**
```bash
readonly DEFAULT_VALUE="constant"   # Good: cannot be changed
CONSTANT_VALUE="constant"           # Bad: can be modified
```

**Prefer [[ ]] over [ ]:**
```bash
if [[ "$var" == "value" ]]; then    # Good: [[ ]] is more robust
if [ "$var" = "value" ]; then       # Acceptable but less flexible
```

### Function Documentation Format

Document all public functions with this format:

```bash
parallel_setup() {
    # Configure CRYSTAL23 hybrid MPI/OpenMP execution
    #
    # Determines execution mode (Serial/OpenMP vs Hybrid MPI/OpenMP)
    # and sets appropriate environment variables.
    #
    # Args:
    #   $1 - nprocs: Number of MPI processes (1 = Serial/OpenMP mode)
    #   $2 - job_state_ref: Name reference to associative array (CRY_JOB)
    #
    # Returns:
    #   0 on success
    #   1 on validation failure
    #
    # Populates job_state with:
    #   MODE - "Serial/OpenMP" or "Hybrid MPI/OpenMP"
    #   EXE_PATH - Path to crystalOMP or PcrystalOMP
    #   MPI_RANKS - Number of MPI processes (empty for serial mode)
    #   THREADS_PER_RANK - OpenMP threads per MPI rank
    #
    # Environment variables set:
    #   OMP_NUM_THREADS - OpenMP thread count
    #   OMP_STACKSIZE - OpenMP stack size (256M)
    #
    # Example:
    #   declare -A CRY_JOB
    #   parallel_setup 4 CRY_JOB

    # Implementation...
}
```

**Key elements:**
- Brief description (one line)
- Detailed explanation (optional)
- Args section with parameter descriptions
- Returns section with exit codes
- Side effects (modified variables, environment)
- Example usage

### Error Handling Patterns

**Return codes vs exit:**
- **Functions**: Use `return 0/1` (allows caller to handle error)
- **Main script**: Use `exit 0/1` (terminates program)

**Error reporting pattern:**
```bash
my_function() {
    local input="$1"

    # Validation with error message to stderr
    if [[ -z "$input" ]]; then
        echo "ERROR: input parameter is required" >&2
        return 1
    fi

    # File existence check
    if [[ ! -f "$input" ]]; then
        echo "ERROR: file not found: $input" >&2
        return 1
    fi

    # Success
    return 0
}

# Caller handles errors
if ! my_function "input.txt"; then
    echo "Failed to process input"
    exit 1
fi
```

**Use traps for cleanup:**
```bash
cleanup() {
    rm -rf "$TEMP_DIR"
}

trap cleanup EXIT

# Script continues, cleanup runs on exit (success or failure)
```

### shellcheck Compliance

shellcheck is integrated into the CI/CD pipeline and runs automatically on every push and pull request. Local validation is strongly recommended before committing.

**Quick validation (recommended):**
```bash
# Run shellcheck on all project scripts
./dev/shellcheck-all.sh
```

**Manual validation:**
```bash
# Check specific file
shellcheck lib/cry-parallel.sh

# Check all library files
shellcheck lib/*.sh

# Check main executable
shellcheck bin/runcrystal

# Check with specific shell
shellcheck -s bash lib/cry-parallel.sh
```

**Configuration:**

The project uses `.shellcheckrc` for global configuration. Common warnings are disabled for legitimate reasons:
- SC1090/SC1091: Dynamic sourcing (modular library loading)
- SC2034: Variables exported for external modules
- SC2153: Uppercase keys in associative arrays
- SC2296: zsh-specific parameter expansions

**Adding shellcheck exceptions:**

Only disable warnings when absolutely necessary and document the reason:
```bash
# shellcheck disable=SC2034  # Exported for use by CRYSTAL binary
export CRY_SCRATCH_DIR="/tmp/crystal_scratch"
```

**CI Integration:**

GitHub Actions runs shellcheck automatically:
- Workflow: `.github/workflows/shellcheck.yml`
- Triggers: Push to main/develop, pull requests
- Uses: Custom validation script + action-shellcheck

**Severity levels:**
- **error**: Must fix before merging
- **warning**: Must fix before merging
- **info/style**: Optional (many disabled in `.shellcheckrc`)

## Pull Request Process

### Pre-submission Checklist

Before submitting a pull request:

- [ ] **Code works locally**
  - [ ] Tested with sample CRYSTAL23 input files
  - [ ] Tested both serial (nprocs=1) and parallel (nprocs>1) modes

- [ ] **Tests pass**
  - [ ] All existing tests still pass: `bats tests/`
  - [ ] New tests added for new functionality
  - [ ] Test coverage is adequate (80%+ for new code)

- [ ] **Code quality**
  - [ ] shellcheck passes with no warnings: `./dev/shellcheck-all.sh`
  - [ ] Functions are documented with comment headers
  - [ ] Variable names are descriptive
  - [ ] Error handling is consistent

- [ ] **Documentation updated**
  - [ ] ARCHITECTURE.md updated if design changed
  - [ ] Function comments added for new public functions
  - [ ] README.md updated if user-facing changes

### Testing Checklist

Your PR should include:

1. **Unit tests** for new functions
   - Happy path test
   - Error handling test
   - Edge case tests

2. **Integration tests** if multiple modules interact
   - Test data flow between modules
   - Test error propagation

3. **Manual testing results** in PR description
   - System tested on (OS, Bash version)
   - CRYSTAL23 version tested with
   - Example command that was tested

### Documentation Requirements

Update the following as needed:

- **Code comments**: Document all public functions
- **ARCHITECTURE.md**: If you changed module responsibilities or added new modules
- **README.md**: If you changed user-facing behavior or added new features
- **CONTRIBUTING.md** (this file): If you changed development workflows

### Review Process

1. **Submit PR** with clear description
   - What problem does this solve?
   - What changes were made?
   - How was it tested?

2. **Automated checks** will run
   - shellcheck
   - bats tests
   - (Future: CI/CD integration)

3. **Code review** by maintainers
   - Code quality assessment
   - Design pattern consistency
   - Test adequacy review

4. **Address feedback**
   - Make requested changes
   - Respond to comments
   - Update PR description if scope changed

5. **Merge** when approved
   - Squash commits if requested
   - Ensure commit message is descriptive

## Common Tasks

### Adding a New Staging File Type

**Location:** `lib/cry-stage.sh`

The staging module handles copying input files to scratch space and retrieving results.

**Steps:**

1. **Identify the file extension** (e.g., `.gui` for CRYSTAL GUI files)

2. **Add detection logic** in `stage_inputs()`:
   ```bash
   stage_inputs() {
       local file_prefix="$1"
       local work_dir="$2"
       local original_dir="$3"

       # Existing: .d12 (required)
       cp "${original_dir}/${file_prefix}.d12" "${work_dir}/"

       # Existing: .d3 (optional)
       if [[ -f "${original_dir}/${file_prefix}.d3" ]]; then
           cp "${original_dir}/${file_prefix}.d3" "${work_dir}/"
       fi

       # New: .gui (optional GUI file)
       if [[ -f "${original_dir}/${file_prefix}.gui" ]]; then
           cp "${original_dir}/${file_prefix}.gui" "${work_dir}/"
           echo "Staged GUI file: ${file_prefix}.gui"
       fi
   }
   ```

3. **Add retrieval logic** in `stage_retrieve_results()`:
   ```bash
   stage_retrieve_results() {
       local file_prefix="$1"
       local work_dir="$2"
       local original_dir="$3"

       # Existing output files
       cp "${work_dir}/${file_prefix}.out" "${original_dir}/" 2>/dev/null || true

       # New: Retrieve modified .gui file
       if [[ -f "${work_dir}/${file_prefix}.gui" ]]; then
           cp "${work_dir}/${file_prefix}.gui" "${original_dir}/"
           echo "Retrieved GUI file: ${file_prefix}.gui"
       fi
   }
   ```

4. **Add tests** in `tests/test_cry-stage.bats`:
   ```bash
   @test "stage_inputs: Stages .gui file if present" {
       local test_prefix="test_job"
       create_test_input "${test_prefix}.d12" "INPUT"
       create_test_input "${test_prefix}.gui" "GUI DATA"

       run stage_inputs "$test_prefix" "$TEST_TEMP_DIR/scratch" "$TEST_TEMP_DIR/data"

       assert_success
       assert_file_exists "$TEST_TEMP_DIR/scratch/${test_prefix}.gui"
   }
   ```

5. **Update documentation** in ARCHITECTURE.md (if file type is significant)

### Modifying Parallel Execution Logic

**Location:** `lib/cry-parallel.sh`

**Example: Changing thread allocation strategy**

1. **Locate the calculation** in `parallel_setup()`:
   ```bash
   # Current: Equal threads per rank
   local threads_per_rank=$((total_cores / nprocs))

   # New: Reserve 2 cores for system, distribute rest
   local available_cores=$((total_cores - 2))
   local threads_per_rank=$((available_cores / nprocs))
   if [[ "$threads_per_rank" -lt 1 ]]; then
       threads_per_rank=1
   fi
   ```

2. **Update environment variables** if needed:
   ```bash
   # New: Add memory binding configuration
   export OMP_PROC_BIND=close
   export OMP_PLACES=cores
   ```

3. **Add to job state** for tracking:
   ```bash
   job_state[RESERVED_CORES]=2
   job_state[AVAILABLE_CORES]="$available_cores"
   ```

4. **Update `parallel_print_config()`** to display new info:
   ```bash
   echo "  Reserved Cores: ${job_state[RESERVED_CORES]}"
   echo "  Available Cores: ${job_state[AVAILABLE_CORES]}"
   ```

5. **Add tests** for new behavior:
   ```bash
   @test "parallel_setup: Reserves 2 cores for system" {
       _parallel_get_cpu_count() { echo 8; }
       export -f _parallel_get_cpu_count

       parallel_setup 2 TEST_JOB

       # 8 total - 2 reserved = 6 available / 2 ranks = 3 threads per rank
       [ "${TEST_JOB[THREADS_PER_RANK]}" = "3" ]
   }
   ```

### Adding a New Help Topic

**Location:** `lib/cry-help.sh`

1. **Add topic to help menu** in `help_show_main()`:
   ```bash
   help_show_main() {
       cat << 'EOF'
   CRY_CLI Help System

   Topics:
     1. Basic Usage
     2. Parallel Execution
     3. File Staging
     4. New Topic         # Your new topic
     5. Troubleshooting

   Select a topic:
   EOF

       local choice
       read -r choice

       case "$choice" in
           1) help_topic_usage ;;
           2) help_topic_parallel ;;
           3) help_topic_staging ;;
           4) help_topic_new ;;      # Your new handler
           5) help_topic_troubleshooting ;;
       esac
   }
   ```

2. **Create topic handler function:**
   ```bash
   help_topic_new() {
       # Display help for new topic
       cat << 'EOF'
   New Topic Help
   ==============

   This section covers...

   Examples:
     runcrystal input 4

   See also:
     - Related topic 1
     - Related topic 2
   EOF
   }
   ```

3. **Use gum for interactive display** (optional):
   ```bash
   help_topic_new() {
       local content="Your help content here..."

       if command -v gum &>/dev/null; then
           echo "$content" | gum format
       else
           echo "$content"
       fi
   }
   ```

### Extending UI Themes

**Location:** `lib/cry-ui.sh`

1. **Add new color to theme:**
   ```bash
   # In ui_theme_setup()
   case "$CRY_THEME" in
       "dark")
           export CRY_COLOR_PRIMARY="#00D9FF"
           export CRY_COLOR_SUCCESS="#00FF87"
           export CRY_COLOR_ERROR="#FF5F87"
           export CRY_COLOR_WARNING="#FFD700"      # New: Warning color
           ;;
       "light")
           export CRY_COLOR_PRIMARY="#0066CC"
           export CRY_COLOR_SUCCESS="#00AA00"
           export CRY_COLOR_ERROR="#CC0000"
           export CRY_COLOR_WARNING="#FF8C00"      # New: Warning color
           ;;
   esac
   ```

2. **Create UI function for new color:**
   ```bash
   ui_warning() {
       # Print warning message with theme color
       # Args: $1 - message: Warning text to display
       local message="$1"

       if command -v gum &>/dev/null; then
           gum style --foreground="$CRY_COLOR_WARNING" "⚠ WARNING: $message"
       else
           echo "WARNING: $message"
       fi
   }
   ```

3. **Use in other modules:**
   ```bash
   # In any module that loads cry-ui
   if [[ "$threads_per_rank" -lt 2 ]]; then
       ui_warning "Low thread count may impact performance"
   fi
   ```

4. **Add theme tests:**
   ```bash
   @test "ui_warning: Displays warning message" {
       run ui_warning "Test warning"

       assert_success
       assert_output_contains "WARNING"
       assert_output_contains "Test warning"
   }
   ```

## Questions?

If you have questions not covered in this guide:

- Check **ARCHITECTURE.md** for design philosophy
- Look at existing modules for patterns
- Open an issue on GitHub with the `question` label
- Contact the maintainers

Thank you for contributing to CRY_CLI!
