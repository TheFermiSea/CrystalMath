#!/bin/bash

exec_crystal_run() {
    local -n job_ref=$1

    # Validate
    if [[ -z "${job_ref[MODE]:-}" ]] || [[ -z "${job_ref[EXE_PATH]:-}" ]] || \
       [[ -z "${job_ref[file_prefix]:-}" ]]; then
        echo "ERROR: Missing required keys" >&2
        return 1
    fi

    # Build command
    local cmd
    if [[ "${job_ref[MODE]}" == "Serial/OpenMP" ]]; then
        cmd="${job_ref[EXE_PATH]} < INPUT > ${job_ref[file_prefix]}.out"
    else
        if [[ -z "${job_ref[MPI_RANKS]:-}" ]]; then
            echo "ERROR: MPI_RANKS required" >&2
            return 1
        fi

        local mpi_bin
        if [[ -n "${I_MPI_ROOT:-}" ]]; then
            mpi_bin="${I_MPI_ROOT}/bin/mpirun"
        else
            mpi_bin="mpirun"
        fi

        cmd="$mpi_bin -np ${job_ref[MPI_RANKS]} ${job_ref[EXE_PATH]} < INPUT > ${job_ref[file_prefix]}.out"
    fi

    echo "Command: $cmd"
    eval "$cmd"
    return $?
}

# Test serial mode
declare -A job_state=(
    [MODE]="Serial/OpenMP"
    [EXE_PATH]="./crystal_mock"
    [file_prefix]="serial_test"
)

exec_crystal_run job_state
exit_code=$?

if [[ $exit_code -eq 0 ]] && [[ -f serial_test.out ]]; then
    echo "SUCCESS: Serial mode executed"
    exit 0
else
    echo "FAILED: Serial mode execution"
    exit 1
fi
