# SSH Status Detection - Quick Reference

**Issue:** crystalmath-1om
**Status:** ✅ FIXED
**Tests:** 22/22 passing

## How It Works

```
Job Status Check (get_status)
       ↓
┌──────────────────────┐
│ Signal 1: ps -p PID  │ ← Most reliable (kernel-level)
└──────────────────────┘
       ↓ (not running)
┌──────────────────────┐
│ Signal 2: .exit_code │ ← Definitive success/failure
└──────────────────────┘
       ↓ (no exit code)
┌──────────────────────┐
│ Signal 3: tail -100  │ ← Fallback (output parsing)
└──────────────────────┘
       ↓ (all failed)
    "unknown"
```

## Status Values

| Status | Meaning | Detection Method |
|--------|---------|------------------|
| `running` | Job is executing | Process exists (ps) |
| `completed` | Job finished successfully | Exit code = 0 |
| `failed` | Job finished with error | Exit code ≠ 0 OR error markers |
| `cancelled` | Job was killed by user | Set by cancel_job() |
| `unknown` | Cannot determine status | All detection methods failed |

## Exit Code File

Every job now writes `.exit_code` in its work directory:

```bash
# In remote work dir after job completes:
$ cat .exit_code
0  # Success

$ cat .exit_code
1  # Failure
```

This file is written IMMEDIATELY after CRYSTAL exits, providing a reliable status signal.

## Error vs Completion Markers

**Checked in this order (error first to prevent false positives):**

### Error Markers (checked first)
- `error termination`
- `abnormal termination`
- `segmentation fault`
- `killed by signal`

### Completion Markers (checked second)
- `scf ended`
- `eeeeeeeeee termination`
- `terminated - job complete`
- `normal termination`

**Why order matters:** "abnormal termination" contains "termination", so we check for errors before checking for generic termination markers.

## Performance

| Scenario | SSH Commands | Typical Time |
|----------|--------------|--------------|
| Running job | 1 | ~100ms |
| Completed job | 2 | ~200ms |
| Failed job | 2 | ~200ms |
| Unknown job | 3 | ~500ms |

All commands have 5-second timeout protection.

## Security

All PIDs validated before use:
```python
validated_pid = int(pid)  # ValueError if not integer
if validated_pid <= 0:    # Reject zero/negative
    raise JobNotFoundError
```

Prevents command injection:
- ❌ `"12345; rm -rf /"` → ValueError
- ❌ `"-1"` → JobNotFoundError
- ❌ `"0"` → JobNotFoundError
- ✅ `"12345"` → Accepted

## Testing

Run tests:
```bash
cd tui/
pytest tests/test_ssh_runner_status_detection.py -v
```

Expected: 22 passed

Test coverage:
- ✅ Running process detection
- ✅ Exit code 0 (success)
- ✅ Exit code non-zero (failure)
- ✅ Output parsing fallback
- ✅ Race conditions (rapid polling)
- ✅ Timeouts
- ✅ Invalid PIDs
- ✅ Command injection prevention

## Troubleshooting

### Job shows "unknown" status

**Possible causes:**
1. Remote connection issue (can't reach SSH)
2. Process crashed without writing exit code
3. Output file doesn't exist or is empty
4. Output format unexpected (no markers found)

**Debug steps:**
```bash
# Check remote work directory
ssh user@host "ls -la /path/to/job_dir"

# Check exit code file
ssh user@host "cat /path/to/job_dir/.exit_code"

# Check output file
ssh user@host "tail -100 /path/to/job_dir/output.log"
```

### Job shows "completed" but actually failed

**Check:**
1. Exit code file: `cat .exit_code` (should be 0 for success)
2. Output file: Look for CRYSTAL error messages

This should NOT happen with the new implementation (exit code is definitive).

### Job shows "running" after it finished

**Likely cause:** Zombie process (ps shows it but it's actually dead)

**Verify:**
```bash
# Check process state
ssh user@host "ps -p PID -o state="
# Z = zombie, R = running, S = sleeping
```

Zombie processes will have exit code file, so status should be correct on next poll.

## Code Location

**Implementation:**
- `tui/src/runners/ssh_runner.py` (lines 209-332, 647-654)

**Tests:**
- `tui/tests/test_ssh_runner_status_detection.py` (22 tests)

**Documentation:**
- `SSH_STATUS_DETECTION_FIX.md` (complete details)
- `SSH_STATUS_FIX_SUMMARY.md` (change summary)
- `SSH_STATUS_QUICK_REF.md` (this file)

## Breaking Changes

**New status value:** `"unknown"`

**UI code must handle it:**
```python
STATUS_ICONS = {
    "running": "▶",
    "completed": "✓",
    "failed": "✗",
    "cancelled": "⊘",
    "unknown": "❓"  # NEW
}
```

## Migration

**Automatic for new jobs** - No action required

**Old jobs (no .exit_code):**
- Will fall back to output parsing
- Still works, just less reliable
- No data migration needed

## Example Usage

```python
from src.runners.ssh_runner import SSHRunner

runner = SSHRunner(connection_manager, cluster_id=1)

# Submit job
handle = await runner.submit_job(job_id=1, work_dir=Path("/tmp"), input_file=Path("input.d12"))

# Check status (will return "running" initially)
status = await runner.get_status(handle)
# → "running" (Signal 1: process exists)

# Wait a bit...
await asyncio.sleep(60)

# Check again (job completed)
status = await runner.get_status(handle)
# → "completed" (Signal 2: exit code = 0)

# Or if job failed
status = await runner.get_status(handle)
# → "failed" (Signal 2: exit code = 1)
```

## Key Takeaways

✅ **Reliable:** Exit code is definitive, not guessed from logs
✅ **Fast:** Early exit optimization (1-2 commands typically)
✅ **Robust:** Handles race conditions, timeouts, edge cases
✅ **Secure:** PID validation prevents injection
✅ **Tested:** 22 comprehensive tests, 100% pass rate

**Result: Production-ready status detection**
