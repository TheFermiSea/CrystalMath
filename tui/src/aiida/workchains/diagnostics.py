"""
Diagnostic analysis for CRYSTAL23 SCF convergence issues.

This module provides tools for analyzing SCF convergence behavior and
recommending parameter modifications for self-healing workflows.

Key features:
    - Convergence pattern classification (oscillation, slow, divergent)
    - Adaptive parameter recommendation (FMIXING, damping, level shift)
    - Resource estimation based on system size
    - Root cause identification for common failures

Data Sources:
    The diagnostics can use two data sources (in order of preference):
    1. Parsed output parameters (from Crystal23Calculation parser) - more robust
    2. Raw output file content (regex-based) - fallback when parsed data unavailable

Usage:
    >>> # Preferred: Use parsed output parameters
    >>> diagnostics = analyze_scf_from_parsed_output(calc.outputs.output_parameters)
    >>>
    >>> # Fallback: Parse raw output content
    >>> diagnostics = analyze_scf_convergence(output_content)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiida import orm


class ConvergencePattern(Enum):
    """Classification of SCF convergence behavior."""

    CONVERGED = auto()  # Normal convergence achieved
    SLOW = auto()  # Converging but too slowly
    OSCILLATING = auto()  # Energy oscillates without converging
    DIVERGING = auto()  # Energy increases or explodes
    STUCK = auto()  # No progress for many cycles
    UNKNOWN = auto()  # Pattern unclear


class FailureReason(Enum):
    """Root cause classification for SCF failures."""

    CHARGE_SLOSHING = auto()  # Charge oscillates between regions
    SMALL_GAP = auto()  # Small HOMO-LUMO gap causes instability
    LINEAR_DEPENDENCE = auto()  # Near-linear dependent basis functions
    POOR_INITIAL_GUESS = auto()  # Bad starting wavefunction
    INSUFFICIENT_MIXING = auto()  # FMIXING too aggressive
    INSUFFICIENT_CYCLES = auto()  # Just needs more iterations
    MEMORY_LIMIT = auto()  # Out of memory
    TIMEOUT = auto()  # Wall time exceeded
    UNKNOWN = auto()


@dataclass
class SCFDiagnostics:
    """Diagnostic results from SCF convergence analysis."""

    pattern: ConvergencePattern = ConvergencePattern.UNKNOWN
    reason: FailureReason = FailureReason.UNKNOWN
    confidence: float = 0.0  # 0.0 to 1.0
    energy_history: list[float] = field(default_factory=list)
    delta_e_history: list[float] = field(default_factory=list)
    oscillation_amplitude: float | None = None
    convergence_rate: float | None = None  # |ΔE_n| / |ΔE_{n-1}|
    homo_lumo_gap: float | None = None
    max_gradient: float | None = None
    recommendations: list[str] = field(default_factory=list)


@dataclass
class ParameterModification:
    """Recommended parameter modification for restart."""

    parameter: str  # e.g., "scf.fmixing", "scf.maxcycle"
    old_value: Any
    new_value: Any
    reason: str
    priority: int = 1  # 1 = highest priority


def analyze_scf_from_parsed_output(
    output_params: dict[str, Any] | None = None,
    parsed_output: orm.Dict | None = None,
) -> SCFDiagnostics:
    """
    Analyze SCF convergence using parsed output parameters (preferred).

    This function uses structured data from the CRYSTAL23 parser, which is
    more robust than regex-based parsing of raw output files.

    Args:
        output_params: Dictionary of parsed output parameters (direct dict).
        parsed_output: AiiDA Dict node with parsed output (alternative).
            One of these must be provided.

    Returns:
        SCFDiagnostics with pattern classification and recommendations.

    Raises:
        ValueError: If neither output_params nor parsed_output is provided.

    Example:
        >>> # From AiiDA calculation node
        >>> diagnostics = analyze_scf_from_parsed_output(
        ...     parsed_output=calc.outputs.output_parameters
        ... )
        >>>
        >>> # From raw dictionary
        >>> diagnostics = analyze_scf_from_parsed_output(
        ...     output_params={"scf_converged": True, "band_gap_ev": 1.5}
        ... )
    """
    # Extract dictionary from AiiDA Dict node if provided
    if output_params is None:
        if parsed_output is None:
            raise ValueError("Either output_params or parsed_output must be provided")
        output_params = parsed_output.get_dict()

    diagnostics = SCFDiagnostics()

    # Check for explicit convergence status from parser
    scf_converged = output_params.get("scf_converged", None)
    if scf_converged is True:
        diagnostics.pattern = ConvergencePattern.CONVERGED
        diagnostics.confidence = 0.99  # Parser is authoritative
    elif scf_converged is False:
        # Will determine pattern from energy history
        pass

    # Check for explicit termination reasons from parser
    termination = output_params.get("termination_reason", "").lower()
    if "memory" in termination or output_params.get("memory_error", False):
        diagnostics.reason = FailureReason.MEMORY_LIMIT
    elif "timeout" in termination or "time" in termination or output_params.get("timeout", False):
        diagnostics.reason = FailureReason.TIMEOUT
    elif (
        "linear" in termination
        and "depend" in termination
        or output_params.get("linear_dependence", False)
    ):
        diagnostics.reason = FailureReason.LINEAR_DEPENDENCE

    # Extract energy history from parsed data
    # Parser may store this under different keys
    energy_history = output_params.get("scf_energy_history", [])
    if not energy_history:
        energy_history = output_params.get("energy_history", [])
    if not energy_history:
        # Try to build from individual cycle data
        cycles = output_params.get("scf_cycles", [])
        energy_history = [c.get("energy") for c in cycles if c.get("energy") is not None]

    diagnostics.energy_history = energy_history

    # Extract HOMO-LUMO gap from parsed data
    homo_lumo_gap = output_params.get("band_gap_ev")
    if homo_lumo_gap is None:
        homo_lumo_gap = output_params.get("homo_lumo_gap_ev")
    if homo_lumo_gap is None:
        homo_lumo_gap = output_params.get("gap_ev")
    diagnostics.homo_lumo_gap = homo_lumo_gap

    # If we already determined it's converged, finish up
    if diagnostics.pattern == ConvergencePattern.CONVERGED:
        diagnostics.confidence = 0.99
        diagnostics.reason = FailureReason.UNKNOWN  # No failure
        diagnostics.recommendations = []
        return diagnostics

    # If explicit error was found, generate recommendations
    if diagnostics.reason != FailureReason.UNKNOWN:
        diagnostics.recommendations = _generate_recommendations(diagnostics)
        return diagnostics

    # Calculate energy deltas if we have history
    if len(energy_history) >= 2:
        delta_e = [
            energy_history[i + 1] - energy_history[i] for i in range(len(energy_history) - 1)
        ]
        diagnostics.delta_e_history = delta_e

        # Classify pattern using the same logic as regex-based function
        # but without needing to parse output_content
        diagnostics.pattern, diagnostics.confidence = _classify_pattern_from_energies(
            energy_history, delta_e, scf_converged
        )

        # Calculate oscillation amplitude if oscillating
        if diagnostics.pattern == ConvergencePattern.OSCILLATING:
            diagnostics.oscillation_amplitude = _calculate_oscillation_amplitude(delta_e)

        # Calculate convergence rate for slow convergence
        if diagnostics.pattern == ConvergencePattern.SLOW:
            diagnostics.convergence_rate = _calculate_convergence_rate(delta_e)

        # Determine root cause from pattern and gap
        diagnostics.reason = _determine_root_cause_from_parsed(
            diagnostics.pattern,
            homo_lumo_gap,
            delta_e,
            output_params,
        )

    # Generate recommendations based on diagnostics
    diagnostics.recommendations = _generate_recommendations(diagnostics)

    return diagnostics


def _classify_pattern_from_energies(
    energies: list[float],
    delta_e: list[float],
    scf_converged: bool | None,
) -> tuple[ConvergencePattern, float]:
    """
    Classify SCF convergence pattern from energy history (no regex).

    This is the parser-based equivalent of _classify_pattern().
    """
    # If parser explicitly says converged
    if scf_converged is True:
        return ConvergencePattern.CONVERGED, 0.99

    if len(delta_e) < 3:
        return ConvergencePattern.UNKNOWN, 0.3

    # Check for convergence (last few deltas small)
    last_deltas = delta_e[-3:] if len(delta_e) >= 3 else delta_e
    if all(abs(d) < 1e-5 for d in last_deltas):
        return ConvergencePattern.CONVERGED, 0.90

    # Check for oscillation (alternating signs)
    sign_changes = sum(1 for i in range(len(delta_e) - 1) if delta_e[i] * delta_e[i + 1] < 0)
    oscillation_ratio = sign_changes / (len(delta_e) - 1)

    if oscillation_ratio > 0.6:
        return ConvergencePattern.OSCILLATING, min(0.5 + oscillation_ratio / 2, 0.95)

    # Check for divergence (energy increasing overall)
    if len(energies) >= 5:
        early_avg = sum(energies[:3]) / 3
        late_avg = sum(energies[-3:]) / 3
        if late_avg > early_avg + 0.1:
            return ConvergencePattern.DIVERGING, 0.85

    # Check for stuck (very small progress)
    recent_progress = sum(abs(d) for d in delta_e[-5:]) if len(delta_e) >= 5 else 0
    if recent_progress < 1e-8 and not all(abs(d) < 1e-6 for d in last_deltas):
        return ConvergencePattern.STUCK, 0.8

    # Check for slow convergence
    if len(delta_e) >= 10:
        abs_deltas = [abs(d) for d in delta_e if d != 0]
        if len(abs_deltas) >= 5:
            avg_rate = sum(
                abs_deltas[i + 1] / abs_deltas[i]
                for i in range(len(abs_deltas) - 1)
                if abs_deltas[i] > 1e-12
            ) / max(len(abs_deltas) - 1, 1)

            if avg_rate > 0.9:
                return ConvergencePattern.SLOW, 0.75

    return ConvergencePattern.UNKNOWN, 0.4


def _determine_root_cause_from_parsed(
    pattern: ConvergencePattern,
    homo_lumo_gap: float | None,
    delta_e: list[float],
    output_params: dict[str, Any],
) -> FailureReason:
    """
    Determine root cause from parsed output parameters.

    Uses structured data instead of regex patterns.
    """
    # Check for explicit error flags from parser
    if output_params.get("memory_error", False):
        return FailureReason.MEMORY_LIMIT

    if output_params.get("timeout", False):
        return FailureReason.TIMEOUT

    if output_params.get("linear_dependence", False):
        return FailureReason.LINEAR_DEPENDENCE

    # Check warnings list if available
    warnings = output_params.get("warnings", [])
    for warning in warnings:
        warning_lower = str(warning).lower()
        if "memory" in warning_lower:
            return FailureReason.MEMORY_LIMIT
        if "linear" in warning_lower and "depend" in warning_lower:
            return FailureReason.LINEAR_DEPENDENCE

    # Infer from pattern and gap (same logic as regex version)
    if pattern == ConvergencePattern.OSCILLATING:
        if homo_lumo_gap is not None and homo_lumo_gap < 0.5:
            return FailureReason.SMALL_GAP
        return FailureReason.CHARGE_SLOSHING

    if pattern == ConvergencePattern.SLOW:
        if homo_lumo_gap is not None and homo_lumo_gap < 1.0:
            return FailureReason.SMALL_GAP
        return FailureReason.INSUFFICIENT_MIXING

    if pattern == ConvergencePattern.DIVERGING:
        return FailureReason.POOR_INITIAL_GUESS

    if pattern == ConvergencePattern.STUCK:
        return FailureReason.INSUFFICIENT_CYCLES

    return FailureReason.UNKNOWN


def analyze_scf_convergence(output_content: str) -> SCFDiagnostics:
    """
    Analyze SCF convergence behavior from CRYSTAL23 output.

    Extracts energy history, identifies convergence pattern, and
    determines root cause of failures.

    Args:
        output_content: Raw CRYSTAL23 output file content.

    Returns:
        SCFDiagnostics with pattern classification and recommendations.
    """
    diagnostics = SCFDiagnostics()

    # First check for explicit error messages (even before energy extraction)
    explicit_reason = _check_explicit_errors(output_content)
    if explicit_reason != FailureReason.UNKNOWN:
        diagnostics.reason = explicit_reason
        diagnostics.pattern = ConvergencePattern.UNKNOWN
        diagnostics.recommendations = _generate_recommendations(diagnostics)
        return diagnostics

    # Extract SCF energy history
    energy_history = _extract_energy_history(output_content)
    diagnostics.energy_history = energy_history

    if len(energy_history) < 2:
        diagnostics.pattern = ConvergencePattern.UNKNOWN
        diagnostics.reason = FailureReason.UNKNOWN
        return diagnostics

    # Calculate energy deltas
    delta_e = [energy_history[i + 1] - energy_history[i] for i in range(len(energy_history) - 1)]
    diagnostics.delta_e_history = delta_e

    # Classify convergence pattern
    diagnostics.pattern, diagnostics.confidence = _classify_pattern(
        energy_history, delta_e, output_content
    )

    # Extract HOMO-LUMO gap if available
    diagnostics.homo_lumo_gap = _extract_homo_lumo_gap(output_content)

    # Determine root cause
    diagnostics.reason = _determine_root_cause(
        diagnostics.pattern,
        diagnostics.homo_lumo_gap,
        delta_e,
        output_content,
    )

    # Calculate oscillation amplitude if oscillating
    if diagnostics.pattern == ConvergencePattern.OSCILLATING:
        diagnostics.oscillation_amplitude = _calculate_oscillation_amplitude(delta_e)

    # Calculate convergence rate for slow convergence
    if diagnostics.pattern == ConvergencePattern.SLOW:
        diagnostics.convergence_rate = _calculate_convergence_rate(delta_e)

    # Generate recommendations
    diagnostics.recommendations = _generate_recommendations(diagnostics)

    return diagnostics


def _check_explicit_errors(output_content: str) -> FailureReason:
    """Check for explicit error messages in output."""
    if re.search(r"INSUFFICIENT\s+MEMORY", output_content, re.IGNORECASE):
        return FailureReason.MEMORY_LIMIT

    if re.search(r"TIME\s+LIMIT|TIMEOUT", output_content, re.IGNORECASE):
        return FailureReason.TIMEOUT

    if re.search(r"LINEAR\s+DEPEND", output_content, re.IGNORECASE):
        return FailureReason.LINEAR_DEPENDENCE

    return FailureReason.UNKNOWN


def _extract_energy_history(output_content: str) -> list[float]:
    """
    Extract SCF cycle energies from output.

    Handles multiple SCF blocks (e.g., geometry optimization steps).
    Returns energies from the most recent SCF cycle.
    """
    energies = []

    # Pattern for CRYSTAL23 SCF cycle output
    # Example: "  1  -456.123456789   3.45E+01   1.00E-01"
    # The energy is the second field after the cycle number
    cycle_pattern = re.compile(
        r"^\s*(\d+)\s+([-]?\d+\.\d+)",
        re.MULTILINE,
    )

    # Find SCF cycle block markers
    scf_blocks = list(re.finditer(r"CYC\s+ETOT\(AU\)", output_content))

    if not scf_blocks:
        # Try alternative pattern for older CRYSTAL versions
        alt_pattern = re.compile(r"TOTAL ENERGY\s*=\s*([-]?\d+\.\d+)")
        matches = alt_pattern.findall(output_content)
        return [float(e) for e in matches]

    # Get the last SCF block
    if scf_blocks:
        last_block_start = scf_blocks[-1].end()
        scf_section = output_content[last_block_start:]

        # Find the end of the SCF block (marked by "==")
        end_match = re.search(r"==", scf_section)
        if end_match:
            scf_section = scf_section[: end_match.start()]

        # Find energy values in this block
        for match in cycle_pattern.finditer(scf_section):
            try:
                cycle_num = int(match.group(1))
                energy = float(match.group(2))
                # Only add if cycle number is sequential (avoid false matches)
                if not energies or cycle_num == len(energies) + 1:
                    energies.append(energy)
            except ValueError:
                continue

    return energies


def _extract_homo_lumo_gap(output_content: str) -> float | None:
    """Extract HOMO-LUMO gap in eV from output."""
    patterns = [
        r"HOMO-LUMO GAP\s*[:\s]*([\d.]+)\s*EV",
        r"GAP\s*[:\s]*([\d.]+)\s*EV",
        r"(DIRECT|INDIRECT)\s+BAND\s+GAP:\s+([\d.]+)\s+EV",
    ]

    for pattern in patterns:
        match = re.search(pattern, output_content, re.IGNORECASE)
        if match:
            try:
                # Handle pattern with (DIRECT|INDIRECT) prefix
                gap_str = match.group(2) if match.lastindex >= 2 else match.group(1)
                return float(gap_str)
            except (ValueError, IndexError):
                continue

    return None


def _classify_pattern(
    energies: list[float],
    delta_e: list[float],
    output_content: str = "",
) -> tuple[ConvergencePattern, float]:
    """
    Classify SCF convergence pattern.

    Returns:
        Tuple of (pattern, confidence) where confidence is 0.0-1.0.
    """
    # First check for explicit convergence message in output
    if re.search(r"SCF ENDED.*CONVERGE", output_content, re.IGNORECASE):
        return ConvergencePattern.CONVERGED, 0.95

    if len(delta_e) < 3:
        return ConvergencePattern.UNKNOWN, 0.3

    # Check for convergence (last few deltas small)
    last_deltas = delta_e[-3:] if len(delta_e) >= 3 else delta_e
    if all(abs(d) < 1e-5 for d in last_deltas):  # Loosened threshold
        return ConvergencePattern.CONVERGED, 0.90

    # Check for oscillation (alternating signs)
    sign_changes = sum(1 for i in range(len(delta_e) - 1) if delta_e[i] * delta_e[i + 1] < 0)
    oscillation_ratio = sign_changes / (len(delta_e) - 1)

    if oscillation_ratio > 0.6:
        # Strong oscillation pattern
        return ConvergencePattern.OSCILLATING, min(0.5 + oscillation_ratio / 2, 0.95)

    # Check for divergence (energy increasing overall)
    if len(energies) >= 5:
        early_avg = sum(energies[:3]) / 3
        late_avg = sum(energies[-3:]) / 3
        if late_avg > early_avg + 0.1:
            return ConvergencePattern.DIVERGING, 0.85

    # Check for stuck (very small progress)
    recent_progress = sum(abs(d) for d in delta_e[-5:]) if len(delta_e) >= 5 else 0
    if recent_progress < 1e-8 and not all(abs(d) < 1e-6 for d in last_deltas):
        return ConvergencePattern.STUCK, 0.8

    # Check for slow convergence
    if len(delta_e) >= 10:
        # Convergence rate: how fast |ΔE| is decreasing
        abs_deltas = [abs(d) for d in delta_e if d != 0]
        if len(abs_deltas) >= 5:
            avg_rate = sum(
                abs_deltas[i + 1] / abs_deltas[i]
                for i in range(len(abs_deltas) - 1)
                if abs_deltas[i] > 1e-12
            ) / max(len(abs_deltas) - 1, 1)

            if avg_rate > 0.9:  # Slow convergence
                return ConvergencePattern.SLOW, 0.75

    return ConvergencePattern.UNKNOWN, 0.4


def _determine_root_cause(
    pattern: ConvergencePattern,
    homo_lumo_gap: float | None,
    delta_e: list[float],
    output_content: str,
) -> FailureReason:
    """Determine root cause of SCF failure."""
    # Check for explicit error messages
    if re.search(r"INSUFFICIENT\s+MEMORY", output_content, re.IGNORECASE):
        return FailureReason.MEMORY_LIMIT

    if re.search(r"TIME\s+LIMIT|TIMEOUT", output_content, re.IGNORECASE):
        return FailureReason.TIMEOUT

    if re.search(r"LINEAR\s+DEPEND", output_content, re.IGNORECASE):
        return FailureReason.LINEAR_DEPENDENCE

    # Infer from pattern and gap
    if pattern == ConvergencePattern.OSCILLATING:
        # Oscillation usually indicates charge sloshing or small gap
        if homo_lumo_gap is not None and homo_lumo_gap < 0.5:
            return FailureReason.SMALL_GAP
        return FailureReason.CHARGE_SLOSHING

    if pattern == ConvergencePattern.SLOW:
        if homo_lumo_gap is not None and homo_lumo_gap < 1.0:
            return FailureReason.SMALL_GAP
        return FailureReason.INSUFFICIENT_MIXING

    if pattern == ConvergencePattern.DIVERGING:
        return FailureReason.POOR_INITIAL_GUESS

    if pattern == ConvergencePattern.STUCK:
        return FailureReason.INSUFFICIENT_CYCLES

    return FailureReason.UNKNOWN


def _calculate_oscillation_amplitude(delta_e: list[float]) -> float:
    """Calculate average oscillation amplitude."""
    if len(delta_e) < 4:
        return 0.0

    # Use last half of cycles for amplitude estimation
    recent = delta_e[len(delta_e) // 2 :]
    return sum(abs(d) for d in recent) / len(recent)


def _calculate_convergence_rate(delta_e: list[float]) -> float:
    """Calculate average convergence rate (should be < 1 for convergence)."""
    abs_deltas = [abs(d) for d in delta_e if abs(d) > 1e-12]

    if len(abs_deltas) < 2:
        return 1.0

    rates = []
    for i in range(len(abs_deltas) - 1):
        if abs_deltas[i] > 1e-12:
            rates.append(abs_deltas[i + 1] / abs_deltas[i])

    return sum(rates) / len(rates) if rates else 1.0


def _generate_recommendations(diagnostics: SCFDiagnostics) -> list[str]:
    """Generate human-readable recommendations."""
    recommendations = []

    if diagnostics.reason == FailureReason.CHARGE_SLOSHING:
        recommendations.append("Increase FMIXING to slow charge mixing (try 50-70%)")
        recommendations.append("Enable Anderson mixing (ANDERSON keyword)")
        recommendations.append("Consider using GUESSP for better initial guess")

    elif diagnostics.reason == FailureReason.SMALL_GAP:
        recommendations.append("Apply level shifting (LEVSHIFT keyword)")
        recommendations.append("Increase FMIXING significantly (70-90%)")
        recommendations.append("Use smearing if allowed (SMEAR keyword)")

    elif diagnostics.reason == FailureReason.LINEAR_DEPENDENCE:
        recommendations.append("Reduce basis set exponents")
        recommendations.append("Check for very close atoms")
        recommendations.append("Use TOLINTEG with smaller values")

    elif diagnostics.reason == FailureReason.POOR_INITIAL_GUESS:
        recommendations.append("Use GUESSP with wavefunction from simpler calculation")
        recommendations.append("Try atomic guess (default)")
        recommendations.append("Reduce initial mixing (FMIXING 90%)")

    elif diagnostics.reason == FailureReason.INSUFFICIENT_MIXING:
        recommendations.append("Decrease FMIXING to speed up mixing (try 30-50%)")
        recommendations.append("Increase DIIS history size")

    elif diagnostics.reason == FailureReason.INSUFFICIENT_CYCLES:
        recommendations.append("Increase MAXCYCLE")
        recommendations.append("Tighten TOLDEE if close to convergence")

    elif diagnostics.reason == FailureReason.MEMORY_LIMIT:
        recommendations.append("Increase available memory")
        recommendations.append("Use more MPI ranks to distribute memory")
        recommendations.append("Reduce k-point mesh density")

    elif diagnostics.reason == FailureReason.TIMEOUT:
        recommendations.append("Increase walltime")
        recommendations.append("Use checkpoint restart")

    return recommendations


def recommend_parameter_modifications(
    diagnostics: SCFDiagnostics,
    current_params: dict[str, Any],
    restart_count: int = 0,
) -> list[ParameterModification]:
    """
    Recommend specific parameter modifications for restart.

    Args:
        diagnostics: Analysis results from analyze_scf_convergence.
        current_params: Current CRYSTAL23 input parameters.
        restart_count: Number of previous restart attempts.

    Returns:
        List of ParameterModification recommendations.
    """
    modifications = []
    scf_params = current_params.get("scf", {})

    # Get current values
    current_fmixing = scf_params.get("fmixing", 30)
    current_maxcycle = scf_params.get("maxcycle", 100)
    current_toldee = scf_params.get("toldee", 7)
    current_levshift = scf_params.get("levshift")

    # Charge sloshing: increase mixing (slower)
    if diagnostics.reason == FailureReason.CHARGE_SLOSHING:
        new_fmixing = min(current_fmixing + 20 * (restart_count + 1), 90)
        if new_fmixing != current_fmixing:
            modifications.append(
                ParameterModification(
                    parameter="scf.fmixing",
                    old_value=current_fmixing,
                    new_value=new_fmixing,
                    reason="Slow down charge mixing to reduce oscillation",
                    priority=1,
                )
            )

    # Small gap: enable level shifting
    elif diagnostics.reason == FailureReason.SMALL_GAP:
        if current_levshift is None:
            modifications.append(
                ParameterModification(
                    parameter="scf.levshift",
                    old_value=None,
                    new_value=[2, 1],  # 2 Hartree shift, lock after 1 cycle
                    reason="Apply level shift for small gap system",
                    priority=1,
                )
            )
        new_fmixing = min(current_fmixing + 30, 90)
        if new_fmixing != current_fmixing:
            modifications.append(
                ParameterModification(
                    parameter="scf.fmixing",
                    old_value=current_fmixing,
                    new_value=new_fmixing,
                    reason="Increase mixing for small gap stability",
                    priority=2,
                )
            )

    # Slow convergence: decrease mixing (faster) or increase DIIS
    elif diagnostics.reason == FailureReason.INSUFFICIENT_MIXING:
        new_fmixing = max(current_fmixing - 10 * (restart_count + 1), 10)
        if new_fmixing != current_fmixing:
            modifications.append(
                ParameterModification(
                    parameter="scf.fmixing",
                    old_value=current_fmixing,
                    new_value=new_fmixing,
                    reason="Speed up charge mixing for faster convergence",
                    priority=1,
                )
            )

    # Insufficient cycles: increase MAXCYCLE
    if diagnostics.reason == FailureReason.INSUFFICIENT_CYCLES:
        new_maxcycle = min(current_maxcycle + 100, 999)
        modifications.append(
            ParameterModification(
                parameter="scf.maxcycle",
                old_value=current_maxcycle,
                new_value=new_maxcycle,
                reason="Increase maximum SCF cycles",
                priority=1,
            )
        )

    # Poor initial guess: add GUESSP if wavefunction available
    elif diagnostics.reason == FailureReason.POOR_INITIAL_GUESS:
        modifications.append(
            ParameterModification(
                parameter="scf.guessp",
                old_value=False,
                new_value=True,
                reason="Use wavefunction restart for better initial guess",
                priority=1,
            )
        )
        # Also slow down mixing initially
        new_fmixing = min(current_fmixing + 30, 90)
        modifications.append(
            ParameterModification(
                parameter="scf.fmixing",
                old_value=current_fmixing,
                new_value=new_fmixing,
                reason="Slow mixing with new initial guess",
                priority=2,
            )
        )

    # Always consider loosening tolerance if nearly converged
    if diagnostics.pattern == ConvergencePattern.SLOW and restart_count >= 2:
        new_toldee = max(current_toldee - 1, 5)
        if new_toldee != current_toldee:
            modifications.append(
                ParameterModification(
                    parameter="scf.toldee",
                    old_value=current_toldee,
                    new_value=new_toldee,
                    reason="Loosen tolerance for stubborn systems",
                    priority=3,
                )
            )

    # Sort by priority
    modifications.sort(key=lambda m: m.priority)

    return modifications


def estimate_resources(
    num_atoms: int,
    num_electrons: int,
    k_points: int = 1,
    basis_size: str = "medium",
) -> dict[str, Any]:
    """
    Estimate computational resources needed for a CRYSTAL23 calculation.

    Args:
        num_atoms: Number of atoms in the unit cell.
        num_electrons: Number of electrons.
        k_points: Number of k-points in the mesh.
        basis_size: "small", "medium", or "large" basis set.

    Returns:
        Dictionary with estimated memory (MB), cores, and walltime (hours).
    """
    # Base memory estimate (very rough)
    # Memory scales roughly as O(N^2) with system size for DFT
    basis_factor = {"small": 0.5, "medium": 1.0, "large": 2.0}.get(basis_size, 1.0)

    # Rough formula: 100 MB base + 10 MB per atom^2 * k_points * basis_factor
    memory_mb = 100 + 10 * (num_atoms**2) * k_points * basis_factor

    # Recommended cores: 1 per ~10 atoms, at least 1, at most 64
    cores = max(1, min(64, num_atoms // 10 + 1))

    # Walltime estimate: 0.5 hours base + 0.1 hours per atom * k_points
    walltime_hours = 0.5 + 0.1 * num_atoms * k_points * basis_factor

    return {
        "memory_mb": int(memory_mb),
        "num_cores": cores,
        "walltime_hours": round(walltime_hours, 1),
        "walltime_seconds": int(walltime_hours * 3600),
    }
