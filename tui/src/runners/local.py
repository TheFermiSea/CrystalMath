"""
Local job execution backend for CRYSTAL calculations.

This module implements the LocalRunner class which executes CRYSTAL jobs
on the local machine using the configured crystalOMP executable.
"""

import asyncio
import os
import signal
from pathlib import Path
from typing import Dict, Any, Optional, AsyncIterator
from dataclasses import dataclass


@dataclass
class JobResult:
    """Structured results from a completed CRYSTAL job."""
    success: bool
    final_energy: Optional[float]
    convergence_status: str
    errors: list[str]
    warnings: list[str]
    metadata: Dict[str, Any]


class LocalRunnerError(Exception):
    """Base exception for LocalRunner errors."""
    pass


class ExecutableNotFoundError(LocalRunnerError):
    """Raised when the CRYSTAL executable cannot be found."""
    pass


class InputFileError(LocalRunnerError):
    """Raised when there are issues with the input file."""
    pass


class LocalRunner:
    """
    Executes CRYSTAL jobs locally using asyncio subprocess management.

    This runner:
    - Validates the input file exists (input.d12)
    - Launches crystalOMP executable with non-blocking execution
    - Streams stdout/stderr in real-time for live monitoring
    - Parses output using CRYSTALpytools after completion
    - Returns structured results including energy, convergence, errors

    Attributes:
        executable_path: Path to the crystalOMP executable
        default_threads: Number of OpenMP threads to use
    """

    def __init__(
        self,
        executable_path: Optional[Path] = None,
        default_threads: Optional[int] = None
    ):
        """
        Initialize the LocalRunner.

        Args:
            executable_path: Path to crystalOMP. If None, reads from CRY23_EXEDIR env var.
            default_threads: Number of OpenMP threads. If None, uses all available cores.

        Raises:
            ExecutableNotFoundError: If executable cannot be found or is not executable.
        """
        self.executable_path = self._resolve_executable(executable_path)
        self.default_threads = default_threads or os.cpu_count() or 4
        self._active_processes: Dict[int, asyncio.subprocess.Process] = {}

    def _resolve_executable(self, executable_path: Optional[Path]) -> Path:
        """
        Resolve the path to the crystalOMP executable.

        Priority order:
        1. Explicitly provided path
        2. CRY23_EXEDIR environment variable
        3. PATH lookup

        Args:
            executable_path: Optional explicit path to executable

        Returns:
            Path to the crystalOMP executable

        Raises:
            ExecutableNotFoundError: If executable cannot be found
        """
        # Try explicit path first
        if executable_path:
            if executable_path.exists() and os.access(executable_path, os.X_OK):
                return executable_path
            raise ExecutableNotFoundError(
                f"Provided executable path does not exist or is not executable: {executable_path}"
            )

        # Try CRY23_EXEDIR environment variable
        cry23_exedir = os.environ.get("CRY23_EXEDIR")
        if cry23_exedir:
            exe_path = Path(cry23_exedir) / "crystalOMP"
            if exe_path.exists() and os.access(exe_path, os.X_OK):
                return exe_path

        # Try PATH lookup
        import shutil
        exe_in_path = shutil.which("crystalOMP")
        if exe_in_path:
            return Path(exe_in_path)

        raise ExecutableNotFoundError(
            "Could not find crystalOMP executable. "
            "Please set CRY23_EXEDIR environment variable or provide explicit path. "
            f"Searched: explicit path={executable_path}, "
            f"CRY23_EXEDIR={cry23_exedir}, PATH lookup failed"
        )

    async def run_job(
        self,
        job_id: int,
        work_dir: Path,
        threads: Optional[int] = None
    ) -> AsyncIterator[str]:
        """
        Execute a CRYSTAL job and stream output in real-time.

        This is an async generator that yields output lines as they are produced.
        After the job completes, it parses the results using CRYSTALpytools.

        The job runs in the specified work directory which must contain:
        - input.d12: CRYSTAL input file

        Output files created:
        - output.out: Main CRYSTAL output
        - fort.9, fort.98, etc.: CRYSTAL internal files

        Args:
            job_id: Database ID of the job (for tracking)
            work_dir: Path to the job's working directory
            threads: Number of OpenMP threads (default: use self.default_threads)

        Yields:
            Lines of output from stdout/stderr as they are produced

        Returns:
            JobResult object with structured results after completion

        Raises:
            InputFileError: If input.d12 does not exist or is empty
            LocalRunnerError: If the job fails to start or encounters errors
        """
        # Validate input file
        input_file = work_dir / "input.d12"
        if not input_file.exists():
            raise InputFileError(f"Input file not found: {input_file}")
        if input_file.stat().st_size == 0:
            raise InputFileError(f"Input file is empty: {input_file}")

        # Setup output file
        output_file = work_dir / "output.out"

        # Prepare environment with OpenMP settings
        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = str(threads or self.default_threads)

        # Build command: crystalOMP < input.d12 > output.out 2>&1
        try:
            process = await asyncio.create_subprocess_exec(
                str(self.executable_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(work_dir),
                env=env
            )

            # Track the process
            self._active_processes[job_id] = process

            # Read input file content
            input_content = input_file.read_bytes()

            # Write to stdin and close it
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
                    yield f"  Final energy: {result.final_energy:.10f} Ha"
                yield f"  Convergence: {result.convergence_status}"
            else:
                yield f"\n✗ Job failed"
                for error in result.errors:
                    yield f"  Error: {error}"

            if result.warnings:
                yield f"\nWarnings ({len(result.warnings)}):"
                for warning in result.warnings:
                    yield f"  ⚠ {warning}"

            # Store result for retrieval
            self._last_result = result

        except Exception as e:
            self._active_processes.pop(job_id, None)
            raise LocalRunnerError(f"Failed to execute CRYSTAL job: {e}") from e

    async def _parse_results(
        self,
        output_file: Path,
        return_code: int
    ) -> JobResult:
        """
        Parse CRYSTAL output file using CRYSTALpytools.

        Args:
            output_file: Path to the output.out file
            return_code: Process return code

        Returns:
            JobResult with extracted information
        """
        errors: list[str] = []
        warnings: list[str] = []
        final_energy: Optional[float] = None
        convergence_status = "UNKNOWN"
        metadata: Dict[str, Any] = {}

        # Check if output file exists and is not empty
        if not output_file.exists() or output_file.stat().st_size == 0:
            errors.append("Output file is missing or empty")
            return JobResult(
                success=False,
                final_energy=None,
                convergence_status="FAILED",
                errors=errors,
                warnings=warnings,
                metadata={"return_code": return_code}
            )

        # Try to parse with CRYSTALpytools
        try:
            from CRYSTALpytools.crystal_io import Crystal_output

            cry_out = Crystal_output(str(output_file))

            # Extract final energy
            if hasattr(cry_out, "get_final_energy"):
                try:
                    final_energy = cry_out.get_final_energy()
                    metadata["energy_unit"] = "Hartree"
                except Exception as e:
                    warnings.append(f"Could not extract final energy: {e}")

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

            # Check for errors
            if hasattr(cry_out, "get_errors"):
                try:
                    crystal_errors = cry_out.get_errors()
                    if crystal_errors:
                        errors.extend(crystal_errors)
                except Exception:
                    pass

            # Check for warnings
            if hasattr(cry_out, "get_warnings"):
                try:
                    crystal_warnings = cry_out.get_warnings()
                    if crystal_warnings:
                        warnings.extend(crystal_warnings)
                except Exception:
                    pass

            # Extract additional metadata
            if hasattr(cry_out, "get_system_info"):
                try:
                    metadata["system_info"] = cry_out.get_system_info()
                except Exception:
                    pass

        except ImportError:
            # Fallback: Manual parsing if CRYSTALpytools not available
            warnings.append("CRYSTALpytools not available, using fallback parser")
            final_energy, convergence_status, parse_errors = self._fallback_parse(
                output_file
            )
            errors.extend(parse_errors)

        except Exception as e:
            errors.append(f"CRYSTALpytools parsing failed: {e}")
            # Try fallback parser
            final_energy, convergence_status, parse_errors = self._fallback_parse(
                output_file
            )
            errors.extend(parse_errors)

        # Add return code to metadata
        metadata["return_code"] = return_code

        # Determine overall success
        success = (
            return_code == 0 and
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

        This implements basic pattern matching to extract:
        - Final energy
        - Convergence status
        - Common error messages

        Args:
            output_file: Path to output.out

        Returns:
            Tuple of (final_energy, convergence_status, errors)
        """
        final_energy: Optional[float] = None
        convergence_status = "UNKNOWN"
        errors: list[str] = []

        try:
            with output_file.open("r") as f:
                content = f.read()
                lines = content.split("\n")

            # Look for final energy patterns
            # CRYSTAL typically prints: "TOTAL ENERGY(DFT)(AU)( 123) -1234.567890123456 DE-1.2E-09"
            for line in lines:
                if "TOTAL ENERGY" in line and "AU" in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == "TOTAL" and i + 2 < len(parts):
                            try:
                                # Look for number after ENERGY
                                for j in range(i + 2, len(parts)):
                                    try:
                                        energy = float(parts[j])
                                        final_energy = energy
                                        break
                                    except ValueError:
                                        continue
                            except (ValueError, IndexError):
                                pass

            # Check convergence
            if "CONVERGENCE" in content and "SCF" in content:
                if "CONVERGENCE REACHED" in content or "SCF ENDED" in content:
                    convergence_status = "CONVERGED"
                elif "NOT CONVERGED" in content or "CONVERGENCE FAILED" in content:
                    convergence_status = "NOT_CONVERGED"

            # Check for common errors
            error_patterns = [
                "ERROR",
                "FATAL",
                "ABNORMAL",
                "STOP",
                "FAILED"
            ]

            for line in lines:
                line_upper = line.upper()
                for pattern in error_patterns:
                    if pattern in line_upper:
                        errors.append(line.strip())
                        break

        except Exception as e:
            errors.append(f"Fallback parsing failed: {e}")

        return final_energy, convergence_status, errors

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

    def get_last_result(self) -> Optional[JobResult]:
        """
        Get the result from the last completed job.

        Returns:
            JobResult if available, None otherwise
        """
        return getattr(self, "_last_result", None)


# Convenience function for simple usage
async def run_crystal_job(
    work_dir: Path,
    job_id: int = 0,
    threads: Optional[int] = None
) -> JobResult:
    """
    Simple wrapper to run a CRYSTAL job and get results.

    Args:
        work_dir: Path to directory containing input.d12
        job_id: Optional job ID for tracking
        threads: Number of OpenMP threads

    Returns:
        JobResult with structured results

    Example:
        >>> from pathlib import Path
        >>> work_dir = Path("/path/to/calculations/job_001_mgo")
        >>> result = await run_crystal_job(work_dir)
        >>> if result.success:
        ...     print(f"Energy: {result.final_energy}")
    """
    runner = LocalRunner()

    # Collect all output lines
    output_lines: list[str] = []
    async for line in runner.run_job(job_id, work_dir, threads):
        output_lines.append(line)

    # Return the result
    result = runner.get_last_result()
    if result is None:
        raise LocalRunnerError("No result available after job completion")

    return result
