"""
Phonon properties extraction and analysis.

Supports extraction from:
- Phonopy (band.yaml, mesh.yaml, thermal_properties.yaml)
- VASP DFPT (OUTCAR)
- Quantum ESPRESSO (matdyn output)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class PhononData:
    """Phonon band structure and DOS data."""

    # Band structure
    qpoints: np.ndarray | None = None  # Shape: (nqpts, 3)
    qpoint_distances: np.ndarray | None = None
    frequencies: np.ndarray | None = None  # Shape: (nqpts, nmodes), THz
    qpoint_labels: list[str] = field(default_factory=list)
    label_positions: list[float] = field(default_factory=list)

    # DOS
    dos_frequencies: np.ndarray | None = None  # THz
    dos_total: np.ndarray | None = None
    dos_partial: dict[str, np.ndarray] | None = None  # Per-element DOS

    # Stability
    has_imaginary: bool = False
    min_frequency: float = 0.0  # THz
    imaginary_modes: list[tuple[int, int]] = field(default_factory=list)  # (qpt, mode)

    # Metadata
    nqpts: int = 0
    nmodes: int = 0
    natoms: int = 0


@dataclass
class ThermalProperties:
    """Thermodynamic properties from phonons."""

    temperature: np.ndarray  # K
    free_energy: np.ndarray  # kJ/mol
    entropy: np.ndarray  # J/K/mol
    heat_capacity: np.ndarray  # J/K/mol

    # Zero-point energy
    zpe: float = 0.0  # kJ/mol

    # At specific temperatures
    properties_at_300K: dict[str, float] | None = None


def extract_phonons_phonopy(
    band_yaml: Path | None = None,
    mesh_yaml: Path | None = None,
    thermal_yaml: Path | None = None,
    work_dir: Path | None = None,
) -> tuple[PhononData, ThermalProperties | None]:
    """Extract phonon data from phonopy output files.

    Args:
        band_yaml: Path to band.yaml file.
        mesh_yaml: Path to mesh.yaml file.
        thermal_yaml: Path to thermal_properties.yaml file.
        work_dir: Working directory to search for files.

    Returns:
        Tuple of (PhononData, ThermalProperties or None).
    """
    if work_dir:
        band_yaml = band_yaml or (work_dir / "band.yaml")
        mesh_yaml = mesh_yaml or (work_dir / "mesh.yaml")
        thermal_yaml = thermal_yaml or (work_dir / "thermal_properties.yaml")

    phonon_data = PhononData()

    # Parse band structure
    if band_yaml and band_yaml.exists():
        _parse_band_yaml(band_yaml, phonon_data)

    # Parse DOS
    if mesh_yaml and mesh_yaml.exists():
        _parse_mesh_yaml(mesh_yaml, phonon_data)

    # Parse thermal properties
    thermal = None
    if thermal_yaml and thermal_yaml.exists():
        thermal = _parse_thermal_yaml(thermal_yaml)

    return phonon_data, thermal


def _parse_band_yaml(band_yaml: Path, phonon_data: PhononData) -> None:
    """Parse phonon band structure from band.yaml."""
    with open(band_yaml) as f:
        content = f.read()

    # Extract q-points and frequencies
    # Phonopy YAML format uses specific structure
    qpoints = []
    frequencies = []
    current_qpt = None
    current_freqs = []

    for line in content.split("\n"):
        line = line.strip()

        # Q-point position
        if line.startswith("q-position:"):
            if current_qpt is not None and current_freqs:
                qpoints.append(current_qpt)
                frequencies.append(current_freqs)
            # Parse q-point
            match = re.search(r"\[\s*([-\d.]+),\s*([-\d.]+),\s*([-\d.]+)\s*\]", line)
            if match:
                current_qpt = [float(match.group(i)) for i in (1, 2, 3)]
            current_freqs = []

        # Frequency
        elif line.startswith("frequency:"):
            match = re.search(r"frequency:\s*([-\d.]+)", line)
            if match:
                current_freqs.append(float(match.group(1)))

        # Labels
        elif line.startswith("label:"):
            match = re.search(r"label:\s*'?([^']+)'?", line)
            if match:
                phonon_data.qpoint_labels.append(match.group(1).strip())

    # Add last q-point
    if current_qpt is not None and current_freqs:
        qpoints.append(current_qpt)
        frequencies.append(current_freqs)

    if qpoints:
        phonon_data.qpoints = np.array(qpoints)
        phonon_data.frequencies = np.array(frequencies)
        phonon_data.nqpts = len(qpoints)
        phonon_data.nmodes = len(frequencies[0]) if frequencies else 0

        # Calculate q-point distances
        phonon_data.qpoint_distances = _calculate_qpoint_distances(phonon_data.qpoints)

        # Check for imaginary frequencies
        min_freq = phonon_data.frequencies.min()
        phonon_data.min_frequency = min_freq
        phonon_data.has_imaginary = min_freq < -0.01  # THz threshold

        if phonon_data.has_imaginary:
            # Find imaginary modes
            for q in range(phonon_data.nqpts):
                for m in range(phonon_data.nmodes):
                    if phonon_data.frequencies[q, m] < -0.01:
                        phonon_data.imaginary_modes.append((q, m))


def _parse_mesh_yaml(mesh_yaml: Path, phonon_data: PhononData) -> None:
    """Parse phonon DOS from mesh.yaml."""
    with open(mesh_yaml) as f:
        content = f.read()

    # Extract DOS data
    # mesh.yaml contains partial DOS information
    # Simplified parsing - full implementation would parse YAML properly

    frequencies = []
    dos_values = []

    in_dos = False
    for line in content.split("\n"):
        if "total_dos:" in line:
            in_dos = True
            continue

        if in_dos:
            if line.strip().startswith("-"):
                # Parse frequency and DOS
                match = re.search(r"\[\s*([-\d.]+),\s*([-\d.]+)\s*\]", line)
                if match:
                    frequencies.append(float(match.group(1)))
                    dos_values.append(float(match.group(2)))
            elif not line.strip().startswith("-") and line.strip():
                in_dos = False

    if frequencies:
        phonon_data.dos_frequencies = np.array(frequencies)
        phonon_data.dos_total = np.array(dos_values)


def _parse_thermal_yaml(thermal_yaml: Path) -> ThermalProperties:
    """Parse thermal properties from thermal_properties.yaml."""
    with open(thermal_yaml) as f:
        content = f.read()

    temperatures = []
    free_energies = []
    entropies = []
    heat_capacities = []

    current_temp = None

    for line in content.split("\n"):
        line = line.strip()

        if line.startswith("temperature:"):
            match = re.search(r"temperature:\s*([\d.]+)", line)
            if match:
                current_temp = float(match.group(1))
                temperatures.append(current_temp)

        elif line.startswith("free_energy:") and current_temp is not None:
            match = re.search(r"free_energy:\s*([-\d.]+)", line)
            if match:
                free_energies.append(float(match.group(1)))

        elif line.startswith("entropy:") and current_temp is not None:
            match = re.search(r"entropy:\s*([\d.]+)", line)
            if match:
                entropies.append(float(match.group(1)))

        elif line.startswith("heat_capacity:") and current_temp is not None:
            match = re.search(r"heat_capacity:\s*([\d.]+)", line)
            if match:
                heat_capacities.append(float(match.group(1)))

    # Calculate ZPE (T=0 free energy)
    zpe = free_energies[0] if free_energies else 0.0

    # Properties at 300K
    props_300K = None
    for i, t in enumerate(temperatures):
        if abs(t - 300.0) < 1.0:
            props_300K = {
                "temperature": t,
                "free_energy": free_energies[i] if i < len(free_energies) else 0,
                "entropy": entropies[i] if i < len(entropies) else 0,
                "heat_capacity": heat_capacities[i] if i < len(heat_capacities) else 0,
            }
            break

    return ThermalProperties(
        temperature=np.array(temperatures),
        free_energy=np.array(free_energies),
        entropy=np.array(entropies),
        heat_capacity=np.array(heat_capacities),
        zpe=zpe,
        properties_at_300K=props_300K,
    )


def _calculate_qpoint_distances(qpoints: np.ndarray) -> np.ndarray:
    """Calculate cumulative distances along q-point path."""
    distances = [0.0]
    for i in range(1, len(qpoints)):
        dq = np.linalg.norm(qpoints[i] - qpoints[i - 1])
        distances.append(distances[-1] + dq)
    return np.array(distances)


def check_stability(phonon_data: PhononData, threshold: float = -0.01) -> dict[str, Any]:
    """Check phonon stability of a structure.

    Args:
        phonon_data: PhononData with frequencies.
        threshold: Threshold for imaginary frequencies (THz).

    Returns:
        Dictionary with stability analysis.
    """
    result = {
        "is_stable": not phonon_data.has_imaginary,
        "min_frequency_THz": phonon_data.min_frequency,
        "min_frequency_cm-1": phonon_data.min_frequency * 33.356,  # THz to cm^-1
        "num_imaginary_modes": len(phonon_data.imaginary_modes),
        "imaginary_modes": phonon_data.imaginary_modes,
    }

    if phonon_data.has_imaginary:
        result["recommendation"] = (
            "Structure has imaginary phonon modes indicating dynamical instability. "
            "Consider: (1) Re-relaxing with tighter convergence, "
            "(2) Checking for symmetry breaking, "
            "(3) Using a different exchange-correlation functional."
        )
    else:
        result["recommendation"] = "Structure is dynamically stable."

    return result


def calculate_zpe(phonon_data: PhononData) -> float:
    """Calculate zero-point energy from phonon frequencies.

    ZPE = (1/2) * hbar * sum(omega)

    Args:
        phonon_data: PhononData with frequencies at Gamma.

    Returns:
        Zero-point energy in eV.
    """
    if phonon_data.frequencies is None:
        return 0.0

    # Get frequencies at Gamma point (q=0)
    gamma_idx = 0
    for i, q in enumerate(phonon_data.qpoints):
        if np.allclose(q, [0, 0, 0]):
            gamma_idx = i
            break

    freqs_THz = phonon_data.frequencies[gamma_idx]

    # Remove acoustic modes (lowest 3 frequencies near 0)
    freqs_THz = np.sort(freqs_THz)[3:]

    # Remove imaginary frequencies
    freqs_THz = freqs_THz[freqs_THz > 0]

    # Convert THz to eV: E = hbar * omega
    # hbar = 6.582e-16 eV*s, 1 THz = 1e12 Hz
    hbar_eV_s = 6.582119569e-16
    freqs_Hz = freqs_THz * 1e12

    zpe = 0.5 * hbar_eV_s * np.sum(freqs_Hz)

    return zpe


__all__ = [
    "PhononData",
    "ThermalProperties",
    "extract_phonons_phonopy",
    "check_stability",
    "calculate_zpe",
]
