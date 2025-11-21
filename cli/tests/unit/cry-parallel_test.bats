#!/usr/bin/env bats

load '../helpers'

readonly TEST_PROJECT_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
readonly LIB_DIR="${TEST_PROJECT_ROOT}/lib"

declare -Ag PARALLEL_CMD_OVERRIDES=()
declare -ag PARALLEL_CMD_CHECKS=()
declare -g FAKE_CPU_COUNT=""

reset_parallel_mocks() {
    for cmd in nproc sysctl grep; do
        unset -f "$cmd" 2>/dev/null || true
    done
}

reset_parallel_env() {
    unset OMP_NUM_THREADS OMP_STACKSIZE I_MPI_PIN_DOMAIN KMP_AFFINITY
}

reset_command_overrides() {
    PARALLEL_CMD_OVERRIDES=()
    PARALLEL_CMD_CHECKS=()
}

set_command_available() {
    PARALLEL_CMD_OVERRIDES["$1"]=present
}

set_command_missing() {
    PARALLEL_CMD_OVERRIDES["$1"]=missing
}

command() {
    if [[ "$1" == "-v" ]]; then
        local target="$2"
        if [[ -n "${PARALLEL_CMD_OVERRIDES[$target]+_}" ]]; then
            PARALLEL_CMD_CHECKS+=("$target")
            if [[ "${PARALLEL_CMD_OVERRIDES[$target]}" == "present" ]]; then
                printf '%s\n' "$target"
                return 0
            fi
            return 1
        fi
    fi
    builtin command "$@"
}

call_parallel_detect_cores() {
    if declare -f parallel_detect_cores >/dev/null; then
        parallel_detect_cores
    else
        _parallel_get_cpu_count
    fi
}

set_fake_cpu_count() {
    FAKE_CPU_COUNT="$1"
    _parallel_get_cpu_count() {
        echo "$FAKE_CPU_COUNT"
    }
}

setup() {
    setup_test_env
    mock_reset
    reset_parallel_mocks
    reset_parallel_env
    reset_command_overrides
    source "${LIB_DIR}/cry-parallel.sh"
}

teardown() {
    reset_parallel_mocks
    teardown_test_env
}

@test "cry-parallel: parallel_detect_cores uses nproc when available" {
    set_command_available nproc
    set_command_missing sysctl
    mock_create nproc "12"

    local cores
    cores="$(call_parallel_detect_cores)"

    [ "$cores" = "12" ]
    assert_mock_called_with nproc
    assert_mock_not_called sysctl
    [ "${PARALLEL_CMD_CHECKS[0]}" = "nproc" ]
}

@test "cry-parallel: parallel_detect_cores falls back to sysctl when nproc missing" {
    if [[ -f /proc/cpuinfo ]]; then
        skip "sysctl fallback triggers only when /proc/cpuinfo is absent"
    fi

    set_command_missing nproc
    set_command_available sysctl
    mock_create sysctl "8"

    local cores
    cores="$(call_parallel_detect_cores)"

    [ "$cores" = "8" ]
    assert_mock_not_called nproc
    assert_mock_called_with sysctl -n hw.ncpu
    [ "${PARALLEL_CMD_CHECKS[0]}" = "nproc" ]
    [ "${PARALLEL_CMD_CHECKS[1]}" = "sysctl" ]
}

@test "cry-parallel: parallel_detect_cores falls back to /proc/cpuinfo when commands missing" {
    skip_if_not_linux

    set_command_missing nproc
    set_command_missing sysctl
    mock_create grep "6"

    local cores
    cores="$(call_parallel_detect_cores)"

    [ "$cores" = "6" ]
    assert_mock_not_called sysctl
    assert_mock_called_with grep -c ^processor /proc/cpuinfo
    [ "${PARALLEL_CMD_CHECKS[0]}" = "nproc" ]
}

@test "cry-parallel: parallel_setup configures serial OpenMP mode" {
    export BIN_DIR="${TEST_TEMP_DIR}/bin"
    mkdir -p "$BIN_DIR"
    declare -Ag job_state=()
    set_fake_cpu_count 8

    run parallel_setup 1 job_state

    assert_success
    [ "${job_state[MODE]}" = "Serial/OpenMP" ]
    [ "${job_state[EXE_PATH]}" = "${BIN_DIR}/crystalOMP" ]
    [ -z "${job_state[MPI_RANKS]}" ]
    [ "${job_state[THREADS_PER_RANK]}" = "8" ]
    [ "${job_state[TOTAL_CORES]}" = "8" ]
    [ "${OMP_NUM_THREADS}" = "8" ]
    [ "${OMP_STACKSIZE}" = "256M" ]
    [ -z "${I_MPI_PIN_DOMAIN:-}" ]
    [ -z "${KMP_AFFINITY:-}" ]
}

@test "cry-parallel: parallel_setup configures hybrid MPI/OpenMP mode" {
    export BIN_DIR="${TEST_TEMP_DIR}/bin"
    mkdir -p "$BIN_DIR"
    declare -Ag job_state=()
    set_fake_cpu_count 16

    run parallel_setup 4 job_state

    assert_success
    [ "${job_state[MODE]}" = "Hybrid MPI/OpenMP" ]
    [ "${job_state[EXE_PATH]}" = "${BIN_DIR}/PcrystalOMP" ]
    [ "${job_state[MPI_RANKS]}" = "4" ]
    [ "${job_state[THREADS_PER_RANK]}" = "4" ]
    [ "${job_state[TOTAL_CORES]}" = "16" ]
    [ "${OMP_NUM_THREADS}" = "4" ]
    [ "${OMP_STACKSIZE}" = "256M" ]
    [ "${I_MPI_PIN_DOMAIN}" = "omp" ]
    [ "${KMP_AFFINITY}" = "compact,1,0,granularity=fine" ]
}

@test "cry-parallel: parallel_setup clamps threads per rank to at least one" {
    export BIN_DIR="${TEST_TEMP_DIR}/bin"
    mkdir -p "$BIN_DIR"
    declare -Ag job_state=()
    set_fake_cpu_count 3

    run parallel_setup 4 job_state

    assert_success
    [ "${job_state[THREADS_PER_RANK]}" = "1" ]
    [ "${OMP_NUM_THREADS}" = "1" ]
}

@test "cry-parallel: CRY_JOB state captures totals and counts" {
    export BIN_DIR="${TEST_TEMP_DIR}/bin"
    mkdir -p "$BIN_DIR"
    declare -Ag job_state=()
    set_fake_cpu_count 24

    run parallel_setup 2 job_state

    assert_success
    [ "${job_state[TOTAL_CORES]}" = "24" ]
    [ "${job_state[MPI_RANKS]}" = "2" ]
    [ "${job_state[THREADS_PER_RANK]}" = "12" ]
    [ "${OMP_NUM_THREADS}" = "12" ]
}
