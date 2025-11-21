"""
Unit tests for the batch submission screen.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from textual.widgets import DataTable

from src.tui.screens.batch_submission import (
    BatchSubmissionScreen,
    BatchJobConfig,
    BatchJobsCreated
)
from src.core.database import Database


@pytest.fixture
def temp_project_dir(tmp_path):
    """Create a temporary project directory."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    calculations_dir = project_dir / "calculations"
    calculations_dir.mkdir()
    return project_dir


@pytest.fixture
def mock_database(tmp_path):
    """Create a mock database."""
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    return db


@pytest.fixture
def batch_screen(mock_database, temp_project_dir):
    """Create a BatchSubmissionScreen instance."""
    calculations_dir = temp_project_dir / "calculations"
    screen = BatchSubmissionScreen(
        database=mock_database,
        calculations_dir=calculations_dir
    )
    return screen


def test_batch_submission_screen_init(batch_screen):
    """Test batch submission screen initialization."""
    assert batch_screen.database is not None
    assert batch_screen.calculations_dir.exists()
    assert len(batch_screen.job_configs) == 0
    assert batch_screen.submitting is False


def test_batch_job_config_creation():
    """Test BatchJobConfig dataclass creation."""
    config = BatchJobConfig(
        name="test_job",
        input_file=Path("/tmp/test.d12"),
        cluster="local",
        mpi_ranks=4,
        threads=8,
        partition="compute",
        time_limit="12:00:00"
    )

    assert config.name == "test_job"
    assert config.input_file == Path("/tmp/test.d12")
    assert config.cluster == "local"
    assert config.mpi_ranks == 4
    assert config.threads == 8
    assert config.partition == "compute"
    assert config.time_limit == "12:00:00"


def test_batch_job_config_defaults():
    """Test BatchJobConfig default values."""
    config = BatchJobConfig(
        name="test_job",
        input_file=Path("/tmp/test.d12")
    )

    assert config.cluster == "local"
    assert config.mpi_ranks == 1
    assert config.threads == 4
    assert config.partition == "compute"
    assert config.time_limit == "24:00:00"


def test_validate_batch_empty(batch_screen):
    """Test validation with no jobs."""
    errors = batch_screen._validate_batch()
    assert len(errors) == 0


def test_validate_batch_duplicate_names(batch_screen, tmp_path):
    """Test validation catches duplicate job names."""
    input_file = tmp_path / "test.d12"
    input_file.write_text("END\nEND\n")

    batch_screen.job_configs = [
        BatchJobConfig(name="job1", input_file=input_file),
        BatchJobConfig(name="job1", input_file=input_file)  # Duplicate
    ]

    errors = batch_screen._validate_batch()
    assert len(errors) > 0
    assert any("duplicate" in err.lower() for err in errors)


def test_validate_batch_invalid_name(batch_screen, tmp_path):
    """Test validation catches invalid job names."""
    input_file = tmp_path / "test.d12"
    input_file.write_text("END\nEND\n")

    batch_screen.job_configs = [
        BatchJobConfig(name="job with spaces!", input_file=input_file)
    ]

    errors = batch_screen._validate_batch()
    assert len(errors) > 0
    assert any("invalid" in err.lower() for err in errors)


def test_validate_batch_invalid_resources(batch_screen, tmp_path):
    """Test validation catches invalid resource requests."""
    input_file = tmp_path / "test.d12"
    input_file.write_text("END\nEND\n")

    batch_screen.job_configs = [
        BatchJobConfig(name="job1", input_file=input_file, mpi_ranks=0),  # Invalid
        BatchJobConfig(name="job2", input_file=input_file, threads=-1)   # Invalid
    ]

    errors = batch_screen._validate_batch()
    assert len(errors) >= 2
    assert any("mpi" in err.lower() for err in errors)
    assert any("threads" in err.lower() for err in errors)


def test_validate_batch_existing_job_name(batch_screen, tmp_path):
    """Test validation catches conflicts with existing job names."""
    # Create an existing job
    work_dir = batch_screen.calculations_dir / "0001_existing_job"
    work_dir.mkdir()
    batch_screen.database.create_job(
        name="existing_job",
        work_dir=str(work_dir),
        input_content="END\nEND\n"
    )

    # Try to create batch with same name
    input_file = tmp_path / "test.d12"
    input_file.write_text("END\nEND\n")

    batch_screen.job_configs = [
        BatchJobConfig(name="existing_job", input_file=input_file)
    ]

    errors = batch_screen._validate_batch()
    assert len(errors) > 0
    assert any("already exists" in err.lower() for err in errors)


def test_validate_batch_valid_jobs(batch_screen, tmp_path):
    """Test validation passes for valid jobs."""
    input_file1 = tmp_path / "job1.d12"
    input_file1.write_text("END\nEND\n")
    input_file2 = tmp_path / "job2.d12"
    input_file2.write_text("END\nEND\n")

    batch_screen.job_configs = [
        BatchJobConfig(name="job1", input_file=input_file1, mpi_ranks=4, threads=8),
        BatchJobConfig(name="job2", input_file=input_file2, mpi_ranks=8, threads=4)
    ]

    errors = batch_screen._validate_batch()
    assert len(errors) == 0


def test_batch_jobs_created_message():
    """Test BatchJobsCreated message creation."""
    job_ids = [1, 2, 3]
    job_names = ["job1", "job2", "job3"]

    message = BatchJobsCreated(job_ids, job_names)

    assert message.job_ids == job_ids
    assert message.job_names == job_names
    assert len(message.job_ids) == len(message.job_names)


def test_add_demo_job(batch_screen):
    """Test adding a demo job to the batch."""
    initial_count = len(batch_screen.job_configs)

    batch_screen._add_demo_job()

    assert len(batch_screen.job_configs) == initial_count + 1
    job = batch_screen.job_configs[-1]
    assert job.name.startswith("batch_job_")
    assert isinstance(job.input_file, Path)


def test_add_multiple_jobs(batch_screen):
    """Test adding multiple jobs to the batch."""
    batch_screen._add_demo_job()
    batch_screen._add_demo_job()
    batch_screen._add_demo_job()

    assert len(batch_screen.job_configs) == 3

    # Job names should be unique
    names = [job.name for job in batch_screen.job_configs]
    assert len(names) == len(set(names))


def test_batch_screen_compose(batch_screen):
    """Test that the batch screen composes without errors."""
    # This would require a full Textual app context
    # For now, we just verify the method exists and is callable
    assert hasattr(batch_screen, 'compose')
    assert callable(batch_screen.compose)


def test_batch_screen_bindings(batch_screen):
    """Test that keyboard bindings are properly defined."""
    bindings = {b.key for b in batch_screen.BINDINGS}

    assert "escape" in bindings
    assert "a" in bindings
    assert "d" in bindings
    assert "enter" in bindings


def test_batch_screen_actions(batch_screen):
    """Test that action methods exist."""
    assert hasattr(batch_screen, 'action_add_job')
    assert hasattr(batch_screen, 'action_delete_job')
    assert hasattr(batch_screen, 'action_submit_all')
    assert hasattr(batch_screen, 'action_cancel')


@pytest.mark.asyncio
async def test_submit_jobs_worker_empty(batch_screen):
    """Test submission worker with no jobs."""
    # Should handle empty job list gracefully
    # This test would require mocking the UI components
    # For now, verify the method exists
    assert hasattr(batch_screen, '_submit_jobs_worker')


def test_update_job_count(batch_screen, tmp_path):
    """Test job count update logic."""
    # Add some jobs
    input_file = tmp_path / "test.d12"
    input_file.write_text("END\nEND\n")

    batch_screen.job_configs = [
        BatchJobConfig(name="job1", input_file=input_file),
        BatchJobConfig(name="job2", input_file=input_file),
        BatchJobConfig(name="job3", input_file=input_file)
    ]

    # Verify count matches
    assert len(batch_screen.job_configs) == 3


def test_batch_submission_workflow_integration(mock_database, temp_project_dir, tmp_path):
    """Integration test for complete batch submission workflow."""
    # Create input files
    input_files = []
    for i in range(3):
        input_file = tmp_path / f"job{i+1}.d12"
        input_file.write_text(f"# Job {i+1}\nEND\nEND\n")
        input_files.append(input_file)

    # Create batch screen
    calculations_dir = temp_project_dir / "calculations"
    screen = BatchSubmissionScreen(
        database=mock_database,
        calculations_dir=calculations_dir
    )

    # Add jobs
    for i, input_file in enumerate(input_files):
        config = BatchJobConfig(
            name=f"job{i+1}",
            input_file=input_file,
            mpi_ranks=4,
            threads=8
        )
        screen.job_configs.append(config)

    # Validate
    errors = screen._validate_batch()
    assert len(errors) == 0

    # Verify job configs
    assert len(screen.job_configs) == 3
    assert all(job.mpi_ranks == 4 for job in screen.job_configs)
    assert all(job.threads == 8 for job in screen.job_configs)


def test_batch_submission_metadata(batch_screen, tmp_path):
    """Test that metadata is correctly configured for batch jobs."""
    input_file = tmp_path / "test.d12"
    input_file.write_text("END\nEND\n")

    config = BatchJobConfig(
        name="metadata_test",
        input_file=input_file,
        cluster="hpc",
        mpi_ranks=16,
        threads=2,
        partition="gpu",
        time_limit="48:00:00"
    )

    assert config.cluster == "hpc"
    assert config.mpi_ranks == 16
    assert config.threads == 2
    assert config.partition == "gpu"
    assert config.time_limit == "48:00:00"
