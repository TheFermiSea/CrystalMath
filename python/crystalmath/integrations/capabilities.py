"""Runtime capability detection for optional CrystalMath integrations."""

from __future__ import annotations

import importlib.util
import logging
import shutil
import sys
from importlib import metadata
from typing import Any

logger = logging.getLogger(__name__)


def _detect_module(module_name: str, distribution_name: str | None = None) -> dict[str, Any]:
    """Detect whether a Python module is importable and report its version if possible."""
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ValueError):
        spec = None

    if spec is None and module_name not in sys.modules:
        return {"available": False, "reason": f"Python module '{module_name}' is not installed"}

    version = None
    for candidate in (distribution_name, module_name):
        if not candidate:
            continue
        try:
            version = metadata.version(candidate)
            break
        except metadata.PackageNotFoundError:
            continue

    return {"available": True, "version": version}


def _detect_executable(executable: str) -> dict[str, Any]:
    """Detect whether an external executable is available on PATH."""
    path = shutil.which(executable)
    if path is None:
        return {"available": False, "reason": f"Executable '{executable}' was not found on PATH"}
    return {"available": True, "path": path}


def _detect_aiida(profile_name: str) -> dict[str, Any]:
    """Probe AiiDA availability and whether the requested profile can be loaded."""
    info = _detect_module("aiida", "aiida-core")
    info["profile_name"] = profile_name
    info["configured"] = False

    if not info["available"]:
        return info

    try:
        import aiida

        aiida.load_profile(profile_name)
        info["configured"] = True
        return info
    except Exception as exc:  # pragma: no cover - environment specific
        logger.info("AiiDA profile '%s' unavailable: %s", profile_name, exc)
        info["reason"] = str(exc)
        return info


def get_runtime_capabilities(
    *,
    profile_name: str = "default",
    db_path: str | None = None,
    selected_backend: str | None = None,
    backend_preference: str = "auto",
) -> dict[str, Any]:
    """Collect runtime capability information for optional integrations."""
    aiida_info = _detect_aiida(profile_name)
    integrations = {
        "pymatgen": _detect_module("pymatgen"),
        "ase": _detect_module("ase"),
        "seekpath": _detect_module("seekpath"),
        "quacc": _detect_module("quacc"),
        "jobflow": _detect_module("jobflow"),
        "atomate2": _detect_module("atomate2"),
        "aiida": aiida_info,
        "aiida_common_workflows": _detect_module(
            "aiida_common_workflows", "aiida-common-workflows"
        ),
        "aiida_vasp": _detect_module("aiida_vasp"),
        "vaspkit": _detect_executable("vaspkit"),
    }

    backends = {
        "sqlite": {
            "available": db_path is not None,
            "path": db_path,
            "reason": None if db_path else "No SQLite database path was provided",
        },
        "aiida": {
            "available": bool(aiida_info["available"]) and bool(aiida_info["configured"]),
            "profile_name": profile_name,
            "reason": aiida_info.get("reason"),
        },
        "demo": {"available": True},
    }

    return {
        "selected_backend": selected_backend,
        "backend_preference": backend_preference,
        "backends": backends,
        "integrations": integrations,
    }


__all__ = ["get_runtime_capabilities"]
