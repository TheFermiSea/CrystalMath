# Architecture

**Analysis Date:** 2026-02-02

## Pattern Overview

**Overall:** Multi-tier monorepo with modular Bash CLI, Python/Textual TUI (primary), and Rust/Ratatui TUI (secondary/experimental). Shared database backend with clear separation between CLI execution, Python business logic, and UI layers.

**Key Characteristics:**
- **Modular CLI:** 130-line thin orchestrator with 9 specialized library modules
- **Python-First UI:** Textual-based TUI ("Workshop") handles job creation, configuration, workflows
- **Rust Secondary UI:** Ratatui TUI ("Cockpit") for read-only monitoring with feature freeze
- **Shared SQLite Backend:** Single `.crystal_tui.db` database shared between all components
- **Multi-Code Support:** CRYSTAL23, Quantum Espresso, VASP with unified template system

## Layers

**Execution Layer (CLI):**
- Purpose: Run CRYSTAL23/QE/VASP calculations with automatic parallelism, scratch management, and cleanup
- Location: `cli/bin/runcrystal` (main), `cli/lib/*.sh` (modules)
- Contains: Bash modules for config, logging, parallelism, file staging, execution
- Depends on: CRYSTAL23/QE/VASP binaries, system environment
- Used by: Users executing calculations, Python TUI job submission

**Python Backend Layer:**
- Purpose: Business logic, database access, job management, template rendering, remote execution
- Location: `python/crystalmath/` (core API), `tui/src/core/` (TUI-specific logic)
- Contains: Models, API facade, database adapter, runners (local/SSH/SLURM), orchestrator, queue manager, workflow engine
- Depends on: Pydantic, SQLite, asyncssh, AiiDA (optional), Materials Project API (optional)
- Used by: Both Python TUI and Rust TUI via bridge/FFI

**UI Layer - Python TUI (Primary):**
- Purpose: Primary user interface for job creation, configuration, template browsing, workflow execution
- Location: `tui/src/tui/` (screens, widgets), `tui/src/main.py` (entry point)
- Contains: Textual screens (jobs, new job, results, logs), widgets, async event handling
- Depends on: Python backend, Textual framework, Rich for styling
- Used by: End users doing job creation and workflow management

**UI Layer - Rust TUI (Secondary):**
- Purpose: High-performance read-only monitoring and diagnostics
- Location: `src/main.rs` (entry), `src/app.rs` (state), `src/ui/` (components)
- Contains: 60fps event loop, dirty-flag rendering, job tables, editor with LSP, results display
- Depends on: Python backend via PyO3 bridge, Ratatui, LSP client
- Used by: Users monitoring long-running calculations, **under feature freeze**

**Database Layer:**
- Purpose: Persistent storage for jobs, clusters, workflows, results
- Location: `tui/src/core/database.py` (schema, migrations), `.crystal_tui.db` (SQLite file)
- Contains: Jobs table, clusters table, workflows table with DAG, results_json column
- Depends on: SQLite
- Used by: All components (CLI, Python TUI, Rust TUI) query database

## Data Flow

**Job Submission Flow:**

1. **User creates job** (Python TUI → `NewJobScreen`)
2. **Template rendering** (TUI calls `orchestrator.submit_job()`)
3. **Job inserted to database** (status=PENDING, input_content stored)
4. **Orchestrator picks up job** (polls queue_manager for PENDING jobs)
5. **Runner executes job** (local/SSH/SLURM runner launches process)
6. **Status updates flow** (runner polls subprocess, updates job status)
7. **Results captured** (output parser extracts energy/bandgap/lattice)
8. **Database updated** (status=COMPLETE, results_json populated)
9. **UI refreshes** (Rust TUI polls Python backend via bridge, Python TUI listens for events)

**Workflow Execution Flow:**

1. **User creates workflow** (DAG-based, defined in `templates/workflows/`)
2. **Orchestrator resolves DAG** (topological sort, identifies independent nodes)
3. **Node execution** (each node can be template or data_transfer node)
4. **Data transfer** (intermediate files transferred between nodes)
5. **Status tracking** (workflow status = min(node statuses))
6. **Error handling** (continue/fail-fast based on workflow config)

**Remote Execution (SSH/SLURM):**

1. **User configures cluster** (name, hostname, username, queue_type)
2. **Cluster saved to database** (clusters table)
3. **SSH runner connects** (asyncssh with host key verification enabled)
4. **Files staged** (sftp upload to remote work directory)
5. **Job script submitted** (for SLURM: sbatch; for SSH: direct execution)
6. **Status polled** (sacct for SLURM, ps/log tailing for SSH)
7. **Results retrieved** (sftp download from remote work directory)

**LSP Editor Integration (Rust TUI):**

1. **Editor opened** (file path recognized, DFT code type detected)
2. **LSP server spawned** (dft-language-server subprocess)
3. **File opened notification** (LSP textDocument/didOpen)
4. **Changes debounced** (200ms debounce on keystrokes)
5. **Diagnostics received** (JSON-RPC 2.0 textDocument/publishDiagnostics)
6. **UI updated** (diagnostic markers displayed inline)
7. **Server gracefully degraded** (if unavailable, editor works without diagnostics)

**Python Bridge (Rust TUI):**

1. **PyO3 initialization** (configure_python_env sets PYTHONHOME)
2. **Bridge service spawned** (worker thread runs async event loop)
3. **Rust sends request** (BridgeRequestKind via mpsc channel)
4. **Python backend executes** (CrystalController method called)
5. **Response returned** (serde JSON serialization)
6. **Rust parses response** (ApiResponse wrapper unwrapped)

## Key Abstractions

**CrystalController (Python API):**
- Purpose: Single facade for all Python backend operations
- Examples: `python/crystalmath/api.py`
- Pattern: Factory for backend selection (AiiDA/SQLite/Demo), returns Pydantic models

**Job/JobDetails Models:**
- Purpose: Typed representation of job state
- Examples: `python/crystalmath/models.py`, `src/models.rs`
- Pattern: Pydantic in Python with serde in Rust for serialization

**Runner Interface:**
- Purpose: Abstract different execution backends (local, SSH, SLURM)
- Examples: `tui/src/runners/base.py`, `tui/src/runners/local.py`, `tui/src/runners/ssh_runner.py`
- Pattern: Base class with run()/poll()/kill() methods, JobStatus enum for state tracking

**Orchestrator:**
- Purpose: DAG-based workflow execution with dependency resolution
- Examples: `tui/src/core/orchestrator.py`
- Pattern: Topological sort of workflow DAG, concurrent execution with safe atexit cleanup

**Template System:**
- Purpose: Jinja2-based DFT input generation with sandboxing
- Examples: `tui/src/core/templates.py`, `tui/templates/*/`
- Pattern: SandboxedEnvironment for safety, custom filter registry, YAML config parsing

**Queue Manager:**
- Purpose: Thread-safe job queue with state transitions
- Examples: `tui/src/core/queue_manager.py`
- Pattern: Main loop polls database, maintains job state machine (PENDING→RUNNING→COMPLETE)

**Connection Manager:**
- Purpose: Thread-safe SSH connection pooling
- Examples: `tui/src/core/connection_manager.py`
- Pattern: Connection cache keyed by (hostname, username), RLock for thread safety

## Entry Points

**CLI:**
- Location: `cli/bin/runcrystal`
- Triggers: User runs `runcrystal input.d12 [nprocs]`
- Responsibilities: Parse args, load modules, manage execution, cleanup

**Python TUI:**
- Location: `tui/src/main.py`
- Triggers: User runs `crystal-tui` or `uv run crystal-tui`
- Responsibilities: Initialize Textual app, connect to database, handle user input

**Rust TUI:**
- Location: `src/main.rs`
- Triggers: User runs `./target/release/crystalmath`
- Responsibilities: Configure Python env, spawn bridge service, run 60fps event loop

**Workflow Daemon (Planned):**
- Would poll database for PENDING workflows
- Execute orchestrator DAG
- Update job/workflow status

## Error Handling

**Strategy:** Layered error handling with recovery attempts

**CLI Error Handling:**

**Patterns:**
- Bash `set -euo pipefail` for strict mode
- `|| EXIT_CODE=$?` to capture CRYSTAL23 exit codes
- Error analysis: `analyze_failure()` inspects output for known patterns
- Graceful degradation: `stage_retrieve_results` runs even if execution failed
- Cleanup guaranteed: Trap-based cleanup on EXIT

**Python TUI Error Handling:**

**Patterns:**
- Exceptions caught and displayed in status bar
- Modal dialogs for critical errors
- Database transactions with rollback on failure
- SSH/SLURM timeouts handled with user notification
- Async exception propagation via event messages

**Rust TUI Error Handling:**

**Patterns:**
- `anyhow::Result<T>` for propagation
- PyO3 exception conversion to Rust errors
- Non-fatal errors stored in `app.last_error` (auto-clears after 5s)
- LSP server unavailable → editor works without diagnostics
- Database connection fails → demo mode with empty job list

## Cross-Cutting Concerns

**Logging:**
- CLI: `cry_log()`, `cry_warn()`, `cry_error()` from `lib/cry-logging.sh`
- Python: Standard `logging` module with handlers
- Rust: `tracing` crate with `tracing_subscriber` for structured logging

**Validation:**
- CLI: File existence checks, input validation before execution
- Python: Pydantic model validation, SSH key verification (never `known_hosts=None`)
- Rust: serde JSON validation on bridge responses

**Authentication:**
- SSH: Host key verification enabled, keyring for credential storage
- SLURM: SSH-based, inherits host key verification
- Materials Project API: API key from environment variable

**Sandbox Security:**
- Template rendering: `jinja2.sandbox.SandboxedEnvironment` prevents code injection
- Workflow conditions: AST-based `_safe_eval_condition()` with whitelisted operations
- Shell escaping: Command building with proper quoting for SLURM scripts

**Concurrency:**
- Python: asyncssh for concurrent SSH connections, Queue for job polling
- Rust: tokio for async event handling, mpsc channels for bridge communication
- Database: SQLite transaction isolation, RLock for connection manager

---

*Architecture analysis: 2026-02-02*
