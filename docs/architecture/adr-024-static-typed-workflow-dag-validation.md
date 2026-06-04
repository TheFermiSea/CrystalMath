# ADR-024: Static typed workflow/DAG validation: `crystalmath validate` before any submission

**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** none (extends [ADR-016](adr-016-wire-contract-codegen-no-drift.md)'s "drift is a build failure, not a runtime error" principle from the Rust↔Python wire inward to the scientific DAG)
**Depends on:** [ADR-016](adr-016-wire-contract-codegen-no-drift.md) (the static-validation template — pydantic-as-source-of-truth → generated/checked artifact → CI failure), [ADR-013](adr-013-multi-code-handoff-and-restart-validation.md) (the typed `CodeHandoff` edge + `HandoffArtifact` enum this checker type-checks), [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) (the jobflow `Flow` whose `OutputReference` edges are walked), [ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md) (every `CalculatorStage` — DFT and MLIP — declares the typed input/output signature this pass reads)
**Backstopped by:** [ADR-013](adr-013-multi-code-handoff-and-restart-validation.md) runtime `RestartValidation` gate (demoted from sole guardian to second-line backstop for values only knowable at run time)
**Pairs with:** [ADR-020](adr-020-reproducibility-and-golden-file-testing.md) (revised — the test-time/physics complement; this ADR draws the crisp compile-time/test-time boundary)
**Invoked by:** [ADR-023](adr-023-agentic-control-plane-mcp-ai-provenance.md) (the `validate_workflow` MCP verb runs this pass on agent-proposed Flows before the `submit_campaign` gate)

## Context

CrystalMath exists to chain *different* engines — the keystone product flow is VASP → YAMBO (a
converged WAVECAR feeding GW/BSE through a `p2y`/`ypp` init), and ADR-021 makes MLIP stages
first-class peers of DFT stages on the same DAG. ADR-013 already gives the cross-code edge the
*right shape*: a typed `CodeHandoff` over a **closed** `HandoffArtifact` enum
(`WAVEFUNCTION | CHARGE_DENSITY | STRUCTURE | FORCE_SET | …`,
`adr-013-multi-code-handoff-and-restart-validation.md:86,98-100`) with a **mandatory positive**
`RestartValidation` that blocks a target job before submission
(`adr-013-multi-code-handoff-and-restart-validation.md:138-142`). But ADR-013's contract is checked
**only at run time, edge by edge, when the edge fires** — `RestartValidation` is a per-handoff gate
that runs as a `@job` in the live Flow. Nothing proves the *whole* multi-code DAG is sound *before*
a single job is queued.

**This leaves a class of errors that cost hours of compute to discover.** A campaign can be
structurally wrong in ways that are statically knowable yet are caught only after the producing job
has already run: a YAMBO stage wired to consume a `WAVEFUNCTION` from a stage that emits no WAVECAR
(an MLIP `MlipCalculatorStage`, per ADR-021, emits *zero files* —
`adr-021-calculatorstage-mlip-foundation-calculators.md`); a `p2y` converter sourced from a code that never
produced the database YAMBO needs; an NBANDS/KPAR or `SHRINK`/basis mismatch that ADR-013 will
reject *at the handoff* but only after the upstream SCF has burned its allocation. ADR-013's own
Alternative E rejected post-hoc detection precisely because "by the time those signs appear the
wasted compute is already spent"
(`adr-013-multi-code-handoff-and-restart-validation.md:198-203`) — yet a per-edge runtime gate is
still *late* relative to the producing job: it fires after the producer completes, not before the
campaign is queued.

**The set has exactly one static-validation discipline, and it stops at the wire.** ADR-016 turns a
parity invariant into a build failure: pydantic models are the single source of truth, exported to
`schema/wire-contract.json`, typified into Rust serde types in `build.rs`, so "drift is a CI/build
failure, not a runtime error" (`adr-016-wire-contract-codegen-no-drift.md:52-101,189-191`). But
ADR-016 is scoped strictly to the Rust↔Python **wire** (the ~50 IPC methods + the `TaskDocument`
family) and explicitly admits "JSON Schema can't express everything"
(`adr-016-wire-contract-codegen-no-drift.md:189-191`). It says nothing about the *scientific* DAG:
a jobflow Flow's `OutputReference` edges (`adr-011-workflow-engine-jobflow-atomate2-quacc.md:70`)
are wired and validated only when a job runs. The "drift is a build failure" principle is the right
one; it simply has not been pointed inward from the wire to the deck/flow.

**The ecosystem outside materials science has converged on pre-execution whole-DAG type-checking.**
CWL's reference runner `cwltool` ships a `static_checker` that, *before any execution*, verifies
every `source → sink` edge in the workflow is type-compatible and raises a `ValidationException` on
mismatch; `cwltool --validate` parses and type-checks the entire document **without running it**
(https://cwltool.readthedocs.io/en/latest/autoapi/cwltool/checker/index.html). WDL has the identical
posture via `womtool`/`wdlTools` type-checking, and Nextflow's channels are statically structured so
that a malformed pipe is a parse-time error, not a runtime one. CrystalMath's ADR-013 `CodeHandoff`
is *already* the CWL `source → sink` edge — a typed physical-artifact edge over a closed enum — but
it is checked at the wrong time. And the multi-code half of the problem is well documented: Steensen
et al. (arXiv:2511.11524, 2025) catalogue the code-specific idiosyncrasies that break naive
cross-engine handoff — exactly the structural mismatches a pre-submission type-checker should refuse.

ADR-021 supplies the missing precondition: every `CalculatorStage` — `DftCalculatorStage` (the
ADR-008 `CodeDeckGenerator`/`InputDeck` specialization) and `MlipCalculatorStage` (a thin wrapper
over an ASE `Calculator` keyed by a content-addressed checkpoint) — declares a **typed input/output
signature**. Once every stage declares what it consumes and emits, the entire DAG becomes statically
type-checkable. This ADR makes that check a first-class, offline, pre-submission pass.

## Decision

**Add an offline static type-checker, invoked as `crystalmath validate`, that walks the jobflow
`Flow` and proves the entire multi-code DAG sound *before any scheduler submission* — modeled on
`cwltool`'s `static_checker` / `--validate` and WDL `womtool` type-checking.** Drift in the
scientific DAG becomes a validation failure at build/lint/pre-submit time, not a runtime error after
compute is spent. ADR-013's runtime `RestartValidation` is **demoted** from sole guardian to a
second-line backstop for values only knowable at run time.

### 1. `crystalmath validate` is a whole-document, offline, pre-submission pass

A new `crystalmath.validate` module exposes `validate_flow(flow: Flow) -> ValidationReport`, surfaced
as the `crystalmath validate` CLI verb and as the ADR-023 `validate_workflow` MCP tool. It walks the
jobflow `Flow`'s `OutputReference` edges (`adr-011-workflow-engine-jobflow-atomate2-quacc.md:70`) and
the `CodeHandoff`s layered on them (ADR-013 §2) **without submitting anything to any
`ExecutionBackend`** (ADR-012) — the exact `cwltool --validate` posture: type-check the whole
document, run nothing. A mismatch raises a `WorkflowValidationError` enumerating *every* offending
edge (not just the first), mirroring `cwltool`'s `static_checker` raising on `source → sink`
incompatibility. `crystalmath submit` runs `validate_flow` as a mandatory precondition; a Flow that
fails validation is never queued.

### 2. Three static proofs over the DAG

For every edge and stage in the Flow, the pass statically proves:

1. **Artifact type match (the `source → sink` check).** Every ADR-013 `CodeHandoff` edge's
   `artifact` (`HandoffArtifact` — the closed enum at
   `adr-013-multi-code-handoff-and-restart-validation.md:86,98-100`) must be **declared in the
   producing `CalculatorStage`'s output signature** *and* **required by the consuming stage's input
   signature** (ADR-021). This is `cwltool`'s type-compatibility check applied to physical artifacts:
   a stage that does not declare `WAVEFUNCTION` in its outputs cannot source a `WAVEFUNCTION` edge,
   and a stage that requires a `FORCE_SET` input cannot be fed a `STRUCTURE`. Because the enum is
   closed (ADR-013) and the signatures are typed (ADR-021), this is a finite, decidable check.

2. **Calculator/code compatibility.** Only a stage whose *code* actually emits a given artifact may
   source an edge that requires it. Concretely: only a stage that emits a VASP/QE WAVECAR can source
   a `VASP → p2y → YAMBO` edge; an `MlipCalculatorStage` (zero files, ADR-021) can never source a
   `p2y` converter edge. This encodes the Steensen et al. (arXiv:2511.11524) cross-engine
   idiosyncrasies as a static compatibility table keyed by `(source_code, artifact, converter)` —
   refusing at validate-time the code-pair handoffs that are physically impossible.

3. **Static parallelization/resource satisfiability.** The parallelization invariants ADR-013's
   `RestartValidation` checks at run time (`adr-013-multi-code-handoff-and-restart-validation.md:133-136`)
   are checked *statically* where the values are declared in the deck rather than discovered in the
   output: VASP NBANDS/KPAR consistency across a restart edge, CRYSTAL `SHRINK`-grid/basis match
   across a `.f9` `GUESSP` edge. These are deck-declared inputs (ADR-008), so a mismatch is provable
   before either job runs — catching at validate-time what ADR-013 would otherwise catch only after
   the producer completes.

### 3. Every `CalculatorStage` must declare a typed input/output signature

This pass has a hard precondition on ADR-021: **each `CalculatorStage` declares a typed
`(inputs: frozenset[HandoffArtifact], outputs: frozenset[HandoffArtifact])` signature.** This is
mandatory for *both* specializations — `DftCalculatorStage` (whose outputs derive from the ADR-008
deck/`InputSet` and the code's known products) and `MlipCalculatorStage` (whose signature declares
energy/forces/stress in, **zero file artifacts out** — the seam that lets the checker prove an MLIP
stage can never source a WAVECAR edge). The signature is the static contract the type-checker reads;
ADR-021 owns its shape, this ADR owns walking it. The signatures are themselves pydantic models, so
they participate in ADR-016's codegen-no-drift discipline and cannot silently diverge from the
`HandoffArtifact` enum they reference.

### 4. ADR-013's runtime `RestartValidation` is demoted to a second-line backstop

A static checker **cannot** validate values only knowable at run time: whether the WAVECAR a stage
*declares* it will emit actually converged, whether the file is non-empty, whether the on-disk
content hash matches at handoff time. Those remain ADR-013 `RestartValidation`'s job — but it is no
longer the *sole* guardian. The division is crisp:

- **`crystalmath validate` (compile-time, this ADR):** structural/type/schema soundness of the whole
  DAG — does this campaign's wiring make sense *as written*, before anything is queued.
- **`RestartValidation` (run-time, ADR-013):** the second line of defense — did the file the static
  edge promised *actually* get produced, converged, and content-match when the edge fired.

This makes ADR-013's "fail before the doomed target job is submitted"
(`adr-013-multi-code-handoff-and-restart-validation.md:198-203`) strictly stronger: the static pass
fails before the *producer* is submitted, and the runtime gate catches what only the run can reveal.

### 5. Dynamically materialized sub-DAGs are re-validated on materialization

ADR-023's adaptive loops and ML escalation, and ADR-011's error recovery, emit sub-DAGs at run time
via jobflow `Response(detour | replace)`
(`adr-011-workflow-engine-jobflow-atomate2-quacc.md`). A static checker run only ahead-of-time would
never see those edges. Therefore **`validate_flow` MUST be callable both ahead-of-time (on the
submitted Flow) and on dynamically materialized sub-DAGs** at the moment a `Response` produces them,
before the new jobs are queued. To keep this tractable for adaptive ML/agent loops whose shape is not
fully known up front, the static signature of a detour-emitting stage may declare **open detour
points** — a typed "here a sub-DAG of kind K will be inserted" placeholder that the ahead-of-time
pass accepts and the on-materialization pass discharges against the concrete sub-DAG. An un-validated
sub-DAG is never queued; this is the run-time analogue of §1's pre-submission gate, and it is how the
static discipline survives ADR-023's agentic, dynamically-composed campaigns.

### 6. Crisp boundary with ADR-020 — no duplicated coverage

ADR-016 and ADR-024 own **structural / schema / type checking (compile-time)**: does the wire match
(016), does the DAG type-check (024). ADR-020 owns **physics / behavioral / metamorphic checking
(test-time)**: golden-file deck regression, Hypothesis property/metamorphic/symmetry tests, real
canned-DFT parser fixtures, per-property scientific tolerances
(`adr-020-reproducibility-and-golden-file-testing.md`). The line is bright: 024 proves a campaign is
*well-typed*; 020 proves a deck-generator is a *deterministic pure function* and that parsed physics
falls within tolerance. A constraint that is *schema-shaped* (artifact type, NBANDS declared) is
024's; a constraint that is *physics-shaped* (does this functional converge, is this energy within
1e-6 Ha) is 020's. Neither re-implements the other.

## Alternatives Considered

**A. Keep validation runtime-only (status quo): rely solely on ADR-013's per-edge
`RestartValidation`.** *Why not:* ADR-013's gate is correct but *late* — it fires when an edge fires,
i.e. *after* the producing job completes. A structurally impossible campaign (MLIP stage sourcing a
WAVECAR edge; YAMBO fed by a code that emits no database) is statically knowable, yet the runtime gate
discovers it only after the upstream SCF has spent its allocation. ADR-013's own Alternative E rejects
post-hoc detection for exactly this reason (`adr-013-multi-code-handoff-and-restart-validation.md:198-203`).
A pre-submission static pass catches the whole structural class in seconds; the runtime gate stays as
the backstop for what only the run can reveal (§4).

**B. Extend ADR-016's wire-contract codegen to also generate the DAG checker (one mechanism).**
ADR-016's pydantic → JSON Schema → `typify` pipeline is the template, and reusing it is tempting.
*Why not as the whole answer:* JSON Schema "can't express everything"
(`adr-016-wire-contract-codegen-no-drift.md:189-191`), and DAG soundness is a *graph-reachability*
property (does every sink's required artifact have a type-compatible source upstream), not a
per-message shape property. JSON Schema validates a single document's shape; it cannot express "edge
e's source stage declares artifact a in its outputs." We *reuse* ADR-016's discipline (the stage
signatures and `HandoffArtifact` enum are codegen-checked pydantic, so they can't drift) but the
graph walk itself is a purpose-built pass over the jobflow `Flow`, the way `cwltool`'s `static_checker`
is a dedicated module, not a JSON-Schema rule.

**C. Validate the DAG only at test time via ADR-020's property/metamorphic suite.** One could assert
DAG well-typedness with Hypothesis tests over generated Flows. *Why not:* test-time validation checks
the *factory code* on CI inputs, not the *specific campaign a user (or ADR-023 agent) composes at
run time*. A novel agent-proposed Flow that no test ever generated would sail past CI and fail only
when submitted. Static validation must run on the *actual* Flow about to be queued (§1, §5), which is
a per-campaign pre-submission act, not a CI-time property. The boundary in §6 keeps 020 for physics
and 024 for structure precisely so neither leans on the other for coverage it cannot provide.

**D. Adopt CWL/WDL as the workflow language to get their type-checkers for free.** `cwltool`'s
`static_checker` and `womtool` are mature and exactly the prior art. *Why not:* ADR-011 already
committed to jobflow `Flow` as the *one* workflow model, and rewriting the orchestration layer in CWL
to borrow its checker would reopen a locked decision and discard the atomate2/quacc recipe library.
The right move is to *port the discipline*, not the language: implement `cwltool`'s whole-document,
pre-execution, `source → sink` type-checking pattern over jobflow's native `OutputReference`/`Flow`
graph, exactly as ADR-013 ported AiiDA's content-addressed guarantee onto the maggma path rather than
mandating AiiDA.

**E. Make the checker an advisory linter (warn, don't block).** A non-blocking `crystalmath lint`
could surface DAG smells without gating submission. *Why not:* this is ADR-013's rejected "post-hoc
warning" posture (`adr-013-multi-code-handoff-and-restart-validation.md:198-203`) relocated to
compile-time. The value of a static pass is that it *blocks* a doomed campaign before compute is
spent; an advisory warning the user can ignore reintroduces the silent-wrong-campaign failure mode.
Validation is a hard pre-submission gate, consistent with the project's fail-loud posture
(`adr-011-workflow-engine-jobflow-atomate2-quacc.md:110-117`,
`adr-013-multi-code-handoff-and-restart-validation.md:138-142`), with a single explicit, logged
override mirroring `allow_stub_execution` / `allow_restart_skew` for the rare case a user knowingly
submits an edge the checker cannot prove sound.

## Consequences

### Positive
- **Whole classes of misconfigured campaigns fail in seconds, not hours.** Wrong-artifact edges,
  incompatible code pairs, and NBANDS/KPAR/`SHRINK` mismatches are caught before *any* job is queued,
  closing the gap between ADR-013's per-edge runtime gate (which fires after the producer runs) and
  the cost of the wasted allocation.
- **The "drift is a build failure" principle reaches the science.** ADR-016's discipline now covers
  not just the Rust↔Python wire but the scientific DAG — a mis-wired multi-code handoff is a
  validate-time failure, the inward extension ADR-016's scope (`adr-016-...:52-101`) lacked.
- **ADR-013 is strengthened, not duplicated.** Its runtime `RestartValidation` becomes a focused
  backstop for run-time-only facts (convergence, content-hash-at-handoff), while structural soundness
  moves earlier and proves the whole DAG at once.
- **Agentic and ML-in-the-loop campaigns stay safe.** ADR-023's agent-proposed Flows are validated by
  the same pass before the `submit_campaign` gate, and ADR-023's / ADR-011's dynamically materialized
  sub-DAGs are re-validated on materialization (§5) — agent output is never executed unvalidated.
- **One uniform check across DFT and MLIP.** Because ADR-021 makes every stage declare a typed
  signature, the checker treats DFT and MLIP stages identically; "MLIP emits zero files" is not a
  special case but a declared signature the type system enforces.

### Negative / Tradeoffs
- **Every `CalculatorStage` must declare a typed I/O signature (a hard precondition on ADR-021),
  including the ML/foundation stages.** This is real authoring work and a coupling to ADR-021's
  rollout — a stage with no declared signature cannot be validated, so the checker is only as complete
  as the signatures it reads. Mitigation: signatures are codegen-checked pydantic (ADR-016), so an
  undeclared or drifted signature is itself a build failure.
- **A static checker cannot prove run-time facts** (did the WAVECAR converge, is it non-empty, does
  the hash match at handoff). This is by design — those stay ADR-013's backstop (§4) — but it means
  `crystalmath validate` passing is necessary, not sufficient, for a correct run.
- **Dynamic detours need an "open detour point" escape hatch (§5).** Fully static checking of
  adaptive ML/agent loops whose shape is unknown up front is impossible; the open-detour placeholder
  is a deliberate, bounded relaxation, discharged by the on-materialization re-validation. Over-using
  it would erode the guarantee, so detour-kinds should be as narrowly typed as the loop allows.
- **A second validation surface alongside ADR-013's runtime gate** means the artifact/parallelization
  knowledge is expressed in two places (static signature + runtime check). Mitigation: both read the
  *same* closed `HandoffArtifact` enum and the *same* deck-declared parallelization fields, so they
  cannot disagree on vocabulary — the static pass checks declarations, the runtime gate checks the
  realized values of those same declarations.

### Migration impact
1. Add `crystalmath.validate` with `validate_flow(flow) -> ValidationReport` and the three static
   proofs (§2); raise `WorkflowValidationError` enumerating all offending edges.
2. Add the `crystalmath validate` CLI verb and wire `crystalmath submit` to run it as a mandatory
   precondition; expose it as ADR-023's `validate_workflow` MCP tool.
3. Land the ADR-021 precondition: every `CalculatorStage` declares its typed
   `(inputs, outputs)` `HandoffArtifact` signature (DFT *and* MLIP), as codegen-checked pydantic.
4. Hook the dynamic path: have jobflow `Response(detour|replace)` materialization (ADR-011/ADR-023)
   call `validate_flow` on the new sub-DAG before its jobs are queued; define the open-detour-point
   placeholder type.
5. Demote ADR-013's `RestartValidation` documentation to "second-line backstop," cross-referencing
   this ADR for the compile-time half; add the single `allow_*` override for knowingly-skewed edges.
6. Add golden/negative validation fixtures (a known-bad DAG must raise `WorkflowValidationError`)
   under ADR-020's test suite, keeping the §6 boundary: 024 fixtures assert *structural* rejection,
   not physics.

## References

- cwltool reference implementation — `static_checker` module and the `--validate` option:
  https://cwltool.readthedocs.io/en/latest/autoapi/cwltool/checker/index.html and
  https://cwltool.readthedocs.io/en/stable/cli.html. — The concrete prior art: `static_checker`
  proves every `source → sink` edge type-compatible and raises a `ValidationException` on mismatch;
  `--validate` type-checks the whole document **without executing** — the exact pattern for
  CrystalMath's pre-submission DAG validator.
- Common Workflow Language (CWL) v1.2 specification, P. Amstutz, M. R. Crusoe, N. Tijanić, et al.
  (2016, updated). DOI:10.6084/m9.figshare.3115156.v2. https://www.commonwl.org/. — Defines the typed
  `source → sink` workflow-graph model whose whole-document static type-check `cwltool` implements.
- WDL (Workflow Description Language) and `womtool` / `wdlTools` type-checking:
  https://github.com/openwdl/wdl and https://github.com/dnanexus-rnd/wdlTools. — Independent prior art
  for whole-document workflow type-checking (validate without running) corroborating the §1 posture.
- Nextflow documentation — statically structured channels:
  https://www.nextflow.io/docs/latest/channel.html. — Production example of statically-typed dataflow
  connectivity where a malformed pipe is a definition-time error, not a runtime one.
- S. K. Steensen, T. Thakur, M. Dillenz, … N. Marzari, T. Vegge, G. Pizzi, I. E. Castelli, "The
  Interoperability Challenge in DFT Workflows Across Implementations," arXiv:2511.11524 (2025). —
  Documents the code-specific input/output idiosyncrasies that break naive cross-engine handoff — the
  basis for §2's static `(source_code, artifact, converter)` compatibility table.
- S. P. Huber, E. Bosoni, M. Bercx, et al., "Common workflows for computing material properties using
  different quantum engines," *npj Computational Materials* **7**, 136 (2021).
  DOI:10.1038/s41524-021-00594-6, arXiv:2105.05063. — The code-agnostic typed-edge reference design
  (ADR-013's basis) whose edges this ADR type-checks statically.
- A. S. Rosen, A. M. Ganose, et al., "Jobflow: Computational Workflows Made Simple," *Journal of Open
  Source Software* **9**(93), 5995 (2024). DOI:10.21105/joss.05995. — `Flow`/`OutputReference`
  connectivity (the graph this pass walks) and `Response(detour|replace)` (the dynamic sub-DAGs §5
  re-validates).
- A. M. Ganose, et al., "Atomate2: modular workflows for materials science," *Digital Discovery*
  (2025). DOI:10.1039/d5dd00019j. — The recipe `Maker`s whose composed Flows are validated before
  submission.
- CrystalMath internal: [ADR-016](adr-016-wire-contract-codegen-no-drift.md) (the static-validation
  template, "drift is a build failure not a runtime error", `:52-101,189-191`),
  [ADR-013](adr-013-multi-code-handoff-and-restart-validation.md) (`CodeHandoff` / closed
  `HandoffArtifact` enum `:86,98-100`, pre-submission gate philosophy `:138-142,198-203`),
  [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) (typed `OutputReference` edges `:70`),
  [ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md) (the `CalculatorStage` typed signatures this
  pass reads), [ADR-020](adr-020-reproducibility-and-golden-file-testing.md) (the test-time/physics
  complement; §6 boundary), [ADR-023](adr-023-agentic-control-plane-mcp-ai-provenance.md) (the
  `validate_workflow` MCP verb that invokes this pass).
