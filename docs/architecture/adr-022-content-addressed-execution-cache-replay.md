# ADR-022: Content-addressed execution identity, hash-hit caching, and the replay contract as the default execution gate

**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** none — *enforces and generalizes* [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md) `input_hash` and [ADR-013](adr-013-multi-code-handoff-and-restart-validation.md) per-handoff checksum
**Depends on:** [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md) (emmet-style TaskDocuments + lineage fields `input_hash`/`parent_job_uuids`/`raw_paths`), [ADR-010](adr-010-single-result-store-jobflow-maggma.md) (the maggma `JobStore` + `additional_stores` blob seam), [ADR-013](adr-013-multi-code-handoff-and-restart-validation.md) (typed handoff edges whose checksum this ADR backs with a real store)
**Participates with:** ADR-021 (the `CalculatorStage` abstraction whose runs this ADR caches; ML checkpoints are content-addressed artifacts), ADR-023 (agentic planner whose AI-provenance folds into the hash), ADR-024 (static DAG validation that re-validates dynamically materialized sub-DAGs)
**Pairs with:** [ADR-020](adr-020-reproducibility-and-golden-file-testing.md) (revised) — golden-file/property testing is the *test-side* aspiration this ADR turns into an *enforced execution contract*; ADR-022 supplies the env-fingerprint/replay tier ADR-020 lacks

## Context

The 007–020 redesign **records** content-addressing in three places but **never enforces it**, and
that gap is the single biggest determinism hole in the set.

- **ADR-009 stores a hash nobody acts on.** `ProvenanceDoc.input_hash` is "a content hash over the
  staged `InputDeck.files`" (`adr-009-…taskdocs.md:114,162`) and `raw_paths` is an advisory
  `dict[str, str]` of "content-addressed paths (hash-named)" (`adr-009-…taskdocs.md:119,166`) — but
  nothing reads `input_hash` to *skip* a calculation, nothing keys storage by it, and there is no
  decided hash algorithm, no canonicalization rule, no dedup contract. The hash is metadata, not
  identity. The execution identity in practice is the jobflow/AiiDA **instance UUID**, which is
  unique per submission and therefore can never produce a cache hit.
- **ADR-010 names a blob store but never decides it is a CAS.** The `additional_store` for large
  blobs (`adr-010-…maggma.md:52,83,104`) is selected *by kind* (FileStore/GridFS/S3Store) only;
  there is no hash-keyed retrieval contract, no dedup, no "have I already stored this exact
  WAVECAR." Reproducibility is asserted as a *property of fields* (`adr-010-…maggma.md:119,192`),
  not as an *enforced execution gate*.
- **ADR-013 compares a hash exactly once, per-edge, at runtime.** `RestartValidation` §2 checks that
  "the transferred file's content hash must equal the hash recorded on the source TaskDocument when
  that job successfully completed" (`adr-013-…validation.md:127-132`), with the hash "computed once
  at source completion … recorded on the source document" (`adr-013-…validation.md:230`). This is
  the *strongest* content-addressing thinking in the set — but it is restart-file-specific,
  DFT-physics-specific, and fires only when a single handoff edge fires. It is a per-edge checksum,
  not a global execution identity.

So the set has a recorded `input_hash` that gates nothing, an advisory `raw_paths` with no backing
store, and one real hash compare scoped to a single edge. Meanwhile **ADR-010 and ADR-012 contradict
each other** about the one backend that already solves this: ADR-010 rejects AiiDA-as-default
because it "mandates PostgreSQL + (historically) RabbitMQ" (`adr-011-…atomate2-quacc.md:124`,
`adr-010-…maggma.md` Alternative), yet ADR-012 admits AiiDA 2.x ships server-free `sqlite_dos`
profiles. "AiiDA only behind an opt-in heavyweight backend" + "an unenforced advisory hash on the
default path" is internally indefensible: the determinism story lives behind a backend most users
never enable.

**The ecosystem has long since converged on the fix: the content hash IS the execution identity,
and hash-hit caching IS the default execution gate.** AiiDA BLAKE2b-hashes a node's immutable
attributes + repository contents + *the hashes of all its inputs* into one queryable identity; on a
match with caching enabled it **clones** the prior outputs and links them, reproducing the same
provenance graph without re-running (Huber et al., Sci. Data 7:300, 2020; AiiDA caching docs:
`_aiida_hash`, `_aiida_cached_from`, `CACHE_VERSION`, `is_valid_cache`). Nextflow's `-resume`
hashes script + input content + container/conda/spack into a task hash and reuses outputs only if
the hash *and* the outputs are valid (Di Tommaso et al., Nat. Biotechnol. 2017). signac makes the
**state-point hash the storage identity** — the job directory literally *is* a 32-char hash, so
re-init is idempotent (Adorf et al., Comput. Mater. Sci. 2018). Koji computes a **causal hash**
recursively over inputs + transformation, computable *before* the resource exists (Maymounkov,
arXiv:1901.01908). Bazel's remote execution keys a hermetic **Merkle action cache** on fully
specified inputs (arXiv:2405.00796). AiiDA's serverless **disk-objectstore** (SHA-256 loose/packed,
tens of millions of files) is exactly the content-addressed raw-file backing `raw_paths` mirrors but
never adopts (Huber, Nat. Rev. Phys. 2022).

The literature is equally sharp that **caching ≠ replay**. ADR-020 conflates bitwise and scientific
reproducibility and elides compiler/MPI/BLAS/GPU nondeterminism. Floating-point non-associativity
under different MPI rank counts, OpenMP thread counts, GPU atomics, BLAS/LAPACK vendors, and FMA
contraction makes bitwise-identical results across heterogeneous hardware **unachievable**
(Shanmugavelu et al., SC24-W 2024; Laguna *Varity*, IPDPS 2020). Reproducible *execution* therefore
needs a full environment fingerprint — executable/lock digest, pseudopotential, BLAS/MPI/thread,
compiler + flags (Bissuel et al., arXiv:2512.13826; Uehlein et al., arXiv:2604.25944). "Have I run
this?" (cheap reuse) and "can I reproduce this elsewhere bit-for-bit?" (strict replay) are two
different questions and need two different hashes.

ADR-009 gives the substrate (one typed TaskDocument with lineage fields), ADR-010 gives the one
store and the `additional_store` seam, ADR-011 gives jobflow `Flow`s whose `Response(detour/replace)`
is a natural pre-execution hook, and ADR-013 gives the per-edge checksum to generalize. This ADR
turns content-addressing from recorded metadata into an **enforced default execution contract**.

## Decision

Adopt **one canonical, versioned content hash over the full execution closure as the execution
identity**, make **idempotent hash-keyed cache-and-clone the default pre-execution gate** in the
maggma path, back `raw_paths` with a **disk-objectstore CAS**, and separate **caching from replay**
via **two hash tiers**. The job UUID is demoted to an instance-id; the content hash is identity.

### 1. One canonical content hash over the closure; the UUID is instance-id only

Define `crystalmath.identity.content_hash(closure) -> str` — a versioned BLAKE2b/BLAKE3 digest over
a **canonicalized** closure, ported from AiiDA's node-hash recipe (Huber 2020) and Koji's causal
recursion (Maymounkov 2019):

```
content_hash = H(
    CACHE_VERSION                       # per-code epoch; bump invalidates all prior hits
  ⊕ canonical(statepoint)              # ADR-008 Structure → canonicalized cell/species/settings
  ⊕ canonical(params)                  # code params, key-sorted, comment-stripped (ADR-024 canon)
  ⊕ calculator_id ⊕ model_version      # ADR-021 CalculatorStage: code OR MLIP model id+version
  ⊕ executable_digest                  # binary / container / pixi-lock digest
  ⊕ pseudopotential_or_basis_hash      # POTCAR/UPF set, or CRYSTAL basis (ADR-013 artifact)
  ⊕ deck_bytes_hash                    # canonicalized InputDeck.files (ADR-008)
  ⊕ sorted(parent_content_hashes)      # PARENT hashes, not parent UUIDs — Huber 2020 / Koji
  ⊕ workflow_version                   # Flow-factory version (ADR-011)
)
```

- **The job UUID is demoted to an instance-id.** ADR-009's `parent_job_uuids` remain as *audit*
  lineage, but identity is the **parent *content* hash**, folded recursively — two submissions of
  the same closure share a hash even though their UUIDs differ. This is the bit ADR-009's recorded
  `input_hash` never did: make the hash the answer to "has this exact calculation run?".
- **`CACHE_VERSION`** is a per-code integer that invalidates all prior hits when a code's
  behavior changes without a version bump (AiiDA caching docs' named failure mode:
  "code changed without version → false positive"). It is a hash input, so bumping it busts the
  cache deterministically.
- **The closure must be neither under- nor over-broad.** Omitting executable/lock/pseudopotential
  produces *false hits* across binary/BLAS/MPI stacks (silent wrong science); including volatile
  fields (timestamps, scratch paths, comment-only deck edits) produces *false misses*.
  Canonicalization is therefore not optional — it is enforced by ADR-024's static canonicalizer and
  audited by ADR-020's golden-file tests over the hash function itself.

`input_hash` (ADR-009 `:114`) is **redefined** from "advisory content hash of the deck" to "the
ADR-022 coarse content hash" — promoting the existing field rather than adding a parallel one.

### 2. Hash-hit cache-and-clone is the DEFAULT pre-execution gate

Before any `CalculatorStage` (ADR-021) runs, the engine queries the ADR-010 `JobStore` by
`content_hash`. This is the AiiDA contract (Huber 2020) ported to the maggma path — *not* its ORM:

1. **Query** the store for a completed TaskDocument with the same `content_hash`.
2. **Validate the hit is defeasible-safe**: source state is `completed` (ADR-009 `JobState`),
   `is_valid_cache` is true, and `CACHE_VERSION` matches. A hit on a non-`completed`,
   superseded, or `CACHE_VERSION`-stale document is **ignored** (AiiDA's `is_valid_cache` /
   `is_finished` discipline — the same "WAVECAR only written on completion" rule ADR-013 §3.2
   enforces per-edge, generalized to every stage).
3. **On a valid hit, CLONE** the prior outputs + provenance into a new TaskDocument (new instance
   UUID, `cached_from = <source content_hash + source uuid>`, mirroring AiiDA's `_aiida_cached_from`)
   instead of re-running. The cloned document carries the *original* env fingerprint plus a
   `cache_clone` provenance marker, so an auditor can always distinguish "computed here" from
   "cloned from there."

This rides jobflow's `Response(detour/replace)` (ADR-011 §1) as the pre-execution hook: the gate is
a `@job` that runs *before* the calculator `@job` and either short-circuits with the clone or lets
execution proceed. It is the **default**, not an opt-in — turning ADR-009's recorded `input_hash` and
ADR-013's per-edge checksum into one enforced reuse contract. Cache-skip is applied to *deterministic
stages only*; the campaign controller (ADR-023) and LLM/agent nodes are explicitly **un-cached** (§5).

### 3. `raw_paths` is backed by a disk-objectstore CAS; ADR-013 validation becomes a hash compare

Adopt AiiDA's **disk-objectstore** (serverless SHA-256 loose/packed, packing + GC, name resolution
for hash-named files; Huber 2022) as the concrete backing for ADR-010's `additional_store`
(`adr-010-…maggma.md:52,83`) and ADR-009's `raw_paths` (`adr-009-…taskdocs.md:119,166`):

- Decks, pseudopotentials/POTCARs, `WAVECAR`/`CHGCAR`/`.f9`/`.f98`, logs, and **ML checkpoints**
  become content-addressed artifacts keyed by SHA-256. `raw_paths` is **redefined** from an advisory
  `dict[str, str]` to **typed CAS references** (algorithm + key format decided here, not late as
  ADR-009 left it).
- **Dedup falls out for free**: an identical pseudopotential or restart file across thousands of
  runs is stored once. In-progress files stay in scratch until *sealed* on source completion
  (Nextflow work-dir discipline), then ingested into the CAS.
- **ADR-013 RestartValidation §2 collapses to a CAS lookup.** "The transferred file's content hash
  must equal the hash recorded on the source document" (`adr-013-…validation.md:128-132`) becomes:
  resolve the artifact by its CAS key; if the key resolves to a sealed object on a `completed`
  source, the restart file is *by construction* the one that source produced. The per-edge checksum
  ADR-013 computes once at source completion (`:230`) is now a *write into the global CAS*, not a
  field on one document.

### 4. Two hash tiers: a coarse SCIENTIFIC-IDENTITY hash for reuse, a fine REPLAY hash for strict reproduction

Caching and replay are separated, because cross-hardware bitwise reproducibility is unachievable
(Shanmugavelu SC24; Laguna IPDPS20):

- **Tier 1 — scientific-identity hash (`content_hash`, §1):** the reuse key. Binds statepoint +
  params + calculator/model + executable/lock + pseudopotential + parent hashes + workflow version.
  Deliberately **does not** bind thread count / rank count / BLAS build, so a result computed on one
  node configuration can be reused on another *within the same scientific-tolerance class*. This is
  the cache key.
- **Tier 2 — replay/env-fingerprint hash (`replay_hash`):** a strict bitwise/environment fingerprint
  recorded on **every** TaskDocument (the env fingerprint ADR-020 lacks), binding
  executable/container/lock digest, pseudopotential, **BLAS/LAPACK + MPI + OpenMP thread/rank counts
  + compiler + flags + GPU/driver** (Bissuel 2025; Uehlein 2026). `replay_hash` is **not** an
  execution gate — it is the answer to "were these two runs even comparable, and can I reproduce
  this bit-for-bit on the same stack?". Strict replay = `replay_hash` match **plus** per-property
  scientific tolerances (total energy ~1e-6 Ha, forces, stresses, band gaps) verified by a ReFrame
  regression layer (the lenient-vs-standard split Nextflow draws between resume modes).

A Tier-1 hit with a Tier-2 mismatch is a **legitimate cache hit** (reuse the science) that is
**flagged as non-bitwise** in provenance — never silently treated as a bitwise reproduction.

### 5. ML and agentic layers are first-class cache participants

The cache pays off *most* where ADR-021/023 add ML/LLM-in-the-loop, because active learning
re-evaluates near-identical structures:

- **ML checkpoints are content-addressed inputs, not weights.** The hash folds the **model registry
  digest** (HF repo + revision, or a CAS key for a local checkpoint), *not* multi-GB weights. An
  `MlipCalculatorStage` (ADR-021) is a pure function of (statepoint, checkpoint digest, settings,
  versions), so a content-addressed key gives cache-and-resume nearly free. **A checkpoint bump
  invalidates every dependent surrogate** by changing `model_version` in the closure — the
  determinism anchor ADR-020 explicitly lacks for ML.
- **LLM/agent nodes are un-cached; their deterministic children are cached.** Closed-model versions
  drift and GPU inference is not bitwise-reproducible, so agent/LLM nodes (ADR-023) are marked
  `cacheable=False` and never produce a hit. But the *typed Flow they emit* and its deterministic
  DFT/MLIP child stages **are** cached normally — the agent is a non-deterministic *producer of a
  deterministic, cache-gated DAG*, consistent with ADR-023's "agent output is a PROPOSED typed Flow,
  validated by 016/024, never executed unvalidated."
- **AI provenance folds into the hash and the document.** Model / prompt / agent-identity /
  acquisition-function / approval (ADR-023) are recorded on the ADR-009 schema and, for the
  deterministic children, are inputs to `content_hash` so an approval change can bust the cache.

### 6. Hash-caching is a backend-agnostic contract; `sqlite_dos` AiiDA is the strict reference impl

Resolve the ADR-010/012 inconsistency the same way ADR-013 resolved AiiDA-vs-default: **adopt
AiiDA's guarantee as a contract the default store must satisfy.**

- The **default maggma path** implements §1–§4 (hash over the closure, hash-keyed cache-and-clone,
  disk-objectstore CAS, two tiers). The determinism story lives on the **default** path.
- **AiiDA with the server-free `sqlite_dos` profile** becomes the opt-in **maximally-strict
  reference implementation** of the same contract — its BLAKE2b input-hash caching + clone-on-hit +
  disk-objectstore + immutable provenance DAG are the gold standard the maggma path is measured
  against. This retires ADR-010's "AiiDA requires PostgreSQL" premise (refuted by ADR-012's own
  admission) without forcing AiiDA on anyone.
- The two stores must agree on identity, so the canonicalization rules (§1) are specified precisely
  enough — and audited by ADR-020/024 — that a result cached under maggma is *recognizably the same
  hash* AiiDA would compute.

### 7. Provenance export is an opt-in Workflow Run RO-Crate

On completion, CrystalMath can export a **Provenance Run Crate** (Workflow Run RO-Crate;
Soiland-Reyes/Leo et al., PLOS ONE 2024 — W3C-PROV-aligned, WorkflowHub-compatible) carrying the
content hashes, both hash tiers, env fingerprints, and (for ADR-023) AI provenance, in a schema
six+ workflow systems already read. RO-Crate is a *packaging* standard, not a caching engine — it
complements the CAS, it does not replace it — so it is an **opt-in export**, not a per-run
requirement.

## Alternatives Considered

**A. Keep `input_hash`/`raw_paths` advisory and never gate on them (status quo of 009/010).** *Why
not:* this is precisely the recorded-but-unenforced gap this ADR exists to close. An `input_hash`
that gates nothing and a `raw_paths` dict with no backing CAS give the *appearance* of content
addressing with none of the determinism. With zero users there is no reason to preserve the
non-enforcing default.

**B. Make AiiDA the only path so caching comes "for free."** AiiDA's node-hash caching + clone +
disk-objectstore (Huber 2020, 2022) is the proven reference. *Why not as the only path:* it imposes
AiiDA's ORM/operational model on the laptop-first TUI ADR-010 deliberately defaults away from. We
port the *contract* to maggma and keep `sqlite_dos` AiiDA as the strict reference implementation
(§6) — getting the guarantee without mandating the database, exactly as ADR-013 did for restart
validation.

**C. One hash for everything (no caching/replay split).** Simpler to implement: a single fingerprint
that binds thread/rank/BLAS/compiler so any hit is a bitwise reproduction. *Why not:* binding the
full environment into the *reuse* key fragments the cache across every node configuration — the same
science recomputed on 32 vs 64 ranks would never hit, destroying the cache's value (the
non-associativity literature, Shanmugavelu SC24/Laguna IPDPS20, shows those runs *aren't* bitwise
identical anyway). Two tiers (§4) give cheap scientific reuse *and* honest strict-replay accounting;
Nextflow's lenient-vs-standard resume modes are the same split.

**D. Treat the UUID as identity and dedup post-hoc by scanning for equal `input_hash`.** One could
keep UUID-as-identity and run a periodic dedup pass. *Why not:* post-hoc dedup never *skips* a
calculation — the compute is already spent before the duplicate is noticed, which defeats the
primary win (active-learning re-evaluation of near-identical structures, §5). The hash must be the
*pre-execution* gate (Koji's "computable before the resource exists," Maymounkov 2019), not a
cleanup step.

**E. Cache everything, including the agent/campaign controller.** Caching LLM/agent nodes would
maximize reuse. *Why not:* closed-model versions drift and inference is non-deterministic, so a
"hit" on an agent node would silently replay a stale decision under a changed model — a correctness
hazard, not a speedup. §5 makes agent nodes `cacheable=False` and caches only their deterministic
children; this preserves ADR-023's fail-loud, human-gated posture.

**F. Hash the model weights directly for ML stages.** A literal content hash of the checkpoint file
is the most precise possible key. *Why not:* multi-GB weight blobs are expensive to hash on every
submission and the registry digest (HF repo + revision, or a CAS key) is an equally sound identity
that is cheap to compute (§5). The CAS still stores the weights once; the *hash input* is the
digest, not the bytes.

## Consequences

### Positive
- **Content-addressing becomes an enforced execution contract, not metadata.** ADR-009's recorded
  `input_hash` and ADR-013's per-edge checksum are promoted into one hash that actually *gates and
  skips* execution — closing the largest determinism gap in the 007–020 set.
- **Free cache-and-resume across the whole stack.** Re-running a campaign, restarting after a crash,
  or re-evaluating near-identical structures in an active-learning loop (ADR-021/023) reuses prior
  outputs by clone-on-hit instead of recomputing — the AiiDA/Nextflow guarantee on the *default*
  path.
- **`raw_paths` gains a real CAS** (disk-objectstore) with dedup and GC; ADR-013's restart validation
  collapses from a bespoke checksum field into a CAS lookup, and ML checkpoints become first-class
  content-addressed artifacts.
- **Caching and replay are honestly separated.** Tier-1 reuse is cheap and cross-configuration;
  Tier-2 supplies the env fingerprint + per-property tolerance contract ADR-020 lacked, so "we
  reused the science" is never conflated with "we reproduced the bits."
- **The 010/012 inconsistency is resolved** by making hash-caching backend-agnostic, with
  `sqlite_dos` AiiDA as the strict reference — determinism no longer hides behind an opt-in
  heavyweight backend.
- **Portable provenance** via opt-in Workflow Run RO-Crate carrying hashes, env fingerprints, and AI
  provenance in a cross-WMS standard.

### Negative / Tradeoffs
- **Canonicalization is now load-bearing and must be audited.** An under-broad closure causes silent
  *false hits* (wrong science reused across an incompatible binary/BLAS/MPI stack); an over-broad one
  causes *false misses*. This pushes real burden onto ADR-024's static canonicalizer and ADR-020's
  golden-file tests *over the hash function itself*, and onto a precise spec so maggma and AiiDA
  agree on identity (§6).
- **Cache invalidation is a correctness surface.** `is_valid_cache`, `CACHE_VERSION`, and the
  "code-changed-without-version" failure mode (AiiDA caching docs) must be wired correctly or a
  stale clone returns wrong results. The gate is therefore *defeasible by default* (§2): unknown
  validity ⇒ no hit.
- **CAS lifecycle is new ownership.** Packing, GC, and name-resolution for hash-named files
  (disk-objectstore) add an operational concern ADR-010 did not own; in-progress files must stay in
  scratch until sealed.
- **Per-property tolerances are physics judgments.** The Tier-2 replay contract needs curated
  per-code, per-quantity tolerances (too loose tests nothing; too tight fails on legitimate hardware
  noise) — real domain work, landing in the ReFrame regression layer paired with ADR-020.
- **Schema growth.** ADR-009 gains `content_hash` (redefined `input_hash`), `replay_hash`,
  `cached_from`, `cache_clone`, env-fingerprint, and (via ADR-023) AI-provenance fields — a
  `schema_version` bump with migration.

### Migration impact
1. Implement `crystalmath.identity.content_hash` (§1) over the canonicalized closure; **redefine**
   ADR-009 `input_hash` as this hash and add `replay_hash` + env-fingerprint fields; bump
   `schema_version`.
2. Add the pre-execution cache gate `@job` (§2) on the jobflow path via `Response(detour/replace)`;
   implement query-by-hash + defeasible validity (`completed`, `is_valid_cache`, `CACHE_VERSION`) +
   clone-on-hit writing `cached_from`/`cache_clone`.
3. Adopt disk-objectstore as the ADR-010 `additional_store` CAS (§3); migrate `raw_paths` to typed
   CAS references; re-express ADR-013 RestartValidation §2 as a CAS lookup.
4. Wire ML checkpoints and AI provenance into the closure (§5); mark agent/LLM nodes
   `cacheable=False`.
5. Implement the §6 contract on the maggma default; validate it against `sqlite_dos` AiiDA as the
   reference, asserting identical hashes on shared closures (ADR-020/024 tests).
6. Add the opt-in Workflow Run RO-Crate exporter (§7).

## References

- S. P. Huber, S. Zoupanos, M. Uhrin, L. Talirz, et al., "AiiDA 1.0, a scalable computational
  infrastructure for automated reproducible workflows and data provenance," *Scientific Data*
  **7**, 300 (2020). DOI:10.1038/s41597-020-00638-4, arXiv:2003.12476. — BLAKE2b node-hash over
  attributes + repository + input-node hashes; clone prior outputs on a match. The contract §1–§2
  port to the maggma path.
- AiiDA caching documentation (`_aiida_hash`, `_aiida_cached_from`, `CACHE_VERSION`,
  `is_valid_cache`, `_hash_ignored_attributes`),
  https://aiida.readthedocs.io/projects/aiida-core/en/latest/topics/provenance/caching.html. —
  Hash inputs, validity via `is_finished`, `CACHE_VERSION` invalidation, and the
  "code-changed-without-version" false-positive — the defeasible-cache discipline of §2.
- S. P. Huber, "Automated reproducible workflows and data provenance with AiiDA," *Nature Reviews
  Physics* **4**, 367 (2022). DOI:10.1038/s42254-022-00463-1; AiiDA disk-objectstore. — Serverless
  SHA-256 loose/packed object store backing the §3 CAS; the `sqlite_dos` profiles that refute
  ADR-010's PostgreSQL premise (§6).
- P. Di Tommaso, M. Chatzou, E. W. Floden, P. P. Barja, E. Palumbo, C. Notredame, "Nextflow enables
  reproducible computational workflows," *Nature Biotechnology* **35**, 316 (2017).
  DOI:10.1038/nbt.3820. https://www.nextflow.io/docs/latest/cache-and-resume.html — Task-hash
  cache-and-resume over script + input content + container/conda/spack; reuse only if hash *and*
  outputs valid; the lenient-vs-standard split mirrored in §4.
- C. S. Adorf, P. M. Dodd, V. Ramasubramani, S. C. Glotzer, "Simple data management with the signac
  framework," *Computational Materials Science* **146**, 220 (2018).
  DOI:10.1016/j.commatsci.2018.01.035, arXiv:1611.03543. — State-point hash as storage identity;
  the job directory *is* a hash, idempotent re-init — the §1 "hash is identity, not UUID" model.
- P. Maymounkov, "Koji: Automating pipelines with mixed-semantics data sources," arXiv:1901.01908
  (2019). — Causal hash recursive over inputs + transformation, computable *before* the resource
  exists; the §1 parent-content-hash recursion and the §2 pre-execution gate.
- H. Zheng, S. Mahmud, P. Devanbu, B. Vasilescu, et al., "Does using Bazel help speed up CI builds?,"
  arXiv:2405.00796 (2024); bazel-remote Merkle action cache. — Hermetic Merkle action
  caching/remote execution; fully specified inputs enable safe reuse — the closure-completeness
  argument of §1.
- D. Bissuel et al., "Reproducible Container Solutions for Materials Science," arXiv:2512.13826
  (2025); F. Uehlein et al., "From Code to Figure: reproducible execution and environment
  fingerprinting," arXiv:2604.25944 (2026). — Reproducible execution requires full environment
  fingerprinting (compiler/MPI/BLAS/container); grounds the Tier-2 `replay_hash` of §4.
- S. Shanmugavelu, M. Taillefumier, C. Culver, O. Hernandez, M. Coletti, A. Sedova, "Impacts of
  floating-point non-associativity on reproducibility for HPC and deep learning applications,"
  *SC24-W (Workshops of SC)*, 2024. DOI:10.1109/SCW63240.2024.00028, arXiv:2408.05148. — Bitwise
  reproducibility is unachievable under parallel FP non-associativity (MPI/OpenMP/GPU atomics) — the
  empirical basis for separating caching from bitwise replay (§4).
- I. Laguna, "Varity: Quantifying Floating-Point Variations in HPC Systems Through Randomized
  Testing," *IEEE IPDPS*, 2020. DOI:10.1109/IPDPS47924.2020.00070. — Identical inputs give
  materially different results across compilers (gcc/clang/xl/nvcc) and CPU vs GPU; motivates the
  env-fingerprint binding of §4.
- S. Soiland-Reyes, S. Leo, et al., "Recording provenance of workflow runs with RO-Crate," *PLOS
  ONE* **19**(9), e0309210 (2024). DOI:10.1371/journal.pone.0309210, arXiv:2312.07852. Profiles:
  https://www.researchobject.org/workflow-run-crate/ — The cross-WMS, W3C-PROV-aligned provenance
  bundle exported in §7, carrying hashes, env fingerprints, and AI provenance.
- A. S. Rosen, A. M. Ganose, et al., "Jobflow: Computational Workflows Made Simple," *Journal of Open
  Source Software* **9**(93), 5995 (2024). DOI:10.21105/joss.05995. — `Response(detour/replace)` as
  the pre-execution hook the §2 cache gate rides.
- CrystalMath internal: `adr-009-canonical-data-model-emmet-pydantic-taskdocs.md:114,118,119,162,166`
  (`input_hash`/`parent_job_uuids`/`raw_paths` — the advisory fields §1/§3 promote);
  `adr-010-single-result-store-jobflow-maggma.md:52,83,104,119` (the `additional_store` blob seam
  §3 turns into a CAS); `adr-013-multi-code-handoff-and-restart-validation.md:127-132,230` (the
  per-edge checksum-at-source-completion §3 generalizes into the global CAS).

## Related Issues

- ADR-009 `input_hash`/`raw_paths` advisory → enforced: this ADR is the consumer that gives them
  teeth (redefine `input_hash` as the content hash; back `raw_paths` with the CAS).
- ADR-013 RestartValidation §2 checksum → CAS lookup once the disk-objectstore lands.
- ADR-010/012 AiiDA-default inconsistency → resolved via the backend-agnostic caching contract with
  `sqlite_dos` AiiDA as the strict reference implementation.
- Companion ADRs ADR-021 (CalculatorStage / MLIP), ADR-023 (agentic planner), ADR-024 (static DAG
  validation + canonicalization audit) — to be authored alongside this one.
