"""
Pymatgen Integration Bridge for CrystalMath.

This module provides structure conversion and analysis functions that bridge
pymatgen's Structure objects with CrystalMath's workflow system. It serves as
the central hub for structure handling across different DFT codes and databases.

Supported Data Sources:
-----------------------
- **Local files**: CIF, POSCAR, and other structure file formats
- **Materials Project**: Structures from the MP database (requires API key)
- **Crystallography Open Database (COD)**: Open-access crystal structures
- **AiiDA**: Integration with AiiDA StructureData nodes
- **ASE**: Integration with ASE Atoms objects

Key Features:
-------------
1. **Structure Loading**: Load structures from various sources with unified API
2. **Format Conversion**: Seamless conversion between pymatgen, AiiDA, and ASE
3. **Symmetry Analysis**: Space group detection, point group analysis
4. **DFT Validation**: Pre-calculation structure validation

Design Notes:
-------------
- Uses TYPE_CHECKING for optional imports to minimize dependencies
- Raises descriptive ImportError when optional deps are missing
- All functions work with pymatgen Structure as the central type
- Follows patterns from crystalmath.protocols

Example Usage:
--------------
>>> from crystalmath.integrations.pymatgen_bridge import (
...     structure_from_cif,
...     get_symmetry_info,
...     validate_for_dft,
... )
>>>
>>> # Load and analyze structure
>>> structure = structure_from_cif("NaCl.cif")
>>> sym_info = get_symmetry_info(structure)
>>> print(f"Space group: {sym_info.space_group_symbol}")
>>>
>>> # Validate for DFT
>>> is_valid, issues = validate_for_dft(structure)

See Also:
---------
- crystalmath.protocols.StructureProvider - Protocol interface
- crystalmath.integrations.atomate2_bridge - atomate2 workflow integration
- tui/src/aiida/converters/structure.py - AiiDA conversion utilities
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

if TYPE_CHECKING:
    from aiida.orm import StructureData
    from ase import Atoms
    from pymatgen.core import Structure

# Configure module logger
logger = logging.getLogger(__name__)


# =============================================================================
# Exceptions
# =============================================================================


class PymatgenBridgeError(Exception):
    """Base exception for pymatgen bridge operations."""

    pass


class StructureLoadError(PymatgenBridgeError):
    """Raised when structure loading fails."""

    pass


class StructureConversionError(PymatgenBridgeError):
    """Raised when structure conversion fails."""

    pass


class ValidationError(PymatgenBridgeError):
    """Raised when structure validation fails."""

    pass


class DependencyError(PymatgenBridgeError):
    """Raised when a required dependency is not available."""

    pass


# =============================================================================
# Enums
# =============================================================================


class CrystalSystem(str, Enum):
    """Crystal system classification."""

    TRICLINIC = "triclinic"
    MONOCLINIC = "monoclinic"
    ORTHORHOMBIC = "orthorhombic"
    TETRAGONAL = "tetragonal"
    TRIGONAL = "trigonal"
    HEXAGONAL = "hexagonal"
    CUBIC = "cubic"


class Dimensionality(int, Enum):
    """Structure dimensionality classification."""

    MOLECULE = 0  # 0D - isolated molecule
    POLYMER = 1  # 1D - chain/polymer
    SLAB = 2  # 2D - layered/surface
    BULK = 3  # 3D - bulk crystal


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class SymmetryInfo:
    """
    Symmetry information for a crystal structure.

    Contains space group, point group, and crystal system information
    extracted from symmetry analysis.

    Attributes:
        space_group_number: International space group number (1-230)
        space_group_symbol: Hermann-Mauguin symbol (e.g., "Fm-3m")
        point_group: Point group symbol (e.g., "m-3m")
        crystal_system: Crystal system classification
        hall_symbol: Hall symbol for the space group
        is_centrosymmetric: Whether the structure has inversion symmetry
        wyckoff_symbols: List of Wyckoff position symbols for each site
        symmetry_operations: Number of symmetry operations
        tolerance: Symmetry detection tolerance used (Angstroms)
    """

    space_group_number: int
    space_group_symbol: str
    point_group: str
    crystal_system: CrystalSystem
    hall_symbol: str = ""
    is_centrosymmetric: bool = False
    wyckoff_symbols: List[str] = field(default_factory=list)
    symmetry_operations: int = 0
    tolerance: float = 0.01

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "space_group_number": self.space_group_number,
            "space_group_symbol": self.space_group_symbol,
            "point_group": self.point_group,
            "crystal_system": self.crystal_system.value,
            "hall_symbol": self.hall_symbol,
            "is_centrosymmetric": self.is_centrosymmetric,
            "wyckoff_symbols": self.wyckoff_symbols,
            "symmetry_operations": self.symmetry_operations,
            "tolerance": self.tolerance,
        }


@dataclass
class StructureMetadata:
    """
    Metadata associated with a loaded structure.

    Attributes:
        source: Origin of the structure (e.g., "cif", "mp", "cod")
        source_id: Identifier at the source (e.g., MP ID, COD ID)
        formula: Chemical formula
        reduced_formula: Reduced chemical formula
        num_sites: Number of atomic sites
        volume: Unit cell volume in Angstrom^3
        density: Density in g/cm^3
        is_ordered: Whether all sites are fully occupied
    """

    source: str
    source_id: Optional[str] = None
    formula: str = ""
    reduced_formula: str = ""
    num_sites: int = 0
    volume: float = 0.0
    density: float = 0.0
    is_ordered: bool = True


# =============================================================================
# Dependency Checking Utilities
# =============================================================================


def _check_pymatgen() -> None:
    """Check if pymatgen is available."""
    try:
        import pymatgen  # noqa: F401
    except ImportError:
        raise DependencyError(
            "pymatgen is required for structure operations. "
            "Install with: pip install pymatgen"
        )


def _check_aiida() -> None:
    """Check if aiida-core is available."""
    try:
        import aiida  # noqa: F401
    except ImportError:
        raise DependencyError(
            "aiida-core is required for AiiDA structure conversion. "
            "Install with: pip install aiida-core"
        )


def _check_ase() -> None:
    """Check if ASE is available."""
    try:
        import ase  # noqa: F401
    except ImportError:
        raise DependencyError(
            "ASE is required for ASE Atoms conversion. "
            "Install with: pip install ase"
        )


def _check_mp_api() -> None:
    """Check if mp-api is available."""
    try:
        from mp_api.client import MPRester  # noqa: F401
    except ImportError:
        raise DependencyError(
            "mp-api is required for Materials Project access. "
            "Install with: pip install mp-api"
        )


# =============================================================================
# Structure Loading Functions
# =============================================================================


def structure_from_cif(path: Union[str, Path]) -> "Structure":
    """
    Load a structure from a CIF file.

    Args:
        path: Path to the CIF file.

    Returns:
        pymatgen Structure object.

    Raises:
        StructureLoadError: If the file cannot be read or parsed.
        DependencyError: If pymatgen is not available.

    Example:
        >>> structure = structure_from_cif("NaCl.cif")
        >>> print(structure.formula)
        'Na1 Cl1'
    """
    _check_pymatgen()
    from pymatgen.core import Structure

    path = Path(path)
    if not path.exists():
        raise StructureLoadError(f"CIF file not found: {path}")

    try:
        structure = Structure.from_file(str(path))
        logger.info(f"Loaded structure from CIF: {path.name}")
        return structure
    except Exception as e:
        raise StructureLoadError(f"Failed to parse CIF file {path}: {e}") from e


def structure_from_poscar(path: Union[str, Path]) -> "Structure":
    """
    Load a structure from a VASP POSCAR/CONTCAR file.

    Args:
        path: Path to the POSCAR file.

    Returns:
        pymatgen Structure object.

    Raises:
        StructureLoadError: If the file cannot be read or parsed.
        DependencyError: If pymatgen is not available.

    Example:
        >>> structure = structure_from_poscar("POSCAR")
        >>> print(structure.num_sites)
        8
    """
    _check_pymatgen()
    from pymatgen.core import Structure
    from pymatgen.io.vasp import Poscar

    path = Path(path)
    if not path.exists():
        raise StructureLoadError(f"POSCAR file not found: {path}")

    try:
        poscar = Poscar.from_file(str(path))
        structure = poscar.structure
        logger.info(f"Loaded structure from POSCAR: {path.name}")
        return structure
    except Exception as e:
        raise StructureLoadError(f"Failed to parse POSCAR file {path}: {e}") from e


def structure_to_poscar(structure: "Structure", comment: Optional[str] = None) -> str:
    """
    Convert a pymatgen Structure to VASP POSCAR format.

    Args:
        structure: pymatgen Structure object.
        comment: Optional comment line. Defaults to structure formula.

    Returns:
        POSCAR file content as string.

    Raises:
        DependencyError: If pymatgen is not available.

    Example:
        >>> structure = structure_from_mp("mp-149")
        >>> poscar_text = structure_to_poscar(structure)
        >>> print(poscar_text[:50])
        'Si2 - Generated by CrystalMath'
    """
    _check_pymatgen()
    from pymatgen.io.vasp import Poscar

    if comment is None:
        comment = f"{structure.formula} - Generated by CrystalMath"

    poscar = Poscar(structure, comment=comment)
    return poscar.get_str()


def structure_from_mp(
    mp_id: str,
    api_key: Optional[str] = None,
    conventional: bool = False,
) -> "Structure":
    """
    Load a structure from the Materials Project database.

    Args:
        mp_id: Materials Project ID (e.g., "mp-149" for Si).
        api_key: Materials Project API key. If None, uses MP_API_KEY
                 environment variable or ~/.config/.pmgrc.yaml.
        conventional: If True, return conventional unit cell instead of
                      primitive cell.

    Returns:
        pymatgen Structure object.

    Raises:
        StructureLoadError: If structure cannot be retrieved.
        DependencyError: If mp-api is not available.

    Example:
        >>> structure = structure_from_mp("mp-149")  # Silicon
        >>> print(structure.formula)
        'Si2'

    Note:
        Requires a Materials Project API key. Set via:
        - MP_API_KEY environment variable
        - ~/.config/.pmgrc.yaml file
        - api_key parameter
    """
    _check_pymatgen()
    _check_mp_api()

    from mp_api.client import MPRester

    # Normalize MP ID format
    if not mp_id.startswith("mp-"):
        mp_id = f"mp-{mp_id}"

    try:
        with MPRester(api_key) as mpr:
            # Get structure from Materials Project
            structure = mpr.get_structure_by_material_id(
                mp_id,
                conventional_unit_cell=conventional,
            )

        if structure is None:
            raise StructureLoadError(f"No structure found for {mp_id}")

        logger.info(f"Loaded structure from Materials Project: {mp_id}")
        return structure

    except Exception as e:
        raise StructureLoadError(
            f"Failed to retrieve structure {mp_id} from Materials Project: {e}"
        ) from e


def structure_from_cod(
    cod_id: int,
    timeout: float = 60.0,
) -> "Structure":
    """
    Load a structure from the Crystallography Open Database (COD).

    Args:
        cod_id: COD structure ID (7-digit number).
        timeout: Request timeout in seconds.

    Returns:
        pymatgen Structure object.

    Raises:
        StructureLoadError: If structure cannot be retrieved.
        DependencyError: If pymatgen is not available.

    Example:
        >>> structure = structure_from_cod(1000041)  # NaCl
        >>> print(structure.formula)
        'Na4 Cl4'

    Note:
        The COD is an open-access database. No API key required.
        See: https://www.crystallography.net/cod/
    """
    _check_pymatgen()
    from pymatgen.core import Structure

    import urllib.request
    import tempfile

    # COD CIF download URL
    url = f"https://www.crystallography.net/cod/{cod_id}.cif"

    try:
        # Download CIF content
        with urllib.request.urlopen(url, timeout=timeout) as response:
            cif_content = response.read().decode("utf-8")

        # Write to temporary file and parse
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cif", delete=False
        ) as tmp:
            tmp.write(cif_content)
            tmp_path = tmp.name

        structure = Structure.from_file(tmp_path)

        # Clean up temp file
        Path(tmp_path).unlink(missing_ok=True)

        logger.info(f"Loaded structure from COD: {cod_id}")
        return structure

    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise StructureLoadError(f"COD entry {cod_id} not found") from e
        raise StructureLoadError(f"HTTP error retrieving COD {cod_id}: {e}") from e
    except urllib.error.URLError as e:
        raise StructureLoadError(f"Network error retrieving COD {cod_id}: {e}") from e
    except Exception as e:
        raise StructureLoadError(f"Failed to load COD {cod_id}: {e}") from e


def structure_from_file(path: Union[str, Path]) -> "Structure":
    """
    Load a structure from any supported file format.

    Automatically detects file format based on extension:
    - .cif -> CIF format
    - POSCAR, CONTCAR -> VASP format
    - .vasp -> VASP format
    - .xyz -> XYZ format
    - .json -> pymatgen JSON

    Args:
        path: Path to the structure file.

    Returns:
        pymatgen Structure object.

    Raises:
        StructureLoadError: If format not recognized or parsing fails.
        DependencyError: If pymatgen is not available.

    Example:
        >>> structure = structure_from_file("structure.cif")
        >>> structure = structure_from_file("POSCAR")
    """
    _check_pymatgen()
    from pymatgen.core import Structure

    path = Path(path)
    if not path.exists():
        raise StructureLoadError(f"File not found: {path}")

    try:
        # pymatgen's from_file handles format detection
        structure = Structure.from_file(str(path))
        logger.info(f"Loaded structure from file: {path.name}")
        return structure
    except Exception as e:
        raise StructureLoadError(f"Failed to load structure from {path}: {e}") from e


# =============================================================================
# Structure Conversion Functions
# =============================================================================


def to_aiida_structure(structure: "Structure") -> "StructureData":
    """
    Convert pymatgen Structure to AiiDA StructureData.

    Args:
        structure: pymatgen Structure object.

    Returns:
        AiiDA StructureData node (not stored).

    Raises:
        StructureConversionError: If conversion fails.
        DependencyError: If aiida-core is not available.

    Example:
        >>> from pymatgen.core import Structure
        >>> pmg_struct = Structure.from_file("POSCAR")
        >>> aiida_struct = to_aiida_structure(pmg_struct)
        >>> aiida_struct.store()  # Persist to database
    """
    _check_pymatgen()
    _check_aiida()

    from aiida.orm import StructureData
    from pymatgen.core import Structure as PymatgenStructure

    if not isinstance(structure, PymatgenStructure):
        raise StructureConversionError(
            f"Expected pymatgen Structure, got {type(structure)}"
        )

    try:
        # Extract cell matrix (3x3 array)
        cell = structure.lattice.matrix.tolist()

        # Create AiiDA StructureData
        aiida_structure = StructureData(cell=cell)

        # Add atoms with their properties
        for site in structure:
            symbol = site.specie.symbol
            position = site.coords.tolist()
            aiida_structure.append_atom(position=position, symbols=symbol)

        # Preserve label if available
        if hasattr(structure, "properties") and structure.properties:
            label = structure.properties.get("label", "")
            if label:
                aiida_structure.label = label

        logger.debug(
            f"Converted to AiiDA StructureData: {structure.composition.reduced_formula}"
        )
        return aiida_structure

    except Exception as e:
        raise StructureConversionError(
            f"Failed to convert to AiiDA StructureData: {e}"
        ) from e


def from_aiida_structure(node: "StructureData") -> "Structure":
    """
    Convert AiiDA StructureData to pymatgen Structure.

    Args:
        node: AiiDA StructureData node.

    Returns:
        pymatgen Structure object.

    Raises:
        StructureConversionError: If conversion fails.
        DependencyError: If pymatgen or aiida-core is not available.

    Example:
        >>> from aiida.orm import load_node
        >>> aiida_struct = load_node(123)  # Load by PK
        >>> pmg_struct = from_aiida_structure(aiida_struct)
    """
    _check_pymatgen()
    _check_aiida()

    from aiida.orm import StructureData
    from pymatgen.core import Lattice, Structure

    if not isinstance(node, StructureData):
        raise StructureConversionError(
            f"Expected AiiDA StructureData, got {type(node)}"
        )

    try:
        # Extract cell matrix
        cell = node.cell

        # Create Lattice object
        lattice = Lattice(cell)

        # Extract species and coordinates
        species = []
        coords = []

        for site in node.sites:
            species.append(site.kind_name)
            coords.append(site.position)

        # Create pymatgen Structure
        pmg_structure = Structure(
            lattice=lattice,
            species=species,
            coords=coords,
            coords_are_cartesian=True,
        )

        logger.debug(
            f"Converted from AiiDA StructureData: {pmg_structure.composition.reduced_formula}"
        )
        return pmg_structure

    except Exception as e:
        raise StructureConversionError(
            f"Failed to convert from AiiDA StructureData: {e}"
        ) from e


def to_ase_atoms(structure: "Structure") -> "Atoms":
    """
    Convert pymatgen Structure to ASE Atoms object.

    Args:
        structure: pymatgen Structure object.

    Returns:
        ASE Atoms object.

    Raises:
        StructureConversionError: If conversion fails.
        DependencyError: If ASE is not available.

    Example:
        >>> structure = structure_from_cif("NaCl.cif")
        >>> atoms = to_ase_atoms(structure)
        >>> print(atoms.get_chemical_formula())
        'NaCl'
    """
    _check_pymatgen()
    _check_ase()

    from ase import Atoms
    from pymatgen.core import Structure as PymatgenStructure

    if not isinstance(structure, PymatgenStructure):
        raise StructureConversionError(
            f"Expected pymatgen Structure, got {type(structure)}"
        )

    try:
        # Use pymatgen's built-in ASE adapter if available
        try:
            from pymatgen.io.ase import AseAtomsAdaptor

            adaptor = AseAtomsAdaptor()
            atoms = adaptor.get_atoms(structure)
            logger.debug(
                f"Converted to ASE Atoms: {structure.composition.reduced_formula}"
            )
            return atoms
        except ImportError:
            pass

        # Manual conversion fallback
        symbols = [str(site.specie) for site in structure]
        positions = [site.coords for site in structure]
        cell = structure.lattice.matrix

        atoms = Atoms(
            symbols=symbols,
            positions=positions,
            cell=cell,
            pbc=True,
        )

        logger.debug(
            f"Converted to ASE Atoms (manual): {structure.composition.reduced_formula}"
        )
        return atoms

    except Exception as e:
        raise StructureConversionError(f"Failed to convert to ASE Atoms: {e}") from e


def from_ase_atoms(atoms: "Atoms") -> "Structure":
    """
    Convert ASE Atoms object to pymatgen Structure.

    Args:
        atoms: ASE Atoms object.

    Returns:
        pymatgen Structure object.

    Raises:
        StructureConversionError: If conversion fails.
        DependencyError: If ASE or pymatgen is not available.

    Example:
        >>> from ase.build import bulk
        >>> atoms = bulk("Cu", "fcc", a=3.6)
        >>> structure = from_ase_atoms(atoms)
    """
    _check_pymatgen()
    _check_ase()

    from ase import Atoms
    from pymatgen.core import Lattice, Structure

    if not isinstance(atoms, Atoms):
        raise StructureConversionError(f"Expected ASE Atoms, got {type(atoms)}")

    try:
        # Use pymatgen's built-in ASE adapter if available
        try:
            from pymatgen.io.ase import AseAtomsAdaptor

            adaptor = AseAtomsAdaptor()
            structure = adaptor.get_structure(atoms)
            logger.debug(
                f"Converted from ASE Atoms: {structure.composition.reduced_formula}"
            )
            return structure
        except ImportError:
            pass

        # Manual conversion fallback
        cell = atoms.get_cell()
        if cell is None or cell.volume < 1e-6:
            raise StructureConversionError(
                "ASE Atoms has no valid cell. Cannot convert to periodic structure."
            )

        lattice = Lattice(cell)
        species = atoms.get_chemical_symbols()
        positions = atoms.get_positions()

        structure = Structure(
            lattice=lattice,
            species=species,
            coords=positions,
            coords_are_cartesian=True,
        )

        logger.debug(
            f"Converted from ASE Atoms (manual): {structure.composition.reduced_formula}"
        )
        return structure

    except Exception as e:
        raise StructureConversionError(
            f"Failed to convert from ASE Atoms: {e}"
        ) from e


# =============================================================================
# Structure Analysis Functions
# =============================================================================


def get_symmetry_info(
    structure: "Structure",
    symprec: float = 0.01,
    angle_tolerance: float = 5.0,
) -> SymmetryInfo:
    """
    Analyze symmetry of a crystal structure.

    Uses spglib (via pymatgen) to detect space group, point group,
    and other symmetry properties.

    Args:
        structure: pymatgen Structure object.
        symprec: Symmetry precision in Angstroms (default 0.01).
        angle_tolerance: Angle tolerance in degrees (default 5.0).

    Returns:
        SymmetryInfo dataclass with symmetry properties.

    Raises:
        ValidationError: If symmetry analysis fails.
        DependencyError: If pymatgen is not available.

    Example:
        >>> structure = structure_from_mp("mp-149")
        >>> sym_info = get_symmetry_info(structure)
        >>> print(f"Space group: {sym_info.space_group_symbol}")
        Space group: Fd-3m
    """
    _check_pymatgen()

    from pymatgen.core import Structure as PymatgenStructure
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    if not isinstance(structure, PymatgenStructure):
        raise ValidationError(f"Expected pymatgen Structure, got {type(structure)}")

    try:
        # Create symmetry analyzer
        sga = SpacegroupAnalyzer(
            structure,
            symprec=symprec,
            angle_tolerance=angle_tolerance,
        )

        # Get space group info
        sg_number = sga.get_space_group_number()
        sg_symbol = sga.get_space_group_symbol()
        hall_symbol = sga.get_hall()

        # Get point group
        point_group = sga.get_point_group_symbol()

        # Get crystal system
        crystal_system_str = sga.get_crystal_system()
        try:
            crystal_system = CrystalSystem(crystal_system_str)
        except ValueError:
            crystal_system = CrystalSystem.TRICLINIC

        # Get symmetry operations
        sym_ops = sga.get_symmetry_operations()
        num_sym_ops = len(sym_ops) if sym_ops else 0

        # Check centrosymmetry
        is_centrosymmetric = sga.is_laue()

        # Get Wyckoff symbols
        symmetrized = sga.get_symmetrized_structure()
        wyckoff_symbols = []
        for eq_indices in symmetrized.equivalent_indices:
            wy = symmetrized.wyckoff_symbols[eq_indices[0]]
            wyckoff_symbols.append(wy)

        logger.debug(f"Symmetry analysis complete: {sg_symbol} ({sg_number})")

        return SymmetryInfo(
            space_group_number=sg_number,
            space_group_symbol=sg_symbol,
            point_group=point_group,
            crystal_system=crystal_system,
            hall_symbol=hall_symbol,
            is_centrosymmetric=is_centrosymmetric,
            wyckoff_symbols=wyckoff_symbols,
            symmetry_operations=num_sym_ops,
            tolerance=symprec,
        )

    except Exception as e:
        raise ValidationError(f"Symmetry analysis failed: {e}") from e


def get_dimensionality(
    structure: "Structure",
    tolerance: float = 0.45,
) -> int:
    """
    Determine the dimensionality of a structure (0D, 1D, 2D, or 3D).

    Uses bond-based connectivity analysis to determine if the structure
    is a molecule (0D), polymer (1D), layered (2D), or bulk (3D).

    Args:
        structure: pymatgen Structure object.
        tolerance: Tolerance for bond detection as fraction of sum of
                   covalent radii (default 0.45).

    Returns:
        Dimensionality as integer (0, 1, 2, or 3).

    Raises:
        ValidationError: If analysis fails.
        DependencyError: If pymatgen is not available.

    Example:
        >>> structure = structure_from_cif("graphite.cif")
        >>> dim = get_dimensionality(structure)
        >>> print(f"Dimensionality: {dim}D")
        Dimensionality: 2D
    """
    _check_pymatgen()

    from pymatgen.core import Structure as PymatgenStructure

    if not isinstance(structure, PymatgenStructure):
        raise ValidationError(f"Expected pymatgen Structure, got {type(structure)}")

    try:
        from pymatgen.analysis.dimensionality import get_dimensionality as pmg_dim

        dim = pmg_dim(structure, tolerance=tolerance)
        logger.debug(f"Dimensionality analysis: {dim}D")
        return dim

    except ImportError:
        # Fallback: simple heuristic based on cell geometry
        warnings.warn(
            "Full dimensionality analysis requires pymatgen >= 2022. "
            "Using simplified heuristic."
        )

        # Check for vacuum regions along each axis
        import numpy as np

        cell = structure.lattice.matrix
        lengths = np.linalg.norm(cell, axis=1)

        # Large cell dimension (>15 A) with few atoms suggests vacuum
        vacuum_threshold = 15.0
        min_density = 0.01  # atoms per A^3

        density = len(structure) / structure.volume
        if density < min_density:
            # Very low density - likely molecular
            return 0

        vacuum_dirs = sum(1 for l in lengths if l > vacuum_threshold)
        return 3 - vacuum_dirs

    except Exception as e:
        raise ValidationError(f"Dimensionality analysis failed: {e}") from e


def validate_for_dft(
    structure: "Structure",
    check_overlapping: bool = True,
    check_oxidation: bool = True,
    min_distance: float = 0.5,
    max_atoms: int = 500,
) -> Tuple[bool, List[str]]:
    """
    Validate a structure for DFT calculations.

    Performs several checks to ensure the structure is suitable for
    DFT calculations:
    - No overlapping atoms
    - Reasonable atomic distances
    - Reasonable number of atoms
    - Valid atomic species
    - Ordered structure (no partial occupancies)

    Args:
        structure: pymatgen Structure object.
        check_overlapping: Check for overlapping atoms.
        check_oxidation: Check for valid oxidation states (if present).
        min_distance: Minimum allowed interatomic distance in Angstroms.
        max_atoms: Maximum number of atoms allowed.

    Returns:
        Tuple of (is_valid, list_of_issues).
        is_valid is True if no critical issues found.
        list_of_issues contains warning/error messages.

    Raises:
        DependencyError: If pymatgen is not available.

    Example:
        >>> structure = structure_from_cif("structure.cif")
        >>> is_valid, issues = validate_for_dft(structure)
        >>> if not is_valid:
        ...     print("Issues found:")
        ...     for issue in issues:
        ...         print(f"  - {issue}")
    """
    _check_pymatgen()

    from pymatgen.core import Structure as PymatgenStructure

    if not isinstance(structure, PymatgenStructure):
        return False, [f"Expected pymatgen Structure, got {type(structure)}"]

    issues: List[str] = []
    is_valid = True

    # Check number of atoms
    num_atoms = len(structure)
    if num_atoms == 0:
        issues.append("CRITICAL: Structure has no atoms")
        return False, issues

    if num_atoms > max_atoms:
        issues.append(
            f"WARNING: Structure has {num_atoms} atoms (max recommended: {max_atoms}). "
            "Consider using a smaller supercell."
        )

    # Check for valid atomic species
    invalid_species = []
    for site in structure:
        symbol = str(site.specie.element) if hasattr(site.specie, "element") else str(site.specie)
        # Check if it's a valid element
        try:
            from pymatgen.core import Element

            Element(symbol)
        except ValueError:
            invalid_species.append(symbol)

    if invalid_species:
        issues.append(f"CRITICAL: Invalid atomic species: {set(invalid_species)}")
        is_valid = False

    # Check for disordered structure
    if not structure.is_ordered:
        issues.append(
            "WARNING: Structure is disordered (partial occupancies). "
            "Consider creating an ordered supercell."
        )

    # Check for overlapping atoms
    if check_overlapping:
        try:
            from pymatgen.core.structure import Structure

            # Get all pairwise distances
            dist_matrix = structure.distance_matrix

            # Check for atoms closer than min_distance
            import numpy as np

            np.fill_diagonal(dist_matrix, np.inf)
            min_dist = np.min(dist_matrix)

            if min_dist < min_distance:
                # Find the problematic pairs
                close_pairs = np.argwhere(dist_matrix < min_distance)
                for i, j in close_pairs:
                    if i < j:  # Avoid duplicates
                        dist = dist_matrix[i, j]
                        issues.append(
                            f"CRITICAL: Atoms {i} ({structure[i].specie}) and "
                            f"{j} ({structure[j].specie}) are only {dist:.3f} A apart"
                        )
                is_valid = False

        except Exception as e:
            issues.append(f"WARNING: Could not check for overlapping atoms: {e}")

    # Check cell volume
    if structure.volume < 1.0:
        issues.append(
            f"CRITICAL: Cell volume ({structure.volume:.3f} A^3) is unreasonably small"
        )
        is_valid = False

    # Check for reasonable density
    density = structure.density
    if density < 0.1:
        issues.append(
            f"WARNING: Very low density ({density:.3f} g/cm^3). "
            "May indicate missing atoms or excessive vacuum."
        )
    elif density > 25:
        issues.append(
            f"WARNING: Very high density ({density:.3f} g/cm^3). "
            "May indicate overlapping atoms."
        )

    # Log results
    if is_valid:
        logger.info(
            f"Structure validation passed: {structure.composition.reduced_formula}"
        )
    else:
        logger.warning(
            f"Structure validation failed: {structure.composition.reduced_formula}"
        )

    return is_valid, issues


def get_structure_metadata(structure: "Structure") -> StructureMetadata:
    """
    Extract metadata from a structure.

    Args:
        structure: pymatgen Structure object.

    Returns:
        StructureMetadata with formula, volume, density, etc.

    Example:
        >>> structure = structure_from_cif("NaCl.cif")
        >>> meta = get_structure_metadata(structure)
        >>> print(f"Formula: {meta.formula}, Density: {meta.density:.2f} g/cm^3")
    """
    _check_pymatgen()

    from pymatgen.core import Structure as PymatgenStructure

    if not isinstance(structure, PymatgenStructure):
        raise ValidationError(f"Expected pymatgen Structure, got {type(structure)}")

    return StructureMetadata(
        source="unknown",
        formula=structure.composition.formula,
        reduced_formula=structure.composition.reduced_formula,
        num_sites=len(structure),
        volume=structure.volume,
        density=structure.density,
        is_ordered=structure.is_ordered,
    )


# =============================================================================
# Convenience Functions
# =============================================================================


def convert_structure(
    structure: Any,
    target_format: str = "pymatgen",
) -> Any:
    """
    Convert a structure between different formats.

    Automatically detects the input format and converts to the target.

    Args:
        structure: Input structure (pymatgen, AiiDA, ASE, or file path).
        target_format: Target format ("pymatgen", "aiida", "ase").

    Returns:
        Structure in the requested format.

    Raises:
        StructureConversionError: If conversion fails.
        ValueError: If format not recognized.

    Example:
        >>> # Convert AiiDA to pymatgen
        >>> pmg_struct = convert_structure(aiida_struct, "pymatgen")
        >>>
        >>> # Convert file to ASE
        >>> atoms = convert_structure("POSCAR", "ase")
    """
    _check_pymatgen()
    from pymatgen.core import Structure as PymatgenStructure

    # First, convert input to pymatgen Structure (intermediate format)
    if isinstance(structure, PymatgenStructure):
        pmg_struct = structure
    elif isinstance(structure, (str, Path)):
        pmg_struct = structure_from_file(structure)
    else:
        # Try to detect format by checking type
        type_name = type(structure).__name__

        if type_name == "StructureData":
            pmg_struct = from_aiida_structure(structure)
        elif type_name == "Atoms":
            pmg_struct = from_ase_atoms(structure)
        else:
            raise StructureConversionError(
                f"Cannot convert from unknown type: {type_name}"
            )

    # Now convert to target format
    target = target_format.lower()

    if target == "pymatgen":
        return pmg_struct
    elif target == "aiida":
        return to_aiida_structure(pmg_struct)
    elif target == "ase":
        return to_ase_atoms(pmg_struct)
    else:
        raise ValueError(
            f"Unknown target format: {target_format}. "
            f"Supported: pymatgen, aiida, ase"
        )


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Exceptions
    "PymatgenBridgeError",
    "StructureLoadError",
    "StructureConversionError",
    "ValidationError",
    "DependencyError",
    # Enums
    "CrystalSystem",
    "Dimensionality",
    # Data classes
    "SymmetryInfo",
    "StructureMetadata",
    # Loading functions
    "structure_from_cif",
    "structure_from_poscar",
    "structure_to_poscar",
    "structure_from_mp",
    "structure_from_cod",
    "structure_from_file",
    # Conversion functions
    "to_aiida_structure",
    "from_aiida_structure",
    "to_ase_atoms",
    "from_ase_atoms",
    "convert_structure",
    # Analysis functions
    "get_symmetry_info",
    "get_dimensionality",
    "validate_for_dft",
    "get_structure_metadata",
]
