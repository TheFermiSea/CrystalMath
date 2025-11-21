# CRY_CLI Testing Framework - Quick Start

## Installation Complete

The bats-core testing framework has been successfully installed and configured for CRY_CLI.

## What Was Installed

- **bats-core 1.13.0** - Bash Automated Testing System
- **Test helpers** (`tests/helpers.bash`) - 20+ utility functions
- **Mock framework** - Simulates mpirun, gum, and crystalOMP
- **Example tests** - 16 comprehensive test cases
- **Documentation** - Complete testing guide

## Quick Test Run

```bash
# Run all tests
bats tests/

# Run example tests
bats tests/unit/example.bats

# Run with TAP output (for CI)
bats --tap tests/

# Run in parallel (faster)
bats --jobs 4 tests/
```

## Test Results

All 16 example tests pass successfully:
- Basic assertions
- Mock command usage (mpirun, gum, crystalOMP)
- File and directory operations
- Pattern matching
- Error handling
- Platform-specific tests

## Directory Structure

```
tests/
├── helpers.bash          # Test utility functions
├── README.md            # Complete documentation
├── INSTALLATION.md      # This file
├── mocks/               # Mock commands
│   ├── mpirun          # Mock MPI runner
│   ├── gum             # Mock gum UI
│   └── crystalOMP      # Mock CRYSTAL17
├── unit/                # Unit tests
│   └── example.bats    # Example test suite (16 tests)
└── integration/         # Integration tests (empty)
```

## Mock System

Production code uses environment variable overrides:

```bash
# In production script
"${CRY_CMD_MPIRUN:-mpirun}" -np 4 crystalOMP < input.d12

# In tests
export CRY_CMD_MPIRUN="tests/mocks/mpirun"
```

This allows tests to inject mocks without modifying production code.

## Next Steps

1. Write unit tests for individual functions
2. Write integration tests for complete workflows
3. Add tests to CI/CD pipeline
4. Maintain tests alongside code changes

## Documentation

For complete documentation, see:
- `tests/README.md` - Comprehensive testing guide
- `bats --help` - Command-line help
- https://bats-core.readthedocs.io/ - Official documentation

## Troubleshooting

### Tests fail with "command not found"
- Ensure mocks are executable: `chmod +x tests/mocks/*`
- Check that helpers.bash is loaded: `load '../helpers'`

### Mock commands not working
- Verify `setup_test_env()` is called in `setup()`
- Check environment variables are set correctly
- Use `CRY_TEST_DEBUG=1 bats tests/` for debug output

### Need to test specific functionality
- See `tests/unit/example.bats` for examples
- Use mock environment variables to control behavior
- Reference `tests/helpers.bash` for available utilities

## Support

For issues or questions:
- Check `tests/README.md` for detailed documentation
- Review `tests/unit/example.bats` for usage examples
- Consult bats-core documentation: https://bats-core.readthedocs.io/
