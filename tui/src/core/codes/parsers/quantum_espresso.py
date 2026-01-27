"""Quantum Espresso output parser implementation.

Parses pw.x, ph.x, and other QE executable output files to extract
energy, convergence status, and other calculation results.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, List

from ..base import DFTCode
from .base import OutputParser, ParsingResult, register_parser


class QuantumEspressoParser(OutputParser):
    """Parser for Quantum Espresso output files.

    Supports pw.x (SCF, relax, vc-relax), ph.x (phonon), and other QE outputs.
    """

    # Regex patterns for QE output parsing
    # Total energy: "!    total energy              =     -65.45703298 Ry"
    ENERGY_PATTERN = re.compile(r"!\s+total energy\s+=\s+([-\d.]+)\s+Ry", re.IGNORECASE)

    # SCF cycle: "     iteration #  1     ecut=    60.00 Ry"
    SCF_CYCLE_PATTERN = re.compile(r"iteration\s+#\s*(\d+)")

    # Forces/stress for geometry optimization
    FORCES_PATTERN = re.compile(r"Total force\s*=\s*([\d.E+-]+)")

    # Warning patterns
    WARNING_PATTERNS = [
        re.compile(r"Warning.*", re.IGNORECASE),
        re.compile(r"DEPRECATED.*", re.IGNORECASE),
    ]

    async def parse(self, output_file: Path) -> ParsingResult:
        """Parse a QE output file into a structured ParsingResult.

        Args:
            output_file: Path to the QE output file.

        Returns:
            ParsingResult with extracted energy, convergence, and metadata.
        """
        if not output_file.exists():
            return ParsingResult(
                success=False,
                final_energy=None,
                energy_unit=self.get_energy_unit(),
                convergence_status="UNKNOWN",
                errors=[f"Output file not found: {output_file}"],
            )

        try:
            content = output_file.read_text()
        except Exception as e:
            return ParsingResult(
                success=False,
                final_energy=None,
                energy_unit=self.get_energy_unit(),
                convergence_status="UNKNOWN",
                errors=[f"Failed to read output file: {e}"],
            )

        # Try aiida-quantumespresso parser first
        aiida_result = self._parse_with_aiida_qe(content)
        if aiida_result:
            return aiida_result

        errors: List[str] = []
        warnings: List[str] = []
        content_upper = content.upper()

        # Check for errors
        if "ERROR" in content_upper and "NO ERROR" not in content_upper:
            # Extract error lines
            for line in content.split("\n"):
                if "error" in line.lower() and "no error" not in line.lower():
                    errors.append(line.strip())
                    if len(errors) >= 5:
                        break

        if "CONVERGENCE NOT ACHIEVED" in content_upper:
            errors.append("SCF convergence not achieved")

        # Extract final energy - get the last occurrence
        final_energy: Optional[float] = None
        energy_matches = self.ENERGY_PATTERN.findall(content)
        if energy_matches:
            try:
                final_energy = float(energy_matches[-1])
            except ValueError:
                pass

        # Extract SCF cycles - count iterations
        scf_cycles: Optional[int] = None
        cycle_matches = self.SCF_CYCLE_PATTERN.findall(content)
        if cycle_matches:
            try:
                scf_cycles = int(cycle_matches[-1])
            except ValueError:
                pass

        # Check for geometry convergence (for relax/vc-relax)
        geometry_converged: Optional[bool] = None
        if "BFGS" in content or "GEOMETRY OPTIMIZATION" in content_upper:
            if (
                "BFGS CONVERGED" in content_upper
                or "GEOMETRY OPTIMIZATION CONVERGED" in content_upper
            ):
                geometry_converged = True
            elif "MAXIMUM NUMBER OF ITERATIONS REACHED" in content_upper:
                geometry_converged = False

        # Extract warnings
        for pattern in self.WARNING_PATTERNS:
            for match in pattern.finditer(content):
                warnings.append(match.group(0).strip())
                if len(warnings) >= 10:
                    break

        # Determine success - QE ends with "JOB DONE." on success
        job_done = "JOB DONE" in content_upper
        success = job_done and len(errors) == 0

        # Determine convergence status
        if "CONVERGENCE HAS BEEN ACHIEVED" in content_upper:
            convergence_status = "CONVERGED"
        elif "CONVERGENCE NOT ACHIEVED" in content_upper:
            convergence_status = "NOT_CONVERGED"
        elif job_done:
            convergence_status = "COMPLETED"
        else:
            convergence_status = "UNKNOWN"

        # Build metadata
        metadata = {
            "parser": "quantum_espresso",
            "job_done": job_done,
        }

        # Try to extract total force for geometry optimizations
        force_matches = self.FORCES_PATTERN.findall(content)
        if force_matches:
            try:
                metadata["total_force"] = float(force_matches[-1])
            except ValueError:
                pass

        return ParsingResult(
            success=success,
            final_energy=final_energy,
            energy_unit=self.get_energy_unit(),
            convergence_status=convergence_status,
            scf_cycles=scf_cycles,
            geometry_converged=geometry_converged,
            errors=errors[:5],
            warnings=warnings[:5],
            metadata=metadata,
        )

    def _parse_with_aiida_qe(self, content: str) -> Optional[ParsingResult]:
        """Parse QE output using aiida-quantumespresso parser."""
        try:
            from aiida_quantumespresso.parsers.parse_raw.pw import parse_stdout
            from qe_tools import CONSTANTS
        except ImportError:
            return None

        try:
            parsed_data, logs = parse_stdout(content, input_parameters={})

            # Check for errors in logs
            errors = logs.error if logs.error else []
            warnings = logs.warning if logs.warning else []

            # Extract final energy
            final_energy = None
            trajectory = parsed_data.get("trajectory", {})
            if "energy" in trajectory:
                energies = trajectory["energy"]
                if energies:
                    # parse_stdout returns eV
                    final_energy_ev = energies[-1]
                    # Convert to Ry to match existing parser behavior
                    final_energy = final_energy_ev / CONSTANTS.ry_to_ev

            # Extract SCF cycles
            scf_cycles = None
            if "scf_iterations" in trajectory:
                scf_iters = trajectory["scf_iterations"]
                if scf_iters:
                    scf_cycles = scf_iters[-1]

            # Check convergence
            convergence_status = "UNKNOWN"
            # parse_stdout puts ERROR_OUTPUT_STDOUT_INCOMPLETE if job not done
            job_done = "ERROR_OUTPUT_STDOUT_INCOMPLETE" not in errors

            if job_done:
                convergence_status = "COMPLETED"
                # Refine status
                # If no SCF convergence error
                if "ERROR_ELECTRONIC_CONVERGENCE_NOT_REACHED" not in errors:
                    convergence_status = "CONVERGED"
                else:
                    convergence_status = "NOT_CONVERGED"

            geometry_converged = None
            if "atomic_positions_relax" in trajectory:
                if "ERROR_IONIC_CONVERGENCE_NOT_REACHED" not in errors:
                    geometry_converged = True
                else:
                    geometry_converged = False

            # If we have energy and no critical errors, success
            # Note: parse_stdout might add errors even for warnings sometimes?
            # We filter known non-critical errors?
            # For now, stick to basic check.
            success = job_done and (final_energy is not None)

            metadata = {
                "parser": "aiida-quantumespresso",
                "parsed_data": parsed_data,
            }

            if "total_force" in trajectory:
                forces = trajectory["total_force"]
                if forces:
                    # aiida-qe converts to ev/angstrom
                    # manual parser uses whatever units are in output (usually Ry/au or eV/A depending on version/verbosity)
                    # The manual parser uses regex `Total force = ...` which is usually in Ry/au in QE < 6?
                    # parse_stdout returns default_force_units = 'ev / angstrom'
                    # We store it as is.
                    metadata["total_force"] = forces[-1]

            return ParsingResult(
                success=success,
                final_energy=final_energy,
                energy_unit="Ry",
                convergence_status=convergence_status,
                scf_cycles=scf_cycles,
                geometry_converged=geometry_converged,
                errors=errors,
                warnings=warnings,
                metadata=metadata,
            )

        except Exception:
            return None

        try:
            content = output_file.read_text()
        except Exception as e:
            return ParsingResult(
                success=False,
                final_energy=None,
                energy_unit=self.get_energy_unit(),
                convergence_status="UNKNOWN",
                errors=[f"Failed to read output file: {e}"],
            )

        errors: List[str] = []
        warnings: List[str] = []
        content_upper = content.upper()

        # Check for errors
        if "ERROR" in content_upper and "NO ERROR" not in content_upper:
            # Extract error lines
            for line in content.split("\n"):
                if "error" in line.lower() and "no error" not in line.lower():
                    errors.append(line.strip())
                    if len(errors) >= 5:
                        break

        if "CONVERGENCE NOT ACHIEVED" in content_upper:
            errors.append("SCF convergence not achieved")

        # Extract final energy - get the last occurrence
        final_energy: Optional[float] = None
        energy_matches = self.ENERGY_PATTERN.findall(content)
        if energy_matches:
            try:
                final_energy = float(energy_matches[-1])
            except ValueError:
                pass

        # Extract SCF cycles - count iterations
        scf_cycles: Optional[int] = None
        cycle_matches = self.SCF_CYCLE_PATTERN.findall(content)
        if cycle_matches:
            try:
                scf_cycles = int(cycle_matches[-1])
            except ValueError:
                pass

        # Check for geometry convergence (for relax/vc-relax)
        geometry_converged: Optional[bool] = None
        if "BFGS" in content or "GEOMETRY OPTIMIZATION" in content_upper:
            if (
                "BFGS CONVERGED" in content_upper
                or "GEOMETRY OPTIMIZATION CONVERGED" in content_upper
            ):
                geometry_converged = True
            elif "MAXIMUM NUMBER OF ITERATIONS REACHED" in content_upper:
                geometry_converged = False

        # Extract warnings
        for pattern in self.WARNING_PATTERNS:
            for match in pattern.finditer(content):
                warnings.append(match.group(0).strip())
                if len(warnings) >= 10:
                    break

        # Determine success - QE ends with "JOB DONE." on success
        job_done = "JOB DONE" in content_upper
        success = job_done and len(errors) == 0

        # Determine convergence status
        if "CONVERGENCE HAS BEEN ACHIEVED" in content_upper:
            convergence_status = "CONVERGED"
        elif "CONVERGENCE NOT ACHIEVED" in content_upper:
            convergence_status = "NOT_CONVERGED"
        elif job_done:
            convergence_status = "COMPLETED"
        else:
            convergence_status = "UNKNOWN"

        # Build metadata
        metadata = {
            "parser": "quantum_espresso",
            "job_done": job_done,
        }

        # Try to extract total force for geometry optimizations
        force_matches = self.FORCES_PATTERN.findall(content)
        if force_matches:
            try:
                metadata["total_force"] = float(force_matches[-1])
            except ValueError:
                pass

        return ParsingResult(
            success=success,
            final_energy=final_energy,
            energy_unit=self.get_energy_unit(),
            convergence_status=convergence_status,
            scf_cycles=scf_cycles,
            geometry_converged=geometry_converged,
            errors=errors[:5],
            warnings=warnings[:5],
            metadata=metadata,
        )

    def get_energy_unit(self) -> str:
        """Return the energy unit (Rydberg for QE)."""
        return "Ry"


# Singleton instance
_parser = QuantumEspressoParser()

# Auto-register when module is imported
register_parser(DFTCode.QUANTUM_ESPRESSO, _parser)


__all__ = ["QuantumEspressoParser"]
