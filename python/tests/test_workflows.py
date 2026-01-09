"""Tests for workflow runners (runners.py module).

This module tests the high-level workflow runners including:
- BaseAnalysisRunner structure loading
- StandardAnalysis workflow building
- OpticalAnalysis multi-code workflows
- PhononAnalysis supercell workflows
- ElasticAnalysis strain workflows
- TransportAnalysis temperature workflows

Tests use mocking to avoid dependencies on actual DFT codes.
Many tests are skipped as methods are private or require complex mocking.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from dataclasses import dataclass

from crystalmath.protocols import (
    WorkflowType,
    WorkflowStep,
    WorkflowResult,
    ResourceRequirements,
    ErrorRecoveryStrategy,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_structure() -> Mock:
    """Create a mock pymatgen Structure."""
    mock = Mock()
    mock.formula = "NbOCl2"
    mock.composition.reduced_formula = "NbOCl2"
    mock.num_sites = 8
    mock.volume = 150.0
    mock.lattice.abc = (5.0, 5.0, 10.0)
    mock.lattice.angles = (90.0, 90.0, 90.0)
    mock.lattice.a = 5.0
    mock.lattice.b = 5.0
    mock.lattice.c = 10.0
    return mock


@pytest.fixture
def sample_cif_file(tmp_path: Path) -> Path:
    """Create a sample CIF file for testing."""
    cif_content = """data_NbOCl2
_cell_length_a 5.0
_cell_length_b 5.0
_cell_length_c 10.0
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Nb 0.0 0.0 0.0
O 0.5 0.5 0.0
Cl 0.25 0.25 0.25
Cl 0.75 0.75 0.75
"""
    cif_path = tmp_path / "test.cif"
    cif_path.write_text(cif_content)
    return cif_path


@pytest.fixture
def mock_workflow_result() -> WorkflowResult:
    """Create a mock workflow result."""
    return WorkflowResult(
        success=True,
        workflow_id="test-workflow-123",
        workflow_pk=1234,
        outputs={"energy": -10.5, "bandgap": 1.1},
    )


@pytest.fixture
def default_resources() -> ResourceRequirements:
    """Create default resource requirements."""
    return ResourceRequirements(
        num_nodes=1,
        num_mpi_ranks=40,
        num_threads_per_rank=1,
        memory_gb=100,
        walltime_hours=24,
        gpus=1,
    )


@pytest.fixture
def mock_cluster_profile() -> Mock:
    """Create a mock ClusterProfile."""
    mock = Mock()
    mock.name = "beefcake2"
    mock.available_codes = ["vasp", "crystal23", "quantum_espresso", "yambo"]
    mock.get_preset.return_value = ResourceRequirements(
        num_nodes=1,
        num_mpi_ranks=40,
        num_threads_per_rank=1,
        memory_gb=100,
        walltime_hours=24,
        gpus=1,
    )
    return mock


# =============================================================================
# Test RunnerConfig
# =============================================================================


class TestRunnerConfig:
    """Tests for RunnerConfig dataclass."""

    def test_create_runner_config(self) -> None:
        """Test creating a RunnerConfig."""
        from crystalmath.high_level.runners import RunnerConfig

        config = RunnerConfig(
            protocol="moderate",
            output_dir=Path("/tmp/test"),
            max_retries=3,
        )

        assert config.protocol == "moderate"
        assert config.max_retries == 3

    def test_runner_config_default_values(self) -> None:
        """Test RunnerConfig default values."""
        from crystalmath.high_level.runners import RunnerConfig

        config = RunnerConfig()

        assert config.protocol == "moderate"
        assert config.max_retries == 3
        assert config.dry_run is False

    def test_runner_config_invalid_protocol(self) -> None:
        """Test invalid protocol raises error."""
        from crystalmath.high_level.runners import RunnerConfig

        with pytest.raises(ValueError):
            RunnerConfig(protocol="invalid_protocol")

    @pytest.mark.parametrize("protocol", ["fast", "moderate", "precise"])
    def test_runner_config_valid_protocols(self, protocol: str) -> None:
        """Test all valid protocols."""
        from crystalmath.high_level.runners import RunnerConfig

        config = RunnerConfig(protocol=protocol)
        assert config.protocol == protocol


# =============================================================================
# Test StepResult
# =============================================================================


class TestStepResult:
    """Tests for StepResult dataclass."""

    def test_create_step_result(self) -> None:
        """Test creating a StepResult."""
        from crystalmath.high_level.runners import StepResult

        result = StepResult(
            step_name="scf",
            success=True,
            outputs={"energy": -10.5},
            wall_time_seconds=100.0,
        )

        assert result.step_name == "scf"
        assert result.success is True
        assert result.outputs["energy"] == -10.5

    def test_step_result_failure(self) -> None:
        """Test StepResult for failed step."""
        from crystalmath.high_level.runners import StepResult

        result = StepResult(
            step_name="scf",
            success=False,
            errors=["Convergence failed"],
        )

        assert result.success is False
        assert len(result.errors) == 1


# =============================================================================
# Test StandardAnalysis
# =============================================================================


class TestStandardAnalysis:
    """Tests for StandardAnalysis workflow runner."""

    def test_creation(self, mock_cluster_profile: Mock) -> None:
        """Test creating StandardAnalysis instance."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(
            cluster=mock_cluster_profile,
            protocol="moderate",
        )

        assert analysis is not None
        assert analysis.config.protocol == "moderate"

    def test_creation_with_options(self, mock_cluster_profile: Mock) -> None:
        """Test creating StandardAnalysis with options."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(
            cluster=mock_cluster_profile,
            include_relax=True,
            include_bands=True,
            include_dos=False,
        )

        assert analysis is not None

    def test_build_workflow_steps(self, mock_cluster_profile: Mock, mock_structure: Mock) -> None:
        """Test building workflow steps."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(
            cluster=mock_cluster_profile,
            include_relax=True,
            include_bands=True,
            include_dos=True,
        )

        # Set structure manually for testing
        analysis._structure = mock_structure
        analysis._structure_info = Mock(formula="Si", space_group_symbol="Fd-3m")

        # Build steps (accessing private method for testing)
        with patch.object(analysis, '_select_code', return_value='vasp'):
            steps = analysis._build_workflow_steps()

        assert len(steps) >= 2  # At least SCF and bands

    def test_workflow_types_included(self, mock_cluster_profile: Mock, mock_structure: Mock) -> None:
        """Test that correct workflow types are included."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(
            cluster=mock_cluster_profile,
            include_relax=True,
            include_bands=True,
            include_dos=True,
        )

        analysis._structure = mock_structure
        analysis._structure_info = Mock(formula="Si", space_group_symbol="Fd-3m")

        with patch.object(analysis, '_select_code', return_value='vasp'):
            steps = analysis._build_workflow_steps()

        workflow_types = [s.workflow_type for s in steps]
        assert WorkflowType.RELAX in workflow_types
        assert WorkflowType.SCF in workflow_types
        assert WorkflowType.BANDS in workflow_types
        assert WorkflowType.DOS in workflow_types


class TestStandardAnalysisProtocols:
    """Tests for StandardAnalysis with different protocols."""

    @pytest.mark.parametrize("protocol", ["fast", "moderate", "precise"])
    def test_protocol_setting(self, mock_cluster_profile: Mock, protocol: str) -> None:
        """Test that protocol is set correctly."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(
            cluster=mock_cluster_profile,
            protocol=protocol,
        )

        assert analysis.config.protocol == protocol


# =============================================================================
# Test OpticalAnalysis
# =============================================================================


class TestOpticalAnalysis:
    """Tests for OpticalAnalysis multi-code workflow runner."""

    def test_creation(self, mock_cluster_profile: Mock) -> None:
        """Test creating OpticalAnalysis instance."""
        from crystalmath.high_level.runners import OpticalAnalysis

        analysis = OpticalAnalysis(
            cluster=mock_cluster_profile,
            dft_code="vasp",
            gw_code="yambo",
        )

        assert analysis is not None

    def test_creation_with_gw_options(self, mock_cluster_profile: Mock) -> None:
        """Test creating OpticalAnalysis with GW options."""
        from crystalmath.high_level.runners import OpticalAnalysis

        analysis = OpticalAnalysis(
            cluster=mock_cluster_profile,
            dft_code="vasp",
            gw_code="yambo",
            gw_protocol="gw0",
            n_bands_gw=100,
            n_valence_bse=4,
            n_conduction_bse=4,
        )

        assert analysis is not None

    def test_build_workflow_steps(self, mock_cluster_profile: Mock, mock_structure: Mock) -> None:
        """Test building GW/BSE workflow steps."""
        from crystalmath.high_level.runners import OpticalAnalysis

        analysis = OpticalAnalysis(
            cluster=mock_cluster_profile,
            dft_code="vasp",
            gw_code="yambo",
            include_bse=True,
        )

        analysis._structure = mock_structure
        analysis._structure_info = Mock(formula="NbOCl2", space_group_symbol="Pmmn")

        steps = analysis._build_workflow_steps()

        # Should have DFT SCF, GW, and BSE
        assert len(steps) >= 2

        workflow_types = [s.workflow_type for s in steps]
        assert WorkflowType.SCF in workflow_types
        assert WorkflowType.GW in workflow_types


class TestOpticalAnalysisConfiguration:
    """Tests for OpticalAnalysis configuration options."""

    def test_gw_protocols(self, mock_cluster_profile: Mock) -> None:
        """Test different GW protocols."""
        from crystalmath.high_level.runners import OpticalAnalysis

        for protocol in ["g0w0", "gw0", "evgw"]:
            analysis = OpticalAnalysis(
                cluster=mock_cluster_profile,
                dft_code="vasp",
                gw_code="yambo",
                gw_protocol=protocol,
            )
            assert analysis._gw_protocol == protocol

    def test_code_not_available(self) -> None:
        """Test error when code not available on cluster."""
        from crystalmath.high_level.runners import OpticalAnalysis, CodeNotAvailableError

        mock_cluster = Mock()
        mock_cluster.available_codes = ["vasp"]  # yambo not available

        with pytest.raises(CodeNotAvailableError):
            OpticalAnalysis(
                cluster=mock_cluster,
                dft_code="vasp",
                gw_code="yambo",  # Not available
            )


# =============================================================================
# Test PhononAnalysis
# =============================================================================


class TestPhononAnalysis:
    """Tests for PhononAnalysis supercell workflow runner."""

    def test_creation(self, mock_cluster_profile: Mock) -> None:
        """Test creating PhononAnalysis instance."""
        from crystalmath.high_level.runners import PhononAnalysis

        analysis = PhononAnalysis(
            cluster=mock_cluster_profile,
            supercell=[2, 2, 2],
        )

        assert analysis is not None
        assert analysis._supercell == [2, 2, 2]

    def test_default_supercell(self, mock_cluster_profile: Mock) -> None:
        """Test default supercell size."""
        from crystalmath.high_level.runners import PhononAnalysis

        analysis = PhononAnalysis(cluster=mock_cluster_profile)

        assert analysis._supercell == [2, 2, 2]

    def test_custom_supercell(self, mock_cluster_profile: Mock) -> None:
        """Test custom supercell size."""
        from crystalmath.high_level.runners import PhononAnalysis

        analysis = PhononAnalysis(
            cluster=mock_cluster_profile,
            supercell=[3, 3, 3],
        )

        assert analysis._supercell == [3, 3, 3]

    def test_displacement_setting(self, mock_cluster_profile: Mock) -> None:
        """Test displacement amplitude setting."""
        from crystalmath.high_level.runners import PhononAnalysis

        analysis = PhononAnalysis(
            cluster=mock_cluster_profile,
            displacement=0.02,
        )

        assert analysis._displacement == 0.02

    def test_build_workflow_steps(self, mock_cluster_profile: Mock, mock_structure: Mock) -> None:
        """Test building phonon workflow steps."""
        from crystalmath.high_level.runners import PhononAnalysis

        analysis = PhononAnalysis(
            cluster=mock_cluster_profile,
            supercell=[2, 2, 2],
        )

        analysis._structure = mock_structure
        analysis._structure_info = Mock(formula="Si", space_group_symbol="Fd-3m")

        with patch.object(analysis, '_select_code', return_value='vasp'):
            steps = analysis._build_workflow_steps()

        assert len(steps) >= 2

        workflow_types = [s.workflow_type for s in steps]
        assert WorkflowType.RELAX in workflow_types
        assert WorkflowType.PHONON in workflow_types


# =============================================================================
# Test ElasticAnalysis
# =============================================================================


class TestElasticAnalysis:
    """Tests for ElasticAnalysis strain workflow runner."""

    def test_creation(self, mock_cluster_profile: Mock) -> None:
        """Test creating ElasticAnalysis instance."""
        from crystalmath.high_level.runners import ElasticAnalysis

        analysis = ElasticAnalysis(
            cluster=mock_cluster_profile,
            strain_magnitude=0.01,
        )

        assert analysis is not None
        assert analysis._strain_magnitude == 0.01

    def test_default_strain(self, mock_cluster_profile: Mock) -> None:
        """Test default strain magnitude."""
        from crystalmath.high_level.runners import ElasticAnalysis

        analysis = ElasticAnalysis(cluster=mock_cluster_profile)

        assert analysis._strain_magnitude == 0.01

    def test_custom_strain(self, mock_cluster_profile: Mock) -> None:
        """Test custom strain magnitude."""
        from crystalmath.high_level.runners import ElasticAnalysis

        analysis = ElasticAnalysis(
            cluster=mock_cluster_profile,
            strain_magnitude=0.02,
        )

        assert analysis._strain_magnitude == 0.02

    def test_num_strains_setting(self, mock_cluster_profile: Mock) -> None:
        """Test number of strains setting."""
        from crystalmath.high_level.runners import ElasticAnalysis

        analysis = ElasticAnalysis(
            cluster=mock_cluster_profile,
            num_strains=8,
        )

        assert analysis._num_strains == 8

    def test_build_workflow_steps(self, mock_cluster_profile: Mock, mock_structure: Mock) -> None:
        """Test building elastic workflow steps."""
        from crystalmath.high_level.runners import ElasticAnalysis

        analysis = ElasticAnalysis(
            cluster=mock_cluster_profile,
            strain_magnitude=0.01,
        )

        analysis._structure = mock_structure
        analysis._structure_info = Mock(formula="TiO2", space_group_symbol="P42/mnm")

        steps = analysis._build_workflow_steps()

        assert len(steps) >= 2

        workflow_types = [s.workflow_type for s in steps]
        assert WorkflowType.RELAX in workflow_types
        assert WorkflowType.ELASTIC in workflow_types


# =============================================================================
# Test TransportAnalysis
# =============================================================================


class TestTransportAnalysis:
    """Tests for TransportAnalysis temperature workflow runner."""

    def test_creation(self, mock_cluster_profile: Mock) -> None:
        """Test creating TransportAnalysis instance."""
        from crystalmath.high_level.runners import TransportAnalysis

        analysis = TransportAnalysis(
            cluster=mock_cluster_profile,
            doping_levels=[1e18, 1e19, 1e20],
        )

        assert analysis is not None

    def test_default_doping_levels(self, mock_cluster_profile: Mock) -> None:
        """Test default doping levels."""
        from crystalmath.high_level.runners import TransportAnalysis

        analysis = TransportAnalysis(cluster=mock_cluster_profile)

        assert analysis._doping_levels == [1e18, 1e19, 1e20]

    def test_custom_doping_levels(self, mock_cluster_profile: Mock) -> None:
        """Test custom doping levels."""
        from crystalmath.high_level.runners import TransportAnalysis

        analysis = TransportAnalysis(
            cluster=mock_cluster_profile,
            doping_levels=[1e17, 1e18],
        )

        assert analysis._doping_levels == [1e17, 1e18]

    def test_temperature_range(self, mock_cluster_profile: Mock) -> None:
        """Test temperature range setting."""
        from crystalmath.high_level.runners import TransportAnalysis

        analysis = TransportAnalysis(
            cluster=mock_cluster_profile,
            temperature_range=(100, 500, 50),
        )

        assert analysis._temperature_range == (100, 500, 50)

    def test_build_workflow_steps(self, mock_cluster_profile: Mock, mock_structure: Mock) -> None:
        """Test building transport workflow steps."""
        from crystalmath.high_level.runners import TransportAnalysis

        analysis = TransportAnalysis(
            cluster=mock_cluster_profile,
        )

        analysis._structure = mock_structure
        analysis._structure_info = Mock(formula="Bi2Te3", space_group_symbol="R-3m")

        steps = analysis._build_workflow_steps()

        assert len(steps) >= 2

        workflow_types = [s.workflow_type for s in steps]
        assert WorkflowType.RELAX in workflow_types
        assert WorkflowType.SCF in workflow_types


# =============================================================================
# Test Exceptions
# =============================================================================


class TestRunnerExceptions:
    """Tests for runner exception classes."""

    def test_runner_error(self) -> None:
        """Test base RunnerError."""
        from crystalmath.high_level.runners import RunnerError

        error = RunnerError("Test error")
        assert str(error) == "Test error"

    def test_structure_load_error(self) -> None:
        """Test StructureLoadError."""
        from crystalmath.high_level.runners import StructureLoadError

        error = StructureLoadError("Failed to load structure")
        assert isinstance(error, Exception)

    def test_workflow_build_error(self) -> None:
        """Test WorkflowBuildError."""
        from crystalmath.high_level.runners import WorkflowBuildError

        error = WorkflowBuildError("Failed to build workflow")
        assert isinstance(error, Exception)

    def test_workflow_execution_error(self) -> None:
        """Test WorkflowExecutionError."""
        from crystalmath.high_level.runners import WorkflowExecutionError

        error = WorkflowExecutionError("Execution failed")
        assert isinstance(error, Exception)

    def test_code_not_available_error(self) -> None:
        """Test CodeNotAvailableError."""
        from crystalmath.high_level.runners import CodeNotAvailableError

        error = CodeNotAvailableError("Code not available")
        assert isinstance(error, Exception)

    def test_multi_code_handoff_error(self) -> None:
        """Test MultiCodeHandoffError."""
        from crystalmath.high_level.runners import MultiCodeHandoffError

        error = MultiCodeHandoffError("Handoff failed")
        assert isinstance(error, Exception)


# =============================================================================
# Test Module Exports
# =============================================================================


class TestModuleExports:
    """Tests for module exports."""

    def test_all_runners_exported(self) -> None:
        """Test that all runner classes are exported."""
        from crystalmath.high_level import runners

        assert hasattr(runners, "BaseAnalysisRunner")
        assert hasattr(runners, "StandardAnalysis")
        assert hasattr(runners, "OpticalAnalysis")
        assert hasattr(runners, "PhononAnalysis")
        assert hasattr(runners, "ElasticAnalysis")
        assert hasattr(runners, "TransportAnalysis")

    def test_all_config_classes_exported(self) -> None:
        """Test that config classes are exported."""
        from crystalmath.high_level import runners

        assert hasattr(runners, "RunnerConfig")
        assert hasattr(runners, "StepResult")

    def test_all_exceptions_exported(self) -> None:
        """Test that exceptions are exported."""
        from crystalmath.high_level import runners

        assert hasattr(runners, "RunnerError")
        assert hasattr(runners, "StructureLoadError")
        assert hasattr(runners, "WorkflowBuildError")
        assert hasattr(runners, "WorkflowExecutionError")
        assert hasattr(runners, "CodeNotAvailableError")
        assert hasattr(runners, "MultiCodeHandoffError")
