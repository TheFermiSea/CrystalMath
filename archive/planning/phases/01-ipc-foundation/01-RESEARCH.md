# Phase 1: IPC Foundation - Research

**Researched:** 2026-02-02
**Domain:** Rust-Python IPC via JSON-RPC 2.0 over Unix Domain Sockets
**Confidence:** HIGH

## Summary

This phase replaces the PyO3 embedded Python bridge with a JSON-RPC 2.0 server communicating over Unix domain sockets. The codebase already has significant infrastructure in place:

1. **JSON-RPC types exist in Rust** (`bridge.rs` lines 26-102): `JsonRpcRequest`, `JsonRpcResponse`, `JsonRpcError`
2. **Python dispatch exists** (`api.py` lines 270-383): The `dispatch()` method already implements JSON-RPC 2.0
3. **Framing pattern exists** (`lsp.rs`): Content-Length header parsing for JSON-RPC over stdio

The implementation builds on these existing patterns rather than introducing new libraries.

**Primary recommendation:** Use the existing JSON-RPC types and LSP-style Content-Length framing. Implement the server with Python's native `asyncio.start_unix_server()` (no external dependencies). Implement the client with tokio's `UnixStream` (already available via tokio's `net` feature).

---

## Standard Stack

### Rust Side (Client)

| Library | Version | Purpose | Why Standard | Confidence |
|---------|---------|---------|--------------|------------|
| tokio | 1.42+ | Async runtime, `UnixStream` | Already in Cargo.toml, provides `tokio::net::UnixStream` | HIGH |
| serde_json | 1.0 | JSON serialization | Already in Cargo.toml, used throughout codebase | HIGH |
| anyhow | 1.0 | Error handling | Already in Cargo.toml | HIGH |

**No new Rust dependencies required.**

### Python Side (Server)

| Library | Version | Purpose | Why Standard | Confidence |
|---------|---------|---------|--------------|------------|
| asyncio | stdlib | Async server via `start_unix_server()` | Zero dependencies, Python 3.10+ built-in | HIGH |
| json | stdlib | JSON parsing | Zero dependencies, Python built-in | HIGH |

**No new Python dependencies required.**

### Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Rust JSON-RPC | Manual with existing types | jsonrpsee | jsonrpsee lacks native Unix socket support, adds complexity |
| Rust JSON-RPC | Manual with existing types | jsonrpc crate | Deprecated, maintainers recommend jsonrpsee |
| Python JSON-RPC | Manual with asyncio | ajsonrpc | External dependency, last release 2021 |
| Python JSON-RPC | Manual with asyncio | aiojsonrpc2 | External dependency, adds complexity |
| Python JSON-RPC | Manual with asyncio | aiohttp-json-rpc | HTTP-focused, overkill for Unix sockets |

**Rationale:** The codebase already has JSON-RPC 2.0 types and a dispatch method. Adding external libraries would introduce dependencies without benefit.

---

## Architecture Patterns

### Recommended Project Structure

```
python/crystalmath/
  server/
    __init__.py        # Server entry point, CLI
    dispatcher.py      # JSON-RPC request routing (existing dispatch logic)
    handlers/          # Method handlers by namespace
      __init__.py
      jobs.py          # jobs.* methods
      clusters.py      # clusters.* methods
      ...

src/
  ipc.rs              # New IPC client module
  ipc/
    client.rs         # IpcClient struct
    framing.rs        # Content-Length codec
    types.rs          # Shared types (or reuse from bridge.rs)
```

### Pattern 1: Content-Length Framing

**What:** Use HTTP-style `Content-Length` header for message framing, same as LSP protocol.

**When to use:** All JSON-RPC messages over Unix socket.

**Why:**
- Already implemented in `lsp.rs` reader thread (lines 263-352)
- Simple: header + body, no length prefixes
- Human-readable for debugging
- Standard in language server ecosystem

**Example (wire format):**
```
Content-Length: 47\r\n
\r\n
{"jsonrpc":"2.0","method":"system.ping","id":1}
```

**Rust reading (adapted from lsp.rs):**
```rust
// Source: Adapted from src/lsp.rs lines 263-352
async fn read_message(stream: &mut BufReader<UnixStream>) -> Result<String> {
    // Read headers until blank line
    let mut content_length: Option<usize> = None;
    loop {
        let mut line = String::new();
        stream.read_line(&mut line).await?;
        let trimmed = line.trim();
        if trimmed.is_empty() {
            break;
        }
        if let Some(colon_pos) = trimmed.find(':') {
            let key = trimmed[..colon_pos].trim();
            let value = trimmed[colon_pos + 1..].trim();
            if key.eq_ignore_ascii_case("Content-Length") {
                content_length = Some(value.parse()?);
            }
        }
    }

    let size = content_length.ok_or_else(|| anyhow!("Missing Content-Length"))?;
    let mut body = vec![0u8; size];
    stream.read_exact(&mut body).await?;
    String::from_utf8(body).map_err(Into::into)
}
```

**Confidence:** HIGH - Pattern verified in existing `lsp.rs` implementation

### Pattern 2: Async Request/Response with Timeout

**What:** Send request, wait for response with 30-second timeout.

**When to use:** All RPC calls from Rust TUI.

**Why:**
- TUI must not block indefinitely
- Python operations can be slow (network, database)
- Graceful degradation on timeout

**Example:**
```rust
// Source: Pattern from ADR-003, timeout from ROADMAP.md
use tokio::time::timeout;

impl IpcClient {
    pub async fn call(
        &mut self,
        method: &str,
        params: serde_json::Value,
    ) -> Result<serde_json::Value> {
        let request = JsonRpcRequest::new(
            method,
            params,
            self.next_id(),
        );

        let result = timeout(
            Duration::from_secs(30),
            self.send_receive(&request),
        ).await;

        match result {
            Ok(Ok(response)) => response.into_result(),
            Ok(Err(e)) => Err(e),
            Err(_) => Err(anyhow!("Request timed out after 30s")),
        }
    }
}
```

**Confidence:** HIGH - Standard async pattern with timeout

### Pattern 3: Auto-Start Server

**What:** Rust TUI spawns Python server if not running.

**When to use:** TUI startup, connection failure recovery.

**Why:**
- Zero-config user experience
- No manual service management
- Defined in ADR-003

**Example:**
```rust
// Source: ADR-003 section 5
fn ensure_server_running(socket_path: &Path) -> Result<()> {
    // Try connecting first
    match std::os::unix::net::UnixStream::connect(socket_path) {
        Ok(_) => return Ok(()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(e) if e.kind() == std::io::ErrorKind::ConnectionRefused => {}
        Err(e) => return Err(e.into()),
    }

    // Server not running - spawn it
    tracing::info!("Starting crystalmath-server...");
    let _child = Command::new("crystalmath-server")
        .arg("--socket")
        .arg(socket_path)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .context("Failed to start crystalmath-server")?;

    // Wait for socket to appear (max 5 seconds)
    for _ in 0..50 {
        if socket_path.exists() {
            // Give server a moment to start accepting
            std::thread::sleep(Duration::from_millis(100));
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(100));
    }

    Err(anyhow!("Server failed to start within 5 seconds"))
}
```

**Confidence:** HIGH - Pattern defined in ADR-003

### Pattern 4: Health Check Endpoint

**What:** Simple `system.ping` method to verify server responsiveness.

**When to use:** Connection establishment, periodic health checks.

**Example:**
```python
# Python server handler
def handle_system_ping(self, params: dict) -> dict:
    return {"pong": True, "timestamp": datetime.utcnow().isoformat()}
```

```rust
// Rust client usage
let response = client.call("system.ping", json!({})).await?;
assert!(response["pong"].as_bool().unwrap());
```

**Confidence:** HIGH - Standard health check pattern

### Anti-Patterns to Avoid

- **Multi-threaded Python server:** Use single-threaded asyncio event loop. GIL makes threading ineffective for CPU-bound work anyway.
- **Blocking I/O in async handlers:** All database/network calls must be async or run in executor.
- **Unbounded message sizes:** Cap Content-Length at 100MB (matching `lsp.rs` line 320).
- **Silent connection failures:** Always surface errors to TUI with clear messages.
- **Spawning server without cleanup:** Track child process, implement graceful shutdown on TUI exit.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON-RPC 2.0 types | New request/response structs | Existing `bridge.rs` types | Already tested, match Python side |
| Content-Length framing | Custom protocol | LSP-style framing from `lsp.rs` | Already debugged, standard format |
| Async Unix sockets | std::os::unix::net | tokio::net::UnixStream | Async integration with TUI event loop |
| Signal handling (Python) | Manual SIGTERM/SIGINT | asyncio event loop integration | Proper cleanup, no orphaned sockets |

**Key insight:** The codebase has 90% of the building blocks. The work is integration, not invention.

---

## Common Pitfalls

### Pitfall 1: Socket Permission Errors

**What goes wrong:** Server creates socket that TUI cannot connect to (different user, bad umask).

**Why it happens:** Unix sockets inherit filesystem permissions. Default umask may restrict access.

**How to avoid:**
1. Create socket in `$XDG_RUNTIME_DIR` (per-user, correct permissions)
2. Set explicit permissions after creation: `os.chmod(socket_path, 0o600)`
3. Fall back to `/tmp/crystalmath-{uid}.sock` if XDG unavailable

**Warning signs:** "Permission denied" on connect, socket exists but connection refused.

### Pitfall 2: Stale Socket File

**What goes wrong:** Old socket file exists from crashed server, new server can't bind.

**Why it happens:** Server crashed without cleanup, TUI killed server without proper shutdown.

**How to avoid:**
1. Attempt to connect before binding - if connection succeeds, server is running
2. If connection fails with `ConnectionRefused`, delete stale socket and retry
3. Use PID file alongside socket for additional verification

**Warning signs:** "Address already in use" error on server start.

### Pitfall 3: Partial Message Reads

**What goes wrong:** Client reads incomplete JSON, parsing fails.

**Why it happens:** `read()` returns partial data, not waiting for full message.

**How to avoid:**
1. Always use `read_exact()` after parsing Content-Length
2. Implement proper framing with `BufReader`
3. Never assume single `read()` returns complete message

**Warning signs:** JSON parse errors, "unexpected end of input", intermittent failures.

### Pitfall 4: Blocking the asyncio Event Loop

**What goes wrong:** Server becomes unresponsive, TUI times out.

**Why it happens:** Synchronous code (SQLite, file I/O) blocks the event loop.

**How to avoid:**
1. Use `aiosqlite` for database access (already in TUI dependencies)
2. Use `asyncio.to_thread()` for CPU-bound operations
3. Use `asyncio.create_task()` for fire-and-forget operations

**Warning signs:** High latency on simple requests, all requests slow when one is slow.

### Pitfall 5: Server Orphan on TUI Crash

**What goes wrong:** Python server continues running after TUI exits unexpectedly.

**Why it happens:** TUI crash doesn't trigger graceful shutdown sequence.

**How to avoid:**
1. Server implements inactivity timeout (5 minutes of no requests)
2. TUI sends explicit shutdown RPC on clean exit
3. Server detects client disconnect and starts inactivity timer

**Warning signs:** Multiple server processes, socket conflict on restart.

---

## Code Examples

### Example 1: Python Server Main Loop

```python
# Source: Python asyncio documentation + ADR-003 pattern
import asyncio
import json
import os
from pathlib import Path

class JsonRpcServer:
    def __init__(self, socket_path: Path, controller):
        self.socket_path = socket_path
        self.controller = controller  # Existing CrystalController

    async def handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        """Handle a single client connection."""
        try:
            while True:
                # Read Content-Length header
                content_length = await self._read_content_length(reader)
                if content_length is None:
                    break  # Client disconnected

                # Read message body
                body = await reader.readexactly(content_length)
                request_json = body.decode('utf-8')

                # Dispatch via existing CrystalController.dispatch()
                response_json = self.controller.dispatch(request_json)

                # Write response with Content-Length
                response_bytes = response_json.encode('utf-8')
                header = f"Content-Length: {len(response_bytes)}\r\n\r\n"
                writer.write(header.encode('utf-8'))
                writer.write(response_bytes)
                await writer.drain()

        except asyncio.IncompleteReadError:
            pass  # Client disconnected mid-message
        except Exception as e:
            # Log error but don't crash server
            import traceback
            traceback.print_exc()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _read_content_length(
        self,
        reader: asyncio.StreamReader,
    ) -> int | None:
        """Read headers and return Content-Length, or None on disconnect."""
        content_length = None
        while True:
            line = await reader.readline()
            if not line:
                return None  # EOF
            decoded = line.decode('utf-8').strip()
            if not decoded:
                break  # End of headers
            if decoded.lower().startswith('content-length:'):
                content_length = int(decoded.split(':', 1)[1].strip())
        return content_length

    async def serve_forever(self):
        """Start the server and run until stopped."""
        # Clean up stale socket
        if self.socket_path.exists():
            self.socket_path.unlink()

        server = await asyncio.start_unix_server(
            self.handle_client,
            path=str(self.socket_path),
        )

        # Set socket permissions
        os.chmod(self.socket_path, 0o600)

        async with server:
            await server.serve_forever()
```

**Confidence:** HIGH - Standard asyncio pattern

### Example 2: Rust IPC Client

```rust
// Source: Adapted from existing bridge.rs and lsp.rs patterns
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::net::UnixStream;
use std::sync::atomic::{AtomicU64, Ordering};

pub struct IpcClient {
    reader: BufReader<tokio::io::ReadHalf<UnixStream>>,
    writer: tokio::io::WriteHalf<UnixStream>,
    request_id: AtomicU64,
}

impl IpcClient {
    pub async fn connect(socket_path: &std::path::Path) -> Result<Self> {
        let stream = UnixStream::connect(socket_path).await?;
        let (reader, writer) = tokio::io::split(stream);
        Ok(Self {
            reader: BufReader::new(reader),
            writer,
            request_id: AtomicU64::new(1),
        })
    }

    pub async fn call(
        &mut self,
        method: &str,
        params: serde_json::Value,
    ) -> Result<serde_json::Value> {
        let id = self.request_id.fetch_add(1, Ordering::SeqCst);
        let request = JsonRpcRequest::new(method, params, id);

        // Send request
        let request_json = serde_json::to_string(&request)?;
        let header = format!("Content-Length: {}\r\n\r\n", request_json.len());
        self.writer.write_all(header.as_bytes()).await?;
        self.writer.write_all(request_json.as_bytes()).await?;
        self.writer.flush().await?;

        // Read response
        let response_json = self.read_message().await?;
        let response: JsonRpcResponse = serde_json::from_str(&response_json)?;
        response.into_result()
    }

    async fn read_message(&mut self) -> Result<String> {
        // Read headers
        let mut content_length: Option<usize> = None;
        loop {
            let mut line = String::new();
            self.reader.read_line(&mut line).await?;
            let trimmed = line.trim();
            if trimmed.is_empty() {
                break;
            }
            if let Some(colon) = trimmed.find(':') {
                let key = trimmed[..colon].trim();
                let value = trimmed[colon + 1..].trim();
                if key.eq_ignore_ascii_case("Content-Length") {
                    content_length = Some(value.parse()?);
                }
            }
        }

        let size = content_length.ok_or_else(|| anyhow!("Missing Content-Length"))?;
        let mut body = vec![0u8; size];
        self.reader.read_exact(&mut body).await?;
        String::from_utf8(body).map_err(Into::into)
    }
}
```

**Confidence:** HIGH - Combines existing patterns from `bridge.rs` and `lsp.rs`

### Example 3: BridgeService Trait Implementation

```rust
// Source: Existing BridgeService trait in bridge.rs lines 114-221
impl BridgeService for IpcClient {
    fn request_fetch_jobs(&self, request_id: usize) -> Result<()> {
        // Non-blocking: spawn task and return immediately
        let client = self.clone();  // IpcClient needs Clone impl
        tokio::spawn(async move {
            let result = client.call("fetch_jobs", json!({})).await;
            // Send result to response channel
        });
        Ok(())
    }

    fn poll_response(&self) -> Option<BridgeResponse> {
        // Check response channel
        self.response_rx.try_recv().ok()
    }

    // ... other methods follow same pattern
}
```

**Confidence:** MEDIUM - Architecture clear, implementation details need validation

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| PyO3 embedded Python | IPC via Unix socket | ADR-003 (2026-01) | Decoupled builds, standalone binary |
| Custom JSON serialization | JSON-RPC 2.0 standard | Codebase evolution | Standard protocol, better tooling |
| Synchronous bridge calls | Async request/response | Existing pattern | Non-blocking UI |

**Deprecated/outdated:**
- **jsonrpc crate (Parity):** Unmaintained, recommends jsonrpsee. Don't use.
- **rust-cpython:** Unmaintained, PyO3 is the successor. Don't use.
- **Newline-delimited JSON:** Less robust than Content-Length framing. Don't use.

---

## Open Questions

1. **Connection pooling?**
   - What we know: Single connection per TUI session should suffice
   - What's unclear: Behavior under heavy load
   - Recommendation: Start with single connection, add pooling if needed later

2. **Bidirectional notifications?**
   - What we know: TUI polls for updates currently
   - What's unclear: Would server-push improve UX for job status updates?
   - Recommendation: Defer. Polling works, bidirectional adds complexity.

3. **Server inactivity timeout value?**
   - What we know: ROADMAP suggests 5 minutes
   - What's unclear: User workflows - do they leave TUI open for hours?
   - Recommendation: Make configurable, default 5 minutes, disable with `--no-timeout`

---

## Sources

### Primary (HIGH confidence)

- [tokio UnixStream documentation](https://docs.rs/tokio/latest/tokio/net/struct.UnixStream.html) - Verified 2026-02-02
- [Python asyncio.start_unix_server documentation](https://docs.python.org/3/library/asyncio-stream.html#asyncio.start_unix_server) - Verified 2026-02-02
- Existing `src/lsp.rs` lines 263-352 - Content-Length framing implementation
- Existing `src/bridge.rs` lines 26-102 - JSON-RPC 2.0 types
- Existing `python/crystalmath/api.py` lines 270-383 - `dispatch()` method
- [ADR-003: IPC Boundary Design](docs/architecture/adr-003-ipc-boundary-design.md) - Architecture decision

### Secondary (MEDIUM confidence)

- [Tokio framing tutorial](https://tokio.rs/tokio/tutorial/framing) - Buffer patterns
- [LSP Specification](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/) - Content-Length protocol
- [Python graceful shutdown patterns](https://roguelynn.com/words/asyncio-graceful-shutdowns/) - asyncio shutdown

### Tertiary (LOW confidence)

- [jsonrpsee documentation](https://docs.rs/jsonrpsee) - Considered but not recommended (no Unix socket support)
- [ajsonrpc GitHub](https://github.com/pavlov99/ajsonrpc) - Considered but not recommended (external dependency)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Using stdlib + existing dependencies
- Architecture: HIGH - Reusing existing patterns (lsp.rs, bridge.rs)
- Pitfalls: MEDIUM - Based on general Unix socket experience
- Code examples: HIGH - Adapted from existing codebase

**Research date:** 2026-02-02
**Valid until:** 90 days (stable patterns, stdlib-based)

---

## Roadmap Implications

Based on research, the phase structure from ROADMAP.md is appropriate:

1. **Python JSON-RPC server skeleton** - Low risk, reuse existing `dispatch()`
2. **Rust IPC client module** - Low risk, adapt from `lsp.rs` patterns
3. **Auto-start logic** - Medium risk, process management edge cases
4. **Health check endpoint** - Low risk, simple implementation
5. **Integration tests** - Medium effort, need both Rust and Python test harness

**Estimated complexity:** 2-3 days of focused work, assuming no blockers.

**No deeper research flags needed** - the patterns are well-established and the codebase has working examples.
