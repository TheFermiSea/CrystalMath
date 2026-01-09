"""
Tests for SLURMWorkflowRunner integration.

Tests cover:
- SLURMConfig creation from ClusterProfile
- SLURMWorkflowRunner initialization and availability
- Auto-selection of SLURM runner in high-level API
- WorkflowRunner protocol compliance
- Job tracking and status management
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_cluster_profile():
    """Create a mock ClusterProfile for testing."""
    profile = Mock()
    profile.name = "beefcake2"
    profile.ssh_host = "10.0.0.20"
    profile.ssh_user = "root"
    profile.default_partition = "compute"
    profile.scheduler = "slurm"
    profile.available_codes = ["vasp", "quantum_espresso", "crystal23"]
    return profile


@pytest.fixture
def slurm_config():
    """Create a SLURMConfig for testing."""
    from crystalmath.integrations.slurm_runner import SLURMConfig

    return SLURMConfig(
        cluster_host="10.0.0.20",
        cluster_port=22,
        username="root",
        remote_scratch="/scratch/crystalmath",
        default_partition="compute",
    )


@pytest.fixture
def slurm_runner(slurm_config):
    """Create a SLURMWorkflowRunner for testing."""
    from crystalmath.integrations.slurm_runner import SLURMWorkflowRunner

    return SLURMWorkflowRunner(config=slurm_config, default_code="vasp")


# =============================================================================
# SLURMConfig Tests
# =============================================================================


class TestSLURMConfig:
    """Tests for SLURMConfig dataclass."""

    def test_config_creation(self):
        """Test basic config creation."""
        from crystalmath.integrations.slurm_runner import SLURMConfig

        config = SLURMConfig(
            cluster_host="10.0.0.20",
            cluster_port=22,
            username="root",
        )

        assert config.cluster_host == "10.0.0.20"
        assert config.cluster_port == 22
        assert config.username == "root"
        assert config.poll_interval_seconds == 30
        assert config.max_concurrent_jobs == 10

    def test_config_from_cluster_profile(self, mock_cluster_profile):
        """Test config creation from ClusterProfile."""
        from crystalmath.integrations.slurm_runner import SLURMConfig

        config = SLURMConfig.from_cluster_profile(mock_cluster_profile)

        assert config.cluster_host == "10.0.0.20"
        assert config.username == "root"
        assert config.default_partition == "compute"

    def test_config_from_profile_missing_ssh_host(self):
        """Test config creation fails when ssh_host is missing."""
        from crystalmath.integrations.slurm_runner import SLURMConfig

        profile = Mock()
        profile.name = "test"
        profile.ssh_host = None

        with pytest.raises(ValueError, match="no ssh_host configured"):
            SLURMConfig.from_cluster_profile(profile)


# =============================================================================
# SLURMWorkflowRunner Tests
# =============================================================================


class TestSLURMWorkflowRunner:
    """Tests for SLURMWorkflowRunner class."""

    def test_runner_initialization(self, slurm_config):
        """Test runner initialization."""
        from crystalmath.integrations.slurm_runner import SLURMWorkflowRunner

        runner = SLURMWorkflowRunner(config=slurm_config, default_code="vasp")

        assert runner.name == "slurm"
        assert runner._default_code == "vasp"
        assert runner._jobs == {}

    def test_runner_from_cluster_profile(self, mock_cluster_profile):
        """Test runner creation from ClusterProfile."""
        from crystalmath.integrations.slurm_runner import SLURMWorkflowRunner

        runner = SLURMWorkflowRunner.from_cluster_profile(
            profile=mock_cluster_profile,
            default_code="vasp",
        )

        assert runner.name == "slurm"
        assert runner._config.cluster_host == "10.0.0.20"

    def test_runner_is_available(self, slurm_runner):
        """Test availability check."""
        # Should be True because TUI path exists or asyncssh can be checked
        assert isinstance(slurm_runner.is_available, bool)

    def test_runner_name_property(self, slurm_runner):
        """Test name property."""
        assert slurm_runner.name == "slurm"

    def test_job_id_parsing(self, slurm_runner):
        """Test SLURM job ID parsing from sbatch output."""
        output = "Submitted batch job 12345"
        job_id = slurm_runner._parse_job_id(output)
        assert job_id == "12345"

    def test_job_id_parsing_fails(self, slurm_runner):
        """Test job ID parsing failure."""
        from crystalmath.integrations.slurm_runner import SLURMSubmissionError

        with pytest.raises(SLURMSubmissionError, match="Could not parse"):
            slurm_runner._parse_job_id("Some invalid output")


# =============================================================================
# Auto-Selection Tests
# =============================================================================


class TestSLURMAutoSelection:
    """Tests for automatic SLURM runner selection in high-level API."""

    def test_auto_select_with_slurm_cluster(self):
        """Test that SLURM runner is auto-selected for SLURM clusters."""
        from crystalmath.high_level.runners import StandardAnalysis
        from crystalmath.high_level.clusters import get_cluster_profile

        profile = get_cluster_profile("beefcake2")
        analysis = StandardAnalysis(cluster=profile, protocol="fast")

        assert analysis._runner is not None
        assert analysis._runner.name == "slurm"

    def test_no_auto_select_for_local_cluster(self):
        """Test that SLURM runner is NOT selected for local clusters."""
        from crystalmath.high_level.runners import StandardAnalysis
        from crystalmath.high_level.clusters import get_cluster_profile

        profile = get_cluster_profile("local")
        analysis = StandardAnalysis(cluster=profile, protocol="fast")

        # Local cluster doesn't use SLURM, so runner should be None
        assert analysis._runner is None

    def test_explicit_runner_overrides_auto_select(self):
        """Test that explicitly provided runner takes precedence."""
        from crystalmath.high_level.runners import StandardAnalysis
        from crystalmath.high_level.clusters import get_cluster_profile

        profile = get_cluster_profile("beefcake2")

        # Create a mock runner
        mock_runner = Mock()
        mock_runner.name = "mock"

        analysis = StandardAnalysis(
            cluster=profile,
            runner=mock_runner,
            protocol="fast",
        )

        assert analysis._runner is mock_runner
        assert analysis._runner.name == "mock"

    def test_no_cluster_no_runner(self):
        """Test that no runner is created when no cluster specified."""
        from crystalmath.high_level.runners import StandardAnalysis

        analysis = StandardAnalysis(cluster=None, protocol="fast")

        assert analysis._runner is None


# =============================================================================
# WorkflowRunner Protocol Tests
# =============================================================================


class TestWorkflowRunnerProtocol:
    """Tests for WorkflowRunner protocol compliance."""

    def test_runner_has_submit_method(self, slurm_runner):
        """Test that runner has submit method."""
        assert hasattr(slurm_runner, "submit")
        assert callable(slurm_runner.submit)

    def test_runner_has_get_status_method(self, slurm_runner):
        """Test that runner has get_status method."""
        assert hasattr(slurm_runner, "get_status")
        assert callable(slurm_runner.get_status)

    def test_runner_has_get_result_method(self, slurm_runner):
        """Test that runner has get_result method."""
        assert hasattr(slurm_runner, "get_result")
        assert callable(slurm_runner.get_result)

    def test_runner_has_cancel_method(self, slurm_runner):
        """Test that runner has cancel method."""
        assert hasattr(slurm_runner, "cancel")
        assert callable(slurm_runner.cancel)

    def test_runner_has_list_workflows_method(self, slurm_runner):
        """Test that runner has list_workflows method."""
        assert hasattr(slurm_runner, "list_workflows")
        assert callable(slurm_runner.list_workflows)


# =============================================================================
# Job Tracking Tests
# =============================================================================


class TestJobTracking:
    """Tests for job tracking functionality."""

    def test_list_workflows_empty(self, slurm_runner):
        """Test list_workflows returns empty list initially."""
        workflows = slurm_runner.list_workflows()
        assert workflows == []

    def test_get_status_unknown_workflow(self, slurm_runner):
        """Test get_status for unknown workflow returns failed."""
        status = slurm_runner.get_status("nonexistent-id")
        assert status == "failed"

    def test_cancel_unknown_workflow(self, slurm_runner):
        """Test cancel for unknown workflow returns False."""
        result = slurm_runner.cancel("nonexistent-id")
        assert result is False


# =============================================================================
# Input Generation Tests
# =============================================================================


class TestInputGeneration:
    """Tests for DFT input file generation."""

    def test_slurm_script_generation_vasp(self, slurm_runner):
        """Test SLURM script generation for VASP."""
        from crystalmath.protocols import WorkflowType

        script = slurm_runner._generate_slurm_script(
            workflow_id="test-123",
            workflow_type=WorkflowType.RELAX,
            code="vasp",
        )

        assert "#!/bin/bash" in script
        assert "#SBATCH" in script
        assert "vasp" in script.lower()
        assert "srun" in script

    def test_slurm_script_generation_qe(self, slurm_runner):
        """Test SLURM script generation for Quantum ESPRESSO."""
        from crystalmath.protocols import WorkflowType

        script = slurm_runner._generate_slurm_script(
            workflow_id="test-123",
            workflow_type=WorkflowType.SCF,
            code="quantum_espresso",
        )

        assert "#!/bin/bash" in script
        assert "#SBATCH" in script
        assert "pw.x" in script

    def test_slurm_script_generation_crystal(self, slurm_runner):
        """Test SLURM script generation for CRYSTAL23."""
        from crystalmath.protocols import WorkflowType

        script = slurm_runner._generate_slurm_script(
            workflow_id="test-123",
            workflow_type=WorkflowType.SCF,
            code="crystal23",
        )

        assert "#!/bin/bash" in script
        assert "#SBATCH" in script
        assert "crystal" in script.lower()

    def test_slurm_script_with_resources(self, slurm_runner):
        """Test SLURM script with custom resources."""
        from crystalmath.protocols import WorkflowType, ResourceRequirements

        resources = ResourceRequirements(
            num_nodes=2,
            num_mpi_ranks=80,
            walltime_hours=48,
            memory_gb=376,
            gpus=2,
        )

        script = slurm_runner._generate_slurm_script(
            workflow_id="test-123",
            workflow_type=WorkflowType.RELAX,
            code="vasp",
            resources=resources,
        )

        assert "--nodes=2" in script
        assert "--ntasks=80" in script
        assert "--gres=gpu:2" in script

    def test_slurm_script_generation_yambo(self, slurm_runner):
        """Test SLURM script generation for YAMBO."""
        from crystalmath.protocols import WorkflowType

        script = slurm_runner._generate_slurm_script(
            workflow_id="test-123",
            workflow_type=WorkflowType.BSE,
            code="yambo",
        )

        assert "#!/bin/bash" in script
        assert "#SBATCH" in script
        assert "yambo" in script
        assert "nvhpc" in script
        assert "UCX_TLS" in script

    def test_slurm_script_generation_yambo_nl_shg(self, slurm_runner):
        """Test SLURM script generation for yambo_nl SHG calculation."""
        from crystalmath.protocols import WorkflowType

        script = slurm_runner._generate_slurm_script(
            workflow_id="test-123",
            workflow_type=WorkflowType.NONLINEAR_OPTICS,
            code="yambo_nl",
        )

        assert "#!/bin/bash" in script
        assert "#SBATCH" in script
        assert "yambo_nl" in script
        assert "SHG" in script
        assert "nvhpc" in script
        assert "UCX_TLS" in script

    def test_yambo_input_generation(self, slurm_runner):
        """Test YAMBO nonlinear input file generation."""
        from crystalmath.protocols import WorkflowType
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            input_path = slurm_runner._generate_yambo_input(
                work_dir=work_dir,
                workflow_type=WorkflowType.NONLINEAR_OPTICS,
                parameters={
                    "energy_range": (0.5, 3.5),
                    "energy_steps": 500,
                    "damping": 0.1,
                },
            )

            assert input_path.exists()
            content = input_path.read_text()
            assert "nonlinear" in content
            assert "NL_Response" in content
            assert "SHG" in content
            assert "NL_EnRange" in content
            assert "0.5 3.5 eV" in content


# =============================================================================
# YAMBO Result Parsing Tests
# =============================================================================


class TestYamboResultParsing:
    """Tests for YAMBO SHG output parsing."""

    def test_parse_yambo_shg_output_empty(self, slurm_runner):
        """Test parsing when no output files exist."""
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            results = slurm_runner._parse_yambo_shg_output(Path(tmpdir))
            assert results == {}

    def test_parse_yambo_shg_output_with_data(self, slurm_runner):
        """Test parsing YAMBO SHG output files."""
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            # Create mock SHG output file (x-component)
            shg_data = """# E(eV) Re(chi) Im(chi) |chi|
1.0  10.0  5.0  11.18
1.5  50.0  25.0  55.9
2.0  20.0  10.0  22.36
"""
            (output_dir / "o-SHG.YPP-SHG_x").write_text(shg_data)

            results = slurm_runner._parse_yambo_shg_output(output_dir)

            assert "chi2_x_energy" in results
            assert "chi2_x_real" in results
            assert "chi2_x_imag" in results
            assert "chi2_x_peak_energy" in results
            assert "chi2_x_peak_value" in results

            # Peak should be at 1.5 eV (highest |chi|)
            assert results["chi2_x_peak_energy"] == 1.5


# =============================================================================
# Integration Tests
# =============================================================================


class TestSLURMIntegration:
    """Integration tests for SLURM runner with high-level API."""

    def test_standard_analysis_with_slurm(self):
        """Test StandardAnalysis uses SLURM runner when configured."""
        from crystalmath.high_level.runners import StandardAnalysis
        from crystalmath.high_level.clusters import get_cluster_profile
        from crystalmath.integrations.slurm_runner import SLURMWorkflowRunner

        profile = get_cluster_profile("beefcake2")
        analysis = StandardAnalysis(cluster=profile, protocol="fast")

        assert isinstance(analysis._runner, SLURMWorkflowRunner)
        assert analysis._runner.name == "slurm"

    def test_optical_analysis_with_slurm(self):
        """Test OpticalAnalysis uses SLURM runner when configured."""
        from crystalmath.high_level.runners import OpticalAnalysis
        from crystalmath.high_level.clusters import get_cluster_profile
        from crystalmath.integrations.slurm_runner import SLURMWorkflowRunner

        profile = get_cluster_profile("beefcake2")
        analysis = OpticalAnalysis(cluster=profile, protocol="fast")

        assert isinstance(analysis._runner, SLURMWorkflowRunner)

    def test_phonon_analysis_with_slurm(self):
        """Test PhononAnalysis uses SLURM runner when configured."""
        from crystalmath.high_level.runners import PhononAnalysis
        from crystalmath.high_level.clusters import get_cluster_profile
        from crystalmath.integrations.slurm_runner import SLURMWorkflowRunner

        profile = get_cluster_profile("beefcake2")
        analysis = PhononAnalysis(cluster=profile, protocol="fast")

        assert isinstance(analysis._runner, SLURMWorkflowRunner)


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_create_slurm_runner_beefcake2(self):
        """Test create_slurm_runner for beefcake2 cluster."""
        from crystalmath.integrations.slurm_runner import create_slurm_runner

        runner = create_slurm_runner(cluster_name="beefcake2", default_code="vasp")

        assert runner.name == "slurm"
        assert runner._config.cluster_host == "10.0.0.20"

    def test_create_slurm_runner_unknown_cluster(self):
        """Test create_slurm_runner raises for unknown cluster."""
        from crystalmath.integrations.slurm_runner import create_slurm_runner

        with pytest.raises(KeyError):
            create_slurm_runner(cluster_name="nonexistent", default_code="vasp")
