"""
Protocol schema definitions for CRYSTAL23 workflows.

Defines the structure and validation for protocol YAML files.
Each protocol type has specific required and optional fields
with sensible defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProtocolLevel(Enum):
    """Standard protocol levels."""

    FAST = "fast"
    MODERATE = "moderate"
    PRECISE = "precise"
    CUSTOM = "custom"


@dataclass
class SCFSettings:
    """SCF convergence settings."""

    maxcycle: int = 100
    toldee: int = 7  # Energy tolerance (10^-toldee Hartree)
    fmixing: int = 40  # Mixing percentage
    anderson: bool = False  # Anderson acceleration
    diis: bool = True  # DIIS acceleration
    smearing: bool = False  # Fermi smearing for metals
    smearing_width: float = 0.01  # eV
    spinpol: bool = False  # Spin-polarized
    level_shift: float | None = None  # Level shifting for gap problems


@dataclass
class KPointsSettings:
    """K-point mesh settings."""

    mesh: list[int] = field(default_factory=lambda: [6, 6, 6])
    offset: list[int] = field(default_factory=lambda: [0, 0, 0])
    density: float | None = None  # Alternative: k-points per Å⁻¹


@dataclass
class OptimizationSettings:
    """Geometry optimization settings."""

    type: str = "FULLOPTG"  # FULLOPTG, ATOMONLY, CELLONLY
    maxcycle: int = 100
    toldeg: float = 0.0003  # Gradient tolerance (Hartree/Bohr)
    toldex: float = 0.0012  # Displacement tolerance (Bohr)
    fix_volume: bool = False
    fix_shape: bool = False


@dataclass
class ResourceSettings:
    """Computational resource settings."""

    num_machines: int = 1
    num_mpiprocs_per_machine: int = 1
    max_wallclock_seconds: int = 7200
    memory_mb: int | None = None


@dataclass
class BaseProtocol:
    """
    Base protocol for all CRYSTAL23 calculations.

    Contains common settings shared across workflow types.
    """

    name: str
    description: str
    level: ProtocolLevel = ProtocolLevel.MODERATE
    scf: SCFSettings = field(default_factory=SCFSettings)
    kpoints: KPointsSettings = field(default_factory=KPointsSettings)
    resources: ResourceSettings = field(default_factory=ResourceSettings)
    basis_set: str = "pob-tzvp"  # Default basis set recommendation
    pseudopotential: str | None = None  # ECP if needed
    clean_workdir: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseProtocol:
        """Create protocol from dictionary."""
        scf_data = data.pop("scf", {})
        kpoints_data = data.pop("kpoints", {})
        resources_data = data.pop("resources", {})

        # Handle level enum
        if "level" in data:
            data["level"] = ProtocolLevel(data["level"])

        return cls(
            scf=SCFSettings(**scf_data),
            kpoints=KPointsSettings(**kpoints_data),
            resources=ResourceSettings(**resources_data),
            **data,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert protocol to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "level": self.level.value,
            "scf": {
                "maxcycle": self.scf.maxcycle,
                "toldee": self.scf.toldee,
                "fmixing": self.scf.fmixing,
                "anderson": self.scf.anderson,
                "diis": self.scf.diis,
                "smearing": self.scf.smearing,
                "smearing_width": self.scf.smearing_width,
                "spinpol": self.scf.spinpol,
                "level_shift": self.scf.level_shift,
            },
            "kpoints": {
                "mesh": self.kpoints.mesh,
                "offset": self.kpoints.offset,
                "density": self.kpoints.density,
            },
            "resources": {
                "num_machines": self.resources.num_machines,
                "num_mpiprocs_per_machine": self.resources.num_mpiprocs_per_machine,
                "max_wallclock_seconds": self.resources.max_wallclock_seconds,
                "memory_mb": self.resources.memory_mb,
            },
            "basis_set": self.basis_set,
            "pseudopotential": self.pseudopotential,
            "clean_workdir": self.clean_workdir,
        }


@dataclass
class SCFProtocol(BaseProtocol):
    """Protocol for single-point SCF calculations."""

    calculate_forces: bool = False
    calculate_stress: bool = False
    store_wavefunction: bool = True


@dataclass
class RelaxationProtocol(BaseProtocol):
    """Protocol for geometry optimization calculations."""

    optimization: OptimizationSettings = field(default_factory=OptimizationSettings)
    relax_type: str = "positions_cell"  # positions, cell, positions_cell
    spin_type: str = "none"  # none, collinear, spin_orbit
    electronic_type: str = "automatic"  # metal, insulator, automatic

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RelaxationProtocol:
        """Create protocol from dictionary."""
        scf_data = data.pop("scf", {})
        kpoints_data = data.pop("kpoints", {})
        resources_data = data.pop("resources", {})
        opt_data = data.pop("optimization", {})

        if "level" in data:
            data["level"] = ProtocolLevel(data["level"])

        return cls(
            scf=SCFSettings(**scf_data),
            kpoints=KPointsSettings(**kpoints_data),
            resources=ResourceSettings(**resources_data),
            optimization=OptimizationSettings(**opt_data),
            **data,
        )


@dataclass
class BandStructureProtocol(BaseProtocol):
    """Protocol for band structure calculations."""

    kpoints_distance: float = 0.05  # K-point spacing (1/Å)
    crystal_system: str | None = None  # Auto-detect if None
    first_band: int = 1
    last_band: int = -1  # -1 means all bands
    run_scf: bool = True  # Run SCF or use existing wavefunction

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BandStructureProtocol:
        """Create protocol from dictionary."""
        scf_data = data.pop("scf", {})
        kpoints_data = data.pop("kpoints", {})
        resources_data = data.pop("resources", {})

        if "level" in data:
            data["level"] = ProtocolLevel(data["level"])

        return cls(
            scf=SCFSettings(**scf_data),
            kpoints=KPointsSettings(**kpoints_data),
            resources=ResourceSettings(**resources_data),
            **data,
        )


@dataclass
class DOSProtocol(BaseProtocol):
    """Protocol for density of states calculations."""

    energy_min: float = -10.0  # eV relative to Fermi
    energy_max: float = 5.0
    n_energy_points: int = 1001
    smearing_width: float = 0.1  # Gaussian smearing (eV)
    compute_pdos: bool = False  # Projected DOS
    pdos_atoms: list[int] | None = None  # Atom indices for PDOS
    run_scf: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DOSProtocol:
        """Create protocol from dictionary."""
        scf_data = data.pop("scf", {})
        kpoints_data = data.pop("kpoints", {})
        resources_data = data.pop("resources", {})

        if "level" in data:
            data["level"] = ProtocolLevel(data["level"])

        return cls(
            scf=SCFSettings(**scf_data),
            kpoints=KPointsSettings(**kpoints_data),
            resources=ResourceSettings(**resources_data),
            **data,
        )


# Pre-defined protocol instances for common use cases
FAST_SCF = SCFProtocol(
    name="fast",
    description="Fast SCF for initial exploration",
    level=ProtocolLevel.FAST,
    scf=SCFSettings(maxcycle=50, toldee=6, fmixing=50),
    kpoints=KPointsSettings(mesh=[4, 4, 4]),
    resources=ResourceSettings(max_wallclock_seconds=1800),
    basis_set="sto-3g",
)

MODERATE_SCF = SCFProtocol(
    name="moderate",
    description="Balanced accuracy and speed (default)",
    level=ProtocolLevel.MODERATE,
    scf=SCFSettings(maxcycle=100, toldee=7, fmixing=40),
    kpoints=KPointsSettings(mesh=[6, 6, 6]),
    resources=ResourceSettings(max_wallclock_seconds=7200),
    basis_set="pob-tzvp",
)

PRECISE_SCF = SCFProtocol(
    name="precise",
    description="High accuracy for publication-quality results",
    level=ProtocolLevel.PRECISE,
    scf=SCFSettings(maxcycle=200, toldee=8, fmixing=30),
    kpoints=KPointsSettings(mesh=[8, 8, 8]),
    resources=ResourceSettings(max_wallclock_seconds=28800),
    basis_set="pob-qzvp",
)

# Registry of built-in protocols
BUILTIN_PROTOCOLS: dict[str, BaseProtocol] = {
    "fast": FAST_SCF,
    "moderate": MODERATE_SCF,
    "precise": PRECISE_SCF,
}
