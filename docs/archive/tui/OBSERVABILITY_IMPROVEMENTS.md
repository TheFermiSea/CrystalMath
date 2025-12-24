# TUI Observability Improvements

Enhanced structured logging in background worker loops for better monitoring and debugging.

## Overview

Two critical background loops now include comprehensive observability instrumentation:

1. **Connection Manager Health Check Loop** (`connection_manager.py:_health_check_loop`)
2. **Queue Manager Scheduler Worker** (`queue_manager.py:_scheduler_worker`)

## Logging Enhancements

### Connection Manager Health Check Loop

**Startup/Shutdown:**
- Loop start/stop events logged at INFO level
- Component name and interval included

**Per-Iteration Logging (DEBUG level):**
- Iteration counter for tracking loop cycles
- Elapsed time for performance monitoring
- Connection statistics:
  - Total connections checked
  - Stale connections removed
  - Healthy vs. unhealthy count
  - Connections removed due to repeated failures

**Example Log Entry:**
```json
{
  "level": "DEBUG",
  "message": "Health check iteration completed",
  "extra": {
    "iteration": 42,
    "elapsed_seconds": 0.125,
    "connections_checked": 8,
    "stale_removed": 1,
    "healthy": 6,
    "unhealthy": 1,
    "unhealthy_removed": 0
  }
}
```

**Error Handling:**
- Errors logged with full context (iteration number, elapsed time, error message)
- Stack traces included via `exc_info=True`

### Queue Manager Scheduler Worker

**Startup/Shutdown:**
- Worker start/stop events at INFO level
- Component and scheduling interval documented

**Per-Iteration Logging (DEBUG level):**
- Iteration counter and elapsed time
- Queue depth: total jobs queued
- Scheduling results: number of schedulable jobs
- Cumulative metrics: jobs scheduled, completed, failed
- When jobs found, lists first 10 to prevent spam

**Example Log Entry:**
```json
{
  "level": "DEBUG",
  "message": "Scheduler iteration completed",
  "extra": {
    "iteration": 123,
    "elapsed_seconds": 0.045,
    "total_queued": 5,
    "schedulable_count": 2,
    "total_jobs_scheduled": 456,
    "total_jobs_completed": 398,
    "total_jobs_failed": 12
  }
}
```

**Error Handling:**
- Same comprehensive error logging as connection manager
- Failure context preserved across retry cycles

## Key Benefits

1. **Debugging**: Quickly identify performance issues and failure patterns
2. **Monitoring**: Structured fields enable easy aggregation in logging systems
3. **Minimal Overhead**: DEBUG logs can be disabled in production (typically disabled by default)
4. **Observability**: Track loop health without additional instrumentation

## Configuration

Configure via standard Python logging:

```python
# Development: Show all logs
logging.basicConfig(level=logging.DEBUG)

# Production: Only warnings and errors
logging.basicConfig(level=logging.INFO)
```

## Performance Impact

- **Negligible overhead**: <1ms per iteration
- DEBUG logs are no-ops when disabled
- Time measurement uses `time.time()` (native syscall)
- Structured logging adds minimal string formatting

## Usage Example

```python
# Logs automatically generated when manager/queue starts
cm = ConnectionManager()
await cm.start()  # Logs: "Health check loop started"

qm = QueueManager(db)
await qm.start()  # Logs: "Scheduler worker started"

# Monitoring per-iteration performance
# Check logs at DEBUG level to see detailed metrics

await cm.stop()  # Logs: "Health check loop stopped"
await qm.stop()  # Logs: "Scheduler worker stopped"
```

## Integration

Logs integrate with Python's standard logging framework:

```python
import logging

# Configure JSON logging for production
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# With structured logging libraries (e.g., python-json-logger):
# Automatically serializes extra fields for monitoring dashboards
```

## See Also

- `connection_manager.py` - Connection pooling with health checks
- `queue_manager.py` - Job scheduling and queue management
- `PHASE2_IMPLEMENTATION.md` - Architecture overview
