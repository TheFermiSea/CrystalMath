"""
Abstract base class for DFT job runners.

This module defines the interface that all job runners (local, SSH, SLURM)
must implement to provide consistent job execution capabilities across
different execution environments. Supports multiple DFT codes (CRYSTAL,
Quantum Espresso, VASP) through the DFTCodeConfig abstraction.

Design principles:
- Async/await throughout for non-blocking execution
- Generator-based output streaming for real-time monitoring
- Type-safe interfaces with comprehensive type hints
- Extensible configuration system for runner-specific settings
- Resource management and cleanup guarantees
- DFT code-agnostic through DFTCodeConfig abstraction
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import AsyncIterator, Any, Dict, Optional, NewType
import asyncio

from ..core.codes import DFTCode, get_code_config


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
        dft_code: DFT code to run (CRYSTAL, QUANTUM_ESPRESSO, VASP)
        scratch_dir: Base directory for temporary calculation files
        executable_path: Path to DFT executable (overrides code config default)
        default_threads: Default number of OpenMP threads
        max_concurrent_jobs: Maximum number of jobs to run simultaneously
        timeout_seconds: Default timeout for job operations (0 = no timeout)
        cleanup_on_success: Whether to delete scratch files after success
        cleanup_on_failure: Whether to delete scratch files after failure
        output_buffer_lines: Number of output lines to buffer before yielding
        extra_config: Runner-specific configuration parameters
    """

    name: str = "default"
    dft_code: DFTCode = DFTCode.CRYSTAL  # Default for backwards compatibility
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
    Structured results from a completed DFT job.

    This dataclass encapsulates the output of a DFT calculation,
    including energy, convergence status, and any errors or warnings.

    Attributes:
        success: Whether the job completed successfully
        final_energy: Final energy (units depend on DFT code: Hartree/Ry/eV)
        energy_unit: Unit of final_energy (e.g., "Hartree", "Ry", "eV")
        convergence_status: Convergence status string (CONVERGED, NOT_CONVERGED, etc.)
        errors: List of error messages encountered during execution
        warnings: List of warning messages
        metadata: Additional job-specific information (timings, system info, etc.)
    """

    success: bool
    final_energy: Optional[float]
    energy_unit: str = "Hartree"  # Default for backwards compatibility
    convergence_status: str = "UNKNOWN"
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


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
        Acquire a job execution slot (DEPRECATED - use acquire_slot_for_job).

        This enforces max_concurrent_jobs limit using an asyncio semaphore.
        Use as an async context manager:

            async with runner.acquire_slot():
                # Execute job

        WARNING: This releases the slot when the context exits, not when the
        job completes. For proper concurrency limiting, use acquire_slot_for_job()
        which spawns a background task to release the slot on job completion.
        """
        return self._semaphore

    async def acquire_slot_for_job(self, job_handle: str) -> None:
        """
        Acquire a job slot and hold it until job completion.

        This properly enforces max_concurrent_jobs by:
        1. Acquiring the semaphore immediately
        2. Spawning a background task that releases it when job completes

        Call this AFTER submit_job() returns a job_handle.

        Args:
            job_handle: The job handle to monitor for completion
        """
        await self._semaphore.acquire()

        # Spawn background task to release slot when job completes
        task = asyncio.create_task(
            self._monitor_and_release_slot(job_handle),
            name=f"slot_monitor_{job_handle}"
        )
        self._active_jobs[job_handle] = task

    async def _monitor_and_release_slot(self, job_handle: str) -> None:
        """
        Background task that releases the semaphore when job completes.

        Args:
            job_handle: Job to monitor
        """
        try:
            # Wait for job to reach terminal state
            await self.wait_for_completion(job_handle, poll_interval=5.0)
        except Exception:
            # Job monitoring failed, still release the slot
            pass
        finally:
            self._semaphore.release()
            # Remove from active jobs
            self._active_jobs.pop(job_handle, None)

    def is_connected(self) -> bool:
        """
        Check if runner is connected and ready to submit jobs.

        Returns:
            bool: True if connected, False otherwise
        """
        return True  # Subclasses should override


# Exception classes are defined in exceptions.py to avoid duplication.
# Import them from there for backwards compatibility or use:
#   from .exceptions import RunnerError, TimeoutError, etc.


class RemoteBaseRunner(BaseRunner):
    """
    Base class for remote job runners (SSH, SLURM).

    This class provides common functionality for runners that execute jobs
    on remote systems, including:
    - Connection management via ConnectionManager
    - DFT code configuration handling
    - SFTP-based file transfer (upload/download)
    - Remote directory management

    Subclasses (SSHRunner, SLURMRunner) implement the abstract methods
    with their specific execution semantics.

    Attributes:
        connection_manager: ConnectionManager instance for SSH pooling
        cluster_id: Database ID of the remote cluster
        dft_code: DFT code to run (CRYSTAL, QUANTUM_ESPRESSO, VASP)
        code_config: DFTCodeConfig for the selected DFT code
        remote_scratch_dir: Base directory for remote scratch space
    """

    def __init__(
        self,
        connection_manager: "ConnectionManager",  # Forward reference
        cluster_id: int,
        dft_code: DFTCode = DFTCode.CRYSTAL,
        remote_scratch_dir: Optional[Path] = None,
        config: Optional[RunnerConfig] = None,
    ):
        """
        Initialize the remote base runner.

        Args:
            connection_manager: ConnectionManager for SSH connections
            cluster_id: Database ID of the cluster to execute on
            dft_code: DFT code to run (default: CRYSTAL for backwards compatibility)
            remote_scratch_dir: Scratch directory on remote (default: ~/dft_jobs)
            config: Optional runner configuration
        """
        super().__init__(config)
        self.connection_manager = connection_manager
        self.cluster_id = cluster_id
        self.dft_code = dft_code
        self.code_config = get_code_config(dft_code)
        self.remote_scratch_dir = remote_scratch_dir or Path.home() / "dft_jobs"

    async def _upload_files_sftp(
        self,
        conn: Any,  # asyncssh.SSHClientConnection
        local_dir: Path,
        remote_dir: str,
        patterns: Optional[list[str]] = None,
    ) -> list[str]:
        """
        Upload files to remote machine via SFTP.

        This method uploads files matching the specified patterns (or
        code-specific defaults) from the local directory to the remote.

        Args:
            conn: SSH connection with SFTP support
            local_dir: Local directory containing files to upload
            remote_dir: Remote directory to upload to
            patterns: Optional list of glob patterns (default: code-specific)

        Returns:
            List of uploaded file names

        Raises:
            FileNotFoundError: If no matching files found
        """
        import logging
        logger = logging.getLogger(__name__)

        # Build file patterns from code config if not provided
        if patterns is None:
            patterns = []
            # Primary input file extensions
            for ext in self.code_config.input_extensions:
                patterns.append(f"*{ext}")
            # Auxiliary input files
            for ext in self.code_config.auxiliary_inputs.keys():
                patterns.append(f"*{ext}")

        files_to_upload = []
        for pattern in patterns:
            files_to_upload.extend(local_dir.glob(pattern))

        if not files_to_upload:
            raise FileNotFoundError(f"No input files found in {local_dir}")

        logger.info(f"Uploading {len(files_to_upload)} files to {remote_dir}")

        uploaded = []
        # Note: start_sftp_client() is a coroutine that must be awaited
        async with await conn.start_sftp_client() as sftp:
            for local_file in files_to_upload:
                remote_file = f"{remote_dir}/{local_file.name}"
                await sftp.put(str(local_file), remote_file)
                uploaded.append(local_file.name)
                logger.debug(f"Uploaded: {local_file.name}")

        logger.info("File upload complete")
        return uploaded

    async def _download_files_sftp(
        self,
        conn: Any,  # asyncssh.SSHClientConnection
        remote_dir: str,
        local_dir: Path,
        patterns: Optional[list[str]] = None,
    ) -> list[str]:
        """
        Download output files from remote machine via SFTP.

        This method downloads files matching the specified patterns from
        the remote directory to the local directory.

        Args:
            conn: SSH connection with SFTP support
            remote_dir: Remote directory containing output files
            local_dir: Local directory to download to
            patterns: Optional list of glob patterns (default: code-specific)

        Returns:
            List of downloaded file names
        """
        import fnmatch
        import logging
        import shlex
        logger = logging.getLogger(__name__)

        # Build output file patterns from code config if not provided
        if patterns is None:
            patterns = [
                "output.log",
                "output.out",
                ".exit_code",
                "slurm-*.out",
                "slurm-*.err",
                "*.xyz",
                "*.cif",
            ]
            # Add code-specific output files
            for fort_name, ext in self.code_config.auxiliary_outputs.items():
                patterns.append(fort_name)
                patterns.append(f"*{ext}")

        logger.info(f"Downloading output files from {remote_dir}")

        downloaded = []
        async with await conn.start_sftp_client() as sftp:
            # List files in remote directory
            remote_files = await sftp.listdir(remote_dir)

            for filename in remote_files:
                # Check if file matches our patterns using proper glob matching
                should_download = any(
                    fnmatch.fnmatch(filename, pattern)
                    for pattern in patterns
                )

                if should_download:
                    # Security: Validate filename to prevent path traversal attacks
                    if "/" in filename or "\\" in filename or filename in (".", ".."):
                        logger.warning(f"Skipping file with suspicious name: {filename}")
                        continue

                    remote_path = f"{remote_dir}/{filename}"
                    local_path = local_dir / filename

                    try:
                        await sftp.get(remote_path, str(local_path))
                        downloaded.append(filename)
                        logger.debug(f"Downloaded: {filename}")
                    except Exception as e:
                        logger.warning(f"Failed to download {filename}: {e}")

        logger.info(f"File download complete ({len(downloaded)} files)")
        return downloaded

    async def _create_remote_directory(
        self,
        conn: Any,  # asyncssh.SSHClientConnection
        remote_dir: str,
    ) -> None:
        """
        Create a directory on the remote machine.

        Args:
            conn: SSH connection
            remote_dir: Remote directory path to create
        """
        import shlex
        mkdir_cmd = f"mkdir -p {shlex.quote(remote_dir)}"
        await conn.run(mkdir_cmd, check=True)

    async def _remove_remote_directory(
        self,
        conn: Any,  # asyncssh.SSHClientConnection
        remote_dir: str,
    ) -> None:
        """
        Remove a directory on the remote machine.

        Args:
            conn: SSH connection
            remote_dir: Remote directory path to remove
        """
        import shlex
        import logging
        logger = logging.getLogger(__name__)
        cleanup_cmd = f"rm -rf {shlex.quote(remote_dir)}"
        await conn.run(cleanup_cmd, check=False)
        logger.info(f"Removed remote directory: {remote_dir}")
