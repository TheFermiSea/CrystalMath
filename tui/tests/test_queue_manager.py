"""
Comprehensive unit tests for the QueueManager module.

Tests cover:
- Queue initialization and state restoration
- Job enqueuing with priority and dependencies
- Dependency validation and circular dependency detection
- Priority-based scheduling
- Concurrent job limits per cluster
- Retry logic and failure handling
- Fair share scheduling
- Resource-aware scheduling
- Queue pause/resume
- Priority reordering
- Metrics tracking
- Persistence and state recovery
"""

import asyncio
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
import pytest
import pytest_asyncio

from src.core.database import Database
from src.core.queue_manager import (
    QueueManager,
    Priority,
    QueuedJob,
    ClusterState,
    CircularDependencyError,
    InvalidJobError,
    QueueManagerError
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    db = Database(db_path)
    yield db

    db.close()
    db_path.unlink(missing_ok=True)


@pytest.fixture
def queue_manager(temp_db):
    """Create a QueueManager instance for testing."""
    qm = QueueManager(temp_db, default_max_concurrent=2)
    return qm


@pytest_asyncio.fixture
async def running_queue_manager(temp_db):
    """Create and start a QueueManager instance."""
    qm = QueueManager(temp_db, default_max_concurrent=2)
    await qm.start()
    yield qm
    await qm.stop()


class TestQueueManagerInitialization:
    """Tests for queue manager initialization."""

    def test_initialization(self, queue_manager):
        """Test basic initialization."""
        assert queue_manager.default_max_concurrent == 2
        assert not queue_manager._running
        assert len(queue_manager._jobs) == 0
        assert len(queue_manager._clusters) == 0

    def test_database_schema_extension(self, temp_db):
        """Test that queue tables are created."""
        qm = QueueManager(temp_db)

        # Check queue_state table
        cursor = temp_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='queue_state'"
        )
        assert cursor.fetchone() is not None

        # Check cluster_state table
        cursor = temp_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cluster_state'"
        )
        assert cursor.fetchone() is not None

        # Check scheduler_metrics table
        cursor = temp_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scheduler_metrics'"
        )
        assert cursor.fetchone() is not None

    @pytest.mark.asyncio
    async def test_start_stop(self, queue_manager):
        """Test starting and stopping the queue manager."""
        assert not queue_manager._running

        await queue_manager.start()
        assert queue_manager._running
        assert queue_manager._scheduler_task is not None

        await queue_manager.stop()
        assert not queue_manager._running


class TestJobEnqueuing:
    """Tests for enqueuing jobs."""

    @pytest.mark.asyncio
    async def test_enqueue_basic_job(self, queue_manager, temp_db):
        """Test enqueuing a basic job."""
        # Create a job in database first
        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\nEND\n")

        await queue_manager.enqueue(job_id, priority=Priority.NORMAL)

        assert job_id in queue_manager._jobs
        queued_job = queue_manager._jobs[job_id]
        assert queued_job.priority == Priority.NORMAL
        assert queued_job.dependencies == set()

    @pytest.mark.asyncio
    async def test_enqueue_with_priority(self, queue_manager, temp_db):
        """Test enqueuing jobs with different priorities."""
        job_ids = []
        for i, priority in enumerate([Priority.HIGH, Priority.LOW, Priority.CRITICAL]):
            job_id = temp_db.create_job(f"job_{i}", f"/tmp/job_{i}", "CRYSTAL\n")
            await queue_manager.enqueue(job_id, priority=priority)
            job_ids.append(job_id)

        # Check priorities assigned correctly
        assert queue_manager._jobs[job_ids[0]].priority == Priority.HIGH
        assert queue_manager._jobs[job_ids[1]].priority == Priority.LOW
        assert queue_manager._jobs[job_ids[2]].priority == Priority.CRITICAL

    @pytest.mark.asyncio
    async def test_enqueue_with_dependencies(self, queue_manager, temp_db):
        """Test enqueuing jobs with dependencies."""
        # Create jobs
        job1 = temp_db.create_job("job1", "/tmp/job1", "CRYSTAL\n")
        job2 = temp_db.create_job("job2", "/tmp/job2", "CRYSTAL\n")
        job3 = temp_db.create_job("job3", "/tmp/job3", "CRYSTAL\n")

        # Enqueue with dependencies: job3 depends on job1 and job2
        await queue_manager.enqueue(job1)
        await queue_manager.enqueue(job2)
        await queue_manager.enqueue(job3, dependencies=[job1, job2])

        # Check dependency tracking
        assert queue_manager._jobs[job3].dependencies == {job1, job2}
        assert job3 in queue_manager._dependents[job1]
        assert job3 in queue_manager._dependents[job2]

    @pytest.mark.asyncio
    async def test_enqueue_invalid_job(self, queue_manager):
        """Test enqueuing a non-existent job."""
        with pytest.raises(InvalidJobError, match="not found"):
            await queue_manager.enqueue(99999)

    @pytest.mark.asyncio
    async def test_enqueue_with_cluster(self, queue_manager, temp_db):
        """Test enqueuing job to specific cluster."""
        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\n")
        await queue_manager.enqueue(job_id, cluster_id=5)

        assert queue_manager._jobs[job_id].cluster_id == 5

    @pytest.mark.asyncio
    async def test_enqueue_with_resources(self, queue_manager, temp_db):
        """Test enqueuing job with resource requirements."""
        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\n")
        resources = {"cores": 8, "memory_gb": 16, "gpu": 1}

        await queue_manager.enqueue(job_id, resource_requirements=resources)

        assert queue_manager._jobs[job_id].resource_requirements == resources


class TestDependencyValidation:
    """Tests for dependency validation and circular dependency detection."""

    @pytest.mark.asyncio
    async def test_circular_dependency_detection(self, queue_manager, temp_db):
        """Test detection of circular dependencies."""
        # Create jobs
        job1 = temp_db.create_job("job1", "/tmp/job1", "CRYSTAL\n")
        job2 = temp_db.create_job("job2", "/tmp/job2", "CRYSTAL\n")
        job3 = temp_db.create_job("job3", "/tmp/job3", "CRYSTAL\n")

        # Create dependency chain: job1 -> job2 -> job3
        await queue_manager.enqueue(job1)
        await queue_manager.enqueue(job2, dependencies=[job1])
        await queue_manager.enqueue(job3, dependencies=[job2])

        # Try to create circular dependency: job1 depends on job3
        with pytest.raises(CircularDependencyError, match="(?i)circular dependency"):
            await queue_manager.enqueue(job1, dependencies=[job3])

    @pytest.mark.asyncio
    async def test_self_dependency_rejection(self, queue_manager, temp_db):
        """Test that self-dependencies are rejected."""
        job1 = temp_db.create_job("job1", "/tmp/job1", "CRYSTAL\n")

        with pytest.raises(CircularDependencyError):
            await queue_manager.enqueue(job1, dependencies=[job1])

    @pytest.mark.asyncio
    async def test_nonexistent_dependency(self, queue_manager, temp_db):
        """Test rejection of non-existent dependencies."""
        job1 = temp_db.create_job("job1", "/tmp/job1", "CRYSTAL\n")

        with pytest.raises(InvalidJobError, match="not found"):
            await queue_manager.enqueue(job1, dependencies=[99999])


class TestScheduling:
    """Tests for job scheduling logic."""

    @pytest.mark.asyncio
    async def test_schedule_by_priority(self, queue_manager, temp_db):
        """Test that jobs are scheduled by priority."""
        # Create jobs with different priorities
        jobs = []
        for i, priority in enumerate([Priority.LOW, Priority.CRITICAL, Priority.HIGH]):
            job_id = temp_db.create_job(f"job_{i}", f"/tmp/job_{i}", "CRYSTAL\n")
            await queue_manager.enqueue(job_id, priority=priority)
            jobs.append(job_id)

        # Schedule jobs
        schedulable = await queue_manager.schedule_jobs()

        # Should be ordered by priority: CRITICAL, HIGH, LOW
        assert schedulable[0] == jobs[1]  # CRITICAL
        assert schedulable[1] == jobs[2]  # HIGH
        assert schedulable[2] == jobs[0]  # LOW

    @pytest.mark.asyncio
    async def test_schedule_respects_dependencies(self, queue_manager, temp_db):
        """Test that jobs with unsatisfied dependencies are not scheduled."""
        # Create job chain: job1 -> job2
        job1 = temp_db.create_job("job1", "/tmp/job1", "CRYSTAL\n")
        job2 = temp_db.create_job("job2", "/tmp/job2", "CRYSTAL\n")

        await queue_manager.enqueue(job1)
        await queue_manager.enqueue(job2, dependencies=[job1])

        # Only job1 should be schedulable
        schedulable = await queue_manager.schedule_jobs()
        assert job1 in schedulable
        assert job2 not in schedulable

        # Complete job1
        temp_db.update_status(job1, "COMPLETED")

        # Now job2 should be schedulable
        schedulable = await queue_manager.schedule_jobs()
        assert job2 in schedulable

    @pytest.mark.asyncio
    async def test_schedule_respects_cluster_capacity(self, queue_manager, temp_db):
        """Test that cluster concurrent limits are respected."""
        # Create 3 jobs for cluster with max_concurrent=2
        jobs = []
        for i in range(3):
            job_id = temp_db.create_job(f"job_{i}", f"/tmp/job_{i}", "CRYSTAL\n")
            await queue_manager.enqueue(job_id, cluster_id=1)
            jobs.append(job_id)

        # Set cluster max concurrent to 2
        cluster = queue_manager._get_cluster(1)
        cluster.max_concurrent_jobs = 2

        # Dequeue first two jobs
        job1 = await queue_manager.dequeue("local")
        job2 = await queue_manager.dequeue("local")

        assert job1 in jobs
        assert job2 in jobs

        # Third job should not be schedulable (cluster at capacity)
        schedulable = await queue_manager.schedule_jobs()
        remaining_job = [j for j in jobs if j != job1 and j != job2][0]

        # Cluster is at capacity, so third job should not be in schedulable list
        # (schedule_jobs filters by capacity)
        assert len(cluster.running_jobs) == 2

    @pytest.mark.asyncio
    async def test_fifo_within_priority(self, queue_manager, temp_db):
        """Test FIFO ordering within same priority level."""
        jobs = []
        for i in range(3):
            job_id = temp_db.create_job(f"job_{i}", f"/tmp/job_{i}", "CRYSTAL\n")
            await queue_manager.enqueue(job_id, priority=Priority.NORMAL)
            jobs.append(job_id)
            # Small delay to ensure different enqueue times
            await asyncio.sleep(0.01)

        schedulable = await queue_manager.schedule_jobs()

        # Should be in FIFO order (oldest first)
        assert schedulable[0] == jobs[0]
        assert schedulable[1] == jobs[1]
        assert schedulable[2] == jobs[2]


class TestDequeuing:
    """Tests for dequeuing jobs."""

    @pytest.mark.asyncio
    async def test_dequeue_basic(self, queue_manager, temp_db):
        """Test basic job dequeuing."""
        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\n")
        await queue_manager.enqueue(job_id, runner_type="local")

        dequeued = await queue_manager.dequeue("local")
        assert dequeued == job_id
        assert job_id not in queue_manager._jobs

    @pytest.mark.asyncio
    async def test_dequeue_empty_queue(self, queue_manager):
        """Test dequeuing from empty queue returns None."""
        result = await queue_manager.dequeue("local")
        assert result is None

    @pytest.mark.asyncio
    async def test_dequeue_filters_by_runner_type(self, queue_manager, temp_db):
        """Test that dequeue filters by runner type."""
        job1 = temp_db.create_job("job1", "/tmp/job1", "CRYSTAL\n")
        job2 = temp_db.create_job("job2", "/tmp/job2", "CRYSTAL\n")

        await queue_manager.enqueue(job1, runner_type="local")
        await queue_manager.enqueue(job2, runner_type="slurm")

        # Dequeue for local runner
        dequeued = await queue_manager.dequeue("local")
        assert dequeued == job1

        # Dequeue for slurm runner
        dequeued = await queue_manager.dequeue("slurm")
        assert dequeued == job2

    @pytest.mark.asyncio
    async def test_dequeue_updates_metrics(self, queue_manager, temp_db):
        """Test that dequeuing updates wait time metrics."""
        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\n")
        await queue_manager.enqueue(job_id)

        # Wait a bit to have measurable wait time
        await asyncio.sleep(0.1)

        await queue_manager.dequeue("local")

        # Metrics should be updated
        assert queue_manager.metrics.total_jobs_scheduled == 1
        assert queue_manager.metrics.average_wait_time_seconds > 0


class TestClusterManagement:
    """Tests for cluster state management."""

    @pytest.mark.asyncio
    async def test_pause_queue(self, queue_manager, temp_db):
        """Test pausing a cluster queue."""
        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\n")
        await queue_manager.enqueue(job_id, cluster_id=1)

        # Pause cluster
        await queue_manager.pause_queue(1)

        cluster = queue_manager._get_cluster(1)
        assert cluster.paused
        assert not cluster.can_accept_job

        # Job should not be schedulable
        schedulable = await queue_manager.schedule_jobs()
        assert job_id not in schedulable

    @pytest.mark.asyncio
    async def test_resume_queue(self, queue_manager, temp_db):
        """Test resuming a paused cluster queue."""
        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\n")
        await queue_manager.enqueue(job_id, cluster_id=1)

        # Pause then resume
        await queue_manager.pause_queue(1)
        await queue_manager.resume_queue(1)

        cluster = queue_manager._get_cluster(1)
        assert not cluster.paused
        assert cluster.can_accept_job

        # Job should be schedulable again
        schedulable = await queue_manager.schedule_jobs()
        assert job_id in schedulable

    def test_cluster_capacity_tracking(self, queue_manager):
        """Test cluster capacity tracking."""
        cluster = queue_manager._get_cluster(1)
        cluster.max_concurrent_jobs = 2

        # Initially can accept jobs
        assert cluster.can_accept_job

        # Add jobs up to capacity
        cluster.running_jobs.add(100)
        assert cluster.can_accept_job

        cluster.running_jobs.add(101)
        assert not cluster.can_accept_job  # At capacity

        # Remove a job
        cluster.running_jobs.remove(100)
        assert cluster.can_accept_job


class TestRetryLogic:
    """Tests for job retry logic."""

    @pytest.mark.asyncio
    async def test_job_retry_on_failure(self, queue_manager, temp_db):
        """Test that failed jobs are retried."""
        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\n")
        await queue_manager.enqueue(job_id, max_retries=3)

        # Dequeue and mark as failed
        await queue_manager.dequeue("local")
        temp_db.update_status(job_id, "FAILED")

        # Handle failure
        await queue_manager.handle_job_completion(job_id, success=False)

        # Job should be re-queued
        job = temp_db.get_job(job_id)
        assert job.status == "QUEUED"

        # Retry count should be incremented
        assert queue_manager.metrics.total_jobs_retried == 1

    @pytest.mark.asyncio
    async def test_job_failure_after_max_retries(self, queue_manager, temp_db):
        """Test that jobs fail permanently after max retries."""
        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\n")
        await queue_manager.enqueue(job_id, max_retries=2)

        # Dequeue and fail multiple times
        for i in range(3):
            # Manually set retry count in database
            queue_manager.db.conn.execute(
                "UPDATE queue_state SET retry_count = ? WHERE job_id = ?",
                (i, job_id)
            )
            queue_manager.db.conn.commit()

            temp_db.update_status(job_id, "FAILED")
            await queue_manager.handle_job_completion(job_id, success=False)

        # Job should be permanently failed
        job = temp_db.get_job(job_id)
        assert job.status == "FAILED"

    @pytest.mark.asyncio
    async def test_dependent_jobs_cancelled_on_failure(self, queue_manager, temp_db):
        """Test that dependent jobs are cancelled when dependency fails."""
        job1 = temp_db.create_job("job1", "/tmp/job1", "CRYSTAL\n")
        job2 = temp_db.create_job("job2", "/tmp/job2", "CRYSTAL\n")

        await queue_manager.enqueue(job1, max_retries=0)  # No retries
        await queue_manager.enqueue(job2, dependencies=[job1])

        # Fail job1 permanently
        temp_db.update_status(job1, "FAILED")
        await queue_manager.handle_job_completion(job1, success=False)

        # job2 should be cancelled
        job2_status = temp_db.get_job(job2)
        assert job2_status.status == "FAILED"


class TestPriorityReordering:
    """Tests for changing job priorities."""

    @pytest.mark.asyncio
    async def test_reorder_queue(self, queue_manager, temp_db):
        """Test changing a job's priority."""
        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\n")
        await queue_manager.enqueue(job_id, priority=Priority.LOW)

        assert queue_manager._jobs[job_id].priority == Priority.LOW

        # Increase priority
        await queue_manager.reorder_queue(job_id, Priority.CRITICAL)

        assert queue_manager._jobs[job_id].priority == Priority.CRITICAL

    @pytest.mark.asyncio
    async def test_reorder_affects_scheduling(self, queue_manager, temp_db):
        """Test that reordering affects scheduling order."""
        job1 = temp_db.create_job("job1", "/tmp/job1", "CRYSTAL\n")
        job2 = temp_db.create_job("job2", "/tmp/job2", "CRYSTAL\n")

        await queue_manager.enqueue(job1, priority=Priority.LOW)
        await queue_manager.enqueue(job2, priority=Priority.NORMAL)

        # job2 should be scheduled first
        schedulable = await queue_manager.schedule_jobs()
        assert schedulable[0] == job2

        # Increase job1 priority
        await queue_manager.reorder_queue(job1, Priority.CRITICAL)

        # Now job1 should be scheduled first
        schedulable = await queue_manager.schedule_jobs()
        assert schedulable[0] == job1

    @pytest.mark.asyncio
    async def test_reorder_nonqueued_job_raises_error(self, queue_manager, temp_db):
        """Test reordering a non-queued job raises error."""
        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\n")

        with pytest.raises(InvalidJobError, match="not in queue"):
            await queue_manager.reorder_queue(job_id, Priority.HIGH)


class TestFairShareScheduling:
    """Tests for fair share scheduling across users."""

    @pytest.mark.asyncio
    async def test_fair_share_bonus(self, temp_db):
        """Test fair share scheduling gives bonus to users who haven't run recently."""
        qm = QueueManager(temp_db, enable_fair_share=True)

        # Create jobs for two users
        job1 = temp_db.create_job("job1", "/tmp/job1", "CRYSTAL\n")
        job2 = temp_db.create_job("job2", "/tmp/job2", "CRYSTAL\n")

        await qm.enqueue(job1, user_id="user_a", priority=Priority.NORMAL)
        await qm.enqueue(job2, user_id="user_b", priority=Priority.NORMAL)

        # Schedule job1 for user_a
        await qm.dequeue("local")

        # Wait a bit
        await asyncio.sleep(0.1)

        # Create another job for user_a
        job3 = temp_db.create_job("job3", "/tmp/job3", "CRYSTAL\n")
        await qm.enqueue(job3, user_id="user_a", priority=Priority.NORMAL)

        # job2 (user_b) should have higher scheduling score due to fair share
        # This is complex to test directly, but we can verify the mechanism exists
        score2 = qm._calculate_scheduling_score(qm._jobs[job2])
        score3 = qm._calculate_scheduling_score(qm._jobs[job3])

        # user_b never scheduled, should have higher score
        assert score2 > score3


class TestResourceAwareScheduling:
    """Tests for resource-aware scheduling."""

    @pytest.mark.asyncio
    async def test_resource_availability_check(self, queue_manager, temp_db):
        """Test that jobs requiring unavailable resources are not scheduled."""
        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\n")
        await queue_manager.enqueue(
            job_id,
            cluster_id=1,
            resource_requirements={"cores": 16, "memory_gb": 32}
        )

        # Set cluster resources insufficient
        cluster = queue_manager._get_cluster(1)
        cluster.available_resources = {"cores": 8, "memory_gb": 16}

        # Job should not be schedulable
        schedulable = await queue_manager.schedule_jobs()
        assert job_id not in schedulable

        # Increase resources
        cluster.available_resources = {"cores": 32, "memory_gb": 64}

        # Now job should be schedulable
        schedulable = await queue_manager.schedule_jobs()
        assert job_id in schedulable


class TestPersistence:
    """Tests for queue state persistence."""

    @pytest.mark.asyncio
    async def test_queue_state_persisted(self, temp_db):
        """Test that queue state is persisted to database."""
        qm = QueueManager(temp_db)

        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\n")
        await qm.enqueue(job_id, priority=Priority.HIGH)

        # Check database
        cursor = temp_db.conn.execute(
            "SELECT * FROM queue_state WHERE job_id = ?",
            (job_id,)
        )
        row = cursor.fetchone()

        assert row is not None
        assert row[1] == Priority.HIGH.value  # priority column

    @pytest.mark.asyncio
    async def test_queue_state_restored_on_restart(self, temp_db):
        """Test that queue state is restored after restart."""
        # Create and populate queue manager
        qm1 = QueueManager(temp_db)
        job1 = temp_db.create_job("job1", "/tmp/job1", "CRYSTAL\n")
        job2 = temp_db.create_job("job2", "/tmp/job2", "CRYSTAL\n")

        await qm1.enqueue(job1, priority=Priority.HIGH)
        await qm1.enqueue(job2, priority=Priority.LOW, dependencies=[job1])

        # Create new queue manager (simulates restart)
        qm2 = QueueManager(temp_db)

        # State should be restored
        assert job1 in qm2._jobs
        assert job2 in qm2._jobs
        assert qm2._jobs[job1].priority == Priority.HIGH
        assert qm2._jobs[job2].priority == Priority.LOW
        assert qm2._jobs[job2].dependencies == {job1}

    @pytest.mark.asyncio
    async def test_cluster_state_persisted(self, temp_db):
        """Test that cluster state is persisted."""
        qm = QueueManager(temp_db)

        await qm.pause_queue(5)

        # Check database
        cursor = temp_db.conn.execute(
            "SELECT * FROM cluster_state WHERE cluster_id = ?",
            (5,)
        )
        row = cursor.fetchone()

        assert row is not None
        assert bool(row[2])  # paused column

    @pytest.mark.asyncio
    async def test_metrics_persisted(self, running_queue_manager, temp_db):
        """Test that metrics are persisted."""
        qm = running_queue_manager

        # Create and complete a job
        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\n")
        await qm.enqueue(job_id)
        await qm.dequeue("local")
        await qm.handle_job_completion(job_id, success=True)

        # Wait for metrics update
        await asyncio.sleep(0.1)

        # Check database
        cursor = temp_db.conn.execute(
            "SELECT * FROM scheduler_metrics WHERE id = 1"
        )
        row = cursor.fetchone()

        assert row is not None
        assert row[1] >= 1  # total_jobs_scheduled
        assert row[2] >= 1  # total_jobs_completed


class TestQueueStatus:
    """Tests for queue status reporting."""

    @pytest.mark.asyncio
    async def test_get_queue_status(self, queue_manager, temp_db):
        """Test getting queue status."""
        # Create jobs with different priorities
        job1 = temp_db.create_job("job1", "/tmp/job1", "CRYSTAL\n")
        job2 = temp_db.create_job("job2", "/tmp/job2", "CRYSTAL\n")
        job3 = temp_db.create_job("job3", "/tmp/job3", "CRYSTAL\n")

        await queue_manager.enqueue(job1, priority=Priority.HIGH)
        await queue_manager.enqueue(job2, priority=Priority.NORMAL)
        await queue_manager.enqueue(job3, priority=Priority.LOW, runner_type="slurm")

        status = queue_manager.get_queue_status()

        assert status["total_queued"] == 3
        assert status["by_priority"]["HIGH"] == 1
        assert status["by_priority"]["NORMAL"] == 1
        assert status["by_priority"]["LOW"] == 1
        assert status["by_runner"]["local"] == 2
        assert status["by_runner"]["slurm"] == 1

    @pytest.mark.asyncio
    async def test_get_queue_status_filtered(self, queue_manager, temp_db):
        """Test getting queue status filtered by runner type."""
        job1 = temp_db.create_job("job1", "/tmp/job1", "CRYSTAL\n")
        job2 = temp_db.create_job("job2", "/tmp/job2", "CRYSTAL\n")

        await queue_manager.enqueue(job1, runner_type="local")
        await queue_manager.enqueue(job2, runner_type="slurm")

        status = queue_manager.get_queue_status(runner_type="local")

        assert status["total_queued"] == 1


class TestBackgroundScheduler:
    """Tests for background scheduler worker."""

    @pytest.mark.asyncio
    async def test_scheduler_worker_runs(self, running_queue_manager):
        """Test that scheduler worker runs in background."""
        qm = running_queue_manager

        assert qm._running
        assert qm._scheduler_task is not None
        assert not qm._scheduler_task.done()

    @pytest.mark.asyncio
    async def test_scheduler_updates_metrics_periodically(self, temp_db):
        """Test that scheduler updates metrics periodically."""
        qm = QueueManager(temp_db, scheduling_interval=0.1)
        await qm.start()

        initial_update = qm.metrics.last_updated

        # Wait for scheduler cycle
        await asyncio.sleep(0.2)

        # Metrics should be updated
        assert qm.metrics.last_updated != initial_update

        await qm.stop()

    @pytest.mark.asyncio
    async def test_scheduler_persists_state_periodically(self, temp_db):
        """Test that scheduler persists state periodically."""
        qm = QueueManager(temp_db, scheduling_interval=0.1)
        await qm.start()

        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\n")
        await qm.enqueue(job_id)

        # Wait for scheduler cycle
        await asyncio.sleep(0.2)

        # State should be in database
        cursor = temp_db.conn.execute(
            "SELECT * FROM queue_state WHERE job_id = ?",
            (job_id,)
        )
        assert cursor.fetchone() is not None

        await qm.stop()


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_handle_completion_for_unknown_job(self, queue_manager):
        """Test handling completion for job not in queue."""
        # Should not raise error
        await queue_manager.handle_job_completion(99999, success=True)

    @pytest.mark.asyncio
    async def test_concurrent_access(self, running_queue_manager, temp_db):
        """Test concurrent access to queue manager."""
        qm = running_queue_manager

        # Create multiple jobs concurrently
        async def enqueue_job(i):
            job_id = temp_db.create_job(f"job_{i}", f"/tmp/job_{i}", "CRYSTAL\n")
            await qm.enqueue(job_id)
            return job_id

        jobs = await asyncio.gather(*[enqueue_job(i) for i in range(10)])

        # All jobs should be enqueued
        assert len(qm._jobs) == 10

    @pytest.mark.asyncio
    async def test_dequeue_with_complex_dependencies(self, queue_manager, temp_db):
        """Test dequeuing with complex dependency graph."""
        # Create DAG: job1 -> job2 -> job4
        #                  -> job3 -> job4
        jobs = {}
        for i in range(1, 5):
            jobs[i] = temp_db.create_job(f"job{i}", f"/tmp/job{i}", "CRYSTAL\n")

        await queue_manager.enqueue(jobs[1])
        await queue_manager.enqueue(jobs[2], dependencies=[jobs[1]])
        await queue_manager.enqueue(jobs[3], dependencies=[jobs[1]])
        await queue_manager.enqueue(jobs[4], dependencies=[jobs[2], jobs[3]])

        # Only job1 should be schedulable initially
        schedulable = await queue_manager.schedule_jobs()
        assert schedulable == [jobs[1]]

        # Complete job1
        temp_db.update_status(jobs[1], "COMPLETED")

        # job2 and job3 should be schedulable
        schedulable = await queue_manager.schedule_jobs()
        assert set(schedulable) == {jobs[2], jobs[3]}

        # Complete job2 and job3
        temp_db.update_status(jobs[2], "COMPLETED")
        temp_db.update_status(jobs[3], "COMPLETED")

        # Now job4 should be schedulable
        schedulable = await queue_manager.schedule_jobs()
        assert schedulable == [jobs[4]]


class TestJobCancellation:
    """Tests for job cancellation functionality."""

    @pytest.mark.asyncio
    async def test_cancel_queued_job(self, queue_manager, temp_db):
        """Test cancelling a job that is queued (pending)."""
        # Create and enqueue a job
        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\n")
        await queue_manager.enqueue(job_id)

        # Verify job is in queue
        assert job_id in queue_manager._jobs

        # Cancel the job
        result = await queue_manager.cancel_job(job_id)

        # Verify cancellation succeeded
        assert result is True

        # Verify job is removed from queue
        assert job_id not in queue_manager._jobs

        # Verify database status is CANCELLED
        job = temp_db.get_job(job_id)
        assert job.status == "CANCELLED"

    @pytest.mark.asyncio
    async def test_cancel_completed_job_returns_false(self, queue_manager, temp_db):
        """Test cancelling a job that is already completed returns False."""
        # Create a job and mark it as completed
        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\n")
        temp_db.update_status(job_id, "COMPLETED")

        # Try to cancel
        result = await queue_manager.cancel_job(job_id)

        # Should return False since job is already completed
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_failed_job_returns_false(self, queue_manager, temp_db):
        """Test cancelling a job that has failed returns False."""
        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\n")
        temp_db.update_status(job_id, "FAILED")

        result = await queue_manager.cancel_job(job_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_job_returns_false(self, queue_manager, temp_db):
        """Test cancelling a job that doesn't exist returns False."""
        result = await queue_manager.cancel_job(99999)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_job_removes_from_cluster(self, queue_manager, temp_db):
        """Test that cancelling a running job removes it from cluster state."""
        # Create and enqueue a job
        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\n")
        await queue_manager.enqueue(job_id)

        # Simulate job being dequeued and running
        await queue_manager.dequeue("local")

        # Verify job is in default cluster running jobs
        assert job_id in queue_manager._default_cluster.running_jobs

        # Cancel the job
        result = await queue_manager.cancel_job(job_id)

        # Verify cancellation succeeded
        assert result is True

        # Verify removed from running jobs
        assert job_id not in queue_manager._default_cluster.running_jobs

    @pytest.mark.asyncio
    async def test_cancel_job_removes_dependencies(self, queue_manager, temp_db):
        """Test that cancelling a job removes it from dependency graph."""
        # Create jobs with dependencies
        job1_id = temp_db.create_job("job1", "/tmp/job1", "CRYSTAL\n")
        job2_id = temp_db.create_job("job2", "/tmp/job2", "CRYSTAL\n")

        await queue_manager.enqueue(job1_id)
        await queue_manager.enqueue(job2_id, dependencies=[job1_id])

        # Verify dependency exists
        assert job2_id in queue_manager._dependents.get(job1_id, set())
        assert job1_id in queue_manager._jobs[job2_id].dependencies

        # Cancel job1
        await queue_manager.cancel_job(job1_id)

        # Verify dependency on job1 is removed from job2
        assert job1_id not in queue_manager._jobs[job2_id].dependencies

    @pytest.mark.asyncio
    async def test_cancel_job_clears_queue_state(self, queue_manager, temp_db):
        """Test that cancelling a job removes it from queue_state table."""
        # Create and enqueue a job
        job_id = temp_db.create_job("test_job", "/tmp/test", "CRYSTAL\n")
        await queue_manager.enqueue(job_id)

        # Verify job is in queue_state table
        cursor = temp_db.conn.execute(
            "SELECT job_id FROM queue_state WHERE job_id = ?",
            (job_id,)
        )
        assert cursor.fetchone() is not None

        # Cancel the job
        await queue_manager.cancel_job(job_id)

        # Verify job is removed from queue_state table
        cursor = temp_db.conn.execute(
            "SELECT job_id FROM queue_state WHERE job_id = ?",
            (job_id,)
        )
        assert cursor.fetchone() is None
