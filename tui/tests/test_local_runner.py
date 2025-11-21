"""
Tests for the LocalRunner job execution backend.

These tests verify:
1. Executable resolution from environment
2. Input file validation
3. Job execution and output streaming
4. Result parsing with CRYSTALpytools
5. Fallback parsing when CRYSTALpytools unavailable
6. Process management and cleanup
"""

import asyncio
import os
import tempfile
from pathlib import Path
import pytest

from src.runners.local import (
    LocalRunner,
    JobResult,
    ExecutableNotFoundError,
    InputFileError,
    run_crystal_job,
)


@pytest.fixture
def temp_work_dir():
    """Create a temporary working directory for test jobs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_executable(temp_work_dir):
    """Create a mock crystalOMP executable for testing."""
    exe_path = temp_work_dir / "crystalOMP"
    exe_path.write_text("""#!/bin/bash
# Mock CRYSTAL executable for testing
cat  # Echo stdin to stdout
echo ""
echo "TOTAL ENERGY(DFT)(AU)( 123) -123.456789012345 DE-1.2E-09"
echo "CONVERGENCE REACHED"
echo "SCF ENDED"
exit 0
""")
    exe_path.chmod(0o755)
    return exe_path


@pytest.fixture
def sample_input():
    """Sample CRYSTAL input file content."""
    return """CRYSTAL
0 0 0
1
1.0
END
OPTGEOM
END
"""


class TestExecutableResolution:
    """Tests for finding the crystalOMP executable."""

    def test_explicit_path(self, mock_executable):
        """Test providing explicit executable path."""
        runner = LocalRunner(executable_path=mock_executable)
        assert runner.executable_path == mock_executable

    def test_explicit_path_not_found(self):
        """Test error when explicit path doesn't exist."""
        with pytest.raises(ExecutableNotFoundError):
            LocalRunner(executable_path=Path("/nonexistent/crystalOMP"))

    def test_env_var_resolution(self, mock_executable, temp_work_dir, monkeypatch):
        """Test resolution from CRY23_EXEDIR environment variable."""
        monkeypatch.setenv("CRY23_EXEDIR", str(temp_work_dir))
        runner = LocalRunner()
        assert runner.executable_path == mock_executable

    def test_no_executable_found(self, monkeypatch):
        """Test error when no executable can be found."""
        monkeypatch.delenv("CRY23_EXEDIR", raising=False)
        with pytest.raises(ExecutableNotFoundError):
            LocalRunner()


class TestInputValidation:
    """Tests for input file validation."""

    @pytest.mark.asyncio
    async def test_missing_input_file(self, mock_executable, temp_work_dir):
        """Test error when input.d12 doesn't exist."""
        runner = LocalRunner(executable_path=mock_executable)
        with pytest.raises(InputFileError, match="Input file not found"):
            async for _ in runner.run_job(1, temp_work_dir):
                pass

    @pytest.mark.asyncio
    async def test_empty_input_file(self, mock_executable, temp_work_dir):
        """Test error when input.d12 is empty."""
        input_file = temp_work_dir / "input.d12"
        input_file.touch()

        runner = LocalRunner(executable_path=mock_executable)
        with pytest.raises(InputFileError, match="Input file is empty"):
            async for _ in runner.run_job(1, temp_work_dir):
                pass


class TestJobExecution:
    """Tests for running jobs."""

    @pytest.mark.asyncio
    async def test_basic_job_execution(self, mock_executable, temp_work_dir, sample_input):
        """Test basic job execution and output streaming."""
        # Create input file
        input_file = temp_work_dir / "input.d12"
        input_file.write_text(sample_input)

        # Run job
        runner = LocalRunner(executable_path=mock_executable)
        output_lines = []
        async for line in runner.run_job(1, temp_work_dir):
            output_lines.append(line)

        # Verify output was streamed
        assert len(output_lines) > 0

        # Check that input was echoed
        assert any(sample_input.split()[0] in line for line in output_lines)

        # Check output file was created
        output_file = temp_work_dir / "output.out"
        assert output_file.exists()
        assert output_file.stat().st_size > 0

    @pytest.mark.asyncio
    async def test_thread_configuration(self, mock_executable, temp_work_dir, sample_input):
        """Test OpenMP thread configuration."""
        input_file = temp_work_dir / "input.d12"
        input_file.write_text(sample_input)

        runner = LocalRunner(executable_path=mock_executable, default_threads=8)
        assert runner.default_threads == 8

        # Run with custom threads
        async for _ in runner.run_job(1, temp_work_dir, threads=4):
            pass

    @pytest.mark.asyncio
    async def test_process_tracking(self, mock_executable, temp_work_dir, sample_input):
        """Test that processes are tracked during execution."""
        input_file = temp_work_dir / "input.d12"
        input_file.write_text(sample_input)

        runner = LocalRunner(executable_path=mock_executable)
        job_id = 42

        # Start job
        async def run_job():
            async for _ in runner.run_job(job_id, temp_work_dir):
                pass

        task = asyncio.create_task(run_job())
        await asyncio.sleep(0.1)  # Let job start

        # Job should be tracked
        assert job_id in runner._active_processes or task.done()

        await task  # Wait for completion


class TestResultParsing:
    """Tests for parsing job results."""

    @pytest.mark.asyncio
    async def test_fallback_parser_energy(self, mock_executable, temp_work_dir):
        """Test fallback parser extracts energy correctly."""
        # Create input and output with known energy
        input_file = temp_work_dir / "input.d12"
        input_file.write_text("CRYSTAL\nEND\n")

        runner = LocalRunner(executable_path=mock_executable)
        async for _ in runner.run_job(1, temp_work_dir):
            pass

        result = runner.get_last_result()
        assert result is not None
        assert result.final_energy is not None
        assert abs(result.final_energy - (-123.456789012345)) < 1e-6

    @pytest.mark.asyncio
    async def test_fallback_parser_convergence(self, mock_executable, temp_work_dir):
        """Test fallback parser detects convergence."""
        input_file = temp_work_dir / "input.d12"
        input_file.write_text("CRYSTAL\nEND\n")

        runner = LocalRunner(executable_path=mock_executable)
        async for _ in runner.run_job(1, temp_work_dir):
            pass

        result = runner.get_last_result()
        assert result is not None
        assert result.convergence_status == "CONVERGED"
        assert result.success

    @pytest.mark.asyncio
    async def test_failed_job_detection(self, temp_work_dir, sample_input):
        """Test detection of failed jobs."""
        # Create a failing mock executable
        exe_path = temp_work_dir / "crystalOMP"
        exe_path.write_text("""#!/bin/bash
echo "ERROR: Something went wrong"
echo "FATAL ERROR"
exit 1
""")
        exe_path.chmod(0o755)

        input_file = temp_work_dir / "input.d12"
        input_file.write_text(sample_input)

        runner = LocalRunner(executable_path=exe_path)
        async for _ in runner.run_job(1, temp_work_dir):
            pass

        result = runner.get_last_result()
        assert result is not None
        assert not result.success
        assert len(result.errors) > 0


class TestProcessManagement:
    """Tests for managing running processes."""

    @pytest.mark.asyncio
    async def test_stop_running_job(self, temp_work_dir, sample_input):
        """Test stopping a running job."""
        # Create a long-running mock executable
        exe_path = temp_work_dir / "crystalOMP"
        exe_path.write_text("""#!/bin/bash
sleep 10
""")
        exe_path.chmod(0o755)

        input_file = temp_work_dir / "input.d12"
        input_file.write_text(sample_input)

        runner = LocalRunner(executable_path=exe_path)
        job_id = 99

        # Start job
        async def run_job():
            async for _ in runner.run_job(job_id, temp_work_dir):
                pass

        task = asyncio.create_task(run_job())
        await asyncio.sleep(0.2)  # Let job start

        # Stop the job
        stopped = await runner.stop_job(job_id, timeout=1.0)
        assert stopped

        # Task should complete
        with pytest.raises(Exception):
            await asyncio.wait_for(task, timeout=2.0)

    @pytest.mark.asyncio
    async def test_stop_nonexistent_job(self, mock_executable):
        """Test stopping a job that isn't running."""
        runner = LocalRunner(executable_path=mock_executable)
        stopped = await runner.stop_job(999)
        assert not stopped

    def test_is_job_running(self, mock_executable):
        """Test checking if job is running."""
        runner = LocalRunner(executable_path=mock_executable)
        assert not runner.is_job_running(123)


class TestConvenienceFunction:
    """Tests for the run_crystal_job convenience function."""

    @pytest.mark.asyncio
    async def test_run_crystal_job_simple(self, mock_executable, temp_work_dir, sample_input, monkeypatch):
        """Test the convenience function."""
        monkeypatch.setenv("CRY23_EXEDIR", str(temp_work_dir))

        input_file = temp_work_dir / "input.d12"
        input_file.write_text(sample_input)

        result = await run_crystal_job(temp_work_dir)
        assert isinstance(result, JobResult)
        assert result.final_energy is not None


class TestRealIntegration:
    """Integration tests with actual CRYSTAL installation (if available)."""

    @pytest.mark.skipif(
        not os.environ.get("CRY23_EXEDIR"),
        reason="CRYSTAL installation not configured"
    )
    @pytest.mark.asyncio
    async def test_with_real_crystal(self, temp_work_dir):
        """Test with actual CRYSTAL executable if available."""
        # This test only runs if CRYSTAL is properly installed
        input_file = temp_work_dir / "input.d12"
        input_file.write_text("""CRYSTAL
0 0 0
99
225
5.64
1
12 0.0 0.0 0.0
END
12 3
1 0 3 2. 1.
1 1 3 2. 1.
1 1 3 8. 1.
99 0
END
SHRINK
8 8
END
""")

        try:
            runner = LocalRunner()
            output_lines = []
            async for line in runner.run_job(1, temp_work_dir):
                output_lines.append(line)

            result = runner.get_last_result()
            assert result is not None
            # Real CRYSTAL should produce valid output
            assert len(output_lines) > 10

        except ExecutableNotFoundError:
            pytest.skip("CRYSTAL executable not found")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
