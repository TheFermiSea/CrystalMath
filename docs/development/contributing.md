# Contributing to CRYSTAL-TOOLS

Thank you for your interest in contributing to CRYSTAL-TOOLS! This guide covers contribution guidelines for both the CLI and TUI components.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Code Style](#code-style)
- [Testing](#testing)
- [Issue Tracking](#issue-tracking)
- [Pull Request Process](#pull-request-process)
- [CLI-Specific Guidelines](#cli-specific-guidelines)
- [TUI-Specific Guidelines](#tui-specific-guidelines)

## Getting Started

### Prerequisites

**General:**
- Git (version control)
- CRYSTAL23 installation (for testing)
- Familiarity with quantum chemistry workflows (helpful but not required)

**CLI Development:**
- Bash 4.0+ (bash 5.x recommended)
- bats-core (testing framework)
- shellcheck (linting)
- Basic understanding of shell scripting

**TUI Development:**
- Python 3.10+
- pip and virtual environments
- Understanding of async/await patterns
- Familiarity with Textual framework (optional)

### Fork and Clone

1. Fork the repository on GitHub
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR-USERNAME/crystalmath.git
   cd crystalmath
   ```
3. Add upstream remote:
   ```bash
   git remote add upstream https://github.com/ORIGINAL-OWNER/crystalmath.git
   ```

## Development Setup

### CLI Development Environment

```bash
# Navigate to CLI directory
cd cli/

# Install development dependencies
# macOS:
brew install bats-core shellcheck

# Linux (example for Ubuntu):
# sudo apt-get install bats shellcheck

# Set environment variables
export CRY23_ROOT=~/CRYSTAL23
export CRY_SCRATCH_BASE=~/tmp_crystal

# Run tests to verify setup
bats tests/unit/*.bats
```

### TUI Development Environment

```bash
# Navigate to TUI directory
cd tui/

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install package in development mode
pip install -e ".[dev]"

# Install additional dev tools
pip install black ruff mypy pytest-cov

# Verify installation
pytest  # (when tests are implemented)
```

## Code Style

### CLI Code Style (Bash)

**Formatting:**
- Use 4-space indentation (not tabs)
- Maximum line length: 100 characters
- Use `snake_case` for function names
- Use `UPPER_CASE` for constants and environment variables

**Best Practices:**
```bash
# ✅ Good: Clear function names
parallel_setup() {
    local nprocs="$1"
    local -n job_ref="$2"  # Name reference
    ...
}

# ✅ Good: Explicit error handling
if ! scratch_create "$job_name"; then
    cry_fatal "Failed to create scratch directory"
fi

# ✅ Good: Local variables
stage_inputs() {
    local input_file="$1"
    local scratch_dir="$2"
    ...
}

# ❌ Bad: Global state changes
GLOBAL_VAR="something"  # Avoid unless necessary

# ❌ Bad: Unclear function names
do_stuff() { ... }
```

**Module Structure:**
```bash
#!/bin/bash
# Module: <module-name>
# Description: <what this module does>
# Dependencies: <list dependent modules>

# Error handling (only in main script, not libraries)
set -euo pipefail  # Use in bin/runcrystal only

# Module-level constants
readonly MODULE_NAME="module-name"

# Public functions (use module prefix)
module_public_function() {
    # Implementation
    return 0
}

# Private functions (use underscore prefix)
_module_internal_function() {
    # Private implementation
}
```

**Linting:**
```bash
# Run shellcheck on all scripts
shellcheck bin/runcrystal lib/*.sh
```

### TUI Code Style (Python)

**Formatting:**
- Use 4-space indentation
- Maximum line length: 88 characters (Black default)
- Follow PEP 8

**Type Hints:**
```python
from pathlib import Path
from typing import Optional, List, Dict

def parse_output(file_path: Path) -> Dict[str, any]:
    """Parse CRYSTAL output file"""
    ...

async def run_job(job_id: int, nprocs: Optional[int] = None) -> int:
    """Execute job asynchronously"""
    ...
```

**Code Quality Tools:**
```bash
# Format code
black src/ tests/

# Lint
ruff check src/ tests/

# Type check
mypy src/

# All checks
black src/ tests/ && ruff check src/ tests/ && mypy src/
```

**Docstrings:**
```python
def function_name(param1: str, param2: int) -> bool:
    """
    Short one-line summary.

    Longer description if needed. Explain the purpose,
    not the implementation details.

    Args:
        param1: Description of param1
        param2: Description of param2

    Returns:
        Description of return value

    Raises:
        ValueError: When param1 is invalid
    """
    ...
```

## Testing

### CLI Testing

**Writing Unit Tests:**

Create test file in `tests/unit/<module>_test.bats`:

```bash
#!/usr/bin/env bats

load helpers

setup() {
    # Create test environment
    export BATS_TEST_TMPDIR=$(mktemp -d)
    export CRY23_ROOT="$BATS_TEST_TMPDIR/crystal"
}

teardown() {
    # Cleanup
    rm -rf "$BATS_TEST_TMPDIR"
}

@test "module_function: returns expected output" {
    source "$LIB_DIR/module.sh"

    result=$(module_function arg1 arg2)

    [ "$result" = "expected_output" ]
}
```

**Running Tests:**
```bash
# Run all tests
bats tests/unit/*.bats tests/integration/*.bats

# Run specific module tests
bats tests/unit/cry-parallel_test.bats

# Run with verbose output
bats -t tests/unit/cry-config_test.bats
```

**Test Coverage:**
- Aim for >80% coverage of module functions
- Test both success and error paths
- Mock external commands (gum, mpirun, crystalOMP)

### TUI Testing

**Writing Unit Tests:**

Create test file in `tests/test_<module>.py`:

```python
import pytest
from pathlib import Path
from crystal_tui.core.database import Database

@pytest.fixture
def temp_db(tmp_path):
    """Create temporary database for testing"""
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    yield db
    db.close()

def test_create_job(temp_db):
    """Test job creation"""
    job_id = temp_db.create_job(
        name="test_job",
        input_content="CRYSTAL\n0 0 0\nEND\n"
    )
    assert job_id > 0

    job = temp_db.get_job(job_id)
    assert job.name == "test_job"
    assert job.status == "pending"
```

**Running Tests:**
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=crystal_tui --cov-report=html

# Run specific test file
pytest tests/test_database.py

# Run specific test
pytest tests/test_database.py::test_create_job
```

**Test Coverage:**
- Aim for >80% coverage
- Test UI components with snapshots
- Test async code with pytest-asyncio
- Mock external dependencies (CRYSTALpytools, subprocess)

## Issue Tracking

This project uses [beads](https://github.com/beadsinc/beads) for issue tracking.

### Creating Issues

```bash
# Create new issue
bd create "Issue title"

# Add description in editor
bd edit <issue-id>

# Add labels
bd label add <issue-id> bug
bd label add <issue-id> enhancement

# Set priority
bd edit <issue-id>  # Set priority field: 0=high, 1=medium, 2=low
```

### Issue Types

- `bug` - Something isn't working
- `enhancement` - New feature or improvement
- `task` - Development task (refactoring, tests, docs)
- `epic` - Large feature spanning multiple issues

### Labels

**Component Labels:**
- `cli` - CLI-specific issue
- `tui` - TUI-specific issue
- `integration` - Integration between CLI and TUI
- `docs` - Documentation

**Priority:**
- P0 - Critical (blocking)
- P1 - High priority
- P2 - Medium priority
- P3 - Low priority (nice to have)

**Status:**
- `open` - Not started
- `in-progress` - Being worked on
- `blocked` - Waiting for dependency
- `closed` - Completed

**TUI Phases:**
- `phase-1` - MVP features
- `phase-2` - Remote execution, batch jobs
- `phase-3` - Advanced features, workflows

### Finding Issues to Work On

```bash
# Show all open issues
bd list

# Show issues by label
bd list --label=bug
bd list --label=cli

# Show issues by priority
bd list --priority=0  # High priority

# Show blocked issues
bd blocked
```

## Pull Request Process

### Before Submitting

1. **Create feature branch:**
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Make changes:**
   - Follow code style guidelines
   - Write tests for new functionality
   - Update documentation

3. **Test your changes:**
   ```bash
   # CLI
   cd cli/
   bats tests/unit/*.bats

   # TUI
   cd tui/
   pytest
   black src/ tests/
   ruff check src/ tests/
   mypy src/
   ```

4. **Update documentation:**
   - Update README if user-facing changes
   - Add docstrings for new functions
   - Update architecture docs if needed

5. **Commit changes:**
   ```bash
   git add .
   git commit -m "Add feature: brief description

   Longer description explaining:
   - What was changed
   - Why it was changed
   - How it was tested
   "
   ```

### Commit Message Format

```
<type>: <brief summary>

<detailed description>

Closes: <issue-id>
```

**Types:**
- `feat:` - New feature
- `fix:` - Bug fix
- `refactor:` - Code refactoring
- `test:` - Adding tests
- `docs:` - Documentation updates
- `style:` - Code style changes (formatting)
- `perf:` - Performance improvements

**Examples:**
```
feat: Add --json output mode to CLI

Adds machine-readable JSON output for integration with TUI.
- New flag: --json
- Outputs job status, files, timing
- Updates help system

Closes: crystalmath-abc
```

```
fix: Prevent race condition in scratch cleanup

Fixes issue where parallel jobs could delete each other's
scratch directories. Now uses PID in directory name.

Closes: crystalmath-xyz
```

### Submitting Pull Request

1. **Push to your fork:**
   ```bash
   git push origin feature/my-feature
   ```

2. **Create pull request on GitHub:**
   - Clear title describing the change
   - Reference related issues
   - Describe testing performed
   - Add screenshots for UI changes (TUI)

3. **PR Template:**
   ```markdown
   ## Description
   Brief description of changes

   ## Related Issues
   Closes #123

   ## Changes Made
   - Change 1
   - Change 2

   ## Testing
   - [ ] Unit tests pass
   - [ ] Integration tests pass
   - [ ] Manual testing performed

   ## Checklist
   - [ ] Code follows style guidelines
   - [ ] Tests added for new functionality
   - [ ] Documentation updated
   - [ ] All tests passing
   ```

4. **Address review feedback:**
   - Make requested changes
   - Push updates to same branch
   - Respond to comments

### Review Process

- All PRs require review from maintainer
- CI checks must pass (when configured)
- Tests must maintain or improve coverage
- Code must follow style guidelines

## CLI-Specific Guidelines

### Adding New Module

1. **Create module file:** `lib/cry-newmodule.sh`
2. **Follow module template:**
   ```bash
   #!/bin/bash
   # Module: cry-newmodule
   # Description: What this module does
   # Dependencies: cry-config, cry-logging

   readonly MODULE_NAME="cry-newmodule"

   newmodule_function() {
       # Implementation
       return 0
   }
   ```

3. **Add to module loader:** Update `lib/core.sh` if needed
4. **Write tests:** `tests/unit/cry-newmodule_test.bats`
5. **Update documentation:** Add to `cli/docs/ARCHITECTURE.md`

### Module Dependencies

**Dependency Rules:**
- `cry-config.sh` and `cry-logging.sh` have no dependencies
- `core.sh` depends only on config and logging
- All other modules can depend on config, logging, core
- Never create circular dependencies

**Loading Order:**
1. cry-config.sh (bootstrap)
2. cry-logging.sh (logging)
3. core.sh (module loader)
4. Remaining modules (via cry_require)

### Error Handling

```bash
# Return exit codes
function_name() {
    if ! some_operation; then
        cry_error "Operation failed"
        return 1
    fi
    return 0
}

# Use cry_fatal for critical errors
if ! critical_check; then
    cry_fatal "Critical failure, cannot continue"
fi

# Check return codes
if ! module_function "$arg"; then
    cry_error "Module failed"
    return 1
fi
```

## TUI-Specific Guidelines

### Adding New Feature

1. **UI Component:** Create in `src/tui/widgets/` or `src/tui/screens/`
2. **Business Logic:** Add to `src/core/`
3. **Database:** Update schema in `src/core/database.py`
4. **Runner:** Add to `src/runners/` if execution-related
5. **Tests:** Add to `tests/`
6. **Documentation:** Update `tui/docs/PROJECT_STATUS.md`

### Textual Patterns

**Message Handling:**
```python
from textual.message import Message

class CustomMessage(Message):
    """Custom message for component communication"""
    def __init__(self, data: str):
        self.data = data
        super().__init__()

class MyWidget(Widget):
    def on_custom_message(self, message: CustomMessage) -> None:
        """Handle custom message"""
        self.update(message.data)
```

**Async Operations:**
```python
async def long_running_task(self):
    """Background task"""
    # Use worker for CPU-bound tasks
    result = await self.run_worker(self._worker_task)

    # Use asyncio for I/O-bound tasks
    data = await self._fetch_data()

@work(exclusive=True)
async def _worker_task(self):
    """CPU-bound worker"""
    # Heavy computation
    return result
```

### Database Changes

**Schema Migrations:**
1. Update `src/core/database.py`
2. Provide migration function
3. Test with existing data
4. Document in changelog

```python
def migrate_v1_to_v2(conn):
    """Migrate database from v1 to v2"""
    conn.execute("ALTER TABLE jobs ADD COLUMN new_field TEXT")
```

## Documentation

### When to Update Docs

- **README:** User-facing feature changes
- **Architecture:** Structural changes, new modules
- **API:** New functions, changed signatures
- **Tutorial:** New workflows, usage patterns

### Documentation Structure

```
docs/
├── installation.md       # Installation guide
├── integration.md        # CLI+TUI integration
├── architecture.md       # High-level architecture
└── CONTRIBUTING.md       # This file

cli/docs/
├── ARCHITECTURE.md       # CLI detailed design
├── TESTING.md           # Testing guide
└── TROUBLESHOOTING.md   # Common issues

tui/docs/
├── PROJECT_STATUS.md    # Roadmap and status
└── INSTALL.md          # TUI-specific install
```

## Getting Help

- **Questions:** Open an issue with `question` label
- **Bugs:** Open an issue with `bug` label
- **Feature Requests:** Open an issue with `enhancement` label
- **Discussion:** Use GitHub Discussions (when available)

## Code of Conduct

- Be respectful and inclusive
- Focus on constructive feedback
- Help newcomers learn
- Credit others' work
- Follow scientific best practices

---

**Thank you for contributing to CRYSTAL-TOOLS!**

For questions or clarification, open an issue or contact the maintainers.
