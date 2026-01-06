# ADR-003: IPC Boundary Design for Rust TUI

**Status:** Proposed
**Date:** 2026-01-06
**Deciders:** Project maintainers
**Depends on:** ADR-001, ADR-002

## Context

Per ADR-002, the Rust TUI is under a feature freeze until PyO3 coupling is replaced with a stable IPC boundary. The current `bridge.rs` (1800+ lines) embeds Python via PyO3, which:

1. **Couples Python versions** - PyO3 must be compiled against the exact Python version used at runtime
2. **Blocks interpreter shutdown** - Worker thread can hang during Python GC traversal
3. **Adds build complexity** - Requires `scripts/build-tui.sh` to configure `PYO3_PYTHON`
4. **Limits deployment** - Cannot distribute a standalone Rust binary

This ADR defines an IPC boundary that decouples Rust from Python while preserving all existing functionality.

## Decision

### 1. Transport: Unix Domain Socket with JSON-RPC 2.0

**Choice:** Unix domain socket for local communication, with JSON-RPC 2.0 as the protocol.

**Rationale:**
- Unix sockets are faster than TCP for local IPC
- JSON-RPC 2.0 is well-specified, has existing libraries in both Rust and Python
- Already using JSON serialization in current bridge (serde + Python json)
- Matches the existing async request/response pattern in `BridgeRequest`/`BridgeResponse`

**Socket path:** `$XDG_RUNTIME_DIR/crystalmath.sock` (Linux) or `~/Library/Caches/crystalmath.sock` (macOS)

### 2. Python Service: `crystalmath-server`

A standalone Python service that:
- Listens on the Unix domain socket
- Handles JSON-RPC 2.0 requests
- Uses the existing `crystalmath.api` module (CrystalController)
- Manages its own lifecycle (start/stop/status)

**Launch options:**
1. **Auto-start**: Rust TUI spawns the service if not running
2. **Manual**: User starts `crystalmath-server` before launching Rust TUI
3. **Systemd/launchd**: Service manager integration (optional)

### 3. Message Schema (JSON-RPC 2.0)

All methods map directly from existing `BridgeRequest` variants:

```json
// Request
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "jobs.list",
  "params": {}
}

// Response (success)
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "status": "ok",
    "data": [...]
  }
}

// Response (error)
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32000,
    "message": "Database connection failed"
  }
}
```

### 4. Method Namespace

Methods organized by domain to match `BridgeRequest` structure:

| Namespace | Methods | Current BridgeRequest |
|-----------|---------|----------------------|
| `jobs` | `list`, `get`, `submit`, `cancel`, `log` | FetchJobs, FetchJobDetails, SubmitJob, CancelJob, FetchJobLog |
| `materials` | `search`, `generate_d12` | SearchMaterials, GenerateD12 |
| `slurm` | `queue`, `cancel`, `adopt`, `sync` | FetchSlurmQueue, CancelSlurmJob, AdoptSlurmJob, SyncRemoteJobs |
| `templates` | `list`, `render` | FetchTemplates, RenderTemplate |
| `clusters` | `list`, `get`, `create`, `update`, `delete`, `test` | FetchClusters, FetchCluster, Create/Update/DeleteCluster, TestClusterConnection |
| `workflows` | `available`, `create_convergence`, `create_bands`, `create_phonon`, `create_eos`, `launch_aiida` | Check/Create workflow variants |

### 5. Rust Client Design

Replace `BridgeHandle` with `IpcClient`:

```rust
pub struct IpcClient {
    socket_path: PathBuf,
    connection: Option<UnixStream>,
    request_id: AtomicUsize,
}

impl IpcClient {
    pub fn connect() -> Result<Self>;
    pub fn send_request(&self, method: &str, params: Value) -> Result<Value>;
    pub async fn send_request_async(&self, method: &str, params: Value) -> Result<Value>;
}

// Implement BridgeService trait for IpcClient
impl BridgeService for IpcClient {
    fn request_fetch_jobs(&self, request_id: usize) -> Result<()> {
        self.send_request("jobs.list", json!({}))
    }
    // ... other methods
}
```

### 6. Migration Strategy

**Phase 1: Add IPC alongside PyO3 (non-breaking)**
- Implement `crystalmath-server` in Python
- Implement `IpcClient` in Rust behind feature flag
- Test parity with existing PyO3 bridge

**Phase 2: Default to IPC**
- Make IPC the default transport
- Keep PyO3 as fallback (for development)
- Update documentation

**Phase 3: Remove PyO3 (ADR-016)**
- Remove PyO3 dependency from Cargo.toml
- Remove `bridge.rs` PyO3 code
- Simplify build (no more `PYO3_PYTHON`)

### 7. Service Lifecycle

```
crystalmath-server start     # Start daemon
crystalmath-server stop      # Stop daemon
crystalmath-server status    # Check if running
crystalmath-server --foreground  # Run in foreground (debugging)
```

**Auto-start logic in Rust TUI:**
```rust
fn ensure_server_running() -> Result<()> {
    if !server_is_running() {
        spawn_server_process()?;
        wait_for_socket(Duration::from_secs(5))?;
    }
    Ok(())
}
```

### 8. Error Handling

| JSON-RPC Error Code | Meaning |
|---------------------|---------|
| -32700 | Parse error (invalid JSON) |
| -32600 | Invalid request |
| -32601 | Method not found |
| -32602 | Invalid params |
| -32603 | Internal error |
| -32000 | Server error (custom) |
| -32001 | Database error |
| -32002 | SSH connection error |
| -32003 | SLURM error |

## Consequences

### Positive
- **Decoupled builds**: Rust TUI can be distributed as standalone binary
- **Version independence**: Python version changes don't break Rust TUI
- **Simpler architecture**: No PyO3 complexity, no GIL concerns
- **Testable**: Can mock IPC server for Rust tests

### Negative / Tradeoffs
- **Additional process**: Users must have Python service running
- **Latency**: IPC adds small overhead vs in-process calls
- **Complexity**: Two processes to debug instead of one

### Mitigations
- Auto-start minimizes user friction
- Unix sockets keep latency sub-millisecond
- Structured logging in both processes aids debugging

## Implementation Checklist

- [ ] Create `python/crystalmath/server/__init__.py` with JSON-RPC handler
- [ ] Add `crystalmath-server` CLI entry point
- [ ] Implement `IpcClient` in `src/ipc.rs`
- [ ] Add `--ipc` feature flag to Cargo.toml
- [ ] Write integration tests (Rust client + Python server)
- [ ] Update CLAUDE.md with IPC architecture
- [ ] Benchmark IPC vs PyO3 latency

## Related Issues

- crystalmath-as6l.11: Define IPC boundary for Rust TUI (this ADR)
- crystalmath-as6l.16: Remove legacy Rust LSP implementation
- crystalmath-as6l.18: Freeze Rust TUI feature work until IPC is defined
