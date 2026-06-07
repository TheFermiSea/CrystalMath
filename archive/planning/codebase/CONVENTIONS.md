# Coding Conventions

**Analysis Date:** 2026-02-02

## Naming Patterns

**Python Files:**
- Module names: `snake_case` (e.g., `models.py`, `api.py`, `slurm_runner.py`)
- Internal modules: `_prefix_snake_case` (e.g., `_init_state_map()` for private helpers)

**Python Functions:**
- Standard functions: `snake_case` (e.g., `map_to_job_state()`, `create_controller()`)
- Private functions: `_leading_underscore` (e.g., `_ok_response()`, `_error_response()`)
- Class methods: `snake_case` (e.g., `__init__()`, `get_jobs_json()`)

**Python Variables:**
- Local variables: `snake_case` (e.g., `file_prefix`, `job_names`, `response_str`)
- Constants: `SCREAMING_SNAKE_CASE` (e.g., `JSONRPC_PARSE_ERROR`, `JSONRPC_METHOD_NOT_FOUND`)
- Private class attributes: `_leading_underscore` (e.g., `_aiida_available`, `_rpc_registry`)

**Python Types:**
- Enums: `PascalCase` (e.g., `JobState`, `DftCode`, `RunnerType`)
- Classes: `PascalCase` (e.g., `CrystalController`, `SchedulerOptions`, `JobDetails`)
- Type hints: Use `from typing import` for complex types, use `Optional[]` for nullable (not `Union[T, None]`)

**Rust Files:**
- Module names: `snake_case` (e.g., `models.rs`, `bridge.rs`, `lsp.rs`)
- Functions: `snake_case` (e.g., `install_panic_hook()`, `configure_python_env()`)
- Constants: `SCREAMING_SNAKE_CASE` (e.g., `TERMINAL_RAW`)
- Structs/Enums: `PascalCase` (e.g., `JobState`, `DftCode`, `TerminalGuard`)
- Module prefixes for private items: `_function_name()` (e.g., `_ok_response()`)

**Bash/Shell Scripts:**
- Function names: `snake_case` with module prefix (e.g., `cry_config_init()`, `parallel_setup()`)
- Private functions: `_module_function()` (e.g., `_cry_init_stage_maps()`, `_cry_load_config_file()`)
- Variables: `SCREAMING_SNAKE_CASE` for exported (e.g., `CRY23_ROOT`, `SCRATCH_BASE`)
- Local variables: `lowercase` (e.g., `test_name`, `actual`, `exit_code`)

## Code Style

**Formatting:**
- **Python:** Black with 100-char line length (`tool.black` in pyproject.toml)
- **Rust:** cargo fmt (2-space indents, standard Rust formatting)
- **Bash:** 4-space indents, `set -euo pipefail` for strict mode

**Linting:**
- **Python:** Ruff with rules: E, F, W, I, N, UP, B, A, C4, SIM (ignores E501 line length)
- **Rust:** cargo clippy (no warnings tolerated)
- **Bash:** ShellCheck patterns observed (set -euo pipefail, proper quoting)

**Type Checking:**
- **Python:** MyPy in strict mode (`strict = true` in pyproject.toml)
  - All functions must have type hints
  - Pydantic models use `ConfigDict(extra="forbid")` to prevent extra fields
  - Uses `from __future__ import annotations` for forward-compatible string annotations
- **Rust:** Compile-time type safety via Rust type system
  - Uses `#[serde(...)]` attributes for JSON serialization
  - Derives like `#[derive(Debug, Clone, Copy, ...)]` are explicit

## Import Organization

**Order (Python):**
1. `from __future__ import annotations` (if needed)
2. Standard library imports (json, logging, pathlib, datetime, etc.)
3. Third-party imports (pydantic, ratatui types, etc.)
4. Local imports from crystalmath package

**Example:**
```python
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from crystalmath.models import JobState, DftCode, RunnerType
```

**Path Aliases (Python):**
- No explicit path aliases configured
- Uses absolute imports from package root (e.g., `from crystalmath.models import ...`)
- Relative imports within package are used (e.g., `from .utils import ...`)

**Path Aliases (Rust):**
- Uses standard module system with `mod app;`, `mod bridge;`, etc.
- Local crate references with `use crate::`:
  ```rust
  use crate::app::App;
  use crate::models::{ClusterType, DftCode};
  use crate::bridge::BridgeService;
  ```

## Error Handling

**Python Patterns:**
- Explicit exception handling: catch specific exceptions before generic ones
  ```python
  try:
      # code
  except json.JSONDecodeError as e:
      # specific handling
  except KeyError as e:
      # specific handling
  except Exception as e:
      # fallback
  ```
- Uses `from e` for exception chaining: `raise RuntimeError(...) from e`
- JSON-RPC protocol uses structured responses: `{"ok": true, "data": {...}}` or `{"ok": false, "error": {...}}`
- Error codes for JSON-RPC: `JSONRPC_PARSE_ERROR` (-32700), `JSONRPC_INVALID_REQUEST` (-32600), `JSONRPC_METHOD_NOT_FOUND` (-32601)

**Rust Patterns:**
- Uses `anyhow::Result<T>` for fallible operations (returns errors as values)
- Uses `thiserror` for custom error types with context
- Never uses bare `unwrap()` in production code (causes panics)
- RAII guards for resource cleanup (e.g., `TerminalGuard` in main.rs manages terminal state)
- Panic hook installed in main to restore terminal state before panic output
  ```rust
  fn install_panic_hook() {
      let default_hook = panic::take_hook();
      panic::set_hook(Box::new(move |panic_info| {
          // Restore terminal state
          let _ = disable_raw_mode();
          default_hook(panic_info);
      }));
  }
  ```

**Bash Patterns:**
- Early return on error with `return 0` for success, non-zero for failure
- Separate error analysis function: `analyze_failure()` inspects OUTPUT log for known patterns
- Continues execution after failure to retrieve partial results: `|| EXIT_CODE=$?`
- Trap-based cleanup guarantee: `trap 'scratch_cleanup' EXIT` ensures cleanup even on error

## Logging

**Framework (Python):** Standard `logging` module
- Logger created per module: `logger = logging.getLogger(__name__)`
- Log levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

**Patterns:**
- Log at module load: `logger.info("Module loaded")`
- Log at function entry for debugging: `logger.debug(f"Fetching jobs...")`
- Log warnings for recoverable issues: `logger.warning(f"Retry attempt {n}")`
- Log errors with context: `logger.error(f"Failed to fetch: {e}")`

**Framework (Rust):** `tracing` crate
- Structured logging with spans: `tracing::info!("Python env: {}", env_var)`
- Used for startup diagnostics (Python version, module discovery)

**Framework (Bash):** Custom `cry_log` functions in `lib/cry-logging.sh`
- `cry_log` - Info messages
- `cry_warn` - Warning messages
- `cry_error` - Error messages (doesn't exit)
- `cry_fatal` - Fatal error with exit

## Comments

**When to Comment:**
- Complex algorithms or non-obvious logic (e.g., state mapping in models.py)
- LSP protocol details (JSON-RPC 2.0 specification references)
- Security-sensitive code (e.g., Jinja2 sandboxing, safe_eval implementation)
- Workarounds for limitations or external constraints
- **NOT:** Self-documenting code (avoid redundant comments)

**Module-level Documentation:**
- All Python modules start with docstring explaining purpose and key contracts:
  ```python
  """
  CrystalController: Primary Python core API for TUIs and CLI.

  This module is the single point of entry for Python consumers. Methods return
  native Python objects (Pydantic models, dicts). JSON serialization should be
  handled at the Rust/IPC boundary.
  """
  ```

**Rust Documentation:**
- Module-level doc comments with `//!` explaining purpose
- Function doc comments with `///` including examples for public APIs
- Inline comments for non-obvious logic (RAII patterns, panic safety, etc.)

**JSDoc/TSDoc:** Not applicable (Python-first project with Rust secondary)

## Function Design

**Size:** 20-40 lines per function is typical
- Smaller functions (10-20 lines) for single responsibilities
- Larger functions acceptable for orchestration (main script, event loop)
- Private helpers keep public interfaces clean

**Parameters:**
- Type-hinted in Python: `def foo(x: int, y: str) -> bool:`
- Positional-only when semantically required (rare)
- Keyword-only arguments for optional configuration
- Accept `Dict[str, Any]` for extensible configurations (e.g., job parameters)

**Return Values:**
- Single return type (no optional mixing when avoidable)
- Use `Optional[T]` explicitly when None is valid
- Pydantic models preferred over dicts for typed returns
- JSON strings only at boundary layer (Rust bridge)

**State Management:**
- Python: Use class attributes for mutable state (e.g., `CrystalController._aiida_available`)
- Rust: Central `App` struct holds all state (dirty flags, tabs, selected indices)
- Bash: Pass associative arrays by reference (e.g., `CRY_JOB` array) or use module-level variables

## Module Design

**Exports (Python):**
- Top-level `__all__` when module re-exports are intentional
- Private modules prefixed with underscore (rare, mostly in integrations)
- Pydantic models exported for type hints

**Exports (Rust):**
- Public functions/types in module files
- Re-exported from `mod.rs` for easy importing
- Example: `pub use app::App;` in main module

**Barrel Files:**
- Python: `__init__.py` files import and re-export key types for public API
  - Example: `from .models import JobState, JobDetails` in `__init__.py`
- Rust: Not used (explicit imports preferred per Rust idiom)

**Circular Dependencies:**
- Avoided through layered architecture:
  - `models.py` - Data structures (no other imports except pydantic)
  - `api.py` - Controller (depends on models)
  - `backends/*.py` - Implementations (depend on models and api)
  - `high_level/*.py` - Workflows (depend on api and models)

## Validation & Constraints

**Python (Pydantic):**
- Field validators with `@field_validator` for custom logic:
  ```python
  @field_validator('walltime')
  def validate_walltime(cls, v: str) -> str:
      # Validation logic
      return v
  ```
- Model validators with `@model_validator` for cross-field logic
- `ConfigDict(extra="forbid")` prevents unknown fields (security)

**Rust:**
- Type-driven validation (enums for restricted sets)
- Serde attributes like `#[serde(rename_all = "...")]` for schema enforcement
- Forward-compatible enum fallback: `#[serde(other)] Unknown` variant

**Bash:**
- Early validation of files: `[[ -f "$FILE" ]] || return 1`
- Environment variable defaults: `: "${VAR:=default}"`
- Strict mode: `set -euo pipefail` (exits on error, undefined vars, pipe failures)

---

*Convention analysis: 2026-02-02*
