# External Integrations

**Analysis Date:** 2026-02-02

## APIs & External Services

**Materials Project (Phase 4):**
- Materials Project API - Crystal structure and properties database
  - SDK/Client: `mp-api>=0.45`
  - Auth: `MP_API_KEY` environment variable
  - Implementation: `tui/src/core/materials_api/clients/mp_api.py`
  - Features: Search by formula, get structures, material properties

- MPContribs API - User contributions to Materials Project
  - SDK/Client: `mpcontribs-client>=5.10`
  - Auth: `MPCONTRIBS_API_KEY` (falls back to `MP_API_KEY`)
  - Implementation: `tui/src/core/materials_api/clients/mpcontribs.py`

- OPTIMADE API - Cross-database structure federation
  - SDK/Client: `optimade[http_client]>=1.2`
  - Auth: None (public federation)
  - Implementation: `tui/src/core/materials_api/clients/optimade.py`
  - Purpose: Fallback search when Materials Project returns no results

**LLM Integration (optional):**
- Anthropic Claude API
  - SDK: `anthropic>=0.39.0`
  - Auth: `ANTHROPIC_API_KEY` environment variable
  - Framework: LangChain 0.3.0+ with `langchain-anthropic>=0.3.0`
  - Purpose: Error diagnosis, natural language input (future phases)

## Data Storage

**Databases:**
- SQLite3 (local/embedded)
  - Database file: `.crystal_tui.db`
  - Client: `sqlite3` (Python stdlib), Rust stdlib
  - Async client: `aiosqlite>=0.20.0` (Python TUI, Materials API cache)
  - Purpose: Job history, cluster configs, workflow DAGs, Materials API cache
  - Schema: Jobs, Clusters, Workflows, WorkflowJobs, Materials cache
  - Shared: Both Python TUI and Rust TUI read/write same database

- PostgreSQL (optional, for AiiDA Phase 3)
  - Adapter: `psycopg2-binary>=2.9`
  - Purpose: AiiDA workflow engine state storage
  - Requirement: PostgreSQL 12+
  - Only used when AiiDA integration is installed

**File Storage:**
- Local filesystem (primary)
  - Input files: `.d12` (CRYSTAL), `.gui` (geometry), `.f9` (wave function)
  - Output files: `.out`, `.xyz`, results JSON
  - Scratch directory: `$CRY_SCRATCH_BASE/cry_<jobname>_<pid>/`
  - Default location: `~/tmp_crystal/`

- Remote filesystem (SSH Phase 2)
  - SFTP via `asyncssh>=2.14.0`
  - Cluster configurations stored in SQLite
  - Connection pooling via `ConnectionManager` in `tui/src/core/connection_manager.py`

**Caching:**
- aiosqlite for Materials API cache
  - Location: `.crystal_tui.db` cache tables
  - TTL: Configurable (default 30 days for structures, 7 days for searches)
  - Strategy: Cache-first, fall through to API on miss/expiry

## Authentication & Identity

**SSH Authentication:**
- Framework: `asyncssh>=2.14.0`
- Methods:
  - SSH private key (from filesystem or SSH agent)
  - Password authentication (with host key verification)
  - Keyring-based credential storage (system keyring fallback)
- Implementation: `tui/src/core/connection_manager.py`
  - Class: `ConnectionManager`
  - Methods: `connect()`, `store_password()`, `retrieve_password()`, `delete_password()`
- Security:
  - Always enabled host key verification (`known_hosts` checking)
  - Secure credential storage via `keyring>=24.0.0` (platform keyring fallback)
  - Connection retry with backoff (max 3 retries, 60s timeout)
  - Example error: `asyncssh.HostKeyNotVerifiable` if host key cannot be verified

**Materials Project API:**
- Key-based authentication via HTTP headers
- Environment variable: `MP_API_KEY`
- Implementation: `tui/src/core/materials_api/clients/mp_api.py`
- Error handling: `AuthenticationError` raised on invalid/missing key

**Keyring Integration:**
- System: macOS Keychain, Linux Secret Service, Windows Credential Manager
- Fallback: In-memory storage if keyring unavailable
- Purpose: Store SSH passwords, API keys securely
- Location: `tui/src/core/connection_manager.py` (password storage)

## Monitoring & Observability

**Error Tracking:**
- None detected (error handling is local)

**Logs:**
- Python logging module (standard library)
  - Loggers: Per-module loggers via `logging.getLogger(__name__)`
  - Format: Time, level, module, message
  - Handlers: Console + file (if configured)
  - Usage: `tui/src/core/`, `tui/src/runners/`

- Rust tracing crate
  - Subscribers: `tracing_subscriber` with env-filter support
  - Format: Structured logging with timestamps
  - Env var: `RUST_LOG` for filtering
  - Usage: `src/bridge.rs`, `src/lsp.rs`, `src/app.rs`

- Bash logging
  - Module: `cli/lib/cry-logging.sh`
  - Functions: `cry_log()`, `cry_warn()`, `cry_error()`, `cry_fatal()`
  - Verbosity levels: silent, normal, verbose

## CI/CD & Deployment

**Hosting:**
- GitHub (repository)
- Local/remote execution only (no web backend)

**CI Pipeline:**
- GitHub Actions (inferred from `.github/` directory, untracked)
- Testing: pytest (Python), cargo test (Rust), bats (Bash)
- Linting: Black, Ruff, MyPy (Python), Clippy (Rust)
- Build: Hatchling (Python), Cargo (Rust)

## Environment Configuration

**Required env vars:**
- `CRY23_ROOT` - CRYSTAL23 installation path
- `MP_API_KEY` - Materials Project API key (for Materials API queries)

**Optional env vars:**
- `CRY_SCRATCH_BASE` - Scratch directory (default: ~/tmp_crystal)
- `PYTHONPATH` - Python module path (auto-set by build-tui.sh)
- `PYO3_PYTHON` - Python path for PyO3 (auto-detected)
- `RUST_LOG` - Rust logging level (tracing-subscriber)
- `CRYSTAL_TUI_DB` - Database path override
- `SSH_KEY_PATH` - SSH private key location

**Secrets Location:**

Python TUI:
- SSH passwords: System keyring (macOS Keychain, Linux Secret Service)
- API keys: Environment variables or .env file (via python-dotenv)
- Database: SQLite file (plaintext, credentials in connection strings)

Rust TUI:
- Shares SSH/API credentials via Python bridge (via crystalmath API)
- Database credentials: Retrieved from Python backend
- LSP server path: Auto-detected or env var

## Remote Execution

**SSH Execution (Phase 2):**
- Implementation: `tui/src/runners/ssh_runner.py`
  - Class: `SshRunner`
  - Protocol: SSH with SFTP file transfer
  - Authentication: Key-based or password
  - Concurrency: Per-job SSH connection (no pooling, new connection per job)

**SLURM Scheduling (Phase 2):**
- Implementation: `tui/src/runners/slurm_runner.py`
  - Class: `SlurmRunner`
  - Interface: SSH + sbatch/squeue commands
  - Features: Job submission, cancellation, queue monitoring
  - Templates: SLURM batch scripts (jinja2-templated)

**Local Execution:**
- Implementation: `tui/src/runners/local.py`
  - Class: `LocalRunner`
  - Process isolation: Per-job subprocess
  - Cleanup: SIGTERM → SIGKILL escalation with 10s timeout
  - Output handling: Real-time stdout/stderr streaming

## Webhooks & Callbacks

**Incoming:**
- None detected

**Outgoing:**
- Job status callbacks (planned for workflow automation Phase 1)
- Event-driven: Job completion, convergence checks, batch submissions

## Rust-Python IPC Boundary

**Bridge Protocol (JSON-RPC 2.0):**
- Location: `src/bridge.rs` (Rust side), `python/crystalmath/api.py` (Python side)
- Transport: JSON strings over PyO3 FFI
- Methods: Thin request/response pattern
- Key methods:
  - `fetch_jobs()` - Get job list from database
  - `fetch_clusters()` - Get cluster configurations
  - `submit_job()` - Create new job
  - `get_job_details()` - Fetch job state and results
  - `search_materials()` - Materials API queries
  - `generate_crystal_input()` - CRYSTAL input generation from structure

**Async Communication:**
- Rust side: Tokio mpsc channels (request → response)
- Python side: asyncio event loop in worker thread
- Non-blocking: Rust UI calls bridge async, continues rendering 60fps
- Error handling: JSON-RPC error codes in responses

## LSP Integration

**dft-language-server:**
- Type: External Node.js process
- Protocol: JSON-RPC 2.0 over stdio (Content-Length framing)
- Auto-launch: From `dft-language-server/` directory
- Graceful degradation: If server unavailable, editor works without diagnostics
- Implementation: `src/lsp.rs`
  - Spawn: `Command::new("node").arg("out/server.js")`
  - Communication: BufRead/Write with JSON-RPC serialization
  - Languages: CRYSTAL (.d12), VASP (INCAR, POSCAR, KPOINTS)
  - Diagnostics: Syntax errors, warnings (displayed in editor)

**Editor Integration:**
- UI Component: `src/ui/editor.rs`
- File types: `.d12` (CRYSTAL), `INCAR`/`POSCAR`/`KPOINTS` (VASP)
- Debounce: 200ms on editor changes before sending to LSP
- Async: Diagnostics received via mpsc channel, non-blocking render

## Materials API Cache

**Implementation:**
- Location: `tui/src/core/materials_api/cache.py`
- Database: aiosqlite tables in `.crystal_tui.db`
- Tables: `materials_cache` (structures, properties, searches)
- Async: `async def get()`, `async def set()`, `async def invalidate()`
- TTL: Configurable per entry type (30 days for structures, 7 days for searches)
- Key generation: Hash of query (formula, API type) + source

## AiiDA Integration (Phase 3)

**Components:**
- aiida-core>=2.7,<3.0 - Workflow engine
- psycopg2-binary - PostgreSQL driver
- aiida-vasp - VASP code plugin
- aiida-quantumespresso - Quantum ESPRESSO plugin

**Database:**
- PostgreSQL 12+ required (not SQLite)
- Connection: Via aiida profile configuration
- Purpose: Workflow DAG storage, job tracking, distributed execution

**Job Store Bridge:**
- Location: `python/crystalmath/integrations/jobflow_store.py`
- Class: `CrystalMathJobStore`
- Purpose: Allow atomate2 workflows to write results to `.crystal_tui.db`

**Optional RabbitMQ:**
- Used for distributed AiiDA workers
- Not required for single-machine workflows

## DFT Code Support Matrix

| Code | Status | Input Files | Output Parser | Notes |
|------|--------|-------------|---|---|
| CRYSTAL23 | Primary | `.d12`, `.gui`, `.f9`, `.born` | Built-in | Main use case |
| VASP | Secondary | INCAR, POSCAR, KPOINTS, POTCAR | `vasp_progress.py` | Phase 3 (AiiDA plugin) |
| Quantum ESPRESSO | Optional | `pw.in` | `qe_progress.py` | Phase 3 (AiiDA plugin) |

## Pymatgen Bridge

**Implementation:**
- Location: `python/crystalmath/integrations/pymatgen_bridge.py`
- Class: `PymatgenBridge`
- Purpose: Structure handling, DFT code input generation
- Lazy loading: Imports only when `has_pymatgen()` is True
- Soft dependency: Not required for core functionality

---

*Integration audit: 2026-02-02*
