"""
Structure converters for multi-code workflow interoperability.

This module provides bidirectional converters between:
    - AiiDA StructureData ↔ pymatgen Structure
    - AiiDA StructureData ↔ CRYSTAL23 .d12 geometry block
    - AiiDA StructureData ↔ VASP POSCAR format

These converters enable seamless structure transfer between DFT codes
in multi-code workflows (e.g., CRYSTAL → VASP → CRYSTAL).

Note:
    Requires numpy and aiida-core. Install with: pip install crystal-tui[aiida]
"""

# Lazy import to allow module to be referenced without crashing
# when dependencies are not installed
_CONVERTERS_AVAILABLE = False
_IMPORT_ERROR = None

try:
    from .structure import (
        crystal_d12_to_structure,
        poscar_to_structure,
        pymatgen_to_structure,
        structure_to_crystal_d12,
        structure_to_poscar,
        structure_to_pymatgen,
    )

    _CONVERTERS_AVAILABLE = True
except ImportError as e:
    _IMPORT_ERROR = str(e)

    # Define stubs that raise on use
    def _raise_import_error(*args, **kwargs):
        raise ImportError(
            f"Structure converters require numpy and aiida. "
            f"Install with: pip install crystal-tui[aiida]\n"
            f"Original error: {_IMPORT_ERROR}"
        )

    crystal_d12_to_structure = _raise_import_error
    poscar_to_structure = _raise_import_error
    pymatgen_to_structure = _raise_import_error
    structure_to_crystal_d12 = _raise_import_error
    structure_to_poscar = _raise_import_error
    structure_to_pymatgen = _raise_import_error


__all__ = [
    "pymatgen_to_structure",
    "structure_to_pymatgen",
    "crystal_d12_to_structure",
    "structure_to_crystal_d12",
    "poscar_to_structure",
    "structure_to_poscar",
    "_CONVERTERS_AVAILABLE",
]
