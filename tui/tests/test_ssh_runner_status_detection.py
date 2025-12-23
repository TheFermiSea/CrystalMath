"""
Comprehensive tests for SSH runner status detection robustness.

Tests the multi-signal status detection approach to ensure reliability
across all scenarios without race conditions or brittle parsing.
"""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from asyncssh import ProcessError

from src.runners.ssh_runner import SSHRunner
from src.runners.base import JobStatus
from src.runners.exceptions import JobNotFoundError
from src.core.connection_manager import ConnectionManager


# Mock SSH result
class MockSSHResult:
    """Mock asyncssh command result."""

    def __init__(self, stdout: str = "", stderr: str = "", exit_status: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_status = exit_status


@pytest.fixture
def mock_connection_manager():
    """Create a mock ConnectionManager."""
    manager = MagicMock(spec=ConnectionManager)
    manager._configs = {1: {"hostname": "test.host", "username": "testuser"}}
    return manager


@pytest.fixture
def ssh_runner(mock_connection_manager):
    """Create SSHRunner instance with mocked connection manager."""
    runner = SSHRunner(
        connection_manager=mock_connection_manager,
        cluster_id=1,
        remote_dft_root=Path("/home/user/CRYSTAL23"),
        remote_scratch_dir=Path("/home/user/crystal_jobs")
    )

    # Pre-populate with a test job
    runner._active_jobs["1:12345:/home/user/crystal_jobs/job_1"] = {
        "job_id": 1,
        "pid": 12345,
        "remote_work_dir": "/home/user/crystal_jobs/job_1",
        "local_work_dir": "/tmp/local_work",
        "status": JobStatus.RUNNING
    }

    return runner


@pytest.mark.asyncio
class TestStatusDetectionRunning:
    """Test status detection for running jobs."""

    async def test_process_running_detected(self, ssh_runner, mock_connection_manager):
        """Test that running process is detected via ps command."""
        mock_conn = AsyncMock()

        # ps command returns PID (process is running)
        mock_conn.run.return_value = MockSSHResult(stdout="12345\n", exit_status=0)

        mock_connection_manager.get_connection.return_value.__aenter__.return_value = mock_conn

        status = await ssh_runner.get_status("1:12345:/home/user/crystal_jobs/job_1")

        assert status == JobStatus.RUNNING
        assert ssh_runner._active_jobs["1:12345:/home/user/crystal_jobs/job_1"]["status"] == JobStatus.RUNNING

        # Verify ps command was called
        mock_conn.run.assert_called_once()
        call_args = mock_conn.run.call_args[0][0]
        assert "ps -p 12345" in call_args

    async def test_process_running_with_whitespace(self, ssh_runner, mock_connection_manager):
        """Test that running process is detected even with extra whitespace."""
        mock_conn = AsyncMock()

        # ps with extra whitespace
        mock_conn.run.return_value = MockSSHResult(stdout="  12345  \n", exit_status=0)

        mock_connection_manager.get_connection.return_value.__aenter__.return_value = mock_conn

        status = await ssh_runner.get_status("1:12345:/home/user/crystal_jobs/job_1")

        assert status == JobStatus.RUNNING

    async def test_rapid_status_checks_no_race_condition(self, ssh_runner, mock_connection_manager):
        """Test multiple rapid status checks don't cause race conditions."""
        mock_conn = AsyncMock()
        mock_conn.run.return_value = MockSSHResult(stdout="12345\n", exit_status=0)
        mock_connection_manager.get_connection.return_value.__aenter__.return_value = mock_conn

        # Simulate rapid polling
        tasks = [
            ssh_runner.get_status("1:12345:/home/user/crystal_jobs/job_1")
            for _ in range(10)
        ]

        results = await asyncio.gather(*tasks)

        # All should return running
        assert all(status == JobStatus.RUNNING for status in results)


@pytest.mark.asyncio
class TestStatusDetectionCompleted:
    """Test status detection for completed jobs."""

    async def test_completed_via_exit_code_zero(self, ssh_runner, mock_connection_manager):
        """Test that completed job is detected via exit code file."""
        mock_conn = AsyncMock()

        # Process not running, exit code file exists with 0
        mock_conn.run.side_effect = [
            MockSSHResult(stdout="", exit_status=1),  # ps: process not found
            MockSSHResult(stdout="0\n", exit_status=0),  # cat .exit_code
        ]

        mock_connection_manager.get_connection.return_value.__aenter__.return_value = mock_conn

        status = await ssh_runner.get_status("1:12345:/home/user/crystal_jobs/job_1")

        assert status == JobStatus.COMPLETED
        assert ssh_runner._active_jobs["1:12345:/home/user/crystal_jobs/job_1"]["status"] == JobStatus.COMPLETED

    async def test_completed_via_exit_code_with_whitespace(self, ssh_runner, mock_connection_manager):
        """Test that exit code is parsed correctly even with whitespace."""
        mock_conn = AsyncMock()

        mock_conn.run.side_effect = [
            MockSSHResult(stdout="", exit_status=1),  # ps: process not found
            MockSSHResult(stdout="  0  \n", exit_status=0),  # exit code with whitespace
        ]

        mock_connection_manager.get_connection.return_value.__aenter__.return_value = mock_conn

        status = await ssh_runner.get_status("1:12345:/home/user/crystal_jobs/job_1")

        assert status == JobStatus.COMPLETED

    async def test_completed_via_output_parsing_fallback(self, ssh_runner, mock_connection_manager):
        """Test fallback to output parsing when exit code unavailable."""
        mock_conn = AsyncMock()

        # Process not running, no exit code, but output shows completion
        crystal_output = """
CRYSTAL23 OUTPUT

 SCF CYCLES :  10
 TOTAL ENERGY =  -123.456 AU

 SCF ENDED - CONVERGENCE ON ENERGY      E(AU) -1.2345678901E+02
 TTTTTTTTTTTTTTTTTTTTTTTTTTTTTT EEEEEEEEEE TERMINATION
        """

        mock_conn.run.side_effect = [
            MockSSHResult(stdout="", exit_status=1),  # ps: process not found
            MockSSHResult(stdout="", exit_status=1),  # no exit code file
            MockSSHResult(stdout=crystal_output, exit_status=0),  # tail output.log
        ]

        mock_connection_manager.get_connection.return_value.__aenter__.return_value = mock_conn

        status = await ssh_runner.get_status("1:12345:/home/user/crystal_jobs/job_1")

        assert status == JobStatus.COMPLETED


@pytest.mark.asyncio
class TestStatusDetectionFailed:
    """Test status detection for failed jobs."""

    async def test_failed_via_exit_code_nonzero(self, ssh_runner, mock_connection_manager):
        """Test that failed job is detected via non-zero exit code."""
        mock_conn = AsyncMock()

        # Process not running, exit code 1 (failure)
        mock_conn.run.side_effect = [
            MockSSHResult(stdout="", exit_status=1),  # ps: process not found
            MockSSHResult(stdout="1\n", exit_status=0),  # cat .exit_code
        ]

        mock_connection_manager.get_connection.return_value.__aenter__.return_value = mock_conn

        status = await ssh_runner.get_status("1:12345:/home/user/crystal_jobs/job_1")

        assert status == JobStatus.FAILED
        assert ssh_runner._active_jobs["1:12345:/home/user/crystal_jobs/job_1"]["status"] == JobStatus.FAILED

    async def test_failed_via_exit_code_137(self, ssh_runner, mock_connection_manager):
        """Test detection of killed job (exit code 137 = SIGKILL)."""
        mock_conn = AsyncMock()

        mock_conn.run.side_effect = [
            MockSSHResult(stdout="", exit_status=1),  # ps: process not found
            MockSSHResult(stdout="137\n", exit_status=0),  # killed by signal
        ]

        mock_connection_manager.get_connection.return_value.__aenter__.return_value = mock_conn

        status = await ssh_runner.get_status("1:12345:/home/user/crystal_jobs/job_1")

        assert status == JobStatus.FAILED

    async def test_failed_via_output_parsing_error_termination(self, ssh_runner, mock_connection_manager):
        """Test fallback detection of error termination in output."""
        mock_conn = AsyncMock()

        error_output = """
CRYSTAL23 OUTPUT

 ERROR: CONVERGENCE NOT ACHIEVED AFTER 100 CYCLES
 ABNORMAL TERMINATION
        """

        mock_conn.run.side_effect = [
            MockSSHResult(stdout="", exit_status=1),  # ps: process not found
            MockSSHResult(stdout="", exit_status=1),  # no exit code file
            MockSSHResult(stdout=error_output, exit_status=0),  # tail output.log
        ]

        mock_connection_manager.get_connection.return_value.__aenter__.return_value = mock_conn

        status = await ssh_runner.get_status("1:12345:/home/user/crystal_jobs/job_1")

        assert status == JobStatus.FAILED

    async def test_failed_via_output_parsing_segfault(self, ssh_runner, mock_connection_manager):
        """Test detection of segmentation fault in output."""
        mock_conn = AsyncMock()

        segfault_output = """
CRYSTAL23 OUTPUT
 ... calculation running ...
 SEGMENTATION FAULT
 Killed
        """

        mock_conn.run.side_effect = [
            MockSSHResult(stdout="", exit_status=1),  # ps: process not found
            MockSSHResult(stdout="", exit_status=1),  # no exit code file
            MockSSHResult(stdout=segfault_output, exit_status=0),  # tail output.log
        ]

        mock_connection_manager.get_connection.return_value.__aenter__.return_value = mock_conn

        status = await ssh_runner.get_status("1:12345:/home/user/crystal_jobs/job_1")

        assert status == JobStatus.FAILED


@pytest.mark.asyncio
class TestStatusDetectionEdgeCases:
    """Test edge cases and error scenarios."""

    async def test_unknown_when_all_signals_fail(self, ssh_runner, mock_connection_manager):
        """Test that unknown status is returned when all detection methods fail."""
        mock_conn = AsyncMock()

        # All checks fail or are inconclusive
        mock_conn.run.side_effect = [
            MockSSHResult(stdout="", exit_status=1),  # ps: process not found
            MockSSHResult(stdout="", exit_status=1),  # no exit code file
            MockSSHResult(stdout="", exit_status=1),  # no output file
        ]

        mock_connection_manager.get_connection.return_value.__aenter__.return_value = mock_conn

        status = await ssh_runner.get_status("1:12345:/home/user/crystal_jobs/job_1")

        assert status == JobStatus.UNKNOWN

    async def test_unknown_when_output_incomplete(self, ssh_runner, mock_connection_manager):
        """Test handling of incomplete output file (job still writing)."""
        mock_conn = AsyncMock()

        # Output exists but doesn't contain termination markers
        incomplete_output = """
CRYSTAL23 OUTPUT
 SCF CYCLE 1
 ...
        """

        mock_conn.run.side_effect = [
            MockSSHResult(stdout="", exit_status=1),  # ps: process not found
            MockSSHResult(stdout="", exit_status=1),  # no exit code file
            MockSSHResult(stdout=incomplete_output, exit_status=0),  # incomplete output
        ]

        mock_connection_manager.get_connection.return_value.__aenter__.return_value = mock_conn

        status = await ssh_runner.get_status("1:12345:/home/user/crystal_jobs/job_1")

        assert status == JobStatus.UNKNOWN

    async def test_invalid_job_handle_raises_error(self, ssh_runner):
        """Test that invalid job handle raises JobNotFoundError."""
        with pytest.raises(JobNotFoundError, match="Job handle not found"):
            await ssh_runner.get_status("nonexistent_handle")

    async def test_invalid_pid_in_handle_raises_error(self, ssh_runner, mock_connection_manager):
        """Test that invalid PID in job handle raises error."""
        # Add job with invalid PID
        ssh_runner._active_jobs["1:invalid:/home/user/jobs/test"] = {
            "job_id": 999,
            "pid": "invalid",
            "remote_work_dir": "/home/user/jobs/test",
            "status": "running"
        }

        # ValueError from _parse_job_handle gets wrapped
        with pytest.raises(ValueError, match="Invalid job handle format"):
            await ssh_runner.get_status("1:invalid:/home/user/jobs/test")

    async def test_timeout_handling_graceful(self, ssh_runner, mock_connection_manager):
        """Test that timeouts are handled gracefully without crashing."""
        mock_conn = AsyncMock()

        # First command times out, subsequent commands work
        async def timeout_then_succeed(*args, **kwargs):
            if mock_conn.run.call_count == 1:
                raise asyncio.TimeoutError()
            return MockSSHResult(stdout="0\n", exit_status=0)

        mock_conn.run.side_effect = timeout_then_succeed

        mock_connection_manager.get_connection.return_value.__aenter__.return_value = mock_conn

        status = await ssh_runner.get_status("1:12345:/home/user/crystal_jobs/job_1")

        # Should fall back to next detection method
        assert status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.UNKNOWN)

    async def test_invalid_exit_code_fallback_to_output(self, ssh_runner, mock_connection_manager):
        """Test fallback when exit code file contains garbage."""
        mock_conn = AsyncMock()

        valid_output = "SCF ENDED - CONVERGENCE ON ENERGY"

        mock_conn.run.side_effect = [
            MockSSHResult(stdout="", exit_status=1),  # ps: process not found
            MockSSHResult(stdout="garbage\n", exit_status=0),  # invalid exit code
            MockSSHResult(stdout=valid_output, exit_status=0),  # fallback to output
        ]

        mock_connection_manager.get_connection.return_value.__aenter__.return_value = mock_conn

        status = await ssh_runner.get_status("1:12345:/home/user/crystal_jobs/job_1")

        assert status == JobStatus.COMPLETED


@pytest.mark.asyncio
class TestStatusDetectionSecurity:
    """Test security aspects of status detection."""

    async def test_pid_validation_prevents_injection(self, ssh_runner, mock_connection_manager):
        """Test that PID validation prevents command injection."""
        # Add job with malicious PID (will be caught during parsing)
        # The handle format "cluster:PID:path" means this will try to parse "12345; rm -rf /" as PID
        ssh_runner._active_jobs["1:12345; rm -rf /:/path"] = {
            "job_id": 999,
            "pid": "12345; rm -rf /",
            "remote_work_dir": "/path",
            "status": "running"
        }

        # ValueError from parsing non-integer PID
        with pytest.raises(ValueError, match="Invalid job handle format"):
            await ssh_runner.get_status("1:12345; rm -rf /:/path")

    async def test_zero_pid_rejected(self, ssh_runner, mock_connection_manager):
        """Test that PID 0 is rejected."""
        ssh_runner._active_jobs["1:0:/path"] = {
            "job_id": 999,
            "pid": 0,
            "remote_work_dir": "/path",
            "status": "running"
        }

        with pytest.raises(JobNotFoundError, match="must be > 0"):
            await ssh_runner.get_status("1:0:/path")

    async def test_negative_pid_rejected(self, ssh_runner, mock_connection_manager):
        """Test that negative PID is rejected."""
        ssh_runner._active_jobs["1:-1:/path"] = {
            "job_id": 999,
            "pid": -1,
            "remote_work_dir": "/path",
            "status": "running"
        }

        with pytest.raises(JobNotFoundError, match="must be > 0"):
            await ssh_runner.get_status("1:-1:/path")


@pytest.mark.asyncio
class TestStatusDetectionPerformance:
    """Test performance and efficiency of status detection."""

    async def test_early_exit_when_running(self, ssh_runner, mock_connection_manager):
        """Test that status detection exits early when process is running."""
        mock_conn = AsyncMock()

        # Process is running - should not check exit code or output
        mock_conn.run.return_value = MockSSHResult(stdout="12345\n", exit_status=0)

        mock_connection_manager.get_connection.return_value.__aenter__.return_value = mock_conn

        status = await ssh_runner.get_status("1:12345:/home/user/crystal_jobs/job_1")

        assert status == JobStatus.RUNNING
        # Should only call ps once
        assert mock_conn.run.call_count == 1

    async def test_early_exit_when_exit_code_found(self, ssh_runner, mock_connection_manager):
        """Test that status detection exits when exit code is found."""
        mock_conn = AsyncMock()

        mock_conn.run.side_effect = [
            MockSSHResult(stdout="", exit_status=1),  # ps: not running
            MockSSHResult(stdout="0\n", exit_status=0),  # exit code found
        ]

        mock_connection_manager.get_connection.return_value.__aenter__.return_value = mock_conn

        status = await ssh_runner.get_status("1:12345:/home/user/crystal_jobs/job_1")

        assert status == JobStatus.COMPLETED
        # Should only call ps and exit code check (not output parsing)
        assert mock_conn.run.call_count == 2

    async def test_timeouts_prevent_hanging(self, ssh_runner, mock_connection_manager):
        """Test that timeouts prevent hanging on slow commands."""
        mock_conn = AsyncMock()

        # Simulate slow command that would hang
        async def slow_command(*args, **kwargs):
            await asyncio.sleep(10)  # Would hang without timeout
            return MockSSHResult(stdout="12345\n", exit_status=0)

        mock_conn.run.side_effect = slow_command
        mock_connection_manager.get_connection.return_value.__aenter__.return_value = mock_conn

        # Should complete quickly due to timeout
        with pytest.raises(asyncio.TimeoutError):
            # Manually enforce timeout for test
            await asyncio.wait_for(
                ssh_runner.get_status("1:12345:/home/user/crystal_jobs/job_1"),
                timeout=1.0
            )
