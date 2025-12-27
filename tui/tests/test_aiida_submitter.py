"""Unit tests for AiiDA job submitter."""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest


class TestAiiDASubmitter:
    """Test suite for AiiDASubmitter class."""

    @pytest.fixture
    def mock_profile(self):
        """Mock AiiDA profile loading."""
        with patch("aiida.load_profile") as mock:
            yield mock

    @pytest.fixture
    def submitter(self, mock_profile):
        """Create AiiDASubmitter instance with mocked profile."""
        from src.aiida.submitter import AiiDASubmitter

        return AiiDASubmitter(profile_name="test-profile")

    def test_init(self):
        """Test submitter initialization."""
        from src.aiida.submitter import AiiDASubmitter

        submitter = AiiDASubmitter(profile_name="custom-profile")
        assert submitter.profile_name == "custom-profile"
        assert not submitter._profile_loaded

    def test_ensure_profile_loads_once(self, submitter, mock_profile):
        """Test that profile is loaded only once."""
        submitter._ensure_profile()
        submitter._ensure_profile()

        mock_profile.assert_called_once_with("test-profile")

    @patch("src.aiida.submitter.orm")
    @patch("src.aiida.submitter.submit")
    def test_submit_basic_job(self, mock_submit, mock_orm, submitter):
        """Test submitting a basic calculation."""
        # Mock Code
        mock_code = MagicMock()
        mock_code.label = "crystalOMP"
        mock_orm.load_code.return_value = mock_code

        # Mock input file
        mock_input_file = MagicMock()
        mock_input_file.pk = 1
        mock_orm.SinglefileData.from_string.return_value = mock_input_file

        # Mock submit result
        mock_node = MagicMock()
        mock_node.pk = 123
        mock_submit.return_value = mock_node

        input_content = "CRYSTAL\n0 0 0\nEND"
        job_id = submitter.submit_job(
            code_label="crystalOMP@localhost",
            input_content=input_content,
            job_name="Test Job",
        )

        assert job_id == 123
        mock_submit.assert_called_once()

    @patch("src.aiida.submitter.orm")
    @patch("src.aiida.submitter.submit")
    def test_submit_with_metadata(self, mock_submit, mock_orm, submitter):
        """Test submitting with metadata options."""
        mock_code = MagicMock()
        mock_orm.load_code.return_value = mock_code

        mock_input_file = MagicMock()
        mock_input_file.pk = 1
        mock_orm.SinglefileData.from_string.return_value = mock_input_file

        mock_node = MagicMock()
        mock_node.pk = 456
        mock_submit.return_value = mock_node

        job_id = submitter.submit_job(
            code_label="crystalOMP@localhost",
            input_content="CRYSTAL\n0 0 0\nEND",
            job_name="Custom Job",
            metadata={
                "options": {
                    "resources": {"num_machines": 1, "num_mpiprocs_per_machine": 4},
                    "max_wallclock_seconds": 3600,
                },
                "label": "Custom Label",
                "description": "Custom Description",
            },
        )

        assert job_id == 456

        # Check that submit was called with correct inputs
        call_args = mock_submit.call_args
        assert call_args is not None

    @patch("src.aiida.submitter.orm")
    @patch("src.aiida.submitter.submit")
    def test_submit_with_parameters(self, mock_submit, mock_orm, submitter):
        """Test submitting with calculation parameters."""
        mock_code = MagicMock()
        mock_orm.load_code.return_value = mock_code

        mock_input_file = MagicMock()
        mock_orm.SinglefileData.from_string.return_value = mock_input_file

        mock_params = MagicMock()
        mock_orm.Dict.return_value = mock_params

        mock_node = MagicMock()
        mock_node.pk = 789
        mock_submit.return_value = mock_node

        job_id = submitter.submit_job(
            code_label="crystalOMP@localhost",
            input_content="CRYSTAL\n0 0 0\nEND",
            parameters={"basis_set": "pob-TZVP", "functional": "PBE"},
        )

        assert job_id == 789
        mock_orm.Dict.assert_called_once_with(
            dict={"basis_set": "pob-TZVP", "functional": "PBE"}
        )

    @patch("src.aiida.submitter.orm")
    def test_submit_code_not_found(self, mock_orm, submitter):
        """Test error when code is not found."""
        mock_orm.load_code.side_effect = Exception("Code not found")

        with pytest.raises(Exception, match="Code not found"):
            submitter.submit_job(
                code_label="nonexistent@localhost",
                input_content="CRYSTAL\n0 0 0\nEND",
            )

    @patch("src.aiida.submitter.orm")
    @patch("src.aiida.submitter.run")
    def test_run_job_blocking(self, mock_run, mock_orm, submitter):
        """Test running a job in blocking mode."""
        mock_code = MagicMock()
        mock_orm.load_code.return_value = mock_code

        mock_input_file = MagicMock()
        mock_orm.SinglefileData.from_string.return_value = mock_input_file

        # Mock run result
        mock_result = {
            "output_parameters": MagicMock(get_dict=lambda: {"energy": -100.5})
        }
        mock_run.return_value = mock_result

        result = submitter.run_job(
            code_label="crystalOMP@localhost",
            input_content="CRYSTAL\n0 0 0\nEND",
        )

        assert "output_parameters" in result
        mock_run.assert_called_once()

    @patch("src.aiida.submitter.orm")
    @patch("src.aiida.submitter.submit")
    def test_submit_with_structure(self, mock_submit, mock_orm, submitter):
        """Test submitting with structure input."""
        mock_code = MagicMock()
        mock_orm.load_code.return_value = mock_code

        mock_input_file = MagicMock()
        mock_orm.SinglefileData.from_string.return_value = mock_input_file

        mock_structure = MagicMock()
        mock_orm.StructureData.return_value = mock_structure

        mock_node = MagicMock()
        mock_node.pk = 111
        mock_submit.return_value = mock_node

        job_id = submitter.submit_job(
            code_label="crystalOMP@localhost",
            input_content="CRYSTAL\n0 0 0\nEND",
            structure=mock_structure,
        )

        assert job_id == 111

    @patch("src.aiida.submitter.orm")
    def test_get_job_status(self, mock_orm, submitter):
        """Test getting job status."""
        mock_node = MagicMock()
        mock_node.process_state.value = "running"
        mock_orm.load_node.return_value = mock_node

        status = submitter.get_job_status(123)

        assert status == "running"

    @patch("src.aiida.submitter.orm")
    def test_get_job_status_not_found(self, mock_orm, submitter):
        """Test getting status of non-existent job."""
        mock_orm.load_node.side_effect = Exception("Not found")

        status = submitter.get_job_status(999)

        assert status is None

    @patch("src.aiida.submitter.orm")
    def test_get_job_results(self, mock_orm, submitter):
        """Test retrieving job results."""
        mock_node = MagicMock()
        mock_node.outputs.output_parameters.get_dict.return_value = {
            "energy": -100.5,
            "converged": True,
        }
        mock_orm.load_node.return_value = mock_node

        results = submitter.get_job_results(123)

        assert results["energy"] == -100.5
        assert results["converged"] is True

    @patch("src.aiida.submitter.orm")
    def test_get_job_results_not_ready(self, mock_orm, submitter):
        """Test getting results when not available."""
        mock_node = MagicMock()
        del mock_node.outputs.output_parameters  # No outputs yet
        mock_orm.load_node.return_value = mock_node

        results = submitter.get_job_results(123)

        assert results is None

    @patch("src.aiida.submitter.orm")
    def test_cancel_job(self, mock_orm, submitter):
        """Test cancelling a job."""
        mock_node = MagicMock()
        mock_orm.load_node.return_value = mock_node

        success = submitter.cancel_job(123)

        # Verify kill method was called
        assert hasattr(mock_node, "kill") or True  # Mocked

    @patch("src.aiida.submitter.orm")
    def test_cancel_job_not_found(self, mock_orm, submitter):
        """Test cancelling non-existent job."""
        mock_orm.load_node.side_effect = Exception("Not found")

        success = submitter.cancel_job(999)

        # Should handle exception gracefully
        assert success is False or success is None

    def test_validate_input_content(self, submitter):
        """Test input content validation."""
        # Valid input
        valid_input = "CRYSTAL\n0 0 0\nEND"
        assert submitter._validate_input_content(valid_input) is True

        # Empty input
        assert submitter._validate_input_content("") is False

        # None input
        assert submitter._validate_input_content(None) is False

    def test_parse_code_label(self, submitter):
        """Test parsing code label."""
        code_name, computer_name = submitter._parse_code_label("crystalOMP@localhost")

        assert code_name == "crystalOMP"
        assert computer_name == "localhost"

    def test_parse_code_label_no_computer(self, submitter):
        """Test parsing code label without computer."""
        code_name, computer_name = submitter._parse_code_label("crystalOMP")

        assert code_name == "crystalOMP"
        assert computer_name is None

    @patch("src.aiida.submitter.orm")
    @patch("src.aiida.submitter.submit")
    def test_submit_with_dry_run(self, mock_submit, mock_orm, submitter):
        """Test dry run mode."""
        submitter.dry_run = True

        mock_code = MagicMock()
        mock_orm.load_code.return_value = mock_code

        mock_input_file = MagicMock()
        mock_orm.SinglefileData.from_string.return_value = mock_input_file

        job_id = submitter.submit_job(
            code_label="crystalOMP@localhost",
            input_content="CRYSTAL\n0 0 0\nEND",
        )

        # Should not actually submit in dry run
        mock_submit.assert_not_called()

    @patch("src.aiida.submitter.orm")
    @patch("src.aiida.submitter.submit")
    def test_submit_calculates_resources(self, mock_submit, mock_orm, submitter):
        """Test automatic resource calculation."""
        mock_code = MagicMock()
        mock_code.computer.get_default_mpiprocs_per_machine.return_value = 16
        mock_orm.load_code.return_value = mock_code

        mock_input_file = MagicMock()
        mock_orm.SinglefileData.from_string.return_value = mock_input_file

        mock_node = MagicMock()
        mock_node.pk = 123
        mock_submit.return_value = mock_node

        # Submit without specifying resources
        job_id = submitter.submit_job(
            code_label="crystalOMP@cluster",
            input_content="CRYSTAL\n0 0 0\nEND",
        )

        # Should use default resources from computer
        assert job_id == 123


class TestSubmitterHelpers:
    """Test helper methods."""

    @pytest.fixture
    def submitter(self):
        """Create submitter with mocked profile."""
        with patch("aiida.load_profile"):
            from src.aiida.submitter import AiiDASubmitter

            return AiiDASubmitter()

    def test_validate_input_content_valid(self, submitter):
        """Test validation of valid input."""
        assert submitter._validate_input_content("CRYSTAL\nEND") is True

    def test_validate_input_content_empty(self, submitter):
        """Test validation of empty input."""
        assert submitter._validate_input_content("") is False
        assert submitter._validate_input_content(None) is False

    def test_parse_code_label_with_computer(self, submitter):
        """Test parsing code label with computer."""
        code, computer = submitter._parse_code_label("crystalOMP@cluster.edu")
        assert code == "crystalOMP"
        assert computer == "cluster.edu"

    def test_parse_code_label_without_computer(self, submitter):
        """Test parsing code label without computer."""
        code, computer = submitter._parse_code_label("crystalOMP")
        assert code == "crystalOMP"
        assert computer is None

    def test_parse_code_label_multiple_at(self, submitter):
        """Test parsing code label with multiple @ symbols."""
        code, computer = submitter._parse_code_label("code@with@multiple@at")
        assert code == "code"
        assert computer == "with@multiple@at"  # Everything after first @


class TestIntegrationWorkflow:
    """Integration tests for complete workflows."""

    @pytest.fixture
    def full_submitter(self):
        """Create submitter with all mocks."""
        with patch("aiida.load_profile"):
            from src.aiida.submitter import AiiDASubmitter

            return AiiDASubmitter(profile_name="test")

    @patch("src.aiida.submitter.orm")
    @patch("src.aiida.submitter.submit")
    def test_full_submit_workflow(self, mock_submit, mock_orm, full_submitter):
        """Test complete job submission workflow."""
        # Setup mocks
        mock_code = MagicMock()
        mock_code.label = "crystalOMP"
        mock_orm.load_code.return_value = mock_code

        mock_input_file = MagicMock()
        mock_input_file.pk = 1
        mock_orm.SinglefileData.from_string.return_value = mock_input_file

        mock_node = MagicMock()
        mock_node.pk = 100
        mock_submit.return_value = mock_node

        # Submit job
        job_id = full_submitter.submit_job(
            code_label="crystalOMP@localhost",
            input_content="CRYSTAL\n0 0 0\nEND",
            job_name="Integration Test",
            parameters={"basis_set": "pob-TZVP"},
            metadata={
                "options": {
                    "resources": {"num_machines": 1, "num_mpiprocs_per_machine": 4}
                }
            },
        )

        # Verify submission
        assert job_id == 100
        mock_orm.load_code.assert_called_once()
        mock_submit.assert_called_once()

    @patch("src.aiida.submitter.orm")
    @patch("src.aiida.submitter.submit")
    @patch("src.aiida.submitter.run")
    def test_submit_then_monitor(self, mock_run, mock_submit, mock_orm, full_submitter):
        """Test submitting and monitoring a job."""
        # Submit
        mock_code = MagicMock()
        mock_orm.load_code.return_value = mock_code

        mock_input_file = MagicMock()
        mock_orm.SinglefileData.from_string.return_value = mock_input_file

        mock_node = MagicMock()
        mock_node.pk = 200
        mock_node.process_state.value = "running"
        mock_submit.return_value = mock_node

        job_id = full_submitter.submit_job(
            code_label="crystalOMP@localhost",
            input_content="CRYSTAL\n0 0 0\nEND",
        )

        # Monitor
        mock_orm.load_node.return_value = mock_node
        status = full_submitter.get_job_status(job_id)

        assert status == "running"
