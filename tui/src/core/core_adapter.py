"""
Adapter for accessing the shared crystalmath core from the Textual TUI.

This module keeps the TUI's data flow stable while gradually migrating away
from direct SQLite access. It converts core Pydantic models into legacy
Job dataclasses for UI consumption.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List

from crystalmath.api import create_controller
from crystalmath.models import JobDetails, JobState, JobStatus

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


def _format_created_at(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="seconds")


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

    def list_jobs(self, limit: int = 200) -> List[Job]:
        jobs = self._controller.get_jobs(limit)
        return [job_status_to_job(job) for job in jobs]

    def get_job_details(self, pk: int) -> JobDetails | None:
        return self._controller.get_job_details(pk)
