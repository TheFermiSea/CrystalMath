# ADR-007: Redesign Overview — Adopt the Materials-Project Ecosystem, Collapse N-Way Facades to One

> **North-star ADR.** This is the umbrella decision for the free-rein redesign. It does not
> introduce a new mechanism so much as it sets a *rule* — replace every "N co-equal
> implementations behind a thin facade" with one default grounded in a mature ecosystem tool —
> and it fixes the dependency-ordered ADR set, the migration sequencing, and the deletion
> triggers that the per-topic ADRs (008+) implement. With **zero current users**, the redesign
> has free rein to delete rather than deprecate.

**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** none
**Depends on:** none (the per-topic ADRs it sequences depend on it)

## Context

CrystalMath is a multi-code computational-materials manager. The original frozen taxonomy was a
flat five-code list (CRYSTAL23, VASP, Quantum ESPRESSO, YAMBO, phonopy); the
[Amendment (2026-06-03)](#amendment-2026-06-03-sota-alignment) below generalizes it to a *code-class*
taxonomy in which DFT/file-codes are **one class** and MLIP/foundation calculators are a **peer
class** (see [ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md)). Concretely the codes are:
today a Rust/Ratatui TUI (`src/`) talks over an IPC boundary ([ADR-003](adr-003-ipc-boundary-design.md))
to a Python core (`python/crystalmath/`) exposed by `crystalmath-server`, with PyO3
(`src/bridge.rs`) as the legacy transport being cut over to IPC ([ADR-006](adr-006-unify-on-rust-tui.md)).
The Python core wraps pymatgen/ASE and integrates quacc, AiiDA, and atomate2/jobflow; it submits
to SLURM over SSH; a `decks` seam generates per-code input files.

**The recurring anti-pattern.** A friction audit of the codebase finds the *same* shape in seven
distinct places: **N co-equal implementations sit behind a thin facade, and the system performs
availability-detection at runtime instead of having made a decision.** Concretely:

- **Runners (≥5 hierarchies, none authoritative).** `protocols.py:304` `WorkflowRunner`,
  `_vendor/runners/base.py:174` `BaseRunner`/`RemoteBaseRunner`, `quacc/runner.py:71` `JobRunner`,
  and `high_level/runners.py:208` `BaseAnalysisRunner` (the file is **2,488 LOC** with six bespoke
  exception types) share no base class, job-state enum, or result type.
- **SLURM-over-SSH (3 implementations).** `_vendor/runners/slurm_runner.py` (**1,758 LOC**),
  `integrations/slurm_runner.py` (**1,549 LOC**), and the deprecated `tui/src/runners/slurm_runner.py`
  each re-implement `sbatch`/`squeue` parsing, job-ID regex, and asyncssh transport — ~3.3k LOC of
  reinvention, including a runtime fallback ("TUI connection manager not available, using direct
  asyncssh", `integrations/slurm_runner.py:689-699`).
- **Dispatch (2 registries, 2 namespaces).** `api.py:189-274` `CrystalController` mixes
  `snake_case` and dotted method names; `server/handlers/` is a *second* registry checked first for
  `system.*` (`server/__init__.py:213-269`). ADR-006 already flags this as an open follow-up.
- **Transport (PyO3 + IPC both live).** `src/bridge.rs` (**1,185 LOC** of PyO3) is the default while
  `src/ipc/client.rs` + `framing.rs` exist behind a Cargo feature; `BridgeService` carries ~40 typed
  `request_*` helpers *and* a generic `request_rpc`, with the request surface duplicated a third time
  in `BridgeRequestKind` enums.
- **Per-code deck logic (4 seams).** `_vendor/core/codes/`, `decks/__init__.py` (`CodeDeckGenerator`),
  `vasp/generator.py` (still called directly by `api.py`), and `quacc/potcar.py` each carry input
  generation for the same codes.
- **Result storage (3 stores + a Pydantic facade).** `backends/__init__.py:220` selects among a
  bespoke SQLite schema (`_vendor/core/database.py:150`, hand-rolled `ALTER TABLE` migrations), AiiDA,
  and a jobflow/maggma `JobStore` bridged by `integrations/jobflow_store.py` (**984 LOC**) — with at
  least **six** different `JobState`/`JobStatus` types across modules and an untyped
  `key_results: Dict[str,Any]` blob in `models.py`.
- **`_vendor/` is a fork-copy of the *deprecated* `tui/`.** `_vendor/__init__.py` documents that it is
  a hand-frozen copy of the Textual TUI's backend closure (33 files, including a 1,452-LOC
  `database.py` and a `materials_api/` client that re-wraps `mp_api`/OPTIMADE) that must round-trip
  through `tui/` to update. The "single source of truth" core depends on frozen copies of a module
  ADR-006 declares dead.

Each facade *defers* a decision; the cumulative cost is a test matrix that is the cross-product of
{storage} × {engine} × {transport}, riddled with `ImportError`-gated degraded modes that turn
missing extras into silent no-ops.

**The ecosystem already made these decisions.** The computational-materials community has converged
on a coherent stack, and CrystalMath is reinventing every layer of it:

- **Workflow model:** jobflow `Maker`s compose into `Flow`s; atomate2 builds per-code workflows on
  top (Rosen et al., *Jobflow*, JOSS 2024; Ganose et al., *Atomate2*, Digital Discovery 2025).
- **Result store:** jobflow's `JobStore` is a thin facade over maggma `Store` backends — a local
  serverless store by default, swappable to MongoDB+S3 by config — keyed by job uuid.
- **Result schema:** emmet-core ships versioned pydantic `TaskDocument`s, replacing untyped blobs.
- **Structure object & interchange:** pymatgen `Structure`/`ComputedEntry` (MSONable) is the lingua
  franca (Ong et al., pymatgen, 2013); ASE `Atoms` + its `FileIOCalculator`/`SocketIOCalculator`
  give per-code I/O for ~40 engines (Larsen et al., 2017); OPTIMADE is the federated interchange
  standard (Andersen et al., 2021).
- **Remote HPC submission:** jobflow-remote runs an *outbound-SSH polling daemon* that matches
  firewalled-HPC reality, where Parsl/Dask require inbound worker callbacks; PSI/J standardizes the
  scheduler abstraction (Hategan-Marandiuc et al., 2023).
- **Provenance (heavyweight, opt-in):** AiiDA's immutable DAG in PostgreSQL is the gold standard
  (Pizzi et al., 2016; Huber et al., 2020) — but its RabbitMQ/PostgreSQL tax is wrong as a default
  for a laptop-first TUI.
- **The Rust↔Python boundary:** JSON-RPC 2.0 over a spawned-child stdio stream is exactly the
  LSP/MCP pattern (MCP spec 2025-06-18, "inspired by LSP"); `framing.rs` already implements
  LSP-style Content-Length framing.

## Decision

**Adopt, don't reinvent.** Every CrystalMath facade collapses to *one default* grounded in the
ecosystem stack above; the rest are demoted to genuinely-optional plugins behind a single stable
seam, or deleted. The target architecture has exactly one of each layer. *(Amended 2026-06-03 — the
[Amendment](#amendment-2026-06-03-sota-alignment) below recasts the calculation layer so that **DFT
is one `CalculatorStage`, not the center**, with MLIP/foundation calculators as a peer instance, and
adds four new load-bearing layers — items 10–13.)*

1. **One structure object** — pymatgen `Structure` / ASE `Atoms` (MSONable, round-trippable).
2. **One per-code I/O seam** — the existing `CodeDeckGenerator`/`InputDeck` vocabulary
   (`decks/__init__.py`, locked in `CONTEXT.md`), re-implemented as **thin adapters over ASE
   FileIO/Socket calculators and pymatgen `InputSet`s** rather than hand-rolled POSCAR/d12/pw.in
   writers. `vasp/generator.py`, `_vendor/core/codes/`, and `quacc/potcar.py` collapse into it.
   *(Amended 2026-06-03: `CodeDeckGenerator`/`InputDeck` is now the DFT-and-file-code specialization
   of a more general `Structure → TaskDocument` **`CalculatorStage`** — see
   [ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md) and item 10 below. The MLIP peer
   (`MlipCalculatorStage`) emits zero files and POTCAR validation becomes DFT-only.)*
3. **One workflow model** — jobflow `Flow`s, using atomate2/quacc recipes where they exist and a
   thin code-specific `Maker` for CRYSTAL23/YAMBO where they don't.
4. **One canonical result store** — jobflow `JobStore` over maggma; default to a serverless local
   store, swappable to MongoDB+S3 by config. Deletes the bespoke SQLite schema *and* the
   `jobflow_store.py` bridge.
5. **One typed result schema** — emmet-style versioned pydantic `TaskDocument`s, **one per code**,
   replacing the untyped `key_results` blob. Multi-code handoff (the VASP→YAMBO keystone, CRYSTAL
   `.f9` / VASP `WAVECAR` passing) is expressed as **typed edges between documents** carrying input
   hash, code+version, parent-job uuids, and content-addressed raw-file paths — so even the default
   non-AiiDA path is reproducible — with mandatory restart-file validation.
6. **One remote-execution layer** — jobflow-remote's outbound-SSH polling daemon as the default
   `ExecutionBackend`; **AiiDA is the single opt-in heavyweight alternative** behind the same
   protocol, never the default, its PostgreSQL/RabbitMQ tax never imposed on the laptop user.
7. **One Rust↔Python boundary** — JSON-RPC 2.0 over a spawned-child stdio stream; PyO3 deleted.
8. **One dispatch table** — collapse `api.py` and `server/handlers/` into a single `domain.verb`
   registry; the Rust `BridgeService` maps 1:1 onto it; surface init errors honestly.
9. **One config resolver** — pydantic-settings (layered XDG-TOML + project-TOML + env) in the Python
   core; the Rust TUI and the Bash CLI read *resolved* values from it and never parse TOML
   independently, killing the socket-path mismatch ([ADR-003](adr-003-ipc-boundary-design.md) ⚠️).

*The following four layers are added by the [Amendment (2026-06-03)](#amendment-2026-06-03-sota-alignment);
they re-center the spine without contradicting items 1–9.*

10. **One calculation abstraction** — a single `CalculatorStage` (`Structure → TaskDocument`), with
    `DftCalculatorStage` (wrapping the item-2 deck generators) and `MlipCalculatorStage` (a thin
    wrapper over an ASE `Calculator` keyed by a content-addressed checkpoint, emitting zero files) as
    co-equal **instances**. DFT is one stage, not the center
    ([ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md)).
11. **One execution identity / CAS** — a canonical content-hash over the full closure (statepoint +
    calculator/model + executable/lock + pseudopotential + parent hashes + env fingerprint) is the
    **default execution gate**: hash-hit ⇒ cache-and-clone rather than re-run; raw artifacts are
    backed by a disk-objectstore CAS. Promotes item-5's advisory `input_hash` and ADR-013's
    per-handoff checksum into one enforced identity ([ADR-022](adr-022-content-addressed-execution-cache-replay.md)).
12. **One agentic control plane + AI-provenance surface** — a planner/campaign controller *above*
    jobflow that emits typed jobflow `Flow`s (item 3's factories remain the building blocks it
    composes, never bypassed), exposed to LLM agents through a guarded MCP tool-server over the
    item-7 stdio JSON-RPC transport with TUI-gated approval; agent/model/prompt/acquisition/approval
    provenance folds into the item-5 schema and the item-11 hash
    ([ADR-023](adr-023-agentic-control-plane-mcp-ai-provenance.md)).
13. **One static DAG validator** — `crystalmath validate` type-checks every ADR-013 handoff edge
    *offline before submission*, extending ADR-016's "drift is a build failure, not a runtime error"
    principle inward from the wire to the scientific DAG and demoting ADR-013's runtime
    `RestartValidation` to a backstop ([ADR-024](adr-024-static-typed-workflow-dag-validation.md)).

**The dependency-ordered ADR set this overview governs:**

| ADR | Topic | Collapses | Default chosen |
|-----|-------|-----------|----------------|
| **007** (this) | Redesign overview | the meta-pattern | "adopt, don't reinvent" |
| **[008](adr-008-structure-and-deck-io-on-ase-pymatgen.md)** | Structure object & per-code I/O seam | deck logic §6, `vasp/generator`, `_vendor/codes` | one `Structure`/`Atoms`; `CodeDeckGenerator` thin-adapters over ASE/pymatgen |
| **[009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md)** | Data model & provenance schema | `key_results` blob §7, six `JobState` enums | emmet-style versioned pydantic `TaskDocument`s + first-class lineage fields |
| **[010](adr-010-single-result-store-jobflow-maggma.md)** | Result store | three-way storage split §7 | jobflow `JobStore` over maggma (serverless default, Mongo/S3 by config) |
| **[011](adr-011-workflow-engine-jobflow-atomate2-quacc.md)** | Workflow engine | runner sprawl §1 | jobflow `Flow`s; atomate2/quacc recipes; thin `Maker`s for CRYSTAL/YAMBO |
| **[012](adr-012-hpc-execution-jobflow-remote-aiida-optional.md)** | HPC execution backend | three SLURM-over-SSH impls §2 | jobflow-remote outbound-SSH daemon; AiiDA opt-in behind one `ExecutionBackend` |
| **[013](adr-013-multi-code-handoff-and-restart-validation.md)** | Multi-code handoff | untyped `CodeHandoff`, no restart validation | typed `TaskDocument` edges + mandatory positive restart-file validation |
| **[014](adr-014-ipc-boundary-stdio-jsonrpc-delete-pyo3.md)** | IPC transport & dispatch | transport §4, dual dispatch §3 | JSON-RPC/stdio (LSP/MCP); delete PyO3; one `domain.verb` registry |
| **[015](adr-015-unified-config-pydantic-settings.md)** | Configuration | three config mechanisms | pydantic-settings, layered XDG-TOML + project-TOML + env |
| **[016](adr-016-wire-contract-codegen-no-drift.md)** | Wire contract | serde↔pydantic drift | pydantic → JSON-Schema → generated Rust serde types (typify) |
| **[017](adr-017-packaging-testing-two-artifacts-pixi.md)** | Packaging, distribution & testing | build coupling, extras sprawl | two artifacts (cargo-dist binary + hatchling wheel); pixi dev env |
| **[018](adr-018-error-recovery-custodian-handlers.md)** | Error recovery | bespoke ADAPTIVE recovery | custodian-style per-code handlers |
| **[019](adr-019-delete-phase3-protocols-aspiration-layer.md)** | Delete Phase 3 aspiration layer | unimplemented Protocol layer | delete `protocols.py`/`high_level` stubs; keep type aliases |
| **[020](adr-020-reproducibility-and-golden-file-testing.md)** | Reproducibility spine | shallow/fragmented testing | golden-file + property/metamorphic tests + real-output parser fixtures |

The ordering is a true dependency chain: 008's I/O seam populates 009's documents; 009's schema is
what 010's store persists; 011's `Flow`s write 009-documents into 010's store and submit to 012's
backend; 013's typed handoff edges connect 009-documents across a 011 `Flow`; on the boundary side,
014's PyO3→stdio cutover is what *enables* 017's decoupled artifacts, 015 resolves the socket path
014 relies on, and 016 makes the 014 boundary drift-proof. ADRs 008–017 are siblings under this
overview; this ADR is normative on the *rule and the sequencing*, and each sibling is normative on
its layer.

**Migration sequencing and deletion triggers.** The redesign proceeds in dependency order, and each
deletion has an explicit, testable trigger — nothing is deleted on faith:

| # | Step (ADR) | Deletion trigger | Deletes |
|---|-----------|------------------|---------|
| 1 | Flip transport default to IPC/stdio + unify dispatch (014) | IPC path soaks green across the CI lanes; one `domain.verb` registry passes parity | `src/bridge.rs` PyO3 internals, `pyo3-bridge` feature, ~40 typed `request_*` helpers, `scripts/build-tui.sh` PYO3 dance |
| 2 | Define typed `TaskDocument`s (009) + stand up `JobStore` as canonical store (010) | every read/write path goes through the store; round-trip tests pass | bespoke SQLite schema (`_vendor/core/database.py`), `integrations/jobflow_store.py` bridge, duplicate `JobState`/`JobStatus` enums, `key_results` blob |
| 3 | Make `CodeDeckGenerator` the only per-code seam over ASE/pymatgen (008) | `api.py`, quacc, and runners all route through it; deck tests pass on synthetic POTCARs | `vasp/generator.py` standalone path, `_vendor/core/codes/`, `quacc/potcar.py` |
| 4 | Adopt jobflow `Flow`s (011) + jobflow-remote as default `ExecutionBackend`, AiiDA behind same protocol (012); typed restart-validated handoff edges (013) | one engine adapter submits + monitors end-to-end on the cluster; VASP→YAMBO handoff validates | `integrations/slurm_runner.py`, `_vendor/runners/`, `high_level/runners.py` sprawl + stub-execution scaffolding |
| 5 | Promote needed `_vendor/` code to first-class `crystalmath` modules (008–012) | nothing imports `_vendor/` | **`tui/` and `_vendor/` deleted together** |
| 6 | Resolve config once (015), drift-proof the wire contract (016), decouple packaging into two artifacts (017) | PyO3 gone (step 1) and core is pure-Python; schema codegen green | the fused-build coupling; ship cargo-dist binary + hatchling wheel |

Steps 1–3 are independently shippable; steps 4–6 depend on them. The single highest-leverage move
remains the PyO3→IPC cutover (step 1), the keystone ADR-006 already identified.

## Alternatives Considered

**A. Keep the facades; finish the half-built integrations in place.** Wire up all five runners, both
dispatch registries, and all three stores so each works. *Why not:* this is the status quo's trajectory
and it does not remove the cost — the test matrix stays a cross-product, the `_vendor/` fork stays
load-bearing, and the team keeps paying maintenance the field has already paid. With zero users there
is no compatibility reason to preserve N implementations; the redesign's entire premise is that a
*decision*, not another facade, is the fix.

**B. Standardize on AiiDA as the single engine + store + provenance graph.** Make AiiDA the one
backend; its plugins (aiida-quantumespresso, aiida-crystal-dft), SSH transport, scheduler abstraction,
and immutable DAG would cover §1, §2, and §7 at once (Pizzi et al., *AiiDA*, Comput. Mater. Sci. 111,
2016; Huber et al., *AiiDA 1.0*, Sci. Data 7, 2020). *Why not:* AiiDA mandates a PostgreSQL server (and
historically RabbitMQ) and an "everything is an AiiDA node" model that fights a laptop-first single-user
TUI; its operational tax is wrong as a *default*. We adopt its **pattern** (first-class provenance edges)
as fields on the default store and keep AiiDA itself as the single opt-in heavyweight `ExecutionBackend`
for users who need publication-grade reproducibility — never imposed by default.

**C. Build the submission layer on Parsl `HighThroughputExecutor` or Dask-Jobqueue.** Use a proven
parallel-Python executor for SLURM (Babuji et al., *Parsl*, HPDC 2019). *Why not:* HTEX requires
**inbound** connections from compute nodes back to the coordinator (worker ports 54000–55000), which
firewalled HPC centers block and which is hostile to a TUI that may run on a NATed laptop. The decisive
connectivity axis favors an outbound-SSH polling daemon (jobflow-remote/AiiDA). Parsl/Dask are reserved
as optional *in-allocation* executors launched inside a batch job, not the SSH submission boundary.

**D. Adopt signac for a serverless, file-based data space.** Use signac's JSON-statepoint workspaces to
track calculation directories (Adorf et al., *signac*, Comput. Mater. Sci. 146, 2018). *Why not:* its
provenance is implicit in directory state rather than a typed, queryable document, and adopting it
*alongside* jobflow would recreate the exact "multiple overlapping stores" problem the redesign exists to
kill. We borrow only its directory-as-statepoint idea (content-addressed raw-file paths on the
`TaskDocument`).

**E. gRPC / Protocol Buffers for the Rust↔Python boundary.** Schema-first IDL with generated typed stubs
on both sides eliminates serde↔pydantic drift by construction (Werner, *gRPC for local IPC*, 2021).
*Why not:* its sole advantage over plain JSON-RPC — generated typed stubs — is buyable far more cheaply via
JSON-Schema codegen (typify/typeshare) on top of the JSON-RPC boundary *already built*; its ~100µs/call,
HTTP/2 (tonic), and `protoc` build weight is unjustified for a single, local, human-paced consumer where
even that latency is imperceptible. Reserved for a future shared multi-client network daemon.

**F. Delete the Rust UI and go Textual-only.** Collapse the entire boundary problem by building the whole
UI in Python/Textual (mature Worker API, built-in web serving). *Why not:* this reverses ADR-006, forfeits
the single distributable binary that is its headline goal, and discards the shipped Rust TUI (Monitor,
SLURM-queue, editor screens). Named honestly as the "simplest thing that works" if a standalone binary is
*not* a hard requirement — but it is, so we finish the JSON-RPC/stdio cutover instead.

## Consequences

### Positive
- **One of each layer.** Five runner hierarchies, three SLURM paths, three stores, four deck seams, and
  two dispatch registries each collapse to one — eliminating the cross-product test matrix and the
  availability-detected degraded modes.
- **Net deletion.** ~3.3k LOC of bespoke SLURM/SSH, the 984-LOC jobflow bridge, the 1,185-LOC PyO3
  bridge, the `_vendor/` fork (33 files), and the deprecated `tui/` package all go; CrystalMath shrinks
  toward thin adapters over maintained libraries.
- **Reproducible by default.** First-class provenance fields on every `TaskDocument` make even the
  serverless path retraceable, without imposing AiiDA's server tax.
- **Distributable binary.** Once PyO3 is gone, the Rust TUI and Python core build and release as two
  independent artifacts (the long-standing ADR-006 goal).
- **One direction documented.** The dependency-ordered ADR set is the single source of truth, preventing
  the drift ADR-006 had to retroactively reconcile.

### Negative / Tradeoffs
- **Large up-front rewrite.** Adapters, the new store/schema, and the engine cutover are real effort, even
  though most of it is *deletion plus delegation* rather than new invention.
- **New external dependencies become load-bearing** (jobflow, jobflow-remote, maggma, emmet-core), trading
  in-house control for community maintenance and the ecosystem's release cadence.
- **Codes the ecosystem doesn't cover** (CRYSTAL23, YAMBO GW/BSE) still need bespoke `Maker`s/parsers and
  emmet-style schemas; we own those, ideally contributing upstream.
- **Two opt-in engines remain** (jobflow-remote default, AiiDA heavyweight), so the `ExecutionBackend`
  protocol must be genuinely stable — but this is *two behind one seam*, not five behind a facade.
- **Four new layers (items 10–13) widen the umbrella** (Amendment 2026-06-03). Generalizing the
  calculation layer to `CalculatorStage` reopens item-2 vocabulary; admitting an in-process/GPU MLIP
  inference backend carves a *narrow non-sbatch exception* into ADR-012's "all compute via sbatch by
  construction" invariant (inference only, never DFT); and the agentic control plane (item 12)
  reintroduces non-determinism that the spine worked to eliminate — bounded by reusing the
  explicit-gate posture (`allow_stub_execution`, `allow_restart_skew`) so agent output is always a
  *proposed* typed `Flow` validated by items 12–13 and never executed unvalidated. These are detailed,
  with citations, in the [Amendment](#amendment-2026-06-03-sota-alignment).

### Migration impact
- Sequenced and trigger-gated (table above); steps 1–3 ship independently, 4–6 follow. Quality gates
  (the three CI lanes, synthetic-POTCAR fixtures, an extras matrix that exercises each `skipif` path) must
  stay green at each step. Issues tracked in `bd` (beads). No data migration is needed — there are zero
  users — so each store/transport swap is a cutover, not a dual-write.

## Amendment (2026-06-03): SOTA alignment

This amendment keeps the entire 007–020 spine intact and adds **four orthogonal layers** stacked on
it, introduced by **ADR-021–024**. None of the locked decisions in items 1–9 is reversed. The
reframing is that **DFT is one instance of a more general abstraction, not the abstraction itself**.
Without this amendment the four new ADRs read as orphans outside the north star: the original
nine-layer list and the frozen five-code taxonomy (007:18, cited downstream by
[009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md),
[011](adr-011-workflow-engine-jobflow-atomate2-quacc.md),
[013](adr-013-multi-code-handoff-and-restart-validation.md),
[020](adr-020-reproducibility-and-golden-file-testing.md)) enumerate exactly the layers the system
owns, and the new ADRs introduce layers — ML calculation, content-addressing as first-class, agentic
control, static validation — that those nine do not name.

### What changes in the taxonomy

The frozen five-code list becomes a **code-class** taxonomy:

- **DFT / file-codes** (CRYSTAL23, VASP, Quantum ESPRESSO, YAMBO) and **phonopy** — file-emitting
  stages that round-trip decks through a real executable; POTCAR/pseudopotential validation lives
  here and *only* here.
- **MLIP / foundation calculators** (e.g. MACE-MP-0, CHGNet, MatterSim, ORB, SevenNet) — a **peer
  class**, not a sub-case of DFT. An MLIP run returns energy/forces/stress with **zero files**, as a
  pure function of (statepoint, checkpoint hash, settings, library versions). Every such model ships
  an ASE `Calculator`, so the universal boundary item 2 already named (the `SocketIOCalculator`
  escape hatch) is exactly the seam — no new seam is invented.

The keystone is **[ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md)**'s `CalculatorStage`: item
2's `CodeDeckGenerator`/`InputDeck` is recast as the DFT-and-file-code specialization of a generic
`Structure → TaskDocument` stage, with `MlipCalculatorStage` (a thin wrapper over an ASE `Calculator`
keyed by a content-addressed checkpoint) as a co-equal peer. This composes cleanly because every
existing seam already speaks the right vocabulary: the ASE `Calculator` boundary (item 2 / ADR-008),
the MSONable round-tripping `TaskDocument` (item 5 / ADR-009), jobflow `Response(detour/replace)` for
dynamic sub-DAGs (item 3 / ADR-011), and the `ExecutionBackend` protocol (item 6 / ADR-012).

### The four new layers and how they slot onto the spine

1. **[ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md) — generalize the CALCULATION layer**
   (items 2/3/5/6, i.e. ADR-008/009/011/012) so MLIPs are first-class. DFT loses its privileged
   center; POTCAR validation becomes DFT-only; and an in-process/GPU inference backend joins
   jobflow-remote/AiiDA under a **narrowly-carved non-sbatch exception** to ADR-012's
   "all compute via sbatch by construction" invariant (inference only, never DFT). The TaskDocument
   gains MLIP provenance (model + checkpoint hash, fidelity lineage, uncertainty with a method tag,
   acquisition function, fine-tune parent), and the five common MLIP usage modes — pre-relax,
   surrogate-screen, uncertainty-gated escalation, active learning, Δ-ML/fine-tune — map onto jobflow
   `Response(detour/replace)`.

2. **[ADR-022](adr-022-content-addressed-execution-cache-replay.md) — make the IDENTITY layer real.**
   The 007–020 set *records* content addressing but never *enforces* it (item 5's `input_hash` is
   advisory; ADR-013's checksum fires only per-handoff). ADR-022 promotes both into **one canonical
   content-hash over the full closure** (statepoint + calculator/model + executable/lock +
   pseudopotential + parent hashes + env fingerprint) and makes **hash-hit cache-and-clone the
   default execution gate** — AiiDA's caching contract ported to the maggma path, with AiiDA's
   `sqlite_dos` (server-free) profile as the strict reference implementation. This resolves the
   internal 010/012 inconsistency (ADR-010 rejected AiiDA-default for needing PostgreSQL; ADR-012
   already admits the lightweight `sqlite_dos` profile exists). Raw artifacts are backed by a
   disk-objectstore CAS, and a **replay / env-fingerprint contract** (per-property scientific
   tolerances, not byte-equality) closes the gap ADR-020 leaves open across heterogeneous HPC.
   Crucially, ML and agentic nodes are **first-class cache participants**: a checkpoint bump
   invalidates dependent surrogates; LLM/agent nodes are themselves un-cached, but their
   deterministic child stages are cached.

3. **[ADR-023](adr-023-agentic-control-plane-mcp-ai-provenance.md) — add the CONTROL layer ABOVE jobflow.** A
   planner/campaign controller emits jobflow `Flow`s (item 3's `Flow` factories remain the typed
   building blocks the agent composes, **never bypassed**), exposed to LLM agents through a guarded
   **MCP tool-server** over the item-7 stdio JSON-RPC transport, with TUI-gated elicitation approval.
   It reuses the spine's explicit-gate posture (`allow_stub_execution`, `allow_restart_skew`) so
   agent output is always a **proposed typed `Flow`** validated by ADR-016/024 and **never executed
   unvalidated**. A generative `CandidateSource` (e.g. a diffusion structure generator) is pluggable;
   AI provenance (model / prompt / agent identity / acquisition / approval) folds into the item-5
   schema and the ADR-022 hash. This layer also fills the opening ADR-018 leaves — an LLM-diagnosis
   step *above* the custodian catalogue when no `ErrorHandler` matches.

4. **[ADR-024](adr-024-static-typed-workflow-dag-validation.md) — add the STATIC-VALIDATION layer.** It extends
   ADR-016's "drift is a build failure, not a runtime error" principle inward from the wire to the
   scientific DAG: `crystalmath validate` type-checks every ADR-013 `CodeHandoff` edge **offline,
   before any submission** (artifact-type match, calculator/code compatibility, static
   resource/parallelization constraints), demoting ADR-013's runtime `RestartValidation` from sole
   guardian to **backstop**, and re-validating dynamically-materialized ML/agent sub-DAGs when they
   are spawned via jobflow `Response.detour`.

### Resulting coherent stack

> agentic planner (ADR-023) → static-validated jobflow DAG (ADR-024 over ADR-011) →
> content-addressed cache-gated `CalculatorStage`s (ADR-022 over ADR-021) → typed `TaskDocument`s
> with full ML + AI + env provenance (ADR-009 revised) → one store and one CAS (ADR-010 revised).

In this stack DFT, MLIP, and LLM steps are **uniform citizens**, and determinism is an **enforced
execution contract on the default path**, not a test-side aspiration. The four ADRs are orthogonal:
021 owns *what computes*, 022 owns *whether it re-computes*, 023 owns *who composes the DAG*, and 024
owns *whether the DAG is well-typed before it runs*.

### Amendment references

- E. Batatia et al., "A foundation model for atomistic materials chemistry (MACE-MP-0)," *J. Chem.
  Phys.* (2024), arXiv:2401.00096. — Canonical foundation-MLIP; DFT as one stage; source of Δ-ML.
- B. Deng et al., "CHGNet as a pretrained universal neural network potential for charge-informed
  atomistic modelling," *Nat. Mach. Intell.* 5, 1031 (2023), DOI:10.1038/s42256-023-00716-3.
- J. Riebesell et al., "Matbench Discovery," *Nat. Mach. Intell.* (2025). — uMLIPs as DFT
  pre-filters (F1 0.57–0.83), grounding the surrogate-screen mode of ADR-021.
- A. M. Ganose et al., "Atomate2: modular workflows for materials science," *Digital Discovery*
  (2025), DOI:10.1039/d5dd00019j. — MLIPs run via one `AseMaker`; precedent for `CalculatorStage`.
- S. P. Huber et al., "AiiDA 1.0," *Scientific Data* 7, 300 (2020),
  DOI:10.1038/s41597-020-00638-4, arXiv:2003.12476. — BLAKE2b node-hash caching with clone-on-hit;
  the content-addressed execution contract ADR-022 adopts as default.
- S. P. Huber, "Automated reproducible workflows and data provenance with AiiDA," *Nat. Rev. Phys.*
  4, 367 (2022), DOI:10.1038/s42254-022-00463-1. — AiiDA 2.x disk-objectstore and server-free
  `sqlite_dos` profiles, refuting ADR-010's PostgreSQL premise (ADR-022 reference impl).
- P. Di Tommaso et al., "Nextflow enables reproducible computational workflows," *Nat. Biotechnol.*
  35, 316 (2017), DOI:10.1038/nbt.3820. — Task-hash cache-and-resume as mainstream non-AiiDA prior
  art for ADR-022.
- S. Shanmugavelu et al., "Impacts of floating-point non-associativity on reproducibility for HPC
  and deep learning applications," *SC24-W* (2024), DOI:10.1109/SCW63240.2024.00028,
  arXiv:2408.05148. — Bitwise reproducibility is unachievable under parallel FP non-associativity;
  the empirical basis for ADR-022's per-property tolerances over byte-equality.
- I. Laguna, "Varity: Quantifying Floating-Point Variations in HPC Systems Through Randomized
  Testing," *IEEE IPDPS* (2020), DOI:10.1109/IPDPS47924.2020.00070. — Identical inputs diverge
  across compilers and CPU/GPU; motivates the env fingerprint on every TaskDocument.
- cwltool reference implementation, `static_checker` module / `--validate`:
  https://cwltool.readthedocs.io/en/latest/autoapi/cwltool/checker/index.html — Prior art for
  ADR-024: whole-document source→sink type checking before execution.
- C. Maydeu-Maymounkov, "Koji: Automating pipelines with mixed-semantics data sources,"
  arXiv:1901.01908 (2019). — Recursive causal hashing over inputs+transformation, computable before
  the resource exists; grounds ADR-022's closure hash including parent hashes.
- C. Zhao et al. (MatterGen), "A generative model for inorganic materials design," *Nature* 639, 624
  (2025), arXiv:2312.03687. — Reference diffusion generator; the pluggable `CandidateSource` of
  ADR-023.
- S. Soiland-Reyes, S. Leo et al., "Recording provenance of workflow runs with RO-Crate," *PLOS ONE*
  19(9), e0309210 (2024), DOI:10.1371/journal.pone.0309210, arXiv:2312.07852. — W3C-PROV-aligned
  portable provenance bundle that can carry ADR-024's validation result and ADR-023's AI provenance.

## References

- Alex M. Ganose et al., "Atomate2: modular workflows for materials science," *Digital Discovery* (2025),
  DOI:10.1039/d5dd00019j.
- Andrew S. Rosen et al., "Jobflow: Computational Workflows Made Simple," *Journal of Open Source Software*
  9(93), 5995 (2024), DOI:10.21105/joss.05995.
- Giovanni Pizzi et al., "AiiDA: Automated Interactive Infrastructure and Database for Computational
  Science," *Comput. Mater. Sci.* 111, 218 (2016), arXiv:1504.01163, DOI:10.1016/j.commatsci.2015.09.013.
- Sebastiaan P. Huber et al., "AiiDA 1.0, a scalable computational infrastructure for automated
  reproducible workflows and data provenance," *Scientific Data* 7, 300 (2020),
  DOI:10.1038/s41597-020-00638-4, arXiv:2003.12476.
- Shyue Ping Ong et al., "Python Materials Genomics (pymatgen): A robust, open-source python library for
  materials analysis," *Comput. Mater. Sci.* 68, 314 (2013), DOI:10.1016/j.commatsci.2012.10.028.
- Ask Hjorth Larsen et al., "The atomic simulation environment — a Python library for working with atoms,"
  *J. Phys.: Condens. Matter* 29, 273002 (2017), DOI:10.1088/1361-648X/aa680e.
- Casper W. Andersen et al., "OPTIMADE, an API for exchanging materials data," *Scientific Data* 8, 217
  (2021), DOI:10.1038/s41597-021-00974-z, arXiv:2103.02068.
- Mihael Hategan-Marandiuc et al., "PSI/J: A Portable Interface for Submitting, Monitoring, and Managing
  Jobs," *IEEE 19th Int. Conf. on e-Science* (2023), arXiv:2307.07895, DOI:10.1109/e-Science58273.2023.10254912.
- Yadu Babuji et al., "Parsl: Pervasive Parallel Programming in Python," *HPDC '19* (2019), arXiv:1905.02158,
  DOI:10.1145/3307681.3325400.
- Carl S. Adorf et al., "Simple data management with the signac framework," *Comput. Mater. Sci.* 146, 220
  (2018), arXiv:1611.03543, DOI:10.1016/j.commatsci.2018.01.035.
- Model Context Protocol Specification, version 2025-06-18 ("inspired by the Language Server Protocol"):
  https://modelcontextprotocol.io/specification/2025-06-18.
- jobflow-remote documentation (outbound-SSH daemon; DB not reachable from HPC center), Matgenix:
  https://matgenix.github.io/jobflow-remote/.
- jobflow `JobStore` over maggma `Store`s: https://materialsproject.github.io/jobflow/stores.html.
- emmet-core pydantic materials documents: https://materialsproject.github.io/emmet/.
- [ADR-003](adr-003-ipc-boundary-design.md) (IPC boundary), [ADR-005](adr-005-unified-configuration.md)
  (unified configuration — superseded by [ADR-015](adr-015-unified-config-pydantic-settings.md)),
  [ADR-006](adr-006-unify-on-rust-tui.md) (unify on Rust TUI).
