"""VASP input file generation utilities.

This module provides tools for generating complete VASP input files
(POSCAR, INCAR, KPOINTS) from pymatgen structures.

Example:
    >>> from pymatgen.core import Structure
    >>> from crystalmath.vasp import VaspInputGenerator, IncarPreset
    >>>
    >>> structure = Structure.from_file("POSCAR")
    >>> generator = VaspInputGenerator(structure, preset=IncarPreset.RELAX)
    >>> inputs = generator.generate()
    >>> print(inputs.incar)
"""

from .incar import IncarBuilder, IncarPreset
from .kpoints import KpointsBuilder, KpointsMesh
from .generator import VaspInputGenerator, VaspInputs

__all__ = [
    "IncarBuilder",
    "IncarPreset",
    "KpointsBuilder",
    "KpointsMesh",
    "VaspInputGenerator",
    "VaspInputs",
]
