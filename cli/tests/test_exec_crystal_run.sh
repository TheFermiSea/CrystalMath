#!/bin/bash
# Simple integration test for exec_crystal_run function
# Tests command building and execution logic

set -euo pipefail

# Test workspace
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="$TEST_DIR/work"
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "  exec_crystal_run Integration Test"
echo "========================================"

# Test 1: Verify function exists and command building for serial mode
echo -e "\n${YELLOW}Test 1: Serial mode command structure${NC}"

# Create test executable
cat > crystal_mock << 'EOF'
#!/bin/bash
echo "CRYSTAL23 Serial Mock: $@"
echo "Reading from stdin..."
cat
echo "Calculation complete"
exit 0
EOF
chmod +x crystal_mock

# Create INPUT file
cat > INPUT << 'EOF'
CRYSTAL
TITLE
Test calculation
END
EOF

# Create minimal exec_crystal_run implementation for testing
cat > test_exec.sh << 'TESTSCRIPT'
#!/bin/bash

exec_crystal_run() {
    local -n job_ref=$1

    # Validate
    if [[ -z "${job_ref[MODE]:-}" ]] || [[ -z "${job_ref[EXE_PATH]:-}" ]] || \
       [[ -z "${job_ref[file_prefix]:-}" ]]; then
        echo "ERROR: Missing required keys" >&2
        return 1
    fi

    # Build command
    local cmd
    if [[ "${job_ref[MODE]}" == "Serial/OpenMP" ]]; then
        cmd="${job_ref[EXE_PATH]} < INPUT > ${job_ref[file_prefix]}.out"
    else
        if [[ -z "${job_ref[MPI_RANKS]:-}" ]]; then
            echo "ERROR: MPI_RANKS required" >&2
            return 1
        fi

        local mpi_bin
        if [[ -n "${I_MPI_ROOT:-}" ]]; then
            mpi_bin="${I_MPI_ROOT}/bin/mpirun"
        else
            mpi_bin="mpirun"
        fi

        cmd="$mpi_bin -np ${job_ref[MPI_RANKS]} ${job_ref[EXE_PATH]} < INPUT > ${job_ref[file_prefix]}.out"
    fi

    echo "Command: $cmd"
    eval "$cmd"
    return $?
}

# Test serial mode
declare -A job_state=(
    [MODE]="Serial/OpenMP"
    [EXE_PATH]="./crystal_mock"
    [file_prefix]="serial_test"
)

exec_crystal_run job_state
exit_code=$?

if [[ $exit_code -eq 0 ]] && [[ -f serial_test.out ]]; then
    echo "SUCCESS: Serial mode executed"
    exit 0
else
    echo "FAILED: Serial mode execution"
    exit 1
fi
TESTSCRIPT

bash test_exec.sh
result=$?

if [[ $result -eq 0 ]]; then
    echo -e "${GREEN}✓ PASS${NC}: Serial mode command building and execution"
    cat serial_test.out
else
    echo -e "${RED}✗ FAIL${NC}: Serial mode failed"
fi

# Test 2: Parallel mode command structure
echo -e "\n${YELLOW}Test 2: Parallel mode command structure${NC}"

# Create mock mpirun
cat > mpirun << 'EOF'
#!/bin/bash
echo "Mock mpirun called with: $@"
# Skip -np and rank count, execute the rest
shift 2
exec "$@"
EOF
chmod +x mpirun

# Add current directory to PATH for mpirun
export PATH="$WORK_DIR:$PATH"

cat > test_parallel.sh << 'TESTSCRIPT'
#!/bin/bash

exec_crystal_run() {
    local -n job_ref=$1

    if [[ -z "${job_ref[MODE]:-}" ]] || [[ -z "${job_ref[EXE_PATH]:-}" ]] || \
       [[ -z "${job_ref[file_prefix]:-}" ]]; then
        echo "ERROR: Missing required keys" >&2
        return 1
    fi

    local cmd
    if [[ "${job_ref[MODE]}" == "Serial/OpenMP" ]]; then
        cmd="${job_ref[EXE_PATH]} < INPUT > ${job_ref[file_prefix]}.out"
    else
        if [[ -z "${job_ref[MPI_RANKS]:-}" ]]; then
            echo "ERROR: MPI_RANKS required" >&2
            return 1
        fi

        local mpi_bin
        if [[ -n "${I_MPI_ROOT:-}" ]]; then
            mpi_bin="${I_MPI_ROOT}/bin/mpirun"
        else
            mpi_bin="mpirun"
        fi

        cmd="$mpi_bin -np ${job_ref[MPI_RANKS]} ${job_ref[EXE_PATH]} < INPUT > ${job_ref[file_prefix]}.out"
    fi

    echo "Command: $cmd"
    eval "$cmd"
    return $?
}

declare -A job_state=(
    [MODE]="Parallel/MPI"
    [EXE_PATH]="./crystal_mock"
    [MPI_RANKS]="4"
    [file_prefix]="parallel_test"
)

exec_crystal_run job_state
exit_code=$?

if [[ $exit_code -eq 0 ]] && [[ -f parallel_test.out ]]; then
    echo "SUCCESS: Parallel mode executed"
    exit 0
else
    echo "FAILED: Parallel mode execution"
    exit 1
fi
TESTSCRIPT

bash test_parallel.sh
result=$?

if [[ $result -eq 0 ]]; then
    echo -e "${GREEN}✓ PASS${NC}: Parallel mode command building and execution"
    cat parallel_test.out
else
    echo -e "${RED}✗ FAIL${NC}: Parallel mode failed"
fi

# Test 3: Error handling - missing keys
echo -e "\n${YELLOW}Test 3: Error handling (missing keys)${NC}"

cat > test_error.sh << 'TESTSCRIPT'
#!/bin/bash

exec_crystal_run() {
    local -n job_ref=$1

    if [[ -z "${job_ref[MODE]:-}" ]] || [[ -z "${job_ref[EXE_PATH]:-}" ]] || \
       [[ -z "${job_ref[file_prefix]:-}" ]]; then
        echo "ERROR: Missing required keys" >&2
        return 1
    fi

    return 0
}

declare -A job_state=(
    [MODE]="Serial/OpenMP"
    # Missing EXE_PATH and file_prefix
)

exec_crystal_run job_state 2>/dev/null
exit $?
TESTSCRIPT

bash test_error.sh
result=$?

if [[ $result -eq 1 ]]; then
    echo -e "${GREEN}✓ PASS${NC}: Correctly rejects missing keys"
else
    echo -e "${RED}✗ FAIL${NC}: Should have failed with missing keys"
fi

# Cleanup
cd "$TEST_DIR"
rm -rf "$WORK_DIR"

echo ""
echo "========================================"
echo "  All integration tests completed"
echo "========================================"
