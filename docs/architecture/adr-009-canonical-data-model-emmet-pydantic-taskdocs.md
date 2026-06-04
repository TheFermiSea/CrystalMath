# ADR-009: Canonical Result Schema — emmet-style Versioned pydantic TaskDocuments with First-Class Provenance Fields

**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Depends on:** [ADR-008](adr-008-structure-and-deck-io-on-ase-pymatgen.md) (per-code I/O + parser seam that populates these documents)
**Refined by:** [ADR-010](adr-010-single-result-store-jobflow-maggma.md) (the maggma `JobStore` this schema is persisted into)
**Supersedes:** none

## Context

CrystalMath has no canonical record of a calculation's result. The same job is
represented three or four different ways depending on which code path touched it, and the
"result" itself is an untyped JSON blob. This is the storage analogue of the runner sprawl
that [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) collapses and the I/O sprawl
that [ADR-008](adr-008-structure-and-deck-io-on-ase-pymatgen.md) collapses — and it must be fixed
before either of those can claim a single source of truth.

**The result payload is untyped.** The Pydantic `JobDetails` model carries a handful of
typed fields (`final_energy`, `bandgap_ev`, `convergence_met`, `scf_cycles`) plus an
escape-hatch `key_results: dict[str, Any] | None` ("Full results dictionary",
`python/crystalmath/models.py:249`). Everything a downstream consumer actually needs —
the relaxed structure, force/stress tensors, per-code convergence details, DOS/band data —
ends up in that blob, unvalidated and unversioned. The bespoke SQLite schema mirrors this
exactly: a `jobs` table with a `final_energy REAL` column and a `key_results TEXT` column
(`python/crystalmath/_vendor/core/database.py:160-161`), grown by hand-rolled
`ALTER TABLE` migrations (`database.py:175-181`). There is no place to put a typed force
array, no schema version on the document, and no way to query "all jobs with bandgap > 2 eV"
without parsing JSON text out of a TEXT column.

**Six competing job-state/status types coexist**, none canonical (Friction Catalog §7):

- `models.py:23` `JobState(str, Enum)` and `models.py:185` `JobStatus(BaseModel)` — the API model.
- `_vendor/runners/base.py:32` `JobStatus(Enum)` — a *different* enum.
- `_vendor/runners/slurm_runner.py:36` `SLURMJobState(Enum)`.
- `quacc/runner.py:57` `JobState(str, Enum)` and `quacc/store.py:20` `JobStatus(str, Enum)`.

A single job can therefore be a Pydantic `JobStatus`, a SQLite row, an AiiDA node, and a
jobflow document at once, with `integrations/jobflow_store.py` (984 LOC) maintaining its own
third `JobRecord` dataclass (`jobflow_store.py:126`) and bidirectional sync between two of
them. Storage is split three ways, selected at runtime by `create_backend(...)` over
`{auto, sqlite, aiida, demo}` (`backends/__init__.py:220`): a bespoke SQLite schema, an
AiiDA provenance DB, and a maggma `JobStore`. **There is no canonical record** — only N
representations behind a Pydantic façade.

**No provenance in the default path.** AiiDA is the only path that records *what ran, with
which inputs, producing which outputs* as a traversable graph. The default (non-AiiDA)
SQLite path stores a `final_energy` float and a blob — it cannot answer "which input
produced this energy, and what was the lineage of the structure it relaxed?" That makes the
laptop-first default non-reproducible, which is unacceptable for a scientific tool even with
zero users.

### Ecosystem state of the art

The computational-materials ecosystem has converged on a clear separation that CrystalMath
conflates:

1. **Validated result documents.** The Materials Project / atomate2 stack stores results as
   versioned, pydantic-typed documents — emmet-core's `TaskDoc`/`MaterialsDoc`, built on an
   `EmmetBaseModel` carrying a `@version` and `builder_meta` — with typed fields for energy,
   structure, forces, bandgap, and convergence, validated on write (Ganose et al., *Atomate2*,
   Digital Discovery 2025; emmet docs). atomate2's `VaspInputGenerator` produces exactly these
   `TaskDocument` schemas, so heterogeneous multi-code workflows compose around one shape.

2. **Automatic provenance.** AiiDA's gold-standard contribution is an immutable directed-acyclic
   provenance graph: every Data/Calc/Workflow node and the **input / create / return / call
   links** between them, persisted with raw files in a content-addressed object store, giving
   full "retrace any result" reproducibility (Pizzi et al. 2016; Huber et al., Sci. Data 2020).
   The *concept* — input links, create links, content-addressed raw files — is portable even
   without adopting AiiDA's heavyweight ORM.

3. **One in-memory object & interchange model.** pymatgen `Structure`/`ComputedEntry`
   (MSONable, round-trippable JSON) is the de-facto object model; OPTIMADE v1.2 is the
   federated interchange schema (Andersen et al. 2021; Evans et al. 2024).

The lesson is that the schema is the hard, valuable part, and the ecosystem has already paid
for it. With zero users we should adopt the pattern wholesale rather than keep growing a
hand-rolled SQLite blob.

## Decision

**Define one versioned pydantic `TaskDocument` per code, validated on write, carrying typed
results plus first-class provenance fields. Make it the single canonical result record.
Delete the `key_results` blob and unify the six job-state types onto one enum.**

### 1. A versioned `TaskDocument` base, one subclass per code

Introduce `crystalmath.schemas` with an emmet-style base (mirroring emmet-core's
`EmmetBaseModel`) and one concrete document per supported code:

```python
# python/crystalmath/schemas/base.py
class TaskDocument(BaseModel):                 # the emmet-core pattern, our own base
    model_config = ConfigDict(extra="forbid")  # validate on write; reject unknown keys

    schema_version: str = "1"                  # bumped on breaking field changes
    code: DftCode                              # crystal | vasp | qe | yambo | phonopy
    state: JobState                            # the ONE canonical enum (see §3)

    # --- typed scientific results (no more key_results blob) ---
    structure: Structure | None = None         # pymatgen Structure (MSONable)
    energy_eV: float | None = None
    forces_eV_per_A: list[list[float]] | None = None
    stress_eV_per_A3: list[list[float]] | None = None
    bandgap_eV: float | None = Field(default=None, ge=0.0)
    convergence: ConvergenceDoc | None = None  # typed, not a bool + blob

    # --- first-class provenance (the AiiDA link concept as fields) ---
    provenance: ProvenanceDoc

class ProvenanceDoc(BaseModel):
    input_hash: str                            # content hash of the staged InputDeck
    code_name: str                             # e.g. "crystal23"
    code_version: str | None                   # parsed from output header
    structure_uuid: str                        # identity of the input structure
    parent_job_uuids: list[str] = []           # lineage edges (AiiDA "input" links)
    raw_paths: dict[str, str] = {}             # content-addressed raw input/output files
```

```python
# python/crystalmath/schemas/crystal.py
class CrystalTaskDoc(TaskDocument):
    code: Literal[DftCode.CRYSTAL] = DftCode.CRYSTAL
    scf_cycles: int | None = Field(default=None, ge=0)
    f9_path: str | None = None                 # CRYSTAL wavefunction for GUESSP restart
```

`VaspTaskDoc`, `QeTaskDoc`, `YamboTaskDoc`, and `PhonopyTaskDoc` follow the same pattern,
each adding only its code-specific fields (e.g. `VaspTaskDoc.wavecar_path`,
`VaspTaskDoc.nbands`; `YamboTaskDoc.gw_qp_corrections`). Where emmet-core's actual VASP
schema applies (it is VASP/MP-centric), `VaspTaskDoc` should reuse emmet-core types directly
rather than re-deriving them; for CRYSTAL/QE/YAMBO we adopt emmet's *pattern* with our own
fields, since those codes are not first-class in emmet.

### 2. Each code's output parser populates its TaskDoc; the blob is deleted

Per [ADR-008](adr-008-structure-and-deck-io-on-ase-pymatgen.md), each code already has a parser seam
(ASE/pymatgen output readers behind the `decks`/IO adapter). That parser's contract becomes:
`parse(work_dir) -> <Code>TaskDoc`. The model is **validated on write** (`extra="forbid"`
plus pydantic field validation), so a parser that drops a field or emits the wrong type fails
loudly instead of silently smuggling data into a blob. `JobDetails.key_results`
(`models.py:249`) and the SQLite `key_results TEXT` column (`database.py:161`) are **removed**;
`JobDetails` becomes a thin projection over the canonical `TaskDocument` for the TUI's Results
view, not a parallel store.

### 3. One job-state enum

Promote `models.py:23` `JobState(str, Enum)` to *the* state type and delete the five
competitors (`_vendor/runners/base.py:32`, `_vendor/runners/slurm_runner.py:36`,
`quacc/runner.py:57`, `quacc/store.py:20`, the `JobStatus` variants). Scheduler-specific
states (SLURM `PD`/`R`/`CG`/…) map into `JobState` at the adapter edge using the existing
`map_to_job_state` helper (`models.py:58`). The Rust side keeps its single serde `JobState`
in parity, as today.

### 4. Provenance as first-class data, even without AiiDA

Every `TaskDocument` carries `ProvenanceDoc` (§1). This borrows AiiDA's **input/create-link
concept as document fields** rather than its ORM:

- `input_hash` — a content hash over the staged `InputDeck.files` (ADR-008), so identical
  inputs are detectable and a result is bound to the exact input that produced it.
- `parent_job_uuids` — the lineage edges; an SCF → bands chain records the SCF job's uuid,
  giving a traversable DAG without a graph database.
- `raw_paths` — **content-addressed** paths (hash-named) to the raw input/output files in an
  object store, mirroring AiiDA's disk-objectstore so raw provenance survives even when the
  document is migrated between stores.

The multi-code handoff contract (the VASP→YAMBO keystone, CRYSTAL `.f9`/VASP `WAVECAR`
passing) is expressed as **typed edges between TaskDocuments**: the consumer's
`parent_job_uuids` references the producer, and the restart artifact is a typed field
(`CrystalTaskDoc.f9_path`, `VaspTaskDoc.wavecar_path`) with mandatory restart-file validation
(checksum/timestamp, per the stale-WAVECAR pitfall) before it is consumed. This makes the
default, non-AiiDA path reproducible.

### 5. Storage seam and the AiiDA relationship

Persistence is owned by [ADR-010](adr-010-single-result-store-jobflow-maggma.md) (jobflow's
`JobStore` over maggma by default; AiiDA opt-in). This ADR is the **schema**, not the store:
the `TaskDocument` is MSONable-serializable and lands as the job `output` document in whatever
maggma store ADR-010 selects (local `JSONStore`/`MontyStore` by default; `MongoStore` +
`S3Store`/`GridFS` by config). When the **AiiDA backend is enabled, AiiDA owns the provenance
DAG and raw-file store**, and results still **round-trip into these TaskDocuments** for the
TUI — so the TUI is backend-agnostic and the schema is the contract both backends honor. The
bespoke SQLite `jobs`/`key_results` schema and the 984-LOC `jobflow_store.py` `JobRecord`
bridge are deleted as part of the ADR-010 storage consolidation.

## Alternatives Considered

**Keep the untyped `key_results` blob (status quo).** Zero migration cost. Rejected: it is
the single weakest part of the data model — unvalidated, unversioned, unqueryable, and the
root cause of the three-way storage split (Friction Catalog §7). Scientific software is
already chronically under-tested (Burrell et al. 2018); an untyped result payload guarantees
silent drift between what a parser writes and what a consumer expects.

**Adopt AiiDA's ORM as the canonical result/provenance model.** AiiDA gives best-in-class
*automatic, immutable, queryable* provenance — the only option that records the full DAG as
a traversable graph (Pizzi et al. 2016; Huber et al. 2020). Rejected as the *default*: it
ties the result schema to the AiiDA ORM rather than portable pydantic docs, and historically
demands PostgreSQL (+ RabbitMQ for the daemon) — too heavy a tax for a laptop-first TUI with
zero users. We keep AiiDA as the opt-in heavyweight backend (ADR-012) and **borrow its
input/create-link concept as document fields** so the lightweight default is still
reproducible.

**Use emmet-core's actual schemas unchanged.** emmet-core's `TaskDoc`/`MaterialsDoc` are
mature, versioned, and battle-tested (emmet docs; Ganose et al. 2025). Rejected as a blanket
solution because they are **VASP/MP-centric** — CRYSTAL23, QE, and YAMBO have no emmet schema.
We adopt emmet's *pattern* (versioned pydantic TaskDoc per code) and reuse emmet-core types
directly where they apply (VASP), defining our own subclasses elsewhere. This is idiomatic:
pydantic is already CrystalMath's model layer (`models.py`).

**signac (file-based, schema-free data spaces).** Serverless, laptop-friendly, maps onto
per-calculation work dirs (Adorf et al. 2018). Rejected: provenance is implicit in directory
state, typing/validation is weak versus emmet pydantic docs, and adopting it alongside the
ADR-010 jobflow store would re-create the very "multiple overlapping stores" problem this ADR
and ADR-010 exist to eliminate. We mine only its directory-as-statepoint idea (reflected in
`raw_paths`).

**A hand-rolled CrystalMath schema (extend the SQLite table with typed columns).** Cheapest
near-term. Rejected on principle: it continues "invent rather than adopt," and the
field has already paid for the typed-document pattern. A bespoke schema also forfeits free
OPTIMADE export and MSONable round-tripping that pydantic-over-pymatgen gives us.

## Consequences

### Positive
- **One canonical result record.** The `key_results` blob, the bespoke SQLite result columns,
  and the parallel `JobRecord` dataclass collapse into one versioned, validated `TaskDocument`
  per code.
- **Validated on write.** `extra="forbid"` + typed fields turn parser/consumer drift into a
  loud failure in CI instead of silent wrong-data — directly fixing the weakest seam in
  `models.py`.
- **Reproducible by default.** First-class `ProvenanceDoc` (input hash, code+version, structure
  uuid, parent-job uuids, content-addressed raw paths) makes the non-AiiDA path traceable —
  no AiiDA tax required.
- **Backend-agnostic TUI.** Both the default maggma store and the opt-in AiiDA backend round-trip
  the same documents, so the Rust TUI reads one shape regardless of backend.
- **Free interchange.** TaskDocuments serialize via MSONable/pymatgen, enabling OPTIMADE export
  and clean handoff between codes.
- **One state enum** kills the six-way `JobState`/`JobStatus` confusion.

### Negative / Tradeoffs
- **Schema-maintenance burden.** CRYSTAL/QE/YAMBO need bespoke TaskDoc subclasses and parsers,
  and `schema_version` must be bumped (with a migration) on breaking field changes.
- **Migration of every parser.** Each code's output parser must be rewritten to populate a
  typed document instead of stuffing a dict; tolerant fields (`| None`) are needed during
  rollout.
- **Stricter writes can surface latent bugs.** `extra="forbid"` will reject payloads that the
  blob silently accepted — intended, but it means more up-front parser work.

### Migration impact
1. Add `crystalmath.schemas` (`base.py` + one module per code); reuse emmet-core for VASP.
2. Rewrite each code's parser to `parse(work_dir) -> <Code>TaskDoc`; populate `ProvenanceDoc`
   from the staged `InputDeck` hash + parsed code version + structure uuid + parent uuids.
3. Make `JobDetails` a projection over `TaskDocument`; **delete** `JobDetails.key_results`
   (`models.py:249`) and the SQLite `key_results`/`final_energy` columns
   (`database.py:160-161`) as part of the ADR-010 storage cutover.
4. Delete the five non-canonical state enums; route all states through `map_to_job_state`.
5. Encode the VASP→YAMBO / SCF→bands handoff as `parent_job_uuids` edges + typed restart-file
   fields with checksum validation.
6. Persist documents into the ADR-010 maggma store; ensure the AiiDA backend round-trips into
   the same documents.

## References

- Ganose, A. M. et al., "Atomate2: modular workflows for materials science," *Digital
  Discovery* (2025), DOI:10.1039/d5dd00019j. *(InputGenerator → emmet TaskDocument pattern.)*
- emmet-core pydantic materials documents (`TaskDoc`/`MaterialsDoc`/`EmmetBaseModel`),
  Materials Project, https://materialsproject.github.io/emmet/
- Huber, S. P. et al., "AiiDA 1.0, a scalable computational infrastructure for automated
  reproducible workflows and data provenance," *Scientific Data* 7, 300 (2020),
  DOI:10.1038/s41597-020-00638-4, arXiv:2003.12476. *(input/create/return/call link concept,
  borrowed as document fields; disk-objectstore content addressing.)*
- Pizzi, G. et al., "AiiDA: Automated Interactive Infrastructure and Database for
  Computational Science," *Comput. Mater. Sci.* 111, 218 (2016), arXiv:1504.01163,
  DOI:10.1016/j.commatsci.2015.09.013.
- Ong, S. P. et al., "Python Materials Genomics (pymatgen)," *Comput. Mater. Sci.* 68, 314
  (2013), DOI:10.1016/j.commatsci.2012.10.028. *(MSONable Structure/ComputedEntry object model.)*
- Andersen, C. W. et al., "OPTIMADE, an API for exchanging materials data," *Scientific Data*
  8, 217 (2021), DOI:10.1038/s41597-021-00974-z, arXiv:2103.02068.
- Evans, M. L. et al., "Developments and applications of the OPTIMADE API," *Digital
  Discovery* (2024), DOI:10.1039/D4DD00039K, arXiv:2402.00572.
- Adorf, C. S. et al., "Simple data management with the signac framework," *Comput. Mater.
  Sci.* 146, 220 (2018), DOI:10.1016/j.commatsci.2018.01.035, arXiv:1611.03543.
- jobflow `JobStore` / maggma `Store` documentation,
  https://materialsproject.github.io/jobflow/stores.html and
  https://materialsproject.github.io/maggma/concepts/
- Friction Catalog §7 ("Three-way storage split with no canonical job record"): six
  job-state/status types and the `key_results` blob — evidence in `python/crystalmath/models.py`,
  `python/crystalmath/_vendor/core/database.py`, `python/crystalmath/integrations/jobflow_store.py`.
