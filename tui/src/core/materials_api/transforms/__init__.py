"""Transform utilities for converting between structure formats.

This package provides converters for transforming pymatgen Structure objects
to various computational chemistry input formats.

Modules:
    crystal_d12: Convert pymatgen Structure to CRYSTAL23 .d12 format

Example:
    >>> from pymatgen.core import Structure
    >>> from core.materials_api.transforms import CrystalD12Generator
    >>>
    >>> structure = Structure.from_file("POSCAR")
    >>> d12 = CrystalD12Generator.generate_full_input(
    ...     structure,
    ...     title="My calculation",
    ...     functional="PBE",
    ... )
"""
from __future__ import annotations

from .crystal_d12 import (
    BasisSetConfig,
    CrystalD12Generator,
    CrystalSystem,
    HamiltonianConfig,
    OptimizationConfig,
)

__all__ = [
    "BasisSetConfig",
    "CrystalD12Generator",
    "CrystalSystem",
    "HamiltonianConfig",
    "OptimizationConfig",
]
