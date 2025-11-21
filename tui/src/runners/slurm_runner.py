"""
SLURM Runner for batch job submission to HPC clusters.

This module provides a SLURM-based runner that submits CRYSTAL jobs
to HPC clusters with batch scheduling. It handles:
- Dynamic SLURM script generation
- Job submission via sbatch
- Non-blocking status monitoring with squeue
- Job arrays for parameter sweeps
- Automatic result retrieval
"""

import asyncio
import re
import logging
from pathlib import Path
from typing import AsyncIterator, Optional, Dict, List, Tuple
from dataclasses import dataclass, field
from enum import Enum

from .base import BaseRunner
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


class SLURMRunnerError(Exception):
    """Base exception for SLURM Runner errors."""
    pass


class SLURMSubmissionError(SLURMRunnerError):
    """Raised when job submission fails."""
    pass


class SLURMStatusError(SLURMRunnerError):
    """Raised when status checking fails."""
    pass


class SLURMRunner(BaseRunner):
    """
    Execute CRYSTAL jobs via SLURM batch system on HPC clusters.

    This runner:
    - Generates SLURM submission scripts dynamically
    - Submits jobs using sbatch via SSH
    - Polls job status with squeue
    - Downloads results when job completes
    - Supports job arrays for parameter sweeps
    - Handles job dependencies for workflows

    Attributes:
        connection_manager: SSH connection manager
        cluster_id: ID of the cluster to submit jobs to
        default_config: Default SLURM job configuration
        poll_interval: Seconds between status checks (default: 30)
    """

    def __init__(
        self,
        connection_manager: ConnectionManager,
        cluster_id: int,
        default_config: Optional[SLURMJobConfig] = None,
        poll_interval: int = 30,
        remote_scratch_base: str = "/scratch/crystal"
    ):
        """
        Initialize the SLURM Runner.

        Args:
            connection_manager: ConnectionManager instance for SSH
            cluster_id: Database ID of the cluster
            default_config: Default SLURM job configuration
            poll_interval: Seconds to wait between status checks
            remote_scratch_base: Base directory for remote scratch space
        """
        self.connection_manager = connection_manager
        self.cluster_id = cluster_id
        self.default_config = default_config or SLURMJobConfig(job_name="crystal_job")
        self.poll_interval = poll_interval
        self.remote_scratch_base = remote_scratch_base

        # Track job ID mappings: our job_id -> SLURM job_id
        self._slurm_job_ids: Dict[int, str] = {}

        # Track job states
        self._job_states: Dict[int, SLURMJobState] = {}

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
                await conn.run(f"mkdir -p {remote_work_dir}")

                # Transfer files using SFTP
                async with conn.start_sftp_client() as sftp:
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
                    f"cd {remote_work_dir} && sbatch job.slurm",
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

        Args:
            job_id: Database ID of the job to cancel

        Returns:
            True if job was cancelled, False if not running or cancel failed
        """
        slurm_job_id = self._slurm_job_ids.get(job_id)
        if not slurm_job_id:
            logger.warning(f"No SLURM job ID found for job {job_id}")
            return False

        try:
            async with self.connection_manager.get_connection(self.cluster_id) as conn:
                result = await conn.run(f"scancel {slurm_job_id}", check=False)

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

    def _generate_slurm_script(
        self,
        config: SLURMJobConfig,
        work_dir: str
    ) -> str:
        """
        Generate a SLURM submission script.

        Args:
            config: SLURM job configuration
            work_dir: Remote working directory

        Returns:
            Complete SLURM script as string
        """
        lines = ["#!/bin/bash"]

        # Required directives
        lines.append(f"#SBATCH --job-name={config.job_name}")
        lines.append(f"#SBATCH --nodes={config.nodes}")
        lines.append(f"#SBATCH --ntasks={config.ntasks}")
        lines.append(f"#SBATCH --cpus-per-task={config.cpus_per_task}")
        lines.append(f"#SBATCH --time={config.time_limit}")

        # Output/error files
        lines.append("#SBATCH --output=slurm-%j.out")
        lines.append("#SBATCH --error=slurm-%j.err")

        # Optional directives
        if config.partition:
            lines.append(f"#SBATCH --partition={config.partition}")
        if config.memory:
            lines.append(f"#SBATCH --mem={config.memory}")
        if config.account:
            lines.append(f"#SBATCH --account={config.account}")
        if config.qos:
            lines.append(f"#SBATCH --qos={config.qos}")
        if config.email:
            lines.append(f"#SBATCH --mail-user={config.email}")
            if config.email_type:
                lines.append(f"#SBATCH --mail-type={config.email_type}")
        if config.constraint:
            lines.append(f"#SBATCH --constraint={config.constraint}")
        if config.exclusive:
            lines.append("#SBATCH --exclusive")
        if config.dependencies:
            dep_str = ":".join(config.dependencies)
            lines.append(f"#SBATCH --dependency=afterok:{dep_str}")
        if config.array:
            lines.append(f"#SBATCH --array={config.array}")

        lines.append("")

        # Environment setup
        lines.append("# Environment setup")

        # Load modules
        if config.modules:
            for module in config.modules:
                lines.append(f"module load {module}")

        # Custom environment setup
        if config.environment_setup:
            lines.append(config.environment_setup)

        # Set OpenMP threads
        lines.append(f"export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK")

        lines.append("")

        # Change to work directory
        lines.append("# Change to working directory")
        lines.append(f"cd {work_dir}")

        lines.append("")

        # Execution command
        lines.append("# Run CRYSTAL calculation")
        if config.ntasks > 1:
            # MPI execution
            lines.append("srun PcrystalOMP < input.d12 > output.out 2>&1")
        else:
            # Serial/OpenMP execution
            lines.append("crystalOMP < input.d12 > output.out 2>&1")

        lines.append("")

        # Exit code
        lines.append("exit_code=$?")
        lines.append("echo \"Job finished with exit code: $exit_code\"")
        lines.append("exit $exit_code")

        return "\n".join(lines)

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
                f"squeue -j {slurm_job_id} -h -o '%T|%r'",
                check=False
            )

            if result.exit_status != 0 or not result.stdout.strip():
                # Job not in queue - check if completed or failed
                sacct_result = await connection.run(
                    f"sacct -j {slurm_job_id} -n -o State -P | head -n1",
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
            async with connection.start_sftp_client() as sftp:
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

                for remote_file in remote_files:
                    # Check if file matches any pattern
                    should_download = False
                    for pattern in download_patterns:
                        if pattern == remote_file or (
                            "*" in pattern and
                            remote_file.endswith(pattern.replace("*", ""))
                        ):
                            should_download = True
                            break

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
