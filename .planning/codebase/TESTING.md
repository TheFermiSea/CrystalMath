# Testing Patterns

**Analysis Date:** 2026-02-02

## Test Framework

**Python:**
- **Runner:** pytest with asyncio support (auto mode)
- **Config:** `pyproject.toml` with `testpaths = ["python/tests", "tui/tests"]`
- **Assertion Library:** pytest assertions (built-in, no separate library)
- **Async Support:** `asyncio_mode = "auto"` enables async/await test functions

**Rust:**
- **Framework:** Built-in Rust test framework (`#[cfg(test)]` modules)
- **Runner:** cargo test
- **Assertion Library:** `pretty_assertions` crate for better diff output
- **Coverage:** No explicit coverage tool configured

**Bash (CLI):**
- **Framework:** bats-core (Bash Automated Testing System)
- **Test Syntax:** Shell syntax with @test blocks
- **Assertion Library:** Custom helpers (`assert_equals`, `assert_not_empty`, `assert_success`)

**Run Commands:**

```bash
# Python: Run all tests
uv run pytest

# Python: Run with verbose output
uv run pytest -v

# Python: Run specific test file
uv run pytest python/tests/test_api.py

# Python: Watch mode
uv run pytest --watch

# Python: Coverage
uv run pytest --cov

# Rust: Run all tests
cargo test

# Rust: Run specific test module
cargo test lsp

# Bash: Run all CLI tests
bats cli/tests/unit/*.bats cli/tests/integration/*.bats

# Bash: Run single module tests
bats cli/tests/unit/cry-config_test.bats
```

## Test File Organization

**Location:**
- **Python:** Co-located in package-parallel directories
  - Core package tests: `python/tests/test_*.py`
  - TUI package tests: `tui/tests/test_*.py`
- **Rust:** Inline in source modules (`#[cfg(test)] mod tests { ... }`)
  - Also: `src/app_tests.rs` for app-specific tests (1113 lines)
- **Bash:** Separate directory structure
  - Unit tests: `cli/tests/unit/*.bats`
  - Integration tests: `cli/tests/integration/*.bats`
  - Helpers: `cli/tests/helpers.bash`

**Naming:**
- **Python:** `test_<module_name>.py` (e.g., `test_api.py`, `test_models.py`, `test_jsonrpc_dispatch.py`)
- **Rust:** Modules have inline test sections with `#[test]` or `#[tokio::test]`
- **Bash:** `test_<module_name>.sh` (e.g., `test-cry-config.sh`, `test_cry_parallel_test.bats`)

**Directory Structure:**
```
python/tests/
├── __init__.py
├── test_api.py
├── test_models.py
├── test_jsonrpc_dispatch.py
├── test_cluster_config.py
├── test_slurm_runner.py
├── test_workflows.py
├── test_pymatgen_bridge.py
├── test_atomate2_bridge.py
└── test_high_level_api.py

tui/tests/
├── __init__.py
└── test_<feature>.py

src/
├── main.rs
├── app.rs
├── app_tests.rs     # Separate file for large test suite
├── models.rs
├── bridge.rs
├── lsp.rs
└── ui/
    └── *.rs         # Inline tests via #[cfg(test)]

cli/tests/
├── helpers.bash
├── mocks/           # Mock binaries for testing
├── unit/
│   ├── cry-config_test.bats
│   ├── cry-ui_test.bats
│   ├── cry-parallel_test.bats
│   └── ...
└── integration/
    └── full_workflow_test.bats
```

## Test Structure

**Python Test Suite Organization:**

```python
class TestCrystalControllerDemoMode:
    """Tests for demo mode (no backend)."""

    def test_create_controller_demo_mode(self):
        """Controller initializes in demo mode without backends."""
        controller = CrystalController(use_aiida=False)
        assert not controller._aiida_available

    @pytest.fixture
    def controller(self):
        """Pytest fixture creates fresh controller for each test."""
        return CrystalController(use_aiida=False, db_path=None)

    def test_with_fixture(self, controller):
        """Test function receives fixture as parameter."""
        result = controller.get_jobs_json()
        assert isinstance(result, str)
```

**Patterns:**
- Test classes group related tests (e.g., `TestCrystalControllerDemoMode`)
- Docstrings on test methods describe what is being tested
- Fixtures (pytest) provide setup/teardown:
  ```python
  @pytest.fixture
  def controller():
      return CrystalController(use_aiida=False)
  ```
- Setup/teardown via class methods:
  ```python
  def setup_method(self):
      """Called before each test method."""
      self.temp_dir = tempfile.mkdtemp()

  def teardown_method(self):
      """Called after each test method."""
      shutil.rmtree(self.temp_dir)
  ```

**Rust Test Structure:**

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::{DftCode, JobDetails};

    struct MockBridgeService {
        requests: Arc<Mutex<Vec<String>>>,
        responses: Arc<Mutex<VecDeque<BridgeResponse>>>,
    }

    #[test]
    fn test_job_state_color() {
        let state = JobState::Running;
        assert_eq!(state.color(), Color::Green);
    }

    #[tokio::test]
    async fn test_async_operation() {
        // Async test with tokio runtime
    }
}
```

**Patterns:**
- Test modules use `#[cfg(test)]` to exclude from release builds
- Mock types defined inline (e.g., `MockBridgeService`)
- Both sync (`#[test]`) and async (`#[tokio::test]`) test attributes
- Test names are descriptive: `test_job_state_color_maps_running_to_green`

**Bash Test Structure:**

```bash
#!/usr/bin/env bash

load helpers  # Source shared test utilities

@test "function_name returns expected output" {
    source "$LIB_DIR/module.sh"

    result=$(function_name arg1)

    [ "$result" = "expected" ]
}

@test "function handles error gracefully" {
    # Test error case
    run function_name invalid_arg

    [ "$status" -ne 0 ]
    [[ "$output" == *"error message"* ]]
}
```

**Patterns:**
- Load helper functions with `load helpers`
- Each test is a `@test` block with description
- Use `run` builtin to capture exit code and output
- Check exit status with `[ "$status" -eq 0 ]`
- Check output with string matching: `[[ "$output" == *"pattern"* ]]`

## Mocking

**Python Framework:** `unittest.mock` (built-in)

**Patterns:**
```python
from unittest.mock import Mock, patch, MagicMock

# Mock an object
mock_backend = Mock()
mock_backend.get_jobs.return_value = []

# Mock as context manager
with patch('crystalmath.api.CrystalController._init_aiida'):
    controller = CrystalController(use_aiida=True)

# Mock with side effects
def side_effect(*args, **kwargs):
    return {"status": "success"}

mock_service.submit.side_effect = side_effect
```

**What to Mock:**
- External service calls (AiiDA, database, SSH connections)
- File I/O (use tempfile.TemporaryDirectory instead when possible)
- Network calls (Materials Project API)
- System calls (subprocess, environment variables)

**What NOT to Mock:**
- Pydantic model validation (test actual behavior)
- Enum operations (test enum dispatch logic)
- Core business logic unless testing error paths
- Functions being tested (only mock dependencies)

**Rust Framework:** Manual trait-based mocks

**Patterns:**
```rust
trait BridgeService {
    fn request_fetch_jobs(&self, request_id: usize) -> Result<()>;
}

struct MockBridgeService {
    requests: Arc<Mutex<Vec<String>>>,
}

impl BridgeService for MockBridgeService {
    fn request_fetch_jobs(&self, request_id: usize) -> Result<()> {
        self.requests.lock().unwrap()
            .push(format!("FetchJobs({})", request_id));
        Ok(())
    }
}

#[test]
fn test_app_requests_jobs() {
    let mock = MockBridgeService::new();
    let app = App::with_service(Box::new(mock));
    // Test that app calls the service correctly
}
```

**Bash Framework:** Mock binaries in test directory

**Patterns:**
```bash
# Create mock executable
export CRY23_ROOT="$BATS_TEST_TMPDIR/mock_crystal"
mkdir -p "$CRY23_ROOT/bin"
echo '#!/bin/bash' > "$CRY23_ROOT/bin/crystalOMP"
echo 'echo "Mock output"' >> "$CRY23_ROOT/bin/crystalOMP"
chmod +x "$CRY23_ROOT/bin/crystalOMP"

# Mock binary returns controlled output
@test "execute_crystal succeeds with mock binary" {
    export CRY23_ROOT="$BATS_TEST_TMPDIR/mock_crystal"
    setup_mock_crystal_bin

    result=$(execute_crystal)

    [[ "$result" == "Mock output" ]]
}
```

## Fixtures and Factories

**Test Data (Python):**

```python
@pytest.fixture
def sample_job_submission() -> Dict[str, Any]:
    """Create a valid job submission for testing."""
    return {
        "name": "test-job",
        "dft_code": "crystal",
        "parameters": {
            "SHRINK": [8, 8],
            "MAXCYCLE": 100,
        }
    }

@pytest.fixture
def controller_with_demo_backend(sample_job_submission):
    """Controller in demo mode with sample data."""
    controller = CrystalController(use_aiida=False)
    controller.submit_job(sample_job_submission)
    return controller
```

**Location:**
- Shared fixtures in `conftest.py` (if created, pytest auto-discovers)
- Module-specific fixtures in test files (rare)
- Factory functions for complex object creation

**Bash Fixtures:**

```bash
setup() {
    export BATS_TEST_TMPDIR=$(mktemp -d)
    export CRY23_ROOT="$BATS_TEST_TMPDIR/crystal"
    mkdir -p "$CRY23_ROOT/bin"
}

teardown() {
    rm -rf "$BATS_TEST_TMPDIR"
}

# Reusable helper functions in helpers.bash
setup_mock_crystal_bin() {
    echo '#!/bin/bash' > "$CRY23_ROOT/bin/crystalOMP"
    chmod +x "$CRY23_ROOT/bin/crystalOMP"
}
```

## Coverage

**Requirements:** Not explicitly enforced in CI
- Projects tracked with test counts (Python: ~10 test files, Rust: ~1113 lines in app_tests.rs)
- Coverage measurement available but not gated

**View Coverage (Python):**
```bash
uv run pytest --cov=crystalmath python/tests/
uv run pytest --cov=crystal_tui tui/tests/
```

**View Coverage (Rust):**
```bash
# Using tarpaulin (external tool)
cargo tarpaulin --out Html
```

## Test Types

**Unit Tests:**
- **Scope:** Single function or method in isolation
- **Approach:** Mock all dependencies, test behavior
- **Examples:**
  - `test_map_to_job_state` - Maps AiiDA states to UI states
  - `test_job_state_color` - Enum color mapping
  - `test_jsonrpc_dispatch_method_not_found` - Error response format

**Integration Tests:**
- **Scope:** Multiple modules working together
- **Approach:** Use minimal mocking, test actual integration
- **Examples:**
  - `test_submit_job_json` - Submission through API boundary
  - `test_cluster_config_from_ssh_host` - Config + cluster integration
  - CLI full_workflow_test.bats - End-to-end with mock CRYSTAL23

**E2E Tests:**
- **Framework:** Not used in current codebase
- **Note:** CLI tests serve as pseudo-E2E with mock binaries
- **Future:** Could add containerized tests with actual CRYSTAL23 binary

## Common Patterns

**Async Testing (Python):**

```python
@pytest.mark.asyncio
async def test_async_job_submission():
    """Test async submission workflow."""
    controller = CrystalController(use_aiida=False)
    result = await controller.submit_job_async(job_data)
    assert result["ok"] is True
```

**Error Testing (Python):**

```python
def test_submit_job_validation_error(self, controller):
    """Submission fails on invalid parameters."""
    payload = json.dumps({
        "name": "test",
        "dft_code": "crystal",
        "parameters": {
            "SHRINK": [8, "invalid"],  # Invalid type
        }
    })

    with pytest.raises(ValueError):
        controller.submit_job_json(payload)
```

**Error Testing (Rust):**

```rust
#[test]
fn test_invalid_cluster_type_deserialization() {
    let json = r#"{"cluster_type": "invalid_type"}"#;
    let result: Result<ClusterConfig, _> = serde_json::from_str(json);

    // Should fail or fallback to Unknown variant
    assert!(result.is_err() || matches!(result.unwrap().cluster_type, ClusterType::Unknown));
}
```

**Error Testing (Bash):**

```bash
@test "cry_parallel_setup handles zero cores gracefully" {
    source "$LIB_DIR/cry-parallel.sh"

    # Mock nproc to return 0
    nproc() { return 1; }

    run parallel_setup 0 CRY_JOB

    # Should fail or use safe default
    [ "$status" -ne 0 ] || [ "${CRY_JOB[THREADS_PER_RANK]}" -gt 0 ]
}
```

**Fixture Parametrization (Python):**

```python
@pytest.mark.parametrize("state,expected_color", [
    ("CREATED", "gray"),
    ("RUNNING", "green"),
    ("COMPLETED", "blue"),
    ("FAILED", "red"),
])
def test_job_state_colors(state, expected_color):
    """Test color mapping for all states."""
    job_state = JobState(state)
    assert job_state.color() == expected_color
```

**Setup/Teardown with Traps (Bash):**

```bash
setup() {
    # Create test scratch directory
    SCRATCH=$(mktemp -d)
    trap "rm -rf $SCRATCH" EXIT
}

@test "scratch cleanup removes directory" {
    mkdir -p "$SCRATCH/work"
    [ -d "$SCRATCH/work" ]

    cleanup_scratch "$SCRATCH"

    [ ! -d "$SCRATCH/work" ]
}
```

## Test Configuration

**pyproject.toml Settings:**

```toml
[tool.pytest.ini_options]
testpaths = ["python/tests", "tui/tests"]
asyncio_mode = "auto"
addopts = "-v --tb=short"
filterwarnings = [
    "ignore::DeprecationWarning",
]
```

- `testpaths`: Directories where pytest searches for tests
- `asyncio_mode = "auto"`: Enables async test functions without decorator
- `addopts = "-v --tb=short"`: Verbose output with short tracebacks
- `filterwarnings`: Suppress deprecation warnings from dependencies

**Cargo Test Configuration:**

```toml
[dev-dependencies]
pretty_assertions = "1.4"  # For better assertion diffs
```

---

*Testing analysis: 2026-02-02*
