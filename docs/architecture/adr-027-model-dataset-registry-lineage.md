# ADR-027: Model & Dataset Registry + Lineage — navigable registries over the ADR-022 CAS; the single unified `ModelIdentifier`

**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** none — makes [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md)'s lineage fields navigable instead of inert, and resolves [ADR-022](adr-022-content-addressed-execution-cache-replay.md)'s `model_version` to concrete weights; it does not reverse a locked decision
**Depends on:** [ADR-022](adr-022-content-addressed-execution-cache-replay.md) (the disk-objectstore content-addressed store the registry resolves weights and dataset members into; `ModelIdentifier.weights_cas_key` *is* a CAS key; the AiiDA `sqlite_dos`/disk-objectstore conformance oracle), [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md) (re-types `training_set_lineage`/`fidelity_lineage`/`fine_tune_parent` to registry/CAS references and adopts `ModelIdentifier` on `MlProvenance`), [ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md) (the `MODEL_REGISTRY` row shape becomes a `ModelIdentifier` resolution)
**Consumed by:** [ADR-025](adr-025-campaign-acquisition-strategy.md) and [ADR-026](adr-026-trustworthy-mlip-evaluation-applicability-domain.md) (both resolve model identity through this `ModelIdentifier`; ADR-026's calibration/OOD/benchmark metrics attach to the Model Card's required applicability block), [ADR-023](adr-023-agentic-control-plane-mcp-ai-provenance.md) (the agent reads the schema-validated applicability block to reason about a surrogate before trusting it)

## Context

ADR-021 makes an MLIP a first-class `CalculatorStage`, ADR-022 makes a content-addressed hash the
execution identity of every calculation, and ADR-009 records ML provenance on the `TaskDocument`.
Across those three the *model* and its *training data* are named in five places — and they do not
agree with each other.

**Model identity is decided three contradictory ways.** ADR-021 §2 keys the registry on a
`checkpoint_hash` that is explicitly *"the digest of the model registry entry (HF repo id + pinned
revision), **not** the multi-gigabyte weights"* (`adr-021-...:113-118`). ADR-022 §F folds the same
registry *digest* — not the weights — into the closure hash (`adr-022-...:267-271`). But ADR-009's
amendment §C calls its `model_checkpoint_hash` field *"content hash of the **weights**/checkpoint
(ADR-022 cache key)"* (`adr-009-...:316`). A registry digest and a hash-of-the-weight-bytes are
**different identities**; left unreconciled, this is a latent silent-wrong-cache bug — two runs that
cite "the same model" by different definitions of "same." There is no single field that says, once,
*what exactly this model is and where its bytes live.*

**ADR-009's lineage fields are inert strings.** `training_set_lineage: list[str]`,
`fidelity_lineage: list[str]`, and `fine_tune_parent` (`adr-009-...:316-319`) are *stored*, but
nothing resolves them: a `training_set_lineage` entry is a free string, not a handle you can follow
to the actual training set; `fine_tune_parent` names a parent but you cannot ask "what was derived
*from* this model." ADR-021 lists `training_provenance`/`fidelity_lineage` (`adr-021-...:162-166`)
with the same gap — *fields with no identity scheme, no population contract, no navigability.* The
REDESIGN consensus flags dataset/training provenance as the **least-specified axis** of the whole
set.

**ADR-022 resolves a `model_version` into the cache key but not into weights.** §5 folds
`calculator_id ⊕ model_version` into the closure and stores "the weights once" in the CAS
(`adr-022-...:191-195`), but *which* weights a given `model_version` denotes — the mapping from the
versioned identity to the CAS blob — is undecided. A cache hit cites `model_version`; nothing
guarantees that version still resolves to the same bytes it did when the hit was produced.

**The industry has converged on one shape for exactly this problem, and CrystalMath already owns
its hardest layer.** DVC (dvc.org), lakeFS (lakefs.io), the MLflow Model Registry (mlflow.org),
Hugging Face Hub (huggingface.co/docs/hub), and W&B Artifacts (docs.wandb.ai/guides/artifacts) are
all the *same* pattern: a thin **metadata/version layer** over a **content-addressed object layer**.
DVC tracks files by content hash while bytes live in a remote; lakeFS gives git-like commits over an
object store by content-addressing; MLflow registers named models with *immutable* versions and a
pointer back to the producing run; HF Hub and W&B carry git-style revisions and explicit lineage
DAGs. None of them store bytes *in the registry* — the registry holds metadata and lineage edges and
*resolves* into the object layer. CrystalMath's ADR-022 CAS — disk-objectstore
(disk-objectstore.readthedocs.io), the AiiDA team's SHA-256 loose+packed object store and the actual
AiiDA file-repository backend, already adopted as the ADR-022 storage layer and aligned with the
AiiDA conformance oracle — **is** that object layer. The missing piece is not a store; it is the
navigable metadata/lineage layer over it, and the one identity that ties them together.

The provenance-documentation field has equally converged: Model Cards (Mitchell et al., FAT* 2019,
arXiv:1810.03993) and Datasheets for Datasets (Gebru et al., CACM 2021, arXiv:1803.09010) are the
canonical structured-documentation practice — intended domain, training data, eval metrics, known
failure modes for models; motivation, composition, collection, maintenance for datasets. ADR-009
stores none of this as structured fields, so the very block ADR-026's trust harness needs to attach
its calibration/OOD/benchmark results to, and the very block the ADR-023 agent needs to read before
trusting a surrogate, does not exist as a typed, queryable thing.

This is the clean-slate opportunity the set invites: define **one** model/dataset identity, and a
navigable registry over the store CrystalMath already has — without reimplementing storage and
without reversing a locked decision.

## Decision

**Define ONE unified `ModelIdentifier` used everywhere (009/021/022/023/025/026), and a three-layer
registry architecture that makes ADR-009's inert lineage strings navigable without reimplementing
storage. IDENTITY is the `ModelIdentifier`. STORAGE is ADR-022's content-addressed store — the
registry stores metadata and lineage edges only, NEVER bytes; weights and dataset members resolve to
CAS blobs by hash. METADATA+LINEAGE is a narrow, tool-agnostic port (`register`/`resolve`/`lineage`)
that is append-only with immutable revisions and a DAG of parent pointers. Datasets are
content-addressed Merkle manifests of CAS members. Model Cards and Datasheets are schema-validated
registry fields with a required applicability block.**

### 1. The single unified `ModelIdentifier`

One identity, used by 009, 021, 022, 023, 025, and 026 — replacing the contradictory `checkpoint_hash`
/ `model_checkpoint_hash` / `model_version` triple:

```python
class ModelIdentifier(BaseModel):           # the IDENTITY layer; the one model handle everywhere
    registry_uri: str                       # which registry (in-repo backend by default)
    model_id: str                           # stable logical name of the model
    immutable_revision: str                 # an append-only revision that can NEVER be reassigned
    weights_cas_key: CasRef                  # ADR-022 CAS key for the weight bytes (resolves to a blob)
    code_package_version: str               # the inference/training code version that interprets the weights
```

This resolves the weights-vs-digest contradiction by **carrying both, with distinct roles**:
`immutable_revision` is the versioned identity ADR-021/022 fold into the closure (the "which model"
a cache hit cites); `weights_cas_key` is the ADR-022 CAS key that resolves to the *actual weight
bytes*. The bytes are stored **once** in the CAS (ADR-022 §F's "store the weights once" stands); the
registry never holds them. `code_package_version` closes the gap that identical weights under a
changed inference package are not the same calculator. ADR-021's `(model_id, factory,
checkpoint_hash)` registry row becomes a `ModelIdentifier` resolution; ADR-009's `MlProvenance`
carries a `ModelIdentifier` instead of the three disagreeing scalar fields.

### 2. Three layers, and the registry never stores bytes

The convergent DVC/lakeFS/MLflow/HF/W&B pattern, mapped onto CrystalMath's existing seams:

- **IDENTITY** = the `ModelIdentifier` (§1).
- **STORAGE** = ADR-022's content-addressed store (disk-objectstore, the AiiDA SHA-256 loose+packed
  backend; `adr-022-...:185-195`). Weight bytes and dataset *members* are CAS blobs keyed by hash; a
  multi-gigabyte checkpoint and a training-set member that recurs across datasets each dedupe under
  SHA-256 packing. This is the same store the ADR-022 conformance oracle already certifies.
- **METADATA + LINEAGE** = a narrow, tool-agnostic port that holds **only** metadata and lineage
  edges and resolves into the CAS:

```python
class ModelRegistry(Protocol):
    def register(self, ident: ModelIdentifier, card: ModelCard,
                 parent: ModelIdentifier | None, dataset: DatasetId) -> None: ...
    def resolve(self, model_id: str, immutable_revision: str) -> ResolvedModel: ...
        # -> {weights_cas_key, hyperparams, parent_model, training_dataset, card}
    def lineage(self, ident: ModelIdentifier) -> LineageDag: ...
        # forward (derived-from) + backward (what-trained-this)
```

The registry is a **metadata DB + lineage edges**; it never holds a weight byte. This is exactly what
makes ADR-009's lineage strings navigable (`resolve`/`lineage` follow them to real objects) and
ADR-022's `model_version` resolvable (`resolve(model_id, immutable_revision) -> weights_cas_key`).

### 3. Append-only, immutable revisions, parent-pointer DAG

A registry revision is **immutable**: once `immutable_revision` is registered, its `weights_cas_key`
and metadata can never be silently reassigned (the MLflow-immutable-version / HF-git-revision
posture). This is the property that lets an ADR-022 cache hit cite `immutable_revision` *safely* — a
revision can never change weights underneath a hit. Parent pointers (`parent: ModelIdentifier`) form
a **DAG**, not a string: an active-learning retrain-from-parent on a grown dataset is a DAG **edge**,
so the registry answers both directions — forward ("what was derived from this model") and backward
("what trained this") — which ADR-009's flat `fine_tune_parent` string cannot. Backward lineage
needs a reverse index; that index is the registry's write-time bookkeeping, not the caller's problem.

### 4. Datasets are content-addressed Merkle manifests

A `DatasetId` is the **hash of a manifest** that lists its members by their CAS content-hashes — a
Merkle root over CAS-addressed members:

```python
class DatasetManifest(BaseModel):
    members: list[CasRef]      # each a CAS key (the bytes live once in the ADR-022 store)
    dataset_id: str            # = hash(canonicalized members)  — the Merkle root
```

Because the `dataset_id` is a hash over content-addressed members, **"same training set" is an exact
hash comparison** (cheap, exact) rather than a path/name comparison, and a dataset is **reproducible
by hash** — resolving a `dataset_id` yields its members directly out of the CAS. This is precisely
what ADR-022's reuse keys require (a training set folded into a closure must be identity-stable) and
what active-learning dataset-growth tracking needs: each AL cycle that appends labels produces a
**new** `dataset_id` (a new manifest), and the parent-DAG (§3) records the growth as an edge.
Member-level dedup keeps the bytes cheap; manifest proliferation is bounded by GC (see risks).

### 5. Model Cards and Datasheets are schema-validated fields, not free text

Every registered model carries a **schema-validated** `ModelCard` and every dataset a `Datasheet`
(Mitchell 2019; Gebru 2021), encoded as required typed fields rather than prose:

- `ModelCard`: training data (a `DatasetId`, §4), eval metrics, known failure modes, and a
  **required `applicability` block** (intended chemical/structural domain, valid statepoint range).
- `Datasheet`: motivation, composition, collection process, maintenance.

The required `applicability` block is load-bearing for the rest of the set: it is **exactly where
ADR-026's calibration / OOD / benchmark results attach** (the harness writes its measured metrics
into the model's applicability block) and **exactly what the ADR-023 agent reads** to reason about a
surrogate's intended domain *before* trusting it. This turns provenance from inert strings into
queryable, validatable metadata — and gives ADR-026's "trust must be measured" a typed home to write
measurements to.

### 6. One narrow port, one concrete in-repo backend; SaaS tools are optional adapters

The port (§2) is deliberately small and tool-agnostic. The one concrete backend that ships is
**disk-objectstore (the ADR-022 CAS) + a metadata DB** — no external service required, consistent
with the laptop-first, zero-user posture. DVC, the MLflow Model Registry, lakeFS, Hugging Face Hub,
and W&B Artifacts are **candidate optional adapters**, not the abstraction — mirroring ADR-023's
"one seam, one adapter, don't over-engineer for zero users" correction. There is no single winner
(MLflow is strongest on model staging/run-lineage, lakeFS/DVC on data branching+CAS, HF on public
distribution, W&B on lineage DAGs); hard-coupling to one is premature for a clean-slate project. The
port must not leak a backend's vocabulary (MLflow "stages" vs HF "revisions") into the core type.

### 7. Referential integrity: a dangling `weights_cas_key` is a hard error

Two systems (registry DB + CAS) must stay consistent. The new failure mode this architecture
introduces is a **dangling `weights_cas_key`** — a registry revision whose CAS blob was
garbage-collected out from under it. The registry **pins** every CAS object any live revision
references (weights blob, dataset manifest, all dataset members), so ADR-022's CAS GC can never
reclaim a blob a registry revision still cites; resolving a revision whose blob is missing is a hard
error, never a silent miss. This makes the registry a pinning client of the CAS, exactly as
ADR-022's cache entries are.

## Alternatives Considered

**A. Keep ADR-009's `*_lineage: list[str]` fields and just document a string convention.** The
minimal change: leave the fields, write a naming scheme for the strings. *Why not:* a string is not
navigable — you cannot `resolve` it to weights or `lineage`-walk it backward, and "same training
set" stays a fragile path/name comparison. It also leaves the weights-vs-digest contradiction
(`adr-009-...:316` vs `adr-021-...:115`/`adr-022-...:267`) unresolved, i.e. a latent silent-wrong-cache
bug intact. The whole point is to make those fields *resolvable*; a convention over strings does not.

**B. Let the registry store the weight/dataset bytes itself (a self-contained model store).** Simpler
to reason about — one system, no two-store consistency problem, no pinning. *Why not:* it reimplements
exactly the content-addressed, deduplicating store ADR-022 already decided and already certifies
against the AiiDA conformance oracle, and it duplicates multi-gigabyte checkpoints and shared
training-set members that the CAS dedupes for free. The convergent industry pattern
(DVC/lakeFS/MLflow/HF/W&B) is precisely *metadata layer over object layer* for this reason. We keep
the registry a metadata+lineage layer and resolve bytes into the one store ADR-022 owns.

**C. Hard-couple to one external registry (e.g. MLflow Model Registry, or HF Hub) as the abstraction.**
These are mature, with UIs, access control, and hosted lineage browsing for free. *Why not:* there is
no single winner across the model-staging / data-branching / public-distribution / lineage-DAG axes,
and binding the core type to one backend's semantics (MLflow stages, HF revisions) leaks that
vocabulary into 009/021/022/023/025/026. For a zero-user clean slate this is premature coupling; we
define the narrow port (§6) and keep the SaaS tools as optional adapters — the same correction
ADR-023 applied to MCP. The cost is re-implementing some convenience features (UI, hosted browsing),
accepted deliberately.

**D. Make `model_version` a plain mutable string/integer (no immutable-revision requirement).**
Lighter bookkeeping; no append-only constraint. *Why not:* mutability breaks ADR-022 outright — if a
`model_version` can be reassigned to new weights, every cache hit that cited it is silently
invalidated *without a hash change*, the exact silent-wrong-cache failure the content-addressing layer
exists to prevent. Immutable revisions (§3) are what let a cache hit cite `immutable_revision` safely.
The append-only cost (retention/GC of abandoned AL branches) is real but bounded by the GC policy in
the risks, and is the price of a sound cache.

**E. Track datasets by path/name + a version tag instead of a content-addressed Merkle manifest.**
Most workflows do this; it is familiar. *Why not:* a path/name+tag is not reproducible by hash, so
"same training set" becomes a string comparison that can quietly drift when files behind the path
change — and ADR-022's reuse key folds the training set into a *closure hash*, which is unsound over a
non-content-addressed dataset identity. The Merkle manifest (§4) makes dataset identity an exact hash
and resolves members straight out of the CAS, which is what reuse keys and AL growth-tracking both
require. Mutable/streaming datasets don't fit a frozen root cleanly — handled by emitting a new
manifest revision per append (the parent-DAG records the growth), at the cost of manifest
proliferation bounded by GC.

**F. Encode Model Cards / Datasheets as free-text blobs (a `notes` field).** Zero schema friction;
submitters write whatever they want. *Why not:* free text is not queryable, so ADR-026's harness has
nowhere typed to attach calibration/OOD/benchmark metrics and the ADR-023 agent has no machine-readable
applicability block to reason over — the two consumers this ADR exists to serve. Schema-validated
fields (§5) cost ingestion friction and need schema versioning as practice evolves, accepted because
the structured applicability block is the seam 026 and 023 both depend on. Qualitative fields
(intended domain, known failure modes) remain only as trustworthy as the submitter — an inherent
limit, not a reason to drop the schema.

## Consequences

### Positive
- **One model identity replaces three contradictory ones.** `ModelIdentifier` (§1) is used by
  009/021/022/023/025/026; the weights-vs-digest contradiction is resolved by carrying both with
  distinct roles (`immutable_revision` for the cache-citable version, `weights_cas_key` for the
  bytes), and the silent-wrong-cache bug latent in `adr-009-...:316` is closed.
- **ADR-009's inert lineage strings become navigable.** `resolve` follows a model to its weights +
  hyperparams + parent + training dataset; `lineage` walks the DAG forward (derived-from) and backward
  (what-trained-this) — `training_set_lineage`/`fidelity_lineage`/`fine_tune_parent` re-type to
  registry/CAS references instead of free strings.
- **ADR-022's `model_version` resolves to concrete weights.** `resolve(model_id, immutable_revision)
  -> weights_cas_key` makes the cache-key version a handle to real bytes, and immutability (§3)
  guarantees a hit can never have the weights changed underneath it.
- **"Same training set" and "reproducible dataset" are exact hash facts.** The Merkle manifest (§4)
  makes dataset identity a content hash — what ADR-022 reuse keys and active-learning growth-tracking
  both need — with member-level dedup in the one CAS.
- **The trust harness and the agent get a typed home.** The required applicability block (§5) is
  exactly where ADR-026 writes calibration/OOD/benchmark metrics and exactly what ADR-023's agent
  reads before trusting a surrogate — provenance becomes queryable, validatable metadata.
- **No new store; one narrow seam.** STORAGE is the ADR-022 CAS already certified by the AiiDA
  conformance oracle; the registry is a thin metadata+lineage layer with one in-repo backend, SaaS
  tools as optional adapters (§6) — the ADR-023 "one seam, one adapter" posture.

### Negative / Tradeoffs
- **Two systems (registry DB + CAS) must stay consistent, introducing the dangling-`weights_cas_key`
  failure mode.** A revision whose blob was GC'd is a new class of error; mitigated by §7's
  referential-integrity pinning (the registry pins every CAS object a live revision references), but
  this makes the registry a hard dependency of, and a pinning client of, the cache layer.
- **Append-only growth needs a retention/GC policy.** Immutable revisions and per-append dataset
  manifests accumulate; abandoned active-learning branches and near-identical manifests must be GC'd
  under a policy that respects §7's pins. Backward-lineage queries also require a reverse index,
  adding write-time bookkeeping.
- **Schema-validated Cards/Datasheets create ingestion friction and need versioning.** Every
  registered model must supply the required fields (intended domain, eval metrics, applicability); the
  schema will need versioning as Model-Card/Datasheet practice evolves. Some fields are inherently
  qualitative and only as trustworthy as the submitter.
- **The single in-repo backend re-implements convenience the SaaS tools give for free.** No hosted UI,
  access control, or lineage browser ships with the in-repo backend; those arrive only if/when an
  optional adapter (MLflow/HF/W&B/lakeFS/DVC) is added. The port must be designed not to leak any one
  backend's vocabulary into the core type.
- **disk-objectstore is single-host/disk-oriented.** It has no built-in distributed/remote
  replication (unlike DVC remotes or lakeFS-on-S3); a future multi-cluster CrystalMath deployment may
  need a remote tier behind the same port. SHA-256 hashing of multi-gigabyte checkpoints is a non-zero
  one-time ingest cost.

### Migration impact
1. Define `ModelIdentifier` (§1) and the `ModelRegistry` port (`register`/`resolve`/`lineage`, §2)
   in a new `crystalmath` registry module; ship the in-repo backend (disk-objectstore CAS + metadata
   DB).
2. Re-type ADR-009's `MlProvenance` to carry a `ModelIdentifier` and re-type
   `training_set_lineage`/`fidelity_lineage`/`fine_tune_parent` to registry/CAS references; correct
   the `adr-009-...:316` "content hash of the weights" comment to "registry-resolved identity; weights
   stored once in the ADR-022 CAS."
3. Make ADR-021's `MODEL_REGISTRY` row a `ModelIdentifier` resolution; make ADR-022's `model_version`
   resolve via `resolve(model_id, immutable_revision) -> weights_cas_key`.
4. Add `DatasetManifest`/`DatasetId` (§4) over the CAS; make AL dataset-growth emit new manifest
   revisions with parent-DAG edges.
5. Add schema-validated `ModelCard`/`Datasheet` (§5) with the required `applicability` block; point
   ADR-026's harness to write its metrics there and ADR-023's agent to read it.
6. Implement §7 CAS-pinning of everything a live registry revision references, and the append-only
   retention/GC policy.

## References

- M. Mitchell, S. Wu, A. Zaldivar, et al., "Model Cards for Model Reporting," *Proc. Conference on
  Fairness, Accountability, and Transparency (FAT\*)* (2019). arXiv:1810.03993. — Canonical structured
  model-documentation practice; the basis for the schema-validated `ModelCard` and its required
  applicability block (§5).
- T. Gebru, J. Morgenstern, B. Vecchione, et al., "Datasheets for Datasets," *Communications of the
  ACM* **64**(12), 86-92 (2021). arXiv:1803.09010. — Canonical structured dataset-documentation
  practice; the basis for the schema-validated `Datasheet` (§5).
- S. P. Huber, S. Zoupanos, M. Uhrin, et al., "AiiDA 1.0, a scalable computational infrastructure for
  automated reproducible workflows and data provenance," *Scientific Data* **7**, 300 (2020).
  DOI:10.1038/s41597-020-00638-4. — Anchors disk-objectstore as the AiiDA file-repository backend and
  aligns the registry's STORAGE layer with the ADR-022 conformance oracle.
- disk-objectstore (AiiDA team) — an efficient, SHA-256-keyed loose+packed object store; the AiiDA
  file-repository backend. https://disk-objectstore.readthedocs.io/,
  https://github.com/aiidateam/disk-objectstore. — The content-addressed STORAGE layer (§2) into which
  `weights_cas_key` and dataset members resolve.
- DVC — Data Version Control. https://dvc.org/. — Content-hash pointers decoupled from byte storage in
  a remote; reference for the three-layer split (§2) and Merkle-manifest datasets (§4); candidate
  optional adapter (§6).
- MLflow Model Registry. https://mlflow.org/docs/latest/model-registry.html. — Named models with
  immutable versions and producing-run lineage; reference for immutable revisions (§3); candidate
  optional adapter (§6).
- lakeFS — git-like, content-addressed versioning over object storage. https://lakefs.io/. —
  Reference for the storage/identity split and dataset commit/branch model; candidate optional adapter
  (§6).
- Hugging Face Hub — model & dataset repositories with git-style revisions and Model/Dataset Cards.
  https://huggingface.co/docs/hub. — Reference for git-style immutable revisions and the structured
  Card practice; candidate optional adapter (§6).
- Weights & Biases Artifacts — versioned model/dataset artifacts with a lineage DAG.
  https://docs.wandb.ai/guides/artifacts/. — Reference for forward/backward lineage-DAG queries (§3);
  candidate optional adapter (§6).
- CrystalMath internal: [ADR-022](adr-022-content-addressed-execution-cache-replay.md)
  (`adr-022-...:185-195,267-271` — the disk-objectstore CAS, "store the weights once," and the
  registry-digest-not-weights hash input the `ModelIdentifier` carries),
  [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md) (`adr-009-...:316-319` — the
  `model_checkpoint_hash` weights-vs-digest contradiction and the inert
  `training_set_lineage`/`fidelity_lineage` strings this ADR re-types),
  [ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md) (`adr-021-...:113-118` — the
  `MODEL_REGISTRY` `(model_id, factory, checkpoint_hash)` row that becomes a `ModelIdentifier`
  resolution), [ADR-026](adr-026-trustworthy-mlip-evaluation-applicability-domain.md) (whose
  calibration/OOD/benchmark metrics attach to the §5 applicability block),
  [ADR-023](adr-023-agentic-control-plane-mcp-ai-provenance.md) (whose agent reads the §5 applicability
  block, and whose "one seam, one adapter" correction §6 mirrors).
