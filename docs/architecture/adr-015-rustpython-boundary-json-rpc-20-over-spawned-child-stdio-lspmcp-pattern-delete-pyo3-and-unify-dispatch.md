---
adr_id: 015
title: "Rustpython Boundary Json Rpc 20 Over Spawned Child Stdio Lspmcp Pattern Delete Pyo3 And Unify Dispatch"
status: "Accepted"
date: "2026-06-11"
macro_context: "crystalmath-tui-core"
---

# ADR-015: Rustpython Boundary Json Rpc 20 Over Spawned Child Stdio Lspmcp Pattern Delete Pyo3 And Unify Dispatch



**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** [ADR-003](adr-003-ipc-boundary-design.md)
**Depends on:** [ADR-006](adr-006-unify-on-rust-tui.md) (single Rust TUI over IPC; PyO3 cutover named as keystone)
**Relates to:** [ADR-015](adr-015-unified-config-pydantic-settings.md) (the pydantic-settings resolver that supplies the server invocation + socket path this boundary uses; ADR-015 in turn depends on this ADR's `config.get` dispatch method)

## Context

[ADR-003](adr-003-ipc-boundary-design.md) chose a JSON-RPC 2.0 boundary over a **Unix domain
socket**, and [ADR-006](adr-006-unify-on-rust-tui.md) made the single Rust/Ratatui TUI primary,
declaring the IPC service — not PyO3 — the official boundary. Both halves were built
(`src/ipc/client.rs`, `src/ipc/framing.rs`, `crystalmath-server`) and integration-tested. Yet the
cutover **stalled**: the live default transport is **still PyO3** (`adr-006:66`), and the
intervening months have made plain that the socket-path approach and the PyO3 fallback are the two
things keeping the cutover from completing. This ADR finishes the job ADR-006 named as its keystone
follow-up, and it corrects ADR-003's two design mistakes (socket-path resolution and the typed
helper sprawl) rather than merely flipping a feature flag.

**The concrete friction this ADR must resolve:**

1. **PyO3 is structural debt, not a transport.** `src/bridge.rs` is **1,185 lines** of PyO3 and is
   the live default. It compile-locks the Rust binary to one exact CPython ABI (forcing the
   `PYO3_PYTHON` dance in `scripts/build-tui.sh`, per `AGENTS.md:57,69`), entangles the GIL and
   interpreter shutdown (the worker thread can stall in Python GC), gives a Python exception the
   blast radius to crash the TUI, and makes a standalone distributable binary impossible —
   precisely the goal of ADR-006. ADR-003 itself enumerates these four costs (`adr-003:18-24`).
   The cost PyO3 buys back — minimal per-call FFI overhead — is **worthless for human-paced DFT job
   submission**, which is sub-second and single-user.

2. **The socket path is a documented bug class.** ADR-003 flags (`adr-003:42-47`) that the Rust
   client falls back to `/tmp/crystalmath.sock` (`src/ipc/client.rs:117`) while the server falls
   back to `/tmp/crystalmath-{uid}.sock` (`server/__init__.py:64`): when neither `$XDG_RUNTIME_DIR`
   nor the macOS cache dir is present, the two never meet. A socket listener also requires an
   auto-start handshake (`ensure_server_running()`, wait-for-socket ≤5s, `adr-003:161-170`) with an
   inherent start race. Both bug classes are artifacts of a *listener* model; a *spawned child* with
   inherited stdio has neither.

3. **The dispatch is split across two registries with two naming schemes.** `api.py:84`
   (`CrystalController`) builds a registry of ~50 methods mixing `snake_case` (`fetch_jobs`,
   `launch_aiida_geopt`) with dotted (`jobs.list`, `vasp.generate_inputs`); `server/__init__.py`
   imports a **second** `HANDLER_REGISTRY` (`server/handlers/jobs.py` is 888 LOC) and routes
   `system.*` there first, falling through to `controller.dispatch` for everything else. The same
   `jobs.*` namespace is split across two files. Worse, controller/DB **init failures are masked as
   `-32601 "Method not found"`** (`crystalmath-gn8`): a real startup error is reported as if the verb
   does not exist. ADR-006 itself lists "unify the two Python JSON-RPC dispatch registries" as an
   open follow-up (`adr-006:94`).

4. **The Rust request surface is triplicated.** The `BridgeService` trait (`src/bridge.rs:127`)
   carries **~40 typed `request_*` helpers** (`request_fetch_jobs`…`request_launch_aiida_geopt`,
   `:133-393`) *and* a generic `request_rpc` *and* the `BridgeRequest`/`BridgeResponse`/
   `BridgeRequestKind` enums (`:581,602,703`) — every operation expressible three ways, all of which
   must move in lockstep with the Python side.

**Ecosystem state of the art.** The industry has already standardized exactly the pattern this
project is reaching for. The **Language Server Protocol** frames JSON-RPC 2.0 over a process's
stdin/stdout stream using `Content-Length` headers, and clients **spawn the language server as a
child process**. The **Model Context Protocol** (spec 2025-06-18) adopts the same wire format and is
explicit that it "takes inspiration from the Language Server Protocol." This project already
implements LSP-style `Content-Length` framing (`src/ipc/framing.rs`) — it built the right framing on
the wrong transport. Werner's local-IPC measurements (2021) confirm the latency axis is irrelevant
here: gRPC-over-UDS unary calls run ~116–167 µs vs ~4–11 µs for raw UDS — both orders of magnitude
below human perception for a job-submission TUI — so the boundary decision is governed by *coupling
and tooling*, which is exactly where stdio JSON-RPC wins.

## Decision

**Cut over to JSON-RPC 2.0 over a spawned-child stdio stream as the default transport, delete PyO3, and collapse the dual dispatch into one registry.** Concretely:
### 1. Default transport: spawned-child stdio with `Content-Length` framing (the LSP/MCP pattern)

The Rust TUI **spawns `crystalmath-server` as a child process** and speaks JSON-RPC 2.0 over the
child's **stdin/stdout**, framed with the existing `Content-Length` framer (`src/ipc/framing.rs`).
This is how LSP/MCP clients launch language servers, and it eliminates two whole bug classes at once:

- **No socket path** → the `/tmp/crystalmath.sock` vs `/tmp/crystalmath-{uid}.sock` mismatch
  (`adr-003:42`) simply cannot occur; there is no path to resolve.
- **No auto-start race** → the child's readiness is its spawned-and-piped state, not a
  poll-the-socket loop (`adr-003:161-170`); lifecycle is parent-owned and dies with the parent.

A **Unix-domain-socket listener is retained only as an opt-in** for the advanced "one long-lived
shared daemon, many clients" case, selected explicitly via config (ADR-015). The default path is
stdio and needs no listener.

### 2. Delete PyO3 and the triplicated request surface

- Delete `src/bridge.rs` (the 1,185-line PyO3 module), the `pyo3-bridge` Cargo feature, the PyO3
  dependency from `Cargo.toml`, and the `PYO3_PYTHON` build dance in `scripts/build-tui.sh`.
- Delete the **~40 typed `request_*` helpers** and the `BridgeRequest`/`BridgeResponse`/
  `BridgeRequestKind` enums. The boundary keeps **one** generic call —
  `request_rpc(method: &str, params: Value) -> Result<Value>` — so the wire surface exists in exactly
  one place. The `IpcBridgeHandle` worker-thread + tokio plumbing (`src/bridge_ipc.rs`) is promoted
  to the sole `BridgeService` implementation.

### 3. One dispatch registry, `domain.verb` only, honest init errors

- Merge `CrystalController`'s registry (`api.py`) and `HANDLER_REGISTRY`
  (`server/__init__.py`, `server/handlers/`) into **one** method table keyed by the dotted
  `domain.verb` convention (`jobs.list`, `slurm.sync`, `vasp.generate_inputs`). The `snake_case`
  legacy aliases are dropped. The Rust `request_rpc(method, params)` maps 1:1 onto this table —
  there is one namespace on both sides.
- **Surface initialization failures honestly.** A controller/DB/SSH init error must return its real
  JSON-RPC error (the ADR-003 taxonomy: `-32000` server, `-32001` DB, `-32002` SSH, `-32003` SLURM,
  `adr-003:174-184`) — **never** `-32601 "Method not found"` (`crystalmath-gn8`). `-32601` is
  reserved for a genuinely-unregistered verb.

### 4. Schema parity by codegen, not discipline

The single remaining risk of a JSON-only boundary is silent serde↔pydantic drift. Close it by
**code generation**: the pydantic models in the Python core (`models.py`, resolved via the ADR-015
config) are the single source of truth; export their JSON Schema and generate the Rust `serde` wire
types in `build.rs` (typify-class tooling) — or run `typeshare` from the Rust side. This buys the
one guarantee gRPC's IDL would have provided (a contract that cannot silently diverge) without
gRPC's `protoc`/HTTP-2/`tonic` weight, which is unjustified for a single local human-paced consumer
(Werner 2021).

### 5. Config resolves the boundary, per ADR-015

The server command, the stdio-vs-socket choice, and (for the opt-in daemon) the socket path are
resolved **once** by pydantic-settings in the Python core (ADR-015). The Rust side never parses TOML
and never invents a fallback path; it reads the resolved server invocation from config. This is the
fix ADR-003 asked for (`adr-003:46`): one resolver, one value, both sides agree.

## Alternatives Considered

**Keep PyO3 in-process (status quo).** Lowest per-call overhead and ergonomic macros (Amaral et al.
2025 find PyO3's per-call cost near-native and its ergonomics superior to cffi/ctypes). *Why not:*
the latency advantage is irrelevant for human-paced DFT submission, while every PyO3 cost —
CPython-ABI compile lock, GIL/shutdown coupling (Harding & Dunlavy 2025), shared-crash blast radius,
and "no standalone binary" — directly blocks ADR-006's headline goal. This is the debt being
deleted, not a candidate.

**JSON-RPC over a Unix domain socket (ADR-003's original choice).** Same wire protocol, crash
isolation, and standalone-binary benefit as stdio. *Why not as the default:* the listener model is
the *source* of the two documented bug classes — the divergent `/tmp` fallback (`adr-003:42`) and
the auto-start race (`adr-003:161-170`). A spawned child with inherited stdio has neither, which is
exactly why LSP and MCP launch servers as children rather than connecting to a socket. UDS is
retained as the opt-in shared-daemon transport, not the default.

**gRPC / Cap'n Proto / msgpack-RPC (schema-first IDL).** Strongly-typed generated stubs on both
sides eliminate drift by construction, with streaming, deadlines, and back-pressure built in
(Werner 2021). *Why not:* heaviest toolchain (`protoc` + `build.rs` codegen + an HTTP/2 stack pulled
into a terminal app); ~100 µs/call and a full async server are over-built for one local consumer
(Werner 2021); and proto's flat data model is a poor fit for the deeply-nested, schema-evolving
pymatgen/ASE objects the core already round-trips as JSON. Its sole advantage over plain JSON-RPC —
generated typed stubs — is bought more cheaply by the §4 JSON-Schema codegen. Reserve gRPC for a
hypothetical future where `crystalmath-server` becomes a shared multi-client *network* daemon.

**Drop the Rust UI; go Textual-only (no boundary at all).** The most intellectually honest
"simplest thing that works": one process, shared types and async loop, mature Worker API, and a
built-in web server for remote HPC access (Textualize). *Why not:* it reverses ADR-006 (which
deprecated `tui/`) and forfeits the single distributable binary that motivates this whole line of
work, while discarding the substantial Rust TUI already shipped (Monitor/Prometheus tabs, `app.rs`).
Named here honestly because it dissolves the boundary problem entirely — but it contradicts the
team's chosen direction, so finishing the stdio cutover is the decisive path.

## Consequences

### Positive


- **Standalone, distributable Rust binary becomes real** — no embedded interpreter, no `PYO3_PYTHON`,
  no Python in every Rust CI job. This unblocks the two-artifact packaging story (binary +
  pure-Python wheel) and `crystalmath-5nz`.
- **Two bug classes deleted, not patched:** the socket-path mismatch and the auto-start race vanish
  with the listener.
- **One wire surface:** the boundary exists once (`request_rpc` + one `domain.verb` table), not three
  times in Rust and twice in Python.
- **Honest errors:** init failures stop masquerading as "Method not found" (`crystalmath-gn8`).
- **Crash isolation:** a Python exception or segfault no longer takes down the TUI.
- **Industry-validated:** the boundary is exactly LSP/MCP, so the design is well-trodden and the
  framing code (`framing.rs`) is already correct.

### Negative / Tradeoffs


- **A second process to supervise.** Mitigated: parent-owned stdio lifecycle is *simpler* than the
  socket+auto-start it replaces; the child dies with the parent.
- **JSON is verbose for large payloads** (structures, DOS grids). Mitigated: pass those by file
  path/handle (shared NFS / scratch), never inline in the JSON envelope.
- **Codegen step adds build machinery.** Mitigated: it is the price of drift-proofing a JSON boundary
  and is far lighter than a gRPC toolchain.

### Migration Impact


1. Implement stdio spawn + `Content-Length` framing as the default `BridgeService`
   (`src/bridge_ipc.rs` becomes the only impl); keep UDS behind an explicit config opt-in.
2. Flip the default Cargo build off `pyo3-bridge`; verify integration tests
   (`tests/ipc_bridge_integration.rs`) pass over stdio (`crystalmath-bc6`).
3. Merge the two dispatch registries into one `domain.verb` table; convert `-32601`-masked init
   errors to the real taxonomy (`crystalmath-dew`, `crystalmath-gn8`).
4. Add JSON-Schema export + Rust `serde` codegen in `build.rs` (or `typeshare`).
5. **Delete** `src/bridge.rs`, the `pyo3-bridge` feature, the PyO3 dep, the ~40 `request_*` helpers,
   the `BridgeRequest*` enums, and the `PYO3_PYTHON` dance in `scripts/build-tui.sh`.
6. Route the resolved server invocation through ADR-015 config; remove all Rust-side path fallbacks.

## References

- Model Context Protocol Specification, version 2025-06-18 — JSON-RPC 2.0 messages; "MCP takes
  inspiration from the Language Server Protocol." https://modelcontextprotocol.io/specification/2025-06-18
- Language Server Protocol Specification (Microsoft), 3.17 — `Content-Length` framing of JSON-RPC over
  a stream; client spawns the server as a child process.
  https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/
- JSON-RPC 2.0 Specification. https://www.jsonrpc.org/specification
- F. Werner, "Using gRPC for (local) inter-process communication" (2021) — gRPC-over-UDS unary
  latency ~116–167 µs vs ~4–11 µs raw UDS; ~100 µs overhead acceptable only for the schema/tooling
  it buys. https://www.mpi-hd.mpg.de/personalhomes/fwerner/research/2021/09/grpc-for-ipc/
- I. Amaral, R. Ferreira, A. Goldman, "Rust vs. C for Python Libraries: Evaluating Rust-Compatible
  Bindings Toolchains," arXiv:2507.00264 (2025) — PyO3 ergonomics and per-call overhead.
- K. Harding & D. M. Dunlavy, "Improving Runtime Performance of Tensor Computations using Rust From
  Python," arXiv:2510.01495 (2025) — PyO3/CPython GIL and reference-counting coupling across the FFI.
- 1Password `typeshare` (generate language types from annotated Rust serde types):
  https://github.com/1Password/typeshare ; Oxide `typify` (JSON Schema → idiomatic Rust types):
  https://github.com/oxidecomputer/typify
- Codebase evidence: `src/bridge.rs` (PyO3, typed `request_*` `:127,133-393`; `BridgeRequest*`
  enums `:581,602,703`); `src/ipc/client.rs:117` and `python/crystalmath/server/__init__.py:64`
  (divergent `/tmp` fallback); `python/crystalmath/api.py:84` and `python/crystalmath/server/`
  (dual dispatch); `scripts/build-tui.sh`, `AGENTS.md:57,69` (`PYO3_PYTHON` dance). Issues:
  `crystalmath-bc6` (flip default to IPC, remove PyO3), `crystalmath-dew` (unify dispatch),
  `crystalmath-gn8` (init errors masked as "Method not found"), `crystalmath-5nz` (standalone binary).
