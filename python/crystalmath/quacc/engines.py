"""
Workflow engine detection for quacc.

This module provides utilities to detect which workflow engines
are installed and configured for use with quacc.
"""

import logging
from importlib import import_module
from typing import Any

logger = logging.getLogger(__name__)

# Known workflow engines supported by quacc
KNOWN_ENGINES = ["parsl", "dask", "prefect", "covalent", "jobflow"]

# Import paths for engine detection
ENGINE_IMPORT_PATHS = {
    "parsl": "parsl",
    "dask": "dask.distributed",
    "prefect": "prefect",
    "covalent": "covalent",
    "jobflow": "jobflow",
}


def get_workflow_engine() -> str | None:
    """
    Get the currently configured quacc workflow engine.

    Returns:
        The configured workflow engine name (e.g., "parsl", "dask"),
        or None if quacc is not installed or no engine is configured.
    """
    try:
        from quacc import SETTINGS
        engine = getattr(SETTINGS, "WORKFLOW_ENGINE", None)
        return engine if engine else None
    except ImportError:
        logger.debug("quacc not installed, cannot get workflow engine")
        return None
    except Exception as e:
        logger.debug(f"Error getting workflow engine: {e}")
        return None


def get_installed_engines() -> list[str]:
    """
    Detect which workflow engines are installed.

    Checks for the availability of known workflow engine packages
    by attempting to import them.

    Returns:
        List of installed engine names.
    """
    installed = []

    for engine, import_path in ENGINE_IMPORT_PATHS.items():
        try:
            import_module(import_path)
            installed.append(engine)
        except ImportError:
            continue

    return installed


def get_engine_status() -> dict[str, Any]:
    """
    Get comprehensive workflow engine status.

    Returns:
        Dict with keys:
        - configured: Currently configured engine (str) or None
        - installed: List of installed engine names
        - quacc_installed: Whether quacc is installed (bool)
    """
    quacc_installed = _is_quacc_installed()

    return {
        "configured": get_workflow_engine() if quacc_installed else None,
        "installed": get_installed_engines(),
        "quacc_installed": quacc_installed,
    }


def _is_quacc_installed() -> bool:
    """Check if quacc is installed."""
    try:
        import quacc  # noqa: F401
        return True
    except ImportError:
        return False
