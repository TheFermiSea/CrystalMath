"""Unit tests for AiiDA QueryAdapter.

These tests verify the AiiDAQueryAdapter class with mocked AiiDA dependencies.
The tests are designed to work without AiiDA installed.
"""

import json
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_aiida_modules():
    """Mock AiiDA modules for all tests in this module."""
    mock_load_profile = MagicMock()
    mock_orm = MagicMock()
    mock_qb = MagicMock()

    # Mock QueryBuilder class
    mock_orm.QueryBuilder = MagicMock(return_value=mock_qb)
    mock_orm.CalcJobNode = type("CalcJobNode", (), {})
    mock_orm.WorkChainNode = type("WorkChainNode", (), {})
    mock_orm.Computer = MagicMock()
    mock_orm.Dict = MagicMock()
    mock_orm.SinglefileData = MagicMock()
    mock_orm.load_node = MagicMock()

    with patch.dict(
        sys.modules,
        {
            "aiida": MagicMock(load_profile=mock_load_profile),
            "aiida.orm": mock_orm,
        },
    ):
        # Import after mocking
        yield {
            "load_profile": mock_load_profile,
            "orm": mock_orm,
            "qb": mock_qb,
        }


class TestAiiDAQueryAdapterInit:
    """Test AiiDAQueryAdapter initialization."""

    def test_init_sets_profile_name(self, mock_aiida_modules):
        """Test that init sets profile name."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        adapter = AiiDAQueryAdapter(profile_name="custom-profile")

        assert adapter.profile_name == "custom-profile"
        assert adapter._profile_loaded is False

    def test_init_defaults_profile_name(self, mock_aiida_modules):
        """Test that init uses default profile name."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        adapter = AiiDAQueryAdapter()

        assert adapter.profile_name == "crystal-tui"


class TestAiiDAQueryAdapterStatusMappings:
    """Test status mapping constants."""

    def test_status_to_aiida_mapping(self, mock_aiida_modules):
        """Test TUI -> AiiDA status mapping."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        assert AiiDAQueryAdapter.STATUS_TO_AIIDA["pending"] == ["created", "waiting"]
        assert AiiDAQueryAdapter.STATUS_TO_AIIDA["running"] == ["running"]
        assert AiiDAQueryAdapter.STATUS_TO_AIIDA["completed"] == ["finished"]
        assert AiiDAQueryAdapter.STATUS_TO_AIIDA["failed"] == ["excepted", "killed"]

    def test_aiida_to_status_mapping(self, mock_aiida_modules):
        """Test AiiDA -> TUI status mapping."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        assert AiiDAQueryAdapter.AIIDA_TO_STATUS["created"] == "pending"
        assert AiiDAQueryAdapter.AIIDA_TO_STATUS["running"] == "running"
        assert AiiDAQueryAdapter.AIIDA_TO_STATUS["finished"] == "completed"
        assert AiiDAQueryAdapter.AIIDA_TO_STATUS["excepted"] == "failed"
        assert AiiDAQueryAdapter.AIIDA_TO_STATUS["killed"] == "cancelled"


class TestAiiDAQueryAdapterProfile:
    """Test profile loading."""

    def test_ensure_profile_loads_once(self, mock_aiida_modules):
        """Test that profile is loaded only once."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        adapter = AiiDAQueryAdapter(profile_name="test-profile")

        adapter._ensure_profile()
        adapter._ensure_profile()

        # Should only be called once (profile is cached after first load)
        assert adapter._profile_loaded is True


class TestAiiDAQueryAdapterListJobs:
    """Test list_jobs method."""

    def test_list_jobs_returns_jobs(self, mock_aiida_modules):
        """Test listing jobs."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        mock_qb = mock_aiida_modules["qb"]
        mock_qb.all.return_value = [
            (1, "Job 1", datetime(2024, 1, 1), datetime(2024, 1, 2), "finished"),
            (2, "Job 2", datetime(2024, 1, 3), datetime(2024, 1, 4), "running"),
        ]

        adapter = AiiDAQueryAdapter()
        jobs = adapter.list_jobs()

        assert len(jobs) == 2
        assert jobs[0]["id"] == 1
        assert jobs[0]["name"] == "Job 1"
        assert jobs[0]["runner_type"] == "aiida"

    def test_list_jobs_with_status_filter(self, mock_aiida_modules):
        """Test listing jobs with status filter."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        mock_qb = mock_aiida_modules["qb"]
        mock_qb.all.return_value = [
            (1, "Running Job", datetime.now(), datetime.now(), "running"),
        ]

        adapter = AiiDAQueryAdapter()
        jobs = adapter.list_jobs(status="running")

        mock_qb.add_filter.assert_called()
        assert len(jobs) == 1

    def test_list_jobs_with_pagination(self, mock_aiida_modules):
        """Test job listing with limit and offset."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        mock_qb = mock_aiida_modules["qb"]
        mock_qb.all.return_value = []

        adapter = AiiDAQueryAdapter()
        adapter.list_jobs(limit=10, offset=20)

        mock_qb.limit.assert_called_once_with(10)
        mock_qb.offset.assert_called_once_with(20)


class TestAiiDAQueryAdapterGetJobCount:
    """Test get_job_count method."""

    def test_get_job_count(self, mock_aiida_modules):
        """Test counting jobs."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        mock_qb = mock_aiida_modules["qb"]
        mock_qb.count.return_value = 42

        adapter = AiiDAQueryAdapter()
        count = adapter.get_job_count()

        assert count == 42

    def test_get_job_count_with_status(self, mock_aiida_modules):
        """Test counting jobs with status filter."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        mock_qb = mock_aiida_modules["qb"]
        mock_qb.count.return_value = 5

        adapter = AiiDAQueryAdapter()
        count = adapter.get_job_count(status="running")

        assert count == 5
        mock_qb.add_filter.assert_called_once()


class TestAiiDAQueryAdapterListClusters:
    """Test list_clusters method."""

    def test_list_clusters(self, mock_aiida_modules):
        """Test listing AiiDA computers as clusters."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        mock_orm = mock_aiida_modules["orm"]

        mock_comp = MagicMock()
        mock_comp.pk = 1
        mock_comp.label = "localhost"
        mock_comp.hostname = "127.0.0.1"
        mock_comp.scheduler_type = "core.direct"
        mock_comp.get_property.return_value = 4

        mock_orm.Computer.collection.all.return_value = [mock_comp]

        adapter = AiiDAQueryAdapter()
        clusters = adapter.list_clusters()

        assert len(clusters) == 1
        assert clusters[0]["name"] == "localhost"
        assert clusters[0]["hostname"] == "127.0.0.1"
        assert clusters[0]["queue_type"] == "direct"


class TestAiiDAQueryAdapterMapStatus:
    """Test _map_status method."""

    def test_map_status_running(self, mock_aiida_modules):
        """Test mapping running status."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        adapter = AiiDAQueryAdapter()
        status = adapter._map_status("running")

        assert status == "running"

    def test_map_status_created(self, mock_aiida_modules):
        """Test mapping created status."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        adapter = AiiDAQueryAdapter()
        status = adapter._map_status("created")

        assert status == "pending"

    def test_map_status_unknown(self, mock_aiida_modules):
        """Test mapping unknown status."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        adapter = AiiDAQueryAdapter()
        status = adapter._map_status("weird_state")

        assert status == "unknown"

    def test_map_status_finished_with_failed_exit(self, mock_aiida_modules):
        """Test mapping finished status with non-zero exit."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        mock_orm = mock_aiida_modules["orm"]
        mock_node = MagicMock()
        mock_node.exit_status = 1
        mock_orm.load_node.return_value = mock_node

        adapter = AiiDAQueryAdapter()
        status = adapter._map_status("finished", node_pk=123)

        assert status == "failed"


class TestAiiDAQueryAdapterExtractContent:
    """Test content extraction methods."""

    def test_extract_input_content_from_crystal(self, mock_aiida_modules):
        """Test extracting input from crystal namespace."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        adapter = AiiDAQueryAdapter()

        mock_node = MagicMock()
        mock_input_file = MagicMock()
        mock_input_file.get_content.return_value = "CRYSTAL\nEND"
        mock_node.inputs.crystal.input_file = mock_input_file

        content = adapter._extract_input_content(mock_node)

        assert content == "CRYSTAL\nEND"

    def test_extract_input_content_empty(self, mock_aiida_modules):
        """Test extracting input when not available."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        adapter = AiiDAQueryAdapter()
        mock_node = MagicMock(spec=[])

        content = adapter._extract_input_content(mock_node)

        assert content == ""

    def test_extract_results_from_output_parameters(self, mock_aiida_modules):
        """Test extracting results from output_parameters."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        adapter = AiiDAQueryAdapter()

        mock_node = MagicMock()
        mock_node.outputs.output_parameters.get_dict.return_value = {
            "energy": -100.5,
        }

        results_json = adapter._extract_results(mock_node)
        results = json.loads(results_json)

        assert results["energy"] == -100.5

    def test_extract_results_empty(self, mock_aiida_modules):
        """Test extracting results when not available."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        adapter = AiiDAQueryAdapter()

        mock_node = MagicMock()
        del mock_node.outputs.output_parameters
        mock_node.base.extras.all = {}

        results_json = adapter._extract_results(mock_node)

        assert results_json == "{}"


class TestDatabaseAlias:
    """Test that Database alias works correctly."""

    def test_database_alias_exists(self, mock_aiida_modules):
        """Test that Database alias is exported."""
        from src.aiida.query_adapter import Database

        assert Database is not None

    def test_database_alias_is_adapter(self, mock_aiida_modules):
        """Test that Database is an alias for AiiDAQueryAdapter."""
        from src.aiida.query_adapter import AiiDAQueryAdapter, Database

        assert Database is AiiDAQueryAdapter
