#!/usr/bin/env bats
# Integration test for --explain/--dry-run educational mode
# Tests that explain mode displays educational information without executing

load ../helpers

setup() {
    # Create temporary test directory
    TEST_DIR=$(mktemp -d)
    cd "$TEST_DIR"

    # Create mock input file
    cat > test_calc.d12 <<EOF
CRYSTAL
0 0 0
1
1.0
1
H 1.0 0.0 0.0
END
EOF

    # Setup mock CRYSTAL23 environment
    export CRY23_ROOT="$TEST_DIR/mock_crystal"
    mkdir -p "$CRY23_ROOT/bin"

    # Create mock executables
    cat > "$CRY23_ROOT/bin/crystalOMP" <<'SCRIPT'
#!/bin/bash
echo "Mock CRYSTAL23 Serial execution"
exit 0
SCRIPT
    chmod +x "$CRY23_ROOT/bin/crystalOMP"

    cat > "$CRY23_ROOT/bin/PcrystalOMP" <<'SCRIPT'
#!/bin/bash
echo "Mock CRYSTAL23 Parallel execution"
exit 0
SCRIPT
    chmod +x "$CRY23_ROOT/bin/PcrystalOMP"

    # Point to the actual runcrystal script
    RUNCRYSTAL="$BATS_TEST_DIRNAME/../../bin/runcrystal"
}

teardown() {
    # Clean up test directory
    cd "$BATS_TEST_DIRNAME"
    rm -rf "$TEST_DIR"
}

@test "explain mode: --explain flag displays educational output and exits" {
    run "$RUNCRYSTAL" --explain test_calc

    # Should exit successfully
    [ "$status" -eq 0 ]

    # Should contain banner (ASCII art contains /___/ pattern)
    [[ "$output" =~ "/___/" ]] || [[ "$output" =~ "Dry Run" ]]

    # Should contain all 5 sections
    [[ "$output" =~ "1. Hardware Detection" ]]
    [[ "$output" =~ "2. Parallel Strategy" ]]
    [[ "$output" =~ "3. Intel Optimizations" ]]
    [[ "$output" =~ "4. File Staging" ]]
    [[ "$output" =~ "5. Execution Command" ]]

    # Should show physical cores
    [[ "$output" =~ "Physical Cores:" ]]

    # Should show mode for serial execution
    [[ "$output" =~ "Serial/OpenMP" ]]

    # Should NOT create scratch directory
    [ ! -d "$HOME/tmp_crystal" ] || [ -z "$(ls -A $HOME/tmp_crystal 2>/dev/null)" ]
}

@test "explain mode: --dry-run flag works identically to --explain" {
    run "$RUNCRYSTAL" --dry-run test_calc

    # Should exit successfully
    [ "$status" -eq 0 ]

    # Should contain educational sections
    [[ "$output" =~ "1. Hardware Detection" ]]
    [[ "$output" =~ "2. Parallel Strategy" ]]
    [[ "$output" =~ "3. Intel Optimizations" ]]
    [[ "$output" =~ "4. File Staging" ]]
    [[ "$output" =~ "5. Execution Command" ]]

    # Should NOT create scratch directory
    [ ! -d "$HOME/tmp_crystal" ] || [ -z "$(ls -A $HOME/tmp_crystal 2>/dev/null)" ]
}

@test "explain mode: shows correct parallel configuration for MPI ranks" {
    run "$RUNCRYSTAL" --explain test_calc 14

    [ "$status" -eq 0 ]

    # Should show hybrid mode
    [[ "$output" =~ "Hybrid MPI/OpenMP" ]]

    # Should show 14 ranks
    [[ "$output" =~ "Requested Ranks: 14" ]]

    # Should show threads per rank calculation
    [[ "$output" =~ "Threads per Rank:" ]]

    # Should show Intel MPI optimizations
    [[ "$output" =~ "Pinning:" ]]
    [[ "$output" =~ "Affinity:" ]]

    # Should show execution command with mpirun
    [[ "$output" =~ "mpirun" ]] || [[ "$output" =~ "Execution Command" ]]
}

@test "explain mode: displays scratch directory path correctly" {
    run "$RUNCRYSTAL" --explain test_calc

    [ "$status" -eq 0 ]

    # Should show scratch path with job name
    [[ "$output" =~ "cry_test_calc_" ]] || [[ "$output" =~ "Scratch Directory:" ]]
}

@test "explain mode: shows auxiliary file staging information" {
    run "$RUNCRYSTAL" --explain test_calc

    [ "$status" -eq 0 ]

    # Should mention auxiliary files
    [[ "$output" =~ ".gui" ]]
    [[ "$output" =~ ".f9" ]]
    [[ "$output" =~ ".hessopt" ]]
    [[ "$output" =~ ".born" ]]
}

@test "explain mode: displays educational 'Why?' information" {
    run "$RUNCRYSTAL" --explain test_calc 14

    [ "$status" -eq 0 ]

    # Should explain WHY the strategy is chosen
    [[ "$output" =~ "Why?" ]]
    [[ "$output" =~ "balance" ]] || [[ "$output" =~ "memory" ]] || [[ "$output" =~ "speed" ]]
}

@test "explain mode: does not execute CRYSTAL23 binary" {
    # Create a "trip wire" - if binary runs, it will create this file
    cat > "$CRY23_ROOT/bin/crystalOMP" <<'SCRIPT'
#!/bin/bash
touch /tmp/crystal_was_executed
exit 0
SCRIPT
    chmod +x "$CRY23_ROOT/bin/crystalOMP"

    run "$RUNCRYSTAL" --explain test_calc

    [ "$status" -eq 0 ]

    # Trip wire file should NOT exist
    [ ! -f "/tmp/crystal_was_executed" ]
}

@test "explain mode: handles missing input file gracefully" {
    run "$RUNCRYSTAL" --explain nonexistent_file

    # Should fail with error
    [ "$status" -ne 0 ]

    # Should show error message
    [[ "$output" =~ "not found" ]] || [[ "$output" =~ "ERROR" ]]
}

@test "explain mode: works with .d12 extension in filename" {
    run "$RUNCRYSTAL" --explain test_calc.d12

    [ "$status" -eq 0 ]

    # Should process correctly
    [[ "$output" =~ "1. Hardware Detection" ]]
}

@test "explain mode: displays correct stack size warning" {
    run "$RUNCRYSTAL" --explain test_calc

    [ "$status" -eq 0 ]

    # Should show stack size with explanation
    [[ "$output" =~ "Stack Size:" ]]
    [[ "$output" =~ "256M" ]] || [[ "$output" =~ "stack overflow" ]]
}
