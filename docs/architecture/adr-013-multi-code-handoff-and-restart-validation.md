# ADR-013: Multi-Code Handoff Contract — Typed Document Edges with Mandatory Restart-File Validation

**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** none
**Depends on:** [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md) (emmet-style TaskDocuments + lineage fields), [ADR-010](adr-010-single-result-store-jobflow-maggma.md) (canonical maggma JobStore the edges are persisted in), [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) (jobflow Flows whose edges these handoffs are), [ADR-008](adr-008-structure-and-deck-io-on-ase-pymatgen.md) (per-code deck seam over ASE/pymatgen)

## Context

CrystalMath exists to chain *different* quantum engines: the keystone product flow is
VASP → YAMBO (a converged ground-state WAVECAR/CHGCAR feeding a GW/BSE calculation), and the
CRYSTAL23 story depends on `.f9`/`.f98` wavefunction passing for `GUESSP` restarts. These are not
incidental features — they are the reason a *multi-code* manager exists rather than five
single-code wrappers. Yet today the handoff between codes is half-formed and dangerously
under-validated.

**The handoff abstraction exists but is untyped and unenforced.** A `CodeHandoff` dataclass already
lives in `python/crystalmath/integrations/atomate2_bridge.py:221` with exactly the right shape —
`(source_code, target_code, output_key, input_key, converter, validation)` plus a `transfer()`
method and a `CodeHandoffError`. But it operates on a stringly-typed `source_outputs: dict[str, Any]`
(`atomate2_bridge.py:244`): `output_key not in source_outputs` is a runtime `KeyError`-style check
against an *untyped* blob, the `validation` hook is an **optional** `Callable[[Any], bool] | None`
that defaults to `None` (`atomate2_bridge.py:242`), and nothing forces a handoff to validate the
*files* it transfers. This is the data-model weakness ADR-009 fixes for results generally
(the untyped `key_results` blob → emmet-style TaskDocuments) reaching into the cross-code seam:
a handoff is an edge between two results, and if the results are untyped, the edge is untyped too.

**Restart passing is implemented per-backend, with no shared validation.** The AiiDA path in
`python/crystalmath/workflows/aiida_launcher.py` passes a `wavefunction` node from SCF → bands
(`aiida_launcher.py:199-322`) and supports geometry-opt restart via `restart_pk`
(`aiida_launcher.py:153,189`), flipping CRYSTAL's `params["scf"]["guessp"] = True`
(`aiida_launcher.py:228`). AiiDA gets this *right* because its provenance graph makes the input
node content-addressed and immutable — you cannot pass a stale file because the file *is* a
hashed Data node. But the **default, non-AiiDA path has no equivalent guard.** Outside AiiDA there
is no enforcement that the WAVECAR a YAMBO step reads actually came from the VASP step that claims
to have produced it.

**This is a known, documented, silent-wrong-result failure mode.** `.planning/research/PITFALLS.md`
Pitfall #4 ("VASP Restart File Confusion After Failed Calculations") states the danger precisely:
"Restarted VASP calculations read stale WAVECAR/CHGCAR files from a previous failed run, leading to
incorrect results" (`PITFALLS.md:121`); "WAVECAR is only written when calculation completes, not
mid-SCF" (`PITFALLS.md:126`); "Parallelization settings (NBANDS, KPAR) must match between restart and
original run" (`PITFALLS.md:127`). The consequence list leads with **"Silently incorrect calculation
results"** and **"Non-reproducible research"** (`PITFALLS.md:130-133`). The detection signs —
"OUTCAR timestamps don't match job submission time", "Restart calculation converges suspiciously
fast" (`PITFALLS.md:143-145`) — are exactly the kind of error a TUI user will *not* catch by eye.
The same pitfall's prevention list already prescribes the fix: positive file matching, timestamp
verification, NBANDS/KPAR in restart metadata, checksum validation (`PITFALLS.md:136-139`).

**The ecosystem has converged on how to do cross-engine handoff and restart safety.** The
canonical reference is Huber et al., "Common workflows for computing material properties using
different quantum engines" (npj Comput. Mater. 7, 136, 2021, arXiv:2105.05063), which defines a
*code-agnostic* common-workflow interface (relax, EOS, bands) implemented identically across QE,
VASP, CASTEP, Siesta, FLEUR, etc. — the edges between steps are typed by the property being passed
(a relaxed `Structure`, a band path), not by per-code dict keys. Phonopy's native interfaces
(VASP/QE/CRYSTAL/ABINIT/…, https://phonopy.github.io/phonopy/interfaces.html) are the concrete
proof that a single code-agnostic force-set contract can drive many engines: phonopy consumes a
*typed* displacement→force-set artifact and never cares which code produced it. On the restart-safety
side, atomate2/custodian's **"positive file matching"** — copy *only* the explicitly-required restart
files, never the whole previous directory — is the precise antidote to PITFALLS #4 and is named in
the pitfall's own prevention list (`PITFALLS.md:136`). The lesson across all three is the same: the
hard, valuable part of multi-code work is **standardizing the typed schema of what crosses the
boundary**, and the dangerous part is letting raw files cross it unvalidated.

ADR-009 gives us the substrate: one typed result schema (emmet-style versioned pydantic
TaskDocuments, one per code) written into one maggma JobStore, with lineage fields (parent-job
uuids, input hashes, content-addressed raw-file paths) on every document. ADR-008 gives us one
per-code deck/InputGenerator seam. This ADR makes the *edge* between those documents a first-class,
typed, validated object.

## Decision

Formalize **`CodeHandoff` as a code-agnostic typed edge between TaskDocuments**, and make
restart-file validation **mandatory and positive** — not an optional hook.

### 1. `CodeHandoff` is a typed edge between TaskDocuments, not a dict transformer

Promote `CodeHandoff` out of `integrations/atomate2_bridge.py` into a first-class
`crystalmath.handoff` module and re-type it against the ADR-009 document model:

```python
class CodeHandoff(BaseModel):
    source_code: str           # e.g. "vasp"
    target_code: str           # e.g. "yambo"
    artifact: HandoffArtifact  # WAVEFUNCTION | CHARGE_DENSITY | STRUCTURE | FORCE_SET | ...
    converter: Converter | None = None   # typed, code-pair-specific (e.g. p2y for VASP→YAMBO)
    validation: RestartValidation         # REQUIRED, not Optional — see §3

    def transfer(self, source: TaskDocument) -> HandoffInput: ...
```

- The input is a **typed `TaskDocument`** (ADR-009), not `dict[str, Any]`. `artifact` selects a
  *typed* field/file-reference on the source document (the content-addressed raw-file path ADR-009
  stores), eliminating the `output_key not in source_outputs` stringly-typed lookup at
  `atomate2_bridge.py:257`.
- `artifact` is a closed enum of code-agnostic *physical* quantities (wavefunction, charge density,
  relaxed structure, phonon force set), mirroring the common-workflows interface (Huber 2021) and
  phonopy's force-set contract. A handoff is named by *what crosses* (a wavefunction), not by which
  code keys it lives under.
- `converter` carries the code-pair-specific transform as a typed step — for VASP→YAMBO this is the
  `p2y`/`ypp` init that converts a VASP/QE ground state into YAMBO's database format (the init steps
  that beefcake2 `docs/hpc/WORKFLOW-VASP-TO-YAMBO.md` documents and that ADR-012's execution layer
  must run under `sbatch`, never on a login node).

### 2. Handoffs are edges in the jobflow Flow, persisted as lineage

A multi-code chain is a jobflow `Flow` (per the workflow-engine decision) whose edges are
`CodeHandoff`s. When a handoff fires, it records itself on the **target** document's lineage fields
(ADR-009): the target document's `parent_job_uuids` includes the source job uuid, and a
`restart_inputs` field records, per transferred file, the **content hash + source path + source
job uuid + validated parallelization metadata** (NBANDS/KPAR for VASP; basis/shrink for CRYSTAL).
This makes even the default (non-AiiDA) path reproducible and auditable — you can always answer
"which exact WAVECAR did this GW run consume, and from which job?" — borrowing AiiDA's
input/create-link guarantee as data on the pydantic document rather than requiring AiiDA's graph DB.

### 3. Restart-file validation is MANDATORY and POSITIVE

The `validation` field is **not** `Optional`. Every `CodeHandoff` that transfers a restart file
runs `RestartValidation` before the target job is allowed to start. Validation has three required
checks, directly implementing PITFALLS #4's prevention list (`PITFALLS.md:136-139`):

1. **Positive file matching.** Copy/symlink *only* the explicitly-declared restart artifacts for the
   `(source_code, target_code, artifact)` triple — never the whole previous work directory. This is
   atomate2/custodian's positive-matching discipline (`PITFALLS.md:136`) and is what prevents a stale
   `OUTCAR`/`vasprun.xml` from a *failed* run masquerading as valid (`PITFALLS.md:124-125`).
2. **Provenance match (checksum + source linkage).** The transferred file's content hash must equal
   the hash recorded on the **source** TaskDocument when that job *successfully completed*. A
   handoff from a source document whose state is not `completed` (ADR-009 status field) is rejected —
   "WAVECAR is only written when calculation completes, not mid-SCF" (`PITFALLS.md:126`). Timestamp
   is checked as a corroborating signal ("OUTCAR timestamps don't match job submission time",
   `PITFALLS.md:144`), but the **checksum + source-completion** is authoritative.
3. **Parallelization consistency.** For artifacts that depend on it (VASP WAVECAR), the target's
   NBANDS/KPAR must be consistent with the values recorded on the source document
   (`PITFALLS.md:127,138`). For CRYSTAL `.f9` GUESSP restarts, the basis set and `SHRINK` grid must
   match. A mismatch is a hard `RestartValidationError`, never a warning.

A failed validation raises `RestartValidationError` (a `CodeHandoffError` subtype) and **blocks the
target job from being submitted.** There is no "best effort" or silent-degrade path — this is the
direct analogue of ADR-011's "no silent simulated success" rule and ADR-008's fail-fast
`DeckStagingError`: a handoff that cannot prove its restart file is correct must fail loudly, because
the alternative is a silently-wrong published result (`PITFALLS.md:130`).

### 4. The CRYSTAL `.f9`/VASP WAVECAR/QE handoffs are the first three concrete implementations

- **CRYSTAL SCF → bands/properties** (`.f9`/`.f98`, `artifact=WAVEFUNCTION`): validates basis +
  SHRINK match, flips `GUESSP`, records the `.f9` hash on the bands document. Replaces the bespoke
  AiiDA-only path at `aiida_launcher.py:199-322` with a backend-agnostic edge that the default store
  also enforces.
- **VASP → YAMBO** (`WAVECAR`+`CHGCAR` → YAMBO DB via `p2y`/`ypp`, `artifact=WAVEFUNCTION`+
  `CHARGE_DENSITY`): the keystone chain; the `converter` runs the p2y/ypp init (under `sbatch`),
  validation enforces NBANDS/KPAR + completion. This is what makes ADR-009's "VASP→YAMBO" product
  goal real and safe.
- **VASP/QE → phonopy** (`artifact=FORCE_SET`): typed force-set edge mirroring phonopy's native
  code-agnostic interface (https://phonopy.github.io/phonopy/interfaces.html).

AiiDA, when enabled as the opt-in heavyweight backend, satisfies the same `RestartValidation`
contract for free via its content-addressed Data nodes — the contract is the seam; AiiDA is one
(maximally-strict) implementation of it, the default maggma path is the other.

## Alternatives Considered

**A. Keep `CodeHandoff` as an untyped dict transformer with an optional `validation` hook
(status quo).** *Why not:* this is exactly the current `atomate2_bridge.py:221-274` design, and it
is the failure mode this ADR exists to kill. An `Optional` validation callable defaulting to `None`
(`atomate2_bridge.py:242`) means the safe path is opt-in and the dangerous path is the default —
the inverse of what PITFALLS #4 demands. Stringly-typed `source_outputs` lookups give a `KeyError`
at best and a *wrong-but-present* value at worst. With zero users we have no reason to preserve it.

**B. Delegate all handoff + restart logic to AiiDA and require AiiDA for any multi-code chain.**
AiiDA's provenance graph is the gold standard for exactly this problem — immutable, content-addressed
Data nodes mean a stale file is structurally impossible, and its common-workflows interface
(Huber et al., npj Comput. Mater. 7, 136, 2021, arXiv:2105.05063) is the reference design for
code-agnostic edges. *Why not as the only path:* it imposes AiiDA's PostgreSQL/RabbitMQ operational
tax (Huber et al., Sci. Data 7, 300, 2020, arXiv:2003.12476) on the laptop-first TUI user for whom
ADR-009 deliberately defaults to a serverless maggma store. We adopt AiiDA's *guarantee* as a
contract (`RestartValidation`) that the default store must also satisfy, and keep AiiDA as the
opt-in implementation that satisfies it most rigorously — getting the provenance guarantee without
mandating the provenance database.

**C. Pass raw output directories between steps and let each code's input generator pick what it
needs ("copy the whole previous dir").** This is the most common ad-hoc approach and the literal
cause of PITFALLS #4: custodian/atomate2 found that copying a previous step's full directory lets a
stale `OUTCAR`/`vasprun.xml` from a *failed* run look valid (`PITFALLS.md:124-125`), which is why the
ecosystem moved to **positive file matching** — copy only required restart files
(`PITFALLS.md:136`). *Why not:* it is the known-bad pattern; §3.1 adopts the ecosystem's positive
matching instead.

**D. Express handoffs only as jobflow `OutputReference`s (jobflow's native data-passing) with no
CrystalMath-level type or validation.** jobflow's `OutputReference` cleanly wires one job's output to
another's input within a Flow (Rosen et al., JOSS 9(93), 5995, 2024) and we *use* it as the wiring
mechanism (§2). *Why not as the whole answer:* an `OutputReference` is a *connection*, not a
*validated physical edge* — it carries no notion of "this is a wavefunction whose NBANDS must match"
or "the source must be completed before its WAVECAR is trusted." jobflow gives us the graph edges;
`CodeHandoff` + `RestartValidation` give those edges *physical meaning and safety*. We layer the
typed contract on top of jobflow's reference mechanism rather than replacing it.

**E. Validation as a post-hoc warning / detector rather than a blocking gate.** PITFALLS #4 lists
detection signs (suspiciously fast convergence, timestamp mismatch — `PITFALLS.md:143-145`) that
could be surfaced as warnings after the fact. *Why not:* by the time those signs appear the wasted
compute is already spent and a wrong result may already be in the store and reported to the user.
The whole point is to fail *before* the doomed target job is submitted (`PITFALLS.md:131`), so
validation must be a pre-submission gate, consistent with the project's fail-loud posture.

## Consequences

### Positive
- **Eliminates the stale-WAVECAR silent-wrong-result failure mode** (PITFALLS #4) on the *default*
  path, not just under AiiDA. The single most consequential correctness bug class for a multi-code
  manager is closed by construction.
- **One typed, code-agnostic handoff contract** drives every cross-code chain (CRYSTAL `.f9`,
  VASP→YAMBO, →phonopy), so adding a new chain is declaring a typed edge, not writing bespoke
  per-backend transfer code (replacing the AiiDA-only path at `aiida_launcher.py:199-322`).
- **Reproducibility on the lightweight path:** every restart records source-job uuid + content hash +
  parallelization metadata on the target document (ADR-009 lineage fields), so non-AiiDA results are
  auditable — borrowing AiiDA's input-link guarantee as data, without AiiDA's database.
- **Edges align with the data model and engine** (ADR-009 TaskDocuments, jobflow Flows): the handoff
  is literally an edge between two documents in the canonical store, not a side-channel.

### Negative / Tradeoffs
- **Per-code restart-validation knowledge must be encoded** (which files, which parallelization
  invariants) for each `(source, target, artifact)` triple. This is real work, but it is the
  *valuable* work the ecosystem (Steensen 2025; Huber 2021) identifies as the hard part of
  interoperability — and it is bounded to the handful of chains CrystalMath actually supports.
- **Validation can reject a chain a user "knows" is fine** (e.g. an intentional NBANDS change on
  restart). Mitigation: an explicit, logged, per-handoff override (`metadata["allow_restart_skew"]`)
  that mirrors the `allow_stub_execution` gate — opt-in, never silent.
- **Checksums on large restart files** (multi-GB WAVECAR) add I/O cost at handoff time. Mitigation:
  hash is computed once at *source completion* (when the file is already being written to the store)
  and recorded on the source document, so the handoff compares stored hashes rather than re-hashing.

### Migration impact
- Move `CodeHandoff` from `integrations/atomate2_bridge.py:221` to `crystalmath.handoff`, re-typed
  against ADR-009 `TaskDocument`; make `validation` required and add `RestartValidation`.
- Re-express the AiiDA-only SCF→bands wavefunction passing (`aiida_launcher.py:199-322`) and the
  `restart_pk`/GUESSP geometry restart (`aiida_launcher.py:153-228`) as `CodeHandoff` edges so the
  default backend enforces the same guarantees.
- Implement the three concrete handoffs (CRYSTAL `.f9`, VASP→YAMBO, →phonopy). VASP→YAMBO depends on
  ADR-012's `sbatch`-only execution for the p2y/ypp converter steps.
- Add lineage fields (`parent_job_uuids`, `restart_inputs`) to the ADR-009 TaskDocument schema if not
  already present; this ADR is the consumer that gives them teeth.

## References

- S. P. Huber, E. Bosoni, M. Bercx, J. Bröder, A. V. Yakutovich, et al., "Common workflows for
  computing material properties using different quantum engines," *npj Computational Materials*
  **7**, 136 (2021). DOI:10.1038/s41524-021-00594-6, arXiv:2105.05063. — Code-agnostic
  common-workflow interface; the reference design for typed cross-engine edges.
- S. P. Huber, S. Zoupanos, M. Uhrin, et al., "AiiDA 1.0, a scalable computational infrastructure
  for automated reproducible workflows and data provenance," *Scientific Data* **7**, 300 (2020).
  DOI:10.1038/s41597-020-00638-4, arXiv:2003.12476. — Content-addressed Data nodes / input links;
  the provenance guarantee `RestartValidation` reproduces on the default path.
- A. S. Rosen, A. M. Ganose, et al., "Jobflow: Computational Workflows Made Simple," *Journal of
  Open Source Software* **9**(93), 5995 (2024). DOI:10.21105/joss.05995. — `Flow`/`OutputReference`
  wiring on which `CodeHandoff` edges are layered.
- Phonopy native code interfaces (VASP/QE/CRYSTAL/ABINIT/…),
  https://phonopy.github.io/phonopy/interfaces.html. — Proof that one code-agnostic force-set
  contract drives many engines; the `FORCE_SET` artifact model.
- S. K. Steensen et al., "The Interoperability Challenge in DFT Workflows Across Implementations,"
  (2025), arXiv:2511.11524. — Code-specific restart/IO idiosyncrasies are the real cost of
  multi-code work; argues for standardizing the boundary schema.
- Custodian VASP handlers (positive file matching, restart handling),
  http://materialsproject.github.io/custodian/custodian.vasp.handlers.html. — Source of the
  positive-file-matching discipline adopted in §3.1.
- CrystalMath internal: `.planning/research/PITFALLS.md` Pitfall #4 ("VASP Restart File Confusion
  After Failed Calculations", `PITFALLS.md:119-152`) — the concrete failure mode and prevention list
  this ADR mandates; `integrations/atomate2_bridge.py:221-274` (current `CodeHandoff`);
  `workflows/aiida_launcher.py:153-322` (AiiDA-only restart/wavefunction passing).
- Depends on [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md) (typed TaskDocuments +
  lineage fields), [ADR-010](adr-010-single-result-store-jobflow-maggma.md) (maggma JobStore),
  [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) (jobflow Flows), and
  [ADR-008](adr-008-structure-and-deck-io-on-ase-pymatgen.md) (per-code deck seam).
