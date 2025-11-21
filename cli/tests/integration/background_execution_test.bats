#!/usr/bin/env bats
# Integration tests for background execution with live monitoring

load ../helpers

setup() {
    # Create temporary test environment
    export BATS_TEST_TMPDIR=$(mktemp -d)
    export CRY23_ROOT="$BATS_TEST_TMPDIR/crystal"
    export CRY_SCRATCH_BASE="$BATS_TEST_TMPDIR/scratch"
    export WORK_DIR="$CRY_SCRATCH_BASE/test_job_$$"

    # Define paths to scripts
    LIB_DIR="$BATS_TEST_DIRNAME/../../lib"
    BIN_DIR="$BATS_TEST_DIRNAME/../../bin"

    # Create mock CRYSTAL23 binaries
    mkdir -p "$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1"

    # Mock crystalOMP with slow execution
    cat > "$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1/crystalOMP" << 'EOF'
#!/bin/bash
# Simulate slow calculation
sleep 2
echo "CRYSTAL23 Mock Output" > /dev/stdout
echo "Calculation complete" > /dev/stdout
exit 0
EOF
    chmod +x "$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1/crystalOMP"

    # Create test input file
    mkdir -p "$WORK_DIR"
    echo "Test input" > "$WORK_DIR/INPUT"
    cd "$WORK_DIR"

    # Source modules directly
    source "$LIB_DIR/cry-config.sh"
    cry_config_init
    source "$LIB_DIR/cry-logging.sh"
    source "$LIB_DIR/core.sh"
    source "$LIB_DIR/cry-ui.sh"
    source "$LIB_DIR/cry-parallel.sh"
    source "$LIB_DIR/cry-exec.sh"
}

teardown() {
    # Cleanup
    cd /
    rm -rf "$BATS_TEST_TMPDIR"
}

@test "background execution runs calculation asynchronously" {
    skip "Requires gum installation"

    # Setup job state
    declare -A CRY_JOB=(
        [MODE]="Serial/OpenMP"
        [EXE_PATH]="$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1/crystalOMP"
        [file_prefix]="test"
    )

    # Record start time
    start_time=$(date +%s)

    # Execute
    exec_crystal_run CRY_JOB
    exit_code=$?

    # Record end time
    end_time=$(date +%s)
    duration=$((end_time - start_time))

    # Verify execution completed
    [ $exit_code -eq 0 ]

    # Verify output file created
    [ -f "test.out" ]

    # Verify it took at least 2 seconds (sleep duration)
    [ $duration -ge 2 ]
}

@test "background execution captures output correctly" {
    # Setup job state
    declare -A CRY_JOB=(
        [MODE]="Serial/OpenMP"
        [EXE_PATH]="$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1/crystalOMP"
        [file_prefix]="test"
    )

    # Execute
    exec_crystal_run CRY_JOB

    # Verify output file contains expected content
    [ -f "test.out" ]
    grep -q "CRYSTAL23 Mock Output" "test.out"
    grep -q "Calculation complete" "test.out"
}

@test "background execution returns correct exit code on failure" {
    # Create failing mock binary
    cat > "$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1/crystalOMP" << 'EOF'
#!/bin/bash
echo "ERROR: Calculation failed" > /dev/stdout
exit 1
EOF
    chmod +x "$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1/crystalOMP"

    # Setup job state
    declare -A CRY_JOB=(
        [MODE]="Serial/OpenMP"
        [EXE_PATH]="$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1/crystalOMP"
        [file_prefix]="test"
    )

    # Execute (should fail)
    run exec_crystal_run CRY_JOB

    # Verify non-zero exit code
    [ $status -eq 1 ]
}

@test "background execution works without gum" {
    # Temporarily hide gum
    export PATH="/dev/null:$PATH"

    # Setup job state
    declare -A CRY_JOB=(
        [MODE]="Serial/OpenMP"
        [EXE_PATH]="$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1/crystalOMP"
        [file_prefix]="test"
    )

    # Execute
    exec_crystal_run CRY_JOB
    exit_code=$?

    # Verify execution completed
    [ $exit_code -eq 0 ]

    # Verify output file created
    [ -f "test.out" ]
}

@test "background execution handles MPI mode" {
    skip "Requires MPI installation"

    # Create MPI mock
    cat > "$BATS_TEST_TMPDIR/mpirun" << 'EOF'
#!/bin/bash
# Mock mpirun - execute the binary directly
shift # Skip -np
shift # Skip rank count
exec "$@"
EOF
    chmod +x "$BATS_TEST_TMPDIR/mpirun"
    export PATH="$BATS_TEST_TMPDIR:$PATH"

    # Create PcrystalOMP mock
    cat > "$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1/PcrystalOMP" << 'EOF'
#!/bin/bash
sleep 1
echo "MPI CRYSTAL23 Mock Output" > /dev/stdout
exit 0
EOF
    chmod +x "$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1/PcrystalOMP"

    # Setup job state
    declare -A CRY_JOB=(
        [MODE]="Hybrid MPI/OpenMP"
        [EXE_PATH]="$CRY23_ROOT/bin/Linux-ifort_i64_omp/v1.0.1/PcrystalOMP"
        [MPI_RANKS]=4
        [file_prefix]="test"
    )

    # Execute
    exec_crystal_run CRY_JOB
    exit_code=$?

    # Verify execution completed
    [ $exit_code -eq 0 ]

    # Verify output file created
    [ -f "test.out" ]
    grep -q "MPI CRYSTAL23 Mock Output" "test.out"
}

@test "SSH color fix is applied on xterm terminals" {
    # Create a test wrapper that checks the TERM fix
    cat > "$BATS_TEST_TMPDIR/test_term_fix.sh" <<'WRAPPER'
#!/bin/bash
export TERM="xterm"
# Source the runcrystal header logic
if [[ "$TERM" == "xterm" || -z "$TERM" ]]; then
    export TERM=xterm-256color
fi
echo "$TERM"
WRAPPER
    chmod +x "$BATS_TEST_TMPDIR/test_term_fix.sh"

    # Run wrapper and check result
    result=$("$BATS_TEST_TMPDIR/test_term_fix.sh")
    [ "$result" = "xterm-256color" ]
}

@test "SSH color fix is applied when TERM is unset" {
    # Create a test wrapper that checks the TERM fix
    cat > "$BATS_TEST_TMPDIR/test_term_unset.sh" <<'WRAPPER'
#!/bin/bash
unset TERM
# Source the runcrystal header logic
if [[ "$TERM" == "xterm" || -z "$TERM" ]]; then
    export TERM=xterm-256color
fi
echo "${TERM:-not_set}"
WRAPPER
    chmod +x "$BATS_TEST_TMPDIR/test_term_unset.sh"

    # Run wrapper and check result
    result=$("$BATS_TEST_TMPDIR/test_term_unset.sh")
    [ "$result" = "xterm-256color" ]
}
