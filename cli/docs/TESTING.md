# CRY_CLI Testing Guide

## Overview

CRY_CLI uses [Bats (Bash Automated Testing System)](https://github.com/bats-core/bats-core) for unit and integration testing.

## Requirements

- **Bats:** Install via `brew install bats` (macOS) or package manager
- **Bash 5.0+:** Required for associative arrays. Install via `brew install bash` (macOS)
- **Test Framework:** Bats-core 1.0+

## Running Tests

### All Tests

```bash
# Run all tests with modern bash
BASH=/opt/homebrew/bin/bash bats tests/

# Or configure bash in your environment
export BASH=/opt/homebrew/bin/bash
bats tests/
```

### Individual Module Tests

```bash
# Test cry-parallel module
BASH=/opt/homebrew/bin/bash bats tests/test_cry-parallel.bats

# Test cry-ui module (when implemented)
BASH=/opt/homebrew/bin/bash bats tests/test_cry-ui.bats
```

### Verbose Output

```bash
# Show detailed test output
BASH=/opt/homebrew/bin/bash bats -t tests/test_cry-parallel.bats
```

## Test Structure

### File Naming Convention

- `test_<module-name>.bats` - Unit tests for a specific module
- `integration_<feature>.bats` - Integration tests spanning multiple modules

### Test Organization

```bash
#!/usr/bin/env bats
# Test suite for <module-name>

# Setup runs before each test
setup() {
    export LIB_DIR="${BATS_TEST_DIRNAME}/../lib"
    source "${LIB_DIR}/<module-name>.sh"

    # Mock dependencies
    export BIN_DIR="/mock/path"
}

# Teardown runs after each test
teardown() {
    unset VARIABLE_NAME
}

# Individual test
@test "Description of what this tests" {
    # Arrange
    local input="test_value"

    # Act
    function_name "$input"

    # Assert
    [ "$?" -eq 0 ]
    [ "$output" = "expected" ]
}
```

## Current Test Coverage

### cry-parallel Module (16 tests)

- ✅ Serial mode configuration (nprocs=1)
- ✅ Hybrid mode configuration (nprocs=4)
- ✅ Input validation (negative, zero, non-numeric nprocs)
- ✅ BIN_DIR requirement validation
- ✅ Thread calculation logic (exact division)
- ✅ Thread calculation logic (oversubscription)
- ✅ Executable validation (not found, not executable, valid)
- ✅ Configuration printing (serial, hybrid)
- ✅ CPU count detection
- ✅ Module initialization
- ✅ Integration workflow

**Status:** All 16 tests passing

## Writing New Tests

### Test Best Practices

1. **Isolate Tests:** Each test should be independent
2. **Use Setup/Teardown:** Clean up state between tests
3. **Mock External Dependencies:** Don't rely on actual CRYSTAL23 installation
4. **Test Edge Cases:** Negative inputs, oversubscription, missing dependencies
5. **Use Descriptive Names:** Test names should explain what they validate

### Example Test Pattern

```bash
@test "module_function: handles edge case correctly" {
    # Arrange: Setup test data
    declare -A TEST_STATE=()
    export REQUIRED_VAR="value"

    # Act: Call the function
    module_function "input" TEST_STATE

    # Assert: Verify results
    [ "${TEST_STATE[KEY]}" = "expected_value" ]
    [ "$REQUIRED_VAR" = "expected_value" ]
}
```

### Mocking Functions

```bash
@test "Uses mocked function" {
    # Override internal function
    _internal_function() {
        echo "mocked_output"
    }
    export -f _internal_function

    # Call code that uses mocked function
    result=$(public_function)

    [ "$result" = "mocked_output" ]
}
```

## Continuous Integration

### GitHub Actions (Future)

```yaml
name: Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Install dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y bats bash
      - name: Run tests
        run: bats tests/
```

### Pre-commit Hook (Recommended)

```bash
#!/bin/bash
# .git/hooks/pre-commit

echo "Running tests..."
if ! BASH=/opt/homebrew/bin/bash bats tests/; then
    echo "Tests failed. Commit aborted."
    exit 1
fi
```

## Debugging Failed Tests

### View Test Output

```bash
# Use -t for tap output
BASH=/opt/homebrew/bin/bash bats -t tests/test_cry-parallel.bats

# Run specific test by line number
BASH=/opt/homebrew/bin/bash bats tests/test_cry-parallel.bats:25
```

### Enable Bash Debugging

```bash
# Add to test file
set -x  # Enable tracing

@test "Debug this test" {
    # Trace will show each command executed
    function_name "input"
}
```

### Check Variable State

```bash
@test "Debug variables" {
    function_name "input"

    # Print variables for debugging
    echo "DEBUG: VAR1=$VAR1" >&3
    echo "DEBUG: VAR2=$VAR2" >&3

    [ "$VAR1" = "expected" ]
}
```

## Test Coverage Goals

- **Unit Tests:** Each public function should have 3-5 tests
  - Happy path (valid input)
  - Edge cases (boundary conditions)
  - Error cases (invalid input)
  - Integration with dependencies

- **Integration Tests:** Each workflow should have 1-2 tests
  - End-to-end workflow
  - Error recovery

- **Coverage Target:** 80%+ code coverage for all modules

## Troubleshooting

### Problem: "declare: -A: invalid option"

**Cause:** Using bash 3.2 (default on macOS)
**Solution:** Install bash 5 and set BASH environment variable:
```bash
brew install bash
BASH=/opt/homebrew/bin/bash bats tests/
```

### Problem: Tests fail with "unbound variable"

**Cause:** `set -euo pipefail` in module causes exit on undefined variables
**Solution:** Initialize variables in setup or use `${VAR:-default}` syntax

### Problem: Executable validation tests fail

**Cause:** Test uses actual file paths instead of mocks
**Solution:** Use `mktemp` to create temporary files for testing

## Resources

- [Bats Documentation](https://bats-core.readthedocs.io/)
- [Bash Test Patterns](https://github.com/sstephenson/bats/wiki/Bash-testing-patterns)
- [Bash Associative Arrays](https://www.gnu.org/software/bash/manual/html_node/Arrays.html)

---

**Last Updated:** 2025-11-19
**Test Framework:** Bats-core 1.x
**Minimum Bash Version:** 5.0
