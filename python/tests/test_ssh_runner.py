"""Tests for SSHRunner: direct (schedulerless) remote job execution.

Uses mocked ConnectionManager/asyncssh connections throughout — no real SSH
connection is made. See scripts/ (or the manual verification session this
was built alongside) for a real end-to-end run against actual hardware;
that's deliberately out of scope for the automated suite.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from crystalmath._vendor.core.codes import DFTCode
from crystalmath._vendor.runners.base import JobStatus, RunnerConfig
from crystalmath._vendor.runners.exceptions import JobNotFoundError
from crystalmath._vendor.runners.ssh_runner import SSHJobConfig, SSHRunner, SSHSubmissionError


def _make_run_result(stdout: str = "", stderr: str = "", exit_status: int = 0):
    result = MagicMock()
    result.stdout = stdout
    result.stderr = stderr
    result.exit_status = exit_status
    return result


@pytest.fixture
def mock_conn():
    """A mock asyncssh connection with run() and start_sftp_client() stubbed."""
    conn = MagicMock()
    conn.run = AsyncMock(return_value=_make_run_result())

    sftp = MagicMock()
    sftp.put = AsyncMock()
    sftp.__aenter__ = AsyncMock(return_value=sftp)
    sftp.__aexit__ = AsyncMock(return_value=False)
    conn.start_sftp_client = AsyncMock(return_value=sftp)
    return conn


@pytest.fixture
def mock_connection_manager(mock_conn):
    """A mock ConnectionManager whose get_connection() async-context-manager
    yields the shared mock_conn."""
    manager = MagicMock()

    class _CtxMgr:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, *exc):
            return False

    manager.get_connection = MagicMock(return_value=_CtxMgr())
    return manager


@pytest.fixture
def runner(mock_connection_manager):
    return SSHRunner(
        connection_manager=mock_connection_manager,
        cluster_id=1,
        dft_code=DFTCode.CRYSTAL,
        remote_scratch_base="/tmp/dft_jobs",
    )


@pytest.fixture
def input_file(tmp_path):
    p = tmp_path / "input.d12"
    p.write_text("TEST INPUT\n")
    return p


class TestJobHandleParsing:
    def test_parse_valid_handle(self, runner):
        cluster_id, pid, remote_dir = runner._parse_job_handle("ssh:1:12345:/tmp/dft_jobs/1_work")
        assert cluster_id == 1
        assert pid == "12345"
        assert remote_dir == "/tmp/dft_jobs/1_work"

    def test_parse_rejects_wrong_prefix(self, runner):
        with pytest.raises(JobNotFoundError):
            runner._parse_job_handle("slurm:1:12345:/tmp/dft_jobs/1_work")

    def test_parse_rejects_malformed_handle(self, runner):
        with pytest.raises(JobNotFoundError):
            runner._parse_job_handle("not-a-handle")


class TestExecutableResolution:
    def test_uses_code_config_by_default(self, runner):
        assert runner._resolve_executable(parallel=False) == "crystal"
        assert runner._resolve_executable(parallel=True) == "Pcrystal"

    def test_executable_path_override_wins(self, mock_connection_manager):
        cfg = RunnerConfig(executable_path=Path("/opt/CRYSTAL23/bin/Pcrystal"))
        r = SSHRunner(mock_connection_manager, cluster_id=1, config=cfg)
        assert r._resolve_executable(parallel=True) == "/opt/CRYSTAL23/bin/Pcrystal"
        assert r._resolve_executable(parallel=False) == "/opt/CRYSTAL23/bin/Pcrystal"


class TestSubmitJob:
    @pytest.mark.asyncio
    async def test_submit_returns_ssh_handle_with_pid(
        self, runner, mock_conn, input_file, tmp_path
    ):
        mock_conn.run = AsyncMock(
            side_effect=[
                _make_run_result(),  # mkdir -p
                _make_run_result(stdout="54321\n"),  # nohup launch, echo $!
            ]
        )
        handle = await runner.submit_job(1, input_file, tmp_path)
        assert handle.startswith("ssh:1:54321:/tmp/dft_jobs/1_")

    @pytest.mark.asyncio
    async def test_submit_missing_input_raises(self, runner, tmp_path):
        with pytest.raises(SSHSubmissionError):
            await runner.submit_job(1, tmp_path / "does_not_exist.d12", tmp_path)

    @pytest.mark.asyncio
    async def test_submit_uploads_input_as_literal_input_file(
        self, runner, mock_conn, input_file, tmp_path
    ):
        """CRYSTAL's parallel binary doesn't reliably read the input deck via
        redirected stdin across all MPI ranks — it must be staged as a file
        literally named INPUT. See _get_remote_input_name's docstring."""
        mock_conn.run = AsyncMock(
            side_effect=[_make_run_result(), _make_run_result(stdout="111\n")]
        )
        sftp = await mock_conn.start_sftp_client()
        await runner.submit_job(1, input_file, tmp_path)
        sftp.put.assert_any_call(str(input_file), f"/tmp/dft_jobs/1_{tmp_path.name}/INPUT")

    @pytest.mark.asyncio
    async def test_submit_no_pid_raises(self, runner, mock_conn, input_file, tmp_path):
        mock_conn.run = AsyncMock(
            side_effect=[_make_run_result(), _make_run_result(stdout="not-a-pid\n")]
        )
        with pytest.raises(SSHSubmissionError):
            await runner.submit_job(1, input_file, tmp_path)

    @pytest.mark.asyncio
    async def test_submit_wraps_with_mpirun_when_parallel(
        self, runner, mock_conn, input_file, tmp_path
    ):
        captured_cmds: list[str] = []

        async def _capture(cmd, check=False):
            captured_cmds.append(cmd)
            if cmd.startswith("mkdir"):
                return _make_run_result()
            return _make_run_result(stdout="222\n")

        mock_conn.run = AsyncMock(side_effect=_capture)
        await runner.submit_job(
            1, input_file, tmp_path, threads=2, config=SSHJobConfig(ntasks=4, threads=2)
        )
        launch_cmd = captured_cmds[-1]
        assert "mpirun -np 4" in launch_cmd
        assert "OMP_NUM_THREADS=2" in launch_cmd
        assert "Pcrystal" in launch_cmd  # parallel executable chosen when ntasks > 1

    @pytest.mark.asyncio
    async def test_submit_serial_when_ntasks_one(self, runner, mock_conn, input_file, tmp_path):
        captured_cmds: list[str] = []

        async def _capture(cmd, check=False):
            captured_cmds.append(cmd)
            if cmd.startswith("mkdir"):
                return _make_run_result()
            return _make_run_result(stdout="333\n")

        mock_conn.run = AsyncMock(side_effect=_capture)
        await runner.submit_job(1, input_file, tmp_path)
        launch_cmd = captured_cmds[-1]
        assert "mpirun" not in launch_cmd
        assert " crystal <" in launch_cmd or "'crystal <" in launch_cmd

    @pytest.mark.asyncio
    async def test_submit_prepends_environment_setup(self, runner, mock_conn, input_file, tmp_path):
        captured_cmds: list[str] = []

        async def _capture(cmd, check=False):
            captured_cmds.append(cmd)
            if cmd.startswith("mkdir"):
                return _make_run_result()
            return _make_run_result(stdout="444\n")

        mock_conn.run = AsyncMock(side_effect=_capture)
        await runner.submit_job(
            1,
            input_file,
            tmp_path,
            config=SSHJobConfig(environment_setup="source /opt/CRYSTAL23/setup-crystal23.sh"),
        )
        assert "source /opt/CRYSTAL23/setup-crystal23.sh" in captured_cmds[-1]


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_running_when_pid_alive(self, runner, mock_conn):
        mock_conn.run = AsyncMock(return_value=_make_run_result(exit_status=0))
        status = await runner.get_status("ssh:1:999:/tmp/dft_jobs/1_x")
        assert status == JobStatus.RUNNING

    @pytest.mark.asyncio
    async def test_completed_when_dead_and_exit_code_zero(self, runner, mock_conn):
        mock_conn.run = AsyncMock(
            side_effect=[
                _make_run_result(exit_status=1),  # kill -0 fails: not alive
                _make_run_result(stdout="0\n"),  # EXIT_CODE contents
            ]
        )
        status = await runner.get_status("ssh:1:999:/tmp/dft_jobs/1_x")
        assert status == JobStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_failed_when_dead_and_exit_code_nonzero(self, runner, mock_conn):
        mock_conn.run = AsyncMock(
            side_effect=[
                _make_run_result(exit_status=1),
                _make_run_result(stdout="1\n"),
            ]
        )
        status = await runner.get_status("ssh:1:999:/tmp/dft_jobs/1_x")
        assert status == JobStatus.FAILED

    @pytest.mark.asyncio
    async def test_running_when_dead_but_exit_code_not_yet_written(self, runner, mock_conn):
        mock_conn.run = AsyncMock(
            side_effect=[
                _make_run_result(exit_status=1),
                _make_run_result(stdout=""),  # EXIT_CODE not there yet
            ]
        )
        status = await runner.get_status("ssh:1:999:/tmp/dft_jobs/1_x")
        assert status == JobStatus.RUNNING

    @pytest.mark.asyncio
    async def test_unknown_on_connection_error(self, runner, mock_connection_manager):
        class _RaisingCtx:
            async def __aenter__(self):
                raise ConnectionError("no route to host")

            async def __aexit__(self, *exc):
                return False

        mock_connection_manager.get_connection = MagicMock(return_value=_RaisingCtx())
        status = await runner.get_status("ssh:1:999:/tmp/dft_jobs/1_x")
        assert status == JobStatus.UNKNOWN


class TestCancelJob:
    @pytest.mark.asyncio
    async def test_cancel_returns_false_if_already_gone(self, runner, mock_conn):
        mock_conn.run = AsyncMock(return_value=_make_run_result(exit_status=1))
        result = await runner.cancel_job("ssh:1:999:/tmp/dft_jobs/1_x")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_escalates_to_sigkill_if_still_alive(self, runner, mock_conn):
        calls: list[str] = []

        async def _capture(cmd, check=False):
            calls.append(cmd)
            if cmd.startswith("kill -TERM"):
                return _make_run_result(exit_status=0)
            if cmd.startswith("kill -0"):
                return _make_run_result(exit_status=0)  # still alive after TERM
            return _make_run_result(exit_status=0)

        mock_conn.run = AsyncMock(side_effect=_capture)
        result = await runner.cancel_job("ssh:1:999:/tmp/dft_jobs/1_x")
        assert result is True
        assert any(c.startswith("kill -KILL") for c in calls)
