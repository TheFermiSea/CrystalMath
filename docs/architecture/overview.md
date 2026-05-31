# Architecture Overview

This document provides a high-level overview of the CrystalMath monorepo architecture, covering both the CLI and TUI components.

> **Direction (ADR-006, 2026-05-31):** The project is unifying on a single
> Rust/Ratatui TUI (`src/`) as the **primary** UI. It handles job creation,
> configuration, and workflows, and communicates with the Python core over an
> IPC boundary — client in `src/ipc/` (`client.rs` + `framing.rs`), server in
> `python/crystalmath/server/`. The legacy Python/Textual TUI (`tui/`) is
> **deprecated** and being phased out. See
> [ADR-003](adr-003-ipc-boundary-design.md) (IPC boundary) and
> [ADR-006](adr-006-unify-on-rust-tui.md) (unification). The "TUI Architecture"
> section below describes the legacy Python TUI and is retained for historical
> reference.

## Repository Structure

```
crystalmath/
├── cli/                         # Bash CLI Tool
│   ├── bin/runcrystal          # Main executable
│   ├── lib/                    # 9 modular libraries
│   ├── tests/                  # 173 bats tests (unit + integration)
│   ├── share/tutorials/        # CRYSTAL documentation mirror
│   └── docs/                   # Detailed CLI architecture
│
├── src/                        # Rust/Ratatui TUI (PRIMARY UI)
│   ├── app.rs                  # Application state, tabs, dirty-flag render
│   ├── bridge.rs               # PyO3 FFI to Python core (legacy transport)
│   ├── ipc.rs + ipc/           # IPC client: client.rs, framing.rs
│   ├── lsp.rs                  # LSP client (vendored vasp-language-server)
│   ├── models.rs               # Data models (serde, match Python)
│   ├── monitor.rs              # Monitoring state
│   ├── prometheus.rs           # Prometheus metrics scraping
│   ├── state/                  # mod.rs, actions.rs, help.rs
│   └── ui/                     # One file per screen (jobs, editor, results,
│                               #   log, materials, cluster_manager,
│                               #   slurm_queue, vasp_input, monitor,
│                               #   workflows, recipes, batch_submission, ...)
│
├── python/                     # crystalmath core package
│   ├── crystalmath/            # models, api, templates, backends
│   │   ├── server/             # IPC server (crystalmath-server entry point)
│   │   └── backends/           # CRYSTAL23, VASP, Quantum ESPRESSO, Yambo, phonopy
│   └── tests/
│
├── tui/                        # Python/Textual TUI (DEPRECATED, being phased out)
│
├── docs/                       # Shared documentation
│   └── architecture/           # overview.md (this file), integration.md, adr-*.md
│
├── .beads/                     # Unified issue tracker (Dolt-backed)
│
└── examples/                   # Example calculations
```

## CLI Architecture

### Design Philosophy

**From Monolith to Modular:** The CLI was refactored from a 372-line monolithic script into a thin 130-line orchestrator with 9 specialized library modules.

**Key Principles:**
- **Separation of Concerns:** Each module has one responsibility
- **Testability:** Modules are unit-testable with mocks
- **Composability:** Functions accept state references, return exit codes
- **Reliability:** Trap-based cleanup guarantees resource cleanup
- **Educational:** `--explain` mode teaches HPC concepts

### Module Architecture

```
bin/runcrystal (130 lines)
  ├─> lib/cry-config.sh      # Configuration & environment
  ├─> lib/cry-logging.sh     # Logging infrastructure
  ├─> lib/core.sh            # Module loader (cry_require)
  ├─> lib/cry-ui.sh          # Visual components (gum wrappers)
  ├─> lib/cry-parallel.sh    # MPI/OpenMP parallelism
  ├─> lib/cry-scratch.sh     # Scratch space management
  ├─> lib/cry-stage.sh       # File staging utilities
  ├─> lib/cry-exec.sh        # Calculation execution
  └─> lib/cry-help.sh        # Help system
```

**Module Loading Order:**
1. `cry-config.sh` - Bootstrap (paths, theme, gum)
2. `cry-logging.sh` - Logging (cry_log, cry_fatal)
3. `core.sh` - Module loader (cry_require)
4. Remaining modules loaded via `cry_require`

### State Management

**CRY_JOB Associative Array:**
```bash
declare -A CRY_JOB

# Populated by modules
CRY_JOB[MODE]="hybrid"              # serial|hybrid
CRY_JOB[MPI_RANKS]=14               # Number of MPI processes
CRY_JOB[THREADS_PER_RANK]=4         # OpenMP threads per rank
CRY_JOB[EXE_PATH]="/path/to/Pcrystal"  # Binary to execute
CRY_JOB[input_d12]="calc.d12"       # Input file
CRY_JOB[file_prefix]="calc"         # Job name
```

**Passed by reference between modules:**
```bash
parallel_setup "$NPROCS" CRY_JOB
scratch_create "${CRY_JOB[file_prefix]}"
stage_inputs CRY_JOB
exec_crystal_run CRY_JOB
```

### Execution Flow

```
1. Parse arguments (input file, nprocs, flags)
   ├─> Validate input file exists
   └─> Extract file prefix

2. Initialize CRY_JOB state
   └─> Declare associative array

3. Setup trap for cleanup
   └─> trap 'scratch_cleanup' EXIT

4. Display banner
   └─> ui_banner with job info

5. Configure parallelism
   ├─> parallel_setup
   │   ├─> Detect system cores
   │   ├─> Calculate thread distribution
   │   ├─> Select binary (crystalOMP vs PcrystalOMP)
   │   └─> Export environment variables

6. Create scratch workspace
   └─> scratch_create ~/tmp_crystal/cry_<job>_<pid>/

7. Stage input files
   ├─> stage_inputs
   │   ├─> Copy input.d12 → scratch/INPUT
   │   ├─> Auto-discover auxiliary files
   │   ├─> Stage .gui → fort.34
   │   ├─> Stage .f9 → fort.9
   │   └─> Stage .hessopt → HESSOPT.DAT

8. Execute calculation
   ├─> exec_crystal_run
   │   ├─> Build command (serial or mpirun)
   │   ├─> Wrap with gum spin (if available)
   │   └─> Run in scratch directory

9. Retrieve results
   ├─> stage_retrieve_results
   │   ├─> Copy OUTPUT → calc.out
   │   ├─> Copy fort.9 → calc.f9
   │   ├─> Copy fort.98 → calc.f98
   │   └─> Copy HESSOPT.DAT → calc.hessopt

10. Report status
    ├─> ui_success (if exitcode=0)
    └─> ui_error (if exitcode≠0)

11. Cleanup (automatic via trap)
    └─> scratch_cleanup
        └─> rm -rf ~/tmp_crystal/cry_<job>_<pid>/
```

### Parallelism Strategy

**Serial Mode** (NPROCS ≤ 1):
```bash
Binary: crystalOMP
Threads: All available cores (e.g., 56)
Command: crystalOMP < INPUT > OUTPUT
```

**Hybrid Mode** (NPROCS > 1):
```bash
Binary: PcrystalOMP
Ranks: User-specified (e.g., 14)
Threads: cores / ranks (e.g., 56/14 = 4)
Environment:
  - OMP_NUM_THREADS=4
  - I_MPI_PIN_DOMAIN=omp
  - KMP_AFFINITY=compact,1,0,granularity=fine
  - OMP_STACKSIZE=256M
Command: mpirun -n 14 PcrystalOMP < INPUT > OUTPUT
```

### Error Handling

**Module Level:**
- Functions return exit codes (0 = success, non-zero = error)
- Main script checks return codes and decides on error handling
- Critical errors use `cry_fatal` (logs and exits)

**Resource Cleanup:**
- Trap-based cleanup: `trap 'scratch_cleanup' EXIT`
- Guaranteed cleanup even on error or interrupt
- Idempotent cleanup function (safe to call multiple times)

**Detailed CLI Architecture:** See `cli/docs/ARCHITECTURE.md`

## TUI Architecture (Legacy Python/Textual — Deprecated)

> This section documents the deprecated Python/Textual TUI (`tui/`), retained for
> historical reference. The primary UI is now the Rust/Ratatui TUI (`src/`) — see
> [ADR-006](adr-006-unify-on-rust-tui.md).

### Design Philosophy

**Modern Terminal UI:** Built on Textual framework for async TUI development with CSS-based styling.

**Key Principles:**
- **Database-Backed:** SQLite for persistent job history
- **Async-First:** Built on asyncio for responsive UI
- **Message-Driven:** Textual message system for event handling
- **Modular:** Separation of UI, logic, and execution
- **Extensible:** Plugin-based runner system

### Component Structure

```
src/crystal_tui/
├── tui/                        # UI Layer (Textual)
│   ├── app.py                 # Main application
│   ├── screens/               # Modal screens
│   │   └── new_job.py         # Job creation modal
│   └── widgets/               # Custom widgets
│
├── core/                      # Business Logic
│   ├── database.py            # SQLite ORM
│   ├── job.py                 # Job state management
│   ├── project.py             # Project management
│   └── crystal_io.py          # CRYSTALpytools integration
│
└── runners/                   # Execution Backends
    ├── local.py              # Local subprocess runner
    ├── remote.py             # SSH/SLURM runner (Phase 2)
    └── cli_backend.py        # CLI integration (planned)
```

### Data Model

**SQLite Schema:**
```sql
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    input_content TEXT,              -- .d12 file content
    status TEXT,                     -- pending|running|completed|failed
    created_at TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    exit_code INTEGER,
    stdout_log TEXT,                 -- Real-time log
    stderr_log TEXT,
    results_json TEXT,               -- Structured results
    work_dir TEXT,                   -- Path to calculations/N_name/
    pid INTEGER                      -- Process ID when running
);
```

**Job Lifecycle:**
```
pending → running → completed
              ↓
           failed
              ↓
          (can be re-run)
```

### UI Layout

```
┌─────────────────────────────────────────────────────┐
│ CRYSTAL-TUI                                   [q]uit│
├─────────────┬───────────────────────────────────────┤
│             │                                       │
│  Jobs       │  Content Tabs                        │
│  (Table)    │  ┌──────┬──────┬─────────┐          │
│             │  │ Log  │Input │ Results │          │
│  [n] New    │  └──────┴──────┴─────────┘          │
│  [r] Run    │                                       │
│  [s] Stop   │  Selected Tab Content                │
│             │                                       │
│             │                                       │
│             │                                       │
│             │                                       │
│             │                                       │
│             │                                       │
│             │                                       │
└─────────────┴───────────────────────────────────────┘
```

**Three-Panel Design:**
1. **Jobs List (Left):** DataTable with job status, timestamps
2. **Log Tab (Right):** Real-time stdout/stderr streaming
3. **Input Tab (Right):** .d12 file preview with syntax highlighting
4. **Results Tab (Right):** Parsed results (energy, geometry, errors)

### Message Architecture

**Textual Message System:**
```python
# Messages for inter-component communication
class JobSelected(Message):
    """Posted when user selects a job"""
    def __init__(self, job_id: int):
        self.job_id = job_id

class JobStatusChanged(Message):
    """Posted when job status updates"""
    def __init__(self, job_id: int, status: str):
        self.job_id = job_id
        self.status = status

class LogLineAdded(Message):
    """Posted when new log line available"""
    def __init__(self, job_id: int, line: str):
        self.job_id = job_id
        self.line = line
```

**Event Flow:**
```
User Action → Message → Handler → Database Update → UI Refresh
```

### Async Execution

**Worker System:**
```python
async def run_job(self, job_id: int):
    """Execute job asynchronously"""
    # Update status
    await self.db.update_job(job_id, status="running")

    # Run in worker
    self.run_worker(self._execute_job(job_id))

async def _execute_job(self, job_id: int):
    """Background job execution"""
    proc = await asyncio.create_subprocess_exec(
        "crystalOMP",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )

    # Stream output
    async for line in proc.stdout:
        await self.db.append_log(job_id, line)
        self.post_message(LogLineAdded(job_id, line))

    # Wait for completion
    await proc.wait()
    await self.db.update_job(job_id, status="completed", exit_code=proc.returncode)
```

**Detailed TUI Architecture:** See `tui/docs/PROJECT_STATUS.md`

## Integration Architecture

### Shared Components

**1. Environment Configuration**
- Both tools source `~/CRYSTAL23/cry23.bashrc`
- Common variables: `CRY23_ROOT`, `CRY23_EXEDIR`, `CRY23_SCRDIR`
- CLI uses bash sourcing, TUI parses via Python

**2. Scratch Directory**
- Shared structure: `~/tmp_crystal/`
- CLI: `cry_<job>_<pid>/`
- TUI: `crystal_tui_<job>_<pid>/`
- Both clean up after completion

**3. File Staging Protocol**
- Common input/output naming convention
- Auxiliary file mapping (.gui → fort.34, etc.)
- Result file retrieval pattern

**4. Result Parsing**
- TUI uses CRYSTALpytools directly
- CLI can optionally call CRYSTALpytools via Python
- Common structured output format (JSON)

### Communication Patterns

**Current: Shared Database + IPC Boundary**
- All tools share the `.crystal_tui.db` SQLite database
- The Rust TUI talks to the Python core over an IPC boundary
  (see [ADR-003](adr-003-ipc-boundary-design.md)): client in `src/ipc/`
  (`client.rs` + `framing.rs`), server in `python/crystalmath/server/`
  (the `crystalmath-server` entry point)
- IPC transport is built; the running TUI still uses the PyO3 bridge
  (`src/bridge.rs`) — cutover to `IpcClient` is the pending keystone follow-up
- Tools also share filesystem (scratch, results) and environment variables

See `docs/architecture/integration.md` for detailed integration patterns.

## Testing Strategy

### CLI Testing

**Unit Tests** (bats-core):
- Mock external commands (gum, mpirun, crystalOMP)
- Test each module in isolation
- Coverage: 173 bats tests (unit + integration)

**Integration Tests:**
- Full workflow with mock CRYSTAL binaries
- Test file staging, execution, result retrieval
- Verify cleanup on success and error

**Test Infrastructure:**
```bash
tests/
├── helpers.bash              # Mock system, assertions
├── mocks/                    # Fake binaries (gum, mpirun)
├── unit/
│   ├── cry-config_test.bats
│   ├── cry-parallel_test.bats
│   ├── cry-scratch_test.bats
│   ├── cry-stage_test.bats
│   └── cry-ui_test.bats
└── integration/
    └── full_workflow_test.bats
```

### TUI Testing

**Unit Tests** (pytest, planned):
- Mock database operations
- Test job state transitions
- Test CRYSTALpytools integration
- Test runner backends

**UI Tests** (Textual snapshots, planned):
- Snapshot testing for UI layout
- Event handling verification
- Message flow testing

**Integration Tests:**
- Full job lifecycle (create → run → complete)
- Database persistence
- File I/O operations

## Performance Considerations

### CLI Performance

**Startup Time:** <100ms (bash script)
**Memory:** ~10MB (bash process)
**Execution Overhead:** Minimal (subprocess spawn only)
**Parallelism:** Native (MPI + OpenMP)

**Bottlenecks:**
- None significant (orchestrator only)
- Actual CRYSTAL execution dominates time

### TUI Performance

**Startup Time:** ~1-2s (Python import + database init)
**Memory:** ~50-100MB (Python + Textual + SQLite)
**UI Responsiveness:** 60 FPS (Textual framework)
**Async I/O:** Non-blocking subprocess management

**Bottlenecks:**
- Database queries (optimized with indexes)
- Log rendering (virtualized with Rich)
- Result parsing (CRYSTALpytools)

## Security Considerations

### CLI Security

- **Input Validation:** File path sanitization
- **Command Injection:** All user input escaped
- **Scratch Permissions:** 0700 (user-only)
- **Cleanup Guarantee:** Trap-based, idempotent

### TUI Security

- **SQL Injection:** Parameterized queries only
- **Path Traversal:** Validate work_dir paths
- **Process Isolation:** Subprocess security
- **Database Permissions:** 0600 (user-only)

## Deployment Patterns

### Local Workstation
- Both tools installed locally
- Shared CRYSTAL23 installation
- Fast scratch on SSD

### HPC Cluster (Planned)
- CLI: Installed on compute nodes
- TUI: Run on login node
- TUI submits via CLI to SLURM

### Remote Access (Planned)
- TUI running on server
- SSH forwarding for terminal
- CLI executes on remote host

## Architecture Evolution

### Shared Database ✅
- CLI, Rust TUI, and Python core all share the `.crystal_tui.db` SQLite database

### IPC Boundary ✅ (built; cutover pending)
- Rust TUI ↔ Python core over IPC (see [ADR-003](adr-003-ipc-boundary-design.md))
- Client in `src/ipc/` (`client.rs` + `framing.rs`); server in
  `python/crystalmath/server/` (`crystalmath-server` entry point)
- The running TUI still uses the PyO3 bridge (`src/bridge.rs`); cutover to
  `IpcClient` is the pending keystone follow-up

### Unify on Rust TUI 🔨 (see [ADR-006](adr-006-unify-on-rust-tui.md))
- Rust/Ratatui TUI becomes the single primary UI for job creation, config, and workflows
- Legacy Python/Textual TUI deprecated and phased out

---

**For detailed architecture documentation:**
- CLI: `cli/docs/ARCHITECTURE.md`
- IPC boundary: [ADR-003](adr-003-ipc-boundary-design.md)
- Unification direction: [ADR-006](adr-006-unify-on-rust-tui.md)
- Integration: `docs/architecture/integration.md`
