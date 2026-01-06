"""
Demo backend for testing and demonstration.

Provides in-memory mock data without any external dependencies.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from crystalmath.backends import Backend
from crystalmath.models import (
    DftCode,
    JobDetails,
    JobState,
    JobStatus,
    JobSubmission,
    RunnerType,
)


class DemoBackend(Backend):
    """
    In-memory mock backend for demos and testing.

    Stores jobs in memory without persistence.
    """

    def __init__(self) -> None:
        self._jobs: List[JobStatus] = []
        self._initialized = False

    def _ensure_demo_data(self) -> None:
        """Lazily initialize demo data."""
        if self._initialized:
            return

        now = datetime.now()
        self._jobs = [
            JobStatus(
                pk=1,
                uuid="demo-001",
                name="MgO-SCF",
                state=JobState.COMPLETED,
                dft_code=DftCode.CRYSTAL,
                runner_type=RunnerType.LOCAL,
                progress_percent=100.0,
                wall_time_seconds=45.2,
                created_at=now,
            ),
            JobStatus(
                pk=2,
                uuid="demo-002",
                name="MoS2-OPTGEOM",
                state=JobState.RUNNING,
                dft_code=DftCode.CRYSTAL,
                runner_type=RunnerType.LOCAL,
                progress_percent=65.0,
                wall_time_seconds=120.0,
                created_at=now,
            ),
        ]
        self._initialized = True

    @property
    def name(self) -> str:
        return "demo"

    @property
    def is_available(self) -> bool:
        return True  # Always available

    def get_jobs(self, limit: int = 100) -> List[JobStatus]:
        """Return demo jobs."""
        self._ensure_demo_data()
        return self._jobs[:limit]

    def get_job_details(self, pk: int) -> Optional[JobDetails]:
        """Return demo job details."""
        self._ensure_demo_data()

        for job in self._jobs:
            if job.pk == pk:
                completed = job.state == JobState.COMPLETED
                return JobDetails(
                    pk=job.pk,
                    uuid=job.uuid,
                    name=job.name,
                    state=job.state,
                    dft_code=job.dft_code,
                    final_energy=-275.123456 if completed else None,
                    convergence_met=completed,
                    scf_cycles=15 if completed else None,
                    stdout_tail=["TOTAL ENERGY -275.123456 AU", "SCF CONVERGED"]
                    if completed
                    else [],
                )
        return None

    def submit_job(self, submission: JobSubmission) -> int:
        """Submit demo job."""
        self._ensure_demo_data()

        pk = len(self._jobs) + 1
        self._jobs.append(
            JobStatus(
                pk=pk,
                uuid=f"demo-{pk:03d}",
                name=submission.name,
                state=JobState.QUEUED,
                dft_code=submission.dft_code,
                runner_type=submission.runner_type,
                progress_percent=0.0,
                wall_time_seconds=None,
                created_at=datetime.now(),
            )
        )
        return pk

    def cancel_job(self, pk: int) -> bool:
        """Cancel demo job."""
        self._ensure_demo_data()

        for job in self._jobs:
            if job.pk == pk:
                # Note: JobStatus is immutable (frozen=True), so we need to replace
                # For demo purposes, we just mark as cancelled
                idx = self._jobs.index(job)
                self._jobs[idx] = JobStatus(
                    pk=job.pk,
                    uuid=job.uuid,
                    name=job.name,
                    state=JobState.CANCELLED,
                    dft_code=job.dft_code,
                    runner_type=job.runner_type,
                    progress_percent=job.progress_percent,
                    wall_time_seconds=job.wall_time_seconds,
                    created_at=job.created_at,
                )
                return True
        return False

    def get_job_log(self, pk: int, tail_lines: int = 100) -> Dict[str, List[str]]:
        """Return empty logs for demo."""
        return {"stdout": [], "stderr": []}
