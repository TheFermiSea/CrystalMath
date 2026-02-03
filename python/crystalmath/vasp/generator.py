"""High-level VASP input file generator."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .incar import IncarBuilder, IncarPreset
from .kpoints import KpointsBuilder, KpointsMesh

if TYPE_CHECKING:
    from pymatgen.core import Structure


# Approximate ENMAX values for common elements (eV)
# Used for ENCUT estimation when POTCAR not available
ENMAX_TABLE = {
    # s-block
    "H": 250,
    "Li": 140,
    "Na": 102,
    "K": 117,
    "Rb": 111,
    "Cs": 86,
    "Be": 309,
    "Mg": 200,
    "Ca": 118,
    "Sr": 107,
    "Ba": 95,
    # p-block
    "B": 319,
    "Al": 240,
    "Ga": 135,
    "In": 96,
    "Tl": 90,
    "C": 400,
    "Si": 245,
    "Ge": 174,
    "Sn": 103,
    "Pb": 98,
    "N": 400,
    "P": 255,
    "As": 209,
    "Sb": 172,
    "Bi": 105,
    "O": 400,
    "S": 280,
    "Se": 212,
    "Te": 175,
    "F": 400,
    "Cl": 262,
    "Br": 213,
    "I": 176,
    # d-block (3d)
    "Sc": 155,
    "Ti": 178,
    "V": 193,
    "Cr": 227,
    "Mn": 270,
    "Fe": 268,
    "Co": 268,
    "Ni": 270,
    "Cu": 295,
    "Zn": 277,
    # d-block (4d)
    "Y": 148,
    "Zr": 156,
    "Nb": 182,
    "Mo": 225,
    "Tc": 229,
    "Ru": 213,
    "Rh": 229,
    "Pd": 251,
    "Ag": 250,
    "Cd": 274,
    # d-block (5d)
    "Hf": 220,
    "Ta": 224,
    "W": 224,
    "Re": 226,
    "Os": 228,
    "Ir": 211,
    "Pt": 230,
    "Au": 230,
    "Hg": 233,
    # f-block (lanthanides)
    "La": 219,
    "Ce": 273,
    "Nd": 253,
    "Gd": 256,
    # Common defaults
    "DEFAULT": 400,
}


@dataclass
class VaspInputs:
    """Complete VASP input file set.

    Attributes:
        poscar: POSCAR file content (atomic structure).
        incar: INCAR file content (calculation parameters).
        kpoints: KPOINTS file content (k-point mesh).
        potcar_symbols: Element symbols for POTCAR (user must provide actual file).
    """

    poscar: str
    incar: str
    kpoints: str
    potcar_symbols: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "poscar": self.poscar,
            "incar": self.incar,
            "kpoints": self.kpoints,
            "potcar_symbols": self.potcar_symbols,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VaspInputs":
        """Create from dict (e.g., from JSON)."""
        return cls(
            poscar=data["poscar"],
            incar=data["incar"],
            kpoints=data["kpoints"],
            potcar_symbols=data["potcar_symbols"],
        )


class VaspInputGenerator:
    """Generate complete VASP inputs from pymatgen Structure.

    Example:
        >>> from pymatgen.core import Structure
        >>> structure = Structure.from_file("POSCAR")
        >>> generator = VaspInputGenerator(
        ...     structure,
        ...     preset=IncarPreset.RELAX,
        ...     encut=520,
        ...     kppra=2000,
        ... )
        >>> inputs = generator.generate()
        >>> print(inputs.poscar)
        >>> print(inputs.incar)
    """

    def __init__(
        self,
        structure: "Structure",
        preset: IncarPreset = IncarPreset.STATIC,
        encut: Optional[float] = None,
        kppra: int = 1000,
        kpoints_mesh: Optional[KpointsMesh] = None,
        **incar_overrides,
    ):
        """Initialize generator.

        Args:
            structure: pymatgen Structure object.
            preset: INCAR preset configuration.
            encut: Plane-wave cutoff (eV). If None, estimated from elements.
            kppra: k-points per reciprocal atom for automatic mesh.
            kpoints_mesh: Explicit KpointsMesh (overrides kppra).
            **incar_overrides: Additional INCAR parameters to override.
        """
        self.structure = structure
        self.preset = preset
        self.encut = encut if encut is not None else self._estimate_encut()
        self.kppra = kppra
        self.kpoints_mesh = kpoints_mesh
        self.incar_overrides = incar_overrides

    def _estimate_encut(self) -> float:
        """Estimate reasonable ENCUT based on elements.

        Uses 1.3x max ENMAX from approximate table.
        This is a conservative estimate - POTCAR ENMAX should be used
        for production calculations.

        Returns:
            Estimated ENCUT in eV.
        """
        elements = set(str(s) for s in self.structure.species)
        max_enmax = max(ENMAX_TABLE.get(e, ENMAX_TABLE["DEFAULT"]) for e in elements)
        return max_enmax * 1.3  # 30% buffer for accuracy

    def generate(self) -> VaspInputs:
        """Generate all VASP input files.

        Returns:
            VaspInputs containing POSCAR, INCAR, KPOINTS, and POTCAR symbols.
        """
        # POSCAR
        poscar = self._generate_poscar()

        # INCAR
        incar_builder = IncarBuilder.from_preset(
            self.preset,
            encut=self.encut,
            **self.incar_overrides,
        )
        incar = incar_builder.to_string()

        # KPOINTS
        if self.kpoints_mesh is not None:
            kpoints = self.kpoints_mesh.to_string()
        else:
            kpoints_mesh = KpointsBuilder.from_density(self.structure, self.kppra)
            kpoints = kpoints_mesh.to_string()

        # POTCAR symbols (preserve order, remove duplicates)
        seen = set()
        potcar_symbols = []
        for s in self.structure.species:
            symbol = str(s)
            if symbol not in seen:
                seen.add(symbol)
                potcar_symbols.append(symbol)

        return VaspInputs(
            poscar=poscar,
            incar=incar,
            kpoints=kpoints,
            potcar_symbols=potcar_symbols,
        )

    def _generate_poscar(self) -> str:
        """Generate POSCAR from structure.

        Returns:
            POSCAR file content as string.
        """
        from pymatgen.io.vasp import Poscar

        comment = f"{self.structure.formula} - Generated by CrystalMath"
        poscar = Poscar(self.structure, comment=comment)
        return poscar.get_str()


def generate_vasp_inputs_from_mp(
    mp_id: str,
    preset: IncarPreset = IncarPreset.STATIC,
    encut: Optional[float] = None,
    kppra: int = 1000,
    **incar_overrides,
) -> VaspInputs:
    """Generate VASP inputs directly from Materials Project ID.

    Args:
        mp_id: Materials Project ID (e.g., "mp-149").
        preset: INCAR preset configuration.
        encut: Plane-wave cutoff (eV). If None, estimated from elements.
        kppra: k-points per reciprocal atom.
        **incar_overrides: Additional INCAR parameters.

    Returns:
        VaspInputs for the material.

    Raises:
        ImportError: If mp-api not installed.
        ValueError: If material not found.
    """
    from crystalmath.integrations.pymatgen_bridge import structure_from_mp

    structure = structure_from_mp(mp_id)
    generator = VaspInputGenerator(
        structure,
        preset=preset,
        encut=encut,
        kppra=kppra,
        **incar_overrides,
    )
    return generator.generate()
