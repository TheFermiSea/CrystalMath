"""
Job metadata storage for quacc workflows.

This module provides tracking of job metadata and status for
quacc-based workflow execution.
"""

import json
import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Status of a quacc job."""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class JobMetadata(BaseModel):
    """
    Metadata for a quacc job.

    Tracks job identity, status, and results for monitoring purposes.
    """

    id: str = Field(..., description="Unique job ID (UUID)")
    recipe: str = Field(
        ..., description="Full recipe path (e.g., quacc.recipes.vasp.core.relax_job)"
    )
    status: JobStatus = Field(..., description="Current job status")
    created_at: datetime = Field(..., description="Job creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    cluster: str | None = Field(default=None, description="Cluster name if remote")
    work_dir: Path | None = Field(default=None, description="Job working directory")
    error_message: str | None = Field(
        default=None, description="Error message if failed"
    )
    results_summary: dict[str, Any] | None = Field(
        default=None, description="Summary of job results"
    )

    model_config = {"extra": "forbid"}


class JobStore:
    """
    Persistent storage for job metadata.

    Stores job metadata in a JSON file, defaulting to
    ~/.crystalmath/jobs.json.
    """

    def __init__(self, store_path: Path | None = None) -> None:
        """
        Initialize the job store.

        Args:
            store_path: Path to the JSON store file. Defaults to
                ~/.crystalmath/jobs.json
        """
        if store_path is None:
            store_path = Path.home() / ".crystalmath" / "jobs.json"
        self.store_path = store_path

        # Create parent directory if needed
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_jobs(self) -> list[dict[str, Any]]:
        """Load jobs from the store file."""
        if not self.store_path.exists():
            return []

        try:
            with open(self.store_path) as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and "jobs" in data:
                    return data["jobs"]
                else:
                    logger.warning(f"Unexpected job store format in {self.store_path}")
                    return []
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse job store: {e}")
            return []
        except OSError as e:
            logger.error(f"Failed to read job store: {e}")
            return []

    def _save_jobs(self, jobs: list[dict[str, Any]]) -> None:
        """Save jobs to the store file."""
        try:
            with open(self.store_path, "w") as f:
                json.dump(jobs, f, indent=2, default=str)
        except OSError as e:
            logger.error(f"Failed to write job store: {e}")
            raise

    def list_jobs(
        self, status: JobStatus | None = None, limit: int = 100
    ) -> list[JobMetadata]:
        """
        List jobs, optionally filtered by status.

        Args:
            status: Filter to only jobs with this status, or None for all.
            limit: Maximum number of jobs to return.

        Returns:
            List of JobMetadata objects, sorted by created_at descending.
        """
        raw_jobs = self._load_jobs()

        # Filter by status if specified
        if status is not None:
            raw_jobs = [j for j in raw_jobs if j.get("status") == status.value]

        # Sort by created_at descending
        raw_jobs.sort(
            key=lambda j: j.get("created_at", ""),
            reverse=True,
        )

        # Apply limit
        raw_jobs = raw_jobs[:limit]

        # Parse to models
        result = []
        for job_dict in raw_jobs:
            try:
                # Convert work_dir string to Path if present
                if job_dict.get("work_dir"):
                    job_dict["work_dir"] = Path(job_dict["work_dir"])
                result.append(JobMetadata(**job_dict))
            except Exception as e:
                logger.warning(f"Skipping invalid job entry: {e}")
                continue

        return result

    def get_job(self, job_id: str) -> JobMetadata | None:
        """
        Get a job by ID.

        Args:
            job_id: The job ID to look up.

        Returns:
            JobMetadata if found, None otherwise.
        """
        raw_jobs = self._load_jobs()
        for job_dict in raw_jobs:
            if job_dict.get("id") == job_id:
                try:
                    if job_dict.get("work_dir"):
                        job_dict["work_dir"] = Path(job_dict["work_dir"])
                    return JobMetadata(**job_dict)
                except Exception as e:
                    logger.error(f"Failed to parse job {job_id}: {e}")
                    return None
        return None

    def save_job(self, job: JobMetadata) -> None:
        """
        Save or update a job.

        If a job with the same ID exists, it will be updated.
        Otherwise, a new job entry will be added.

        Args:
            job: The job metadata to save.
        """
        raw_jobs = self._load_jobs()

        # Serialize the job
        job_dict = job.model_dump(mode="json")

        # Find and update existing or append new
        found = False
        for i, existing in enumerate(raw_jobs):
            if existing.get("id") == job.id:
                raw_jobs[i] = job_dict
                found = True
                break

        if not found:
            raw_jobs.append(job_dict)

        self._save_jobs(raw_jobs)
