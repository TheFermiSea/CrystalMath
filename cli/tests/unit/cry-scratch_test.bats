#!/usr/bin/env bats

load '../helpers'

readonly TEST_PROJECT_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
readonly LIB_DIR="${TEST_PROJECT_ROOT}/lib"

declare -Ag SCRATCH_CMD_LAST_ARGS=()
declare -Ag SCRATCH_CMD_CALL_COUNT=()
declare -g SCRATCH_TRACK_COMMANDS=0

reset_scratch_command_spies() {
    SCRATCH_CMD_LAST_ARGS=()
    SCRATCH_CMD_CALL_COUNT=()
}

record_scratch_command_call() {
    local cmd="$1"
    shift
    SCRATCH_CMD_LAST_ARGS["$cmd"]="$*"
    local count="${SCRATCH_CMD_CALL_COUNT["$cmd"]:-0}"
    SCRATCH_CMD_CALL_COUNT["$cmd"]=$((count + 1))
}

mkdir() {
    if [[ "${SCRATCH_TRACK_COMMANDS:-0}" == "1" ]]; then
        record_scratch_command_call mkdir "$@"
    fi
    command mkdir "$@"
}

rm() {
    if [[ "${SCRATCH_TRACK_COMMANDS:-0}" == "1" ]]; then
        record_scratch_command_call rm "$@"
    fi
    command rm "$@"
}

test() {
    if [[ "${SCRATCH_TRACK_COMMANDS:-0}" == "1" && -n "${CRY_SCRATCH_BASE:-}" && "$*" == *"${CRY_SCRATCH_BASE}"* ]]; then
        record_scratch_command_call test "$@"
    fi
    builtin test "$@"
}

assert_scratch_command_called_with() {
    local cmd="$1"
    shift
    local expected="$*"
    if [[ "${SCRATCH_CMD_LAST_ARGS[$cmd]:-}" != "$expected" ]]; then
        echo "Expected $cmd to be called with: $expected"
        echo "Actually called with: ${SCRATCH_CMD_LAST_ARGS[$cmd]:-<not called>}"
        return 1
    fi
}

get_scratch_command_call_count() {
    local cmd="$1"
    echo "${SCRATCH_CMD_CALL_COUNT[$cmd]:-0}"
}

setup() {
    setup_test_env
    mock_reset
    reset_scratch_command_spies
    export CRY_SCRATCH_BASE="${BATS_TEST_TMPDIR}/tmp_crystal"
    command rm -rf "${CRY_SCRATCH_BASE}"
    command mkdir -p "${CRY_SCRATCH_BASE}"
    source "${LIB_DIR}/cry-scratch.sh"
    SCRATCH_TRACK_COMMANDS=1
    unset WORK_DIR
}

teardown() {
    SCRATCH_TRACK_COMMANDS=0
    teardown_test_env
}

@test "cry-scratch: scratch_create creates unique directory with naming pattern" {
    run scratch_create default

    assert_success
    [[ "$WORK_DIR" =~ ^${CRY_SCRATCH_BASE}/cry_default_[0-9]+$ ]]
    assert_dir_exists "$WORK_DIR"
    assert_scratch_command_called_with mkdir -p "$WORK_DIR"
}

@test "cry-scratch: scratch_create exports WORK_DIR global" {
    run scratch_create geom

    assert_success
    [ -n "${WORK_DIR:-}" ]
    local exported
    exported="$(env | grep '^WORK_DIR=')"
    [ "$exported" = "WORK_DIR=$WORK_DIR" ]
}

@test "cry-scratch: scratch_create creates parent directories via mkdir -p" {
    command rm -rf "${CRY_SCRATCH_BASE}"

    run scratch_create nested

    assert_success
    assert_dir_exists "$WORK_DIR"
    assert_dir_exists "${CRY_SCRATCH_BASE}"
    assert_scratch_command_called_with mkdir -p "$WORK_DIR"
}

@test "cry-scratch: scratch_cleanup removes directory when WORK_DIR set" {
    run scratch_create cleanup
    assert_success
    local dir="$WORK_DIR"

    run scratch_cleanup

    assert_success
    [ ! -d "$dir" ]
    assert_scratch_command_called_with rm -rf "$dir"
}

@test "cry-scratch: scratch_cleanup no-ops when WORK_DIR unset" {
    unset WORK_DIR

    run scratch_cleanup

    assert_success
    [ "$(get_scratch_command_call_count rm)" -eq 0 ]
}

@test "cry-scratch: scratch_cleanup skips removal when directory missing" {
    export WORK_DIR="${CRY_SCRATCH_BASE}/ghost"
    command rm -rf "$WORK_DIR"

    run scratch_cleanup

    assert_success
    [ "$(get_scratch_command_call_count rm)" -eq 0 ]
}

@test "cry-scratch: scratch_cleanup unsets WORK_DIR after cleanup" {
    run scratch_create final
    assert_success

    run scratch_cleanup

    assert_success
    [ -z "${WORK_DIR:-}" ]
}
