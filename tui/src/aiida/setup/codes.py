"""
AiiDA Code configuration for CRYSTAL23.

This module provides functions to register CRYSTAL23 executables
as AiiDA Codes:
    - crystalOMP: OpenMP-parallel CRYSTAL executable
    - PcrystalOMP: MPI+OpenMP hybrid CRYSTAL executable
    - properties: Post-SCF analysis executable
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiida.orm import Code, Computer


def get_crystal23_path() -> Path | None:
    """
    Get CRYSTAL23 installation path from environment.

    Checks CRY23_ROOT and CRY23_EXEDIR environment variables.

    Returns:
        Path to CRYSTAL23 executables, or None if not found.
    """
    # Check CRY23_EXEDIR first (direct path to binaries)
    exe_dir = os.environ.get("CRY23_EXEDIR")
    if exe_dir:
        return Path(exe_dir)

    # Fall back to CRY23_ROOT
    root = os.environ.get("CRY23_ROOT")
    if root:
        root_path = Path(root)
        # Try common subdirectory patterns
        patterns = [
            "bin/MacOsx_ARM-gfortran_omp/v1.0.1",
            "bin/Linux-ifort_i64_omp/v1.0.1",
            "bin/*/v1.0.1",
        ]
        for pattern in patterns:
            matches = list(root_path.glob(pattern))
            if matches:
                return matches[0]

    return None


def setup_crystal_code(
    computer: Computer,
    executable: str = "crystalOMP",
    label: str | None = None,
    prepend_text: str = "",
    append_text: str = "",
) -> Code:
    """
    Setup CRYSTAL23 Code on a computer.

    Args:
        computer: AiiDA Computer to register the code on.
        executable: Executable name ('crystalOMP' or 'PcrystalOMP').
        label: Code label (defaults to executable name).
        prepend_text: Commands to prepend before execution (e.g., module loads).
        append_text: Commands to append after execution.

    Returns:
        Configured and stored Code instance.

    Example:
        >>> from src.aiida.setup.computers import setup_localhost_computer
        >>> computer = setup_localhost_computer()
        >>> code = setup_crystal_code(computer, executable="crystalOMP")
    """
    from aiida import load_profile, orm

    load_profile()

    if label is None:
        label = executable

    # Full code label includes computer
    full_label = f"{label}@{computer.label}"

    # Check if code already exists
    try:
        existing = orm.load_code(full_label)
        return existing
    except Exception:
        pass

    # Find executable path
    exe_path = get_crystal23_path()
    if exe_path is None:
        raise RuntimeError(
            "CRYSTAL23 installation not found. Set CRY23_ROOT or CRY23_EXEDIR environment variable."
        )

    executable_path = exe_path / executable
    if not executable_path.exists():
        raise RuntimeError(f"Executable not found: {executable_path}")

    # Create Code using InstalledCode (AiiDA 2.x style)
    code = orm.InstalledCode(
        label=label,
        description=f"CRYSTAL23 {executable}",
        default_calc_job_plugin="crystal23.crystal",  # Our CalcJob entry point
        computer=computer,
        filepath_executable=str(executable_path),
    )

    # Set prepend/append text for environment setup
    if prepend_text:
        code.prepend_text = prepend_text
    if append_text:
        code.append_text = append_text

    code.store()

    return code


def setup_properties_code(
    computer: Computer,
    label: str = "properties",
    prepend_text: str = "",
) -> Code:
    """
    Setup CRYSTAL23 properties Code on a computer.

    Args:
        computer: AiiDA Computer.
        label: Code label.
        prepend_text: Commands to prepend before execution.

    Returns:
        Configured and stored Code instance.
    """
    from aiida import load_profile, orm

    load_profile()

    full_label = f"{label}@{computer.label}"

    try:
        existing = orm.load_code(full_label)
        return existing
    except Exception:
        pass

    exe_path = get_crystal23_path()
    if exe_path is None:
        raise RuntimeError("CRYSTAL23 installation not found.")

    executable_path = exe_path / "properties"
    if not executable_path.exists():
        raise RuntimeError(f"Properties executable not found: {executable_path}")

    code = orm.InstalledCode(
        label=label,
        description="CRYSTAL23 properties post-processor",
        default_calc_job_plugin="crystal23.properties",  # Properties CalcJob
        computer=computer,
        filepath_executable=str(executable_path),
    )

    if prepend_text:
        code.prepend_text = prepend_text

    code.store()

    return code


def setup_localhost_codes(
    crystal_omp: bool = True,
    pcrystal_omp: bool = False,
    properties: bool = True,
) -> dict[str, Code]:
    """
    Setup all CRYSTAL23 codes on localhost.

    Args:
        crystal_omp: Setup crystalOMP code.
        pcrystal_omp: Setup PcrystalOMP code.
        properties: Setup properties code.

    Returns:
        Dictionary of code labels to Code instances.

    Example:
        >>> codes = setup_localhost_codes()
        >>> codes['crystalOMP'].label
        'crystalOMP@localhost'
    """
    from .computers import setup_localhost_computer

    computer = setup_localhost_computer()
    codes = {}

    # Default prepend for OpenMP threading
    omp_prepend = """
# CRYSTAL23 OpenMP environment
export OMP_STACKSIZE=128M
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-4}
export KMP_AFFINITY=compact,granularity=fine
"""

    if crystal_omp:
        codes["crystalOMP"] = setup_crystal_code(
            computer=computer,
            executable="crystalOMP",
            prepend_text=omp_prepend,
        )

    if pcrystal_omp:
        codes["PcrystalOMP"] = setup_crystal_code(
            computer=computer,
            executable="PcrystalOMP",
            prepend_text=omp_prepend,
        )

    if properties:
        codes["properties"] = setup_properties_code(
            computer=computer,
            prepend_text=omp_prepend,
        )

    return codes


def list_codes() -> list[dict]:
    """
    List all CRYSTAL23 codes registered in AiiDA.

    Returns:
        List of code info dictionaries.
    """
    from aiida import load_profile, orm

    load_profile()

    codes = []
    qb = orm.QueryBuilder()
    qb.append(orm.Code, project=["label", "description"])

    for label, description in qb.all():
        if "crystal" in label.lower() or "crystal" in (description or "").lower():
            codes.append(
                {
                    "label": label,
                    "description": description,
                }
            )

    return codes


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Setup AiiDA codes for CRYSTAL23")
    parser.add_argument(
        "--localhost",
        action="store_true",
        help="Setup codes on localhost",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List registered CRYSTAL23 codes",
    )
    parser.add_argument(
        "--with-mpi",
        action="store_true",
        help="Include MPI-parallel code (PcrystalOMP)",
    )

    args = parser.parse_args()

    if args.localhost:
        codes = setup_localhost_codes(pcrystal_omp=args.with_mpi)
        print("Registered codes:")
        for label, code in codes.items():
            print(f"  {code.full_label}")
    elif args.list:
        codes = list_codes()
        if codes:
            print("CRYSTAL23 codes:")
            for c in codes:
                print(f"  {c['label']}: {c['description']}")
        else:
            print("No CRYSTAL23 codes found")
    else:
        parser.print_help()
