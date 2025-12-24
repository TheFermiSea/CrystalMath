"""
Queue Manager for job scheduling and prioritization.

This module provides a sophisticated queue management system for CRYSTAL calculations:
- Priority-based scheduling (0-4, lower = higher priority)
- Job dependency resolution with DAG validation
- Concurrent job limits per cluster/runner
- Retry logic for failed jobs
- Fair scheduling across users
- Persistent queue state
- Resource-aware scheduling
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
import json

from .database import Database
from .dependency_utils import assert_acyclic, CircularDependencyError as DependencyUtilsCircularError
from .constants import JobStatus


logger = logging.getLogger(__name__)


class Priority(IntEnum):
    """Job priority levels (lower number = higher priority)."""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


@dataclass
class QueuedJob:
    """Represents a job in the queue with scheduling metadata."""
    job_id: int
    priority: Priority
    enqueued_at: datetime
    dependencies: Set[int] = field(default_factory=set)
    retry_count: int = 0
    max_retries: int = 3
    runner_type: str = "local"
    cluster_id: Optional[int] = None
    user_id: Optional[str] = None
    resource_requirements: Dict[str, Any] = field(default_factory=dict)

    def __lt__(self, other: "QueuedJob") -> bool:
        """Compare jobs for priority queue ordering."""
        if self.priority != other.priority:
            return self.priority < other.priority
        # Within same priority, FIFO (older first)
        return self.enqueued_at < other.enqueued_at


@dataclass
class ClusterState:
    """Tracks the state of a cluster/runner."""
    cluster_id: int
    max_concurrent_jobs: int
    running_jobs: Set[int] = field(default_factory=set)
    paused: bool = False
    available_resources: Dict[str, Any] = field(default_factory=dict)

    @property
    def can_accept_job(self) -> bool:
        """Check if cluster can accept more jobs."""
        return not self.paused and len(self.running_jobs) < self.max_concurrent_jobs


@dataclass
class SchedulerMetrics:
    """Metrics for monitoring scheduler performance."""
    total_jobs_scheduled: int = 0
    total_jobs_completed: int = 0
    total_jobs_failed: int = 0
    total_jobs_retried: int = 0
    queue_depth_by_cluster: Dict[int, int] = field(default_factory=dict)
    average_wait_time_seconds: float = 0.0
    jobs_per_hour: float = 0.0
    failed_job_rate: float = 0.0
    last_updated: Optional[datetime] = None


class QueueManagerError(Exception):
    """Base exception for queue manager errors."""
    pass


class CircularDependencyError(QueueManagerError):
    """Raised when circular dependencies are detected."""
    pass


class InvalidJobError(QueueManagerError):
    """Raised when a job is invalid or not found."""
    pass


class QueueManager:
    """
    Manages job scheduling, prioritization, and execution coordination.

    This class provides:
    - Priority-based job queuing with FIFO within priority levels
    - Dependency resolution and DAG validation
    - Concurrent job limits per cluster
    - Retry logic for failed jobs
    - Fair scheduling across users
    - Resource-aware scheduling
    - Persistent queue state
    - Background scheduling worker

    Architecture:
    - Uses asyncio.Queue for in-memory priority queue
    - Database as source of truth for persistence
    - Supports distributed deployment (future)

    Example:
        >>> db = Database(Path("project.db"))
        >>> qm = QueueManager(db)
        >>> await qm.start()
        >>> await qm.enqueue(job_id=1, priority=Priority.HIGH)
        >>> job_id = await qm.dequeue("local")
        >>> await qm.stop()
    """

    def __init__(
        self,
        database: Database,
        default_max_concurrent: int = 4,
        scheduling_interval: float = 1.0,
        enable_fair_share: bool = False
    ):
        """
        Initialize the queue manager.

        Args:
            database: Database instance for persistence
            default_max_concurrent: Default concurrent job limit per cluster
            scheduling_interval: Seconds between scheduling cycles
            enable_fair_share: Enable fair share scheduling across users
        """
        self.db = database
        self.default_max_concurrent = default_max_concurrent
        self.scheduling_interval = scheduling_interval
        self.enable_fair_share = enable_fair_share

        # In-memory queue state (priority queue per runner type)
        self._queues: Dict[str, asyncio.PriorityQueue] = defaultdict(
            lambda: asyncio.PriorityQueue()
        )

        # Job metadata indexed by job_id
        self._jobs: Dict[int, QueuedJob] = {}

        # Cluster state tracking
        self._clusters: Dict[int, ClusterState] = {}
        self._default_cluster = ClusterState(
            cluster_id=0,
            max_concurrent_jobs=default_max_concurrent
        )

        # Dependency graph (job_id -> set of dependent job_ids)
        self._dependents: Dict[int, Set[int]] = defaultdict(set)

        # Fair share tracking (user_id -> last scheduled time)
        self._user_last_scheduled: Dict[str, datetime] = {}

        # Metrics
        self.metrics = SchedulerMetrics()

        # Background worker
        self._scheduler_task: Optional[asyncio.Task] = None
        self._running = False

        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

        # In-memory status cache (optimization for N+1 queries)
        # Maps job_id -> (status, timestamp)
        self._status_cache: Dict[int, Tuple[str, datetime]] = {}
        self._cache_ttl_seconds = 0.1  # Cache expires after 100ms

        # Initialize database schema extensions
        self._initialize_queue_schema()

    # ==================== Async Database Helpers ====================

    async def _run_db(self, func, *args, **kwargs):
        """
        Run a blocking database call in a thread to avoid freezing the event loop.

        This wraps synchronous database operations to be async-safe, preventing
        TUI freezes during database operations.

        Args:
            func: The database method to call
            *args: Positional arguments for the method
            **kwargs: Keyword arguments for the method

        Returns:
            Result of the database call
        """
        return await asyncio.to_thread(func, *args, **kwargs)

    # ==================== Schema Initialization ====================

    def _initialize_queue_schema(self) -> None:
        """Extend database schema for queue management."""
        schema_extension = """
        -- Queue state table
        CREATE TABLE IF NOT EXISTS queue_state (
            job_id INTEGER PRIMARY KEY,
            priority INTEGER NOT NULL,
            enqueued_at TIMESTAMP NOT NULL,
            dependencies TEXT,  -- JSON array of job_ids
            retry_count INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 3,
            runner_type TEXT DEFAULT 'local',
            cluster_id INTEGER,
            user_id TEXT,
            resource_requirements TEXT,  -- JSON object
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        );

        -- Cluster state table
        CREATE TABLE IF NOT EXISTS cluster_state (
            cluster_id INTEGER PRIMARY KEY,
            max_concurrent_jobs INTEGER NOT NULL,
            paused INTEGER DEFAULT 0,
            available_resources TEXT  -- JSON object
        );

        -- Scheduler metrics table
        CREATE TABLE IF NOT EXISTS scheduler_metrics (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            total_jobs_scheduled INTEGER DEFAULT 0,
            total_jobs_completed INTEGER DEFAULT 0,
            total_jobs_failed INTEGER DEFAULT 0,
            total_jobs_retried INTEGER DEFAULT 0,
            average_wait_time_seconds REAL DEFAULT 0.0,
            jobs_per_hour REAL DEFAULT 0.0,
            failed_job_rate REAL DEFAULT 0.0,
            last_updated TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_queue_priority ON queue_state (priority, enqueued_at);
        CREATE INDEX IF NOT EXISTS idx_queue_runner ON queue_state (runner_type);
        CREATE INDEX IF NOT EXISTS idx_queue_cluster ON queue_state (cluster_id);
        """

        # FIX: Use connection context manager instead of raw self.db.conn
        with self.db.connection() as conn:
            conn.executescript(schema_extension)
            conn.commit()

        # Restore queue state from database
        self._restore_from_database()

    def _restore_from_database(self) -> None:
        """Restore queue state from database after restart.

        CRITICAL: Also handles crash recovery by resetting any RUNNING jobs
        that exist in queue_state back to QUEUED status. This prevents
        "zombie" jobs that are stuck in RUNNING state after a crash.
        """
        # FIX: Use connection context manager instead of raw self.db.conn
        with self.db.connection() as conn:
            # CRASH RECOVERY: Reset any RUNNING jobs in queue_state to QUEUED
            # These are jobs that were running when the app crashed/was killed
            conn.execute(
                f"UPDATE jobs SET status = '{JobStatus.QUEUED}' "
                f"WHERE status = '{JobStatus.RUNNING}' "
                "AND id IN (SELECT job_id FROM queue_state)"
            )
            conn.commit()

            cursor = conn.execute(
                "SELECT * FROM queue_state WHERE job_id IN "
                f"(SELECT id FROM jobs WHERE status IN ('{JobStatus.PENDING}', '{JobStatus.QUEUED}'))"
            )

            for row in cursor.fetchall():
                job_id = row[0]
                priority = Priority(row[1])
                enqueued_at = datetime.fromisoformat(row[2])
                dependencies = set(json.loads(row[3])) if row[3] else set()
                retry_count = row[4]
                max_retries = row[5]
                runner_type = row[6]
                cluster_id = row[7]
                user_id = row[8]
                resource_requirements = json.loads(row[9]) if row[9] else {}

                queued_job = QueuedJob(
                    job_id=job_id,
                    priority=priority,
                    enqueued_at=enqueued_at,
                    dependencies=dependencies,
                    retry_count=retry_count,
                    max_retries=max_retries,
                    runner_type=runner_type,
                    cluster_id=cluster_id,
                    user_id=user_id,
                    resource_requirements=resource_requirements
                )

                self._jobs[job_id] = queued_job

                # Build dependency graph
                for dep_id in dependencies:
                    self._dependents[dep_id].add(job_id)

            # Restore cluster state
            cursor = conn.execute("SELECT * FROM cluster_state")
            for row in cursor.fetchall():
                cluster_id = row[0]
                max_concurrent = row[1]
                paused = bool(row[2])
                available_resources = json.loads(row[3]) if row[3] else {}

                # Get running jobs for this cluster
                running_cursor = conn.execute(
                    f"SELECT id FROM jobs WHERE status = '{JobStatus.RUNNING}' AND id IN "
                    "(SELECT job_id FROM queue_state WHERE cluster_id = ?)",
                    (cluster_id,)
                )
                running_jobs = {row[0] for row in running_cursor.fetchall()}

                self._clusters[cluster_id] = ClusterState(
                    cluster_id=cluster_id,
                    max_concurrent_jobs=max_concurrent,
                    running_jobs=running_jobs,
                    paused=paused,
                    available_resources=available_resources
                )

            # Restore metrics
            cursor = conn.execute("SELECT * FROM scheduler_metrics WHERE id = 1")
            row = cursor.fetchone()
            if row:
                self.metrics = SchedulerMetrics(
                    total_jobs_scheduled=row[1],
                    total_jobs_completed=row[2],
                    total_jobs_failed=row[3],
                    total_jobs_retried=row[4],
                    average_wait_time_seconds=row[5],
                    jobs_per_hour=row[6],
                    failed_job_rate=row[7],
                    last_updated=datetime.fromisoformat(row[8]) if row[8] else None
                )

        logger.info(
            f"Restored queue state: {len(self._jobs)} queued jobs, "
            f"{len(self._clusters)} clusters"
        )

    async def start(self) -> None:
        """Start the background scheduler worker."""
        if self._running:
            logger.warning("Queue manager already running")
            return

        self._running = True
        self._scheduler_task = asyncio.create_task(self._scheduler_worker())
        logger.info("Queue manager started")

    async def stop(self) -> None:
        """Stop the background scheduler worker.

        Uses locking to ensure thread-safe shutdown and prevent
        race conditions with concurrent job completions.
        """
        if not self._running:
            return

        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass

        # Persist final state under lock to prevent race with handle_job_completion
        async with self._lock:
            self._persist_to_database()
        logger.info("Queue manager stopped")

    async def enqueue(
        self,
        job_id: int,
        priority: int = 2,
        dependencies: Optional[List[int]] = None,
        runner_type: str = "local",
        cluster_id: Optional[int] = None,
        user_id: Optional[str] = None,
        max_retries: int = 3,
        resource_requirements: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Add a job to the queue.

        Args:
            job_id: Database ID of the job to enqueue
            priority: Priority level (0-4, lower = higher priority)
            dependencies: List of job IDs that must complete first
            runner_type: Type of runner ("local", "slurm", "ssh", etc.)
            cluster_id: Cluster/runner instance ID
            user_id: User who submitted the job (for fair share)
            max_retries: Maximum retry attempts on failure
            resource_requirements: Dict of required resources (cores, memory, etc.)

        Raises:
            InvalidJobError: If job doesn't exist in database
            CircularDependencyError: If dependencies form a cycle
        """
        async with self._lock:
            # Validate job exists
            job = self.db.get_job(job_id)
            if not job:
                raise InvalidJobError(f"Job {job_id} not found in database")

            # Validate dependencies
            deps = set(dependencies) if dependencies else set()
            if deps:
                self._validate_dependencies(job_id, deps)

            # Create queued job
            queued_job = QueuedJob(
                job_id=job_id,
                priority=Priority(priority),
                enqueued_at=datetime.now(),
                dependencies=deps,
                max_retries=max_retries,
                runner_type=runner_type,
                cluster_id=cluster_id,
                user_id=user_id,
                resource_requirements=resource_requirements or {}
            )

            self._jobs[job_id] = queued_job

            # Update dependency graph
            for dep_id in deps:
                self._dependents[dep_id].add(job_id)

            # Update database status
            self.db.update_status(job_id, JobStatus.QUEUED)
            # Invalidate cache since status changed
            self._invalidate_status_cache(job_id)

            # Persist queue state
            self._persist_job_to_database(queued_job)

            logger.info(
                f"Enqueued job {job_id} with priority {priority} "
                f"(dependencies: {deps})"
            )

    def _validate_dependencies(self, job_id: int, dependencies: Set[int]) -> None:
        """
        Validate that dependencies don't form cycles.

        This is the enforcement point for all callers - ensures no circular
        dependencies are introduced when adding new job dependencies.

        Args:
            job_id: Job being validated
            dependencies: Set of dependency job IDs

        Raises:
            CircularDependencyError: If cycle detected
            InvalidJobError: If dependency job doesn't exist
        """
        # Check for self-dependency
        if job_id in dependencies:
            raise CircularDependencyError(
                f"Job {job_id} cannot depend on itself"
            )

        # Check all dependencies exist (OPTIMIZATION: single batch query)
        # This is DB-specific validation that dependency_utils doesn't handle
        job_statuses = self.db.get_job_statuses_batch(dependencies)
        for dep_id in dependencies:
            if dep_id not in job_statuses:
                raise InvalidJobError(f"Dependency job {dep_id} not found")

        # Build temporary graph including proposed dependencies for cycle detection
        # Graph format: {job_id: [list of jobs this job depends on]}
        graph = {}

        # Add existing dependencies from all jobs in queue
        for jid, queued_job in self._jobs.items():
            graph[jid] = list(queued_job.dependencies) if queued_job.dependencies else []

        # Add the proposed dependencies for this job
        graph[job_id] = list(dependencies)

        # Use shared cycle detection utility (raises CircularDependencyError if cycle found)
        try:
            assert_acyclic(graph)
        except DependencyUtilsCircularError as e:
            # Re-raise with queue_manager's CircularDependencyError type for consistency
            raise CircularDependencyError(
                f"Adding dependencies {dependencies} to job {job_id} would create a cycle: {e}"
            ) from e

    def _get_job_statuses_batch(self, job_ids: List[int]) -> Dict[int, str]:
        """
        Get job statuses efficiently using batch query with caching.

        This method:
        1. Fetches statuses from database using single batch query
        2. Returns a dictionary mapping job_id -> status

        Replaces the N+1 query pattern where each job was queried individually.

        Args:
            job_ids: List of job IDs to fetch statuses for

        Returns:
            Dictionary mapping job_id -> status string
        """
        if not job_ids:
            return {}

        # Use batch query from database (single query for all jobs)
        return self.db.get_job_statuses_batch(job_ids)

    def _invalidate_status_cache(self, job_id: Optional[int] = None) -> None:
        """
        Invalidate status cache for a job or all jobs.

        Called when job status changes to ensure fresh data.

        Args:
            job_id: Job to invalidate, or None to clear entire cache
        """
        if job_id is None:
            self._status_cache.clear()
        else:
            self._status_cache.pop(job_id, None)

    async def dequeue(self, runner_type: str) -> Optional[int]:
        """
        Get the next job to execute for a specific runner type.

        This method is typically called by runner instances when they're
        ready to accept a new job.

        Args:
            runner_type: Type of runner requesting a job

        Returns:
            Job ID if a job is available, None otherwise
        """
        async with self._lock:
            # Find highest priority job that can run (use locked version to avoid deadlock)
            schedulable = self._schedule_jobs_locked()

            for job_id in schedulable:
                queued_job = self._jobs.get(job_id)
                if queued_job and queued_job.runner_type == runner_type:
                    # Remove from queue
                    del self._jobs[job_id]

                    # Update cluster state
                    cluster = self._get_cluster(queued_job.cluster_id)
                    cluster.running_jobs.add(job_id)

                    # Update metrics
                    wait_time = (datetime.now() - queued_job.enqueued_at).total_seconds()
                    self._update_wait_time_metric(wait_time)
                    self.metrics.total_jobs_scheduled += 1

                    # Update user fair share
                    if queued_job.user_id:
                        self._user_last_scheduled[queued_job.user_id] = datetime.now()

                    # Update database
                    self.db.update_status(job_id, JobStatus.RUNNING)
                    # Invalidate cache since status changed
                    self._invalidate_status_cache(job_id)
                    # DON'T remove from queue_state yet - keep for retry logic

                    logger.info(f"Dequeued job {job_id} for {runner_type}")
                    return job_id

            return None

    async def schedule_jobs(self) -> List[int]:
        """
        Determine which jobs should be scheduled next.

        This method applies scheduling policies:
        - Priority-based ordering
        - Dependency satisfaction
        - Resource availability
        - Concurrent job limits
        - Fair share (if enabled)

        Optimized to use batch query instead of N+1 individual queries.

        Thread-safe: Acquires lock before reading shared state.

        Returns:
            List of job IDs ready to be scheduled (in priority order)
        """
        async with self._lock:
            return self._schedule_jobs_locked()

    def _schedule_jobs_locked(self) -> List[int]:
        """
        Internal scheduling logic without lock acquisition.

        IMPORTANT: Caller MUST hold self._lock before calling this method.
        This is an internal helper used by methods that already hold the lock.

        Returns:
            List of job IDs ready to be scheduled (in priority order)
        """
        schedulable: List[Tuple[QueuedJob, float]] = []

        # OPTIMIZATION: Batch query all job statuses instead of individual queries
        job_ids = list(self._jobs.keys())
        job_statuses = self._get_job_statuses_batch(job_ids)

        for job_id, queued_job in self._jobs.items():
            # Check job status from batch query cache (O(1) lookup)
            status = job_statuses.get(job_id)
            if not status or status not in (JobStatus.PENDING, JobStatus.QUEUED):
                continue

            # Check if dependencies are satisfied (using locked helper)
            if not self._dependencies_satisfied_locked(job_id):
                continue

            # Check cluster capacity
            cluster = self._get_cluster(queued_job.cluster_id)
            if not cluster.can_accept_job:
                continue

            # Check resources available (if resource-aware scheduling)
            if queued_job.resource_requirements:
                if not self._resources_available(cluster, queued_job.resource_requirements):
                    continue

            # Calculate scheduling score
            score = self._calculate_scheduling_score(queued_job)
            schedulable.append((queued_job, score))

        # Sort by score (higher = better)
        schedulable.sort(key=lambda x: x[1], reverse=True)

        return [job.job_id for job, _ in schedulable]

    def _dependencies_satisfied(self, job_id: int) -> bool:
        """
        Check if all dependencies for a job are satisfied.

        WARNING: This method does NOT acquire the lock. If you need thread-safe
        dependency checking, use _dependencies_satisfied_locked() and ensure you
        hold the lock before calling.

        This method is kept for backward compatibility but should generally not
        be called directly - use the locked version instead.
        """
        return self._dependencies_satisfied_locked(job_id)

    def _dependencies_satisfied_locked(self, job_id: int) -> bool:
        """
        Check if all dependencies for a job are satisfied.

        IMPORTANT: Caller MUST hold self._lock before calling this method.
        This is an internal helper used by methods that already hold the lock.

        Args:
            job_id: Job to check dependencies for

        Returns:
            True if all dependencies are satisfied, False otherwise
        """
        queued_job = self._jobs.get(job_id)
        if not queued_job:
            return False

        if not queued_job.dependencies:
            return True

        # OPTIMIZATION: Batch query for all dependency statuses (single DB query)
        dep_statuses = self._get_job_statuses_batch(list(queued_job.dependencies))

        # Check if all dependencies are completed
        for dep_id in queued_job.dependencies:
            status = dep_statuses.get(dep_id)
            if status != JobStatus.COMPLETED:
                return False

        return True

    def _resources_available(
        self,
        cluster: ClusterState,
        requirements: Dict[str, Any]
    ) -> bool:
        """
        Check if cluster has sufficient resources for job.

        Args:
            cluster: Cluster state
            requirements: Resource requirements dict (e.g., {'cores': 8, 'memory_gb': 16})

        Returns:
            True if resources available, False otherwise
        """
        if not cluster.available_resources:
            # No resource tracking, assume available
            return True

        for resource, required in requirements.items():
            available = cluster.available_resources.get(resource, 0)
            if available < required:
                return False

        return True

    def _calculate_scheduling_score(self, queued_job: QueuedJob) -> float:
        """
        Calculate scheduling score for a job.

        Higher score = higher scheduling priority

        Score factors:
        - Priority level (0-4)
        - Wait time (older = higher score)
        - Fair share (less recently scheduled user = higher score)

        Args:
            queued_job: Job to score

        Returns:
            Scheduling score (higher is better)
        """
        # Base score from priority (invert so lower priority = higher score)
        priority_score = (4 - queued_job.priority.value) * 1000

        # Wait time bonus (1 point per minute waiting)
        wait_seconds = (datetime.now() - queued_job.enqueued_at).total_seconds()
        wait_score = wait_seconds / 60.0

        # Fair share bonus (if enabled)
        fair_share_score = 0.0
        if self.enable_fair_share and queued_job.user_id:
            last_scheduled = self._user_last_scheduled.get(queued_job.user_id)
            if last_scheduled:
                seconds_since = (datetime.now() - last_scheduled).total_seconds()
                fair_share_score = seconds_since / 60.0  # 1 point per minute
            else:
                fair_share_score = 1000.0  # Never scheduled = high bonus

        return priority_score + wait_score + fair_share_score

    def _get_cluster(self, cluster_id: Optional[int]) -> ClusterState:
        """Get or create cluster state."""
        if cluster_id is None or cluster_id == 0:
            return self._default_cluster

        if cluster_id not in self._clusters:
            self._clusters[cluster_id] = ClusterState(
                cluster_id=cluster_id,
                max_concurrent_jobs=self.default_max_concurrent
            )

        return self._clusters[cluster_id]

    async def pause_queue(self, cluster_id: int) -> None:
        """
        Pause job scheduling for a cluster.

        Running jobs continue, but no new jobs will be scheduled.

        Args:
            cluster_id: Cluster to pause
        """
        async with self._lock:
            cluster = self._get_cluster(cluster_id)
            cluster.paused = True
            self._persist_cluster_to_database(cluster)
            logger.info(f"Paused queue for cluster {cluster_id}")

    async def resume_queue(self, cluster_id: int) -> None:
        """
        Resume job scheduling for a cluster.

        Args:
            cluster_id: Cluster to resume
        """
        async with self._lock:
            cluster = self._get_cluster(cluster_id)
            cluster.paused = False
            self._persist_cluster_to_database(cluster)
            logger.info(f"Resumed queue for cluster {cluster_id}")

    async def reorder_queue(self, job_id: int, new_priority: int) -> None:
        """
        Change the priority of a queued job.

        Args:
            job_id: Job to reorder
            new_priority: New priority level (0-4)

        Raises:
            InvalidJobError: If job is not queued
        """
        async with self._lock:
            queued_job = self._jobs.get(job_id)
            if not queued_job:
                raise InvalidJobError(f"Job {job_id} is not in queue")

            old_priority = queued_job.priority
            queued_job.priority = Priority(new_priority)

            # Persist change
            self._persist_job_to_database(queued_job)

            logger.info(
                f"Reordered job {job_id}: priority {old_priority} → {new_priority}"
            )

    async def cancel_job(self, job_id: int) -> bool:
        """
        Cancel a job, removing it from the queue.

        If the job is queued (pending), it is removed from the queue.
        If the job is running, it is marked as cancelled but the actual
        process termination should be handled by the runner.
        If the job is already completed or failed, returns False.

        Args:
            job_id: Database ID of the job to cancel

        Returns:
            True if job was cancelled, False if job was not cancellable
            (already completed, failed, or not found)
        """
        async with self._lock:
            # Get current job status from database
            job = self.db.get_job(job_id)
            if not job:
                logger.warning(f"Cannot cancel job {job_id}: not found")
                return False

            current_status = job.get("status") if isinstance(job, dict) else getattr(job, "status", None)

            # Already in terminal state
            if current_status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                logger.debug(f"Job {job_id} already in terminal state: {current_status}")
                return False

            # Remove from internal queue if present
            if job_id in self._jobs:
                del self._jobs[job_id]

            # Remove from cluster running jobs
            for cluster in self._clusters.values():
                if job_id in cluster.running_jobs:
                    cluster.running_jobs.remove(job_id)
                    break
            else:
                self._default_cluster.running_jobs.discard(job_id)

            # Remove from dependency graph
            if job_id in self._dependents:
                del self._dependents[job_id]

            # Remove any dependencies on this job from other jobs
            for other_job in self._jobs.values():
                other_job.dependencies.discard(job_id)

            # Update database status to CANCELLED
            self.db.update_status(job_id, JobStatus.CANCELLED)

            # Invalidate cache
            self._invalidate_status_cache(job_id)

            # Remove from queue_state table
            self._remove_job_from_database(job_id)

            logger.info(f"Cancelled job {job_id}")
            return True

    async def handle_job_completion(self, job_id: int, success: bool) -> None:
        """
        Handle job completion event.

        This method:
        - Updates metrics
        - Releases cluster resources
        - Schedules dependent jobs if successful
        - Retries job if failed and retries available

        Args:
            job_id: Completed job ID
            success: Whether job completed successfully
        """
        async with self._lock:
            # Invalidate cache since status will change
            self._invalidate_status_cache(job_id)

            # Update metrics
            if success:
                self.metrics.total_jobs_completed += 1
            else:
                self.metrics.total_jobs_failed += 1

            # Find and update cluster state
            for cluster in self._clusters.values():
                if job_id in cluster.running_jobs:
                    cluster.running_jobs.remove(job_id)
                    break
            else:
                self._default_cluster.running_jobs.discard(job_id)

            # Handle failure with retry logic
            if not success:
                await self._handle_job_failure(job_id)

            # If successful, check for dependent jobs and clean up
            if success:
                if job_id in self._dependents:
                    dependents = self._dependents[job_id]
                    logger.info(
                        f"Job {job_id} completed, checking {len(dependents)} dependent jobs"
                    )
                    # Dependent jobs will be picked up by scheduler
                    del self._dependents[job_id]

                # Remove from queue_state on successful completion
                self._remove_job_from_database(job_id)

            # Update metrics
            self._update_metrics()
            self._persist_to_database()

    async def _handle_job_failure(self, job_id: int) -> None:
        """
        Handle job failure with retry logic.

        Args:
            job_id: Failed job ID
        """
        # FIX: Use connection context manager instead of raw self.db.conn
        with self.db.connection() as conn:
            # Check if job was queued (might have retry metadata)
            cursor = conn.execute(
                "SELECT * FROM queue_state WHERE job_id = ?",
                (job_id,)
            )
            row = cursor.fetchone()

        if row:
            retry_count = row[4]  # retry_count column
            max_retries = row[5]  # max_retries column

            if retry_count < max_retries:
                # Re-enqueue with incremented retry count
                retry_count += 1
                self.metrics.total_jobs_retried += 1

                # Reconstruct QueuedJob and re-add to internal queue
                priority = Priority(row[1])
                enqueued_at = datetime.fromisoformat(row[2])
                dependencies = set(json.loads(row[3])) if row[3] else set()
                runner_type = row[6]
                cluster_id = row[7]
                user_id = row[8]
                resource_requirements = json.loads(row[9]) if row[9] else {}

                queued_job = QueuedJob(
                    job_id=job_id,
                    priority=priority,
                    enqueued_at=enqueued_at,
                    dependencies=dependencies,
                    retry_count=retry_count,
                    max_retries=max_retries,
                    runner_type=runner_type,
                    cluster_id=cluster_id,
                    user_id=user_id,
                    resource_requirements=resource_requirements
                )

                # Re-add to internal queue
                self._jobs[job_id] = queued_job

                # Update retry count in database
                with self.db.connection() as conn:
                    conn.execute(
                        "UPDATE queue_state SET retry_count = ? WHERE job_id = ?",
                        (retry_count, job_id)
                    )
                    conn.commit()

                # Reset job status to QUEUED
                await self._run_db(self.db.update_status, job_id, JobStatus.QUEUED)

                logger.info(
                    f"Retrying job {job_id} (attempt {retry_count}/{max_retries})"
                )
            else:
                logger.warning(
                    f"Job {job_id} failed after {max_retries} retries, giving up"
                )
                # Mark as permanently failed
                self.db.update_status(job_id, JobStatus.FAILED)

                # Remove from queue_state on permanent failure
                self._remove_job_from_database(job_id)

                # Cancel dependent jobs
                if job_id in self._dependents:
                    for dependent_id in self._dependents[job_id]:
                        self.db.update_status(dependent_id, JobStatus.FAILED)
                        # Also remove dependent from queue
                        self._remove_job_from_database(dependent_id)
                        if dependent_id in self._jobs:
                            del self._jobs[dependent_id]
                        logger.warning(
                            f"Cancelled job {dependent_id} due to failed dependency {job_id}"
                        )
                    del self._dependents[job_id]

    async def _scheduler_worker(self) -> None:
        """
        Background worker that continuously schedules jobs.

        This runs in a loop and:
        1. Checks for schedulable jobs
        2. Updates queue state
        3. Updates metrics
        4. Persists state periodically

        Thread-safe: All shared state access is properly synchronized.
        """
        logger.info("Scheduler worker started", extra={
            "component": "queue_manager",
            "interval_seconds": self.scheduling_interval
        })

        loop_iteration = 0

        while self._running:
            loop_iteration += 1
            start_time = time.time()

            try:
                # Schedule jobs (acquires lock internally)
                schedulable = await self.schedule_jobs()

                if schedulable:
                    logger.debug("Scheduler found schedulable jobs", extra={
                        "job_count": len(schedulable),
                        "job_ids": schedulable[:10]  # Log first 10 to avoid spam
                    })

                # Update queue depth metrics (with lock)
                total_queued = 0
                async with self._lock:
                    for cluster_id, cluster in self._clusters.items():
                        queue_depth = sum(
                            1 for job in self._jobs.values()
                            if job.cluster_id == cluster_id
                        )
                        self.metrics.queue_depth_by_cluster[cluster_id] = queue_depth
                        total_queued += queue_depth

                    # Update and persist metrics
                    self._update_metrics()
                    self._persist_to_database()

                # Log iteration completion
                elapsed = time.time() - start_time
                logger.debug("Scheduler iteration completed", extra={
                    "iteration": loop_iteration,
                    "elapsed_seconds": round(elapsed, 3),
                    "total_queued": total_queued,
                    "schedulable_count": len(schedulable),
                    "total_jobs_scheduled": self.metrics.total_jobs_scheduled,
                    "total_jobs_completed": self.metrics.total_jobs_completed,
                    "total_jobs_failed": self.metrics.total_jobs_failed
                })

                # Sleep until next cycle (lock-free, don't hold during sleep)
                await asyncio.sleep(self.scheduling_interval)

            except asyncio.CancelledError:
                logger.info("Scheduler worker stopped")
                break
            except Exception as e:
                elapsed = time.time() - start_time
                logger.error("Scheduler worker error", extra={
                    "iteration": loop_iteration,
                    "elapsed_seconds": round(elapsed, 3),
                    "error": str(e)
                }, exc_info=True)
                await asyncio.sleep(self.scheduling_interval)

    def _update_metrics(self) -> None:
        """Update scheduler metrics."""
        self.metrics.last_updated = datetime.now()

        # Calculate failed job rate
        total_jobs = self.metrics.total_jobs_completed + self.metrics.total_jobs_failed
        if total_jobs > 0:
            self.metrics.failed_job_rate = (
                self.metrics.total_jobs_failed / total_jobs
            )

        # Calculate jobs per hour (simple moving average)
        # This would need more sophisticated tracking in production
        if self.metrics.last_updated:
            # Placeholder - real implementation would track start time
            self.metrics.jobs_per_hour = float(self.metrics.total_jobs_completed)

    def _update_wait_time_metric(self, wait_time_seconds: float) -> None:
        """Update average wait time with exponential moving average."""
        alpha = 0.1  # Smoothing factor
        if self.metrics.average_wait_time_seconds == 0.0:
            self.metrics.average_wait_time_seconds = wait_time_seconds
        else:
            self.metrics.average_wait_time_seconds = (
                alpha * wait_time_seconds +
                (1 - alpha) * self.metrics.average_wait_time_seconds
            )

    def _persist_to_database(self) -> None:
        """Persist all queue state to database."""
        # FIX: Use a single connection context for all persistence operations
        with self.db.connection() as conn:
            # Persist all queued jobs
            for queued_job in self._jobs.values():
                self._persist_job_to_database(queued_job, conn)

            # Persist cluster states
            for cluster in self._clusters.values():
                self._persist_cluster_to_database(cluster, conn)

            # Persist metrics
            conn.execute(
                """
                INSERT OR REPLACE INTO scheduler_metrics
                (id, total_jobs_scheduled, total_jobs_completed, total_jobs_failed,
                 total_jobs_retried, average_wait_time_seconds, jobs_per_hour,
                 failed_job_rate, last_updated)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.metrics.total_jobs_scheduled,
                    self.metrics.total_jobs_completed,
                    self.metrics.total_jobs_failed,
                    self.metrics.total_jobs_retried,
                    self.metrics.average_wait_time_seconds,
                    self.metrics.jobs_per_hour,
                    self.metrics.failed_job_rate,
                    self.metrics.last_updated.isoformat() if self.metrics.last_updated else None
                )
            )
            conn.commit()

    def _persist_job_to_database(self, queued_job: QueuedJob, conn=None) -> None:
        """Persist a single queued job to database.

        Args:
            queued_job: Job to persist
            conn: Optional connection (if None, uses context manager)
        """
        def _execute(c):
            c.execute(
                """
                INSERT OR REPLACE INTO queue_state
                (job_id, priority, enqueued_at, dependencies, retry_count, max_retries,
                 runner_type, cluster_id, user_id, resource_requirements)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    queued_job.job_id,
                    queued_job.priority.value,
                    queued_job.enqueued_at.isoformat(),
                    json.dumps(list(queued_job.dependencies)),
                    queued_job.retry_count,
                    queued_job.max_retries,
                    queued_job.runner_type,
                    queued_job.cluster_id,
                    queued_job.user_id,
                    json.dumps(queued_job.resource_requirements)
                )
            )

        if conn:
            _execute(conn)
        else:
            with self.db.connection() as c:
                _execute(c)
                c.commit()

    def _persist_cluster_to_database(self, cluster: ClusterState, conn=None) -> None:
        """Persist cluster state to database.

        Args:
            cluster: Cluster state to persist
            conn: Optional connection (if None, uses context manager)
        """
        def _execute(c):
            c.execute(
                """
                INSERT OR REPLACE INTO cluster_state
                (cluster_id, max_concurrent_jobs, paused, available_resources)
                VALUES (?, ?, ?, ?)
                """,
                (
                    cluster.cluster_id,
                    cluster.max_concurrent_jobs,
                    1 if cluster.paused else 0,
                    json.dumps(cluster.available_resources)
                )
            )

        if conn:
            _execute(conn)
        else:
            with self.db.connection() as c:
                _execute(c)
                c.commit()

    def _remove_job_from_database(self, job_id: int) -> None:
        """Remove job from queue_state table (after dequeue)."""
        with self.db.connection() as conn:
            conn.execute(
                "DELETE FROM queue_state WHERE job_id = ?",
                (job_id,)
            )
            conn.commit()

    def get_queue_status(self, runner_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Get current queue status.

        Args:
            runner_type: Optional filter by runner type

        Returns:
            Dict with queue statistics
        """
        jobs = list(self._jobs.values())

        if runner_type:
            jobs = [j for j in jobs if j.runner_type == runner_type]

        # Count by priority
        by_priority = defaultdict(int)
        for job in jobs:
            by_priority[job.priority.name] += 1

        return {
            "total_queued": len(jobs),
            "by_priority": dict(by_priority),
            "by_runner": {
                rt: len([j for j in jobs if j.runner_type == rt])
                for rt in set(j.runner_type for j in jobs)
            },
            "metrics": {
                "scheduled": self.metrics.total_jobs_scheduled,
                "completed": self.metrics.total_jobs_completed,
                "failed": self.metrics.total_jobs_failed,
                "retried": self.metrics.total_jobs_retried,
                "avg_wait_time_seconds": self.metrics.average_wait_time_seconds,
                "jobs_per_hour": self.metrics.jobs_per_hour,
                "failed_rate": self.metrics.failed_job_rate
            },
            "clusters": {
                cid: {
                    "running": len(cluster.running_jobs),
                    "max_concurrent": cluster.max_concurrent_jobs,
                    "paused": cluster.paused,
                    "capacity": cluster.can_accept_job
                }
                for cid, cluster in self._clusters.items()
            }
        }
