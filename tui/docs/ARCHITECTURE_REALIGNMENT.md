# TUI Architecture Realignment

This document describes the architectural issues identified through AI cross-validation and the fixes applied.

## Background

On 2025-12-23, a comprehensive codebase analysis was performed using Gemini and Codex CLI tools. Both identified critical architectural issues in the TUI application.

## Issues Identified

### Critical: Production TUI Bypasses QueueManager

**Finding**: `app_enhanced.py` instantiates `LocalRunner` directly and bypasses the `QueueManager` and `Orchestrator` systems entirely.

**Impact**:
- No concurrency limits enforced
- No priority scheduling
- No dependency resolution
- No retry logic

**Status**: Partial fix applied. Full integration tracked in `crystalmath-7ta`.

### High: JobResult Type Mismatch (FIXED)

**Finding**: `LocalRunner.run_job()` yields strings during execution, then a `JobResult` object as the final yield. The handler in `app_enhanced.py` treated all yields as strings, calling `.rstrip()` on the `JobResult` which would cause `AttributeError`.

**Fix Applied** (`app_enhanced.py:479-491`):
```python
async for item in runner.run_job(job_id, work_dir):
    if isinstance(item, JobResult):
        result = item  # Capture directly
    else:
        self.post_message(JobLog(job_id, item))  # Only log strings
```

**Issue**: `crystalmath-vw3` - CLOSED

### High: Race Condition in get_last_result() (FIXED)

**Finding**: The code used `runner.get_last_result()` which stores results in shared state `_last_result`. With concurrent jobs, results would be overwritten.

**Fix Applied**: Capture `JobResult` directly from the async generator yield, eliminating dependency on shared state.

**Issue**: `crystalmath-b42` - CLOSED

### Medium: Tests Target Legacy App

**Finding**: Tests in `test_app.py` import and test `app.py` instead of the production `app_enhanced.py`.

**Status**: Open - `crystalmath-djc`

### Medium: Dead Code in backend.py

**Finding**: `tui/src/core/backend.py` is not referenced anywhere in the codebase.

**Status**: Open - `crystalmath-4y8`

### Low: FIX Comments Without Issues

**Finding**: `queue_manager.py` contains 4 `# FIX:` comments at lines 261, 271, 943, 1128.

**Status**: Open - `crystalmath-skp`

## Related Epics

### crystalmath-tai: TUI Architecture Realignment (P0)

Parent epic for all architecture fixes. Tasks:
- `7ta`: Wire app_enhanced.py to QueueManager (OPEN)
- `vw3`: Fix JobResult type mismatch (CLOSED)
- `b42`: Fix _last_result race condition (CLOSED)
- `djc`: Align tests with production entrypoint (OPEN)
- `4y8`: Remove/integrate dead backend.py (OPEN)
- `skp`: Address FIX comments in queue_manager.py (OPEN)

## Cross-Validation Process

1. **Gemini CLI** performed initial codebase investigation
2. **Codex CLI** validated findings and discovered additional issues
3. Issues were created/updated in bd (beads) issue tracker
4. Critical bugs were fixed immediately
5. Remaining work tracked for future sprints

## Files Modified

- `tui/src/tui/app_enhanced.py`: Added JobResult import, fixed _run_crystal_job to handle mixed yield types
- `tui/docs/ARCHITECTURE_REALIGNMENT.md`: This document
- `tui/docs/QE_VASP_SUPPORT.md`: QE/VASP support documentation

## Test Results

After fixes: **880 passed**, 19 skipped, 54 warnings
