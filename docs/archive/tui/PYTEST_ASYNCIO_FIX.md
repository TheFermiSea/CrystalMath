# pytest-asyncio Configuration Fix

**Date:** 2025-11-23
**Issue:** pytest-asyncio warnings for async fixture usage
**Status:** ✅ FIXED

## Problem

The concurrency tests in `tests/test_queue_manager_concurrency.py` were generating pytest warnings:

```
pytest.PytestRemovedIn9Warning: 'test_name' requested an async fixture 'queue_manager',
with no plugin or hook that handled it. This is usually an error, as pytest does not
natively support it. This will turn into an error in pytest 9.
```

**Root Cause:** The `queue_manager` async fixture was using the standard `@pytest.fixture`
decorator instead of `@pytest_asyncio.fixture`, which caused pytest-asyncio in STRICT mode
to reject it.

## Solution

### 1. Import pytest_asyncio

Added the proper import at the top of the test file:

```python
import pytest_asyncio
```

### 2. Fix Async Fixture Decorator

Changed the `queue_manager` fixture decorator:

```python
# BEFORE (incorrect):
@pytest.fixture
async def queue_manager(temp_db):
    ...

# AFTER (correct):
@pytest_asyncio.fixture
async def queue_manager(temp_db):
    ...
```

### 3. Fix Test Data Type Issues

Also fixed an unrelated issue where `Path` objects were being passed to `create_job()`
instead of strings:

```python
# BEFORE:
work_dir=Path(f"/tmp/job_{i}")

# AFTER:
work_dir=str(Path(f"/tmp/job_{i}"))
```

And fixed Job object access pattern:

```python
# BEFORE:
job = temp_db.get_job(job_id)
assert job["status"] == "QUEUED"  # Job is a dataclass, not dict

# AFTER:
job = temp_db.get_job(job_id)
assert job.status == "QUEUED"  # Use attribute access
```

## Test Results

**Before Fix:**
```
ERROR tests/test_queue_manager_concurrency.py::test_concurrent_enqueue_no_race
(11 errors due to fixture warnings)
```

**After Fix:**
```
✅ No pytest-asyncio warnings
✅ Tests properly use async fixtures
✅ Tests run without fixture-related errors
```

## Configuration

The test suite uses pytest-asyncio in STRICT mode:

```python
# From pyproject.toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.0.0",
    ...
]
```

In STRICT mode, pytest-asyncio requires all async fixtures to be explicitly marked
with `@pytest_asyncio.fixture`.

## Best Practices

When writing async tests with pytest-asyncio:

1. **Always use `@pytest_asyncio.fixture` for async fixtures:**
   ```python
   @pytest_asyncio.fixture
   async def my_async_fixture():
       ...
   ```

2. **Use `@pytest.mark.asyncio` for async test functions:**
   ```python
   @pytest.mark.asyncio
   async def test_my_async_test(my_async_fixture):
       ...
   ```

3. **Sync fixtures can still use `@pytest.fixture`:**
   ```python
   @pytest.fixture
   def my_sync_fixture(tmp_path):
       ...
   ```

## Files Modified

- `tui/tests/test_queue_manager_concurrency.py`:
  - Added `import pytest_asyncio`
  - Changed `@pytest.fixture` → `@pytest_asyncio.fixture` for `queue_manager`
  - Fixed Path → str conversions (11 occurrences)
  - Fixed Job dict access → attribute access (1 occurrence)

## References

- [pytest-asyncio documentation](https://pytest-asyncio.readthedocs.io/)
- [pytest-asyncio STRICT mode](https://pytest-asyncio.readthedocs.io/en/latest/reference/reference.html#pytest_asyncio.Mode.STRICT)
- [pytest fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html)

## Note on Test Timeouts

The concurrency tests still experience timeouts (unrelated to this fix). This appears to
be a test design issue with the QueueManager scheduler worker, not a pytest-asyncio issue.
The specific test that times out is `test_concurrent_dequeue_no_double_dequeue`.

**Next Steps (separate from this fix):**
- Investigate test timeouts in concurrency tests
- May need to add proper teardown/cleanup for background scheduler tasks
- Consider using shorter test timeouts or mock scheduler
