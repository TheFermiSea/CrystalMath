"""
Unit tests for BaseRunner abstract interface.

This module tests the BaseRunner abstract class, RunnerConfig,
JobStatus enum, and related data structures. It also includes tests
for the exception hierarchy.
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from src.runners.base import (
    BaseRunner,
    RunnerConfig,
    JobHandle,
    JobStatus,
    JobInfo,
)
from src.runners.exceptions import (
    RunnerError,
    ConnectionError,
    ExecutionError,
    TimeoutError,
    ConfigurationError,
    ResourceError,
    CancellationError,
)


# -------------------------------------------------------------------------
# Test Fixtures
# -------------------------------------------------------------------------


class ConcreteRunner(BaseRunner):
    """Concrete implementation of BaseRunner for testing."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._submitted_jobs = {}
        self._job_statuses = {}

    async def submit_job(self, job_id, input_file, work_dir, threads=None, **kwargs):
        handle = JobHandle(f"test_{job_id}")
        self._submitted_jobs[handle] = {
            "job_id": job_id,
            "input_file": input_file,
            "work_dir": work_dir,
            "threads": threads,
        }
        self._job_statuses[handle] = JobStatus.RUNNING
        return handle

    async def get_status(self, job_handle):
        return self._job_statuses.get(job_handle, JobStatus.UNKNOWN)

    async def cancel_job(self, job_handle):
        if job_handle in self._job_statuses:
            self._job_statuses[job_handle] = JobStatus.CANCELLED
            return True
        return False

    async def get_output(self, job_handle):
        yield "Test output line 1"
        yield "Test output line 2"
        yield "Test output line 3"

    async def retrieve_results(self, job_handle, dest, cleanup=None):
        pass  # No-op for testing

    def set_job_status(self, job_handle, status):
        """Helper method for testing."""
        self._job_statuses[job_handle] = status


@pytest.fixture
def temp_dir(tmp_path):
    """Temporary directory for test files."""
    return tmp_path


@pytest.fixture
def runner_config(temp_dir):
    """Default runner configuration for testing."""
    return RunnerConfig(
        name="test_runner",
        scratch_dir=temp_dir / "scratch",
        default_threads=4,
        max_concurrent_jobs=2,
    )


@pytest.fixture
def concrete_runner(runner_config):
    """Concrete runner instance for testing."""
    return ConcreteRunner(config=runner_config)


# -------------------------------------------------------------------------
# RunnerConfig Tests
# -------------------------------------------------------------------------


def test_runner_config_defaults():
    """Test RunnerConfig with default values."""
    config = RunnerConfig()

    assert config.name == "default"
    assert config.scratch_dir == Path.home() / "tmp_crystal"
    assert config.executable_path is None
    assert config.default_threads == 4
    assert config.max_concurrent_jobs == 1
    assert config.timeout_seconds == 0.0
    assert config.cleanup_on_success is False
    assert config.cleanup_on_failure is False
    assert config.output_buffer_lines == 100
    assert isinstance(config.extra_config, dict)
    assert len(config.extra_config) == 0


def test_runner_config_custom_values(temp_dir):
    """Test RunnerConfig with custom values."""
    exe_path = temp_dir / "crystalOMP"
    exe_path.touch()

    config = RunnerConfig(
        name="custom_runner",
        scratch_dir=temp_dir / "scratch",
        executable_path=exe_path,
        default_threads=8,
        max_concurrent_jobs=4,
        timeout_seconds=3600.0,
        cleanup_on_success=True,
        cleanup_on_failure=False,
        output_buffer_lines=200,
        extra_config={"partition": "gpu", "account": "myaccount"},
    )

    assert config.name == "custom_runner"
    assert config.scratch_dir == temp_dir / "scratch"
    assert config.executable_path == exe_path
    assert config.default_threads == 8
    assert config.max_concurrent_jobs == 4
    assert config.timeout_seconds == 3600.0
    assert config.cleanup_on_success is True
    assert config.cleanup_on_failure is False
    assert config.output_buffer_lines == 200
    assert config.extra_config["partition"] == "gpu"
    assert config.extra_config["account"] == "myaccount"


def test_runner_config_path_normalization():
    """Test that paths are normalized to Path objects."""
    config = RunnerConfig(
        scratch_dir="/tmp/scratch",
        executable_path="/usr/bin/crystal",
    )

    assert isinstance(config.scratch_dir, Path)
    assert isinstance(config.executable_path, Path)
    assert config.scratch_dir == Path("/tmp/scratch")
    assert config.executable_path == Path("/usr/bin/crystal")


def test_runner_config_validation_errors():
    """Test RunnerConfig validation errors."""
    # default_threads < 1
    with pytest.raises(ValueError, match="default_threads must be >= 1"):
        RunnerConfig(default_threads=0)

    # max_concurrent_jobs < 1
    with pytest.raises(ValueError, match="max_concurrent_jobs must be >= 1"):
        RunnerConfig(max_concurrent_jobs=0)

    # timeout_seconds < 0
    with pytest.raises(ValueError, match="timeout_seconds must be >= 0"):
        RunnerConfig(timeout_seconds=-1.0)


# -------------------------------------------------------------------------
# JobStatus Enum Tests
# -------------------------------------------------------------------------


def test_job_status_values():
    """Test JobStatus enum values."""
    assert JobStatus.PENDING.value == "pending"
    assert JobStatus.QUEUED.value == "queued"
    assert JobStatus.RUNNING.value == "running"
    assert JobStatus.COMPLETED.value == "completed"
    assert JobStatus.FAILED.value == "failed"
    assert JobStatus.CANCELLED.value == "cancelled"
    assert JobStatus.UNKNOWN.value == "unknown"


def test_job_status_comparison():
    """Test JobStatus enum comparison."""
    status1 = JobStatus.RUNNING
    status2 = JobStatus.RUNNING
    status3 = JobStatus.COMPLETED

    assert status1 == status2
    assert status1 != status3


# -------------------------------------------------------------------------
# JobInfo Tests
# -------------------------------------------------------------------------


def test_job_info_creation():
    """Test JobInfo dataclass creation."""
    handle = JobHandle("test_123")
    work_dir = Path("/work/job_123")

    info = JobInfo(
        job_handle=handle,
        status=JobStatus.RUNNING,
        work_dir=work_dir,
        pid=12345,
    )

    assert info.job_handle == handle
    assert info.status == JobStatus.RUNNING
    assert info.work_dir == work_dir
    assert info.pid == 12345
    assert info.scratch_dir is None
    assert info.exit_code is None


def test_job_info_with_metadata():
    """Test JobInfo with resource usage and metadata."""
    handle = JobHandle("test_456")

    info = JobInfo(
        job_handle=handle,
        status=JobStatus.COMPLETED,
        work_dir=Path("/work/job_456"),
        exit_code=0,
        resource_usage={"cpu_time": 3600.0, "max_memory_mb": 2048},
        metadata={"queue": "normal", "node": "compute01"},
    )

    assert info.resource_usage["cpu_time"] == 3600.0
    assert info.resource_usage["max_memory_mb"] == 2048
    assert info.metadata["queue"] == "normal"
    assert info.metadata["node"] == "compute01"


# -------------------------------------------------------------------------
# Exception Hierarchy Tests
# -------------------------------------------------------------------------


def test_exception_hierarchy():
    """Test exception inheritance."""
    # All exceptions inherit from RunnerError
    assert issubclass(ConnectionError, RunnerError)
    assert issubclass(ExecutionError, RunnerError)
    assert issubclass(TimeoutError, RunnerError)
    assert issubclass(ConfigurationError, RunnerError)
    assert issubclass(ResourceError, RunnerError)
    assert issubclass(CancellationError, RunnerError)


def test_connection_error_attributes():
    """Test ConnectionError with attributes."""
    error = ConnectionError(
        "Failed to connect",
        host="cluster.example.com",
        details="Connection timed out after 30 seconds"
    )

    assert str(error) == "Failed to connect"
    assert error.host == "cluster.example.com"
    assert error.details == "Connection timed out after 30 seconds"


def test_execution_error_attributes():
    """Test ExecutionError with attributes."""
    error = ExecutionError(
        "Job execution failed",
        job_handle="slurm_12345",
        exit_code=1,
        stderr_output="Error: Invalid input file"
    )

    assert str(error) == "Job execution failed"
    assert error.job_handle == "slurm_12345"
    assert error.exit_code == 1
    assert error.stderr_output == "Error: Invalid input file"


def test_timeout_error_attributes():
    """Test TimeoutError with attributes."""
    error = TimeoutError(
        "Operation timed out",
        timeout_seconds=300.0,
        operation="job_submission"
    )

    assert str(error) == "Operation timed out"
    assert error.timeout_seconds == 300.0
    assert error.operation == "job_submission"


# -------------------------------------------------------------------------
# BaseRunner Tests
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_baserunner_submit_job(concrete_runner, temp_dir):
    """Test job submission through BaseRunner interface."""
    input_file = temp_dir / "input.d12"
    input_file.write_text("TEST INPUT")
    work_dir = temp_dir / "work"
    work_dir.mkdir()

    handle = await concrete_runner.submit_job(
        job_id=1,
        input_file=input_file,
        work_dir=work_dir,
        threads=8,
    )

    assert handle == JobHandle("test_1")
    assert handle in concrete_runner._submitted_jobs

    job_info = concrete_runner._submitted_jobs[handle]
    assert job_info["job_id"] == 1
    assert job_info["input_file"] == input_file
    assert job_info["work_dir"] == work_dir
    assert job_info["threads"] == 8


@pytest.mark.asyncio
async def test_baserunner_get_status(concrete_runner, temp_dir):
    """Test getting job status."""
    input_file = temp_dir / "input.d12"
    work_dir = temp_dir / "work"
    input_file.touch()
    work_dir.mkdir()

    handle = await concrete_runner.submit_job(1, input_file, work_dir)

    # Initially running
    status = await concrete_runner.get_status(handle)
    assert status == JobStatus.RUNNING

    # Change status
    concrete_runner.set_job_status(handle, JobStatus.COMPLETED)
    status = await concrete_runner.get_status(handle)
    assert status == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_baserunner_cancel_job(concrete_runner, temp_dir):
    """Test cancelling a job."""
    input_file = temp_dir / "input.d12"
    work_dir = temp_dir / "work"
    input_file.touch()
    work_dir.mkdir()

    handle = await concrete_runner.submit_job(1, input_file, work_dir)

    # Cancel the job
    success = await concrete_runner.cancel_job(handle)
    assert success is True

    # Check status is cancelled
    status = await concrete_runner.get_status(handle)
    assert status == JobStatus.CANCELLED


@pytest.mark.asyncio
async def test_baserunner_get_output(concrete_runner, temp_dir):
    """Test streaming job output."""
    input_file = temp_dir / "input.d12"
    work_dir = temp_dir / "work"
    input_file.touch()
    work_dir.mkdir()

    handle = await concrete_runner.submit_job(1, input_file, work_dir)

    # Collect output
    output_lines = []
    async for line in concrete_runner.get_output(handle):
        output_lines.append(line)

    assert len(output_lines) == 3
    assert output_lines[0] == "Test output line 1"
    assert output_lines[1] == "Test output line 2"
    assert output_lines[2] == "Test output line 3"


@pytest.mark.asyncio
async def test_baserunner_wait_for_completion(concrete_runner, temp_dir):
    """Test waiting for job completion."""
    input_file = temp_dir / "input.d12"
    work_dir = temp_dir / "work"
    input_file.touch()
    work_dir.mkdir()

    handle = await concrete_runner.submit_job(1, input_file, work_dir)

    # Schedule status change after 0.5 seconds
    async def change_status():
        await asyncio.sleep(0.5)
        concrete_runner.set_job_status(handle, JobStatus.COMPLETED)

    asyncio.create_task(change_status())

    # Wait for completion
    final_status = await concrete_runner.wait_for_completion(
        handle,
        poll_interval=0.1,
        timeout=2.0
    )

    assert final_status == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_baserunner_wait_for_completion_timeout(concrete_runner, temp_dir):
    """Test timeout during wait_for_completion."""
    input_file = temp_dir / "input.d12"
    work_dir = temp_dir / "work"
    input_file.touch()
    work_dir.mkdir()

    handle = await concrete_runner.submit_job(1, input_file, work_dir)

    # Job stays running, should timeout
    with pytest.raises(TimeoutError) as exc_info:
        await concrete_runner.wait_for_completion(
            handle,
            poll_interval=0.1,
            timeout=0.3
        )

    assert "did not complete within 0.3 seconds" in str(exc_info.value)
    assert exc_info.value.timeout_seconds == 0.3


@pytest.mark.asyncio
async def test_baserunner_max_concurrent_jobs(temp_dir):
    """Test max_concurrent_jobs semaphore."""
    config = RunnerConfig(max_concurrent_jobs=2)
    runner = ConcreteRunner(config=config)

    input_file = temp_dir / "input.d12"
    work_dir = temp_dir / "work"
    input_file.touch()
    work_dir.mkdir()

    # Should be able to acquire 2 slots
    async with runner.acquire_slot():
        async with runner.acquire_slot():
            # Both slots acquired
            assert True

    # Third slot should wait
    acquired_count = 0

    async def acquire_and_release():
        nonlocal acquired_count
        async with runner.acquire_slot():
            acquired_count += 1
            await asyncio.sleep(0.1)

    # Start 3 tasks, only 2 should run concurrently
    tasks = [acquire_and_release() for _ in range(3)]
    await asyncio.gather(*tasks)

    assert acquired_count == 3


@pytest.mark.asyncio
async def test_baserunner_context_manager(runner_config):
    """Test BaseRunner as async context manager."""
    runner = ConcreteRunner(config=runner_config)

    async with runner as r:
        assert r is runner
        assert r.is_connected()

    # Cleanup should be called on exit


def test_baserunner_is_connected(concrete_runner):
    """Test is_connected method."""
    # Default implementation returns True
    assert concrete_runner.is_connected() is True


# -------------------------------------------------------------------------
# Integration Tests
# -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_job_lifecycle(concrete_runner, temp_dir):
    """Test complete job lifecycle from submit to completion."""
    input_file = temp_dir / "input.d12"
    work_dir = temp_dir / "work"
    results_dir = temp_dir / "results"
    input_file.touch()
    work_dir.mkdir()
    results_dir.mkdir()

    # 1. Submit job
    handle = await concrete_runner.submit_job(1, input_file, work_dir, threads=4)
    assert handle

    # 2. Check initial status
    status = await concrete_runner.get_status(handle)
    assert status == JobStatus.RUNNING

    # 3. Stream output
    output_lines = []
    async for line in concrete_runner.get_output(handle):
        output_lines.append(line)
    assert len(output_lines) > 0

    # 4. Change to completed
    concrete_runner.set_job_status(handle, JobStatus.COMPLETED)
    status = await concrete_runner.get_status(handle)
    assert status == JobStatus.COMPLETED

    # 5. Retrieve results
    await concrete_runner.retrieve_results(handle, results_dir)

    # 6. Get job info
    info = await concrete_runner.get_job_info(handle)
    assert info.job_handle == handle
    assert info.status == JobStatus.COMPLETED
