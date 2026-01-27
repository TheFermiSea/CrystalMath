"""
Optical properties extraction and analysis.

Supports extraction from:
- VASP (OUTCAR, vasprun.xml for dielectric function)
- YAMBO (o-*.eps*, absorption spectra)
- Quantum ESPRESSO (epsilon.dat from turbo_lanczos)
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class DielectricFunction:
    """Complex dielectric function data."""

    energy: np.ndarray  # eV
    eps_real: np.ndarray  # Real part (xx, yy, zz or averaged)
    eps_imag: np.ndarray  # Imaginary part

    # Tensor components (optional)
    eps_xx: np.ndarray | None = None
    eps_yy: np.ndarray | None = None
    eps_zz: np.ndarray | None = None
    eps_xy: np.ndarray | None = None
    eps_xz: np.ndarray | None = None
    eps_yz: np.ndarray | None = None

    # Metadata
    is_tensor: bool = False
    calculation_level: str = "DFT"  # DFT, GW, BSE


@dataclass
class OpticalData:
    """Complete optical properties data."""

    dielectric: DielectricFunction

    # Derived quantities
    absorption: np.ndarray | None = None  # cm^-1
    reflectivity: np.ndarray | None = None  # 0-1
    refractive_index: np.ndarray | None = None  # n
    extinction_coeff: np.ndarray | None = None  # k
    conductivity: np.ndarray | None = None  # S/cm

    # Key properties
    optical_gap: float | None = None  # eV
    static_dielectric: float | None = None  # epsilon(0)

    # Metadata
    source: str = "unknown"  # vasp, yambo, qe


def extract_optics_vasp(
    outcar_path: Path | None = None,
    vasprun_path: Path | None = None,
    work_dir: Path | None = None,
) -> OpticalData:
    """Extract optical properties from VASP output.

    Args:
        outcar_path: Path to OUTCAR file.
        vasprun_path: Path to vasprun.xml file.
        work_dir: Working directory to search for files.

    Returns:
        OpticalData with extracted properties.
    """
    if work_dir:
        outcar_path = outcar_path or (work_dir / "OUTCAR")
        vasprun_path = vasprun_path or (work_dir / "vasprun.xml")

    # Try vasprun.xml first
    if vasprun_path and vasprun_path.exists():
        dielectric = _parse_vasprun_optics(vasprun_path)
    elif outcar_path and outcar_path.exists():
        dielectric = _parse_outcar_optics(outcar_path)
    else:
        raise FileNotFoundError("No VASP optics files found")

    # Calculate derived quantities
    absorption = calculate_absorption(dielectric)
    reflectivity = calculate_reflectivity(dielectric)

    # Find optical gap
    optical_gap = _find_optical_gap(dielectric)

    # Static dielectric constant
    static = dielectric.eps_real[0] if len(dielectric.eps_real) > 0 else None

    return OpticalData(
        dielectric=dielectric,
        absorption=absorption,
        reflectivity=reflectivity,
        optical_gap=optical_gap,
        static_dielectric=static,
        source="vasp",
    )


def _parse_vasprun_optics(vasprun_path: Path) -> DielectricFunction:
    """Parse dielectric function from vasprun.xml."""
    tree = ET.parse(vasprun_path)
    root = tree.getroot()

    # Find dielectric function data
    dielectric_elem = root.find(".//dielectricfunction")

    if dielectric_elem is None:
        raise ValueError("No dielectric function found in vasprun.xml")

    # Parse real part
    real_elem = dielectric_elem.find(".//imag/array/set")
    imag_elem = dielectric_elem.find(".//real/array/set")

    energies = []
    eps_real_data = []
    eps_imag_data = []

    # Parse imaginary part (contains energy grid)
    if imag_elem is not None:
        for r in imag_elem.findall("r"):
            values = [float(x) for x in r.text.split()]
            energies.append(values[0])
            eps_imag_data.append(values[1:])  # xx, yy, zz, xy, yz, zx

    # Parse real part
    if real_elem is not None:
        for r in real_elem.findall("r"):
            values = [float(x) for x in r.text.split()]
            eps_real_data.append(values[1:])

    energy = np.array(energies)
    eps_imag_data = np.array(eps_imag_data)
    eps_real_data = np.array(eps_real_data)

    # Average diagonal components for isotropic approximation
    eps_real = (eps_real_data[:, 0] + eps_real_data[:, 1] + eps_real_data[:, 2]) / 3
    eps_imag = (eps_imag_data[:, 0] + eps_imag_data[:, 1] + eps_imag_data[:, 2]) / 3

    return DielectricFunction(
        energy=energy,
        eps_real=eps_real,
        eps_imag=eps_imag,
        eps_xx=eps_real_data[:, 0] + 1j * eps_imag_data[:, 0],
        eps_yy=eps_real_data[:, 1] + 1j * eps_imag_data[:, 1],
        eps_zz=eps_real_data[:, 2] + 1j * eps_imag_data[:, 2],
        is_tensor=True,
        calculation_level="DFT",
    )


def _parse_outcar_optics(outcar_path: Path) -> DielectricFunction:
    """Parse dielectric function from OUTCAR."""
    with open(outcar_path) as f:
        content = f.read()

    # Find IMAGINARY DIELECTRIC FUNCTION section
    energies = []
    eps_imag = []
    eps_real = []

    # Parse imaginary part
    imag_match = re.search(
        r"IMAGINARY DIELECTRIC FUNCTION.*?energy.*?\n(.*?)(?=\n\s*\n|\Z)",
        content,
        re.DOTALL,
    )

    if imag_match:
        for line in imag_match.group(1).strip().split("\n"):
            values = [float(x) for x in line.split()]
            if len(values) >= 4:
                energies.append(values[0])
                # Average xx, yy, zz
                eps_imag.append((values[1] + values[2] + values[3]) / 3)

    # Parse real part
    real_match = re.search(
        r"REAL DIELECTRIC FUNCTION.*?energy.*?\n(.*?)(?=\n\s*\n|\Z)",
        content,
        re.DOTALL,
    )

    if real_match:
        for line in real_match.group(1).strip().split("\n"):
            values = [float(x) for x in line.split()]
            if len(values) >= 4:
                eps_real.append((values[1] + values[2] + values[3]) / 3)

    return DielectricFunction(
        energy=np.array(energies),
        eps_real=np.array(eps_real),
        eps_imag=np.array(eps_imag),
        calculation_level="DFT",
    )


def extract_optics_yambo(
    eps_file: Path | None = None,
    alpha_file: Path | None = None,
    work_dir: Path | None = None,
) -> OpticalData:
    """Extract optical properties from YAMBO output.

    Args:
        eps_file: Path to o-*.eps* file.
        alpha_file: Path to o-*.alpha* file.
        work_dir: Working directory to search for files.

    Returns:
        OpticalData with extracted properties.
    """
    if work_dir:
        eps_files = list(work_dir.glob("o-*.eps*"))
        alpha_files = list(work_dir.glob("o-*.alpha*"))

        if eps_files:
            eps_file = eps_files[0]
        if alpha_files:
            alpha_file = alpha_files[0]

    dielectric = None
    absorption = None

    # Parse dielectric function
    if eps_file and eps_file.exists():
        dielectric = _parse_yambo_eps(eps_file)

    # Parse absorption
    if alpha_file and alpha_file.exists():
        energy, alpha = _parse_yambo_alpha(alpha_file)
        absorption = alpha

    if dielectric is None:
        raise FileNotFoundError("No YAMBO optical output found")

    # Determine calculation level from filename
    calc_level = "DFT"
    if eps_file:
        name = eps_file.name.lower()
        if "bse" in name:
            calc_level = "BSE"
        elif "gw" in name:
            calc_level = "GW"

    dielectric.calculation_level = calc_level

    return OpticalData(
        dielectric=dielectric,
        absorption=absorption,
        optical_gap=_find_optical_gap(dielectric),
        source="yambo",
    )


def _parse_yambo_eps(eps_file: Path) -> DielectricFunction:
    """Parse dielectric function from YAMBO eps file."""
    energies = []
    eps_real = []
    eps_imag = []

    with open(eps_file) as f:
        for line in f:
            if line.startswith("#"):
                continue
            values = [float(x) for x in line.split()]
            if len(values) >= 3:
                energies.append(values[0])
                eps_real.append(values[1])
                eps_imag.append(values[2])

    return DielectricFunction(
        energy=np.array(energies),
        eps_real=np.array(eps_real),
        eps_imag=np.array(eps_imag),
    )


def _parse_yambo_alpha(alpha_file: Path) -> tuple[np.ndarray, np.ndarray]:
    """Parse absorption coefficient from YAMBO alpha file."""
    energies = []
    alpha = []

    with open(alpha_file) as f:
        for line in f:
            if line.startswith("#"):
                continue
            values = [float(x) for x in line.split()]
            if len(values) >= 2:
                energies.append(values[0])
                alpha.append(values[1])

    return np.array(energies), np.array(alpha)


def _find_optical_gap(dielectric: DielectricFunction) -> float | None:
    """Find optical gap from onset of absorption."""
    eps_imag = dielectric.eps_imag
    energy = dielectric.energy

    # Find first energy where eps_imag exceeds threshold
    threshold = 0.01 * np.max(eps_imag)

    for i, (e, eps) in enumerate(zip(energy, eps_imag, strict=False)):
        if eps > threshold:
            # Interpolate for more precise value
            if i > 0:
                e_gap = energy[i - 1] + (threshold - eps_imag[i - 1]) * (
                    energy[i] - energy[i - 1]
                ) / (eps_imag[i] - eps_imag[i - 1])
                return float(e_gap)
            return float(e)

    return None


def calculate_absorption(dielectric: DielectricFunction) -> np.ndarray:
    """Calculate absorption coefficient from dielectric function.

    alpha = (2 * omega / c) * k
    where k = Im(sqrt(eps))

    Args:
        dielectric: DielectricFunction data.

    Returns:
        Absorption coefficient in cm^-1.
    """
    energy = dielectric.energy
    eps = dielectric.eps_real + 1j * dielectric.eps_imag

    # Refractive index: n + ik = sqrt(eps)
    sqrt_eps = np.sqrt(eps)
    k = np.imag(sqrt_eps)

    # alpha = 2 * omega * k / c
    # omega = E / hbar, c = 3e10 cm/s, hbar = 6.582e-16 eV*s
    # alpha (cm^-1) = 2 * E * k / (hbar * c)
    hbar_c = 1.97327e-5  # eV*cm

    alpha = 2 * energy * k / hbar_c

    return alpha


def calculate_reflectivity(dielectric: DielectricFunction) -> np.ndarray:
    """Calculate normal-incidence reflectivity.

    R = |n - 1|^2 / |n + 1|^2
    where n = sqrt(eps)

    Args:
        dielectric: DielectricFunction data.

    Returns:
        Reflectivity (0 to 1).
    """
    eps = dielectric.eps_real + 1j * dielectric.eps_imag
    n = np.sqrt(eps)

    R = np.abs((n - 1) / (n + 1)) ** 2

    return np.real(R)


__all__ = [
    "DielectricFunction",
    "OpticalData",
    "extract_optics_vasp",
    "extract_optics_yambo",
    "calculate_absorption",
    "calculate_reflectivity",
]
