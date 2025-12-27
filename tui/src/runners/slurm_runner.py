"""
SLURM Runner for batch job submission to HPC clusters.

This module provides a SLURM-based runner that submits DFT jobs
(CRYSTAL, Quantum Espresso, VASP, etc.) to HPC clusters with batch scheduling.
It handles:
- Dynamic SLURM script generation for multiple DFT codes
- Job submission via sbatch
- Non-blocking status monitoring with squeue
- Job arrays for parameter sweeps
- Automatic result retrieval
"""

import asyncio
import re
import logging
import shlex
from pathlib import Path
from typing import Any, AsyncIterator, Optional, Dict, List, Tuple
from dataclasses import dataclass, field
from enum import Enum

from .base import RemoteBaseRunner, JobResult, JobHandle, JobStatus, RunnerConfig
from .exceptions import SLURMRunnerError
from .slurm_templates import SLURMTemplateGenerator, SLURMTemplateParams, SLURMTemplateValidationError
from ..core.codes import DFTCode, get_code_config, get_parser, InvocationStyle
from ..core.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


class SLURMJobState(Enum):
    """SLURM job states as reported by squeue."""
    PENDING = "PENDING"  # Job waiting in queue
    RUNNING = "RUNNING"  # Job is executing
    COMPLETED = "COMPLETED"  # Job finished successfully
    FAILED = "FAILED"  # Job failed
    CANCELLED = "CANCELLED"  # Job was cancelled
    TIMEOUT = "TIMEOUT"  # Job exceeded time limit
    NODE_FAIL = "NODE_FAIL"  # Node failure
    OUT_OF_MEMORY = "OUT_OF_MEMORY"  # Job ran out of memory
    UNKNOWN = "UNKNOWN"  # State could not be determined


@dataclass
class SLURMJobConfig:
    """Configuration for a SLURM job submission."""
    job_name: str
    nodes: int = 1
    ntasks: int = 1
    cpus_per_task: int = 4
    time_limit: str = "24:00:00"  # HH:MM:SS format
    partition: Optional[str] = None
    memory: Optional[str] = None  # e.g., "32GB"
    account: Optional[str] = None
    qos: Optional[str] = None
    email: Optional[str] = None
    email_type: Optional[str] = None  # e.g., "BEGIN,END,FAIL"
    dependencies: List[str] = field(default_factory=list)  # Job IDs to depend on
    array: Optional[str] = None  # Array specification, e.g., "1-10" or "1,3,5"
    constraint: Optional[str] = None  # Node constraints
    exclusive: bool = False  # Request exclusive node access
    modules: List[str] = field(default_factory=lambda: ["crystal23"])
    environment_setup: str = ""  # Additional environment setup commands


# SLURMRunnerError is imported from exceptions.py
# These are SLURM-specific sub-exceptions


class SLURMSubmissionError(SLURMRunnerError):
    """Raised when SLURM job submission fails."""
    pass


class SLURMStatusError(SLURMRunnerError):
    """Raised when SLURM status checking fails."""
    pass


class SLURMValidationError(SLURMRunnerError):
    """Raised when SLURM input validation fails."""
    pass


class SLURMRunner(RemoteBaseRunner):
    """
    Execute DFT jobs via SLURM batch system on HPC clusters.

    This runner supports multiple DFT codes through the DFTCodeConfig abstraction:
    - CRYSTAL23: stdin invocation with cry23.bashrc environment
    - Quantum Espresso: flag invocation with QE environment
    - VASP: cwd invocation with VASP environment

    Features:
    - Generates SLURM submission scripts dynamically for any DFT code
    - Submits jobs using sbatch via SSH
    - Polls job status with squeue
    - Downloads results when job completes
    - Supports job arrays for parameter sweeps
    - Handles job dependencies for workflows

    Attributes:
        connection_manager: SSH connection manager
        cluster_id: ID of the cluster to submit jobs to
        dft_code: DFT code to run (CRYSTAL, QUANTUM_ESPRESSO, VASP)
        code_config: DFTCodeConfig for the selected DFT code
        default_config: Default SLURM job configuration
        poll_interval: Seconds between status checks (default: 30)
    """

    def __init__(
        self,
        connection_manager: ConnectionManager,
        cluster_id: int,
        dft_code: DFTCode = DFTCode.CRYSTAL,
        default_config: Optional[SLURMJobConfig] = None,
        poll_interval: int = 30,
        remote_scratch_base: str = "/scratch/dft_jobs"
    ):
        """
        Initialize the SLURM Runner.

        Args:
            connection_manager: ConnectionManager instance for SSH
            cluster_id: Database ID of the cluster
            dft_code: DFT code to run (default: CRYSTAL for backwards compatibility)
            default_config: Default SLURM job configuration
            poll_interval: Seconds to wait between status checks
            remote_scratch_base: Base directory for remote scratch space
        """
        # Call parent class constructor
        super().__init__(
            connection_manager=connection_manager,
            cluster_id=cluster_id,
            dft_code=dft_code,
            remote_scratch_dir=Path(remote_scratch_base),
        )

        self.default_config = default_config or SLURMJobConfig(
            job_name=f"{self.code_config.name}_job",
            modules=[self.code_config.name]
        )
        self.poll_interval = poll_interval
        self.remote_scratch_base = remote_scratch_base

        # Track job ID mappings: our job_id -> SLURM job_id
        self._slurm_job_ids: Dict[int, str] = {}

        # Track job states
        self._job_states: Dict[int, SLURMJobState] = {}

        # Initialize template generator for SLURM scripts
        self._template_generator = SLURMTemplateGenerator(dft_code=dft_code)

        logger.info(
            f"Initialized SLURMRunner for cluster {cluster_id}, "
            f"dft_code={self.code_config.display_name}"
        )

    # -------------------------------------------------------------------------
    # BaseRunner Abstract Method Implementations
    # -------------------------------------------------------------------------

    async def submit_job(
        self,
        job_id: int,
        input_file: Path,
        work_dir: Path,
        threads: Optional[int] = None,
        **kwargs
    ) -> JobHandle:
        """
        Submit a job to SLURM and return a job handle.

        Args:
            job_id: Database ID of the job for tracking
            input_file: Path to the input file (.d12, .in, INCAR, etc.)
            work_dir: Path to the job's working directory
            threads: Number of CPUs per task (overrides default)
            **kwargs: Additional SLURM configuration options
                - config: SLURMJobConfig instance
                - nodes: Number of nodes
                - ntasks: Number of MPI tasks
                - partition: SLURM partition name
                - time_limit: Time limit (HH:MM:SS)

        Returns:
            JobHandle: Opaque identifier in format "slurm:{cluster_id}:{slurm_job_id}:{remote_dir}"

        Raises:
            SLURMSubmissionError: If job submission fails
            SLURMValidationError: If input validation fails
        """
        # Acquire slot to enforce max_concurrent_jobs limit
        async with self.acquire_slot():
            # Validate input file exists
            if not input_file.exists():
                raise SLURMSubmissionError(f"Input file not found: {input_file}")

            # Get or create SLURM config
            config: SLURMJobConfig = kwargs.get("config") or SLURMJobConfig(
                job_name=f"{self.code_config.name}_job_{job_id}",
                modules=[self.code_config.name]
            )

            # Apply kwargs overrides
            if threads:
                config.cpus_per_task = threads
            if "nodes" in kwargs:
                config.nodes = kwargs["nodes"]
            if "ntasks" in kwargs:
                config.ntasks = kwargs["ntasks"]
            if "partition" in kwargs:
                config.partition = kwargs["partition"]
            if "time_limit" in kwargs:
                config.time_limit = kwargs["time_limit"]

            # Setup remote work directory
            remote_work_dir = f"{self.remote_scratch_base}/{job_id}_{work_dir.name}"

            try:
                # Generate SLURM script
                script_content = self._generate_slurm_script(config, remote_work_dir)

                # Write script locally
                script_file = work_dir / "job.slurm"
                script_file.write_text(script_content)

                # Create remote directory and transfer files
                async with self.connection_manager.get_connection(self.cluster_id) as conn:
                    # Create remote directory
                    await conn.run(f"mkdir -p {shlex.quote(remote_work_dir)}")

                    # Transfer files using SFTP
                    # Note: start_sftp_client() is a coroutine that must be awaited
                    async with await conn.start_sftp_client() as sftp:
                        # Upload input file with appropriate name for DFT code
                        remote_input_name = self._get_remote_input_name(input_file)
                        await sftp.put(str(input_file), f"{remote_work_dir}/{remote_input_name}")

                        # Upload SLURM script
                        await sftp.put(str(script_file), f"{remote_work_dir}/job.slurm")

                        # Upload any additional files (.gui, .f9, etc.)
                        for file_path in work_dir.glob("*"):
                            if file_path.is_file() and file_path.suffix in [".gui", ".f9", ".f20"]:
                                await sftp.put(str(file_path), f"{remote_work_dir}/{file_path.name}")

                    # Submit job
                    result = await conn.run(
                        f"cd {shlex.quote(remote_work_dir)} && sbatch job.slurm",
                        check=False
                    )

                    if result.exit_status != 0:
                        raise SLURMSubmissionError(f"sbatch failed: {result.stderr}")

                    # Parse SLURM job ID from sbatch output
                    slurm_job_id = self._parse_job_id(result.stdout)
                    if not slurm_job_id:
                        raise SLURMSubmissionError(
                            f"Could not parse job ID from sbatch output: {result.stdout}"
                        )

                    # Track job mappings
                    self._slurm_job_ids[job_id] = slurm_job_id
                    self._job_states[job_id] = SLURMJobState.PENDING

                    # Return handle in format: slurm:{cluster_id}:{slurm_job_id}:{remote_dir}
                    job_handle = JobHandle(f"slurm:{self.cluster_id}:{slurm_job_id}:{remote_work_dir}")

                    logger.info(f"Submitted SLURM job {slurm_job_id} for job_id={job_id}")
                    return job_handle

            except SLURMSubmissionError:
                raise
            except Exception as e:
                logger.error(f"SLURM job submission failed: {e}")
                raise SLURMSubmissionError(f"Job submission failed: {e}") from e

    def _get_remote_input_name(self, input_file: Path) -> str:
        """Get the appropriate remote input file name for the DFT code."""
        # For CRYSTAL, use input.d12 convention
        if self.dft_code == DFTCode.CRYSTAL:
            return "input.d12"
        # For other codes, preserve the original name
        return input_file.name

    async def get_status(self, job_handle: JobHandle) -> JobStatus:
        """
        Query the current status of a submitted SLURM job.

        Args:
            job_handle: Job identifier returned by submit_job()

        Returns:
            JobStatus: Current status of the job

        Raises:
            SLURMStatusError: If status cannot be determined
        """
        # Parse handle: slurm:{cluster_id}:{slurm_job_id}:{remote_dir}
        cluster_id, slurm_job_id, _ = self._parse_job_handle(job_handle)

        try:
            async with self.connection_manager.get_connection(cluster_id) as conn:
                slurm_state, _ = await self._check_status(conn, slurm_job_id)

                # Map SLURMJobState to JobStatus
                return self._slurm_state_to_job_status(slurm_state)

        except Exception as e:
            logger.error(f"Failed to get status for {job_handle}: {e}")
            return JobStatus.UNKNOWN

    async def cancel_job(self, job_handle: JobHandle) -> bool:
        """
        Cancel a running or queued SLURM job.

        Args:
            job_handle: Job identifier to cancel

        Returns:
            bool: True if job was successfully cancelled, False otherwise

        Raises:
            SLURMRunnerError: If cancellation fails unexpectedly
        """
        # Parse handle
        cluster_id, slurm_job_id, _ = self._parse_job_handle(job_handle)

        try:
            async with self.connection_manager.get_connection(cluster_id) as conn:
                result = await conn.run(f"scancel {shlex.quote(slurm_job_id)}", check=False)

                if result.exit_status == 0:
                    logger.info(f"Cancelled SLURM job {slurm_job_id}")
                    return True
                else:
                    logger.warning(f"scancel failed for {slurm_job_id}: {result.stderr}")
                    return False

        except Exception as e:
            logger.error(f"Failed to cancel job {slurm_job_id}: {e}")
            return False

    async def get_output(self, job_handle: JobHandle) -> AsyncIterator[str]:
        """
        Stream job output in real-time as an async generator.

        This method tails the SLURM output file on the remote cluster.

        Args:
            job_handle: Job identifier to stream output from

        Yields:
            str: Output lines from the job

        Raises:
            SLURMRunnerError: If output streaming fails
        """
        # Parse handle
        cluster_id, slurm_job_id, remote_dir = self._parse_job_handle(job_handle)

        try:
            async with self.connection_manager.get_connection(cluster_id) as conn:
                # Find the SLURM output file
                output_file = f"{remote_dir}/slurm-{slurm_job_id}.out"

                # Wait for the file to exist
                for _ in range(30):  # Wait up to 30 seconds
                    result = await conn.run(f"test -f {shlex.quote(output_file)}", check=False)
                    if result.exit_status == 0:
                        break
                    await asyncio.sleep(1)
                else:
                    yield f"Waiting for output file: {output_file}"

                # Track file position for incremental reads
                last_size = 0

                while True:
                    # Check job status
                    status = await self.get_status(job_handle)

                    # Read new content from file
                    result = await conn.run(
                        f"tail -c +{last_size + 1} {shlex.quote(output_file)} 2>/dev/null",
                        check=False
                    )

                    if result.stdout:
                        for line in result.stdout.splitlines():
                            yield line
                        last_size += len(result.stdout.encode())

                    # Check for terminal states
                    if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                        # Read any remaining output
                        result = await conn.run(
                            f"tail -c +{last_size + 1} {shlex.quote(output_file)} 2>/dev/null",
                            check=False
                        )
                        if result.stdout:
                            for line in result.stdout.splitlines():
                                yield line
                        break

                    await asyncio.sleep(self.poll_interval)

        except Exception as e:
            logger.error(f"Failed to stream output for {job_handle}: {e}")
            raise SLURMRunnerError(f"Output streaming failed: {e}") from e

    async def retrieve_results(
        self,
        job_handle: JobHandle,
        dest: Path,
        cleanup: Optional[bool] = None
    ) -> None:
        """
        Retrieve all output files from a completed SLURM job.

        Args:
            job_handle: Job identifier to retrieve results from
            dest: Destination directory for output files
            cleanup: Whether to delete remote scratch files after retrieval

        Raises:
            SLURMRunnerError: If result retrieval fails
        """
        # Parse handle
        cluster_id, slurm_job_id, remote_dir = self._parse_job_handle(job_handle)

        try:
            async with self.connection_manager.get_connection(cluster_id) as conn:
                await self._download_results(conn, remote_dir, dest)

                # Clean up remote directory if requested
                if cleanup:
                    await conn.run(f"rm -rf {shlex.quote(remote_dir)}", check=False)
                    logger.info(f"Cleaned up remote directory: {remote_dir}")

        except Exception as e:
            logger.error(f"Failed to retrieve results for {job_handle}: {e}")
            raise SLURMRunnerError(f"Result retrieval failed: {e}") from e

    def _parse_job_handle(self, job_handle: JobHandle) -> Tuple[int, str, str]:
        """
        Parse a SLURM job handle into its components.

        Args:
            job_handle: Handle in format "slurm:{cluster_id}:{slurm_job_id}:{remote_dir}"

        Returns:
            Tuple of (cluster_id, slurm_job_id, remote_dir)

        Raises:
            ValueError: If handle format is invalid
        """
        parts = str(job_handle).split(":", 3)
        if len(parts) != 4 or parts[0] != "slurm":
            raise ValueError(f"Invalid SLURM job handle format: {job_handle}")

        return int(parts[1]), parts[2], parts[3]

    def _slurm_state_to_job_status(self, slurm_state: SLURMJobState) -> JobStatus:
        """Map SLURMJobState to BaseRunner JobStatus."""
        state_map = {
            SLURMJobState.PENDING: JobStatus.QUEUED,
            SLURMJobState.RUNNING: JobStatus.RUNNING,
            SLURMJobState.COMPLETED: JobStatus.COMPLETED,
            SLURMJobState.FAILED: JobStatus.FAILED,
            SLURMJobState.CANCELLED: JobStatus.CANCELLED,
            SLURMJobState.TIMEOUT: JobStatus.FAILED,
            SLURMJobState.NODE_FAIL: JobStatus.FAILED,
            SLURMJobState.OUT_OF_MEMORY: JobStatus.FAILED,
            SLURMJobState.UNKNOWN: JobStatus.UNKNOWN,
        }
        return state_map.get(slurm_state, JobStatus.UNKNOWN)

    # -------------------------------------------------------------------------
    # Legacy Method (deprecated - use submit_job + get_output instead)
    # -------------------------------------------------------------------------

    async def run_job(
        self,
        job_id: int,
        work_dir: Path,
        threads: Optional[int] = None,
        config: Optional[SLURMJobConfig] = None
    ) -> AsyncIterator[str]:
        """
        Submit a CRYSTAL job to SLURM and monitor until completion.

        Args:
            job_id: Database ID of the job
            work_dir: Local directory containing input.d12
            threads: Number of cores/threads to use (overrides config.cpus_per_task)
            config: Custom SLURM configuration (uses default if None)

        Yields:
            Status messages and output lines as job executes

        Raises:
            SLURMSubmissionError: If job submission fails
            SLURMStatusError: If status monitoring fails
        """
        # Validate input file
        input_file = work_dir / "input.d12"
        if not input_file.exists():
            raise SLURMSubmissionError(f"Input file not found: {input_file}")

        # Merge configuration
        job_config = config or self.default_config
        if threads:
            job_config.cpus_per_task = threads

        # Setup remote work directory
        remote_work_dir = f"{self.remote_scratch_base}/{job_id}_{work_dir.name}"

        yield f"Preparing job submission to SLURM cluster"
        yield f"Remote directory: {remote_work_dir}"

        try:
            # Generate SLURM script
            script_content = self._generate_slurm_script(
                job_config,
                remote_work_dir
            )

            # Write script locally
            script_file = work_dir / "job.slurm"
            script_file.write_text(script_content)
            yield f"Generated SLURM script: {script_file.name}"

            # Create remote directory and transfer files
            yield "Transferring files to cluster..."
            async with self.connection_manager.get_connection(self.cluster_id) as conn:
                # Create remote directory
                await conn.run(f"mkdir -p {shlex.quote(remote_work_dir)}")

                # Transfer files using SFTP
                # Note: start_sftp_client() is a coroutine that must be awaited
                async with await conn.start_sftp_client() as sftp:
                    # Upload input file
                    await sftp.put(str(input_file), f"{remote_work_dir}/input.d12")
                    yield f"  Uploaded: input.d12"

                    # Upload SLURM script
                    await sftp.put(str(script_file), f"{remote_work_dir}/job.slurm")
                    yield f"  Uploaded: job.slurm"

                    # Upload any additional files (.gui, .f9, etc.)
                    for file_path in work_dir.glob("*"):
                        if file_path.is_file() and file_path.suffix in [".gui", ".f9", ".f20"]:
                            remote_file = f"{remote_work_dir}/{file_path.name}"
                            await sftp.put(str(file_path), remote_file)
                            yield f"  Uploaded: {file_path.name}"

                yield "File transfer complete"

                # Submit job
                yield "Submitting job to SLURM..."
                result = await conn.run(
                    f"cd {shlex.quote(remote_work_dir)} && sbatch job.slurm",
                    check=False
                )

                if result.exit_status != 0:
                    raise SLURMSubmissionError(
                        f"sbatch failed: {result.stderr}"
                    )

                # Parse SLURM job ID from sbatch output
                slurm_job_id = self._parse_job_id(result.stdout)
                if not slurm_job_id:
                    raise SLURMSubmissionError(
                        f"Could not parse job ID from sbatch output: {result.stdout}"
                    )

                self._slurm_job_ids[job_id] = slurm_job_id
                self._job_states[job_id] = SLURMJobState.PENDING

                yield f"Job submitted successfully"
                yield f"SLURM Job ID: {slurm_job_id}"
                yield f"Status: PENDING"

                # Monitor job status
                async for status_line in self._monitor_job(job_id, conn):
                    yield status_line

                # Download results if job completed successfully
                final_state = self._job_states.get(job_id)
                if final_state == SLURMJobState.COMPLETED:
                    yield "\nDownloading results..."
                    await self._download_results(conn, remote_work_dir, work_dir)
                    yield "Results downloaded successfully"
                    yield "\n✓ Job completed successfully"

                elif final_state == SLURMJobState.FAILED:
                    yield "\n✗ Job failed"
                    # Still try to download output for debugging
                    yield "Downloading logs for debugging..."
                    await self._download_results(conn, remote_work_dir, work_dir)

                elif final_state == SLURMJobState.CANCELLED:
                    yield "\n⚠ Job was cancelled"

                elif final_state == SLURMJobState.TIMEOUT:
                    yield "\n⚠ Job exceeded time limit"

                elif final_state == SLURMJobState.OUT_OF_MEMORY:
                    yield "\n⚠ Job ran out of memory"
                    yield f"Consider increasing memory allocation in SLURM config"

        except Exception as e:
            logger.error(f"SLURM job execution failed: {e}")
            raise SLURMRunnerError(f"Job execution failed: {e}") from e

    async def stop_job(self, job_id: int) -> bool:
        """
        Cancel a running SLURM job.

        .. deprecated:: Use cancel_job(job_handle) instead.
            This method is provided for backwards compatibility.

        Args:
            job_id: Database ID of the job to cancel

        Returns:
            True if job was cancelled, False if not running or cancel failed
        """
        import warnings
        warnings.warn(
            "stop_job(job_id) is deprecated. Use cancel_job(job_handle) instead.",
            DeprecationWarning,
            stacklevel=2
        )

        slurm_job_id = self._slurm_job_ids.get(job_id)
        if not slurm_job_id:
            logger.warning(f"No SLURM job ID found for job {job_id}")
            return False

        try:
            async with self.connection_manager.get_connection(self.cluster_id) as conn:
                result = await conn.run(f"scancel {shlex.quote(slurm_job_id)}", check=False)

                if result.exit_status == 0:
                    self._job_states[job_id] = SLURMJobState.CANCELLED
                    logger.info(f"Cancelled SLURM job {slurm_job_id}")
                    return True
                else:
                    logger.warning(
                        f"scancel failed for {slurm_job_id}: {result.stderr}"
                    )
                    return False

        except Exception as e:
            logger.error(f"Failed to cancel job {slurm_job_id}: {e}")
            return False

    def is_job_running(self, job_id: int) -> bool:
        """
        Check if a SLURM job is currently running or pending.

        Args:
            job_id: Database ID of the job

        Returns:
            True if job is pending or running, False otherwise
        """
        state = self._job_states.get(job_id)
        return state in [SLURMJobState.PENDING, SLURMJobState.RUNNING]

    def get_slurm_job_id(self, job_id: int) -> Optional[str]:
        """
        Get the SLURM job ID for a given database job ID.

        Args:
            job_id: Database ID of the job

        Returns:
            SLURM job ID string if found, None otherwise
        """
        return self._slurm_job_ids.get(job_id)

    def get_job_state(self, job_id: int) -> Optional[SLURMJobState]:
        """
        Get the current SLURM state for a job.

        Args:
            job_id: Database ID of the job

        Returns:
            SLURMJobState if known, None otherwise
        """
        return self._job_states.get(job_id)

    # -------------------------------------------------------------------------
    # Queue Management Methods (for SLURMQueueWidget)
    # -------------------------------------------------------------------------

    async def get_queue_status(
        self,
        user_only: bool = True,
        partition: Optional[str] = None,
        states: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get SLURM queue status for the cluster.

        Queries squeue to get all jobs matching the filter criteria.
        Uses JSON output for modern SLURM (21.08+), falls back to
        formatted output for older versions.

        Args:
            user_only: If True, only show current user's jobs
            partition: Filter by partition name (optional)
            states: Filter by job states (optional, e.g., ["RUNNING", "PENDING"])

        Returns:
            List of job dictionaries with standardized keys:
            - job_id: int
            - name: str
            - user: str
            - state: str
            - state_reason: str (why pending)
            - partition: str
            - nodes: int
            - node_list: str
            - time_used: str
            - time_limit: str
            - tres: str (for GPU info, e.g., "cpu=32,gres/gpu=1")
            - submit_time: str
            - start_time: str
        """
        try:
            async with self.connection_manager.get_connection(self.cluster_id) as conn:
                # Build squeue command
                cmd_parts = ["squeue"]

                if user_only:
                    cmd_parts.append("--me")

                if partition:
                    cmd_parts.extend(["-p", shlex.quote(partition)])

                if states:
                    # Validate states against allowed SLURM job states
                    allowed_states = {
                        "RUNNING", "PENDING", "COMPLETING", "COMPLETED",
                        "FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL",
                        "PREEMPTED", "SUSPENDED", "CONFIGURING", "BOOT_FAIL",
                        "DEADLINE", "OUT_OF_MEMORY", "REQUEUED", "RESIZING",
                        "REVOKED", "SIGNALING", "SPECIAL_EXIT", "STAGE_OUT",
                    }
                    valid_states = [s for s in states if s.upper() in allowed_states]
                    if valid_states:
                        state_str = ",".join(valid_states)
                        cmd_parts.extend(["-t", shlex.quote(state_str)])

                # Try JSON format first (SLURM >= 21.08)
                json_cmd = " ".join(cmd_parts) + " --json"
                result = await conn.run(json_cmd, check=False)

                if result.exit_status == 0 and result.stdout.strip():
                    try:
                        import json
                        data = json.loads(result.stdout)
                        jobs = data.get("jobs", [])
                        return self._parse_squeue_json(jobs)
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning(f"Failed to parse squeue JSON: {e}")

                # Fallback to formatted output for older clusters
                # Format: job_id|name|user|state|reason|partition|nodes|nodelist|time|timelimit
                format_str = "%i|%j|%u|%T|%r|%P|%D|%N|%M|%l"
                fallback_cmd = " ".join(cmd_parts) + f" -h -o '{format_str}'"
                result = await conn.run(fallback_cmd, check=False)

                if result.exit_status == 0:
                    return self._parse_squeue_formatted(result.stdout)

                logger.warning(f"squeue failed: {result.stderr}")
                return []

        except Exception as e:
            logger.error(f"Failed to get queue status: {e}")
            return []

    def _parse_squeue_json(self, jobs: List[Dict]) -> List[Dict[str, Any]]:
        """Parse squeue --json output into standardized format."""
        result = []
        for j in jobs:
            # Handle job_state which may be string or dict in different SLURM versions
            state = j.get("job_state", "UNKNOWN")
            if isinstance(state, dict):
                state = state.get("current", ["UNKNOWN"])[0] if isinstance(state.get("current"), list) else str(state)
            elif isinstance(state, list):
                state = state[0] if state else "UNKNOWN"

            # Extract node_count from wrapped structure (SLURM 21.08+)
            node_count = j.get("node_count", 1)
            if isinstance(node_count, dict):
                node_count = node_count.get("number", 1)

            # Calculate elapsed time from start_time (Unix timestamp)
            import time as time_module
            start_time_obj = j.get("start_time", {})
            elapsed = 0
            if isinstance(start_time_obj, dict) and start_time_obj.get("set"):
                start_ts = start_time_obj.get("number", 0)
                if start_ts > 0:
                    elapsed = int(time_module.time()) - start_ts
                    if elapsed < 0:
                        elapsed = 0

            time_limit_obj = j.get("time_limit", 0)
            time_limit = 0
            if isinstance(time_limit_obj, dict):
                time_limit = time_limit_obj.get("number", 0)
            elif isinstance(time_limit_obj, int):
                time_limit = time_limit_obj

            # Get TRES string (GPU allocation info)
            tres_alloc = j.get("tres_alloc_str", "") or j.get("tres_req_str", "")
            # Also check gres field for GPU info
            gres = j.get("gres_detail", [])
            if isinstance(gres, list) and gres:
                gres_str = ",".join(gres)
            else:
                gres_str = ""

            result.append({
                "job_id": j.get("job_id"),
                "name": str(j.get("name", ""))[:50],  # Truncate long names
                "user": j.get("user_name", j.get("user", "")),
                "state": str(state),
                "state_reason": j.get("state_reason", ""),
                "partition": j.get("partition", ""),
                "nodes": node_count,
                "node_list": j.get("nodes", ""),
                "time_used": self._format_time(elapsed),
                "time_limit": self._format_time(time_limit * 60),  # time_limit in minutes
                "tres": tres_alloc,
                "submit_time": j.get("submit_time", ""),
                "start_time": j.get("start_time", ""),
                "gpus": self._parse_gpu_count(tres_alloc) or self._parse_gpu_count(gres_str),
            })
        return result

    def _parse_squeue_formatted(self, output: str) -> List[Dict[str, Any]]:
        """Parse formatted squeue output into standardized format."""
        result = []
        for line in output.strip().splitlines():
            if not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 10:
                result.append({
                    "job_id": int(parts[0]) if parts[0].isdigit() else parts[0],
                    "name": parts[1][:50],
                    "user": parts[2],
                    "state": parts[3],
                    "state_reason": parts[4] if parts[4] != "(null)" else "",
                    "partition": parts[5],
                    "nodes": int(parts[6]) if parts[6].isdigit() else 1,
                    "node_list": parts[7],
                    "time_used": parts[8],
                    "time_limit": parts[9],
                    "tres": "",  # Not available in compact format
                    "submit_time": "",
                    "start_time": "",
                    "gpus": 0,
                })
        return result

    @staticmethod
    def _format_time(seconds: int) -> str:
        """Format seconds into HH:MM:SS or D-HH:MM:SS."""
        if not seconds or seconds < 0:
            return "0:00"
        days, remainder = divmod(int(seconds), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, secs = divmod(remainder, 60)
        if days > 0:
            return f"{days}-{hours:02d}:{minutes:02d}:{secs:02d}"
        elif hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"

    @staticmethod
    def _parse_gpu_count(tres_str: str) -> int:
        """Extract GPU count from TRES allocation string."""
        if not tres_str:
            return 0
        # Match patterns like "gres/gpu=2" or "gres/gpu:v100s=1"
        match = re.search(r'gres/gpu[^=]*=(\d+)', tres_str)
        return int(match.group(1)) if match else 0

    async def get_job_details(self, slurm_job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information for a specific SLURM job.

        Uses scontrol show job for comprehensive job details.

        Args:
            slurm_job_id: SLURM job ID

        Returns:
            Dictionary with full job details, or None if not found
        """
        try:
            async with self.connection_manager.get_connection(self.cluster_id) as conn:
                # Try JSON format first
                result = await conn.run(
                    f"scontrol show job {shlex.quote(slurm_job_id)} --json",
                    check=False
                )

                if result.exit_status == 0 and result.stdout.strip():
                    try:
                        import json
                        data = json.loads(result.stdout)
                        jobs = data.get("jobs", [])
                        if jobs:
                            return jobs[0]
                    except json.JSONDecodeError:
                        pass

                # Fallback to text format
                result = await conn.run(
                    f"scontrol show job {shlex.quote(slurm_job_id)}",
                    check=False
                )

                if result.exit_status == 0:
                    return self._parse_scontrol_output(result.stdout)

                return None

        except Exception as e:
            logger.error(f"Failed to get job details for {slurm_job_id}: {e}")
            return None

    def _parse_scontrol_output(self, output: str) -> Dict[str, str]:
        """Parse scontrol show job output into a dictionary."""
        result = {}
        # scontrol output is space-separated key=value pairs
        for line in output.splitlines():
            for part in line.split():
                if "=" in part:
                    key, _, value = part.partition("=")
                    result[key] = value
        return result

    @staticmethod
    def _expand_slurm_path(path: str, job_id: str, job_name: str = "job") -> str:
        """
        Expand SLURM filename placeholders in output path.

        Common placeholders:
            %j - job ID
            %x - job name
            %A - array job ID (same as %j for non-array)
            %a - array task ID
            %u - username
            %N - short hostname
        """
        if not path:
            return path

        # Expand common placeholders
        expanded = path.replace("%j", str(job_id))
        expanded = expanded.replace("%x", job_name)
        expanded = expanded.replace("%A", str(job_id))  # Array job ID fallback
        # %a, %u, %N would need more context - leave them for now

        return expanded

    async def get_job_logs(
        self,
        slurm_job_id: str,
        log_type: str = "stdout",
        tail_lines: int = 100
    ) -> AsyncIterator[str]:
        """
        Stream job log output (stdout or stderr).

        Args:
            slurm_job_id: SLURM job ID
            log_type: "stdout" or "stderr"
            tail_lines: Number of lines to tail (default 100)

        Yields:
            Log lines from the job output file
        """
        try:
            async with self.connection_manager.get_connection(self.cluster_id) as conn:
                log_path = None

                # Try scontrol first (for running/recent jobs)
                details = await self.get_job_details(slurm_job_id)
                job_name = details.get("JobName", details.get("name", "job")) if details else "job"

                if details:
                    if log_type == "stderr":
                        log_path = details.get("StdErr", details.get("stderr", ""))
                    else:
                        log_path = details.get("StdOut", details.get("stdout", ""))

                    # Expand SLURM placeholders in path
                    if log_path:
                        log_path = self._expand_slurm_path(log_path, slurm_job_id, job_name)

                # If no path from scontrol, try sacct (for completed jobs)
                if not log_path or log_path == "(null)" or log_path == "":
                    field = "StdErr" if log_type == "stderr" else "StdOut"
                    sacct_cmd = f"sacct -j {shlex.quote(slurm_job_id)} --format={field},WorkDir,JobName --noheader --parsable2 2>/dev/null | head -1"
                    result = await conn.run(sacct_cmd, check=False)
                    if result.exit_status == 0 and result.stdout.strip():
                        parts = result.stdout.strip().split("|")
                        sacct_job_name = parts[2] if len(parts) >= 3 else job_name
                        if len(parts) >= 1 and parts[0] and parts[0] != "(null)":
                            log_path = self._expand_slurm_path(parts[0], slurm_job_id, sacct_job_name)
                        elif len(parts) >= 2 and parts[1]:
                            # Use WorkDir to construct default path
                            work_dir = parts[1]
                            ext = ".err" if log_type == "stderr" else ".out"
                            log_path = f"{work_dir}/slurm-{slurm_job_id}{ext}"

                # Still no path? Try common patterns in home directory
                if not log_path or log_path == "(null)" or log_path == "":
                    # Get user's home directory
                    home_result = await conn.run("echo $HOME", check=False)
                    home_dir = home_result.stdout.strip() if home_result.exit_status == 0 else "/home"
                    ext = ".err" if log_type == "stderr" else ".out"

                    # Try common locations
                    candidates = [
                        f"{home_dir}/slurm-{slurm_job_id}{ext}",
                        f"/tmp/slurm-{slurm_job_id}{ext}",
                    ]

                    for candidate in candidates:
                        result = await conn.run(f"test -f {shlex.quote(candidate)}", check=False)
                        if result.exit_status == 0:
                            log_path = candidate
                            break

                if not log_path:
                    yield f"Could not determine log file path for job {slurm_job_id}"
                    yield "Try checking: sacct -j {job_id} --format=StdOut,WorkDir"
                    return

                # Check if file exists
                result = await conn.run(f"test -f {shlex.quote(log_path)}", check=False)
                if result.exit_status != 0:
                    yield f"Log file not found: {log_path}"
                    yield ""
                    yield "The log file may not exist yet (job still starting) or has been cleaned up."
                    return

                # Tail the log file
                result = await conn.run(
                    f"tail -n {tail_lines} {shlex.quote(log_path)}",
                    check=False
                )

                if result.exit_status == 0:
                    for line in result.stdout.splitlines():
                        yield line
                else:
                    yield f"Failed to read log: {result.stderr}"

        except Exception as e:
            logger.error(f"Failed to get job logs for {slurm_job_id}: {e}")
            yield f"Error: {e}"

    async def get_partition_info(self) -> List[Dict[str, Any]]:
        """
        Get information about available SLURM partitions.

        Returns:
            List of partition dictionaries with keys:
            - name: str
            - state: str (UP/DOWN)
            - nodes: int
            - timelimit: str
            - default: bool
        """
        try:
            async with self.connection_manager.get_connection(self.cluster_id) as conn:
                result = await conn.run(
                    "sinfo -h -o '%P|%a|%D|%l'",
                    check=False
                )

                if result.exit_status != 0:
                    return []

                partitions = []
                for line in result.stdout.strip().splitlines():
                    if not line.strip():
                        continue
                    parts = line.split("|")
                    if len(parts) >= 4:
                        name = parts[0]
                        is_default = name.endswith("*")
                        if is_default:
                            name = name[:-1]
                        partitions.append({
                            "name": name,
                            "state": parts[1],
                            "nodes": int(parts[2]) if parts[2].isdigit() else 0,
                            "timelimit": parts[3],
                            "default": is_default,
                        })
                return partitions

        except Exception as e:
            logger.error(f"Failed to get partition info: {e}")
            return []

    async def cancel_slurm_job(self, slurm_job_id: str) -> Tuple[bool, str]:
        """
        Cancel a SLURM job by its SLURM job ID.

        This is a direct interface for queue management (vs cancel_job which
        uses job handles).

        Args:
            slurm_job_id: SLURM job ID to cancel

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            async with self.connection_manager.get_connection(self.cluster_id) as conn:
                result = await conn.run(
                    f"scancel {shlex.quote(slurm_job_id)}",
                    check=False
                )

                if result.exit_status == 0:
                    logger.info(f"Cancelled SLURM job {slurm_job_id}")
                    return True, f"Job {slurm_job_id} cancelled successfully"
                else:
                    msg = result.stderr.strip() or f"scancel exited with code {result.exit_status}"
                    logger.warning(f"Failed to cancel job {slurm_job_id}: {msg}")
                    return False, msg

        except Exception as e:
            logger.error(f"Exception cancelling job {slurm_job_id}: {e}")
            return False, str(e)

    @staticmethod
    def _validate_job_name(job_name: str) -> None:
        """
        Validate SLURM job name format.

        Job names must contain only alphanumeric characters, hyphens, and underscores.

        Args:
            job_name: Job name to validate

        Raises:
            SLURMValidationError: If job name is invalid
        """
        if not job_name:
            raise SLURMValidationError("Job name cannot be empty")

        if len(job_name) > 255:
            raise SLURMValidationError("Job name cannot exceed 255 characters")

        # Allow alphanumeric, hyphens, underscores only
        if not re.match(r"^[a-zA-Z0-9_-]+$", job_name):
            raise SLURMValidationError(
                f"Invalid job name '{job_name}': "
                "must contain only alphanumeric characters, hyphens, and underscores"
            )

    @staticmethod
    def _validate_partition(partition: Optional[str]) -> None:
        """
        Validate SLURM partition name format.

        Partition names must be alphanumeric with optional underscores.

        Args:
            partition: Partition name to validate

        Raises:
            SLURMValidationError: If partition name is invalid
        """
        if not partition:
            return

        if len(partition) > 255:
            raise SLURMValidationError("Partition name cannot exceed 255 characters")

        if not re.match(r"^[a-zA-Z0-9_]+$", partition):
            raise SLURMValidationError(
                f"Invalid partition '{partition}': "
                "must contain only alphanumeric characters and underscores"
            )

    @staticmethod
    def _validate_module(module: str) -> None:
        """
        Validate SLURM module name format.

        Module names must be alphanumeric with optional slashes, dots, and hyphens.

        Args:
            module: Module name to validate

        Raises:
            SLURMValidationError: If module name is invalid
        """
        if not module:
            raise SLURMValidationError("Module name cannot be empty")

        if len(module) > 255:
            raise SLURMValidationError("Module name cannot exceed 255 characters")

        # Allow alphanumeric, slashes, dots, hyphens (common in module names)
        if not re.match(r"^[a-zA-Z0-9/_.-]+$", module):
            raise SLURMValidationError(
                f"Invalid module '{module}': "
                "must contain only alphanumeric characters, slashes, dots, and hyphens"
            )

    @staticmethod
    def _validate_account(account: Optional[str]) -> None:
        """
        Validate SLURM account name format.

        Account names must be alphanumeric with optional underscores.

        Args:
            account: Account name to validate

        Raises:
            SLURMValidationError: If account name is invalid
        """
        if not account:
            return

        if len(account) > 255:
            raise SLURMValidationError("Account name cannot exceed 255 characters")

        if not re.match(r"^[a-zA-Z0-9_]+$", account):
            raise SLURMValidationError(
                f"Invalid account '{account}': "
                "must contain only alphanumeric characters and underscores"
            )

    @staticmethod
    def _validate_qos(qos: Optional[str]) -> None:
        """
        Validate SLURM QOS name format.

        QOS names must be alphanumeric with optional underscores and hyphens.

        Args:
            qos: QOS name to validate

        Raises:
            SLURMValidationError: If QOS name is invalid
        """
        if not qos:
            return

        if len(qos) > 255:
            raise SLURMValidationError("QOS name cannot exceed 255 characters")

        if not re.match(r"^[a-zA-Z0-9_-]+$", qos):
            raise SLURMValidationError(
                f"Invalid QOS '{qos}': "
                "must contain only alphanumeric characters, hyphens, and underscores"
            )

    @staticmethod
    def _validate_email(email: Optional[str]) -> None:
        """
        Validate email address format.

        Args:
            email: Email address to validate

        Raises:
            SLURMValidationError: If email is invalid
        """
        if not email:
            return

        # Basic email validation
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(email_pattern, email):
            raise SLURMValidationError(f"Invalid email address: {email}")

    @staticmethod
    def _validate_time_limit(time_limit: str) -> None:
        """
        Validate SLURM time limit format.

        Accepts formats: HH:MM:SS, MM:SS, or minutes.

        Args:
            time_limit: Time limit string to validate

        Raises:
            SLURMValidationError: If time limit is invalid
        """
        if not time_limit:
            raise SLURMValidationError("Time limit cannot be empty")

        # SLURM time format: [DD-]HH:MM:SS or minutes
        if not re.match(r"^(\d+-)?(\d{1,2}:)?\d{1,2}:\d{2}$|^\d+$", time_limit):
            raise SLURMValidationError(
                f"Invalid time limit '{time_limit}': "
                "must be in format HH:MM:SS or [DD-]HH:MM:SS"
            )

    @staticmethod
    def _validate_dependency(job_id: str) -> None:
        """
        Validate SLURM job dependency ID format.

        Job IDs must be numeric.

        Args:
            job_id: Job ID to validate

        Raises:
            SLURMValidationError: If job ID is invalid
        """
        if not job_id:
            raise SLURMValidationError("Job ID cannot be empty")

        if not re.match(r"^\d+$", job_id):
            raise SLURMValidationError(f"Invalid job ID '{job_id}': must be numeric")

    @staticmethod
    def _validate_array_spec(array_spec: str) -> None:
        """
        Validate SLURM job array specification.

        Accepts formats: 1-10, 1,3,5 or combinations.

        Args:
            array_spec: Array specification to validate

        Raises:
            SLURMValidationError: If array spec is invalid
        """
        if not array_spec:
            raise SLURMValidationError("Array specification cannot be empty")

        # Allow ranges (1-10) and comma-separated lists (1,3,5)
        if not re.match(r"^[\d,\-:]+$", array_spec):
            raise SLURMValidationError(
                f"Invalid array specification '{array_spec}': "
                "must contain only digits, commas, hyphens, and colons"
            )

    def _validate_config(self, config: SLURMJobConfig) -> None:
        """
        Validate entire SLURM job configuration.

        Args:
            config: Configuration to validate

        Raises:
            SLURMValidationError: If any field is invalid
        """
        # Validate job name (required)
        self._validate_job_name(config.job_name)

        # Validate optional fields
        if config.partition:
            self._validate_partition(config.partition)
        if config.account:
            self._validate_account(config.account)
        if config.qos:
            self._validate_qos(config.qos)
        if config.email:
            self._validate_email(config.email)

        # Validate time limit
        self._validate_time_limit(config.time_limit)

        # Validate modules
        for module in config.modules:
            self._validate_module(module)

        # Validate dependencies
        for dep in config.dependencies:
            self._validate_dependency(dep)

        # Validate array specification
        if config.array:
            self._validate_array_spec(config.array)

        # Validate numeric fields
        if config.nodes < 1:
            raise SLURMValidationError("Number of nodes must be at least 1")
        if config.ntasks < 1:
            raise SLURMValidationError("Number of tasks must be at least 1")
        if config.cpus_per_task < 1:
            raise SLURMValidationError("CPUs per task must be at least 1")

    def _generate_slurm_script(
        self,
        config: SLURMJobConfig,
        work_dir: str
    ) -> str:
        """
        Generate a SLURM submission script using templates.

        Uses the SLURMTemplateGenerator for template-based script generation
        with comprehensive input validation.

        Args:
            config: SLURM job configuration
            work_dir: Remote working directory

        Returns:
            Complete SLURM script as string

        Raises:
            SLURMValidationError: If configuration contains invalid values
        """
        try:
            # Use the template generator
            return self._template_generator.generate(
                job_name=config.job_name,
                work_dir=work_dir,
                nodes=config.nodes,
                ntasks=config.ntasks,
                cpus_per_task=config.cpus_per_task,
                time_limit=config.time_limit,
                partition=config.partition,
                memory=config.memory,
                account=config.account,
                qos=config.qos,
                email=config.email,
                email_type=config.email_type,
                constraint=config.constraint,
                exclusive=config.exclusive,
                dependencies=config.dependencies,
                array=config.array,
                modules=config.modules,
                environment_setup=config.environment_setup,
            )
        except SLURMTemplateValidationError as e:
            raise SLURMValidationError(str(e)) from e

    def _parse_job_id(self, sbatch_output: str) -> Optional[str]:
        """
        Parse SLURM job ID from sbatch output.

        Expected format: "Submitted batch job 12345"

        Args:
            sbatch_output: stdout from sbatch command

        Returns:
            Job ID as string if found, None otherwise
        """
        match = re.search(r"Submitted batch job (\d+)", sbatch_output)
        if match:
            return match.group(1)
        return None

    async def _monitor_job(
        self,
        job_id: int,
        connection
    ) -> AsyncIterator[str]:
        """
        Monitor SLURM job status until completion.

        Args:
            job_id: Database ID of the job
            connection: Active SSH connection

        Yields:
            Status update messages
        """
        slurm_job_id = self._slurm_job_ids.get(job_id)
        if not slurm_job_id:
            raise SLURMStatusError(f"No SLURM job ID for job {job_id}")

        previous_state = SLURMJobState.PENDING
        iteration = 0

        while True:
            iteration += 1

            # Query job status
            state, reason = await self._check_status(connection, slurm_job_id)
            self._job_states[job_id] = state

            # Report state changes
            if state != previous_state:
                if reason:
                    yield f"Status: {state.value} ({reason})"
                else:
                    yield f"Status: {state.value}"
                previous_state = state

            # Check for terminal states
            if state in [
                SLURMJobState.COMPLETED,
                SLURMJobState.FAILED,
                SLURMJobState.CANCELLED,
                SLURMJobState.TIMEOUT,
                SLURMJobState.NODE_FAIL,
                SLURMJobState.OUT_OF_MEMORY
            ]:
                break

            # Periodic update for long-running jobs
            if iteration % 10 == 0:  # Every 5 minutes at 30s intervals
                yield f"Still {state.value} (checked {iteration} times)"

            # Wait before next poll
            await asyncio.sleep(self.poll_interval)

    async def _check_status(
        self,
        connection,
        slurm_job_id: str
    ) -> Tuple[SLURMJobState, Optional[str]]:
        """
        Check SLURM job status using squeue.

        Args:
            connection: Active SSH connection
            slurm_job_id: SLURM job ID

        Returns:
            Tuple of (SLURMJobState, reason string)
        """
        try:
            # Query job status with state and reason
            result = await connection.run(
                f"squeue -j {shlex.quote(slurm_job_id)} -h -o '%T|%r'",
                check=False
            )

            if result.exit_status != 0 or not result.stdout.strip():
                # Job not in queue - check if completed or failed
                sacct_result = await connection.run(
                    f"sacct -j {shlex.quote(slurm_job_id)} -n -o State -P | head -n1",
                    check=False
                )

                if sacct_result.exit_status == 0 and sacct_result.stdout.strip():
                    state_str = sacct_result.stdout.strip()
                    return self._parse_state(state_str), None
                else:
                    # Can't determine state
                    return SLURMJobState.UNKNOWN, "Job not found in queue or history"

            # Parse state and reason from squeue output
            output = result.stdout.strip()
            if "|" in output:
                state_str, reason = output.split("|", 1)
                return self._parse_state(state_str), reason
            else:
                return self._parse_state(output), None

        except Exception as e:
            logger.error(f"Failed to check job status: {e}")
            return SLURMJobState.UNKNOWN, str(e)

    def _parse_state(self, state_str: str) -> SLURMJobState:
        """
        Parse SLURM state string to SLURMJobState enum.

        Args:
            state_str: State string from squeue/sacct

        Returns:
            Corresponding SLURMJobState
        """
        state_str = state_str.upper().strip()

        # Map SLURM states to our enum
        state_map = {
            "PENDING": SLURMJobState.PENDING,
            "PD": SLURMJobState.PENDING,
            "RUNNING": SLURMJobState.RUNNING,
            "R": SLURMJobState.RUNNING,
            "COMPLETED": SLURMJobState.COMPLETED,
            "CD": SLURMJobState.COMPLETED,
            "FAILED": SLURMJobState.FAILED,
            "F": SLURMJobState.FAILED,
            "CANCELLED": SLURMJobState.CANCELLED,
            "CA": SLURMJobState.CANCELLED,
            "TIMEOUT": SLURMJobState.TIMEOUT,
            "TO": SLURMJobState.TIMEOUT,
            "NODE_FAIL": SLURMJobState.NODE_FAIL,
            "NF": SLURMJobState.NODE_FAIL,
            "OUT_OF_MEMORY": SLURMJobState.OUT_OF_MEMORY,
            "OOM": SLURMJobState.OUT_OF_MEMORY,
        }

        return state_map.get(state_str, SLURMJobState.UNKNOWN)

    async def _download_results(
        self,
        connection,
        remote_dir: str,
        local_dir: Path
    ) -> None:
        """
        Download result files from remote directory.

        Args:
            connection: Active SSH connection
            remote_dir: Remote directory path
            local_dir: Local destination directory
        """
        try:
            # Note: start_sftp_client() is a coroutine that must be awaited
            async with await connection.start_sftp_client() as sftp:
                # List remote files
                remote_files = await sftp.listdir(remote_dir)

                # Download important files
                download_patterns = [
                    "output.out",
                    "*.f9",
                    "*.f98",
                    "slurm-*.out",
                    "slurm-*.err",
                    "*.xyz",
                    "*.cif"
                ]

                import fnmatch
                for remote_file in remote_files:
                    # Check if file matches any pattern using proper glob matching
                    should_download = any(
                        fnmatch.fnmatch(remote_file, pattern)
                        for pattern in download_patterns
                    )

                    if should_download:
                        remote_path = f"{remote_dir}/{remote_file}"
                        local_path = local_dir / remote_file

                        try:
                            await sftp.get(remote_path, str(local_path))
                            logger.debug(f"Downloaded: {remote_file}")
                        except Exception as e:
                            logger.warning(f"Failed to download {remote_file}: {e}")

        except Exception as e:
            logger.error(f"Failed to download results: {e}")
            raise SLURMRunnerError(f"Result download failed: {e}") from e
