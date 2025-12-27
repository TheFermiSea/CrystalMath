"""
VASP error detection, classification, and recovery suggestions.

Provides detailed error analysis for VASP calculations with actionable
recovery suggestions based on common failure modes.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from enum import Enum


class VASPErrorSeverity(Enum):
    """Severity levels for VASP errors."""
    FATAL = "fatal"          # Job cannot continue
    RECOVERABLE = "recoverable"  # Can be fixed and restarted
    WARNING = "warning"      # Non-fatal but should be addressed


@dataclass
class VASPError:
    """Container for a detected VASP error with recovery info."""
    code: str                    # Short error code (e.g., "ZBRENT")
    severity: VASPErrorSeverity
    message: str                 # Human-readable error description
    line_content: Optional[str] = None  # Actual line from OUTCAR
    suggestions: List[str] = field(default_factory=list)  # Recovery suggestions
    incar_changes: Dict[str, str] = field(default_factory=dict)  # Suggested INCAR changes


# Known VASP error patterns with recovery strategies
VASP_ERROR_PATTERNS: List[Tuple[re.Pattern, str, VASPErrorSeverity, str, List[str], Dict[str, str]]] = [
    # ZBRENT: Bracketing error in Brent algorithm (common in relaxation)
    (
        re.compile(r"ZBRENT: fatal error in bracketing", re.IGNORECASE),
        "ZBRENT",
        VASPErrorSeverity.RECOVERABLE,
        "Brent algorithm failed to bracket the minimum during line search",
        [
            "Reduce POTIM (e.g., from 0.5 to 0.1-0.2)",
            "Switch optimizer: try IBRION=1 (quasi-Newton) or IBRION=3 (damped MD)",
            "Check for unreasonable starting geometry",
            "Increase EDIFF for looser SCF convergence initially",
        ],
        {"POTIM": "0.1", "IBRION": "1"}
    ),

    # EDDDAV: SCF did not converge
    (
        re.compile(r"Error EDDDAV", re.IGNORECASE),
        "EDDDAV",
        VASPErrorSeverity.RECOVERABLE,
        "Electronic self-consistency (SCF) did not converge",
        [
            "Increase NELM (max electronic iterations, e.g., 200)",
            "Try different algorithm: ALGO=All or ALGO=Damped",
            "Reduce EDIFF (looser convergence, e.g., 1E-5)",
            "Check k-point mesh density",
            "For metals: increase SIGMA or use ISMEAR=-5",
        ],
        {"NELM": "200", "ALGO": "All"}
    ),

    # POSMAP: Internal error with positions
    (
        re.compile(r"POSMAP internal error", re.IGNORECASE),
        "POSMAP",
        VASPErrorSeverity.FATAL,
        "Internal error in position mapping - likely overlapping atoms",
        [
            "Check POSCAR for overlapping or too-close atoms",
            "Increase the unit cell if atoms are too close to periodic images",
            "Verify all atomic positions are within 0.0-1.0 (direct) or cell bounds (Cartesian)",
        ],
        {}
    ),

    # Sub-space matrix error
    (
        re.compile(r"RSPHER: internal error: .* (increase|decrease) RSPHER", re.IGNORECASE),
        "RSPHER",
        VASPErrorSeverity.RECOVERABLE,
        "Subspace rotation error - atoms may be too close",
        [
            "Check for atoms too close together",
            "Try ADDGRID=.TRUE. in INCAR",
            "Reduce POTIM for geometry optimization",
        ],
        {"ADDGRID": ".TRUE."}
    ),

    # VERY BAD NEWS - general serious error
    (
        re.compile(r"VERY BAD NEWS", re.IGNORECASE),
        "VERYBAD",
        VASPErrorSeverity.FATAL,
        "Serious internal VASP error detected",
        [
            "Check OUTCAR for details above this message",
            "Review input structure for anomalies",
            "Consider restarting from a known good CONTCAR",
        ],
        {}
    ),

    # SGRCON: Symmetry group error
    (
        re.compile(r"SGRCON.*group", re.IGNORECASE),
        "SGRCON",
        VASPErrorSeverity.RECOVERABLE,
        "Symmetry detection failed - atoms may have moved asymmetrically",
        [
            "Set ISYM=0 to disable symmetry",
            "Or increase SYMPREC to be more tolerant",
            "Check that input structure has correct symmetry",
        ],
        {"ISYM": "0"}
    ),

    # RHOSYG: Charge density symmetrization error
    (
        re.compile(r"RHOSYG internal error", re.IGNORECASE),
        "RHOSYG",
        VASPErrorSeverity.RECOVERABLE,
        "Error symmetrizing charge density",
        [
            "Set ISYM=0 to disable symmetry",
            "Check for atoms at special positions",
        ],
        {"ISYM": "0"}
    ),

    # BRIONS: ionic relaxation problems
    (
        re.compile(r"BRIONS problems", re.IGNORECASE),
        "BRIONS",
        VASPErrorSeverity.RECOVERABLE,
        "Ionic relaxation algorithm encountered problems",
        [
            "Reduce POTIM (smaller ionic steps)",
            "Try different optimizer: IBRION=1, 2, or 3",
            "Check that forces on atoms are reasonable",
            "Consider starting from different initial geometry",
        ],
        {"POTIM": "0.1", "IBRION": "1"}
    ),

    # PRICEL: primitive cell error
    (
        re.compile(r"PRICEL.*not found", re.IGNORECASE),
        "PRICEL",
        VASPErrorSeverity.RECOVERABLE,
        "Problem finding primitive cell - likely symmetry issue",
        [
            "Set SYMPREC to a larger value (e.g., 1E-4)",
            "Or disable symmetry with ISYM=0",
        ],
        {"SYMPREC": "1E-4"}
    ),

    # Memory allocation errors
    (
        re.compile(r"allocation.*failed|cannot allocate", re.IGNORECASE),
        "MEMORY",
        VASPErrorSeverity.FATAL,
        "Memory allocation failed - job ran out of memory",
        [
            "Reduce NCORE/NPAR to use less memory per node",
            "Request more memory or fewer cores per node",
            "Consider reducing ENCUT or NGX/NGY/NGZ",
            "For very large systems: use LREAL=Auto",
        ],
        {"LREAL": "Auto"}
    ),

    # BRMIX: Mixing failed
    (
        re.compile(r"BRMIX.*internal error", re.IGNORECASE),
        "BRMIX",
        VASPErrorSeverity.RECOVERABLE,
        "Charge density mixing failed",
        [
            "Reduce AMIX and/or BMIX (e.g., 0.1)",
            "Try different mixing: IMIX=1 with smaller AMIX",
            "For magnetic systems: reduce AMIX_MAG",
        ],
        {"AMIX": "0.1", "BMIX": "0.0001"}
    ),

    # DENTET: Tetrahedron method error
    (
        re.compile(r"DENTET", re.IGNORECASE),
        "DENTET",
        VASPErrorSeverity.RECOVERABLE,
        "Tetrahedron method (ISMEAR=-5) failed",
        [
            "Use Gaussian smearing instead: ISMEAR=0, SIGMA=0.05",
            "For metals: ISMEAR=1 or 2 with appropriate SIGMA",
            "Increase k-point density",
        ],
        {"ISMEAR": "0", "SIGMA": "0.05"}
    ),

    # PSMAXN: augmentation charge error
    (
        re.compile(r"PSMAXN for non-local potential", re.IGNORECASE),
        "PSMAXN",
        VASPErrorSeverity.RECOVERABLE,
        "Augmentation charge overflow - FFT grid too coarse",
        [
            "Increase ENCUT (denser FFT grid)",
            "Explicitly set larger NGX, NGY, NGZ",
            "Check POTCAR files are appropriate for the calculation",
        ],
        {"PREC": "Accurate"}
    ),
]


class VASPErrorHandler:
    """
    Analyzes VASP output for errors and provides recovery suggestions.

    Usage:
        handler = VASPErrorHandler()
        errors = handler.analyze_outcar(outcar_content)
        for error in errors:
            print(f"{error.code}: {error.message}")
            for suggestion in error.suggestions:
                print(f"  - {suggestion}")
    """

    def __init__(self):
        """Initialize the error handler."""
        self._patterns = VASP_ERROR_PATTERNS

    def analyze_outcar(self, content: str) -> List[VASPError]:
        """
        Analyze OUTCAR content for errors.

        Args:
            content: Full or partial OUTCAR content.

        Returns:
            List of detected VASPError objects.
        """
        errors = []
        lines = content.split('\n')

        for line in lines:
            for pattern, code, severity, message, suggestions, incar_changes in self._patterns:
                if pattern.search(line):
                    # Check if we already have this error (avoid duplicates)
                    if not any(e.code == code for e in errors):
                        errors.append(VASPError(
                            code=code,
                            severity=severity,
                            message=message,
                            line_content=line.strip(),
                            suggestions=suggestions.copy(),
                            incar_changes=incar_changes.copy(),
                        ))
                    break  # Only match first pattern per line

        return errors

    def get_recovery_incar(self, errors: List[VASPError]) -> Dict[str, str]:
        """
        Generate combined INCAR changes to address all detected errors.

        Args:
            errors: List of VASPError objects.

        Returns:
            Dictionary of INCAR tag -> value changes.
        """
        combined = {}
        for error in errors:
            if error.severity == VASPErrorSeverity.RECOVERABLE:
                combined.update(error.incar_changes)
        return combined

    def format_error_report(self, errors: List[VASPError]) -> str:
        """
        Format errors into a human-readable report.

        Args:
            errors: List of VASPError objects.

        Returns:
            Formatted string report.
        """
        if not errors:
            return "No errors detected."

        lines = ["VASP Error Analysis", "=" * 40]

        for i, error in enumerate(errors, 1):
            severity_icon = {
                VASPErrorSeverity.FATAL: "❌",
                VASPErrorSeverity.RECOVERABLE: "⚠️",
                VASPErrorSeverity.WARNING: "💡",
            }.get(error.severity, "❓")

            lines.append(f"\n{i}. [{error.code}] {severity_icon} {error.severity.value.upper()}")
            lines.append(f"   {error.message}")

            if error.line_content:
                lines.append(f"   Line: {error.line_content[:80]}...")

            if error.suggestions:
                lines.append("   Suggestions:")
                for suggestion in error.suggestions:
                    lines.append(f"     • {suggestion}")

            if error.incar_changes:
                changes = ", ".join(f"{k}={v}" for k, v in error.incar_changes.items())
                lines.append(f"   INCAR: {changes}")

        return "\n".join(lines)


def analyze_vasp_errors(outcar_content: str) -> Tuple[List[VASPError], str]:
    """
    Convenience function to analyze VASP errors.

    Args:
        outcar_content: OUTCAR file content.

    Returns:
        Tuple of (list of errors, formatted report).
    """
    handler = VASPErrorHandler()
    errors = handler.analyze_outcar(outcar_content)
    report = handler.format_error_report(errors)
    return errors, report


__all__ = [
    "VASPError",
    "VASPErrorSeverity",
    "VASPErrorHandler",
    "analyze_vasp_errors",
    "VASP_ERROR_PATTERNS",
]
