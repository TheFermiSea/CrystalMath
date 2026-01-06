"""
Backend abstraction for CrystalController.

This module defines the Backend protocol that all storage/execution backends
must implement. The primary backends are:

- SQLiteBackend: Local SQLite database (default)
- AiiDABackend: AiiDA ORM with PostgreSQL (optional)
- DemoBackend: In-memory mock for testing/demos

Usage:
    from crystalmath.backends import SQLiteBackend, AiiDABackend, create_backend

    # Create backend based on config
    backend = create_backend(use_aiida=False, db_path="jobs.db")

    # Use backend
    jobs = backend.get_jobs(limit=100)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from pathlib import Path

    from crystalmath.models import JobDetails, JobStatus, JobSubmission

logger = logging.getLogger(__name__)


class Backend(ABC):
    """
    Abstract base class for job storage/execution backends.

    All backends must implement these methods to provide a consistent
    interface for the CrystalController.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend identifier (e.g., 'sqlite', 'aiida', 'demo')."""
        ...

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Whether this backend is ready for use."""
        ...

    @abstractmethod
    def get_jobs(self, limit: int = 100) -> List[JobStatus]:
        """
        Get list of jobs.

        Args:
            limit: Maximum number of jobs to return

        Returns:
            List of JobStatus objects, ordered by creation time (newest first)
        """
        ...

    @abstractmethod
    def get_job_details(self, pk: int) -> Optional[JobDetails]:
        """
        Get detailed information for a specific job.

        Args:
            pk: Job primary key

        Returns:
            JobDetails object, or None if job not found
        """
        ...

    @abstractmethod
    def submit_job(self, submission: JobSubmission) -> int:
        """
        Submit a new job.

        Args:
            submission: Job submission data

        Returns:
            Primary key of the created job

        Raises:
            RuntimeError: If submission fails
        """
        ...

    @abstractmethod
    def cancel_job(self, pk: int) -> bool:
        """
        Cancel a running job.

        Args:
            pk: Job primary key

        Returns:
            True if cancellation was successful
        """
        ...

    @abstractmethod
    def get_job_log(self, pk: int, tail_lines: int = 100) -> Dict[str, List[str]]:
        """
        Get job stdout/stderr logs.

        Args:
            pk: Job primary key
            tail_lines: Number of lines from end of log

        Returns:
            Dict with 'stdout' and 'stderr' keys, each containing list of lines
        """
        ...


def create_backend(
    use_aiida: bool = False,
    db_path: Optional[str] = None,
    profile_name: str = "default",
) -> Backend:
    """
    Factory function to create the appropriate backend.

    Priority:
    1. AiiDA if use_aiida=True and AiiDA is available
    2. SQLite if db_path is provided
    3. Demo backend as fallback

    Args:
        use_aiida: Whether to try AiiDA backend
        db_path: Path to SQLite database
        profile_name: AiiDA profile name (if use_aiida=True)

    Returns:
        Configured Backend instance
    """
    if use_aiida:
        from crystalmath.backends.aiida import AiiDABackend

        backend = AiiDABackend(profile_name=profile_name)
        if backend.is_available:
            logger.info(f"Using AiiDA backend with profile '{profile_name}'")
            return backend
        logger.info("AiiDA not available, falling back")

    if db_path:
        from crystalmath.backends.sqlite import SQLiteBackend

        backend = SQLiteBackend(db_path=db_path)
        if backend.is_available:
            logger.info(f"Using SQLite backend: {db_path}")
            return backend
        logger.warning(f"Failed to load SQLite database: {db_path}")

    # Fallback to demo
    from crystalmath.backends.demo import DemoBackend

    logger.warning("No backend available - using demo mode")
    return DemoBackend()


# Re-export backends for convenience
from crystalmath.backends.aiida import AiiDABackend
from crystalmath.backends.demo import DemoBackend
from crystalmath.backends.sqlite import SQLiteBackend

__all__ = [
    "Backend",
    "AiiDABackend",
    "DemoBackend",
    "SQLiteBackend",
    "create_backend",
]
