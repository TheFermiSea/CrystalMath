# ADR-018: Replace the Bespoke ADAPTIVE Recovery with custodian-Style Code-Specific Error Handlers

**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** none
**Depends on:** [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) (workflow engine — jobflow `Flow`s), [ADR-012](adr-012-hpc-execution-jobflow-remote-aiida-optional.md) (HPC execution — jobflow-remote/AiiDA)
**Relates to:** [ADR-013](adr-013-multi-code-handoff-and-restart-validation.md) (multi-code handoff + restart-file validation)

> **Amendment (2026-06-07) — consolidation audit ([CONSOLIDATION-PLAN.md](CONSOLIDATION-PLAN.md)):**
> **Factual correction — custodian has NO Quantum ESPRESSO handlers.** custodian ships handlers for
> VASP, CP2K, Q-Chem, NWChem, FEFF, and Lobster only; there is no `espresso`/QE handler. The claims
> below that we "inherit custodian correction for VASP/QE" hold for **VASP only**. The authored-handler
> workload is therefore **three codes — CRYSTAL23, YAMBO, and QE** — not two: the laptop-first
> jobflow-remote + custodian default path gets **zero** automated QE recovery unless CrystalMath authors
> a `QeErrorHandler` (mine `aiida-quantumespresso`'s catalogue), or QE recovery is explicitly relegated
> to the opt-in AiiDA / quacc-ASE path. The plan picks the authored `QeErrorHandler` for the
> laptop-first promise.

## Context

DFT calculations fail in code-specific, well-catalogued ways. A VASP relaxation hits
`ZBRENT` (a Brent-method line-search failure that needs the geometry restarted from
`CONTCAR`), or `TET` (the tetrahedron method failing with a non-physical k-mesh, needing
a switch to Gaussian smearing), or simply runs out of electronic SCF steps and must be
restarted with a different mixing scheme. Quantum ESPRESSO has its own catalogue
(`%%%%` convergence-not-achieved, `S matrix not positive definite`, FFT grid mismatches).
These signatures are public knowledge, and the materials ecosystem has spent a decade
encoding them into a single, curated, version-aware library: **custodian**.

CrystalMath today reinvents a crippled subset of this. In
`python/crystalmath/high_level/runners.py`, `BaseAnalysisRunner` carries a bespoke
`ErrorRecoveryStrategy` enum (`FAIL_FAST` / `RETRY` / `ADAPTIVE` / `CHECKPOINT`) backed by
two methods:

- `_is_retryable_error()` — a substring grep over the error text for `'memory'` and
  `'timeout'`. It cannot tell an OOM from a node failure from an application-level
  non-convergence; it has no notion of *which code* failed; and a benign log line
  containing the word "timeout" is enough to trigger a retry of a deterministically
  failing job.
- `_attempt_adaptive_recovery()` — an in-place mutation of `step.parameters` that halves
  the MPI rank count or multiplies the energy-convergence tolerance by ten. This is a
  blind, code-agnostic patch applied regardless of the actual failure: it loosens
  convergence on a job that ran out of *walltime*, or halves ranks on a job that failed
  on a *bad k-mesh*. It mutates a shared step object, which is fragile under any future
  parallel or restartable execution. And it knows nothing of restart files — it never
  copies `CONTCAR`→`POSCAR`, never reuses a wavefunction, never edits `INCAR`/`d12`
  keywords by name.

This is a worse reimplementation of custodian's core loop (wrap the executable, detect a
known failure signature, patch the inputs, restart in place with bounded retries), with
none of custodian's actual handlers and none of its accumulated DFT domain knowledge.
The research is unanimous on this point (workflow-orchestration researcher rec 3;
dft-code researcher rec 6): adopt custodian, do not hand-roll error recovery. atomate2 —
the modern Materials Project stack (Ganose et al., *Digital Discovery* 2025) — delegates
*all* per-code robustness to custodian, and quacc recipes (Rosen et al.) wrap ASE
calculators with custodian correction by default.

Two structural facts shape the decision:

1. **custodian operates at the single-job level.** Its model is wrap–detect–patch–restart
   for *one* executable invocation. It does not, and should not, decide to skip a failed
   branch of a workflow graph or substitute an alternate calculation. That is
   workflow-graph-level recovery, and it belongs in the engine layer — the jobflow
   `Flow`s adopted in [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) — per
   the field's standard separation of concerns: (a) the workflow graph/dataflow, (b)
   per-code error recovery, (c) cluster execution/scheduling
   ([ADR-012](adr-012-hpc-execution-jobflow-remote-aiida-optional.md)).

2. **custodian does not cover CRYSTAL23 or YAMBO.** These are exactly CrystalMath's
   differentiating codes (ADR-006: the multi-code physics knowledge is the code we
   actually own). custodian ships `VaspErrorHandler`, `QCJobErrorHandler`,
   `FeffErrorHandler`, etc., but has no CRYSTAL or YAMBO handlers upstream. CrystalMath
   must author thin `ErrorHandler` subclasses for these — which is *appropriate*
   differentiating work, not reinvention.

This ADR is the per-code error-recovery instance of the redesign rule in
[ADR-007](adr-007-redesign-overview-adopt-ecosystem.md): replace homegrown machinery with
a mature ecosystem tool wherever one exists, and reserve bespoke code for the genuinely
novel (the Rust/Ratatui TUI, and CRYSTAL23/YAMBO physics). With zero active users,
backward compatibility is not a constraint; the bespoke recovery code can be deleted
outright.

## Decision

1. **Delete `_attempt_adaptive_recovery()` and `_is_retryable_error()`** from
   `python/crystalmath/high_level/runners.py`, along with the in-place `step.parameters`
   mutation they perform. No replacement substring-grep or blind-patch logic is written.

2. **Adopt custodian as the single-job error-recovery layer for VASP and QE.** For
   ecosystem-covered codes, jobs run under a `custodian.Custodian` instance configured
   with the code's standard handler set (e.g. `VaspErrorHandler`, `NonConvergingErrorHandler`,
   `PositiveEnergyErrorHandler`, `FrozenJobErrorHandler` for VASP). This lands naturally
   through the quacc/atomate2 recipe path adopted in
   [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md), whose recipes wrap
   ASE/pymatgen calculators with custodian correction — so for VASP/QE we inherit the
   maintained handlers rather than curating our own.

3. **Author thin `custodian.ErrorHandler` subclasses for CRYSTAL23 and YAMBO**, living in
   the per-code adapter layer (the canonical home being the per-code modules under the
   `CodeDeckGenerator`/`InputDeck` seam of
   [ADR-008](adr-008-structure-and-deck-io-on-ase-pymatgen.md), plus the run/parse
   knowledge currently in `python/crystalmath/_vendor/core/codes/`). Each handler
   implements custodian's contract — `check()` (does my known signature appear in the
   output?) and `correct()` (patch the `InputDeck`/restart files and report what was done)
   — using the convergence/error grep patterns the `_vendor` `DFTCodeConfig` already
   encodes, and the aux-file maps (CRYSTAL `.f9`→`fort.20`, YAMBO `SAVE`) for restart
   staging. Concretely:
   - **CRYSTAL23:** handlers for SCF non-convergence (loosen `TOLDEE`, adjust `FMIXING`,
     enable `LEVSHIFT`/`BROYDEN`, restart from `fort.9`), `TOLINTEG`/integration-grid
     failures, and geometry-optimisation `MAXCYCLE` exhaustion (restart from `.optinfo`).
   - **YAMBO:** handlers for missing/incomplete `SAVE` databases (re-run `p2y`/`yambo -i`
     setup), and memory/blocksize failures (adjust `DBs`/parallelisation variables).
   These handlers operate on the typed `InputDeck` value object, **not** on a raw string
   dict, so corrections are named keyword edits, not blind multipliers.

4. **Workflow-graph-level recovery stays in the engine layer.** Skipping a permanently
   failed branch, substituting an alternate calculation, or marking a node failed and
   continuing dependent-independent work is the engine's responsibility (jobflow's
   `Response`, atomate2's flow semantics) per
   [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md). custodian never makes
   graph-level decisions; CrystalMath's recovery code must not either. This ADR only fixes
   the *single-job* recovery layer and draws the boundary.

5. **`ErrorRecoveryStrategy` survives only as a high-level policy knob.** The enum is
   demoted from "the place recovery logic lives" to "the place a user selects a handler
   *set*." Its meaning becomes:
   - `FAIL_FAST` → run with **no** custodian handlers (`max_errors=0`); the first failure
     propagates.
   - `RETRY` → a minimal handler set (transient/walltime/frozen-job handlers only).
   - `ADAPTIVE` → the full code-specific handler set (the curated custodian + CrystalMath
     handlers for that code).
   - `CHECKPOINT` → folds into the engine's durable-execution / restart semantics, not a
     per-job grep.
   The enum no longer dispatches to any bespoke `_attempt_*` method; it maps to a list of
   `ErrorHandler` instances handed to `Custodian`.

## Consequences

### Positive

- **Real DFT robustness for free** on VASP/QE: the entire community-maintained custodian
  handler catalogue (ZBRENT, TET, electronic non-convergence, Brillouin-zone and FFT
  failures, frozen jobs) replaces a two-substring grep and a blind tolerance multiplier.
- **Corrections become correct.** A walltime failure is no longer "fixed" by loosening
  convergence; a bad-k-mesh failure is no longer "fixed" by halving MPI ranks. Each
  handler patches the *right* knob for the *detected* signature, with restart-file reuse.
- **No more shared-object mutation.** Killing the in-place `step.parameters` rewrite
  removes a fragility that would have bitten any future parallel/restartable executor.
- **Differentiating effort is concentrated where it belongs.** CrystalMath writes and
  maintains *only* the CRYSTAL23 and YAMBO handlers — the codes the ecosystem does not
  cover — instead of re-deriving VASP/QE recovery the rest of the field already maintains.
- **Clean layering.** Single-job recovery (custodian) and graph-level recovery (the
  jobflow engine, ADR-011) are explicitly separated, matching the AiiDA/atomate2 consensus
  and making both layers independently testable.
- **The typed `InputDeck` pays off.** Handlers edit named keywords on a value object, so a
  correction is auditable ("set `LEVSHIFT 5 1`, restarted from `fort.9`") rather than an
  opaque parameter mutation. This dovetails with the mandatory restart-file validation of
  [ADR-013](adr-013-multi-code-handoff-and-restart-validation.md): a `correct()` that
  stages a restart file produces exactly the typed edge ADR-013 then validates before the
  retried job is submitted.

### Negative / Risks

- **CRYSTAL23/YAMBO handlers are bespoke and must be curated and tested.** There is no
  upstream to inherit from; every signature, every keyword patch, and every restart-file
  move has to be authored, version-pinned to CRYSTAL23 / a YAMBO release, and regression-
  tested against real (canned) failure outputs. This is ongoing maintenance.
- **Handler correctness needs real failure fixtures.** Per the reproducibility spine
  ([ADR-020](adr-020-reproducibility-and-golden-file-testing.md)), CI runs no live DFT;
  these handlers must be tested against captured real failure outputs (golden-file
  `check()` inputs) plus a fake runner, with a separate live smoke test.
- **custodian pulls dependency weight** (custodian + its pymatgen/ASE expectations) deeper
  into the Python core — acceptable, since quacc/atomate2 already bring them (ADR-011).
- **Graph-level recovery is explicitly out of scope here.** "Skip the failed branch and
  keep going" is the engine's job (ADR-011); a job that custodian cannot fix fails its
  node, and the surrounding behaviour is whatever the jobflow `Response` defines. This ADR
  deliberately does not paper over that boundary with more bespoke grep logic.
- **`ErrorRecoveryStrategy` semantics change.** With zero users this is free, but any
  doc/UI surfacing the enum (the Rust `new_job`/`workflow_config` screens) must be updated
  to describe "handler set selection," not "retry vs adaptive-mutate."

## Alternatives Considered

1. **Keep and extend the bespoke recovery.** Add more substrings to `_is_retryable_error`
   and more code paths to `_attempt_adaptive_recovery`. Rejected: this is the explicit
   anti-pattern the research names (workflow-orchestration rec 3) — a crippled reinvention
   of custodian that would forever lag the community catalogue and carry no DFT-specific
   knowledge. Every line added is a line that must be maintained against a moving target
   (VASP/QE error strings) that custodian already tracks.

2. **Adopt AiiDA's error-handling for everything.** AiiDA's engine offers robust,
   provenance-recorded, restart-on-transition recovery (Uhrin et al., *Comput. Mater. Sci.*
   2020). Rejected as the *default*: it is heavyweight (daemon + broker + DB), and its
   per-code handling still ultimately wraps code-specific logic. AiiDA remains the single
   opt-in heavyweight backend (per
   [ADR-012](adr-012-hpc-execution-jobflow-remote-aiida-optional.md)), but the default
   single-job recovery layer should be the lighter, ubiquitous custodian.

3. **Use only engine-level (jobflow) recovery, no per-job handlers.** Let the graph engine
   retry a failed job wholesale. Rejected: a blind whole-job retry without patching inputs
   re-runs the identical failing calculation. The field's separation of concerns exists
   precisely because graph-level retry (ADR-011) and signature-specific in-place patching
   are different jobs; you need both, at different layers.

4. **Write CRYSTAL23/YAMBO support as ASE calculators so they become quacc recipes and get
   custodian "for free."** Attractive (one path for all codes), but CRYSTAL23/YAMBO have no
   first-class ASE calculator, so this means writing ASE calculators *first* — strictly
   more work than authoring custodian `ErrorHandler` subclasses against the existing
   `InputDeck`/`_vendor` run-parse knowledge. Deferred; the thin-handler path ships value
   sooner and reuses code we already have.

## References

- A. Ganose, J. Sahasrabuddhe, … A. Rosen, A. Jain, et al., "Atomate2: modular workflows
  for materials science," *Digital Discovery* (2025). — Defines the current Materials
  Project stack (jobflow Flows of Makers) and its delegation of all per-code error
  recovery to custodian; the model CrystalMath should adopt.
- custodian (materialsproject/custodian), documentation, 2025 —
  `https://materialsproject.github.io/custodian/`. The de-facto DFT error-handler layer:
  the `Custodian` wrap–detect–patch–restart loop and the `ErrorHandler`
  `check()`/`correct()` contract, plus the curated `VaspErrorHandler` /
  `QCJobErrorHandler` catalogues this ADR adopts and extends.
- A. S. Rosen et al., quacc — The Quantum Accelerator, Zenodo `10.5281/zenodo.10460657`;
  docs `https://quantum-accelerators.github.io/quacc/`. — `@job`/`@flow` recipes wrap ASE
  calculators with custodian error correction by default; the path through which VASP/QE
  recovery lands in CrystalMath via the engine adoption of ADR-011.
- M. Uhrin, S. P. Huber, J. Yu, N. Marzari, G. Pizzi, "Workflows in AiiDA: Engineering a
  high-throughput, event-based engine for robust and modular computational workflows,"
  *Computational Materials Science* 187, 110086 (2021) (arXiv:2007.10312). — The
  event-based, checkpoint-on-transition engine; cited for the graph-level vs single-job
  recovery separation of concerns and as the rejected heavyweight default (Alternative 2).
- A. Jain, S. P. Ong, W. Chen, … K. A. Persson, "FireWorks: a dynamic workflow system
  designed for high-throughput applications," *Concurrency and Computation: Practice and
  Experience* 27(17):5037 (2015). — Establishes the dynamic-DAG + restart-file provenance
  model in which graph-level recovery (skip/replace a branch) lives, distinct from
  per-job patching.
- In-repo: `python/crystalmath/high_level/runners.py` (`BaseAnalysisRunner`,
  `_attempt_adaptive_recovery`, `_is_retryable_error`, `ErrorRecoveryStrategy`) — the
  bespoke recovery this ADR deletes. `python/crystalmath/decks/__init__.py` (`InputDeck`,
  `CodeDeckGenerator`, `stage`) — the typed value object custodian handlers patch.
  `python/crystalmath/_vendor/core/codes/` (`DFTCodeConfig` error/convergence grep
  patterns, aux input/output file maps) — the run-parse knowledge the CRYSTAL23/YAMBO
  handlers reuse.
- [ADR-007](adr-007-redesign-overview-adopt-ecosystem.md) — the redesign rule (adopt the
  ecosystem, collapse N-way facades to one) this ADR applies to error recovery.
- [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md),
  [ADR-012](adr-012-hpc-execution-jobflow-remote-aiida-optional.md),
  [ADR-013](adr-013-multi-code-handoff-and-restart-validation.md) — the workflow engine
  (graph-level recovery home), the HPC execution seam (AiiDA opt-in backend), and the
  typed restart-file edges that a custodian `correct()` feeds.
