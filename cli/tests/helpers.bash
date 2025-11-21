#!/usr/bin/env bash
# tests/helpers.bash - Common test utilities for CRY_CLI test suite

# Test environment setup
# Called at the start of each test to initialize clean test environment
setup_test_env() {
    # Create temporary directory for test files
    TEST_TEMP_DIR="$(mktemp -d)"
    export TEST_TEMP_DIR
    export TEST_ORIGINAL_DIR="$PWD"

    # Determine the path to the tests directory
    # BATS_TEST_DIRNAME is the directory of the test file (e.g., tests/unit)
    # We need to go up one level to find tests/mocks
    local tests_root_dir
    if [[ "${BATS_TEST_DIRNAME}" =~ .*/tests/[^/]+$ ]]; then
        # We're in tests/unit or tests/integration
        tests_root_dir="$(dirname "${BATS_TEST_DIRNAME}")"
    else
        # We're directly in tests/
        tests_root_dir="${BATS_TEST_DIRNAME}"
    fi

    # Set up mock command paths
    export PATH="${tests_root_dir}/mocks:${PATH}"

    # Export mock command overrides
    export CRY_CMD_MPIRUN="${tests_root_dir}/mocks/mpirun"
    export CRY_CMD_GUM="${tests_root_dir}/mocks/gum"
    export CRY_CMD_CRYSTALOMP="${tests_root_dir}/mocks/crystalOMP"

    # Disable colors in output for consistent test results
    export NO_COLOR=1
    export CRY_NO_COLOR=1

    # Set test mode flag
    export CRY_TEST_MODE=1

    # Create test data directory if needed
    mkdir -p "${TEST_TEMP_DIR}/data"
    mkdir -p "${TEST_TEMP_DIR}/output"
}

# Test environment teardown
# Called at the end of each test to clean up
teardown_test_env() {
    # Clean up temporary directory
    if [[ -n "${TEST_TEMP_DIR}" && -d "${TEST_TEMP_DIR}" ]]; then
        rm -rf "${TEST_TEMP_DIR}"
    fi

    # Return to original directory
    if [[ -n "${TEST_ORIGINAL_DIR}" ]]; then
        cd "${TEST_ORIGINAL_DIR}" || true
    fi

    # Unset test environment variables
    unset TEST_TEMP_DIR
    unset TEST_ORIGINAL_DIR
    unset CRY_TEST_MODE
}

# Create a mock command dynamically
# Usage: mock_command "command_name" "output" [exit_code]
mock_command() {
    local cmd_name="$1"
    local output="$2"
    local exit_code="${3:-0}"
    local mock_path="${TEST_TEMP_DIR}/mocks/${cmd_name}"

    mkdir -p "${TEST_TEMP_DIR}/mocks"

    cat > "${mock_path}" <<EOF
#!/usr/bin/env bash
# Mock: ${cmd_name}
echo "${output}"
exit ${exit_code}
EOF

    chmod +x "${mock_path}"
    export PATH="${TEST_TEMP_DIR}/mocks:${PATH}"
}

# Assert that output contains a specific string
# Usage: assert_output_contains "expected string"
assert_output_contains() {
    local expected="$1"
    if [[ "${output}" != *"${expected}"* ]]; then
        echo "Expected output to contain: ${expected}"
        echo "Actual output: ${output}"
        return 1
    fi
}

# Assert that output does not contain a specific string
# Usage: assert_output_not_contains "unexpected string"
assert_output_not_contains() {
    local unexpected="$1"
    if [[ "${output}" == *"${unexpected}"* ]]; then
        echo "Expected output to NOT contain: ${unexpected}"
        echo "Actual output: ${output}"
        return 1
    fi
}

# Assert that a file exists
# Usage: assert_file_exists "path/to/file"
assert_file_exists() {
    local file_path="$1"
    if [[ ! -f "${file_path}" ]]; then
        echo "Expected file to exist: ${file_path}"
        return 1
    fi
}

# Assert that a file does not exist
# Usage: assert_file_not_exists "path/to/file"
assert_file_not_exists() {
    local file_path="$1"
    if [[ -f "${file_path}" ]]; then
        echo "Expected file to NOT exist: ${file_path}"
        return 1
    fi
}

# Assert that a directory exists
# Usage: assert_dir_exists "path/to/dir"
assert_dir_exists() {
    local dir_path="$1"
    if [[ ! -d "${dir_path}" ]]; then
        echo "Expected directory to exist: ${dir_path}"
        return 1
    fi
}

# Assert exit status equals expected value
# Usage: assert_status_equals 0
assert_status_equals() {
    local expected="$1"
    if [[ "${status}" -ne "${expected}" ]]; then
        echo "Expected exit status: ${expected}"
        echo "Actual exit status: ${status}"
        return 1
    fi
}

# Assert exit status is success (0)
# Usage: assert_success
assert_success() {
    assert_status_equals 0
}

# Assert exit status is failure (non-zero)
# Usage: assert_failure
assert_failure() {
    if [[ "${status}" -eq 0 ]]; then
        echo "Expected non-zero exit status"
        echo "Actual exit status: ${status}"
        return 1
    fi
}

# Create a test input file with specific content
# Usage: create_test_input "filename" "content"
create_test_input() {
    local filename="$1"
    local content="$2"
    local filepath="${TEST_TEMP_DIR}/data/${filename}"

    echo "${content}" > "${filepath}"
    echo "${filepath}"
}

# Run a command and capture its output with mock environment
# Usage: run_with_mocks command arg1 arg2
run_with_mocks() {
    run "$@"
}

# Mock log output for debugging
# Usage: mock_log "message"
mock_log() {
    if [[ "${CRY_TEST_DEBUG:-0}" == "1" ]]; then
        echo "[TEST DEBUG] $*" >&2
    fi
}

# Assert that output matches a regex pattern
# Usage: assert_output_matches "pattern"
assert_output_matches() {
    local pattern="$1"
    if [[ ! "${output}" =~ ${pattern} ]]; then
        echo "Expected output to match pattern: ${pattern}"
        echo "Actual output: ${output}"
        return 1
    fi
}

# Assert that a command was called (check mock log)
# Usage: assert_command_called "command_name"
assert_command_called() {
    local cmd_name="$1"
    local log_file="${TEST_TEMP_DIR}/${cmd_name}.called"

    if [[ ! -f "${log_file}" ]]; then
        echo "Expected command to be called: ${cmd_name}"
        return 1
    fi
}

# Load project-specific test fixtures
# Usage: load_fixture "fixture_name"
load_fixture() {
    local fixture_name="$1"
    local fixture_path="${BATS_TEST_DIRNAME}/fixtures/${fixture_name}"

    if [[ ! -f "${fixture_path}" ]]; then
        echo "Fixture not found: ${fixture_path}" >&2
        return 1
    fi

    source "${fixture_path}"
}

# Helper to skip tests on specific platforms
# Usage: skip_if_not_linux
skip_if_not_linux() {
    if [[ "$(uname -s)" != "Linux" ]]; then
        skip "Test only runs on Linux"
    fi
}

# Helper to skip tests on macOS
# Usage: skip_if_macos
skip_if_macos() {
    if [[ "$(uname -s)" == "Darwin" ]]; then
        skip "Test does not run on macOS"
    fi
}

# Advanced mocking system for unit tests
# Based on gemini's recommendations for bash unit testing

# Store mock call data in associative arrays
# Note: Using declare -A instead of declare -gA for bash 3.2 compatibility
declare -A MOCK_CALLS
declare -A MOCK_STDOUT
declare -A MOCK_EXIT_CODE

# Resets all mock data. Call this in your setup() functions.
mock_reset() {
    MOCK_CALLS=()
    MOCK_STDOUT=()
    MOCK_EXIT_CODE=()
}

# Creates a mock for a command.
# Usage: mock_create <command> [stdout] [exit_code]
mock_create() {
    local cmd="$1"
    local stdout_val="${2:-}"
    local exit_code="${3:-0}"

    MOCK_STDOUT[$cmd]="$stdout_val"
    MOCK_EXIT_CODE[$cmd]="$exit_code"

    # Override the function in the current shell
    # Use a safer eval that handles unbound variables
    eval "
    ${cmd}() {
        local args=\"\${*}\"
        MOCK_CALLS[\"${cmd}\"]=\" \${args}\"
        echo -n \"\${MOCK_STDOUT[${cmd}]:-}\"
        return \${MOCK_EXIT_CODE[${cmd}]:-0}
    }
    "
}

# Helper to assert a mock was called with specific arguments
# Usage: assert_mock_called_with <command> "arg1" "arg2" ...
assert_mock_called_with() {
    local cmd="$1"
    shift
    local expected_args="$*"

    if [[ "${MOCK_CALLS[$cmd]:-}" != "$expected_args" ]]; then
        echo "Expected $cmd to be called with: $expected_args"
        echo "Actually called with: ${MOCK_CALLS[$cmd]:-<not called>}"
        return 1
    fi
}

# Assert that a mock was called (regardless of arguments)
# Usage: assert_mock_called <command>
assert_mock_called() {
    local cmd="$1"

    if [[ -z "${MOCK_CALLS[$cmd]:-}" ]]; then
        echo "Expected $cmd to be called, but it was not"
        return 1
    fi
}

# Assert that a mock was NOT called
# Usage: assert_mock_not_called <command>
assert_mock_not_called() {
    local cmd="$1"

    if [[ -n "${MOCK_CALLS[$cmd]:-}" ]]; then
        echo "Expected $cmd to NOT be called, but it was called with: ${MOCK_CALLS[$cmd]}"
        return 1
    fi
}

# Export all functions for use in tests
export -f setup_test_env
export -f teardown_test_env
export -f mock_command
export -f mock_reset
export -f mock_create
export -f assert_output_contains
export -f assert_output_not_contains
export -f assert_file_exists
export -f assert_file_not_exists
export -f assert_dir_exists
export -f assert_status_equals
export -f assert_success
export -f assert_failure
export -f create_test_input
export -f run_with_mocks
export -f mock_log
export -f assert_output_matches
export -f assert_command_called
export -f assert_mock_called_with
export -f assert_mock_called
export -f assert_mock_not_called
export -f load_fixture
export -f skip_if_not_linux
export -f skip_if_macos
