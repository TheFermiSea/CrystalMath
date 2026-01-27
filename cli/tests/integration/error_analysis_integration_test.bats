#!/usr/bin/env bats
# Integration test for error analysis with full runcrystal workflow

# Load test helpers
load '../helpers'

# Project root directory
readonly PROJECT_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
readonly BIN_DIR="${PROJECT_ROOT}/bin"
readonly RUNCRYSTAL="${BIN_DIR}/runcrystal"

# Setup before each test
setup() {
    setup_test_env

    # Create mock CRYSTAL23 installation
    export CRY23_ROOT="${TEST_TEMP_DIR}/mock_crystal23"
    mkdir -p "${CRY23_ROOT}/bin"

    # Verify runcrystal exists
    if [[ ! -x "$RUNCRYSTAL" ]]; then
        skip "runcrystal not found at $RUNCRYSTAL"
    fi
}

# Teardown after each test
teardown() {
    teardown_test_env
}

# Test 1: Verify analyze_failure can be called from exec module
@test "integration: analyze_failure function loads correctly" {
    # Arrange - Create mock dependencies
    ui_error() { echo "ERROR: $*"; }
    ui_info() { echo "INFO: $*"; }
    cry_log() { echo "LOG [$1]: ${*:2}"; }
    export -f ui_error ui_info cry_log

    # Act - Source the exec module
    source "${PROJECT_ROOT}/lib/cry-exec.sh"

    # Assert - Function should be available
    [ "$(type -t analyze_failure)" = "function" ]
}

# Test 2: Error analysis detects patterns in output file
@test "integration: analyze_failure detects SCF divergence" {
    # Arrange - Create mock dependencies
    ui_error() { echo "ERROR: $*"; }
    ui_info() { echo "INFO: $*"; }
    cry_log() { echo "LOG [$1]: ${*:2}"; }
    export -f ui_error ui_info cry_log

    # Source the exec module
    source "${PROJECT_ROOT}/lib/cry-exec.sh"

    # Create output file with SCF divergence
    local output_file="${TEST_TEMP_DIR}/test.out"
    cat > "$output_file" <<'EOF'
DIVERGENCE DETECTED
EOF

    # Act - Call analyze_failure
    run analyze_failure "$output_file"

    # Assert - Should detect pattern
    assert_success
    assert_output_contains "Detected SCF Divergence"
    assert_output_contains "calculation is unstable"
}

# Test 3: Error analysis handles memory errors
@test "integration: analyze_failure detects memory errors" {
    # Arrange - Create mock dependencies
    ui_error() { echo "ERROR: $*"; }
    ui_info() { echo "INFO: $*"; }
    cry_log() { echo "LOG [$1]: ${*:2}"; }
    export -f ui_error ui_info cry_log

    # Source the exec module
    source "${PROJECT_ROOT}/lib/cry-exec.sh"

    # Create output file with memory error
    local output_file="${TEST_TEMP_DIR}/test.out"
    cat > "$output_file" <<'EOF'
insufficient memory for calculation
EOF

    # Act - Call analyze_failure
    run analyze_failure "$output_file"

    # Assert - Should detect memory error
    assert_success
    assert_output_contains "Memory Error Detected"
    assert_output_contains "increasing the number of MPI ranks"
}

# =============================================================================
# Failure Output Retrieval Tests (Issue crystalmath-e1h)
# =============================================================================

# Test 4: Verify exit code is captured without triggering set -e
@test "integration: non-zero exit code is captured and propagated" {
    # Arrange - Create mock dependencies that fail
    ui_error() { echo "ERROR: $*"; }
    ui_info() { echo "INFO: $*"; }
    ui_success() { echo "SUCCESS: $*"; }
    ui_warning() { echo "WARNING: $*"; }
    cry_log() { :; }
    cry_warn() { echo "WARN: $*"; }
    export -f ui_error ui_info ui_success ui_warning cry_log cry_warn

    # Source modules
    source "${PROJECT_ROOT}/lib/cry-exec.sh"
    source "${PROJECT_ROOT}/lib/cry-stage.sh" 2>/dev/null || true

    # Create a function that returns non-zero
    test_failing_exec() {
        return 42
    }

    # Test capturing exit code without triggering set -e
    local EXIT_CODE=0
    test_failing_exec || EXIT_CODE=$?

    # Assert - Exit code should be captured
    [ "$EXIT_CODE" -eq 42 ]
}

# Test 5: Verify error analysis runs on failure
@test "integration: error analysis runs when calculation fails" {
    # Arrange
    ui_error() { echo "ERROR: $*"; }
    ui_info() { echo "INFO: $*"; }
    cry_log() { echo "LOG [$1]: ${*:2}"; }
    export -f ui_error ui_info cry_log

    source "${PROJECT_ROOT}/lib/cry-exec.sh"

    # Create output file with error pattern
    local output_file="${TEST_TEMP_DIR}/failed_calc.out"
    cat > "$output_file" <<'EOF'
CRYSTAL23 calculation started
Processing integrals...
*** DIVERGENCE DETECTED ***
Calculation terminated
EOF

    # Act - Simulate what happens on failure (analyze_failure is called)
    run analyze_failure "$output_file"

    # Assert - Error analysis should have run
    assert_success
    assert_output_contains "Detected SCF Divergence"
    assert_output_contains "calculation is unstable"
}

# Test 6: Verify the || EXIT_CODE=$? pattern works correctly
@test "integration: || EXIT_CODE pattern captures exit codes" {
    # This tests the specific pattern used in bin/runcrystal

    # Arrange - Function that fails with specific exit code
    failing_command() {
        return 17
    }

    # Act - Use the exact pattern from runcrystal
    local EXIT_CODE=0
    failing_command || EXIT_CODE=$?

    # Assert
    [ "$EXIT_CODE" -eq 17 ]
}

# Test 7: Verify successful command sets exit code to 0
@test "integration: successful command keeps EXIT_CODE at 0" {
    # Arrange - Function that succeeds
    succeeding_command() {
        return 0
    }

    # Act - Use the exact pattern from runcrystal
    local EXIT_CODE=0
    succeeding_command || EXIT_CODE=$?

    # Assert
    [ "$EXIT_CODE" -eq 0 ]
}

# Test 8: Verify exit code propagates through full workflow
@test "integration: exit code propagates correctly through workflow simulation" {
    # Arrange
    local final_exit=0

    # Simulate the workflow pattern
    simulate_workflow() {
        local step1_exit=0
        local step2_exit=0
        local calc_exit=0

        # Step 1: Always succeeds
        true || step1_exit=$?

        # Step 2: Calculation fails
        false || calc_exit=$?

        # Step 3: Result retrieval (always runs, may warn)
        true || step2_exit=$?

        # Return the calculation exit code
        return $calc_exit
    }

    simulate_workflow || final_exit=$?

    # Assert - Should propagate the calculation failure
    [ "$final_exit" -eq 1 ]
}
