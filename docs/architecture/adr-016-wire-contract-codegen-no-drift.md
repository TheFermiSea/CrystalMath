# ADR-016: Wire Contract — pydantic Models as Source of Truth, Generate Rust serde Types

**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** none
**Depends on:** [ADR-014](adr-014-ipc-boundary-stdio-jsonrpc-delete-pyo3.md) (single JSON-RPC dispatch table), [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md) (emmet-style pydantic TaskDocuments)

## Context

[ADR-003](adr-003-ipc-boundary-design.md) put a JSON-RPC 2.0 boundary between the Rust TUI and
the Python core, and [ADR-006](adr-006-unify-on-rust-tui.md) committed to finishing the PyO3→IPC
cutover. That boundary buys crash isolation, version independence, and a standalone binary — but
it gives up the one thing PyO3's in-process FFI never had to worry about: **the two sides agree on
the shape of the data only by manual discipline.** Every JSON-RPC payload is a pydantic model on
the Python side (`python/crystalmath/models.py`) and a hand-written serde `struct` on the Rust side
(`src/models.rs`). Nothing checks that they match. `AGENTS.md` §3 states the requirement as a rule
to be obeyed — "`src/models.rs` must stay in serde-parity with the Python pydantic models" — which
is precisely the failure mode: a parity invariant enforced by a sentence in a doc, not by the
build.

The drift is not hypothetical and the surface is large. The dispatch table carries ~50 methods
(`api.py:189-274`), each with a request and response shape; `JobStatus`/`JobState`
(`models.py:23,185`) are mirrored in `src/models.rs`; and once [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md)
replaces the untyped `key_results: Dict[str,Any]` blob with versioned `TaskDocument` schemas (one
per code — `CrystalTaskDoc`, `VaspTaskDoc`, `QeTaskDoc`, …), the typed surface the Rust side must
deserialize grows substantially and will keep evolving as fields are added. A renamed field, a
changed enum variant, a widened-to-`Optional` field, or a new required key on the Python side
produces a `serde` deserialize error at runtime on the Rust side — surfaced to the user as a broken
TUI tab, not a build failure. This is the classic cost of an untyped, human-readable wire format:
the boundary research (domain "Rust/Ratatui TUI + interop") names it directly — JSON-RPC "has no
built-in schema enforcement, so serde↔pydantic can silently drift unless you add codegen."

The ecosystem has a clean answer, and it is the deciding argument against the heavier alternative.
The single concrete advantage gRPC/protobuf has over plain JSON-RPC for a local boundary is
**generated typed stubs on both sides** — Werner's "Using gRPC for (local) IPC" (2021) measures
gRPC-over-UDS unary latency at ~116–167µs vs ~4–11µs for raw UDS and concludes the ~100µs overhead
is "entirely acceptable" *for the schema/tooling benefits*, i.e. the codegen is the value, the
binary transport is incidental. For human-paced DFT job submission that latency difference is
irrelevant, so the right move is to **keep the lightweight JSON-RPC/stdio boundary already built
and buy the one thing gRPC offers — generated types — directly**, without protoc, an HTTP/2 stack
(tonic), or a second IDL. Two mature tools make this routine: oxidecomputer's **typify** compiles a
JSON Schema document into idiomatic Rust serde types, and 1Password's **typeshare** generates
cross-language types from annotated serde types. Because the Python core is already the single
source of truth for business logic (ADR-006 decision 5) and pydantic is already the model layer,
pydantic is the natural authority for the *schema* too: pydantic emits JSON Schema natively
(`model_json_schema()`), so the contract can flow Python → JSON Schema → Rust with no hand-mirroring
at any step.

## Decision

**Make the Python pydantic models the single source of truth for the wire contract, emit JSON
Schema from them, and generate the Rust serde types from that schema in `build.rs`. The serde↔pydantic
parity invariant becomes a build artifact, not a discipline — the two sides cannot silently diverge
because the Rust types are mechanically derived from the Python ones.**

### 1. The schema seam: one exported JSON Schema document

Add `python -m crystalmath.contract export-schema` to the Python core. It collects every type that
crosses the IPC boundary — the JSON-RPC envelopes, `JobStatus`/`JobState` (`models.py`), the config
models (ADR-015's pydantic-settings models), and the per-code `TaskDocument` family from
[ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md) — into one root pydantic model and serializes it via
`model_json_schema(ref_template=...)` to a single, versioned **`schema/wire-contract.json`**. This
file is the contract: checked into the repo, the canonical artifact both languages consume.

Crucially, **the dispatch table itself is part of the contract.** Per [ADR-014](adr-014-ipc-boundary-stdio-jsonrpc-delete-pyo3.md)
there is exactly one method registry; the export walks it and, for each `domain.verb` method, emits
the `params` schema and the `result` schema. While the dispatch table (registry of `domain.verb` entries
with `params`/`result` schemas) is part of the contract and the generator emits per-method typed signatures,
those typed Rust client methods are thin wrappers that marshal arguments into the single generic boundary
call `request_rpc(method, serde_json::Value) -> serde_json::Value` rather than introducing multiple distinct
IPC calls. The generated signatures map to the single generic RPC boundary.

### 2. Rust codegen: `typify` in `build.rs`

The Rust crate gains a `build.rs` that runs **typify** (`typify` / `cargo-typify`, oxidecomputer)
over `schema/wire-contract.json` and writes generated serde types to `$OUT_DIR/wire_contract.rs`,
which `src/models.rs` includes via `include!`. The generated types carry `#[derive(Serialize,
Deserialize)]` and match the pydantic field names, optionality, and enum variants by construction.
Hand-written types in `src/models.rs` for boundary-crossing data are **deleted** and replaced by the
generated ones; `src/models.rs` retains only Rust-only UI state that never crosses the wire.

We choose **typify over typeshare as the primary generator** because it makes the *Python pydantic
models* authoritative (schema flows Python → Rust), which matches ADR-006's "Python core is the
single source of truth" exactly. typeshare inverts the authority (it generates *from* annotated Rust
serde types), which would make Rust the source of truth for the shared shapes — the wrong direction
for a project where the business logic, validation, and result schemas all live in Python. typeshare
is retained only as the tool of record for the rare Rust-originated type that Python must read back
(none today; documented as the escape hatch).

### 3. Drift is a CI failure, not a runtime error

Two gates make the contract non-bypassable:

- **Schema freshness:** a CI job runs `python -m crystalmath.contract export-schema --check`, which
  re-exports the schema and fails if `schema/wire-contract.json` is out of date relative to the
  pydantic models. A model change that isn't accompanied by a regenerated schema fails the Python
  lane.
- **Codegen freshness:** `build.rs` regenerates the Rust types from the committed schema on every
  build, so a stale schema is impossible to compile against — the Rust lane builds against exactly
  what's in `schema/wire-contract.json`. A field rename on the Python side now breaks `cargo build`
  (the generated struct changes; call sites that used the old name fail to compile) **at CI time,
  the moment the schema is regenerated**, instead of breaking a TUI tab at runtime.

### 4. Round-trip parity test

A single integration test (extending `tests/ipc_bridge_integration.rs`) asserts that a
representative payload of each boundary type — a `JobStatus`, one `TaskDocument` per code, a config
snapshot — produced by the Python server deserializes into the generated Rust type without error and
round-trips back. This catches the residual class of mismatches JSON Schema can't express (e.g.
`serde` rename attributes, custom (de)serializers) and is the canary that the generation pipeline is
wired correctly.

### 5. Versioning at the handshake

The exported schema carries a contract version (a hash of the schema document, surfaced as a field).
The IPC handshake (the first JSON-RPC exchange after connect) exchanges contract versions; a mismatch
is reported as a typed, user-legible error rather than a deserialize failure deep in a tab. This makes
the two-artifact packaging story (separately released Rust binary + Python wheel — see the packaging
research) safe against version skew: an old binary talking to a new server fails fast and clearly.

## Alternatives Considered

### gRPC / Protocol Buffers (define the contract in `.proto`, generate both sides)

The schema-first option that gets typed stubs by construction and is the canonical "no drift"
answer. **Why not:** it forces a *second* source of truth (a `.proto` IDL) parallel to the pydantic
models that already exist and that ADR-009 makes the result schema — so the pydantic↔proto drift
simply replaces the pydantic↔serde drift, and protobuf's data model is a poor fit for the
deeply-nested, schema-evolving pymatgen/ASE/emmet objects the core already serializes as JSON. It
also drags protoc + a `build.rs` codegen step + an HTTP/2 stack (tonic) into a terminal app for a
single local consumer, and discards the human-readable wire format that aids debugging. Werner (2021)
shows the *only* advantage over plain JSON-RPC here is the generated stubs — which typify gives us on
top of the JSON-RPC boundary already built, at a fraction of the weight. Reserve gRPC for a future
where `crystalmath-server` becomes a shared multi-client network daemon.
(Werner, "Using gRPC for (local) inter-process communication," 2021.)

### typeshare as the primary generator (Rust serde types as source of truth)

1Password's typeshare generates Python (and other languages) from annotated Rust serde types and is
the natural pick if Rust owned the shared types. **Why not:** it inverts the authority. ADR-006
decision 5 makes the Python core the single source of truth for business logic, pydantic is already
the model layer (`models.py`), and ADR-009 makes pydantic `TaskDocument`s the result schema —
generating *from* Rust would force those canonical Python models to be mirrors of Rust annotations,
the exact backwards dependency this redesign avoids. Adopted only as the documented escape hatch for
any future Rust-originated type. (1Password typeshare, https://github.com/1Password/typeshare.)

### Hand-mirroring with a parity unit test (status quo, hardened)

Keep both `models.py` and `src/models.rs` hand-written but add a test that serializes each Python
model and asserts the Rust type deserializes it. **Why not:** a parity test catches drift only for
the exact payloads it enumerates and only *after* someone notices to write the test for a new field;
it does not prevent the divergence, and it leaves the generation burden on humans for a ~50-method ×
N-TaskDocument surface that ADR-009 is actively growing. This is the discipline-not-codegen approach
`AGENTS.md` §3 already encodes and that this ADR exists to replace. The round-trip test in §4 is kept,
but as a canary on the *generated* pipeline, not as the primary defense.

### datamodel-code-generator in reverse / shared OpenAPI doc

Generate from a hand-maintained JSON Schema / OpenAPI document that both pydantic and serde derive
from. **Why not:** it introduces a third hand-maintained artifact (the schema doc) that can itself
drift from the pydantic models, when pydantic already *emits* JSON Schema for free. Letting pydantic
be the schema source (via `model_json_schema()`) removes the extra artifact entirely; the schema is a
build output of the models, not a parallel input.

## Consequences

### Positive

- **The parity invariant is mechanical.** serde↔pydantic drift becomes a `cargo build` / CI failure
  at change time, not a runtime deserialize error in a TUI tab. The `AGENTS.md` §3 "must stay in
  parity" rule is now enforced by the toolchain.
- **JSON-RPC keeps its advantages and gains gRPC's only real one.** Human-readable wire, no protoc,
  no HTTP/2, sub-ms local latency — plus generated typed stubs. The boundary is "as safe as gRPC
  without the weight" (boundary research recommendation).
- **Typed Rust client per method.** Generating the dispatch table's params/result schemas gives the
  Rust client typed signatures, shrinking the `request_rpc(Value) -> Value` generic surface that
  ADR-006 already wants reduced.
- **Safe two-artifact packaging.** The handshake version check (§5) makes independently-released
  binary + wheel robust against version skew — a precondition for the cargo-dist/wheel split.
- **ADR-009 pays off immediately.** Every new `TaskDocument` field is a free, typed Rust field on
  the next build; the result schema can evolve without a manual Rust edit.

### Negative / Tradeoffs

- **Generated code is less ergonomic.** typify output is mechanical (naming, doc comments) and Rust
  authors lose the ability to hand-tune boundary structs; Rust-only conveniences must live in wrapper
  types or `impl` blocks on the generated types.
- **A build-time dependency on typify + a committed schema artifact.** `build.rs` now runs codegen,
  and `schema/wire-contract.json` is a checked-in file that must be regenerated (the `--check` gate
  enforces this, but it is one more step in a model-changing PR).
- **JSON Schema can't express everything.** Custom serde (de)serializers, `#[serde(rename)]`
  subtleties, and validators with no schema analogue fall outside the contract; the §4 round-trip
  test exists precisely to catch this residue.

### Migration impact

1. Add `crystalmath.contract` with `export-schema [--check]`; wire it into the Python CI lane.
2. Commit the first `schema/wire-contract.json` generated from the current `models.py` +
   ADR-009 `TaskDocument`s + the ADR-014 dispatch table.
3. Add `build.rs` + the typify dependency; generate into `$OUT_DIR` and `include!` from
   `src/models.rs`; delete the hand-written boundary structs, keeping Rust-only UI-state types.
4. Add the §4 round-trip test and the §3 freshness gates to CI (`ci-python.yml`, `ci-rust.yml`).
5. Add the §5 contract-version handshake to the IPC client/server.

This depends on [ADR-014](adr-014-ipc-boundary-stdio-jsonrpc-delete-pyo3.md) (one dispatch table to walk) and
[ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md) (the typed pydantic result schemas that make a generated
contract worth having); it is best landed immediately after the PyO3→IPC default-flip
([ADR-006](adr-006-unify-on-rust-tui.md) follow-up), so the boundary the contract protects is the
live one.

## References

- oxidecomputer **typify** — compile JSON Schema to idiomatic Rust serde types (`typify` /
  `cargo-typify`). https://github.com/oxidecomputer/typify
- 1Password **typeshare** — generate cross-language types from annotated Rust serde types.
  https://github.com/1Password/typeshare
- Felix Werner, "Using gRPC for (local) inter-process communication" (2021) — gRPC-over-UDS unary
  latency ~116–167µs vs ~4–11µs raw UDS; the ~100µs overhead "entirely acceptable" *for the
  schema/tooling benefits*, i.e. generated typed stubs are gRPC's real advantage over plain JSON-RPC.
  https://www.mpi-hd.mpg.de/personalhomes/fwerner/research/2021/09/grpc-for-ipc/
- Pydantic — `model_json_schema()` JSON Schema generation; pydantic-settings as the config model
  layer. https://docs.pydantic.dev/latest/concepts/json_schema/
- JSON-RPC 2.0 Specification. https://www.jsonrpc.org/specification
- Internal: `AGENTS.md` §3 (requirement D3 — "`src/models.rs` must stay in serde-parity with the
  Python pydantic models"); `python/crystalmath/models.py`; `src/models.rs`;
  `python/crystalmath/api.py:189-274` (dispatch surface); `tests/ipc_bridge_integration.rs`.
