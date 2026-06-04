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


def _try_mkdir(path) -> bool:
    """Create ``path`` (and parents) if possible; return success."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


def _platform_data_dir():
    """Best-effort equivalent of Rust ``dirs::data_dir()`` for this platform."""
    import os
    import sys
    from pathlib import Path

    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support"
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        return Path(appdata) if appdata else None
    xdg = os.environ.get("XDG_DATA_HOME")
    return Path(xdg) if xdg else home / ".local" / "share"


def find_database_path() -> str | None:
    """Resolve the shared crystal_tui database path.

    Mirrors the Rust resolver in ``src/bridge.rs::find_database_path`` so the
    Python CLI/server open the SAME database the Rust TUI uses. Resolution order:

    1. ``CRYSTAL_TUI_DB`` env var (used as-is; the parent dir is created so a new
       DB can be initialized there).
    2. ``.crystal_tui.db`` at the project root (nearest ancestor with
       ``Cargo.toml``), then ``<project>/tui/.crystal_tui.db``.
    3. ``.crystal_tui.db`` in the CWD, then ``./tui/.crystal_tui.db``.
    4. ``~/.local/share/crystal-tui/jobs.db``.
    5. The platform data dir: ``<data>/crystal-tui/jobs.db`` (created if absent).
    6. Legacy ``./tui/jobs.db``.

    Returns ``None`` (demo mode) only if every location above is unavailable.
    """
    import os
    from pathlib import Path

    # 1. Explicit override.
    env = os.environ.get("CRYSTAL_TUI_DB")
    if env:
        p = Path(env)
        if p.exists() or p.parent.exists() or _try_mkdir(p.parent):
            return str(p)

    db_name = ".crystal_tui.db"
    here = Path.cwd()

    # 2. Project root (nearest ancestor containing Cargo.toml).
    for d in [here, *here.parents]:
        if (d / "Cargo.toml").exists():
            project_db = d / db_name
            if project_db.exists():
                return str(project_db)
            tui_db = d / "tui" / db_name
            if tui_db.exists():
                return str(tui_db)
            break

    # 3. Current working directory.
    cwd_db = here / db_name
    if cwd_db.exists():
        return str(cwd_db)
    cwd_tui_db = here / "tui" / db_name
    if cwd_tui_db.exists():
        return str(cwd_tui_db)

    # 4. Explicit XDG-style location (checked even on macOS, mirroring Rust).
    xdg_db = Path.home() / ".local" / "share" / "crystal-tui" / "jobs.db"
    if xdg_db.exists():
        return str(xdg_db)

    # 5. Platform data dir (created if missing, like the Rust resolver).
    data_dir = _platform_data_dir()
    if data_dir is not None:
        platform_db = data_dir / "crystal-tui" / "jobs.db"
        if platform_db.exists() or _try_mkdir(platform_db.parent):
            return str(platform_db)

    # 6. Legacy development location.
    legacy_db = here / "tui" / "jobs.db"
    if legacy_db.exists():
        return str(legacy_db)

    logger.warning("No database found - running in demo mode. Set CRYSTAL_TUI_DB to override.")
    return None


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
    def get_jobs(self, limit: int = 100) -> list[JobStatus]:
        """
        Get list of jobs.

        Args:
            limit: Maximum number of jobs to return

        Returns:
            List of JobStatus objects, ordered by creation time (newest first)
        """
        ...

    @abstractmethod
    def get_job_details(self, pk: int) -> JobDetails | None:
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
    def get_job_log(self, pk: int, tail_lines: int = 100) -> dict[str, list[str]]:
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
    db_path: str | None = None,
    profile_name: str = "default",
    backend_preference: str = "auto",
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
        backend_preference: Backend selection strategy.
            Supported values: "auto", "sqlite", "aiida", "demo".

    Returns:
        Configured Backend instance
    """
    preference = backend_preference.lower().strip()

    if preference not in {"auto", "sqlite", "aiida", "demo"}:
        logger.warning("Unknown backend preference '%s', falling back to auto", backend_preference)
        preference = "auto"

    try_aiida = preference in {"auto", "aiida"} and use_aiida
    try_sqlite = preference in {"auto", "sqlite"}

    if preference == "demo":
        from crystalmath.backends.demo import DemoBackend

        logger.info("Using demo backend by explicit preference")
        return DemoBackend()

    if preference == "sqlite" and not db_path:
        logger.warning(
            "SQLite backend requested via backend_preference='%s' but no db_path was "
            "provided; falling back to demo mode",
            backend_preference,
        )

    if try_aiida:
        from crystalmath.backends.aiida import AiiDABackend

        backend = AiiDABackend(profile_name=profile_name)
        if backend.is_available:
            logger.info(f"Using AiiDA backend with profile '{profile_name}'")
            return backend
        logger.info("AiiDA not available, falling back")

    if try_sqlite and db_path:
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
    "find_database_path",
]
