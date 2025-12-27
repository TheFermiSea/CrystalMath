"""Unit tests for AiiDA QueryAdapter."""

import json
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest


class TestAiiDAQueryAdapter:
    """Test suite for AiiDAQueryAdapter class."""

    @pytest.fixture
    def mock_profile(self):
        """Mock AiiDA profile loading."""
        with patch("aiida.load_profile") as mock:
            yield mock

    @pytest.fixture
    def adapter(self, mock_profile):
        """Create QueryAdapter instance with mocked profile."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        return AiiDAQueryAdapter(profile_name="test-profile")

    def test_init(self):
        """Test adapter initialization."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        adapter = AiiDAQueryAdapter(profile_name="custom-profile")
        assert adapter.profile_name == "custom-profile"
        assert not adapter._profile_loaded

    def test_status_mapping(self):
        """Test status mapping dictionaries."""
        from src.aiida.query_adapter import AiiDAQueryAdapter

        # TUI -> AiiDA mapping
        assert AiiDAQueryAdapter.STATUS_TO_AIIDA["pending"] == ["created", "waiting"]
        assert AiiDAQueryAdapter.STATUS_TO_AIIDA["running"] == ["running"]
        assert AiiDAQueryAdapter.STATUS_TO_AIIDA["completed"] == ["finished"]
        assert AiiDAQueryAdapter.STATUS_TO_AIIDA["failed"] == ["excepted", "killed"]

        # AiiDA -> TUI mapping
        assert AiiDAQueryAdapter.AIIDA_TO_STATUS["created"] == "pending"
        assert AiiDAQueryAdapter.AIIDA_TO_STATUS["running"] == "running"
        assert AiiDAQueryAdapter.AIIDA_TO_STATUS["finished"] == "completed"
        assert AiiDAQueryAdapter.AIIDA_TO_STATUS["excepted"] == "failed"

    def test_ensure_profile_loads_once(self, adapter, mock_profile):
        """Test that profile is loaded only once."""
        adapter._ensure_profile()
        adapter._ensure_profile()

        # Should only be called once
        mock_profile.assert_called_once_with("test-profile")

    @patch("src.aiida.query_adapter.QueryBuilder")
    @patch("src.aiida.query_adapter.CalcJobNode")
    @patch("src.aiida.query_adapter.WorkChainNode")
    def test_list_jobs_no_filter(self, mock_wc, mock_calc, mock_qb, adapter):
        """Test listing all jobs without status filter."""
        # Mock QueryBuilder results
        mock_qb_instance = MagicMock()
        mock_qb.return_value = mock_qb_instance
        mock_qb_instance.all.return_value = [
            (1, "Job 1", datetime(2024, 1, 1), datetime(2024, 1, 2), "finished"),
            (2, "Job 2", datetime(2024, 1, 3), datetime(2024, 1, 4), "running"),
        ]

        jobs = adapter.list_jobs()

        assert len(jobs) == 2
        assert jobs[0]["id"] == 1
        assert jobs[0]["name"] == "Job 1"
        assert jobs[0]["runner_type"] == "aiida"
        assert jobs[1]["id"] == 2

    @patch("src.aiida.query_adapter.QueryBuilder")
    @patch("src.aiida.query_adapter.CalcJobNode")
    @patch("src.aiida.query_adapter.WorkChainNode")
    def test_list_jobs_with_status_filter(self, mock_wc, mock_calc, mock_qb, adapter):
        """Test listing jobs filtered by status."""
        mock_qb_instance = MagicMock()
        mock_qb.return_value = mock_qb_instance
        mock_qb_instance.all.return_value = [
            (1, "Running Job", datetime.now(), datetime.now(), "running"),
        ]

        jobs = adapter.list_jobs(status="running")

        # Check that filter was added
        mock_qb_instance.add_filter.assert_called()
        assert len(jobs) == 1
        assert jobs[0]["name"] == "Running Job"

    @patch("src.aiida.query_adapter.QueryBuilder")
    @patch("src.aiida.query_adapter.CalcJobNode")
    @patch("src.aiida.query_adapter.WorkChainNode")
    def test_list_jobs_with_pagination(self, mock_wc, mock_calc, mock_qb, adapter):
        """Test job listing with limit and offset."""
        mock_qb_instance = MagicMock()
        mock_qb.return_value = mock_qb_instance
        mock_qb_instance.all.return_value = []

        adapter.list_jobs(limit=10, offset=20)

        mock_qb_instance.limit.assert_called_once_with(10)
        mock_qb_instance.offset.assert_called_once_with(20)

    @patch("src.aiida.query_adapter.orm")
    def test_get_job_found(self, mock_orm, adapter):
        """Test getting a job that exists."""
        # Mock node
        mock_node = MagicMock()
        mock_node.pk = 123
        mock_node.label = "Test Job"
        mock_node.process_state.value = "finished"
        mock_node.ctime = datetime(2024, 1, 1)
        mock_node.mtime = datetime(2024, 1, 2)
        mock_node.computer = None

        mock_orm.load_node.return_value = mock_node
        mock_orm.CalcJobNode = type("CalcJobNode", (), {})
        mock_orm.WorkChainNode = type("WorkChainNode", (), {})

        # Make isinstance check pass
        mock_node.__class__.__bases__ = (mock_orm.CalcJobNode,)

        job = adapter.get_job(123)

        assert job is not None
        assert job["id"] == 123
        assert job["name"] == "Test Job"
        assert job["runner_type"] == "aiida"

    @patch("src.aiida.query_adapter.orm")
    def test_get_job_not_found(self, mock_orm, adapter):
        """Test getting a job that doesn't exist."""
        mock_orm.load_node.side_effect = Exception("Not found")

        job = adapter.get_job(999)

        assert job is None

    @patch("src.aiida.query_adapter.orm")
    def test_create_job(self, mock_orm, adapter):
        """Test creating a new job."""
        # Mock SinglefileData
        mock_input_file = MagicMock()
        mock_input_file.pk = 1
        mock_orm.SinglefileData.from_string.return_value = mock_input_file

        # Mock Dict
        mock_metadata = MagicMock()
        mock_metadata.pk = 2
        mock_orm.Dict.return_value = mock_metadata

        job_id = adapter.create_job(
            name="New Job",
            input_content="CRYSTAL\n0 0 0\nEND",
        )

        assert job_id == 2
        mock_orm.SinglefileData.from_string.assert_called_once()
        mock_input_file.store.assert_called_once()
        mock_metadata.store.assert_called_once()

    @patch("src.aiida.query_adapter.orm")
    def test_update_job(self, mock_orm, adapter):
        """Test updating job extras."""
        mock_node = MagicMock()
        mock_orm.load_node.return_value = mock_node

        results_json = json.dumps({"energy": -100.5})
        success = adapter.update_job(123, results_json=results_json, custom_field="value")

        assert success
        mock_node.base.extras.set.assert_called()

    @patch("src.aiida.query_adapter.orm")
    def test_update_job_not_found(self, mock_orm, adapter):
        """Test updating non-existent job."""
        mock_orm.load_node.side_effect = Exception("Not found")

        success = adapter.update_job(999, results_json="{}")

        assert not success

    @patch("src.aiida.query_adapter.orm")
    def test_delete_job(self, mock_orm, adapter):
        """Test deleting (hiding) a job."""
        mock_node = MagicMock()
        mock_orm.load_node.return_value = mock_node

        success = adapter.delete_job(123)

        assert success
        mock_node.base.extras.set.assert_called_once_with("tui_hidden", True)

    @patch("src.aiida.query_adapter.QueryBuilder")
    @patch("src.aiida.query_adapter.CalcJobNode")
    @patch("src.aiida.query_adapter.WorkChainNode")
    def test_get_job_count(self, mock_wc, mock_calc, mock_qb, adapter):
        """Test counting jobs."""
        mock_qb_instance = MagicMock()
        mock_qb.return_value = mock_qb_instance
        mock_qb_instance.count.return_value = 42

        count = adapter.get_job_count()

        assert count == 42

    @patch("src.aiida.query_adapter.QueryBuilder")
    @patch("src.aiida.query_adapter.CalcJobNode")
    @patch("src.aiida.query_adapter.WorkChainNode")
    def test_get_job_count_with_status(self, mock_wc, mock_calc, mock_qb, adapter):
        """Test counting jobs with status filter."""
        mock_qb_instance = MagicMock()
        mock_qb.return_value = mock_qb_instance
        mock_qb_instance.count.return_value = 5

        count = adapter.get_job_count(status="running")

        assert count == 5
        mock_qb_instance.add_filter.assert_called_once()

    @patch("src.aiida.query_adapter.Computer")
    def test_list_clusters(self, mock_computer, adapter):
        """Test listing AiiDA computers as clusters."""
        mock_comp1 = MagicMock()
        mock_comp1.pk = 1
        mock_comp1.label = "localhost"
        mock_comp1.hostname = "127.0.0.1"
        mock_comp1.scheduler_type = "core.direct"
        mock_comp1.get_property.return_value = 4

        mock_computer.collection.all.return_value = [mock_comp1]

        clusters = adapter.list_clusters()

        assert len(clusters) == 1
        assert clusters[0]["name"] == "localhost"
        assert clusters[0]["hostname"] == "127.0.0.1"
        assert clusters[0]["queue_type"] == "direct"

    def test_map_status_finished_success(self, adapter):
        """Test mapping finished status with success."""
        with patch("src.aiida.query_adapter.orm") as mock_orm:
            mock_node = MagicMock()
            mock_node.exit_status = 0
            mock_orm.load_node.return_value = mock_node

            status = adapter._map_status("finished", node_pk=123)

            assert status == "completed"

    def test_map_status_finished_failed(self, adapter):
        """Test mapping finished status with failure."""
        with patch("src.aiida.query_adapter.orm") as mock_orm:
            mock_node = MagicMock()
            mock_node.exit_status = 1
            mock_orm.load_node.return_value = mock_node

            status = adapter._map_status("finished", node_pk=123)

            assert status == "failed"

    def test_map_status_running(self, adapter):
        """Test mapping running status."""
        status = adapter._map_status("running")
        assert status == "running"

    def test_map_status_unknown(self, adapter):
        """Test mapping unknown status."""
        status = adapter._map_status("some_weird_state")
        assert status == "unknown"

    def test_extract_input_content_from_crystal_inputs(self, adapter):
        """Test extracting input content from crystal.input_file."""
        mock_node = MagicMock()
        mock_input_file = MagicMock()
        mock_input_file.get_content.return_value = "CRYSTAL\n0 0 0\nEND"
        mock_node.inputs.crystal.input_file = mock_input_file

        content = adapter._extract_input_content(mock_node)

        assert content == "CRYSTAL\n0 0 0\nEND"

    def test_extract_input_content_empty(self, adapter):
        """Test extracting input content when not available."""
        mock_node = MagicMock()
        mock_node.inputs = MagicMock()
        del mock_node.inputs.crystal  # No crystal inputs

        content = adapter._extract_input_content(mock_node)

        assert content == ""

    def test_extract_results_from_output_parameters(self, adapter):
        """Test extracting results from output_parameters."""
        mock_node = MagicMock()
        mock_node.outputs.output_parameters.get_dict.return_value = {
            "energy": -100.5,
            "converged": True,
        }

        results_json = adapter._extract_results(mock_node)
        results = json.loads(results_json)

        assert results["energy"] == -100.5
        assert results["converged"] is True

    def test_extract_results_from_extras(self, adapter):
        """Test extracting results from extras."""
        mock_node = MagicMock()
        del mock_node.outputs.output_parameters  # No output_parameters
        mock_node.base.extras.all = {"tui_results": '{"custom": "data"}'}

        results_json = adapter._extract_results(mock_node)

        assert results_json == '{"custom": "data"}'

    def test_extract_results_empty(self, adapter):
        """Test extracting results when not available."""
        mock_node = MagicMock()
        del mock_node.outputs.output_parameters
        mock_node.base.extras.all = {}

        results_json = adapter._extract_results(mock_node)

        assert results_json == "{}"


class TestDatabaseAlias:
    """Test that Database alias works correctly."""

    def test_database_alias_exists(self):
        """Test that Database alias is exported."""
        from src.aiida.query_adapter import Database

        assert Database is not None

    def test_database_alias_is_adapter(self):
        """Test that Database is an alias for AiiDAQueryAdapter."""
        from src.aiida.query_adapter import AiiDAQueryAdapter, Database

        assert Database is AiiDAQueryAdapter
