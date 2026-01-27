"""
Adapter for accessing the shared crystalmath core from the Textual TUI.

This module keeps the TUI's data flow stable while gradually migrating away
from direct SQLite access. It converts core Pydantic models into legacy
Job dataclasses for UI consumption.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from crystalmath.api import create_controller
from crystalmath.models import (
    DftCode,
    JobDetails,
    JobState,
    JobStatus,
    JobSubmission,
    RunnerType,
    map_to_job_state,
)

from .database import Job


_STATE_TO_STATUS = {
    JobState.CREATED: "PENDING",
    JobState.SUBMITTED: "QUEUED",
    JobState.QUEUED: "QUEUED",
    JobState.RUNNING: "RUNNING",
    JobState.COMPLETED: "COMPLETED",
    JobState.FAILED: "FAILED",
    JobState.CANCELLED: "CANCELLED",
}


def _format_created_at(value: datetime | None) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat(timespec="seconds")


def _parse_created_at(value: Optional[str]) -> Optional[datetime]:
    """Convert a stored timestamp string to datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def job_record_to_status(job: Job) -> JobStatus:
    """Convert a legacy Job dataclass into the core JobStatus model."""
    state = map_to_job_state(job.status)
    created_at = _parse_created_at(job.created_at)
    dft_code = DftCode(job.dft_code) if job.dft_code else DftCode.CRYSTAL
    runner_type = RunnerType(job.runner_type) if job.runner_type else RunnerType.LOCAL

    progress = 100.0 if state == JobState.COMPLETED else 0.0

    return JobStatus(
        pk=job.id or 0,
        uuid=str(job.id or 0),
        name=job.name,
        state=state,
        dft_code=dft_code,
        runner_type=runner_type,
        progress_percent=progress,
        created_at=created_at,
    )


def job_status_to_job(job_status: JobStatus) -> Job:
    """Convert a core JobStatus model into a legacy Job dataclass."""
    status = _STATE_TO_STATUS.get(job_status.state, "PENDING")
    created_at = _format_created_at(job_status.created_at)

    return Job(
        id=job_status.pk,
        name=job_status.name,
        work_dir="",
        status=status,
        created_at=created_at,
        final_energy=None,
        runner_type=job_status.runner_type.value,
        dft_code=job_status.dft_code.value,
    )


class CrystalCoreClient:
    """Thin wrapper around crystalmath.api for the Textual UI."""

    def __init__(self, db_path: Path) -> None:
        self._controller = create_controller(
            profile_name="default",
            use_aiida=False,
            db_path=str(db_path),
        )

    def list_jobs(self, limit: int = 200) -> List[JobStatus]:
        return self._controller.get_jobs(limit)

    def get_job_details(self, pk: int) -> Optional[JobDetails]:
        return self._controller.get_job_details(pk)

    def get_job_log(self, pk: int, tail_lines: int = 100) -> Dict[str, List[str]]:
        return self._controller.get_job_log(pk, tail_lines)

    def submit_job(self, submission: JobSubmission) -> int:
        return self._controller.submit_job(submission)
