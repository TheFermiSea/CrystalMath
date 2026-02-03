"""POTCAR validation utilities for VASP job submission.

This module validates that VASP pseudopotentials are available before
attempting job submission, providing clear error messages for common
configuration issues.
"""

import os
from pathlib import Path
from typing import Set, Tuple, Optional


def get_potcar_path() -> Optional[Path]:
    """Get POTCAR directory path from environment or quacc settings.

    Checks in order:
    1. VASP_PP_PATH environment variable
    2. quacc SETTINGS.VASP_PP_PATH (if quacc installed)

    Returns:
        Path to POTCAR directory, or None if not configured.
    """
    # Check environment variable first
    env_path = os.environ.get("VASP_PP_PATH")
    if env_path:
        return Path(env_path)

    # Try quacc settings (may not be installed)
    try:
        from quacc import SETTINGS
        quacc_path = getattr(SETTINGS, "VASP_PP_PATH", None)
        if quacc_path:
            return Path(quacc_path)
    except ImportError:
        pass

    return None


def validate_potcars(elements: Set[str]) -> Tuple[bool, Optional[str]]:
    """Validate that POTCARs are available for given elements.

    Checks that:
    1. VASP_PP_PATH is configured
    2. A PBE POTCAR directory exists
    3. Each element has a POTCAR directory

    Args:
        elements: Set of element symbols (e.g., {"Si", "O"})

    Returns:
        Tuple of (valid, error_message):
        - (True, None) if all POTCARs found
        - (False, error_message) if validation fails

    Example:
        >>> valid, error = validate_potcars({"Si", "O"})
        >>> if not valid:
        ...     print(f"POTCAR validation failed: {error}")
    """
    if not elements:
        return True, None

    # Get POTCAR path
    potcar_path = get_potcar_path()
    if potcar_path is None:
        return False, (
            "VASP_PP_PATH not configured. "
            "Set the VASP_PP_PATH environment variable or configure it in ~/.quacc.yaml"
        )

    # Check path exists
    if not potcar_path.exists():
        return False, f"VASP_PP_PATH does not exist: {potcar_path}"

    if not potcar_path.is_dir():
        return False, f"VASP_PP_PATH is not a directory: {potcar_path}"

    # Find PBE POTCAR directory (most common functional)
    pbe_dirs = (
        list(potcar_path.glob("potpaw_PBE*")) +
        list(potcar_path.glob("PBE*")) +
        list(potcar_path.glob("pbe*"))
    )

    if not pbe_dirs:
        return False, (
            f"No PBE POTCAR directory found in {potcar_path}. "
            "Expected potpaw_PBE, PBE, or similar directory."
        )

    potcar_base = pbe_dirs[0]

    # Check each element
    missing = []
    for elem in elements:
        # Check standard POTCAR naming patterns:
        # - Element (e.g., Si)
        # - Element_suffix (e.g., Si_sv, O_s)
        elem_patterns = [
            potcar_base / elem,
            *potcar_base.glob(f"{elem}_*"),
        ]

        found = any(p.exists() and p.is_dir() for p in elem_patterns)
        if not found:
            missing.append(elem)

    if missing:
        return False, (
            f"Missing POTCARs for elements: {', '.join(sorted(missing))}. "
            f"Checked in: {potcar_base}"
        )

    return True, None


def get_potcar_info() -> dict:
    """Get information about POTCAR configuration.

    Returns:
        Dictionary with POTCAR configuration details.
    """
    potcar_path = get_potcar_path()

    if potcar_path is None:
        return {
            "configured": False,
            "path": None,
            "exists": False,
            "functionals": [],
        }

    exists = potcar_path.exists()
    functionals = []

    if exists and potcar_path.is_dir():
        # Find available functionals
        for pattern in ["potpaw_*", "PBE*", "LDA*", "GGA*"]:
            for d in potcar_path.glob(pattern):
                if d.is_dir():
                    functionals.append(d.name)

    return {
        "configured": True,
        "path": str(potcar_path),
        "exists": exists,
        "functionals": sorted(functionals),
    }
