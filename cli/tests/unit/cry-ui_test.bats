#!/usr/bin/env bats

load '../helpers'

readonly TEST_PROJECT_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
readonly LIB_DIR="${TEST_PROJECT_ROOT}/lib"

GUM_CALL_LOG=""

setup() {
    setup_test_env
    mock_reset
    unset -f gum 2>/dev/null || true
    source "${LIB_DIR}/cry-ui.sh"
    HAS_GUM=false
    GUM_CALL_LOG=""
}

teardown() {
    teardown_test_env
}

setup_gum_mock() {
    local stdout_value="${1:-}"
    local exit_code="${2:-0}"

    GUM_CALL_LOG="${TEST_TEMP_DIR}/gum_calls.log"
    : >"${GUM_CALL_LOG}"

    mock_create gum "${stdout_value}" "${exit_code}"

    eval "
gum() {
    echo \"\$*\" >> \"${GUM_CALL_LOG}\"
    echo -n \"\${MOCK_STDOUT[gum]}\"
    return \${MOCK_EXIT_CODE[gum]}
}
"

    HAS_GUM=true
}

assert_gum_call_line_equals() {
    local line="$1"
    shift
    if [[ -z "${GUM_CALL_LOG}" || ! -f "${GUM_CALL_LOG}" ]]; then
        fail "gum call log not initialized"
    fi

    local actual
    actual="$(sed -n "${line}p" "${GUM_CALL_LOG}")"
    if [[ -z "${actual}" ]]; then
        fail "no gum call recorded on line ${line}"
    fi

    MOCK_CALLS["gum"]="${actual}"
    assert_mock_called_with gum "$@"
}

assert_no_gum_calls() {
    if [[ -n "${GUM_CALL_LOG}" && -s "${GUM_CALL_LOG}" ]]; then
        fail "gum was unexpectedly invoked: $(cat "${GUM_CALL_LOG}")"
    fi
}

@test "cry-ui: ui_banner uses gum style with primary color" {
    setup_gum_mock

    run ui_banner

    assert_success
    assert_gum_call_line_equals 1 style --foreground 39
}

@test "cry-ui: ui_banner falls back to plain echo without gum" {
    HAS_GUM=false

    run ui_banner

    assert_success
    [ "${output}" = "CRYSTAL 23" ]
    assert_no_gum_calls
}

@test "cry-ui: ui_card uses gum to style title and body" {
    setup_gum_mock

    run ui_card "Project" "Line 1" "Line 2"

    assert_success
    assert_gum_call_line_equals 1 style --foreground 86 --bold Project
    assert_gum_call_line_equals 2 style --border rounded --margin 1 0 --padding 0 2 --border-foreground 39   Line 1 Line 2
}

@test "cry-ui: ui_card prints separators and all lines when gum missing" {
    HAS_GUM=false

    run ui_card "Project" "Line 1" "Line 2"

    assert_success
    expected_output=$'--- Project ---\nLine 1\nLine 2\n-----------------'
    [ "${output}" = "${expected_output}" ]
    assert_no_gum_calls
}

@test "cry-ui: ui_status_line uses dim/text colors with gum" {
    setup_gum_mock

    run ui_status_line "Label" "Value"

    assert_success
    assert_gum_call_line_equals 1 style --foreground 240 Label:
    assert_gum_call_line_equals 2 style --foreground 255 --bold Value
}

@test "cry-ui: ui_status_line echoes plain label when gum missing" {
    HAS_GUM=false

    run ui_status_line "Label" "Value"

    assert_success
    [ "${output}" = "Label: Value" ]
    assert_no_gum_calls
}

@test "cry-ui: ui_success styles check mark with gum" {
    setup_gum_mock

    run ui_success "All good"

    assert_success
    assert_gum_call_line_equals 1 style --foreground 86 ✓
}

@test "cry-ui: ui_success echoes symbol when gum missing" {
    HAS_GUM=false

    run ui_success "All good"

    assert_success
    [ "${output}" = "✓ All good" ]
    assert_no_gum_calls
}

@test "cry-ui: ui_error styles prefix with gum" {
    setup_gum_mock

    run ui_error "Failure"

    assert_success
    assert_gum_call_line_equals 1 style --foreground 196 --bold ERROR:
}

@test "cry-ui: ui_error prints to stderr when gum missing" {
    HAS_GUM=false

    run ui_error "Failure"

    assert_success
    [ "${output}" = "ERROR: Failure" ]
    assert_no_gum_calls
}

@test "cry-ui: ui_section_header uses gum bold secondary color" {
    setup_gum_mock

    run ui_section_header "Section"

    assert_success
    assert_gum_call_line_equals 1 style --foreground 86 --bold Section
}

@test "cry-ui: ui_section_header echoes title without gum" {
    HAS_GUM=false

    run ui_section_header "Section"

    assert_success
    [ "${output}" = "Section" ]
    assert_no_gum_calls
}

@test "cry-ui: ui_file_found uses gum style with found text" {
    setup_gum_mock

    run ui_file_found "/tmp/demo"

    assert_success
    assert_gum_call_line_equals 1 style --foreground 86 ✓ Found:
}

@test "cry-ui: ui_file_found echoes check mark when gum missing" {
    HAS_GUM=false

    run ui_file_found "/tmp/demo"

    assert_success
    [ "${output}" = "✓ Found: /tmp/demo" ]
    assert_no_gum_calls
}

@test "cry-ui: ui_spin delegates to gum spinner with command" {
    setup_gum_mock

    run ui_spin "Install" "echo hi"

    assert_success
    assert_gum_call_line_equals 1 spin --spinner dot --title Install -- bash -c echo hi
}

@test "cry-ui: ui_spin executes command and exit code without gum" {
    HAS_GUM=false

    run ui_spin "Run task" "exit 7"

    [ "${status}" -eq 7 ]
    assert_output_contains ">> Run task..."
    assert_no_gum_calls
}
