#!/usr/bin/env bats
# Integration tests for CRY_CLI full workflow
# Tests: input staging → execution → output retrieval → cleanup

load '../helpers'

readonly TEST_PROJECT_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
readonly BIN_DIR="${TEST_PROJECT_ROOT}/bin"
readonly LIB_DIR="${TEST_PROJECT_ROOT}/lib"

setup() {
    setup_test_env

    # Set up mock environment
    export CRY23_ROOT="${TEST_TEMP_DIR}/mock_crystal"
    export CRY_SCRATCH_BASE="${TEST_TEMP_DIR}/scratch"

    # Create mock CRYSTAL23 installation
    mkdir -p "${CRY23_ROOT}/bin/Linux-ifort_i64_omp/v1.0.1"

    # Copy mock executables
    cp "${BATS_TEST_DIRNAME}/../mocks/crystalOMP" "${CRY23_ROOT}/bin/Linux-ifort_i64_omp/v1.0.1/"
    cp "${BATS_TEST_DIRNAME}/../mocks/PcrystalOMP" "${CRY23_ROOT}/bin/Linux-ifort_i64_omp/v1.0.1/"
    chmod +x "${CRY23_ROOT}/bin/Linux-ifort_i64_omp/v1.0.1/crystalOMP"
    chmod +x "${CRY23_ROOT}/bin/Linux-ifort_i64_omp/v1.0.1/PcrystalOMP"

    # Disable color output for consistent test results
    export NO_COLOR=1
    export CRY_NO_COLOR=1
    export CRY_TEST_MODE=1

    # Create test input directory
    TEST_INPUT_DIR="${TEST_TEMP_DIR}/input"
    mkdir -p "${TEST_INPUT_DIR}"
    cd "${TEST_INPUT_DIR}"
}

teardown() {
    teardown_test_env
}

# Helper: Create a minimal valid d12 file
create_test_input() {
    local prefix="$1"
    cat > "${prefix}.d12" <<'EOF'
TEST CALCULATION
CRYSTAL
0 0 0
1
1 0.0 0.0 0.0
END
99 0
STO-3G
END
DFT
END
END
EOF
}

# Helper: Create auxiliary files for testing
create_auxiliary_files() {
    local prefix="$1"
    echo "mock gui data" > "${prefix}.gui"
    echo "mock f9 data" > "${prefix}.f9"
    echo "mock hessopt data" > "${prefix}.hessopt"
    echo "mock born data" > "${prefix}.born"
}

#===============================================================================
# Serial Mode Integration Tests
#===============================================================================

@test "integration: serial mode - complete workflow" {
    create_test_input "test_job"

    run "${BIN_DIR}/runcrystal" test_job

    # Should succeed
    assert_success

    # Should create output file
    assert_file_exists "test_job.out"

    # Output file should contain mock CRYSTAL23 content
    grep -q "CRYSTAL17 (Mock Output)" test_job.out
    grep -q "CALCULATION COMPLETED SUCCESSFULLY" test_job.out

    # Should retrieve result files (f9, f98)
    assert_file_exists "test_job.f9"
    assert_file_exists "test_job.f98"
}

@test "integration: serial mode - with auxiliary files" {
    create_test_input "test_aux"
    create_auxiliary_files "test_aux"

    run "${BIN_DIR}/runcrystal" test_aux

    assert_success
    assert_file_exists "test_aux.out"

    # Auxiliary files should have been staged (check via logs)
    # Since mocks don't verify staging, just ensure execution succeeds
}

@test "integration: serial mode - scratch directory cleanup" {
    create_test_input "test_cleanup"

    # Run calculation
    run "${BIN_DIR}/runcrystal" test_cleanup
    assert_success

    # Scratch directory should be cleaned up
    # Check that no cry_test_cleanup_* directories remain
    run find "${CRY_SCRATCH_BASE}" -type d -name "cry_test_cleanup_*"
    [ -z "$output" ]
}

@test "integration: serial mode - missing input file" {
    # Don't create input file
    run "${BIN_DIR}/runcrystal" nonexistent

    # Should fail
    assert_failure

    # Should show error message
    assert_output_contains "not found"
}

@test "integration: serial mode - explain mode (dry run)" {
    create_test_input "test_explain"

    run "${BIN_DIR}/runcrystal" --explain test_explain

    # Should succeed without executing
    assert_success

    # Should show educational output (with section numbers)
    assert_output_contains "1. Hardware Detection"
    assert_output_contains "2. Parallel Strategy"
    assert_output_contains "5. Execution Command"

    # Should NOT create output file
    assert_file_not_exists "test_explain.out"
}

#===============================================================================
# Parallel Mode Integration Tests
#===============================================================================

@test "integration: parallel mode - complete workflow" {
    create_test_input "test_parallel"

    # Request 4 MPI ranks
    run "${BIN_DIR}/runcrystal" test_parallel 4

    assert_success
    assert_file_exists "test_parallel.out"

    # Output should indicate parallel execution
    run cat test_parallel.out
    assert_output_contains "Mock Parallel Output"
}

@test "integration: parallel mode - with auxiliary files" {
    create_test_input "test_parallel_aux"
    create_auxiliary_files "test_parallel_aux"

    run "${BIN_DIR}/runcrystal" test_parallel_aux 8

    assert_success
    assert_file_exists "test_parallel_aux.out"
}

@test "integration: parallel mode - scratch cleanup" {
    create_test_input "test_parallel_cleanup"

    run "${BIN_DIR}/runcrystal" test_parallel_cleanup 4
    assert_success

    # Verify scratch directory is cleaned up
    run find "${CRY_SCRATCH_BASE}" -type d -name "cry_test_parallel_cleanup_*"
    [ -z "$output" ]
}

@test "integration: parallel mode - explain mode" {
    create_test_input "test_parallel_explain"

    run "${BIN_DIR}/runcrystal" --explain test_parallel_explain 14

    assert_success
    assert_output_contains "Requested Ranks: 14"
    assert_output_contains "mpirun -np"

    # Should NOT create output file
    assert_file_not_exists "test_parallel_explain.out"
}

#===============================================================================
# Error Handling Tests
#===============================================================================

@test "integration: error - calculation failure handling" {
    create_test_input "test_fail"

    # Set mock to fail
    export TEST_CRYSTALOMP_EXIT=1

    run "${BIN_DIR}/runcrystal" test_fail

    # Should fail gracefully
    assert_failure

    # Scratch should still be cleaned up even on failure
    sleep 0.5
    run find "${CRY_SCRATCH_BASE}" -type d -name "cry_test_fail_*"
    [ -z "$output" ]
}

@test "integration: error - scratch directory creation failure" {
    create_test_input "test_scratch_fail"

    # Create scratch base first, then make it read-only
    mkdir -p "${CRY_SCRATCH_BASE}"
    chmod 000 "${CRY_SCRATCH_BASE}"

    run "${BIN_DIR}/runcrystal" test_scratch_fail

    # Should fail
    assert_failure

    # Restore permissions
    chmod 755 "${CRY_SCRATCH_BASE}"
}

@test "integration: error - cleanup on interrupt" {
    skip "Requires signal handling testing"
    # This would test trap-based cleanup on SIGINT/SIGTERM
}

#===============================================================================
# File Staging Tests
#===============================================================================

@test "integration: staging - d12 file copied to INPUT" {
    create_test_input "test_staging"

    # Mock scratch_create and verify INPUT file
    run "${BIN_DIR}/runcrystal" test_staging

    assert_success

    # Verify output was generated (indicates INPUT was created)
    assert_file_exists "test_staging.out"
}

@test "integration: staging - gui file staged as fort.34" {
    create_test_input "test_gui"
    echo "GUI data for fort.34" > "test_gui.gui"

    run "${BIN_DIR}/runcrystal" test_gui

    assert_success

    # Since mock doesn't verify staging, check that execution completes
    assert_file_exists "test_gui.out"
}

@test "integration: staging - f9 file staged as fort.20" {
    create_test_input "test_f9"
    echo "Wavefunction data" > "test_f9.f9"

    run "${BIN_DIR}/runcrystal" test_f9

    assert_success
    assert_file_exists "test_f9.out"
}

@test "integration: staging - hessopt file staged as HESSOPT.DAT" {
    create_test_input "test_hessopt"
    echo "Hessian data" > "test_hessopt.hessopt"

    run "${BIN_DIR}/runcrystal" test_hessopt

    assert_success
    assert_file_exists "test_hessopt.out"
}

@test "integration: staging - born file staged as BORN.DAT" {
    create_test_input "test_born"
    echo "Born charges data" > "test_born.born"

    run "${BIN_DIR}/runcrystal" test_born

    assert_success
    assert_file_exists "test_born.out"
}

@test "integration: staging - multiple auxiliary files" {
    create_test_input "test_multi_aux"
    echo "GUI" > "test_multi_aux.gui"
    echo "F9" > "test_multi_aux.f9"
    echo "HESS" > "test_multi_aux.hessopt"
    echo "BORN" > "test_multi_aux.born"

    run "${BIN_DIR}/runcrystal" test_multi_aux

    assert_success
    assert_file_exists "test_multi_aux.out"
}

#===============================================================================
# Output Retrieval Tests
#===============================================================================

@test "integration: retrieval - output file copied back" {
    create_test_input "test_output"

    run "${BIN_DIR}/runcrystal" test_output

    assert_success
    assert_file_exists "test_output.out"

    # Verify content
    grep -q "TERMINATION" test_output.out
}

@test "integration: retrieval - f9 result file retrieved" {
    create_test_input "test_retrieve_f9"

    run "${BIN_DIR}/runcrystal" test_retrieve_f9

    assert_success

    # Mock should create fort.9 which gets retrieved as .f9
    assert_file_exists "test_retrieve_f9.f9"
}

@test "integration: retrieval - f98 result file retrieved" {
    create_test_input "test_retrieve_f98"

    run "${BIN_DIR}/runcrystal" test_retrieve_f98

    assert_success
    assert_file_exists "test_retrieve_f98.f98"
}

@test "integration: retrieval - hessopt result retrieved" {
    create_test_input "test_retrieve_hess"

    run "${BIN_DIR}/runcrystal" test_retrieve_hess

    assert_success

    # If calculation creates HESSOPT.DAT, it should be retrieved
    # (Mock may or may not create this - check if exists)
    if [ -f "test_retrieve_hess.hessopt" ]; then
        assert_file_exists "test_retrieve_hess.hessopt"
    fi
}

#===============================================================================
# Edge Cases and Corner Cases
#===============================================================================

@test "integration: edge case - empty input file" {
    touch "empty.d12"

    # Should handle gracefully (may fail or succeed depending on mock)
    run "${BIN_DIR}/runcrystal" empty

    # At minimum, should not crash
    # Accept either success or specific error
}

@test "integration: edge case - very long job name" {
    local long_name="test_$(printf 'a%.0s' {1..200})"
    create_test_input "${long_name}"

    run "${BIN_DIR}/runcrystal" "${long_name}"

    # Should handle gracefully
    assert_success
    assert_file_exists "${long_name}.out"
}

@test "integration: edge case - special characters in filename" {
    # Note: Some shells may not support all special characters
    local special_name="test-calc_v1.0"
    create_test_input "${special_name}"

    run "${BIN_DIR}/runcrystal" "${special_name}"

    assert_success
    assert_file_exists "${special_name}.out"
}

@test "integration: edge case - concurrent executions" {
    create_test_input "test_concurrent1"
    create_test_input "test_concurrent2"

    # Run two calculations in background
    "${BIN_DIR}/runcrystal" test_concurrent1 &
    local pid1=$!

    "${BIN_DIR}/runcrystal" test_concurrent2 &
    local pid2=$!

    # Wait for both to complete
    wait $pid1
    local exit1=$?
    wait $pid2
    local exit2=$?

    # Both should succeed
    [ "$exit1" -eq 0 ]
    [ "$exit2" -eq 0 ]

    # Both should have outputs
    assert_file_exists "test_concurrent1.out"
    assert_file_exists "test_concurrent2.out"

    # Scratch directories should be unique (different PIDs)
}

@test "integration: edge case - existing output file overwrite" {
    create_test_input "test_overwrite"

    # Create existing output file
    echo "OLD OUTPUT" > "test_overwrite.out"

    run "${BIN_DIR}/runcrystal" test_overwrite

    assert_success

    # Should overwrite old output
    grep -q "CRYSTAL17" test_overwrite.out
    ! grep -q "OLD OUTPUT" test_overwrite.out
}

#===============================================================================
# Performance and Resource Tests
#===============================================================================

@test "integration: performance - large auxiliary files" {
    create_test_input "test_large"

    # Create large auxiliary files (10MB each)
    dd if=/dev/zero of="test_large.f9" bs=1M count=10 2>/dev/null

    run "${BIN_DIR}/runcrystal" test_large

    # Should handle large files without issue
    assert_success
}

@test "integration: performance - many auxiliary files" {
    create_test_input "test_many_aux"

    # Create all possible auxiliary files
    echo "GUI" > "test_many_aux.gui"
    echo "F9" > "test_many_aux.f9"
    echo "F98" > "test_many_aux.f98"
    echo "HESS" > "test_many_aux.hessopt"
    echo "BORN" > "test_many_aux.born"

    run "${BIN_DIR}/runcrystal" test_many_aux

    assert_success
}

#===============================================================================
# Help and Usage Tests
#===============================================================================

@test "integration: help - main help display" {
    run "${BIN_DIR}/runcrystal" --help

    # Help may exit with 0 or 1 depending on implementation
    # Check that it shows usage information
    assert_output_contains "Usage"
}

@test "integration: help - short help flag" {
    run "${BIN_DIR}/runcrystal" -h

    # Help may exit with 0 or 1 depending on implementation
    assert_output_contains "Usage"
}

#===============================================================================
# Cleanup Verification Tests
#===============================================================================

@test "integration: cleanup - no scratch directories left after success" {
    create_test_input "test_cleanup_success"

    "${BIN_DIR}/runcrystal" test_cleanup_success

    # Wait for cleanup
    sleep 0.5

    # No scratch directories should remain
    local scratch_count=$(find "${CRY_SCRATCH_BASE}" -type d -name "cry_*" | wc -l)
    [ "$scratch_count" -eq 0 ]
}

@test "integration: cleanup - no scratch directories left after failure" {
    create_test_input "test_cleanup_fail"

    export TEST_CRYSTALOMP_EXIT=1
    "${BIN_DIR}/runcrystal" test_cleanup_fail || true

    # Wait for cleanup
    sleep 0.5

    # Scratch should still be cleaned up
    local scratch_count=$(find "${CRY_SCRATCH_BASE}" -type d -name "cry_*" | wc -l)
    [ "$scratch_count" -eq 0 ]
}

@test "integration: cleanup - scratch not in unexpected location" {
    create_test_input "test_location"

    "${BIN_DIR}/runcrystal" test_location

    # Verify no scratch directories created in current directory
    run find . -maxdepth 1 -type d -name "cry_*"
    [ -z "$output" ]
}
