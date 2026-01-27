"""Band structure workflow for electronic structure calculations.

Orchestrates band structure + DOS calculations from a converged SCF wavefunction.
Provides JSON-serializable interface for Rust TUI bridge.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class BandPathPreset(str, Enum):
    """Preset k-point paths for common crystal systems."""

    AUTO = "auto"  # Auto-detect from structure
    CUBIC = "cubic"  # Gamma-X-M-Gamma-R-X
    FCC = "fcc"  # Gamma-X-W-K-Gamma-L-U-W-L-K
    BCC = "bcc"  # Gamma-H-N-Gamma-P-H
    HEXAGONAL = "hexagonal"  # Gamma-M-K-Gamma-A-L-H-A
    TETRAGONAL = "tetragonal"  # Gamma-X-M-Gamma-Z-R-A-Z
    CUSTOM = "custom"  # User-specified path


# Standard high-symmetry points for common crystal systems
HIGH_SYMMETRY_POINTS: dict[str, dict[str, list[float]]] = {
    "cubic": {
        "Gamma": [0.0, 0.0, 0.0],
        "X": [0.5, 0.0, 0.0],
        "M": [0.5, 0.5, 0.0],
        "R": [0.5, 0.5, 0.5],
    },
    "fcc": {
        "Gamma": [0.0, 0.0, 0.0],
        "X": [0.5, 0.0, 0.5],
        "W": [0.5, 0.25, 0.75],
        "K": [0.375, 0.375, 0.75],
        "L": [0.5, 0.5, 0.5],
        "U": [0.625, 0.25, 0.625],
    },
    "bcc": {
        "Gamma": [0.0, 0.0, 0.0],
        "H": [0.5, -0.5, 0.5],
        "N": [0.0, 0.0, 0.5],
        "P": [0.25, 0.25, 0.25],
    },
    "hexagonal": {
        "Gamma": [0.0, 0.0, 0.0],
        "M": [0.5, 0.0, 0.0],
        "K": [1.0 / 3.0, 1.0 / 3.0, 0.0],
        "A": [0.0, 0.0, 0.5],
        "L": [0.5, 0.0, 0.5],
        "H": [1.0 / 3.0, 1.0 / 3.0, 0.5],
    },
    "tetragonal": {
        "Gamma": [0.0, 0.0, 0.0],
        "X": [0.5, 0.0, 0.0],
        "M": [0.5, 0.5, 0.0],
        "Z": [0.0, 0.0, 0.5],
        "R": [0.5, 0.0, 0.5],
        "A": [0.5, 0.5, 0.5],
    },
}

# Standard k-paths for common crystal systems
STANDARD_PATHS: dict[str, list[str]] = {
    "cubic": ["Gamma", "X", "M", "Gamma", "R", "X"],
    "fcc": ["Gamma", "X", "W", "K", "Gamma", "L", "U", "W", "L", "K"],
    "bcc": ["Gamma", "H", "N", "Gamma", "P", "H"],
    "hexagonal": ["Gamma", "M", "K", "Gamma", "A", "L", "H", "A"],
    "tetragonal": ["Gamma", "X", "M", "Gamma", "Z", "R", "A", "Z"],
}


@dataclass
class BandStructureConfig:
    """Configuration for band structure calculation.

    Attributes:
        source_job_pk: PK of converged SCF job to use as starting point
        band_path: K-point path preset or custom path string
        custom_path: Custom k-point path (e.g., "Gamma X M Gamma")
        kpoints_per_segment: Number of k-points per path segment
        compute_dos: Whether to compute DOS as well
        dos_mesh: K-point mesh for DOS (e.g., [12, 12, 12])
        first_band: First band to include (1-indexed, default: all)
        last_band: Last band to include (-1 for all)
        dft_code: DFT code (crystal, vasp, qe)
        cluster_id: Cluster to run on (None = local)
        name_prefix: Prefix for job names
    """

    source_job_pk: int
    band_path: BandPathPreset = BandPathPreset.AUTO
    custom_path: str | None = None
    kpoints_per_segment: int = 50
    compute_dos: bool = True
    dos_mesh: list[int] = field(default_factory=lambda: [12, 12, 12])
    first_band: int = 1
    last_band: int = -1  # All bands
    dft_code: str = "crystal"
    cluster_id: int | None = None
    name_prefix: str = "bands"


@dataclass
class BandStructureResult:
    """Results of band structure calculation.

    Attributes:
        status: Workflow status (pending, running, completed, failed)
        band_job_pk: PK of band structure job
        dos_job_pk: PK of DOS job (if computed)
        fermi_energy_ev: Fermi energy in eV
        band_gap_ev: Band gap in eV (0 for metals)
        band_gap_type: direct or indirect
        is_metal: Whether system is metallic
        vbm_ev: Valence band maximum
        cbm_ev: Conduction band minimum
        n_bands: Number of bands computed
        kpath_labels: Labels of high-symmetry points
        error_message: Error message if failed
    """

    status: str = "pending"
    band_job_pk: int | None = None
    dos_job_pk: int | None = None
    fermi_energy_ev: float | None = None
    band_gap_ev: float | None = None
    band_gap_type: str | None = None
    is_metal: bool | None = None
    vbm_ev: float | None = None
    cbm_ev: float | None = None
    n_bands: int | None = None
    kpath_labels: list[str] = field(default_factory=list)
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "status": self.status,
            "band_job_pk": self.band_job_pk,
            "dos_job_pk": self.dos_job_pk,
            "fermi_energy_ev": self.fermi_energy_ev,
            "band_gap_ev": self.band_gap_ev,
            "band_gap_type": self.band_gap_type,
            "is_metal": self.is_metal,
            "vbm_ev": self.vbm_ev,
            "cbm_ev": self.cbm_ev,
            "n_bands": self.n_bands,
            "kpath_labels": self.kpath_labels,
            "error_message": self.error_message,
        }


class BandStructureWorkflow:
    """Band structure workflow manager.

    Orchestrates band structure and DOS calculations from a converged
    SCF wavefunction. Generates k-paths, manages job submission,
    and collects results.

    Example:
        config = BandStructureConfig(
            source_job_pk=123,
            band_path=BandPathPreset.FCC,
            compute_dos=True
        )
        workflow = BandStructureWorkflow(config)

        # Generate band structure input
        band_input = workflow.generate_band_input()

        # After jobs complete, update results
        workflow.update_result(band_gap_ev=1.5, is_metal=False)
    """

    def __init__(self, config: BandStructureConfig) -> None:
        """Initialize band structure workflow.

        Args:
            config: Workflow configuration
        """
        self.config = config
        self.result = BandStructureResult()

    def generate_kpath(self, crystal_system: str | None = None) -> list[tuple[str, list[float]]]:
        """Generate k-point path for band structure.

        Args:
            crystal_system: Crystal system (cubic, fcc, bcc, hexagonal, tetragonal)
                           If None, uses config.band_path preset

        Returns:
            List of (label, k-point) tuples along the path
        """
        if self.config.band_path == BandPathPreset.CUSTOM and self.config.custom_path:
            return self._parse_custom_path(self.config.custom_path)

        # Determine crystal system
        if crystal_system is None:
            system = self.config.band_path.value
            if system == "auto":
                system = "cubic"  # Default fallback
        else:
            system = crystal_system.lower()

        # Get high-symmetry points and path
        hs_points = HIGH_SYMMETRY_POINTS.get(system, HIGH_SYMMETRY_POINTS["cubic"])
        path_labels = STANDARD_PATHS.get(system, STANDARD_PATHS["cubic"])

        # Build path with coordinates
        path = []
        for label in path_labels:
            if label in hs_points:
                path.append((label, hs_points[label]))

        self.result.kpath_labels = path_labels
        return path

    def _parse_custom_path(self, path_string: str) -> list[tuple[str, list[float]]]:
        """Parse custom k-point path string.

        Args:
            path_string: Space-separated list of high-symmetry point labels
                        e.g., "Gamma X M Gamma"

        Returns:
            List of (label, k-point) tuples
        """
        labels = path_string.split()
        path = []

        # Try to find points in all crystal system definitions
        all_points: dict[str, list[float]] = {}
        for system_points in HIGH_SYMMETRY_POINTS.values():
            all_points.update(system_points)

        for label in labels:
            # Handle Gamma variations
            if label.lower() in ("gamma", "g", "\\gamma"):
                label = "Gamma"

            if label in all_points:
                path.append((label, all_points[label]))
            else:
                logger.warning(f"Unknown high-symmetry point: {label}")

        self.result.kpath_labels = [p[0] for p in path]
        return path

    def generate_band_input_crystal(self) -> str:
        """Generate CRYSTAL BAND input block.

        Returns:
            CRYSTAL properties input for band structure calculation
        """
        kpath = self.generate_kpath()

        lines = ["BAND"]
        # BAND keyword format:
        # BAND
        # title
        # n_segments n_kpoints first_band last_band
        # k1x k1y k1z k2x k2y k2z  (for each segment)

        title = f"Band structure: {' -> '.join(self.result.kpath_labels)}"
        lines.append(title)

        n_segments = len(kpath) - 1
        first_band = self.config.first_band
        last_band = self.config.last_band

        lines.append(f"{n_segments} {self.config.kpoints_per_segment} {first_band} {last_band}")

        # Add segments
        for i in range(len(kpath) - 1):
            start = kpath[i][1]
            end = kpath[i + 1][1]
            lines.append(
                f"{start[0]:.6f} {start[1]:.6f} {start[2]:.6f} "
                f"{end[0]:.6f} {end[1]:.6f} {end[2]:.6f}"
            )

        lines.append("END")
        return "\n".join(lines)

    def generate_dos_input_crystal(self) -> str:
        """Generate CRYSTAL DOSS input block.

        Returns:
            CRYSTAL properties input for DOS calculation
        """
        mesh = self.config.dos_mesh
        first_band = self.config.first_band
        last_band = self.config.last_band

        lines = [
            "DOSS",
            f"{mesh[0]} {mesh[1]} {mesh[2]}",  # Shrinking factors
            f"{first_band} {last_band}",  # Band range
            "1000",  # Number of energy points
            "0.01",  # Gaussian smearing (eV)
            "END",
        ]
        return "\n".join(lines)

    def update_result(
        self,
        *,
        status: str | None = None,
        band_job_pk: int | None = None,
        dos_job_pk: int | None = None,
        fermi_energy_ev: float | None = None,
        band_gap_ev: float | None = None,
        band_gap_type: str | None = None,
        is_metal: bool | None = None,
        vbm_ev: float | None = None,
        cbm_ev: float | None = None,
        n_bands: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update workflow result with job outcomes.

        Args:
            status: Workflow status
            band_job_pk: Band structure job PK
            dos_job_pk: DOS job PK
            fermi_energy_ev: Fermi energy
            band_gap_ev: Band gap
            band_gap_type: Gap type (direct/indirect)
            is_metal: Whether metallic
            vbm_ev: VBM energy
            cbm_ev: CBM energy
            n_bands: Number of bands
            error_message: Error message
        """
        if status is not None:
            self.result.status = status
        if band_job_pk is not None:
            self.result.band_job_pk = band_job_pk
        if dos_job_pk is not None:
            self.result.dos_job_pk = dos_job_pk
        if fermi_energy_ev is not None:
            self.result.fermi_energy_ev = fermi_energy_ev
        if band_gap_ev is not None:
            self.result.band_gap_ev = band_gap_ev
        if band_gap_type is not None:
            self.result.band_gap_type = band_gap_type
        if is_metal is not None:
            self.result.is_metal = is_metal
        if vbm_ev is not None:
            self.result.vbm_ev = vbm_ev
        if cbm_ev is not None:
            self.result.cbm_ev = cbm_ev
        if n_bands is not None:
            self.result.n_bands = n_bands
        if error_message is not None:
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
                    "band_path": self.config.band_path.value,
                    "custom_path": self.config.custom_path,
                    "kpoints_per_segment": self.config.kpoints_per_segment,
                    "compute_dos": self.config.compute_dos,
                    "dos_mesh": self.config.dos_mesh,
                    "first_band": self.config.first_band,
                    "last_band": self.config.last_band,
                    "dft_code": self.config.dft_code,
                    "cluster_id": self.config.cluster_id,
                    "name_prefix": self.config.name_prefix,
                },
                "result": self.result.to_dict(),
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, json_str: str) -> BandStructureWorkflow:
        """Deserialize workflow from JSON.

        Args:
            json_str: JSON string representation

        Returns:
            BandStructureWorkflow instance
        """
        data = json.loads(json_str)
        config_data = data["config"]

        config = BandStructureConfig(
            source_job_pk=config_data["source_job_pk"],
            band_path=BandPathPreset(config_data.get("band_path", "auto")),
            custom_path=config_data.get("custom_path"),
            kpoints_per_segment=config_data.get("kpoints_per_segment", 50),
            compute_dos=config_data.get("compute_dos", True),
            dos_mesh=config_data.get("dos_mesh", [12, 12, 12]),
            first_band=config_data.get("first_band", 1),
            last_band=config_data.get("last_band", -1),
            dft_code=config_data.get("dft_code", "crystal"),
            cluster_id=config_data.get("cluster_id"),
            name_prefix=config_data.get("name_prefix", "bands"),
        )

        workflow = cls(config)

        # Restore result state
        result_data = data.get("result", {})
        workflow.result.status = result_data.get("status", "pending")
        workflow.result.band_job_pk = result_data.get("band_job_pk")
        workflow.result.dos_job_pk = result_data.get("dos_job_pk")
        workflow.result.fermi_energy_ev = result_data.get("fermi_energy_ev")
        workflow.result.band_gap_ev = result_data.get("band_gap_ev")
        workflow.result.band_gap_type = result_data.get("band_gap_type")
        workflow.result.is_metal = result_data.get("is_metal")
        workflow.result.vbm_ev = result_data.get("vbm_ev")
        workflow.result.cbm_ev = result_data.get("cbm_ev")
        workflow.result.n_bands = result_data.get("n_bands")
        workflow.result.kpath_labels = result_data.get("kpath_labels", [])
        workflow.result.error_message = result_data.get("error_message")

        return workflow
