"""
Rust JSON adapters for the CrystalMath Python core.

These helpers keep JSON serialization at the Rust boundary while the core API
returns native Pydantic objects for Python consumers.
"""

from __future__ import annotations

import json
from typing import List

from crystalmath.api import _error_response, _ok_response
from crystalmath.models import JobDetails, JobStatus, JobSubmission


def get_jobs_json(controller, limit: int = 100) -> str:
    """Return job list JSON for Rust."""
    jobs: List[JobStatus] = controller.get_jobs(limit)
    return json.dumps([job.model_dump(mode="json") for job in jobs])


def get_job_details_json(controller, pk: int) -> str:
    """Return job details JSON for Rust."""
    details: JobDetails | None = controller.get_job_details(pk)
    if details is None:
        return _error_response("NOT_FOUND", f"Job with pk={pk} not found")
    return _ok_response(details.model_dump(mode="json"))


def get_job_log_json(controller, pk: int, tail_lines: int = 100) -> str:
    """Return job log JSON for Rust."""
    logs = controller.get_job_log(pk, tail_lines)
    return json.dumps(logs)


def submit_job_json(controller, json_payload: str) -> int:
    """Submit a new job from JSON payload (Rust adapter)."""
    submission = JobSubmission.model_validate_json(json_payload)
    return controller.submit_job(submission)
