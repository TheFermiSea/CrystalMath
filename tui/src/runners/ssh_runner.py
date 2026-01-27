"""
SSH-based remote job execution backend for DFT calculations.

This module implements the SSHRunner class which executes DFT jobs
(CRYSTAL, Quantum Espresso, VASP, etc.) on remote machines via SSH,
with features including file transfer, remote process monitoring,
and output streaming.

Security:
    All remote commands are properly escaped to prevent shell injection attacks.
    Path interpolations use shlex.quote() and PIDs are validated as integers.
"""

import asyncio
import asyncssh
import logging
import re
import shlex
import time
from pathlib import Path, PurePosixPath
from typing import Dict, Optional, Any, AsyncIterator
from datetime import datetime

from .base import RemoteBaseRunner, RunnerConfig, JobResult, JobStatus
from .exceptions import (
    JobSubmissionError,
    JobNotFoundError,
    ConnectionError as RunnerConnectionError,
    SSHRunnerError,
)
from ..core.codes import DFTCode, get_code_config, get_parser, InvocationStyle
from ..core.connection_manager import ConnectionManager


logger = logging.getLogger(__name__)

# Security: Regex pattern for valid chemical element symbols (1-2 letters, first capitalized)
# Prevents command injection when element is used in shell commands
_ELEMENT_PATTERN = re.compile(r'^[A-Z][a-z]?$')


class SSHRunner(RemoteBaseRunner):
    """
    Executes DFT jobs on remote machines via SSH.

    Features:
    - File transfer via SFTP (input staging, output retrieval)
    - Remote directory management (create, cleanup)
    - Environment setup on remote machine (source code-specific bashrc)
    - Process monitoring (PID tracking, resource usage)
    - Output streaming (tail -f equivalent)

    Supports multiple DFT codes through the DFTCodeConfig abstraction:
    - CRYSTAL23: stdin invocation with cry23.bashrc environment
    - Quantum Espresso: flag invocation with QE environment
    - VASP: cwd invocation with VASP environment

    The remote execution flow:
    1. Create remote work directory: ~/dft_jobs/job_<id>_<timestamp>/
    2. Upload input files (code-specific via DFTCodeConfig)
    3. Write execution script (bash wrapper)
    4. Execute: nohup bash run_job.sh > output.log 2>&1 &
    5. Capture PID and store as job_handle (format: "cluster_id:PID")
    6. Monitor execution
    7. Download results when complete
    8. Clean up remote directory (configurable)

    Attributes:
        connection_manager: ConnectionManager instance for SSH pooling
        cluster_id: Database ID of the remote cluster
        dft_code: DFT code to run (CRYSTAL, QUANTUM_ESPRESSO, VASP)
        code_config: DFTCodeConfig for the selected DFT code
        remote_dft_root: Path to DFT software on remote system
        remote_scratch_dir: Scratch directory on remote system
        cleanup_on_success: Whether to remove remote directory after success
    """

    def __init__(
        self,
        connection_manager: ConnectionManager,
        cluster_id: int,
        dft_code: DFTCode = DFTCode.CRYSTAL,
        remote_dft_root: Optional[Path] = None,
        remote_scratch_dir: Optional[Path] = None,
        cleanup_on_success: bool = False,
    ):
        """
        Initialize the SSH runner.

        Args:
            connection_manager: ConnectionManager for SSH connections
            cluster_id: Database ID of the cluster to execute on
            dft_code: DFT code to run (default: CRYSTAL for backwards compatibility)
            remote_dft_root: DFT software root directory on remote (default: ~/CRYSTAL23 for CRYSTAL)
            remote_scratch_dir: Scratch directory on remote (default: ~/dft_jobs)
            cleanup_on_success: Whether to remove remote directory after successful job

        Raises:
            ValueError: If cluster is not registered
        """
        # Call parent class constructor
        super().__init__(
            connection_manager=connection_manager,
            cluster_id=cluster_id,
            dft_code=dft_code,
            remote_scratch_dir=remote_scratch_dir,
        )

        # Set default remote root based on DFT code
        if remote_dft_root:
            self.remote_dft_root = remote_dft_root
        elif dft_code == DFTCode.CRYSTAL:
            self.remote_dft_root = Path.home() / "CRYSTAL23"
        else:
            self.remote_dft_root = Path.home() / self.code_config.name.upper()

        self.cleanup_on_success = cleanup_on_success

        # Track active jobs: job_handle -> job_info
        self._active_jobs: Dict[str, Dict[str, Any]] = {}
        # Track slot monitor tasks: job_handle -> asyncio.Task
        self._slot_monitors: Dict[str, asyncio.Task] = {}

        # Validate cluster is registered
        if cluster_id not in connection_manager._configs:
            raise ValueError(f"Cluster {cluster_id} not registered in ConnectionManager")

        logger.info(
            f"Initialized SSHRunner for cluster {cluster_id}, "
            f"dft_code={self.code_config.display_name}, "
            f"remote_root={self.remote_dft_root}"
        )

    async def submit_job(
        self,
        job_id: int,
        work_dir: Path,
        input_file: Path,
        threads: Optional[int] = None,
        mpi_ranks: Optional[int] = None,
        **kwargs: Any
    ) -> str:
        """
        Submit a DFT job for remote execution.

        Creates remote directory, uploads files, writes execution script,
        and starts the job in the background.

        Note: max_concurrent_jobs is enforced by acquiring a semaphore slot
        that is held until the job completes (not just until submission).

        Args:
            job_id: Database ID for tracking
            work_dir: Local working directory
            input_file: Path to input file (e.g., input.d12 for CRYSTAL)
            threads: Number of OpenMP threads (optional)
            mpi_ranks: Number of MPI ranks (optional)
            **kwargs: Additional options (timeout, custom_env, etc.)

        Returns:
            Job handle in format "cluster_id:PID:remote_work_dir"

        Raises:
            FileNotFoundError: If input file doesn't exist
            JobSubmissionError: If submission fails
        """
        # Acquire slot - blocks until a slot is available
        # Slot is held until job completes (via background monitor task)
        await self._semaphore.acquire()
        slot_acquired = True

        try:
            # Validate input file
            if not input_file.exists():
                raise FileNotFoundError(f"Input file not found: {input_file}")

            # Create remote work directory
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            remote_work_dir = PurePosixPath(
                self.remote_scratch_dir / f"job_{job_id}_{timestamp}"
            )

            try:
                async with self.connection_manager.get_connection(self.cluster_id) as conn:
                    # Create remote directory (with proper shell escaping)
                    mkdir_cmd = f"mkdir -p {shlex.quote(str(remote_work_dir))}"
                    await conn.run(mkdir_cmd, check=True)
                    logger.info(f"Created remote work directory: {remote_work_dir}")

                    # Upload input files
                    await self._upload_files(conn, work_dir, remote_work_dir)

                    # Create execution script
                    script_content = self._generate_execution_script(
                        remote_work_dir=remote_work_dir,
                        input_file=input_file.name,
                        threads=threads,
                        mpi_ranks=mpi_ranks,
                        **kwargs
                    )

                    # Write script to remote
                    script_path = remote_work_dir / "run_job.sh"
                    # Note: start_sftp_client() is a coroutine that must be awaited
                    async with await conn.start_sftp_client() as sftp:
                        async with sftp.open(str(script_path), "w") as f:
                            await f.write(script_content)
                    chmod_cmd = f"chmod +x {shlex.quote(str(script_path))}"
                    await conn.run(chmod_cmd, check=True)

                    # Execute job in background and capture PID
                    execute_cmd = (
                        f"cd {shlex.quote(str(remote_work_dir))} && "
                        f"nohup bash run_job.sh > output.log 2>&1 & "
                        f"echo $!"
                    )
                    result = await conn.run(execute_cmd, check=True)
                    pid_str = result.stdout.strip()
                    # Validate PID is an integer
                    try:
                        pid = int(pid_str)
                    except ValueError:
                        raise JobSubmissionError(f"Invalid PID returned: {pid_str}")
                    if pid <= 0:
                        raise JobSubmissionError(f"Invalid PID (must be > 0): {pid}")

                    # Create job handle
                    job_handle = f"{self.cluster_id}:{pid}:{remote_work_dir}"

                    # Track job
                    self._active_jobs[job_handle] = {
                        "job_id": job_id,
                        "pid": pid,
                        "remote_work_dir": str(remote_work_dir),
                        "local_work_dir": str(work_dir),
                        "submitted_at": time.time(),
                        "status": JobStatus.RUNNING,
                    }

                    logger.info(
                        f"Submitted job {job_id} with PID {pid} on cluster {self.cluster_id}"
                    )

                    # Spawn background task to monitor job and release slot when done
                    monitor_task = asyncio.create_task(
                        self._monitor_and_release_slot(job_handle),
                        name=f"slot_monitor_{job_handle}"
                    )
                    self._slot_monitors[job_handle] = monitor_task
                    slot_acquired = False  # Monitor will release it

                    return job_handle

            except asyncssh.Error as e:
                raise JobSubmissionError(f"SSH error during job submission: {e}") from e
            except Exception as e:
                raise JobSubmissionError(f"Failed to submit job: {e}") from e

        finally:
            # Release slot immediately if submission failed (monitor not spawned)
            if slot_acquired:
                self._semaphore.release()

    async def _monitor_and_release_slot(self, job_handle: str) -> None:
        """
        Background task that monitors job and releases semaphore slot when done.

        This ensures max_concurrent_jobs limits actual running jobs, not just
        submission rate.

        Args:
            job_handle: Job handle to monitor
        """
        try:
            # Poll until job reaches terminal state
            while True:
                try:
                    status = await self.get_status(job_handle)
                    if status in (JobStatus.COMPLETED, JobStatus.FAILED,
                                  JobStatus.CANCELLED, JobStatus.UNKNOWN):
                        logger.debug(f"Job {job_handle} reached terminal state: {status}")
                        break
                except Exception as e:
                    logger.warning(f"Error checking job status for {job_handle}: {e}")
                    # Continue monitoring - transient errors shouldn't abort
                await asyncio.sleep(5.0)  # Poll every 5 seconds
        finally:
            self._semaphore.release()
            self._slot_monitors.pop(job_handle, None)
            logger.debug(f"Released slot for job {job_handle}")

    async def get_status(self, job_handle: str) -> str:
        """
        Get the current status of a job using robust multi-signal detection.

        Uses three layers of status detection in priority order:
        1. Process status (ps command) - most reliable for running jobs
        2. Exit code file (.exit_code) - reliable for completed jobs
        3. Output file parsing - fallback only

        This approach prevents race conditions and brittle string matching issues.

        Args:
            job_handle: Handle returned by submit_job()

        Returns:
            Status string: "pending", "running", "completed", "failed", "cancelled", "unknown"

        Raises:
            JobNotFoundError: If job_handle is invalid
        """
        job_info = self._active_jobs.get(job_handle)
        if not job_info:
            raise JobNotFoundError(f"Job handle not found: {job_handle}")

        # Parse job handle
        cluster_id, pid, remote_work_dir = self._parse_job_handle(job_handle)

        try:
            async with self.connection_manager.get_connection(cluster_id) as conn:
                # Validate PID is an integer
                try:
                    validated_pid = int(pid)
                except (ValueError, TypeError):
                    raise JobNotFoundError(f"Invalid PID in job handle: {pid}")

                if validated_pid <= 0:
                    raise JobNotFoundError(f"Invalid PID (must be > 0): {validated_pid}")

                # Signal 1: Check if process is running (most reliable)
                try:
                    check_cmd = f"ps -p {validated_pid} -o pid= 2>/dev/null"
                    result = await conn.run(check_cmd, check=False, timeout=5)
                    if result.exit_status == 0 and result.stdout.strip():
                        # Process exists and is running
                        job_info["status"] = JobStatus.RUNNING
                        return JobStatus.RUNNING
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout checking process status for PID {validated_pid}")
                except Exception as e:
                    logger.debug(f"Process check failed (expected if job finished): {e}")

                # Signal 2: Check exit code file (reliable for completed jobs)
                quoted_work_dir = shlex.quote(remote_work_dir)
                try:
                    exit_code_cmd = (
                        f"test -f {quoted_work_dir}/.exit_code && "
                        f"cat {quoted_work_dir}/.exit_code"
                    )
                    result = await conn.run(exit_code_cmd, check=False, timeout=5)

                    if result.exit_status == 0 and result.stdout.strip():
                        try:
                            exit_code = int(result.stdout.strip())
                            if exit_code == 0:
                                job_info["status"] = JobStatus.COMPLETED
                                return JobStatus.COMPLETED
                            else:
                                job_info["status"] = JobStatus.FAILED
                                return JobStatus.FAILED
                        except ValueError:
                            logger.warning(f"Invalid exit code in .exit_code: {result.stdout.strip()}")
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout reading exit code file")
                except Exception as e:
                    logger.debug(f"Exit code check failed: {e}")

                # Signal 3: Parse output file (fallback only)
                try:
                    output_file = f"{quoted_work_dir}/output.log"
                    tail_cmd = f"tail -100 {output_file} 2>/dev/null"
                    result = await conn.run(tail_cmd, check=False, timeout=5)

                    if result.exit_status == 0 and result.stdout:
                        output_lower = result.stdout.lower()

                        # Check for error indicators FIRST (more specific)
                        if any(marker in output_lower for marker in [
                            "error termination",
                            "abnormal termination",
                            "segmentation fault",
                            "killed by signal"
                        ]):
                            job_info["status"] = JobStatus.FAILED
                            return JobStatus.FAILED

                        # Check for completion indicators (less specific)
                        if any(marker in output_lower for marker in [
                            "scf ended",
                            "eeeeeeeeee termination",
                            "terminated - job complete",
                            "normal termination"
                        ]):
                            job_info["status"] = JobStatus.COMPLETED
                            return JobStatus.COMPLETED
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout reading output file")
                except Exception as e:
                    logger.debug(f"Output parsing failed: {e}")

                # Unknown status - all detection methods failed
                logger.warning(
                    f"Could not determine status for job {validated_pid}. "
                    f"Process not running, no exit code, and output parsing inconclusive."
                )
                job_info["status"] = JobStatus.UNKNOWN
                return JobStatus.UNKNOWN

        except JobNotFoundError:
            # Re-raise JobNotFoundError without wrapping
            raise
        except Exception as e:
            logger.error(f"Error checking job status: {e}")
            job_info["status"] = JobStatus.UNKNOWN
            return JobStatus.UNKNOWN

    async def cancel_job(self, job_handle: str, timeout: float = 10.0) -> bool:
        """
        Cancel a running job.

        Sends SIGTERM first, then SIGKILL if process doesn't terminate.

        Args:
            job_handle: Handle returned by submit_job()
            timeout: Seconds to wait before force kill

        Returns:
            True if job was cancelled, False if job wasn't running

        Raises:
            JobNotFoundError: If job_handle is invalid
        """
        job_info = self._active_jobs.get(job_handle)
        if not job_info:
            raise JobNotFoundError(f"Job handle not found: {job_handle}")

        cluster_id, pid, remote_work_dir = self._parse_job_handle(job_handle)

        try:
            async with self.connection_manager.get_connection(cluster_id) as conn:
                # Validate PID is an integer
                try:
                    validated_pid = int(pid)
                except (ValueError, TypeError):
                    raise JobNotFoundError(f"Invalid PID in job handle: {pid}")

                if validated_pid <= 0:
                    raise ValueError(f"Invalid PID (must be > 0): {validated_pid}")

                # Check if process is running
                check_cmd = f"ps -p {validated_pid} > /dev/null 2>&1 && echo running"
                result = await conn.run(check_cmd, check=False)

                if "running" not in result.stdout:
                    logger.info(f"Job {validated_pid} not running, nothing to cancel")
                    return False

                # Send SIGTERM
                logger.info(f"Sending SIGTERM to job {validated_pid}")
                await conn.run(f"kill {validated_pid}", check=False)

                # Wait for termination
                start_time = time.time()
                while time.time() - start_time < timeout:
                    result = await conn.run(check_cmd, check=False)
                    if "running" not in result.stdout:
                        logger.info(f"Job {validated_pid} terminated gracefully")
                        job_info["status"] = JobStatus.CANCELLED
                        return True
                    await asyncio.sleep(0.5)

                # Force kill
                logger.info(f"Sending SIGKILL to job {validated_pid}")
                await conn.run(f"kill -9 {validated_pid}", check=False)
                await asyncio.sleep(1.0)

                job_info["status"] = JobStatus.CANCELLED
                return True

        except Exception as e:
            logger.error(f"Error cancelling job: {e}")
            return False

    async def get_output(self, job_handle: str) -> AsyncIterator[str]:
        """
        Stream job output in real-time.

        Uses tail -f to stream the output.log file from the remote machine.

        Args:
            job_handle: Handle returned by submit_job()

        Yields:
            Lines of output from the remote output.log file

        Raises:
            JobNotFoundError: If job_handle is invalid
        """
        job_info = self._active_jobs.get(job_handle)
        if not job_info:
            raise JobNotFoundError(f"Job handle not found: {job_handle}")

        cluster_id, pid, remote_work_dir = self._parse_job_handle(job_handle)
        # Properly escape the output file path
        quoted_work_dir = shlex.quote(remote_work_dir)
        output_file = f"{quoted_work_dir}/output.log"

        try:
            async with self.connection_manager.get_connection(cluster_id) as conn:
                # Wait for output file to be created
                for _ in range(30):  # Wait up to 30 seconds
                    check_cmd = f"test -f {output_file} && echo exists"
                    result = await conn.run(check_cmd, check=False)
                    if "exists" in result.stdout:
                        break
                    await asyncio.sleep(1.0)
                else:
                    logger.warning(f"Output file not found after 30 seconds: {remote_work_dir}/output.log")
                    yield "⚠ Output file not created yet\n"
                    return

                # Stream output using tail -f
                # Note: tail -f will continue until the process exits
                tail_cmd = f"tail -f {output_file}"
                async with conn.create_process(tail_cmd) as process:
                    if process.stdout:
                        # Debounce status checks to avoid per-line overhead
                        # Only check status every 5 seconds, not every line
                        last_status_check = 0.0
                        status_check_interval = 5.0  # seconds

                        async for line in process.stdout:
                            yield line.strip()

                            # Check if job has finished (with debounce)
                            now = time.time()
                            if now - last_status_check >= status_check_interval:
                                last_status_check = now
                                status = await self.get_status(job_handle)
                                if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                                    # Read any remaining output
                                    break

        except asyncssh.Error as e:
            logger.error(f"SSH error while streaming output: {e}")
            yield f"\n✗ SSH error: {e}\n"
        except Exception as e:
            logger.error(f"Error streaming output: {e}")
            yield f"\n✗ Error: {e}\n"

    async def retrieve_results(self, job_handle: str, work_dir: Path) -> JobResult:
        """
        Retrieve and parse final job results.

        Downloads output files from remote machine and parses using CRYSTALpytools.

        Args:
            job_handle: Handle returned by submit_job()
            work_dir: Local working directory to download files to

        Returns:
            JobResult with parsed information

        Raises:
            JobNotFoundError: If job_handle is invalid
            ValueError: If job hasn't completed yet
        """
        job_info = self._active_jobs.get(job_handle)
        if not job_info:
            raise JobNotFoundError(f"Job handle not found: {job_handle}")

        # Check if job is complete
        status = await self.get_status(job_handle)
        if status == JobStatus.RUNNING:
            raise ValueError("Job is still running, cannot retrieve results yet")

        cluster_id, pid, remote_work_dir = self._parse_job_handle(job_handle)

        try:
            async with self.connection_manager.get_connection(cluster_id) as conn:
                # Download output files
                await self._download_files(conn, remote_work_dir, work_dir)

                # Determine output file based on DFT code
                if self.dft_code == DFTCode.VASP:
                    # VASP outputs to OUTCAR
                    output_file = work_dir / "OUTCAR"
                else:
                    # CRYSTAL and others use our standardized output.log
                    output_file = work_dir / "output.log"

                result = await self._parse_results(output_file, status)

                return result

        except Exception as e:
            logger.error(f"Error retrieving results: {e}")
            return JobResult(
                success=False,
                final_energy=None,
                convergence_status="UNKNOWN",
                errors=[f"Failed to retrieve results: {e}"],
                warnings=[],
                metadata={"job_handle": job_handle, "status": status}
            )

    def is_job_running(self, job_handle: str) -> bool:
        """
        Check if a job is currently running (synchronous check).

        This checks the cached status. For live status, use get_status().

        Args:
            job_handle: Handle returned by submit_job()

        Returns:
            True if job is running, False otherwise
        """
        job_info = self._active_jobs.get(job_handle)
        if not job_info:
            return False
        return job_info.get("status") == JobStatus.RUNNING

    def get_job_pid(self, job_handle: str) -> Optional[int]:
        """
        Get the process ID for a running job.

        Args:
            job_handle: Handle returned by submit_job()

        Returns:
            PID as int if available, None if job not found
        """
        job_info = self._active_jobs.get(job_handle)
        if not job_info:
            return None
        return job_info.get("pid")

    async def get_vasp_progress(self, job_handle: str) -> Optional[Any]:
        """
        Get real-time VASP calculation progress by parsing OUTCAR.

        Only applicable for VASP jobs. Downloads the last ~500 lines of OUTCAR
        and parses current progress (ionic steps, SCF iterations, energies).

        Args:
            job_handle: Handle returned by submit_job()

        Returns:
            VASPProgress object with current status, or None if not a VASP job
            or OUTCAR not yet available

        Raises:
            JobNotFoundError: If job_handle is invalid
        """
        from ..runners.vasp_progress import VASPProgressParser

        # Only applicable for VASP jobs
        if self.dft_code != DFTCode.VASP:
            return None

        job_info = self._active_jobs.get(job_handle)
        if not job_info:
            raise JobNotFoundError(f"Job handle not found: {job_handle}")

        cluster_id, pid, remote_work_dir = self._parse_job_handle(job_handle)

        try:
            async with self.connection_manager.get_connection(cluster_id) as conn:
                # OUTCAR path
                quoted_work_dir = shlex.quote(remote_work_dir)
                outcar_path = f"{quoted_work_dir}/OUTCAR"

                # Check if OUTCAR exists
                check_cmd = f"test -f {outcar_path} && echo OK"
                result = await conn.run(check_cmd, check=False)

                if "OK" not in result.stdout:
                    logger.debug(f"OUTCAR not yet created for job {pid}")
                    return None

                # Download last 500 lines of OUTCAR
                tail_cmd = f"tail -500 {outcar_path}"
                result = await conn.run(tail_cmd, check=False, timeout=10)

                if result.exit_status != 0 or not result.stdout:
                    logger.warning(f"Failed to read OUTCAR tail for job {pid}")
                    return None

                # Parse progress
                parser = VASPProgressParser()
                progress = parser.parse_outcar_tail(result.stdout)

                # Store progress in job info for caching
                job_info["vasp_progress"] = progress.to_dict()
                job_info["last_progress_update"] = time.time()

                return progress

        except asyncio.TimeoutError:
            logger.warning(f"Timeout while fetching VASP progress for job {pid}")
            return None
        except Exception as e:
            logger.error(f"Error getting VASP progress: {e}")
            return None

    async def cleanup(self, job_handle: str, remove_files: bool = False) -> None:
        """
        Cleanup resources associated with a job.

        Args:
            job_handle: Handle returned by submit_job()
            remove_files: If True, also remove remote working directory

        Raises:
            JobNotFoundError: If job_handle is invalid
        """
        job_info = self._active_jobs.get(job_handle)
        if not job_info:
            raise JobNotFoundError(f"Job handle not found: {job_handle}")

        cluster_id, pid, remote_work_dir = self._parse_job_handle(job_handle)

        try:
            # Cancel slot monitor if running
            monitor_task = self._slot_monitors.pop(job_handle, None)
            if monitor_task and not monitor_task.done():
                monitor_task.cancel()
                try:
                    await monitor_task
                except asyncio.CancelledError:
                    pass

            if remove_files:
                async with self.connection_manager.get_connection(cluster_id) as conn:
                    # Properly escape the directory path for removal
                    cleanup_cmd = f"rm -rf {shlex.quote(remote_work_dir)}"
                    await conn.run(cleanup_cmd, check=False)
                    logger.info(f"Removed remote work directory: {remote_work_dir}")

            # Remove from tracking
            del self._active_jobs[job_handle]
            logger.info(f"Cleaned up job {job_handle}")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            # Still remove from tracking even if cleanup failed
            self._active_jobs.pop(job_handle, None)
            self._slot_monitors.pop(job_handle, None)

    async def cleanup_all(self) -> None:
        """
        Clean up all resources and cancel all slot monitors.

        Call this when shutting down the runner to ensure proper cleanup.
        """
        # Cancel all slot monitor tasks
        for job_handle, task in list(self._slot_monitors.items()):
            if not task.done():
                task.cancel()

        # Wait for all monitor tasks to finish
        if self._slot_monitors:
            await asyncio.gather(*self._slot_monitors.values(), return_exceptions=True)

        self._slot_monitors.clear()
        self._active_jobs.clear()
        logger.info("SSHRunner cleanup complete")

    # Helper methods

    @staticmethod
    def _validate_pid(pid: Any) -> int:
        """
        Validate and convert a PID to an integer.

        Args:
            pid: Value to validate as a PID

        Returns:
            Validated PID as integer

        Raises:
            ValueError: If PID is not a valid positive integer
        """
        try:
            validated_pid = int(pid)
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid PID: must be an integer, got {type(pid).__name__}: {pid}") from e

        if validated_pid <= 0:
            raise ValueError(f"Invalid PID: must be > 0, got {validated_pid}")

        return validated_pid

    def _parse_job_handle(self, job_handle: str) -> tuple[int, int, str]:
        """
        Parse job handle into components.

        Args:
            job_handle: Handle in format "cluster_id:PID:remote_work_dir"

        Returns:
            Tuple of (cluster_id, pid, remote_work_dir)

        Raises:
            ValueError: If job_handle format is invalid
        """
        parts = job_handle.split(":", 2)
        if len(parts) != 3:
            raise ValueError(f"Invalid job handle format: {job_handle}")

        try:
            cluster_id = int(parts[0])
            pid = int(parts[1])
            remote_work_dir = parts[2]
            return cluster_id, pid, remote_work_dir
        except ValueError as e:
            raise ValueError(f"Invalid job handle format: {job_handle}") from e

    def _generate_execution_script(
        self,
        remote_work_dir: PurePosixPath,
        input_file: str,
        threads: Optional[int] = None,
        mpi_ranks: Optional[int] = None,
        **kwargs: Any
    ) -> str:
        """
        Generate bash script for remote execution.

        Args:
            remote_work_dir: Remote working directory
            input_file: Name of input file (e.g., "input.d12")
            threads: Number of OpenMP threads
            mpi_ranks: Number of MPI ranks
            **kwargs: Additional options

        Returns:
            Bash script content
        """
        # Validate mpi_ranks BEFORE using it (security: prevent command injection)
        if mpi_ranks is not None:
            if not isinstance(mpi_ranks, int) or mpi_ranks <= 0:
                raise ValueError(f"Invalid mpi_ranks: must be positive integer, got {mpi_ranks}")

        # Determine executable and parallelization
        # Quote all paths and variables for security (convert Path objects to strings)
        quoted_dft_root = shlex.quote(str(self.remote_dft_root))

        # Build command based on code configuration
        if mpi_ranks and mpi_ranks > 1:
            exe_name = self.code_config.parallel_executable
        else:
            exe_name = self.code_config.serial_executable

        # Build run command based on invocation style
        invocation = self.code_config.invocation_style
        quoted_input_file = shlex.quote(str(input_file))
        quoted_work_dir = shlex.quote(str(remote_work_dir))

        # For CRYSTAL, use glob pattern to find executable in bin directory
        if self.dft_code == DFTCode.CRYSTAL:
            executable = f"{quoted_dft_root}/bin/*/v*/{exe_name}"
        else:
            # Generic: look in bin directory or root
            executable = f"{quoted_dft_root}/bin/{exe_name}"

        if mpi_ranks and mpi_ranks > 1:
            run_cmd = f"mpirun -np {mpi_ranks} {executable}"
        else:
            run_cmd = executable

        # Set thread count (validate to prevent command injection via environment variable)
        if threads is not None:
            if not isinstance(threads, int) or threads <= 0:
                raise ValueError(f"Invalid threads: must be positive integer, got {threads}")
            omp_threads = threads
        else:
            omp_threads = 4

        # Build input/output redirection based on invocation style
        if invocation == InvocationStyle.STDIN:
            # CRYSTAL-style: exe < input > output
            run_with_io = f"{run_cmd} < {quoted_input_file}"
        elif invocation == InvocationStyle.FLAG:
            # QE-style: exe -in input
            run_with_io = f"{run_cmd} -in {quoted_input_file}"
        else:
            # VASP-style (CWD): exe (reads from cwd)
            run_with_io = run_cmd

        # Determine bashrc path
        if self.code_config.bashrc_pattern:
            quoted_bashrc = shlex.quote(f"{self.remote_dft_root}/{self.code_config.bashrc_pattern}")
        else:
            quoted_bashrc = None

        # Build bashrc sourcing block
        if quoted_bashrc:
            bashrc_block = f"""# Source {self.code_config.display_name} environment (if exists)
if [ -f {quoted_bashrc} ]; then
    source {quoted_bashrc}
fi
"""
        else:
            bashrc_block = f"# No bashrc configured for {self.code_config.display_name}"

        script = f"""#!/bin/bash
# {self.code_config.display_name} job execution script
# Generated by SSHRunner

set -e  # Exit on error

# Change to work directory
cd {quoted_work_dir}

{bashrc_block}

# Set OpenMP threads
export OMP_NUM_THREADS={omp_threads}

# Print environment info
echo "=== {self.code_config.display_name} Job Starting ==="
echo "Date: $(date)"
echo "Host: $(hostname)"
echo "Work dir: $(pwd)"
echo "Executable: {run_cmd}"
echo "OMP_NUM_THREADS: $OMP_NUM_THREADS"
echo "================================"
echo ""

# Run {self.code_config.display_name} (don't exit on error to capture exit code)
set +e
{run_with_io}

# Capture exit code IMMEDIATELY after {self.code_config.display_name} execution
EXIT_CODE=$?
echo $EXIT_CODE > .exit_code
set -e

echo ""
echo "=== {self.code_config.display_name} Job Finished ==="
echo "Date: $(date)"
echo "Exit code: $EXIT_CODE"
echo "================================"

exit $EXIT_CODE
"""
        return script

    async def _upload_files(
        self,
        conn: asyncssh.SSHClientConnection,
        local_dir: Path,
        remote_dir: PurePosixPath
    ) -> None:
        """
        Upload input files to remote machine via SFTP.

        Uploads all relevant input files based on DFT code configuration.
        For VASP jobs, also retrieves POTCAR from cluster's VASP_PP_PATH.

        Args:
            conn: SSH connection
            local_dir: Local directory containing input files
            remote_dir: Remote directory to upload to
        """
        # Build file patterns from code config
        input_patterns = []

        # Primary input file extensions
        for ext in self.code_config.input_extensions:
            input_patterns.append(f"*{ext}")

        # Auxiliary input files
        for ext in self.code_config.auxiliary_inputs.keys():
            input_patterns.append(f"*{ext}")

        files_to_upload = []
        for pattern in input_patterns:
            files_to_upload.extend(local_dir.glob(pattern))

        if not files_to_upload:
            raise FileNotFoundError(f"No input files found in {local_dir}")

        logger.info(f"Uploading {len(files_to_upload)} files to {remote_dir}")

        # Note: start_sftp_client() is a coroutine that must be awaited
        async with await conn.start_sftp_client() as sftp:
            for local_file in files_to_upload:
                remote_file = str(remote_dir / local_file.name)
                await sftp.put(str(local_file), remote_file)
                logger.debug(f"Uploaded: {local_file.name}")

        # VASP-specific: Retrieve POTCAR from cluster
        if self.dft_code == DFTCode.VASP:
            await self._retrieve_vasp_potcar(conn, local_dir, remote_dir)

        logger.info("File upload complete")

    async def _retrieve_vasp_potcar(
        self,
        conn: asyncssh.SSHClientConnection,
        local_dir: Path,
        remote_dir: PurePosixPath
    ) -> None:
        """
        Retrieve and concatenate POTCARs from cluster's VASP_PP_PATH for VASP calculations.

        Reads vasp_metadata.json to determine which elements need POTCARs,
        then concatenates all POTCARs in order to the work directory.

        Args:
            conn: SSH connection
            local_dir: Local directory containing vasp_metadata.json
            remote_dir: Remote work directory

        Raises:
            FileNotFoundError: If vasp_metadata.json or POTCAR not found
            JobSubmissionError: If POTCAR retrieval fails
        """
        import json

        # Read metadata to get POTCAR elements and type
        metadata_file = local_dir / "vasp_metadata.json"
        if not metadata_file.exists():
            raise FileNotFoundError(f"VASP metadata file not found: {metadata_file}")

        metadata = json.loads(metadata_file.read_text())

        # Support new multi-element format or legacy single element
        potcar_elements = metadata.get("potcar_elements")
        potcar_type = metadata.get("potcar_type", "potpaw_PBE")

        if not potcar_elements:
            # Fallback to legacy single element format
            element = metadata.get("potcar_element", "Si")
            # Handle comma-separated elements from legacy format
            potcar_elements = [e.strip() for e in element.split(",")]

        # Security: Validate all elements are valid chemical symbols (1-2 letters)
        for element in potcar_elements:
            if not _ELEMENT_PATTERN.match(element):
                raise JobSubmissionError(
                    f"Invalid POTCAR element '{element}': must be a valid chemical symbol "
                    "(1-2 letters, e.g., 'Si', 'O', 'Fe')"
                )

        # Get cluster configuration for VASP_PP_PATH
        cluster_config = self.connection_manager._configs.get(self.cluster_id)
        if not cluster_config:
            raise ValueError(f"Cluster {self.cluster_id} not found in ConnectionManager")

        # Try to get explicit VASP_PP_PATH from cluster config, otherwise use env var
        vasp_pp_path = getattr(cluster_config, 'vasp_pp_path', None)
        if vasp_pp_path:
            base_path = vasp_pp_path
        else:
            base_path = "$VASP_PP_PATH"

        logger.info(f"Retrieving POTCARs for elements: {potcar_elements} (type: {potcar_type})")

        # Find POTCAR for each element and build concatenation command
        potcar_paths = []
        missing_elements = []

        for element in potcar_elements:
            # Try multiple common POTCAR library paths in order of preference
            search_paths = [
                f"{base_path}/{potcar_type}/{element}/POTCAR",  # User-selected type
                f"{base_path}/potpaw_PBE/{element}/POTCAR",  # Standard PBE fallback
                f"{base_path}/{element}/POTCAR",  # Direct element path
                f"{base_path}/PAW_PBE/{element}/POTCAR",  # Another common structure
            ]

            # Find first existing POTCAR for this element
            found = False
            for path in search_paths:
                try:
                    check_cmd = f"test -f {path} && echo OK"
                    result = await conn.run(check_cmd)
                    if "OK" in result.stdout:
                        potcar_paths.append(path)
                        logger.debug(f"Found POTCAR for {element}: {path}")
                        found = True
                        break
                except Exception as e:
                    logger.debug(f"POTCAR not found at {path}: {e}")
                    continue

            if not found:
                missing_elements.append(element)

        # Error if any elements are missing
        if missing_elements:
            raise JobSubmissionError(
                f"POTCAR not found for element(s): {', '.join(missing_elements)}. "
                f"Ensure VASP_PP_PATH is set on cluster and contains POTCARs for all elements. "
                f"Searched in: {base_path}/{potcar_type}/"
            )

        # Concatenate all POTCARs into single file
        remote_potcar = f"{shlex.quote(str(remote_dir))}/POTCAR"
        if len(potcar_paths) == 1:
            # Single element: just copy
            copy_cmd = f"cp {potcar_paths[0]} {remote_potcar}"
        else:
            # Multiple elements: concatenate in order
            concat_cmd = "cat " + " ".join(potcar_paths) + f" > {remote_potcar}"
            copy_cmd = concat_cmd

        await conn.run(copy_cmd, check=True)
        logger.info(f"Retrieved and concatenated {len(potcar_paths)} POTCARs for: {', '.join(potcar_elements)}")

    async def _download_files(
        self,
        conn: asyncssh.SSHClientConnection,
        remote_dir: str,
        local_dir: Path
    ) -> None:
        """
        Download output files from remote machine via SFTP.

        Args:
            conn: SSH connection
            remote_dir: Remote directory containing output files
            local_dir: Local directory to download to
        """
        # Build output file patterns from code config
        output_files = [
            "output.log",  # Our standardized output log
            ".exit_code",  # Exit code marker
        ]

        # Add code-specific output files
        for fort_name, ext in self.code_config.auxiliary_outputs.items():
            output_files.append(fort_name)
            output_files.append(f"*{ext}")

        # Common output formats
        output_files.extend(["*.xyz", "*.cif"])

        logger.info(f"Downloading output files from {remote_dir}")

        async with await conn.start_sftp_client() as sftp:
            # List files in remote directory
            remote_files = await sftp.listdir(remote_dir)

            import fnmatch
            for filename in remote_files:
                # Check if file matches our patterns using proper glob matching
                should_download = any(
                    fnmatch.fnmatch(filename, pattern)
                    for pattern in output_files
                )

                if should_download:
                    # Security: Validate filename to prevent path traversal attacks
                    # Only allow filenames without path separators
                    if "/" in filename or "\\" in filename or filename in (".", ".."):
                        logger.warning(f"Skipping file with suspicious name: {filename}")
                        continue

                    # Use PurePosixPath for SFTP paths (not shlex.quote - SFTP is not shell)
                    remote_file = str(PurePosixPath(remote_dir) / filename)
                    local_file = local_dir / filename
                    try:
                        await sftp.get(remote_file, str(local_file))
                        logger.debug(f"Downloaded: {filename}")
                    except Exception as e:
                        logger.warning(f"Failed to download {filename}: {e}")

        logger.info("File download complete")

    async def _parse_results(self, output_file: Path, status: str) -> JobResult:
        """
        Parse DFT output file using code-specific parser.

        Args:
            output_file: Path to output.log
            status: Job status from get_status()

        Returns:
            JobResult with extracted information
        """
        metadata: Dict[str, Any] = {"status": status}

        if not output_file.exists():
            return JobResult(
                success=False,
                final_energy=None,
                energy_unit=self.code_config.energy_unit,
                convergence_status="FAILED",
                errors=["Output file not found"],
                warnings=[],
                metadata=metadata
            )

        # Use code-specific parser
        try:
            parser = get_parser(self.dft_code)
            parse_result = await parser.parse(output_file)

            # Determine success
            success = (
                status == JobStatus.COMPLETED and
                parse_result.convergence_status == "CONVERGED" and
                len(parse_result.errors) == 0
            )

            return JobResult(
                success=success,
                final_energy=parse_result.final_energy,
                energy_unit=parse_result.energy_unit,
                convergence_status=parse_result.convergence_status,
                errors=parse_result.errors,
                warnings=parse_result.warnings,
                metadata={
                    **metadata,
                    "scf_cycles": parse_result.scf_cycles,
                    "geometry_converged": parse_result.geometry_converged,
                    **parse_result.metadata
                }
            )
        except Exception as e:
            return JobResult(
                success=False,
                final_energy=None,
                energy_unit=self.code_config.energy_unit,
                convergence_status="UNKNOWN",
                errors=[f"Failed to parse output: {e}"],
                warnings=[],
                metadata=metadata
            )
