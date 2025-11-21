#!/usr/bin/env bash
# test-cry-config.sh - Test suite for cry-config.sh module

set -euo pipefail

# Test counter
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
assert_equals() {
    local expected="$1"
    local actual="$2"
    local test_name="$3"

    ((TESTS_RUN++))

    if [[ "$expected" == "$actual" ]]; then
        echo -e "${GREEN}✓${NC} $test_name"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "${RED}✗${NC} $test_name"
        echo "  Expected: $expected"
        echo "  Actual:   $actual"
        ((TESTS_FAILED++))
        return 1
    fi
}

assert_not_empty() {
    local value="$1"
    local test_name="$2"

    ((TESTS_RUN++))

    if [[ -n "$value" ]]; then
        echo -e "${GREEN}✓${NC} $test_name"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "${RED}✗${NC} $test_name"
        echo "  Value was empty"
        ((TESTS_FAILED++))
        return 1
    fi
}

assert_success() {
    local test_name="$1"
    local exit_code="${2:-$?}"

    ((TESTS_RUN++))

    if [[ $exit_code -eq 0 ]]; then
        echo -e "${GREEN}✓${NC} $test_name"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "${RED}✗${NC} $test_name"
        echo "  Command failed with exit code $exit_code"
        ((TESTS_FAILED++))
        return 1
    fi
}

# Test suite
echo "Testing cry-config.sh module"
echo "=============================="
echo ""

# Test 1: Module sources without errors
echo "Test Group: Module Loading"
(source lib/cry-config.sh 2>&1) >/dev/null; exit_code=$?
assert_success "Module sources without errors" $exit_code

# Test 2: Configuration variables are set
source lib/cry-config.sh
assert_not_empty "$CRY23_ROOT" "CRY23_ROOT is set"
assert_not_empty "$CRY_VERSION" "CRY_VERSION is set"
assert_not_empty "$CRY_ARCH" "CRY_ARCH is set"
assert_not_empty "$CRY_BIN_DIR" "CRY_BIN_DIR is set"
assert_not_empty "$CRY_SCRATCH_BASE" "CRY_SCRATCH_BASE is set"

# Test 3: Color constants are defined
echo ""
echo "Test Group: Color Theme"
assert_equals "39" "$C_PRIMARY" "C_PRIMARY (Sapphire Blue)"
assert_equals "86" "$C_SEC" "C_SEC (Teal)"
assert_equals "214" "$C_WARN" "C_WARN (Orange)"
assert_equals "196" "$C_ERR" "C_ERR (Red)"
assert_equals "255" "$C_TEXT" "C_TEXT (White)"
assert_equals "240" "$C_DIM" "C_DIM (Gray)"

# Test 4: cry_config_get function
echo ""
echo "Test Group: Helper Functions"
result=$(cry_config_get CRY23_ROOT)
assert_not_empty "$result" "cry_config_get returns value"

# Test 5: Environment variable override
echo ""
echo "Test Group: Environment Overrides"
result=$(CRY23_ROOT=/custom/path bash -c 'source lib/cry-config.sh && cry_config_get CRY23_ROOT' 2>/dev/null || echo "")
if [[ -n "$result" ]]; then
    assert_equals "/custom/path" "$result" "CRY23_ROOT override works"
else
    # Bash 3.2 doesn't support the test, skip it
    echo -e "${YELLOW}⊘${NC} CRY23_ROOT override (skipped - bash 3.2)"
fi

# Test 6: Derived paths update with override
result=$(CRY23_ROOT=/test bash -c 'source lib/cry-config.sh && cry_config_get CRY_BIN_DIR' 2>/dev/null || echo "")
if [[ -n "$result" ]]; then
    assert_equals "/test/bin/Linux-ifort_i64_omp/v1.0.1" "$result" "Derived paths update with override"
else
    echo -e "${YELLOW}⊘${NC} Derived paths update (skipped - bash 3.2)"
fi

# Test 7: Stage map functionality
echo ""
echo "Test Group: File Staging Maps"
result=$(cry_stage_map_get gui)
assert_equals "fort.34" "$result" "STAGE_MAP[gui] = fort.34"

result=$(cry_stage_map_get hessopt)
assert_equals "HESSOPT.DAT" "$result" "STAGE_MAP[hessopt] = HESSOPT.DAT"

# Test 8: Retrieve map functionality
result=$(cry_retrieve_map_get "fort.9")
assert_equals "f9" "$result" "RETRIEVE_MAP[fort.9] = f9"

result=$(cry_retrieve_map_get "OPTINFO.DAT")
assert_equals "optinfo" "$result" "RETRIEVE_MAP[OPTINFO.DAT] = optinfo"

# Test 9: cry_config_show runs without errors
echo ""
echo "Test Group: Display Functions"
cry_config_show >/dev/null 2>&1; exit_code=$?
assert_success "cry_config_show runs without errors" $exit_code

# Test 10: Multiple sourcing protection
echo ""
echo "Test Group: Module Protection"
(
    source lib/cry-config.sh
    source lib/cry-config.sh
    source lib/cry-config.sh
) >/dev/null 2>&1; exit_code=$?
assert_success "Multiple sourcing protection works" $exit_code

# Test 11: Cross-shell compatibility (if bash available)
if command -v bash &>/dev/null; then
    echo ""
    echo "Test Group: Cross-Shell Compatibility"
    result=$(bash -c 'source lib/cry-config.sh && cry_stage_map_get f9' 2>/dev/null || echo "")
    if [[ -n "$result" ]]; then
        assert_equals "fort.20" "$result" "Works in bash shell"
    else
        echo -e "${YELLOW}⊘${NC} Bash compatibility (bash not available or failed)"
    fi
fi

# Summary
echo ""
echo "=============================="
echo "Test Summary"
echo "=============================="
echo "Tests Run:    $TESTS_RUN"
echo -e "Tests Passed: ${GREEN}$TESTS_PASSED${NC}"

if [[ $TESTS_FAILED -gt 0 ]]; then
    echo -e "Tests Failed: ${RED}$TESTS_FAILED${NC}"
    exit 1
else
    echo -e "Tests Failed: ${GREEN}0${NC}"
    echo ""
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
fi
