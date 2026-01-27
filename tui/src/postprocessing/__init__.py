"""
Post-processing module for DFT calculation analysis.

This module provides unified interfaces for extracting and analyzing
results from various DFT codes (VASP, QE, CRYSTAL, YAMBO).

Supported analyses:
- Band structure extraction and plotting
- Density of states (DOS) analysis
- Phonon properties and thermodynamics
- Optical properties (dielectric function, absorption)
- Born effective charges and polarization
"""

from .bands import (
    BandData,
    BandStructure,
    extract_bands_qe,
    extract_bands_vasp,
    find_band_gap,
    find_vbm_cbm,
)
from .born_charges import (
    BornCharges,
    calculate_polarization,
    extract_born_charges_qe,
    extract_born_charges_vasp,
)
from .dos import (
    DOSData,
    ProjectedDOS,
    extract_dos_qe,
    extract_dos_vasp,
    integrate_dos,
)
from .optics import (
    DielectricFunction,
    OpticalData,
    calculate_absorption,
    calculate_reflectivity,
    extract_optics_vasp,
    extract_optics_yambo,
)
from .phonons import (
    PhononData,
    ThermalProperties,
    calculate_zpe,
    check_stability,
    extract_phonons_phonopy,
)

__all__ = [
    # Band structure
    "BandStructure",
    "BandData",
    "extract_bands_vasp",
    "extract_bands_qe",
    "find_band_gap",
    "find_vbm_cbm",
    # DOS
    "DOSData",
    "ProjectedDOS",
    "extract_dos_vasp",
    "extract_dos_qe",
    "integrate_dos",
    # Phonons
    "PhononData",
    "ThermalProperties",
    "extract_phonons_phonopy",
    "check_stability",
    "calculate_zpe",
    # Optics
    "OpticalData",
    "DielectricFunction",
    "extract_optics_vasp",
    "extract_optics_yambo",
    "calculate_absorption",
    "calculate_reflectivity",
    # Born charges
    "BornCharges",
    "extract_born_charges_vasp",
    "extract_born_charges_qe",
    "calculate_polarization",
]
