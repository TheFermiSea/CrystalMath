#!/usr/bin/env bash
# test-cry-logging.sh - Test suite for cry-logging.sh

set -uo pipefail

# Source the logging library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/cry-logging.sh"

# Test counter
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Test result tracking
test_pass() {
    ((TESTS_PASSED++))
    ((TESTS_RUN++))
    echo "✓ $1"
}

test_fail() {
    ((TESTS_FAILED++))
    ((TESTS_RUN++))
    echo "✗ $1"
}

# Test 1: cry_log with all log levels
echo "=== Test 1: cry_log with all log levels ==="
CRY_LOG_LEVEL=debug

if cry_log debug "Debug message" 2>&1 | grep -q "DEBUG"; then
    test_pass "debug level logs correctly"
else
    test_fail "debug level failed"
fi

if cry_log info "Info message" 2>&1 | grep -q "INFO"; then
    test_pass "info level logs correctly"
else
    test_fail "info level failed"
fi

if cry_log warn "Warning message" 2>&1 | grep -q "WARN"; then
    test_pass "warn level logs correctly"
else
    test_fail "warn level failed"
fi

if cry_log error "Error message" 2>&1 | grep -q "ERROR"; then
    test_pass "error level logs correctly"
else
    test_fail "error level failed"
fi

# Test 2: Invalid log level
echo -e "\n=== Test 2: Invalid log level handling ==="
output=$(cry_log invalid "Test" 2>&1 || true)
if echo "$output" | grep -q "Invalid log level"; then
    test_pass "Invalid log level rejected"
else
    test_fail "Invalid log level not handled"
fi

# Test 3: cry_fatal returns exit code without calling exit
echo -e "\n=== Test 3: cry_fatal return behavior ==="
cry_fatal "Test fatal error" 42 2>/dev/null
exit_code=$?
if [[ $exit_code -eq 42 ]]; then
    test_pass "cry_fatal returns exit code without calling exit"
else
    test_fail "cry_fatal behavior incorrect (got $exit_code)"
fi

# Test 4: cry_fatal default exit code
echo -e "\n=== Test 4: cry_fatal default exit code ==="
cry_fatal "Test fatal without code" 2>/dev/null
exit_code=$?
if [[ $exit_code -eq 1 ]]; then
    test_pass "cry_fatal defaults to exit code 1"
else
    test_fail "cry_fatal default exit code incorrect (got $exit_code)"
fi

# Test 5: Log level filtering
echo -e "\n=== Test 5: Log level filtering ==="
CRY_LOG_LEVEL=warn

output=$(cry_log debug "Should not appear" 2>&1)
if [[ -z "$output" ]]; then
    test_pass "Debug filtered when CRY_LOG_LEVEL=warn"
else
    test_fail "Debug not filtered"
fi

output=$(cry_log info "Should not appear" 2>&1)
if [[ -z "$output" ]]; then
    test_pass "Info filtered when CRY_LOG_LEVEL=warn"
else
    test_fail "Info not filtered"
fi

output=$(cry_log warn "Should appear" 2>&1)
if [[ -n "$output" ]]; then
    test_pass "Warn not filtered when CRY_LOG_LEVEL=warn"
else
    test_fail "Warn incorrectly filtered"
fi

output=$(cry_log error "Should appear" 2>&1)
if [[ -n "$output" ]]; then
    test_pass "Error not filtered when CRY_LOG_LEVEL=warn"
else
    test_fail "Error incorrectly filtered"
fi

# Test 6: Timestamp format
echo -e "\n=== Test 6: Timestamp format (ISO 8601) ==="
CRY_LOG_LEVEL=debug
output=$(cry_log info "Test timestamp" 2>&1)
if echo "$output" | grep -qE '\[[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\]'; then
    test_pass "Timestamp in ISO 8601 format"
else
    test_fail "Timestamp format incorrect"
fi

# Test 7: Convenience functions
echo -e "\n=== Test 7: Convenience functions ==="
CRY_LOG_LEVEL=debug

if cry_debug "Debug via convenience" 2>&1 | grep -q "DEBUG"; then
    test_pass "cry_debug() convenience function works"
else
    test_fail "cry_debug() failed"
fi

if cry_info "Info via convenience" 2>&1 | grep -q "INFO"; then
    test_pass "cry_info() convenience function works"
else
    test_fail "cry_info() failed"
fi

if cry_warn "Warn via convenience" 2>&1 | grep -q "WARN"; then
    test_pass "cry_warn() convenience function works"
else
    test_fail "cry_warn() failed"
fi

# Test 8: Message with multiple arguments
echo -e "\n=== Test 8: Multi-argument messages ==="
output=$(cry_log info "Message" "with" "multiple" "args" 2>&1)
if echo "$output" | grep -q "Message with multiple args"; then
    test_pass "Multi-argument messages concatenated correctly"
else
    test_fail "Multi-argument message handling failed"
fi

# Test 9: cry_fatal logs error level
echo -e "\n=== Test 9: cry_fatal logs at error level ==="
output=$(cry_fatal "Fatal error message" 99 2>&1)
if echo "$output" | grep -q "\[ERROR\]"; then
    test_pass "cry_fatal logs at ERROR level"
else
    test_fail "cry_fatal error level incorrect"
fi

# Test 10: Default CRY_LOG_LEVEL
echo -e "\n=== Test 10: Default CRY_LOG_LEVEL ==="
unset CRY_LOG_LEVEL
source "${SCRIPT_DIR}/../lib/cry-logging.sh"

output=$(cry_log info "Should appear with default level" 2>&1)
if [[ -n "$output" ]]; then
    test_pass "Default CRY_LOG_LEVEL allows info messages"
else
    test_fail "Default CRY_LOG_LEVEL incorrect"
fi

output=$(cry_log debug "Should not appear with default level" 2>&1)
if [[ -z "$output" ]]; then
    test_pass "Default CRY_LOG_LEVEL filters debug messages"
else
    test_fail "Default CRY_LOG_LEVEL filtering incorrect"
fi

# Summary
echo -e "\n=== Test Summary ==="
echo "Tests run: $TESTS_RUN"
echo "Tests passed: $TESTS_PASSED"
echo "Tests failed: $TESTS_FAILED"

if [[ $TESTS_FAILED -eq 0 ]]; then
    echo -e "\n✓ All tests passed!"
    exit 0
else
    echo -e "\n✗ Some tests failed"
    exit 1
fi
