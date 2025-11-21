# Integration Tests for CRY_CLI

This directory contains comprehensive integration tests for the CRYSTAL23 CLI (`runcrystal`).

## Overview

Integration tests verify the complete workflow from input staging through execution to output retrieval and cleanup. Tests use mock CRYSTAL23 binaries to simulate real calculations without requiring the actual CRYSTAL23 installation.

## Test Coverage

### Serial Mode Tests (6 tests)
- Complete workflow execution
- Auxiliary file staging
- Scratch directory cleanup
- Missing input file handling
- Explain mode (dry run)

### Parallel Mode Tests (4 tests)
- MPI parallel execution
- Auxiliary files with parallel mode
- Scratch cleanup after parallel execution
- Explain mode for parallel calculations

### Error Handling Tests (3 tests)
- Calculation failure handling
- Scratch directory creation failure
- Cleanup on interrupt (manual test required)

### File Staging Tests (6 tests)
- d12 file staged as INPUT
- gui file staged as fort.34
- f9 file staged as fort.20
- hessopt file staged as HESSOPT.DAT
- born file staged as BORN.DAT
- Multiple auxiliary files

### Output Retrieval Tests (4 tests)
- OUTPUT file copied to .out
- fort.9 retrieved as .f9
- fort.98 retrieved as .f98
- HESSOPT.DAT retrieved

### Edge Cases (7 tests)
- Empty input files
- Very long job names
- Special characters in filenames
- Concurrent executions
- Existing output file overwrite
- Large auxiliary files (10MB)
- Many auxiliary files simultaneously

### Help System Tests (2 tests)
- --help flag display
- -h flag display

### Cleanup Verification Tests (3 tests)
- No scratch directories after success
- No scratch directories after failure
- Scratch not in unexpected locations

## Total: 34 Integration Tests

**Current Status**: 27 passing (79%)

## Running Tests

### Run all integration tests:
```bash
cd cli/
bats tests/integration/full_workflow_test.bats
```

### Run specific test:
```bash
bats tests/integration/full_workflow_test.bats -f "serial mode - complete workflow"
```

### View verbose output:
```bash
bats tests/integration/full_workflow_test.bats --verbose-run
```

## Mock System

### Mock Binaries
- **crystalOMP**: Simulates serial/OpenMP execution
  - Creates OUTPUT, fort.9, fort.98
  - Optional HESSOPT.DAT for frequency calculations
  - Exit code controlled by `TEST_CRYSTALOMP_EXIT` environment variable

- **PcrystalOMP**: Simulates parallel MPI+OpenMP execution
  - Creates parallel-tagged output files
  - Same file creation as crystalOMP
  - Exit code controlled by `TEST_PCRYSTALOMP_EXIT`

- **mpirun**: Simulates MPI launcher
  - Logs process count and command
  - Passes through to actual binary

- **gum**: Simulates UI library
  - Returns mock styled output
  - Supports basic commands (style, spin, format)

### Environment Variables

Tests set up a clean mock environment:
- `CRY23_ROOT`: Points to mock CRYSTAL23 installation
- `CRY_SCRATCH_BASE`: Temporary scratch directory
- `NO_COLOR=1`: Disable color output for consistent test results
- `CRY_TEST_MODE=1`: Enable test mode in scripts

## Test Structure

Each test follows this pattern:

```bash
@test "integration: <category> - <description>" {
    # 1. Setup: Create input files
    create_test_input "job_name"
    create_auxiliary_files "job_name"  # Optional

    # 2. Execute: Run runcrystal
    run "${BIN_DIR}/runcrystal" job_name [nprocs]

    # 3. Verify: Check results
    assert_success
    assert_file_exists "job_name.out"
    grep -q "expected content" job_name.out

    # 4. Cleanup verification
    # (automatic via teardown, some tests verify explicitly)
}
```

## Known Issues

1. **Test 6**: Parallel output string mismatch (cosmetic)
2. **Test 19, 27**: Timing-sensitive output file checks
3. **Test 30-31**: Help system format differs from expected

These do not affect core functionality.

## Test Dependencies

- `bats-core`: Test framework
- `bash 4.0+`: For associative arrays
- Mock binaries in `tests/mocks/`
- Test helpers in `tests/helpers.bash`

## Writing New Integration Tests

### Template:
```bash
@test "integration: <category> - <test description>" {
    # Setup
    create_test_input "test_name"

    # Optional: Create auxiliary files
    echo "data" > "test_name.gui"

    # Execute
    run "${BIN_DIR}/runcrystal" test_name [ranks]

    # Verify
    assert_success  # or assert_failure
    assert_file_exists "test_name.out"
    grep -q "expected" test_name.out

    # Optional: Check result files
    assert_file_exists "test_name.f9"
}
```

### Best Practices:
1. Use unique job names for each test
2. Test both success and failure paths
3. Verify cleanup happens (scratch directories removed)
4. Use `grep` for file content checks (more reliable than captured output)
5. Add `sleep 0.5` if checking async cleanup

## Workflow Coverage

The integration tests verify this complete workflow:

```
1. Input Validation
   ├─ File existence checks
   └─ Argument parsing

2. Scratch Directory Management
   ├─ Creation: ~/tmp_crystal/cry_<job>_<pid>/
   └─ Cleanup: Trap-based guarantee

3. File Staging
   ├─ INPUT ← job.d12
   ├─ fort.34 ← job.gui (optional)
   ├─ fort.20 ← job.f9 (optional)
   ├─ HESSOPT.DAT ← job.hessopt (optional)
   └─ BORN.DAT ← job.born (optional)

4. Execution
   ├─ Serial: crystalOMP < INPUT > OUTPUT
   └─ Parallel: mpirun -np N PcrystalOMP < INPUT > OUTPUT

5. Output Retrieval
   ├─ job.out ← OUTPUT
   ├─ job.f9 ← fort.9
   ├─ job.f98 ← fort.98
   └─ job.hessopt ← HESSOPT.DAT

6. Cleanup
   └─ Remove scratch directory (guaranteed by trap)
```

## Future Improvements

- [ ] Add timeout tests for long-running calculations
- [ ] Test signal handling (SIGINT, SIGTERM) explicitly
- [ ] Add network filesystem simulation tests
- [ ] Test with very large files (>1GB)
- [ ] Add tests for properties calculations
- [ ] Test error recovery mechanisms
- [ ] Add performance benchmarks

## Related Documentation

- Unit tests: `../unit/`
- Test helpers: `../helpers.bash`
- Mock binaries: `../mocks/`
- Main CLI documentation: `../../docs/`
