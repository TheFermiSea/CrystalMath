# ADR-011: Workflow Engine — jobflow Flows (atomate2/quacc recipes) as the One Orchestration Model

**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** none
**Depends on:** [ADR-010](adr-010-single-result-store-jobflow-maggma.md) (the maggma `JobStore`), [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md) (emmet-style `TaskDocument` data model), [ADR-008](adr-008-structure-and-deck-io-on-ase-pymatgen.md) (per-code deck seam)
**Refined by:** [ADR-012](adr-012-hpc-execution-jobflow-remote-aiida-optional.md) (the `ExecutionBackend` seam a `Flow` is submitted to — this ADR introduces the seam; ADR-012 chooses its implementations: jobflow-remote default, AiiDA opt-in)

## Context

CrystalMath today has **five distinct runner base types** and no authoritative one. They do not
share a base class, a job-state enum, or a result type:

- `protocols.py:304` — `WorkflowRunner(Protocol)` (`submit`/`get_status`/`get_result`/`cancel`/
  `list_workflows`), advertised as *the* interface.
- `_vendor/runners/base.py:174` — `BaseRunner(ABC)` and `:552` `RemoteBaseRunner` (a *different*
  method set: `acquire_slot`, `is_connected`, abstract `submit`/poll).
- `quacc/runner.py:71` — `JobRunner(ABC)` (`submit(recipe_fullname, atoms)`) — a third,
  recipe-oriented contract.
- `high_level/runners.py:208` — `BaseAnalysisRunner(ABC)`, which *wraps* a `WorkflowRunner`
  (`high_level/runners.py:249,261`) and is subclassed six times for science types
  (`StandardAnalysis:1441`, `OpticalAnalysis:1609`, `PhononAnalysis:1798`, `ElasticAnalysis:1948`,
  `TransportAnalysis:2073`, `NonlinearOpticsAnalysis:2198`).
- `integrations/slurm_runner.py:252` — `SLURMWorkflowRunner`, a fifth path implementing the
  protocol over its own sbatch logic.

`high_level/runners.py` alone is **2,488 LOC** with six bespoke exception types
(`RunnerError`…`MultiCodeHandoffError`, `:88-132`). Worse, its execution path was, until recently,
a *simulation*: `:117-120` documents that the no-runner case "Previously … silently returned a
fake-success `StepResult(success=True, outputs={'simulated': True})`." The current code gates this
behind `metadata['allow_stub_execution']` (`:1192`, hardened in commit `8497cda`), but the
stub scaffolding is still load-bearing (`:296`, `:406`, `:1200` `outputs={'simulated': True}`,
`:1372` "placeholder result for dry run").

The capability all this machinery exists to provide — **multi-step dependency chaining,
wait-for-completion, and inter-step data handoff** — is itself *incomplete* (issue
`crystalmath-0gs`, P1). The bands workflow explicitly depends on a converged SCF wavefunction
(`workflows/bands.py:3,165`), and the cross-code handoff abstraction is a hand-rolled dataclass
(`integrations/atomate2_bridge.py:222` `CodeHandoff`). So CrystalMath maintains five runner
hierarchies and 2.5k LOC of orchestration scaffolding and *still does not robustly do the one
thing — a dependency DAG with data passed between steps — that those abstractions are for*.

**The ecosystem already provides this decision.** jobflow (Rosen et al. 2024) is a lightweight,
database-agnostic library for exactly this: a `Job` is a deferred function call, a `Flow` is a
DAG of jobs, and the `OutputReference` mechanism passes a job's output as a *lazy reference* into
a downstream job's input — the connectivity is resolved at execution time, which is precisely the
"inter-step data handoff" `high_level/runners.py` reinvents. atomate2 (Ganose et al. 2025) is the
library of materials-science `Maker`/`Flow` recipes built on jobflow (relax → static → bands/DOS,
EOS, phonon via phonopy), and quacc (Rosen, Zenodo 10.5281/zenodo.10399417) provides
`@job`/`@flow`-decorated recipes over ASE/pymatgen that *dispatch unchanged across jobflow, Parsl,
Dask, Prefect, and Covalent* — separating the science (recipe) from the executor (HPC/SLURM/local).
CrystalMath already depends on all three (the `quacc/` package, `integrations/atomate2_bridge.py`,
`integrations/jobflow_store.py`) but treats them as three more co-equal, availability-detected
integrations rather than committing to one orchestration model.

With zero users, the redesign should adopt jobflow as *the* workflow model and delete the bespoke
runner sprawl rather than maintain a homegrown DAG engine the field has already built and tested.

## Decision

**Adopt jobflow as the one workflow/DAG model and quacc/atomate2 recipes as the calculation layer.
Collapse the five runner families into a single thin engine adapter, and delete the bespoke
orchestration scaffolding.**

### 1. jobflow `Flow` is the only workflow model

Every CrystalMath workflow — `relax`, `scf`, `static`, `bands`, `dos`, `gw`, `bse`, `phonon`,
`eos`, `convergence` — is expressed as a jobflow `Flow` of `Job`s. Multi-step dependency chaining
(`crystalmath-0gs`) is jobflow's native `Flow` connectivity; inter-step data handoff is jobflow's
`OutputReference` (a downstream job receives `prev_job.output["wavefunction"]`, resolved at run
time). This **replaces** the hand-rolled wait-for-completion / handoff logic in
`high_level/runners.py` and `workflows/bands.py`.

> **Scope note (see Amendment 2026-06-03):** The named workflow set and its `make_*_flow`
> factories are the *typed building blocks*, not a closed campaign brain. They are **composed by**
> the ADR-023 planner/campaign controller above them, and jobflow `Response(detour/replace)` is
> a first-class dynamic-branching primitive (not merely an error-recovery mechanism). MLIP
> screening / pre-relax / active-learning Flow patterns ([ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md))
> join this set, with high-throughput MLIP screening given a first-class in-allocation home.

### 2. Recipes come from atomate2/quacc where they exist; thin code adapters fill the gaps

- For codes atomate2/quacc support (VASP, and the pymatgen/ASE-backed common workflows), use the
  upstream `Maker`/recipe directly.
- For codes they do not (CRYSTAL23, YAMBO/`yambo_nl`), wrap CrystalMath's per-code seam — the
  `CodeDeckGenerator`/`InputDeck` from [ADR-008](adr-008-structure-and-deck-io-on-ase-pymatgen.md) — in a
  `@job`-decorated quacc-style recipe (stage deck → submit via the ADR-012 backend → parse into
  the ADR-010 `TaskDocument`). The recipe is the *only* place per-code orchestration lives.

### 3. One engine-adapter seam; delete the other four runner hierarchies

The single execution seam is the `ExecutionBackend` protocol defined in **[ADR-012](adr-012-hpc-execution-jobflow-remote-aiida-optional.md)**
(default `JobflowRemoteBackend`, opt-in `AiiDABackend`). A jobflow `Flow` is submitted *to* that
backend; CrystalMath no longer owns a runner abstraction at all. Consequently:

- **DELETE** `high_level/runners.py` (2,488 LOC: `BaseAnalysisRunner` + the six `*Analysis`
  subclasses + six exception types). The science-type taxonomy becomes a set of Flow factories
  (`make_bands_flow(structure, code, params) -> Flow`), not a runner class hierarchy.
- **DELETE** `protocols.py:304 WorkflowRunner`, `_vendor/runners/base.py` (`BaseRunner`/
  `RemoteBaseRunner`), and `quacc/runner.py:71 JobRunner`. The one remaining contract is the
  jobflow `Flow` → `ExecutionBackend` boundary.
- The `quacc/{parsl_runner,mock_runner,covalent_runner}.py` sprawl collapses: quacc *recipes* are
  kept; quacc's pluggable *engine* selection is subsumed by the ADR-012 backend, which is the one
  place an executor (jobflow-remote daemon, or in-allocation Parsl) is chosen.

### 4. Multi-code handoff is a typed edge between jobflow jobs, not a bespoke class

> **Note:** The original `CodeHandoff` dataclass approach described here is superseded by
> ADR-013's `TaskDocument.OutputReference` approach plus validation jobs (e.g.,
> `validate_wavecar`/`validate_restart`). See ADR-013 for the refined multi-code handoff
> contract with typed `HandoffArtifact` edges and mandatory `RestartValidation`.

The multi-code handoff is expressed as an `OutputReference` from a source job's `TaskDocument` to
a target job's input, plus a **mandatory restart-file validation step** (a `@job` that checks
the CRYSTAL `.f9`/`.f98` or VASP `WAVECAR`/`CHGCAR` exists, is non-empty, and matches the expected
structure/checksum before the downstream job consumes it — addressing the stale-restart-file
pitfall where a failed run's `WAVECAR` silently produces wrong results). The canonical VASP→YAMBO
chain becomes a jobflow `Flow` of `[vasp_scf → validate_wavecar → p2y → yambo]` jobs.

### 5. Delete the stub-simulation scaffolding; keep only the gate

The `allow_stub_execution` *gate* (a security non-negotiable per commit `8497cda`) is preserved as
a single explicit dry-run mode at the Flow-submission boundary. But the simulation *scaffolding*
threaded through `high_level/runners.py` (`outputs={'simulated': True}`, the placeholder-result
paths) is **deleted** with that file: a dry run becomes "build the Flow, validate it, do not
submit," not a parallel fake-execution code path that can leak `simulated: True` into results.

## Alternatives Considered

**A. AiiDA `WorkChain` as the one workflow model.** AiiDA (Pizzi et al. 2016; Huber et al. 2020;
Uhrin et al. 2021) is the gold standard for reproducible workflows with an event-based engine and
automatic, immutable provenance, and it has a cross-engine *common workflows* interface (Huber et
al. 2021) that already solves multi-code relax/EOS. *Why not as the default:* it mandates
PostgreSQL + (historically) RabbitMQ and a daemon, and its "everything is an AiiDA node" model is a
heavy adoption cost for a laptop-first TUI with zero users. CrystalMath keeps AiiDA as the **opt-in
heavyweight backend** behind the ADR-012 `ExecutionBackend` seam (the existing `backends/aiida.py`,
`workflows/aiida_launcher.py`), not as the orchestration model every user pays for.

**B. quacc's engine selection *is* the orchestration model (skip jobflow).** quacc can dispatch
recipes over Parsl/Dask/Prefect/Covalent directly, so one could treat quacc as both recipe and
DAG layer. *Why not:* quacc is deliberately thin on *multi-step DAG* semantics — it shines at "run
one recipe, pick an executor," whereas the bands/EOS/phonon/VASP→YAMBO chains CrystalMath needs are
explicit dependency DAGs with typed handoff. jobflow is the purpose-built DAG layer (Rosen et al.
2024) and is the native target for atomate2's multi-step `Maker`s. We use quacc for *recipes* and
jobflow for the *DAG*, which is exactly how the upstream stack composes. *Refined by the Amendment
(2026-06-03):* this alternative's original rejection of Parsl/Dask "except as in-allocation
executors" is **narrowed, not reversed** — high-throughput MLIP screening is now an explicitly
endorsed first-class use of an *in-allocation* Parsl/Dask fan-out under the
[ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md) inference backend, still beneath the
jobflow DAG, never as the top-level orchestration model.

**C. Keep a homegrown runner, rebuilt on PSI/J.** PSI/J (Hategan-Marandiuc et al. 2023) is a clean
portable scheduler-abstraction primitive. *Why not:* it abstracts *submission*, not *workflow DAGs
or data handoff* — adopting it would still leave CrystalMath owning the orchestration layer it is
trying to delete. Choosing jobflow + the ADR-012 backend gets PSI/J-grade abstraction transitively
without maintaining it.

**D. FireWorks as the engine.** FireWorks (Jain et al. 2015) is proven at 50M+ CPU-hours with a
LaunchPad/`fworker` model. *Why not:* it requires a MongoDB LaunchPad reachable from compute nodes,
a poor fit for firewalled HPC and the outbound-SSH model ADR-012 adopts; jobflow is the lighter,
more modern successor in the same Materials Project lineage and is what atomate2 now targets.

**E. Parsl/Dask as the workflow layer.** Both are mature generic parallel-task engines and are
reachable *via quacc*. *Why not as the top-level model:* their worker-callback connectivity model
suits in-allocation fan-out, not a TUI submitting across SSH (see ADR-012); and neither carries the
materials-science recipe library atomate2 provides. Reserve them as optional *in-allocation*
executors under the ADR-012 backend, not as the orchestration model.

## Consequences

### Positive


- **One orchestration model.** Five runner hierarchies → one jobflow `Flow` + one
  `ExecutionBackend` seam. The job-state-enum / result-type fragmentation (six coexisting status
  types) collapses onto jobflow's job model and the ADR-010 `TaskDocument`.
- **The required capability arrives for free.** Multi-step chaining, wait-for-completion, and typed
  inter-step handoff (`crystalmath-0gs`) are jobflow primitives (`Flow`, `OutputReference`), not
  code CrystalMath must finish writing and test.
- **~2.5k LOC deleted** (`high_level/runners.py`) plus the `quacc/{parsl,mock,covalent}_runner.py`
  and the redundant `protocols.WorkflowRunner` / `_vendor` / `JobRunner` contracts; the
  stub-simulation scaffolding goes with it, removing the `simulated: True` leak surface entirely.
- **Recipes, not reinvention.** VASP/relax/static/EOS/phonon ride atomate2/quacc upstream; only
  CRYSTAL23 and YAMBO need ~per-code recipe adapters over the ADR-008 deck seam.
- **Composes with the data model.** jobflow `Flow`s write emmet-style `TaskDocument`s into the
  maggma `JobStore` (ADR-010) natively; lineage edges (parent-job uuids) are first-class.

### Negative / Tradeoffs


- **Hard dependency on jobflow + the ADR-012 backend** for *all* execution; the
  availability-detected "degrade to no-op" behavior is gone by design (this is the point).
- **CRYSTAL23/YAMBO recipes are CrystalMath's to maintain**, since atomate2 doesn't cover them;
  the gap (linear YAMBO GW/BSE still unimplemented) does not close automatically.
- **Science-type taxonomy is reframed** from runner classes to Flow factories — a real
  reorganization of the `high_level/` surface, and `high_level/builder.py`/`clusters.py` must be
  re-pointed at Flow factories or deleted alongside `runners.py`.

### Migration Impact


1. Stand up Flow factories (`make_{relax,scf,bands,dos,eos,phonon,gw,bse}_flow`) that emit jobflow
   `Flow`s; for VASP/EOS/phonon delegate to atomate2 `Maker`s, for CRYSTAL23/YAMBO wrap the ADR-008
   deck seam in `@job` recipes.
2. Re-point `api.py`'s recipe/workflow methods at the Flow factories; submission goes to the
   ADR-012 `ExecutionBackend`.
3. Delete `high_level/runners.py`, `protocols.WorkflowRunner`, `_vendor/runners/`,
   `quacc/runner.py` + `quacc/{parsl,mock,covalent}_runner.py`, and `CodeHandoff`; replace the
   handoff with `OutputReference` + a restart-file-validation `@job`.
4. Preserve the `allow_stub_execution` gate as a Flow-level dry-run; delete all `simulated: True`
   paths.
5. Keep tests green: the optional-deps matrix shrinks to "jobflow (required) + AiiDA (opt-in)."

## Amendment (2026-06-03): SOTA alignment

This ADR's original framing — a **closed, static enumeration** of `make_*_flow` factories
(§1, line 68) as the workflow model, with jobflow `Response` treated as error-recovery-only
(per [ADR-018](adr-018-error-recovery-custodian-handlers.md)) and Alternative B rejecting both
dynamic orchestration and high-throughput screening — is too narrow for the adaptive
ML/agentic campaigns the new ADR-021…024 set targets. The amendment below **demotes jobflow
from "the campaign brain" to "an executable sub-DAG IR"** beneath a planner, *without changing
the locked decision* that jobflow `Flow` is the one DAG model and quacc/atomate2 the one
recipe layer. The Flow factories survive unchanged as the typed building blocks; what changes
is who composes them and what `Response` is for.

**1. Flow factories are building blocks composed by the ADR-023 planner — not the campaign
brain.** A static DAG cannot be the brain of an adaptive campaign. The named factories
(`make_{relax,scf,bands,dos,eos,phonon,gw,bse}_flow`, §1/§Migration line 181) remain the
**typed, validated units** an upper layer assembles; they are never bypassed. The
[ADR-023](adr-023-agentic-control-plane-mcp-ai-provenance.md) planner/campaign controller sits *above* this
layer and **emits jobflow `Flow`s by composing these factories**, exposing them to LLM agents
through a guarded MCP tool-server over the [ADR-014](adr-014-ipc-boundary-stdio-jsonrpc-delete-pyo3.md)
stdio JSON-RPC transport. Agent output is always a **proposed** typed `Flow`, statically
validated by [ADR-024](adr-024-static-typed-workflow-dag-validation.md) (and the wire contract of
[ADR-016](adr-016-wire-contract-codegen-no-drift.md)) and gated by TUI elicitation approval
before submission — reusing the explicit-gate posture this ADR already establishes
(`allow_stub_execution`, §5) so no agent-proposed Flow is ever executed unvalidated. This is
the separation of planner from executable workflow that SparksMatter and MASTER demonstrate
(the latter reporting up to ~90% fewer simulations), and that MCP-driven systems such as
Catalyst-Agent and the Aurora work of Pham et al. already run in closed loops.

**2. `Response(detour/replace)` is promoted to a first-class dynamic-branching primitive.**
The decision text scopes dynamic DAG construction to error recovery only. This amendment
makes jobflow's existing `Response(detour=…)` / `Response(replace=…)` the **endorsed primitive
for ML-in-the-loop and agent-proposed sub-DAGs**, not just custodian-style recovery: a job may
return a `Response` that materializes a new sub-Flow at run time (e.g. an uncertainty-gated
escalation from an MLIP surrogate to a DFT confirmation, or an active-learning retrain step).
Because such sub-DAGs are materialized at run time, ADR-024's static checker must be callable
**both ahead-of-time and on dynamically-spawned sub-DAGs** when they are materialized; the
detour points are the explicit, typed seams the checker is allowed to leave open.

**3. MLIP screening / pre-relax / active-learning Flow patterns join the workflow set
(ADR-021).** The named workflow enumeration (§1, line 68) is extended with MLIP-centric
patterns realized as Flow factories over the [ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md)
`MlipCalculatorStage` (a peer of the DFT `CalculatorStage`, emitting zero files and keyed by a
content-addressed model checkpoint per [ADR-022](adr-022-content-addressed-execution-cache-replay.md)):

- **MLIP pre-relax → DFT** — a foundation-model relaxation feeds a DFT refinement (precedent:
  atomate2 runs MLIPs through a single `AseMaker`).
- **Surrogate screening** — high-throughput MLIP energy/force/stress evaluation as a DFT
  pre-filter (Matbench Discovery reports F1 ≈ 0.57–0.83 for uMLIP filters), realized as a
  fan-out (see §4 below).
- **Uncertainty-gated escalation** — a `Response(detour)` from a surrogate to DFT when an
  ensemble/GP variance (e.g. FLARE) exceeds a method-tagged threshold.
- **Active learning** — a propose → compute → retrain loop (e.g. MatterSim-style) expressed as
  `Response(detour/replace)` cycles.
- **Δ-ML / fine-tune** — a correction or fine-tuning step over a parent checkpoint, with the
  fine-tune parent recorded in provenance.

These map onto the typed `Flow`/`Response` machinery above; the dynamic patterns (escalation,
active learning, Δ-ML fine-tune) are exactly the open detour points of §2.

**4. High-throughput MLIP screening gets a first-class in-allocation home.** Alternative B's
original "Parsl/Dask only as in-allocation executors, never the orchestration model" is
**narrowed rather than reversed**: high-throughput MLIP screening is now an explicitly
endorsed first-class workload that fans out over an **in-allocation Parsl/Dask executor under
the ADR-021 inference backend** (the narrow non-`sbatch` in-process/GPU-inference exception
ADR-021 carves into [ADR-012](adr-012-hpc-execution-jobflow-remote-aiida-optional.md)'s
"exactly two backends, all compute via sbatch" rule). The fan-out remains **beneath** the
jobflow DAG and the ADR-023 planner — it is an executor choice for one screening node, never
the top-level orchestration model — so this does not reopen Alternative E's rejection of
Parsl/Dask *as the workflow layer*.

**Net effect on the stack.** The coherent layering becomes: agentic planner
([ADR-023](adr-023-agentic-control-plane-mcp-ai-provenance.md)) → static-validated jobflow DAG
([ADR-024](adr-024-static-typed-workflow-dag-validation.md) over this ADR) → content-addressed,
cache-gated `CalculatorStage`s ([ADR-022](adr-022-content-addressed-execution-cache-replay.md) over
[ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md)) → typed `TaskDocument`s with ML+AI+env
provenance ([ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md)). jobflow remains
the one DAG model; it is now explicitly an **executable sub-DAG IR** under a planner, with its
already-existing dynamic `Response` capability acknowledged as the agent/ML branching primitive.

## References

- Rosen, A. S. et al. (2024). "Jobflow: Computational Workflows Made Simple." *Journal of Open
  Source Software* 9(93), 5995. DOI:10.21105/joss.05995.
- Ganose, A. M. et al. (2025). "Atomate2: modular workflows for materials science." *Digital
  Discovery*. DOI:10.1039/d5dd00019j.
- Rosen, A. S. et al. "quacc – The Quantum Accelerator." Zenodo. DOI:10.5281/zenodo.10399417.
  https://quantum-accelerators.github.io/quacc/
- Larsen, A. H. et al. (2017). "The atomic simulation environment — a Python library for working
  with atoms." *J. Phys.: Condens. Matter* 29, 273002. DOI:10.1088/1361-648X/aa680e.
- Ong, S. P. et al. (2013). "Python Materials Genomics (pymatgen)." *Computational Materials
  Science* 68, 314. DOI:10.1016/j.commatsci.2012.10.028.
- Pizzi, G. et al. (2016). "AiiDA: Automated Interactive Infrastructure and Database for
  Computational Science." *Comput. Mater. Sci.* 111, 218. arXiv:1504.01163.
  DOI:10.1016/j.commatsci.2015.09.013.
- Huber, S. P. et al. (2020). "AiiDA 1.0, a scalable computational infrastructure for automated
  reproducible workflows and data provenance." *Scientific Data* 7, 300. arXiv:2003.12476.
  DOI:10.1038/s41597-020-00638-4.
- Huber, S. P. et al. (2021). "Common workflows for computing material properties using different
  quantum engines." *npj Computational Materials* 7, 136. arXiv:2105.05063.
- Uhrin, M. et al. (2021). "Workflows in AiiDA: Engineering a high-throughput, event-based engine
  for robust and modular computational workflows." *Comput. Mater. Sci.* 187, 110086.
  arXiv:2007.10312.
- Jain, A. et al. (2015). "FireWorks: a dynamic workflow system designed for high-throughput
  applications." *Concurrency and Computation: Practice and Experience* 27(17), 5037.
  DOI:10.1002/cpe.3505.
- Hategan-Marandiuc, M. et al. (2023). "PSI/J: A Portable Interface for Submitting, Monitoring, and
  Managing Jobs." *IEEE 19th Int. Conf. on e-Science.* arXiv:2307.07895.
- Babuji, Y. et al. (2019). "Parsl: Pervasive Parallel Programming in Python." *HPDC '19.*
  arXiv:1905.02158. DOI:10.1145/3307681.3325400.
- jobflow documentation (Job, Flow, OutputReference, JobStore):
  https://materialsproject.github.io/jobflow/

*Added with the Amendment (2026-06-03):*

- Batatia, I. et al. (2024). "A foundation model for atomistic materials chemistry (MACE-MP-0)."
  *J. Chem. Phys.* arXiv:2401.00096. — Canonical foundation-MLIP; MLIP pre-relax and Δ-ML patterns.
- Deng, B. et al. (2023). "CHGNet as a pretrained universal neural network potential for
  charge-informed atomistic modelling." *Nature Machine Intelligence*. DOI:10.1038/s42256-023-00716-3.
- Riebesell, J. et al. (2025). "Matbench Discovery." *Nature Machine Intelligence.* — uMLIPs as
  DFT pre-filters (F1 ≈ 0.57–0.83), motivating the surrogate-screening Flow pattern.
- Yang, H. et al. (2024). "MatterSim." arXiv:2405.04967. — Active-learning surrogate precedent.
- Vandermause, J. et al. (2020). "On-the-fly active learning of interpretable Bayesian force
  fields (FLARE)." *npj Comput. Mater.* 6, 20. — Uncertainty (GP variance) gating.
- MatterGen (2025). *Nature.* arXiv:2312.03687. — Generative `CandidateSource` feeding MLIP
  screening → DFT validation (ADR-023 planner).
- Catalyst-Agent (2026). arXiv:2603.01311; Pham, et al. (2026). arXiv:2604.07681. — MCP-driven
  agents driving materials workflows in closed loops (ADR-023 control plane).
- SparksMatter (2025). arXiv:2508.02956; MASTER (2025). arXiv:2512.13930. — Planner separated
  from executable workflow; MASTER reports up to ~90% fewer simulations.

## Related Issues

- crystalmath-0gs (P1): multi-step dependency chaining + wait-for-completion + inter-step data
  handoff — realized natively by this ADR (jobflow `Flow` + `OutputReference`).
- crystalmath-cjc (P2): HighThroughput/WorkflowBuilder execution unimplemented — resolved by
  Flow factories or deleted with `high_level/`.
- crystalmath-4m6 (P1): executor wiring — folded into the ADR-012 `ExecutionBackend`.
