# Exception Hierarchy Issue - Detailed Analysis

**Issue ID:** CRIT-002, HIGH-001
**Severity:** CRITICAL
**Date:** December 9, 2025

---

## Problem Statement

The crystalmath TUI has **duplicate exception class definitions** across multiple files, creating a fragmented and inconsistent error handling system.

---

## Current State

### File 1: `tui/src/runners/base.py` (lines 516-563)

```python
class RunnerError(Exception):
    """Base exception for runner errors."""
    pass

class ConnectionError(RunnerError):
    """Connection to execution target failed."""
    pass

class ExecutionError(RunnerError):
    """Job execution failed."""
    pass

class TimeoutError(RunnerError):
    """Operation timed out."""
    pass

class ConfigurationError(RunnerError):
    """Invalid configuration."""
    pass

class ResourceError(RunnerError):
    """Resource unavailable or exhausted."""
    pass

class CancellationError(RunnerError):
    """Job was cancelled."""
    pass
```

### File 2: `tui/src/runners/exceptions.py` (lines 9-156)

```python
class RunnerError(Exception):
    """Base exception for all runner-related errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.timestamp = datetime.now()

class ConnectionError(RunnerError):
    """Raised when connection to remote host fails."""
    pass

class ExecutionError(RunnerError):
    """Raised when job execution fails."""
    pass

class TimeoutError(RunnerError):
    """Raised when an operation times out."""
    pass

class ConfigurationError(RunnerError):
    """Raised for configuration-related errors."""
    pass

class ResourceError(RunnerError):
    """Raised when required resources are unavailable."""
    pass

class CancellationError(RunnerError):
    """Raised when a job is cancelled."""
    pass
```

### File 3: Runner-Specific Exceptions

Additionally, individual runners define their own exceptions:

**`slurm_runner.py`:**
```python
class SLURMRunnerError(RunnerError):
    """SLURM-specific runner error."""
    pass
```

**`ssh_runner.py`:**
```python
class SSHRunnerError(RunnerError):
    """SSH-specific runner error."""
    pass
```

**`local_runner.py`:**
```python
class LocalRunnerError(RunnerError):
    """Local runner-specific error."""
    pass
```

---

## Why This Is A Problem

### 1. Type Identity Failure

```python
# In module A
from runners.base import ConnectionError as BaseConnError

# In module B
from runners.exceptions import ConnectionError as ExcConnError

# These are DIFFERENT classes!
BaseConnError is not ExcConnError  # True

# This exception handling FAILS:
try:
    raise BaseConnError("Connection failed")
except ExcConnError:
    print("Caught!")  # NEVER REACHED
```

### 2. isinstance() Failures

```python
from runners.base import ConnectionError as CE1
from runners.exceptions import ConnectionError as CE2

err = CE1("test")
isinstance(err, CE2)  # False! They are different classes
```

### 3. Import Confusion

Developers don't know which module to import from:
```python
# Which one is correct?
from runners.base import ConnectionError
from runners.exceptions import ConnectionError
```

### 4. Different Implementations

The `exceptions.py` version has additional attributes:
- `self.message`
- `self.details`
- `self.timestamp`

The `base.py` version is a plain exception with no additional attributes.

Code expecting `error.details` will fail if it catches the `base.py` version.

---

## Impact Analysis

### Affected Files

All files that import or handle exceptions:

1. `tui/src/runners/local_runner.py`
2. `tui/src/runners/ssh_runner.py`
3. `tui/src/runners/slurm_runner.py`
4. `tui/src/core/orchestrator.py`
5. `tui/src/core/queue_manager.py`
6. `tui/tests/test_*.py` (multiple test files)

### Current Import Analysis

```bash
# base.py exceptions are imported by:
grep -r "from.*base import.*Error" tui/src/

# exceptions.py exceptions are imported by:
grep -r "from.*exceptions import" tui/src/
```

---

## Recommended Solution

### Step 1: Consolidate to Single Source

Keep `exceptions.py` as the single source (it has the richer implementation).

**`tui/src/runners/exceptions.py`** (final version):
```python
"""
Unified exception hierarchy for all runners.

All runner exceptions should be imported from this module.
"""
from datetime import datetime
from typing import Any, Dict, Optional


class RunnerError(Exception):
    """Base exception for all runner-related errors.

    Attributes:
        message: Human-readable error description
        details: Additional context as key-value pairs
        timestamp: When the error occurred
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.timestamp = datetime.now()

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} (details: {self.details})"
        return self.message


class ConnectionError(RunnerError):
    """Raised when connection to execution target fails.

    Examples:
        - SSH connection refused
        - Network timeout
        - Authentication failure
    """
    pass


class ExecutionError(RunnerError):
    """Raised when job execution fails.

    Examples:
        - Process returned non-zero exit code
        - Required executable not found
        - Out of memory
    """
    pass


class TimeoutError(RunnerError):
    """Raised when an operation exceeds its time limit.

    Examples:
        - Job exceeded wall time
        - Connection attempt timed out
        - Response not received within deadline
    """
    pass


class ConfigurationError(RunnerError):
    """Raised for configuration-related errors.

    Examples:
        - Invalid cluster configuration
        - Missing required setting
        - Incompatible options
    """
    pass


class ResourceError(RunnerError):
    """Raised when required resources are unavailable.

    Examples:
        - Disk space exhausted
        - Memory limit exceeded
        - No available compute nodes
    """
    pass


class CancellationError(RunnerError):
    """Raised when a job is cancelled.

    Examples:
        - User-initiated cancellation
        - System preemption
        - Dependency failure
    """
    pass


# Runner-specific exceptions
class SLURMError(RunnerError):
    """SLURM scheduler-specific error."""
    pass


class SSHError(ConnectionError):
    """SSH connection-specific error."""
    pass


class LocalError(RunnerError):
    """Local execution-specific error."""
    pass


# Convenience exports
__all__ = [
    'RunnerError',
    'ConnectionError',
    'ExecutionError',
    'TimeoutError',
    'ConfigurationError',
    'ResourceError',
    'CancellationError',
    'SLURMError',
    'SSHError',
    'LocalError',
]
```

### Step 2: Remove Duplicates from base.py

Delete lines 516-563 from `tui/src/runners/base.py` (the duplicate exception definitions).

### Step 3: Update All Imports

Find and replace all imports:

**Before:**
```python
from .base import RunnerError, ConnectionError, ExecutionError
```

**After:**
```python
from .exceptions import RunnerError, ConnectionError, ExecutionError
```

### Step 4: Update Runner-Specific Exceptions

**`slurm_runner.py`:**
```python
# Before
class SLURMRunnerError(RunnerError):
    pass

# After - just import from exceptions
from .exceptions import SLURMError
```

### Step 5: Add Re-exports to __init__.py

**`tui/src/runners/__init__.py`:**
```python
from .exceptions import (
    RunnerError,
    ConnectionError,
    ExecutionError,
    TimeoutError,
    ConfigurationError,
    ResourceError,
    CancellationError,
    SLURMError,
    SSHError,
    LocalError,
)

from .base import BaseRunner
from .local_runner import LocalRunner
from .ssh_runner import SSHRunner
from .slurm_runner import SLURMRunner

__all__ = [
    # Exceptions
    'RunnerError',
    'ConnectionError',
    'ExecutionError',
    'TimeoutError',
    'ConfigurationError',
    'ResourceError',
    'CancellationError',
    'SLURMError',
    'SSHError',
    'LocalError',
    # Runners
    'BaseRunner',
    'LocalRunner',
    'SSHRunner',
    'SLURMRunner',
]
```

---

## Verification Steps

After making changes:

1. **Run grep to verify no duplicates:**
   ```bash
   grep -r "class.*Error.*RunnerError" tui/src/runners/
   # Should only show exceptions.py
   ```

2. **Run import check:**
   ```bash
   python -c "from src.runners import ConnectionError; print(ConnectionError.__module__)"
   # Should print: src.runners.exceptions
   ```

3. **Run test suite:**
   ```bash
   cd tui && pytest tests/ -v
   ```

4. **Verify exception catching works:**
   ```python
   from src.runners import ConnectionError
   from src.runners.ssh_runner import SSHRunner

   # Should work correctly
   try:
       raise ConnectionError("test")
   except ConnectionError as e:
       print(f"Caught: {e.message}")
   ```

---

## Estimated Effort

- **Time:** 2-4 hours
- **Risk:** Low (changes are straightforward)
- **Testing:** Run full test suite after changes

---

## Related Issues

- HIGH-001: Multiple Exception Hierarchies (resolved by this fix)
- Tests in `test_ssh_runner.py`, `test_slurm_runner.py` may need updates
