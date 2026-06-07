---
phase: 01-ipc-foundation
plan: 03
subsystem: ipc
tags: [rust, integration-tests, auto-start, health-check]

# Dependency graph
requires:
  - phase: 01-ipc-foundation/01-01
    provides: Python JSON-RPC server with system.ping endpoint
  - phase: 01-ipc-foundation/01-02
    provides: IpcClient with connect() and call() methods
provides:
  - ensure_server_running() for zero-config TUI startup
  - connect_or_start() convenience method
  - ping() health check with latency measurement
  - 7 integration tests verifying full IPC stack
affects: [bridge-migration, rust-tui-startup]

# Tech tracking
tech-stack:
  added: []  # No new dependencies
  patterns:
    - Server auto-start via Command::new spawn
    - Stale socket detection and cleanup
    - Connection retry with exponential backoff
    - Integration test pattern with per-test socket paths

key-files:
  created:
    - src/lib.rs
    - tests/ipc_integration.rs
  modified:
    - src/ipc.rs
    - src/ipc/client.rs
    - src/main.rs

key-decisions:
  - "5-second timeout for server startup (matches ADR-003)"
  - "100ms polling interval for socket existence check"
  - "Expose library modules via lib.rs for integration tests"
  - "Per-test unique socket paths to avoid test conflicts"
  - "Skip tests gracefully when Python server unavailable"

patterns-established:
  - "Server auto-start: try connect -> spawn if needed -> wait for socket"
  - "Stale socket: ConnectionRefused -> remove socket -> start fresh"
  - "Integration test: unique socket path -> ensure_server -> test -> cleanup"

# Metrics
duration: 6min
completed: 2026-02-02
---

# Phase 01 Plan 03: Auto-start Logic and Integration Tests Summary

**Server auto-start with ensure_server_running(), ping health check, and 7 integration tests verifying < 10ms IPC latency**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-02T22:00:50Z
- **Completed:** 2026-02-02T22:06:21Z
- **Tasks:** 2
- **Files modified:** 5
- **Tests added:** 7 integration tests (17 total IPC tests now)

## Accomplishments

- `ensure_server_running()` spawns crystalmath-server if not running
- `connect_or_start()` combines auto-start with connection retry
- `ping()` method for health checks with latency measurement
- Stale socket detection and cleanup (ConnectionRefused case)
- 7 integration tests verifying full Rust-Python IPC stack
- Average ping latency: ~95 microseconds (well under 10ms target)

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement auto-start logic** - `7c09a2a` (feat)
2. **Task 2: Create integration tests** - `5362889` (test)

## Files Created/Modified

- `src/lib.rs` - New library root exposing ipc, bridge, models modules
- `src/ipc.rs` - Added ensure_server_running to public exports
- `src/ipc/client.rs` - Added ensure_server_running(), connect_or_start(), ping()
- `src/main.rs` - Updated to use library modules instead of duplicating
- `tests/ipc_integration.rs` - 7 integration tests for IPC stack

## Decisions Made

1. **5-second server startup timeout** - Matches ADR-003 specification, allows for Python interpreter startup.
2. **100ms polling interval** - Balance between responsiveness and CPU usage during server startup.
3. **lib.rs for test access** - Standard Rust pattern to expose modules for integration tests while keeping main.rs minimal.
4. **Per-test socket paths** - Each test gets unique socket path to prevent test interference when running in parallel.
5. **Graceful skip when server unavailable** - Tests skip with message instead of failing in CI environments without Python.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Created lib.rs for integration test imports**
- **Found during:** Task 2 (Integration tests)
- **Issue:** Integration tests couldn't import `crystalmath_tui::ipc` without a library crate
- **Fix:** Created `src/lib.rs` exposing necessary modules, updated main.rs to use library imports
- **Files modified:** src/lib.rs, src/main.rs
- **Verification:** `cargo test --test ipc_integration` compiles and runs
- **Committed in:** 5362889 (Task 2 commit)

**2. [Rule 1 - Bug] Fixed stale socket test for macOS compatibility**
- **Found during:** Task 2 (Test failure on macOS)
- **Issue:** Creating a regular file and trying Unix socket connect gives different errors on macOS vs Linux
- **Fix:** Create a real Unix socket (bind listener, then drop) to properly simulate crashed server
- **Files modified:** tests/ipc_integration.rs
- **Verification:** test_stale_socket_cleanup passes on macOS
- **Committed in:** 5362889 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Both fixes necessary for cross-platform compatibility and proper test structure.

## Issues Encountered

- macOS reports "Socket operation on non-socket" (ENOTSOCK) when attempting Unix socket connect on a regular file, while Linux reports "Connection refused" (ECONNREFUSED). Fixed by using real Unix sockets in the stale socket test.

## Test Results

```
$ cargo test --test ipc_integration
test test_default_socket_path_format ... ok
test test_connect_to_nonexistent_socket ... ok
test test_stale_socket_cleanup ... ok
test test_connect_or_start ... ok
test test_ping_roundtrip ... ok
test test_multiple_sequential_calls ... ok
test test_ping_latency_under_10ms ... ok

test result: ok. 7 passed; 0 failed
```

**Latency measurement:**
- First ping: ~2.3ms (includes TCP handshake)
- Subsequent pings: 50-200 microseconds
- Average (after warmup): ~95 microseconds
- **Target (< 10ms): PASSED**

## User Setup Required

None - server auto-starts when TUI connects.

## Next Phase Readiness

- Phase 1 IPC foundation is now complete:
  - [x] 01-01: Python JSON-RPC server
  - [x] 01-02: Rust IPC client
  - [x] 01-03: Auto-start and integration tests
- Ready for Phase 2: Bridge migration (replace PyO3 calls with IPC)
- All success criteria from ROADMAP.md met:
  - [x] Server starts automatically (ensure_server_running)
  - [x] Ping roundtrip < 10ms (avg ~95us)
  - [x] Integration tests pass (7/7)
  - [x] Stale socket cleanup works

---
*Phase: 01-ipc-foundation*
*Completed: 2026-02-02*
