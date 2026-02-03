"""
SQLite backend for job storage.

Uses the existing TUI database module for compatibility.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from crystalmath.backends import Backend
from crystalmath.models import (
    DftCode,
    JobDetails,
    JobState,
    JobStatus,
    JobSubmission,
    RunnerType,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Status mapping from database strings to JobState
_STATUS_MAP = {
    "PENDING": JobState.CREATED,
    "QUEUED": JobState.QUEUED,
    "RUNNING": JobState.RUNNING,
    "COMPLETED": JobState.COMPLETED,
    "FAILED": JobState.FAILED,
    "CANCELLED": JobState.CANCELLED,
}


class SQLiteBackend(Backend):
    """
    SQLite-based job storage backend.

    Uses the TUI's Database class for persistence.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: Any = None
        self._available = False
        self._init_database()

    def _init_database(self) -> None:
        """Initialize connection to TUI database."""
        try:
            # Import TUI database module
            # Need to add tui/src to path for core.database import
            repo_root = Path(__file__).parent.parent.parent.parent  # crystalmath/
            tui_path = repo_root / "tui" / "src"

            if str(tui_path) not in sys.path:
                sys.path.insert(0, str(tui_path))

            from core.database import Database

            self._db = Database(Path(self._db_path))
            self._available = True
            logger.info(f"Loaded SQLite database: {self._db_path}")

        except Exception as e:
            logger.warning(f"Failed to load SQLite database: {e}")
            self._available = False

    @property
    def name(self) -> str:
        return "sqlite"

    @property
    def is_available(self) -> bool:
        return self._available

    def get_jobs(self, limit: int = 100) -> List[JobStatus]:
        """Query SQLite for job list."""
        if not self._db:
            return []

        jobs = self._db.get_all_jobs()[:limit]
        results: List[JobStatus] = []

        for job in jobs:
            created_at = None
            if job.created_at:
                try:
                    created_at = datetime.fromisoformat(job.created_at)
                except ValueError:
                    created_at = None

            results.append(
                JobStatus(
                    pk=job.id,
                    uuid=str(job.id),  # SQLite doesn't have UUID
                    name=job.name,
                    state=_STATUS_MAP.get(job.status, JobState.CREATED),
                    dft_code=DftCode(job.dft_code) if job.dft_code else DftCode.CRYSTAL,
                    runner_type=RunnerType(job.runner_type)
                    if job.runner_type
                    else RunnerType.LOCAL,
                    workflow_id=job.workflow_id,
                    progress_percent=100.0 if job.status == "COMPLETED" else 0.0,
                    created_at=created_at,
                )
            )

        return results

    def get_job_details(self, pk: int) -> Optional[JobDetails]:
        """Get job details from SQLite."""
        if not self._db:
            return None

        try:
            job = self._db.get_job(pk)
            if not job:
                return None

            # Get additional results if available
            result = self._db.get_job_result(pk)

            return JobDetails(
                pk=job.id,
                uuid=str(job.id),
                name=job.name,
                state=_STATUS_MAP.get(job.status, JobState.CREATED),
                dft_code=DftCode(job.dft_code) if job.dft_code else DftCode.CRYSTAL,
                final_energy=job.final_energy,
                convergence_met=result.convergence_status == "converged" if result else False,
                scf_cycles=result.scf_cycles if result else None,
                cpu_time_seconds=result.cpu_time_seconds if result else None,
                wall_time_seconds=result.wall_time_seconds if result else None,
                key_results=result.key_results if result else None,
                work_dir=job.work_dir,
                input_file=job.input_file,
            )
        except Exception as e:
            logger.error(f"Error getting job details for pk={pk}: {e}")
            return None

    def submit_job(self, submission: JobSubmission) -> int:
        """Submit job via SQLite."""
        if not self._db:
            raise RuntimeError("SQLite database not available")

        # 1. Determine next ID
        with self._db.connection() as conn:
            cursor = conn.execute("SELECT MAX(id) FROM jobs")
            row = cursor.fetchone()
            next_id = (row[0] or 0) + 1 if row else 1

        # 2. Setup directory
        base_dir = Path("calculations")
        work_dir_name = f"{next_id:04d}_{submission.name}"
        work_dir = base_dir / work_dir_name

        try:
            work_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise RuntimeError(f"Failed to create work directory {work_dir}: {e}")

        # 3. Write input file
        final_input_content = self._write_input_files(submission, work_dir)

        # 4. Copy auxiliary files
        self._copy_auxiliary_files(submission, work_dir)

        # 5. Write metadata
        self._write_metadata(submission, work_dir)

        # 6. Create DB entry
        job_id = self._db.create_job(
            name=submission.name,
            work_dir=str(work_dir.absolute()),
            input_content=final_input_content,
            workflow_id=submission.workflow_id,
            cluster_id=submission.cluster_id,
            runner_type=submission.runner_type.value,
            dft_code=submission.dft_code.value,
            parallelism_config={"mpi_ranks": submission.mpi_ranks}
            if submission.mpi_ranks
            else None,
        )
        return job_id

    def _write_input_files(self, submission: JobSubmission, work_dir: Path) -> str:
        """Write input files based on DFT code."""
        if submission.dft_code == DftCode.VASP:
            # Special handling for VASP multi-file input
            params = submission.parameters
            (work_dir / "POSCAR").write_text(str(params.get("poscar", "")))
            (work_dir / "INCAR").write_text(str(params.get("incar", "")))
            (work_dir / "KPOINTS").write_text(str(params.get("kpoints", "")))
            (work_dir / "POTCAR.spec").write_text(str(params.get("potcar_config", "")))
            return "VASP Calculation\nSee POSCAR, INCAR, KPOINTS, POTCAR in work directory."

        elif submission.dft_code == DftCode.QUANTUM_ESPRESSO:
            input_filename = "input.in"
            input_path = work_dir / input_filename
            content = submission.input_content or json.dumps(submission.parameters, indent=2)
            input_path.write_text(content)
            return content

        else:
            # CRYSTAL or others
            input_filename = "input.d12"
            input_path = work_dir / input_filename
            content = submission.input_content or json.dumps(submission.parameters, indent=2)
            input_path.write_text(content)
            return content

    def _copy_auxiliary_files(self, submission: JobSubmission, work_dir: Path) -> None:
        """Copy auxiliary files to work directory."""
        if not submission.auxiliary_files:
            return

        import shutil

        for type_, src_path_str in submission.auxiliary_files.items():
            src_path = Path(src_path_str)
            if src_path.exists():
                # Destination naming convention
                dst_name = src_path.name
                if type_ == "gui":
                    dst_name = f"{submission.name}.gui"
                elif type_ == "f9":
                    dst_name = f"{submission.name}.f9"
                elif type_ == "hessopt":
                    dst_name = f"{submission.name}.hessopt"

                dst_path = work_dir / dst_name
                try:
                    shutil.copy2(src_path, dst_path)
                except Exception as e:
                    logger.warning(f"Failed to copy aux file {src_path}: {e}")

    def _write_metadata(self, submission: JobSubmission, work_dir: Path) -> None:
        """Write job metadata file."""
        metadata: Dict[str, Any] = {
            "dft_code": submission.dft_code.value,
            "runner_type": submission.runner_type.value,
            "mpi_ranks": submission.mpi_ranks or 1,
            "parallel_mode": submission.parallel_mode or "serial",
            "auxiliary_files": list(submission.auxiliary_files.keys())
            if submission.auxiliary_files
            else [],
        }

        if submission.scheduler_options:
            metadata["scheduler"] = submission.scheduler_options.model_dump()

        try:
            (work_dir / "job_metadata.json").write_text(json.dumps(metadata, indent=2))
        except Exception as e:
            logger.warning(f"Failed to write metadata: {e}")

    def cancel_job(self, pk: int) -> bool:
        """Cancel SQLite job."""
        if not self._db:
            return False

        try:
            self._db.update_status(pk, "CANCELLED")
            return True
        except Exception:
            return False

    def get_job_log(self, pk: int, tail_lines: int = 100) -> Dict[str, List[str]]:
        """Get job log from work directory."""
        if not self._db:
            return {"stdout": [], "stderr": []}

        try:
            job = self._db.get_job(pk)
            if not job or not job.work_dir:
                return {"stdout": [], "stderr": []}

            work_dir = Path(job.work_dir)
            stdout_lines: List[str] = []
            stderr_lines: List[str] = []

            # Try common output file names
            for stdout_name in ["stdout.log", "output.out", f"{job.name}.out"]:
                stdout_path = work_dir / stdout_name
                if stdout_path.exists():
                    lines = stdout_path.read_text().splitlines()
                    stdout_lines = lines[-tail_lines:]
                    break

            for stderr_name in ["stderr.log", "error.err"]:
                stderr_path = work_dir / stderr_name
                if stderr_path.exists():
                    lines = stderr_path.read_text().splitlines()
                    stderr_lines = lines[-tail_lines:]
                    break

            return {"stdout": stdout_lines, "stderr": stderr_lines}

        except Exception as e:
            logger.error(f"Error getting job log for pk={pk}: {e}")
            return {"stdout": [], "stderr": []}
