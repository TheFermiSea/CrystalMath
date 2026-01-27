"""
Density of States (DOS) extraction and analysis.

Supports extraction from:
- VASP (DOSCAR, vasprun.xml)
- Quantum ESPRESSO (*.dos, *.pdos_*)
- CRYSTAL (.DOSS files)
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class DOSData:
    """Total density of states data."""

    energy: np.ndarray  # Energy grid (eV)
    total_dos: np.ndarray  # Total DOS
    integrated_dos: np.ndarray | None = None  # Integrated DOS

    # Spin-resolved
    spin_up: np.ndarray | None = None
    spin_down: np.ndarray | None = None

    # Reference
    fermi_energy: float = 0.0
    energy_min: float = 0.0
    energy_max: float = 0.0
    nedos: int = 0

    # Metadata
    is_spin_polarized: bool = False


@dataclass
class ProjectedDOS:
    """Projected density of states (per atom/orbital)."""

    energy: np.ndarray
    fermi_energy: float = 0.0

    # Per-atom projections: {atom_index: {orbital: dos_array}}
    atom_projections: dict[int, dict[str, np.ndarray]] = field(default_factory=dict)

    # Per-element projections: {element: dos_array}
    element_projections: dict[str, np.ndarray] = field(default_factory=dict)

    # Orbital labels
    orbital_labels: list[str] = field(default_factory=lambda: ["s", "p", "d", "f"])


def extract_dos_vasp(
    doscar_path: Path | None = None,
    vasprun_path: Path | None = None,
    work_dir: Path | None = None,
) -> tuple[DOSData, ProjectedDOS | None]:
    """Extract DOS from VASP output files.

    Args:
        doscar_path: Path to DOSCAR file.
        vasprun_path: Path to vasprun.xml file.
        work_dir: Working directory to search for files.

    Returns:
        Tuple of (DOSData, ProjectedDOS or None).
    """
    if work_dir:
        doscar_path = doscar_path or (work_dir / "DOSCAR")
        vasprun_path = vasprun_path or (work_dir / "vasprun.xml")

    # Try vasprun.xml first
    if vasprun_path and vasprun_path.exists():
        return _parse_vasprun_dos(vasprun_path)

    # Fall back to DOSCAR
    if doscar_path and doscar_path.exists():
        return _parse_doscar(doscar_path), None

    raise FileNotFoundError("No VASP DOS files found")


def _parse_vasprun_dos(vasprun_path: Path) -> tuple[DOSData, ProjectedDOS | None]:
    """Parse DOS from vasprun.xml."""
    tree = ET.parse(vasprun_path)
    root = tree.getroot()

    # Get Fermi energy
    fermi = root.find(".//dos/i[@name='efermi']")
    fermi_energy = float(fermi.text) if fermi is not None else 0.0

    # Get total DOS
    total_dos_elem = root.find(".//dos/total/array/set/set")

    energies = []
    total_dos = []
    integrated_dos = []

    if total_dos_elem is not None:
        for r in total_dos_elem.findall("r"):
            values = [float(x) for x in r.text.split()]
            energies.append(values[0])
            total_dos.append(values[1])
            if len(values) > 2:
                integrated_dos.append(values[2])

    energy = np.array(energies)
    total = np.array(total_dos)
    integrated = np.array(integrated_dos) if integrated_dos else None

    dos_data = DOSData(
        energy=energy,
        total_dos=total,
        integrated_dos=integrated,
        fermi_energy=fermi_energy,
        energy_min=energy.min() if len(energy) > 0 else 0.0,
        energy_max=energy.max() if len(energy) > 0 else 0.0,
        nedos=len(energy),
    )

    # Try to get projected DOS
    pdos = _parse_vasprun_pdos(root, energy, fermi_energy)

    return dos_data, pdos


def _parse_vasprun_pdos(
    root: ET.Element,
    energy: np.ndarray,
    fermi_energy: float,
) -> ProjectedDOS | None:
    """Parse projected DOS from vasprun.xml."""
    partial_elem = root.find(".//dos/partial")
    if partial_elem is None:
        return None

    pdos = ProjectedDOS(energy=energy, fermi_energy=fermi_energy)

    # Get orbital labels
    fields = partial_elem.find(".//array/field")
    if fields is not None:
        # Parse field names for orbital labels
        pass

    # Parse per-atom projections
    ion_sets = partial_elem.findall(".//set/set")
    for atom_idx, ion_set in enumerate(ion_sets):
        pdos.atom_projections[atom_idx] = {}

        for spin_set in ion_set.findall("set"):
            orb_dos = []
            for r in spin_set.findall("r"):
                values = [float(x) for x in r.text.split()]
                orb_dos.append(values[1:])  # Skip energy

            orb_dos = np.array(orb_dos)

            # Map to orbital labels
            for i, label in enumerate(["s", "py", "pz", "px", "dxy", "dyz", "dz2", "dxz", "dx2"]):
                if i < orb_dos.shape[1]:
                    pdos.atom_projections[atom_idx][label] = orb_dos[:, i]

    return pdos


def _parse_doscar(doscar_path: Path) -> DOSData:
    """Parse DOS from DOSCAR file."""
    with open(doscar_path) as f:
        lines = f.readlines()

    # Header (first 5 lines)
    # Line 6: EMAX EMIN NEDOS EFERMI
    header = lines[5].split()
    emax = float(header[0])
    emin = float(header[1])
    nedos = int(header[2])
    fermi_energy = float(header[3])

    # Parse total DOS (starts at line 7)
    energies = []
    total_dos = []
    integrated_dos = []
    spin_up = []
    spin_down = []

    for i in range(6, 6 + nedos):
        values = [float(x) for x in lines[i].split()]
        energies.append(values[0])

        if len(values) == 3:
            # Non-spin-polarized
            total_dos.append(values[1])
            integrated_dos.append(values[2])
        elif len(values) == 5:
            # Spin-polarized
            spin_up.append(values[1])
            spin_down.append(values[2])
            total_dos.append(values[1] + values[2])
            integrated_dos.append(values[3] + values[4])

    is_spin = len(spin_up) > 0

    return DOSData(
        energy=np.array(energies),
        total_dos=np.array(total_dos),
        integrated_dos=np.array(integrated_dos),
        spin_up=np.array(spin_up) if is_spin else None,
        spin_down=np.array(spin_down) if is_spin else None,
        fermi_energy=fermi_energy,
        energy_min=emin,
        energy_max=emax,
        nedos=nedos,
        is_spin_polarized=is_spin,
    )


def extract_dos_qe(
    dos_file: Path | None = None,
    pdos_files: list[Path] | None = None,
    work_dir: Path | None = None,
) -> tuple[DOSData, ProjectedDOS | None]:
    """Extract DOS from Quantum ESPRESSO output.

    Args:
        dos_file: Path to *.dos file.
        pdos_files: List of paths to *.pdos_* files.
        work_dir: Working directory to search for files.

    Returns:
        Tuple of (DOSData, ProjectedDOS or None).
    """
    if work_dir:
        dos_files = list(work_dir.glob("*.dos"))
        pdos_glob = list(work_dir.glob("*.pdos_*"))

        if dos_files:
            dos_file = dos_files[0]
        if pdos_glob:
            pdos_files = pdos_glob

    if not dos_file or not dos_file.exists():
        raise FileNotFoundError("No QE DOS file found")

    # Parse total DOS
    dos_data = _parse_qe_dos(dos_file)

    # Parse projected DOS if available
    pdos = None
    if pdos_files:
        pdos = _parse_qe_pdos(pdos_files, dos_data.energy, dos_data.fermi_energy)

    return dos_data, pdos


def _parse_qe_dos(dos_file: Path) -> DOSData:
    """Parse DOS from QE .dos file."""
    with open(dos_file) as f:
        lines = f.readlines()

    # Skip header lines starting with #
    data_lines = [l for l in lines if not l.strip().startswith("#")]

    # Parse Fermi energy from header
    fermi_energy = 0.0
    for line in lines:
        if "Fermi" in line or "EFermi" in line:
            match = re.search(r"[-+]?\d*\.?\d+", line)
            if match:
                fermi_energy = float(match.group())
            break

    energies = []
    total_dos = []
    integrated_dos = []

    for line in data_lines:
        values = [float(x) for x in line.split()]
        if len(values) >= 2:
            energies.append(values[0])
            total_dos.append(values[1])
            if len(values) >= 3:
                integrated_dos.append(values[2])

    return DOSData(
        energy=np.array(energies),
        total_dos=np.array(total_dos),
        integrated_dos=np.array(integrated_dos) if integrated_dos else None,
        fermi_energy=fermi_energy,
        energy_min=min(energies) if energies else 0.0,
        energy_max=max(energies) if energies else 0.0,
        nedos=len(energies),
    )


def _parse_qe_pdos(
    pdos_files: list[Path],
    energy: np.ndarray,
    fermi_energy: float,
) -> ProjectedDOS:
    """Parse projected DOS from QE pdos files."""
    pdos = ProjectedDOS(energy=energy, fermi_energy=fermi_energy)

    for pdos_file in pdos_files:
        # Extract atom index and orbital from filename
        # Format: prefix.pdos_atm#N(Element)_wfc#M(orbital)
        name = pdos_file.name
        match = re.search(r"atm#(\d+)\((\w+)\)_wfc#\d+\((\w+)\)", name)

        if match:
            atom_idx = int(match.group(1)) - 1  # 0-indexed
            element = match.group(2)
            orbital = match.group(3)

            # Parse file
            with open(pdos_file) as f:
                lines = [l for l in f if not l.startswith("#")]

            dos_values = []
            for line in lines:
                values = [float(x) for x in line.split()]
                if len(values) >= 2:
                    dos_values.append(values[1])

            dos_array = np.array(dos_values)

            # Store by atom
            if atom_idx not in pdos.atom_projections:
                pdos.atom_projections[atom_idx] = {}
            pdos.atom_projections[atom_idx][orbital] = dos_array

            # Accumulate by element
            if element not in pdos.element_projections:
                pdos.element_projections[element] = np.zeros_like(energy)
            pdos.element_projections[element] += dos_array

    return pdos


def integrate_dos(
    dos_data: DOSData,
    energy_range: tuple[float, float] | None = None,
) -> float:
    """Integrate DOS over energy range.

    Args:
        dos_data: DOSData to integrate.
        energy_range: Optional (min, max) energy range. Defaults to (-inf, Ef).

    Returns:
        Integrated DOS (number of electrons).
    """
    energy = dos_data.energy
    dos = dos_data.total_dos

    if energy_range is None:
        energy_range = (energy.min(), dos_data.fermi_energy)

    mask = (energy >= energy_range[0]) & (energy <= energy_range[1])
    return np.trapz(dos[mask], energy[mask])


__all__ = [
    "DOSData",
    "ProjectedDOS",
    "extract_dos_vasp",
    "extract_dos_qe",
    "integrate_dos",
]
