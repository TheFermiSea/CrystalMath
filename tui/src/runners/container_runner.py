"""
Container Runner for executing DFT codes in Apptainer/Singularity containers.

This module provides a container-based runner that wraps commands to execute
inside Apptainer containers. It supports:
- Local .sif container files
- Registry pulling from Docker Hub, Singularity Hub, etc.
- GPU passthrough via --nv flag
- Bind mounts for data access
- Overlay filesystem support for writable scratch

Container execution provides:
- Isolated, reproducible environments
- Easy deployment of codes like YAMBO without native installation
- GPU support without CUDA version conflicts
- Portable execution across different Linux distributions

Usage:
    # With local container file
    runner = ContainerRunner(
        container_path="/home/containers/yambo_5.2.0.sif",
        gpu_enabled=True,
    )

    # With registry pulling
    runner = ContainerRunner(
        container_uri="docker://yambocode/yambo:5.2.0-cuda11.8-gnu9",
        gpu_enabled=True,
        cache_dir=Path("/home/containers"),
    )
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.codes import DFTCode, get_code_config
from .base import BaseRunner, JobHandle, JobStatus, RunnerConfig
from .exceptions import ConfigurationError, RunnerError

logger = logging.getLogger(__name__)


class ContainerRunnerError(RunnerError):
    """Raised when container operations fail."""

    pass


class ContainerPullError(ContainerRunnerError):
    """Raised when container image pull fails."""

    pass


class ContainerValidationError(ContainerRunnerError):
    """Raised when container validation fails."""

    pass


@dataclass
class ContainerConfig:
    """
    Configuration for container execution.

    Attributes:
        container_path: Path to local .sif container file
        container_uri: URI for registry pull (docker://, shub://, oras://)
        gpu_enabled: Enable GPU passthrough with --nv flag
        bind_mounts: List of bind mount specifications (src:dest or src:dest:opts)
        environment: Environment variables to set inside container
        overlay: Overlay filesystem path for writable scratch
        contain: Isolate container from host (--contain flag)
        cleanenv: Clean environment inside container (--cleanenv flag)
        working_dir: Working directory inside container (--pwd)
        cache_dir: Directory for caching pulled containers
        pull_always: Always pull fresh image (ignore cache)
    """

    container_path: Path | None = None
    container_uri: str | None = None
    gpu_enabled: bool = True
    bind_mounts: list[str] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    overlay: Path | None = None
    contain: bool = False
    cleanenv: bool = False
    working_dir: Path | None = None
    cache_dir: Path = field(default_factory=lambda: Path.home() / ".apptainer" / "cache")
    pull_always: bool = False

    def __post_init__(self):
        """Validate configuration after initialization."""
        if not self.container_path and not self.container_uri:
            raise ConfigurationError("Either container_path or container_uri must be specified")

        # Normalize paths
        if self.container_path and not isinstance(self.container_path, Path):
            self.container_path = Path(self.container_path)

        if self.cache_dir and not isinstance(self.cache_dir, Path):
            self.cache_dir = Path(self.cache_dir)

        if self.overlay and not isinstance(self.overlay, Path):
            self.overlay = Path(self.overlay)

        if self.working_dir and not isinstance(self.working_dir, Path):
            self.working_dir = Path(self.working_dir)

    def get_container_path(self) -> Path | None:
        """
        Get the path to the container file.

        If using a URI, this returns the expected cache path.

        Returns:
            Path to container file, or None if not yet pulled
        """
        if self.container_path:
            return self.container_path

        if self.container_uri:
            # Convert URI to cache filename
            # docker://user/image:tag -> user_image_tag.sif
            name = self._uri_to_filename(self.container_uri)
            return self.cache_dir / name

        return None

    @staticmethod
    def _uri_to_filename(uri: str) -> str:
        """Convert container URI to a safe filename."""
        # Remove protocol prefix
        name = re.sub(r"^(docker|shub|oras|library)://", "", uri)
        # Replace special characters
        name = re.sub(r"[/:@]", "_", name)
        # Add .sif extension if not present
        if not name.endswith(".sif"):
            name += ".sif"
        return name


class ContainerRunner(BaseRunner):
    """
    Execute DFT codes inside Apptainer/Singularity containers.

    This runner wraps commands to execute inside containers, providing:
    - Isolation from host system
    - Reproducible execution environments
    - GPU support via NVIDIA container toolkit
    - Easy deployment of complex software stacks

    Supports both local .sif files and registry pulling.

    Example:
        # Using local container
        runner = ContainerRunner(
            container_path=Path("/home/containers/yambo.sif"),
            gpu_enabled=True,
        )

        # Using registry
        runner = ContainerRunner(
            container_uri="docker://yambocode/yambo:5.2.0",
            gpu_enabled=True,
        )

    Attributes:
        container_config: Container configuration
        dft_code: DFT code to run
        code_config: DFTCodeConfig for the selected code
    """

    def __init__(
        self,
        container_path: str | Path | None = None,
        container_uri: str | None = None,
        dft_code: DFTCode = DFTCode.CRYSTAL,
        gpu_enabled: bool = True,
        bind_mounts: list[str] | None = None,
        environment: dict[str, str] | None = None,
        config: RunnerConfig | None = None,
        container_config: ContainerConfig | None = None,
    ):
        """
        Initialize the container runner.

        Args:
            container_path: Path to local .sif container file
            container_uri: URI for registry pull (docker://, shub://)
            dft_code: DFT code to run
            gpu_enabled: Enable GPU passthrough
            bind_mounts: Additional bind mount specifications
            environment: Environment variables for container
            config: Runner configuration
            container_config: Full container configuration (overrides other args)
        """
        super().__init__(config)

        # Build container config from arguments or use provided
        if container_config:
            self.container_config = container_config
        else:
            self.container_config = ContainerConfig(
                container_path=Path(container_path) if container_path else None,
                container_uri=container_uri,
                gpu_enabled=gpu_enabled,
                bind_mounts=bind_mounts or [],
                environment=environment or {},
            )

        self.dft_code = dft_code
        self.code_config = get_code_config(dft_code)

        # Track job state
        self._jobs: dict[str, dict[str, Any]] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}

        # Container binary detection
        self._container_binary: str | None = None

        logger.info(
            f"Initialized ContainerRunner for {self.code_config.display_name}, "
            f"container={self.container_config.container_path or self.container_config.container_uri}"
        )

    async def connect(self) -> None:
        """
        Validate container setup and pull image if needed.

        This method:
        1. Detects available container runtime (apptainer/singularity)
        2. Validates local container file exists (if using path)
        3. Pulls container from registry (if using URI)

        Raises:
            ConfigurationError: If no container runtime found
            ContainerPullError: If registry pull fails
            ContainerValidationError: If container validation fails
        """
        # Detect container runtime
        self._container_binary = await self._detect_container_runtime()
        if not self._container_binary:
            raise ConfigurationError(
                "No container runtime found. Install apptainer or singularity."
            )

        logger.info(f"Using container runtime: {self._container_binary}")

        # If using local path, validate it exists
        if self.container_config.container_path:
            if not self.container_config.container_path.exists():
                raise ContainerValidationError(
                    f"Container file not found: {self.container_config.container_path}"
                )
            logger.info(f"Using local container: {self.container_config.container_path}")

        # If using URI, pull the container
        elif self.container_config.container_uri:
            await self._pull_container()

    async def _detect_container_runtime(self) -> str | None:
        """
        Detect available container runtime.

        Checks for apptainer first (preferred), then singularity.

        Returns:
            Name of available container binary, or None if not found
        """
        for binary in ["apptainer", "singularity"]:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "which",
                    binary,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0 and stdout.strip():
                    return binary
            except Exception:
                continue
        return None

    async def _pull_container(self) -> None:
        """
        Pull container image from registry.

        Handles:
        - docker:// URIs (Docker Hub)
        - shub:// URIs (Singularity Hub)
        - oras:// URIs (OCI registries)
        - library:// URIs (Sylabs Cloud)

        Raises:
            ContainerPullError: If pull fails
        """
        if not self.container_config.container_uri:
            return

        # Get expected cache path
        cache_path = self.container_config.get_container_path()
        if not cache_path:
            raise ContainerPullError("Could not determine cache path for container")

        # Check if already cached
        if cache_path.exists() and not self.container_config.pull_always:
            logger.info(f"Using cached container: {cache_path}")
            return

        # Create cache directory
        self.container_config.cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Pulling container: {self.container_config.container_uri}")

        # Build pull command
        cmd = [
            self._container_binary,
            "pull",
            "--force" if self.container_config.pull_always else "",
            str(cache_path),
            self.container_config.container_uri,
        ]
        cmd = [c for c in cmd if c]  # Remove empty strings

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise ContainerPullError(f"Failed to pull container: {stderr.decode()}")

            if not cache_path.exists():
                raise ContainerPullError(
                    f"Container pull succeeded but file not found: {cache_path}"
                )

            logger.info(f"Successfully pulled container to: {cache_path}")

        except ContainerPullError:
            raise
        except Exception as e:
            raise ContainerPullError(f"Container pull failed: {e}") from e

    def _build_exec_command(
        self,
        command: str,
        work_dir: Path | None = None,
        extra_binds: list[str] | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> list[str]:
        """
        Build the container exec command with all flags.

        Args:
            command: Command to execute inside container
            work_dir: Working directory (adds bind mount and --pwd)
            extra_binds: Additional bind mounts for this execution
            extra_env: Additional environment variables

        Returns:
            Full command list for subprocess execution
        """
        container_path = self.container_config.get_container_path()
        if not container_path:
            raise ContainerRunnerError("No container path available")

        cmd = [self._container_binary or "apptainer", "exec"]

        # GPU support
        if self.container_config.gpu_enabled:
            cmd.append("--nv")

        # Contain/cleanenv flags
        if self.container_config.contain:
            cmd.append("--contain")
        if self.container_config.cleanenv:
            cmd.append("--cleanenv")

        # Bind mounts
        all_binds = list(self.container_config.bind_mounts)
        if extra_binds:
            all_binds.extend(extra_binds)

        # Add work directory as bind mount if specified
        if work_dir:
            all_binds.append(f"{work_dir}:{work_dir}")

        for bind in all_binds:
            cmd.extend(["--bind", bind])

        # Environment variables
        all_env = dict(self.container_config.environment)
        if extra_env:
            all_env.update(extra_env)

        for key, value in all_env.items():
            cmd.extend(["--env", f"{key}={value}"])

        # Overlay filesystem
        if self.container_config.overlay:
            cmd.extend(["--overlay", str(self.container_config.overlay)])

        # Working directory
        pwd = work_dir or self.container_config.working_dir
        if pwd:
            cmd.extend(["--pwd", str(pwd)])

        # Container image
        cmd.append(str(container_path))

        # Command to execute (using bash -c for complex commands)
        cmd.extend(["bash", "-c", command])

        return cmd

    async def submit_job(
        self, job_id: int, input_file: Path, work_dir: Path, threads: int | None = None, **kwargs
    ) -> JobHandle:
        """
        Submit a job for execution in a container.

        This method:
        1. Validates input files exist
        2. Builds the containerized command
        3. Launches the process in the background
        4. Returns a job handle for tracking

        Args:
            job_id: Database ID of the job
            input_file: Path to the input file
            work_dir: Path to the job's working directory
            threads: Number of OpenMP threads
            **kwargs: Additional execution options

        Returns:
            JobHandle for tracking this job

        Raises:
            ContainerRunnerError: If submission fails
        """
        # Validate input
        if not input_file.exists():
            raise ContainerRunnerError(f"Input file not found: {input_file}")

        if not work_dir.exists():
            work_dir.mkdir(parents=True, exist_ok=True)

        # Build execution command based on DFT code
        exec_cmd = self._build_dft_command(input_file, threads)

        # Environment for OMP threads
        extra_env = {}
        if threads:
            extra_env["OMP_NUM_THREADS"] = str(threads)

        # Build full containerized command
        cmd = self._build_exec_command(
            command=exec_cmd,
            work_dir=work_dir,
            extra_env=extra_env,
        )

        logger.debug(f"Container command: {' '.join(cmd)}")

        try:
            # Launch process
            output_file = work_dir / "output.log"

            with open(output_file, "w") as out_f:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=out_f,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=str(work_dir),
                )

            # Create job handle
            handle = JobHandle(f"container:{job_id}:{proc.pid}:{work_dir}")

            # Track job
            self._jobs[str(handle)] = {
                "job_id": job_id,
                "pid": proc.pid,
                "work_dir": work_dir,
                "status": JobStatus.RUNNING,
                "output_file": output_file,
            }
            self._processes[str(handle)] = proc

            logger.info(f"Submitted container job {job_id}, PID={proc.pid}")
            return handle

        except Exception as e:
            raise ContainerRunnerError(f"Job submission failed: {e}") from e

    def _build_dft_command(
        self,
        input_file: Path,
        threads: int | None = None,
    ) -> str:
        """
        Build the DFT execution command based on code type.

        Args:
            input_file: Path to input file
            threads: Number of threads

        Returns:
            Command string for execution
        """
        # Get executable from code config
        executable = self.code_config.default_executable

        # Build command based on invocation style
        from ..core.codes import InvocationStyle

        if self.code_config.invocation_style == InvocationStyle.STDIN:
            # CRYSTAL style: executable < input.d12 > output.out
            return f"{executable} < {input_file.name} > output.out 2>&1"

        elif self.code_config.invocation_style == InvocationStyle.FLAG:
            # QE style: pw.x -i input.in > output.out
            flag = self.code_config.input_flag or "-i"
            return f"{executable} {flag} {input_file.name} > output.out 2>&1"

        elif self.code_config.invocation_style == InvocationStyle.CWD:
            # VASP style: executable reads from CWD
            return f"{executable} > output.out 2>&1"

        elif self.code_config.invocation_style == InvocationStyle.ARGUMENT:
            # YAMBO style: executable with various flags
            return f"{executable} > output.out 2>&1"

        else:
            # Default: try stdin
            return f"{executable} < {input_file.name} > output.out 2>&1"

    async def get_status(self, job_handle: JobHandle) -> JobStatus:
        """
        Get the current status of a container job.

        Args:
            job_handle: Job identifier

        Returns:
            Current job status
        """
        handle_str = str(job_handle)

        if handle_str not in self._jobs:
            return JobStatus.UNKNOWN

        job_info = self._jobs[handle_str]
        proc = self._processes.get(handle_str)

        if not proc:
            return job_info.get("status", JobStatus.UNKNOWN)

        # Check if process is still running
        if proc.returncode is None:
            # Process still running, poll to update
            try:
                # Non-blocking poll
                proc._transport.get_pid()  # Check if process exists
                return JobStatus.RUNNING
            except Exception:
                pass

        # Process has exited
        if proc.returncode == 0:
            self._jobs[handle_str]["status"] = JobStatus.COMPLETED
            return JobStatus.COMPLETED
        else:
            self._jobs[handle_str]["status"] = JobStatus.FAILED
            return JobStatus.FAILED

    async def cancel_job(self, job_handle: JobHandle) -> bool:
        """
        Cancel a running container job.

        Args:
            job_handle: Job identifier to cancel

        Returns:
            True if job was cancelled, False otherwise
        """
        handle_str = str(job_handle)

        proc = self._processes.get(handle_str)
        if not proc:
            return False

        if proc.returncode is not None:
            # Already finished
            return False

        try:
            proc.terminate()
            await asyncio.sleep(1)

            if proc.returncode is None:
                proc.kill()

            self._jobs[handle_str]["status"] = JobStatus.CANCELLED
            logger.info(f"Cancelled job {job_handle}")
            return True

        except Exception as e:
            logger.error(f"Failed to cancel job {job_handle}: {e}")
            return False

    async def get_output(self, job_handle: JobHandle) -> AsyncIterator[str]:
        """
        Stream job output from the container.

        Args:
            job_handle: Job identifier

        Yields:
            Output lines from the job
        """
        handle_str = str(job_handle)

        if handle_str not in self._jobs:
            yield f"Job not found: {job_handle}"
            return

        job_info = self._jobs[handle_str]
        output_file: Path = job_info["output_file"]

        if not output_file.exists():
            yield f"Output file not found: {output_file}"
            return

        # Track position for incremental reads
        last_pos = 0

        while True:
            status = await self.get_status(job_handle)

            # Read new content
            try:
                with open(output_file) as f:
                    f.seek(last_pos)
                    content = f.read()
                    if content:
                        for line in content.splitlines():
                            yield line
                        last_pos = f.tell()
            except Exception as e:
                yield f"Error reading output: {e}"

            # Check for terminal states
            if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                # Final read
                try:
                    with open(output_file) as f:
                        f.seek(last_pos)
                        content = f.read()
                        if content:
                            for line in content.splitlines():
                                yield line
                except Exception:
                    pass
                break

            await asyncio.sleep(1)

    async def retrieve_results(
        self, job_handle: JobHandle, dest: Path, cleanup: bool | None = None
    ) -> None:
        """
        Retrieve results from a completed container job.

        For local container execution, results are already in work_dir.
        This method copies them to the destination if different.

        Args:
            job_handle: Job identifier
            dest: Destination directory for results
            cleanup: Whether to clean up scratch files
        """
        handle_str = str(job_handle)

        if handle_str not in self._jobs:
            raise ContainerRunnerError(f"Job not found: {job_handle}")

        job_info = self._jobs[handle_str]
        work_dir: Path = job_info["work_dir"]

        # If destination is same as work_dir, nothing to do
        if dest.resolve() == work_dir.resolve():
            logger.info("Results already in destination directory")
            return

        # Copy result files
        dest.mkdir(parents=True, exist_ok=True)

        # Build list of files to copy based on code config
        patterns = ["output.*", "*.out", "*.log"]
        for ext in self.code_config.auxiliary_outputs.values():
            patterns.append(f"*{ext}")

        import shutil

        copied = []
        for pattern in patterns:
            for file_path in work_dir.glob(pattern):
                if file_path.is_file():
                    shutil.copy2(file_path, dest / file_path.name)
                    copied.append(file_path.name)

        logger.info(f"Retrieved {len(copied)} result files to {dest}")

        # Cleanup if requested
        if cleanup:
            shutil.rmtree(work_dir)
            logger.info(f"Cleaned up work directory: {work_dir}")

    async def run_command(
        self,
        command: str,
        work_dir: Path | None = None,
        capture_output: bool = True,
    ) -> tuple[int, str, str]:
        """
        Run a single command inside the container.

        Convenience method for one-off commands like p2y, yambo -p p, etc.

        Args:
            command: Command to execute
            work_dir: Working directory
            capture_output: Whether to capture stdout/stderr

        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        cmd = self._build_exec_command(command=command, work_dir=work_dir)

        if capture_output:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(work_dir) if work_dir else None,
            )
            stdout, stderr = await proc.communicate()
            return proc.returncode or 0, stdout.decode(), stderr.decode()
        else:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(work_dir) if work_dir else None,
            )
            await proc.wait()
            return proc.returncode or 0, "", ""

    def is_connected(self) -> bool:
        """Check if container runtime is available."""
        return self._container_binary is not None


# Convenience factory functions


def create_yambo_runner(
    container_path: Path | None = None,
    container_uri: str = "docker://yambocode/yambo:5.2.0-cuda11.8-gnu9",
    gpu_enabled: bool = True,
    **kwargs,
) -> ContainerRunner:
    """
    Create a ContainerRunner configured for YAMBO.

    Args:
        container_path: Local .sif file path (uses URI if None)
        container_uri: Registry URI for YAMBO container
        gpu_enabled: Enable GPU support
        **kwargs: Additional ContainerRunner arguments

    Returns:
        Configured ContainerRunner for YAMBO
    """
    # YAMBO uses ARGUMENT invocation style
    # Note: YAMBO not yet in DFTCode enum, use CRYSTAL as fallback
    return ContainerRunner(
        container_path=container_path,
        container_uri=container_uri if not container_path else None,
        dft_code=DFTCode.CRYSTAL,  # Will update when YAMBO added to enum
        gpu_enabled=gpu_enabled,
        **kwargs,
    )


def create_qe_container_runner(
    container_path: Path | None = None,
    container_uri: str = "docker://qe-forge/q-e-sirius:v7.3-cuda11.8",
    gpu_enabled: bool = True,
    **kwargs,
) -> ContainerRunner:
    """
    Create a ContainerRunner configured for Quantum Espresso.

    Args:
        container_path: Local .sif file path
        container_uri: Registry URI for QE container
        gpu_enabled: Enable GPU support
        **kwargs: Additional arguments

    Returns:
        Configured ContainerRunner for QE
    """
    return ContainerRunner(
        container_path=container_path,
        container_uri=container_uri if not container_path else None,
        dft_code=DFTCode.QUANTUM_ESPRESSO,
        gpu_enabled=gpu_enabled,
        **kwargs,
    )
