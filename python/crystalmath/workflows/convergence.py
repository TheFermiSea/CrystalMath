"""Convergence study workflow for automated parameter testing.

Generates a series of calculations with varying parameters (k-points, basis sets,
energy cutoffs) to determine optimal production settings.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ConvergenceParameter(str, Enum):
    """Parameters that can be tested for convergence."""

    KPOINTS = "kpoints"  # k-point mesh density
    SHRINK = "shrink"  # CRYSTAL SHRINK parameter
    BASIS = "basis"  # Basis set quality
    ENCUT = "encut"  # Plane-wave cutoff (VASP/QE)
    ECUTWFC = "ecutwfc"  # Wavefunction cutoff (QE)


@dataclass
class ConvergencePoint:
    """A single point in a convergence study."""

    parameter_value: int | float | str
    energy: float | None = None
    energy_per_atom: float | None = None
    forces_max: float | None = None
    wall_time_seconds: float | None = None
    job_pk: int | None = None
    status: str = "pending"  # pending, running, completed, failed
    error_message: str | None = None


@dataclass
class ConvergenceStudyConfig:
    """Configuration for a convergence study.

    Attributes:
        parameter: Which parameter to test (kpoints, shrink, basis, etc.)
        values: List of parameter values to test
        base_input: Base input file content to modify
        structure_file: Path to structure file (for basis set convergence)
        energy_threshold: Convergence threshold in eV (default: 1 meV/atom)
        dft_code: DFT code to use (crystal, vasp, qe)
        cluster_id: Cluster to run on (None = local)
    """

    parameter: ConvergenceParameter
    values: list[int | float | str]
    base_input: str
    structure_file: str | None = None
    energy_threshold: float = 0.001  # 1 meV/atom
    dft_code: str = "crystal"
    cluster_id: int | None = None
    name_prefix: str = "conv"


@dataclass
class ConvergenceStudyResult:
    """Results of a convergence study.

    Attributes:
        parameter: Which parameter was tested
        points: List of convergence points with results
        converged_value: Recommended value (if converged)
        converged_at_index: Index where convergence was achieved
        recommendation: Human-readable recommendation
    """

    parameter: ConvergenceParameter
    points: list[ConvergencePoint] = field(default_factory=list)
    converged_value: int | float | str | None = None
    converged_at_index: int | None = None
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "parameter": self.parameter.value,
            "points": [
                {
                    "parameter_value": p.parameter_value,
                    "energy": p.energy,
                    "energy_per_atom": p.energy_per_atom,
                    "forces_max": p.forces_max,
                    "wall_time_seconds": p.wall_time_seconds,
                    "job_pk": p.job_pk,
                    "status": p.status,
                    "error_message": p.error_message,
                }
                for p in self.points
            ],
            "converged_value": self.converged_value,
            "converged_at_index": self.converged_at_index,
            "recommendation": self.recommendation,
        }


class ConvergenceStudy:
    """Manages convergence study workflow.

    This class generates input files for convergence testing, tracks
    job submissions, collects results, and determines convergence.

    Example:
        config = ConvergenceStudyConfig(
            parameter=ConvergenceParameter.SHRINK,
            values=[4, 6, 8, 10, 12],
            base_input="MgO\nCRYSTAL\n..."
        )
        study = ConvergenceStudy(config)

        # Generate input files
        inputs = study.generate_inputs()

        # After jobs complete, analyze results
        result = study.analyze_results(energies=[...])
    """

    def __init__(self, config: ConvergenceStudyConfig) -> None:
        """Initialize convergence study.

        Args:
            config: Study configuration
        """
        self.config = config
        self.result = ConvergenceStudyResult(parameter=config.parameter)

        # Initialize points
        for value in config.values:
            self.result.points.append(ConvergencePoint(parameter_value=value))

    def generate_inputs(self) -> list[tuple[str, str]]:
        """Generate input files for each parameter value.

        Returns:
            List of (job_name, input_content) tuples
        """
        inputs = []

        for i, value in enumerate(self.config.values):
            job_name = f"{self.config.name_prefix}_{self.config.parameter.value}_{value}"
            input_content = self._modify_input(value)
            inputs.append((job_name, input_content))

        return inputs

    def _modify_input(self, value: int | float | str) -> str:
        """Modify base input to use specified parameter value.

        Args:
            value: Parameter value to set

        Returns:
            Modified input file content
        """
        base = self.config.base_input
        param = self.config.parameter

        if param == ConvergenceParameter.SHRINK:
            # CRYSTAL SHRINK parameter - replace or add SHRINK line
            return self._modify_crystal_shrink(base, int(value))
        elif param == ConvergenceParameter.KPOINTS:
            # Generic k-points (code-dependent)
            return self._modify_kpoints(base, int(value))
        elif param == ConvergenceParameter.ENCUT:
            # VASP ENCUT
            return self._modify_vasp_encut(base, float(value))
        elif param == ConvergenceParameter.ECUTWFC:
            # QE ecutwfc
            return self._modify_qe_ecutwfc(base, float(value))
        elif param == ConvergenceParameter.BASIS:
            # Basis set - this requires more complex handling
            return base  # Placeholder - basis set changes need structure info

        return base

    def _modify_crystal_shrink(self, input_content: str, shrink: int) -> str:
        """Modify CRYSTAL SHRINK parameter.

        Args:
            input_content: Base input content
            shrink: SHRINK value (same for both meshes)

        Returns:
            Modified input with updated SHRINK line
        """
        import re

        lines = input_content.split("\n")
        modified_lines = []
        shrink_found = False

        for line in lines:
            # Look for SHRINK line (format: SHRINK\nIS1 IS2)
            if line.strip().upper() == "SHRINK":
                modified_lines.append(line)
                shrink_found = True
                continue

            # If previous line was SHRINK, replace the values
            if shrink_found and re.match(r"^\s*\d+\s+\d+", line):
                modified_lines.append(f"{shrink} {shrink}")
                shrink_found = False
                continue

            modified_lines.append(line)

        return "\n".join(modified_lines)

    def _modify_kpoints(self, input_content: str, kpoints: int) -> str:
        """Modify generic k-points setting."""
        # Placeholder - implementation depends on DFT code
        return input_content

    def _modify_vasp_encut(self, input_content: str, encut: float) -> str:
        """Modify VASP ENCUT in INCAR."""
        import re

        # Replace existing ENCUT or add it
        if re.search(r"ENCUT\s*=", input_content, re.IGNORECASE):
            return re.sub(
                r"ENCUT\s*=\s*[\d.]+",
                f"ENCUT = {encut:.1f}",
                input_content,
                flags=re.IGNORECASE,
            )
        else:
            return f"ENCUT = {encut:.1f}\n" + input_content

    def _modify_qe_ecutwfc(self, input_content: str, ecutwfc: float) -> str:
        """Modify QE ecutwfc in input file."""
        import re

        # Replace existing ecutwfc or add it
        if re.search(r"ecutwfc\s*=", input_content, re.IGNORECASE):
            return re.sub(
                r"ecutwfc\s*=\s*[\d.]+",
                f"ecutwfc = {ecutwfc:.1f}",
                input_content,
                flags=re.IGNORECASE,
            )
        else:
            # Add after &system line
            return re.sub(
                r"(&system)",
                f"\\1\n    ecutwfc = {ecutwfc:.1f}",
                input_content,
                flags=re.IGNORECASE,
            )

    def update_point(
        self,
        index: int,
        *,
        energy: float | None = None,
        energy_per_atom: float | None = None,
        forces_max: float | None = None,
        wall_time_seconds: float | None = None,
        job_pk: int | None = None,
        status: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update a convergence point with results.

        Args:
            index: Point index
            energy: Total energy
            energy_per_atom: Energy per atom
            forces_max: Maximum force component
            wall_time_seconds: Wall time
            job_pk: Job primary key
            status: Job status
            error_message: Error message if failed
        """
        point = self.result.points[index]

        if energy is not None:
            point.energy = energy
        if energy_per_atom is not None:
            point.energy_per_atom = energy_per_atom
        if forces_max is not None:
            point.forces_max = forces_max
        if wall_time_seconds is not None:
            point.wall_time_seconds = wall_time_seconds
        if job_pk is not None:
            point.job_pk = job_pk
        if status is not None:
            point.status = status
        if error_message is not None:
            point.error_message = error_message

    def analyze_results(self) -> ConvergenceStudyResult:
        """Analyze convergence and determine optimal parameter.

        Checks if energies have converged within the threshold and
        recommends a production value.

        Returns:
            Updated ConvergenceStudyResult with analysis
        """
        completed_points = [p for p in self.result.points if p.status == "completed"]

        if len(completed_points) < 2:
            self.result.recommendation = (
                "Insufficient completed calculations for convergence analysis."
            )
            return self.result

        # Get energies (prefer per-atom if available)
        energies = []
        for p in self.result.points:
            if p.energy_per_atom is not None:
                energies.append(p.energy_per_atom)
            elif p.energy is not None:
                energies.append(p.energy)
            else:
                energies.append(None)

        # Find convergence point
        threshold = self.config.energy_threshold
        converged_idx = None

        for i in range(1, len(energies)):
            if energies[i] is None or energies[i - 1] is None:
                continue

            diff = abs(energies[i] - energies[i - 1])
            if diff < threshold:
                # Check if subsequent points also converged
                all_converged = True
                for j in range(i, len(energies)):
                    if energies[j] is None:
                        continue
                    if abs(energies[j] - energies[i]) > threshold:
                        all_converged = False
                        break

                if all_converged:
                    converged_idx = i
                    break

        if converged_idx is not None:
            self.result.converged_at_index = converged_idx
            self.result.converged_value = self.result.points[converged_idx].parameter_value
            self.result.recommendation = (
                f"Converged at {self.config.parameter.value} = {self.result.converged_value}. "
                f"Energy change < {threshold * 1000:.1f} meV/atom."
            )
        else:
            self.result.recommendation = (
                f"Not yet converged within {threshold * 1000:.1f} meV/atom threshold. "
                "Consider testing larger values."
            )

        return self.result

    def to_json(self) -> str:
        """Serialize study to JSON.

        Returns:
            JSON string representation
        """
        return json.dumps(
            {
                "config": {
                    "parameter": self.config.parameter.value,
                    "values": self.config.values,
                    "base_input": self.config.base_input,
                    "energy_threshold": self.config.energy_threshold,
                    "dft_code": self.config.dft_code,
                    "cluster_id": self.config.cluster_id,
                    "name_prefix": self.config.name_prefix,
                },
                "result": self.result.to_dict(),
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, json_str: str) -> ConvergenceStudy:
        """Deserialize study from JSON.

        Args:
            json_str: JSON string representation

        Returns:
            ConvergenceStudy instance
        """
        data = json.loads(json_str)
        config_data = data["config"]

        config = ConvergenceStudyConfig(
            parameter=ConvergenceParameter(config_data["parameter"]),
            values=config_data["values"],
            base_input=config_data["base_input"],
            energy_threshold=config_data.get("energy_threshold", 0.001),
            dft_code=config_data.get("dft_code", "crystal"),
            cluster_id=config_data.get("cluster_id"),
            name_prefix=config_data.get("name_prefix", "conv"),
        )

        study = cls(config)

        # Restore result state
        result_data = data.get("result", {})
        for i, point_data in enumerate(result_data.get("points", [])):
            if i < len(study.result.points):
                point = study.result.points[i]
                point.energy = point_data.get("energy")
                point.energy_per_atom = point_data.get("energy_per_atom")
                point.forces_max = point_data.get("forces_max")
                point.wall_time_seconds = point_data.get("wall_time_seconds")
                point.job_pk = point_data.get("job_pk")
                point.status = point_data.get("status", "pending")
                point.error_message = point_data.get("error_message")

        study.result.converged_value = result_data.get("converged_value")
        study.result.converged_at_index = result_data.get("converged_at_index")
        study.result.recommendation = result_data.get("recommendation", "")

        return study


# Alias for consistent naming with other workflows
ConvergenceWorkflow = ConvergenceStudy
