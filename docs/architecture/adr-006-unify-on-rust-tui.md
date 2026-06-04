# ADR-006: Unify on a Single Rust TUI over an IPC Backend

**Status:** Accepted
**Date:** 2026-05-31
**Deciders:** Project maintainers
**Supersedes:** [ADR-001](adr-001-primary-python-tui.md), [ADR-002](adr-002-rust-tui-secondary-policy.md)
**Depends on:** [ADR-003](adr-003-ipc-boundary-design.md) (IPC boundary)

## Context

[ADR-001](adr-001-primary-python-tui.md) and [ADR-002](adr-002-rust-tui-secondary-policy.md)
(both Accepted, January 2026) designated the **Python/Textual TUI as primary** and the
**Rust/Ratatui TUI as secondary/experimental under a feature freeze** until "a stable IPC
boundary replaces PyO3."

Since then the project has executed the opposite direction, and the code now reflects it:

- The **IPC boundary that was the precondition for lifting the freeze has been built** — the
  Rust client (`src/ipc/`: `client.rs`, `framing.rs`) and the Python service
  (`python/crystalmath/server/`, the `crystalmath-server` entry point) both exist and are
  exercised by integration tests. This is the boundary ADR-003 proposed.
- A new **quacc** workflow backend (`python/crystalmath/quacc/`) was added.
- A new **Monitor tab** (Prometheus-backed: `src/monitor.rs`, `src/prometheus.rs`,
  `src/ui/monitor.rs`) was added to the Rust TUI — a new screen and a new Cargo dependency
  (`reqwest`), both of which the ADR-002 freeze prohibited.
- The active development branch (`codex/integrations-foundation`) and the `.planning/` tree
  (dated February 2026) describe a single unified UI rather than two.

The result was a **dated strategic reversal that no document reconciled**: the ADRs, the
top-level instruction files, and `REFACTOR/` still described "Python primary, Rust frozen,"
while the running code and latest planning moved to "unify on Rust." Maintaining two parallel
UIs (Textual + Ratatui) over the same database is the project's largest source of duplicated
logic and documentation drift.

## Decision

1. **A single Rust/Ratatui TUI is the primary UI.** It owns all user workflows — job creation,
   configuration, templates, workflow orchestration, and monitoring — not just read-only views.

2. **The Python/Textual TUI (`tui/`) is deprecated** and will be phased out. It remains in the
   tree during the transition but receives only critical fixes; new feature work targets the
   Rust TUI and the Python core.

3. **The ADR-002 feature freeze is rescinded.** Its preconditions ("until an IPC boundary is
   defined") have been met. The Rust TUI may add screens, dependencies, and features.

4. **The Rust↔Python boundary is the IPC service of [ADR-003](adr-003-ipc-boundary-design.md)**,
   not PyO3. PyO3 (`src/bridge.rs`) is being **retired**; it remains the live transport only
   until the cutover to `IpcClient` completes (tracked as a follow-up — see Migration Status).

5. **The Python core library (`python/crystalmath/`) is the single source of truth for business
   logic**, exposed over JSON-RPC by `crystalmath-server`. The Rust TUI holds UI state and
   rendering only.

6. **Both `quacc` and AiiDA remain supported, co-equal workflow backends.** This pivot is about
   the UI/transport architecture, not the scientific backend; neither workflow engine is removed.

## Migration Status (as of this ADR)

| Piece | State |
|-------|-------|
| IPC server (`python/crystalmath/server/`, `crystalmath-server`) | Built; now resolves `--db-path`/`CRYSTAL_TUI_DB` so it opens the same `.crystal_tui.db` |
| Rust IPC client (`src/ipc/client.rs`, `framing.rs`) | Built, integration-tested |
| IPC `BridgeService` impl (`src/bridge_ipc.rs`, `IpcBridgeHandle`) | **Implemented** — worker thread + tokio runtime, reuses `route_rpc_response`; end-to-end tested (`tests/ipc_bridge_integration.rs`) |
| Transport selection | Behind the `pyo3-bridge` Cargo feature. **Default is still PyO3**; the IPC transport is opt-in via `cargo build --no-default-features` (needs no `PYO3_PYTHON`) |
| Live default transport | **Still PyO3** via `src/bridge.rs`, pending a soak of the IPC path |
| PyO3 removal | Pending the default-flip + soak (do not delete `bridge.rs` yet) |
| Monitor tab (Prometheus) | Shipped |
| Python TUI (`tui/`) | Present, deprecated, maintenance-only |

The cutover is **implemented and feature-gated** (`BridgeService` is the seam; its typed
`request_*` helpers are now default methods so `BridgeHandle` and `IpcBridgeHandle` differ only in
`request_rpc`/`poll_response`). Remaining: **flip the default feature to IPC and soak**, then
**delete `bridge.rs`'s PyO3 internals + the `pyo3-bridge` feature + the `PYO3_PYTHON` build dance**
(`scripts/build-tui.sh`). See the architectural roadmap for sequencing.

## Consequences

### Positive
- One UI stack to maintain; eliminates Textual↔Ratatui logic duplication.
- A standalone, distributable Rust binary becomes possible once PyO3 is gone.
- Ends the version-coupling pain (PyO3 must match the runtime Python exactly).
- The instruction files, ADRs, and planning docs now describe one direction.

### Negative / Tradeoffs
- Reimplementing the Python TUI's mature workflows in Rust is significant effort.
- Until the PyO3→IPC cutover lands, the build still requires the correct `PYO3_PYTHON`.
- Existing Python TUI users must migrate to the Rust TUI over time.

## Follow-ups

- Cut the running TUI over from PyO3 to `IpcClient` (the keystone refactor).
- Promote [ADR-003](adr-003-ipc-boundary-design.md) to **Implemented** (done in this pass).
- Unify the two Python JSON-RPC dispatch registries (`api.py` controller vs `server/handlers/`).
- Update `AGENTS.md` (the canonical agent doc), `README.md`, and `.planning/` to this direction
  (done in this pass).
