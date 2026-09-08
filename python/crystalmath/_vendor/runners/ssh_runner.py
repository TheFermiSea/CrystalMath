"""SSH runner: direct remote execution without a job scheduler.

Complements SLURMRunner for the common case of a plain workstation or
standalone HPC node reachable over SSH that has no SLURM/PBS/LSF scheduler —
e.g. a lab machine where jobs are just launched directly. Reuses the same
ConnectionManager/RemoteBaseRunner plumbing (pooled asyncssh connections,
SFTP transfer) as SLURMRunner; the only real difference is how a job is
started and how its liveness is tracked (a backgrounded PID instead of a
scheduler job ID).
"""

from __future__ import annotations

import asyncio
import logging
import shlex
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

from .base import JobHandle, JobStatus, RemoteBaseRunner, RunnerConfig
from .exceptions import JobNotFoundError, SSHRunnerError

logger = logging.getLogger(__name__)


class SSHSubmissionError(SSHRunnerError):
    """Raised when job submission over SSH fails."""


class SSHStatusError(SSHRunnerError):
    """Raised when job status cannot be determined over SSH."""


@dataclass
class SSHJobConfig:
    """Configuration for a single SSHRunner job submission.

    Mirrors the parts of SLURMJobConfig that are meaningful without a
    scheduler: parallelism and environment setup. There is no queue/time
    limit/partition here because there is no scheduler to enforce them.
    """

    ntasks: int = 1  # MPI ranks (mpirun -np). 1 = no MPI wrapper.
    threads: int = 1  # OMP_NUM_THREADS per rank.
    mpi_command: str = "mpirun -np {ntasks}"
    # Shell snippet sourced before the executable runs, e.g. a vendor
    # environment script that sets PATH/LD_LIBRARY_PATH for the DFT code's
    # runtime libraries. Executed via `source`, so it must be shell syntax
    # valid in the remote's login shell (bash assumed).
    environment_setup: str = ""


class SSHRunner(RemoteBaseRunner):
    """Runs DFT jobs directly over SSH, no scheduler involved.

    A job is started with `nohup ... & echo $!` so it survives the SSH
    session closing, and tracked by PID rather than a scheduler job ID.
    Job handles have the form ``"ssh:{cluster_id}:{pid}:{remote_dir}"``,
    matching SLURMRunner's ``"slurm:{cluster_id}:{slurm_job_id}:{remote_dir}"``
    convention so callers that already parse one format can be adapted
    to the other trivially.
    """

    def __init__(
        self,
        connection_manager,
        cluster_id: int,
        dft_code=None,
        remote_scratch_base: str = "/tmp/dft_jobs",
        config: RunnerConfig | None = None,
    ):
        from ..core.codes import DFTCode

        super().__init__(
            connection_manager,
            cluster_id,
            dft_code=dft_code or DFTCode.CRYSTAL,
            remote_scratch_dir=Path(remote_scratch_base),
            config=config,
        )
        self.remote_scratch_base = remote_scratch_base

    async def submit_job(
        self, job_id: int, input_file: Path, work_dir: Path, threads: int | None = None, **kwargs
    ) -> JobHandle:
        """Upload the input and launch the job in the background over SSH.

        Args:
            job_id: Database ID of the job for tracking.
            input_file: Path to the local input file (e.g. a `.d12`).
            work_dir: Local working directory (auxiliary input files matching
                the code's config are picked up from here alongside the
                input file).
            threads: OMP_NUM_THREADS override (overrides config.threads).
            **kwargs:
                config: Optional SSHJobConfig instance.
                ntasks: MPI rank count override.

        Returns:
            JobHandle in the form "ssh:{cluster_id}:{pid}:{remote_dir}".

        Raises:
            SSHSubmissionError: If the input file is missing or launch fails.
        """
        await self._semaphore.acquire()
        try:
            if not input_file.exists():
                raise SSHSubmissionError(
                    f"Input file not found: {input_file}", host=str(self.cluster_id)
                )

            job_config: SSHJobConfig = kwargs.get("config") or SSHJobConfig()
            if threads:
                job_config.threads = threads
            if "ntasks" in kwargs:
                job_config.ntasks = kwargs["ntasks"]

            remote_work_dir = f"{self.remote_scratch_base}/{job_id}_{work_dir.name}"
            remote_input_name = self._get_remote_input_name(input_file)
            remote_output_name = f"{Path(remote_input_name).stem}{self.code_config.output_extension}"

            async with self.connection_manager.get_connection(self.cluster_id) as conn:
                await conn.run(f"mkdir -p {shlex.quote(remote_work_dir)}")

                async with await conn.start_sftp_client() as sftp:
                    await sftp.put(str(input_file), f"{remote_work_dir}/{remote_input_name}")
                    for suffix, remote_name in self.code_config.auxiliary_inputs.items():
                        local_aux = input_file.with_suffix(suffix)
                        if local_aux.exists():
                            await sftp.put(str(local_aux), f"{remote_work_dir}/{remote_name}")

                executable = self._resolve_executable(job_config.ntasks > 1)
                inner_cmd = f"{executable} < {shlex.quote(remote_input_name)} > {shlex.quote(remote_output_name)} 2>&1"
                if job_config.ntasks > 1:
                    mpi_prefix = job_config.mpi_command.format(ntasks=job_config.ntasks)
                    inner_cmd = f"{mpi_prefix} {inner_cmd}"
                if job_config.threads:
                    inner_cmd = f"OMP_NUM_THREADS={job_config.threads} {inner_cmd}"
                if job_config.environment_setup:
                    inner_cmd = f"{job_config.environment_setup}; {inner_cmd}"

                # `nohup ... ; echo $? > EXIT_CODE` backgrounded and detached
                # from the SSH channel so it survives the connection closing.
                # `echo $!` (outside the quoted script, in the outer shell)
                # captures the backgrounded PID, which conn.run() returns
                # before the job itself has necessarily finished.
                launch_script = f"cd {shlex.quote(remote_work_dir)} && {inner_cmd}; echo $? > EXIT_CODE"
                launch_cmd = (
                    f"nohup bash -c {shlex.quote(launch_script)} "
                    f"> /dev/null 2>&1 < /dev/null & echo $!"
                )
                result = await conn.run(launch_cmd, check=False)
                pid_str = result.stdout.strip() if result.stdout else ""
                if not pid_str.isdigit():
                    raise SSHSubmissionError(
                        f"Failed to launch job: no PID returned (stdout={result.stdout!r}, "
                        f"stderr={result.stderr!r})",
                        host=str(self.cluster_id),
                        command=launch_cmd,
                    )

            job_handle = JobHandle(f"ssh:{self.cluster_id}:{pid_str}:{remote_work_dir}")
            logger.info(f"Submitted SSH job {job_id} as PID {pid_str} in {remote_work_dir}")
            return job_handle
        finally:
            self._semaphore.release()

    async def get_status(self, job_handle: JobHandle) -> JobStatus:
        """Check whether the PID is alive; if not, consult EXIT_CODE.

        Racy by nature (the process could exit between the liveness check
        and the EXIT_CODE read), so a missing EXIT_CODE right after the PID
        disappears is treated as still-finishing rather than an error —
        callers polling in a loop will see the real terminal state on the
        next call.
        """
        cluster_id, pid, remote_dir = self._parse_job_handle(job_handle)

        try:
            async with self.connection_manager.get_connection(cluster_id) as conn:
                alive = await conn.run(f"kill -0 {pid}", check=False)
                if alive.exit_status == 0:
                    return JobStatus.RUNNING

                exit_code_result = await conn.run(
                    f"cat {shlex.quote(remote_dir)}/EXIT_CODE 2>/dev/null", check=False
                )
                exit_code = exit_code_result.stdout.strip() if exit_code_result.stdout else ""
                if not exit_code:
                    return JobStatus.RUNNING  # process just exited, EXIT_CODE not flushed yet
                return JobStatus.COMPLETED if exit_code == "0" else JobStatus.FAILED

        except Exception as e:
            logger.error(f"Failed to get status for {job_handle}: {e}")
            return JobStatus.UNKNOWN

    async def cancel_job(self, job_handle: JobHandle) -> bool:
        """Send SIGTERM, escalating to SIGKILL if still alive after a grace period."""
        cluster_id, pid, _ = self._parse_job_handle(job_handle)

        try:
            async with self.connection_manager.get_connection(cluster_id) as conn:
                term = await conn.run(f"kill -TERM {pid}", check=False)
                if term.exit_status != 0:
                    return False  # already gone, or never existed

                await asyncio.sleep(2)
                still_alive = await conn.run(f"kill -0 {pid}", check=False)
                if still_alive.exit_status == 0:
                    await conn.run(f"kill -KILL {pid}", check=False)
                logger.info(f"Cancelled SSH job PID {pid}")
                return True

        except Exception as e:
            logger.error(f"Failed to cancel job PID {pid}: {e}")
            return False

    async def get_output(self, job_handle: JobHandle) -> AsyncIterator[str]:
        """Poll-tail the remote output file until the job reaches a terminal state."""
        cluster_id, _, remote_dir = self._parse_job_handle(job_handle)
        output_glob = f"*{self.code_config.output_extension}"

        async with self.connection_manager.get_connection(cluster_id) as conn:
            output_file = f"{remote_dir}/{await self._find_output_file(conn, remote_dir, output_glob)}"

            last_size = 0
            while True:
                status = await self.get_status(job_handle)

                result = await conn.run(
                    f"tail -c +{last_size + 1} {shlex.quote(output_file)} 2>/dev/null", check=False
                )
                if result.stdout:
                    for line in result.stdout.splitlines():
                        yield line
                    last_size += len(result.stdout.encode())

                if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                    break
                await asyncio.sleep(2.0)

    async def retrieve_results(
        self, job_handle: JobHandle, dest: Path, cleanup: bool | None = None
    ) -> None:
        """Download the output file and any auxiliary outputs the code produces."""
        cluster_id, _, remote_dir = self._parse_job_handle(job_handle)
        dest.mkdir(parents=True, exist_ok=True)

        async with self.connection_manager.get_connection(cluster_id) as conn:
            patterns = [f"*{self.code_config.output_extension}"] + list(
                self.code_config.auxiliary_outputs.keys()
            )
            await self._download_files_sftp(conn, remote_dir, dest, patterns)

            should_cleanup = cleanup
            if should_cleanup is None:
                status = await self.get_status(job_handle)
                should_cleanup = (
                    self.config.cleanup_on_success
                    if status == JobStatus.COMPLETED
                    else self.config.cleanup_on_failure
                )
            if should_cleanup:
                await conn.run(f"rm -rf {shlex.quote(remote_dir)}", check=False)
                logger.info(f"Cleaned up remote directory: {remote_dir}")

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def _resolve_executable(self, parallel: bool) -> str:
        """Absolute path if RunnerConfig.executable_path is set, else bare
        name from the code config (relying on remote PATH)."""
        if self.config.executable_path is not None:
            return str(self.config.executable_path)
        return self.code_config.get_executable(parallel=parallel)

    def _get_remote_input_name(self, input_file: Path) -> str:
        """Remote input filename.

        CRYSTAL's parallel (MPI) binary does not reliably read the input
        deck via redirected stdin across all ranks — most MPI
        implementations only connect stdin to rank 0 by default, and
        CRYSTAL's non-zero ranks were observed opening a literal file named
        `INPUT` in the working directory instead (found empty and aborting,
        when the real input had been staged under its original filename and
        only piped via `<`). CRYSTAL's own convention is exactly this: the
        input deck is always named `INPUT` in the working directory,
        regardless of the DFTCodeConfig's declared STDIN invocation style,
        which stdin-redirects `INPUT` as a belt-and-suspenders match for
        codes/versions that *do* honor it. Serial-only codes/binaries are
        unaffected either way.
        """
        return "INPUT"

    async def _find_output_file(self, conn, remote_dir: str, pattern: str) -> str:
        """Best-effort discovery of the output filename actually written
        (the caller controls the name at submit time, but get_output() may
        be called by something that only has the job_handle)."""
        result = await conn.run(
            f"cd {shlex.quote(remote_dir)} && ls -t {pattern} 2>/dev/null | head -1", check=False
        )
        name = result.stdout.strip() if result.stdout else ""
        return name or f"output{self.code_config.output_extension}"

    def _parse_job_handle(self, job_handle: JobHandle) -> tuple[int, str, str]:
        """Parse "ssh:{cluster_id}:{pid}:{remote_dir}" -> (cluster_id, pid, remote_dir)."""
        parts = str(job_handle).split(":", 3)
        if len(parts) != 4 or parts[0] != "ssh":
            raise JobNotFoundError(f"Invalid SSH job handle: {job_handle}", job_handle=str(job_handle))
        _, cluster_id_str, pid, remote_dir = parts
        return int(cluster_id_str), pid, remote_dir
