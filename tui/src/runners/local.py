"""
Local job execution backend for DFT calculations.

This module implements the LocalRunner class which executes DFT jobs
(CRYSTAL, Quantum Espresso, VASP, etc.) on the local machine using
the configured executable from DFTCodeConfig.
"""

import asyncio
import os
import signal
from pathlib import Path
from typing import Dict, Any, Optional, AsyncIterator

from ..core.codes import DFTCode, get_code_config, get_parser, InvocationStyle
from ..core.environment import get_crystal_config, EnvironmentError as CrystalEnvError
from .base import BaseRunner, RunnerConfig, JobHandle, JobStatus, JobInfo, JobResult
from .exceptions import (
    ConfigurationError,
    ResourceError,
    RunnerError,
    LocalRunnerError,
    ExecutionError,
)


class ExecutableNotFoundError(ConfigurationError):
    """Raised when the DFT executable cannot be found."""
    pass


class InputFileError(ResourceError):
    """Raised when there are issues with the input file."""
    pass


class LocalRunner(BaseRunner):
    """
    Executes DFT jobs locally using asyncio subprocess management.

    This runner:
    - Validates input files exist based on DFTCodeConfig
    - Launches appropriate executable with non-blocking execution
    - Streams stdout/stderr in real-time for live monitoring
    - Parses output using code-specific parser after completion
    - Returns structured results including energy, convergence, errors

    Supports multiple DFT codes through the DFTCodeConfig abstraction:
    - CRYSTAL23: stdin invocation (exe < input.d12 > output.out)
    - Quantum Espresso: flag invocation (exe -in input.in > output.out)
    - VASP: cwd invocation (exe runs in directory with INCAR, POSCAR, etc.)

    Attributes:
        executable_path: Path to the DFT executable
        default_threads: Number of OpenMP threads to use
        code_config: DFTCodeConfig for the selected DFT code
    """

    def __init__(
        self,
        executable_path: Optional[Path] = None,
        default_threads: Optional[int] = None,
        config: Optional[RunnerConfig] = None
    ):
        """
        Initialize the LocalRunner.

        Args:
            executable_path: Path to DFT executable. If None, resolved from DFTCodeConfig.
            default_threads: Number of OpenMP threads. If None, uses all available cores.
            config: Runner configuration (includes dft_code for code-specific behavior)

        Raises:
            ExecutableNotFoundError: If executable cannot be found or is not executable.
        """
        # Initialize base class
        if config is None:
            config = RunnerConfig(
                executable_path=executable_path,
                default_threads=default_threads or os.cpu_count() or 4
            )
        super().__init__(config)

        # Get DFT code configuration
        self.code_config = get_code_config(self.config.dft_code)

        # Resolve executable path
        self.executable_path = self._resolve_executable(
            self.config.executable_path or executable_path
        )
        self.default_threads = self.config.default_threads
        self._active_processes: Dict[int, asyncio.subprocess.Process] = {}
        self._job_handles: Dict[JobHandle, int] = {}  # Map handles to job IDs
        self._job_work_dirs: Dict[JobHandle, Path] = {}  # Map handles to work directories
        self._job_results: Dict[JobHandle, JobResult] = {}  # Per-job results storage
        self._job_errors: Dict[JobHandle, Exception] = {}  # Per-job error storage

    def _resolve_executable(self, executable_path: Optional[Path]) -> Path:
        """
        Resolve the path to the DFT executable.

        Priority order:
        1. Explicitly provided path
        2. Code-specific environment (e.g., CRY23_ROOT for CRYSTAL)
        3. Code-specific legacy environment variables
        4. PATH lookup

        Args:
            executable_path: Optional explicit path to executable

        Returns:
            Path to the DFT executable

        Raises:
            ExecutableNotFoundError: If executable cannot be found
        """
        exe_name = self.code_config.serial_executable

        # Try explicit path first
        if executable_path:
            if executable_path.exists() and os.access(executable_path, os.X_OK):
                return executable_path
            raise ExecutableNotFoundError(
                f"Provided executable path does not exist or is not executable: {executable_path}"
            )

        # Try code-specific environment resolution
        exe_path = self._resolve_from_environment()
        if exe_path:
            return exe_path

        # Try PATH lookup
        import shutil
        exe_in_path = shutil.which(exe_name)
        if exe_in_path:
            return Path(exe_in_path)

        raise ExecutableNotFoundError(
            f"Could not find {self.code_config.display_name} executable '{exe_name}'. "
            f"Please ensure {self.code_config.display_name} is properly installed, "
            f"or set {self.code_config.root_env_var} environment variable, "
            f"or provide explicit path. "
            f"Searched: explicit path={executable_path}, "
            f"environment variable {self.code_config.root_env_var}, PATH lookup"
        )

    def _resolve_from_environment(self) -> Optional[Path]:
        """
        Resolve executable from code-specific environment variables.

        Returns:
            Path to executable if found, None otherwise
        """
        exe_name = self.code_config.serial_executable

        # Code-specific resolution for CRYSTAL (backwards compatibility)
        if self.config.dft_code == DFTCode.CRYSTAL:
            # Try loading from CRYSTAL23 environment
            try:
                config = get_crystal_config()
                if config.executable_path.exists() and os.access(config.executable_path, os.X_OK):
                    return config.executable_path
            except CrystalEnvError:
                pass

            # Try CRY23_EXEDIR environment variable (legacy)
            cry23_exedir = os.environ.get("CRY23_EXEDIR")
            if cry23_exedir:
                exe_path = Path(cry23_exedir) / exe_name
                if exe_path.exists() and os.access(exe_path, os.X_OK):
                    return exe_path

        # Generic: Try root_env_var/bin/<executable>
        root_dir = os.environ.get(self.code_config.root_env_var)
        if root_dir:
            for bin_subdir in ["bin", ""]:
                exe_path = Path(root_dir) / bin_subdir / exe_name if bin_subdir else Path(root_dir) / exe_name
                if exe_path.exists() and os.access(exe_path, os.X_OK):
                    return exe_path

        return None

    async def run_job(
        self,
        job_id: int,
        work_dir: Path,
        threads: Optional[int] = None
    ) -> AsyncIterator[str]:
        """
        Execute a DFT job and stream output in real-time.

        This is an async generator that yields output lines as they are produced.
        After the job completes, it parses the results using the code-specific parser.

        The job runs in the specified work directory which must contain the
        appropriate input files for the DFT code (e.g., input.d12 for CRYSTAL,
        input.in for QE, INCAR/POSCAR/POTCAR/KPOINTS for VASP).

        Args:
            job_id: Database ID of the job (for tracking)
            work_dir: Path to the job's working directory
            threads: Number of OpenMP threads (default: use self.default_threads)

        Yields:
            Lines of output from stdout/stderr as they are produced

        Returns:
            JobResult object with structured results after completion

        Raises:
            InputFileError: If required input files do not exist or are empty
            LocalRunnerError: If the job fails to start or encounters errors
        """
        # Determine input/output file names from code config
        input_ext = self.code_config.input_extensions[0]  # Primary extension
        output_ext = self.code_config.output_extension

        # Validate input file
        input_file = work_dir / f"input{input_ext}"
        if not input_file.exists():
            raise InputFileError(f"Input file not found: {input_file}")
        if input_file.stat().st_size == 0:
            raise InputFileError(f"Input file is empty: {input_file}")

        # Setup output file
        output_file = work_dir / f"output{output_ext}"

        # Prepare environment with OpenMP settings
        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = str(threads or self.default_threads)

        # Build command based on invocation style
        try:
            process = await self._create_process(input_file, work_dir, env)

            # Track the process
            self._active_processes[job_id] = process

            # Handle stdin-based invocation (CRYSTAL)
            if self.code_config.invocation_style == InvocationStyle.STDIN:
                input_content = input_file.read_bytes()
                if process.stdin:
                    process.stdin.write(input_content)
                    await process.stdin.drain()
                    process.stdin.close()

            # Open output file for writing
            with output_file.open("w") as outf:
                # Stream output line by line
                if process.stdout:
                    async for line in process.stdout:
                        line_str = line.decode("utf-8", errors="replace")
                        outf.write(line_str)
                        outf.flush()
                        yield line_str.rstrip("\n")

            # Wait for process to complete
            return_code = await process.wait()

            # Remove from active processes
            self._active_processes.pop(job_id, None)

            # Parse results
            yield "\n--- Job completed, parsing results ---\n"
            result = await self._parse_results(output_file, return_code)

            # Yield final summary
            if result.success:
                yield f"\n✓ Job completed successfully"
                if result.final_energy is not None:
                    yield f"  Final energy: {result.final_energy:.10f} {result.energy_unit}"
                yield f"  Convergence: {result.convergence_status}"
            else:
                yield f"\n✗ Job failed"
                for error in result.errors:
                    yield f"  Error: {error}"

            if result.warnings:
                yield f"\nWarnings ({len(result.warnings)}):"
                for warning in result.warnings:
                    yield f"  ⚠ {warning}"

            # Store result for retrieval (legacy - used by non-async callers)
            self._last_result = result

            # Yield the result as final item for async task capture
            # This allows _run_job_task to get the result without race conditions
            yield result

        except Exception as e:
            self._active_processes.pop(job_id, None)
            raise LocalRunnerError(f"Failed to execute {self.code_config.display_name} job: {e}") from e

    async def _create_process(
        self,
        input_file: Path,
        work_dir: Path,
        env: Dict[str, str]
    ) -> asyncio.subprocess.Process:
        """
        Create subprocess based on DFT code invocation style.

        Args:
            input_file: Path to the input file
            work_dir: Working directory for execution
            env: Environment variables

        Returns:
            asyncio.subprocess.Process: The created subprocess

        Raises:
            LocalRunnerError: If process creation fails
        """
        invocation = self.code_config.invocation_style

        if invocation == InvocationStyle.STDIN:
            # CRYSTAL-style: exe < input > output (stdin redirection)
            return await asyncio.create_subprocess_exec(
                str(self.executable_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(work_dir),
                env=env
            )
        elif invocation == InvocationStyle.FLAG:
            # QE-style: exe -in input (flag-based input)
            return await asyncio.create_subprocess_exec(
                str(self.executable_path),
                "-in", str(input_file.name),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(work_dir),
                env=env
            )
        elif invocation == InvocationStyle.CWD:
            # VASP-style: exe (reads from cwd - INCAR, POSCAR, etc.)
            return await asyncio.create_subprocess_exec(
                str(self.executable_path),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(work_dir),
                env=env
            )
        else:
            raise LocalRunnerError(f"Unknown invocation style: {invocation}")

    async def _parse_results(
        self,
        output_file: Path,
        return_code: int
    ) -> JobResult:
        """
        Parse DFT output file using code-specific parser.

        Args:
            output_file: Path to the output file
            return_code: Process return code

        Returns:
            JobResult with extracted information
        """
        # Check if output file exists and is not empty
        if not output_file.exists() or output_file.stat().st_size == 0:
            return JobResult(
                success=False,
                final_energy=None,
                energy_unit=self.code_config.energy_unit,
                convergence_status="FAILED",
                errors=["Output file is missing or empty"],
                warnings=[],
                metadata={"return_code": return_code}
            )

        # Use code-specific parser
        try:
            parser = get_parser(self.config.dft_code)
            parse_result = await parser.parse(output_file)

            # Determine overall success
            success = (
                return_code == 0 and
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
                    "return_code": return_code,
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
                metadata={"return_code": return_code}
            )

    async def stop_job(self, job_id: int, timeout: float = 10.0) -> bool:
        """
        Stop a running job gracefully.

        Sends SIGTERM first, then SIGKILL if process doesn't terminate.

        Args:
            job_id: Database ID of the job to stop
            timeout: Seconds to wait before sending SIGKILL

        Returns:
            True if job was stopped, False if job was not running
        """
        process = self._active_processes.get(job_id)
        if not process:
            return False

        try:
            # Send SIGTERM for graceful shutdown
            process.send_signal(signal.SIGTERM)

            # Wait for process to terminate
            try:
                await asyncio.wait_for(process.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                # Process didn't terminate, send SIGKILL
                process.kill()
                await process.wait()

            # Remove from active processes
            self._active_processes.pop(job_id, None)
            return True

        except Exception:
            return False

    def is_job_running(self, job_id: int) -> bool:
        """
        Check if a job is currently running.

        Args:
            job_id: Database ID of the job

        Returns:
            True if job is running, False otherwise
        """
        process = self._active_processes.get(job_id)
        if not process:
            return False
        return process.returncode is None

    def get_process_pid(self, job_id: int) -> Optional[int]:
        """
        Get the PID for a running job, if available.

        Args:
            job_id: Database ID of the job

        Returns:
            PID as int if running, otherwise None
        """
        process = self._active_processes.get(job_id)
        if not process:
            return None
        return process.pid

    def get_last_result(self) -> Optional[JobResult]:
        """
        Get the result from the last completed job.

        Returns:
            JobResult if available, None otherwise

        Note:
            This method is deprecated. Use get_job_result(handle) instead
            for proper per-job result isolation.
        """
        return getattr(self, "_last_result", None)

    def get_job_result(self, job_handle: JobHandle) -> Optional[JobResult]:
        """
        Get the result for a specific job.

        Args:
            job_handle: Job handle from submit_job()

        Returns:
            JobResult if available, None if job hasn't completed
        """
        return self._job_results.get(job_handle)

    def get_job_error(self, job_handle: JobHandle) -> Optional[Exception]:
        """
        Get the exception for a failed job.

        Args:
            job_handle: Job handle from submit_job()

        Returns:
            Exception if job failed with an error, None otherwise
        """
        return self._job_errors.get(job_handle)

    # -------------------------------------------------------------------------
    # BaseRunner Interface Implementation
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
        Submit a job for execution (BaseRunner interface).

        This wraps the existing run_job method to conform to the BaseRunner API.

        Args:
            job_id: Database ID of the job
            input_file: Path to .d12 input file
            work_dir: Working directory for job execution
            threads: Number of OpenMP threads
            **kwargs: Additional options (ignored)

        Returns:
            JobHandle: String handle for the job (format: "local_{job_id}")
        """
        # Create job handle
        handle = JobHandle(f"local_{job_id}")
        self._job_handles[handle] = job_id
        self._job_work_dirs[handle] = work_dir

        # Start job execution in background, passing handle for result storage
        task = asyncio.create_task(self._run_job_task(handle, job_id, work_dir, threads))
        self._active_jobs[handle] = task

        return handle

    async def _run_job_task(self, handle: JobHandle, job_id: int, work_dir: Path, threads: Optional[int]):
        """Background task that runs a job to completion.

        Args:
            handle: Job handle for result/error storage
            job_id: Database ID of the job
            work_dir: Working directory for the job
            threads: Number of OpenMP threads
        """
        # Acquire slot to enforce max_concurrent_jobs limit
        async with self.acquire_slot():
            try:
                result: Optional[JobResult] = None
                # Consume output and capture the final yielded JobResult
                # run_job yields strings during execution, then yields JobResult at the end
                async for item in self.run_job(job_id, work_dir, threads):
                    if isinstance(item, JobResult):
                        # Capture the result directly - no race condition
                        result = item
                    # else: it's a status string, ignore it

                if result:
                    self._job_results[handle] = result
            except Exception as e:
                # Store exception for later retrieval - don't swallow it
                self._job_errors[handle] = e
                # Also create a failed result
                self._job_results[handle] = JobResult(
                    success=False,
                    final_energy=None,
                    convergence_status="FAILED",
                    errors=[str(e)],
                )

    async def get_status(self, job_handle: JobHandle) -> JobStatus:
        """
        Get job status (BaseRunner interface).

        Args:
            job_handle: Job handle from submit_job()

        Returns:
            JobStatus: Current status
        """
        job_id = self._job_handles.get(job_handle)
        if job_id is None:
            return JobStatus.UNKNOWN

        if self.is_job_running(job_id):
            return JobStatus.RUNNING

        # Check if task completed
        task = self._active_jobs.get(job_handle)
        if task is None:
            # Task not found - check if we have stored results
            if job_handle in self._job_results:
                result = self._job_results[job_handle]
                return JobStatus.COMPLETED if result.success else JobStatus.FAILED
            return JobStatus.UNKNOWN

        if task.done():
            # Check for successful completion using per-job results
            try:
                task.result()
                # Use per-job result storage instead of global _last_result
                result = self._job_results.get(job_handle)
                if result and result.success:
                    return JobStatus.COMPLETED
                return JobStatus.FAILED
            except asyncio.CancelledError:
                return JobStatus.CANCELLED
            except Exception:
                return JobStatus.FAILED

        return JobStatus.RUNNING

    async def cancel_job(self, job_handle: JobHandle) -> bool:
        """
        Cancel a job (BaseRunner interface).

        Args:
            job_handle: Job handle to cancel

        Returns:
            bool: True if cancelled, False if not running
        """
        job_id = self._job_handles.get(job_handle)
        if job_id is None:
            return False

        # Use existing stop_job method
        success = await self.stop_job(job_id)

        # Clean up tracking
        if success:
            task = self._active_jobs.pop(job_handle, None)
            if task:
                task.cancel()

        return success

    async def get_output(self, job_handle: JobHandle) -> AsyncIterator[str]:
        """
        Stream job output in real-time (BaseRunner interface).

        Reads the output file from the work directory, streaming
        new lines as they are appended by the running job.

        Args:
            job_handle: Job handle to stream from

        Yields:
            str: Output lines (without trailing newlines)

        Raises:
            LocalRunnerError: If job handle is invalid or work directory not found
        """
        job_id = self._job_handles.get(job_handle)
        if job_id is None:
            raise LocalRunnerError(f"Invalid job handle: {job_handle}")

        work_dir = self._job_work_dirs.get(job_handle)
        if work_dir is None:
            raise LocalRunnerError(f"Work directory not found for job {job_id}")

        # Determine output file based on DFT code
        # Output file is written as output{ext} by run_job() (see line ~224)
        output_file = work_dir / f"output{self.code_config.output_extension}"

        # Wait for output file to be created (up to 30 seconds)
        for _ in range(30):
            if output_file.exists():
                break
            await asyncio.sleep(1)
        else:
            yield f"⚠ Output file not found: {output_file}"
            return

        # Stream output file content
        last_position = 0
        while True:
            try:
                with open(output_file, "r") as f:
                    f.seek(last_position)
                    new_content = f.read()
                    if new_content:
                        for line in new_content.splitlines():
                            yield line
                        last_position = f.tell()

                # Check if job is still running
                status = await self.get_status(job_handle)
                if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                    # Final read to get any remaining content
                    with open(output_file, "r") as f:
                        f.seek(last_position)
                        final_content = f.read()
                        if final_content:
                            for line in final_content.splitlines():
                                yield line
                    break

                await asyncio.sleep(0.5)  # Poll interval for local files

            except FileNotFoundError:
                yield f"⚠ Output file removed: {output_file}"
                break
            except Exception as e:
                yield f"⚠ Error reading output: {e}"
                break

    async def retrieve_results(
        self,
        job_handle: JobHandle,
        dest: Path,
        cleanup: Optional[bool] = None
    ) -> None:
        """
        Retrieve results (BaseRunner interface).

        For local execution, copies output files from work_dir to dest if different.
        This includes the main output file and all auxiliary files defined in
        code_config.auxiliary_outputs.

        Args:
            job_handle: Job handle
            dest: Destination directory
            cleanup: Whether to clean up scratch after retrieval
                    (default: use config.cleanup_on_success/cleanup_on_failure)

        Raises:
            LocalRunnerError: If job handle is invalid or file operations fail
        """
        import shutil
        import logging
        logger = logging.getLogger(__name__)

        job_id = self._job_handles.get(job_handle)
        if job_id is None:
            raise LocalRunnerError(f"Invalid job handle: {job_handle}")

        work_dir = self._job_work_dirs.get(job_handle)
        if work_dir is None:
            raise LocalRunnerError(f"Work directory not found for job {job_id}")

        # Determine cleanup behavior
        if cleanup is None:
            result = self._job_results.get(job_handle)
            if result and result.success:
                cleanup = self.config.cleanup_on_success
            else:
                cleanup = self.config.cleanup_on_failure

        # If work_dir == dest, nothing to copy (but still may cleanup)
        if work_dir.resolve() == dest.resolve():
            logger.info(f"Work directory equals destination, skipping copy")
            if cleanup:
                logger.info(f"Cleaning up work directory: {work_dir}")
                try:
                    shutil.rmtree(work_dir)
                except Exception as e:
                    logger.warning(f"Failed to clean up work directory: {e}")
            return

        # Ensure destination exists
        dest.mkdir(parents=True, exist_ok=True)

        # Copy main output file
        output_file = work_dir / f"output{self.code_config.output_extension}"
        if output_file.exists():
            dest_output = dest / output_file.name
            try:
                shutil.copy2(output_file, dest_output)
                logger.info(f"Copied: {output_file.name} -> {dest_output}")
            except Exception as e:
                logger.warning(f"Failed to copy {output_file.name}: {e}")
        else:
            logger.warning(f"Main output file not found: {output_file}")

        # Copy auxiliary output files based on code_config
        copied_count = 0
        for fort_name, ext in self.code_config.auxiliary_outputs.items():
            src_file = work_dir / fort_name
            if src_file.exists():
                # Destination: use the extension mapping (e.g., fort.9 -> job.f9)
                dest_file = dest / f"{dest.stem}{ext}"
                try:
                    shutil.copy2(src_file, dest_file)
                    logger.debug(f"Copied: {fort_name} -> {dest_file.name}")
                    copied_count += 1
                except Exception as e:
                    logger.warning(f"Failed to copy {fort_name}: {e}")

        logger.info(f"Retrieved {copied_count + 1} output files to {dest}")

        # Cleanup if requested
        if cleanup:
            logger.info(f"Cleaning up work directory: {work_dir}")
            try:
                shutil.rmtree(work_dir)
            except Exception as e:
                logger.warning(f"Failed to clean up work directory: {e}")

    async def get_job_info(self, job_handle: JobHandle) -> JobInfo:
        """
        Get complete job information (BaseRunner interface).

        Args:
            job_handle: Job handle to query

        Returns:
            JobInfo: Complete job state
        """
        status = await self.get_status(job_handle)
        job_id = self._job_handles.get(job_handle)
        pid = self.get_process_pid(job_id) if job_id else None

        return JobInfo(
            job_handle=job_handle,
            status=status,
            work_dir=Path.cwd(),  # Would need to track actual work_dir
            pid=pid,
        )

    def is_connected(self) -> bool:
        """Check if runner is ready (BaseRunner interface)."""
        return self.executable_path.exists()

    async def cleanup(self) -> None:
        """
        Clean up resources and terminate active subprocesses.

        This method extends BaseRunner.cleanup() to also terminate
        any active CRYSTAL/DFT processes that may be running.
        """
        # First, terminate all active subprocesses
        for job_id, process in list(self._active_processes.items()):
            try:
                if process.returncode is None:  # Still running
                    # Send SIGTERM first for graceful shutdown
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        # Force kill if still running
                        process.kill()
                        await process.wait()
            except Exception:
                # Ignore errors during cleanup
                pass

        self._active_processes.clear()

        # Clean up job result/error tracking
        self._job_results.clear()
        self._job_errors.clear()

        # Call parent cleanup to cancel asyncio tasks
        await super().cleanup()


# Convenience function for simple usage
async def run_dft_job(
    work_dir: Path,
    dft_code: DFTCode = DFTCode.CRYSTAL,
    job_id: int = 0,
    threads: Optional[int] = None
) -> JobResult:
    """
    Simple wrapper to run a DFT job and get results.

    Args:
        work_dir: Path to directory containing input files
        dft_code: DFT code to use (default: CRYSTAL)
        job_id: Optional job ID for tracking
        threads: Number of OpenMP threads

    Returns:
        JobResult with structured results

    Example:
        >>> from pathlib import Path
        >>> work_dir = Path("/path/to/calculations/job_001_mgo")
        >>> result = await run_dft_job(work_dir)
        >>> if result.success:
        ...     print(f"Energy: {result.final_energy}")
    """
    config = RunnerConfig(dft_code=dft_code)
    runner = LocalRunner(config=config)

    # Collect all output lines
    output_lines: list[str] = []
    async for line in runner.run_job(job_id, work_dir, threads):
        output_lines.append(line)

    # Return the result
    result = runner.get_last_result()
    if result is None:
        raise LocalRunnerError("No result available after job completion")

    return result


# Backward-compatible alias
async def run_crystal_job(
    work_dir: Path,
    job_id: int = 0,
    threads: Optional[int] = None
) -> JobResult:
    """Backward-compatible alias for run_dft_job with CRYSTAL code."""
    return await run_dft_job(work_dir, DFTCode.CRYSTAL, job_id, threads)
