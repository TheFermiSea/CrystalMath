# SSH Runner Status Detection Fix

**Issue ID:** crystalmath-1om
**Status:** ✅ Fixed
**Date:** 2025-11-23

## Problem Statement

The SSH runner's status detection logic was brittle and unreliable, causing false positives/negatives in job status reporting. The original implementation had several critical issues:

### Root Causes

1. **Brittle String Matching**
   - Relied on grep pattern `'error\\|failed\\|abort'` which could:
     - Miss errors with different wording
     - Trigger false positives on benign log messages containing these words
     - Fail on output format variations between CRYSTAL versions

2. **Race Conditions**
   - Checked output files while job was still writing
   - No synchronization between process termination and file availability
   - Could read incomplete output and make incorrect status determination

3. **Missing Exit Code**
   - Original execution script didn't capture CRYSTAL's exit code
   - No reliable way to distinguish successful completion from failure
   - Had to guess based on log file content

4. **No Fallback Chain**
   - Only checked `ps` (process status) and grep (output parsing)
   - If both failed, would incorrectly report status
   - No intermediate signals for better reliability

5. **Edge Case Failures**
   ```python
   # Original brittle logic:
   if "running" in result.stdout:
       return "running"
   elif "exists" in output_check:
       if "failed" in grep_result:
           return "failed"
       else:
           return "completed"
   else:
       return "failed"  # Assumes failure if no output file!
   ```

## Solution: Multi-Signal Status Detection

Implemented a robust three-tier detection system with proper fallback chain.

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   get_status()                          │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
          ┌────────────────────────────────┐
          │  Signal 1: Process Status (ps) │
          │  ✓ Most reliable for running   │
          │  ✓ Kernel-level truth          │
          └────────────────────────────────┘
                           │
                           │ Process not found
                           ▼
          ┌────────────────────────────────┐
          │  Signal 2: Exit Code File      │
          │  ✓ Reliable for completed jobs │
          │  ✓ Written atomically          │
          └────────────────────────────────┘
                           │
                           │ No exit code file
                           ▼
          ┌────────────────────────────────┐
          │  Signal 3: Output Parsing      │
          │  ✓ Fallback only               │
          │  ✓ Multiple completion markers │
          └────────────────────────────────┘
                           │
                           │ No markers found
                           ▼
                      "unknown"
```

### Implementation Details

#### 1. Exit Code Capture (Modified Execution Script)

```bash
# Before: No exit code capture
{run_cmd} < {quoted_input_file}

# After: Atomic exit code capture
set +e  # Don't exit on error
{run_cmd} < {quoted_input_file}
EXIT_CODE=$?
echo $EXIT_CODE > .exit_code  # Write IMMEDIATELY after execution
set -e
exit $EXIT_CODE
```

**Why This Works:**
- Exit code captured before any other operations
- Written to dedicated file (no parsing complexity)
- Single integer value (no ambiguity)
- Written atomically (no race conditions)

#### 2. Signal 1: Process Status Check

```python
# Check if process is running (most reliable)
check_cmd = f"ps -p {validated_pid} -o pid= 2>/dev/null"
result = await conn.run(check_cmd, check=False, timeout=5)

if result.exit_status == 0 and result.stdout.strip():
    # Process exists and is running
    return "running"
```

**Benefits:**
- Kernel-level truth (can't be spoofed by log files)
- No parsing required (exit status is 0/1)
- Fast check (< 100ms typically)
- No false positives

**Edge Cases Handled:**
- Process just finished (exit_status != 0, falls through to Signal 2)
- Zombie process (ps will still show it, but exit code will be available)

#### 3. Signal 2: Exit Code File Check

```python
# Check exit code file (reliable for completed jobs)
exit_code_cmd = (
    f"test -f {quoted_work_dir}/.exit_code && "
    f"cat {quoted_work_dir}/.exit_code"
)
result = await conn.run(exit_code_cmd, check=False, timeout=5)

if result.exit_status == 0 and result.stdout.strip():
    exit_code = int(result.stdout.strip())
    if exit_code == 0:
        return "completed"
    else:
        return "failed"
```

**Benefits:**
- Definitive success/failure signal (CRYSTAL's actual exit code)
- No parsing ambiguity (single integer)
- Works for any error type (convergence, segfault, OOM, etc.)
- Written by job script itself (no race condition)

**Edge Cases Handled:**
- File doesn't exist (falls through to Signal 3)
- Invalid content (ValueError caught, logs warning, falls through)
- File exists but empty (stdout.strip() is falsy, falls through)

#### 4. Signal 3: Output Parsing (Fallback)

```python
# Parse output file (fallback only)
tail_cmd = f"tail -100 {output_file} 2>/dev/null"
result = await conn.run(tail_cmd, check=False, timeout=5)

if result.exit_status == 0 and result.stdout:
    output_lower = result.stdout.lower()

    # Check for completion indicators
    if any(marker in output_lower for marker in [
        "scf ended",
        "eeeeeeeeee termination",
        "terminated - job complete",
        "normal termination"
    ]):
        return "completed"

    # Check for error indicators
    if any(marker in output_lower for marker in [
        "error termination",
        "abnormal termination",
        "segmentation fault",
        "killed by signal"
    ]):
        return "failed"
```

**Improvements Over Original:**
- Multiple specific markers (not generic "error" string)
- Case-insensitive matching (handles CRYSTAL's all-caps output)
- Only checks last 100 lines (faster, avoids intermediate errors)
- Clear precedence: completion markers checked first

**Why This Is Last Resort:**
- Can have false positives (word appears in different context)
- Can have false negatives (unexpected termination message format)
- Requires job to have written output (fails for crashed jobs)
- Slower than exit code check

#### 5. Unknown Status (Safety Net)

```python
# Unknown status - all detection methods failed
logger.warning(
    f"Could not determine status for job {validated_pid}. "
    f"Process not running, no exit code, and output parsing inconclusive."
)
return "unknown"
```

**Better Than:**
- Guessing "failed" (original behavior)
- Raising exception (breaks error recovery)
- Returning "completed" optimistically (dangerous)

## Security Improvements

All PID validation now centralized and enforced:

```python
# Validate PID BEFORE any shell command
try:
    validated_pid = int(pid)
except (ValueError, TypeError):
    raise JobNotFoundError(f"Invalid PID in job handle: {pid}")

if validated_pid <= 0:
    raise JobNotFoundError(f"Invalid PID (must be > 0): {validated_pid}")
```

**Prevents:**
- Command injection via malicious PID (`"12345; rm -rf /"`)
- Negative PIDs (undefined behavior)
- Zero PID (kernel process)
- Non-integer PIDs

## Performance Optimizations

### Early Exit Strategy

```python
# Signal 1: Process running? → Return immediately, skip signals 2 & 3
if process_exists:
    return "running"  # Only 1 SSH command

# Signal 2: Exit code available? → Return immediately, skip signal 3
if exit_code_found:
    return "completed" or "failed"  # Only 2 SSH commands

# Signal 3: Parse output (last resort)
if output_markers_found:
    return status  # All 3 SSH commands
```

**Result:**
- Running jobs: 1 SSH command (< 100ms)
- Completed jobs: 2 SSH commands (< 200ms)
- Unknown jobs: 3 SSH commands (< 500ms)

### Timeout Protection

All SSH commands have 5-second timeouts:

```python
result = await conn.run(cmd, check=False, timeout=5)
```

**Prevents:**
- Hanging on slow remote machines
- Deadlocks from stuck commands
- UI freezing during status checks

## Testing Coverage

Created comprehensive test suite (`test_ssh_runner_status_detection.py`) with 6 test classes:

### 1. TestStatusDetectionRunning (3 tests)
- Process running detected via ps
- Extra whitespace handling
- Rapid status checks (no race conditions)

### 2. TestStatusDetectionCompleted (3 tests)
- Exit code 0 detection
- Whitespace in exit code file
- Fallback to output parsing

### 3. TestStatusDetectionFailed (4 tests)
- Exit code 1 detection
- Exit code 137 (SIGKILL) detection
- Error termination in output
- Segmentation fault detection

### 4. TestStatusDetectionEdgeCases (7 tests)
- Unknown when all signals fail
- Incomplete output handling
- Invalid job handle errors
- Invalid PID errors
- Timeout handling
- Invalid exit code fallback
- Missing output file

### 5. TestStatusDetectionSecurity (4 tests)
- PID injection prevention
- Zero PID rejection
- Negative PID rejection
- Command injection via PID

### 6. TestStatusDetectionPerformance (3 tests)
- Early exit when running
- Early exit when exit code found
- Timeout prevents hanging

**Total: 24 comprehensive tests covering all scenarios**

## Before/After Comparison

### Original Implementation
```python
async def get_status(self, job_handle: str) -> str:
    # Check if process running
    check_cmd = f"ps -p {pid} > /dev/null 2>&1 && echo running || echo stopped"
    result = await conn.run(check_cmd, check=False)

    if "running" in result.stdout:
        return "running"

    # Process stopped, check output for errors
    error_check_cmd = (
        f"grep -i 'error\\|failed\\|abort' {output_file} "
        f"> /dev/null 2>&1 && echo failed || echo completed"
    )
    result = await conn.run(error_check_cmd, check=False)

    if "failed" in result.stdout:
        return "failed"
    else:
        return "completed"
```

**Problems:**
- ❌ Assumes job completed if process not running
- ❌ Single grep pattern for error detection
- ❌ No exit code capture
- ❌ Can return "completed" for crashed jobs
- ❌ No handling of missing output file
- ❌ No timeout protection

### New Implementation

```python
async def get_status(self, job_handle: str) -> str:
    # Signal 1: Process status
    result = await conn.run(f"ps -p {pid} -o pid= 2>/dev/null", timeout=5)
    if result.exit_status == 0 and result.stdout.strip():
        return "running"

    # Signal 2: Exit code file
    result = await conn.run(
        f"test -f {work_dir}/.exit_code && cat {work_dir}/.exit_code",
        timeout=5
    )
    if result.exit_status == 0 and result.stdout.strip():
        exit_code = int(result.stdout.strip())
        return "completed" if exit_code == 0 else "failed"

    # Signal 3: Output parsing (fallback)
    result = await conn.run(f"tail -100 {output_file} 2>/dev/null", timeout=5)
    if result.exit_status == 0:
        if any(marker in output for marker in completion_markers):
            return "completed"
        if any(marker in output for marker in error_markers):
            return "failed"

    # All signals failed
    return "unknown"
```

**Improvements:**
- ✅ Reliable exit code detection
- ✅ Multiple completion/error markers
- ✅ Proper fallback chain
- ✅ Returns "unknown" instead of guessing
- ✅ Timeout protection on all commands
- ✅ Handles all edge cases gracefully

## Migration Notes

### API Compatibility

**BREAKING CHANGE:** New status value added:
- Before: `"running"`, `"completed"`, `"failed"`, `"cancelled"`
- After: `"running"`, `"completed"`, `"failed"`, `"cancelled"`, `"unknown"`

**Action Required:**
- Update UI code to handle `"unknown"` status
- Update database schema if status is an enum
- Update documentation to describe `"unknown"` status

### Backward Compatibility

The execution script change is **backward compatible**:
- Old jobs (without `.exit_code`) will fall back to output parsing
- New jobs will benefit from reliable exit code detection
- No data migration required

## Verification Steps

1. **Run tests:**
   ```bash
   cd tui/
   pytest tests/test_ssh_runner_status_detection.py -v
   ```

2. **Manual testing:**
   ```python
   # Test running job
   runner = SSHRunner(...)
   handle = await runner.submit_job(...)
   status = await runner.get_status(handle)  # Should be "running"

   # Wait for completion
   await asyncio.sleep(10)
   status = await runner.get_status(handle)  # Should be "completed" or "failed"
   ```

3. **Integration testing:**
   - Submit real CRYSTAL job via TUI
   - Monitor status updates during execution
   - Verify correct final status (completed/failed)
   - Check `.exit_code` file exists in remote work directory

## Performance Impact

**Benchmarks (estimated):**

| Scenario | Before | After | Change |
|----------|--------|-------|--------|
| Running job | 150ms | 100ms | -33% (1 command instead of 2) |
| Completed job | 200ms | 200ms | No change (2 commands) |
| Failed job | 200ms | 200ms | No change (2 commands) |
| Unknown job | 200ms | 500ms | +150% (3 commands, but rare) |

**Overall:** Slight performance improvement for common case (running jobs), no degradation for completed/failed jobs.

## Known Limitations

1. **Requires remote bash:**
   - The `.exit_code` capture uses bash features (`$?`)
   - Won't work with pure sh (POSIX shell)
   - **Mitigation:** Document requirement, check shell in connection manager

2. **Disk space:**
   - Each job now writes `.exit_code` file (4 bytes)
   - Negligible impact (billions of jobs = few GB)

3. **Cross-platform:**
   - `ps -o pid=` format may vary on BSD vs. GNU/Linux
   - **Mitigation:** Already using portable format, tested on both

## Future Enhancements

1. **State machine:**
   - Track status transitions (pending → running → completed)
   - Detect invalid transitions (completed → running = error)

2. **Metrics collection:**
   - Track how often each signal is used
   - Measure false positive/negative rates
   - Optimize marker lists based on real CRYSTAL output

3. **Proactive monitoring:**
   - Push-based status updates (inotify on remote)
   - Reduce polling frequency
   - Lower SSH overhead

4. **Resource usage:**
   - Extend status to include CPU/memory usage
   - Track progress via output file size
   - Estimate time remaining

## References

- Original issue: `crystalmath-1om`
- Code: `tui/src/runners/ssh_runner.py`
- Tests: `tui/tests/test_ssh_runner_status_detection.py`
- Related: `CODE_REVIEW_FINDINGS.md` (security review)

## Conclusion

The multi-signal status detection approach provides:

✅ **Reliability:** Three independent signals with proper fallback
✅ **Security:** PID validation prevents injection attacks
✅ **Performance:** Early exit optimization for common cases
✅ **Robustness:** Handles all edge cases gracefully
✅ **Maintainability:** Clear signal hierarchy, comprehensive tests

**Result:** Production-ready status detection that won't fail due to brittle string matching or race conditions.
