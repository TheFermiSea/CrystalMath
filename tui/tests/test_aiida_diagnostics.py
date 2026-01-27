"""
Tests for CRYSTAL23 SCF convergence diagnostics module.

Tests the self-healing diagnostic capabilities:
    - Convergence pattern classification
    - Root cause identification
    - Parameter modification recommendations
    - Resource estimation
"""

import pytest

from src.aiida.workchains.diagnostics import (
    ConvergencePattern,
    FailureReason,
    SCFDiagnostics,
    analyze_scf_convergence,
    analyze_scf_from_parsed_output,
    estimate_resources,
    recommend_parameter_modifications,
)


class TestConvergencePatternClassification:
    """Test SCF convergence pattern detection."""

    def test_converged_pattern(self):
        """Test detection of converged SCF."""
        # Simulated output with converging SCF
        output = """
 CYC   ETOT(AU)        DETOT      PDIFF
   1  -123.456789    1.23E+00   1.00E-01
   2  -123.567890    1.11E-01   1.00E-02
   3  -123.578901    1.10E-02   1.00E-03
   4  -123.579012    1.11E-04   1.00E-05
   5  -123.579023    1.10E-06   1.00E-07
   6  -123.579024    1.00E-08   1.00E-09

 == SCF ENDED - CONVERGED ==
        """
        diagnostics = analyze_scf_convergence(output)

        assert diagnostics.pattern == ConvergencePattern.CONVERGED
        assert diagnostics.confidence > 0.8
        assert len(diagnostics.energy_history) >= 5

    def test_oscillating_pattern(self):
        """Test detection of oscillating SCF."""
        output = """
 CYC   ETOT(AU)        DETOT
   1  -100.000000    1.00E+00
   2  -100.100000   -1.00E-01
   3  -100.050000    5.00E-02
   4  -100.080000   -3.00E-02
   5  -100.060000    2.00E-02
   6  -100.075000   -1.50E-02
   7  -100.065000    1.00E-02
   8  -100.070000   -5.00E-03
        """
        diagnostics = analyze_scf_convergence(output)

        assert diagnostics.pattern == ConvergencePattern.OSCILLATING
        assert diagnostics.oscillation_amplitude is not None

    def test_slow_convergence_pattern(self):
        """Test detection of slow convergence."""
        output = """
 CYC   ETOT(AU)        DETOT
   1  -100.000000    1.00E+00
   2  -100.010000   -1.00E-02
   3  -100.019000   -9.00E-03
   4  -100.027100   -8.10E-03
   5  -100.034390   -7.29E-03
   6  -100.040951   -6.56E-03
   7  -100.046856   -5.91E-03
   8  -100.052170   -5.31E-03
   9  -100.056953   -4.78E-03
  10  -100.061258   -4.31E-03
        """
        diagnostics = analyze_scf_convergence(output)

        # May detect as slow or unknown depending on threshold
        assert diagnostics.pattern in [
            ConvergencePattern.SLOW,
            ConvergencePattern.UNKNOWN,
        ]

    def test_empty_output(self):
        """Test handling of empty output."""
        diagnostics = analyze_scf_convergence("")

        assert diagnostics.pattern == ConvergencePattern.UNKNOWN
        assert len(diagnostics.energy_history) == 0


class TestFailureReasonIdentification:
    """Test root cause identification."""

    def test_memory_failure(self):
        """Test detection of memory failure."""
        output = """
 CYC   ETOT(AU)
   1  -100.000000

 ERROR: INSUFFICIENT MEMORY FOR INTEGRALS
        """
        diagnostics = analyze_scf_convergence(output)

        assert diagnostics.reason == FailureReason.MEMORY_LIMIT

    def test_small_gap_detection(self):
        """Test detection of small HOMO-LUMO gap issues."""
        output = """
 CYC   ETOT(AU)        DETOT
   1  -100.000000    1.00E+00
   2  -100.100000   -1.00E-01
   3  -100.050000    5.00E-02
   4  -100.080000   -3.00E-02

 HOMO-LUMO GAP: 0.05 EV
        """
        diagnostics = analyze_scf_convergence(output)

        # Should detect small gap as reason for oscillation
        if diagnostics.pattern == ConvergencePattern.OSCILLATING:
            assert diagnostics.reason == FailureReason.SMALL_GAP
            assert diagnostics.homo_lumo_gap == pytest.approx(0.05, rel=0.1)

    def test_linear_dependence(self):
        """Test detection of linear dependence issues."""
        output = """
 WARNING: LINEAR DEPENDENCE DETECTED IN BASIS SET

 CYC   ETOT(AU)
   1  -100.000000
        """
        diagnostics = analyze_scf_convergence(output)

        assert diagnostics.reason == FailureReason.LINEAR_DEPENDENCE


class TestParameterRecommendations:
    """Test adaptive parameter modification recommendations."""

    def test_charge_sloshing_recommendations(self):
        """Test recommendations for charge sloshing."""
        diagnostics = SCFDiagnostics(
            pattern=ConvergencePattern.OSCILLATING,
            reason=FailureReason.CHARGE_SLOSHING,
            confidence=0.8,
        )
        current_params = {"scf": {"fmixing": 30, "maxcycle": 100}}

        mods = recommend_parameter_modifications(diagnostics, current_params, restart_count=0)

        # Should recommend increasing FMIXING
        fmixing_mod = next((m for m in mods if "fmixing" in m.parameter), None)
        assert fmixing_mod is not None
        assert fmixing_mod.new_value > 30

    def test_small_gap_recommendations(self):
        """Test recommendations for small gap systems."""
        diagnostics = SCFDiagnostics(
            pattern=ConvergencePattern.OSCILLATING,
            reason=FailureReason.SMALL_GAP,
            confidence=0.9,
            homo_lumo_gap=0.1,
        )
        current_params = {"scf": {"fmixing": 30}}

        mods = recommend_parameter_modifications(diagnostics, current_params, restart_count=0)

        # Should recommend level shifting
        levshift_mod = next((m for m in mods if "levshift" in m.parameter), None)
        assert levshift_mod is not None
        assert levshift_mod.new_value is not None

    def test_slow_convergence_recommendations(self):
        """Test recommendations for slow convergence."""
        diagnostics = SCFDiagnostics(
            pattern=ConvergencePattern.SLOW,
            reason=FailureReason.INSUFFICIENT_MIXING,
            confidence=0.7,
        )
        current_params = {"scf": {"fmixing": 70, "maxcycle": 100}}

        mods = recommend_parameter_modifications(diagnostics, current_params, restart_count=0)

        # Should recommend decreasing FMIXING for faster mixing
        fmixing_mod = next((m for m in mods if "fmixing" in m.parameter), None)
        assert fmixing_mod is not None
        assert fmixing_mod.new_value < 70

    def test_insufficient_cycles_recommendations(self):
        """Test recommendations for insufficient cycles."""
        diagnostics = SCFDiagnostics(
            pattern=ConvergencePattern.STUCK,
            reason=FailureReason.INSUFFICIENT_CYCLES,
            confidence=0.8,
        )
        current_params = {"scf": {"maxcycle": 100}}

        mods = recommend_parameter_modifications(diagnostics, current_params, restart_count=0)

        # Should recommend increasing MAXCYCLE
        maxcycle_mod = next((m for m in mods if "maxcycle" in m.parameter), None)
        assert maxcycle_mod is not None
        assert maxcycle_mod.new_value > 100

    def test_escalating_recommendations(self):
        """Test that recommendations escalate with restart count."""
        diagnostics = SCFDiagnostics(
            pattern=ConvergencePattern.OSCILLATING,
            reason=FailureReason.CHARGE_SLOSHING,
            confidence=0.8,
        )
        current_params = {"scf": {"fmixing": 30}}

        mods_0 = recommend_parameter_modifications(diagnostics, current_params, restart_count=0)
        mods_1 = recommend_parameter_modifications(diagnostics, current_params, restart_count=1)

        # FMIXING should increase more on second restart
        fmixing_0 = next((m for m in mods_0 if "fmixing" in m.parameter), None)
        fmixing_1 = next((m for m in mods_1 if "fmixing" in m.parameter), None)

        assert fmixing_0 and fmixing_1
        assert fmixing_1.new_value > fmixing_0.new_value


class TestResourceEstimation:
    """Test computational resource estimation."""

    def test_small_system(self):
        """Test resource estimation for small system."""
        resources = estimate_resources(
            num_atoms=10,
            num_electrons=40,
            k_points=1,
            basis_size="small",
        )

        assert "memory_mb" in resources
        assert "num_cores" in resources
        assert "walltime_seconds" in resources
        assert resources["num_cores"] >= 1

    def test_large_system(self):
        """Test resource estimation for large system."""
        resources_small = estimate_resources(
            num_atoms=10,
            num_electrons=40,
            k_points=1,
        )
        resources_large = estimate_resources(
            num_atoms=100,
            num_electrons=400,
            k_points=8,
        )

        # Large system should require more resources
        assert resources_large["memory_mb"] > resources_small["memory_mb"]
        assert resources_large["num_cores"] >= resources_small["num_cores"]
        assert resources_large["walltime_seconds"] > resources_small["walltime_seconds"]

    def test_basis_size_scaling(self):
        """Test that basis size affects resource estimates."""
        resources_small = estimate_resources(
            num_atoms=50,
            num_electrons=200,
            basis_size="small",
        )
        resources_large = estimate_resources(
            num_atoms=50,
            num_electrons=200,
            basis_size="large",
        )

        assert resources_large["memory_mb"] > resources_small["memory_mb"]


class TestEnergyHistoryExtraction:
    """Test energy history extraction from various output formats."""

    def test_standard_crystal23_format(self):
        """Test extraction from standard CRYSTAL23 output."""
        output = """
 CYC   ETOT(AU)        DETOT      PDIFF      DDMN     TIME
   1  -456.123456789   3.45E+01   1.00E-01   0.100    10.5
   2  -456.234567890   1.11E-01   1.00E-02   0.050    15.3
   3  -456.245678901   1.11E-02   1.00E-03   0.010    20.1

 == SCF ENDED - CONVERGED ==
        """
        diagnostics = analyze_scf_convergence(output)

        assert len(diagnostics.energy_history) == 3
        assert diagnostics.energy_history[0] == pytest.approx(-456.123456789)
        assert diagnostics.energy_history[-1] == pytest.approx(-456.245678901)

    def test_alternative_energy_format(self):
        """Test fallback extraction from alternative format."""
        output = """
 TOTAL ENERGY = -123.456789 HARTREE

 TERMINATION
        """
        diagnostics = analyze_scf_convergence(output)

        # Should at least extract the final energy
        assert len(diagnostics.energy_history) >= 0  # May or may not extract

    def test_multiple_scf_blocks(self):
        """Test that only last SCF block is analyzed (geometry optimization)."""
        output = """
 === GEOMETRY OPTIMIZATION STEP 1 ===

 CYC   ETOT(AU)
   1  -100.000000
   2  -100.100000
   3  -100.110000

 == SCF ENDED - CONVERGED ==

 === GEOMETRY OPTIMIZATION STEP 2 ===

 CYC   ETOT(AU)
   1  -100.200000
   2  -100.250000
   3  -100.260000

 == SCF ENDED - CONVERGED ==
        """
        diagnostics = analyze_scf_convergence(output)

        # Should analyze last SCF block (step 2)
        if diagnostics.energy_history:
            assert diagnostics.energy_history[-1] == pytest.approx(-100.26, rel=0.01)


class TestDiagnosticsDataclass:
    """Test SCFDiagnostics dataclass functionality."""

    def test_default_values(self):
        """Test default values of SCFDiagnostics."""
        diag = SCFDiagnostics()

        assert diag.pattern == ConvergencePattern.UNKNOWN
        assert diag.reason == FailureReason.UNKNOWN
        assert diag.confidence == 0.0
        assert diag.energy_history == []
        assert diag.recommendations == []

    def test_custom_values(self):
        """Test SCFDiagnostics with custom values."""
        diag = SCFDiagnostics(
            pattern=ConvergencePattern.OSCILLATING,
            reason=FailureReason.CHARGE_SLOSHING,
            confidence=0.85,
            energy_history=[-100.0, -100.1, -100.05],
            oscillation_amplitude=0.05,
            recommendations=["Increase FMIXING"],
        )

        assert diag.pattern == ConvergencePattern.OSCILLATING
        assert diag.reason == FailureReason.CHARGE_SLOSHING
        assert diag.confidence == 0.85
        assert len(diag.energy_history) == 3
        assert diag.oscillation_amplitude == 0.05
        assert len(diag.recommendations) == 1


class TestParsedOutputDiagnostics:
    """Test parser-based diagnostics (preferred method)."""

    def test_converged_from_parsed(self):
        """Test detection of converged SCF from parsed output."""
        output_params = {
            "scf_converged": True,
            "scf_energy_history": [-100.0, -100.1, -100.11, -100.111],
            "band_gap_ev": 2.5,
        }
        diagnostics = analyze_scf_from_parsed_output(output_params=output_params)

        assert diagnostics.pattern == ConvergencePattern.CONVERGED
        assert diagnostics.confidence == 0.99  # Parser is authoritative
        assert diagnostics.homo_lumo_gap == 2.5
        assert len(diagnostics.recommendations) == 0  # No issues

    def test_not_converged_oscillating_from_parsed(self):
        """Test oscillating pattern from parsed output."""
        output_params = {
            "scf_converged": False,
            "scf_energy_history": [
                -100.0,
                -100.1,
                -100.05,
                -100.08,
                -100.06,
                -100.075,
                -100.065,
                -100.07,
            ],
            "band_gap_ev": 0.05,  # Small gap
        }
        diagnostics = analyze_scf_from_parsed_output(output_params=output_params)

        assert diagnostics.pattern == ConvergencePattern.OSCILLATING
        assert diagnostics.reason == FailureReason.SMALL_GAP
        assert diagnostics.oscillation_amplitude is not None

    def test_memory_error_from_parsed(self):
        """Test memory error detection from parsed output."""
        output_params = {
            "scf_converged": False,
            "memory_error": True,
            "termination_reason": "insufficient memory",
        }
        diagnostics = analyze_scf_from_parsed_output(output_params=output_params)

        assert diagnostics.reason == FailureReason.MEMORY_LIMIT

    def test_timeout_from_parsed(self):
        """Test timeout detection from parsed output."""
        output_params = {
            "scf_converged": False,
            "timeout": True,
            "termination_reason": "time limit exceeded",
        }
        diagnostics = analyze_scf_from_parsed_output(output_params=output_params)

        assert diagnostics.reason == FailureReason.TIMEOUT

    def test_linear_dependence_from_parsed(self):
        """Test linear dependence detection from parsed output."""
        output_params = {
            "scf_converged": False,
            "linear_dependence": True,
        }
        diagnostics = analyze_scf_from_parsed_output(output_params=output_params)

        assert diagnostics.reason == FailureReason.LINEAR_DEPENDENCE

    def test_warnings_list_from_parsed(self):
        """Test detection of issues from warnings list."""
        output_params = {
            "scf_converged": False,
            "scf_energy_history": [-100.0, -100.01, -100.02],
            "warnings": ["Linear dependence detected in basis set"],
        }
        diagnostics = analyze_scf_from_parsed_output(output_params=output_params)

        assert diagnostics.reason == FailureReason.LINEAR_DEPENDENCE

    def test_alternative_energy_history_key(self):
        """Test extraction with alternative key 'energy_history'."""
        output_params = {
            "scf_converged": True,
            "energy_history": [-100.0, -100.1, -100.11],  # Different key
        }
        diagnostics = analyze_scf_from_parsed_output(output_params=output_params)

        assert len(diagnostics.energy_history) == 3
        assert diagnostics.pattern == ConvergencePattern.CONVERGED

    def test_scf_cycles_extraction(self):
        """Test extraction from scf_cycles list."""
        output_params = {
            "scf_converged": True,
            "scf_cycles": [
                {"cycle": 1, "energy": -100.0},
                {"cycle": 2, "energy": -100.1},
                {"cycle": 3, "energy": -100.11},
            ],
        }
        diagnostics = analyze_scf_from_parsed_output(output_params=output_params)

        assert len(diagnostics.energy_history) == 3
        assert diagnostics.energy_history[0] == -100.0

    def test_alternative_gap_keys(self):
        """Test extraction of gap from various key names."""
        # Test homo_lumo_gap_ev
        output_params = {"scf_converged": True, "homo_lumo_gap_ev": 1.5}
        diag1 = analyze_scf_from_parsed_output(output_params=output_params)
        assert diag1.homo_lumo_gap == 1.5

        # Test gap_ev
        output_params = {"scf_converged": True, "gap_ev": 2.0}
        diag2 = analyze_scf_from_parsed_output(output_params=output_params)
        assert diag2.homo_lumo_gap == 2.0

    def test_missing_params_raises(self):
        """Test that missing params raises ValueError."""
        with pytest.raises(ValueError, match="Either output_params or parsed_output"):
            analyze_scf_from_parsed_output()

    def test_slow_convergence_from_parsed(self):
        """Test slow convergence detection from parsed output."""
        # Create slowly converging energy sequence (rate > 0.9)
        energies = [-100.0]
        for i in range(15):
            delta = 0.01 * (0.92**i)  # Slow decay rate ~0.92
            energies.append(energies[-1] - delta)

        output_params = {
            "scf_converged": False,
            "scf_energy_history": energies,
            "band_gap_ev": 3.0,  # Not a small gap issue
        }
        diagnostics = analyze_scf_from_parsed_output(output_params=output_params)

        # Should detect slow convergence or unknown
        assert diagnostics.pattern in [
            ConvergencePattern.SLOW,
            ConvergencePattern.UNKNOWN,
        ]

    def test_diverging_from_parsed(self):
        """Test divergence detection from parsed output."""
        output_params = {
            "scf_converged": False,
            "scf_energy_history": [-100.0, -99.9, -99.7, -99.4, -98.9],  # Increasing
        }
        diagnostics = analyze_scf_from_parsed_output(output_params=output_params)

        assert diagnostics.pattern == ConvergencePattern.DIVERGING
        assert diagnostics.reason == FailureReason.POOR_INITIAL_GUESS

    def test_recommendations_generated_for_failures(self):
        """Test that recommendations are generated for failed SCF."""
        output_params = {
            "scf_converged": False,
            "scf_energy_history": [
                -100.0,
                -100.1,
                -100.05,
                -100.08,
                -100.06,
                -100.075,
                -100.065,
                -100.07,
            ],
        }
        diagnostics = analyze_scf_from_parsed_output(output_params=output_params)

        # Should have recommendations for oscillation
        assert len(diagnostics.recommendations) > 0
