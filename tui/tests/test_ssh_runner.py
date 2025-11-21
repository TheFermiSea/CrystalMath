"""
Unit tests for SSHRunner.

Tests cover:
- Job submission and file transfer
- Remote process monitoring
- Output streaming
- Result retrieval
- Error handling
- Connection management
"""

import pytest
import pytest_asyncio
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import tempfile
import shutil

# Import the classes we're testing
from src.runners.ssh_runner import SSHRunner
from src.runners.base import JobStatus, JobResult, JobSubmissionError, JobNotFoundError
from src.core.connection_manager import ConnectionManager


@pytest.fixture
def temp_work_dir():
    """Create a temporary working directory with test input file."""
    temp_dir = Path(tempfile.mkdtemp())

    # Create a test input file
    input_file = temp_dir / "input.d12"
    input_file.write_text("""
CRYSTAL
0 0 0
2
1.0 1.0
2
8 0.7
""")

    yield temp_dir

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mock_connection_manager():
    """Create a mocked ConnectionManager."""
    manager = Mock(spec=ConnectionManager)
    manager._configs = {1: Mock()}  # Cluster 1 is registered
    return manager


@pytest.fixture
def mock_ssh_connection():
    """Create a mocked SSH connection."""
    conn = AsyncMock()

    # Mock run command
    async def mock_run(cmd, check=False):
        result = Mock()
        result.stdout = ""
        result.stderr = ""
        result.exit_status = 0

        # Simulate different commands
        if "mkdir" in cmd:
            result.stdout = ""
        elif "echo $!" in cmd:
            result.stdout = "12345\n"  # PID
        elif "ps -p" in cmd:
            result.stdout = "running\n"
        elif "test -f" in cmd:
            result.stdout = "exists\n"
        elif "grep" in cmd:
            result.stdout = "completed\n"
        elif "echo alive" in cmd:
            result.stdout = ""
            result.exit_status = 0

        return result

    conn.run = mock_run

    # Mock SFTP client
    sftp_mock = AsyncMock()
    sftp_mock.put = AsyncMock()
    sftp_mock.get = AsyncMock()
    sftp_mock.listdir = AsyncMock(return_value=["output.log", "fort.9"])
    sftp_mock.open = AsyncMock()

    conn.start_sftp_client = AsyncMock(return_value=sftp_mock)
    conn.create_process = AsyncMock()

    return conn


@pytest_asyncio.fixture
async def ssh_runner(mock_connection_manager, mock_ssh_connection):
    """Create an SSHRunner instance with mocked connection."""
    # Create async context manager using contextlib
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_get_connection(cluster_id):
        yield mock_ssh_connection

    # Setup connection manager to return mocked connection
    mock_connection_manager.get_connection = mock_get_connection

    runner = SSHRunner(
        connection_manager=mock_connection_manager,
        cluster_id=1,
        remote_crystal_root=Path("/home/user/CRYSTAL23"),
        remote_scratch_dir=Path("/home/user/crystal_jobs"),
        cleanup_on_success=False
    )

    return runner


class TestSSHRunnerInitialization:
    """Test SSHRunner initialization and configuration."""

    def test_init_with_valid_cluster(self, mock_connection_manager):
        """Test initialization with valid cluster configuration."""
        runner = SSHRunner(
            connection_manager=mock_connection_manager,
            cluster_id=1
        )

        assert runner.cluster_id == 1
        assert runner.connection_manager is mock_connection_manager
        assert isinstance(runner.remote_crystal_root, Path)
        assert isinstance(runner.remote_scratch_dir, Path)

    def test_init_with_invalid_cluster(self, mock_connection_manager):
        """Test initialization with unregistered cluster."""
        mock_connection_manager._configs = {}  # No clusters registered

        with pytest.raises(ValueError, match="not registered"):
            SSHRunner(
                connection_manager=mock_connection_manager,
                cluster_id=999
            )

    def test_init_with_custom_paths(self, mock_connection_manager):
        """Test initialization with custom paths."""
        custom_root = Path("/opt/crystal")
        custom_scratch = Path("/scratch/user")

        runner = SSHRunner(
            connection_manager=mock_connection_manager,
            cluster_id=1,
            remote_crystal_root=custom_root,
            remote_scratch_dir=custom_scratch
        )

        assert runner.remote_crystal_root == custom_root
        assert runner.remote_scratch_dir == custom_scratch


class TestJobSubmission:
    """Test job submission and file transfer."""

    @pytest.mark.asyncio
    async def test_submit_job_success(self, ssh_runner, temp_work_dir):
        """Test successful job submission."""
        input_file = temp_work_dir / "input.d12"

        job_handle = await ssh_runner.submit_job(
            job_id=1,
            work_dir=temp_work_dir,
            input_file=input_file,
            threads=4
        )

        # Verify job handle format: "cluster_id:PID:remote_work_dir"
        assert job_handle.startswith("1:")  # cluster_id
        assert ":12345:" in job_handle  # PID

        # Verify job is tracked
        assert job_handle in ssh_runner._active_jobs
        assert ssh_runner._active_jobs[job_handle]["job_id"] == 1
        assert ssh_runner._active_jobs[job_handle]["pid"] == 12345

    @pytest.mark.asyncio
    async def test_submit_job_missing_input(self, ssh_runner, temp_work_dir):
        """Test job submission with missing input file."""
        nonexistent = temp_work_dir / "nonexistent.d12"

        with pytest.raises(FileNotFoundError):
            await ssh_runner.submit_job(
                job_id=1,
                work_dir=temp_work_dir,
                input_file=nonexistent
            )

    @pytest.mark.asyncio
    async def test_submit_job_with_mpi(self, ssh_runner, temp_work_dir):
        """Test job submission with MPI configuration."""
        input_file = temp_work_dir / "input.d12"

        job_handle = await ssh_runner.submit_job(
            job_id=1,
            work_dir=temp_work_dir,
            input_file=input_file,
            threads=2,
            mpi_ranks=4
        )

        assert job_handle is not None
        # Verify MPI configuration is in execution script
        # (would check script content in integration test)

    @pytest.mark.asyncio
    async def test_file_upload(self, ssh_runner, temp_work_dir, mock_ssh_connection):
        """Test file upload via SFTP."""
        input_file = temp_work_dir / "input.d12"

        # Create additional test files
        (temp_work_dir / "test.gui").write_text("geometry data")
        (temp_work_dir / "test.f9").write_text("wave function")

        await ssh_runner.submit_job(
            job_id=1,
            work_dir=temp_work_dir,
            input_file=input_file
        )

        # Verify SFTP client was used for file transfer
        assert mock_ssh_connection.start_sftp_client.called


class TestJobStatus:
    """Test job status monitoring."""

    @pytest.mark.asyncio
    async def test_get_status_running(self, ssh_runner, temp_work_dir):
        """Test status check for running job."""
        input_file = temp_work_dir / "input.d12"
        job_handle = await ssh_runner.submit_job(
            job_id=1,
            work_dir=temp_work_dir,
            input_file=input_file
        )

        status = await ssh_runner.get_status(job_handle)
        assert status == "running"

    @pytest.mark.asyncio
    async def test_get_status_completed(self, ssh_runner, temp_work_dir, mock_ssh_connection):
        """Test status check for completed job."""
        # Modify mock to return "stopped" for ps check
        async def mock_run_completed(cmd, check=False):
            result = Mock()
            result.stdout = ""
            result.exit_status = 0

            if "ps -p" in cmd:
                result.stdout = "stopped\n"
            elif "test -f" in cmd:
                result.stdout = "exists\n"
            elif "grep" in cmd:
                result.stdout = "completed\n"
            else:
                result.stdout = "12345\n"

            return result

        mock_ssh_connection.run = mock_run_completed

        input_file = temp_work_dir / "input.d12"
        job_handle = await ssh_runner.submit_job(
            job_id=1,
            work_dir=temp_work_dir,
            input_file=input_file
        )

        status = await ssh_runner.get_status(job_handle)
        assert status == "completed"

    @pytest.mark.asyncio
    async def test_get_status_failed(self, ssh_runner, temp_work_dir, mock_ssh_connection):
        """Test status check for failed job."""
        async def mock_run_failed(cmd, check=False):
            result = Mock()
            result.stdout = ""
            result.exit_status = 0

            if "ps -p" in cmd:
                result.stdout = "stopped\n"
            elif "test -f" in cmd:
                result.stdout = "exists\n"
            elif "grep" in cmd:
                result.stdout = "failed\n"  # Error detected
            else:
                result.stdout = "12345\n"

            return result

        mock_ssh_connection.run = mock_run_failed

        input_file = temp_work_dir / "input.d12"
        job_handle = await ssh_runner.submit_job(
            job_id=1,
            work_dir=temp_work_dir,
            input_file=input_file
        )

        status = await ssh_runner.get_status(job_handle)
        assert status == "failed"

    @pytest.mark.asyncio
    async def test_get_status_invalid_handle(self, ssh_runner):
        """Test status check with invalid job handle."""
        with pytest.raises(JobNotFoundError):
            await ssh_runner.get_status("invalid:handle:path")


class TestJobCancellation:
    """Test job cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_running_job(self, ssh_runner, temp_work_dir):
        """Test cancelling a running job."""
        input_file = temp_work_dir / "input.d12"
        job_handle = await ssh_runner.submit_job(
            job_id=1,
            work_dir=temp_work_dir,
            input_file=input_file
        )

        success = await ssh_runner.cancel_job(job_handle)
        assert success is True

        # Verify status updated
        job_info = ssh_runner._active_jobs[job_handle]
        assert job_info["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_job(self, ssh_runner):
        """Test cancelling non-existent job."""
        with pytest.raises(JobNotFoundError):
            await ssh_runner.cancel_job("1:99999:/tmp/fake")

    @pytest.mark.asyncio
    async def test_cancel_already_stopped(self, ssh_runner, temp_work_dir, mock_ssh_connection):
        """Test cancelling already stopped job."""
        async def mock_run_stopped(cmd, check=False):
            result = Mock()
            result.exit_status = 0

            if "ps -p" in cmd:
                result.stdout = ""  # Not running
            else:
                result.stdout = "12345\n"

            return result

        mock_ssh_connection.run = mock_run_stopped

        input_file = temp_work_dir / "input.d12"
        job_handle = await ssh_runner.submit_job(
            job_id=1,
            work_dir=temp_work_dir,
            input_file=input_file
        )

        success = await ssh_runner.cancel_job(job_handle)
        assert success is False


class TestOutputStreaming:
    """Test output streaming."""

    @pytest.mark.asyncio
    async def test_stream_output(self, ssh_runner, temp_work_dir, mock_ssh_connection):
        """Test streaming job output."""
        # Mock process with stdout
        mock_process = AsyncMock()
        mock_stdout = AsyncMock()

        async def mock_stdout_lines():
            lines = [
                "CRYSTAL23 starting...",
                "SCF iteration 1",
                "SCF iteration 2",
                "Convergence reached"
            ]
            for line in lines:
                yield line

        mock_stdout.__aiter__ = mock_stdout_lines
        mock_process.stdout = mock_stdout
        mock_ssh_connection.create_process = AsyncMock(
            return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_process))
        )

        # Modify get_status to return completed after some lines
        call_count = 0
        async def mock_get_status(handle):
            nonlocal call_count
            call_count += 1
            return "completed" if call_count > 2 else "running"

        ssh_runner.get_status = mock_get_status

        input_file = temp_work_dir / "input.d12"
        job_handle = await ssh_runner.submit_job(
            job_id=1,
            work_dir=temp_work_dir,
            input_file=input_file
        )

        # Stream output
        output_lines = []
        async for line in ssh_runner.get_output(job_handle):
            output_lines.append(line)
            if len(output_lines) >= 4:
                break

        assert len(output_lines) > 0

    @pytest.mark.asyncio
    async def test_stream_output_no_file(self, ssh_runner, temp_work_dir, mock_ssh_connection):
        """Test streaming when output file doesn't exist."""
        # Mock file check to always fail
        async def mock_run_no_file(cmd, check=False):
            result = Mock()
            result.stdout = ""
            result.exit_status = 0

            if "test -f" in cmd:
                result.stdout = ""  # File doesn't exist
            elif "echo $!" in cmd:
                result.stdout = "12345\n"

            return result

        mock_ssh_connection.run = mock_run_no_file

        input_file = temp_work_dir / "input.d12"
        job_handle = await ssh_runner.submit_job(
            job_id=1,
            work_dir=temp_work_dir,
            input_file=input_file
        )

        # Try to stream output
        output_lines = []
        async for line in ssh_runner.get_output(job_handle):
            output_lines.append(line)

        # Should get warning message
        assert len(output_lines) > 0
        assert "Output file not created" in output_lines[0]


class TestResultRetrieval:
    """Test result retrieval and parsing."""

    @pytest.mark.asyncio
    async def test_retrieve_results_success(self, ssh_runner, temp_work_dir, mock_ssh_connection):
        """Test successful result retrieval."""
        # Setup: job is completed
        async def mock_run_completed(cmd, check=False):
            result = Mock()
            result.exit_status = 0

            if "ps -p" in cmd:
                result.stdout = "stopped\n"
            elif "test -f" in cmd:
                result.stdout = "exists\n"
            elif "grep" in cmd:
                result.stdout = "completed\n"
            else:
                result.stdout = "12345\n"

            return result

        mock_ssh_connection.run = mock_run_completed

        # Create output file locally (simulating download)
        output_file = temp_work_dir / "output.log"
        output_file.write_text("""
CRYSTAL23 OUTPUT
TOTAL ENERGY(DFT)(AU) -123.456789
CONVERGENCE REACHED
""")

        input_file = temp_work_dir / "input.d12"
        job_handle = await ssh_runner.submit_job(
            job_id=1,
            work_dir=temp_work_dir,
            input_file=input_file
        )

        result = await ssh_runner.retrieve_results(job_handle, temp_work_dir)

        assert isinstance(result, JobResult)
        # Note: Actual parsing depends on CRYSTALpytools availability

    @pytest.mark.asyncio
    async def test_retrieve_results_still_running(self, ssh_runner, temp_work_dir):
        """Test retrieving results while job is still running."""
        input_file = temp_work_dir / "input.d12"
        job_handle = await ssh_runner.submit_job(
            job_id=1,
            work_dir=temp_work_dir,
            input_file=input_file
        )

        # Job is still running
        with pytest.raises(ValueError, match="still running"):
            await ssh_runner.retrieve_results(job_handle, temp_work_dir)


class TestUtilityMethods:
    """Test utility methods."""

    def test_parse_job_handle(self, ssh_runner):
        """Test job handle parsing."""
        handle = "1:12345:/home/user/crystal_jobs/job_1_20231120"

        cluster_id, pid, remote_dir = ssh_runner._parse_job_handle(handle)

        assert cluster_id == 1
        assert pid == 12345
        assert remote_dir == "/home/user/crystal_jobs/job_1_20231120"

    def test_parse_invalid_job_handle(self, ssh_runner):
        """Test parsing invalid job handle."""
        with pytest.raises(ValueError, match="Invalid job handle"):
            ssh_runner._parse_job_handle("invalid")

    def test_is_job_running(self, ssh_runner):
        """Test is_job_running check."""
        # Add a fake job
        ssh_runner._active_jobs["1:12345:/tmp"] = {
            "status": "running",
            "pid": 12345
        }

        assert ssh_runner.is_job_running("1:12345:/tmp") is True
        assert ssh_runner.is_job_running("1:99999:/tmp") is False

    def test_get_job_pid(self, ssh_runner):
        """Test PID retrieval."""
        ssh_runner._active_jobs["1:12345:/tmp"] = {
            "pid": 12345
        }

        assert ssh_runner.get_job_pid("1:12345:/tmp") == 12345
        assert ssh_runner.get_job_pid("invalid") is None

    def test_generate_execution_script_serial(self, ssh_runner):
        """Test execution script generation for serial job."""
        script = ssh_runner._generate_execution_script(
            remote_work_dir=Path("/home/user/job"),
            input_file="input.d12",
            threads=8
        )

        assert "crystalOMP" in script
        assert "OMP_NUM_THREADS=8" in script
        assert "input.d12" in script

    def test_generate_execution_script_mpi(self, ssh_runner):
        """Test execution script generation for MPI job."""
        script = ssh_runner._generate_execution_script(
            remote_work_dir=Path("/home/user/job"),
            input_file="input.d12",
            threads=4,
            mpi_ranks=8
        )

        assert "Pcrystal" in script
        assert "mpirun -np 8" in script
        assert "OMP_NUM_THREADS=4" in script


class TestCleanup:
    """Test cleanup operations."""

    @pytest.mark.asyncio
    async def test_cleanup_without_removing_files(self, ssh_runner, temp_work_dir):
        """Test cleanup without removing remote files."""
        input_file = temp_work_dir / "input.d12"
        job_handle = await ssh_runner.submit_job(
            job_id=1,
            work_dir=temp_work_dir,
            input_file=input_file
        )

        await ssh_runner.cleanup(job_handle, remove_files=False)

        # Verify job removed from tracking
        assert job_handle not in ssh_runner._active_jobs

    @pytest.mark.asyncio
    async def test_cleanup_with_removing_files(self, ssh_runner, temp_work_dir, mock_ssh_connection):
        """Test cleanup with remote file removal."""
        input_file = temp_work_dir / "input.d12"
        job_handle = await ssh_runner.submit_job(
            job_id=1,
            work_dir=temp_work_dir,
            input_file=input_file
        )

        await ssh_runner.cleanup(job_handle, remove_files=True)

        # Verify job removed
        assert job_handle not in ssh_runner._active_jobs

        # Verify rm command was called (check mock calls)
        # Would need to track mock_ssh_connection.run calls

    @pytest.mark.asyncio
    async def test_cleanup_invalid_handle(self, ssh_runner):
        """Test cleanup with invalid job handle."""
        with pytest.raises(JobNotFoundError):
            await ssh_runner.cleanup("invalid:handle:path")


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_connection_failure_on_submit(self, mock_connection_manager, temp_work_dir):
        """Test handling connection failure during submission."""
        # Make connection fail
        async def failing_connection(*args, **kwargs):
            raise Exception("Connection failed")

        mock_connection_manager.get_connection = AsyncMock(side_effect=failing_connection)

        runner = SSHRunner(
            connection_manager=mock_connection_manager,
            cluster_id=1
        )

        input_file = temp_work_dir / "input.d12"

        with pytest.raises(JobSubmissionError):
            await runner.submit_job(
                job_id=1,
                work_dir=temp_work_dir,
                input_file=input_file
            )

    @pytest.mark.asyncio
    async def test_parse_results_missing_file(self, ssh_runner, temp_work_dir, mock_ssh_connection):
        """Test result parsing with missing output file."""
        # Submit and complete job
        async def mock_run_completed(cmd, check=False):
            result = Mock()
            result.stdout = "stopped\n" if "ps -p" in cmd else "12345\n"
            result.exit_status = 0
            return result

        mock_ssh_connection.run = mock_run_completed

        input_file = temp_work_dir / "input.d12"
        job_handle = await ssh_runner.submit_job(
            job_id=1,
            work_dir=temp_work_dir,
            input_file=input_file
        )

        # Don't create output file
        result = await ssh_runner.retrieve_results(job_handle, temp_work_dir)

        assert result.success is False
        assert "not found" in result.errors[0].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
