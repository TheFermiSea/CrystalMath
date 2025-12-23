"""VASP code configuration and multi-file input handling.

VASP requires multiple input files in the working directory:
- POSCAR: Crystal structure
- INCAR: Calculation parameters
- KPOINTS: K-point mesh specification
- POTCAR: Pseudopotential files (concatenated)

Optional files:
- WAVECAR: Wavefunction restart
- CHGCAR: Charge density restart
- CONTCAR: Continued geometry (can be used as POSCAR)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .base import DFTCode, DFTCodeConfig, InvocationStyle
from .registry import register_code


# VASP required input files
VASP_REQUIRED_FILES = ["POSCAR", "INCAR", "KPOINTS", "POTCAR"]

# VASP optional input files for restarts
VASP_OPTIONAL_INPUTS = ["WAVECAR", "CHGCAR", "CONTCAR"]

# VASP output files to retrieve
VASP_OUTPUT_FILES = [
    "OUTCAR",       # Main text output
    "CONTCAR",      # Final structure
    "OSZICAR",      # SCF convergence info
    "vasprun.xml",  # XML output for parsing
    "EIGENVAL",     # Eigenvalues
    "DOSCAR",       # Density of states
    "IBZKPT",       # Irreducible k-points
    "PROCAR",       # Projected density (if LORBIT)
    "CHGCAR",       # Charge density
    "WAVECAR",      # Wavefunction (for restarts)
]


@dataclass
class VASPInputFiles:
    """Container for VASP multi-file input.

    VASP uses a fixed set of filenames in the working directory.
    This class manages validation and staging of these files.
    """

    poscar: str  # Structure in VASP POSCAR format
    incar: str   # Calculation parameters
    kpoints: str  # K-point specification
    potcar: str  # Pseudopotentials (concatenated)

    # Optional restart files
    wavecar: Optional[Path] = None  # Binary file, keep as path
    chgcar: Optional[Path] = None   # Binary file, keep as path
    contcar: Optional[str] = None   # Alternative structure

    def validate(self) -> List[str]:
        """Validate input files and return list of issues.

        Returns:
            List of validation error messages (empty if valid).
        """
        issues = []

        # Check required files have content
        if not self.poscar.strip():
            issues.append("POSCAR is empty or missing")
        if not self.incar.strip():
            issues.append("INCAR is empty or missing")
        if not self.kpoints.strip():
            issues.append("KPOINTS is empty or missing")
        if not self.potcar.strip():
            issues.append("POTCAR is empty or missing")

        # Basic POSCAR validation
        if self.poscar.strip():
            lines = self.poscar.strip().split("\n")
            if len(lines) < 8:
                issues.append("POSCAR appears incomplete (fewer than 8 lines)")

        # Basic INCAR validation
        if self.incar.strip():
            incar_upper = self.incar.upper()
            # Check for common required tags
            if "ENCUT" not in incar_upper and "PREC" not in incar_upper:
                issues.append(
                    "INCAR missing ENCUT or PREC - energy cutoff not specified"
                )

        return issues

    def write_to_directory(self, work_dir: Path) -> Dict[str, Path]:
        """Write all input files to the specified work directory.

        Args:
            work_dir: Directory to write files to.

        Returns:
            Dictionary mapping filename to written path.
        """
        written = {}

        # Write required text files
        (work_dir / "POSCAR").write_text(self.poscar)
        written["POSCAR"] = work_dir / "POSCAR"

        (work_dir / "INCAR").write_text(self.incar)
        written["INCAR"] = work_dir / "INCAR"

        (work_dir / "KPOINTS").write_text(self.kpoints)
        written["KPOINTS"] = work_dir / "KPOINTS"

        (work_dir / "POTCAR").write_text(self.potcar)
        written["POTCAR"] = work_dir / "POTCAR"

        # Copy optional binary files if provided
        if self.wavecar and self.wavecar.exists():
            import shutil
            dst = work_dir / "WAVECAR"
            shutil.copy2(self.wavecar, dst)
            written["WAVECAR"] = dst

        if self.chgcar and self.chgcar.exists():
            import shutil
            dst = work_dir / "CHGCAR"
            shutil.copy2(self.chgcar, dst)
            written["CHGCAR"] = dst

        # Use CONTCAR as POSCAR if provided (for continuation)
        if self.contcar and self.contcar.strip():
            (work_dir / "CONTCAR").write_text(self.contcar)
            written["CONTCAR"] = work_dir / "CONTCAR"

        return written

    @classmethod
    def from_directory(cls, source_dir: Path) -> "VASPInputFiles":
        """Read VASP input files from a directory.

        Args:
            source_dir: Directory containing VASP input files.

        Returns:
            VASPInputFiles instance.

        Raises:
            FileNotFoundError: If required files are missing.
        """
        # Read required files
        poscar_path = source_dir / "POSCAR"
        incar_path = source_dir / "INCAR"
        kpoints_path = source_dir / "KPOINTS"
        potcar_path = source_dir / "POTCAR"

        if not poscar_path.exists():
            raise FileNotFoundError(f"POSCAR not found in {source_dir}")
        if not incar_path.exists():
            raise FileNotFoundError(f"INCAR not found in {source_dir}")
        if not kpoints_path.exists():
            raise FileNotFoundError(f"KPOINTS not found in {source_dir}")
        if not potcar_path.exists():
            raise FileNotFoundError(f"POTCAR not found in {source_dir}")

        # Read optional files
        wavecar = source_dir / "WAVECAR" if (source_dir / "WAVECAR").exists() else None
        chgcar = source_dir / "CHGCAR" if (source_dir / "CHGCAR").exists() else None
        contcar = None
        contcar_path = source_dir / "CONTCAR"
        if contcar_path.exists():
            contcar = contcar_path.read_text()

        return cls(
            poscar=poscar_path.read_text(),
            incar=incar_path.read_text(),
            kpoints=kpoints_path.read_text(),
            potcar=potcar_path.read_text(),
            wavecar=wavecar,
            chgcar=chgcar,
            contcar=contcar,
        )


def get_vasp_files_to_stage(work_dir: Path) -> List[Path]:
    """Get list of VASP files to stage for remote execution.

    Args:
        work_dir: Local work directory containing VASP input files.

    Returns:
        List of paths to files that should be uploaded.
    """
    files = []

    # Required files
    for filename in VASP_REQUIRED_FILES:
        path = work_dir / filename
        if path.exists():
            files.append(path)

    # Optional restart files
    for filename in VASP_OPTIONAL_INPUTS:
        path = work_dir / filename
        if path.exists():
            files.append(path)

    return files


def get_vasp_output_patterns() -> List[str]:
    """Get list of patterns for VASP output files to retrieve.

    Returns:
        List of filename patterns to download after job completion.
    """
    return VASP_OUTPUT_FILES.copy()


VASP_CONFIG = DFTCodeConfig(
    name="vasp",
    display_name="VASP",
    # VASP uses fixed filenames in CWD - no extensions
    input_extensions=[],
    output_extension="",  # Output is OUTCAR
    # Multi-file input mappings (local filename -> remote filename, same for VASP)
    auxiliary_inputs={
        "POSCAR": "POSCAR",
        "INCAR": "INCAR",
        "KPOINTS": "KPOINTS",
        "POTCAR": "POTCAR",
        "WAVECAR": "WAVECAR",
        "CHGCAR": "CHGCAR",
        "CONTCAR": "CONTCAR",
    },
    # Output file mappings
    auxiliary_outputs={
        "OUTCAR": "OUTCAR",
        "CONTCAR": "CONTCAR",
        "OSZICAR": "OSZICAR",
        "vasprun.xml": "vasprun.xml",
        "EIGENVAL": "EIGENVAL",
        "DOSCAR": "DOSCAR",
        "IBZKPT": "IBZKPT",
        "PROCAR": "PROCAR",
        "CHGCAR": "CHGCAR",
        "WAVECAR": "WAVECAR",
    },
    # Executables
    serial_executable="vasp_std",
    parallel_executable="mpirun vasp_std",
    invocation_style=InvocationStyle.CWD,  # VASP reads from current directory
    # Environment
    root_env_var="VASP_ROOT",
    bashrc_pattern="vasp.bashrc",
    # Parsing
    energy_unit="eV",
    convergence_patterns=[
        "reached required accuracy",
        "General timing and accounting",
        "Total CPU time used",
    ],
    error_patterns=[
        "Error",
        "VERY BAD NEWS",
        "internal error",
        "ZBRENT: fatal error",
    ],
)


# Auto-register when module is imported
register_code(DFTCode.VASP, VASP_CONFIG)


__all__ = [
    "VASP_CONFIG",
    "VASPInputFiles",
    "VASP_REQUIRED_FILES",
    "VASP_OPTIONAL_INPUTS",
    "VASP_OUTPUT_FILES",
    "get_vasp_files_to_stage",
    "get_vasp_output_patterns",
]
