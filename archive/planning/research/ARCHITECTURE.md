# Architecture Patterns: Rust TUI with AiiDA + atomate2 Backend

**Domain:** VASP TUI with AiiDA/atomate2 workflow orchestration
**Researched:** 2026-02-02
**Confidence:** MEDIUM (verified patterns with some gaps in edge cases)

---

## Recommended Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     RUST TUI (60fps, ratatui)                    │
│  ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌──────┐ │
│  │  Jobs   │  │ Editor  │  │ Template │  │Materials│  │Cluster│ │
│  │  List   │  │ (VASP)  │  │ Browser  │  │ Search  │  │Config │ │
│  └────┬────┘  └────┬────┘  └────┬─────┘  └────┬────┘  └───┬───┘ │
└───────┼────────────┼────────────┼─────────────┼───────────┼─────┘
        │            │            │             │           │
        └────────────┴────────────┴─────────────┴───────────┘
                                  │
                     ┌────────────▼────────────┐
                     │     IPC BOUNDARY        │
                     │  (JSON-RPC 2.0 over     │
                     │   Unix Domain Socket)   │
                     └────────────┬────────────┘
                                  │
┌─────────────────────────────────▼─────────────────────────────────┐
│                    PYTHON SERVICE (crystalmath-server)            │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                    JSON-RPC Dispatcher                      │  │
│  │  jobs.list | jobs.submit | clusters.list | templates.list  │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                  │                                │
│  ┌───────────────────────────────┼───────────────────────────┐   │
│  │                     CrystalMath API                        │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐   │   │
│  │  │ InputMakers │  │ JobSubmitter │  │  ResultsParser  │   │   │
│  │  │ (atomate2)  │  │   (AiiDA)    │  │   (pymatgen)    │   │   │
│  │  └──────┬──────┘  └──────┬───────┘  └────────┬────────┘   │   │
│  └─────────┼────────────────┼───────────────────┼────────────┘   │
│            │                │                   │                 │
│  ┌─────────▼────────────────▼───────────────────▼────────────┐   │
│  │                    Integration Layer                       │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐   │   │
│  │  │  atomate2    │  │    AiiDA     │  │   pymatgen/    │   │   │
│  │  │  InputSets   │  │  WorkChains  │  │   ASE          │   │   │
│  │  │  Validators  │  │  CalcJobs    │  │   Structures   │   │   │
│  │  └──────────────┘  └──────────────┘  └────────────────┘   │   │
└──────────────────────────────────┼────────────────────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │    AiiDA DATABASE           │
                    │    (PostgreSQL + RabbitMQ)  │
                    │    - Nodes (ProcessNode)    │
                    │    - Links (provenance)     │
                    │    - Computers/Codes        │
                    └──────────────┬──────────────┘
                                   │
            ┌──────────────────────┴──────────────────────┐
            │                                              │
            ▼                                              ▼
┌───────────────────────┐                    ┌───────────────────────┐
│   AiiDA Daemon        │                    │   HPC Cluster         │
│   (RabbitMQ worker)   │ ---------------→   │   (SLURM + VASP)      │
│   - Job dispatch      │     SSH/SFTP       │   - VASP binary       │
│   - Status polling    │                    │   - POTCAR library    │
└───────────────────────┘                    └───────────────────────┘
```

### Component Boundaries

| Component | Responsibility | Communicates With | Language |
|-----------|---------------|-------------------|----------|
| **Rust TUI** | UI rendering (60fps), keyboard input, state management | Python Service via IPC | Rust |
| **IPC Client** | JSON-RPC request/response, connection management | Python Service | Rust |
| **Python Service** | Request dispatch, orchestration, stateless API | AiiDA, atomate2, pymatgen | Python |
| **InputMakers** | VASP input generation (atomate2 InputSets) | Pydantic validators | Python |
| **JobSubmitter** | CalcJob/WorkChain submission to AiiDA | AiiDA engine | Python |
| **ResultsParser** | Output parsing (pymatgen, ASE) | File I/O | Python |
| **AiiDA Core** | Workflow engine, database ORM, daemon | PostgreSQL, RabbitMQ | Python |
| **AiiDA Daemon** | Background job execution and monitoring | AiiDA Core, SSH transports | Python |

### Data Flow

```
User Action (TUI)
        │
        ▼
┌──────────────────┐
│ Rust Event Loop  │ ← 60fps, async poll
│ (crossterm)      │
└────────┬─────────┘
         │ User submits job
         ▼
┌──────────────────┐
│ IpcClient.send() │ ← Non-blocking, timeout 30s
│ JSON-RPC request │
└────────┬─────────┘
         │
         ▼ Unix Socket
┌──────────────────┐
│ Python Dispatcher│
│ jobs.submit(...)│
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ atomate2 Maker   │ ← VaspInputSet, RelaxMaker, etc.
│ - Validate inputs│
│ - Generate INCAR │
│ - Configure KPTS │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ AiiDA Submitter  │ ← engine.submit(workchain)
│ - Create nodes   │
│ - Store inputs   │
│ - Queue job      │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ AiiDA Database   │ ← ProcessNode with provenance
│ (PostgreSQL)     │
└────────┬─────────┘
         │
         ▼ (async, via daemon)
┌──────────────────┐
│ AiiDA Daemon     │ ← Polls RabbitMQ, dispatches jobs
│ - SSH to cluster │
│ - sbatch script  │
│ - Poll squeue    │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ SLURM Cluster    │
│ - Run VASP       │
│ - Store outputs  │
└──────────────────┘
```

---

## Patterns to Follow

### Pattern 1: IPC Boundary (JSON-RPC 2.0)

**What:** All communication between Rust TUI and Python backend happens over a Unix domain socket using JSON-RPC 2.0 protocol.

**Why:**
- Decouples Python version from Rust build (no PyO3 version conflicts)
- Enables standalone Rust binary distribution
- Matches existing async request/response pattern in the codebase
- Sub-millisecond latency for local IPC

**When:** All data exchange between Rust and Python.

**Example (Rust client):**
```rust
pub struct IpcClient {
    socket_path: PathBuf,
    connection: Option<UnixStream>,
    request_id: AtomicUsize,
}

impl IpcClient {
    pub async fn send_request(
        &self,
        method: &str,
        params: serde_json::Value,
    ) -> Result<serde_json::Value> {
        let request = JsonRpcRequest::new(
            method,
            params,
            self.request_id.fetch_add(1, Ordering::SeqCst) as u64,
        );

        // Send over Unix socket
        let response_json = self.send_raw(&serde_json::to_string(&request)?).await?;

        // Parse response
        let response: JsonRpcResponse = serde_json::from_str(&response_json)?;
        response.into_result()
    }
}
```

**Example (Python dispatcher):**
```python
class JsonRpcDispatcher:
    """Handle JSON-RPC 2.0 requests."""

    METHODS = {
        "jobs.list": "handle_jobs_list",
        "jobs.submit": "handle_jobs_submit",
        "jobs.cancel": "handle_jobs_cancel",
        "clusters.list": "handle_clusters_list",
        "templates.list": "handle_templates_list",
    }

    def dispatch(self, request_json: str) -> str:
        """Parse request, route to handler, return response."""
        request = json.loads(request_json)
        method = request.get("method")

        if method not in self.METHODS:
            return self._error_response(-32601, "Method not found")

        handler = getattr(self, self.METHODS[method])
        result = handler(request.get("params", {}))

        return json.dumps({
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": result,
        })
```

**Confidence:** HIGH - Pattern defined in ADR-003, existing JSON-RPC infrastructure in bridge.rs

### Pattern 2: Maker Pattern (atomate2 Integration)

**What:** Use atomate2's Maker classes for VASP input generation rather than custom templates.

**Why:**
- Battle-tested Pydantic validation
- Community-maintained input sets (Materials Project protocols)
- Extensible for custom workflows
- Automatic POTCAR handling

**When:** Any VASP input file generation.

**Example:**
```python
from atomate2.vasp.jobs.core import RelaxMaker, StaticMaker
from atomate2.vasp.sets.core import RelaxSetGenerator

# Create maker with custom settings
relax_maker = RelaxMaker(
    input_set_generator=RelaxSetGenerator(
        user_incar_settings={"EDIFF": 1e-6, "ISMEAR": 0},
        user_kpoints_settings={"reciprocal_density": 100},
    )
)

# Generate job (returns jobflow.Job)
job = relax_maker.make(structure)

# Access inputs for preview
inputs = job.function.__self__.input_set_generator.get_input_set(structure)
print(inputs.incar)  # Preview INCAR before submission
```

**Confidence:** HIGH - Verified via [atomate2 documentation](https://materialsproject.github.io/atomate2/)

### Pattern 3: AiiDA CalcJob Wrapping

**What:** Wrap atomate2 jobs in AiiDA CalcJobs to leverage AiiDA's workflow engine and provenance.

**Why:**
- Unified job tracking database
- Full provenance graph
- Automatic restart and error handling
- HPC scheduler abstraction

**When:** Submitting any calculation to the cluster.

**Example:**
```python
from aiida import orm, engine
from aiida.engine import CalcJob, ToContext, WorkChain

class VaspCalcJob(CalcJob):
    """AiiDA CalcJob wrapping VASP execution."""

    @classmethod
    def define(cls, spec):
        super().define(spec)

        # Inputs from atomate2 InputSet
        spec.input("incar", valid_type=orm.Dict)
        spec.input("kpoints", valid_type=orm.Dict)
        spec.input("structure", valid_type=orm.StructureData)
        spec.input("potcar_mapping", valid_type=orm.Dict)

        # Outputs
        spec.output("output_parameters", valid_type=orm.Dict)
        spec.output("output_structure", valid_type=orm.StructureData, required=False)

        # Error handling
        spec.exit_code(300, "ERROR_SCF_NOT_CONVERGED")
        spec.exit_code(400, "ERROR_IONIC_NOT_CONVERGED")

    def prepare_for_submission(self, folder):
        """Write VASP input files to submission folder."""
        # Write INCAR
        with folder.open("INCAR", "w") as f:
            f.write(self._format_incar(self.inputs.incar.get_dict()))

        # Write POSCAR
        with folder.open("POSCAR", "w") as f:
            f.write(self.inputs.structure.get_poscar())

        # ... KPOINTS, POTCAR

        return self._get_calcinfo(folder)
```

**Confidence:** HIGH - Standard AiiDA pattern, verified via [AiiDA documentation](https://www.aiida.net/)

### Pattern 4: Query Adapter for Job Listing

**What:** Translate TUI job queries to AiiDA QueryBuilder queries.

**Why:**
- Single source of truth (AiiDA database)
- No SQLite sync issues
- Leverage AiiDA's ORM

**When:** Listing, filtering, or searching jobs.

**Example:**
```python
from aiida.orm import QueryBuilder, CalcJobNode, WorkChainNode

class AiiDAJobAdapter:
    """Translate TUI queries to AiiDA QueryBuilder."""

    STATUS_MAP = {
        "pending": ["created", "waiting"],
        "running": ["running"],
        "completed": ["finished"],
        "failed": ["excepted", "killed"],
    }

    def list_jobs(
        self,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Query jobs from AiiDA database."""
        qb = QueryBuilder()
        qb.append(
            (CalcJobNode, WorkChainNode),
            tag="process",
            project=["id", "label", "ctime", "mtime",
                     "attributes.process_state", "attributes.exit_status"],
        )

        if status:
            aiida_states = self.STATUS_MAP.get(status, [status])
            qb.add_filter("process", {
                "attributes.process_state": {"in": aiida_states}
            })

        qb.order_by({"process": {"ctime": "desc"}})
        qb.limit(limit)
        qb.offset(offset)

        return [self._format_job(row) for row in qb.all()]
```

**Confidence:** HIGH - Existing implementation in `tui/src/aiida/query_adapter.py`

### Pattern 5: Async Service with Auto-Start

**What:** Python service runs as a background daemon, auto-started by Rust TUI if not running.

**Why:**
- No manual service management
- Clean process separation
- Survives TUI restarts

**When:** TUI startup.

**Example (Rust auto-start):**
```rust
fn ensure_server_running() -> Result<()> {
    let socket_path = get_socket_path();

    if socket_path.exists() {
        // Try connecting
        if let Ok(_) = UnixStream::connect(&socket_path) {
            return Ok(());  // Server already running
        }
    }

    // Start server
    let server = Command::new("crystalmath-server")
        .arg("--socket")
        .arg(&socket_path)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .context("Failed to start crystalmath-server")?;

    // Wait for socket to appear
    for _ in 0..50 {
        if socket_path.exists() {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(100));
    }

    Err(anyhow!("Server failed to start within 5 seconds"))
}
```

**Confidence:** MEDIUM - Pattern defined in ADR-003, not yet implemented

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: PyO3 Embedding

**What:** Using PyO3 to embed Python directly in the Rust binary.

**Why bad:**
- Python version coupling (must compile against exact runtime version)
- GIL contention blocks UI thread
- Complex build (requires `PYO3_PYTHON` configuration)
- No standalone binary distribution
- Thread safety issues during Python interpreter shutdown

**Instead:** Use IPC boundary (JSON-RPC over Unix socket).

**Evidence:** ADR-002 and ADR-003 document this decision based on production issues.

### Anti-Pattern 2: Bypassing AiiDA for Direct SLURM

**What:** Submitting jobs directly to SLURM via SSH, bypassing AiiDA.

**Why bad:**
- No provenance tracking
- Manual status polling
- No automatic restart on failure
- Two sources of truth (SQLite + SLURM)
- Duplicated scheduler abstraction

**Instead:** All jobs through AiiDA CalcJobs/WorkChains.

### Anti-Pattern 3: Synchronous Python Calls from UI Thread

**What:** Making blocking Python calls that freeze the UI.

**Why bad:**
- 60fps TUI drops to 0fps during Python call
- User sees frozen screen
- Timeout handling is difficult

**Instead:**
- All Python calls are async via IPC
- UI shows "loading" state
- Timeouts cancel gracefully

### Anti-Pattern 4: Custom Input Validation

**What:** Writing custom VASP input validators instead of using atomate2.

**Why bad:**
- Duplicating community effort
- Missing edge cases
- No POTCAR handling
- Inconsistent with Materials Project workflows

**Instead:** Use atomate2 InputSet validators, extend only when necessary.

### Anti-Pattern 5: Dual Database Sync

**What:** Maintaining SQLite alongside AiiDA database and syncing between them.

**Why bad:**
- Eventual consistency issues
- Data loss on sync failures
- Double migration burden
- Complexity in query logic

**Instead:** AiiDA database as single source of truth. No local SQLite.

---

## Component Interaction Matrix

| From \ To | TUI | IPC | Python Service | AiiDA | atomate2 | Cluster |
|-----------|-----|-----|----------------|-------|----------|---------|
| **TUI** | - | Request | - | - | - | - |
| **IPC** | Response | - | Forward | - | - | - |
| **Python Service** | - | Response | - | Query/Submit | InputSets | - |
| **AiiDA** | - | - | Results | - | - | SSH/SLURM |
| **atomate2** | - | - | Validation | - | - | - |
| **Cluster** | - | - | - | Status | - | - |

---

## Build Order Implications

Based on component dependencies, suggested implementation order:

### Phase 1: IPC Foundation
1. **Python JSON-RPC server skeleton** — Basic dispatcher, no handlers
2. **Rust IPC client** — Connect, send, receive
3. **Integration test** — Rust client talks to Python server
4. **Auto-start logic** — TUI spawns server if missing

*Dependency:* Nothing external. Pure infrastructure.

### Phase 2: Read-Only Operations
1. **jobs.list handler** — Query AiiDA, return JSON
2. **Rust job list UI update** — Display from IPC response
3. **clusters.list handler** — Query AiiDA computers
4. **templates.list handler** — List available InputSets

*Dependency:* Requires AiiDA profile configured with existing data.

### Phase 3: Input Creation
1. **atomate2 InputSet integration** — VaspInputSet wrappers
2. **Input preview in TUI** — INCAR/KPOINTS display
3. **Structure import** — POSCAR/CIF parsing via pymatgen
4. **Materials Project search** — Existing API, adapt to IPC

*Dependency:* atomate2 installed, MP API key configured.

### Phase 4: Job Submission
1. **VaspCalcJob definition** — AiiDA CalcJob for VASP
2. **jobs.submit handler** — Create nodes, submit
3. **TUI submission flow** — Form -> preview -> submit
4. **Status polling** — AiiDA daemon updates

*Dependency:* AiiDA computer/code configured, VASP installed on cluster.

### Phase 5: Results and Cleanup
1. **Output parser integration** — pymatgen parsers
2. **Results display in TUI** — Energy, forces, etc.
3. **Python TUI removal** — Delete Textual code
4. **Migration documentation** — User upgrade path

*Dependency:* Completed calculations to parse.

---

## Scalability Considerations

| Concern | Local Development | Research Group (10 users) | HPC Center (100+ users) |
|---------|-------------------|---------------------------|------------------------|
| **Database** | SQLite (AiiDA default) | PostgreSQL (single node) | PostgreSQL cluster |
| **Message Broker** | None (direct scheduler) | RabbitMQ (single node) | RabbitMQ cluster |
| **Python Service** | Single process | Single process, shared socket | Multiple instances, load balancer |
| **Job Throughput** | ~10/day | ~100/day | ~10,000/day |
| **UI Instances** | 1 | 10 | N/A (web interface needed) |

**Note:** For HPC center scale, a web interface (AiiDA Lab) is more appropriate than TUI.

---

## Sources

- [AiiDA Official Documentation](https://www.aiida.net/) — HIGH confidence
- [atomate2 DeepWiki](https://deepwiki.com/materialsproject/atomate2) — MEDIUM confidence
- [Existing ADR-003: IPC Boundary Design](/Users/briansquires/CRYSTAL23/crystalmath/docs/architecture/adr-003-ipc-boundary-design.md) — HIGH confidence
- [Existing AiiDA Integration Design](/Users/briansquires/CRYSTAL23/crystalmath/docs/architecture/aiida-integration.md) — HIGH confidence
- [Existing atomate2 Integration Design](/Users/briansquires/CRYSTAL23/crystalmath/docs/architecture/ATOMATE2-INTEGRATION.md) — HIGH confidence
- [pyo3-async-runtimes](https://github.com/PyO3/pyo3-async-runtimes) — MEDIUM confidence (not recommended for this project)
- [Atomate2: modular workflows for materials science (RSC 2025)](https://pubs.rsc.org/en/content/articlehtml/2025/dd/d5dd00019j) — MEDIUM confidence

---

## Open Questions

1. **Multi-user socket permissions** — How to handle when multiple users share a machine?
   - Potential: Per-user socket in `$XDG_RUNTIME_DIR`
   - Needs: Testing on shared HPC login nodes

2. **AiiDA profile selection** — How does user switch between AiiDA profiles from TUI?
   - Potential: Server restart with different profile
   - Potential: Profile parameter in every request

3. **Long-running job monitoring** — How to efficiently poll job status?
   - Potential: Server pushes updates (requires bidirectional IPC)
   - Potential: TUI polls periodically (simpler)

4. **POTCAR handling** — How to handle VASP POTCAR files?
   - atomate2 has `VASP_PP_PATH` configuration
   - Needs: Validation in Python service

5. **Error recovery** — How to handle server crash during job submission?
   - AiiDA's transaction model should protect data
   - Needs: Testing and documentation
