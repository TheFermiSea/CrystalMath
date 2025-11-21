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
