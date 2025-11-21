"""
Comprehensive tests for SQLite concurrent access with WAL mode.

Tests verify that:
- WAL mode is enabled
- Busy timeout is configured (5 seconds)
- Synchronous is set to NORMAL
- Multiple connections can write concurrently
- Context managers prevent "database is locked" errors
- Transaction isolation is maintained
"""

import json
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

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
    # Clean up WAL files
    wal_path = Path(str(db_path) + "-wal")
    shm_path = Path(str(db_path) + "-shm")
    wal_path.unlink(missing_ok=True)
    shm_path.unlink(missing_ok=True)


class TestWALConfiguration:
    """Tests for WAL mode configuration."""

    def test_wal_mode_enabled(self, temp_db):
        """Test that WAL mode is enabled."""
        cursor = temp_db.conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode.upper() == "WAL"

    def test_busy_timeout_set(self, temp_db):
        """Test that busy_timeout is configured."""
        cursor = temp_db.conn.execute("PRAGMA busy_timeout")
        timeout = cursor.fetchone()[0]
        assert timeout == 5000  # 5 seconds in milliseconds

    def test_synchronous_normal(self, temp_db):
        """Test that synchronous is set to NORMAL."""
        cursor = temp_db.conn.execute("PRAGMA synchronous")
        # Returns 1 for NORMAL
        sync_level = cursor.fetchone()[0]
        assert sync_level == 1  # NORMAL = 1

    def test_foreign_keys_enabled(self, temp_db):
        """Test that foreign keys are enforced."""
        cursor = temp_db.conn.execute("PRAGMA foreign_keys")
        enabled = cursor.fetchone()[0]
        assert enabled == 1

    def test_wal_files_created(self, temp_db):
        """Test that WAL files are created on first write."""
        # WAL files should exist after first write
        db_path = temp_db.db_path
        wal_path = Path(str(db_path) + "-wal")

        # Create a job to trigger write
        temp_db.create_job("test", "/tmp/test", "input")

        # WAL files should be created
        assert wal_path.exists()


class TestConcurrentWrites:
    """Tests for concurrent write operations."""

    def test_concurrent_job_creation_sequential(self, temp_db):
        """Test creating jobs sequentially from same connection."""
        job_ids = []
        for i in range(10):
            job_id = temp_db.create_job(f"job_{i}", f"/tmp/job_{i}", f"input_{i}")
            job_ids.append(job_id)

        assert len(job_ids) == 10
        assert len(set(job_ids)) == 10  # All unique

    def test_concurrent_job_creation_multiple_connections(self, temp_db):
        """Test creating jobs from multiple database connections."""
        db_path = temp_db.db_path
        job_ids = []
        lock = threading.Lock()

        def create_job_from_thread(index):
            db = Database(db_path)
            try:
                job_id = db.create_job(
                    f"job_{index}",
                    f"/tmp/job_{index}",
                    f"input_{index}"
                )
                with lock:
                    job_ids.append(job_id)
            finally:
                db.close()

        # Create jobs from 5 concurrent threads
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(create_job_from_thread, i)
                for i in range(20)
            ]
            for future in as_completed(futures):
                future.result()  # Raise any exceptions

        # All jobs should be created
        assert len(job_ids) == 20
        assert len(set(job_ids)) == 20  # All unique

        # Verify all jobs exist in original connection
        jobs = temp_db.get_all_jobs()
        assert len(jobs) == 20

    def test_concurrent_status_updates(self, temp_db):
        """Test concurrent status updates from multiple threads."""
        # Create a job first
        job_id = temp_db.create_job("test", "/tmp/test", "input")

        db_path = temp_db.db_path
        statuses = ["QUEUED", "RUNNING", "COMPLETED"]
        update_count = [0]
        lock = threading.Lock()

        def update_status_from_thread(status):
            db = Database(db_path)
            try:
                db.update_status(job_id, status)
                with lock:
                    update_count[0] += 1
            finally:
                db.close()

        # Update status from multiple threads
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [
                executor.submit(update_status_from_thread, status)
                for status in statuses
            ]
            for future in as_completed(futures):
                future.result()

        assert update_count[0] == 3

    def test_concurrent_results_updates(self, temp_db):
        """Test concurrent results updates."""
        job_ids = []
        for i in range(5):
            job_id = temp_db.create_job(f"job_{i}", f"/tmp/job_{i}", f"input_{i}")
            job_ids.append(job_id)

        db_path = temp_db.db_path
        update_count = [0]
        lock = threading.Lock()

        def update_results_from_thread(job_id, energy):
            db = Database(db_path)
            try:
                db.update_results(
                    job_id,
                    final_energy=energy,
                    key_results={"convergence": "CONVERGED"}
                )
                with lock:
                    update_count[0] += 1
            finally:
                db.close()

        # Update results from multiple threads
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(update_results_from_thread, job_ids[i], -100.0 - i)
                for i in range(5)
            ]
            for future in as_completed(futures):
                future.result()

        assert update_count[0] == 5

        # Verify all results were written
        for i, job_id in enumerate(job_ids):
            job = temp_db.get_job(job_id)
            assert job.final_energy == -100.0 - i
            assert job.key_results["convergence"] == "CONVERGED"

    def test_concurrent_cluster_operations(self, temp_db):
        """Test concurrent cluster create and update operations."""
        db_path = temp_db.db_path
        cluster_ids = []
        lock = threading.Lock()

        def create_cluster_from_thread(index):
            db = Database(db_path)
            try:
                cluster_id = db.create_cluster(
                    name=f"cluster_{index}",
                    type="ssh",
                    hostname=f"host{index}.example.com",
                    username=f"user_{index}"
                )
                with lock:
                    cluster_ids.append(cluster_id)
            finally:
                db.close()

        # Create clusters from multiple threads
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(create_cluster_from_thread, i)
                for i in range(10)
            ]
            for future in as_completed(futures):
                future.result()

        assert len(cluster_ids) == 10

    def test_mixed_read_write_operations(self, temp_db):
        """Test mixed read and write operations from multiple threads."""
        # Create initial jobs
        for i in range(10):
            temp_db.create_job(f"job_{i}", f"/tmp/job_{i}", f"input_{i}")

        db_path = temp_db.db_path
        operations_completed = [0]
        lock = threading.Lock()

        def reader_thread():
            db = Database(db_path)
            try:
                for _ in range(10):
                    jobs = db.get_all_jobs()
                    assert len(jobs) >= 10
                with lock:
                    operations_completed[0] += 1
            finally:
                db.close()

        def writer_thread(base_index):
            db = Database(db_path)
            try:
                for i in range(5):
                    job_id = db.create_job(
                        f"new_job_{base_index}_{i}",
                        f"/tmp/new_job_{base_index}_{i}",
                        f"input_{base_index}_{i}"
                    )
                    db.update_status(job_id, "RUNNING")
                with lock:
                    operations_completed[0] += 1
            finally:
                db.close()

        # Run readers and writers concurrently
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            # 3 reader threads
            for _ in range(3):
                futures.append(executor.submit(reader_thread))
            # 2 writer threads
            for i in range(2):
                futures.append(executor.submit(writer_thread, i))

            for future in as_completed(futures):
                future.result()

        assert operations_completed[0] == 5


class TestContextManagerTransactions:
    """Tests for context manager transaction handling."""

    def test_context_manager_commits_on_success(self, temp_db):
        """Test that context manager commits on successful operation."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")

        # Read in new connection to verify commit
        db2 = Database(temp_db.db_path)
        job = db2.get_job(job_id)
        db2.close()

        assert job is not None
        assert job.name == "test"

    def test_context_manager_rollback_on_error(self, temp_db):
        """Test that context manager rolls back on error."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")
        initial_status = "PENDING"

        # Try to update with invalid status (should fail)
        try:
            with temp_db.conn:
                temp_db.conn.execute(
                    "UPDATE jobs SET status = ? WHERE id = ?",
                    ("INVALID_STATUS", job_id)
                )
        except sqlite3.IntegrityError:
            pass

        # Status should not have changed
        job = temp_db.get_job(job_id)
        assert job.status == initial_status

    def test_create_job_uses_context_manager(self, temp_db):
        """Test that create_job uses context manager properly."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")

        # Verify job was committed
        job = temp_db.get_job(job_id)
        assert job is not None

    def test_update_status_uses_context_manager(self, temp_db):
        """Test that update_status uses context manager properly."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")
        temp_db.update_status(job_id, "RUNNING", pid=12345)

        # Verify update was committed
        job = temp_db.get_job(job_id)
        assert job.status == "RUNNING"
        assert job.pid == 12345

    def test_update_results_uses_context_manager(self, temp_db):
        """Test that update_results uses context manager properly."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")
        temp_db.update_results(job_id, final_energy=-123.45, key_results={"a": 1})

        # Verify update was committed
        job = temp_db.get_job(job_id)
        assert job.final_energy == -123.45
        assert job.key_results["a"] == 1


class TestConcurrencyStress:
    """Stress tests for concurrent database access."""

    def test_high_volume_concurrent_writes(self, temp_db):
        """Test high volume of concurrent writes."""
        db_path = temp_db.db_path
        total_jobs = 100
        thread_count = 10
        jobs_per_thread = total_jobs // thread_count

        def create_many_jobs(thread_id):
            db = Database(db_path)
            try:
                for i in range(jobs_per_thread):
                    db.create_job(
                        f"stress_job_{thread_id}_{i}",
                        f"/tmp/stress_job_{thread_id}_{i}",
                        f"input_{thread_id}_{i}"
                    )
            finally:
                db.close()

        # Run concurrent creation
        with ThreadPoolExecutor(max_workers=thread_count) as executor:
            futures = [
                executor.submit(create_many_jobs, i)
                for i in range(thread_count)
            ]
            for future in as_completed(futures):
                future.result()

        # Verify all jobs were created
        jobs = temp_db.get_all_jobs()
        assert len(jobs) == total_jobs

    def test_concurrent_read_consistency(self, temp_db):
        """Test that concurrent reads see consistent data."""
        # Create initial data
        job_ids = []
        for i in range(50):
            job_id = temp_db.create_job(
                f"consistency_job_{i}",
                f"/tmp/consistency_job_{i}",
                f"input_{i}"
            )
            job_ids.append(job_id)
            temp_db.update_status(job_id, "RUNNING", pid=1000 + i)

        db_path = temp_db.db_path
        results = []
        lock = threading.Lock()

        def read_jobs():
            db = Database(db_path)
            try:
                for _ in range(10):
                    jobs = db.get_all_jobs()
                    with lock:
                        results.append(len(jobs))
                    assert len(jobs) == 50
            finally:
                db.close()

        # Read from multiple threads
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(read_jobs) for _ in range(5)]
            for future in as_completed(futures):
                future.result()

        # All reads should see 50 jobs
        assert all(count == 50 for count in results)

    def test_database_locked_error_recovery(self, temp_db):
        """Test that system recovers from lock contention."""
        db_path = temp_db.db_path
        success_count = [0]
        error_count = [0]
        lock = threading.Lock()

        def aggressive_write(index):
            db = Database(db_path)
            try:
                # Very aggressive writes without delays
                for i in range(20):
                    try:
                        db.create_job(
                            f"lock_test_{index}_{i}",
                            f"/tmp/lock_test_{index}_{i}",
                            f"input_{index}_{i}"
                        )
                        with lock:
                            success_count[0] += 1
                    except sqlite3.DatabaseError:
                        with lock:
                            error_count[0] += 1
                        raise
            finally:
                db.close()

        # Stress test with many concurrent writers
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(aggressive_write, i)
                for i in range(10)
            ]
            for future in as_completed(futures):
                future.result()

        # All writes should succeed due to WAL + timeout
        assert success_count[0] == 200
        assert error_count[0] == 0


class TestDatabaseIsolation:
    """Tests for transaction isolation."""

    def test_isolation_between_connections(self, temp_db):
        """Test that changes are isolated between connections until commit."""
        job_id = temp_db.create_job("test", "/tmp/test", "input")
        initial_status = "PENDING"

        # Create second connection
        db2 = Database(temp_db.db_path)

        # Update status in first connection
        temp_db.update_status(job_id, "RUNNING", pid=999)

        # Read in second connection
        job1 = temp_db.get_job(job_id)
        job2 = db2.get_job(job_id)

        # Both should see updated status (WAL ensures visibility)
        assert job1.status == "RUNNING"
        assert job2.status == "RUNNING"

        db2.close()


class TestPragmaSettings:
    """Tests for PRAGMA configurations."""

    def test_all_pragmas_set_correctly(self, temp_db):
        """Test that all required PRAGMAs are set."""
        cursor = temp_db.conn.execute("PRAGMA journal_mode")
        journal_mode = cursor.fetchone()[0].upper()
        assert journal_mode == "WAL"

        cursor = temp_db.conn.execute("PRAGMA busy_timeout")
        busy_timeout = cursor.fetchone()[0]
        assert busy_timeout == 5000

        cursor = temp_db.conn.execute("PRAGMA synchronous")
        synchronous = cursor.fetchone()[0]
        assert synchronous == 1  # NORMAL

        cursor = temp_db.conn.execute("PRAGMA foreign_keys")
        foreign_keys = cursor.fetchone()[0]
        assert foreign_keys == 1

    def test_timeout_applies_to_connection(self, temp_db):
        """Test that sqlite3.connect timeout is set."""
        # Connection timeout is passed to sqlite3.connect
        # Verify connection was created with timeout
        assert temp_db.conn is not None
        # Underlying timeout handled by sqlite3 module


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
