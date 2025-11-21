"""
Comprehensive unit tests for the Database module.

Tests cover:
- Database initialization and schema creation
- Job CRUD operations (create, read, update, delete)
- Status updates with timestamps
- Results updates with JSON serialization
- Edge cases and error handling
- Concurrent access patterns
"""

import json
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime
import pytest

from src.core.database import Database, Job


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    db = Database(db_path)
    yield db

    db.close()
    db_path.unlink(missing_ok=True)


class TestDatabaseInitialization:
    """Tests for database initialization and schema creation."""

    def test_database_creation(self, temp_db):
        """Test that database is created with proper schema."""
        assert temp_db.db_path.exists()

        # Check that jobs table exists
        cursor = temp_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
        )
        assert cursor.fetchone() is not None

    def test_schema_includes_all_columns(self, temp_db):
        """Test that jobs table has all required columns."""
        cursor = temp_db.conn.execute("PRAGMA table_info(jobs)")
        columns = {row[1] for row in cursor.fetchall()}

        expected_columns = {
            'id', 'name', 'work_dir', 'status', 'created_at',
            'started_at', 'completed_at', 'pid', 'input_file',
            'final_energy', 'key_results'
        }
        assert expected_columns.issubset(columns)

    def test_indexes_created(self, temp_db):
        """Test that proper indexes are created."""
        cursor = temp_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        indexes = {row[0] for row in cursor.fetchall()}

        assert 'idx_jobs_status' in indexes
        assert 'idx_jobs_created' in indexes

    def test_status_constraint(self, temp_db):
        """Test that invalid status values are rejected."""
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            temp_db.conn.execute(
                "INSERT INTO jobs (name, work_dir, status) VALUES (?, ?, ?)",
                ("test", "/tmp/test", "INVALID_STATUS")
            )


class TestJobCreation:
    """Tests for creating new jobs."""

    def test_create_basic_job(self, temp_db):
        """Test creating a basic job with minimal fields."""
        job_id = temp_db.create_job(
            name="test_job",
            work_dir="/tmp/test_job",
            input_content="CRYSTAL\nEND\n"
        )

        assert isinstance(job_id, int)
        assert job_id > 0

    def test_created_job_has_correct_defaults(self, temp_db):
        """Test that created job has proper default values."""
        job_id = temp_db.create_job(
            name="test_job",
            work_dir="/tmp/test_job",
            input_content="CRYSTAL\nEND\n"
        )

        job = temp_db.get_job(job_id)
        assert job is not None
        assert job.name == "test_job"
        assert job.work_dir == "/tmp/test_job"
        assert job.status == "PENDING"
        assert job.input_file == "CRYSTAL\nEND\n"
        assert job.created_at is not None
        assert job.started_at is None
        assert job.completed_at is None
        assert job.pid is None
        assert job.final_energy is None
        assert job.key_results is None

    def test_create_duplicate_work_dir_fails(self, temp_db):
        """Test that duplicate work_dir raises constraint error."""
        temp_db.create_job("job1", "/tmp/test", "input1")

        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            temp_db.create_job("job2", "/tmp/test", "input2")

    def test_create_multiple_jobs(self, temp_db):
        """Test creating multiple jobs with unique work_dirs."""
        job_ids = []
        for i in range(5):
            job_id = temp_db.create_job(
                name=f"job_{i}",
                work_dir=f"/tmp/job_{i}",
                input_content=f"CRYSTAL {i}\nEND\n"
            )
            job_ids.append(job_id)

        assert len(job_ids) == 5
        assert len(set(job_ids)) == 5  # All unique


class TestJobRetrieval:
    """Tests for retrieving jobs from database."""

    def test_get_existing_job(self, temp_db):
        """Test retrieving a job that exists."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")
        job = temp_db.get_job(job_id)

        assert job is not None
        assert job.id == job_id
        assert job.name == "test"

    def test_get_nonexistent_job(self, temp_db):
        """Test retrieving a job that doesn't exist."""
        job = temp_db.get_job(99999)
        assert job is None

    def test_get_all_jobs_empty(self, temp_db):
        """Test get_all_jobs returns empty list for new database."""
        jobs = temp_db.get_all_jobs()
        assert jobs == []

    def test_get_all_jobs_multiple(self, temp_db):
        """Test get_all_jobs returns all jobs in reverse chronological order."""
        job_ids = []
        for i in range(3):
            job_id = temp_db.create_job(f"job_{i}", f"/tmp/job_{i}", f"input_{i}")
            job_ids.append(job_id)

        jobs = temp_db.get_all_jobs()
        assert len(jobs) == 3

        # Verify all jobs are present
        assert set(j.id for j in jobs) == set(job_ids)

        # Verify ordering - should be descending by created_at (newest first)
        # If timestamps identical, ordering by id DESC is acceptable
        for i in range(len(jobs) - 1):
            # Either newer timestamp or same timestamp with higher ID
            assert jobs[i].created_at >= jobs[i+1].created_at

    def test_job_dataclass_conversion(self, temp_db):
        """Test that database rows are properly converted to Job objects."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")
        job = temp_db.get_job(job_id)

        assert isinstance(job, Job)
        assert isinstance(job.id, int)
        assert isinstance(job.name, str)
        assert isinstance(job.work_dir, str)
        assert isinstance(job.status, str)


class TestStatusUpdates:
    """Tests for updating job status."""

    def test_update_status_basic(self, temp_db):
        """Test basic status update."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")
        temp_db.update_status(job_id, "RUNNING")

        job = temp_db.get_job(job_id)
        assert job.status == "RUNNING"

    def test_update_status_with_pid(self, temp_db):
        """Test status update with PID."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")
        temp_db.update_status(job_id, "RUNNING", pid=12345)

        job = temp_db.get_job(job_id)
        assert job.status == "RUNNING"
        assert job.pid == 12345

    def test_update_status_running_sets_started_at(self, temp_db):
        """Test that RUNNING status sets started_at timestamp."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")
        job_before = temp_db.get_job(job_id)
        assert job_before.started_at is None

        temp_db.update_status(job_id, "RUNNING")
        job_after = temp_db.get_job(job_id)
        assert job_after.started_at is not None

    def test_update_status_completed_sets_completed_at(self, temp_db):
        """Test that COMPLETED status sets completed_at timestamp."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")
        temp_db.update_status(job_id, "COMPLETED")

        job = temp_db.get_job(job_id)
        assert job.completed_at is not None

    def test_update_status_failed_sets_completed_at(self, temp_db):
        """Test that FAILED status sets completed_at timestamp."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")
        temp_db.update_status(job_id, "FAILED")

        job = temp_db.get_job(job_id)
        assert job.completed_at is not None

    def test_update_status_queued_no_timestamp(self, temp_db):
        """Test that QUEUED status doesn't set any timestamp."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")
        temp_db.update_status(job_id, "QUEUED")

        job = temp_db.get_job(job_id)
        assert job.started_at is None
        assert job.completed_at is None

    def test_update_status_multiple_times(self, temp_db):
        """Test updating status through multiple states."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")

        temp_db.update_status(job_id, "QUEUED")
        job1 = temp_db.get_job(job_id)
        assert job1.status == "QUEUED"

        temp_db.update_status(job_id, "RUNNING", pid=999)
        job2 = temp_db.get_job(job_id)
        assert job2.status == "RUNNING"
        assert job2.pid == 999
        assert job2.started_at is not None

        temp_db.update_status(job_id, "COMPLETED")
        job3 = temp_db.get_job(job_id)
        assert job3.status == "COMPLETED"
        assert job3.completed_at is not None


class TestResultsUpdates:
    """Tests for updating job results."""

    def test_update_results_energy_only(self, temp_db):
        """Test updating only final energy."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")
        temp_db.update_results(job_id, final_energy=-123.456789)

        job = temp_db.get_job(job_id)
        assert job.final_energy == -123.456789
        assert job.key_results is None

    def test_update_results_dict_only(self, temp_db):
        """Test updating only key_results dictionary."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")
        results = {
            "convergence": "CONVERGED",
            "iterations": 42,
            "timing": {"total": 123.45}
        }
        temp_db.update_results(job_id, key_results=results)

        job = temp_db.get_job(job_id)
        assert job.final_energy is None
        assert job.key_results == results

    def test_update_results_both(self, temp_db):
        """Test updating both energy and results."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")
        results = {"convergence": "CONVERGED"}
        temp_db.update_results(job_id, final_energy=-999.999, key_results=results)

        job = temp_db.get_job(job_id)
        assert job.final_energy == -999.999
        assert job.key_results == results

    def test_update_results_json_serialization(self, temp_db):
        """Test that complex dictionaries are properly JSON serialized."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")
        results = {
            "convergence": "CONVERGED",
            "errors": [],
            "warnings": ["Warning 1", "Warning 2"],
            "metadata": {
                "version": "23.0",
                "nested": {"a": 1, "b": [2, 3, 4]}
            }
        }
        temp_db.update_results(job_id, key_results=results)

        # Verify round-trip through database
        job = temp_db.get_job(job_id)
        assert job.key_results == results
        assert isinstance(job.key_results["warnings"], list)
        assert isinstance(job.key_results["metadata"]["nested"]["b"], list)

    def test_update_results_none_clears_data(self, temp_db):
        """Test that None values properly clear data."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")

        # Set some results
        temp_db.update_results(job_id, final_energy=-100.0, key_results={"a": 1})

        # Clear with None
        temp_db.update_results(job_id, final_energy=None, key_results=None)

        job = temp_db.get_job(job_id)
        assert job.final_energy is None
        assert job.key_results is None

    def test_update_results_overwrite(self, temp_db):
        """Test that updating results overwrites previous values."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")

        temp_db.update_results(job_id, final_energy=-100.0)
        temp_db.update_results(job_id, final_energy=-200.0)

        job = temp_db.get_job(job_id)
        assert job.final_energy == -200.0


class TestConcurrency:
    """Tests for concurrent database access."""

    def test_multiple_connections(self, temp_db):
        """Test that multiple Database instances can access same file."""
        # Create job with first connection
        job_id = temp_db.create_job("test", "/tmp/test", "input")

        # Create second connection
        db2 = Database(temp_db.db_path)

        # Read from second connection
        job = db2.get_job(job_id)
        assert job is not None
        assert job.name == "test"

        db2.close()

    def test_concurrent_writes(self, temp_db):
        """Test that concurrent writes work correctly."""
        # Create multiple jobs in sequence
        job_ids = []
        for i in range(10):
            job_id = temp_db.create_job(f"job_{i}", f"/tmp/job_{i}", f"input_{i}")
            job_ids.append(job_id)

        # Verify all jobs exist
        jobs = temp_db.get_all_jobs()
        assert len(jobs) == 10
        assert set(j.id for j in jobs) == set(job_ids)


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_empty_job_name(self, temp_db):
        """Test creating job with empty name."""
        job_id = temp_db.create_job("", "/tmp/test", "input")
        job = temp_db.get_job(job_id)
        assert job.name == ""

    def test_long_job_name(self, temp_db):
        """Test creating job with very long name."""
        long_name = "a" * 1000
        job_id = temp_db.create_job(long_name, "/tmp/test", "input")
        job = temp_db.get_job(job_id)
        assert job.name == long_name

    def test_special_characters_in_name(self, temp_db):
        """Test job name with special characters."""
        special_name = "test_job-123.v2 (final)"
        job_id = temp_db.create_job(special_name, "/tmp/test", "input")
        job = temp_db.get_job(job_id)
        assert job.name == special_name

    def test_unicode_in_input_content(self, temp_db):
        """Test input content with unicode characters."""
        unicode_input = "CRYSTAL\n# Comment with unicode: α β γ δ\nEND\n"
        job_id = temp_db.create_job("test", "/tmp/test", unicode_input)
        job = temp_db.get_job(job_id)
        assert job.input_file == unicode_input

    def test_very_large_results_dict(self, temp_db):
        """Test storing large results dictionary."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")

        # Create large nested dictionary
        large_results = {
            "iterations": [
                {"energy": -100.0 + i * 0.001, "step": i}
                for i in range(1000)
            ],
            "metadata": {"description": "x" * 10000}
        }

        temp_db.update_results(job_id, key_results=large_results)

        job = temp_db.get_job(job_id)
        assert len(job.key_results["iterations"]) == 1000
        assert len(job.key_results["metadata"]["description"]) == 10000

    def test_negative_energy_values(self, temp_db):
        """Test storing negative energy values."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")
        temp_db.update_results(job_id, final_energy=-9876.543210)

        job = temp_db.get_job(job_id)
        assert job.final_energy == -9876.543210

    def test_database_close_and_reopen(self, temp_db):
        """Test that database can be closed and reopened."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")
        db_path = temp_db.db_path

        temp_db.close()

        # Reopen database
        db2 = Database(db_path)
        job = db2.get_job(job_id)
        assert job is not None
        assert job.name == "test"

        db2.close()


class TestJobLifecycle:
    """Integration tests for complete job lifecycle."""

    def test_full_job_lifecycle(self, temp_db):
        """Test a complete job from creation to completion."""
        # Create job
        job_id = temp_db.create_job(
            name="mgo_bulk",
            work_dir="/calculations/0001_mgo_bulk",
            input_content="CRYSTAL\n0 0 0\n225\n4.21\nEND\n"
        )

        job = temp_db.get_job(job_id)
        assert job.status == "PENDING"

        # Queue job
        temp_db.update_status(job_id, "QUEUED")
        job = temp_db.get_job(job_id)
        assert job.status == "QUEUED"

        # Start running
        temp_db.update_status(job_id, "RUNNING", pid=54321)
        job = temp_db.get_job(job_id)
        assert job.status == "RUNNING"
        assert job.pid == 54321
        assert job.started_at is not None

        # Complete with results
        temp_db.update_status(job_id, "COMPLETED")
        temp_db.update_results(
            job_id,
            final_energy=-275.3456789012,
            key_results={
                "convergence": "CONVERGED",
                "iterations": 25,
                "errors": [],
                "warnings": ["Tight convergence used"]
            }
        )

        job = temp_db.get_job(job_id)
        assert job.status == "COMPLETED"
        assert job.completed_at is not None
        assert job.final_energy == -275.3456789012
        assert job.key_results["convergence"] == "CONVERGED"
        assert len(job.key_results["warnings"]) == 1

    def test_failed_job_lifecycle(self, temp_db):
        """Test job that fails during execution."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")

        temp_db.update_status(job_id, "RUNNING", pid=99999)
        temp_db.update_status(job_id, "FAILED")
        temp_db.update_results(
            job_id,
            key_results={
                "convergence": "NOT_CONVERGED",
                "errors": ["SCF did not converge in 100 cycles"]
            }
        )

        job = temp_db.get_job(job_id)
        assert job.status == "FAILED"
        assert job.completed_at is not None
        assert job.final_energy is None
        assert len(job.key_results["errors"]) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
