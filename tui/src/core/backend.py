"""
Backend configuration and factory for CRYSTAL-TOOLS TUI.

This module provides backend switching between:
    - Legacy: SQLite + custom orchestrator (Phase 2)
    - AiiDA: Full AiiDA integration (Phase 3)

The backend can be configured via:
    - Environment variable: CRYSTAL_TUI_BACKEND=aiida|legacy
    - Configuration file: ~/.crystal_tui/config.yaml
    - Programmatic setting

Example:
    >>> from src.core.backend import get_database, BackendMode
    >>>
    >>> # Auto-detect or use configured backend
    >>> db = get_database()
    >>>
    >>> # Force specific backend
    >>> db = get_database(mode=BackendMode.AIIDA)
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, Union

if TYPE_CHECKING:
    from src.aiida.query_adapter import AiiDAQueryAdapter
    from src.core.database import Database


class BackendMode(str, Enum):
    """Backend mode selection."""

    LEGACY = "legacy"
    AIIDA = "aiida"
    AUTO = "auto"  # Auto-detect based on availability


class DatabaseProtocol(Protocol):
    """Protocol defining the database interface."""

    def list_jobs(
        self, status: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        ...

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        ...

    def create_job(
        self,
        name: str,
        input_content: str,
        runner_type: str = "local",
        **kwargs: Any,
    ) -> int:
        ...

    def update_job(
        self,
        job_id: int,
        status: str | None = None,
        **kwargs: Any,
    ) -> bool:
        ...


def get_backend_mode() -> BackendMode:
    """
    Determine the backend mode to use.

    Priority:
        1. Environment variable CRYSTAL_TUI_BACKEND
        2. Config file ~/.crystal_tui/config.yaml
        3. Auto-detection

    Returns:
        BackendMode enum value.
    """
    # Check environment variable
    env_backend = os.environ.get("CRYSTAL_TUI_BACKEND", "").lower()
    if env_backend == "aiida":
        return BackendMode.AIIDA
    elif env_backend == "legacy":
        return BackendMode.LEGACY

    # Check config file
    config_path = Path.home() / ".crystal_tui" / "config.yaml"
    if config_path.exists():
        try:
            import yaml

            with open(config_path) as f:
                config = yaml.safe_load(f)
                if config and "backend" in config:
                    backend = config["backend"].lower()
                    if backend == "aiida":
                        return BackendMode.AIIDA
                    elif backend == "legacy":
                        return BackendMode.LEGACY
        except Exception:
            pass

    # Auto-detect
    return BackendMode.AUTO


def is_aiida_available() -> bool:
    """Check if AiiDA is available and configured."""
    try:
        import aiida

        # Try to load the crystal-tui profile
        from aiida import load_profile

        load_profile("crystal-tui")
        return True
    except ImportError:
        return False
    except Exception:
        # AiiDA installed but not configured
        return False


def get_database(
    mode: BackendMode | None = None,
    **kwargs: Any,
) -> Union["Database", "AiiDAQueryAdapter"]:
    """
    Get database instance based on backend mode.

    Args:
        mode: Backend mode (defaults to configured/auto-detected mode).
        **kwargs: Additional arguments for database initialization.

    Returns:
        Database instance (either SQLite or AiiDA-backed).

    Raises:
        RuntimeError: If requested backend is not available.
    """
    if mode is None:
        mode = get_backend_mode()

    if mode == BackendMode.AUTO:
        # Auto-detect: prefer AiiDA if available
        mode = BackendMode.AIIDA if is_aiida_available() else BackendMode.LEGACY

    if mode == BackendMode.AIIDA:
        if not is_aiida_available():
            raise RuntimeError(
                "AiiDA backend requested but not available. "
                "Install with: pip install crystal-tui[aiida] "
                "and configure with: verdi quicksetup"
            )
        from src.aiida.query_adapter import AiiDAQueryAdapter

        profile = kwargs.get("aiida_profile", "crystal-tui")
        return AiiDAQueryAdapter(profile_name=profile)

    else:  # LEGACY mode
        from src.core.database import Database

        db_path = kwargs.get("db_path")
        return Database(db_path=db_path) if db_path else Database()


def get_submitter(
    mode: BackendMode | None = None,
    **kwargs: Any,
):
    """
    Get job submitter based on backend mode.

    For legacy mode, returns the orchestrator.
    For AiiDA mode, returns a WorkChain submitter.

    Args:
        mode: Backend mode.
        **kwargs: Additional arguments.

    Returns:
        Submitter instance.
    """
    if mode is None:
        mode = get_backend_mode()

    if mode == BackendMode.AUTO:
        mode = BackendMode.AIIDA if is_aiida_available() else BackendMode.LEGACY

    if mode == BackendMode.AIIDA:
        from src.aiida.submitter import AiiDASubmitter

        return AiiDASubmitter(**kwargs)
    else:
        from src.core.orchestrator import Orchestrator

        return Orchestrator(**kwargs)


# Module-level cache for database instance
_database_instance: Union["Database", "AiiDAQueryAdapter"] | None = None


def get_shared_database() -> Union["Database", "AiiDAQueryAdapter"]:
    """
    Get shared database instance (singleton pattern).

    Returns:
        Shared database instance.
    """
    global _database_instance
    if _database_instance is None:
        _database_instance = get_database()
    return _database_instance


def reset_shared_database() -> None:
    """Reset shared database instance (for testing)."""
    global _database_instance
    _database_instance = None
