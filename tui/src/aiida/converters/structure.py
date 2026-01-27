"""
Structure format converters for AiiDA-based workflows.

Provides bidirectional conversion between AiiDA StructureData and:
    - pymatgen Structure objects
    - CRYSTAL23 geometry blocks (.d12 format)
    - VASP POSCAR format

These converters are essential for multi-code workflows where structures
flow between different DFT packages.

Note:
    This module requires numpy and aiida-core. Install with:
        pip install crystal-tui[aiida]
"""

from __future__ import annotations

from typing import TYPE_CHECKING

try:
    import numpy as np
except ImportError as err:
    raise ImportError(
        "numpy is required for structure converters. Install with: pip install crystal-tui[aiida]"
    ) from err

from aiida import orm

if TYPE_CHECKING:
    from pymatgen.core import Structure as PymatgenStructure

# Mapping of atomic numbers to symbols
ATOMIC_SYMBOLS = {
    1: "H",
    2: "He",
    3: "Li",
    4: "Be",
    5: "B",
    6: "C",
    7: "N",
    8: "O",
    9: "F",
    10: "Ne",
    11: "Na",
    12: "Mg",
    13: "Al",
    14: "Si",
    15: "P",
    16: "S",
    17: "Cl",
    18: "Ar",
    19: "K",
    20: "Ca",
    21: "Sc",
    22: "Ti",
    23: "V",
    24: "Cr",
    25: "Mn",
    26: "Fe",
    27: "Co",
    28: "Ni",
    29: "Cu",
    30: "Zn",
    31: "Ga",
    32: "Ge",
    33: "As",
    34: "Se",
    35: "Br",
    36: "Kr",
    37: "Rb",
    38: "Sr",
    39: "Y",
    40: "Zr",
    41: "Nb",
    42: "Mo",
    43: "Tc",
    44: "Ru",
    45: "Rh",
    46: "Pd",
    47: "Ag",
    48: "Cd",
    49: "In",
    50: "Sn",
    51: "Sb",
    52: "Te",
    53: "I",
    54: "Xe",
    55: "Cs",
    56: "Ba",
    57: "La",
    58: "Ce",
    59: "Pr",
    60: "Nd",
    61: "Pm",
    62: "Sm",
    63: "Eu",
    64: "Gd",
    65: "Tb",
    66: "Dy",
    67: "Ho",
    68: "Er",
    69: "Tm",
    70: "Yb",
    71: "Lu",
    72: "Hf",
    73: "Ta",
    74: "W",
    75: "Re",
    76: "Os",
    77: "Ir",
    78: "Pt",
    79: "Au",
    80: "Hg",
    81: "Tl",
    82: "Pb",
    83: "Bi",
    84: "Po",
    85: "At",
    86: "Rn",
    87: "Fr",
    88: "Ra",
    89: "Ac",
    90: "Th",
    91: "Pa",
    92: "U",
    93: "Np",
    94: "Pu",
    95: "Am",
    96: "Cm",
    97: "Bk",
    98: "Cf",
    99: "Es",
    100: "Fm",
    101: "Md",
    102: "No",
    103: "Lr",
}

# Reverse mapping: symbol -> atomic number
SYMBOL_TO_Z = {v: k for k, v in ATOMIC_SYMBOLS.items()}


def pymatgen_to_structure(pmg_structure: PymatgenStructure) -> orm.StructureData:
    """
    Convert pymatgen Structure to AiiDA StructureData.

    Args:
        pmg_structure: pymatgen Structure object.

    Returns:
        AiiDA StructureData node (not stored).

    Raises:
        ImportError: If pymatgen is not available.
        ValueError: If structure is invalid.
    """
    try:
        from pymatgen.core import Structure as PymatgenStructure
    except ImportError as err:
        raise ImportError("pymatgen is required for structure conversion") from err

    if not isinstance(pmg_structure, PymatgenStructure):
        raise ValueError(f"Expected pymatgen Structure, got {type(pmg_structure)}")

    # Extract cell matrix (3x3 array)
    cell = pmg_structure.lattice.matrix.tolist()

    # Create AiiDA StructureData
    structure = orm.StructureData(cell=cell)

    # Add atoms
    for site in pmg_structure:
        symbol = site.specie.symbol
        position = site.coords.tolist()
        structure.append_atom(position=position, symbols=symbol)

    # Copy metadata if available
    if hasattr(pmg_structure, "properties"):
        structure.label = pmg_structure.properties.get("label", "")

    return structure


def structure_to_pymatgen(structure: orm.StructureData) -> PymatgenStructure:
    """
    Convert AiiDA StructureData to pymatgen Structure.

    Args:
        structure: AiiDA StructureData node.

    Returns:
        pymatgen Structure object.

    Raises:
        ImportError: If pymatgen is not available.
    """
    try:
        from pymatgen.core import Lattice
        from pymatgen.core import Structure as PymatgenStructure
    except ImportError as err:
        raise ImportError("pymatgen is required for structure conversion") from err

    # Extract cell matrix
    cell = structure.cell

    # Create Lattice object
    lattice = Lattice(cell)

    # Extract species and coordinates
    species = []
    coords = []

    for site in structure.sites:
        species.append(site.kind_name)
        coords.append(site.position)

    # Create pymatgen Structure
    pmg_structure = PymatgenStructure(
        lattice=lattice,
        species=species,
        coords=coords,
        coords_are_cartesian=True,
    )

    return pmg_structure


def crystal_d12_to_structure(d12_content: str) -> orm.StructureData:
    """
    Parse CRYSTAL23 .d12 geometry block to AiiDA StructureData.

    Supports CRYSTAL and SLAB geometry formats. Extracts cell parameters
    and atomic positions from the geometry section.

    Args:
        d12_content: Content of .d12 input file or geometry block.

    Returns:
        AiiDA StructureData node (not stored).

    Raises:
        ValueError: If geometry cannot be parsed.
    """
    lines = d12_content.strip().split("\n")

    # Find geometry section
    geom_start = None
    for i, line in enumerate(lines):
        upper = line.strip().upper()
        if upper in ("CRYSTAL", "SLAB", "POLYMER", "MOLECULE"):
            geom_start = i
            break

    if geom_start is None:
        raise ValueError("No geometry section found (CRYSTAL/SLAB/POLYMER/MOLECULE)")

    dimensionality = lines[geom_start].strip().upper()

    # Parse based on dimensionality
    if dimensionality == "CRYSTAL":
        return _parse_crystal_geometry(lines[geom_start:])
    elif dimensionality == "SLAB":
        return _parse_slab_geometry(lines[geom_start:])
    else:
        raise ValueError(f"Unsupported geometry type: {dimensionality}")


def _parse_crystal_geometry(lines: list[str]) -> orm.StructureData:
    """Parse CRYSTAL (3D periodic) geometry."""
    # Line 0: CRYSTAL
    # Line 1: Space group number
    # Line 2: Cell parameters (a, b, c, alpha, beta, gamma) - may be reduced
    # Line 3: Number of atoms
    # Lines 4+: Atomic positions (Z, x, y, z)

    space_group = int(lines[1].strip())

    # Parse cell parameters
    cell_params = list(map(float, lines[2].split()))

    # Determine number of cell parameters provided
    if len(cell_params) == 1:
        # Cubic: only a
        a = cell_params[0]
        cell = _cell_from_params(a, a, a, 90, 90, 90)
    elif len(cell_params) == 2:
        # Hexagonal: a, c
        a, c = cell_params
        cell = _cell_from_params(a, a, c, 90, 90, 120)
    elif len(cell_params) == 3:
        # Orthorhombic: a, b, c
        a, b, c = cell_params
        cell = _cell_from_params(a, b, c, 90, 90, 90)
    elif len(cell_params) == 6:
        # General: a, b, c, alpha, beta, gamma
        cell = _cell_from_params(*cell_params)
    else:
        raise ValueError(f"Invalid number of cell parameters: {len(cell_params)}")

    # Parse atoms
    num_atoms = int(lines[3].strip())
    structure = orm.StructureData(cell=cell)

    for i in range(4, 4 + num_atoms):
        parts = lines[i].split()
        if len(parts) < 4:
            continue

        atomic_num = int(parts[0])
        # Handle conventional atomic numbers (>100 means ghost atom, etc.)
        if atomic_num > 100:
            atomic_num = atomic_num % 100

        symbol = ATOMIC_SYMBOLS.get(atomic_num, "X")

        # Fractional coordinates
        frac_coords = [float(parts[1]), float(parts[2]), float(parts[3])]

        # Convert to Cartesian
        cart_coords = _frac_to_cart(frac_coords, cell)

        structure.append_atom(position=cart_coords, symbols=symbol)

    return structure


def _parse_slab_geometry(lines: list[str]) -> orm.StructureData:
    """Parse SLAB (2D periodic) geometry."""
    # Line 0: SLAB
    # Line 1: Layer group number
    # Line 2: Cell parameters (a, b, gamma) for 2D
    # Line 3: Number of atoms
    # Lines 4+: Atomic positions

    layer_group = int(lines[1].strip())

    # Parse 2D cell parameters
    cell_params = list(map(float, lines[2].split()))

    # Build 3D cell with large vacuum in z
    if len(cell_params) == 2:
        # Hexagonal 2D: a, gamma assumed 120°
        a = cell_params[0]
        gamma = 120.0
        cell = _cell_from_params(a, a, 30.0, 90, 90, gamma)
    elif len(cell_params) == 3:
        # General 2D: a, b, gamma
        a, b, gamma = cell_params
        cell = _cell_from_params(a, b, 30.0, 90, 90, gamma)
    else:
        raise ValueError(f"Invalid 2D cell parameters: {len(cell_params)}")

    # Parse atoms
    num_atoms = int(lines[3].strip())
    structure = orm.StructureData(cell=cell)

    for i in range(4, 4 + num_atoms):
        parts = lines[i].split()
        if len(parts) < 4:
            continue

        atomic_num = int(parts[0])
        if atomic_num > 100:
            atomic_num = atomic_num % 100

        symbol = ATOMIC_SYMBOLS.get(atomic_num, "X")

        # For SLAB: x, y are fractional, z is Cartesian (Angstrom)
        frac_x = float(parts[1])
        frac_y = float(parts[2])
        z_cart = float(parts[3])

        # Convert x, y to Cartesian
        cart_x = frac_x * cell[0][0] + frac_y * cell[1][0]
        cart_y = frac_x * cell[0][1] + frac_y * cell[1][1]

        structure.append_atom(position=[cart_x, cart_y, z_cart], symbols=symbol)

    return structure


def structure_to_crystal_d12(
    structure: orm.StructureData,
    dimensionality: str = "CRYSTAL",
    space_group: int = 1,
) -> str:
    """
    Convert AiiDA StructureData to CRYSTAL23 geometry block.

    Args:
        structure: AiiDA StructureData node.
        dimensionality: "CRYSTAL" (3D), "SLAB" (2D), etc.
        space_group: Space/layer group number (default P1=1).

    Returns:
        String containing CRYSTAL23 geometry block.
    """
    cell = np.array(structure.cell)

    # Calculate cell parameters
    a, b, c, alpha, beta, gamma = _cell_to_params(cell)

    lines = [dimensionality]
    lines.append(str(space_group))

    if dimensionality == "CRYSTAL":
        # Full cell parameters
        lines.append(f"{a:.8f} {b:.8f} {c:.8f} {alpha:.4f} {beta:.4f} {gamma:.4f}")
    elif dimensionality == "SLAB":
        # 2D cell parameters
        lines.append(f"{a:.8f} {b:.8f} {gamma:.4f}")

    # Add atoms
    lines.append(str(len(structure.sites)))

    for site in structure.sites:
        symbol = site.kind_name
        z = SYMBOL_TO_Z.get(symbol, 1)

        # Convert Cartesian to fractional
        cart = np.array(site.position)
        frac = _cart_to_frac(cart, cell)

        if dimensionality == "SLAB":
            # For SLAB: x, y fractional, z Cartesian
            lines.append(f"{z} {frac[0]:.10f} {frac[1]:.10f} {cart[2]:.10f}")
        else:
            lines.append(f"{z} {frac[0]:.10f} {frac[1]:.10f} {frac[2]:.10f}")

    return "\n".join(lines)


def poscar_to_structure(poscar_content: str) -> orm.StructureData:
    """
    Parse VASP POSCAR format to AiiDA StructureData.

    Args:
        poscar_content: Content of POSCAR file.

    Returns:
        AiiDA StructureData node (not stored).

    Raises:
        ValueError: If POSCAR format is invalid.
    """
    lines = poscar_content.strip().split("\n")

    if len(lines) < 8:
        raise ValueError("POSCAR file too short")

    # Line 0: Comment
    comment = lines[0].strip()

    # Line 1: Scaling factor
    scaling = float(lines[1].strip())

    # Lines 2-4: Lattice vectors
    cell = []
    for i in range(2, 5):
        vec = list(map(float, lines[i].split()))
        cell.append([v * scaling for v in vec])

    # Line 5: Species symbols (optional in older format)
    # Line 6: Number of each species
    species_line = lines[5].split()
    counts_line = lines[6].split()

    # Determine if species names are on line 5 or if it's counts directly
    try:
        counts = list(map(int, species_line))
        # Old format: no species names, need to infer
        species = ["X"] * len(counts)
        count_offset = 0
    except ValueError:
        # New format: line 5 is species, line 6 is counts
        species = species_line
        counts = list(map(int, counts_line))
        count_offset = 1

    # Determine coordinate type
    coord_line_idx = 6 + count_offset
    coord_type = lines[coord_line_idx].strip()[0].upper()
    is_cartesian = coord_type in ("C", "K")  # Cartesian or Kartesian

    # Build species list
    species_list = []
    for sp, count in zip(species, counts, strict=False):
        species_list.extend([sp] * count)

    # Parse atomic positions
    structure = orm.StructureData(cell=cell)
    total_atoms = sum(counts)

    for i in range(total_atoms):
        line_idx = coord_line_idx + 1 + i
        parts = lines[line_idx].split()
        coords = [float(parts[0]), float(parts[1]), float(parts[2])]

        if is_cartesian:
            cart_coords = [c * scaling for c in coords]
        else:
            # Fractional - convert to Cartesian
            cart_coords = _frac_to_cart(coords, cell)

        structure.append_atom(position=cart_coords, symbols=species_list[i])

    structure.label = comment

    return structure


def structure_to_poscar(
    structure: orm.StructureData,
    comment: str = "Generated by crystalmath",
) -> str:
    """
    Convert AiiDA StructureData to VASP POSCAR format.

    Args:
        structure: AiiDA StructureData node.
        comment: Comment line for POSCAR header.

    Returns:
        String in POSCAR format.
    """
    cell = np.array(structure.cell)

    # Group atoms by species
    species_order = []
    species_counts = {}
    atom_data = []  # (species, position)

    for site in structure.sites:
        symbol = site.kind_name
        if symbol not in species_counts:
            species_counts[symbol] = 0
            species_order.append(symbol)
        species_counts[symbol] += 1
        atom_data.append((symbol, site.position))

    # Sort atoms by species order
    atom_data.sort(key=lambda x: species_order.index(x[0]))

    lines = [comment]
    lines.append("1.0")  # Scaling factor

    # Cell vectors
    for vec in cell:
        lines.append(f"  {vec[0]:20.14f}  {vec[1]:20.14f}  {vec[2]:20.14f}")

    # Species names
    lines.append("  " + "  ".join(species_order))

    # Species counts
    lines.append("  " + "  ".join(str(species_counts[s]) for s in species_order))

    # Use Direct (fractional) coordinates
    lines.append("Direct")

    # Atomic positions
    for symbol, cart_pos in atom_data:
        frac = _cart_to_frac(np.array(cart_pos), cell)
        lines.append(f"  {frac[0]:20.14f}  {frac[1]:20.14f}  {frac[2]:20.14f}")

    return "\n".join(lines)


# ============================================================================
# Helper functions
# ============================================================================


def _cell_from_params(
    a: float, b: float, c: float, alpha: float, beta: float, gamma: float
) -> list[list[float]]:
    """
    Build 3x3 cell matrix from lattice parameters.

    Uses standard crystallographic convention:
        - a along x
        - b in xy plane
        - c general direction
    """
    alpha_rad = np.radians(alpha)
    beta_rad = np.radians(beta)
    gamma_rad = np.radians(gamma)

    cos_alpha = np.cos(alpha_rad)
    cos_beta = np.cos(beta_rad)
    cos_gamma = np.cos(gamma_rad)
    sin_gamma = np.sin(gamma_rad)

    # Standard crystallographic cell construction
    va = [a, 0, 0]
    vb = [b * cos_gamma, b * sin_gamma, 0]

    cx = c * cos_beta
    cy = c * (cos_alpha - cos_beta * cos_gamma) / sin_gamma
    cz = np.sqrt(c**2 - cx**2 - cy**2)
    vc = [cx, cy, cz]

    return [va, vb, vc]


def _cell_to_params(cell: np.ndarray) -> tuple[float, float, float, float, float, float]:
    """
    Extract lattice parameters from 3x3 cell matrix.

    Returns:
        (a, b, c, alpha, beta, gamma) where angles are in degrees.
    """
    va, vb, vc = cell[0], cell[1], cell[2]

    a = np.linalg.norm(va)
    b = np.linalg.norm(vb)
    c = np.linalg.norm(vc)

    alpha = np.degrees(np.arccos(np.dot(vb, vc) / (b * c)))
    beta = np.degrees(np.arccos(np.dot(va, vc) / (a * c)))
    gamma = np.degrees(np.arccos(np.dot(va, vb) / (a * b)))

    return a, b, c, alpha, beta, gamma


def _frac_to_cart(frac: list[float], cell: list[list[float]]) -> list[float]:
    """Convert fractional to Cartesian coordinates."""
    cell_arr = np.array(cell)
    frac_arr = np.array(frac)
    cart = np.dot(frac_arr, cell_arr)
    return cart.tolist()


def _cart_to_frac(cart: np.ndarray, cell: np.ndarray) -> np.ndarray:
    """Convert Cartesian to fractional coordinates."""
    inv_cell = np.linalg.inv(cell)
    return np.dot(cart, inv_cell)
