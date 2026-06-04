# ADR-010: A Single Canonical Result Store — jobflow JobStore over maggma

**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** none
**Depends on:** [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md) (the emmet-style `TaskDocument` schema this store persists)
**Refined by:** [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) (jobflow Flows are what write documents into this store)

## Context

CrystalMath today has **no single canonical place a job result lives**. The same calculation is
persisted three different ways, with a Pydantic façade on top, and the result payload itself is an
untyped JSON blob. This is the storage equivalent of the runner sprawl ADR-011 collapses, and it is
the seventh entry in the friction catalog (Requirement **H3**: three-way storage split + SQLite
single-writer contention).

**The three overlapping stores.** `backends/__init__.py:220` `create_backend(...)` selects at runtime
across `{auto, sqlite, aiida, demo}`:

1. **A bespoke SQLite schema.** `_vendor/core/database.py:150` defines a hand-rolled `jobs` table —
   `final_energy REAL`, `key_results TEXT`, `status` constrained by a literal `CHECK(...)` list — plus
   `clusters` and `remote_jobs` tables grown by string-concatenated `ALTER TABLE` migrations
   (`MIGRATION_V1_TO_V2`, `_vendor/core/database.py:175-181`). This 1,452-LOC module is itself part of
   the `_vendor/` fork-copy of the deprecated Textual TUI, so the "single source of truth" Python core
   depends on a frozen copy of a deprecated package and must round-trip every schema fix through
   `tui/` and re-vendor it.
2. **AiiDA's provenance graph** (`backends/aiida.py`), a completely separate PostgreSQL-backed store.
3. **A jobflow `JobStore`**, bridged back into the SQLite database by
   `integrations/jobflow_store.py` — **984 LOC** whose own module docstring draws the bridge
   (`MemoryStore <-> SQLiteBackend`, `jobflow_store.py:12-19`), carries its *own* `JobRecord`
   (`jobflow_store.py:126`) plus `to_jobflow_document`/`from_jobflow_document` translators
   (`:156`, `:173`), and runs bidirectional `sync_to_crystalmath`/`sync_from_crystalmath` with a
   `SyncStats` accounting type (`:215`, `:230-260`). `SQLiteJobStore.remove_docs()` is still
   `NotImplementedError` (`jobflow_store.py:582`).

So a single job can simultaneously be a Pydantic `JobStatus` (`models.py:185`), a SQLite row, an
AiiDA node, **and** a jobflow document, with 984 lines of bridge translating between two of them and
no fewer than six independent job-state enums across the codebase (`models.py:23`,
`_vendor/runners/base.py:32`, `_vendor/runners/slurm_runner.py:36`, `quacc/store.py:20`,
`quacc/runner.py:57`).

**The data model is also untyped where it matters.** `models.py:217` `JobDetails` exposes a handful
of typed convenience fields (`final_energy`, `bandgap_ev`, `convergence_met`) but the actual result
payload is `key_results: dict[str, Any] | None` (`models.py:249`) — an unvalidated, unversioned,
self-undocumenting blob mirrored straight into the SQLite `key_results TEXT` column. There is no
structure-aware model, no schema validation on write, and no provenance edges (which job produced
this, from which inputs).

**Ecosystem state of the art.** The Materials Project stack separated these concerns years ago.
jobflow's **`JobStore`** is a thin façade over **maggma** `Store` backends, keyed by `(uuid, index)`,
storing each job's `output` document plus metadata, with large blobs offloaded to `additional_stores`
(jobflow stores docs; maggma concepts). maggma's defining property is that *the same workflow code
targets a serverless local store or a MongoDB or S3 without changing the workflow* — `MemoryStore`
and `JSONStore`/`MontyStore` need no server; `MongoStore` + `S3Store`/`GridFS` scale to shared
deployments. atomate2 workflows write to this store natively (Rosen et al. 2024; Ganose et al. 2025).
Because ADR-011 already commits CrystalMath's execution model to jobflow Flows, the result store is no
longer an open question — **jobflow Flows already produce documents that want a `JobStore`**, and we
are currently maintaining 984 lines to fight that rather than use it.

With zero users, there is no migration debt protecting the bespoke schema. This is the moment to adopt
the ecosystem store wholesale.

## Decision

**Make jobflow's `JobStore`-over-maggma the one canonical result store for CrystalMath. Default to a
server-free local store for the laptop/TUI case, swap to a server-backed store by config for
shared/HPC, and delete the bespoke SQLite jobs/clusters/remote_jobs schema, `_vendor/core/database.py`,
and the 984-LOC `jobflow_store.py` bridge.**

### 1. One store seam: jobflow `JobStore`

`crystalmath` constructs exactly one `jobflow.JobStore` and threads it through the execution layer
(ADR-011). Every Flow's output is written to it; every TUI/CLI read goes through it. There is no
second persistence path, no `create_backend(...)` fan-out over `{sqlite, demo}`, and no Pydantic-row /
SQLite-row / jobflow-doc translation layer. The store is resolved once, by the Python core, from
config (ADR-015 / pydantic-settings).

### 2. Default backend: serverless local (`MontyStore` / `JSONStore`)

For the default laptop-first TUI deployment the docstore is a **`MontyStore`** (montydb — a
file-backed MongoDB-API store, no server) for the per-job documents, with a `JSONStore` acceptable for
read-mostly/export cases. The `additional_store` for large blobs (DOS grids, band data, raw output
text) is a local `FileStore`/`GridFSStore`-equivalent under the config-resolved data dir. This needs
**no MongoDB, no PostgreSQL, no RabbitMQ** — it replaces the single-file `.crystal_tui.db` with a
single maggma store the TUI opens directly, and it eliminates the SQLite single-writer contention
called out in **H3** / PITFALLS #3 because concurrent writers go through maggma's store semantics, not
a lock-prone single SQLite file.

### 3. Swappable backend: `MongoStore` + `S3Store`/`GridFS` by config

A `[store]` section in the unified config (ADR-015) selects the backend:

```toml
[store]
kind = "local"        # default: MontyStore docstore + local blob store

# kind = "mongo"      # shared / HPC deployment
# uri = "mongodb://..."
# database = "crystalmath"
# [store.blobs] kind = "s3"  bucket = "..."   # or "gridfs"
```

The Python core maps this onto `JobStore(docs_store=..., additional_stores={...})`. Because maggma's
`Store` interface is uniform, *no workflow, handoff, or TUI code changes* when the backend changes —
this is exactly maggma's database-agnostic promise, and it is what kills the three-overlapping-stores
problem with a single config key.

### 4. Typed result documents replace `key_results: dict[str, Any]`

The store holds **emmet-style versioned Pydantic `TaskDocument`s** — one per code (`CrystalTaskDoc`,
`VaspTaskDoc`, `QeTaskDoc`, `YamboTaskDoc`), each with typed `energy`/`structure`/`forces`/`bandgap`/
`convergence` fields, validated on write. This deletes the untyped `key_results` blob
(`models.py:249`) and the parallel SQLite `key_results TEXT` column. Pydantic is already the core's
model layer (`models.py`), so this is idiomatic. `JobDetails` becomes a thin TUI projection *derived
from* the canonical `TaskDocument`, not a competing record.

Every document also carries **first-class lineage fields** so the default (non-AiiDA) path is still
reproducible: `input_hash`, `code` + `code_version`, `structure_uuid`, `parent_uuids` (the
inter-job edges), and content-addressed paths of raw inputs/outputs. This borrows AiiDA's
input/create-link concept as plain fields on the document. The multi-code handoff keystone
(CRYSTAL `.f9` / VASP `WAVECAR` → downstream, the VASP→YAMBO chain — Requirements **C1/C2**) is then a
typed edge between two `TaskDocument`s, with the restart-file validation **C2** mandates expressed as
a document-level check.

### 5. AiiDA stays an opt-in backend, not the default

AiiDA (`backends/aiida.py`) remains the heavyweight provenance backend behind the single
`ExecutionBackend` protocol (ADR-012), for users who need publication-grade immutable provenance and
Materials-Cloud sharing. When enabled, AiiDA owns the provenance DAG; results still round-trip into the
emmet-style `TaskDocument`s so the TUI is backend-agnostic. AiiDA's PostgreSQL/RabbitMQ tax is **never**
imposed on the laptop-first default.

### 6. Deletions

- **Delete** `_vendor/core/database.py` (1,452 LOC) and the `jobs`/`clusters`/`remote_jobs` SQLite
  schema with its `ALTER TABLE` migrations.
- **Delete** `integrations/jobflow_store.py` (984 LOC): `JobStoreBridge`, `SQLiteJobStore`,
  `CrystalMathJobStore`, `JobRecord`, `SyncStats`, and the bidirectional sync. With one store there is
  nothing to bridge.
- **Delete** `backends/sqlite.py` and the `{sqlite, demo}` arms of `create_backend(...)`
  (`backends/__init__.py:220`). The factory reduces to `{local (maggma), mongo (maggma), aiida}`.
- **Collapse** the six job-state enums (§Context) to the canonical jobflow/`JobState` pair.

## Alternatives Considered

**Keep the bespoke SQLite schema as canonical (status quo).** Rejected. It is a hand-rolled
single-writer store with string-concatenated migrations, embedded in the `_vendor/` fork-copy of a
deprecated package, with an untyped `key_results` blob and no provenance edges. It forces the 984-LOC
bridge to exist at all, and it cannot represent a jobflow Flow's output without translation. SQLite
single-writer contention under concurrent submission is a named pitfall (**H3** / PITFALLS #3). With
zero users there is no reason to preserve it.

**AiiDA's provenance store as the single canonical store.** Rejected as the *default*; kept as opt-in.
AiiDA is the gold standard for automatic, immutable, queryable provenance (Pizzi et al. 2016; Huber et
al. 2020), but it requires a PostgreSQL server (and historically RabbitMQ) and an "everything is an
AiiDA node" model that fights a laptop-first TUI manager — too heavy to be the *only* store. The
redesign captures provenance as first-class document fields (§4) so the lightweight path is still
reproducible, and offers AiiDA behind the same `ExecutionBackend` seam for users who need the full
graph.

**signac file-based data spaces.** Rejected. signac's serverless, JSON-statepoint-keyed workspaces map
naturally onto per-calculation work dirs and are laptop-friendly (Adorf et al. 2018), but its
provenance is implicit in directory state, its typing is weaker than emmet Pydantic docs, and — most
decisively — adopting it *alongside* jobflow would recreate the exact "multiple overlapping stores"
problem this ADR eliminates. Mine its directory-as-statepoint idea for the content-addressed blob
paths only; do not adopt it as a second store.

**A new, CrystalMath-specific store schema (e.g. SQLAlchemy + Alembic over Postgres).** Rejected. This
is reinvention. It would re-derive maggma's swappable-backend abstraction by hand, require us to
maintain migrations and a query layer, and still need a bridge to feed jobflow Flow outputs. jobflow
Flows already emit `JobStore` documents; building a parallel schema for them is precisely the cost the
field has already paid (jobflow stores docs; maggma concepts).

**MongoDB as the hard-required backend (the classic atomate2/atomate deployment).** Rejected as the
*default*. Requiring a running MongoDB for the laptop TUI case is the operational tax that makes the MP
stack feel heavy. maggma exists specifically so we don't have to: `MontyStore`/`JSONStore` give the
same `JobStore` API server-free, and `MongoStore` is a one-line config swap for shared deployments
(maggma concepts). We adopt the abstraction, not the server requirement.

## Consequences

### Positive
- **One store, one schema, one query path.** Deletes ~2,400 LOC of bespoke persistence
  (`_vendor/core/database.py` 1,452 + `jobflow_store.py` 984) and the entire three-way storage split.
- **Server-free by default** (`MontyStore`/`JSONStore`), removing SQLite single-writer contention
  (**H3** / PITFALLS #3) and the `.crystal_tui.db` lock model.
- **jobflow Flow outputs land natively** in their intended store; no translation, no `SyncStats`, no
  half-implemented `remove_docs()`.
- **Typed, validated, versioned results** (emmet-style `TaskDocument`s) replace the
  `key_results: dict[str, Any]` blob — the weakest part of the current data model.
- **Reproducible even without AiiDA**: lineage (`input_hash`, `parent_uuids`, content-addressed raw
  paths) is carried as first-class document fields; the multi-code handoff (**C1/C2**) becomes a typed
  edge with mandatory restart-file validation.
- **Scales by config**, not by code: `MongoStore` + `S3Store`/`GridFS` for shared/HPC with no workflow
  changes.

### Negative / Tradeoffs
- New dependency surface: `maggma` (and montydb for the default `MontyStore`) become core deps. These
  are already transitively in the jobflow/atomate2 stack ADR-011 adopts, so the marginal cost is small.
- We must author per-code `TaskDocument` schemas. emmet-core is VASP/MP-centric, so CRYSTAL23 / QE /
  YAMBO need new schemas — a real schema-maintenance burden, but one that replaces the *larger*
  maintenance burden of the bespoke SQLite layer and is the high-value standardization work the
  interoperability literature identifies (Steensen et al. 2025).
- maggma's query language is MongoDB-flavored; readers (TUI handlers, CLI) must use it instead of SQL.
  This is a net simplification (one query model) but a porting task.

### Migration impact
- **Schema fixes stop round-tripping through `tui/`**: deleting `_vendor/core/database.py` removes a
  load-bearing dependency on the deprecated package and advances the `_vendor/` / `tui/` removal
  (Requirements **G5/I5**).
- The IPC handlers that read jobs (`server/handlers/jobs.py`, the `jobs.*` namespace) re-point at the
  `JobStore` instead of `SQLiteBackend`; the wire schema seen by the Rust TUI is the `TaskDocument`
  projection, kept in serde-parity via JSON-Schema codegen (per the boundary ADRs).
- No user data migration is required (zero users); the bespoke schema and its rows are simply removed.

## References

- Jobflow `JobStore` documentation (façade over maggma Stores; `additional_stores` for large outputs).
  <https://materialsproject.github.io/jobflow/stores.html>
- maggma concepts — the `Store` abstraction (MongoStore / JSONStore / MontyStore / S3Store / GridFS)
  and database-agnostic query interface. <https://materialsproject.github.io/maggma/concepts/>
- Andrew S. Rosen et al., "Jobflow: Computational Workflows Made Simple," *Journal of Open Source
  Software* 9(93), 5995 (2024). DOI:10.21105/joss.05995
- Alex M. Ganose et al., "Atomate2: modular workflows for materials science," *Digital Discovery*
  (2025). DOI:10.1039/d5dd00019j
- Sebastiaan P. Huber et al., "AiiDA 1.0, a scalable computational infrastructure for automated
  reproducible workflows and data provenance," *Scientific Data* 7, 300 (2020).
  DOI:10.1038/s41597-020-00638-4, arXiv:2003.12476
- Giovanni Pizzi et al., "AiiDA: Automated Interactive Infrastructure and Database for Computational
  Science," *Comput. Mater. Sci.* 111, 218 (2016). DOI:10.1016/j.commatsci.2015.09.013, arXiv:1504.01163
- Carl S. Adorf et al., "Simple data management with the signac framework," *Comput. Mater. Sci.* 146,
  220 (2018). DOI:10.1016/j.commatsci.2018.01.035, arXiv:1611.03543
- S. K. Steensen et al., "The Interoperability Challenge in DFT Workflows Across Implementations,"
  arXiv:2511.11524 (2025).
- emmet (emmet-core pydantic materials documents — TaskDoc/MaterialsDoc) documentation.
  <https://materialsproject.github.io/emmet/>

## Codebase Evidence

- Three-way storage split selected at runtime: `backends/__init__.py:220` `create_backend(...)`.
- Bespoke schema + string-concat migrations: `_vendor/core/database.py:150`, `:175-181` (1,452 LOC).
- The bridge to delete: `integrations/jobflow_store.py` (984 LOC) — `JobStoreBridge` (`:230`),
  `SQLiteJobStore` (`:305`, `remove_docs` `NotImplementedError` `:582`), `CrystalMathJobStore` (`:590`),
  `JobRecord` (`:126`), `SyncStats` (`:215`).
- Untyped result payload: `models.py:249` `key_results: dict[str, Any] | None`; mirrored as
  `key_results TEXT` in `_vendor/core/database.py:150`.
- Six competing job-state enums: `models.py:23`, `_vendor/runners/base.py:32`,
  `_vendor/runners/slurm_runner.py:36`, `quacc/store.py:20`, `quacc/runner.py:57`.
