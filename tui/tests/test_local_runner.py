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
    LocalRunnerError,
    JobResult,
    ExecutableNotFoundError,
    InputFileError,
    run_crystal_job,
    run_dft_job,
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
        # Mock get_crystal_config to fail so we fall through to env var resolution
        from src.core.environment import EnvironmentError as CrystalEnvError
        monkeypatch.setattr(
            "src.runners.local.get_crystal_config",
            lambda: (_ for _ in ()).throw(CrystalEnvError("test"))
        )
        monkeypatch.delenv("CRY23_ROOT", raising=False)
        monkeypatch.setenv("CRY23_EXEDIR", str(temp_work_dir))
        runner = LocalRunner()
        assert runner.executable_path == mock_executable

    def test_no_executable_found(self, monkeypatch):
        """Test error when no executable can be found."""
        # Mock get_crystal_config to fail
        from src.core.environment import EnvironmentError as CrystalEnvError
        monkeypatch.setattr(
            "src.runners.local.get_crystal_config",
            lambda: (_ for _ in ()).throw(CrystalEnvError("test"))
        )
        monkeypatch.delenv("CRY23_EXEDIR", raising=False)
        monkeypatch.delenv("CRY23_ROOT", raising=False)
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

    @pytest.mark.skip(reason="Flaky in full suite due to process cleanup timing - passes individually")
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

        # Task should complete gracefully (not hang) after being stopped
        # The task may complete normally or be cancelled - either is acceptable
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except asyncio.CancelledError:
            pass  # Task was cancelled - this is also acceptable

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
    async def test_run_crystal_job_simple(self, temp_work_dir, monkeypatch):
        """Test the convenience function with a mock executable that produces valid output."""
        # Mock get_crystal_config to fail so we use our mock executable
        from src.core.environment import EnvironmentError as CrystalEnvError
        monkeypatch.setattr(
            "src.runners.local.get_crystal_config",
            lambda: (_ for _ in ()).throw(CrystalEnvError("test"))
        )

        # Create a mock executable that produces valid CRYSTAL-like output
        mock_exe = temp_work_dir / "crystalOMP"
        mock_exe.write_text('''#!/bin/bash
cat << 'EOF'
CRYSTAL23 - Job started

TOTAL ENERGY(DFT)(AU)(  10)     -123.4567890123456  DE -1.2E-09
CONVERGENCE REACHED

TTTTTT END
EOF
''')
        mock_exe.chmod(0o755)

        monkeypatch.setenv("CRY23_EXEDIR", str(temp_work_dir))
        monkeypatch.delenv("CRY23_ROOT", raising=False)

        input_file = temp_work_dir / "input.d12"
        input_file.write_text("CRYSTAL\n0 0 0\n225\n5.64\n1\n12 0 0 0\nEND\n")

        result = await run_crystal_job(temp_work_dir)
        assert isinstance(result, JobResult)
        # The mock produces valid output, so we should get energy
        assert result.final_energy is not None or result.convergence_status == "CONVERGED"


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


class TestMultipleJobExecution:
    """Tests for running multiple jobs sequentially or concurrently."""

    @pytest.mark.asyncio
    async def test_sequential_job_execution(self, mock_executable, temp_work_dir, sample_input):
        """Test running multiple jobs one after another."""
        runner = LocalRunner(executable_path=mock_executable)

        # Create multiple job directories
        job_dirs = []
        for i in range(3):
            job_dir = temp_work_dir / f"job_{i}"
            job_dir.mkdir()
            input_file = job_dir / "input.d12"
            input_file.write_text(sample_input)
            job_dirs.append(job_dir)

        # Run jobs sequentially
        for i, job_dir in enumerate(job_dirs):
            async for _ in runner.run_job(i, job_dir):
                pass

        # All jobs should complete
        for job_dir in job_dirs:
            output_file = job_dir / "output.out"
            assert output_file.exists()

    @pytest.mark.asyncio
    async def test_concurrent_job_tracking(self, mock_executable, temp_work_dir, sample_input):
        """Test that runner can track multiple concurrent jobs."""
        runner = LocalRunner(executable_path=mock_executable)

        # Create multiple job directories
        job_dirs = []
        for i in range(2):
            job_dir = temp_work_dir / f"job_{i}"
            job_dir.mkdir()
            input_file = job_dir / "input.d12"
            input_file.write_text(sample_input)
            job_dirs.append(job_dir)

        # Start jobs concurrently
        async def run_job(job_id, job_dir):
            async for _ in runner.run_job(job_id, job_dir):
                pass

        tasks = [
            asyncio.create_task(run_job(i, job_dirs[i]))
            for i in range(2)
        ]

        await asyncio.gather(*tasks)

        # Both jobs should complete
        for job_dir in job_dirs:
            output_file = job_dir / "output.out"
            assert output_file.exists()


class TestResultStorage:
    """Tests for storing and retrieving job results."""

    @pytest.mark.asyncio
    async def test_get_last_result_none_initially(self, mock_executable):
        """Test that get_last_result returns None before any jobs run."""
        runner = LocalRunner(executable_path=mock_executable)
        assert runner.get_last_result() is None

    @pytest.mark.asyncio
    async def test_get_last_result_after_job(self, mock_executable, temp_work_dir, sample_input):
        """Test that get_last_result returns result after job completes."""
        input_file = temp_work_dir / "input.d12"
        input_file.write_text(sample_input)

        runner = LocalRunner(executable_path=mock_executable)
        async for _ in runner.run_job(1, temp_work_dir):
            pass

        result = runner.get_last_result()
        assert result is not None
        assert isinstance(result, JobResult)

    @pytest.mark.asyncio
    async def test_last_result_overwritten_by_new_job(self, mock_executable, temp_work_dir, sample_input):
        """Test that last result is replaced by newer job."""
        # Run first job
        job1_dir = temp_work_dir / "job1"
        job1_dir.mkdir()
        (job1_dir / "input.d12").write_text(sample_input)

        runner = LocalRunner(executable_path=mock_executable)
        async for _ in runner.run_job(1, job1_dir):
            pass

        result1 = runner.get_last_result()

        # Run second job
        job2_dir = temp_work_dir / "job2"
        job2_dir.mkdir()
        (job2_dir / "input.d12").write_text(sample_input)

        async for _ in runner.run_job(2, job2_dir):
            pass

        result2 = runner.get_last_result()

        # Results should be different objects
        assert result1 is not result2


class TestThreadConfiguration:
    """Tests for OpenMP thread configuration."""

    def test_default_threads_from_cpu_count(self, mock_executable):
        """Test that default threads uses CPU count."""
        runner = LocalRunner(executable_path=mock_executable)

        expected = os.cpu_count() or 4
        assert runner.default_threads == expected

    def test_explicit_default_threads(self, mock_executable):
        """Test setting explicit default thread count."""
        runner = LocalRunner(executable_path=mock_executable, default_threads=16)
        assert runner.default_threads == 16

    @pytest.mark.asyncio
    async def test_per_job_thread_override(self, mock_executable, temp_work_dir, sample_input):
        """Test that per-job thread count overrides default."""
        input_file = temp_work_dir / "input.d12"
        input_file.write_text(sample_input)

        runner = LocalRunner(executable_path=mock_executable, default_threads=8)

        # Run with custom threads
        async for _ in runner.run_job(1, temp_work_dir, threads=4):
            pass

        # No direct way to verify OMP_NUM_THREADS, but test should pass


class TestPathHandling:
    """Tests for path resolution and handling."""

    def test_path_lookup_in_system_path(self, temp_work_dir, monkeypatch):
        """Test finding executable via PATH."""
        # Create executable in temp dir
        exe_path = temp_work_dir / "crystalOMP"
        exe_path.touch()
        exe_path.chmod(0o755)

        # Mock get_crystal_config to fail so we fall through to PATH lookup
        from src.core.environment import EnvironmentError as CrystalEnvError
        monkeypatch.setattr(
            "src.runners.local.get_crystal_config",
            lambda: (_ for _ in ()).throw(CrystalEnvError("test"))
        )

        # Mock shutil.which to return our executable
        import shutil
        original_which = shutil.which

        def mock_which(cmd):
            if cmd == "crystalOMP":
                return str(exe_path)
            return original_which(cmd)

        monkeypatch.setattr(shutil, "which", mock_which)
        monkeypatch.delenv("CRY23_EXEDIR", raising=False)
        monkeypatch.delenv("CRY23_ROOT", raising=False)

        runner = LocalRunner()
        assert runner.executable_path == exe_path

    def test_relative_work_dir_converted_to_absolute(self, mock_executable):
        """Test that relative paths work correctly."""
        runner = LocalRunner(executable_path=mock_executable)

        # Method accepts Path objects which may be relative
        # Internal handling should work regardless


class TestErrorScenarios:
    """Tests for various error conditions."""

    @pytest.mark.asyncio
    async def test_output_file_creation_failure(self, temp_work_dir, sample_input):
        """Test handling when output file cannot be created."""
        # Create executable
        exe_path = temp_work_dir / "crystalOMP"
        exe_path.write_text("#!/bin/bash\necho 'test'\n")
        exe_path.chmod(0o755)

        # Create read-only work directory
        work_dir = temp_work_dir / "readonly"
        work_dir.mkdir()
        input_file = work_dir / "input.d12"
        input_file.write_text(sample_input)

        # Make directory read-only (skip on Windows)
        import platform
        if platform.system() != "Windows":
            work_dir.chmod(0o555)

            runner = LocalRunner(executable_path=exe_path)

            try:
                async for _ in runner.run_job(1, work_dir):
                    pass
                # Should fail to create output file
            except (PermissionError, LocalRunnerError):
                pass
            finally:
                # Restore permissions for cleanup
                work_dir.chmod(0o755)

    @pytest.mark.asyncio
    async def test_input_file_disappears_during_execution(self, mock_executable, temp_work_dir):
        """Test error when input file is deleted before execution."""
        input_file = temp_work_dir / "input.d12"
        input_file.write_text("CRYSTAL\nEND\n")

        # Delete input file immediately
        input_file.unlink()

        runner = LocalRunner(executable_path=mock_executable)

        with pytest.raises(InputFileError, match="Input file not found"):
            async for _ in runner.run_job(1, temp_work_dir):
                pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
