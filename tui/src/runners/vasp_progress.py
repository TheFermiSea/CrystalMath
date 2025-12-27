"""
VASP job progress monitoring and parsing.

Provides real-time progress tracking for VASP calculations by parsing
OUTCAR file during execution. Extracts SCF iterations, ionic steps,
energies, and convergence status.
"""

import re
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass
class VASPProgress:
    """Container for VASP calculation progress information."""

    ionic_step: int = 0
    scf_iteration: int = 0
    current_energy: Optional[float] = None
    energy_change: Optional[float] = None
    scf_converged: bool = False
    ionic_converged: bool = False
    total_ionic_steps: Optional[int] = None
    max_scf_iterations: Optional[int] = None
    calculation_complete: bool = False
    error_detected: bool = False
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "ionic_step": self.ionic_step,
            "scf_iteration": self.scf_iteration,
            "current_energy": self.current_energy,
            "energy_change": self.energy_change,
            "scf_converged": self.scf_converged,
            "ionic_converged": self.ionic_converged,
            "total_ionic_steps": self.total_ionic_steps,
            "max_scf_iterations": self.max_scf_iterations,
            "calculation_complete": self.calculation_complete,
            "error_detected": self.error_detected,
            "error_message": self.error_message,
            "progress_percentage": self.progress_percentage(),
        }

    def progress_percentage(self) -> float:
        """
        Calculate overall progress percentage.

        Returns:
            Progress as percentage (0-100), or 0 if unknown.
        """
        if self.calculation_complete:
            return 100.0

        if self.total_ionic_steps and self.ionic_step > 0:
            # Ionic step progress
            return min(100.0, (self.ionic_step / self.total_ionic_steps) * 100.0)

        # For single-point calculations, estimate based on SCF
        if self.max_scf_iterations and self.scf_iteration > 0:
            return min(50.0, (self.scf_iteration / self.max_scf_iterations) * 50.0)

        return 0.0

    def status_summary(self) -> str:
        """
        Generate human-readable status summary.

        Returns:
            Status string for display in UI.
        """
        if self.error_detected:
            return f"Error: {self.error_message or 'Unknown error'}"

        if self.calculation_complete:
            if self.ionic_converged or self.scf_converged:
                return "Completed (converged)"
            return "Completed"

        if self.ionic_step > 0:
            status = f"Ionic step {self.ionic_step}"
            if self.total_ionic_steps:
                status += f"/{self.total_ionic_steps}"
            status += f", SCF {self.scf_iteration}"
            if self.current_energy is not None:
                status += f", E={self.current_energy:.6f} eV"
            return status

        if self.scf_iteration > 0:
            status = f"SCF iteration {self.scf_iteration}"
            if self.max_scf_iterations:
                status += f"/{self.max_scf_iterations}"
            if self.current_energy is not None:
                status += f", E={self.current_energy:.6f} eV"
            return status

        return "Initializing..."


class VASPProgressParser:
    """
    Parser for extracting progress information from VASP OUTCAR.

    Designed to work with partial OUTCAR files during job execution.
    Handles both single-point and relaxation calculations.
    """

    # Regex patterns for OUTCAR parsing
    IONIC_STEP_PATTERN = re.compile(r"^\s*(\d+)\s+F=\s*(-?\d+\.\d+E[+-]\d+)")
    SCF_ITERATION_PATTERN = re.compile(
        r"^\s*(?:RMM:|DAV:|CG:|DIA:)\s+(\d+)\s+(-?\d+\.\d+E[+-]\d+)"
    )
    ENERGY_PATTERN = re.compile(r"free\s+energy\s+TOTEN\s*=\s*(-?\d+\.\d+)")
    CONVERGENCE_PATTERN = re.compile(r"reached required accuracy")
    NSW_PATTERN = re.compile(r"NSW\s*=\s*(\d+)")
    NELM_PATTERN = re.compile(r"NELM\s*=\s*(\d+)")
    COMPLETION_PATTERN = re.compile(r"reached required accuracy|General timing")

    # VASP error patterns
    ERROR_PATTERNS = [
        (re.compile(r"ZBRENT: fatal error"), "ZBRENT: Fatal bracketing error"),
        (re.compile(r"VERY BAD NEWS"), "VERY BAD NEWS: Internal error"),
        (re.compile(r"POSMAP internal error"), "POSMAP: Internal error"),
        (re.compile(r"Error EDDDAV"), "EDDDAV: SCF convergence failure"),
        (re.compile(r"LPEAD=T.*VASP STOP"), "LPEAD incompatibility error"),
        (re.compile(r"internal error in subroutine"), "Internal subroutine error"),
    ]

    def __init__(self):
        """Initialize the VASP progress parser."""
        self.progress = VASPProgress()

    def parse_outcar_tail(self, outcar_content: str) -> VASPProgress:
        """
        Parse partial OUTCAR content (typically last 100-500 lines).

        Extracts current ionic step, SCF iteration, energy, and convergence status.

        Args:
            outcar_content: Tail of OUTCAR file (last N lines)

        Returns:
            VASPProgress object with current status
        """
        lines = outcar_content.split('\n')

        # Check for errors first
        for pattern, error_msg in self.ERROR_PATTERNS:
            for line in lines:
                if pattern.search(line):
                    self.progress.error_detected = True
                    self.progress.error_message = error_msg
                    logger.warning(f"VASP error detected: {error_msg}")
                    return self.progress

        # Parse configuration parameters (NSW, NELM) from header
        for line in lines[:50]:  # Check first 50 lines for parameters
            nsw_match = self.NSW_PATTERN.search(line)
            if nsw_match:
                self.progress.total_ionic_steps = int(nsw_match.group(1))

            nelm_match = self.NELM_PATTERN.search(line)
            if nelm_match:
                self.progress.max_scf_iterations = int(nelm_match.group(1))

        # Parse current state from tail (most recent data)
        current_ionic = 0
        current_scf = 0
        latest_energy = None

        for line in reversed(lines):  # Parse from end for most recent state
            # Check for ionic step
            ionic_match = self.IONIC_STEP_PATTERN.search(line)
            if ionic_match and current_ionic == 0:
                current_ionic = int(ionic_match.group(1))
                try:
                    latest_energy = float(ionic_match.group(2))
                except ValueError:
                    pass

            # Check for SCF iteration
            scf_match = self.SCF_ITERATION_PATTERN.search(line)
            if scf_match and current_scf == 0:
                current_scf = int(scf_match.group(1))
                if latest_energy is None:
                    try:
                        latest_energy = float(scf_match.group(2))
                    except ValueError:
                        pass

            # Check for free energy
            energy_match = self.ENERGY_PATTERN.search(line)
            if energy_match and latest_energy is None:
                try:
                    latest_energy = float(energy_match.group(1))
                except ValueError:
                    pass

            # Check for convergence
            if self.CONVERGENCE_PATTERN.search(line):
                self.progress.scf_converged = True
                self.progress.ionic_converged = True

            # Check for completion
            if self.COMPLETION_PATTERN.search(line):
                self.progress.calculation_complete = True

        # Update progress object
        self.progress.ionic_step = current_ionic
        self.progress.scf_iteration = current_scf
        self.progress.current_energy = latest_energy

        # Calculate energy change if we have previous energy
        if latest_energy is not None and hasattr(self, '_previous_energy'):
            self.progress.energy_change = latest_energy - self._previous_energy
        if latest_energy is not None:
            self._previous_energy = latest_energy

        return self.progress

    def parse_full_outcar(self, outcar_content: str) -> VASPProgress:
        """
        Parse complete OUTCAR file (for finished calculations).

        Provides comprehensive analysis of completed calculation.

        Args:
            outcar_content: Full OUTCAR file content

        Returns:
            VASPProgress object with final results
        """
        # Use tail parsing for consistency
        progress = self.parse_outcar_tail(outcar_content[-10000:])  # Last ~10K chars

        # Mark as complete if we see timing section
        if "General timing" in outcar_content:
            progress.calculation_complete = True

        return progress

    def reset(self) -> None:
        """Reset parser state for new calculation."""
        self.progress = VASPProgress()
        if hasattr(self, '_previous_energy'):
            delattr(self, '_previous_energy')


def parse_vasp_progress(outcar_tail: str) -> VASPProgress:
    """
    Convenience function for parsing VASP OUTCAR tail.

    Args:
        outcar_tail: Last N lines of OUTCAR file

    Returns:
        VASPProgress object with current status

    Example:
        >>> progress = parse_vasp_progress(outcar_content)
        >>> print(progress.status_summary())
        'Ionic step 5/50, SCF 12, E=-123.456789 eV'
    """
    parser = VASPProgressParser()
    return parser.parse_outcar_tail(outcar_tail)
