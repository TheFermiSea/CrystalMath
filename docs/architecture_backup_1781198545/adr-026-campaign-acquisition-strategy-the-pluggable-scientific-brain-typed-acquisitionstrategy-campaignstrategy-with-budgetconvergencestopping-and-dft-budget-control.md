---
adr_id: 026
title: "Campaign Acquisition Strategy The Pluggable Scientific Brain Typed Acquisitionstrategy Campaignstrategy With Budgetconvergencestopping And Dft Budget Control"
status: "Accepted"
date: "2026-06-11"
macro_context: "crystalmath-tui-core"
---

# ADR-026: Campaign Acquisition Strategy The Pluggable Scientific Brain Typed Acquisitionstrategy Campaignstrategy With Budgetconvergencestopping And Dft Budget Control



**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** none (extracts the campaign/acquisition *policy* that [ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md) §4-5 and [ADR-023](adr-023-agentic-control-plane-mcp-ai-provenance.md) §1/§4 leave implicit; ADR-021 keeps the MLIP *mechanism*, ADR-023's controller is *configured-with* a strategy from this ADR)
**Depends on:** [ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md) (the `MlipCalculatorStage` mechanism and the five MLIP usage modes this strategy *drives*), [ADR-026](adr-026-trustworthy-mlip-evaluation-applicability-domain.md) (this ADR consumes its `UncertaintyEstimate`, applicability-domain gate, and escalation threshold at the escalation boundary), [ADR-023](adr-023-agentic-control-plane-mcp-ai-provenance.md) (the `CampaignController` is *configured-with* an `AcquisitionStrategy` + `CampaignStrategy` rather than containing the logic), [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) (a `CampaignStrategy` emits `Response(detour/replace)` sub-DAGs over the `make_*_flow` factories)
**Consumed by:** [ADR-023](adr-023-agentic-control-plane-mcp-ai-provenance.md) (the `CampaignController` holds a strategy object; the propose→screen→validate→retrain loop *is* the `CampaignStrategy`), [ADR-024](adr-024-static-typed-workflow-dag-validation.md) (the escalation detours a `CampaignStrategy` emits are the "open detour points" the static checker re-validates on materialization)

## Context

CrystalMath's whole reason to carry an MLIP layer (ADR-021) is to **spend expensive DFT budget
where it buys the most**: screen cheaply, escalate to DFT only when the cheap answer is untrustworthy
or the design space is under-explored, retrain, repeat. That is a *policy* — a sequence of judgment
calls about what to compute next and when to pay for an oracle — and right now CrystalMath has **no
home for it.** The judgment is scattered, asserted, and un-typed:

- **ADR-021 §4 names five MLIP usage modes** (pre-relax, surrogate-screen, uncertainty-gated
  escalation, active-learning, Delta-ML/fine-tune,
  `adr-021-calculatorstage-mlip-foundation-calculators.md:138-156`) but is explicit that these are
  *mechanisms* — "named jobflow patterns, not a new engine." Mode 3 says "if ensemble/GP variance
  exceeds **a threshold**, escalate to DFT"; mode 4 says "label **uncertain** points with DFT" —
  but *which* threshold, *how* uncertainty is measured and calibrated, *when* the loop stops, and
  *how* the next candidate is chosen are all left as the word "threshold." The policy is implied by
  the mode, never decided.
- **ADR-023 §1/§4 makes a `CampaignController` that COMPOSES the ADR-011 `make_*_flow` factories**
  and emits jobflow `Response(detour/replace)` for propose→MLIP-screen→DFT-validate→retrain
  (`adr-023-agentic-control-plane-mcp-ai-provenance.md`). ADR-023 §4 correctly insists candidates
  are "hypotheses, not results" that MUST pass screen→validate — but the *steering logic* (the
  acquisition score that ranks candidates, the budget that bounds DFT calls, the convergence test
  that ends the campaign) has no decided shape. If that logic lives anywhere today it lives **inside
  an LLM prompt** the agent emits — exactly the inert-string anti-pattern two independent reviews
  flagged: the scientific judgment that decides whether to spend a DFT allocation is *unwritten,
  untestable, and unpinned.*
- **ADR-020 regime 4 gives MLIP energies per-property tolerances** but no *acquisition* primitive:
  tolerances say whether two numbers agree, not which candidate to compute or which fidelity to
  query.

**The field has already converged on the right decomposition, and it is not "prompt the LLM."**
Every battle-tested atomistic active-learning workflow factors into three typed pieces: (1) an
**`UncertaintyEstimate`** over a candidate (ADR-026 owns *measuring* this); (2) an **acquisition
score** — a pure function `score(candidate, estimate) -> priority` that ranks what to compute next;
and (3) a **campaign loop** that selects by that score, escalates to DFT, retrains, and applies
typed budget/convergence/stopping criteria. The acquisition primitives are well known and few:
uncertainty sampling and query-by-committee over ensemble disagreement grew the ANI training sets
(Smith et al. 2018) and rest on the deep-ensemble disagreement signal (Lakshminarayanan et al.
2017); expected-improvement / UCB / qEI are the canonical Bayesian-optimization acquisition family,
available as a typed, composable library in BoTorch (Balandat et al. 2019); multi-fidelity BO
formalizes choosing *both* candidate and fidelity per unit cost (Takeno et al. 2019); on-the-fly
active learning gates each inline DFT call on a single calibrated variance cutoff (FLARE,
Vandermause et al. 2020, scaled to reactive catalysis in Vandermause et al. 2022); and adversarial,
uncertainty-driven generation actively *seeks* high-uncertainty geometries (Schwalbe-Koda et al.
2021).

The shape these share is the shape ADR-021 §4 and ADR-023 §1 only gesture at. The clean-slate move
the set's mandate invites is to **make the campaign-steering policy a first-class, typed, pluggable
pair of protocols** that the ADR-023 controller is *configured with*, never the controller's
embedded logic — and to draw a single coupling to ADR-026 at the one place a policy is allowed to
trust a cheap answer: the escalation boundary.

## Decision

**Make the campaign-steering policy a first-class pair of typed, pluggable protocols — an
`AcquisitionStrategy` (a pure scoring object) and a `CampaignStrategy` (the budget/convergence/
stopping loop) — that the ADR-023 `CampaignController` is CONFIGURED WITH, never logic the
controller embeds. Provide a thin-adapter family of named strategies over the field's canonical
primitives, model multi-fidelity DFT-budget control as one `CampaignStrategy` configuration, and
make the escalation boundary the single, one-directional coupling to ADR-026: a low-fidelity score
may skip or precede DFT ONLY if ADR-026's applicability-domain gate passes AND the calibrated
uncertainty is below the escalation threshold; an out-of-domain candidate always routes to DFT.**

### 1. `AcquisitionStrategy` is a pure scoring object over an `UncertaintyEstimate`

Introduce a `crystalmath.campaign` module whose narrowest seam is a pure function:

```python
class AcquisitionStrategy(Protocol):
    """score(candidate, estimate) -> priority. Pure, stateless, testable. No I/O, no DFT, no LLM."""
    def score(self, candidate: Candidate, estimate: UncertaintyEstimate) -> float: ...
```

`UncertaintyEstimate{mean, epistemic, aleatoric, in_domain: bool, calibration_method}` is **defined
in ADR-026** and supplied to `score` by the loop; this ADR only *consumes* it. Because `score` is a
pure function of `(candidate, estimate)` it is unit-testable in isolation — the scientific judgment
that ranks candidates becomes a function with a golden-file test, not a sentence in a prompt.
The named strategies are **thin adapters**, not bespoke math:

| Strategy | Score | Adapter over |
|---|---|---|
| **`UncertaintySampler`** | rank by `estimate.epistemic` | ensemble disagreement (Lakshminarayanan et al. 2017) |
| **`QueryByCommittee`** | rank by committee disagreement across ensemble members | Smith et al. 2018 (grew ANI training sets exactly this way) |
| **`ExpectedImprovement` / `UpperConfidenceBound` / `qEI`** | the named BoTorch acquisition value | BoTorch acquisition functions (Balandat et al. 2019; botorch.org) |
| **`AdversarialGenerator`** | differentiable uncertainty-maximizing geometry search | Schwalbe-Koda et al. 2021 |

The EI/UCB/qEI adapters are deliberately *adapters over BoTorch* rather than re-implemented math:
BoTorch is the canonical typed, composable acquisition library, so `ExpectedImprovement.score`
delegates to a BoTorch acquisition function evaluated on the candidate. This is the keystone of the
"thin adapter" decision — adding an acquisition function is registering an adapter, not writing a
new optimizer.

### 2. `CampaignStrategy` is the typed loop with budget/convergence/stopping

`CampaignStrategy` owns the loop ADR-023 §1 composes but does not specify: select candidates by an
`AcquisitionStrategy`, escalate to DFT, retrain, and apply **typed** termination criteria.

```python
class CampaignStrategy(Protocol):
    acquisition: AcquisitionStrategy
    budget_remaining: DftBudget        # DFT cost units still available
    convergence: ConvergenceCriterion  # "the campaign has learned enough"
    stopping: StoppingCriterion        # "stop regardless (budget, wall-clock, no-improvement)"
    def step(self, pool: CandidatePool, estimates: UncertaintyEstimates) -> CampaignDecision: ...
```

`step` returns a typed `CampaignDecision` — *which* candidates to escalate to DFT, whether to
retrain, whether to stop — that the ADR-023 controller realizes as `make_*_flow` factory calls and
`Response(detour/replace)` sub-DAGs (ADR-011). `budget_remaining`, `convergence`, and `stopping` are
**typed objects, not prose**: a campaign that exhausts `budget_remaining`, meets `convergence`, or
trips `stopping` halts — and *why* it halted is a recorded, auditable value, not an LLM's say-so.
Three named families ship:

- **`ActiveLearning`** — the **cheap, calibrated-uncertainty-threshold gate**. FLARE-style on-the-fly:
  a single scalar variance cutoff decides each inline DFT call (Vandermause et al. 2020; scaled to
  heterogeneous catalysis in Vandermause et al. 2022). The acquisition is `UncertaintySampler` /
  `QueryByCommittee`; the loop escalates exactly when the calibrated uncertainty crosses the
  threshold and stops when the threshold stops firing within budget. **This family deliberately
  avoids pulling PyTorch/GPyTorch** — a scalar threshold needs none of it.
- **`BayesianOptimization`** — GP/BoTorch design-space search. The acquisition is an
  `ExpectedImprovement`/`UCB`/`qEI` adapter; the loop fits a GP surrogate and selects the
  acquisition-maximizing candidate. Reserved for design-space campaigns over thousands of
  candidates, where the GP cost (cubic in observations) and the PyTorch/GPyTorch dependency are
  justified.
- **`ExhaustiveScreening`** — the Matbench-style fan-out filter: score every candidate, keep the
  top-k, escalate survivors to DFT. The acquisition is any `AcquisitionStrategy`; the loop is a
  static fan-out with a budget-bounded survivor set.

### 3. `MultiFidelity` is a `BayesianOptimization` configuration — this IS the DFT-budget control

The MLIP/DFT relationship in CrystalMath *is* a fidelity hierarchy: MLIP energy is cheap and biased,
DFT is expensive and trusted. `MultiFidelity` is a **configuration of `BayesianOptimization`** that
models `MLIP(cheap)` and `DFT(oracle)` as an explicit fidelity hierarchy and chooses **both the
candidate AND the fidelity per unit DFT cost** — which *is* the DFT-budget control the reviewers
asked for, not new infrastructure. It is grounded in max-value-entropy multi-fidelity BO (Takeno
et al. 2019) and realized over BoTorch's cost-aware multi-fidelity acquisition (botorch.org). The
campaign maximizes information gained per unit of DFT cost, spending the oracle only where a DFT
query is worth more than its price.

`MultiFidelity` assumes the cheap fidelity is *informative* about the expensive one. When the MLIP
is badly out-of-domain that assumption breaks and the policy would waste DFT budget — which is
exactly why the escalation boundary (§4) runs ADR-026's applicability-domain gate *before* trusting
any low-fidelity score.

### 4. The escalation boundary is the single, one-directional coupling to ADR-026

A `CampaignStrategy` may trust a low-fidelity / surrogate score to **skip or precede** a DFT call —
the entire economic point of the MLIP layer — but only through one gate, stated once:

> **A surrogate score may skip or precede DFT iff ADR-026's applicability-domain gate passes
> (`estimate.in_domain == True`) AND the calibrated uncertainty is below the escalation threshold.
> An out-of-domain candidate ALWAYS routes to DFT and is never skipped.**

This is the *only* coupling between the two ADRs and it is **one-directional**: ADR-025 consumes
ADR-026's `UncertaintyEstimate{in_domain, calibration_method}` and its escalation threshold; ADR-026
never depends on a campaign. The gate closes the silent-confident-but-wrong failure mode: a
calibrated uncertainty degrades quietly far from training data, so `in_domain` is a separate,
mandatory veto on top of the threshold. This is the MLIP analogue of ADR-024's "an un-validated
sub-DAG is never queued" — an un-trusted (OOD or over-threshold) surrogate result never substitutes
for the DFT oracle on a trust-bearing path.

### 5. Two interface-compatible cost classes are kept deliberately

`ActiveLearning` and `BayesianOptimization` implement the *same* `CampaignStrategy` interface but are
kept as two cost classes on purpose:

- **Cheap scalar-threshold (`ActiveLearning`)** — a calibrated variance cutoff decides each DFT call.
  It pulls **no** PyTorch/GPyTorch and pays **no** GP cost. This is the default for on-the-fly,
  streaming, single-structure loops where one scalar suffices.
- **GP/BO (`BayesianOptimization`/`MultiFidelity`)** — fits a GP and optimizes a BoTorch acquisition.
  It pulls PyTorch/GPyTorch and pays the cubic-in-observations GP cost, and is **reserved** for
  design-space campaigns over thousands of candidates where that cost buys global, cost-aware search.

Keeping both behind one interface lets a campaign pick the right cost for its shape without the
laptop-first user paying GP cost for a threshold loop — the ML stack stays behind ADR-021's optional
`[ml]` extra, and the GP stack behind a further-narrowed BO sub-extra.

### 6. The five ADR-021 modes become mechanisms a `CampaignStrategy` drives

ADR-021's five MLIP usage modes (§4) are *mechanisms*, not policy. Under this ADR they are things a
`CampaignStrategy` **drives**: surrogate-screen is what `ExhaustiveScreening` does with an
`MlipCalculatorStage`; uncertainty-gated escalation is what `ActiveLearning` does at the §4 boundary;
active-learning is the `ActiveLearning` loop; Delta-ML/fine-tune is the retrain step a
`CampaignStrategy` emits as `Response(replace)`. ADR-021 keeps the mechanism (the modes, the
`MlipCalculatorStage`, the model registry); this ADR owns the policy that decides *which* mode fires,
*on which* candidate, *under what* budget, and *when to stop*. ADR-023's `CampaignController` is
reduced to the *executor* of a `CampaignDecision`: it holds a strategy object and realizes its
decisions over the ADR-011 factories — it does not contain the steering logic.

## Consequences

### Positive

- **The scientific judgment leaves the prompt and becomes a tested object.** `score` is a pure
  function with a golden-file test; `budget_remaining`/`convergence`/`stopping` are typed values an
  audit log records. The decision to spend a DFT allocation is no longer an unwritten, unpinned LLM
  sentence — it is a registered, version-pinned strategy object, the MLIP analogue of ADR-024's
  "drift is a build failure."
- **The ADR-023 controller is simplified, not duplicated.** ADR-023's `CampaignController` is
  *configured-with* an `AcquisitionStrategy` + `CampaignStrategy` and becomes a thin executor of
  typed `CampaignDecision`s over the ADR-011 factories — the campaign logic lives in one swappable
  place, so a new acquisition function is a new adapter, not a controller rewrite.
- **DFT-budget control is first-class and grounded.** `MultiFidelity` models MLIP/DFT as an explicit
  fidelity hierarchy and chooses candidate *and* fidelity per unit cost (Takeno et al. 2019; BoTorch
  cost-aware multi-fidelity) — the budget control the reviewers asked for, expressed as a
  configuration of the same seam rather than new machinery.
- **The trust coupling is explicit and minimal.** Exactly one boundary (§4) couples campaign policy
  to ADR-026's measured trust, one-directionally; the "OOD ⇒ always DFT" rule closes the
  confident-but-wrong failure mode that silently corrupts an active-learning campaign.
- **Two cost classes, one interface.** A threshold loop pays no GP cost and pulls no GPyTorch; a
  design-space campaign gets global BoTorch search — both behind the same `CampaignStrategy`
  contract, so the right cost is a configuration choice, not a fork.
- **The escalation detours are exactly ADR-024's open detour points.** A `CampaignStrategy`'s
  run-time `Response(detour/replace)` sub-DAGs are re-validated on materialization by the ADR-024
  static checker — adaptive campaigns stay statically safe with no new machinery.

### Negative / Tradeoffs

- **Per-method calibration thresholds and convergence criteria are physics judgments.** The
  escalation threshold and `convergence` criterion are scientific defaults that must be tuned per
  chemistry/statepoint — the same caveat ADR-020/ADR-022 already carry for tolerances. This ADR
  decides the *shape* (a typed, calibrated cutoff consuming ADR-026's `calibration_method`); the
  *numbers* are physics that must be validated on a held-out split, not asserted.
- **`BayesianOptimization`/`MultiFidelity` pull PyTorch/GPyTorch and pay GP cost.** The GP surrogate
  is cubic in observations and the BoTorch dependency is a real maintenance surface. Mitigation: it
  lives behind a narrowed BO sub-extra and is *reserved* for thousands-of-candidates design-space
  campaigns; the cheap `ActiveLearning` threshold path is the default and pulls neither.
- **The §4 coupling makes ADR-025 useless without ADR-026.** A `CampaignStrategy` cannot honor the
  escalation boundary without ADR-026's `UncertaintyEstimate{in_domain, calibration_method}` and
  threshold. This is deliberate (trust must be *measured*, not asserted) but it means the two ADRs
  land together; a campaign run before ADR-026 exists must treat every candidate as out-of-domain
  and route all of it to DFT (the safe degenerate case).
- **Multi-fidelity assumes the cheap fidelity is informative.** If the MLIP is systematically biased
  the multi-fidelity model wastes budget; the §4 gate bounds this but cannot eliminate a
  well-calibrated-yet-biased surrogate, which only ADR-026's benchmark harness on an OOD split can
  expose.
- **Strategy proliferation risk.** A pluggable seam invites a sprawl of bespoke strategies.
  Mitigation: ship the named families as thin adapters over the canonical primitives (BoTorch for
  BO, scalar threshold for AL) and treat new strategies as adapters that must come with a `score`
  golden-file test, not free-form code.

### Migration impact

1. Add `crystalmath.campaign` with the `AcquisitionStrategy` and `CampaignStrategy` protocols and the
   typed `DftBudget`/`ConvergenceCriterion`/`StoppingCriterion`/`CampaignDecision` value objects.
2. Ship the named `AcquisitionStrategy` adapters (`UncertaintySampler`, `QueryByCommittee`,
   `ExpectedImprovement`/`UpperConfidenceBound`/`qEI` over BoTorch, `AdversarialGenerator`), each with
   a pure-function golden-file test.
3. Ship the three `CampaignStrategy` families (`ActiveLearning` threshold gate with no GPyTorch
   dependency; `BayesianOptimization`/`MultiFidelity` behind a BO sub-extra of ADR-021's `[ml]`
   extra; `ExhaustiveScreening` fan-out).
4. Wire ADR-023's `CampaignController` to be *configured-with* a strategy pair and to realize
   `CampaignDecision`s over the ADR-011 `make_*_flow` factories and `Response(detour/replace)` —
   removing any steering logic from the controller/prompt.
5. Implement the §4 escalation boundary against ADR-026's `UncertaintyEstimate{in_domain,
   calibration_method}` + escalation threshold; an OOD candidate always routes to DFT.
6. Ensure each `CampaignStrategy`'s escalation `Response(detour/replace)` declares an ADR-024
   open-detour point so the materialized sub-DAG is re-validated before its jobs are queued.

## Alternatives Considered

**A. Leave the campaign-steering policy inside the ADR-023 controller (or its LLM prompt).** The
controller already composes the `make_*_flow` factories and emits `Response`; one could let it embed
"if uncertain, escalate" as code or prompt text. *Why not:* this is the exact inert-string
anti-pattern two reviews flagged. A threshold buried in a prompt is untestable, unpinned, and
invisible to provenance; the decision to spend a DFT allocation must be a typed, version-pinned
object with a golden-file test. Pulling the policy out makes the controller a thin executor and the
policy a swappable, audited unit — the same move ADR-024 made by extracting DAG soundness into a
checker rather than leaving it implicit in the runtime.

**B. One `CampaignStrategy` class with mode flags instead of named families.** A single
configurable loop with `mode="active_learning" | "bayes_opt" | "screen"` is fewer types. *Why not:*
it forces every deployment to carry the union of dependencies — the laptop-first threshold user
would pull PyTorch/GPyTorch/BoTorch and the GP cubic cost to run a scalar cutoff. Keeping two
*interface-compatible cost classes* (§5) is the whole point: the cheap path pulls nothing heavy, the
expensive path is reserved for thousands-of-candidate design-space search. One class with flags
collapses that cost distinction.

**C. Re-implement EI/UCB/qEI and multi-fidelity acquisition in-house rather than adapting BoTorch.**
Avoids the PyTorch/GPyTorch dependency entirely. *Why not:* BoTorch is the canonical typed,
composable acquisition library (Balandat et al. 2019) with cost-aware multi-fidelity acquisition
already implemented; re-deriving it is bespoke optimization math we would have to test and maintain
against a moving research frontier. The adapter approach (§1) confines the dependency to the
`BayesianOptimization`/`MultiFidelity` families behind a sub-extra, so the cheap `ActiveLearning`
path never touches it — we get the library where it pays and avoid it where it does not.

**D. Make the escalation decision a property/metamorphic test (ADR-020) rather than a run-time
gate.** One could assert "OOD ⇒ DFT" as a CI property over generated campaigns. *Why not:* ADR-020
tests the *factory code* on CI inputs, not the *specific candidate* a live campaign scores at run
time (the same argument ADR-024 §C makes). The escalation boundary is a per-candidate run-time
decision consuming a per-candidate `UncertaintyEstimate`; it must fire in the loop, not in CI. The
ADR-020 suite still owns the *physics* (does the per-property tolerance hold), and ADR-026's harness
owns *validating the threshold* on a held-out OOD split — but the gate itself is a run-time policy
object, not a test.

**E. Adopt a dedicated active-learning framework (e.g. a FLARE/Ax service) as the campaign engine,
parallel to jobflow.** FLARE and Ax are mature and implement exactly these primitives. *Why not:* it
reintroduces the multiple-orchestration-models sprawl ADR-011 deleted and ADR-021 Alternative E
already rejected. The right move is to *port the primitives* as thin adapters onto the jobflow
`Response`/`Flow` spine CrystalMath already owns (FLARE's scalar-threshold gate becomes
`ActiveLearning`; Ax/BoTorch acquisition becomes the `BayesianOptimization` adapters) — not to bolt
on a second top-level campaign engine. This mirrors ADR-024's "port the discipline, not the
language."

## References

- B. Lakshminarayanan, A. Pritzel, C. Blundell, "Simple and Scalable Predictive Uncertainty
  Estimation using Deep Ensembles," *NeurIPS* (2017). arXiv:1612.01474. — The SOTA-baseline epistemic
  uncertainty source and the disagreement signal behind `UncertaintySampler`/`QueryByCommittee` (§1).
- J. S. Smith, B. Nebgen, N. Lubbers, O. Isayev, A. E. Roitberg, "Less is more: Sampling chemical
  space with active learning," *J. Chem. Phys.* **148**, 241733 (2018). DOI:10.1063/1.5023802,
  arXiv:1801.09319. — Query-by-committee used directly to grow MLIP (ANI) training sets; the concrete
  `QueryByCommittee` acquisition (§1).
- M. Balandat, B. Karrer, D. R. Jiang, et al., "BoTorch: A Framework for Efficient Monte-Carlo
  Bayesian Optimization," (2019). arXiv:1910.06403. https://botorch.org/ , https://ax.dev/ — The
  canonical typed, composable acquisition library (EI/UCB/qEI and cost-aware multi-fidelity); the
  implementation seam the `ExpectedImprovement`/`UpperConfidenceBound`/`qEI`/`MultiFidelity` adapters
  delegate to (§1, §3).
- S. Takeno, H. Fukuoka, Y. Tsukada, et al., "Multi-fidelity Bayesian Optimization with Max-value
  Entropy Search and its Parallelization," *ICML* (2020). arXiv:1901.08275. — Formalizes choosing
  both candidate and fidelity (cheap MLIP vs. DFT oracle) per unit cost — the basis for
  `MultiFidelity` DFT-budget control (§3).
- J. Vandermause, S. B. Torrisi, S. Batzner, et al., "On-the-fly active learning of interpretable
  Bayesian force fields for atomistic rare events" (FLARE), *npj Computational Materials* **6**, 20
  (2020). DOI:10.1038/s41524-020-0283-z, arXiv:1904.02042. — The canonical on-the-fly active-learning
  template: a sparse-GP force field with an explicit calibrated-variance threshold gating each inline
  DFT call — the `ActiveLearning` family (§2).
- J. Vandermause, Y. Xie, J. S. Lim, C. J. Owen, B. Kozinsky, "Active learning of reactive Bayesian
  force fields applied to heterogeneous catalysis dynamics of H/Pt," *Nature Communications* **13**,
  5183 (2022). DOI:10.1038/s41467-022-32294-0, arXiv:2106.01949. — Reactive FLARE scaling on-the-fly
  active learning to catalysis; the `ActiveLearning` threshold gate at scale (§2).
- D. Schwalbe-Koda, A. R. Tan, R. Gómez-Bombarelli, "Differentiable sampling of molecular geometries
  with uncertainty-based adversarial attacks," *Nature Communications* **12**, 5104 (2021).
  DOI:10.1038/s41467-021-25342-8, arXiv:2101.11588. — Uncertainty-driven adversarial candidate
  generation; the `AdversarialGenerator` acquisition that actively seeks high-uncertainty geometries
  (§1).
- A. S. Rosen, A. M. Ganose, et al., "Jobflow: Computational Workflows Made Simple," *Journal of Open
  Source Software* **9**(93), 5995 (2024). DOI:10.21105/joss.05995. — `Response(detour/replace)` is
  the primitive a `CampaignStrategy` emits to materialize escalation/retrain sub-DAGs (§2, §6).
- CrystalMath internal:
  [ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md) (the `MlipCalculatorStage`
  mechanism, the model registry, and the five MLIP modes §4 this strategy drives — `:138-156`),
  [ADR-023](adr-023-agentic-control-plane-mcp-ai-provenance.md) (the `CampaignController` that is now
  *configured-with* an `AcquisitionStrategy`+`CampaignStrategy` rather than embedding the loop),
  [ADR-026](adr-026-trustworthy-mlip-evaluation-applicability-domain.md) (the `UncertaintyEstimate`,
  applicability-domain gate, and escalation threshold consumed at the §4 escalation boundary),
  [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) (the `make_*_flow` factories and the
  `Response(detour/replace)` sub-DAGs a `CampaignStrategy` emits),
  [ADR-024](adr-024-static-typed-workflow-dag-validation.md) (the open-detour points re-validated when
  a `CampaignStrategy`'s escalation sub-DAG materializes),
  [ADR-020](adr-020-reproducibility-and-golden-file-testing.md) (the per-property tolerances and the
  test-time boundary that validates threshold/convergence physics, not the run-time gate itself).
