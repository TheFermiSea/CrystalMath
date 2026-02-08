#!/bin/bash
# Test script for cry-exec.sh module
# Tests the exec_crystal_run function with mock data

set -euo pipefail

# Colors for test output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0

# Mock directories
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$(dirname "$TEST_DIR")/lib"

# Source required modules
source "$LIB_DIR/cry-ui.sh"
source "$LIB_DIR/cry-exec.sh"

# Helper functions
assert_equals() {
    local expected="$1"
    local actual="$2"
    local message="${3:-}"

    if [[ "$expected" == "$actual" ]]; then
        echo -e "${GREEN}✓${NC} PASS: $message"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "${RED}✗${NC} FAIL: $message"
        echo "  Expected: $expected"
        echo "  Actual:   $actual"
        ((TESTS_FAILED++))
        return 1
    fi
}

assert_exit_code() {
    local expected_code="$1"
    local actual_code="$2"
    local message="${3:-}"

    if [[ "$expected_code" -eq "$actual_code" ]]; then
        echo -e "${GREEN}✓${NC} PASS: $message (exit code: $actual_code)"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "${RED}✗${NC} FAIL: $message"
        echo "  Expected exit code: $expected_code"
        echo "  Actual exit code:   $actual_code"
        ((TESTS_FAILED++))
        return 1
    fi
}

# Test 1: Missing required keys
test_missing_keys() {
    echo -e "\n${YELLOW}Test 1: Missing required keys${NC}"

    declare -A job_state=(
        [MODE]="Serial/OpenMP"
        # Missing EXE_PATH and file_prefix
    )

    exec_crystal_run job_state 2>/dev/null
    local exit_code=$?

    assert_exit_code 1 $exit_code "Should fail with missing keys"
}

# Test 2: Serial mode command building
test_serial_mode() {
    echo -e "\n${YELLOW}Test 2: Serial mode command building${NC}"

    # Create mock executable
    local mock_exe="$TEST_DIR/mock_crystal"
    cat > "$mock_exe" << 'EOF'
#!/bin/bash
echo "Mock CRYSTAL23 serial execution"
exit 0
EOF
    chmod +x "$mock_exe"

    # Create mock INPUT file
    echo "MOCK INPUT" > INPUT

    declare -A job_state=(
        [MODE]="Serial/OpenMP"
        [EXE_PATH]="$mock_exe"
        [file_prefix]="test_serial"
    )

    exec_crystal_run job_state >/dev/null 2>&1
    local exit_code=$?

    # Clean up
    rm -f "$mock_exe" INPUT test_serial.out

    assert_exit_code 0 $exit_code "Serial mode should execute successfully"
}

# Test 3: Parallel mode with MPI_RANKS
test_parallel_mode() {
    echo -e "\n${YELLOW}Test 3: Parallel mode command building${NC}"

    # Create mock mpirun
    local mock_mpirun="$TEST_DIR/mock_mpirun"
    cat > "$mock_mpirun" << 'EOF'
#!/bin/bash
echo "Mock MPI execution with $2 ranks"
shift 2 # Skip -np and rank count
exec "$@"
EOF
    chmod +x "$mock_mpirun"

    # Create mock executable
    local mock_exe="$TEST_DIR/mock_Pcrystal"
    cat > "$mock_exe" << 'EOF'
#!/bin/bash
echo "Mock CRYSTAL23 parallel execution"
exit 0
EOF
    chmod +x "$mock_exe"

    # Create mock INPUT file
    echo "MOCK INPUT" > INPUT

    # Temporarily add mock_mpirun to PATH
    export PATH="$TEST_DIR:$PATH"

    declare -A job_state=(
        [MODE]="Parallel/MPI"
        [EXE_PATH]="$mock_exe"
        [MPI_RANKS]="4"
        [file_prefix]="test_parallel"
    )

    exec_crystal_run job_state >/dev/null 2>&1
    local exit_code=$?

    # Clean up
    rm -f "$mock_mpirun" "$mock_exe" INPUT test_parallel.out

    assert_exit_code 0 $exit_code "Parallel mode should execute successfully"
}

# Test 4: Parallel mode missing MPI_RANKS
test_parallel_missing_ranks() {
    echo -e "\n${YELLOW}Test 4: Parallel mode missing MPI_RANKS${NC}"

    declare -A job_state=(
        [MODE]="Parallel/MPI"
        [EXE_PATH]="/fake/path/PcrystalOMP"
        [file_prefix]="test_parallel"
        # Missing MPI_RANKS
    )

    exec_crystal_run job_state 2>/dev/null
    local exit_code=$?

    assert_exit_code 1 $exit_code "Should fail without MPI_RANKS in parallel mode"
}

# Test 5: Failed calculation returns non-zero exit code
test_failed_calculation() {
    echo -e "\n${YELLOW}Test 5: Failed calculation exit code${NC}"

    # Create mock executable that fails
    local mock_exe="$TEST_DIR/mock_crystal_fail"
    cat > "$mock_exe" << 'EOF'
#!/bin/bash
echo "Mock CRYSTAL23 execution with error"
exit 42
EOF
    chmod +x "$mock_exe"

    # Create mock INPUT file
    echo "MOCK INPUT" > INPUT

    declare -A job_state=(
        [MODE]="Serial/OpenMP"
        [EXE_PATH]="$mock_exe"
        [file_prefix]="test_fail"
    )

    exec_crystal_run job_state >/dev/null 2>&1
    local exit_code=$?

    # Clean up
    rm -f "$mock_exe" INPUT test_fail.out

    assert_exit_code 42 $exit_code "Should return executable's exit code (42)"
}

# Run all tests
echo "========================================"
echo "  cry-exec.sh Test Suite"
echo "========================================"

test_missing_keys
test_serial_mode
test_parallel_mode
test_parallel_missing_ranks
test_failed_calculation

# Summary
echo ""
echo "========================================"
echo "  Test Summary"
echo "========================================"
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"
echo "========================================"

if [[ $TESTS_FAILED -eq 0 ]]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
fi
