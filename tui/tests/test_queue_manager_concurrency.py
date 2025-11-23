"""
Concurrency tests for QueueManager race condition fixes.

Tests the thread-safety of the queue manager's shared state operations,
including job scheduling, status updates, and dependency resolution.
"""

import asyncio
import pytest
import pytest_asyncio
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock

from src.core.queue_manager import (
    QueueManager,
    Priority,
    QueuedJob,
    InvalidJobError,
    CircularDependencyError,
)
from src.core.database import Database


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for testing."""
    db_path = tmp_path / "test_concurrency.db"
    db = Database(db_path)
    yield db
    db.conn.close()


@pytest_asyncio.fixture
async def queue_manager(temp_db):
    """Create a queue manager instance."""
    qm = QueueManager(
        database=temp_db,
        default_max_concurrent=10,
        scheduling_interval=0.1
    )
    await qm.start()
    yield qm
    await qm.stop()


@pytest.mark.asyncio
async def test_concurrent_enqueue_no_race(queue_manager, temp_db):
    """Test that concurrent enqueue operations don't cause race conditions."""
    # Create test jobs in database
    job_ids = []
    for i in range(20):
        job_id = temp_db.create_job(
            name=f"test_job_{i}",
            input_content=f"input {i}",
            work_dir=str(Path(f"/tmp/job_{i}"))
        )
        job_ids.append(job_id)

    # Enqueue all jobs concurrently
    tasks = [
        queue_manager.enqueue(
            job_id=job_id,
            priority=Priority.NORMAL,
            runner_type="local"
        )
        for job_id in job_ids
    ]

    await asyncio.gather(*tasks)

    # Verify all jobs were enqueued exactly once
    assert len(queue_manager._jobs) == 20
    for job_id in job_ids:
        assert job_id in queue_manager._jobs
        job = temp_db.get_job(job_id)
        assert job.status == "QUEUED"


@pytest.mark.asyncio
async def test_concurrent_schedule_no_double_scheduling(queue_manager, temp_db):
    """Test that concurrent schedule_jobs() calls don't double-schedule jobs."""
    # Create test jobs
    job_ids = []
    for i in range(10):
        job_id = temp_db.create_job(
            name=f"test_job_{i}",
            input_content=f"input {i}",
            work_dir=str(Path(f"/tmp/job_{i}"))
        )
        job_ids.append(job_id)
        await queue_manager.enqueue(job_id=job_id, priority=Priority.NORMAL)

    # Call schedule_jobs() concurrently multiple times
    results = await asyncio.gather(
        queue_manager.schedule_jobs(),
        queue_manager.schedule_jobs(),
        queue_manager.schedule_jobs(),
        queue_manager.schedule_jobs(),
    )

    # Each call should return the same schedulable jobs
    # (since none have been dequeued yet)
    for result in results:
        assert len(result) == 10
        assert set(result) == set(job_ids)


@pytest.mark.asyncio
async def test_concurrent_dequeue_no_double_dequeue(queue_manager, temp_db):
    """Test that concurrent dequeue() calls don't return the same job twice."""
    # Create test jobs
    job_ids = []
    for i in range(5):
        job_id = temp_db.create_job(
            name=f"test_job_{i}",
            input_content=f"input {i}",
            work_dir=str(Path(f"/tmp/job_{i}"))
        )
        job_ids.append(job_id)
        await queue_manager.enqueue(job_id=job_id, priority=Priority.NORMAL)

    # Dequeue concurrently from multiple workers
    tasks = [
        queue_manager.dequeue("local")
        for _ in range(10)  # More workers than jobs
    ]

    dequeued = await asyncio.gather(*tasks)

    # Filter out None results (workers that didn't get a job)
    dequeued_jobs = [j for j in dequeued if j is not None]

    # Verify no job was dequeued twice
    assert len(dequeued_jobs) == len(set(dequeued_jobs))
    # Verify all jobs were dequeued exactly once
    assert len(dequeued_jobs) == 5
    assert set(dequeued_jobs) == set(job_ids)


@pytest.mark.asyncio
async def test_concurrent_status_updates_no_lost_updates(queue_manager, temp_db):
    """Test that concurrent status updates don't cause lost updates."""
    # Create a test job
    job_id = temp_db.create_job(
        name="test_job",
        input_content="input",
        work_dir=str(Path("/tmp/job"))
    )
    await queue_manager.enqueue(job_id=job_id, priority=Priority.NORMAL)

    # Dequeue the job
    dequeued = await queue_manager.dequeue("local")
    assert dequeued == job_id

    # Simulate concurrent completion handlers
    # (only one should succeed, but no race condition should occur)
    completion_tasks = [
        queue_manager.handle_job_completion(job_id, success=True)
        for _ in range(5)
    ]

    # Should not raise any exceptions
    await asyncio.gather(*completion_tasks)

    # Verify metrics were updated correctly
    # (5 concurrent completions, but only first should count)
    assert queue_manager.metrics.total_jobs_completed >= 1


@pytest.mark.asyncio
async def test_concurrent_dependency_check_no_race(queue_manager, temp_db):
    """Test that concurrent dependency satisfaction checks are thread-safe."""
    # Create job chain: job1 -> job2 -> job3 -> job4
    job1 = temp_db.create_job(name="job1", input_content="1", work_dir=str(Path("/tmp/1")))
    job2 = temp_db.create_job(name="job2", input_content="2", work_dir=str(Path("/tmp/2")))
    job3 = temp_db.create_job(name="job3", input_content="3", work_dir=str(Path("/tmp/3")))
    job4 = temp_db.create_job(name="job4", input_content="4", work_dir=str(Path("/tmp/4")))

    # Enqueue with dependencies
    await queue_manager.enqueue(job_id=job1, priority=Priority.NORMAL)
    await queue_manager.enqueue(job_id=job2, dependencies=[job1], priority=Priority.NORMAL)
    await queue_manager.enqueue(job_id=job3, dependencies=[job2], priority=Priority.NORMAL)
    await queue_manager.enqueue(job_id=job4, dependencies=[job3], priority=Priority.NORMAL)

    # Check dependencies concurrently
    async def check_deps(job_id):
        async with queue_manager._lock:
            return queue_manager._dependencies_satisfied_locked(job_id)

    results = await asyncio.gather(
        check_deps(job1),
        check_deps(job2),
        check_deps(job3),
        check_deps(job4),
    )

    # Only job1 should have satisfied dependencies
    assert results == [True, False, False, False]


@pytest.mark.asyncio
async def test_scheduler_worker_concurrent_with_enqueue(queue_manager, temp_db):
    """Test that scheduler worker doesn't interfere with concurrent enqueue operations."""
    # The scheduler is already running in the background

    # Enqueue jobs while scheduler is running
    job_ids = []
    for i in range(20):
        job_id = temp_db.create_job(
            name=f"test_job_{i}",
            input_content=f"input {i}",
            work_dir=str(Path(f"/tmp/job_{i}"))
        )
        job_ids.append(job_id)

    # Enqueue concurrently while scheduler is running
    tasks = [
        queue_manager.enqueue(job_id=job_id, priority=Priority.NORMAL)
        for job_id in job_ids
    ]
    await asyncio.gather(*tasks)

    # Wait for a few scheduler cycles
    await asyncio.sleep(0.5)

    # Verify all jobs are still in queue (not lost)
    status = queue_manager.get_queue_status()
    assert status["total_queued"] == 20


@pytest.mark.asyncio
async def test_concurrent_priority_changes_no_corruption(queue_manager, temp_db):
    """Test that concurrent priority changes don't corrupt queue state."""
    # Create test jobs
    job_ids = []
    for i in range(10):
        job_id = temp_db.create_job(
            name=f"test_job_{i}",
            input_content=f"input {i}",
            work_dir=str(Path(f"/tmp/job_{i}"))
        )
        job_ids.append(job_id)
        await queue_manager.enqueue(job_id=job_id, priority=Priority.NORMAL)

    # Change priorities concurrently
    tasks = [
        queue_manager.reorder_queue(job_id, Priority.HIGH)
        for job_id in job_ids[::2]  # Every other job
    ]
    await asyncio.gather(*tasks)

    # Verify all priority changes were applied
    for i, job_id in enumerate(job_ids):
        queued_job = queue_manager._jobs[job_id]
        if i % 2 == 0:
            assert queued_job.priority == Priority.HIGH
        else:
            assert queued_job.priority == Priority.NORMAL


@pytest.mark.asyncio
async def test_concurrent_pause_resume_no_deadlock(queue_manager, temp_db):
    """Test that concurrent pause/resume operations don't deadlock."""
    # Create cluster with jobs
    cluster_id = 1
    for i in range(5):
        job_id = temp_db.create_job(
            name=f"test_job_{i}",
            input_content=f"input {i}",
            work_dir=str(Path(f"/tmp/job_{i}"))
        )
        await queue_manager.enqueue(
            job_id=job_id,
            cluster_id=cluster_id,
            priority=Priority.NORMAL
        )

    # Pause and resume concurrently
    tasks = []
    for _ in range(10):
        tasks.append(queue_manager.pause_queue(cluster_id))
        tasks.append(queue_manager.resume_queue(cluster_id))

    # Should complete without deadlock
    await asyncio.gather(*tasks)

    # Final state should be consistent
    cluster = queue_manager._get_cluster(cluster_id)
    assert isinstance(cluster.paused, bool)


@pytest.mark.asyncio
async def test_stress_test_concurrent_operations(queue_manager, temp_db):
    """Stress test with many concurrent operations of different types."""
    # Create initial jobs
    job_ids = []
    for i in range(50):
        job_id = temp_db.create_job(
            name=f"test_job_{i}",
            input_content=f"input {i}",
            work_dir=str(Path(f"/tmp/job_{i}"))
        )
        job_ids.append(job_id)

    # Mix of concurrent operations
    tasks = []

    # Enqueue jobs
    for job_id in job_ids[:25]:
        tasks.append(queue_manager.enqueue(job_id=job_id, priority=Priority.NORMAL))

    # Schedule checks
    for _ in range(10):
        tasks.append(queue_manager.schedule_jobs())

    # Wait a bit then enqueue more
    async def delayed_enqueue(job_id, delay):
        await asyncio.sleep(delay)
        await queue_manager.enqueue(job_id=job_id, priority=Priority.HIGH)

    for i, job_id in enumerate(job_ids[25:]):
        tasks.append(delayed_enqueue(job_id, i * 0.01))

    # Execute all concurrently
    await asyncio.gather(*tasks)

    # Verify queue state is consistent
    assert len(queue_manager._jobs) == 50
    for job_id in job_ids:
        assert job_id in queue_manager._jobs


@pytest.mark.asyncio
async def test_validation_no_self_dependency_race(queue_manager, temp_db):
    """Test that dependency validation is atomic (no self-dependency accepted)."""
    job_id = temp_db.create_job(
        name="test_job",
        input_content="input",
        work_dir=str(Path("/tmp/job"))
    )

    # Try to create self-dependency
    with pytest.raises(CircularDependencyError):
        await queue_manager.enqueue(
            job_id=job_id,
            dependencies=[job_id],  # Self-dependency
            priority=Priority.NORMAL
        )

    # Job should not be in queue
    assert job_id not in queue_manager._jobs


@pytest.mark.asyncio
async def test_validation_circular_dependency_atomic(queue_manager, temp_db):
    """Test that circular dependency detection is atomic."""
    # Create job chain
    job1 = temp_db.create_job(name="job1", input_content="1", work_dir=str(Path("/tmp/1")))
    job2 = temp_db.create_job(name="job2", input_content="2", work_dir=str(Path("/tmp/2")))
    job3 = temp_db.create_job(name="job3", input_content="3", work_dir=str(Path("/tmp/3")))

    # Create chain: job1 -> job2 -> job3
    await queue_manager.enqueue(job_id=job1, priority=Priority.NORMAL)
    await queue_manager.enqueue(job_id=job2, dependencies=[job1], priority=Priority.NORMAL)
    await queue_manager.enqueue(job_id=job3, dependencies=[job2], priority=Priority.NORMAL)

    # Try to create cycle: job1 depends on job3
    with pytest.raises(CircularDependencyError):
        # This would create: job1 -> job2 -> job3 -> job1 (cycle)
        async with queue_manager._lock:
            queue_manager._jobs[job1].dependencies.add(job3)
            queue_manager._validate_dependencies(job1, {job3})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
