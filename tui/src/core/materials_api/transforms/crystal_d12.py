"""Convert pymatgen Structure to CRYSTAL23 .d12 input format.

This module provides the CrystalD12Generator class for generating CRYSTAL23
input files from pymatgen Structure objects. It supports:
- 3D crystals (CRYSTAL keyword)
- 2D slabs (SLAB keyword)
- 1D polymers (POLYMER keyword)
- 0D molecules (MOLECULE keyword)

The generator handles:
- Lattice parameter extraction and formatting
- Atomic position conversion to fractional coordinates
- Space group / layer group detection
- Basis set specification (internal library or custom)
- DFT/HF Hamiltonian configuration
- K-point mesh (SHRINK) settings

Example:
    >>> from pymatgen.core import Structure
    >>> from crystal_d12 import CrystalD12Generator
    >>>
    >>> structure = Structure.from_file("POSCAR")
    >>> d12_content = CrystalD12Generator.generate_full_input(
    ...     structure,
    ...     title="My calculation",
    ...     functional="PBE",
    ...     shrink=(8, 8),
    ... )
    >>> with open("input.d12", "w") as f:
    ...     f.write(d12_content)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pymatgen.core import Structure


class CrystalSystem(Enum):
    """CRYSTAL23 system dimensionality types."""

    CRYSTAL = "CRYSTAL"  # 3D periodic
    SLAB = "SLAB"  # 2D periodic
    POLYMER = "POLYMER"  # 1D periodic
    MOLECULE = "MOLECULE"  # 0D (cluster)


@dataclass
class BasisSetConfig:
    """Configuration for basis set specification.

    Attributes:
        use_internal: If True, use CRYSTAL23's internal BASISSET keyword
        library_name: Name of internal library (e.g., 'POB-TZVP-REV2')
        custom_basis: Dict mapping atomic number to basis set definition strings
    """

    use_internal: bool = True
    library_name: str = "POB-TZVP-REV2"
    custom_basis: dict[int, str] = field(default_factory=dict)


@dataclass
class HamiltonianConfig:
    """Configuration for Hamiltonian and SCF settings.

    Attributes:
        method: Calculation method ('DFT', 'HF', 'UHF')
        functional: DFT functional (e.g., 'PBE', 'B3LYP', 'HSE06')
        grid: Integration grid ('XLGRID', 'XXLGRID', or None for default)
        tolinteg: Coulomb/exchange integral tolerances (5 integers)
        maxcycle: Maximum SCF iterations
        toldee: Energy convergence threshold (10^-N Hartree)
        fmixing: Fock matrix mixing percentage
        levshift: Level shift parameters (shift, lock flag)
    """

    method: str = "DFT"
    functional: str = "PBE"
    grid: str | None = "XLGRID"
    tolinteg: tuple[int, int, int, int, int] = (7, 7, 7, 7, 14)
    maxcycle: int = 200
    toldee: int = 8
    fmixing: int | None = None
    levshift: tuple[int, int] | None = None


@dataclass
class OptimizationConfig:
    """Configuration for geometry optimization.

    Attributes:
        enabled: Whether to perform geometry optimization
        opt_type: Type of optimization ('FULLOPTG', 'ATOMONLY', 'CELLONLY')
        toldeg: Gradient convergence threshold
        toldee: Energy convergence threshold for optimization
        maxcycle: Maximum optimization cycles
    """

    enabled: bool = False
    opt_type: str = "FULLOPTG"
    toldeg: float = 0.00003
    toldee: int = 8
    maxcycle: int = 500


# Element symbol to atomic number mapping
ELEMENT_TO_Z: dict[str, int] = {
    "H": 1, "He": 2, "Li": 3, "Be": 4, "B": 5, "C": 6, "N": 7, "O": 8,
    "F": 9, "Ne": 10, "Na": 11, "Mg": 12, "Al": 13, "Si": 14, "P": 15,
    "S": 16, "Cl": 17, "Ar": 18, "K": 19, "Ca": 20, "Sc": 21, "Ti": 22,
    "V": 23, "Cr": 24, "Mn": 25, "Fe": 26, "Co": 27, "Ni": 28, "Cu": 29,
    "Zn": 30, "Ga": 31, "Ge": 32, "As": 33, "Se": 34, "Br": 35, "Kr": 36,
    "Rb": 37, "Sr": 38, "Y": 39, "Zr": 40, "Nb": 41, "Mo": 42, "Tc": 43,
    "Ru": 44, "Rh": 45, "Pd": 46, "Ag": 47, "Cd": 48, "In": 49, "Sn": 50,
    "Sb": 51, "Te": 52, "I": 53, "Xe": 54, "Cs": 55, "Ba": 56, "La": 57,
    "Ce": 58, "Pr": 59, "Nd": 60, "Pm": 61, "Sm": 62, "Eu": 63, "Gd": 64,
    "Tb": 65, "Dy": 66, "Ho": 67, "Er": 68, "Tm": 69, "Yb": 70, "Lu": 71,
    "Hf": 72, "Ta": 73, "W": 74, "Re": 75, "Os": 76, "Ir": 77, "Pt": 78,
    "Au": 79, "Hg": 80, "Tl": 81, "Pb": 82, "Bi": 83, "Po": 84, "At": 85,
    "Rn": 86, "Fr": 87, "Ra": 88, "Ac": 89, "Th": 90, "Pa": 91, "U": 92,
    "Np": 93, "Pu": 94, "Am": 95, "Cm": 96, "Bk": 97, "Cf": 98, "Es": 99,
    "Fm": 100, "Md": 101, "No": 102, "Lr": 103,
}


class CrystalD12Generator:
    """Generate CRYSTAL23 .d12 input files from pymatgen structures.

    This class provides methods to convert pymatgen Structure objects to
    CRYSTAL23 input format. It handles the geometry block, basis sets,
    Hamiltonian settings, and optional geometry optimization.

    The generator automatically determines the appropriate dimensionality
    (3D/2D/1D/0D) based on structure properties, or allows explicit override.

    Example:
        >>> structure = Structure.from_file("POSCAR")
        >>> d12 = CrystalD12Generator.generate_full_input(
        ...     structure,
        ...     title="MoS2 monolayer",
        ...     functional="PBE",
        ...     shrink=(12, 24),
        ... )
    """

    @staticmethod
    def _get_atomic_number(symbol: str) -> int:
        """Get atomic number from element symbol.

        Args:
            symbol: Element symbol (e.g., 'Mo', 'S')

        Returns:
            Atomic number

        Raises:
            ValueError: If element symbol is not recognized
        """
        # Strip any charge or oxidation state suffix (e.g., 'Fe2+' -> 'Fe')
        clean_symbol = "".join(c for c in symbol if c.isalpha())
        if clean_symbol not in ELEMENT_TO_Z:
            raise ValueError(f"Unknown element symbol: {symbol}")
        return ELEMENT_TO_Z[clean_symbol]

    @staticmethod
    def _detect_dimensionality(structure: "Structure") -> CrystalSystem:
        """Detect structure dimensionality from lattice parameters.

        Uses lattice vector lengths and vacuum detection to determine
        if structure is 3D (bulk), 2D (slab), 1D (polymer), or 0D (molecule).

        Args:
            structure: pymatgen Structure object

        Returns:
            CrystalSystem enum indicating dimensionality
        """
        lattice = structure.lattice
        a, b, c = lattice.a, lattice.b, lattice.c

        # Vacuum detection threshold (Angstroms)
        # If a dimension is much larger than bond lengths, it's likely vacuum
        vacuum_threshold = 12.0

        # Count number of "vacuum" dimensions
        # This is a heuristic - proper 2D detection would use pymatgen's
        # structure_analyzer module
        vacuum_dims = 0
        if c > vacuum_threshold and c > 2 * max(a, b):
            vacuum_dims += 1
        if b > vacuum_threshold and b > 2 * max(a, c):
            vacuum_dims += 1
        if a > vacuum_threshold and a > 2 * max(b, c):
            vacuum_dims += 1

        if vacuum_dims == 0:
            return CrystalSystem.CRYSTAL
        elif vacuum_dims == 1:
            return CrystalSystem.SLAB
        elif vacuum_dims == 2:
            return CrystalSystem.POLYMER
        else:
            return CrystalSystem.MOLECULE

    @staticmethod
    def _format_lattice_params(
        structure: "Structure",
        system: CrystalSystem,
    ) -> list[str]:
        """Format lattice parameters for CRYSTAL23 geometry block.

        Different dimensionalities require different parameter formats:
        - CRYSTAL (3D): a, b, c, alpha, beta, gamma (reduced by symmetry)
        - SLAB (2D): a [, b, gamma] (depends on layer group)
        - POLYMER (1D): a
        - MOLECULE (0D): no lattice parameters

        Args:
            structure: pymatgen Structure object
            system: CrystalSystem enum for dimensionality

        Returns:
            List of formatted lattice parameter lines
        """
        lattice = structure.lattice
        a, b, c = lattice.a, lattice.b, lattice.c
        alpha, beta, gamma = lattice.alpha, lattice.beta, lattice.gamma

        lines = []

        if system == CrystalSystem.CRYSTAL:
            # Full 3D lattice - format depends on space group
            # For triclinic (P1, space group 1): a, b, c, alpha, beta, gamma
            # For cubic: just a
            # For now, output full parameters on separate lines
            # CRYSTAL23 expects space group-dependent format
            lines.append(f"{a:.6f}")
            # Additional parameters depend on crystal system
            # For lower symmetry, add more parameters
            if not (
                abs(a - b) < 0.001
                and abs(a - c) < 0.001
                and abs(alpha - 90) < 0.1
                and abs(beta - 90) < 0.1
                and abs(gamma - 90) < 0.1
            ):
                # Non-cubic: need more parameters
                if abs(a - b) > 0.001 or abs(alpha - 90) > 0.1:
                    lines[-1] = f"{a:.6f} {b:.6f} {c:.6f}"
                    lines.append(f"{alpha:.4f} {beta:.4f} {gamma:.4f}")

        elif system == CrystalSystem.SLAB:
            # 2D slab - typically just 'a' for hexagonal layer groups
            lines.append(f"{a:.6f}")
            # For non-hexagonal slabs, may need more params
            if abs(a - b) > 0.001 or abs(gamma - 120) > 1:
                lines[-1] = f"{a:.6f} {b:.6f}"
                if abs(gamma - 90) > 1 and abs(gamma - 120) > 1:
                    lines.append(f"{gamma:.4f}")

        elif system == CrystalSystem.POLYMER:
            # 1D polymer - just the repeat distance
            lines.append(f"{a:.6f}")

        # MOLECULE has no lattice parameters

        return lines

    @staticmethod
    def _get_symmetry_info(
        structure: "Structure",
        system: CrystalSystem,
    ) -> tuple[int, str]:
        """Get space group or layer group number for structure.

        Args:
            structure: pymatgen Structure object
            system: CrystalSystem enum for dimensionality

        Returns:
            Tuple of (group_number, group_symbol)
        """
        try:
            from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

            analyzer = SpacegroupAnalyzer(structure, symprec=0.1)
            spg_symbol = analyzer.get_space_group_symbol()
            spg_number = analyzer.get_space_group_number()

            if system == CrystalSystem.SLAB:
                # For 2D materials, we should use layer groups
                # Common mappings (simplified):
                # P-6m2 (space group 187 projected) -> Layer group 73
                # This is a simplification - proper layer group detection
                # would require pymatgen's 2D symmetry analysis
                return (spg_number, spg_symbol)

            return (spg_number, spg_symbol)

        except Exception:
            # Default to P1 (no symmetry) if detection fails
            return (1, "P1")

    @staticmethod
    def _get_irreducible_atoms(
        structure: "Structure",
        space_group: int,
    ) -> list[tuple[int, float, float, float]]:
        """Get irreducible (asymmetric unit) atoms.

        For symmetry-aware input, we need only the atoms in the asymmetric
        unit. This is a simplified version that returns all atoms for P1,
        or attempts symmetry reduction for higher symmetry.

        Args:
            structure: pymatgen Structure object
            space_group: Space group number

        Returns:
            List of (atomic_number, x, y, z) tuples with fractional coords
        """
        atoms = []

        if space_group == 1:
            # P1: all atoms are independent
            for site in structure.sites:
                z = CrystalD12Generator._get_atomic_number(
                    site.specie.symbol
                )
                frac = site.frac_coords
                atoms.append((z, frac[0], frac[1], frac[2]))
        else:
            # For higher symmetry, try to get asymmetric unit
            try:
                from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

                analyzer = SpacegroupAnalyzer(structure, symprec=0.1)
                sym_struct = analyzer.get_symmetrized_structure()

                # Get one representative from each equivalent set
                for equiv_sites in sym_struct.equivalent_sites:
                    site = equiv_sites[0]  # Take first of equivalent set
                    z = CrystalD12Generator._get_atomic_number(
                        site.specie.symbol
                    )
                    frac = site.frac_coords
                    atoms.append((z, frac[0], frac[1], frac[2]))

            except Exception:
                # Fall back to all atoms
                for site in structure.sites:
                    z = CrystalD12Generator._get_atomic_number(
                        site.specie.symbol
                    )
                    frac = site.frac_coords
                    atoms.append((z, frac[0], frac[1], frac[2]))

        return atoms

    @staticmethod
    def structure_to_geometry(
        structure: "Structure",
        title: str = "Structure from Materials Project",
        system: CrystalSystem | None = None,
        symmetry_group: int | None = None,
        convention: str = "0 0 0",
    ) -> str:
        """Convert pymatgen Structure to CRYSTAL23 geometry block.

        Generates the geometry section of a .d12 file, from the title
        through the END keyword (before basis sets).

        Args:
            structure: pymatgen Structure object
            title: Title line for the .d12 file
            system: System dimensionality (auto-detected if None)
            symmetry_group: Space/layer group number (auto-detected if None)
            convention: Crystal setting convention (default "0 0 0")

        Returns:
            String containing CRYSTAL23 geometry block

        Example:
            >>> geom = CrystalD12Generator.structure_to_geometry(
            ...     structure,
            ...     title="MgO bulk",
            ...     system=CrystalSystem.CRYSTAL,
            ...     symmetry_group=225,
            ... )
        """
        lines = []

        # Title
        lines.append(title)

        # Determine dimensionality
        if system is None:
            system = CrystalD12Generator._detect_dimensionality(structure)

        # System keyword
        lines.append(system.value)

        # For 3D crystals, add convention line
        if system == CrystalSystem.CRYSTAL:
            lines.append(convention)

        # Space/layer group
        if symmetry_group is None:
            symmetry_group, _ = CrystalD12Generator._get_symmetry_info(
                structure, system
            )
        lines.append(str(symmetry_group))

        # Lattice parameters
        lattice_lines = CrystalD12Generator._format_lattice_params(
            structure, system
        )
        lines.extend(lattice_lines)

        # Get atoms (asymmetric unit for high symmetry, all for P1)
        atoms = CrystalD12Generator._get_irreducible_atoms(
            structure, symmetry_group
        )

        # Number of atoms
        lines.append(str(len(atoms)))

        # Atomic positions (atomic_number x y z)
        for z, x, y, zcoord in atoms:
            lines.append(f"{z} {x:.6f} {y:.6f} {zcoord:.6f}")

        # End of geometry
        lines.append("END")

        return "\n".join(lines)

    @staticmethod
    def _format_basis_set_block(
        structure: "Structure",
        config: BasisSetConfig,
    ) -> str:
        """Format basis set block for .d12 file.

        Args:
            structure: pymatgen Structure to get element list
            config: BasisSetConfig with basis set settings

        Returns:
            Formatted basis set block string
        """
        lines = []

        if config.use_internal:
            # Use CRYSTAL23's internal basis set library
            lines.append("BASISSET")
            lines.append(config.library_name)
        else:
            # Custom basis sets - must provide for each element
            # Get unique elements in structure
            elements = set(site.specie.symbol for site in structure.sites)

            for element in sorted(elements):
                z = CrystalD12Generator._get_atomic_number(element)
                if z in config.custom_basis:
                    lines.append(config.custom_basis[z])
                else:
                    raise ValueError(
                        f"No custom basis set provided for element {element}"
                    )

            # End of basis sets marker
            lines.append("99 0")
            lines.append("END")

        return "\n".join(lines)

    @staticmethod
    def _format_hamiltonian_block(config: HamiltonianConfig) -> str:
        """Format Hamiltonian/SCF block for .d12 file.

        Args:
            config: HamiltonianConfig with calculation settings

        Returns:
            Formatted Hamiltonian block string
        """
        lines = []

        # Method (DFT, HF, UHF)
        if config.method == "DFT":
            lines.append("DFT")
            lines.append(config.functional)
            if config.grid:
                lines.append(config.grid)
            lines.append("END")
        elif config.method in ("HF", "UHF"):
            lines.append(config.method)

        # Integration tolerances
        lines.append("TOLINTEG")
        lines.append(" ".join(str(t) for t in config.tolinteg))

        # SCF settings
        lines.append("SHRINK")
        # Note: SHRINK values are set in generate_full_input
        # This is a placeholder that will be overridden

        if config.fmixing is not None:
            lines.append("FMIXING")
            lines.append(str(config.fmixing))

        if config.levshift is not None:
            lines.append("LEVSHIFT")
            lines.append(f"{config.levshift[0]} {config.levshift[1]}")

        lines.append("MAXCYCLE")
        lines.append(str(config.maxcycle))

        lines.append("TOLDEE")
        lines.append(str(config.toldee))

        return "\n".join(lines)

    @staticmethod
    def _format_optimization_block(config: OptimizationConfig) -> str:
        """Format geometry optimization block.

        Args:
            config: OptimizationConfig with optimization settings

        Returns:
            Formatted OPTGEOM block string, or empty string if disabled
        """
        if not config.enabled:
            return ""

        lines = ["OPTGEOM", config.opt_type]

        lines.append("TOLDEG")
        lines.append(f"{config.toldeg:.5f}")

        lines.append("TOLDEE")
        lines.append(str(config.toldee))

        lines.append("END")  # End OPTGEOM block

        return "\n".join(lines)

    @staticmethod
    def generate_full_input(
        structure: "Structure",
        title: str = "MP Structure",
        system: CrystalSystem | None = None,
        symmetry_group: int | None = None,
        basis_set: str | BasisSetConfig | None = None,
        hamiltonian: str = "DFT",
        functional: str = "PBE",
        shrink: tuple[int, int] = (8, 8),
        tolinteg: tuple[int, int, int, int, int] = (7, 7, 7, 7, 14),
        maxcycle: int = 200,
        toldee: int = 8,
        fmixing: int | None = None,
        levshift: tuple[int, int] | None = None,
        grid: str | None = "XLGRID",
        optimization: OptimizationConfig | None = None,
        extra_keywords: list[str] | None = None,
    ) -> str:
        """Generate complete .d12 input file.

        Creates a full CRYSTAL23 input file with geometry, basis sets,
        Hamiltonian settings, and optional geometry optimization.

        Args:
            structure: pymatgen Structure object
            title: Title line for the calculation
            system: Dimensionality (CRYSTAL/SLAB/POLYMER/MOLECULE), auto if None
            symmetry_group: Space/layer group number, auto-detected if None
            basis_set: Basis set config, library name string, or None for default
            hamiltonian: Method type ('DFT', 'HF', 'UHF')
            functional: DFT functional (e.g., 'PBE', 'B3LYP', 'HSE06')
            shrink: k-point mesh SHRINK parameters (IS, ISP)
            tolinteg: Integration tolerances (5 integers)
            maxcycle: Maximum SCF iterations
            toldee: Energy convergence (10^-N Hartree)
            fmixing: Fock matrix mixing percentage (None to skip)
            levshift: Level shift (shift, lock_flag) or None to skip
            grid: DFT integration grid ('XLGRID', 'XXLGRID', None)
            optimization: OptimizationConfig for geometry optimization
            extra_keywords: Additional keywords to append before END

        Returns:
            Complete .d12 input file content as string

        Example:
            >>> d12 = CrystalD12Generator.generate_full_input(
            ...     structure,
            ...     title="MoS2 monolayer PBE",
            ...     system=CrystalSystem.SLAB,
            ...     symmetry_group=73,
            ...     basis_set="POB-TZVP-REV2",
            ...     functional="PBE",
            ...     shrink=(12, 24),
            ...     optimization=OptimizationConfig(
            ...         enabled=True,
            ...         opt_type="ATOMONLY",
            ...     ),
            ... )
        """
        sections = []

        # 1. Geometry block
        geometry = CrystalD12Generator.structure_to_geometry(
            structure,
            title=title,
            system=system,
            symmetry_group=symmetry_group,
        )
        sections.append(geometry)

        # 2. Optimization block (goes after geometry END, before basis)
        if optimization and optimization.enabled:
            opt_block = CrystalD12Generator._format_optimization_block(
                optimization
            )
            # Insert OPTGEOM before the final END of geometry
            # Actually, OPTGEOM comes after geometry END in CRYSTAL23
            sections.append(opt_block)

        # 3. Basis set block
        if basis_set is None:
            basis_config = BasisSetConfig()
        elif isinstance(basis_set, str):
            basis_config = BasisSetConfig(
                use_internal=True, library_name=basis_set
            )
        else:
            basis_config = basis_set

        basis_block = CrystalD12Generator._format_basis_set_block(
            structure, basis_config
        )
        sections.append(basis_block)

        # 4. Hamiltonian block
        ham_config = HamiltonianConfig(
            method=hamiltonian,
            functional=functional,
            grid=grid,
            tolinteg=tolinteg,
            maxcycle=maxcycle,
            toldee=toldee,
            fmixing=fmixing,
            levshift=levshift,
        )

        # Build Hamiltonian section manually for proper formatting
        ham_lines = []

        if hamiltonian == "DFT":
            ham_lines.append("DFT")
            ham_lines.append(functional)
            if grid:
                ham_lines.append(grid)
            ham_lines.append("END")
        elif hamiltonian in ("HF", "UHF"):
            ham_lines.append(hamiltonian)

        # Integration tolerances
        ham_lines.append("TOLINTEG")
        ham_lines.append(" ".join(str(t) for t in tolinteg))

        # k-point mesh
        ham_lines.append("SHRINK")
        ham_lines.append(f"{shrink[0]} {shrink[1]}")

        # Optional SCF settings
        if fmixing is not None:
            ham_lines.append("FMIXING")
            ham_lines.append(str(fmixing))

        if levshift is not None:
            ham_lines.append("LEVSHIFT")
            ham_lines.append(f"{levshift[0]} {levshift[1]}")

        ham_lines.append("MAXCYCLE")
        ham_lines.append(str(maxcycle))

        # Extra keywords before final END
        if extra_keywords:
            ham_lines.extend(extra_keywords)

        # Final END
        ham_lines.append("END")

        sections.append("\n".join(ham_lines))

        # Combine all sections
        return "\n".join(sections)

    @staticmethod
    def from_mp_structure(
        structure: "Structure",
        mp_id: str,
        functional: str = "PBE",
        shrink: tuple[int, int] = (8, 8),
        basis_set: str = "POB-TZVP-REV2",
        optimize: bool = False,
        opt_type: str = "FULLOPTG",
    ) -> str:
        """Convenience method for Materials Project structures.

        Creates a sensible default .d12 input for a structure downloaded
        from the Materials Project, with the MP-ID in the title.

        Args:
            structure: pymatgen Structure from Materials Project
            mp_id: Materials Project ID (e.g., 'mp-1234')
            functional: DFT functional (default 'PBE')
            shrink: k-point mesh (default (8, 8))
            basis_set: Basis set library name
            optimize: Whether to include geometry optimization
            opt_type: Optimization type if optimize=True

        Returns:
            Complete .d12 input file content
        """
        # Create title with MP-ID
        formula = structure.composition.reduced_formula
        title = f"{formula} ({mp_id}) - {functional}"

        # Determine system type
        system = CrystalD12Generator._detect_dimensionality(structure)

        # Setup optimization if requested
        optimization = None
        if optimize:
            optimization = OptimizationConfig(
                enabled=True,
                opt_type=opt_type,
                maxcycle=500,
            )

        return CrystalD12Generator.generate_full_input(
            structure,
            title=title,
            system=system,
            basis_set=basis_set,
            functional=functional,
            shrink=shrink,
            optimization=optimization,
        )
