# Queue Manager Documentation

## Overview

The Queue Manager is a sophisticated job scheduling system for CRYSTAL calculations that provides priority-based scheduling, dependency resolution, resource management, and automatic retry handling.

## Features

### Core Capabilities

- **Priority-Based Scheduling**: 5 priority levels (CRITICAL, HIGH, NORMAL, LOW, BACKGROUND)
- **Dependency Management**: DAG-based job dependencies with cycle detection
- **Concurrent Job Limits**: Per-cluster limits on simultaneous job execution
- **Automatic Retry**: Configurable retry attempts for failed jobs
- **Fair Share Scheduling**: Optional round-robin across users
- **Resource-Aware Scheduling**: Match jobs to available cluster resources
- **Persistent State**: Queue state survives restarts
- **Real-time Metrics**: Job throughput, wait times, failure rates

### Architecture

```
┌─────────────────────────────────────────────────┐
│           QueueManager                          │
│                                                 │
│  ┌──────────────┐      ┌──────────────┐       │
│  │ Priority     │      │ Dependency   │       │
│  │ Queues       │◄────►│ Graph (DAG)  │       │
│  └──────────────┘      └──────────────┘       │
│         │                      │               │
│         ▼                      ▼               │
│  ┌──────────────────────────────────┐         │
│  │   Scheduler (Background Worker)  │         │
│  └──────────────────────────────────┘         │
│         │                                      │
│         ▼                                      │
│  ┌──────────────┐      ┌──────────────┐       │
│  │ Cluster      │      │ Database     │       │
│  │ State        │◄────►│ Persistence  │       │
│  └──────────────┘      └──────────────┘       │
└─────────────────────────────────────────────────┘
```

## Usage

### Basic Usage

```python
from pathlib import Path
from src.core.database import Database
from src.core.queue_manager import QueueManager, Priority

# Initialize
db = Database(Path("project.db"))
qm = QueueManager(db, default_max_concurrent=4)

# Start background scheduler
await qm.start()

# Enqueue a job
job_id = db.create_job("mgo_scf", "/work/mgo", "CRYSTAL\nEND\n")
await qm.enqueue(job_id, priority=Priority.HIGH)

# Dequeue when runner ready
job_id = await qm.dequeue("local")
if job_id:
    # Execute job...
    pass

# Stop when done
await qm.stop()
```

### Advanced Usage

#### Job Dependencies

```python
# Create job chain: opt -> freq -> analysis
opt_job = db.create_job("optimize", "/work/opt", "OPTGEOM\n...")
freq_job = db.create_job("frequency", "/work/freq", "FREQCALC\n...")
analysis_job = db.create_job("analysis", "/work/analysis", "...")

await qm.enqueue(opt_job, priority=Priority.HIGH)
await qm.enqueue(freq_job, dependencies=[opt_job])
await qm.enqueue(analysis_job, dependencies=[freq_job])

# Jobs execute in order: opt -> freq -> analysis
```

#### Resource-Aware Scheduling

```python
# Job requiring specific resources
await qm.enqueue(
    job_id,
    cluster_id=1,
    resource_requirements={
        "cores": 16,
        "memory_gb": 32,
        "gpu": 1
    }
)

# Set cluster available resources
cluster = qm._get_cluster(1)
cluster.available_resources = {
    "cores": 64,
    "memory_gb": 128,
    "gpu": 2
}
```

#### Cluster Management

```python
# Pause cluster for maintenance
await qm.pause_queue(cluster_id=1)

# Resume after maintenance
await qm.resume_queue(cluster_id=1)

# Set concurrent job limits
cluster = qm._get_cluster(1)
cluster.max_concurrent_jobs = 8
```

#### Priority Management

```python
# Change job priority
await qm.reorder_queue(job_id, Priority.CRITICAL)

# Higher priority jobs execute first
```

#### Retry Configuration

```python
# Job with custom retry settings
await qm.enqueue(
    job_id,
    max_retries=5,  # Try up to 5 times
    priority=Priority.HIGH
)

# Failed jobs automatically retry
# Dependent jobs cancelled after max retries
```

## API Reference

### QueueManager Class

#### Constructor

```python
QueueManager(
    database: Database,
    default_max_concurrent: int = 4,
    scheduling_interval: float = 1.0,
    enable_fair_share: bool = False
)
```

**Parameters:**
- `database`: Database instance for persistence
- `default_max_concurrent`: Default concurrent job limit per cluster
- `scheduling_interval`: Seconds between scheduling cycles
- `enable_fair_share`: Enable fair share scheduling across users

#### Methods

##### `async def start() -> None`

Start the background scheduler worker.

```python
await qm.start()
```

##### `async def stop() -> None`

Stop the background scheduler worker and persist state.

```python
await qm.stop()
```

##### `async def enqueue(...) -> None`

Add a job to the queue.

```python
await qm.enqueue(
    job_id: int,
    priority: int = 2,                           # 0-4 (lower = higher priority)
    dependencies: Optional[List[int]] = None,    # Job IDs that must complete first
    runner_type: str = "local",                  # Runner type
    cluster_id: Optional[int] = None,            # Cluster/runner instance
    user_id: Optional[str] = None,               # For fair share
    max_retries: int = 3,                        # Retry attempts
    resource_requirements: Optional[Dict[str, Any]] = None
)
```

**Raises:**
- `InvalidJobError`: Job doesn't exist in database
- `CircularDependencyError`: Dependencies form a cycle

##### `async def dequeue(runner_type: str) -> Optional[int]`

Get the next job to execute for a specific runner type.

```python
job_id = await qm.dequeue("local")
if job_id:
    # Execute job
    pass
```

**Returns:** Job ID if available, None otherwise

##### `async def schedule_jobs() -> List[int]`

Determine which jobs should be scheduled next (internal use).

```python
schedulable = await qm.schedule_jobs()
# Returns list of job IDs in priority order
```

##### `async def pause_queue(cluster_id: int) -> None`

Pause job scheduling for a cluster.

```python
await qm.pause_queue(1)
```

##### `async def resume_queue(cluster_id: int) -> None`

Resume job scheduling for a cluster.

```python
await qm.resume_queue(1)
```

##### `async def reorder_queue(job_id: int, new_priority: int) -> None`

Change the priority of a queued job.

```python
await qm.reorder_queue(job_id, Priority.CRITICAL)
```

**Raises:** `InvalidJobError` if job is not queued

##### `async def handle_job_completion(job_id: int, success: bool) -> None`

Handle job completion event (called by runners).

```python
await qm.handle_job_completion(job_id, success=True)
```

This method:
- Updates metrics
- Releases cluster resources
- Schedules dependent jobs if successful
- Retries job if failed and retries available

##### `def get_queue_status(runner_type: Optional[str] = None) -> Dict[str, Any]`

Get current queue status.

```python
status = qm.get_queue_status()
print(f"Total queued: {status['total_queued']}")
print(f"By priority: {status['by_priority']}")
print(f"Metrics: {status['metrics']}")
```

**Returns:**
```python
{
    "total_queued": 10,
    "by_priority": {"HIGH": 3, "NORMAL": 5, "LOW": 2},
    "by_runner": {"local": 8, "slurm": 2},
    "metrics": {
        "scheduled": 100,
        "completed": 90,
        "failed": 5,
        "retried": 3,
        "avg_wait_time_seconds": 45.2,
        "jobs_per_hour": 12.5,
        "failed_rate": 0.05
    },
    "clusters": {
        1: {
            "running": 3,
            "max_concurrent": 4,
            "paused": False,
            "capacity": True
        }
    }
}
```

### Data Classes

#### Priority (IntEnum)

```python
class Priority(IntEnum):
    CRITICAL = 0   # Highest priority
    HIGH = 1
    NORMAL = 2     # Default
    LOW = 3
    BACKGROUND = 4 # Lowest priority
```

#### QueuedJob

```python
@dataclass
class QueuedJob:
    job_id: int
    priority: Priority
    enqueued_at: datetime
    dependencies: Set[int]
    retry_count: int
    max_retries: int
    runner_type: str
    cluster_id: Optional[int]
    user_id: Optional[str]
    resource_requirements: Dict[str, Any]
```

#### ClusterState

```python
@dataclass
class ClusterState:
    cluster_id: int
    max_concurrent_jobs: int
    running_jobs: Set[int]
    paused: bool
    available_resources: Dict[str, Any]

    @property
    def can_accept_job(self) -> bool:
        """Check if cluster can accept more jobs."""
```

#### SchedulerMetrics

```python
@dataclass
class SchedulerMetrics:
    total_jobs_scheduled: int
    total_jobs_completed: int
    total_jobs_failed: int
    total_jobs_retried: int
    queue_depth_by_cluster: Dict[int, int]
    average_wait_time_seconds: float
    jobs_per_hour: float
    failed_job_rate: float
    last_updated: Optional[datetime]
```

## Scheduling Algorithms

### Priority-Based Scheduling

Jobs are ordered by:
1. **Priority level** (0-4, lower = higher priority)
2. **Wait time** (FIFO within priority level)
3. **Fair share bonus** (if enabled)

Scheduling score calculation:

```python
score = (4 - priority) * 1000  # Priority component
      + wait_minutes           # Wait time component
      + fair_share_minutes     # Fair share component
```

Higher score = scheduled first.

### Dependency Resolution

Jobs with dependencies only become schedulable when:
- All dependency jobs have status = "COMPLETED"
- No circular dependencies exist (validated at enqueue time)

DAG validation uses depth-first search to detect cycles.

### Resource-Aware Scheduling

Jobs with resource requirements only match clusters where:

```python
cluster.available_resources[resource] >= job.requirements[resource]
```

For all required resources (cores, memory, GPU, etc.).

### Concurrent Job Limits

Each cluster has `max_concurrent_jobs` limit. Jobs are only scheduled if:

```python
len(cluster.running_jobs) < cluster.max_concurrent_jobs
```

### Retry Logic

Failed jobs are automatically retried if:

```python
job.retry_count < job.max_retries
```

After max retries:
- Job marked as permanently FAILED
- All dependent jobs are cancelled (marked FAILED)

## Database Schema

The queue manager extends the database with three tables:

### queue_state

Stores queued job metadata:

```sql
CREATE TABLE queue_state (
    job_id INTEGER PRIMARY KEY,
    priority INTEGER NOT NULL,
    enqueued_at TIMESTAMP NOT NULL,
    dependencies TEXT,              -- JSON array
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    runner_type TEXT DEFAULT 'local',
    cluster_id INTEGER,
    user_id TEXT,
    resource_requirements TEXT,     -- JSON object
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
```

### cluster_state

Stores cluster configuration:

```sql
CREATE TABLE cluster_state (
    cluster_id INTEGER PRIMARY KEY,
    max_concurrent_jobs INTEGER NOT NULL,
    paused INTEGER DEFAULT 0,
    available_resources TEXT        -- JSON object
);
```

### scheduler_metrics

Stores aggregated metrics:

```sql
CREATE TABLE scheduler_metrics (
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
```

## Background Scheduler Worker

The background worker runs in an async loop:

1. Call `schedule_jobs()` to find schedulable jobs
2. Update queue depth metrics per cluster
3. Update and persist scheduler metrics
4. Sleep for `scheduling_interval` seconds
5. Repeat

This ensures:
- Jobs are scheduled as soon as possible
- Metrics stay current
- State is persisted regularly

## Error Handling

### Exceptions

- **QueueManagerError**: Base exception
- **InvalidJobError**: Job not found or not queued
- **CircularDependencyError**: Dependency cycle detected

### Recovery

The queue manager is designed to be resilient:

- **Crash recovery**: State restored from database on restart
- **Failed jobs**: Automatically retried with backoff
- **Orphaned jobs**: Background worker detects and reschedules
- **Lock contention**: AsyncIO lock prevents race conditions

## Performance Considerations

### Scalability

The queue manager is designed to scale:

- **In-memory queues**: Fast O(log n) priority queue operations
- **Database persistence**: Async commits, indexed queries
- **Lock-free reads**: Status queries don't acquire locks
- **Batch updates**: Multiple jobs processed per cycle

### Bottlenecks

Potential bottlenecks:

1. **Scheduling interval**: Lower = more responsive, higher CPU
2. **Database commits**: Tunable trade-off (durability vs. throughput)
3. **Dependency checks**: O(n) per job, optimized with early termination
4. **Lock contention**: Minimal due to coarse-grained locking

### Optimization Tips

- Set `scheduling_interval` based on job duration (1-5 seconds typical)
- Use `enable_fair_share=False` if single user
- Batch enqueue operations when possible
- Use resource requirements only when needed

## Integration with Runners

Runners integrate with the queue manager:

```python
class Runner:
    async def execute_jobs(self):
        while self.running:
            # Request next job
            job_id = await self.queue_manager.dequeue(self.runner_type)

            if job_id:
                # Execute job
                try:
                    await self.run_job(job_id)
                    await self.queue_manager.handle_job_completion(
                        job_id, success=True
                    )
                except Exception as e:
                    await self.queue_manager.handle_job_completion(
                        job_id, success=False
                    )
            else:
                # No jobs available, wait
                await asyncio.sleep(5)
```

## Best Practices

### Job Submission

- Use appropriate priority levels (don't overuse CRITICAL)
- Set realistic resource requirements
- Specify dependencies explicitly
- Configure retry count based on job stability

### Cluster Management

- Set `max_concurrent_jobs` based on hardware capacity
- Pause queues before maintenance
- Monitor queue depth and adjust limits
- Use separate clusters for different job types

### Monitoring

- Check metrics regularly: `get_queue_status()`
- Alert on high failure rates (> 10%)
- Monitor average wait times
- Track queue depth trends

### Testing

- Test with mock runners for development
- Validate dependency chains work correctly
- Test failure and retry scenarios
- Verify persistence works across restarts

## Example Workflows

### Simple Serial Pipeline

```python
# Geometry optimization -> Frequency calculation -> Thermodynamics
opt = db.create_job("opt", "/work/opt", "OPTGEOM\n...")
freq = db.create_job("freq", "/work/freq", "FREQCALC\n...")
thermo = db.create_job("thermo", "/work/thermo", "...")

await qm.enqueue(opt, priority=Priority.HIGH)
await qm.enqueue(freq, dependencies=[opt], priority=Priority.HIGH)
await qm.enqueue(thermo, dependencies=[freq], priority=Priority.NORMAL)
```

### Parallel Independent Jobs

```python
# Multiple independent calculations
for structure in ["mgo", "cao", "sro"]:
    job_id = db.create_job(structure, f"/work/{structure}", "...")
    await qm.enqueue(job_id, priority=Priority.NORMAL)

# All run in parallel (up to cluster limit)
```

### Complex DAG

```python
# Diamond dependency pattern
#     opt
#    /   \
# freq   band
#    \   /
#   analysis

opt = db.create_job("opt", ...)
freq = db.create_job("freq", ...)
band = db.create_job("band", ...)
analysis = db.create_job("analysis", ...)

await qm.enqueue(opt)
await qm.enqueue(freq, dependencies=[opt])
await qm.enqueue(band, dependencies=[opt])
await qm.enqueue(analysis, dependencies=[freq, band])
```

### High-Throughput Screening

```python
# Screen 1000 structures
for i in range(1000):
    job_id = db.create_job(f"structure_{i}", ...)
    await qm.enqueue(
        job_id,
        priority=Priority.BACKGROUND,
        max_retries=5,  # Robust to failures
        user_id="screening_campaign"
    )

# Enable fair share for mixed workloads
qm_fair = QueueManager(db, enable_fair_share=True)
```

## Troubleshooting

### Jobs Not Scheduling

**Symptoms:** Jobs stay in QUEUED state indefinitely

**Possible Causes:**
1. Unsatisfied dependencies - check dependency status
2. Cluster at capacity - check `cluster.running_jobs`
3. Queue paused - check `cluster.paused`
4. Insufficient resources - check `cluster.available_resources`

**Debug:**
```python
status = qm.get_queue_status()
schedulable = await qm.schedule_jobs()
print(f"Schedulable: {schedulable}")
```

### High Failure Rate

**Symptoms:** Many jobs failing and retrying

**Possible Causes:**
1. Input file errors
2. Insufficient resources (memory, disk)
3. Runner configuration issues

**Mitigation:**
- Reduce max retries to fail fast
- Fix input file issues
- Increase cluster resources
- Check runner logs

### Queue Growing Unbounded

**Symptoms:** Queue depth keeps increasing

**Possible Causes:**
1. Job submission rate > completion rate
2. Runner not dequeuing jobs
3. Cluster limits too restrictive

**Solutions:**
- Increase `max_concurrent_jobs`
- Add more runner instances
- Reduce job submission rate
- Scale cluster capacity

### Circular Dependency Errors

**Symptoms:** `CircularDependencyError` on enqueue

**Cause:** Job dependencies form a cycle

**Solution:** Review dependency chain, ensure DAG structure

```python
# BAD: Circular
await qm.enqueue(job1, dependencies=[job2])
await qm.enqueue(job2, dependencies=[job1])  # Error!

# GOOD: DAG
await qm.enqueue(job1)
await qm.enqueue(job2, dependencies=[job1])
```

## Future Enhancements

Planned features for future versions:

- **Distributed scheduling**: Multi-node coordination
- **GPU scheduling**: First-class GPU resource management
- **Preemption**: Lower priority jobs can be paused
- **Backfill scheduling**: Fill idle slots with small jobs
- **Cost optimization**: Schedule based on compute cost
- **SLA enforcement**: Guarantee job completion times
- **Advanced fairness**: Multi-level fair share (user, group, project)

## References

- Database module: `src/core/database.py`
- Local runner: `src/runners/local.py`
- Unit tests: `tests/test_queue_manager.py`
- TUI integration: `tui/screens/job_list.py`
