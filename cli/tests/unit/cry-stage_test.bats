#!/usr/bin/env bats

load '../helpers'

readonly TEST_PROJECT_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
readonly LIB_DIR="${TEST_PROJECT_ROOT}/lib"

declare -Ag STAGE_CMD_LAST_ARGS=()
declare -Ag STAGE_CMD_CALL_COUNT=()
declare -Ag STAGE_CMD_LOG=()
declare -g STAGE_TRACK_COMMANDS=0

declare STAGE_ORIGINAL_DIR=""
declare STAGE_WORK_DIR=""

ui_error() { echo "UI_ERROR: $*" >&2; }
ui_info() { :; }
ui_warning() { :; }
ui_file_found() { echo "FILE_FOUND: $*"; }

stage_reset_command_spies() {
    STAGE_CMD_LAST_ARGS=()
    STAGE_CMD_CALL_COUNT=()
    STAGE_CMD_LOG=()
}

record_stage_command_call() {
    local cmd="$1"
    shift
    local args="$*"
    STAGE_CMD_LAST_ARGS["$cmd"]="$args"
    local count="${STAGE_CMD_CALL_COUNT["$cmd"]:-0}"
    STAGE_CMD_CALL_COUNT["$cmd"]=$((count + 1))
    local log="${STAGE_CMD_LOG["$cmd"]:-}"
    STAGE_CMD_LOG["$cmd"]+="${args}\n"
}

cp() {
    if [[ "${STAGE_TRACK_COMMANDS:-0}" == "1" ]]; then
        record_stage_command_call cp "$@"
    fi
    command cp "$@"
}

ls() {
    if [[ "${STAGE_TRACK_COMMANDS:-0}" == "1" ]]; then
        record_stage_command_call ls "$@"
    fi
    command ls "$@"
}

test() {
    if [[ "${STAGE_TRACK_COMMANDS:-0}" == "1" ]]; then
        record_stage_command_call test "$@"
    fi
    builtin test "$@"
}

assert_stage_command_call_present() {
    local cmd="$1"
    shift
    local expected="$*"
    local log="${STAGE_CMD_LOG[$cmd]:-}"
    if [[ -z "$log" ]]; then
        echo "Expected $cmd to be called with: $expected"
        echo "But it was never called"
        return 1
    fi
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        if [[ "$line" == "$expected" ]]; then
            return 0
        fi
    done <<< "${log%$'\n'}"
    echo "Expected $cmd call args: $expected"
    echo "Recorded calls:\n${log}"
    return 1
}

assert_stage_command_not_called() {
    local cmd="$1"
    if [[ "${STAGE_CMD_CALL_COUNT[$cmd]:-0}" -ne 0 ]]; then
        echo "Expected $cmd to not be called, but it was"
        echo "Log:\n${STAGE_CMD_LOG[$cmd]}"
        return 1
    fi
}

get_stage_command_call_count() {
    local cmd="$1"
    echo "${STAGE_CMD_CALL_COUNT[$cmd]:-0}"
}

create_stage_dirs() {
    local label="$1"
    STAGE_ORIGINAL_DIR="${TEST_TEMP_DIR}/${label}/original"
    STAGE_WORK_DIR="${TEST_TEMP_DIR}/${label}/work"
    command rm -rf "${TEST_TEMP_DIR}/${label}"
    command mkdir -p "$STAGE_ORIGINAL_DIR" "$STAGE_WORK_DIR"
}

setup() {
    setup_test_env
    mock_reset
    stage_reset_command_spies
    STAGE_TRACK_COMMANDS=1
    source "${LIB_DIR}/cry-stage.sh"

    if [[ -n "${ZSH_VERSION:-}" ]]; then
        typeset -gA STAGE_MAP=(
            [gui]="fort.34"
            [f9]="fort.20"
            [f98]="fort.98"
            [hessopt]="HESSOPT.DAT"
            [born]="BORN.DAT"
        )
        typeset -gA RETRIEVE_MAP=(
            [fort.9]="f9"
            [fort.98]="f98"
            [HESSOPT.DAT]="hessopt"
        )
    elif [[ "${BASH_VERSINFO:-0}" -ge 4 ]]; then
        declare -gA STAGE_MAP=(
            [gui]="fort.34"
            [f9]="fort.20"
            [f98]="fort.98"
            [hessopt]="HESSOPT.DAT"
            [born]="BORN.DAT"
        )
        declare -gA RETRIEVE_MAP=(
            [fort.9]="f9"
            [fort.98]="f98"
            [HESSOPT.DAT]="hessopt"
        )
    else
        STAGE_MAP="gui:fort.34;f9:fort.20;f98:fort.98;hessopt:HESSOPT.DAT;born:BORN.DAT"
        RETRIEVE_MAP="fort.9:f9;fort.98:f98;HESSOPT.DAT:hessopt"
    fi
}

teardown() {
    STAGE_TRACK_COMMANDS=0
    teardown_test_env
}

@test "cry-stage: stage_inputs copies .d12 file to INPUT" {
    create_stage_dirs "inputs_default"
    printf 'input data' > "${STAGE_ORIGINAL_DIR}/calc.d12"

    run stage_inputs calc "$STAGE_WORK_DIR" "$STAGE_ORIGINAL_DIR"

    assert_success
    assert_file_exists "$STAGE_WORK_DIR/INPUT"
    assert_stage_command_call_present cp "$STAGE_ORIGINAL_DIR/calc.d12 $STAGE_WORK_DIR/INPUT"
}

@test "cry-stage: stage_inputs stages .gui file to fort.34" {
    create_stage_dirs "inputs_gui"
    printf 'input data' > "${STAGE_ORIGINAL_DIR}/calc.d12"
    printf 'gui data' > "${STAGE_ORIGINAL_DIR}/calc.gui"

    run stage_inputs calc "$STAGE_WORK_DIR" "$STAGE_ORIGINAL_DIR"

    assert_success
    assert_file_exists "$STAGE_WORK_DIR/fort.34"
    assert_stage_command_call_present cp "$STAGE_ORIGINAL_DIR/calc.gui $STAGE_WORK_DIR/fort.34"
}

@test "cry-stage: stage_inputs stages .f9 file to fort.20" {
    create_stage_dirs "inputs_f9"
    printf 'input data' > "${STAGE_ORIGINAL_DIR}/calc.d12"
    printf 'f9 data' > "${STAGE_ORIGINAL_DIR}/calc.f9"

    run stage_inputs calc "$STAGE_WORK_DIR" "$STAGE_ORIGINAL_DIR"

    assert_success
    assert_file_exists "$STAGE_WORK_DIR/fort.20"
    assert_stage_command_call_present cp "$STAGE_ORIGINAL_DIR/calc.f9 $STAGE_WORK_DIR/fort.20"
}

@test "cry-stage: stage_inputs succeeds when auxiliary files are missing" {
    create_stage_dirs "inputs_missing_aux"
    printf 'input data' > "${STAGE_ORIGINAL_DIR}/calc.d12"

    run stage_inputs calc "$STAGE_WORK_DIR" "$STAGE_ORIGINAL_DIR"

    assert_success
    [ "$(get_stage_command_call_count cp)" -eq 1 ]
    assert_stage_command_call_present cp "$STAGE_ORIGINAL_DIR/calc.d12 $STAGE_WORK_DIR/INPUT"
}

@test "cry-stage: stage_inputs honors STAGE_MAP destinations" {
    create_stage_dirs "inputs_map"
    printf 'input data' > "${STAGE_ORIGINAL_DIR}/calc.d12"
    printf 'hess data' > "${STAGE_ORIGINAL_DIR}/calc.hessopt"
    printf 'born data' > "${STAGE_ORIGINAL_DIR}/calc.born"

    run stage_inputs calc "$STAGE_WORK_DIR" "$STAGE_ORIGINAL_DIR"

    assert_success
    assert_file_exists "$STAGE_WORK_DIR/HESSOPT.DAT"
    assert_file_exists "$STAGE_WORK_DIR/BORN.DAT"
    assert_stage_command_call_present cp "$STAGE_ORIGINAL_DIR/calc.hessopt $STAGE_WORK_DIR/HESSOPT.DAT"
    assert_stage_command_call_present cp "$STAGE_ORIGINAL_DIR/calc.born $STAGE_WORK_DIR/BORN.DAT"
}

@test "cry-stage: stage_retrieve_results copies OUTPUT to .out" {
    create_stage_dirs "retrieve_output"
    printf 'output data' > "${STAGE_WORK_DIR}/OUTPUT"

    run stage_retrieve_results calc "$STAGE_WORK_DIR" "$STAGE_ORIGINAL_DIR"

    assert_success
    assert_stage_command_call_present cp "$STAGE_WORK_DIR/OUTPUT $STAGE_ORIGINAL_DIR/calc.out"
    assert_file_exists "$STAGE_ORIGINAL_DIR/calc.out"
}

@test "cry-stage: stage_retrieve_results copies f9, f98, and hessopt results" {
    create_stage_dirs "retrieve_results"
    printf 'f9 result' > "${STAGE_WORK_DIR}/fort.9"
    printf 'f98 result' > "${STAGE_WORK_DIR}/fort.98"
    printf 'hessopt result' > "${STAGE_WORK_DIR}/HESSOPT.DAT"

    run stage_retrieve_results calc "$STAGE_WORK_DIR" "$STAGE_ORIGINAL_DIR"

    assert_success
    assert_stage_command_call_present cp "$STAGE_WORK_DIR/fort.9 $STAGE_ORIGINAL_DIR/calc.f9"
    assert_stage_command_call_present cp "$STAGE_WORK_DIR/fort.98 $STAGE_ORIGINAL_DIR/calc.f98"
    assert_stage_command_call_present cp "$STAGE_WORK_DIR/HESSOPT.DAT $STAGE_ORIGINAL_DIR/calc.hessopt"
}

@test "cry-stage: missing result files do not cause stage_retrieve_results to fail" {
    create_stage_dirs "retrieve_missing"

    run stage_retrieve_results calc "$STAGE_WORK_DIR" "$STAGE_ORIGINAL_DIR"

    assert_success
    assert_stage_command_not_called cp
}
