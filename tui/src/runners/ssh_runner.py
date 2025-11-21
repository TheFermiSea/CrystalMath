"""
SSH-based remote job execution backend for CRYSTAL calculations.

This module implements the SSHRunner class which executes CRYSTAL jobs on
remote machines via SSH, with features including file transfer, remote
process monitoring, and output streaming.

Security:
    All remote commands are properly escaped to prevent shell injection attacks.
    Path interpolations use shlex.quote() and PIDs are validated as integers.
"""

import asyncio
import asyncssh
import logging
import shlex
import time
from pathlib import Path, PurePosixPath
from typing import Dict, Optional, Any, AsyncIterator
from datetime import datetime

from .base import (
    BaseRunner,
    JobResult,
    JobSubmissionError,
    JobNotFoundError,
    ConnectionError as RunnerConnectionError
)
from ..core.connection_manager import ConnectionManager


logger = logging.getLogger(__name__)


class SSHRunner(BaseRunner):
    """
    Executes CRYSTAL jobs on remote machines via SSH.

    Features:
    - File transfer via SFTP (input staging, output retrieval)
    - Remote directory management (create, cleanup)
    - Environment setup on remote machine (source cry23.bashrc)
    - Process monitoring (PID tracking, resource usage)
    - Output streaming (tail -f equivalent)

    The remote execution flow:
    1. Create remote work directory: ~/crystal_jobs/job_<id>_<timestamp>/
    2. Upload input files (.d12, .gui, .f9, etc.)
    3. Write execution script (bash wrapper)
    4. Execute: nohup bash run_job.sh > output.log 2>&1 &
    5. Capture PID and store as job_handle (format: "cluster_id:PID")
    6. Monitor execution
    7. Download results when complete
    8. Clean up remote directory (configurable)

    Attributes:
        connection_manager: ConnectionManager instance for SSH pooling
        cluster_id: Database ID of the remote cluster
        remote_crystal_root: Path to CRYSTAL23 on remote system
        remote_scratch_dir: Scratch directory on remote system
        cleanup_on_success: Whether to remove remote directory after success
    """

    def __init__(
        self,
        connection_manager: ConnectionManager,
        cluster_id: int,
        remote_crystal_root: Optional[Path] = None,
        remote_scratch_dir: Optional[Path] = None,
        cleanup_on_success: bool = False,
    ):
        """
        Initialize the SSH runner.

        Args:
            connection_manager: ConnectionManager for SSH connections
            cluster_id: Database ID of the cluster to execute on
            remote_crystal_root: CRYSTAL23 root directory on remote (default: ~/CRYSTAL23)
            remote_scratch_dir: Scratch directory on remote (default: ~/crystal_jobs)
            cleanup_on_success: Whether to remove remote directory after successful job

        Raises:
            ValueError: If cluster is not registered
        """
        self.connection_manager = connection_manager
        self.cluster_id = cluster_id
        self.remote_crystal_root = remote_crystal_root or Path.home() / "CRYSTAL23"
        self.remote_scratch_dir = remote_scratch_dir or Path.home() / "crystal_jobs"
        self.cleanup_on_success = cleanup_on_success

        # Track active jobs: job_handle -> job_info
        self._active_jobs: Dict[str, Dict[str, Any]] = {}

        # Validate cluster is registered
        if cluster_id not in connection_manager._configs:
            raise ValueError(f"Cluster {cluster_id} not registered in ConnectionManager")

        logger.info(
            f"Initialized SSHRunner for cluster {cluster_id}, "
            f"remote_root={self.remote_crystal_root}"
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
        Submit a CRYSTAL job for remote execution.

        Creates remote directory, uploads files, writes execution script,
        and starts the job in the background.

        Args:
            job_id: Database ID for tracking
            work_dir: Local working directory
            input_file: Path to input.d12 file
            threads: Number of OpenMP threads (optional)
            mpi_ranks: Number of MPI ranks (optional)
            **kwargs: Additional options (timeout, custom_env, etc.)

        Returns:
            Job handle in format "cluster_id:PID:remote_work_dir"

        Raises:
            FileNotFoundError: If input file doesn't exist
            JobSubmissionError: If submission fails
        """
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
                async with conn.start_sftp_client() as sftp:
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
                    "status": "running",
                }

                logger.info(
                    f"Submitted job {job_id} with PID {pid} on cluster {self.cluster_id}"
                )
                return job_handle

        except asyncssh.Error as e:
            raise JobSubmissionError(f"SSH error during job submission: {e}") from e
        except Exception as e:
            raise JobSubmissionError(f"Failed to submit job: {e}") from e

    async def get_status(self, job_handle: str) -> str:
        """
        Get the current status of a job.

        Checks if the remote process is still running using ps.

        Args:
            job_handle: Handle returned by submit_job()

        Returns:
            Status string: "pending", "running", "completed", "failed", "cancelled"

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

                # Check if process is running
                check_cmd = f"ps -p {validated_pid} > /dev/null 2>&1 && echo running || echo stopped"
                result = await conn.run(check_cmd, check=False)

                if "running" in result.stdout:
                    job_info["status"] = "running"
                    return "running"

                # Process stopped, check output for completion status
                quoted_work_dir = shlex.quote(remote_work_dir)
                check_output_cmd = f"test -f {quoted_work_dir}/output.log && echo exists"
                result = await conn.run(check_output_cmd, check=False)

                if "exists" in result.stdout:
                    # Check for error indicators in output
                    output_file = f"{quoted_work_dir}/output.log"
                    error_check_cmd = (
                        f"grep -i 'error\\|failed\\|abort' {output_file} "
                        f"> /dev/null 2>&1 && echo failed || echo completed"
                    )
                    result = await conn.run(error_check_cmd, check=False)

                    if "failed" in result.stdout:
                        job_info["status"] = "failed"
                        return "failed"
                    else:
                        job_info["status"] = "completed"
                        return "completed"

                # No output file, job likely failed
                job_info["status"] = "failed"
                return "failed"

        except Exception as e:
            logger.error(f"Error checking job status: {e}")
            return "unknown"

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
                        job_info["status"] = "cancelled"
                        return True
                    await asyncio.sleep(0.5)

                # Force kill
                logger.info(f"Sending SIGKILL to job {validated_pid}")
                await conn.run(f"kill -9 {validated_pid}", check=False)
                await asyncio.sleep(1.0)

                job_info["status"] = "cancelled"
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
                        async for line in process.stdout:
                            yield line.strip()

                            # Check if job has finished
                            status = await self.get_status(job_handle)
                            if status in ("completed", "failed", "cancelled"):
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
        if status == "running":
            raise ValueError("Job is still running, cannot retrieve results yet")

        cluster_id, pid, remote_work_dir = self._parse_job_handle(job_handle)

        try:
            async with self.connection_manager.get_connection(cluster_id) as conn:
                # Download output files
                await self._download_files(conn, remote_work_dir, work_dir)

                # Parse results locally using CRYSTALpytools
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
        return job_info.get("status") == "running"

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
        # Determine executable and parallelization
        if mpi_ranks and mpi_ranks > 1:
            executable = f"{self.remote_crystal_root}/bin/*/v*/Pcrystal"
            run_cmd = f"mpirun -np {mpi_ranks} {executable}"
        else:
            executable = f"{self.remote_crystal_root}/bin/*/v*/crystalOMP"
            run_cmd = executable

        # Set thread count
        omp_threads = threads or 4

        script = f"""#!/bin/bash
# CRYSTAL23 job execution script
# Generated by SSHRunner

set -e  # Exit on error

# Change to work directory
cd {remote_work_dir}

# Source CRYSTAL environment (if exists)
if [ -f {self.remote_crystal_root}/cry23.bashrc ]; then
    source {self.remote_crystal_root}/cry23.bashrc
fi

# Set OpenMP threads
export OMP_NUM_THREADS={omp_threads}

# Print environment info
echo "=== CRYSTAL23 Job Starting ==="
echo "Date: $(date)"
echo "Host: $(hostname)"
echo "Work dir: $(pwd)"
echo "Executable: {run_cmd}"
echo "OMP_NUM_THREADS: $OMP_NUM_THREADS"
echo "================================"
echo ""

# Run CRYSTAL
{run_cmd} < {input_file}

# Capture exit code
EXIT_CODE=$?

echo ""
echo "=== CRYSTAL23 Job Finished ==="
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

        Uploads all relevant CRYSTAL input files (.d12, .gui, .f9, etc.)

        Args:
            conn: SSH connection
            local_dir: Local directory containing input files
            remote_dir: Remote directory to upload to
        """
        # Files to upload (if they exist)
        input_patterns = [
            "*.d12",   # Main input
            "*.gui",   # Geometry
            "*.f9",    # Wave function
            "*.f20",   # Alternative wave function
            "*.hessopt",  # Hessian
            "*.optinfo",  # Optimization info
        ]

        files_to_upload = []
        for pattern in input_patterns:
            files_to_upload.extend(local_dir.glob(pattern))

        if not files_to_upload:
            raise FileNotFoundError(f"No input files found in {local_dir}")

        logger.info(f"Uploading {len(files_to_upload)} files to {remote_dir}")

        async with conn.start_sftp_client() as sftp:
            for local_file in files_to_upload:
                remote_file = str(remote_dir / local_file.name)
                await sftp.put(str(local_file), remote_file)
                logger.debug(f"Uploaded: {local_file.name}")

        logger.info("File upload complete")

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
        # Files to download
        output_files = [
            "output.log",
            "fort.9",
            "fort.98",
            "fort.25",  # Properties
            "*.xyz",
            "*.cif",
        ]

        logger.info(f"Downloading output files from {remote_dir}")

        async with conn.start_sftp_client() as sftp:
            # List files in remote directory
            remote_files = await sftp.listdir(remote_dir)

            for filename in remote_files:
                # Check if file matches our patterns
                should_download = False
                for pattern in output_files:
                    if "*" in pattern:
                        # Simple wildcard matching
                        suffix = pattern.replace("*", "")
                        if filename.endswith(suffix):
                            should_download = True
                            break
                    elif filename == pattern:
                        should_download = True
                        break

                if should_download:
                    remote_file = f"{remote_dir}/{filename}"
                    local_file = local_dir / filename
                    try:
                        await sftp.get(remote_file, str(local_file))
                        logger.debug(f"Downloaded: {filename}")
                    except Exception as e:
                        logger.warning(f"Failed to download {filename}: {e}")

        logger.info("File download complete")

    async def _parse_results(self, output_file: Path, status: str) -> JobResult:
        """
        Parse CRYSTAL output file using CRYSTALpytools.

        Args:
            output_file: Path to output.log
            status: Job status from get_status()

        Returns:
            JobResult with extracted information
        """
        errors: list[str] = []
        warnings: list[str] = []
        final_energy: Optional[float] = None
        convergence_status = "UNKNOWN"
        metadata: Dict[str, Any] = {"status": status}

        if not output_file.exists():
            errors.append("Output file not found")
            return JobResult(
                success=False,
                final_energy=None,
                convergence_status="FAILED",
                errors=errors,
                warnings=warnings,
                metadata=metadata
            )

        # Try parsing with CRYSTALpytools
        try:
            from CRYSTALpytools.crystal_io import Crystal_output

            cry_out = Crystal_output(str(output_file))

            # Extract energy
            if hasattr(cry_out, "get_final_energy"):
                try:
                    final_energy = cry_out.get_final_energy()
                except Exception as e:
                    warnings.append(f"Could not extract energy: {e}")

            # Check convergence
            if hasattr(cry_out, "is_converged"):
                try:
                    if cry_out.is_converged():
                        convergence_status = "CONVERGED"
                    else:
                        convergence_status = "NOT_CONVERGED"
                        warnings.append("SCF did not converge")
                except Exception as e:
                    warnings.append(f"Could not check convergence: {e}")

        except ImportError:
            warnings.append("CRYSTALpytools not available, using fallback parser")
            # Simple fallback parsing
            final_energy, convergence_status, parse_errors = self._fallback_parse(output_file)
            errors.extend(parse_errors)

        except Exception as e:
            errors.append(f"Parsing failed: {e}")

        # Determine success
        success = (
            status == "completed" and
            convergence_status == "CONVERGED" and
            len(errors) == 0
        )

        return JobResult(
            success=success,
            final_energy=final_energy,
            convergence_status=convergence_status,
            errors=errors,
            warnings=warnings,
            metadata=metadata
        )

    def _fallback_parse(self, output_file: Path) -> tuple[Optional[float], str, list[str]]:
        """
        Fallback parser when CRYSTALpytools is not available.

        Args:
            output_file: Path to output.log

        Returns:
            Tuple of (final_energy, convergence_status, errors)
        """
        final_energy: Optional[float] = None
        convergence_status = "UNKNOWN"
        errors: list[str] = []

        try:
            with output_file.open("r") as f:
                content = f.read()

            # Look for energy
            for line in content.split("\n"):
                if "TOTAL ENERGY" in line and "AU" in line:
                    parts = line.split()
                    for part in parts:
                        try:
                            energy = float(part)
                            final_energy = energy
                            break
                        except ValueError:
                            continue

            # Check convergence
            if "CONVERGENCE REACHED" in content or "SCF ENDED" in content:
                convergence_status = "CONVERGED"
            elif "NOT CONVERGED" in content:
                convergence_status = "NOT_CONVERGED"

            # Check for errors
            if "ERROR" in content or "FAILED" in content:
                errors.append("Errors detected in output")

        except Exception as e:
            errors.append(f"Fallback parsing failed: {e}")

        return final_energy, convergence_status, errors
