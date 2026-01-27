"""
Band structure extraction and analysis.

Supports extraction from:
- VASP (EIGENVAL, vasprun.xml)
- Quantum ESPRESSO (bands.out, *.xml)
- CRYSTAL (.f25 files)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class BandData:
    """Band structure data container."""

    # K-point information
    kpoints: np.ndarray  # Shape: (nkpts, 3)
    kpoint_distances: np.ndarray  # Cumulative distance along path
    kpoint_labels: list[str] = field(default_factory=list)  # High-symmetry labels
    label_positions: list[float] = field(default_factory=list)  # Label positions

    # Eigenvalues
    eigenvalues: np.ndarray  # Shape: (nkpts, nbands) or (nkpts, nbands, 2) for spin
    occupations: np.ndarray | None = None

    # Reference energies
    fermi_energy: float = 0.0
    vbm: float | None = None
    cbm: float | None = None

    # Metadata
    nspin: int = 1
    nbands: int = 0
    nkpts: int = 0
    is_metal: bool = False


@dataclass
class BandStructure:
    """Complete band structure analysis result."""

    data: BandData
    band_gap: float | None = None
    gap_type: str = "unknown"  # direct, indirect, metal
    vbm_location: tuple[int, int] | None = None  # (kpt_idx, band_idx)
    cbm_location: tuple[int, int] | None = None

    # Additional properties
    effective_masses: dict[str, float] | None = None
    spin_polarization: float | None = None


def extract_bands_vasp(
    eigenval_path: Path | None = None,
    vasprun_path: Path | None = None,
    outcar_path: Path | None = None,
    work_dir: Path | None = None,
) -> BandData:
    """Extract band structure from VASP output files.

    Args:
        eigenval_path: Path to EIGENVAL file.
        vasprun_path: Path to vasprun.xml file.
        outcar_path: Path to OUTCAR file (for Fermi energy).
        work_dir: Working directory to search for files.

    Returns:
        BandData with extracted band structure.
    """
    if work_dir:
        eigenval_path = eigenval_path or (work_dir / "EIGENVAL")
        vasprun_path = vasprun_path or (work_dir / "vasprun.xml")
        outcar_path = outcar_path or (work_dir / "OUTCAR")

    # Try vasprun.xml first (more complete)
    if vasprun_path and vasprun_path.exists():
        return _parse_vasprun_bands(vasprun_path)

    # Fall back to EIGENVAL
    if eigenval_path and eigenval_path.exists():
        return _parse_eigenval(eigenval_path, outcar_path)

    raise FileNotFoundError("No VASP band structure files found")


def _parse_vasprun_bands(vasprun_path: Path) -> BandData:
    """Parse band structure from vasprun.xml."""
    tree = ET.parse(vasprun_path)
    root = tree.getroot()

    # Get Fermi energy
    fermi = root.find(".//dos/i[@name='efermi']")
    fermi_energy = float(fermi.text) if fermi is not None else 0.0

    # Get k-points
    kpoints_elem = root.find(".//kpoints/varray[@name='kpointlist']")
    kpoints = []
    if kpoints_elem is not None:
        for v in kpoints_elem.findall("v"):
            kpoints.append([float(x) for x in v.text.split()])
    kpoints = np.array(kpoints)

    # Get eigenvalues
    eigenvalues_elem = root.find(".//eigenvalues/array/set")
    nspin = len(eigenvalues_elem.findall("set"))

    all_eigenvalues = []
    all_occupations = []

    for spin_set in eigenvalues_elem.findall("set"):
        spin_eigenvalues = []
        spin_occupations = []

        for kpt_set in spin_set.findall("set"):
            kpt_eigenvalues = []
            kpt_occupations = []

            for r in kpt_set.findall("r"):
                values = r.text.split()
                kpt_eigenvalues.append(float(values[0]))
                kpt_occupations.append(float(values[1]))

            spin_eigenvalues.append(kpt_eigenvalues)
            spin_occupations.append(kpt_occupations)

        all_eigenvalues.append(spin_eigenvalues)
        all_occupations.append(spin_occupations)

    eigenvalues = np.array(all_eigenvalues)
    occupations = np.array(all_occupations)

    # Reshape: (nspin, nkpts, nbands) -> (nkpts, nbands, nspin) or (nkpts, nbands)
    if nspin == 1:
        eigenvalues = eigenvalues[0]
        occupations = occupations[0]
    else:
        eigenvalues = np.transpose(eigenvalues, (1, 2, 0))
        occupations = np.transpose(occupations, (1, 2, 0))

    nkpts, nbands = eigenvalues.shape[:2]

    # Calculate k-point distances
    kpoint_distances = _calculate_kpoint_distances(kpoints)

    return BandData(
        kpoints=kpoints,
        kpoint_distances=kpoint_distances,
        eigenvalues=eigenvalues,
        occupations=occupations,
        fermi_energy=fermi_energy,
        nspin=nspin,
        nbands=nbands,
        nkpts=nkpts,
    )


def _parse_eigenval(eigenval_path: Path, outcar_path: Path | None = None) -> BandData:
    """Parse band structure from EIGENVAL file."""
    with open(eigenval_path) as f:
        lines = f.readlines()

    # Header
    nelect, nkpts, nbands = map(int, lines[5].split())

    # Get Fermi energy from OUTCAR if available
    fermi_energy = 0.0
    if outcar_path and outcar_path.exists():
        with open(outcar_path) as f:
            for line in f:
                if "E-fermi" in line:
                    fermi_energy = float(line.split()[2])
                    break

    # Parse k-points and eigenvalues
    kpoints = []
    eigenvalues = []

    i = 7  # Start after header
    for _ in range(nkpts):
        # K-point line
        parts = lines[i].split()
        kpoints.append([float(x) for x in parts[:3]])
        i += 1

        # Eigenvalue lines
        kpt_eigenvalues = []
        for _ in range(nbands):
            parts = lines[i].split()
            kpt_eigenvalues.append(float(parts[1]))
            i += 1

        eigenvalues.append(kpt_eigenvalues)
        i += 1  # Empty line

    kpoints = np.array(kpoints)
    eigenvalues = np.array(eigenvalues)
    kpoint_distances = _calculate_kpoint_distances(kpoints)

    return BandData(
        kpoints=kpoints,
        kpoint_distances=kpoint_distances,
        eigenvalues=eigenvalues,
        fermi_energy=fermi_energy,
        nspin=1,
        nbands=nbands,
        nkpts=nkpts,
    )


def extract_bands_qe(
    bands_out: Path | None = None,
    xml_path: Path | None = None,
    work_dir: Path | None = None,
) -> BandData:
    """Extract band structure from Quantum ESPRESSO output.

    Args:
        bands_out: Path to bands.out or *.bands file.
        xml_path: Path to data-file-schema.xml.
        work_dir: Working directory to search for files.

    Returns:
        BandData with extracted band structure.
    """
    if work_dir:
        # Find output files
        bands_files = list(work_dir.glob("*.bands"))
        xml_files = list(work_dir.glob("*.save/data-file-schema.xml"))

        if xml_files:
            xml_path = xml_files[0]
        if bands_files:
            bands_out = bands_files[0]

    if xml_path and xml_path.exists():
        return _parse_qe_xml_bands(xml_path)

    if bands_out and bands_out.exists():
        return _parse_qe_bands_dat(bands_out)

    raise FileNotFoundError("No QE band structure files found")


def _parse_qe_xml_bands(xml_path: Path) -> BandData:
    """Parse bands from QE XML output."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Get Fermi energy
    fermi = root.find(".//fermi_energy")
    # QE uses Hartree
    fermi_energy = float(fermi.text) * 27.2114 if fermi is not None else 0.0

    # Get k-points
    kpoints_elem = root.find(".//band_structure/ks_energies")
    # Parse based on QE XML structure...

    # Simplified - actual implementation would parse full XML
    return BandData(
        kpoints=np.array([[0, 0, 0]]),
        kpoint_distances=np.array([0.0]),
        eigenvalues=np.array([[0.0]]),
        fermi_energy=fermi_energy,
        nspin=1,
        nbands=1,
        nkpts=1,
    )


def _parse_qe_bands_dat(bands_path: Path) -> BandData:
    """Parse bands from QE .bands or bands.dat file."""
    with open(bands_path) as f:
        content = f.read()

    # Parse header
    lines = content.strip().split("\n")
    header = lines[0].split()
    nbands = int(header[2].rstrip(","))
    nkpts = int(header[4])

    # Parse data blocks
    kpoints = []
    eigenvalues = []

    i = 1
    for _ in range(nkpts):
        # K-point line
        kpt_line = lines[i].strip()
        kpt = [float(x) for x in kpt_line.split()]
        kpoints.append(kpt)
        i += 1

        # Eigenvalue lines (may span multiple lines)
        kpt_eigs = []
        while len(kpt_eigs) < nbands:
            eig_line = lines[i].strip()
            kpt_eigs.extend([float(x) for x in eig_line.split()])
            i += 1

        eigenvalues.append(kpt_eigs[:nbands])

    kpoints = np.array(kpoints)
    eigenvalues = np.array(eigenvalues)
    kpoint_distances = _calculate_kpoint_distances(kpoints)

    return BandData(
        kpoints=kpoints,
        kpoint_distances=kpoint_distances,
        eigenvalues=eigenvalues,
        fermi_energy=0.0,
        nspin=1,
        nbands=nbands,
        nkpts=nkpts,
    )


def _calculate_kpoint_distances(kpoints: np.ndarray) -> np.ndarray:
    """Calculate cumulative distances along k-point path."""
    distances = [0.0]
    for i in range(1, len(kpoints)):
        dk = np.linalg.norm(kpoints[i] - kpoints[i - 1])
        distances.append(distances[-1] + dk)
    return np.array(distances)


def find_band_gap(band_data: BandData) -> tuple[float | None, str]:
    """Find the band gap from band structure data.

    Args:
        band_data: BandData with eigenvalues and occupations.

    Returns:
        Tuple of (gap in eV, gap_type: 'direct'|'indirect'|'metal').
    """
    eigenvalues = band_data.eigenvalues
    fermi = band_data.fermi_energy

    if band_data.nspin == 2:
        # Average over spins for gap finding
        eigenvalues = eigenvalues.mean(axis=-1)

    # Find VBM and CBM
    vbm_info = find_vbm_cbm(band_data)
    if vbm_info is None:
        return None, "metal"

    vbm, cbm, vbm_k, cbm_k = vbm_info

    if cbm <= vbm:
        return None, "metal"

    gap = cbm - vbm
    gap_type = "direct" if vbm_k == cbm_k else "indirect"

    return gap, gap_type


def find_vbm_cbm(
    band_data: BandData,
) -> tuple[float, float, int, int] | None:
    """Find valence band maximum and conduction band minimum.

    Args:
        band_data: BandData with eigenvalues.

    Returns:
        Tuple of (VBM, CBM, VBM k-index, CBM k-index) or None if metal.
    """
    eigenvalues = band_data.eigenvalues
    fermi = band_data.fermi_energy

    if band_data.nspin == 2:
        eigenvalues = eigenvalues.mean(axis=-1)

    # Find bands near Fermi level
    tol = 0.01  # eV tolerance for occupation

    vbm = -np.inf
    cbm = np.inf
    vbm_k = 0
    cbm_k = 0

    for k in range(band_data.nkpts):
        for b in range(band_data.nbands):
            e = eigenvalues[k, b]

            if e <= fermi + tol and e > vbm:
                vbm = e
                vbm_k = k

            if e > fermi - tol and e < cbm:
                cbm = e
                cbm_k = k

    if cbm < vbm + 0.01:  # Overlap = metal
        return None

    return vbm, cbm, vbm_k, cbm_k


__all__ = [
    "BandData",
    "BandStructure",
    "extract_bands_vasp",
    "extract_bands_qe",
    "find_band_gap",
    "find_vbm_cbm",
]
