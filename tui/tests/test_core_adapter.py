from datetime import datetime

from crystalmath.models import DftCode, JobState, JobStatus, RunnerType

from src.core.core_adapter import job_status_to_job


def test_job_status_to_job_maps_fields() -> None:
    created_at = datetime(2025, 1, 2, 3, 4, 5)
    status = JobStatus(
        pk=7,
        uuid="demo-007",
        name="Test Job",
        state=JobState.RUNNING,
        dft_code=DftCode.CRYSTAL,
        runner_type=RunnerType.LOCAL,
        created_at=created_at,
    )

    job = job_status_to_job(status)

    assert job.id == 7
    assert job.name == "Test Job"
    assert job.status == "RUNNING"
    assert job.runner_type == "local"
    assert job.dft_code == "crystal"
    assert job.created_at == "2025-01-02T03:04:05"
