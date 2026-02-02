---
phase: 01-ipc-foundation
plan: 02
subsystem: ipc
tags: [rust, tokio, unix-socket, json-rpc, async]

# Dependency graph
requires:
  - phase: 01-ipc-foundation/01-01
    provides: JSON-RPC types exist in bridge.rs (JsonRpcRequest, JsonRpcResponse)
provides:
  - IpcClient struct with connect() and call() methods
  - Content-Length framing codec (read_message, write_message)
  - IpcError enum for actionable error messages
  - default_socket_path() for cross-platform socket resolution
affects: [01-ipc-foundation/01-03, 01-ipc-foundation/01-04, bridge-migration]

# Tech tracking
tech-stack:
  added: []  # No new dependencies - reuses existing tokio, serde_json, thiserror
  patterns: [content-length-framing, async-ipc, exponential-backoff-retry]

key-files:
  created:
    - src/ipc.rs
    - src/ipc/client.rs
    - src/ipc/framing.rs
  modified:
    - src/main.rs

key-decisions:
  - "Use dirs crate for cross-platform socket path instead of libc::getuid()"
  - "30-second default timeout matching ADR-003 specification"
  - "Reuse JsonRpcRequest/Response from bridge.rs rather than duplicate"

patterns-established:
  - "Content-Length framing: HTTP-style headers with case-insensitive parsing, CRLF/LF support"
  - "Socket path resolution: XDG_RUNTIME_DIR -> dirs::cache_dir -> /tmp fallback"
  - "Async error handling: IpcError enum with From impls for common error sources"

# Metrics
duration: 13min
completed: 2026-02-02
---

# Phase 1 Plan 2: Rust IPC Client Module Summary

**Async IPC client with Content-Length framing, 30s timeout, and IpcError enum for Unix socket communication**

## Performance

- **Duration:** 13 min
- **Started:** 2026-02-02T21:45:23Z
- **Completed:** 2026-02-02T21:58:41Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- IpcClient struct with connect(), connect_with_retry(), and call() methods
- Content-Length framing codec matching LSP protocol (100MB cap, case-insensitive headers)
- IpcError enum with Timeout, ConnectionFailed, Protocol, ServerError variants
- 10 unit tests passing for framing and error handling

## Task Commits

Each task was committed atomically:

1. **Task 1: Create IPC client module with framing** - `6d4e63a` (feat)
2. **Task 2: Add timeout and error handling** - `4e6a01f` (feat)

## Files Created/Modified
- `src/ipc.rs` - Module root with public exports (IpcClient, IpcError, read/write_message)
- `src/ipc/client.rs` - IpcClient struct with async connect/call methods, 30s timeout
- `src/ipc/framing.rs` - Content-Length codec with tests for CRLF/LF, case-insensitive headers
- `src/main.rs` - Added `mod ipc;` declaration

## Decisions Made
- **dirs crate instead of libc**: Used existing `dirs` crate for `cache_dir()` instead of adding `libc` dependency for `getuid()`. More portable and already in Cargo.toml.
- **Reuse bridge.rs types**: JsonRpcRequest and JsonRpcResponse from bridge.rs are reused via `crate::bridge::*` rather than duplicating in ipc module.
- **Socket path fallback chain**: XDG_RUNTIME_DIR (Linux) -> dirs::cache_dir (macOS ~/Library/Caches) -> /tmp. This matches ADR-003 but avoids UID in path for simplicity.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Changed socket path resolution to avoid libc dependency**
- **Found during:** Task 1 (Module creation)
- **Issue:** Plan suggested `libc::getuid()` for UID-specific socket path, but libc not in Cargo.toml
- **Fix:** Used `dirs::cache_dir()` which already provides user-specific path on macOS
- **Files modified:** src/ipc/client.rs
- **Verification:** `cargo check` passes, default_socket_path test passes
- **Committed in:** 6d4e63a (Task 1 commit)

**2. [Rule 1 - Bug] Fixed socket direction in framing tests**
- **Found during:** Task 2 (Tests were hanging)
- **Issue:** Tests wrote to wrong socket half - `client_write` and `client_read` were same socket split, not connected pair
- **Fix:** Corrected socket pair usage: server_read reads from client_write across the pair, added timeouts
- **Files modified:** src/ipc/framing.rs
- **Verification:** All 10 IPC tests pass in < 1 second
- **Committed in:** 4e6a01f (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Both fixes necessary for compilation and test correctness. No scope creep.

## Issues Encountered
- Tests initially hung indefinitely because async `read_line` waits for newlines that never arrive on improperly connected sockets. Fixed by correcting socket pair direction and adding test timeouts.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- IpcClient ready for integration with auto-start logic (01-03)
- Framing codec tested and ready for Python server interop
- IpcError types ready for UI error display

---
*Phase: 01-ipc-foundation*
*Completed: 2026-02-02*
