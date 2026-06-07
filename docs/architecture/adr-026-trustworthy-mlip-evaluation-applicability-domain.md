# ADR-026: Trustworthy MLIP Evaluation & Applicability Domain — measured (not asserted) surrogate trust: benchmark harness, calibrated uncertainty, OOD/applicability-domain gate, escalation thresholds

**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** none (decides the MLIP-trust *policy* that [ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md) §4-5 leaves implicit — 021 keeps the *mechanism*, 026 owns *when an MLIP result may be believed* — and supplies the per-property tolerance/escalation contract [ADR-020](adr-020-reproducibility-and-golden-file-testing.md) regime-4 only gestures at)
**Depends on:** [ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md) (the `MlipCalculatorStage` whose results are evaluated; the method-tagged `uncertainty` field §5), [ADR-027](adr-027-model-dataset-registry-lineage.md) (the `UncertaintyEstimate`/calibration/OOD metrics attach to the `ModelIdentifier` and Model Card applicability block; the harness reads models *by* `ModelIdentifier`), [ADR-020](adr-020-reproducibility-and-golden-file-testing.md) (the per-property scientific tolerances; the escalation threshold is validated on a held-out OOD split paired with the regime-4 ReFrame tolerance layer)
**Consumed by:** [ADR-025](adr-025-campaign-acquisition-strategy.md) (the `CampaignStrategy` reads this harness's `{calibration, OOD/in_domain, benchmark}` output at the escalation boundary — an OOD candidate must hit DFT, never skip)

> **Amendment (2026-06-07) — consolidation audit ([CONSOLIDATION-PLAN.md](CONSOLIDATION-PLAN.md)):**
> Refresh the dated evidence: the headline benchmark metric has moved from single-number Matbench
> Discovery F1 to **CPS** (combined F1 + geometry RMSD + thermal-conductivity kSRME) — adopt CPS-style
> multi-property scoring. Make **single-model + conformal** the cheap **default** (laptop path);
> deep-ensemble uncertainty becomes **opt-in** (GPU-heavy). The trust *architecture* (calibration +
> applicability-domain gate + escalation thresholds) is unchanged and remains ahead of the field.

## Context

ADR-021 makes an MLIP a first-class `CalculatorStage` peer of DFT and names five usage modes —
surrogate-screen, uncertainty-gated escalation, active learning, pre-relax, Delta-ML. In every one
of those modes **the trust decision is left implicit.** Surrogate-screen treats the MLIP as a
"pre-filter whose survivors are DFT-validated"
(`adr-021-calculatorstage-mlip-foundation-calculators.md:146`) but decides no acceptance gate.
Uncertainty-gated escalation "run[s] DFT when … variance exceeds a threshold"
(`adr-021...:147`) but decides no *value* for the threshold, no requirement that the variance be
*calibrated*, and no test that the surrogate is even in-domain for the chemistry being screened.
ADR-021 §5 mandates only that the `uncertainty` field be *method-tagged* — "ensemble spread vs. GP
variance are not interchangeable" (`adr-021...:163`) — and explicitly defers everything downstream:
"the *trust policy* … is decided in ADR-026; this ADR owns only the mechanism." ADR-020 regime 4
gives MLIP energies per-property tolerances (`adr-020-reproducibility-and-golden-file-testing.md`)
but no *acceptance* gate — a tolerance is a yardstick, not a decision about whether to spend DFT.

**The result is that surrogate trust is asserted, not measured.** "Trust the MACE screen, then DFT
the top-k" is a sentence in a Flow factory or — worse, before the redesign — a sentence in an LLM
prompt. There is no decided object that answers "*is* this surrogate good enough to act on, here,
now, for this property?" with a number on held-out data. Three failure modes follow directly:

- **In-distribution test error is reported as if it were trust.** A universal MLIP's headline
  accuracy is measured on data drawn from its training distribution. CrystalMath's whole point is to
  compute *novel* structures — exactly the out-of-distribution regime where that number does not
  hold. Matbench Discovery (Riebesell et al. 2023) exists *because* the field needed an
  out-of-distribution stability-prediction benchmark; its real universal-MLIP F1 spans **0.57-0.82**
  (the value ADR-021 §4 now carries after its 2026-06-03 citation-integrity fix, corrected from the
  earlier optimistic "0.83") — and even that F1 is for thermodynamic stability, a proxy that does
  **not** transfer to phonon or elastic accuracy.
- **Raw uncertainty is treated as if it were calibrated.** A neural-network potential's ensemble
  spread or single-model variance is a *number*, but it is not automatically a *coverage guarantee*.
  Single-model UQ for NN potentials does not consistently beat deep ensembles (Tan et al. 2023), and
  calibration is itself a measurable property that must be checked, not assumed (Wang 2023). An
  escalation gate that compares an *un*-calibrated variance to a fixed cutoff is comparing the wrong
  quantity.
- **Calibrated uncertainty degrades silently far from training data.** Even a well-calibrated
  estimator is only calibrated *on its calibration distribution*. ML materials models degrade under
  distribution shift (Li et al. 2023), and the degradation is silent: a confident, wrong surrogate
  far from its training set produces a small uncertainty and a wrong answer. Without a separate
  in/out-of-domain signal, the escalation gate cannot tell "confidently right" from "confidently
  wrong."

These are three *orthogonal* failures — a model can be benchmark-strong but mis-calibrated, or
well-calibrated in-domain but silently extrapolating, or in-domain but benchmark-weak on the target
property. They need three separately-testable capabilities, not one conflated "trust score." And
because the surrogate's training set *grows every active-learning cycle* (ADR-021 §4, ADR-025), the
domain boundary and the calibration set are not fixed: they must be re-fit after every retrain or
they certify a stale region of chemistry. ADR-021 supplies the mechanism (the modes, the
method-tagged field); this ADR supplies the policy that decides when a result those modes produce
may be believed.

## Decision

**Surrogate trust is MEASURED on held-out, distribution-shifted data and exposed as typed objects
ADR-025 consumes at the escalation boundary — never asserted in a prompt or implied by a mode.**
Provide three orthogonal, separately-testable capabilities: (1) an `EvaluationHarness` built around
Matbench Discovery *semantics* with property-specific OOD splits; (2) a typed `UncertaintyEstimate`
with calibrated epistemic uncertainty (deep ensembles baseline) wrapped in distribution-free
conformal prediction; (3) an explicit applicability-domain / OOD gate that sets `in_domain`. The
escalation threshold is then a testable policy object: **trust the surrogate to skip-or-precede DFT
iff (conformal interval width < per-property tolerance) AND `in_domain == true`; otherwise escalate
to DFT.**

### 1. The `EvaluationHarness` measures trust on Matbench-Discovery-style OOD splits, per property

Introduce `crystalmath.evaluation` with an `EvaluationHarness` that emits, for a model resolved by
its ADR-027 `ModelIdentifier`, a typed `HarnessReport{benchmark, calibration, ood}` measured on
**held-out, distribution-shifted** data — not in-distribution test error.

- **Matbench Discovery is the methodology *template*, not the only metric.** Riebesell et al. (2023)
  is the canonical out-of-distribution leaderboard: predict the thermodynamic stability of unseen
  structures, the regime CrystalMath actually operates in. The harness reproduces its *semantics*
  (train on one chemical region, evaluate on a disjoint one) and pins the reference universal MLIPs
  it ranks — CHGNet (Deng et al. 2023) and MACE (Batatia et al. 2022) — as both benchmark anchors
  and the default ensemble members for §2.
- **Property-specific held-out splits, because stability-F1 does not transfer.** A high
  Matbench-Discovery F1 is a *formation-energy/stability* score; it says nothing about phonon or
  elastic accuracy. The harness therefore carries a **per-property** OOD split (relaxed energy,
  phonon, elastic, …) and emits a per-property metric. ADR-025's escalation gate reads the metric
  for the *target* property of the campaign, never a global "trust score."
- **The real universal-MLIP F1 range is 0.57-0.82** (Riebesell et al. 2023). This corrects ADR-021
  §4's "0.83" upper bound; the harness reports the measured number for the specific pinned model, not
  a leaderboard headline.

The harness output is what ADR-025's `CampaignStrategy` reads at the escalation boundary and what
attaches to ADR-027's Model Card applicability block. It is the single home of "how good is this
surrogate, measured" — the analogue, for ML trust, of what `crystalmath validate` (ADR-024) is for
DAG structure.

### 2. `UncertaintyEstimate` is a typed object with calibrated epistemic uncertainty + conformal coverage

ADR-021's method-tagged `uncertainty` field is given a typed shape:

```python
class UncertaintyEstimate(BaseModel):
    mean: float
    epistemic: float            # model uncertainty (ensemble disagreement / GP variance)
    aleatoric: float            # irreducible data noise
    in_domain: bool             # set by the §3 applicability-domain gate
    calibration_method: str     # method-tag: which estimator + which conformal wrapper produced this
```

- **Deep ensembles are the calibrated-epistemic baseline.** Lakshminarayanan et al. (2017) is the
  simple, strong baseline; for NN potentials single-model UQ does **not** consistently beat ensembles
  (Tan et al. 2023). Ensemble disagreement across the §1 reference members (MACE/CHGNet) is the
  default `epistemic` source.
- **Cheaper single-pass alternatives are pluggable behind the same interface.** GMM-on-features
  (Zhu et al. 2023) and MC-dropout (Wen & Tadmor 2020) trade calibration for one forward pass; both
  satisfy the `UncertaintyEstimate` contract so a budget-constrained campaign can swap them in. The
  `calibration_method` tag records which was used, so an escalation gate never compares incomparable
  numbers (the same anti-foot-gun ADR-021 §5 motivates).
- **Conformal prediction wraps *any* of them to give finite-sample coverage.** A raw `epistemic`
  number is not a guarantee; distribution-free conformal prediction (Angelopoulos & Bates 2021;
  Shafer & Vovk 2008) converts it into an interval with finite-sample marginal coverage on a held-out
  calibration set. **Prefer group-conditional / Mondrian conformal keyed on composition or structure
  class**, because marginal coverage is uneven across chemistries — a marginally-valid interval can
  systematically under-cover a minority chemistry. The conformal interval *width* is the quantity the
  §4 escalation threshold compares to a per-property tolerance.
- **Calibration is measured, not assumed.** Calibration is a surveyed, measurable property
  (Wang 2023); the harness §1 emits a calibration metric (e.g. coverage vs. nominal) so a
  mis-calibrated model is caught at evaluation time, not at escalation time.

### 3. An explicit applicability-domain / OOD gate sets `in_domain`

Because calibrated uncertainty degrades *silently* far from training data (Li et al. 2023), a
separate in/out-of-domain signal is mandatory and orthogonal to the uncertainty magnitude.

- **Feature-space / latent-distance or GMM-density on features** — the same machinery as Zhu et al.
  (2023) — scores how far a candidate sits from the training distribution and sets the typed
  `in_domain: bool` on the `UncertaintyEstimate`. This reuses, rather than reinvents, the §2
  GMM-on-features estimator: one feature pass yields both a cheap epistemic signal and the OOD score.
- **The gate runs *before* any surrogate result is trusted to skip or precede DFT.** An OOD candidate
  (`in_domain == false`) is never trusted on a low uncertainty alone; ADR-025's loop must route it to
  DFT. This closes the confident-but-wrong-extrapolation failure mode at the policy boundary, not in
  prose.
- **The OOD model and the conformal calibration set MUST be re-fit after every active-learning
  retrain.** The training set — and therefore the domain — expands each cycle (ADR-021 §4). A domain
  model fit to cycle *n* would wrongly flag cycle-*n+1* in-domain candidates as OOD (or vice versa).
  Re-fitting the domain model and re-conformalizing on the grown set is a declared step of the
  retrain pattern, not an afterthought.

### 4. The escalation threshold is an explicit, testable policy object

The trust decision is a single typed predicate, validated on a held-out OOD split paired with the
ADR-020 regime-4 ReFrame tolerance layer:

> **Trust the surrogate to skip-or-precede DFT for property `P` iff
> `conformal_interval_width(P) < tolerance(P)` AND `in_domain == true`; otherwise escalate to DFT.**

- `tolerance(P)` is the **per-property** ADR-020 regime-4 scientific tolerance — the contract ADR-020
  regime 4 only gestures at, now made the right-hand side of an explicit gate.
- The predicate is a *testable* object: a known-OOD candidate must fail it (escalate), a known
  in-domain low-width candidate must pass it (skip) — golden/negative fixtures under ADR-020's suite,
  mirroring ADR-024's known-bad-DAG fixtures.
- It is **never** prompt text and **never** a mode. ADR-025's `CampaignStrategy` is *configured with*
  this threshold object; it does not embed the logic. An MLIP result that fails the gate never becomes
  a published `TaskDocument` on a trust-bearing path without DFT confirmation — the MLIP analogue of
  `allow_stub_execution` / `allow_restart_skew`, with a single explicit logged override.

This three-part output — calibration + OOD/`in_domain` + per-property benchmark metric — is exactly
what ADR-025's `CampaignStrategy` reads at the escalation boundary (an OOD candidate must hit DFT,
never skip) and what attaches to ADR-027's Model Card applicability block.

## Alternatives Considered

**A. Assert trust mode-by-mode (status quo in ADR-021): the surrogate-screen survivors go to DFT, the
escalation threshold is a constant in the Flow factory.** The minimal change: keep the five modes,
hard-code a variance cutoff. *Why not:* it conflates the three orthogonal failures (benchmark,
calibration, domain) into one un-measured constant. A fixed cutoff on an *un*-calibrated, possibly
*out-of-domain* variance is comparing the wrong quantity in the wrong region — precisely the silent
confident-wrong failure (Li et al. 2023). The number must be measured on held-out shifted data and
carry a coverage guarantee, which a constant cannot.

**B. Use in-distribution test error (or a single Matbench-Discovery F1) as the trust signal.** Report
the model's headline accuracy and gate on it. *Why not:* CrystalMath computes *novel* structures, the
out-of-distribution regime where in-distribution error does not hold — the exact reason Matbench
Discovery exists (Riebesell et al. 2023). And a stability F1 is a *proxy*: a model strong on
formation-energy F1 can be weak on phonons or elastic constants. The harness must use
Matbench-Discovery *semantics* (OOD splits) *and* property-specific held-out splits, and emit the
metric for the campaign's target property — not one global score.

**C. A single-model uncertainty head instead of deep ensembles.** One forward pass, no N-model cost.
*Why not as the default:* for NN potentials single-model UQ does not consistently outperform
ensembles (Tan et al. 2023). Ensembles are kept as the calibrated baseline; the single-pass methods
(GMM-on-features, MC-dropout) are admitted as *pluggable* alternatives behind the same
`UncertaintyEstimate` interface for budget-constrained campaigns, with the calibration metric (§1)
catching the accuracy they trade away. This is "ensembles by default, cheaper by choice," not
"cheaper by default."

**D. Trust the raw uncertainty number without conformal calibration.** Compare the ensemble spread
directly to a cutoff. *Why not:* a raw variance is not a coverage guarantee, and marginal calibration
is uneven across chemistries. Distribution-free conformal prediction (Angelopoulos & Bates 2021;
Shafer & Vovk 2008) gives a finite-sample guarantee that wraps any estimator; group-conditional /
Mondrian variants keyed on composition fix the per-chemistry under-coverage a marginal interval
hides. The cost is a held-out calibration set and a re-fit each retrain — paid because the
alternative is an escalation gate with no guarantee.

**E. Fold the OOD/in-domain check into the uncertainty magnitude (no separate gate).** Treat "high
uncertainty" as "out of domain." *Why not:* the two degrade *independently*. A model can be confidently
wrong far from its training data — small uncertainty, large error (Li et al. 2023). The applicability
domain needs its own signal (latent-distance / GMM-density, Zhu et al. 2023); `in_domain` is a typed
boolean *orthogonal* to `epistemic`, and ADR-025's gate requires **both** (`width < tol` AND
`in_domain`). Collapsing them reopens the silent-extrapolation hole.

**F. Skip the harness and let ADR-025's campaign decide trust at run time from whatever the model
reports.** Simpler — no evaluation infrastructure. *Why not:* it puts trust back where the redesign
is pulling it *out* of — an implicit run-time judgment rather than a measured, typed, pre-computed
object. The harness's whole value is that trust is *measured ahead of time* on held-out shifted data
and *read* at the boundary, the same posture ADR-024 takes for structure (`validate` ahead of
submission) and ADR-020 takes for physics (tolerances measured against golden files). Trust is a
property of the model+property+domain, computed once per (re)train, not re-derived per candidate.

## Consequences

### Positive
- **Surrogate trust is a measured, typed object, not a prompt sentence or a mode.** The escalation
  decision (`width < tol` AND `in_domain`) is a testable predicate with golden/negative fixtures —
  the ML analogue of ADR-024's static DAG check, closing the policy gap ADR-021 §4-5 leaves implicit.
- **The three orthogonal failures are caught separately.** Benchmark-weak, mis-calibrated, and
  out-of-domain are distinct signals (`HarnessReport.benchmark`, `.calibration`, `in_domain`), so a
  model that is strong on one and weak on another cannot pass on its strong axis alone.
- **OOD candidates can never silently skip DFT.** The applicability-domain gate sets `in_domain`, and
  ADR-025 must route `in_domain == false` to DFT — closing the confident-but-wrong-extrapolation hole
  that an uncertainty cutoff alone leaves open (Li et al. 2023).
- **Coverage is guaranteed, not hoped.** Conformal prediction gives finite-sample coverage wrapping
  any estimator (Angelopoulos & Bates 2021), and group-conditional variants fix per-chemistry
  under-coverage — so the escalation gate compares a *guaranteed* interval width, not a raw number.
- **The 0.57-0.82 correction lands.** The harness reports the measured per-property number for the
  pinned model, replacing ADR-021's optimistic "0.83" headline with a measured value, per property.
- **It feeds the existing spine surgically.** The `HarnessReport` is read by ADR-025 at the escalation
  boundary, resolves the model through ADR-027's `ModelIdentifier`, attaches to ADR-027's Model Card
  applicability block, and uses ADR-020's regime-4 per-property tolerances as its right-hand side —
  no locked decision is reopened.

### Negative / Tradeoffs
- **Deep ensembles cost N forward passes / N trainings.** The calibrated baseline is not free; the
  single-pass alternatives (GMM-on-features, MC-dropout) are admitted behind the same interface to
  buy back speed, but they trade calibration the harness must then measure. This is a real compute
  surface behind the optional `[ml]` extra.
- **The OOD model and conformal calibration set must be re-fit every active-learning retrain.** The
  domain expands each cycle, so a stale domain/calibration model certifies the wrong region. The
  retrain pattern must carry the re-fit step, and a missed re-fit is a silent-wrong-trust bug — the
  domain-side analogue of a stale cache.
- **Conformal coverage is only marginal unless group-conditional.** Plain conformal can systematically
  under-cover a minority chemistry; the Mondrian/group-conditional variant fixes it but needs a
  composition/structure-class key and enough calibration points per group — a data-budget cost for
  sparsely-sampled chemistries.
- **Per-property tolerances are physics judgments.** `tolerance(P)` is the same kind of expert-set
  number ADR-020/ADR-022 already carry; a wrong tolerance makes the gate too eager (waste) or too
  timid (over-escalate). It is set in ADR-020's regime-4 contract, not invented here, but it is a
  human judgment the gate's soundness rests on.
- **A second evaluation surface.** The harness is infrastructure beyond ADR-020's golden-file suite;
  the §6-style boundary (ADR-024) keeps it from re-implementing physics tolerances — the harness
  *consumes* ADR-020's tolerances, it does not redefine them.

### Migration impact
1. Add `crystalmath.evaluation` with `EvaluationHarness` emitting `HarnessReport{benchmark,
   calibration, ood}` on per-property OOD splits (Matbench-Discovery semantics); pin MACE/CHGNet as
   reference members behind the `[ml]` extra.
2. Type ADR-021's `uncertainty` field as `UncertaintyEstimate{mean, epistemic, aleatoric, in_domain,
   calibration_method}`; implement the deep-ensemble baseline plus pluggable GMM-on-features /
   MC-dropout estimators behind one interface.
3. Add the conformal wrapper (group-conditional / Mondrian keyed on composition/structure class) that
   converts any estimator's raw uncertainty into a finite-sample-coverage interval.
4. Add the applicability-domain / OOD gate (latent-distance / GMM-density on features) setting
   `in_domain`; wire the re-fit-on-retrain step into the ADR-021/ADR-025 active-learning pattern.
5. Define the escalation threshold object `(conformal_width(P) < tolerance(P)) AND in_domain` against
   ADR-020 regime-4 tolerances; expose it for ADR-025's `CampaignStrategy` to be configured with.
6. Add golden/negative fixtures under ADR-020's suite: a known-OOD candidate must fail the gate
   (escalate), a known in-domain low-width candidate must pass it (skip); attach `HarnessReport` to
   ADR-027's Model Card applicability block.

## References

- J. Riebesell, R. E. A. Goodall, P. Benner, et al., "Matbench Discovery — A framework to evaluate
  machine learning crystal stability predictions," arXiv:2308.14920 (2023). — The canonical
  out-of-distribution stability-prediction leaderboard; the methodology template for §1's harness and
  the source of the corrected universal-MLIP F1 range 0.57-0.82.
- I. Batatia, D. P. Kovács, G. Simm, C. Ortner, G. Csányi, "MACE: Higher Order Equivariant Message
  Passing Neural Networks for Fast and Accurate Force Fields," NeurIPS 2022, arXiv:2206.07697. —
  Reference universal MLIP for the §1 benchmark and a default §2 ensemble member.
- B. Deng, P. Zhong, K. Jun, et al., "CHGNet as a pretrained universal neural network potential for
  charge-informed atomistic modelling," *Nature Machine Intelligence* (2023).
  DOI:10.1038/s42256-023-00716-3. — Reference universal MLIP for the §1 benchmark and a default §2
  ensemble member.
- B. Lakshminarayanan, A. Pritzel, C. Blundell, "Simple and Scalable Predictive Uncertainty
  Estimation using Deep Ensembles," NeurIPS 2017, arXiv:1612.01474. — The calibrated-epistemic
  baseline for §2's `UncertaintyEstimate`.
- K. Tan, et al., "Single-model uncertainty quantification in neural network potentials does not
  consistently outperform model ensembles," *npj Computational Materials* (2023), arXiv:2305.01754. —
  Evidence that ensembles remain the §2 default for NN-potential UQ over single-model methods.
- Y. Zhu, S. Batzner, A. Musaelian, B. Kozinsky, "Fast Uncertainty Estimates in Deep Learning
  Interatomic Potentials," *J. Chem. Phys.* (2023), arXiv:2211.09866. — The GMM-on-features single-pass
  UQ that is both a §2 cheaper estimator and the §3 latent-density OOD/applicability-domain signal.
- M. Wen, E. B. Tadmor, "Uncertainty quantification in molecular simulations with dropout neural
  network potentials," *npj Computational Materials* **6**, 124 (2020).
  DOI:10.1038/s41524-020-00390-8. — The MC-dropout option for §2's pluggable `UncertaintyEstimate`,
  documenting the speed/calibration tradeoff.
- A. N. Angelopoulos, S. Bates, "A Gentle Introduction to Conformal Prediction and Distribution-Free
  Uncertainty Quantification," arXiv:2107.07511 (2021). — The distribution-free finite-sample coverage
  wrapper that converts any §2 estimate into the guaranteed interval §4's threshold compares.
- G. Shafer, V. Vovk, "A Tutorial on Conformal Prediction," *Journal of Machine Learning Research*
  (2008), arXiv:0706.3188. — The foundational conformal-prediction reference underpinning §2's
  coverage guarantee.
- K. Li, B. DeCost, K. Choudhary, M. Greenwood, J. Hattrick-Simpers, "A critical examination of
  robustness and generalizability of machine learning prediction of materials properties," *npj
  Computational Materials* (2023), arXiv:2210.13597. — Evidence that ML materials models degrade under
  distribution shift, motivating §3's applicability-domain / OOD gate.
- C. Wang, "Calibration in Deep Learning: A Survey of the State-of-the-Art," arXiv:2308.01222 (2023).
  — Establishes calibration as a measurable property, grounding §1's "trust must be measured"
  calibration metric.
- CrystalMath internal: [ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md)
  (`adr-021...:146-147,163` — the surrogate-screen / uncertainty-gated modes and the method-tagged
  `uncertainty` field whose trust policy this ADR decides; the "0.83" F1 corrected here),
  [ADR-020](adr-020-reproducibility-and-golden-file-testing.md) (the regime-4 per-property scientific
  tolerances that are the right-hand side of §4's escalation threshold),
  [ADR-025](adr-025-campaign-acquisition-strategy.md) (the `CampaignStrategy` configured with §4's
  threshold object, consuming this harness's output at the escalation boundary),
  [ADR-027](adr-027-model-dataset-registry-lineage.md) (the `ModelIdentifier` the harness reads models
  by, and the Model Card applicability block this ADR's metrics attach to).
