#!/usr/bin/env bats

load '../helpers'

readonly TEST_PROJECT_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
readonly LIB_DIR="${TEST_PROJECT_ROOT}/lib"

declare -Ag TEST_CMD_V_OVERRIDES=()

record_mock_call() {
    local cmd="$1"
    shift
    local args="$*"
    MOCK_CALLS["$cmd"]="$args"
}

mock_command_noop() {
    local cmd="$1"
    local exit_code="${2:-0}"

    eval "
${cmd}() {
    record_mock_call ${cmd} \"\$*\"
    return ${exit_code}
}
"
}

mock_tar_extracts_gum() {
    tar() {
        record_mock_call tar "$*"
        local dest="."
        local arg
        while (($#)); do
            arg="$1"
            if [[ "$arg" == "-C" ]]; then
                shift
                dest="$1"
            fi
            shift
        done

        mkdir -p "$dest/gum-extracted"
        printf 'binary' > "$dest/gum-extracted/gum"
        chmod +x "$dest/gum-extracted/gum"
        mkdir -p "$dest/man"
        printf 'manual' > "$dest/man/gum.1"
        return 0
    }
}

mock_command_presence() {
    TEST_CMD_V_OVERRIDES["$1"]=present
}

mock_command_absence() {
    TEST_CMD_V_OVERRIDES["$1"]=missing
}

reset_command_overrides() {
    TEST_CMD_V_OVERRIDES=()
}

reset_mocked_commands() {
    for cmd in go curl tar chmod; do
        unset -f "$cmd" 2>/dev/null || true
    done
}

require_cry_ensure_gum() {
    if ! declare -f cry_ensure_gum >/dev/null; then
        skip "cry_ensure_gum not implemented in lib/cry-config.sh"
    fi
}

reset_config_state() {
    unset CRY23_ROOT CRY_VERSION CRY_ARCH CRY_BIN_DIR BIN_DIR
    unset CRY_SCRATCH_BASE SCRATCH_BASE CRY_USER_BIN CRY_USER_MAN
    unset CRY_TUTORIAL_DIR TUTORIAL_DIR PROJECT_ROOT
}

prepare_gum_install_env() {
    export CRY_USER_BIN="${TEST_TEMP_DIR}/user-bin"
    export CRY_USER_MAN="${TEST_TEMP_DIR}/user-man"
    mkdir -p "$CRY_USER_BIN" "$CRY_USER_MAN"
}

create_fake_gum_on_path() {
    local fake_bin="${TEST_TEMP_DIR}/bin"
    mkdir -p "$fake_bin"
    cat > "$fake_bin/gum" <<'SCRIPT'
#!/usr/bin/env bash
exit 0
SCRIPT
    chmod +x "$fake_bin/gum"
    PATH="$fake_bin:${PATH}"
}

command() {
    if [[ "$1" == "-v" ]]; then
        local target="$2"
        if [[ -n "${TEST_CMD_V_OVERRIDES[$target]+_}" ]]; then
            if [[ "${TEST_CMD_V_OVERRIDES[$target]}" == "present" ]]; then
                printf '%s\n' "$target"
                return 0
            fi
            return 1
        fi
    fi
    builtin command "$@"
}

setup() {
    setup_test_env
    mock_reset
    reset_mocked_commands
    reset_command_overrides
    ORIGINAL_PATH="$PATH"
    ORIGINAL_HOME="$HOME"
    export HOME="${TEST_TEMP_DIR}/home"
    mkdir -p "$HOME"
    export CRY_NO_AUTO_INIT=1
    export CRY_CONFIG_FILE="${TEST_TEMP_DIR}/cry.conf"
    source "${LIB_DIR}/cry-config.sh"
}

teardown() {
    PATH="$ORIGINAL_PATH"
    HOME="$ORIGINAL_HOME"
    teardown_test_env
}

@test "cry-config: cry_config_init sets default paths when env unset" {
    reset_config_state
    cry_config_init

    [ "$CRY23_ROOT" = "$HOME/CRYSTAL23" ]
    [ "$CRY_BIN_DIR" = "$HOME/CRYSTAL23/bin/Linux-ifort_i64_omp/v1.0.1" ]
    [ "$CRY_SCRATCH_BASE" = "$HOME/tmp_crystal" ]
    [ "$SCRATCH_BASE" = "$CRY_SCRATCH_BASE" ]
    [ "$CRY_USER_BIN" = "$HOME/.local/bin" ]
    [ "$CRY_USER_MAN" = "$HOME/.local/share/man/man1" ]
    [ "$TUTORIAL_DIR" = "${TEST_PROJECT_ROOT}/share/tutorials" ]
}

@test "cry-config: cry_config_init respects existing CRY23_ROOT" {
    reset_config_state
    export CRY23_ROOT="${TEST_TEMP_DIR}/custom-root"
    cry_config_init

    [ "$CRY23_ROOT" = "${TEST_TEMP_DIR}/custom-root" ]
    [ "$CRY_BIN_DIR" = "${CRY23_ROOT}/bin/${CRY_ARCH}/${CRY_VERSION}" ]
}

@test "cry-config: theme colors are exported" {
    [ "$C_PRIMARY" = "39" ]
    [ "$C_SEC" = "86" ]
    [ "$C_WARN" = "214" ]
    [ "$C_ERR" = "196" ]
    [ "$C_TEXT" = "255" ]
    [ "$C_DIM" = "240" ]
}

@test "cry-config: cry_ensure_gum returns immediately when gum already installed" {
    require_cry_ensure_gum
    prepare_gum_install_env
    create_fake_gum_on_path
    mock_command_noop go
    mock_command_noop curl
    mock_command_noop tar

    run cry_ensure_gum

    assert_success
    assert_mock_not_called go
    assert_mock_not_called curl
    assert_mock_not_called tar
}

@test "cry-config: cry_ensure_gum uses go install when go is available" {
    require_cry_ensure_gum
    prepare_gum_install_env
    mock_command_absence gum
    mock_command_presence go
    mock_command_noop go
    mock_command_noop curl
    mock_command_noop tar

    run cry_ensure_gum

    assert_success
    assert_mock_called go
    assert_mock_not_called curl
}

@test "cry-config: cry_ensure_gum downloads via curl when go unavailable" {
    require_cry_ensure_gum
    prepare_gum_install_env
    mock_command_absence gum
    mock_command_absence go
    mock_command_presence curl
    mock_command_noop go
    mock_command_noop curl
    mock_tar_extracts_gum

    run cry_ensure_gum

    assert_success
    assert_mock_not_called go
    assert_mock_called curl
    assert_mock_called tar
}

@test "cry-config: cry_ensure_gum fails when neither go nor curl succeeds" {
    require_cry_ensure_gum
    prepare_gum_install_env
    mock_command_absence gum
    mock_command_absence go
    mock_command_presence curl
    mock_command_noop go
    mock_command_noop curl 1

    run cry_ensure_gum

    assert_failure
}
