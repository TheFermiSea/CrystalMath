"""
Unit tests for SLURM Runner.

Tests cover:
- SLURM script generation
- Job submission and ID parsing
- Status monitoring and parsing
- Job cancellation
- Result downloading
- Error handling
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, MagicMock, patch, mock_open
from dataclasses import dataclass

# Import the modules to test
from src.runners.slurm_runner import (
    SLURMRunner,
    SLURMJobConfig,
    SLURMJobState,
    SLURMSubmissionError,
    SLURMStatusError,
)
from src.core.connection_manager import ConnectionManager


@pytest.fixture
def mock_connection_manager():
    """Create a mock ConnectionManager."""
    manager = Mock(spec=ConnectionManager)
    manager.cluster_id = 1
    return manager


@pytest.fixture
def mock_connection():
    """Create a mock SSH connection."""
    conn = AsyncMock()
    conn.run = AsyncMock()
    conn.start_sftp_client = AsyncMock()
    return conn


@pytest.fixture
def slurm_runner(mock_connection_manager):
    """Create a SLURMRunner instance with mocked dependencies."""
    runner = SLURMRunner(
        connection_manager=mock_connection_manager,
        cluster_id=1,
        poll_interval=0.1  # Fast polling for tests
    )
    return runner


@pytest.fixture
def temp_work_dir(tmp_path):
    """Create a temporary work directory with input file."""
    work_dir = tmp_path / "test_job"
    work_dir.mkdir()

    # Create input file
    input_file = work_dir / "input.d12"
    input_file.write_text("CRYSTAL\nEND\n")

    return work_dir


class TestSLURMScriptGeneration:
    """Test SLURM script generation."""

    def test_basic_script_generation(self, slurm_runner):
        """Test generation of basic SLURM script."""
        config = SLURMJobConfig(
            job_name="test_job",
            nodes=1,
            ntasks=1,
            cpus_per_task=4,
            time_limit="01:00:00"
        )

        script = slurm_runner._generate_slurm_script(config, "/scratch/test")

        # Check required directives
        assert "#SBATCH --job-name=test_job" in script
        assert "#SBATCH --nodes=1" in script
        assert "#SBATCH --ntasks=1" in script
        assert "#SBATCH --cpus-per-task=4" in script
        assert "#SBATCH --time=01:00:00" in script

        # Check output files
        assert "#SBATCH --output=slurm-%j.out" in script
        assert "#SBATCH --error=slurm-%j.err" in script

        # Check environment setup
        assert "module load crystal23" in script
        assert "export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK" in script

        # Check execution command
        assert "cd /scratch/test" in script
        assert "crystalOMP < input.d12 > output.out 2>&1" in script

    def test_script_with_optional_parameters(self, slurm_runner):
        """Test script generation with optional SLURM parameters."""
        config = SLURMJobConfig(
            job_name="test_job",
            nodes=2,
            ntasks=28,
            cpus_per_task=2,
            time_limit="24:00:00",
            partition="compute",
            memory="64GB",
            account="myproject",
            qos="high",
            email="user@example.com",
            email_type="BEGIN,END,FAIL",
            constraint="haswell"
        )

        script = slurm_runner._generate_slurm_script(config, "/scratch/test")

        # Check optional directives
        assert "#SBATCH --partition=compute" in script
        assert "#SBATCH --mem=64GB" in script
        assert "#SBATCH --account=myproject" in script
        assert "#SBATCH --qos=high" in script
        assert "#SBATCH --mail-user=user@example.com" in script
        assert "#SBATCH --mail-type=BEGIN,END,FAIL" in script
        assert "#SBATCH --constraint=haswell" in script

    def test_script_with_mpi_execution(self, slurm_runner):
        """Test script generation for MPI parallel execution."""
        config = SLURMJobConfig(
            job_name="mpi_job",
            nodes=2,
            ntasks=28,  # More than 1 ntask triggers MPI
            cpus_per_task=2
        )

        script = slurm_runner._generate_slurm_script(config, "/scratch/test")

        # Should use srun for MPI
        assert "srun PcrystalOMP < input.d12 > output.out 2>&1" in script

    def test_script_with_job_array(self, slurm_runner):
        """Test script generation with job array."""
        config = SLURMJobConfig(
            job_name="array_job",
            array="1-10"
        )

        script = slurm_runner._generate_slurm_script(config, "/scratch/test")

        assert "#SBATCH --array=1-10" in script

    def test_script_with_dependencies(self, slurm_runner):
        """Test script generation with job dependencies."""
        config = SLURMJobConfig(
            job_name="dependent_job",
            dependencies=["12345", "12346"]
        )

        script = slurm_runner._generate_slurm_script(config, "/scratch/test")

        assert "#SBATCH --dependency=afterok:12345:12346" in script

    def test_script_with_custom_modules(self, slurm_runner):
        """Test script generation with custom modules."""
        config = SLURMJobConfig(
            job_name="test_job",
            modules=["intel/2023", "crystal23", "openmpi/4.1"]
        )

        script = slurm_runner._generate_slurm_script(config, "/scratch/test")

        assert "module load intel/2023" in script
        assert "module load crystal23" in script
        assert "module load openmpi/4.1" in script

    def test_script_with_environment_setup(self, slurm_runner):
        """Test script generation with custom environment setup."""
        config = SLURMJobConfig(
            job_name="test_job",
            environment_setup="source /opt/crystal/env.sh\nexport MY_VAR=value"
        )

        script = slurm_runner._generate_slurm_script(config, "/scratch/test")

        assert "source /opt/crystal/env.sh" in script
        assert "export MY_VAR=value" in script


class TestJobIDParsing:
    """Test parsing of SLURM job IDs from sbatch output."""

    def test_parse_valid_job_id(self, slurm_runner):
        """Test parsing valid sbatch output."""
        output = "Submitted batch job 123456\n"
        job_id = slurm_runner._parse_job_id(output)
        assert job_id == "123456"

    def test_parse_job_id_with_extra_text(self, slurm_runner):
        """Test parsing with additional text."""
        output = "Some warning message\nSubmitted batch job 789012\n"
        job_id = slurm_runner._parse_job_id(output)
        assert job_id == "789012"

    def test_parse_invalid_output(self, slurm_runner):
        """Test parsing invalid output returns None."""
        output = "Error: Unable to submit job\n"
        job_id = slurm_runner._parse_job_id(output)
        assert job_id is None


class TestStatusParsing:
    """Test parsing of SLURM job states."""

    def test_parse_pending_state(self, slurm_runner):
        """Test parsing PENDING state."""
        assert slurm_runner._parse_state("PENDING") == SLURMJobState.PENDING
        assert slurm_runner._parse_state("PD") == SLURMJobState.PENDING

    def test_parse_running_state(self, slurm_runner):
        """Test parsing RUNNING state."""
        assert slurm_runner._parse_state("RUNNING") == SLURMJobState.RUNNING
        assert slurm_runner._parse_state("R") == SLURMJobState.RUNNING

    def test_parse_completed_state(self, slurm_runner):
        """Test parsing COMPLETED state."""
        assert slurm_runner._parse_state("COMPLETED") == SLURMJobState.COMPLETED
        assert slurm_runner._parse_state("CD") == SLURMJobState.COMPLETED

    def test_parse_failed_state(self, slurm_runner):
        """Test parsing FAILED state."""
        assert slurm_runner._parse_state("FAILED") == SLURMJobState.FAILED
        assert slurm_runner._parse_state("F") == SLURMJobState.FAILED

    def test_parse_cancelled_state(self, slurm_runner):
        """Test parsing CANCELLED state."""
        assert slurm_runner._parse_state("CANCELLED") == SLURMJobState.CANCELLED
        assert slurm_runner._parse_state("CA") == SLURMJobState.CANCELLED

    def test_parse_timeout_state(self, slurm_runner):
        """Test parsing TIMEOUT state."""
        assert slurm_runner._parse_state("TIMEOUT") == SLURMJobState.TIMEOUT
        assert slurm_runner._parse_state("TO") == SLURMJobState.TIMEOUT

    def test_parse_out_of_memory_state(self, slurm_runner):
        """Test parsing OUT_OF_MEMORY state."""
        assert slurm_runner._parse_state("OUT_OF_MEMORY") == SLURMJobState.OUT_OF_MEMORY
        assert slurm_runner._parse_state("OOM") == SLURMJobState.OUT_OF_MEMORY

    def test_parse_unknown_state(self, slurm_runner):
        """Test parsing unknown state."""
        assert slurm_runner._parse_state("WEIRD_STATE") == SLURMJobState.UNKNOWN


class TestJobSubmission:
    """Test job submission functionality."""

    @pytest.mark.asyncio
    async def test_successful_job_submission(
        self,
        slurm_runner,
        temp_work_dir,
        mock_connection_manager,
        mock_connection
    ):
        """Test successful job submission flow."""
        # Setup mocks
        mock_connection_manager.get_connection = AsyncMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_connection),
                __aexit__=AsyncMock()
            )
        )

        # Mock sbatch output
        mock_connection.run.return_value = Mock(
            exit_status=0,
            stdout="Submitted batch job 12345\n",
            stderr=""
        )

        # Mock SFTP for file transfer
        mock_sftp = AsyncMock()
        mock_sftp.put = AsyncMock()
        mock_connection.start_sftp_client.return_value = AsyncMock(
            __aenter__=AsyncMock(return_value=mock_sftp),
            __aexit__=AsyncMock()
        )

        # Mock status checks (immediate completion)
        async def mock_status_check(*args, **kwargs):
            if "squeue" in args[0]:
                # Job not in queue (completed)
                return Mock(exit_status=1, stdout="", stderr="")
            elif "sacct" in args[0]:
                # Job completed
                return Mock(exit_status=0, stdout="COMPLETED\n", stderr="")
            return Mock(exit_status=0, stdout="", stderr="")

        mock_connection.run.side_effect = [
            Mock(exit_status=0, stdout="", stderr=""),  # mkdir
            Mock(exit_status=0, stdout="Submitted batch job 12345\n", stderr=""),  # sbatch
            Mock(exit_status=1, stdout="", stderr=""),  # squeue (not found)
            Mock(exit_status=0, stdout="COMPLETED\n", stderr=""),  # sacct
        ]

        # Mock listdir for results download
        mock_sftp.listdir.return_value = ["output.out", "input.d12", "slurm-12345.out"]
        mock_sftp.get = AsyncMock()

        # Run job
        output_lines = []
        async for line in slurm_runner.run_job(1, temp_work_dir):
            output_lines.append(line)

        # Verify job was submitted
        assert slurm_runner.get_slurm_job_id(1) == "12345"
        assert "Job submitted successfully" in "\n".join(output_lines)
        assert "SLURM Job ID: 12345" in "\n".join(output_lines)

    @pytest.mark.asyncio
    async def test_submission_with_missing_input(self, slurm_runner, tmp_path):
        """Test submission fails with missing input file."""
        work_dir = tmp_path / "empty"
        work_dir.mkdir()

        with pytest.raises(SLURMSubmissionError, match="Input file not found"):
            async for line in slurm_runner.run_job(1, work_dir):
                pass

    @pytest.mark.asyncio
    async def test_submission_failure(
        self,
        slurm_runner,
        temp_work_dir,
        mock_connection_manager,
        mock_connection
    ):
        """Test handling of sbatch submission failure."""
        # Setup mocks
        mock_connection_manager.get_connection = AsyncMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_connection),
                __aexit__=AsyncMock()
            )
        )

        # Mock sbatch failure
        mock_connection.run.return_value = Mock(
            exit_status=1,
            stdout="",
            stderr="sbatch: error: Invalid partition name specified\n"
        )

        # Mock SFTP
        mock_sftp = AsyncMock()
        mock_connection.start_sftp_client.return_value = AsyncMock(
            __aenter__=AsyncMock(return_value=mock_sftp),
            __aexit__=AsyncMock()
        )

        # Run job and expect error
        with pytest.raises(SLURMSubmissionError, match="sbatch failed"):
            async for line in slurm_runner.run_job(1, temp_work_dir):
                pass


class TestJobCancellation:
    """Test job cancellation functionality."""

    @pytest.mark.asyncio
    async def test_cancel_running_job(
        self,
        slurm_runner,
        mock_connection_manager,
        mock_connection
    ):
        """Test cancelling a running job."""
        # Setup mocks
        mock_connection_manager.get_connection = AsyncMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_connection),
                __aexit__=AsyncMock()
            )
        )

        # Mock successful cancellation
        mock_connection.run.return_value = Mock(exit_status=0, stdout="", stderr="")

        # Register job
        slurm_runner._slurm_job_ids[1] = "12345"
        slurm_runner._job_states[1] = SLURMJobState.RUNNING

        # Cancel job
        result = await slurm_runner.stop_job(1)

        assert result is True
        assert slurm_runner._job_states[1] == SLURMJobState.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_job(self, slurm_runner):
        """Test cancelling job that doesn't exist."""
        result = await slurm_runner.stop_job(999)
        assert result is False


class TestJobStateTracking:
    """Test job state tracking functionality."""

    def test_is_job_running_pending(self, slurm_runner):
        """Test is_job_running for pending job."""
        slurm_runner._job_states[1] = SLURMJobState.PENDING
        assert slurm_runner.is_job_running(1) is True

    def test_is_job_running_active(self, slurm_runner):
        """Test is_job_running for running job."""
        slurm_runner._job_states[1] = SLURMJobState.RUNNING
        assert slurm_runner.is_job_running(1) is True

    def test_is_job_running_completed(self, slurm_runner):
        """Test is_job_running for completed job."""
        slurm_runner._job_states[1] = SLURMJobState.COMPLETED
        assert slurm_runner.is_job_running(1) is False

    def test_is_job_running_failed(self, slurm_runner):
        """Test is_job_running for failed job."""
        slurm_runner._job_states[1] = SLURMJobState.FAILED
        assert slurm_runner.is_job_running(1) is False

    def test_get_slurm_job_id(self, slurm_runner):
        """Test retrieving SLURM job ID."""
        slurm_runner._slurm_job_ids[1] = "12345"
        assert slurm_runner.get_slurm_job_id(1) == "12345"
        assert slurm_runner.get_slurm_job_id(999) is None

    def test_get_job_state(self, slurm_runner):
        """Test retrieving job state."""
        slurm_runner._job_states[1] = SLURMJobState.RUNNING
        assert slurm_runner.get_job_state(1) == SLURMJobState.RUNNING
        assert slurm_runner.get_job_state(999) is None


class TestResultDownload:
    """Test result file downloading."""

    @pytest.mark.asyncio
    async def test_download_results(
        self,
        slurm_runner,
        temp_work_dir,
        mock_connection
    ):
        """Test downloading result files."""
        # Mock SFTP
        mock_sftp = AsyncMock()
        mock_sftp.listdir.return_value = [
            "output.out",
            "input.d12",
            "fort.9",
            "fort.98",
            "slurm-12345.out",
            "slurm-12345.err",
            "structure.xyz"
        ]
        mock_sftp.get = AsyncMock()

        mock_connection.start_sftp_client.return_value = AsyncMock(
            __aenter__=AsyncMock(return_value=mock_sftp),
            __aexit__=AsyncMock()
        )

        # Download results
        await slurm_runner._download_results(
            mock_connection,
            "/scratch/job_001",
            temp_work_dir
        )

        # Verify important files were downloaded
        downloaded_files = [call[0][1] for call in mock_sftp.get.call_args_list]
        assert str(temp_work_dir / "output.out") in downloaded_files
        assert str(temp_work_dir / "slurm-12345.out") in downloaded_files


class TestSLURMJobConfig:
    """Test SLURMJobConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = SLURMJobConfig(job_name="test")
        assert config.nodes == 1
        assert config.ntasks == 1
        assert config.cpus_per_task == 4
        assert config.time_limit == "24:00:00"
        assert config.modules == ["crystal23"]
        assert config.dependencies == []

    def test_custom_config(self):
        """Test custom configuration."""
        config = SLURMJobConfig(
            job_name="custom",
            nodes=4,
            ntasks=56,
            cpus_per_task=2,
            time_limit="48:00:00",
            partition="gpu",
            memory="128GB"
        )
        assert config.job_name == "custom"
        assert config.nodes == 4
        assert config.ntasks == 56
        assert config.partition == "gpu"
        assert config.memory == "128GB"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
