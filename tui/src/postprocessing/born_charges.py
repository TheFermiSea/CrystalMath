"""
Born effective charges and polarization extraction.

Born effective charges are defined as:
Z*_ij = V * dP_i / du_j

where P is the polarization and u is the atomic displacement.

Supports extraction from:
- VASP (OUTCAR from LEPSILON=.TRUE. or DFPT)
- Quantum ESPRESSO (ph.x output)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class BornCharges:
    """Born effective charges data."""

    # Per-atom Born charges: shape (natoms, 3, 3)
    charges: np.ndarray

    # Atomic labels
    atom_symbols: list[str] = field(default_factory=list)
    atom_indices: list[int] = field(default_factory=list)

    # Dielectric tensor
    dielectric_tensor: np.ndarray | None = None  # Shape (3, 3)
    dielectric_ionic: np.ndarray | None = None  # Ionic contribution
    dielectric_electronic: np.ndarray | None = None  # Electronic contribution

    # Metadata
    natoms: int = 0
    source: str = "unknown"

    def get_isotropic_charges(self) -> np.ndarray:
        """Get isotropic (trace/3) Born charges for each atom."""
        return np.trace(self.charges, axis1=1, axis2=2) / 3

    def check_asr(self) -> tuple[bool, float]:
        """Check acoustic sum rule: sum of Z* should be zero.

        Returns:
            Tuple of (passes_asr, max_violation).
        """
        sum_charges = np.sum(self.charges, axis=0)
        max_violation = np.max(np.abs(sum_charges))
        passes = max_violation < 0.1  # Tolerance
        return passes, max_violation


def extract_born_charges_vasp(
    outcar_path: Path | None = None,
    work_dir: Path | None = None,
) -> BornCharges:
    """Extract Born effective charges from VASP OUTCAR.

    Requires calculation with LEPSILON=.TRUE. or IBRION=7/8 (DFPT).

    Args:
        outcar_path: Path to OUTCAR file.
        work_dir: Working directory to search for files.

    Returns:
        BornCharges with extracted data.
    """
    if work_dir:
        outcar_path = outcar_path or (work_dir / "OUTCAR")

    if not outcar_path or not outcar_path.exists():
        raise FileNotFoundError("OUTCAR not found")

    with open(outcar_path) as f:
        content = f.read()

    # Parse Born effective charges
    charges_list = []
    symbols = []

    # Find BORN EFFECTIVE CHARGES section
    born_match = re.search(
        r"BORN EFFECTIVE CHARGES.*?-{40,}(.*?)(?=-{40,}|MACROSCOPIC)",
        content,
        re.DOTALL,
    )

    if born_match:
        born_text = born_match.group(1)

        # Parse each ion's charges
        ion_blocks = re.findall(
            r"ion\s+(\d+).*?\n(.*?)(?=ion\s+\d+|\Z)",
            born_text,
            re.DOTALL,
        )

        for ion_num, block in ion_blocks:
            # Parse 3x3 tensor
            tensor = []
            for line in block.strip().split("\n"):
                values = re.findall(r"[-\d.]+", line)
                if len(values) >= 3:
                    tensor.append([float(v) for v in values[-3:]])

            if len(tensor) >= 3:
                charges_list.append(tensor[:3])

    if not charges_list:
        raise ValueError("No Born effective charges found in OUTCAR")

    charges = np.array(charges_list)

    # Get atom symbols from OUTCAR
    symbols = _parse_atom_symbols_vasp(content)

    # Parse dielectric tensor
    dielectric = _parse_dielectric_vasp(content)

    return BornCharges(
        charges=charges,
        atom_symbols=symbols,
        atom_indices=list(range(len(charges))),
        dielectric_tensor=dielectric.get("total"),
        dielectric_ionic=dielectric.get("ionic"),
        dielectric_electronic=dielectric.get("electronic"),
        natoms=len(charges),
        source="vasp",
    )


def _parse_atom_symbols_vasp(content: str) -> list[str]:
    """Parse atom symbols from VASP OUTCAR."""
    symbols = []

    # Find POTCAR entries
    potcar_match = re.findall(r"TITEL\s*=\s*\w+\s+(\w+)", content)
    if potcar_match:
        # Get ion counts from POSCAR/CONTCAR section
        ions_match = re.search(r"ions per type\s*=\s*([\d\s]+)", content)
        if ions_match:
            counts = [int(x) for x in ions_match.group(1).split()]
            for elem, count in zip(potcar_match, counts, strict=False):
                symbols.extend([elem] * count)

    return symbols


def _parse_dielectric_vasp(content: str) -> dict[str, np.ndarray]:
    """Parse dielectric tensor from VASP OUTCAR."""
    result = {}

    # Electronic contribution
    elec_match = re.search(
        r"MACROSCOPIC STATIC DIELECTRIC TENSOR \(electronic\).*?-{40,}\s*\n(.*?)\n\s*-{40,}",
        content,
        re.DOTALL,
    )

    if elec_match:
        tensor = []
        for line in elec_match.group(1).strip().split("\n"):
            values = [float(x) for x in line.split()]
            if len(values) >= 3:
                tensor.append(values[:3])
        if len(tensor) >= 3:
            result["electronic"] = np.array(tensor[:3])

    # Ionic contribution
    ionic_match = re.search(
        r"MACROSCOPIC STATIC DIELECTRIC TENSOR IONIC CONTRIBUTION.*?-{40,}\s*\n(.*?)\n\s*-{40,}",
        content,
        re.DOTALL,
    )

    if ionic_match:
        tensor = []
        for line in ionic_match.group(1).strip().split("\n"):
            values = [float(x) for x in line.split()]
            if len(values) >= 3:
                tensor.append(values[:3])
        if len(tensor) >= 3:
            result["ionic"] = np.array(tensor[:3])

    # Total (if both present)
    if "electronic" in result and "ionic" in result:
        result["total"] = result["electronic"] + result["ionic"]
    elif "electronic" in result:
        result["total"] = result["electronic"]

    return result


def extract_born_charges_qe(
    dynmat_file: Path | None = None,
    ph_output: Path | None = None,
    work_dir: Path | None = None,
) -> BornCharges:
    """Extract Born effective charges from Quantum ESPRESSO ph.x output.

    Args:
        dynmat_file: Path to dynamical matrix file.
        ph_output: Path to ph.x output file.
        work_dir: Working directory to search for files.

    Returns:
        BornCharges with extracted data.
    """
    if work_dir:
        dynmat_files = list(work_dir.glob("*.dyn*"))
        ph_outputs = list(work_dir.glob("*.ph.out")) + list(work_dir.glob("ph.out"))

        if dynmat_files:
            dynmat_file = dynmat_files[0]
        if ph_outputs:
            ph_output = ph_outputs[0]

    # Try ph.x output first
    if ph_output and ph_output.exists():
        return _parse_qe_ph_output(ph_output)

    # Try dynamical matrix file
    if dynmat_file and dynmat_file.exists():
        return _parse_qe_dynmat(dynmat_file)

    raise FileNotFoundError("No QE phonon output found")


def _parse_qe_ph_output(ph_output: Path) -> BornCharges:
    """Parse Born charges from QE ph.x output."""
    with open(ph_output) as f:
        content = f.read()

    charges_list = []
    symbols = []

    # Find Born effective charges section
    born_match = re.search(
        r"Effective Charges E-U.*?\n(.*?)(?=Dielectric|Done|\Z)",
        content,
        re.DOTALL,
    )

    if born_match:
        # Parse atom blocks
        atom_blocks = re.findall(
            r"atom\s+(\d+)\s+(\w+).*?\n(.*?)(?=atom\s+\d+|\Z)",
            born_match.group(1),
            re.DOTALL,
        )

        for atom_num, symbol, block in atom_blocks:
            symbols.append(symbol)
            tensor = []

            for line in block.strip().split("\n"):
                match = re.match(r"\s*E[xyz]\s*\((.*?)\)", line)
                if match:
                    values = [float(x) for x in match.group(1).split()]
                    if len(values) >= 3:
                        tensor.append(values[:3])

            if len(tensor) >= 3:
                charges_list.append(tensor[:3])

    if not charges_list:
        raise ValueError("No Born charges found in QE output")

    charges = np.array(charges_list)

    # Parse dielectric tensor
    dielectric = _parse_qe_dielectric(content)

    return BornCharges(
        charges=charges,
        atom_symbols=symbols,
        atom_indices=list(range(len(charges))),
        dielectric_tensor=dielectric,
        natoms=len(charges),
        source="qe",
    )


def _parse_qe_dynmat(dynmat_file: Path) -> BornCharges:
    """Parse Born charges from QE dynamical matrix file."""
    with open(dynmat_file) as f:
        content = f.read()

    # Simplified parsing - full implementation would parse .dyn format
    raise NotImplementedError("Dynamical matrix parsing not yet implemented")


def _parse_qe_dielectric(content: str) -> np.ndarray | None:
    """Parse dielectric tensor from QE output."""
    dielectric_match = re.search(
        r"Dielectric constant.*?\n(.*?)(?=\n\s*\n|\Z)",
        content,
        re.DOTALL,
    )

    if dielectric_match:
        tensor = []
        for line in dielectric_match.group(1).strip().split("\n"):
            values = [float(x) for x in line.split() if re.match(r"[-\d.]+", x)]
            if len(values) >= 3:
                tensor.append(values[:3])

        if len(tensor) >= 3:
            return np.array(tensor[:3])

    return None


def calculate_polarization(
    born_charges: BornCharges,
    displacements: np.ndarray,
    volume: float,
) -> np.ndarray:
    """Calculate polarization from Born charges and atomic displacements.

    P_i = (e / V) * sum_j(Z*_ij * u_j)

    Args:
        born_charges: BornCharges with effective charges.
        displacements: Atomic displacements in Angstrom, shape (natoms, 3).
        volume: Unit cell volume in A^3.

    Returns:
        Polarization vector in C/m^2.
    """
    # Elementary charge
    e = 1.602176634e-19  # C

    # Convert volume to m^3
    V_m3 = volume * 1e-30

    # Calculate polarization
    P = np.zeros(3)
    for atom in range(born_charges.natoms):
        for i in range(3):
            for j in range(3):
                P[i] += born_charges.charges[atom, i, j] * displacements[atom, j]

    P = (e / V_m3) * P

    return P


__all__ = [
    "BornCharges",
    "extract_born_charges_vasp",
    "extract_born_charges_qe",
    "calculate_polarization",
]
