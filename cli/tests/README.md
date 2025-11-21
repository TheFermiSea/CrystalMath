# CRY_CLI Testing Framework

This directory contains the test suite for CRY_CLI using bats-core (Bash Automated Testing System).

## Table of Contents

- [Installation](#installation)
- [Running Tests](#running-tests)
- [Writing Tests](#writing-tests)
- [Mock System](#mock-system)
- [Test Helpers](#test-helpers)
- [Directory Structure](#directory-structure)
- [Best Practices](#best-practices)

## Installation

### Install bats-core

**macOS (Homebrew):**
```bash
brew install bats-core
```

**Linux (from source):**
```bash
git clone https://github.com/bats-core/bats-core.git
cd bats-core
./install.sh /usr/local
```

**Verify installation:**
```bash
bats --version
```

## Running Tests

### Run all tests
```bash
bats tests/
```

### Run specific test file
```bash
bats tests/unit/example.bats
```

### Run with tap output (for CI)
```bash
bats --tap tests/
```

### Run with timing information
```bash
bats --timing tests/
```

### Run specific test by line number
```bash
bats tests/unit/example.bats:15
```

### Parallel execution (faster)
```bash
bats --jobs 4 tests/
```

## Writing Tests

### Basic Test Structure

```bash
#!/usr/bin/env bats

# Load test helpers
load '../helpers'

# Setup runs before each test
setup() {
    setup_test_env
}

# Teardown runs after each test
teardown() {
    teardown_test_env
}

# Individual test
@test "description of what this tests" {
    # Arrange - set up test conditions
    local test_value="hello"

    # Act - execute the code under test
    run echo "${test_value}"

    # Assert - verify the results
    assert_success
    [ "${output}" = "hello" ]
}
```

### Test File Naming

- Unit tests: `tests/unit/test_*.bats` or `tests/unit/*_test.bats`
- Integration tests: `tests/integration/test_*.bats`
- Test descriptions should be clear and descriptive

### Using Assertions

```bash
# Built-in bats assertions
[ "${status}" -eq 0 ]           # Check exit status
[ "${output}" = "expected" ]     # Check exact output
[[ "${output}" =~ pattern ]]     # Check output matches regex

# Custom helper assertions
assert_success                   # Exit status is 0
assert_failure                   # Exit status is non-zero
assert_status_equals 1           # Exit status equals specific value
assert_output_contains "text"    # Output contains substring
assert_output_not_contains "text" # Output doesn't contain substring
assert_output_matches "pattern"  # Output matches regex pattern
assert_file_exists "path"        # File exists
assert_file_not_exists "path"    # File doesn't exist
assert_dir_exists "path"         # Directory exists
assert_command_called "cmd"      # Mock command was called
```

## Mock System

The mock system allows testing without requiring actual external dependencies.

### Available Mock Commands

1. **mpirun** - Mock MPI runner
2. **gum** - Mock Charmbracelet gum UI
3. **crystalOMP** - Mock CRYSTAL17 OMP binary

### Using Mocks in Production Code

Production scripts should use environment variable overrides:

```bash
# In your script (e.g., cry-cli.sh)
"${CRY_CMD_MPIRUN:-mpirun}" -np 4 crystalOMP < input.d12

# Instead of hardcoding:
# mpirun -np 4 crystalOMP < input.d12
```

This allows tests to inject mocks via environment variables.

### Mock Environment Variables

**mpirun mock:**
- No special variables needed
- Logs calls to `${TEST_TEMP_DIR}/mpirun.called`

**gum mock:**
- `TEST_GUM_CHOICE` - Return value for `gum choose`
- `TEST_GUM_INPUT` - Return value for `gum input`
- `TEST_GUM_CONFIRM` - "yes" or "no" for `gum confirm`
- `TEST_GUM_FILTER` - Return value for `gum filter`
- `TEST_GUM_WRITE` - Return value for `gum write`

**crystalOMP mock:**
- `TEST_CRYSTALOMP_EXIT` - Exit code (default: 0)
- Generates mock output file with CRYSTAL17-like format

### Example: Testing with Mocks

```bash
@test "run CRYSTAL calculation with mocked commands" {
    # Arrange
    export TEST_GUM_CHOICE="parallel"
    local input_file="${TEST_TEMP_DIR}/test.d12"
    echo "CRYSTAL INPUT" > "${input_file}"

    # Act
    run bash -c '
        source src/cry-cli.sh
        run_calculation "${input_file}"
    '

    # Assert
    assert_success
    assert_command_called "mpirun"
    assert_command_called "crystalOMP"
}
```

### Creating Dynamic Mocks

```bash
@test "create custom mock on the fly" {
    # Create a mock command that returns specific output
    mock_command "my_tool" "custom output" 0

    # Use the mock
    run my_tool arg1 arg2

    assert_success
    [ "${output}" = "custom output" ]
}
```

## Test Helpers

The `tests/helpers.bash` file provides utility functions for testing.

### Environment Management

- `setup_test_env()` - Initialize test environment (called in `setup()`)
- `teardown_test_env()` - Clean up test environment (called in `teardown()`)

### Mock Management

- `mock_command "name" "output" [exit_code]` - Create dynamic mock

### Assertions

See [Using Assertions](#using-assertions) section above.

### File Operations

- `create_test_input "filename" "content"` - Create test input file
- Returns path to created file in `${TEST_TEMP_DIR}/data/`

### Debugging

- `mock_log "message"` - Log debug output (only if `CRY_TEST_DEBUG=1`)

```bash
# Run tests with debug output
CRY_TEST_DEBUG=1 bats tests/unit/example.bats
```

### Platform-Specific Tests

- `skip_if_not_linux` - Skip test if not on Linux
- `skip_if_macos` - Skip test if on macOS

```bash
@test "Linux-only feature" {
    skip_if_not_linux
    # Test code that only runs on Linux
}
```

## Directory Structure

```
tests/
├── README.md           # This file
├── helpers.bash        # Common test utilities
├── mocks/              # Mock command implementations
│   ├── mpirun         # Mock MPI runner
│   ├── gum            # Mock gum UI
│   └── crystalOMP     # Mock CRYSTAL17
├── unit/               # Unit tests (individual functions)
│   └── example.bats   # Example test suite
├── integration/        # Integration tests (multiple components)
└── fixtures/           # Test data and fixtures
```

## Best Practices

### 1. Test Isolation

Each test should be independent and not rely on other tests:

```bash
# Good - self-contained test
@test "process file" {
    local file="${TEST_TEMP_DIR}/test.txt"
    echo "data" > "${file}"
    run process_file "${file}"
    assert_success
}

# Bad - depends on previous test
@test "create file" {
    echo "data" > test.txt
}
@test "process file" {
    run process_file test.txt  # Assumes previous test ran
}
```

### 2. Clear Test Names

Use descriptive test names that explain what is being tested:

```bash
# Good
@test "calculate_energy returns correct value for H2O molecule"

# Bad
@test "test1"
```

### 3. Arrange-Act-Assert Pattern

Structure tests clearly:

```bash
@test "clear test structure" {
    # Arrange - set up test conditions
    local input="test_data"

    # Act - execute code under test
    run my_function "${input}"

    # Assert - verify results
    assert_success
    assert_output_contains "expected"
}
```

### 4. Use Helpers

Leverage helper functions to reduce duplication:

```bash
# Good - using helper
@test "file exists after creation" {
    local file=$(create_test_input "test.txt" "content")
    assert_file_exists "${file}"
}

# Bad - manual setup
@test "file exists after creation" {
    local file="${TEST_TEMP_DIR}/data/test.txt"
    mkdir -p "${TEST_TEMP_DIR}/data"
    echo "content" > "${file}"
    [[ -f "${file}" ]]
}
```

### 5. Test Both Success and Failure

Test happy paths and error conditions:

```bash
@test "succeeds with valid input" {
    run my_function "valid"
    assert_success
}

@test "fails with invalid input" {
    run my_function "invalid"
    assert_failure
    assert_output_contains "Error"
}
```

### 6. Use Mock Commands Appropriately

Mock external dependencies, but don't over-mock:

```bash
# Good - mock external dependency
@test "uses mpirun correctly" {
    run "${CRY_CMD_MPIRUN}" -np 4 echo test
    assert_success
}

# Bad - mocking bash builtins (unnecessary)
@test "echo works" {
    mock_command "echo" "mocked"
    run echo test
    # This doesn't test anything useful
}
```

### 7. Keep Tests Fast

Unit tests should run in milliseconds, integration tests in seconds:

```bash
# Good - fast test
@test "parse arguments" {
    run parse_args --flag value
    assert_success
}

# Bad - slow test (in unit tests)
@test "wait for completion" {
    run sleep 30  # Don't do this in unit tests
}
```

### 8. Clean Up Resources

Always use teardown to clean up:

```bash
setup() {
    setup_test_env
    # Additional setup
}

teardown() {
    # Additional cleanup
    teardown_test_env  # Always call this last
}
```

## Continuous Integration

### GitHub Actions Example

```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Install bats
        run: |
          git clone https://github.com/bats-core/bats-core.git
          cd bats-core
          sudo ./install.sh /usr/local
      - name: Run tests
        run: bats --tap tests/
```

## Debugging Failed Tests

### Run single test with verbose output
```bash
bats -x tests/unit/example.bats:15
```

### Enable debug logging
```bash
CRY_TEST_DEBUG=1 bats tests/unit/example.bats
```

### Check mock logs
```bash
# After a test run (if TEST_TEMP_DIR is known)
cat /tmp/tmp.XXXXXX/mpirun.called
cat /tmp/tmp.XXXXXX/gum.called
```

## Resources

- [bats-core documentation](https://bats-core.readthedocs.io/)
- [bats-core GitHub](https://github.com/bats-core/bats-core)
- [Bash test operators](https://www.gnu.org/software/bash/manual/html_node/Bash-Conditional-Expressions.html)

## Contributing

When adding new tests:

1. Follow the existing structure and naming conventions
2. Add tests to appropriate directory (unit vs integration)
3. Use helpers and mocks where applicable
4. Document any new helper functions
5. Ensure tests are fast and isolated
6. Run full test suite before committing: `bats tests/`
