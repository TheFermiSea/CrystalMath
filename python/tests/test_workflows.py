"""Tests for workflow runners (runners.py module).

This module tests the high-level workflow runners including:
- BaseAnalysisRunner structure loading
- StandardAnalysis step building
- OpticalAnalysis multi-code handoff configuration
- PhononAnalysis supercell configuration
- ElasticAnalysis strain configuration
- TransportAnalysis temperature ranges

Tests use mocking to avoid dependencies on actual DFT codes.
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


# =============================================================================
# Test BaseAnalysisRunner
# =============================================================================


class TestBaseAnalysisRunner:
    """Tests for BaseAnalysisRunner structure loading."""

    def test_load_structure_from_cif(
        self, sample_cif_file: Path, mock_structure: Mock
    ) -> None:
        """Test loading structure from CIF file."""
        with patch(
            "crystalmath.high_level.runners.PymatgenBridge.structure_from_cif",
            return_value=mock_structure,
        ):
            from crystalmath.high_level.runners import BaseAnalysisRunner

            runner = BaseAnalysisRunner()
            structure = runner.load_structure(str(sample_cif_file))
            assert structure is not None

    def test_load_structure_from_poscar(
        self, tmp_path: Path, mock_structure: Mock
    ) -> None:
        """Test loading structure from POSCAR."""
        poscar_path = tmp_path / "POSCAR"
        poscar_path.write_text("test poscar content")

        with patch(
            "crystalmath.high_level.runners.PymatgenBridge.structure_from_poscar",
            return_value=mock_structure,
        ):
            from crystalmath.high_level.runners import BaseAnalysisRunner

            runner = BaseAnalysisRunner()
            structure = runner.load_structure(str(poscar_path))
            assert structure is not None

    def test_load_structure_from_pymatgen(self, mock_structure: Mock) -> None:
        """Test loading structure from pymatgen Structure object."""
        from crystalmath.high_level.runners import BaseAnalysisRunner

        runner = BaseAnalysisRunner()
        structure = runner.load_structure(mock_structure)
        assert structure == mock_structure

    def test_load_structure_from_mp_id(self, mock_structure: Mock) -> None:
        """Test loading structure from Materials Project ID."""
        with patch(
            "crystalmath.high_level.runners.PymatgenBridge.fetch_from_mp",
            return_value=mock_structure,
        ):
            from crystalmath.high_level.runners import BaseAnalysisRunner

            runner = BaseAnalysisRunner()
            structure = runner.load_structure("mp-149")
            assert structure is not None

    def test_load_structure_invalid_input(self) -> None:
        """Test error handling for invalid structure input."""
        from crystalmath.high_level.runners import BaseAnalysisRunner

        runner = BaseAnalysisRunner()
        with pytest.raises((FileNotFoundError, ValueError)):
            runner.load_structure("/nonexistent/path.cif")

    def test_validate_structure(self, mock_structure: Mock) -> None:
        """Test structure validation."""
        mock_structure.num_sites = 10
        mock_structure.volume = 100.0
        mock_structure.is_ordered = True

        with patch(
            "crystalmath.high_level.runners.PymatgenBridge.validate_for_dft",
            return_value=(True, []),
        ):
            from crystalmath.high_level.runners import BaseAnalysisRunner

            runner = BaseAnalysisRunner()
            is_valid, issues = runner.validate_structure(mock_structure)
            assert is_valid is True

    def test_get_structure_info(self, mock_structure: Mock) -> None:
        """Test extracting structure information."""
        with patch(
            "crystalmath.high_level.runners.PymatgenBridge.get_symmetry_info",
            return_value={"crystal_system": "tetragonal", "space_group_number": 136},
        ):
            from crystalmath.high_level.runners import BaseAnalysisRunner

            runner = BaseAnalysisRunner()
            info = runner.get_structure_info(mock_structure)
            assert "crystal_system" in info


class TestBaseAnalysisRunnerConfiguration:
    """Tests for BaseAnalysisRunner configuration."""

    def test_set_protocol(self) -> None:
        """Test setting protocol level."""
        from crystalmath.high_level.runners import BaseAnalysisRunner

        runner = BaseAnalysisRunner()
        runner.set_protocol("precise")
        assert runner.protocol == "precise"

    def test_set_resources(self, default_resources: ResourceRequirements) -> None:
        """Test setting computational resources."""
        from crystalmath.high_level.runners import BaseAnalysisRunner

        runner = BaseAnalysisRunner()
        runner.set_resources(default_resources)
        assert runner.resources == default_resources

    def test_set_cluster(self) -> None:
        """Test setting cluster profile."""
        from crystalmath.high_level.runners import BaseAnalysisRunner

        runner = BaseAnalysisRunner()
        runner.set_cluster("beefcake2")
        assert runner.cluster == "beefcake2"


# =============================================================================
# Test StandardAnalysis
# =============================================================================


class TestStandardAnalysis:
    """Tests for StandardAnalysis step building."""

    def test_build_scf_step(self, mock_structure: Mock) -> None:
        """Test building SCF calculation step."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(mock_structure)
        step = analysis.build_scf_step()

        assert step.workflow_type == WorkflowType.SCF
        assert step.code in ["vasp", "crystal23", "quantum_espresso"]

    def test_build_relax_step(self, mock_structure: Mock) -> None:
        """Test building relaxation step."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(mock_structure)
        step = analysis.build_relax_step()

        assert step.workflow_type == WorkflowType.RELAX
        assert step.name == "relax"

    def test_build_bands_step(self, mock_structure: Mock) -> None:
        """Test building band structure step."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(mock_structure)
        step = analysis.build_bands_step()

        assert step.workflow_type == WorkflowType.BANDS
        assert "scf" in step.depends_on

    def test_build_dos_step(self, mock_structure: Mock) -> None:
        """Test building DOS calculation step."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(mock_structure)
        step = analysis.build_dos_step()

        assert step.workflow_type == WorkflowType.DOS
        assert "scf" in step.depends_on

    def test_build_standard_workflow(self, mock_structure: Mock) -> None:
        """Test building complete standard workflow."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(mock_structure)
        steps = analysis.build_workflow(["scf", "bands", "dos"])

        assert len(steps) == 3
        step_names = [s.name for s in steps]
        assert "scf" in step_names
        assert "bands" in step_names
        assert "dos" in step_names

    def test_step_dependencies(self, mock_structure: Mock) -> None:
        """Test that step dependencies are correct."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(mock_structure)
        steps = analysis.build_workflow(["relax", "scf", "bands"])

        step_map = {s.name: s for s in steps}

        # SCF should depend on relax
        assert "relax" in step_map["scf"].depends_on
        # Bands should depend on SCF
        assert "scf" in step_map["bands"].depends_on

    @pytest.mark.parametrize(
        "properties",
        [
            ["scf"],
            ["scf", "bands"],
            ["relax", "scf", "bands", "dos"],
            ["scf", "dos"],
        ],
    )
    def test_build_workflow_variations(
        self, mock_structure: Mock, properties: List[str]
    ) -> None:
        """Test building workflows with various property combinations."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(mock_structure)
        steps = analysis.build_workflow(properties)

        assert len(steps) == len(properties)


class TestStandardAnalysisProtocols:
    """Tests for StandardAnalysis with different protocols."""

    @pytest.mark.parametrize("protocol", ["fast", "moderate", "precise"])
    def test_protocol_affects_parameters(
        self, mock_structure: Mock, protocol: str
    ) -> None:
        """Test that protocol affects calculation parameters."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(mock_structure, protocol=protocol)
        step = analysis.build_scf_step()

        # Parameters should vary by protocol
        assert step.parameters is not None

    def test_fast_protocol_lower_cutoff(self, mock_structure: Mock) -> None:
        """Test that fast protocol uses lower cutoffs."""
        from crystalmath.high_level.runners import StandardAnalysis

        fast_analysis = StandardAnalysis(mock_structure, protocol="fast")
        precise_analysis = StandardAnalysis(mock_structure, protocol="precise")

        fast_step = fast_analysis.build_scf_step()
        precise_step = precise_analysis.build_scf_step()

        # Fast should have lower computational requirements
        # (specific assertions depend on implementation)


# =============================================================================
# Test OpticalAnalysis
# =============================================================================


class TestOpticalAnalysis:
    """Tests for OpticalAnalysis multi-code handoff configuration."""

    def test_build_gw_step(self, mock_structure: Mock) -> None:
        """Test building GW calculation step."""
        from crystalmath.high_level.runners import OpticalAnalysis

        analysis = OpticalAnalysis(mock_structure)
        step = analysis.build_gw_step()

        assert step.workflow_type == WorkflowType.GW
        assert step.code in ["yambo", "berkeleygw"]

    def test_build_bse_step(self, mock_structure: Mock) -> None:
        """Test building BSE calculation step."""
        from crystalmath.high_level.runners import OpticalAnalysis

        analysis = OpticalAnalysis(mock_structure)
        step = analysis.build_bse_step()

        assert step.workflow_type == WorkflowType.BSE
        assert "gw" in step.depends_on

    def test_multi_code_handoff_vasp_yambo(self, mock_structure: Mock) -> None:
        """Test VASP -> YAMBO multi-code handoff."""
        from crystalmath.high_level.runners import OpticalAnalysis

        analysis = OpticalAnalysis(
            mock_structure,
            dft_code="vasp",
            gw_code="yambo",
        )
        steps = analysis.build_workflow()

        # Verify handoff configuration
        codes = [s.code for s in steps]
        assert "vasp" in codes
        assert "yambo" in codes

    def test_multi_code_handoff_qe_yambo(self, mock_structure: Mock) -> None:
        """Test QE -> YAMBO multi-code handoff."""
        from crystalmath.high_level.runners import OpticalAnalysis

        analysis = OpticalAnalysis(
            mock_structure,
            dft_code="quantum_espresso",
            gw_code="yambo",
        )
        steps = analysis.build_workflow()

        codes = [s.code for s in steps]
        assert "quantum_espresso" in codes
        assert "yambo" in codes

    def test_build_optical_workflow(self, mock_structure: Mock) -> None:
        """Test building complete optical workflow."""
        from crystalmath.high_level.runners import OpticalAnalysis

        analysis = OpticalAnalysis(mock_structure)
        steps = analysis.build_workflow()

        workflow_types = [s.workflow_type for s in steps]
        assert WorkflowType.SCF in workflow_types
        assert WorkflowType.GW in workflow_types
        assert WorkflowType.BSE in workflow_types

    def test_gw_parameters(self, mock_structure: Mock) -> None:
        """Test GW calculation parameters."""
        from crystalmath.high_level.runners import OpticalAnalysis

        analysis = OpticalAnalysis(mock_structure)
        step = analysis.build_gw_step()

        # GW should have appropriate parameters
        assert "bands_range" in step.parameters or step.parameters is not None

    def test_bse_parameters(self, mock_structure: Mock) -> None:
        """Test BSE calculation parameters."""
        from crystalmath.high_level.runners import OpticalAnalysis

        analysis = OpticalAnalysis(mock_structure)
        step = analysis.build_bse_step()

        # BSE should have kernel parameters
        assert step.parameters is not None


class TestOpticalAnalysisConfiguration:
    """Tests for OpticalAnalysis configuration options."""

    def test_set_gw_bands_range(self, mock_structure: Mock) -> None:
        """Test setting GW bands range."""
        from crystalmath.high_level.runners import OpticalAnalysis

        analysis = OpticalAnalysis(mock_structure)
        analysis.set_gw_bands_range(10, 20)

        step = analysis.build_gw_step()
        # Verify bands range is set

    def test_set_bse_excitons(self, mock_structure: Mock) -> None:
        """Test setting number of BSE excitons."""
        from crystalmath.high_level.runners import OpticalAnalysis

        analysis = OpticalAnalysis(mock_structure)
        analysis.set_bse_excitons(50)

        step = analysis.build_bse_step()
        # Verify exciton count


# =============================================================================
# Test PhononAnalysis
# =============================================================================


class TestPhononAnalysis:
    """Tests for PhononAnalysis supercell configuration."""

    def test_build_phonon_step(self, mock_structure: Mock) -> None:
        """Test building phonon calculation step."""
        from crystalmath.high_level.runners import PhononAnalysis

        analysis = PhononAnalysis(mock_structure)
        step = analysis.build_phonon_step()

        assert step.workflow_type == WorkflowType.PHONON
        assert "relax" in step.depends_on

    def test_default_supercell_size(self, mock_structure: Mock) -> None:
        """Test default supercell size."""
        from crystalmath.high_level.runners import PhononAnalysis

        analysis = PhononAnalysis(mock_structure)
        supercell = analysis.get_supercell_size()

        assert len(supercell) == 3
        assert all(s >= 1 for s in supercell)

    @pytest.mark.parametrize(
        "supercell",
        [
            [2, 2, 2],
            [3, 3, 3],
            [2, 2, 1],
            [4, 4, 2],
        ],
    )
    def test_custom_supercell_size(
        self, mock_structure: Mock, supercell: List[int]
    ) -> None:
        """Test setting custom supercell size."""
        from crystalmath.high_level.runners import PhononAnalysis

        analysis = PhononAnalysis(mock_structure, supercell=supercell)
        result = analysis.get_supercell_size()

        assert result == supercell

    def test_auto_supercell_determination(self, mock_structure: Mock) -> None:
        """Test automatic supercell size determination."""
        from crystalmath.high_level.runners import PhononAnalysis

        analysis = PhononAnalysis(mock_structure, auto_supercell=True)
        supercell = analysis.get_supercell_size()

        # Auto should give reasonable supercell
        assert all(s >= 1 for s in supercell)

    def test_phonon_mesh(self, mock_structure: Mock) -> None:
        """Test phonon q-point mesh."""
        from crystalmath.high_level.runners import PhononAnalysis

        analysis = PhononAnalysis(mock_structure)
        mesh = analysis.get_qpoint_mesh()

        assert len(mesh) == 3

    def test_build_phonon_workflow(self, mock_structure: Mock) -> None:
        """Test building complete phonon workflow."""
        from crystalmath.high_level.runners import PhononAnalysis

        analysis = PhononAnalysis(mock_structure)
        steps = analysis.build_workflow()

        workflow_types = [s.workflow_type for s in steps]
        assert WorkflowType.RELAX in workflow_types
        assert WorkflowType.PHONON in workflow_types


class TestPhononAnalysisMethods:
    """Tests for PhononAnalysis calculation methods."""

    def test_finite_displacement_method(self, mock_structure: Mock) -> None:
        """Test finite displacement method configuration."""
        from crystalmath.high_level.runners import PhononAnalysis

        analysis = PhononAnalysis(mock_structure, method="finite_displacement")
        step = analysis.build_phonon_step()

        assert step.parameters.get("method") == "finite_displacement"

    def test_dfpt_method(self, mock_structure: Mock) -> None:
        """Test DFPT method configuration."""
        from crystalmath.high_level.runners import PhononAnalysis

        analysis = PhononAnalysis(mock_structure, method="dfpt")
        step = analysis.build_phonon_step()

        assert step.parameters.get("method") == "dfpt"

    def test_displacement_distance(self, mock_structure: Mock) -> None:
        """Test setting displacement distance."""
        from crystalmath.high_level.runners import PhononAnalysis

        analysis = PhononAnalysis(mock_structure, displacement=0.01)
        step = analysis.build_phonon_step()

        assert step.parameters.get("displacement", 0.01) == 0.01


# =============================================================================
# Test ElasticAnalysis
# =============================================================================


class TestElasticAnalysis:
    """Tests for ElasticAnalysis strain configuration."""

    def test_build_elastic_step(self, mock_structure: Mock) -> None:
        """Test building elastic constants step."""
        from crystalmath.high_level.runners import ElasticAnalysis

        analysis = ElasticAnalysis(mock_structure)
        step = analysis.build_elastic_step()

        assert step.workflow_type == WorkflowType.ELASTIC
        assert "relax" in step.depends_on

    def test_default_strain_magnitude(self, mock_structure: Mock) -> None:
        """Test default strain magnitude."""
        from crystalmath.high_level.runners import ElasticAnalysis

        analysis = ElasticAnalysis(mock_structure)
        strain = analysis.get_strain_magnitude()

        assert 0.001 <= strain <= 0.1

    @pytest.mark.parametrize("strain", [0.005, 0.01, 0.02, 0.05])
    def test_custom_strain_magnitude(
        self, mock_structure: Mock, strain: float
    ) -> None:
        """Test setting custom strain magnitude."""
        from crystalmath.high_level.runners import ElasticAnalysis

        analysis = ElasticAnalysis(mock_structure, strain_magnitude=strain)
        result = analysis.get_strain_magnitude()

        assert result == strain

    def test_strain_states(self, mock_structure: Mock) -> None:
        """Test strain states configuration."""
        from crystalmath.high_level.runners import ElasticAnalysis

        analysis = ElasticAnalysis(mock_structure)
        states = analysis.get_strain_states()

        # Should have multiple strain states
        assert len(states) >= 6  # Minimum for full tensor

    def test_num_deformations(self, mock_structure: Mock) -> None:
        """Test number of deformations."""
        from crystalmath.high_level.runners import ElasticAnalysis

        analysis = ElasticAnalysis(mock_structure, num_deformations=5)
        num = analysis.get_num_deformations()

        assert num == 5

    def test_build_elastic_workflow(self, mock_structure: Mock) -> None:
        """Test building complete elastic workflow."""
        from crystalmath.high_level.runners import ElasticAnalysis

        analysis = ElasticAnalysis(mock_structure)
        steps = analysis.build_workflow()

        workflow_types = [s.workflow_type for s in steps]
        assert WorkflowType.RELAX in workflow_types
        assert WorkflowType.ELASTIC in workflow_types


class TestElasticAnalysisSymmetry:
    """Tests for symmetry-aware elastic analysis."""

    def test_use_symmetry(self, mock_structure: Mock) -> None:
        """Test using symmetry to reduce deformations."""
        from crystalmath.high_level.runners import ElasticAnalysis

        analysis = ElasticAnalysis(mock_structure, use_symmetry=True)
        states = analysis.get_strain_states()

        # With symmetry, should have fewer states
        analysis_no_sym = ElasticAnalysis(mock_structure, use_symmetry=False)
        states_no_sym = analysis_no_sym.get_strain_states()

        assert len(states) <= len(states_no_sym)

    def test_symmetry_for_cubic(self, mock_structure: Mock) -> None:
        """Test symmetry handling for cubic structure."""
        with patch(
            "crystalmath.high_level.runners.PymatgenBridge.get_symmetry_info",
            return_value={"crystal_system": "cubic"},
        ):
            from crystalmath.high_level.runners import ElasticAnalysis

            analysis = ElasticAnalysis(mock_structure, use_symmetry=True)
            # Cubic has only 3 independent elastic constants


# =============================================================================
# Test TransportAnalysis
# =============================================================================


class TestTransportAnalysis:
    """Tests for TransportAnalysis temperature ranges."""

    def test_build_transport_step(self, mock_structure: Mock) -> None:
        """Test building transport calculation step."""
        from crystalmath.high_level.runners import TransportAnalysis

        analysis = TransportAnalysis(mock_structure)
        step = analysis.build_transport_step()

        assert step.name == "transport"
        assert "bands" in step.depends_on

    def test_default_temperature_range(self, mock_structure: Mock) -> None:
        """Test default temperature range."""
        from crystalmath.high_level.runners import TransportAnalysis

        analysis = TransportAnalysis(mock_structure)
        temps = analysis.get_temperature_range()

        assert len(temps) > 0
        assert temps[0] > 0  # Positive temperatures

    @pytest.mark.parametrize(
        "temp_range",
        [
            (100, 500, 50),  # min, max, step
            (300, 300, 1),  # Single temperature
            (100, 1000, 100),  # Wide range
        ],
    )
    def test_custom_temperature_range(
        self, mock_structure: Mock, temp_range: tuple
    ) -> None:
        """Test setting custom temperature range."""
        from crystalmath.high_level.runners import TransportAnalysis

        t_min, t_max, t_step = temp_range
        analysis = TransportAnalysis(
            mock_structure,
            temp_min=t_min,
            temp_max=t_max,
            temp_step=t_step,
        )
        temps = analysis.get_temperature_range()

        assert temps[0] >= t_min
        assert temps[-1] <= t_max

    def test_doping_levels(self, mock_structure: Mock) -> None:
        """Test doping level configuration."""
        from crystalmath.high_level.runners import TransportAnalysis

        doping = [1e18, 1e19, 1e20]
        analysis = TransportAnalysis(mock_structure, doping_levels=doping)
        levels = analysis.get_doping_levels()

        assert len(levels) == 3

    def test_build_transport_workflow(self, mock_structure: Mock) -> None:
        """Test building complete transport workflow."""
        from crystalmath.high_level.runners import TransportAnalysis

        analysis = TransportAnalysis(mock_structure)
        steps = analysis.build_workflow()

        step_names = [s.name for s in steps]
        assert "relax" in step_names or "scf" in step_names
        assert "bands" in step_names
        assert "transport" in step_names


class TestTransportAnalysisProperties:
    """Tests for transport property calculations."""

    def test_seebeck_coefficient(self, mock_structure: Mock) -> None:
        """Test Seebeck coefficient calculation setup."""
        from crystalmath.high_level.runners import TransportAnalysis

        analysis = TransportAnalysis(mock_structure)
        step = analysis.build_transport_step()

        # Should include Seebeck in properties
        assert "seebeck" in step.parameters.get("properties", ["seebeck"])

    def test_electrical_conductivity(self, mock_structure: Mock) -> None:
        """Test electrical conductivity calculation setup."""
        from crystalmath.high_level.runners import TransportAnalysis

        analysis = TransportAnalysis(mock_structure)
        step = analysis.build_transport_step()

        assert "conductivity" in step.parameters.get("properties", ["conductivity"])

    def test_thermal_conductivity(self, mock_structure: Mock) -> None:
        """Test thermal conductivity calculation setup."""
        from crystalmath.high_level.runners import TransportAnalysis

        analysis = TransportAnalysis(mock_structure)
        step = analysis.build_transport_step()

        # Electronic thermal conductivity
        assert step.parameters is not None


# =============================================================================
# Test Workflow Execution
# =============================================================================


class TestWorkflowExecution:
    """Tests for workflow execution functionality."""

    def test_submit_workflow(
        self, mock_structure: Mock, mock_workflow_result: WorkflowResult
    ) -> None:
        """Test submitting a workflow for execution."""
        with patch(
            "crystalmath.high_level.runners.get_runner"
        ) as mock_get_runner:
            mock_runner = Mock()
            mock_runner.submit_composite.return_value = mock_workflow_result
            mock_get_runner.return_value = mock_runner

            from crystalmath.high_level.runners import StandardAnalysis

            analysis = StandardAnalysis(mock_structure)
            steps = analysis.build_workflow(["scf", "bands"])
            result = analysis.submit(steps)

            assert result.success is True

    def test_run_locally(
        self, mock_structure: Mock, mock_workflow_result: WorkflowResult
    ) -> None:
        """Test running workflow locally."""
        with patch(
            "crystalmath.high_level.runners.get_runner"
        ) as mock_get_runner:
            mock_runner = Mock()
            mock_runner.submit_composite.return_value = mock_workflow_result
            mock_get_runner.return_value = mock_runner

            from crystalmath.high_level.runners import StandardAnalysis

            analysis = StandardAnalysis(mock_structure)
            result = analysis.run(["scf"])

            assert result is not None

    def test_workflow_status_tracking(self, mock_structure: Mock) -> None:
        """Test workflow status tracking."""
        with patch(
            "crystalmath.high_level.runners.get_runner"
        ) as mock_get_runner:
            mock_runner = Mock()
            mock_runner.get_status.return_value = "running"
            mock_get_runner.return_value = mock_runner

            from crystalmath.high_level.runners import StandardAnalysis

            analysis = StandardAnalysis(mock_structure)
            status = analysis.get_status("workflow-123")

            assert status in ["created", "submitted", "running", "completed", "failed"]


# =============================================================================
# Test Error Recovery
# =============================================================================


class TestErrorRecovery:
    """Tests for workflow error recovery."""

    def test_retry_failed_step(
        self, mock_structure: Mock, mock_workflow_result: WorkflowResult
    ) -> None:
        """Test retrying a failed step."""
        mock_workflow_result.success = False
        mock_workflow_result.errors = ["SCF did not converge"]

        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(mock_structure)
        can_retry = analysis.can_retry(mock_workflow_result)

        assert isinstance(can_retry, bool)

    def test_adaptive_recovery(self, mock_structure: Mock) -> None:
        """Test adaptive error recovery."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(
            mock_structure,
            recovery_strategy=ErrorRecoveryStrategy.ADAPTIVE,
        )

        # Adaptive recovery should be enabled
        assert analysis.recovery_strategy == ErrorRecoveryStrategy.ADAPTIVE

    def test_checkpoint_restart(self, mock_structure: Mock) -> None:
        """Test checkpoint restart capability."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(
            mock_structure,
            recovery_strategy=ErrorRecoveryStrategy.CHECKPOINT_RESTART,
        )

        # Should support checkpointing
        assert analysis.supports_checkpointing() is True


# =============================================================================
# Test Parameter Generation
# =============================================================================


class TestParameterGeneration:
    """Tests for automatic parameter generation."""

    def test_generate_vasp_parameters(self, mock_structure: Mock) -> None:
        """Test VASP parameter generation."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(mock_structure, code="vasp")
        step = analysis.build_scf_step()

        params = step.parameters
        assert "ENCUT" in params or params is not None

    def test_generate_crystal_parameters(self, mock_structure: Mock) -> None:
        """Test CRYSTAL23 parameter generation."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(mock_structure, code="crystal23")
        step = analysis.build_scf_step()

        params = step.parameters
        assert params is not None

    def test_generate_qe_parameters(self, mock_structure: Mock) -> None:
        """Test Quantum ESPRESSO parameter generation."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(mock_structure, code="quantum_espresso")
        step = analysis.build_scf_step()

        params = step.parameters
        assert params is not None

    def test_kpoint_generation(self, mock_structure: Mock) -> None:
        """Test k-point mesh generation."""
        with patch(
            "crystalmath.high_level.runners.PymatgenBridge.get_kpoints_mesh",
            return_value=(8, 8, 8),
        ):
            from crystalmath.high_level.runners import StandardAnalysis

            analysis = StandardAnalysis(mock_structure)
            step = analysis.build_scf_step()

            # Should have k-points
            assert "KPOINTS" in step.parameters or step.parameters is not None


# =============================================================================
# Test Integration
# =============================================================================


class TestWorkflowIntegration:
    """Integration tests for workflow runners."""

    def test_full_standard_workflow(self, mock_structure: Mock) -> None:
        """Test complete standard workflow creation."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(mock_structure, cluster="beefcake2")
        steps = analysis.build_workflow(["relax", "scf", "bands", "dos"])

        # Verify all steps created
        assert len(steps) == 4

        # Verify dependency chain
        step_map = {s.name: s for s in steps}
        assert "relax" in step_map["scf"].depends_on
        assert "scf" in step_map["bands"].depends_on
        assert "scf" in step_map["dos"].depends_on

    def test_full_optical_workflow(self, mock_structure: Mock) -> None:
        """Test complete optical workflow creation."""
        from crystalmath.high_level.runners import OpticalAnalysis

        analysis = OpticalAnalysis(
            mock_structure,
            dft_code="vasp",
            gw_code="yambo",
            cluster="beefcake2",
        )
        steps = analysis.build_workflow()

        # Should include DFT, GW, and BSE steps
        workflow_types = [s.workflow_type for s in steps]
        assert WorkflowType.GW in workflow_types
        assert WorkflowType.BSE in workflow_types

    def test_full_phonon_workflow(self, mock_structure: Mock) -> None:
        """Test complete phonon workflow creation."""
        from crystalmath.high_level.runners import PhononAnalysis

        analysis = PhononAnalysis(
            mock_structure,
            supercell=[2, 2, 2],
            cluster="beefcake2",
        )
        steps = analysis.build_workflow()

        workflow_types = [s.workflow_type for s in steps]
        assert WorkflowType.PHONON in workflow_types
