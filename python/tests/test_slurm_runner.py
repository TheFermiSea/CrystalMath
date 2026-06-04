"""
Tests for SLURMWorkflowRunner integration.

Tests cover:
- SLURMConfig creation from ClusterProfile
- SLURMWorkflowRunner initialization and availability
- Auto-selection of SLURM runner in high-level API
- WorkflowRunner protocol compliance
- Job tracking and status management
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

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
def slurm_runner(slurm_config, tmp_path):
    """Create a SLURMWorkflowRunner for testing.

    Points persistence at a tmp state file so tests never touch the real
    per-user state directory (~/.local/share/crystalmath).
    """
    from crystalmath.integrations.slurm_runner import SLURMWorkflowRunner

    return SLURMWorkflowRunner(
        config=slurm_config,
        default_code="vasp",
        state_file=tmp_path / "slurm_jobs.json",
    )


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

    def test_allow_insecure_refused_in_production(self, monkeypatch):
        """allow_insecure=True must be refused when CRYSTALMATH_ENV=production."""
        from crystalmath.integrations.slurm_runner import SLURMConfig

        monkeypatch.setenv("CRYSTALMATH_ENV", "production")
        with pytest.raises(ValueError, match="allow_insecure"):
            SLURMConfig(cluster_host="10.0.0.20", allow_insecure=True)

    def test_allow_insecure_permitted_outside_production(self, monkeypatch):
        """allow_insecure=True is allowed in non-production environments."""
        from crystalmath.integrations.slurm_runner import SLURMConfig

        monkeypatch.delenv("CRYSTALMATH_ENV", raising=False)
        config = SLURMConfig(cluster_host="10.0.0.20", allow_insecure=True)
        assert config.allow_insecure is True

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
        from crystalmath.high_level.clusters import get_cluster_profile
        from crystalmath.high_level.runners import StandardAnalysis

        profile = get_cluster_profile("beefcake2")
        analysis = StandardAnalysis(cluster=profile, protocol="fast")

        assert analysis._runner is not None
        assert analysis._runner.name == "slurm"

    def test_no_auto_select_for_local_cluster(self):
        """Test that SLURM runner is NOT selected for local clusters."""
        from crystalmath.high_level.clusters import get_cluster_profile
        from crystalmath.high_level.runners import StandardAnalysis

        profile = get_cluster_profile("local")
        analysis = StandardAnalysis(cluster=profile, protocol="fast")

        # Local cluster doesn't use SLURM, so runner should be None
        assert analysis._runner is None

    def test_explicit_runner_overrides_auto_select(self):
        """Test that explicitly provided runner takes precedence."""
        from crystalmath.high_level.clusters import get_cluster_profile
        from crystalmath.high_level.runners import StandardAnalysis

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
        from crystalmath.protocols import ResourceRequirements, WorkflowType

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


# =============================================================================
# YAMBO Result Parsing Tests
# =============================================================================


class TestYamboResultParsing:
    """Tests for YAMBO SHG output parsing."""

    def test_parse_yambo_shg_output_empty(self, slurm_runner):
        """Test parsing when no output files exist."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            results = slurm_runner._parse_yambo_shg_output(Path(tmpdir))
            assert results == {}

    def test_parse_yambo_shg_output_with_data(self, slurm_runner):
        """Test parsing YAMBO SHG output files."""
        import tempfile
        from pathlib import Path

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
        from crystalmath.high_level.clusters import get_cluster_profile
        from crystalmath.high_level.runners import StandardAnalysis
        from crystalmath.integrations.slurm_runner import SLURMWorkflowRunner

        profile = get_cluster_profile("beefcake2")
        analysis = StandardAnalysis(cluster=profile, protocol="fast")

        assert isinstance(analysis._runner, SLURMWorkflowRunner)
        assert analysis._runner.name == "slurm"

    def test_optical_analysis_with_slurm(self):
        """Test OpticalAnalysis uses SLURM runner when configured."""
        from crystalmath.high_level.clusters import get_cluster_profile
        from crystalmath.high_level.runners import OpticalAnalysis
        from crystalmath.integrations.slurm_runner import SLURMWorkflowRunner

        profile = get_cluster_profile("beefcake2")
        analysis = OpticalAnalysis(cluster=profile, protocol="fast")

        assert isinstance(analysis._runner, SLURMWorkflowRunner)

    def test_phonon_analysis_with_slurm(self):
        """Test PhononAnalysis uses SLURM runner when configured."""
        from crystalmath.high_level.clusters import get_cluster_profile
        from crystalmath.high_level.runners import PhononAnalysis
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


# =============================================================================
# Job-State Persistence Tests (crystalmath-z46)
# =============================================================================


def _make_runner(slurm_config, state_file):
    """Helper: build a runner pointed at a specific state file."""
    from crystalmath.integrations.slurm_runner import SLURMWorkflowRunner

    return SLURMWorkflowRunner(
        config=slurm_config,
        default_code="vasp",
        state_file=state_file,
    )


def _register_job(runner, workflow_id="wf-persist-1", slurm_job_id="99999", state="PENDING"):
    """Helper: register and persist a SLURMJobInfo directly, mirroring submit."""
    from crystalmath.integrations.slurm_runner import SLURMJobInfo

    job = SLURMJobInfo(
        workflow_id=workflow_id,
        slurm_job_id=slurm_job_id,
        state=state,
        remote_dir=f"/scratch/crystalmath/{workflow_id}",
        code="vasp",
        submitted_at=datetime(2026, 6, 3, 12, 0, 0),
    )
    runner._jobs[workflow_id] = job
    runner._save_state()
    return job


class TestSLURMJobInfoSerialization:
    """Tests for SLURMJobInfo (de)serialization."""

    def test_to_dict_serializes_datetimes_to_iso(self):
        from crystalmath.integrations.slurm_runner import SLURMJobInfo

        job = SLURMJobInfo(
            workflow_id="wf-1",
            slurm_job_id="123",
            submitted_at=datetime(2026, 6, 3, 9, 30, 0),
        )
        data = job.to_dict()

        assert data["workflow_id"] == "wf-1"
        assert data["slurm_job_id"] == "123"
        assert data["submitted_at"] == "2026-06-03T09:30:00"
        assert data["started_at"] is None

    def test_round_trip_preserves_fields(self):
        from crystalmath.integrations.slurm_runner import SLURMJobInfo

        job = SLURMJobInfo(
            workflow_id="wf-2",
            slurm_job_id="456",
            state="RUNNING",
            remote_dir="/scratch/x",
            code="crystal23",
            submitted_at=datetime(2026, 6, 3, 9, 30, 0),
            completed_at=datetime(2026, 6, 3, 10, 0, 0),
            outputs={"energy": -1.23},
            errors=["warn"],
        )
        restored = SLURMJobInfo.from_dict(job.to_dict())

        assert restored == job
        assert isinstance(restored.submitted_at, datetime)
        assert isinstance(restored.completed_at, datetime)

    def test_from_dict_ignores_unknown_keys_and_bad_datetime(self):
        from crystalmath.integrations.slurm_runner import SLURMJobInfo

        restored = SLURMJobInfo.from_dict(
            {
                "workflow_id": "wf-3",
                "slurm_job_id": "789",
                "submitted_at": "not-a-date",
                "bogus_future_field": 42,
            }
        )

        assert restored.workflow_id == "wf-3"
        assert restored.slurm_job_id == "789"
        # Unparseable datetime falls back to None rather than crashing.
        assert restored.submitted_at is None


class TestSLURMJobPersistence:
    """Tests that submitted jobs survive a runner (server) restart."""

    def test_save_then_reload_recovers_job(self, slurm_config, tmp_path):
        state_file = tmp_path / "slurm_jobs.json"

        runner = _make_runner(slurm_config, state_file)
        _register_job(runner, workflow_id="wf-reload")

        assert state_file.exists()

        # Simulate IPC-server restart: brand new runner, same state file.
        runner2 = _make_runner(slurm_config, state_file)

        assert "wf-reload" in runner2._jobs
        reloaded = runner2._jobs["wf-reload"]
        assert reloaded.slurm_job_id == "99999"
        assert reloaded.remote_dir == "/scratch/crystalmath/wf-reload"
        assert reloaded.submitted_at == datetime(2026, 6, 3, 12, 0, 0)

    def test_reloaded_job_status_not_failed(self, slurm_config, tmp_path):
        """After reload, get_status must no longer treat the job as unknown."""

        state_file = tmp_path / "slurm_jobs.json"
        runner = _make_runner(slurm_config, state_file)
        _register_job(runner, workflow_id="wf-status", state="PENDING")

        runner2 = _make_runner(slurm_config, state_file)

        # Sanity: an unknown id still maps to "failed" (baseline behavior).
        assert runner2.get_status("does-not-exist") == "failed"

        # The reloaded job is found; stub the remote squeue query so we don't
        # require a live cluster. PENDING -> "submitted".
        with patch.object(runner2, "_get_slurm_status", new=AsyncMock(return_value="PENDING")):
            status = runner2.get_status("wf-status")

        assert status != "failed"
        assert status == "submitted"

    def test_reloaded_job_can_be_cancelled(self, slurm_config, tmp_path):
        """cancel() must locate a job that only exists via persisted state."""

        state_file = tmp_path / "slurm_jobs.json"
        runner = _make_runner(slurm_config, state_file)
        _register_job(runner, workflow_id="wf-cancel", slurm_job_id="55555")

        runner2 = _make_runner(slurm_config, state_file)

        # Unknown id cannot be cancelled.
        assert runner2.cancel("missing") is False

        with patch.object(
            runner2, "_cancel_slurm_job", new=AsyncMock(return_value=None)
        ) as mock_cancel:
            result = runner2.cancel("wf-cancel")

        assert result is True
        mock_cancel.assert_awaited_once_with("55555")
        # Cancellation transition is persisted.
        assert runner2._jobs["wf-cancel"].state == "CANCELLED"
        runner3 = _make_runner(slurm_config, state_file)
        assert runner3._jobs["wf-cancel"].state == "CANCELLED"

    def test_missing_state_file_starts_empty(self, slurm_config, tmp_path):
        """A non-existent state file must not crash construction."""
        runner = _make_runner(slurm_config, tmp_path / "nope" / "missing.json")
        assert runner._jobs == {}

    def test_corrupt_state_file_starts_empty(self, slurm_config, tmp_path):
        """A corrupt state file must be tolerated (log + start empty)."""
        state_file = tmp_path / "corrupt.json"
        state_file.write_text("{ this is not valid json ]]]")

        runner = _make_runner(slurm_config, state_file)
        assert runner._jobs == {}

    def test_state_file_malformed_records_skipped(self, slurm_config, tmp_path):
        """Malformed individual records are skipped; valid ones still load."""
        import json

        state_file = tmp_path / "partial.json"
        state_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "jobs": [
                        "not-a-dict",
                        {"slurm_job_id": "1"},  # missing workflow_id -> skipped
                        {"workflow_id": "good", "slurm_job_id": "2"},
                    ],
                }
            )
        )

        runner = _make_runner(slurm_config, state_file)
        assert list(runner._jobs.keys()) == ["good"]

    def test_default_state_file_is_namespaced_by_host(self, slurm_config, monkeypatch, tmp_path):
        """Default path lands under the per-user data dir, namespaced by host."""
        from crystalmath.integrations.slurm_runner import SLURMWorkflowRunner

        monkeypatch.delenv("CRYSTALMATH_SLURM_STATE_FILE", raising=False)
        monkeypatch.delenv("CRYSTALMATH_STATE_DIR", raising=False)
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

        runner = SLURMWorkflowRunner(config=slurm_config, default_code="vasp")
        path = runner._state_file

        assert path.parent == tmp_path / "xdg" / "crystalmath" / "slurm_jobs"
        assert path.name == "10.0.0.20.json"

    def test_state_file_env_override(self, slurm_config, monkeypatch, tmp_path):
        """CRYSTALMATH_SLURM_STATE_FILE overrides the default location."""
        from crystalmath.integrations.slurm_runner import SLURMWorkflowRunner

        override = tmp_path / "operator" / "jobs.json"
        monkeypatch.setenv("CRYSTALMATH_SLURM_STATE_FILE", str(override))

        runner = SLURMWorkflowRunner(config=slurm_config, default_code="vasp")
        assert runner._state_file == override


# =============================================================================
# VASP POTCAR Staging Tests (crystalmath-d4l)
# =============================================================================


class TestVaspPotcarStaging:
    """Tests for real POTCAR staging in the VASP submission path."""

    def test_vasp_slurm_script_has_no_hardcoded_potcar_generator(self, slurm_runner):
        """The SLURM script must not call the old hardcoded generate_potcar.sh."""
        from crystalmath.protocols import WorkflowType

        script = slurm_runner._generate_slurm_script(
            workflow_id="test-123",
            workflow_type=WorkflowType.RELAX,
            code="vasp",
        )

        assert "generate_potcar.sh" not in script
        assert "POTCAR_NEEDED" not in script
        # It should instead verify the locally staged POTCAR exists.
        assert "POTCAR" in script


# =============================================================================
# SSH Host-Key Verification Tests (Finding #1 — fail closed, never silently off)
# =============================================================================


class TestKnownHostsFailClosed:
    """asyncssh known_hosts semantics: None=OFF (insecure), ()=fail closed.

    The runner's direct path and the vendored ConnectionManager must NEVER hand
    asyncssh ``known_hosts=None`` unless verification was *explicitly* opted out.
    """

    def test_runner_get_known_hosts_fails_closed_when_no_known_hosts(
        self, slurm_config, tmp_path, monkeypatch
    ):
        """No ~/.ssh/known_hosts + secure config -> () (fail closed), never None."""
        from crystalmath.integrations.slurm_runner import SLURMWorkflowRunner

        # Point HOME at an empty dir so ~/.ssh/known_hosts does not exist.
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        runner = SLURMWorkflowRunner(
            config=slurm_config,
            default_code="vasp",
            state_file=tmp_path / "jobs.json",
        )
        assert runner._config.allow_insecure is False
        assert runner._get_known_hosts() == ()

    def test_runner_get_known_hosts_none_only_with_explicit_insecure(self, tmp_path, monkeypatch):
        """known_hosts=None (verification OFF) only on explicit allow_insecure."""
        from crystalmath.integrations.slurm_runner import SLURMConfig, SLURMWorkflowRunner

        monkeypatch.delenv("CRYSTALMATH_ENV", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        config = SLURMConfig(cluster_host="10.0.0.20", allow_insecure=True)
        runner = SLURMWorkflowRunner(
            config=config,
            default_code="vasp",
            state_file=tmp_path / "jobs.json",
        )
        assert runner._get_known_hosts() is None

    def test_vendored_manager_fails_closed_when_no_known_hosts(self, tmp_path, monkeypatch):
        """Vendored ConnectionManager must return () (not None) when strict checking
        is on and ~/.ssh/known_hosts is absent — the dh7 hardening must not be
        bypassable through the vendored path the runner prefers."""
        from crystalmath._vendor.core.connection_manager import (
            ConnectionConfig,
            ConnectionManager,
        )

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        config = ConnectionConfig(host="10.0.0.20", strict_host_key_checking=True)
        # Absent known_hosts must FAIL CLOSED, not disable verification.
        assert ConnectionManager._get_known_hosts_file(config) == ()

    def test_vendored_manager_none_only_when_strict_disabled(self, tmp_path, monkeypatch):
        """known_hosts=None (verification disabled) only when strict checking is
        explicitly turned off — the deliberate insecure opt-in."""
        from crystalmath._vendor.core.connection_manager import (
            ConnectionConfig,
            ConnectionManager,
        )

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        config = ConnectionConfig(host="10.0.0.20", strict_host_key_checking=False)
        assert ConnectionManager._get_known_hosts_file(config) is None

    def test_vendored_manager_uses_known_hosts_path_when_present(self, tmp_path, monkeypatch):
        """When ~/.ssh/known_hosts exists, verify against it (return the path)."""
        from crystalmath._vendor.core.connection_manager import (
            ConnectionConfig,
            ConnectionManager,
        )

        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        (ssh_dir / "known_hosts").write_text("example.com ssh-ed25519 AAAA\n")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        config = ConnectionConfig(host="10.0.0.20", strict_host_key_checking=True)
        result = ConnectionManager._get_known_hosts_file(config)
        assert result == str(ssh_dir / "known_hosts")


# =============================================================================
# CRYSTAL23 .d12 Generation Tests (crystalmath-drm)
# =============================================================================
