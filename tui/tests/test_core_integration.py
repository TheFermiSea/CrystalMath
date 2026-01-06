from pathlib import Path

import pytest

from crystalmath.models import DftCode, JobSubmission, RunnerType
from src.core.core_adapter import CrystalCoreClient


def test_core_client_submit_and_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the Textual TUI core adapter writes via the shared core and can read back."""
    db_path = tmp_path / ".crystal_tui.db"
    monkeypatch.chdir(tmp_path)

    client = CrystalCoreClient(db_path)

    submission = JobSubmission(
        name="demo_submission",
        dft_code=DftCode.CRYSTAL,
        runner_type=RunnerType.LOCAL,
        parameters={},
        input_content="CRYSTAL\nEND\nEND",
        parallel_mode="serial",
    )

    job_id = client.submit_job(submission)
    assert job_id > 0

    jobs = client.list_jobs()
    assert any(job.id == job_id for job in jobs)

    calculations_dir = tmp_path / "calculations"
    assert calculations_dir.exists()
