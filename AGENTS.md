# CrystalMath Agent Guidelines

This file outlines the operational procedures, build commands, and coding standards for agents working in the CrystalMath repository.

## 1. Project Architecture & Scope

This is a monorepo containing a unified tool for CRYSTAL23 DFT calculations:

*   **CLI** (`cli/`): Production Bash tools. Thin orchestrator (`bin/runcrystal`) loading modules (`lib/`).
*   **Python TUI (Primary)** (`tui/`): Textual-based interface for *creating*, *configuring*, and *monitoring* jobs. Preferred UI for new features and workflows.
*   **Rust TUI (Secondary)** (`src/` + `python/`): High-performance Ratatui interface for monitoring; treated as secondary/experimental until a stable IPC boundary replaces PyO3 coupling.

**Crucial Philosophy**:
*   **Primary UI (Python/Textual)**: The source of truth for user interaction and workflows.
*   **Secondary UI (Rust/Ratatui)**: Optional monitoring cockpit; no new feature work without a stable IPC boundary.
*   **Python Backend**: Provides business logic, database access, and scientific computing capabilities.
*   **Shared State**: All tools use the same `.crystal_tui.db` SQLite database.

## 2. Build, Test, & Lint Commands

### A. CLI (Bash)
Work directory: `cli/`
*   **Run All Tests**: `bats tests/unit/*.bats`
*   **Run Single Test File**: `bats tests/unit/cry-parallel_test.bats`
*   **Integration Tests**: `bats tests/integration/*.bats`
*   **Manual Run**: `bin/runcrystal --explain my_job` (Dry run)

### B. Rust TUI (Secondary) + Python Backend
Work directory: Root for Rust, `python/` for backend.

**Rust Frontend**:
*   **Build (CRITICAL)**: Use `./scripts/build-tui.sh` to ensure PyO3 links to the correct Python version.
    *   *Never* just run `cargo build` if the python env is uncertain.
*   **Run Tests**: `cargo test`
*   **Run Single Test**: `cargo test test_name`
*   **Lint**: `cargo clippy` (must be clean)
*   **Format**: `cargo fmt --check`

**Python Backend (`python/`)**:
*   **Setup**: `cd python && uv pip install -e .`
*   **Test**: `pytest`
*   **Lint**: `black . && ruff check .`

### C. Python TUI (Primary)
Work directory: `tui/`
*   **Setup**: `uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"`
*   **Run All Tests**: `pytest`

## 3. Code Style & Standards

### General
*   **Commits**: Use Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`). Keep scope small and description present tense.
*   **Secrets**: NEVER commit credentials or machine-specific paths. Use environment variables.

### Bash (`cli/`)
*   **Indent**: 4 spaces.
*   **Variables**: Always use `local` inside functions. Snake_case (`my_var`).
*   **Safety**: Use `[[ ... ]]` for tests. Quote variables `"${VAR}"`.
*   **Structure**: Modular design. `bin/runcrystal` is just a loader. Logic goes in `lib/`.
*   **Error Handling**: Functions return exit codes (0 success, non-0 failure). Main script handles traps/cleanup.

### Python (`tui/`, `python/`)
*   **Formatter**: Black (100 columns for TUI, 88 standard).
*   **Linter**: Ruff (Strict: E, F, W, I, N, UP, B, A, C4, SIM).
*   **Typing**: `mypy` strict. Type hints are mandatory for new code.
*   **Async**: Heavy use of `asyncio` in TUI. Avoid blocking calls in the main event loop.
*   **Security**:
    *   Jinja2: Must use `SandboxedEnvironment`.
    *   SSH: Never disable host key verification (`known_hosts=None` is forbidden).
    *   Eval: Never use raw `eval()`. Use AST-based whitelisting for conditions.

### Rust (`src/`)
*   **Style**: Standard Rust idioms. `cargo fmt` mandatory.
*   **Models**: `src/models.rs` must match Python Pydantic models via `serde`.
*   **Architecture**:
    *   **Dirty-Flag Rendering**: Only draw when `app.needs_redraw()` is true.
    *   **FFI**: `bridge.rs` handles PyO3. Don't put business logic here; delegate to Python backend or Rust internal state.
    *   **LSP**: Non-blocking `mpsc` channels for communication.

## 4. Workflow & Issue Tracking (Beads)

**Mandatory**: This repo uses `bd` (Beads) for all issue tracking.
*   **Start Work**:
    1.  `bd ready` to see available tasks.
    2.  `bd update <id> --status in_progress` to claim.
*   **During Work**:
    *   Create sub-tasks if needed: `bd create "Subtask" --deps parent:<id>`.
    *   Link discoveries: `bd create "Found bug" --deps discovered-from:<id>`.
*   **Finish Work**:
    1.  Verify tests pass.
    2.  `bd close <id> --reason "Implemented via PR #..."`
    3.  Commit the `.beads/issues.jsonl` file updates along with your code.

## 5. Directory Structure Reference

```text
.
├── cli/                # Bash CLI
│   ├── bin/            # Entry points
│   ├── lib/            # Modules
│   └── tests/          # .bats tests
├── tui/                # Python Workshop TUI
│   ├── src/            # Source (textual app)
│   └── tests/          # pytest
├── src/                # Rust Cockpit TUI source
├── python/             # Python backend for Rust TUI
├── Cargo.toml          # Rust config
├── .beads/             # Issue database
└── scripts/            # Build helpers (build-tui.sh)
```

## 6. Agent "Do Not" List

1.  **Do not** edit `.cursor/rules` or `AGENTS.md` unless explicitly asked to improve instructions.
2.  **Do not** bypass `scripts/build-tui.sh` when building the Rust binary if you are changing Python dependencies.
3.  **Do not** leave broken tests. If you change behavior, update the test.
4.  **Do not** introduce new Python dependencies without adding them to `pyproject.toml` (in `tui/` or `python/`).
5.  **Do not** hardcode paths like `/Users/brian...`. Use env vars: `CRY23_ROOT`, `CRY_SCRATCH_BASE`.
