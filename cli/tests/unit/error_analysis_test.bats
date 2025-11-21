#!/usr/bin/env bats
# Unit tests for CRYSTAL23 error analysis system

# Load test helpers
load '../helpers'

# Project root directory (two levels up from tests/unit)
readonly PROJECT_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
readonly LIB_DIR="${PROJECT_ROOT}/lib"

# Setup before each test
setup() {
    setup_test_env

    # Mock UI functions (define BEFORE export)
    ui_error() { echo "ERROR: $*"; }
    ui_info() { echo "INFO: $*"; }
    ui_success() { echo "SUCCESS: $*"; }
    cry_log() { echo "LOG [$1]: ${*:2}"; }

    # Export the mock functions
    export -f ui_error
    export -f ui_info
    export -f ui_success
    export -f cry_log

    # Source the cry-exec module (requires dependencies)
    source "${LIB_DIR}/cry-exec.sh"

    # Ensure analyze_failure is available
    if ! declare -f analyze_failure > /dev/null; then
        echo "Error: analyze_failure function not found" >&2
        return 1
    fi
}

# Teardown after each test
teardown() {
    teardown_test_env
}

# Test 1: SCF divergence detection
@test "error_analysis: detects SCF divergence" {
    # Arrange
    local output_file="${TEST_TEMP_DIR}/scf_divergence.out"
    cat > "${output_file}" <<'EOF'
CRYSTAL23 output file
Starting SCF calculation
Iteration 1: E = -100.5 Ha
Iteration 2: E = -101.2 Ha
Iteration 3: E = -102.8 Ha
*** DIVERGENCE DETECTED ***
SCF procedure failed to converge
EOF

    # Act
    run analyze_failure "${output_file}"

    # Assert
    assert_success
    assert_output_contains "Detected SCF Divergence"
    assert_output_contains "calculation is unstable"
    assert_output_contains "Check your geometry"
    assert_output_contains "GUESSP"
    assert_output_contains "FMIXING"
}

# Test 2: SCF NOT CONVERGED alternative pattern
@test "error_analysis: detects SCF NOT CONVERGED pattern" {
    # Arrange
    local output_file="${TEST_TEMP_DIR}/scf_not_converged.out"
    cat > "${output_file}" <<'EOF'
CRYSTAL23 output file
Starting SCF calculation
Iteration 50: E = -100.5 Ha
Iteration 51: E = -100.4 Ha
SCF NOT CONVERGED after 51 iterations
EOF

    # Act
    run analyze_failure "${output_file}"

    # Assert
    assert_success
    assert_output_contains "Detected SCF Divergence"
    assert_output_contains "calculation is unstable"
}

# Test 3: Memory error detection (insufficient memory)
@test "error_analysis: detects insufficient memory error" {
    # Arrange
    local output_file="${TEST_TEMP_DIR}/memory_error.out"
    cat > "${output_file}" <<'EOF'
CRYSTAL23 output file
Allocating memory for integral arrays
Error: insufficient memory for calculation
Required: 128 GB
Available: 64 GB
EOF

    # Act
    run analyze_failure "${output_file}"

    # Assert
    assert_success
    assert_output_contains "Memory Error Detected"
    assert_output_contains "ran out of memory"
    assert_output_contains "increasing the number of MPI ranks"
    assert_output_contains "runcrystal input 14"
}

# Test 4: Memory error detection (SIGSEGV)
@test "error_analysis: detects SIGSEGV error" {
    # Arrange
    local output_file="${TEST_TEMP_DIR}/sigsegv.out"
    cat > "${output_file}" <<'EOF'
CRYSTAL23 output file
Starting calculation
Processing integrals
SIGSEGV: Segmentation violation
Program terminated abnormally
EOF

    # Act
    run analyze_failure "${output_file}"

    # Assert
    assert_success
    assert_output_contains "Memory Error Detected"
    assert_output_contains "ran out of memory"
}

# Test 5: Memory error detection (Segmentation fault)
@test "error_analysis: detects Segmentation fault error" {
    # Arrange
    local output_file="${TEST_TEMP_DIR}/segfault.out"
    cat > "${output_file}" <<'EOF'
CRYSTAL23 output file
Initializing calculation
Segmentation fault
Core dumped
EOF

    # Act
    run analyze_failure "${output_file}"

    # Assert
    assert_success
    assert_output_contains "Memory Error Detected"
}

# Test 6: Basis set error detection
@test "error_analysis: detects basis set error" {
    # Arrange
    local output_file="${TEST_TEMP_DIR}/basis_error.out"
    cat > "${output_file}" <<'EOF'
CRYSTAL23 output file
Reading input file
Processing basis set definition
ERROR: BASIS SET not found for element 42
Please check your basis set library
EOF

    # Act
    run analyze_failure "${output_file}"

    # Assert
    assert_success
    assert_output_contains "Basis Set Error"
    assert_output_contains "Check BS keyword syntax"
    assert_output_contains "Verify atomic numbers"
    assert_output_contains "standard basis set"
}

# Test 7: No error pattern detected (fallback)
@test "error_analysis: handles unknown error pattern" {
    # Arrange
    local output_file="${TEST_TEMP_DIR}/unknown_error.out"
    cat > "${output_file}" <<'EOF'
CRYSTAL23 output file
Starting calculation
Some unknown error occurred
Calculation terminated
EOF

    # Act
    run analyze_failure "${output_file}"

    # Assert
    assert_success
    assert_output_contains "No specific known error pattern detected"
    assert_output_contains "Check the error log below"
}

# Test 8: Missing output file handling
@test "error_analysis: handles missing output file" {
    # Arrange - no file created

    # Act
    run analyze_failure "${TEST_TEMP_DIR}/nonexistent.out"

    # Assert
    assert_success
    assert_output_contains "Output file not found"
}

# Test 9: Works without gum (plain text fallback)
@test "error_analysis: works without gum" {
    # Arrange
    local output_file="${TEST_TEMP_DIR}/scf_divergence_nogum.out"
    cat > "${output_file}" <<'EOF'
DIVERGENCE DETECTED
EOF

    # Remove gum from PATH temporarily
    local original_path="$PATH"
    export PATH="/usr/bin:/bin"

    # Act
    run analyze_failure "${output_file}"

    # Restore PATH
    export PATH="$original_path"

    # Assert
    assert_success
    assert_output_contains "Detected SCF Divergence"
    # Should not contain gum style commands
    assert_output_not_contains "gum style"
}

# Test 10: Multiple error patterns (first match wins)
@test "error_analysis: stops at first matching pattern" {
    # Arrange - file has both SCF divergence and memory error
    local output_file="${TEST_TEMP_DIR}/multiple_errors.out"
    cat > "${output_file}" <<'EOF'
CRYSTAL23 output file
DIVERGENCE DETECTED
insufficient memory
EOF

    # Act
    run analyze_failure "${output_file}"

    # Assert
    assert_success
    # Should report SCF divergence (checked first)
    assert_output_contains "Detected SCF Divergence"
    # Should NOT report memory error (second pattern)
    assert_output_not_contains "Memory Error Detected"
}

# Test 11: Empty output file
@test "error_analysis: handles empty output file" {
    # Arrange
    local output_file="${TEST_TEMP_DIR}/empty.out"
    touch "${output_file}"

    # Act
    run analyze_failure "${output_file}"

    # Assert
    assert_success
    assert_output_contains "No specific known error pattern detected"
}

# Test 12: Logging integration
@test "error_analysis: logs analysis to cry_log" {
    # Arrange
    local output_file="${TEST_TEMP_DIR}/test.out"
    echo "DIVERGENCE" > "${output_file}"

    # Act
    run analyze_failure "${output_file}"

    # Assert
    assert_success
    # Check that cry_log was called (our mock outputs LOG lines)
    assert_output_matches "LOG \[info\]: Analyzing failure"
}

# Test 13: Pattern matching is case-sensitive
@test "error_analysis: SCF divergence pattern is case-sensitive" {
    # Arrange
    local output_file="${TEST_TEMP_DIR}/lowercase.out"
    cat > "${output_file}" <<'EOF'
divergence detected
scf not converged
EOF

    # Act
    run analyze_failure "${output_file}"

    # Assert
    assert_success
    # Should NOT match lowercase patterns
    assert_output_not_contains "Detected SCF Divergence"
    assert_output_contains "No specific known error pattern detected"
}

# Test 14: Robust grep pattern matching
@test "error_analysis: uses grep -q for silent pattern matching" {
    # Arrange
    local output_file="${TEST_TEMP_DIR}/divergence.out"
    cat > "${output_file}" <<'EOF'
Line 1
Line 2
DIVERGENCE
Line 4
EOF

    # Act - should find pattern anywhere in file
    run analyze_failure "${output_file}"

    # Assert
    assert_success
    assert_output_contains "Detected SCF Divergence"
}

# Test 15: Educational tone in error messages
@test "error_analysis: provides educational error messages" {
    # Arrange
    local output_file="${TEST_TEMP_DIR}/scf.out"
    echo "DIVERGENCE" > "${output_file}"

    # Act
    run analyze_failure "${output_file}"

    # Assert
    assert_success
    # Check for educational language
    assert_output_contains "Try:"
    assert_output_matches "[0-9]\."  # Numbered suggestions
    # Helpful hints, not just error reporting
    assert_output_contains "atoms too close"
}
