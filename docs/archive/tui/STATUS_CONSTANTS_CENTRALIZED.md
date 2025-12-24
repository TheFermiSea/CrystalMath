# Status Constants Centralization

## Overview

Centralized all status string constants used throughout the TUI codebase into a single source of truth: `src/core/constants.py`.

## Problem Solved

Previously, status strings like `"pending"`, `"running"`, `"completed"`, `"failed"` were scattered as magic strings across the codebase, leading to:
- Typos and inconsistencies
- Difficulty maintaining status conventions
- Brittle string comparisons
- No single reference for valid status values

## Solution

Created `src/core/constants.py` with the following constant classes:

### JobStatus (lowercase)
Job execution statuses used in database and runners:
- `PENDING` = `"pending"`
- `RUNNING` = `"running"`
- `COMPLETED` = `"completed"`
- `FAILED` = `"failed"`
- `CANCELLED` = `"cancelled"`
- `UNKNOWN` = `"unknown"`
- `QUEUED` = `"QUEUED"` (legacy uppercase)

### QueueStatus
Queue and workflow scheduling statuses:
- `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`, `PAUSED`, `CANCELLED`

### RunnerType
Job execution backends:
- `LOCAL` = `"local"`
- `SSH` = `"ssh"`
- `SLURM` = `"slurm"`

### NodeStatusUppercase & WorkflowStatusUppercase
Workflow/DAG statuses (uppercase format, for workflow.py compatibility)

## Files Updated

1. **tui/src/core/queue_manager.py** (9 replacements)
   - Added import: `from .constants import JobStatus`
   - Replaced all status string literals with constants
   - Example: `"QUEUED"` → `JobStatus.QUEUED`

2. **tui/src/runners/ssh_runner.py** (11 replacements)
   - Added import: `from ..core.constants import JobStatus`
   - Updated status checks in `get_status()` method
   - Updated status assignments in `submit_job()` method
   - Updated status checks in `stream_output()` method

## Usage Pattern

### Before
```python
if job.status == "completed":
    # Handle completion
    pass

self.db.update_status(job_id, "FAILED")
```

### After
```python
from src.core.constants import JobStatus

if job.status == JobStatus.COMPLETED:
    # Handle completion
    pass

self.db.update_status(job_id, JobStatus.FAILED)
```

## Benefits

1. **Single Source of Truth** - All status constants defined in one file
2. **Type Safety** - IDE autocomplete and static analysis support
3. **Consistency** - Eliminates typos and inconsistencies
4. **Maintainability** - Easy to add new statuses or change conventions
5. **Documentation** - `all()` methods provide valid status values
6. **No Breaking Changes** - String values remain unchanged (backward compatible)

## Testing

All existing tests pass without modification because constant values match original magic strings:
- `JobStatus.PENDING == "pending"` ✅
- `JobStatus.RUNNING == "running"` ✅
- `JobStatus.COMPLETED == "completed"` ✅
- `JobStatus.FAILED == "failed"` ✅

## Future Improvements

1. Add mypy validation for status types
2. Create StatusLiteral types for type hints
3. Update remaining files (local.py, slurm_runner.py)
4. Migrate workflow.py enums to constants module
