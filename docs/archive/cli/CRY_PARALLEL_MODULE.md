# cry-parallel Module Documentation

**Module:** `lib/cry-parallel.sh`
**Version:** 1.0.0
**Purpose:** CRYSTAL23 hybrid MPI/OpenMP execution configuration

## Overview

The `cry-parallel` module handles parallelism configuration for CRYSTAL23 quantum chemistry calculations. It automatically determines the optimal execution mode (Serial/OpenMP or Hybrid MPI/OpenMP), calculates thread distribution, and sets Intel MPI and OpenMP runtime environment variables.

## Key Features

- **Automatic Mode Detection**: Chooses between serial and hybrid parallelism based on requested MPI ranks
- **Thread Distribution**: Intelligently calculates threads per MPI rank based on available CPU cores
- **Intel MPI/OpenMP Tuning**: Configures environment variables for optimal performance on Intel architectures
- **Cross-Platform Support**: Works on Linux (with nproc) and macOS (with sysctl)
- **Input Validation**: Validates nprocs, BIN_DIR, and executable paths

## Public Functions

### parallel_setup(nprocs, job_state_ref)

Configures CRYSTAL23 hybrid MPI/OpenMP execution environment.

**Arguments:**
- `$1` - `nprocs`: Number of MPI processes (1 = Serial/OpenMP mode, >1 = Hybrid mode)
- `$2` - `job_state_ref`: Name reference to associative array (e.g., `CRY_JOB`)

**Returns:**
- `0` on success
- `1` on validation failure

**Populates job_state with:**
- `MODE` - "Serial/OpenMP" or "Hybrid MPI/OpenMP"
- `EXE_PATH` - Path to `crystalOMP` or `PcrystalOMP`
- `MPI_RANKS` - Number of MPI processes (empty for serial mode)
- `THREADS_PER_RANK` - OpenMP threads per MPI rank
- `TOTAL_CORES` - Total CPU cores available

**Environment Variables Set:**
- `OMP_NUM_THREADS` - OpenMP thread count
- `OMP_STACKSIZE` - OpenMP stack size (256M for CRYSTAL23)
- `I_MPI_PIN_DOMAIN` - Intel MPI thread pinning (only for hybrid mode)
- `KMP_AFFINITY` - Intel OpenMP thread affinity (only for hybrid mode)

**Example Usage:**
```bash
#!/bin/bash
source lib/cry-parallel.sh

declare -A CRY_JOB=()
export BIN_DIR="/path/to/CRYSTAL23/bin/Linux-ifort_i64_omp/v1.0.1"

# Configure for 4 MPI ranks
parallel_setup 4 CRY_JOB

echo "Mode: ${CRY_JOB[MODE]}"
echo "Executable: ${CRY_JOB[EXE_PATH]}"
echo "MPI Ranks: ${CRY_JOB[MPI_RANKS]}"
echo "Threads per Rank: ${CRY_JOB[THREADS_PER_RANK]}"
```

### parallel_validate_executables(exe_path)

Validates CRYSTAL23 executable exists and is executable.

**Arguments:**
- `$1` - `exe_path`: Path to CRYSTAL23 executable

**Returns:**
- `0` if valid
- `1` if not found or not executable

**Example:**
```bash
if parallel_validate_executables "${CRY_JOB[EXE_PATH]}"; then
    echo "Executable is valid"
else
    echo "ERROR: Executable validation failed"
    exit 1
fi
```

### parallel_print_config(job_state_ref)

Prints parallel execution configuration for debugging.

**Arguments:**
- `$1` - `job_state_ref`: Name reference to associative array

**Returns:** `0` on success

**Example Output (Serial Mode):**
```
Parallel Configuration:
  Mode: Serial/OpenMP
  Executable: /path/to/crystalOMP
  Total Cores: 32
  OpenMP Threads: 32
Environment Variables:
  OMP_NUM_THREADS=32
  OMP_STACKSIZE=256M
```

**Example Output (Hybrid Mode):**
```
Parallel Configuration:
  Mode: Hybrid MPI/OpenMP
  Executable: /path/to/PcrystalOMP
  Total Cores: 32
  MPI Ranks: 4
  Threads per Rank: 8
Environment Variables:
  OMP_NUM_THREADS=8
  OMP_STACKSIZE=256M
  I_MPI_PIN_DOMAIN=omp
  KMP_AFFINITY=compact,1,0,granularity=fine
```

## Execution Modes

### Serial/OpenMP Mode (nprocs ≤ 1)

- **Executable:** `crystalOMP`
- **Parallelism:** Single MPI process with OpenMP threads across all cores
- **Use Case:** Single-node calculations where memory is not a bottleneck
- **Configuration:**
  ```bash
  export OMP_NUM_THREADS=<total_cores>
  export OMP_STACKSIZE=256M
  unset I_MPI_PIN_DOMAIN
  ```

### Hybrid MPI/OpenMP Mode (nprocs > 1)

- **Executable:** `PcrystalOMP`
- **Parallelism:** Multiple MPI ranks, each with OpenMP threads
- **Use Case:** Large calculations requiring distributed memory, multi-node HPC
- **Thread Distribution:** `threads_per_rank = total_cores / nprocs` (minimum 1)
- **Configuration:**
  ```bash
  export OMP_NUM_THREADS=<threads_per_rank>
  export OMP_STACKSIZE=256M
  export I_MPI_PIN_DOMAIN=omp
  export KMP_AFFINITY=compact,1,0,granularity=fine
  ```

## Intel MPI/OpenMP Tuning

### I_MPI_PIN_DOMAIN=omp

Instructs Intel MPI to pin MPI ranks to leave space for OpenMP threads within each rank. This prevents thread oversubscription and ensures proper NUMA locality.

### KMP_AFFINITY=compact,1,0,granularity=fine

- **compact**: Pack OpenMP threads close together for cache locality
- **1,0**: Start at offset 1, stride 0 (sequential placement)
- **granularity=fine**: Use individual cores, not packages

This configuration is optimized for Intel Xeon processors with hyper-threading disabled.

## Thread Calculation Logic

```
if nprocs <= 1:
    mode = "Serial/OpenMP"
    threads = total_cores
else:
    mode = "Hybrid MPI/OpenMP"
    threads_per_rank = total_cores / nprocs
    if threads_per_rank < 1:
        threads_per_rank = 1  # Minimum 1 thread per rank (oversubscription)
```

## Error Handling

The module performs input validation and returns appropriate error codes:

- **Invalid nprocs (negative, zero, non-numeric):** Returns 1, prints error
- **BIN_DIR not set:** Returns 1, prints error
- **Executable not found:** Returns 1 (via `parallel_validate_executables`)
- **Executable not executable:** Returns 1 (via `parallel_validate_executables`)

## Testing

Comprehensive test suite: `tests/test_cry-parallel.bats`

**Test Coverage:**
- Serial and hybrid mode configuration ✓
- Input validation (nprocs, BIN_DIR) ✓
- Thread calculation logic (including oversubscription) ✓
- Executable validation ✓
- Cross-platform CPU detection ✓
- Integration workflow ✓

**Running Tests:**
```bash
# Requires bash 5.0+ for associative array support
BASH=/opt/homebrew/bin/bash bats tests/test_cry-parallel.bats
```

All 16 tests passing as of implementation.

## Integration with runcrystal

Expected usage in the main `bin/runcrystal` orchestrator:

```bash
#!/bin/bash
source lib/core.sh
cry_require cry-parallel

# Parse command-line arguments
NPROCS=${1:-1}
INPUT_FILE="$2"

# Setup configuration
export BIN_DIR="$CRY23_ROOT/bin/$ARCH/$VERSION"
declare -A CRY_JOB=()

# Configure parallelism
if ! parallel_setup "$NPROCS" CRY_JOB; then
    echo "ERROR: Failed to setup parallel execution"
    exit 1
fi

# Validate executable
if ! parallel_validate_executables "${CRY_JOB[EXE_PATH]}"; then
    echo "ERROR: CRYSTAL23 executable validation failed"
    exit 1
fi

# Debug output
parallel_print_config CRY_JOB

# Execute CRYSTAL23 (handled by cry-exec module)
# ...
```

## Dependencies

- **Core Modules:** `lib/core.sh` (for module loading)
- **System Commands:** `nproc` (Linux) or `sysctl` (macOS) for CPU detection
- **Bash Version:** 4.0+ required for associative arrays (`-A`)

## Performance Considerations

### Thread Binding

The Intel MPI and OpenMP settings ensure proper thread binding to physical cores:
- Prevents thread migration (reduces cache misses)
- Maintains NUMA locality (reduces memory latency)
- Avoids hyper-threading contention (assumes HT disabled)

### Oversubscription Handling

When `nprocs > total_cores`, the module ensures each MPI rank gets at least 1 thread. This allows testing on small systems but may cause performance degradation due to oversubscription.

**Warning:** For production, always use `nprocs <= total_cores` and ensure `total_cores / nprocs` is an integer for optimal load balancing.

## Future Enhancements

Potential improvements for future versions:

1. **GPU Support:** Detect and configure CUDA/HIP for GPU-accelerated CRYSTAL23
2. **NUMA-Aware Pinning:** Explicit CPU affinity masks for multi-socket systems
3. **Hybrid OMP/MPI Balance:** Automatically determine optimal MPI/OpenMP ratio based on problem size
4. **Cgroup Limits:** Respect cgroup CPU limits in containerized environments
5. **InfiniBand Detection:** Configure MPI for high-speed interconnects

## References

- **CRYSTAL23 User Manual:** [https://www.crystal.unito.it/](https://www.crystal.unito.it/)
- **Intel MPI Documentation:** [https://www.intel.com/content/www/us/en/developer/tools/oneapi/mpi-library.html](https://www.intel.com/content/www/us/en/developer/tools/oneapi/mpi-library.html)
- **OpenMP Specification:** [https://www.openmp.org/](https://www.openmp.org/)

---

**Last Updated:** 2025-11-19
**Implemented By:** Brian Squires (CRY_CLI-3cv)
**Status:** Complete, all tests passing
