"""Phonon calculation workflow using finite displacement method.

Orchestrates phonon calculations via phonopy or direct CRYSTAL phonon keywords.
Manages displacement generation, force calculations, and post-processing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class PhononMethod(str, Enum):
    """Methods for phonon calculation."""

    PHONOPY = "phonopy"  # External phonopy with finite displacements
    CRYSTAL_FD = "crystal_fd"  # CRYSTAL finite displacement
    CRYSTAL_DFPT = "crystal_dfpt"  # CRYSTAL DFPT (linear response)


class PhononDFTCode(str, Enum):
    """DFT codes for force calculations in phonopy workflow."""

    CRYSTAL = "crystal"
    VASP = "vasp"
    QE = "qe"


@dataclass
class PhononConfig:
    """Configuration for phonon workflow.

    Attributes:
        source_job_pk: PK of optimized structure job
        method: Phonon calculation method
        supercell_dim: Supercell dimensions for phonopy (e.g., [2, 2, 2])
        displacement_distance: Displacement amplitude in Angstrom
        use_symmetry: Whether to use symmetry to reduce displacements
        mesh: Q-point mesh for DOS/thermal properties
        band_path: Q-point path for dispersion (AUTO or explicit)
        compute_thermal: Whether to compute thermodynamic properties
        tmin: Minimum temperature for thermal properties (K)
        tmax: Maximum temperature (K)
        tstep: Temperature step (K)
        dft_code: DFT code for force calculations
        cluster_id: Cluster to run on (None = local)
        name_prefix: Prefix for job names
    """

    source_job_pk: int
    method: PhononMethod = PhononMethod.PHONOPY
    supercell_dim: list[int] = field(default_factory=lambda: [2, 2, 2])
    displacement_distance: float = 0.01  # Angstrom
    use_symmetry: bool = True
    mesh: list[int] = field(default_factory=lambda: [20, 20, 20])
    band_path: str = "AUTO"
    compute_thermal: bool = True
    tmin: float = 0.0
    tmax: float = 1000.0
    tstep: float = 10.0
    dft_code: PhononDFTCode = PhononDFTCode.CRYSTAL
    cluster_id: int | None = None
    name_prefix: str = "phonon"


@dataclass
class DisplacementPoint:
    """A single displacement in the phonon calculation."""

    index: int  # Displacement number (1-indexed)
    atom_index: int  # Which atom is displaced
    direction: list[float]  # Displacement direction
    job_pk: int | None = None  # PK of force calculation job
    status: str = "pending"  # pending, running, completed, failed
    forces: list[list[float]] | None = None  # Resulting forces on all atoms
    error_message: str | None = None


@dataclass
class PhononResult:
    """Results of phonon workflow.

    Attributes:
        status: Overall workflow status
        n_displacements: Total number of displacement calculations
        displacements: List of displacement points with status
        force_sets_ready: Whether FORCE_SETS is available
        frequencies_at_gamma: Phonon frequencies at Gamma (cm^-1)
        has_imaginary: Whether imaginary frequencies exist
        min_frequency: Minimum phonon frequency
        band_yaml: Path to band.yaml output
        thermal_properties: Thermal properties data
        zero_point_energy_ev: Zero-point vibrational energy
        error_message: Error message if failed
    """

    status: str = "pending"
    n_displacements: int = 0
    displacements: list[DisplacementPoint] = field(default_factory=list)
    force_sets_ready: bool = False
    frequencies_at_gamma: list[float] = field(default_factory=list)
    has_imaginary: bool = False
    min_frequency: float | None = None
    band_yaml: str | None = None
    thermal_properties: dict[str, Any] | None = None
    zero_point_energy_ev: float | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "status": self.status,
            "n_displacements": self.n_displacements,
            "displacements": [
                {
                    "index": d.index,
                    "atom_index": d.atom_index,
                    "direction": d.direction,
                    "job_pk": d.job_pk,
                    "status": d.status,
                    "error_message": d.error_message,
                    # Forces omitted for size - can be retrieved if needed
                }
                for d in self.displacements
            ],
            "force_sets_ready": self.force_sets_ready,
            "frequencies_at_gamma": self.frequencies_at_gamma,
            "has_imaginary": self.has_imaginary,
            "min_frequency": self.min_frequency,
            "band_yaml": self.band_yaml,
            "thermal_properties": self.thermal_properties,
            "zero_point_energy_ev": self.zero_point_energy_ev,
            "error_message": self.error_message,
        }

    @property
    def completed_count(self) -> int:
        """Number of completed displacement calculations."""
        return sum(1 for d in self.displacements if d.status == "completed")

    @property
    def failed_count(self) -> int:
        """Number of failed displacement calculations."""
        return sum(1 for d in self.displacements if d.status == "failed")

    @property
    def progress_percent(self) -> float:
        """Completion progress as percentage."""
        if self.n_displacements == 0:
            return 0.0
        return 100.0 * self.completed_count / self.n_displacements


class PhononWorkflow:
    """Phonon workflow manager using phonopy finite displacement method.

    Orchestrates the complete phonon calculation pipeline:
    1. Generate displaced supercells
    2. Submit force calculations for each displacement
    3. Collect forces and compute force constants
    4. Calculate phonon dispersion and DOS
    5. Compute thermodynamic properties

    Example:
        config = PhononConfig(
            source_job_pk=123,
            supercell_dim=[2, 2, 2],
            method=PhononMethod.PHONOPY
        )
        workflow = PhononWorkflow(config)

        # Generate displacements
        displacements = workflow.generate_displacements(structure)

        # After force calculations complete
        workflow.update_displacement(0, status="completed", forces=[[...]])

        # When all done, analyze
        result = workflow.analyze_results()
    """

    def __init__(self, config: PhononConfig) -> None:
        """Initialize phonon workflow.

        Args:
            config: Workflow configuration
        """
        self.config = config
        self.result = PhononResult()

    def generate_displacements_phonopy(
        self,
        cell: list[list[float]],
        positions: list[list[float]],
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        """Generate displaced structures using phonopy.

        This is a simplified implementation that generates the displacement
        specifications. The actual structure generation would use phonopy's
        Python API if available.

        Args:
            cell: 3x3 lattice vectors
            positions: Fractional coordinates
            symbols: Atomic symbols

        Returns:
            List of displacement specifications with:
                - atom_index: Which atom to displace
                - direction: Displacement direction [dx, dy, dz]
                - displaced_positions: New atomic positions
        """
        displacements = []
        n_atoms = len(positions)
        amp = self.config.displacement_distance

        # Simple finite difference approach:
        # Displace each atom in +x, +y, +z (and -x, -y, -z if symmetry not used)
        disp_count = 0
        directions = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        if not self.config.use_symmetry:
            directions.extend([[-1, 0, 0], [0, -1, 0], [0, 0, -1]])

        for atom_idx in range(n_atoms):
            for direction in directions:
                disp_count += 1

                # Create displaced structure
                new_positions = [list(p) for p in positions]
                for i in range(3):
                    new_positions[atom_idx][i] += direction[i] * amp

                disp = {
                    "index": disp_count,
                    "atom_index": atom_idx,
                    "atom_symbol": symbols[atom_idx],
                    "direction": direction,
                    "amplitude": amp,
                    "displaced_positions": new_positions,
                }
                displacements.append(disp)

                # Track in result
                self.result.displacements.append(
                    DisplacementPoint(
                        index=disp_count,
                        atom_index=atom_idx,
                        direction=direction,
                    )
                )

        self.result.n_displacements = disp_count
        self.result.status = "displacements_generated"
        return displacements

    def generate_crystal_freq_input(self) -> str:
        """Generate CRYSTAL FREQCALC input for direct phonon calculation.

        Returns:
            CRYSTAL input block for frequency calculation at Gamma
        """
        lines = [
            "FREQCALC",
            "INTENS",  # Calculate IR intensities
            "INTRAMAN",  # Calculate Raman intensities
            "END",
        ]
        return "\n".join(lines)

    def generate_crystal_dispersion_input(
        self,
        supercell_dim: list[int] | None = None,
    ) -> str:
        """Generate CRYSTAL SCELPHONO input for phonon dispersion.

        Args:
            supercell_dim: Supercell dimensions (uses config if None)

        Returns:
            CRYSTAL input block for phonon dispersion
        """
        dim = supercell_dim or self.config.supercell_dim

        lines = [
            "SCELPHONO",
            f"{dim[0]} 0 0 0 {dim[1]} 0 0 0 {dim[2]}",  # Supercell matrix
            "DISPERSIO",  # Calculate dispersion
            "BAND",  # Along k-path
            self.config.band_path,  # Path specification
            "END",
        ]
        return "\n".join(lines)

    def update_displacement(
        self,
        index: int,
        *,
        job_pk: int | None = None,
        status: str | None = None,
        forces: list[list[float]] | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update displacement calculation status.

        Args:
            index: Displacement index (0-based)
            job_pk: Job PK
            status: Job status
            forces: Calculated forces on all atoms
            error_message: Error message if failed
        """
        if 0 <= index < len(self.result.displacements):
            disp = self.result.displacements[index]
            if job_pk is not None:
                disp.job_pk = job_pk
            if status is not None:
                disp.status = status
            if forces is not None:
                disp.forces = forces
            if error_message is not None:
                disp.error_message = error_message

    def all_displacements_complete(self) -> bool:
        """Check if all displacement calculations are done."""
        return all(d.status in ("completed", "failed") for d in self.result.displacements)

    def collect_forces(self) -> list[list[list[float]]]:
        """Collect forces from all completed displacement calculations.

        Returns:
            Forces for each displacement: [n_disp, n_atoms, 3]
        """
        forces = []
        for disp in self.result.displacements:
            if disp.status == "completed" and disp.forces is not None:
                forces.append(disp.forces)
        return forces

    def analyze_gamma_frequencies(
        self,
        frequencies: list[float],
        imaginary_threshold: float = -0.5,
    ) -> None:
        """Analyze phonon frequencies at Gamma point.

        Args:
            frequencies: Phonon frequencies in cm^-1
            imaginary_threshold: Threshold for imaginary frequency (negative)
        """
        self.result.frequencies_at_gamma = frequencies

        if frequencies:
            self.result.min_frequency = min(frequencies)
            self.result.has_imaginary = self.result.min_frequency < imaginary_threshold

            if self.result.has_imaginary:
                logger.warning(
                    f"Imaginary frequencies detected: min = {self.result.min_frequency:.2f} cm^-1"
                )

    def compute_zero_point_energy(self, frequencies_cm: list[float]) -> float:
        """Compute zero-point vibrational energy.

        Args:
            frequencies_cm: Phonon frequencies in cm^-1 (positive only)

        Returns:
            Zero-point energy in eV
        """
        # ZPE = (1/2) * sum(h * nu) for all modes
        # h * c = 1.2398e-4 eV*cm (conversion from cm^-1 to eV)
        h_c = 1.2398e-4  # eV*cm

        # Only include positive (real) frequencies
        positive_freqs = [f for f in frequencies_cm if f > 0]
        zpe = 0.5 * sum(f * h_c for f in positive_freqs)

        self.result.zero_point_energy_ev = zpe
        return zpe

    def set_thermal_properties(
        self,
        temperatures: list[float],
        free_energies: list[float],
        entropies: list[float],
        heat_capacities: list[float],
    ) -> None:
        """Store thermal properties from phonopy output.

        Args:
            temperatures: Temperature values (K)
            free_energies: Helmholtz free energy (kJ/mol)
            entropies: Entropy (J/mol/K)
            heat_capacities: Heat capacity Cv (J/mol/K)
        """
        self.result.thermal_properties = {
            "temperature_K": temperatures,
            "free_energy_kJ_mol": free_energies,
            "entropy_J_mol_K": entropies,
            "heat_capacity_J_mol_K": heat_capacities,
        }

    def finalize(self, success: bool = True, error_message: str | None = None) -> None:
        """Mark workflow as complete.

        Args:
            success: Whether workflow completed successfully
            error_message: Error message if failed
        """
        if success:
            self.result.status = "completed"
            self.result.force_sets_ready = True
        else:
            self.result.status = "failed"
            self.result.error_message = error_message

    def to_json(self) -> str:
        """Serialize workflow to JSON.

        Returns:
            JSON string representation
        """
        return json.dumps(
            {
                "config": {
                    "source_job_pk": self.config.source_job_pk,
                    "method": self.config.method.value,
                    "supercell_dim": self.config.supercell_dim,
                    "displacement_distance": self.config.displacement_distance,
                    "use_symmetry": self.config.use_symmetry,
                    "mesh": self.config.mesh,
                    "band_path": self.config.band_path,
                    "compute_thermal": self.config.compute_thermal,
                    "tmin": self.config.tmin,
                    "tmax": self.config.tmax,
                    "tstep": self.config.tstep,
                    "dft_code": self.config.dft_code.value,
                    "cluster_id": self.config.cluster_id,
                    "name_prefix": self.config.name_prefix,
                },
                "result": self.result.to_dict(),
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, json_str: str) -> PhononWorkflow:
        """Deserialize workflow from JSON.

        Args:
            json_str: JSON string representation

        Returns:
            PhononWorkflow instance
        """
        data = json.loads(json_str)
        config_data = data["config"]

        config = PhononConfig(
            source_job_pk=config_data["source_job_pk"],
            method=PhononMethod(config_data.get("method", "phonopy")),
            supercell_dim=config_data.get("supercell_dim", [2, 2, 2]),
            displacement_distance=config_data.get("displacement_distance", 0.01),
            use_symmetry=config_data.get("use_symmetry", True),
            mesh=config_data.get("mesh", [20, 20, 20]),
            band_path=config_data.get("band_path", "AUTO"),
            compute_thermal=config_data.get("compute_thermal", True),
            tmin=config_data.get("tmin", 0.0),
            tmax=config_data.get("tmax", 1000.0),
            tstep=config_data.get("tstep", 10.0),
            dft_code=PhononDFTCode(config_data.get("dft_code", "crystal")),
            cluster_id=config_data.get("cluster_id"),
            name_prefix=config_data.get("name_prefix", "phonon"),
        )

        workflow = cls(config)

        # Restore result state
        result_data = data.get("result", {})
        workflow.result.status = result_data.get("status", "pending")
        workflow.result.n_displacements = result_data.get("n_displacements", 0)
        workflow.result.force_sets_ready = result_data.get("force_sets_ready", False)
        workflow.result.frequencies_at_gamma = result_data.get("frequencies_at_gamma", [])
        workflow.result.has_imaginary = result_data.get("has_imaginary", False)
        workflow.result.min_frequency = result_data.get("min_frequency")
        workflow.result.band_yaml = result_data.get("band_yaml")
        workflow.result.thermal_properties = result_data.get("thermal_properties")
        workflow.result.zero_point_energy_ev = result_data.get("zero_point_energy_ev")
        workflow.result.error_message = result_data.get("error_message")

        # Restore displacement points
        for disp_data in result_data.get("displacements", []):
            workflow.result.displacements.append(
                DisplacementPoint(
                    index=disp_data["index"],
                    atom_index=disp_data["atom_index"],
                    direction=disp_data["direction"],
                    job_pk=disp_data.get("job_pk"),
                    status=disp_data.get("status", "pending"),
                    error_message=disp_data.get("error_message"),
                )
            )

        return workflow
