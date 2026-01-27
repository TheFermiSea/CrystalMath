"""Equation of State (EOS) workflow for bulk modulus determination.

Generates a series of volume-scaled structures, runs SCF calculations,
and fits the energy-volume curve to the Birch-Murnaghan equation of state.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EOSConfig:
    """Configuration for EOS calculation.

    Attributes:
        source_job_pk: PK of optimized geometry job (reference structure)
        volume_range: Volume scaling range as (min_scale, max_scale)
        num_points: Number of volume points to calculate
        eos_type: Equation of state type ("birch_murnaghan", "murnaghan", "vinet")
        dft_code: DFT code for calculations
        cluster_id: Cluster to run on (None = local)
        name_prefix: Job name prefix
    """

    source_job_pk: int
    volume_range: tuple[float, float] = (0.90, 1.10)  # +/- 10% volume
    num_points: int = 7
    eos_type: str = "birch_murnaghan"
    dft_code: str = "crystal"
    cluster_id: int | None = None
    name_prefix: str = "eos"


@dataclass
class EOSPoint:
    """A single point in the EOS calculation."""

    volume_scale: float  # V/V0
    volume: float | None = None  # Absolute volume (A^3)
    energy: float | None = None  # Total energy (eV or Hartree)
    pressure: float | None = None  # Pressure (GPa)
    job_pk: int | None = None
    status: str = "pending"  # pending, running, completed, failed
    error_message: str | None = None


@dataclass
class EOSResult:
    """Results from EOS fitting.

    Attributes:
        status: Workflow status
        points: List of calculated EOS points
        v0: Equilibrium volume (A^3)
        e0: Equilibrium energy (eV)
        b0: Bulk modulus (GPa)
        bp: Bulk modulus pressure derivative (dimensionless)
        eos_type: Type of EOS used for fitting
        residual: Fitting residual
        error_message: Error message if failed
    """

    status: str = "pending"
    points: list[EOSPoint] = field(default_factory=list)
    v0: float | None = None
    e0: float | None = None
    b0: float | None = None  # Bulk modulus in GPa
    bp: float | None = None  # B' (pressure derivative)
    eos_type: str = "birch_murnaghan"
    residual: float | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "status": self.status,
            "points": [
                {
                    "volume_scale": p.volume_scale,
                    "volume": p.volume,
                    "energy": p.energy,
                    "pressure": p.pressure,
                    "job_pk": p.job_pk,
                    "status": p.status,
                    "error_message": p.error_message,
                }
                for p in self.points
            ],
            "v0": self.v0,
            "e0": self.e0,
            "b0": self.b0,
            "bp": self.bp,
            "eos_type": self.eos_type,
            "residual": self.residual,
            "error_message": self.error_message,
        }


class EOSWorkflow:
    """Equation of State workflow manager.

    Orchestrates volume scaling, SCF calculations, and Birch-Murnaghan fitting
    to extract bulk modulus and equilibrium volume.

    Example:
        config = EOSConfig(
            source_job_pk=123,
            volume_range=(0.90, 1.10),
            num_points=7
        )
        workflow = EOSWorkflow(config)

        # Generate scaled structures
        structures = workflow.generate_volume_points(reference_cell, positions)

        # After calculations complete
        workflow.fit_eos()
        print(f"Bulk modulus: {workflow.result.b0:.1f} GPa")
    """

    def __init__(self, config: EOSConfig) -> None:
        """Initialize EOS workflow.

        Args:
            config: Workflow configuration
        """
        self.config = config
        self.result = EOSResult(eos_type=config.eos_type)
        self._reference_volume: float | None = None

    def generate_volume_points(
        self,
        cell: list[list[float]],
        positions: list[list[float]],
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        """Generate structures at different volumes.

        Scales the cell isotropically to achieve target volumes.

        Args:
            cell: 3x3 reference lattice vectors
            positions: Fractional atomic positions
            symbols: Atomic symbols

        Returns:
            List of scaled structure dicts
        """
        import numpy as np

        cell_array = np.array(cell)

        # Calculate reference volume
        v0 = abs(np.linalg.det(cell_array))
        self._reference_volume = v0

        # Generate volume scales
        v_min, v_max = self.config.volume_range
        volume_scales = np.linspace(v_min, v_max, self.config.num_points)

        structures = []

        for i, v_scale in enumerate(volume_scales):
            # Scale factor for cell vectors (cubic root of volume scale)
            cell_scale = v_scale ** (1.0 / 3.0)

            # Scale the cell
            scaled_cell = cell_array * cell_scale

            # Calculate actual volume
            volume = v0 * v_scale

            structure = {
                "cell": scaled_cell.tolist(),
                "scaled_positions": positions,  # Fractional coords unchanged
                "symbols": symbols,
                "volume_scale": float(v_scale),
                "volume": float(volume),
                "point_index": i,
            }
            structures.append(structure)

            # Track in result
            self.result.points.append(
                EOSPoint(
                    volume_scale=float(v_scale),
                    volume=float(volume),
                )
            )

        self.result.status = "structures_generated"
        return structures

    def update_point(
        self,
        index: int,
        *,
        energy: float | None = None,
        pressure: float | None = None,
        job_pk: int | None = None,
        status: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update an EOS point with calculation results.

        Args:
            index: Point index
            energy: Total energy
            pressure: Pressure
            job_pk: Job PK
            status: Calculation status
            error_message: Error message if failed
        """
        if 0 <= index < len(self.result.points):
            point = self.result.points[index]
            if energy is not None:
                point.energy = energy
            if pressure is not None:
                point.pressure = pressure
            if job_pk is not None:
                point.job_pk = job_pk
            if status is not None:
                point.status = status
            if error_message is not None:
                point.error_message = error_message

    def all_points_complete(self) -> bool:
        """Check if all calculations are complete."""
        return all(p.status in ("completed", "failed") for p in self.result.points)

    def fit_eos(self) -> EOSResult:
        """Fit energy-volume data to equation of state.

        Uses the Birch-Murnaghan equation of state by default.

        Returns:
            Updated EOSResult with fitted parameters
        """
        # Collect completed points
        volumes = []
        energies = []

        for p in self.result.points:
            if p.status == "completed" and p.energy is not None and p.volume is not None:
                volumes.append(p.volume)
                energies.append(p.energy)

        if len(volumes) < 4:
            self.result.error_message = (
                f"Insufficient data for EOS fitting ({len(volumes)} points, need >= 4)"
            )
            self.result.status = "failed"
            return self.result

        try:
            # Try using ASE's EOS fitting
            from ase.eos import EquationOfState

            eos = EquationOfState(volumes, energies, eos=self.config.eos_type)
            v0, e0, b0 = eos.fit()

            self.result.v0 = float(v0)
            self.result.e0 = float(e0)
            # B0 from ASE is in eV/A^3, convert to GPa
            # 1 eV/A^3 = 160.2176634 GPa
            self.result.b0 = float(b0) * 160.2176634

            # Get B' from polynomial coefficients if available
            if hasattr(eos, "eos_parameters") and len(eos.eos_parameters) > 3:
                self.result.bp = float(eos.eos_parameters[3])
            else:
                self.result.bp = 4.0  # Default assumption

            self.result.status = "completed"
            logger.info(
                f"EOS fit: V0={self.result.v0:.2f} A^3, "
                f"E0={self.result.e0:.4f} eV, "
                f"B0={self.result.b0:.1f} GPa"
            )

        except ImportError:
            # Fallback to simple Birch-Murnaghan fit
            logger.warning("ASE not available, using simple polynomial fit")
            self._fit_polynomial(volumes, energies)

        except Exception as e:
            logger.error(f"EOS fitting failed: {e}")
            self.result.error_message = str(e)
            self.result.status = "failed"

        return self.result

    def _fit_polynomial(
        self,
        volumes: list[float],
        energies: list[float],
    ) -> None:
        """Simple polynomial fit as fallback.

        Fits E(V) to a parabola to extract approximate V0 and B0.
        """
        import numpy as np

        v = np.array(volumes)
        e = np.array(energies)

        # Fit to parabola: E = a*V^2 + b*V + c
        coeffs = np.polyfit(v, e, 2)
        a, b, c = coeffs

        # Minimum at V0 = -b/(2a)
        v0 = -b / (2 * a)
        e0 = c - b**2 / (4 * a)

        # Second derivative gives bulk modulus
        # B = V * d2E/dV2 = V * 2a
        b0_ev_a3 = v0 * 2 * a
        b0_gpa = abs(b0_ev_a3) * 160.2176634

        self.result.v0 = float(v0)
        self.result.e0 = float(e0)
        self.result.b0 = b0_gpa
        self.result.bp = 4.0  # Assumed

        # Calculate residual
        e_fit = np.polyval(coeffs, v)
        self.result.residual = float(np.sqrt(np.mean((e - e_fit) ** 2)))

        self.result.status = "completed"

    def to_json(self) -> str:
        """Serialize workflow to JSON.

        Returns:
            JSON string representation
        """
        return json.dumps(
            {
                "config": {
                    "source_job_pk": self.config.source_job_pk,
                    "volume_range": list(self.config.volume_range),
                    "num_points": self.config.num_points,
                    "eos_type": self.config.eos_type,
                    "dft_code": self.config.dft_code,
                    "cluster_id": self.config.cluster_id,
                    "name_prefix": self.config.name_prefix,
                },
                "result": self.result.to_dict(),
                "reference_volume": self._reference_volume,
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, json_str: str) -> EOSWorkflow:
        """Deserialize workflow from JSON.

        Args:
            json_str: JSON string representation

        Returns:
            EOSWorkflow instance
        """
        data = json.loads(json_str)
        config_data = data["config"]

        config = EOSConfig(
            source_job_pk=config_data["source_job_pk"],
            volume_range=tuple(config_data.get("volume_range", [0.90, 1.10])),
            num_points=config_data.get("num_points", 7),
            eos_type=config_data.get("eos_type", "birch_murnaghan"),
            dft_code=config_data.get("dft_code", "crystal"),
            cluster_id=config_data.get("cluster_id"),
            name_prefix=config_data.get("name_prefix", "eos"),
        )

        workflow = cls(config)
        workflow._reference_volume = data.get("reference_volume")

        # Restore result
        result_data = data.get("result", {})
        workflow.result.status = result_data.get("status", "pending")
        workflow.result.v0 = result_data.get("v0")
        workflow.result.e0 = result_data.get("e0")
        workflow.result.b0 = result_data.get("b0")
        workflow.result.bp = result_data.get("bp")
        workflow.result.eos_type = result_data.get("eos_type", config.eos_type)
        workflow.result.residual = result_data.get("residual")
        workflow.result.error_message = result_data.get("error_message")

        # Restore points
        for p_data in result_data.get("points", []):
            workflow.result.points.append(
                EOSPoint(
                    volume_scale=p_data["volume_scale"],
                    volume=p_data.get("volume"),
                    energy=p_data.get("energy"),
                    pressure=p_data.get("pressure"),
                    job_pk=p_data.get("job_pk"),
                    status=p_data.get("status", "pending"),
                    error_message=p_data.get("error_message"),
                )
            )

        return workflow
