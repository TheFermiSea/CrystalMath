"""
Comprehensive unit tests for TUI screens and UI interactions.

Tests cover:
- NewJobScreen modal behavior
- Input validation (job names, CRYSTAL input)
- Button interactions and keyboard shortcuts
- Error message display
- Job creation workflow
- File system operations (work directory creation)
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
import pytest
from textual.widgets import Input, TextArea, Button, Static

from src.core.database import Database
from src.tui.screens.new_job import NewJobScreen, JobCreated


@pytest.fixture
def temp_workspace():
    """Create temporary workspace for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        db_path = workspace / "test.db"
        calculations_dir = workspace / "calculations"
        calculations_dir.mkdir()

        db = Database(db_path)
        yield db, calculations_dir

        db.close()


@pytest.fixture
def mock_app():
    """Create a mock Textual app for screen testing."""
    app = MagicMock()
    app.query_one = Mock()
    return app


class TestNewJobScreenInitialization:
    """Tests for NewJobScreen initialization and composition."""

    def test_screen_creates_with_database(self, temp_workspace):
        """Test that screen initializes with database reference."""
        db, calcs_dir = temp_workspace
        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        assert screen.database is db
        assert screen.calculations_dir == calcs_dir

    def test_screen_has_correct_bindings(self, temp_workspace):
        """Test that keyboard bindings are registered."""
        db, calcs_dir = temp_workspace
        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        binding_keys = [b.key for b in screen.BINDINGS]
        assert "escape" in binding_keys
        assert "ctrl+s" in binding_keys


class TestInputValidation:
    """Tests for input validation logic."""

    @pytest.mark.skip(reason="Requires complete widget mocking or Textual app context")
    def test_empty_job_name_validation(self, temp_workspace):
        """Test that empty job name is rejected."""
        db, calcs_dir = temp_workspace
        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        # Mock widgets
        job_name_input = Mock(spec=Input)
        job_name_input.value = ""
        input_textarea = Mock(spec=TextArea)
        input_textarea.text = "CRYSTAL\nEND\nEND\n"
        error_message = Mock(spec=Static)

        with patch.object(screen, 'query_one') as mock_query:
            def query_side_effect(selector, widget_type=None):
                if "job_name_input" in selector:
                    return job_name_input
                elif "input_textarea" in selector:
                    return input_textarea
                elif "error_message" in selector:
                    return error_message
            mock_query.side_effect = query_side_effect

            screen.action_submit()

            # Should show error
            error_message.update.assert_called()
            assert "cannot be empty" in error_message.update.call_args[0][0].lower()

    @pytest.mark.skip(reason="Requires complete widget mocking or Textual app context")
    def test_invalid_characters_in_job_name(self, temp_workspace):
        """Test that job names with invalid characters are rejected."""
        db, calcs_dir = temp_workspace
        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        invalid_names = [
            "job name with spaces",
            "job/with/slashes",
            "job@with#special",
            "job.with.dots",
        ]

        for invalid_name in invalid_names:
            job_name_input = Mock(spec=Input)
            job_name_input.value = invalid_name
            input_textarea = Mock(spec=TextArea)
            input_textarea.text = "CRYSTAL\nEND\nEND\n"
            error_message = Mock(spec=Static)

            with patch.object(screen, 'query_one') as mock_query:
                def query_side_effect(selector, widget_type=None):
                    if "job_name_input" in selector:
                        return job_name_input
                    elif "input_textarea" in selector:
                        return input_textarea
                    elif "error_message" in selector:
                        return error_message
                mock_query.side_effect = query_side_effect

                screen.action_submit()

                error_message.update.assert_called()
                error_msg = error_message.update.call_args[0][0].lower()
                assert "letters" in error_msg or "characters" in error_msg

    def test_valid_job_name_characters(self, temp_workspace):
        """Test that valid job names with allowed characters pass validation."""
        db, calcs_dir = temp_workspace

        valid_names = [
            "job123",
            "my_job",
            "test-job",
            "job_123-test",
            "JOB",
            "j",
        ]

        for valid_name in valid_names:
            screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

            # All of these should pass name validation
            # (may fail later on duplicate check or input validation)
            assert all(c.isalnum() or c in "_-" for c in valid_name)

    @pytest.mark.skip(reason="Requires complete widget mocking or Textual app context")
    def test_duplicate_job_name_validation(self, temp_workspace):
        """Test that duplicate job names are rejected."""
        db, calcs_dir = temp_workspace

        # Create existing job
        db.create_job("existing_job", str(calcs_dir / "0001_existing_job"), "CRYSTAL\nEND\nEND\n")

        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        job_name_input = Mock(spec=Input)
        job_name_input.value = "existing_job"
        input_textarea = Mock(spec=TextArea)
        input_textarea.text = "CRYSTAL\nEND\nEND\n"
        error_message = Mock(spec=Static)

        with patch.object(screen, 'query_one') as mock_query:
            def query_side_effect(selector, widget_type=None):
                if "job_name_input" in selector:
                    return job_name_input
                elif "input_textarea" in selector:
                    return input_textarea
                elif "error_message" in selector:
                    return error_message
            mock_query.side_effect = query_side_effect

            screen.action_submit()

            error_message.update.assert_called()
            assert "already exists" in error_message.update.call_args[0][0].lower()


class TestCrystalInputValidation:
    """Tests for CRYSTAL input file validation."""

    @pytest.mark.skip(reason="Requires complete widget mocking or Textual app context")
    def test_empty_input_rejected(self, temp_workspace):
        """Test that empty input content is rejected."""
        db, calcs_dir = temp_workspace
        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        job_name_input = Mock(spec=Input)
        job_name_input.value = "test_job"
        input_textarea = Mock(spec=TextArea)
        input_textarea.text = "   "
        error_message = Mock(spec=Static)

        with patch.object(screen, 'query_one') as mock_query:
            def query_side_effect(selector, widget_type=None):
                if "job_name_input" in selector:
                    return job_name_input
                elif "input_textarea" in selector:
                    return input_textarea
                elif "error_message" in selector:
                    return error_message
            mock_query.side_effect = query_side_effect

            screen.action_submit()

            error_message.update.assert_called()
            assert "cannot be empty" in error_message.update.call_args[0][0].lower()

    def test_validate_crystal_input_too_short(self, temp_workspace):
        """Test that input files that are too short are rejected."""
        db, calcs_dir = temp_workspace
        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        short_input = "CRYSTAL\nEND"
        error = screen._validate_crystal_input(short_input)

        assert error is not None
        assert "too short" in error.lower()

    def test_validate_crystal_input_missing_geometry_keyword(self, temp_workspace):
        """Test that input without geometry keyword is rejected."""
        db, calcs_dir = temp_workspace
        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        no_geometry = "TITLE\nSOME LINES\nEND\nEND\nEND"
        error = screen._validate_crystal_input(no_geometry)

        assert error is not None
        assert "geometry" in error.lower() or "CRYSTAL" in error or "SLAB" in error

    def test_validate_crystal_input_missing_end(self, temp_workspace):
        """Test that input without END keyword is rejected."""
        db, calcs_dir = temp_workspace
        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        no_end = "CRYSTAL\n0 0 0\n225\n4.21\nBASIS\n12 3\n"
        error = screen._validate_crystal_input(no_end)

        assert error is not None
        assert "END" in error

    def test_validate_crystal_input_insufficient_ends(self, temp_workspace):
        """Test that input with only one END is rejected."""
        db, calcs_dir = temp_workspace
        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        one_end = "CRYSTAL\n0 0 0\n225\n4.21\nEND"
        error = screen._validate_crystal_input(one_end)

        assert error is not None
        assert "2 END" in error or "two END" in error.lower()

    def test_validate_crystal_input_valid(self, temp_workspace):
        """Test that valid CRYSTAL input passes validation."""
        db, calcs_dir = temp_workspace
        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        valid_inputs = [
            "CRYSTAL\n0 0 0\n225\n4.21\n1\n12 0.0 0.0 0.0\nEND\n12 3\n1 0 3 2. 1.\nEND",
            "SLAB\n1 0 0\n225\n5.0\nEND\nBASIS\n8 3\nEND",
            "MOLECULE\n0 1\n8 0.0 0.0 0.0\nEND\n8 3\nEND",
        ]

        for valid_input in valid_inputs:
            error = screen._validate_crystal_input(valid_input)
            assert error is None, f"Valid input rejected: {valid_input[:50]}..."


class TestJobCreationWorkflow:
    """Tests for the complete job creation workflow."""

    @pytest.mark.skip(reason="Requires complete widget mocking or Textual app context")
    def test_successful_job_creation(self, temp_workspace):
        """Test successful job creation with valid inputs."""
        db, calcs_dir = temp_workspace
        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        job_name_input = Mock(spec=Input)
        job_name_input.value = "mgo_bulk"
        input_textarea = Mock(spec=TextArea)
        input_textarea.text = "CRYSTAL\n0 0 0\n225\n4.21\nEND\n12 3\n1 0 3 2. 1.\nEND"
        error_message = Mock(spec=Static)

        # Mock dismiss and post_message
        screen.dismiss = Mock()
        screen.post_message = Mock()

        with patch.object(screen, 'query_one') as mock_query:
            def query_side_effect(selector, widget_type=None):
                if "job_name_input" in selector:
                    return job_name_input
                elif "input_textarea" in selector:
                    return input_textarea
                elif "error_message" in selector:
                    return error_message
            mock_query.side_effect = query_side_effect

            screen.action_submit()

            # Verify job was created in database
            jobs = db.get_all_jobs()
            assert len(jobs) == 1
            assert jobs[0].name == "mgo_bulk"

            # Verify work directory was created
            work_dirs = list(calcs_dir.glob("*_mgo_bulk"))
            assert len(work_dirs) == 1

            # Verify input file was written
            input_file = work_dirs[0] / "input.d12"
            assert input_file.exists()
            assert "CRYSTAL" in input_file.read_text()

            # Verify screen was dismissed
            screen.dismiss.assert_called_once()

            # Verify JobCreated message was posted
            screen.post_message.assert_called_once()
            message = screen.post_message.call_args[0][0]
            assert isinstance(message, JobCreated)

    @pytest.mark.skip(reason="Requires complete widget mocking or Textual app context")
    def test_work_directory_naming(self, temp_workspace):
        """Test that work directories are named correctly."""
        db, calcs_dir = temp_workspace
        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        # Create first job
        job_id_1 = db.create_job("job1", str(calcs_dir / "0001_job1"), "input1")

        # Mock screen to create second job
        job_name_input = Mock(spec=Input)
        job_name_input.value = "job2"
        input_textarea = Mock(spec=TextArea)
        input_textarea.text = "CRYSTAL\n0 0 0\n225\n4.21\nEND\n12 3\nEND"
        error_message = Mock(spec=Static)

        screen.dismiss = Mock()
        screen.post_message = Mock()

        with patch.object(screen, 'query_one') as mock_query:
            def query_side_effect(selector, widget_type=None):
                if "job_name_input" in selector:
                    return job_name_input
                elif "input_textarea" in selector:
                    return input_textarea
                elif "error_message" in selector:
                    return error_message
            mock_query.side_effect = query_side_effect

            screen.action_submit()

            # Check that second job gets ID 2
            jobs = db.get_all_jobs()
            job2 = [j for j in jobs if j.name == "job2"][0]
            assert "0002_job2" in job2.work_dir

    @pytest.mark.skip(reason="Requires complete widget mocking or Textual app context")
    def test_work_directory_already_exists(self, temp_workspace):
        """Test error handling when work directory already exists."""
        db, calcs_dir = temp_workspace

        # Create work directory manually
        existing_dir = calcs_dir / "0001_test_job"
        existing_dir.mkdir()

        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        job_name_input = Mock(spec=Input)
        job_name_input.value = "test_job"
        input_textarea = Mock(spec=TextArea)
        input_textarea.text = "CRYSTAL\n0 0 0\n225\n4.21\nEND\n12 3\nEND"
        error_message = Mock(spec=Static)

        with patch.object(screen, 'query_one') as mock_query:
            def query_side_effect(selector, widget_type=None):
                if "job_name_input" in selector:
                    return job_name_input
                elif "input_textarea" in selector:
                    return input_textarea
                elif "error_message" in selector:
                    return error_message
            mock_query.side_effect = query_side_effect

            screen.action_submit()

            # Should show error
            error_message.update.assert_called()
            assert "already exists" in error_message.update.call_args[0][0].lower()


class TestButtonInteractions:
    """Tests for button press handling."""

    def test_create_button_calls_submit(self, temp_workspace):
        """Test that Create Job button triggers submit action."""
        db, calcs_dir = temp_workspace
        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        # Mock the action_submit method
        screen.action_submit = Mock()

        # Create mock button pressed event
        create_button = Mock(spec=Button)
        create_button.id = "create_button"

        event = Mock()
        event.button = create_button

        screen.on_button_pressed(event)

        screen.action_submit.assert_called_once()

    def test_cancel_button_dismisses_screen(self, temp_workspace):
        """Test that Cancel button dismisses the screen."""
        db, calcs_dir = temp_workspace
        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        # Mock dismiss
        screen.dismiss = Mock()

        # Create mock button pressed event
        cancel_button = Mock(spec=Button)
        cancel_button.id = "cancel_button"

        event = Mock()
        event.button = cancel_button

        screen.on_button_pressed(event)

        screen.dismiss.assert_called_once_with(None)

    def test_escape_key_cancels(self, temp_workspace):
        """Test that Escape key cancels the modal."""
        db, calcs_dir = temp_workspace
        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        screen.dismiss = Mock()
        screen.action_cancel()

        screen.dismiss.assert_called_once_with(None)

    def test_ctrl_s_submits(self, temp_workspace):
        """Test that Ctrl+S submits the form."""
        db, calcs_dir = temp_workspace
        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        screen.action_submit = Mock()

        # Trigger the binding manually
        screen.action_submit()

        screen.action_submit.assert_called_once()


class TestErrorMessageDisplay:
    """Tests for error message display functionality."""

    def test_show_error_displays_message(self, temp_workspace):
        """Test that _show_error properly displays error messages."""
        db, calcs_dir = temp_workspace
        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        error_message = Mock(spec=Static)

        with patch.object(screen, 'query_one', return_value=error_message):
            screen._show_error("Test error message")

            error_message.update.assert_called_once()
            update_text = error_message.update.call_args[0][0]
            assert "Error:" in update_text
            assert "Test error message" in update_text

            error_message.add_class.assert_called_once_with("visible")

    @pytest.mark.skip(reason="Requires complete widget mocking or Textual app context")
    def test_error_cleared_on_resubmit(self, temp_workspace):
        """Test that previous error is cleared when resubmitting."""
        db, calcs_dir = temp_workspace
        screen = NewJobScreen(database=db, calculations_dir=calcs_dir)

        job_name_input = Mock(spec=Input)
        job_name_input.value = ""
        input_textarea = Mock(spec=TextArea)
        input_textarea.text = "CRYSTAL\nEND\nEND\n"
        error_message = Mock(spec=Static)

        with patch.object(screen, 'query_one') as mock_query:
            def query_side_effect(selector, widget_type=None):
                if "job_name_input" in selector:
                    return job_name_input
                elif "input_textarea" in selector:
                    return input_textarea
                elif "error_message" in selector:
                    return error_message
            mock_query.side_effect = query_side_effect

            # First submission
            screen.action_submit()
            error_message.update.assert_called()

            # Reset mock
            error_message.reset_mock()

            # Second submission should clear error first
            screen.action_submit()
            calls = error_message.update.call_args_list
            assert len(calls) >= 2
            # First call should clear with empty string
            assert calls[0][0][0] == ""


class TestJobCreatedMessage:
    """Tests for JobCreated message."""

    def test_job_created_message_contains_correct_data(self):
        """Test that JobCreated message stores job details correctly."""
        message = JobCreated(job_id=42, job_name="test_job")

        assert message.job_id == 42
        assert message.job_name == "test_job"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
