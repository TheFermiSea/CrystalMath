# N+1 Query Problem Fix: Queue Manager

**Issue:** crystalmath-02y
**Status:** Fixed
**Date:** 2025-11-21

## Problem Summary

The queue manager's `schedule_jobs()` method had a critical N+1 query problem that degraded performance as the job queue grew:

```python
# OLD CODE (SLOW - O(n) queries per cycle):
async def schedule_jobs(self) -> List[int]:
    for job_id, queued_job in self._jobs.items():
        db_job = self.db.get_job(job_id)  # ← 1 query per job!
        if not db_job or db_job.status not in ("PENDING", "QUEUED"):
            continue
        # ... rest of logic ...
```

**Impact:**
- With 100 jobs in queue: 100 database queries per scheduling cycle
- With 10 scheduling cycles per second: 1,000 queries/second
- Database becomes bottleneck; scheduler latency increases with queue size

## Solution

Implemented **batch query optimization** with in-memory caching:

### 1. Added Batch Query Method to Database

**File:** `tui/src/core/database.py`

```python
def get_job_statuses_batch(self, job_ids: List[int]) -> Dict[int, str]:
    """
    Get statuses for multiple jobs in a single batch query.

    Args:
        job_ids: List of job IDs to fetch statuses for

    Returns:
        Dictionary mapping job_id -> status string
    """
    if not job_ids:
        return {}

    placeholders = ','.join('?' * len(job_ids))
    cursor = self.conn.execute(
        f"SELECT id, status FROM jobs WHERE id IN ({placeholders})",
        job_ids
    )
    return {row[0]: row[1] for row in cursor.fetchall()}
```

**Key Features:**
- Single SQL query instead of N individual queries
- Parameterized query to prevent SQL injection
- Returns dictionary for O(1) lookup

### 2. Updated Scheduler to Use Batch Query

**File:** `tui/src/core/queue_manager.py`

```python
# NEW CODE (FAST - O(1) queries per cycle):
async def schedule_jobs(self) -> List[int]:
    schedulable: List[Tuple[QueuedJob, float]] = []

    # OPTIMIZATION: Batch query all job statuses instead of individual queries
    job_ids = list(self._jobs.keys())
    job_statuses = self._get_job_statuses_batch(job_ids)

    for job_id, queued_job in self._jobs.items():
        # Check job status from batch query cache (O(1) lookup)
        status = job_statuses.get(job_id)
        if not status or status not in ("PENDING", "QUEUED"):
            continue
        # ... rest of logic ...
```

### 3. Added In-Memory Status Cache

**File:** `tui/src/core/queue_manager.py`

```python
def __init__(self, ...):
    # In-memory status cache (optimization for N+1 queries)
    # Maps job_id -> (status, timestamp)
    self._status_cache: Dict[int, Tuple[str, datetime]] = {}
    self._cache_ttl_seconds = 0.1  # Cache expires after 100ms
```

**Cache Invalidation:**
- `_invalidate_status_cache(job_id)` - Clear specific job from cache
- `_invalidate_status_cache(None)` - Clear entire cache
- Called whenever job status changes (enqueue, dequeue, completion)

## Performance Improvements

### Benchmark Results

**Single Query vs Multiple Queries (20 jobs, 100 cycles):**
```
Individual queries: 0.0190s
Batch query:        0.0021s
Speedup:            8.9x
```

**Scaling Test (100 cycles each):**
```
Jobs     Individual   Batch        Speedup
5        0.0005s      0.0001s      4.2x
10       0.0009s      0.0002s      6.1x
20       0.0019s      0.0002s      8.7x
50       0.0049s      0.0005s      10.6x
```

**Real-world Scenario (100 jobs, 10 scheduling cycles):**
```
Total time: 0.1332s
Average per cycle: 0.0133s
```

### Complexity Analysis

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Queries per cycle | O(n) | O(1) | n× faster |
| 10 jobs, 1 cycle | 10 queries | 1 query | 10× |
| 100 jobs, 1 cycle | 100 queries | 1 query | 100× |
| 100 jobs, 10 cycles | 1,000 queries | 10 queries | 100× |

## Implementation Details

### Files Modified

1. **tui/src/core/database.py**
   - Added `get_job_statuses_batch()` method
   - Single parameterized query for multiple job IDs
   - Returns dictionary for O(1) lookups

2. **tui/src/core/queue_manager.py**
   - Added `_status_cache` dictionary
   - Added `_cache_ttl_seconds` configuration
   - Added `_get_job_statuses_batch()` wrapper method
   - Added `_invalidate_status_cache()` invalidation method
   - Updated `schedule_jobs()` to use batch query
   - Added cache invalidation to `enqueue()`, `dequeue()`, `handle_job_completion()`

### Files Added

**tui/tests/test_queue_manager_performance.py** (700+ lines)
- 4 tests for batch query method
- 6 tests for queue manager optimization
- 2 performance benchmark tests
- 1 real-world scenario test
- All tests passing

## Testing

All 13 performance tests pass:

```bash
source .venv/bin/activate
cd tui
python -m pytest tests/test_queue_manager_performance.py -v

====== 13 passed in 0.26s ======
```

### Test Coverage

1. **Batch Query Tests**
   - Empty list handling
   - Single job query
   - Multiple jobs with different statuses
   - Non-existent job handling

2. **Queue Manager Tests**
   - Batch query usage verification
   - Query complexity improvement
   - Cache invalidation on enqueue
   - Cache invalidation on dequeue
   - Cache invalidation on completion
   - Full cache clearing

3. **Performance Tests**
   - Single query vs multiple queries
   - Scaling with queue size
   - Real-world scenario (100 jobs × 10 cycles)

4. **Benchmark Results**
   - 8.9× speedup (20 jobs)
   - Up to 10.6× speedup (50 jobs)
   - Consistent improvement across all queue sizes

## Success Criteria

✅ Batch query method added to Database class
✅ Scheduler uses batch query instead of per-job queries
✅ Performance tests show improvement
✅ O(1) queries per tick instead of O(n)
✅ Cache invalidation implemented
✅ All tests passing (13/13)
✅ Real-world scenario completes in 0.13s for 100 jobs

## Migration Notes

No breaking changes. The optimization is transparent to callers:
- `schedule_jobs()` still returns the same result
- Public API unchanged
- Database schema unchanged
- Fully backward compatible

## Future Optimizations

1. **TTL-based Cache**: Implement time-based cache expiration for read-only scenarios
2. **Event-driven Updates**: Subscribe to status change events instead of polling
3. **Async Database**: Use async SQLite driver for non-blocking queries
4. **Connection Pooling**: Use connection pool for concurrent database access

## Related Issues

- **crystalmath-02y**: N+1 query problem in queue manager (FIXED)
- **crystalmath-031**: Scheduler performance optimization (related)

## References

- N+1 Query Problem: https://en.wikipedia.org/wiki/N%2B1_problem
- Database Query Optimization: SQLite performance best practices
- Batch Operations: Parameterized queries and query consolidation
