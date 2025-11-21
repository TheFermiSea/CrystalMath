#!/usr/bin/env bats
# Example test suite demonstrating bats-core and mock framework usage

# Load test helpers
load '../helpers'

# Setup before each test
setup() {
    setup_test_env
}

# Teardown after each test
teardown() {
    teardown_test_env
}

# Test 1: Basic assertion
@test "example: basic test with assertions" {
    # Arrange
    local test_value="hello world"

    # Act
    run echo "${test_value}"

    # Assert
    assert_success
    assert_output_contains "hello"
    assert_output_contains "world"
    [ "${status}" -eq 0 ]
    [ "${output}" = "hello world" ]
}

# Test 2: Using mock commands
@test "example: mock mpirun command" {
    # Arrange - mpirun is already mocked via setup_test_env

    # Act
    run "${CRY_CMD_MPIRUN}" -np 4 echo "test program"

    # Assert
    assert_success
    assert_output_contains "Mock MPI execution"
    assert_output_contains "Processes: 4"
    assert_command_called "mpirun"
}

# Test 3: Using mock gum input
@test "example: mock gum choose" {
    # Arrange
    export TEST_GUM_CHOICE="option2"

    # Act
    run "${CRY_CMD_GUM}" choose "option1" "option2" "option3"

    # Assert
    assert_success
    [ "${output}" = "option2" ]
    assert_command_called "gum"
}

# Test 4: Using mock gum confirm
@test "example: mock gum confirm (yes)" {
    # Arrange
    export TEST_GUM_CONFIRM="yes"

    # Act
    run "${CRY_CMD_GUM}" confirm "Continue?"

    # Assert
    assert_success
}

@test "example: mock gum confirm (no)" {
    # Arrange
    export TEST_GUM_CONFIRM="no"

    # Act
    run "${CRY_CMD_GUM}" confirm "Continue?"

    # Assert
    assert_failure
}

# Test 5: Using mock crystalOMP
@test "example: mock crystalOMP execution" {
    # Arrange
    local input_file="${TEST_TEMP_DIR}/test.d12"
    echo "CRYSTAL TEST INPUT" > "${input_file}"

    # Act
    run "${CRY_CMD_CRYSTALOMP}" -i "${input_file}" -o "${TEST_TEMP_DIR}/test.out"

    # Assert
    assert_success
    assert_output_contains "Mock crystalOMP execution completed"
    assert_file_exists "${TEST_TEMP_DIR}/test.out"

    # Verify output file content
    run cat "${TEST_TEMP_DIR}/test.out"
    assert_output_contains "CRYSTAL17 (Mock Output)"
    assert_output_contains "TOTAL ENERGY"
}

# Test 6: File assertions
@test "example: file existence assertions" {
    # Arrange & Act
    touch "${TEST_TEMP_DIR}/exists.txt"

    # Assert
    assert_file_exists "${TEST_TEMP_DIR}/exists.txt"
    assert_file_not_exists "${TEST_TEMP_DIR}/does_not_exist.txt"
}

# Test 7: Directory assertions
@test "example: directory assertions" {
    # Arrange & Act
    mkdir -p "${TEST_TEMP_DIR}/testdir"

    # Assert
    assert_dir_exists "${TEST_TEMP_DIR}/testdir"
    assert_dir_exists "${TEST_TEMP_DIR}"
}

# Test 8: Dynamic mock creation
@test "example: dynamic mock command" {
    # Arrange
    mock_command "fake_cmd" "fake output" 0

    # Act
    run fake_cmd arg1 arg2

    # Assert
    assert_success
    [ "${output}" = "fake output" ]
}

# Test 9: Output pattern matching
@test "example: regex pattern matching" {
    # Arrange & Act
    run echo "Test output with number 42"

    # Assert
    assert_success
    assert_output_matches "number [0-9]+"
    assert_output_matches "^Test.*42$"
}

# Test 10: Test helper utilities
@test "example: create test input file" {
    # Arrange & Act
    local filepath=$(create_test_input "test.txt" "test content")

    # Assert
    assert_file_exists "${filepath}"
    run cat "${filepath}"
    [ "${output}" = "test content" ]
}

# Test 11: Testing with environment variables
@test "example: environment variable usage" {
    # Arrange
    export TEST_VAR="test_value"

    # Act
    run bash -c 'echo ${TEST_VAR}'

    # Assert
    assert_success
    [ "${output}" = "test_value" ]
}

# Test 12: Multiple assertions in one test
@test "example: comprehensive test with multiple checks" {
    # Arrange
    local test_script="${TEST_TEMP_DIR}/test_script.sh"
    cat > "${test_script}" <<'EOF'
#!/usr/bin/env bash
echo "Starting test"
echo "Processing data"
echo "Test complete"
exit 0
EOF
    chmod +x "${test_script}"

    # Act
    run "${test_script}"

    # Assert - all must pass
    assert_success
    assert_output_contains "Starting test"
    assert_output_contains "Processing data"
    assert_output_contains "Test complete"
    assert_output_not_contains "Error"
    assert_output_not_contains "Failed"
}

# Test 13: Skip test conditionally (example)
@test "example: skip test on macOS" {
    skip_if_macos

    # This test only runs on Linux
    run uname -s
    [ "${output}" = "Linux" ]
}

# Test 14: Testing mock gum spinner
@test "example: mock gum spin command" {
    # Arrange
    export TEST_TEMP_DIR="${TEST_TEMP_DIR}"

    # Act
    run "${CRY_CMD_GUM}" spin --title "Testing" echo "command output"

    # Assert
    assert_success
    assert_output_contains "command output"
}

# Test 15: Testing error conditions
@test "example: handle command failure" {
    # Arrange
    export TEST_CRYSTALOMP_EXIT=1

    # Act
    run "${CRY_CMD_CRYSTALOMP}" -i "nonexistent.d12"

    # Assert
    assert_failure
    [ "${status}" -eq 1 ]
}
