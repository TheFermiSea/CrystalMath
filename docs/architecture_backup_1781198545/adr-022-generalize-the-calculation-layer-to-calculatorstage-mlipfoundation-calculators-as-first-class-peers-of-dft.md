---
adr_id: 022
title: "Generalize The Calculation Layer To Calculatorstage Mlipfoundation Calculators As First Class Peers Of Dft"
status: "Accepted"
date: "2026-06-11"
macro_context: "crystalmath-tui-core"
---

# ADR-022: Generalize The Calculation Layer To Calculatorstage Mlipfoundation Calculators As First Class Peers Of Dft



**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** none (refactors and amends ADR-008's calculation-layer vocabulary; the 007-020 spine stays intact)
**Depends on:** [ADR-008](adr-008-structure-and-deck-io-on-ase-pymatgen.md) (one `Structure` object + per-code deck seam over ASE/pymatgen), [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md) (emmet-style versioned `TaskDocument` + lineage fields), [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) (jobflow `Flow`/`Response` as the one orchestration model), [ADR-012](adr-012-hpc-execution-jobflow-remote-aiida-optional.md) (the `ExecutionBackend` seam)
**Consumed by:** [ADR-022](adr-022-content-addressed-execution-cache-replay.md) (the checkpoint hash this ADR introduces is a primary input to the canonical content hash), [ADR-023](adr-023-agentic-control-plane-mcp-ai-provenance.md) (MLIP screening is the cheap inner loop an agentic planner composes), [ADR-024](adr-024-static-typed-workflow-dag-validation.md) (each `CalculatorStage`'s declared input/output type signature is what the static checker reads), [ADR-025](adr-025-campaign-acquisition-strategy.md) (consumes the MLIP mechanism + `UncertaintyEstimate` to decide *what to run next* and *when to spend DFT budget*), [ADR-026](adr-026-trustworthy-mlip-evaluation-applicability-domain.md) (owns the MLIP *trust policy*: calibration, applicability-domain gate, escalation thresholds, and the `UncertaintyEstimate` type this ADR's mechanism emits), [ADR-027](adr-027-model-dataset-registry-lineage.md) (owns the `ModelIdentifier` and the model/dataset registry this ADR's `MODEL_REGISTRY` row resolves to)

> **Amendment (2026-06-07) — consolidation audit ([CONSOLIDATION-PLAN.md](CONSOLIDATION-PLAN.md)):**
> The MLIP roster cited below is dated. Refresh the candidate foundation models to the 2026 leaders
> (ORB v3, GRACE-2L-OAM, SevenNet-MP-ompa, eSEN, MatterSim) alongside MACE-MP / CHGNet; the
> `CalculatorStage` *mechanism* is unchanged. (Trust/metric refresh lives in ADR-026.)

## Context

CrystalMath's calculation layer is **DFT-centric by construction, not by accident.** The code
taxonomy is frozen at five DFT/phonon engines — "CRYSTAL23, VASP, Quantum ESPRESSO, YAMBO,
phonopy" — and it is hard-coded in three of the set's most-cited anchors:
`adr-007-redesign-overview-adopt-ecosystem.md:18` (the umbrella taxonomy and the 9-point
"one of each layer" list), `adr-009-canonical-data-model-emmet-pydantic-taskdocs.md:97`
(`DftCode = crystal | vasp | qe | yambo | phonopy`), and
`adr-011-workflow-engine-jobflow-atomate2-quacc.md:68` (the `relax | scf | static | bands | dos |
gw | bse | phonon | eos | convergence` workflow enumeration). The whole machinery assumes that "run
a calculation" means "generate a code deck, stage it to scratch, submit it under `sbatch`, parse
the output files back into a `TaskDocument`." ADR-008's `CodeDeckGenerator`/`InputDeck` *is* that
assumption made concrete: a calculation is a **file-writing, deck-staged, scheduler-submitted**
act, and POTCAR/deck validation (ADR-008's `DeckStagingError`, ADR-013's `RestartValidation`) is
woven into it as if all calculators write files.

**Machine-learning interatomic potentials (MLIPs) break that assumption, and the field has already
reorganized around them.** A foundation MLIP — MACE-MP-0 (Batatia et al. 2024), CHGNet
(Deng et al. 2023), SevenNet (Park et al. 2024), MatterSim (Yang et al. 2024), ORB
(Neumann et al. 2024) — is a *pre-trained model checkpoint* that, given a `Structure`, returns
energy / forces / stress **in-process, on a GPU, in milliseconds, writing zero files.** Matbench
Discovery (Riebesell et al. 2025) establishes the production use case: universal MLIPs are now
*DFT pre-filters* with discovery F1 in the 0.57-0.82 range, screening millions of candidates so
that only the promising few reach a DFT verifier. The ecosystem CrystalMath already adopts has
absorbed this: atomate2 (Ganose et al. 2025) runs *every* MLIP through a single `ForceFieldStaticMaker`/
`AseMaker` that wraps an ASE `Calculator`, and quacc exposes the same models via a `method=` argument
on its recipes. In both, an MLIP is not a sixth "code" with its own deck dialect — it is **one
instance of a more general thing: a `Structure -> (energy, forces, stress)` calculator**, of which
DFT is *another* instance that happens to round-trip through files.

**Every seam CrystalMath already owns speaks the right vocabulary to absorb this — but each is
closed against it.**

- ADR-008 names the **ASE `Calculator` interface** as the universal boundary covering "~40 engines"
  and provides the `SocketIOCalculator`/`FileIOCalculator` escape hatch
  (`adr-008-structure-and-deck-io-on-ase-pymatgen.md:82-85`) — but reserves it for YAMBO. An MLIP
  *is* an ASE `Calculator`; the hatch is the exact insertion seam, currently nailed shut.
- ADR-009's `TaskDocument` already round-trips MSONable results with lineage fields, but its
  `DftCode` enum and `ProvenanceDoc` have no field for a *model identity* — no model id, no
  checkpoint hash, no ensemble uncertainty, no fine-tune parent, no acquisition function.
- ADR-011's workflows are a **static enumeration of Flow factories**, and its Alternative B
  explicitly rejects high-throughput Parsl/Dask except as in-allocation executors — so the
  surrogate-screening loop that *is* the point of foundation models has no first-class home, even
  though jobflow's `Response(detour/replace)` (acknowledged in ADR-018 only for error recovery)
  is exactly the dynamic-sub-DAG primitive the adaptive MLIP modes need.
- ADR-012 commits to **"exactly two implementations, no more"** of `ExecutionBackend`
  (`adr-012-hpc-execution-jobflow-remote-aiida-optional.md:91`) with *all compute via `sbatch` by
  construction* (`adr-012...:102-104`). A foundation model's entire value proposition is *fast
  in-process GPU inference that bypasses the queue*; forcing a 5-millisecond MACE call through an
  `sbatch` round-trip would defeat the reason to adopt it.

The result is a clean-slate opportunity the set's "outrageous-if-beneficial" mandate invites: the
abstraction at the center of the calculation layer is wrong. It is `CodeDeckGenerator` — a
*file-and-DFT* shape — when it should be a code-agnostic `Structure -> TaskDocument` stage of which
file-writing DFT is one specialization and zero-file MLIP inference is a peer. This ADR re-centers
the layer without contradicting a single locked decision: it makes DFT *one instance* of a more
general abstraction rather than the abstraction itself.

## Decision

**Re-center the calculation layer on a code-agnostic `CalculatorStage` (`Structure -> TaskDocument`).
DFT becomes `DftCalculatorStage` (file-writing, deck-staged, POTCAR-validated, `sbatch`-executed);
MLIP/foundation models become `MlipCalculatorStage`, a thin wrapper over any ASE-native `Calculator`
keyed by a content-addressed checkpoint hash that returns energy/forces/stress with zero files.
Narrow POTCAR/deck validation to DFT only, model the five MLIP usage modes as named jobflow
patterns, and admit a third `ExecutionBackend` for in-process inference under a narrowly-carved
exception to ADR-012's `sbatch`-by-construction rule.**

### 1. `CalculatorStage` is the calculation abstraction; `DftCalculatorStage` is one instance

Introduce a `crystalmath.calculation` module with a code-agnostic protocol:

```python
class CalculatorStage(Protocol):
    """A Structure -> TaskDocument step. DFT is one instance; MLIP is a peer."""
    def declared_inputs(self) -> InputSignature: ...    # consumed by ADR-024's static checker
    def declared_outputs(self) -> OutputSignature: ...  # e.g. {ENERGY, FORCES, STRESS, WAVEFUNCTION?}
    def run(self, structure: Structure, spec: CalcSpec) -> TaskDocument: ...
```

ADR-008's `CodeDeckGenerator`/`InputDeck` is **not deleted** — it becomes the body of
`DftCalculatorStage`, the **DFT-and-file-code specialization** of `CalculatorStage`: it generates a
deck, stages it (`DeckStagingError` on failure), submits via the ADR-012 backend under `sbatch`,
and parses output files into the per-code `TaskDocument` (ADR-009). Everything ADR-008 decided about
decks survives verbatim, demoted from "the calculation layer" to "the calculation layer's
file-code instance." This is the keystone reframing: the deck seam is *one stage type*, not the
center.

### 2. `MlipCalculatorStage` is a peer that emits zero files, keyed by checkpoint hash

`MlipCalculatorStage` is a thin adapter over an ASE `Calculator` obtained from a **model registry**:

```python
class MlipCalculatorStage:                # a CalculatorStage peer of DftCalculatorStage
    def run(self, structure: Structure, spec: MlipCalcSpec) -> MlipTaskDoc:
        calc = MODEL_REGISTRY.calculator(spec.model_id)   # model_id -> ASE Calculator factory
        atoms = AseAtomsAdaptor.get_atoms(structure); atoms.calc = calc
        return MlipTaskDoc.from_ase(
            atoms, model_id=spec.model_id,
            checkpoint_hash=MODEL_REGISTRY.checkpoint_hash(spec.model_id),  # ADR-022 anchor
        )                                  # energy/forces/stress; NO files written
```

- A `MODEL_REGISTRY` entry **is an [ADR-027](adr-027-model-dataset-registry-lineage.md)
  `ModelIdentifier` resolution**: the registry resolves a model's identity to an ASE `Calculator`
  factory. The **digest, not the weight bytes, is the identity** — the content-addressed digest of
  the model registry entry (e.g. the HuggingFace repo id + pinned revision), *not* the
  multi-gigabyte weights themselves (cf. the corrected
  `adr-009-canonical-data-model-emmet-pydantic-taskdocs.md:315`). MACE, CHGNet, SevenNet, MatterSim,
  and ORB each ship an ASE `Calculator`; registering one is adding a registry entry that resolves a
  `ModelIdentifier`, not a new code seam. This realizes ADR-008's
  `SocketIOCalculator`/`FileIOCalculator` hatch (`adr-008...:82-85`) for the
  calculator-that-is-a-model-checkpoint case. **Checkpoint acquisition / pin / verify and dataset
  identity are decided in ADR-027**, not here; this ADR consumes the resolved `ModelIdentifier`.
- The MLIP "deck" is a typed `MlipCalcSpec` (model id, dispersion/cutoff settings, dtype,
  device) — **config only, no file**. An MLIP run is a pure function of
  `(statepoint, checkpoint_hash, settings, library_versions)`, which is precisely the content key
  ADR-022 needs and the reproducibility anchor ADR-020 currently lacks for ML.

### 3. POTCAR/deck validation is narrowed to DFT only

POTCAR validity, deck-keyword schemas, and `RestartValidation` (ADR-013) are **DFT-stage
concerns**, moved onto `DftCalculatorStage`, not `CalculatorStage`. An `MlipCalculatorStage` has no
POTCAR, no deck, and no restart file, so demanding one would be a category error. Concretely:

- The pseudopotential/POTCAR-hash check and the `DeckStagingError` path live on
  `DftCalculatorStage` and on DFT handoff edges.
- ADR-013's closed `HandoffArtifact` enum gains MLIP-relevant members for ML-in-the-loop chains —
  `FORCE_SET` already covers MLIP-computed forces feeding phonopy; a new `MODEL_CHECKPOINT` artifact
  lets a fine-tune stage declare a model as a typed edge — but `WAVEFUNCTION`/`CHARGE_DENSITY`
  validation simply *does not apply* to an MLIP stage that never produces them. ADR-024's static
  checker reads each stage's `declared_outputs` and never asks an MLIP stage for a WAVECAR.

### 4. The five MLIP usage modes are named jobflow patterns; the dynamic ones use `Response`

MLIPs are used in five characteristic modes; each is a named pattern over the ADR-011 Flow
factories, not a new engine:

| Mode | Pattern | jobflow mechanism |
|---|---|---|
| **Pre-relax** | MLIP geometry relaxation feeding a DFT static/relax | static `Flow` edge (`OutputReference`) |
| **Surrogate-screen** | MLIP filters N candidates; only the top-k reach DFT | static fan-out `Flow` (Matbench F1 0.57-0.82) |
| **Uncertainty-gated escalation** | run MLIP; if ensemble/GP variance exceeds a threshold, escalate to DFT | **`Response(detour)`** (FLARE GP-variance gate, Vandermause et al. 2020) |
| **Active learning** | propose → MLIP-evaluate → label uncertain points with DFT → retrain | **`Response(detour/replace)`** loop |
| **Delta-ML / fine-tune** | fine-tune a foundation checkpoint on DFT labels; emit a new checkpoint | **`Response(replace)`** emitting a new `model_id` (`MODEL_CHECKPOINT` artifact) |

The static modes (pre-relax, surrogate-screen) are ordinary Flow edges. The **dynamic** modes
(escalation, active-learning, fine-tune) are emitted as jobflow `Response(detour)`/`Response(replace)`
sub-DAGs decided at run time — the same primitive ADR-018 uses for graph-level recovery, here
promoted to a first-class calculation pattern. These dynamic detour points are exactly the
"open detour points" ADR-024's static validator must tolerate and re-validate when materialized.

### 5. `MlipProvenance` on the `TaskDocument`; the checkpoint hash seeds ADR-022

ADR-009's schema gains an `MlipTaskDoc` subclass and extends `ProvenanceDoc` so an ML result is as
auditable as a DFT one:

- `model: ModelIdentifier` — the single unified [ADR-027](adr-027-model-dataset-registry-lineage.md)
  `ModelIdentifier` (carrying model id, pinned revision, content-addressed digest, and dataset
  lineage), replacing the bespoke `model_id`/`checkpoint_hash`/`model_version`/`training_provenance`
  fields with one resolved identity object
- `uncertainty: UncertaintyEstimate` — the method-tagged
  [ADR-026](adr-026-trustworthy-mlip-evaluation-applicability-domain.md) `UncertaintyEstimate`
  (ensemble spread vs. GP variance are not interchangeable; the method tag and in-domain flag travel
  with the number)
- `acquisition_function` and `fine_tune_parent` (the parent `ModelIdentifier` a Delta-ML run
  descends from)
- `fidelity_lineage` — which MLIP/DFT rungs produced this result

The `checkpoint_hash` is the load-bearing field: it is the content-address ADR-022 folds into the
canonical closure hash, so that **bumping a model checkpoint invalidates every dependent surrogate
result** automatically. GPU inference is *not* bitwise-reproducible (FMA contraction, atomics,
vendor BLAS), so the reproducibility key is `(statepoint + checkpoint_hash + tolerance_class)` and
ADR-020's env fingerprint must record `torch`/CUDA versions plus per-property tolerances — never
byte-equality on an MLIP result.

**This ADR owns only the MLIP *mechanism*, not the policy that governs it.** The mechanism is the
five usage modes (§4) and the method-tagged uncertainty field — now an
[ADR-026](adr-026-trustworthy-mlip-evaluation-applicability-domain.md) `UncertaintyEstimate`. The
**trust policy** — the calibration requirement, the escalation thresholds, the
applicability-domain / `in_domain` OOD gate, and what it means to *accept* an MLIP result — is
decided in **ADR-026**, not here. The **acquisition / campaign policy** — which candidates to
evaluate, the DFT budget, and the convergence / stopping criteria — is decided in
**[ADR-025](adr-025-campaign-acquisition-strategy.md)**. This ADR provides the mechanism those
policies actuate; it does not re-litigate (or hard-code) either policy. The coupling is explicit
and one-directional: at the escalation boundary, an out-of-domain candidate flagged by ADR-026 must
hit DFT and may never be silently skipped — ADR-025's `AcquisitionStrategy` scores over the
ADR-026 `UncertaintyEstimate`, and both resolve model identity through ADR-027's `ModelIdentifier`.

### 6. A third `ExecutionBackend` for in-process inference — a narrow, DFT-excluded exception

ADR-012's "exactly two implementations" wall is **amended**, not demolished. Add a third
`ExecutionBackend` implementation, `InProcessInferenceBackend`, that runs `MlipCalculatorStage`
calls **in-process on a local/GPU device, bypassing `sbatch`** — because fast queue-free evaluation
is the entire reason to adopt foundation models. The exception is carved narrowly so it does not
reopen the SSH-direct-execution hole ADR-012 closed:

- **Inference only, never DFT.** The backend accepts *only* `MlipCalculatorStage` work; routing a
  `DftCalculatorStage` to it is a hard error. ADR-012's invariant "all DFT compute via `sbatch` by
  construction" (`adr-012...:102-104`) is preserved unchanged — it is now stated as "all *DFT*
  compute," with MLIP inference as the explicitly enumerated, type-guarded exception.
- For *heavy* MLIP work that genuinely needs a GPU allocation (large-batch screening, fine-tuning
  with PyTorch), the stage still routes through the default `JobflowRemoteBackend` under `sbatch`;
  the in-process backend is for the light, interactive, single-structure calls where the queue
  latency would dominate the compute.

## Alternatives Considered

**A. Treat MLIP as a sixth "code" alongside CRYSTAL23/VASP/QE/YAMBO/phonopy.** The minimal change:
add `mace`/`chgnet`/… to the `DftCode` enum (`adr-009...:97`) and write an `MlipDeckGenerator` that
emits a config file. *Why not:* it preserves the wrong center. A foundation model is not a
"code with a deck dialect" — it writes no files, needs no POTCAR, runs in-process, and is keyed by a
model checkpoint, not an executable path. Bolting it onto the `CodeDeckGenerator` hierarchy would
force POTCAR/deck/restart validation onto a thing that has none of those, and would still leave the
calculation layer DFT-shaped. atomate2 (Ganose et al. 2025) deliberately routes MLIPs through one
`AseMaker`, not a sixth deck generator — the precedent is `CalculatorStage`, not "another code."

**B. Keep `CodeDeckGenerator` as the center and add MLIPs via the ASE `SocketIOCalculator` hatch
only (no new abstraction).** ADR-008 already reserves the socket hatch (`adr-008...:82-85`); one
could route MLIPs through it and call it done. *Why not:* the socket hatch is an *I/O transport* for
a code that runs out-of-process and streams positions/forces over a socket — it still assumes an
external long-running calculator process. A foundation model is a *Python object in the same
process*; wrapping it in a socket server to satisfy a DFT-shaped seam adds latency and a process
boundary for no benefit. The hatch is the right *idea* (ASE `Calculator` is the universal boundary)
but the wrong *level*: we lift the ASE `Calculator` boundary up to `MlipCalculatorStage` rather than
tunneling it through a socket reserved for YAMBO.

**C. Run all MLIP inference through `sbatch` like every other compute step, leaving ADR-012's
"exactly two backends" wall intact.** This keeps the cleanest possible execution invariant
(`adr-012...:91,102`): every compute step is a batch job, no exceptions. *Why not:* it negates the
reason to adopt foundation models. A MACE-MP-0 single-point is milliseconds of GPU compute; an
`sbatch` round-trip is seconds-to-minutes of queue + staging latency, a 100-1000x overhead on the
hot inner loop of surrogate screening and active learning. The whole Matbench-Discovery value
proposition (Riebesell et al. 2025) — screen millions cheaply, verify few with DFT — collapses if
every screen is a queued job. The narrow, type-guarded inference-only exception (§6) preserves
ADR-012's *DFT* invariant exactly while admitting the one workload for which the wall is
counterproductive.

**D. Skip `MlipProvenance`/checkpoint-hashing and treat MLIP results as ordinary `TaskDocument`s.**
Simpler schema, no `MlipTaskDoc` subclass. *Why not:* an MLIP result without its `model_id` +
`checkpoint_hash` is scientifically meaningless and irreproducible — "MACE said -4.2 eV" is unusable
without "which MACE." The checkpoint hash is also the seam ADR-022 needs to make a checkpoint bump
invalidate dependent caches; omitting it strands ML results outside the content-addressing story the
022-024 layer is built on, exactly the gap ADR-020 already has for ML determinism.

**E. Adopt a dedicated high-throughput screening engine (Parsl/Dask/FireWorks) for the MLIP loop,
parallel to jobflow.** MLIP screening is embarrassingly parallel and these engines excel at it.
*Why not:* it reintroduces the multiple-orchestration-models sprawl ADR-011 spent 2.5k LOC deleting,
and ADR-011 Alternative E already reserves Parsl/Dask as *in-allocation executors under the ADR-012
backend*, not as a second top-level DAG model. The five MLIP modes (§4) express cleanly as jobflow
Flow patterns + `Response` detours; a high-throughput screen is a fan-out `Flow` whose leaves run on
the in-process inference backend (§6) or an in-allocation Parsl executor — no parallel engine
needed.

## Consequences

### Positive
- **DFT loses its privileged center; the calculation layer is code-agnostic.** `CalculatorStage`
  is the abstraction; `DftCalculatorStage` (file/deck/`sbatch`) and `MlipCalculatorStage`
  (zero-file/in-process) are peers. Adding a foundation model is a registry row, not a new deck
  dialect — and the spine (008/009/011/012) is amended, not contradicted.
- **The Matbench-Discovery workflow becomes first-class.** Surrogate-screen-then-verify, the
  dominant production use of foundation models (F1 0.57-0.82), is a named Flow pattern (§4) running
  on a queue-free inference backend (§6) — the MLIP inner loop runs at MLIP speed.
- **MLIP results are as auditable as DFT results.** `MlipProvenance` (model id, checkpoint hash,
  uncertainty, acquisition, fine-tune parent) folds ML into ADR-009's provenance contract and seeds
  the ADR-022 content hash, closing the ML-reproducibility gap ADR-020 leaves open.
- **The dynamic modes reuse an existing primitive.** Escalation/active-learning/fine-tune are
  jobflow `Response(detour/replace)` — the same mechanism ADR-018 already uses — so adaptive
  ML-in-the-loop needs no new engine machinery, only a new *use* of one CrystalMath already has.
- **POTCAR/deck validation gets sharper, not weaker.** Narrowing it to `DftCalculatorStage` removes
  the implicit assumption "all calculators write files," which is exactly what made the layer
  DFT-shaped; the DFT checks themselves are unchanged.

### Negative / Tradeoffs
- **Amends the most-cited anchors in the set.** The 5-code taxonomy at `adr-007...:18`,
  `adr-009...:97`, and `adr-011...:68` must be widened to admit a non-DFT calculator class, with
  knock-on edits to ADR-013's `HandoffArtifact` (new `MODEL_CHECKPOINT`) and ADR-020's fixtures
  (MLIP-determinism tolerances). This is deliberate re-centering, but it touches load-bearing
  decisions and must be done carefully to avoid drift.
- **The non-`sbatch` backend weakens ADR-012's "E1 holds by construction" cleanliness.** Admitting
  any in-process execution path reopens, in principle, the door ADR-012 closed. Mitigation: the
  exception is type-guarded to `MlipCalculatorStage` only and DFT routing to it is a hard error, so
  the "all *DFT* compute via `sbatch`" invariant is preserved exactly — but the invariant is now
  conditional rather than absolute, and that conditionality must be enforced in code, not just prose.
- **Couples the project to fast-moving torch/CUDA packages.** MACE/CHGNet/SevenNet/MatterSim/ORB
  live on a churning PyTorch + CUDA stack; this lands behind an optional `[ml]` extra so the
  laptop-first DFT user does not pay for it, but the ML env is a real maintenance surface and GPU
  inference is non-deterministic (necessitating the tolerance-class key of §2/§5).
- **Patterns 3-5 are dynamic sub-DAGs.** Escalation/active-learning/fine-tune materialize at run
  time, so ADR-024's static checker must explicitly allow open detour points and re-validate them
  when spawned — a real constraint the static-validation ADR must honor. Fine-tuning additionally
  needs a PyTorch+GPU training runtime (the optional `[ml]` extra), not just inference.
- **Uncertainty must be method-tagged.** Ensemble spread, GP variance (FLARE), and dropout estimates
  are not interchangeable; the `uncertainty` field must carry its method or an escalation gate will
  compare incomparable numbers.

### Migration Impact
1. Introduce `crystalmath.calculation` with the `CalculatorStage` protocol; refactor ADR-008's
   `CodeDeckGenerator`/`InputDeck` into `DftCalculatorStage` (no behavior change — POTCAR/deck/
   `RestartValidation` move onto it).
2. Add `MlipCalculatorStage` + a model registry (`model_id -> Calculator` factory + `checkpoint_hash`);
   register MACE-MP-0, CHGNet, SevenNet, MatterSim, ORB behind the optional `[ml]` extra.
3. Extend ADR-009: add `MlipTaskDoc` and the `MlipProvenance` fields (`model_id`, `checkpoint_hash`,
   `uncertainty` (method-tagged), `acquisition_function`, `fine_tune_parent`, `fidelity_lineage`);
   widen the code-class enums at `adr-007...:18` / `adr-009...:97` / `adr-011...:68` to admit MLIPs.
4. Add the five named MLIP Flow patterns to the ADR-011 factory surface; emit the dynamic three via
   `Response(detour/replace)`.
5. Add `InProcessInferenceBackend` as the third `ExecutionBackend` (ADR-012), type-guarded to
   `MlipCalculatorStage`; DFT routing to it raises.
6. Add `MODEL_CHECKPOINT` to ADR-013's `HandoffArtifact`; keep `FORCE_SET` for MLIP→phonopy.
   Hand the `checkpoint_hash` to ADR-022 as a closure-hash input and to ADR-020 as a fingerprinted,
   tolerance-classed reproducibility key.

## References

- I. Batatia, P. Benner, Y. Chiang, et al., "A foundation model for atomistic materials chemistry"
  (MACE-MP-0), *J. Chem. Phys.* (2024). arXiv:2401.00096. — Canonical foundation-MLIP paper; an
  MLIP is one calculator stage, and the source of the Delta-ML / fine-tune pattern (§4).
- B. Deng, P. Zhong, K. Jun, et al., "CHGNet as a pretrained universal neural network potential for
  charge-informed atomistic modelling," *Nature Machine Intelligence* **5**, 1031-1041 (2023).
  DOI:10.1038/s42256-023-00716-3. — Charge-informed universal MLIP wrapped as an ASE `Calculator`.
- J. Riebesell, R. E. A. Goodall, P. Benner, et al., "Matbench Discovery — A framework to evaluate
  machine learning crystal stability predictions," *Nature Machine Intelligence* (2025).
  arXiv:2308.14920. — Universal MLIPs as DFT pre-filters; discovery F1 0.57-0.82 — the empirical
  basis for the surrogate-screen pattern (§4).
- A. M. Ganose, H. Sahasrabuddhe, M. Asta, et al., "Atomate2: modular workflows for materials
  science," *Digital Discovery* (2025). DOI:10.1039/d5dd00019j. — Runs MLIPs through one
  `AseMaker`/force-field maker; the precedent for `CalculatorStage` over a sixth deck generator.
- Y. Park, J. Kim, S. Hwang, S. Han, "Scalable Parallel Algorithm for Graph Neural Network
  Interatomic Potentials in Molecular Dynamics Simulations" (SevenNet), *J. Chem. Theory Comput.*
  **20**, 4857 (2024). DOI:10.1021/acs.jctc.4c00190. — Foundation MLIP shipping an ASE `Calculator`.
- H. Yang, C. Hu, Y. Zhou, et al., "MatterSim: A Deep Learning Atomistic Model Across Elements,
  Temperatures and Pressures" (2024). arXiv:2405.04967. — Foundation model used for the
  active-learning data-generation mode (§4).
- M. Neumann, J. Gin, B. Rhodes, et al., "Orb: A Fast, Scalable Neural Network Potential" (2024).
  arXiv:2410.22570. — Fast foundation MLIP; an ASE `Calculator` registered behind the model registry.
- J. Vandermause, S. B. Torrisi, S. Batzner, et al., "On-the-fly active learning of interpretable
  Bayesian force fields for atomistic rare events" (FLARE), *npj Computational Materials* **6**, 20
  (2020). DOI:10.1038/s41524-020-0283-z, arXiv:1904.02042. — GP-variance uncertainty gate; the basis
  for the uncertainty-gated escalation pattern (§4) and the method-tagged `uncertainty` field (§5).
- A. S. Rosen, A. M. Ganose, et al., "Jobflow: Computational Workflows Made Simple," *Journal of Open
  Source Software* **9**(93), 5995 (2024). DOI:10.21105/joss.05995. — `Response(detour/replace)` is
  the primitive the dynamic MLIP modes (escalation/AL/fine-tune) emit.
- A. H. Larsen, J. J. Mortensen, J. Blomqvist, et al., "The atomic simulation environment — a Python
  library for working with atoms," *J. Phys.: Condens. Matter* **29**, 273002 (2017).
  DOI:10.1088/1361-648X/aa680e. — The ASE `Calculator` interface that is the universal boundary every
  MLIP (and DFT engine) implements; `MlipCalculatorStage` lifts it up one level.
- quacc – The Quantum Accelerator (recipe `method=` dispatch over ASE force fields). Zenodo
  DOI:10.5281/zenodo.10399417. https://quantum-accelerators.github.io/quacc/ — Precedent for
  selecting an MLIP via a typed spec rather than a deck.
- CrystalMath internal: `adr-007-redesign-overview-adopt-ecosystem.md:18` (frozen 5-code taxonomy +
  9-point list), `adr-008-structure-and-deck-io-on-ase-pymatgen.md:82-85` (ASE
  `SocketIOCalculator`/`FileIOCalculator` hatch — the MLIP insertion seam),
  `adr-009-canonical-data-model-emmet-pydantic-taskdocs.md:97` (`DftCode` enum to widen),
  `adr-011-workflow-engine-jobflow-atomate2-quacc.md:68` (static workflow enum the MLIP patterns
  extend), `adr-012-hpc-execution-jobflow-remote-aiida-optional.md:91,102-104` (the "exactly two
  backends" / `sbatch`-by-construction wall this ADR amends with a narrow inference-only exception),
  `adr-013-multi-code-handoff-and-restart-validation.md:86` (closed `HandoffArtifact` enum gaining
  `MODEL_CHECKPOINT`), `adr-020-reproducibility-and-golden-file-testing.md` (the ML-determinism /
  GPU-tolerance gap the `checkpoint_hash` and tolerance-class key fill).

## Amendment (2026-06-03): consensus-review fixes

A two-reviewer consensus pass surfaced that ADR-021, as originally written, quietly embedded three
*scientific-judgment policies* — surrogate trust, campaign/acquisition strategy, and model identity —
inside an ADR whose job is the calculation-layer *mechanism*. Three new ADRs added this round own
those policy seams; this amendment **scopes 021 to the mechanism and wires it to consume them via
cross-reference, reversing no decision**. The single principle: pull every implicit scientific
judgment out of inert provenance strings and prompts and make it a typed, testable, pluggable object,
then have the existing ADRs *consume* those objects rather than re-implement them.

- **021 owns the MLIP *mechanism* only.** The five usage modes (§4), the `MlipCalculatorStage`, the
  zero-file in-process backend (§6), and the method-tagged uncertainty *field* (§5) stay here. The
  *policy* that reads that field is delegated:
  - **[ADR-025](adr-025-campaign-acquisition-strategy.md) — Campaign & Acquisition Strategy**
    answers "**what should the campaign do next, and when do I spend DFT budget?**": a pluggable
    typed `AcquisitionStrategy.score` over an `UncertaintyEstimate` plus a `CampaignStrategy` loop
    with budget / convergence / stopping and DFT-budget control. The agentic controller (ADR-023) is
    *configured with* a 025 strategy object rather than containing the campaign logic.
  - **[ADR-026](adr-026-trustworthy-mlip-evaluation-applicability-domain.md) — Trustworthy MLIP
    Evaluation & Applicability Domain** answers "**is the surrogate trustworthy enough to act on?**":
    measured-not-asserted trust via an `EvaluationHarness` on Matbench-Discovery-style OOD splits, a
    calibrated `UncertaintyEstimate`, an applicability-domain / OOD (`in_domain`) gate, and the
    escalation thresholds. §5's `uncertainty` field is now an ADR-026 `UncertaintyEstimate`.
  - **[ADR-027](adr-027-model-dataset-registry-lineage.md) — Model & Dataset Registry + Lineage**
    answers "**what exactly is this model/dataset and where did it come from?**": navigable
    `ModelRegistry` / `DatasetRegistry` over the ADR-022 content-addressed store, defining the single
    unified `ModelIdentifier` used everywhere. §2's `MODEL_REGISTRY` entry **is** an ADR-027
    `ModelIdentifier` resolution; §5's provenance carries a `model: ModelIdentifier`. The digest, not
    the weight bytes, is the identity (cf. corrected `adr-009...:315`).
- **The coupling is explicit and one-directional.** ADR-025 consumes ADR-026's `UncertaintyEstimate`
  and escalation threshold at the escalation boundary (an OOD candidate must hit DFT, never skip);
  both 025 and 026 resolve model identity through 027's `ModelIdentifier`. 021 delegates *policy* to
  025/026 and *identity* to 027 and re-litigates none of them.
- **Citation-integrity fix.** The Matbench Discovery F1 upper bound is corrected from the wrong
  `0.57-0.83` to the real **`0.57-0.82`** at every occurrence (§Context, §4 table, §Consequences,
  References). No reference was added that is not already in the verified-canonical set
  (Riebesell et al., Matbench Discovery, arXiv:2308.14920; Batatia et al., MACE; Deng et al., CHGNet;
  Vandermause et al., FLARE; Ganose et al., atomate2; Rosen et al., jobflow; Larsen et al., ASE).
