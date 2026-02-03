"""KPOINTS file generation utilities."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Tuple

if TYPE_CHECKING:
    import numpy as np
    from pymatgen.core import Structure


@dataclass
class KpointsMesh:
    """Monkhorst-Pack k-point mesh specification.

    Attributes:
        mesh: k-point grid dimensions (ka, kb, kc).
        shift: Grid shift in fractional coordinates (default: Gamma-centered).
    """

    mesh: Tuple[int, int, int]
    shift: Tuple[float, float, float] = (0.0, 0.0, 0.0)

    def to_string(self) -> str:
        """Generate KPOINTS file content.

        Returns:
            Complete KPOINTS file as a string.
        """
        lines = [
            "Automatic mesh",
            "0",  # 0 = automatic generation
            "Monkhorst-Pack",
            f"{self.mesh[0]}  {self.mesh[1]}  {self.mesh[2]}",
            f"{self.shift[0]}  {self.shift[1]}  {self.shift[2]}",
        ]
        return "\n".join(lines)


@dataclass
class KpointsBuilder:
    """Build KPOINTS files with automatic density calculation."""

    @staticmethod
    def from_density(structure: "Structure", kppra: int = 1000) -> KpointsMesh:
        """Generate mesh from k-point density.

        Uses k-points per reciprocal atom (KPPRA) to determine appropriate
        mesh density, distributing k-points proportionally to reciprocal
        lattice vector lengths.

        Args:
            structure: pymatgen Structure object.
            kppra: k-points per reciprocal atom (default 1000).
                   Higher values = denser mesh = more accurate but slower.
                   Typical values: 500 (fast), 1000 (standard), 2000+ (accurate).

        Returns:
            KpointsMesh with appropriate density.
        """
        import numpy as np

        lattice = structure.lattice
        lengths = np.array(lattice.reciprocal_lattice.abc)

        # Number of atoms
        natoms = len(structure)

        # Target total k-points
        target_kpts = kppra / natoms

        # Distribute proportionally to reciprocal lengths
        # Longer reciprocal vector = more k-points needed
        ratio = lengths / min(lengths)
        base = (target_kpts / np.prod(ratio)) ** (1 / 3)
        mesh_list = [max(1, int(round(base * r))) for r in ratio]
        mesh = (mesh_list[0], mesh_list[1], mesh_list[2])

        return KpointsMesh(mesh=mesh)

    @staticmethod
    def gamma_centered(ka: int, kb: int, kc: int) -> KpointsMesh:
        """Create Gamma-centered mesh with explicit dimensions.

        Args:
            ka: k-points along a* direction.
            kb: k-points along b* direction.
            kc: k-points along c* direction.

        Returns:
            Gamma-centered KpointsMesh.
        """
        return KpointsMesh(mesh=(ka, kb, kc), shift=(0.0, 0.0, 0.0))

    @staticmethod
    def monkhorst_pack(ka: int, kb: int, kc: int) -> KpointsMesh:
        """Create shifted Monkhorst-Pack mesh.

        Standard MP mesh is shifted by half a grid spacing.

        Args:
            ka: k-points along a* direction.
            kb: k-points along b* direction.
            kc: k-points along c* direction.

        Returns:
            Shifted KpointsMesh.
        """
        # Shift by 0.5/k for proper MP centering
        shift = (0.5 / ka if ka > 1 else 0, 0.5 / kb if kb > 1 else 0, 0.5 / kc if kc > 1 else 0)
        return KpointsMesh(mesh=(ka, kb, kc), shift=shift)

    @staticmethod
    def for_slab(structure: "Structure", kppra: int = 1000) -> KpointsMesh:
        """Generate mesh appropriate for slab calculations.

        Uses only 1 k-point perpendicular to the slab surface.
        Assumes c-axis is the surface normal direction.

        Args:
            structure: pymatgen Structure (slab geometry).
            kppra: k-points per reciprocal atom for in-plane directions.

        Returns:
            KpointsMesh with 1 k-point in c direction.
        """
        mesh = KpointsBuilder.from_density(structure, kppra)
        return KpointsMesh(mesh=(mesh.mesh[0], mesh.mesh[1], 1))

    @staticmethod
    def for_molecule(structure: "Structure") -> KpointsMesh:
        """Generate mesh for molecular calculations.

        Uses Gamma-point only sampling appropriate for isolated molecules
        in large supercells.

        Args:
            structure: pymatgen Structure (molecule in box).

        Returns:
            Gamma-point only KpointsMesh.
        """
        return KpointsMesh(mesh=(1, 1, 1))


def generate_band_path_kpoints(
    structure: "Structure", num_kpts: int = 40, line_density: int = 20
) -> str:
    """Generate KPOINTS for band structure calculation.

    Uses pymatgen's high-symmetry path generation.

    Args:
        structure: pymatgen Structure object.
        num_kpts: Total number of k-points (approximate).
        line_density: k-points per segment.

    Returns:
        KPOINTS file content for band structure.
    """
    from pymatgen.symmetry.bandstructure import HighSymmKpath

    kpath = HighSymmKpath(structure)
    kpoints: List[str] = ["Band structure k-path"]
    kpoints.append(str(line_density))
    kpoints.append("Line-mode")
    kpoints.append("Reciprocal")

    # Get path segments
    path = kpath.kpath
    points = path["kpoints"]
    segments = path["path"]

    for segment in segments:
        for i, label in enumerate(segment):
            coord = points[label]
            coord_str = f"  {coord[0]:.6f}  {coord[1]:.6f}  {coord[2]:.6f}"
            if i == 0:
                kpoints.append(f"{coord_str}  ! {label}")
            else:
                kpoints.append(f"{coord_str}  ! {label}")
                kpoints.append("")  # Empty line between segments

    return "\n".join(kpoints)
