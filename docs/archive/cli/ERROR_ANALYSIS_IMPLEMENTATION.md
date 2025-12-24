# Error Analysis System Implementation

**Status:** ✅ Complete
**Task ID:** CRY_CLI-wil
**Date:** 2025-11-19

## Overview

Implemented automatic error analysis system for CRYSTAL23 calculations that detects common failure patterns and provides student-friendly diagnostic messages and solutions.

## Implementation Summary

### 1. Core Function - `analyze_failure()`

**Location:** `/Users/briansquires/Ultrafast/CRY_CLI/lib/cry-exec.sh` (lines 77-149)

**Functionality:**
- Analyzes CRYSTAL23 output files for common error patterns
- Provides educational, student-friendly error messages
- Works with or without `gum` (graceful fallback)
- Returns 0 always (analysis is informational, doesn't affect exit codes)

**Error Patterns Detected:**
1. **SCF Divergence** - Matches "DIVERGENCE" or "SCF NOT CONVERGED"
2. **Memory Errors** - Matches "insufficient memory", "SIGSEGV", or "Segmentation fault"
3. **Basis Set Errors** - Matches combination of "BASIS SET" and "ERROR"
4. **Unknown Errors** - Fallback message for unrecognized patterns

### 2. Integration with `exec_crystal_run()`

**Location:** `/Users/briansquires/Ultrafast/CRY_CLI/lib/cry-exec.sh` (lines 226-247)

**Behavior:**
- Automatically called when calculation exits with non-zero status
- Runs `analyze_failure()` on the output file
- Displays last 20 lines of error log with styled border (gum) or plain text
- Logs failure to `cry_log` system

**Example Output:**
```
⚠️  Detected SCF Divergence
The calculation is unstable. Try:
1. Check your geometry (atoms too close?)
2. Use a better initial guess (GUESSP)
3. Increase FMIXING (e.g., FMIXING 30)

╔══════════════════════════════════════╗
║  Error Log (Last 20 lines)           ║
╚══════════════════════════════════════╝
[last 20 lines of output file]
```

### 3. Test Coverage

**Unit Tests:** `/Users/briansquires/Ultrafast/CRY_CLI/tests/unit/error_analysis_test.bats`
- 15 comprehensive test cases
- 100% pattern coverage
- Tests edge cases (missing files, empty files, multiple patterns)
- Validates educational tone and message quality

**Integration Tests:** `/Users/briansquires/Ultrafast/CRY_CLI/tests/integration/error_analysis_integration_test.bats`
- 3 integration test cases
- Validates module loading and function availability
- Tests pattern detection in realistic scenarios

**Test Results:** ✅ All 18 tests passing

### 4. Documentation

**Troubleshooting Guide:** `/Users/briansquires/Ultrafast/CRY_CLI/docs/TROUBLESHOOTING.md`

Comprehensive guide covering:
- Automatic error analysis overview
- Detailed solutions for each error type
- Example input file fixes
- Advanced troubleshooting techniques
- File staging workflow

## Technical Details

### Pattern Matching Strategy

Uses `grep -q` for silent, efficient pattern matching:
```bash
if grep -q "DIVERGENCE" "$logfile" || grep -q "SCF NOT CONVERGED" "$logfile"; then
    # Handle SCF divergence
fi
```

**Design Decisions:**
- **First match wins** - Stops at first detected pattern (prevents mixed messages)
- **Case-sensitive** - Matches exact error strings from CRYSTAL23
- **Robust** - Handles missing files, empty files, malformed output

### UI Fallback System

Gracefully degrades when `gum` is unavailable:
```bash
local has_gum=false
if command -v gum &> /dev/null; then
    has_gum=true
fi

if $has_gum; then
    gum style --foreground 214 "⚠️  Detected SCF Divergence"
else
    echo "⚠️  Detected SCF Divergence"
fi
```

### Educational Message Format

All error messages follow this pattern:
1. **Error identification** - What was detected (⚠️ emoji + title)
2. **Explanation** - What it means in plain language
3. **Numbered solutions** - Concrete steps to fix the issue
4. **Examples** - Code snippets showing correct syntax

Example:
```
⚠️  Memory Error Detected
The job ran out of memory.
Try increasing the number of MPI ranks (e.g., runcrystal input 14)
This spreads the memory load across more processes.
```

## Integration Points

### 1. Module Loading (bin/runcrystal)

Already integrated - no changes needed to main script:
```bash
cry_require cry-exec  # Loads analyze_failure automatically
```

### 2. Execution Flow

```
exec_crystal_run()
  ├─ Run CRYSTAL23 calculation
  ├─ Check exit code
  └─ If non-zero:
      ├─ cry_log error
      ├─ analyze_failure() ← Automatic error analysis
      └─ tail -n 20 output file
```

### 3. Logging Integration

All analysis events logged via `cry_log`:
```bash
cry_log info "Analyzing failure in $logfile"
cry_log error "Calculation failed with exit code: $exit_code"
```

## Requirements Met

✅ **Pattern matching robust** - Uses `grep -q`, handles all edge cases
✅ **Educational tone** - Student-friendly messages with numbered steps
✅ **Works without gum** - Plain text fallback mode
✅ **Shows log tail** - Always displays last 20 lines
✅ **Logs to cry-logging** - Full integration with logging system
✅ **Comprehensive tests** - 18 passing tests (15 unit + 3 integration)
✅ **Documentation** - Complete troubleshooting guide

## Usage Examples

### Scenario 1: SCF Divergence

**Input file problem:**
```crystal
CRYSTAL
0 0 0
1
1.0 1.0 1.0  # Atoms too close!
ATOM
6 0.0 0.0 0.0
6 0.1 0.0 0.0  # Only 0.1 Å apart - unstable
END
```

**Automatic analysis output:**
```
⚠️  Detected SCF Divergence
The calculation is unstable. Try:
1. Check your geometry (atoms too close?)
2. Use a better initial guess (GUESSP)
3. Increase FMIXING (e.g., FMIXING 30)
```

### Scenario 2: Memory Error

**Large system with serial execution:**
```bash
runcrystal large_system  # Fails with memory error
```

**Automatic analysis output:**
```
⚠️  Memory Error Detected
The job ran out of memory.
Try increasing the number of MPI ranks (e.g., runcrystal input 14)
This spreads the memory load across more processes.
```

**Fixed command:**
```bash
runcrystal large_system 14  # Distributes memory across 14 processes
```

### Scenario 3: Basis Set Error

**Input file with wrong basis code:**
```crystal
BS
6 99  # Invalid basis code
END
```

**Automatic analysis output:**
```
⚠️  Basis Set Error
Problem with basis set definition.
1. Check BS keyword syntax in your .d12 file
2. Verify atomic numbers match basis set library
3. Try using a standard basis set (e.g., STO-3G)
```

## Future Enhancements

Potential additions (not in current scope):
- Geometry optimization failure detection
- Symmetry analysis errors
- K-point mesh issues
- Dispersion correction problems
- Phonon calculation failures

## Files Modified

1. `/Users/briansquires/Ultrafast/CRY_CLI/lib/cry-exec.sh` - Added `analyze_failure()` function and integration
2. `/Users/briansquires/Ultrafast/CRY_CLI/tests/unit/error_analysis_test.bats` - New test file (15 tests)
3. `/Users/briansquires/Ultrafast/CRY_CLI/tests/integration/error_analysis_integration_test.bats` - New test file (3 tests)
4. `/Users/briansquires/Ultrafast/CRY_CLI/docs/TROUBLESHOOTING.md` - New comprehensive guide
5. `/Users/briansquires/Ultrafast/CRY_CLI/docs/ERROR_ANALYSIS_IMPLEMENTATION.md` - This document

## Testing Commands

Run unit tests:
```bash
bats tests/unit/error_analysis_test.bats
```

Run integration tests:
```bash
bats tests/integration/error_analysis_integration_test.bats
```

Run all error analysis tests:
```bash
bats tests/unit/error_analysis_test.bats tests/integration/error_analysis_integration_test.bats
```

## Verification

All requirements from task specification verified:

| Requirement | Status | Verification |
|-------------|--------|--------------|
| Pattern matching robust | ✅ | grep -q used, 14 pattern tests pass |
| Educational tone | ✅ | Test #15 validates message quality |
| Works without gum | ✅ | Test #9 validates plain text mode |
| Shows last 20 lines | ✅ | Implemented in exec_crystal_run() |
| Logs to cry-logging | ✅ | Test #12 validates logging |
| Unit tests | ✅ | 15/15 tests passing |
| Documentation | ✅ | TROUBLESHOOTING.md created |

---

**Implementation completed:** 2025-11-19
**Total lines of code:** ~75 (analyze_failure function)
**Test coverage:** 18 tests (100% of error patterns)
**Documentation:** 350+ lines (troubleshooting guide)
