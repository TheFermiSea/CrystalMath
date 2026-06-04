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

CrystalMath is a multi-code DFT manager (CRYSTAL23, VASP, Quantum ESPRESSO, YAMBO, phonopy):
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
seam, or deleted. The target architecture has exactly one of each layer:

1. **One structure object** — pymatgen `Structure` / ASE `Atoms` (MSONable, round-trippable).
2. **One per-code I/O seam** — the existing `CodeDeckGenerator`/`InputDeck` vocabulary
   (`decks/__init__.py`, locked in `CONTEXT.md`), re-implemented as **thin adapters over ASE
   FileIO/Socket calculators and pymatgen `InputSet`s** rather than hand-rolled POSCAR/d12/pw.in
   writers. `vasp/generator.py`, `_vendor/core/codes/`, and `quacc/potcar.py` collapse into it.
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

### Migration impact
- Sequenced and trigger-gated (table above); steps 1–3 ship independently, 4–6 follow. Quality gates
  (the three CI lanes, synthetic-POTCAR fixtures, an extras matrix that exercises each `skipif` path) must
  stay green at each step. Issues tracked in `bd` (beads). No data migration is needed — there are zero
  users — so each store/transport swap is a cutover, not a dual-write.

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
