#!/usr/bin/env bats
# Test suite for cry-parallel module

# Setup and teardown
setup() {

    # Load the module
    export LIB_DIR="${BATS_TEST_DIRNAME}/../lib"
    source "${LIB_DIR}/cry-parallel.sh"

    # Mock BIN_DIR for testing
    export BIN_DIR="/mock/crystal23/bin"

    # Create test job state array
    declare -gA TEST_JOB=()
}

teardown() {
    # Cleanup environment
    unset OMP_NUM_THREADS OMP_STACKSIZE I_MPI_PIN_DOMAIN KMP_AFFINITY
    unset TEST_JOB
}

# Test: parallel_setup with nprocs=1 (Serial/OpenMP mode)
@test "parallel_setup: Serial mode with nprocs=1" {
    parallel_setup 1 TEST_JOB

    [ "${TEST_JOB[MODE]}" = "Serial/OpenMP" ]
    [ "${TEST_JOB[EXE_PATH]}" = "/mock/crystal23/bin/crystalOMP" ]
    [ -z "${TEST_JOB[MPI_RANKS]}" ]
    [ "${TEST_JOB[THREADS_PER_RANK]}" -gt 0 ]
    [ "${TEST_JOB[TOTAL_CORES]}" -gt 0 ]

    # Verify environment variables
    [ "$OMP_NUM_THREADS" = "${TEST_JOB[THREADS_PER_RANK]}" ]
    [ "$OMP_STACKSIZE" = "256M" ]
    [ -z "${I_MPI_PIN_DOMAIN:-}" ]
}

# Test: parallel_setup with nprocs=4 (Hybrid MPI/OpenMP mode)
@test "parallel_setup: Hybrid mode with nprocs=4" {
    parallel_setup 4 TEST_JOB

    [ "${TEST_JOB[MODE]}" = "Hybrid MPI/OpenMP" ]
    [ "${TEST_JOB[EXE_PATH]}" = "/mock/crystal23/bin/PcrystalOMP" ]
    [ "${TEST_JOB[MPI_RANKS]}" = "4" ]
    [ "${TEST_JOB[THREADS_PER_RANK]}" -ge 1 ]
    [ "${TEST_JOB[TOTAL_CORES]}" -gt 0 ]

    # Verify environment variables
    [ "$OMP_NUM_THREADS" = "${TEST_JOB[THREADS_PER_RANK]}" ]
    [ "$OMP_STACKSIZE" = "256M" ]
    [ "$I_MPI_PIN_DOMAIN" = "omp" ]
    [ "$KMP_AFFINITY" = "compact,1,0,granularity=fine" ]
}

# Test: parallel_setup validates nprocs input
@test "parallel_setup: Rejects invalid nprocs (negative)" {
    run parallel_setup -1 TEST_JOB
    [ "$status" -eq 1 ]
}

@test "parallel_setup: Rejects invalid nprocs (zero)" {
    run parallel_setup 0 TEST_JOB
    [ "$status" -eq 1 ]
}

@test "parallel_setup: Rejects invalid nprocs (non-numeric)" {
    run parallel_setup "abc" TEST_JOB
    [ "$status" -eq 1 ]
}

# Test: parallel_setup requires BIN_DIR
@test "parallel_setup: Fails when BIN_DIR not set" {
    unset BIN_DIR
    run parallel_setup 1 TEST_JOB
    [ "$status" -eq 1 ]
    [[ "$output" =~ "BIN_DIR not set" ]]
}

# Test: Thread calculation logic
@test "parallel_setup: Calculates threads correctly (8 cores / 4 ranks = 2 threads)" {
    # Mock nproc to return 8
    _parallel_get_cpu_count() { echo 8; }
    export -f _parallel_get_cpu_count

    parallel_setup 4 TEST_JOB
    [ "${TEST_JOB[TOTAL_CORES]}" = "8" ]
    [ "${TEST_JOB[THREADS_PER_RANK]}" = "2" ]
    [ "$OMP_NUM_THREADS" = "2" ]
}

@test "parallel_setup: Ensures minimum 1 thread per rank (oversubscribed)" {
    # Mock nproc to return 4
    _parallel_get_cpu_count() { echo 4; }
    export -f _parallel_get_cpu_count

    # Request 8 MPI ranks on 4 cores (oversubscribed)
    parallel_setup 8 TEST_JOB
    [ "${TEST_JOB[THREADS_PER_RANK]}" = "1" ]
}

# Test: parallel_validate_executables
@test "parallel_validate_executables: Rejects non-existent file" {
    run parallel_validate_executables "/nonexistent/crystal"
    [ "$status" -eq 1 ]
    [[ "$output" =~ "not found" ]]
}

@test "parallel_validate_executables: Rejects non-executable file" {
    local tmpfile=$(mktemp)
    chmod -x "$tmpfile"

    run parallel_validate_executables "$tmpfile"
    [ "$status" -eq 1 ]
    [[ "$output" =~ "not executable" ]]

    rm -f "$tmpfile"
}

@test "parallel_validate_executables: Accepts valid executable" {
    local tmpfile=$(mktemp)
    chmod +x "$tmpfile"

    run parallel_validate_executables "$tmpfile"
    [ "$status" -eq 0 ]

    rm -f "$tmpfile"
}

# Test: parallel_print_config
@test "parallel_print_config: Prints serial mode configuration" {
    parallel_setup 1 TEST_JOB

    run parallel_print_config TEST_JOB
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Serial/OpenMP" ]]
    [[ "$output" =~ "crystalOMP" ]]
    [[ "$output" =~ "OMP_NUM_THREADS" ]]
}

@test "parallel_print_config: Prints hybrid mode configuration" {
    parallel_setup 4 TEST_JOB

    run parallel_print_config TEST_JOB
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Hybrid MPI/OpenMP" ]]
    [[ "$output" =~ "PcrystalOMP" ]]
    [[ "$output" =~ "MPI Ranks: 4" ]]
    [[ "$output" =~ "I_MPI_PIN_DOMAIN" ]]
    [[ "$output" =~ "KMP_AFFINITY" ]]
}

# Test: _parallel_get_cpu_count
@test "_parallel_get_cpu_count: Returns positive integer" {
    run _parallel_get_cpu_count
    [ "$status" -eq 0 ]
    [[ "$output" =~ ^[0-9]+$ ]]
    [ "$output" -gt 0 ]
}

# Test: Module initialization
@test "Module loads without errors" {
    # If we got here, setup() succeeded in sourcing the module
    [ "$MODULE_NAME" = "cry-parallel" ]
    [ "$MODULE_VERSION" = "1.0.0" ]
}

# Integration test: Full workflow
@test "Integration: Complete parallel setup workflow" {
    # Setup for serial mode
    parallel_setup 1 TEST_JOB
    [ "${TEST_JOB[MODE]}" = "Serial/OpenMP" ]

    # Validate configuration
    run parallel_print_config TEST_JOB
    [ "$status" -eq 0 ]

    # Reset for hybrid mode
    declare -gA TEST_JOB=()

    # Setup for hybrid mode
    parallel_setup 2 TEST_JOB
    [ "${TEST_JOB[MODE]}" = "Hybrid MPI/OpenMP" ]

    # Validate configuration
    run parallel_print_config TEST_JOB
    [ "$status" -eq 0 ]
}
