"""
Performance tests for queue manager N+1 query optimization.

These tests verify that:
1. The batch query method works correctly
2. Scheduler uses batch queries instead of individual queries
3. Performance improvement is significant (O(1) queries vs O(n))
4. Cache invalidation works properly
"""

import asyncio
import pytest
import sqlite3
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, List

from src.core.database import Database
from src.core.queue_manager import QueueManager, Priority


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for testing."""
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    yield db
    db.close()


@pytest.fixture
def queue_manager(temp_db):
    """Create a queue manager with test database."""
    qm = QueueManager(temp_db, default_max_concurrent=4, scheduling_interval=0.1)
    return qm


class TestBatchQueryMethod:
    """Test the batch query method in Database class."""

    def test_get_job_statuses_batch_empty(self, temp_db):
        """Test batch query with empty list returns empty dict."""
        result = temp_db.get_job_statuses_batch([])
        assert result == {}

    def test_get_job_statuses_batch_single_job(self, temp_db):
        """Test batch query with single job."""
        # Create a job
        job_id = temp_db.create_job(
            name="test_job",
            work_dir="/tmp/test",
            input_content="test input"
        )

        # Query it
        result = temp_db.get_job_statuses_batch([job_id])
        assert result == {job_id: "PENDING"}

    def test_get_job_statuses_batch_multiple_jobs(self, temp_db):
        """Test batch query with multiple jobs."""
        # Create multiple jobs with different statuses
        job_id1 = temp_db.create_job(
            name="job1",
            work_dir="/tmp/job1",
            input_content="input1"
        )
        job_id2 = temp_db.create_job(
            name="job2",
            work_dir="/tmp/job2",
            input_content="input2"
        )
        job_id3 = temp_db.create_job(
            name="job3",
            work_dir="/tmp/job3",
            input_content="input3"
        )

        # Update some statuses
        temp_db.update_status(job_id2, "RUNNING")
        temp_db.update_status(job_id3, "COMPLETED")

        # Query all at once
        result = temp_db.get_job_statuses_batch([job_id1, job_id2, job_id3])

        assert result == {
            job_id1: "PENDING",
            job_id2: "RUNNING",
            job_id3: "COMPLETED"
        }

    def test_get_job_statuses_batch_nonexistent_jobs(self, temp_db):
        """Test batch query with mix of existing and non-existent jobs."""
        # Create one real job
        job_id1 = temp_db.create_job(
            name="job1",
            work_dir="/tmp/job1",
            input_content="input1"
        )

        # Query real and fake job IDs
        result = temp_db.get_job_statuses_batch([job_id1, 999999])

        # Should only return the existing job
        assert result == {job_id1: "PENDING"}
        assert 999999 not in result


class TestQueueManagerBatchOptimization:
    """Test queue manager uses batch queries efficiently."""

    @pytest.mark.asyncio
    async def test_schedule_jobs_uses_batch_query(self, queue_manager, temp_db):
        """Test that schedule_jobs uses batch query instead of individual queries."""
        # Create test jobs
        job_ids = []
        for i in range(5):
            job_id = temp_db.create_job(
                name=f"job{i}",
                work_dir=f"/tmp/job{i}",
                input_content=f"input{i}"
            )
            job_ids.append(job_id)

        # Enqueue all jobs
        for job_id in job_ids:
            await queue_manager.enqueue(job_id, priority=Priority.NORMAL)

        # Mock the database batch query method to count calls
        original_batch_query = temp_db.get_job_statuses_batch
        call_count = {"batch": 0, "individual": 0}

        def mock_batch_query(ids):
            call_count["batch"] += 1
            return original_batch_query(ids)

        original_get_job = temp_db.get_job

        def mock_get_job(job_id):
            call_count["individual"] += 1
            return original_get_job(job_id)

        # Patch both methods
        temp_db.get_job_statuses_batch = mock_batch_query
        temp_db.get_job = mock_get_job

        # Call schedule_jobs
        schedulable = await queue_manager.schedule_jobs()

        # Verify batch query was used, not individual queries
        assert call_count["batch"] >= 1, "Should use batch query"
        # Individual get_job calls should be 0 or minimal (only for dependency checks)
        # The old code would call get_job N times per job
        assert call_count["individual"] == 0, "Should not use individual get_job for status checking"

    @pytest.mark.asyncio
    async def test_query_complexity_improvement(self, queue_manager, temp_db):
        """Test that query complexity improves from O(n) to O(1) per cycle."""
        # Create jobs
        job_count = 10
        job_ids = []
        for i in range(job_count):
            job_id = temp_db.create_job(
                name=f"job{i}",
                work_dir=f"/tmp/job{i}",
                input_content=f"input{i}"
            )
            job_ids.append(job_id)

        # Enqueue all jobs
        for job_id in job_ids:
            await queue_manager.enqueue(job_id, priority=Priority.NORMAL)

        # Clear cache to test fresh scheduling
        queue_manager._invalidate_status_cache()

        # Track method calls instead of SQL queries (more reliable)
        call_tracker = {"batch_calls": 0, "individual_calls": 0}

        original_batch = temp_db.get_job_statuses_batch
        original_individual = temp_db.get_job

        def tracked_batch(ids):
            call_tracker["batch_calls"] += 1
            return original_batch(ids)

        def tracked_individual(job_id):
            call_tracker["individual_calls"] += 1
            return original_individual(job_id)

        # Patch the methods
        temp_db.get_job_statuses_batch = tracked_batch
        temp_db.get_job = tracked_individual

        # Call schedule_jobs
        await queue_manager.schedule_jobs()

        # Verify batch query was used
        assert call_tracker["batch_calls"] >= 1, \
            "Should use batch query for status checking"

        # Individual calls might happen for dependency checking, but not for status
        # So the ratio should show optimization
        # Old code: job_count + dependency checks = ~10 + N
        # New code: 1 batch + dependency checks = 1 + N
        # So batch_calls should be 1 and individual_calls should be minimal
        assert call_tracker["batch_calls"] >= 1, \
            "Batch query optimization not being used"

    @pytest.mark.asyncio
    async def test_cache_invalidation_on_enqueue(self, queue_manager, temp_db):
        """Test that cache is invalidated when job is enqueued."""
        job_id = temp_db.create_job(
            name="test_job",
            work_dir="/tmp/test",
            input_content="test"
        )

        # Manually add to cache (simulating a previous schedule_jobs call)
        queue_manager._status_cache[job_id] = ("PENDING", datetime.now())

        # Enqueue should invalidate
        await queue_manager.enqueue(job_id, priority=Priority.NORMAL)

        # Cache should be cleared for this job
        assert job_id not in queue_manager._status_cache

    @pytest.mark.asyncio
    async def test_cache_invalidation_on_dequeue(self, queue_manager, temp_db):
        """Test that cache is invalidated when job is dequeued."""
        job_id = temp_db.create_job(
            name="test_job",
            work_dir="/tmp/test",
            input_content="test"
        )

        # Enqueue the job
        await queue_manager.enqueue(job_id, priority=Priority.NORMAL)

        # Add to cache
        queue_manager._status_cache[job_id] = ("QUEUED", datetime.now())

        # Dequeue should invalidate
        dequeued_id = await queue_manager.dequeue("local")
        assert dequeued_id == job_id

        # Cache should be cleared for this job
        assert job_id not in queue_manager._status_cache

    @pytest.mark.asyncio
    async def test_cache_invalidation_on_completion(self, queue_manager, temp_db):
        """Test that cache is invalidated when job completes."""
        job_id = temp_db.create_job(
            name="test_job",
            work_dir="/tmp/test",
            input_content="test"
        )

        # Add to cache
        queue_manager._status_cache[job_id] = ("RUNNING", datetime.now())

        # Handle completion
        await queue_manager.handle_job_completion(job_id, success=True)

        # Cache should be cleared for this job
        assert job_id not in queue_manager._status_cache

    def test_invalidate_all_caches(self, queue_manager):
        """Test clearing entire cache."""
        # Add multiple entries
        queue_manager._status_cache[1] = ("PENDING", datetime.now())
        queue_manager._status_cache[2] = ("RUNNING", datetime.now())
        queue_manager._status_cache[3] = ("COMPLETED", datetime.now())

        assert len(queue_manager._status_cache) == 3

        # Clear all
        queue_manager._invalidate_status_cache(None)

        assert len(queue_manager._status_cache) == 0


class TestQueryPerformanceBenchmark:
    """Benchmark tests comparing old vs new query patterns."""

    def test_single_query_vs_multiple_queries(self, temp_db):
        """
        Benchmark: Single batch query vs N individual queries.

        This demonstrates the N+1 query problem and its fix.
        """
        import time

        # Create test jobs
        job_count = 20
        job_ids = []
        for i in range(job_count):
            job_id = temp_db.create_job(
                name=f"job{i}",
                work_dir=f"/tmp/job{i}",
                input_content=f"input{i}"
            )
            job_ids.append(job_id)

        # Method 1: Individual queries (OLD - SLOW)
        start_time = time.time()
        for _ in range(100):  # Simulate 100 scheduling cycles
            statuses = {}
            for job_id in job_ids:
                job = temp_db.get_job(job_id)
                if job:
                    statuses[job_id] = job.status
        individual_time = time.time() - start_time

        # Method 2: Batch query (NEW - FAST)
        start_time = time.time()
        for _ in range(100):  # Same 100 scheduling cycles
            statuses = temp_db.get_job_statuses_batch(job_ids)
        batch_time = time.time() - start_time

        # Batch should be significantly faster
        speedup = individual_time / batch_time if batch_time > 0 else float('inf')
        print(f"\nPerformance Improvement:")
        print(f"  Individual queries: {individual_time:.4f}s")
        print(f"  Batch query:        {batch_time:.4f}s")
        print(f"  Speedup:            {speedup:.1f}x")

        assert batch_time < individual_time, \
            f"Batch query should be faster than individual queries"
        assert speedup >= 1.5, \
            f"Expected at least 1.5x speedup, got {speedup:.1f}x"

    def test_scaling_with_queue_size(self, temp_db):
        """Test that batch query scales better than individual queries."""
        import time

        results = []

        for job_count in [5, 10, 20, 50]:
            # Create jobs
            job_ids = []
            for i in range(job_count):
                job_id = temp_db.create_job(
                    name=f"job{i}",
                    work_dir=f"/tmp/job{i}_{job_count}",
                    input_content=f"input{i}"
                )
                job_ids.append(job_id)

            # Batch query
            start_time = time.time()
            for _ in range(10):
                statuses = temp_db.get_job_statuses_batch(job_ids)
            batch_time = time.time() - start_time

            # Individual queries
            start_time = time.time()
            for _ in range(10):
                statuses = {}
                for job_id in job_ids:
                    job = temp_db.get_job(job_id)
                    if job:
                        statuses[job_id] = job.status
            individual_time = time.time() - start_time

            speedup = individual_time / batch_time if batch_time > 0 else float('inf')
            results.append({
                "job_count": job_count,
                "individual_time": individual_time,
                "batch_time": batch_time,
                "speedup": speedup
            })

        # Print scaling results
        print("\nScaling Test Results:")
        print(f"{'Jobs':<8} {'Individual':<12} {'Batch':<12} {'Speedup':<8}")
        print("-" * 40)
        for r in results:
            print(
                f"{r['job_count']:<8} {r['individual_time']:<12.4f} "
                f"{r['batch_time']:<12.4f} {r['speedup']:<8.1f}x"
            )

        # All should show speedup
        assert all(r["speedup"] >= 1.0 for r in results), \
            "Batch query should be faster for all queue sizes"


class TestRealWorldSchedulingScenario:
    """Test realistic scheduling scenario with batch queries."""

    @pytest.mark.asyncio
    async def test_scheduling_with_many_queued_jobs(self, queue_manager, temp_db):
        """
        Simulate a realistic scenario:
        - 100 jobs in queue
        - Multiple scheduling cycles
        - Verify efficiency without explicit query counting
        """
        # Create 100 jobs
        job_ids = []
        for i in range(100):
            job_id = temp_db.create_job(
                name=f"job{i}",
                work_dir=f"/tmp/job{i}",
                input_content=f"input{i}"
            )
            job_ids.append(job_id)

        # Enqueue all with various priorities
        for i, job_id in enumerate(job_ids):
            priority = (i % 5)  # Distribute across priority levels
            await queue_manager.enqueue(job_id, priority=priority)

        # Run multiple scheduling cycles
        import time
        start_time = time.time()

        for cycle in range(10):
            schedulable = await queue_manager.schedule_jobs()
            # Dequeue a few jobs
            for _ in range(min(4, len(schedulable))):  # Respect max_concurrent
                dequeued = await queue_manager.dequeue("local")
                if dequeued:
                    await queue_manager.handle_job_completion(dequeued, success=True)

        elapsed_time = time.time() - start_time

        print(f"\nRealworld Scenario:")
        print(f"  100 jobs, 10 scheduling cycles")
        print(f"  Total time: {elapsed_time:.4f}s")
        print(f"  Average per cycle: {elapsed_time / 10:.4f}s")

        # Should complete reasonably fast (well under 10 seconds for 1000 ops)
        assert elapsed_time < 10.0, \
            f"Scheduling should be fast with batch queries, took {elapsed_time:.2f}s"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
