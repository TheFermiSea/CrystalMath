#!/bin/bash
# Module: cry-parallel
# Description: CRYSTAL23 hybrid MPI/OpenMP execution configuration
# Dependencies: core, cry-ui

# Enable strict mode for better error handling
set -euo pipefail

# Default OpenMP stack size for CRYSTAL23
readonly DEFAULT_OMP_STACKSIZE="256M"

# Public functions

parallel_setup() {
    # Configure CRYSTAL23 hybrid MPI/OpenMP execution
    # Determines execution mode (Serial/OpenMP vs Hybrid MPI/OpenMP)
    # Sets environment variables for Intel MPI and OpenMP runtime
    # Populates job state with execution configuration
    #
    # Args:
    #   $1 - nprocs: Number of MPI processes (1 = Serial/OpenMP mode)
    #   $2 - job_state_ref: Name reference to associative array (CRY_JOB)
    #
    # Returns: 0 on success, 1 on validation failure
    #
    # Populates job_state with:
    #   MODE - "Serial/OpenMP" or "Hybrid MPI/OpenMP"
    #   EXE_PATH - Path to crystalOMP or PcrystalOMP
    #   MPI_RANKS - Number of MPI processes (empty for serial mode)
    #   THREADS_PER_RANK - OpenMP threads per MPI rank
    #   TOTAL_CORES - Total CPU cores available
    #
    # Environment variables set:
    #   OMP_NUM_THREADS - OpenMP thread count
    #   OMP_STACKSIZE - OpenMP stack size (256M for CRYSTAL23)
    #   I_MPI_PIN_DOMAIN - Intel MPI thread pinning (omp for hybrid mode)
    #   KMP_AFFINITY - Intel OpenMP thread affinity

    local nprocs="$1"
    local -n job_state=$2  # Name reference to associative array

    # Validate inputs
    if [[ ! "$nprocs" =~ ^[0-9]+$ ]]; then
        echo "ERROR: nprocs must be a positive integer: $nprocs" >&2
        return 1
    fi

    if [[ "$nprocs" -lt 1 ]]; then
        echo "ERROR: nprocs must be >= 1: $nprocs" >&2
        return 1
    fi

    # Detect total CPU cores
    local total_cores
    total_cores=$(_parallel_get_cpu_count)
    job_state[TOTAL_CORES]="$total_cores"

    # Validate BIN_DIR is set (should be set by caller)
    if [[ -z "${BIN_DIR:-}" ]]; then
        echo "ERROR: BIN_DIR not set (required for locating CRYSTAL23 executables)" >&2
        return 1
    fi

    # Determine execution mode
    if [[ "$nprocs" -le 1 ]]; then
        # Serial/OpenMP mode - single process, all cores as threads
        job_state[MODE]="Serial/OpenMP"
        job_state[EXE_PATH]="${BIN_DIR}/crystalOMP"
        job_state[MPI_RANKS]=""  # No MPI ranks
        job_state[THREADS_PER_RANK]="$total_cores"

        # OpenMP configuration for serial mode
        export OMP_NUM_THREADS="$total_cores"
        unset I_MPI_PIN_DOMAIN 2>/dev/null || true

    else
        # Hybrid MPI/OpenMP mode
        job_state[MODE]="Hybrid MPI/OpenMP"
        job_state[EXE_PATH]="${BIN_DIR}/PcrystalOMP"
        job_state[MPI_RANKS]="$nprocs"

        # Calculate threads per rank
        local threads_per_rank=$((total_cores / nprocs))
        if [[ "$threads_per_rank" -lt 1 ]]; then
            threads_per_rank=1
        fi
        job_state[THREADS_PER_RANK]="$threads_per_rank"

        # OpenMP configuration for hybrid mode
        export OMP_NUM_THREADS="$threads_per_rank"

        # Intel MPI configuration for hybrid mode
        # I_MPI_PIN_DOMAIN=omp: Pin MPI ranks to leave space for OpenMP threads
        export I_MPI_PIN_DOMAIN=omp

        # Intel OpenMP (KMP) thread affinity
        # compact: Pack threads close together for cache locality
        # 1,0: Start at offset 1, stride 0 (sequential)
        # granularity=fine: Use individual cores, not packages
        export KMP_AFFINITY=compact,1,0,granularity=fine
    fi

    # CRYSTAL23-specific OpenMP stack size
    export OMP_STACKSIZE="$DEFAULT_OMP_STACKSIZE"

    # Validate executable exists
    if ! parallel_validate_executables "${job_state[EXE_PATH]}"; then
        # For parallel mode, attempt fallback to serial
        if [[ "${job_state[MODE]}" == "Hybrid MPI/OpenMP" ]]; then
            local serial_exe="${BIN_DIR}/crystalOMP"
            if [[ -x "$serial_exe" ]]; then
                echo "WARNING: PcrystalOMP not found, falling back to serial mode" >&2
                job_state[MODE]="Serial/OpenMP"
                job_state[EXE_PATH]="$serial_exe"
                job_state[MPI_RANKS]=""
                job_state[THREADS_PER_RANK]="$total_cores"
                export OMP_NUM_THREADS="$total_cores"
                unset I_MPI_PIN_DOMAIN 2>/dev/null || true
                unset KMP_AFFINITY 2>/dev/null || true
            else
                echo "ERROR: No CRYSTAL23 executables found (PcrystalOMP or crystalOMP)" >&2
                return 1
            fi
        else
            # Serial mode but crystalOMP not found
            echo "ERROR: crystalOMP not found at ${job_state[EXE_PATH]}" >&2
            return 1
        fi
    fi

    return 0
}

parallel_validate_executables() {
    # Validate CRYSTAL23 executables exist
    # Args: $1 - exe_path: Path to executable
    # Returns: 0 if valid, 1 if not found
    local exe_path="$1"

    if [[ ! -f "$exe_path" ]]; then
        echo "ERROR: CRYSTAL23 executable not found: $exe_path" >&2
        return 1
    fi

    if [[ ! -x "$exe_path" ]]; then
        echo "ERROR: CRYSTAL23 executable not executable: $exe_path" >&2
        return 1
    fi

    return 0
}

parallel_print_config() {
    # Print parallel execution configuration for debugging
    # Args: $1 - job_state_ref: Name reference to associative array
    # Returns: 0 on success
    local -n job_state=$1

    echo "Parallel Configuration:"
    echo "  Mode: ${job_state[MODE]}"
    echo "  Executable: ${job_state[EXE_PATH]}"
    echo "  Total Cores: ${job_state[TOTAL_CORES]}"

    if [[ -n "${job_state[MPI_RANKS]:-}" ]]; then
        echo "  MPI Ranks: ${job_state[MPI_RANKS]}"
        echo "  Threads per Rank: ${job_state[THREADS_PER_RANK]}"
    else
        echo "  OpenMP Threads: ${job_state[THREADS_PER_RANK]}"
    fi

    echo "Environment Variables:"
    echo "  OMP_NUM_THREADS=$OMP_NUM_THREADS"
    echo "  OMP_STACKSIZE=$OMP_STACKSIZE"
    if [[ -n "${I_MPI_PIN_DOMAIN:-}" ]]; then
        echo "  I_MPI_PIN_DOMAIN=$I_MPI_PIN_DOMAIN"
        echo "  KMP_AFFINITY=$KMP_AFFINITY"
    fi

    return 0
}

# Private functions

_parallel_get_cpu_count() {
    # Get number of CPU cores (Linux and macOS compatible)
    # Returns: CPU count to stdout
    if command -v nproc &>/dev/null; then
        # Linux (preferred, respects cgroup limits)
        nproc
    elif [[ -f /proc/cpuinfo ]]; then
        # Linux fallback
        grep -c ^processor /proc/cpuinfo
    elif command -v sysctl &>/dev/null; then
        # macOS
        sysctl -n hw.ncpu
    else
        # Conservative fallback
        echo 4
    fi
}

