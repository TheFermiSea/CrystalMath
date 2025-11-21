"""
Abstract base class for CRYSTAL job runners.

This module defines the interface that all job runners (local, SSH, SLURM)
must implement to provide consistent job execution capabilities across
different execution environments.

Design principles:
- Async/await throughout for non-blocking execution
- Generator-based output streaming for real-time monitoring
- Type-safe interfaces with comprehensive type hints
- Extensible configuration system for runner-specific settings
- Resource management and cleanup guarantees
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import AsyncIterator, Any, Dict, Optional, NewType
import asyncio


# Type alias for job handles (runner-specific identifiers)
JobHandle = NewType("JobHandle", str)


class JobStatus(Enum):
    """
    Standard job status values across all runners.

    States represent the lifecycle of a job from submission to completion:

    PENDING: Job created but not yet submitted to execution system
    QUEUED: Job submitted and waiting in a queue (SLURM, SSH queue)
    RUNNING: Job is actively executing
    COMPLETED: Job finished successfully with exit code 0
    FAILED: Job finished with errors or non-zero exit code
    CANCELLED: Job was terminated by user request
    UNKNOWN: Job status cannot be determined (connection lost, etc.)
    """

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


@dataclass
class RunnerConfig:
    """
    Base configuration for all runner types.

    This class provides common configuration options that apply to all
    runners. Specific runner implementations should subclass this and
    add their own configuration fields.

    Attributes:
        name: Human-readable name for this runner instance
        scratch_dir: Base directory for temporary calculation files
        executable_path: Path to crystalOMP or crystal executable
        default_threads: Default number of OpenMP threads
        max_concurrent_jobs: Maximum number of jobs to run simultaneously
        timeout_seconds: Default timeout for job operations (0 = no timeout)
        cleanup_on_success: Whether to delete scratch files after success
        cleanup_on_failure: Whether to delete scratch files after failure
        output_buffer_lines: Number of output lines to buffer before yielding
        extra_config: Runner-specific configuration parameters
    """

    name: str = "default"
    scratch_dir: Path = Path.home() / "tmp_crystal"
    executable_path: Optional[Path] = None
    default_threads: int = 4
    max_concurrent_jobs: int = 1
    timeout_seconds: float = 0.0
    cleanup_on_success: bool = False
    cleanup_on_failure: bool = False
    output_buffer_lines: int = 100
    extra_config: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate and normalize configuration after initialization."""
        # Ensure scratch_dir is a Path object
        if not isinstance(self.scratch_dir, Path):
            self.scratch_dir = Path(self.scratch_dir)

        # Ensure executable_path is a Path object if provided
        if self.executable_path is not None and not isinstance(self.executable_path, Path):
            self.executable_path = Path(self.executable_path)

        # Validate numeric constraints
        if self.default_threads < 1:
            raise ValueError(f"default_threads must be >= 1, got {self.default_threads}")

        if self.max_concurrent_jobs < 1:
            raise ValueError(
                f"max_concurrent_jobs must be >= 1, got {self.max_concurrent_jobs}"
            )

        if self.timeout_seconds < 0:
            raise ValueError(
                f"timeout_seconds must be >= 0, got {self.timeout_seconds}"
            )


@dataclass
class JobInfo:
    """
    Complete information about a job's current state.

    This structure is returned by get_job_info() and provides a complete
    snapshot of a job's state, including execution details and resource usage.

    Attributes:
        job_handle: Runner-specific job identifier
        status: Current job status
        work_dir: Path to the job's working directory
        scratch_dir: Path to the job's scratch directory (if different)
        pid: Process ID (local execution only)
        submit_time: Timestamp when job was submitted
        start_time: Timestamp when job started executing
        end_time: Timestamp when job completed
        exit_code: Process exit code (if completed)
        resource_usage: Resource usage statistics (CPU time, memory, etc.)
        metadata: Additional runner-specific information
    """

    job_handle: JobHandle
    status: JobStatus
    work_dir: Path
    scratch_dir: Optional[Path] = None
    pid: Optional[int] = None
    submit_time: Optional[float] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    exit_code: Optional[int] = None
    resource_usage: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class JobResult:
    """
    Structured results from a completed CRYSTAL job.

    This dataclass encapsulates the output of a CRYSTAL calculation,
    including energy, convergence status, and any errors or warnings.

    Attributes:
        success: Whether the job completed successfully
        final_energy: Final energy in Hartree (if available)
        convergence_status: Convergence status string (CONVERGED, NOT_CONVERGED, etc.)
        errors: List of error messages encountered during execution
        warnings: List of warning messages
        metadata: Additional job-specific information (timings, system info, etc.)
    """

    success: bool
    final_energy: Optional[float]
    convergence_status: str
    errors: list[str]
    warnings: list[str]
    metadata: Dict[str, Any]


class BaseRunner(ABC):
    """
    Abstract base class for all CRYSTAL job runners.

    This class defines the interface that all runner implementations must
    provide. Runners handle job submission, monitoring, and result retrieval
    across different execution environments (local, SSH, SLURM).

    Subclasses must implement all abstract methods and follow these patterns:
    - Use async/await for all I/O operations
    - Yield output incrementally using async generators
    - Raise runner-specific exceptions from runners.exceptions
    - Clean up resources in __aexit__ or explicit cleanup methods
    - Support connection pooling and resource reuse

    Attributes:
        config: Runner configuration
    """

    def __init__(self, config: Optional[RunnerConfig] = None):
        """
        Initialize the base runner.

        Args:
            config: Runner configuration. If None, uses default RunnerConfig.
        """
        self.config = config or RunnerConfig()
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_jobs)
        self._active_jobs: Dict[JobHandle, asyncio.Task] = {}

    # -------------------------------------------------------------------------
    # Core Abstract Methods - Must be implemented by all runners
    # -------------------------------------------------------------------------

    @abstractmethod
    async def submit_job(
        self,
        job_id: int,
        input_file: Path,
        work_dir: Path,
        threads: Optional[int] = None,
        **kwargs
    ) -> JobHandle:
        """
        Submit a job for execution and return a job handle.

        This method stages the input file to the execution environment,
        submits the job to the execution system (local process, SSH, SLURM),
        and returns a handle that can be used to query status and retrieve results.

        Args:
            job_id: Database ID of the job for tracking
            input_file: Path to the .d12 input file
            work_dir: Path to the job's working directory
            threads: Number of OpenMP threads (default: config.default_threads)
            **kwargs: Runner-specific submission options

        Returns:
            JobHandle: Opaque identifier for this job

        Raises:
            ConnectionError: Cannot connect to execution environment
            ConfigurationError: Invalid configuration or missing executable
            ResourceError: Insufficient resources to submit job
            RunnerError: Other submission failures

        Example:
            >>> runner = LocalRunner()
            >>> input_path = Path("my_calc/input.d12")
            >>> work_path = Path("my_calc")
            >>> handle = await runner.submit_job(1, input_path, work_path, threads=8)
        """
        pass

    @abstractmethod
    async def get_status(self, job_handle: JobHandle) -> JobStatus:
        """
        Query the current status of a submitted job.

        This method polls the execution system to determine the job's current
        state. It should be efficient and non-blocking.

        Args:
            job_handle: Job identifier returned by submit_job()

        Returns:
            JobStatus: Current status of the job

        Raises:
            ConnectionError: Cannot connect to execution environment
            RunnerError: Cannot determine job status

        Example:
            >>> status = await runner.get_status(handle)
            >>> if status == JobStatus.RUNNING:
            ...     print("Job is currently executing")
        """
        pass

    @abstractmethod
    async def cancel_job(self, job_handle: JobHandle) -> bool:
        """
        Cancel a running or queued job.

        This method attempts to terminate a job gracefully. For local jobs,
        this sends SIGTERM followed by SIGKILL. For remote jobs, this uses
        the appropriate scheduler command (scancel, qdel, etc.).

        Args:
            job_handle: Job identifier to cancel

        Returns:
            bool: True if job was successfully cancelled, False if job was
                  not running or already completed

        Raises:
            CancellationError: Job exists but cannot be cancelled
            ConnectionError: Cannot connect to execution environment
            RunnerError: Other cancellation failures

        Example:
            >>> success = await runner.cancel_job(handle)
            >>> if success:
            ...     print("Job cancelled successfully")
        """
        pass

    @abstractmethod
    async def get_output(self, job_handle: JobHandle) -> AsyncIterator[str]:
        """
        Stream job output in real-time as an async generator.

        This method yields output lines as they are produced by the job.
        For local jobs, this reads from stdout/stderr. For remote jobs,
        this tails the output file or uses scheduler-specific streaming.

        The generator continues until the job completes or an error occurs.

        Args:
            job_handle: Job identifier to stream output from

        Yields:
            str: Output lines from the job (without trailing newlines)

        Raises:
            ConnectionError: Cannot connect to execution environment
            ExecutionError: Job failed during execution
            RunnerError: Cannot retrieve output

        Example:
            >>> async for line in runner.get_output(handle):
            ...     print(f"[JOB] {line}")
        """
        pass
        # Make this a generator to satisfy type checker
        yield ""  # pragma: no cover

    @abstractmethod
    async def retrieve_results(
        self,
        job_handle: JobHandle,
        dest: Path,
        cleanup: Optional[bool] = None
    ) -> None:
        """
        Retrieve all output files from a completed job.

        This method copies all output files (.out, .f9, .f98, etc.) from
        the execution environment to the specified destination directory.

        For local jobs, this may be a no-op if files are already in place.
        For remote jobs, this copies files via SSH/rsync.

        Args:
            job_handle: Job identifier to retrieve results from
            dest: Destination directory for output files
            cleanup: Whether to delete scratch files after retrieval
                     (default: use config.cleanup_on_success/cleanup_on_failure)

        Raises:
            ConnectionError: Cannot connect to execution environment
            ResourceError: Insufficient disk space for results
            RunnerError: Cannot retrieve files

        Example:
            >>> await runner.retrieve_results(handle, Path("results"))
            >>> # Files now available in results/output.out, results/fort.9, etc.
        """
        pass

    # -------------------------------------------------------------------------
    # Optional Methods - Can be overridden for optimization
    # -------------------------------------------------------------------------

    async def get_job_info(self, job_handle: JobHandle) -> JobInfo:
        """
        Get complete information about a job.

        This method provides a comprehensive snapshot of job state including
        status, timing, resource usage, and metadata. Default implementation
        constructs JobInfo from get_status(), but runners can override for
        more efficient bulk queries.

        Args:
            job_handle: Job identifier to query

        Returns:
            JobInfo: Complete job information

        Raises:
            ConnectionError: Cannot connect to execution environment
            RunnerError: Cannot retrieve job information
        """
        status = await self.get_status(job_handle)
        return JobInfo(
            job_handle=job_handle,
            status=status,
            work_dir=Path.cwd(),  # Subclasses should override
        )

    async def wait_for_completion(
        self,
        job_handle: JobHandle,
        poll_interval: float = 1.0,
        timeout: Optional[float] = None
    ) -> JobStatus:
        """
        Wait for a job to complete.

        This method polls job status until it reaches a terminal state
        (COMPLETED, FAILED, CANCELLED) or the timeout is exceeded.

        Args:
            job_handle: Job to wait for
            poll_interval: Seconds between status checks
            timeout: Maximum seconds to wait (None = wait forever)

        Returns:
            JobStatus: Final job status

        Raises:
            TimeoutError: Timeout exceeded before job completed
            ConnectionError: Lost connection during waiting
            RunnerError: Other waiting failures
        """
        from .exceptions import TimeoutError

        start_time = asyncio.get_event_loop().time()

        while True:
            status = await self.get_status(job_handle)

            # Check for terminal states
            if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                return status

            # Check timeout
            if timeout is not None:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= timeout:
                    raise TimeoutError(
                        f"Job did not complete within {timeout} seconds",
                        timeout_seconds=timeout,
                        operation="wait_for_completion"
                    )

            # Sleep before next poll
            await asyncio.sleep(poll_interval)

    # -------------------------------------------------------------------------
    # Resource Management
    # -------------------------------------------------------------------------

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit with cleanup."""
        await self.cleanup()

    async def connect(self) -> None:
        """
        Establish connection to execution environment.

        For local runners, this validates executables exist.
        For remote runners, this establishes SSH connections or
        authenticates with the scheduler.

        Subclasses should override to implement connection logic.
        """
        pass

    async def cleanup(self) -> None:
        """
        Clean up resources and close connections.

        This method should:
        - Close any open connections (SSH, scheduler)
        - Cancel any active background tasks
        - Release file locks and other resources

        Subclasses should override to implement cleanup logic.
        """
        # Cancel all active jobs
        for task in self._active_jobs.values():
            task.cancel()

        # Wait for cancellation to complete
        if self._active_jobs:
            await asyncio.gather(*self._active_jobs.values(), return_exceptions=True)

        self._active_jobs.clear()

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def acquire_slot(self):
        """
        Acquire a job execution slot.

        This enforces max_concurrent_jobs limit using an asyncio semaphore.
        Use as an async context manager:

            async with runner.acquire_slot():
                # Execute job
        """
        return self._semaphore

    def is_connected(self) -> bool:
        """
        Check if runner is connected and ready to submit jobs.

        Returns:
            bool: True if connected, False otherwise
        """
        return True  # Subclasses should override


# -------------------------------------------------------------------------
# Exception Classes
# -------------------------------------------------------------------------


class RunnerError(Exception):
    """Base exception for all runner errors."""
    pass


class JobSubmissionError(RunnerError):
    """Raised when job submission fails."""
    pass


class JobNotFoundError(RunnerError):
    """Raised when job handle is not found or invalid."""
    pass


class ConnectionError(RunnerError):
    """Raised when connection to execution backend fails."""
    pass


class CancellationError(RunnerError):
    """Raised when job cancellation fails."""
    pass


class ExecutionError(RunnerError):
    """Raised when job execution fails."""
    pass


class TimeoutError(RunnerError):
    """Raised when operation exceeds timeout limit."""

    def __init__(self, message: str, timeout_seconds: float, operation: str):
        super().__init__(message)
        self.timeout_seconds = timeout_seconds
        self.operation = operation


class ConfigurationError(RunnerError):
    """Raised when runner configuration is invalid."""
    pass


class ResourceError(RunnerError):
    """Raised when insufficient resources are available."""
    pass
