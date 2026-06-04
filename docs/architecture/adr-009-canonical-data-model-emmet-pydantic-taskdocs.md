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
                                               # (bumped to "2" by the 2026-06-03 amendment below)
    code: CodeClass                            # crystal | vasp | qe | yambo | phonopy
                                               # | mlip (open enum; see Amendment / ADR-021)
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
    raw_paths: dict[str, CasRef] = {}          # typed content-addressed references (ADR-022 CAS;
                                               # was advisory dict[str,str] — see Amendment below)
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
- `raw_paths` — **content-addressed** references to the raw input/output files in an
  object store, mirroring AiiDA's disk-objectstore so raw provenance survives even when the
  document is migrated between stores. *(Amended 2026-06-03: these are now typed `CasRef`
  values backed by a real disk-objectstore CAS per [ADR-022](adr-022-content-addressed-execution-cache-replay.md),
  not advisory `dict[str,str]` strings — see Amendment below.)*

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
- **Provenance is now sufficient for the ML/agentic/determinism layers.** Per the 2026-06-03
  amendment below, `ProvenanceDoc` carries ML, AI, and environment-fingerprint provenance, so
  ADR-021/022/023 have a canonical place to persist what they produce and ADR-022's content
  hash is computable. This bumps `schema_version` to `"2"`.

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

## Amendment (2026-06-03): SOTA alignment

This amendment **preserves the original decision** — one versioned pydantic `TaskDocument` per
code, validated on write, with first-class provenance — and **extends** it so the TaskDocument can
serve as the canonical record for the ML, agentic, and determinism layers introduced by the new
ADR set ([ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md),
[ADR-022](adr-022-content-addressed-execution-cache-replay.md),
[ADR-023](adr-023-agentic-control-plane-mcp-ai-provenance.md),
[ADR-024](adr-024-static-typed-workflow-dag-validation.md);
later refined by [ADR-025](adr-025-campaign-acquisition-strategy.md),
[ADR-026](adr-026-trustworthy-mlip-evaluation-applicability-domain.md),
[ADR-027](adr-027-model-dataset-registry-lineage.md) — see Amendment 2). The original ADR is the canonical
*record*, but as written it lacked every field those layers must persist: model-checkpoint
identity (for ADR-021/022 caching), uncertainty/acquisition (for active learning), AI provenance
(for ADR-023), and an environment fingerprint (for ADR-020/022 replay comparability). Without
these the new ADRs have nowhere to persist their provenance and the ADR-022 content hash cannot be
computed. This is a **breaking, additive schema change: `schema_version` is bumped `"1"` → `"2"`.**

### A. Open the closed code enum (was `DftCode`, 009:97 → `CodeClass`)

The fixed `DftCode = crystal | vasp | qe | yambo | phonopy` enum is **renamed to `CodeClass` and
opened** to admit MLIP / foundation-model calculators as first-class peers of DFT, per
[ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md). DFT loses its privileged center:
an MLIP run is a `CalculatorStage` peer of a DFT stage (ADR-021), and POTCAR/pseudopotential
validation (ADR-008/013) becomes a **DFT-only** concern rather than a property of every document.
`DftCode` is retained as a narrowed alias for the DFT subset where POTCAR/restart logic legitimately
applies. New members (e.g. `mlip`) are added without breaking the closed-enum guarantee for the DFT
subset.

### B. New `MlipTaskDoc` subclass

Add an `MlipTaskDoc(TaskDocument)` subclass alongside `CrystalTaskDoc`/`VaspTaskDoc`/etc., following
the identical §1 pattern. An MLIP/foundation-model run emits **zero files** and returns
energy/forces/stress as a pure function of (statepoint, checkpoint, settings, library versions),
so `MlipTaskDoc` carries the typed scientific results already on the base plus the ML provenance in
§C. It is the document a `MlipCalculatorStage` (a thin wrapper over an ASE `Calculator` keyed by a
content-addressed checkpoint, per ADR-021) produces.

### C. Extend `ProvenanceDoc` (009:111-118) with ML, AI, and environment provenance

`ProvenanceDoc` gains three new typed sub-structures. These are the fields ADR-022's canonical
content hash is computed over, and the fields ADR-023's audit trail requires.

```python
class MlProvenance(BaseModel):                  # populated for MlipTaskDoc (ADR-021)
    model: ModelIdentifier                      # the ONE unified model identity (ADR-027); see note below.
                                                # Weights live ONCE in the ADR-022 CAS (model.weights_cas_key);
                                                # identity is model.immutable_revision / registry digest, NOT the
                                                # multi-GB weights. (Amendment 2 replaces the contradictory
                                                # model_uuid/model_checkpoint_hash/model_version/registry_digest quad.)
    training_set_lineage: list[DatasetRef] = []  # ADR-027 dataset_id Merkle-manifest refs (navigable, not str)
    fidelity_lineage: list[DatasetRef] = []      # Δ-ML / multi-fidelity ancestry as ADR-027 navigable refs
    uncertainty: UncertaintyEstimate | None = None  # ADR-026 estimate (method-tagged + calibration); see note
    uncertainty_method: str | None = None       # legacy tag; trust semantics now decided in ADR-025/026 (see note)
    acquisition_function: str | None = None      # active-learning acquisition that selected this statepoint (ADR-025)
    fine_tune_parent: ModelRef | None = None     # ADR-027 parent-model DAG edge (navigable ref, not uuid/hash str)

class AiProvenance(BaseModel):                   # populated when an LLM/agent produced/modified an input (ADR-023)
    model: str | None = None                     # LLM/agent model identity + version
    prompt: str | None = None                    # prompt (or its content hash) that produced the artifact
    tool_call: str | None = None                 # the MCP tool verb invoked (ADR-023 guarded tool-server)
    agent_identity: str | None = None            # which agent/campaign controller acted
    human_approval: str | None = None            # TUI-gated elicitation approval record (who/when)

class EnvironmentFingerprint(BaseModel):         # recorded on EVERY document (ADR-020/022 replay comparability)
    executable_hash: str | None = None           # hash of the code/binary actually run
    pseudopotential_hash: str | None = None      # POTCAR/pseudopotential/basis hash (DFT-only)
    mpi_version: str | None = None
    blas_version: str | None = None
    lapack_version: str | None = None
    torch_version: str | None = None             # for MLIP/GPU inference stages
    cuda_version: str | None = None
    thread_count: int | None = None              # OMP_NUM_THREADS
    rank_count: int | None = None                # MPI ranks
    compiler: str | None = None                  # compiler + flags (FP non-associativity sources)
    compiler_flags: str | None = None

class ProvenanceDoc(BaseModel):
    input_hash: str
    code_name: str
    code_version: str | None
    structure_uuid: str
    parent_job_uuids: list[str] = []
    raw_paths: dict[str, CasRef] = {}            # see §D
    # --- new (schema_version "2") ---
    ml: MlProvenance | None = None               # ADR-021
    ai: AiProvenance | None = None               # ADR-023
    env: EnvironmentFingerprint | None = None    # ADR-020 / ADR-022
```

Rationale for each group:
- **ML provenance** gives the active-learning loop (ADR-021) and the cache (ADR-022) what they need:
  the model **identity** (its `immutable_revision` / registry digest, per the unified
  `ModelIdentifier` of Amendment 2 / ADR-027) is a first-class ADR-022 cache key — a model-revision
  bump must invalidate dependent surrogates — and `uncertainty`/`acquisition_function` let
  uncertainty-gated escalation and acquisition-driven selection persist their decisions.
  `uncertainty` is **always method-tagged** because an ensemble σ and a GP variance are not
  comparable. Per ADR-022, the registry **digest** (HF repo + revision) is the cache key, never the
  multi-GB weights — which live once in the ADR-022 CAS under `model.weights_cas_key`.
- **AI provenance** makes every LLM/agent-produced or -modified input auditable (ADR-023) and folds
  into the ADR-022 execution hash. Because closed-model versions drift, agent steps are **not
  bitwise-cacheable**: agent nodes are un-cached, but their deterministic child stages are cached.
- **Environment fingerprint** is the field ADR-020's replay contract and ADR-022's hash both
  require. Floating-point non-associativity (MPI rank / OMP thread counts, GPU atomics, BLAS/LAPACK
  vendor, compiler flags, FMA contraction) makes bitwise reproducibility unachievable across
  heterogeneous hardware, so two runs are only comparable when their fingerprints are known. GPU
  MLIP inference is likewise not bitwise-reproducible, hence `torch_version`/`cuda_version` are
  captured and the ADR-022 reuse key is (statepoint + checkpoint + tolerance-class).

### D. Re-type `raw_paths` from advisory `dict[str,str]` to typed CAS references (ADR-022)

`raw_paths` (009:117, 164-166) was an **advisory** `dict[str, str]` of "content-addressed
(hash-named)" paths with no decided algorithm, no store, and no dedup contract. It is re-typed to
`dict[str, CasRef]`, where `CasRef` is a **typed reference into the real content-addressed store**
decided by [ADR-022](adr-022-content-addressed-execution-cache-replay.md) (a
disk-objectstore CAS with a decided hash algorithm and dedup contract). This is what makes ADR-013's
per-handoff checksum a lookup into a global CAS rather than a one-off comparison, and what gives
ADR-021's model checkpoints a place to live as content-addressed artifacts. MSONable round-tripping
(009:149) and the maggma `additional_stores` model (ADR-010) are preserved.

### Amendment 2 (2026-06-03): consensus-review fixes

A two-reviewer consensus pass surfaced a latent **silent-wrong-cache** contradiction in the §C
`MlProvenance` block and a set of inert lineage strings. This amendment makes **surgical
clarifications plus one re-type inside the existing `schema_version "2"`** — there is **no further
version bump** — and wires §C into the three new policy ADRs added this round:
[ADR-025](adr-025-campaign-acquisition-strategy.md) (Campaign & Acquisition Strategy — the pluggable
scientific brain: typed `AcquisitionStrategy` + `CampaignStrategy` with budget/convergence/stopping
and DFT-budget control),
[ADR-026](adr-026-trustworthy-mlip-evaluation-applicability-domain.md) (Trustworthy MLIP Evaluation &
Applicability Domain — measured-not-asserted surrogate trust: benchmark harness, calibrated
uncertainty, OOD/applicability-domain gate, escalation thresholds), and
[ADR-027](adr-027-model-dataset-registry-lineage.md) (Model & Dataset Registry + Lineage — navigable
registries over the ADR-022 CAS; the single unified `ModelIdentifier`).

1. **Unify model identity on `ModelIdentifier` (ADR-027); kill the weights-vs-digest contradiction.**
   The original §C carried a contradictory quad —
   `model_uuid` / `model_checkpoint_hash` / `model_version` / `registry_digest` — whose line-315
   comment ("content hash of the weights/checkpoint") **directly contradicted**
   [ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md):115 and
   [ADR-022](adr-022-content-addressed-execution-cache-replay.md) §F: hashing multi-GB weights and
   hashing a registry digest are **different identities**, and using one where the other is expected
   is a silent-wrong-cache bug (a checkpoint that round-trips to the same bytes but a different
   registry revision, or vice versa, mis-hits the cache). The quad is **replaced by a single
   `model: ModelIdentifier`** field carrying
   `{registry_uri, model_id, immutable_revision, weights_cas_key, code_package_version}` per ADR-027.
   The decided semantics: **weights live exactly once in the ADR-022 CAS** under `weights_cas_key`;
   **identity for caching is the `immutable_revision` / registry digest**, *not* the GB-scale weights.
   This is the same principle already applied to `raw_paths` in §D.

2. **Re-type the inert lineage strings into ADR-027 navigable registry references.**
   `training_set_lineage` (009:318) and `fidelity_lineage` (009:319) were `list[str]` — opaque,
   non-navigable. They are re-typed to `list[DatasetRef]`, where a `DatasetRef` resolves an ADR-027
   `dataset_id` to a Merkle-manifest entry in the `DatasetRegistry`. `fine_tune_parent` (009:323) is
   re-typed from a bare uuid/hash `str` to a `ModelRef` — an ADR-027 **parent-model DAG edge** into
   the `ModelRegistry`. This mirrors the §D `raw_paths` → `CasRef` re-type: lineage stops being a
   string you cannot follow and becomes an edge you can traverse.

3. **Delegate uncertainty trust semantics to ADR-025/026.** Beside `uncertainty_method` (009:321),
   note that the **trust semantics** — `calibration_method`, `in_domain`/applicability-domain
   membership, and `escalation` thresholds — are **decided in
   [ADR-025](adr-025-campaign-acquisition-strategy.md)/[ADR-026](adr-026-trustworthy-mlip-evaluation-applicability-domain.md),
   not here**. Accordingly `uncertainty` is re-typed from a bare `float` to an ADR-026
   `UncertaintyEstimate`, which carries the method tag, calibration, and OOD/applicability-domain
   signal as one object. `uncertainty_method` is retained as a legacy tag for back-compat but is
   subsumed by `UncertaintyEstimate`. ADR-009 remains the **record** of the estimate; ADR-026 owns
   *how it is measured and calibrated* and ADR-025 owns *how it drives acquisition/escalation*. The
   one-directional coupling is explicit: ADR-025 consumes ADR-026's `UncertaintyEstimate` + escalation
   threshold at the escalation boundary (an OOD candidate must hit DFT, never skip the surrogate
   gate), and both resolve model identity through ADR-027's `ModelIdentifier`.

These are clarifications plus one re-type **inside** the already-bumped `schema_version "2"`. No
field is removed from the persisted schema in a way that changes the version contract: the
replaced `MlProvenance` quad and the `str`/`float` lineage types had not shipped (this ADR is
*Proposed*), so consolidating them onto `ModelIdentifier`/`DatasetRef`/`ModelRef`/`UncertaintyEstimate`
is part of the same `"2"` definition.

### Integration thesis (why this stays coherent with 007-020)

The 007-020 spine is intact: this remains "one versioned TaskDocument per code, validated on
write." The four new ADRs re-center the set without contradicting any locked decision by treating
**DFT as one instance of a more general abstraction** rather than the abstraction itself. ADR-021's
`CalculatorStage` (Structure → TaskDocument) generalizes ADR-008's `CodeDeckGenerator`/`InputDeck`
into the DFT-and-file-code specialization, with `MlipCalculatorStage` as a zero-file peer; this
ADR's revised schema is what both specializations write. ADR-022 turns the identity layer real by
hashing the full closure (statepoint + calculator/model + executable/lock + pseudopotential +
parent hashes + the §C environment fingerprint) and backing `raw_paths` with a CAS. ADR-023's
agentic control plane folds its AI provenance (§C) into the same schema and the ADR-022 hash.
ADR-024 statically type-checks the DAG before submission, re-validating the ML/agent sub-DAGs that
materialize at runtime. DFT, MLIP, and LLM steps become uniform citizens of one TaskDocument.

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

### Added by the 2026-06-03 amendment (ML / AI / determinism provenance)

- Batatia, I. et al., "A foundation model for atomistic materials chemistry (MACE-MP-0),"
  *J. Chem. Phys.* (2024), arXiv:2401.00096. *(Canonical foundation-MLIP; DFT as one stage;
  source of the Δ-ML / fidelity-lineage concept in `MlProvenance`.)*
- Deng, B. et al., "CHGNet as a pretrained universal neural network potential for
  charge-informed atomistic modelling," *Nat. Mach. Intell.* (2023),
  DOI:10.1038/s42256-023-00716-3. *(Charge-informed universal MLIP shipped as an ASE Calculator.)*
- Riebesell, J. et al., "Matbench Discovery — A framework to evaluate machine learning
  crystal stability predictions," *Nat. Mach. Intell.* (2025). *(uMLIPs as DFT pre-filters;
  motivates surrogate-screening and uncertainty/acquisition fields.)*
- Ganose, A. M. et al., "Atomate2," *Digital Discovery* (2025), DOI:10.1039/d5dd00019j.
  *(Precedent for running MLIPs via one `AseMaker` — the `CalculatorStage`/`MlipTaskDoc` pattern.)*
- Huber, S. P. et al., "AiiDA 1.0," *Scientific Data* 7, 300 (2020),
  DOI:10.1038/s41597-020-00638-4. *(BLAKE2b node-hash caching incl. parent-input hashes — the
  model ADR-022's content hash and the `CasRef`-backed `raw_paths` re-type build on.)*
- Shanmugavelu, S. et al., "Impacts of floating-point non-associativity on reproducibility
  for HPC and deep learning applications," *SC24-W* (2024),
  DOI:10.1109/SCW63240.2024.00028, arXiv:2408.05148. *(Why bitwise reproducibility is
  unachievable across heterogeneous hardware — motivates `EnvironmentFingerprint`.)*
- Laguna, I., "Varity: Quantifying Floating-Point Variations in HPC Systems Through
  Randomized Testing," *IEEE IPDPS* (2020), DOI:10.1109/IPDPS47924.2020.00070.
  *(Identical inputs diverge across compilers and CPU/GPU — grounds the compiler/flags and
  torch/CUDA fields of `EnvironmentFingerprint`.)*
- MatterGen, "A generative model for inorganic materials design," *Nature* (2025),
  arXiv:2312.03687. *(Reference generative `CandidateSource` whose outputs ADR-023 records via
  `AiProvenance`.)*
