"""Unit tests for AiiDA job submitter.

These tests verify the AiiDASubmitter class with mocked AiiDA dependencies.
The tests are designed to work without AiiDA installed.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_aiida_modules():
    """Mock AiiDA modules for all tests in this module."""
    mock_load_profile = MagicMock()
    mock_orm = MagicMock()
    mock_engine = MagicMock()

    # Mock ORM objects
    mock_orm.load_code = MagicMock()
    mock_orm.load_node = MagicMock()
    mock_orm.SinglefileData = MagicMock()
    mock_orm.Dict = MagicMock()
    mock_orm.StructureData = MagicMock()
    mock_orm.Str = MagicMock()
    mock_orm.Code = MagicMock()
    mock_orm.QueryBuilder = MagicMock()
    mock_orm.Computer = MagicMock()

    # Mock engine
    mock_engine.submit = MagicMock()
    mock_engine.run = MagicMock()
    mock_engine.process = MagicMock()

    with patch.dict(
        sys.modules,
        {
            "aiida": MagicMock(load_profile=mock_load_profile),
            "aiida.orm": mock_orm,
            "aiida.engine": mock_engine,
        },
    ):
        yield {
            "load_profile": mock_load_profile,
            "orm": mock_orm,
            "engine": mock_engine,
        }


class TestAiiDASubmitterInit:
    """Test AiiDASubmitter initialization."""

    def test_init_sets_profile_name(self, mock_aiida_modules):
        """Test that init sets profile name."""
        from src.aiida.submitter import AiiDASubmitter

        submitter = AiiDASubmitter(profile_name="custom-profile")

        assert submitter.profile_name == "custom-profile"
        assert submitter._profile_loaded is False

    def test_init_defaults_profile_name(self, mock_aiida_modules):
        """Test that init uses default profile name."""
        from src.aiida.submitter import AiiDASubmitter

        submitter = AiiDASubmitter()

        assert submitter.profile_name == "crystal-tui"


class TestAiiDASubmitterProfile:
    """Test profile loading."""

    def test_ensure_profile_loads_once(self, mock_aiida_modules):
        """Test that profile is loaded only once."""
        from src.aiida.submitter import AiiDASubmitter

        submitter = AiiDASubmitter(profile_name="test-profile")

        submitter._ensure_profile()
        submitter._ensure_profile()

        assert submitter._profile_loaded is True


class TestAiiDASubmitterBuildOptions:
    """Test _build_options method."""

    def test_build_options_defaults(self, mock_aiida_modules):
        """Test default calculation options."""
        from src.aiida.submitter import AiiDASubmitter

        submitter = AiiDASubmitter()
        options = submitter._build_options(None)

        assert options["resources"]["num_machines"] == 1
        assert options["max_wallclock_seconds"] == 3600
        assert options["withmpi"] is False

    def test_build_options_custom_machines(self, mock_aiida_modules):
        """Test custom num_machines option."""
        from src.aiida.submitter import AiiDASubmitter

        submitter = AiiDASubmitter()
        resources = {"num_machines": 4}

        options = submitter._build_options(resources)

        assert options["resources"]["num_machines"] == 4

    def test_build_options_custom_mpiprocs(self, mock_aiida_modules):
        """Test custom num_mpiprocs option."""
        from src.aiida.submitter import AiiDASubmitter

        submitter = AiiDASubmitter()
        resources = {"num_mpiprocs": 16}

        options = submitter._build_options(resources)

        assert options["resources"]["num_mpiprocs_per_machine"] == 16

    def test_build_options_custom_walltime(self, mock_aiida_modules):
        """Test custom walltime option."""
        from src.aiida.submitter import AiiDASubmitter

        submitter = AiiDASubmitter()
        resources = {"walltime": 7200}

        options = submitter._build_options(resources)

        assert options["max_wallclock_seconds"] == 7200

    def test_build_options_withmpi(self, mock_aiida_modules):
        """Test withmpi option."""
        from src.aiida.submitter import AiiDASubmitter

        submitter = AiiDASubmitter()
        resources = {"withmpi": True}

        options = submitter._build_options(resources)

        assert options["withmpi"] is True


class TestAiiDASubmitterListComputers:
    """Test list_computers method."""

    def test_list_computers(self, mock_aiida_modules):
        """Test listing available computers."""
        from src.aiida.submitter import AiiDASubmitter

        mock_orm = mock_aiida_modules["orm"]

        mock_computer = MagicMock()
        mock_computer.label = "localhost"
        mock_computer.hostname = "127.0.0.1"
        mock_computer.scheduler_type = "core.direct"
        mock_computer.is_configured = True
        mock_orm.Computer.collection.all.return_value = [mock_computer]

        submitter = AiiDASubmitter()
        computers = submitter.list_computers()

        assert len(computers) == 1
        assert computers[0]["label"] == "localhost"
        assert computers[0]["is_configured"] is True


class TestAiiDASubmitterCancelJob:
    """Test cancel_job method."""

    @pytest.mark.asyncio
    async def test_cancel_job_not_running(self, mock_aiida_modules):
        """Test cancelling a job that's not running."""
        from src.aiida.submitter import AiiDASubmitter

        mock_orm = mock_aiida_modules["orm"]

        mock_node = MagicMock()
        mock_node.process_state.value = "finished"
        mock_orm.load_node.return_value = mock_node

        submitter = AiiDASubmitter()
        success = await submitter.cancel_job(123)

        assert success is False

    @pytest.mark.asyncio
    async def test_cancel_job_not_found(self, mock_aiida_modules):
        """Test cancelling non-existent job."""
        from src.aiida.submitter import AiiDASubmitter

        mock_orm = mock_aiida_modules["orm"]
        mock_orm.load_node.side_effect = Exception("Not found")

        submitter = AiiDASubmitter()
        success = await submitter.cancel_job(999)

        assert success is False
