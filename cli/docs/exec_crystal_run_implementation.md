# exec_crystal_run Implementation

## Overview

Implementation of CRYSTAL23 calculation execution function in `lib/cry-exec.sh`.

## Function: `exec_crystal_run()`

### Purpose
Execute CRYSTAL23 calculations with proper command construction based on execution mode (Serial/OpenMP or Parallel/MPI).

### Signature
```bash
exec_crystal_run job_state_ref
```

### Parameters
- `job_state_ref`: Name reference to an associative array containing job configuration

### Required Job State Keys
- `MODE`: Execution mode - "Serial/OpenMP" or "Parallel/MPI"
- `EXE_PATH`: Full path to CRYSTAL23 executable (crystalOMP or PcrystalOMP)
- `file_prefix`: Base name for output files
- `MPI_RANKS`: Number of MPI ranks (required only for Parallel/MPI mode)

### Return Value
Returns the exit code from the CRYSTAL23 execution (0 for success, non-zero for failure)

## Implementation Details

### Serial/OpenMP Mode
```bash
$EXE_PATH < INPUT > ${file_prefix}.out
```

### Parallel/MPI Mode
```bash
$MPI_BIN -np $MPI_RANKS $EXE_PATH < INPUT > ${file_prefix}.out
```

Where `$MPI_BIN` is determined by:
- `$I_MPI_ROOT/bin/mpirun` if `I_MPI_ROOT` environment variable is set
- `mpirun` otherwise (uses system PATH)

### Visual Feedback
- Uses `gum spin` if available for animated progress indicator
- Falls back to simple text output if gum is not installed

### Error Handling
- Validates required job state keys before execution
- Returns proper exit codes for validation failures
- Logs execution details via `_exec_log()` function

## Example Usage

### Serial Execution
```bash
declare -A crystal_job=(
    [MODE]="Serial/OpenMP"
    [EXE_PATH]="/home/user/CRYSTAL23/bin/Linux-ifort_i64_omp/v1.0.1/crystalOMP"
    [file_prefix]="silicon"
)

exec_crystal_run crystal_job
exit_code=$?
```

### Parallel Execution
```bash
declare -A crystal_job=(
    [MODE]="Parallel/MPI"
    [EXE_PATH]="/home/user/CRYSTAL23/bin/Linux-ifort_i64_omp/v1.0.1/PcrystalOMP"
    [MPI_RANKS]="8"
    [file_prefix]="silicon_parallel"
)

exec_crystal_run crystal_job
exit_code=$?
```

## Integration with runcrystal

The function is designed to be called from the main `runcrystal` script after:
1. Job state has been configured
2. Working directory has been prepared
3. INPUT file has been staged

Example integration:
```bash
# In bin/runcrystal
cd "$WORK_DIR"

# Stage files...
# Prepare INPUT...

# Execute calculation
if ! exec_crystal_run CRY_JOB; then
    ui_error "Calculation failed"
    exit 1
fi
```

## Testing

### Logic Verification
Run `tests/test_exec_logic.sh` to verify command construction logic:
```bash
./tests/test_exec_logic.sh
```

This tests:
1. Serial mode command generation
2. Parallel mode with default mpirun
3. Parallel mode with I_MPI_ROOT set

All tests verify exact command string construction.

## Compatibility Notes

- **Bash Version**: Requires Bash 4.0+ for associative arrays and name references
- **System Requirements**:
  - MPI implementation (Intel MPI or OpenMPI) for parallel mode
  - Optional: `gum` for enhanced UI
- **Environment Variables**:
  - `I_MPI_ROOT`: Location of Intel MPI installation (optional)

## Related Modules

- `cry-ui.sh`: UI functions for visual feedback
- `cry-logging.sh`: Execution logging via `_exec_log()`
- `cry-scratch.sh`: Working directory management

## References

- Original implementation: `runcrystal.monolithic` lines 328-347
- Issue: CRY_CLI-a2j
- Module: lib/cry-exec.sh lines 77-159
