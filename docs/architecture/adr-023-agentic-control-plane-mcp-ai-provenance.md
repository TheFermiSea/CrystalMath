# ADR-023: Agentic/LLM Control Plane — a Guarded MCP Tool-Server Above jobflow, a Generative CandidateSource, and First-Class AI Provenance

**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** none — *amends* [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md)'s static-Flow-factory framing (the campaign brain moves above the factories; the factories stay) and [ADR-019](adr-019-delete-phase3-protocols-aspiration-layer.md)'s "decks + jobflow are the single answer to *how do I run a workflow*" claim (an agentic composition entry point is admitted above that answer)
**Depends on:** [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) (the `make_*_flow` factories the agent composes and the jobflow `Response` detour/replace primitive it emits), [ADR-014](adr-014-ipc-boundary-stdio-jsonrpc-delete-pyo3.md) (the stdio JSON-RPC transport the MCP tool-server rides), [ADR-016](adr-016-wire-contract-codegen-no-drift.md) (wire-contract validation of the proposed-Flow schemas), [ADR-018](adr-018-error-recovery-custodian-handlers.md) (the custodian handler catalogue the LLM-diagnosis step sits above), [ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md) (the `CalculatorStage` — DFT and MLIP — the generative loop screens and validates against), [ADR-024](adr-024-static-typed-workflow-dag-validation.md) (the offline DAG type-checker that gates every proposed Flow before submission), [ADR-025](adr-025-campaign-acquisition-strategy.md) (the pluggable `AcquisitionStrategy`+`CampaignStrategy` the `CampaignController` is *configured with* — campaign policy lives here, not in this ADR), [ADR-026](adr-026-trustworthy-mlip-evaluation-applicability-domain.md) (the measured-trust gate whose `UncertaintyEstimate`/OOD escalation threshold the MLIP-screen→DFT-validate step obeys), [ADR-027](adr-027-model-dataset-registry-lineage.md) (the unified `ModelIdentifier` resolving the agent/generative model identity in `AIProvenance` and the fetched/pinned MatterGen model)
**Writes into:** [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md) (AI provenance folded into the `ProvenanceDoc` schema), hashed by [ADR-022](adr-022-content-addressed-execution-cache-replay.md) (AI provenance becomes part of the content-address closure)

## Context

CrystalMath's workflow layer is, by [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md)'s decision, a fixed
enumeration of jobflow `Flow` factories — `make_{relax,scf,bands,dos,gw,bse,phonon,eos,convergence}_flow`
(`adr-011…:68,181`) — and ADR-011's Alternative B (`adr-011…:128-135`) explicitly rejected dynamic
orchestration as a top-level model, admitting jobflow's `Response` (detour/replace) only for error
recovery via [ADR-018](adr-018-error-recovery-custodian-handlers.md). That is the right *executable* layer. It is the
wrong *campaign* layer.

**A static DAG cannot be the campaign brain.** The scientific question a materials manager exists to
answer — "find me a stable, low-band-gap chalcogenide," "close the loop until the surrogate agrees with
DFT to tolerance," "diagnose why this VASP run died with a signature no handler recognizes" — is not a
fixed DAG. It is a *search* whose shape is decided as results arrive: propose candidates → screen them
cheaply with an MLIP ([ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md)'s `MlipCalculatorStage`) →
validate the survivors with DFT → retrain the surrogate on the validated set → propose again. That loop
is exactly what jobflow's `Response(detour=…)` / `Response(replace=…)` is *for* (Rosen et al. 2024) — a
running job materializing new sub-DAGs from runtime evidence — but ADR-011 reserved it for recovery and
gave the loop no first-class home (its Alternative B even denied high-throughput screening one). The
campaign controller that decides *what to compose next* is missing.

**The separation this layer requires — a planner that proposes, a deterministic engine that executes — is
the established pattern, not a novelty.** The Model Context Protocol (modelcontextprotocol.io) standardizes a
typed tool/elicitation vocabulary for exactly this kind of agent↔engine seam, and CrystalMath already speaks
its transport (ADR-014's JSON-RPC-over-stdio was chosen *because* it is the LSP/MCP pattern). On the
generative side, MatterGen (Zeni et al., *Nature* 2025; arXiv:2312.03687) is the reference diffusion model
that *proposes* novel structures conditioned on target properties — but its outputs are hypotheses, not
results: they require DFT validation, which is precisely the screen→validate loop above. And on provenance,
the discipline an autonomous agent demands is plain: once an agent touches an artifact, *which* model,
prompt, tool-call transcript, agent identity, and human approval produced or modified it must travel *with*
the artifact, or the result is unauditable.

> **Citation note (2026-06-03):** an earlier draft of this paragraph cited several agentic-materials papers
> (Catalyst-Agent, Pham/Aurora, SparksMatter, MASTER, Kosmos) by arXiv ID. Those identifiers could not be
> verified against the known-canonical set and have been removed rather than risk a fabricated or mislabeled
> reference; the architectural argument stands on the planner/executor separation and the verified anchors
> (MatterGen, jobflow, Matbench Discovery, the MCP spec) alone. See the Amendment below.

**CrystalMath already has an un-guarded version of exactly the wrong shape.** `python/crystalmath/ai/service.py`
is today a free-text Anthropic chat client (`ai/service.py:31` `AIService`, `:11` `from anthropic import Anthropic`)
that "diagnoses failed calculations" and "suggests input parameters" as raw natural-language strings, with
no typed verb surface, no approval gate, no provenance record, and no validation of what it emits. That is
the prompt-injection / silent-wrong-science surface the rest of this redesign exists to eliminate, wearing
an LLM hat: a model that can emit arbitrary deck text into a submission path is the agentic analogue of the
`simulated: True` leak ADR-011 deleted and the stale-WAVECAR handoff ADR-013 closed.

**The three execution seams the redesign already built are precisely the seams an agentic layer needs, and
all three already speak the right vocabulary.** [ADR-014](adr-014-ipc-boundary-stdio-jsonrpc-delete-pyo3.md)
adopted JSON-RPC 2.0 over spawned-child stdio explicitly because it is *the LSP/MCP pattern* — an MCP
tool-server is the same transport with a tool/elicitation vocabulary layered on. [ADR-016](adr-016-wire-contract-codegen-no-drift.md)
made pydantic schemas the single source of truth with "drift is a build failure, not a runtime error" — so
a *proposed Flow* expressed as a typed pydantic object is wire-checkable for free. [ADR-024](adr-024-static-typed-workflow-dag-validation.md)
type-checks the whole multi-code DAG offline before submission — so a *proposed Flow* can be statically
proven valid before a single job is queued. The redesign's own fail-loud, explicit-gate posture — the
`allow_stub_execution` gate (`adr-011…:112`) and the `allow_restart_skew` override (`adr-013…:227`) — is the
template for how agent output must be gated: opt-in, logged, never silent.

This ADR inserts the missing **control layer** above jobflow: a planner/campaign controller that *composes*
ADR-011's typed factories into proposed Flows and emits jobflow `Response` detours for adaptive loops,
exposed to LLM agents through a *guarded* MCP tool-server with typed verbs and TUI-gated human approval,
with a pluggable generative `CandidateSource` feeding the screen→validate loop, an LLM-diagnosis step above
ADR-018's catalogue, and AI provenance recorded on every artifact it touches.

## Decision

**Insert a planner/campaign-controller layer ABOVE the ADR-011 Flow factories. The agent COMPOSES the typed
`make_*_flow` building blocks and emits jobflow `Flow`s (using `Response` detour/replace for adaptive loops);
it never builds raw flows and never runs compute directly. Expose the engine to LLM agents through a guarded
MCP tool-server over the ADR-014 stdio JSON-RPC transport, with typed verbs and TUI-gated elicitation
approval. Agent output is always a PROPOSED typed Flow, validated by ADR-016 (wire) and ADR-024 (DAG) BEFORE
execution — never executed unvalidated. Add a pluggable generative `CandidateSource`, an LLM-diagnosis step
above ADR-018's custodian catalogue, and first-class AI provenance on every artifact.**

### 1. A campaign controller composes ADR-011 factories; it never builds raw flows

> **Refined by Amendment §2 (2026-06-03).** The `CampaignController` is **configured with** an ADR-025
> `AcquisitionStrategy` + `CampaignStrategy` and holds **no** embedded acquisition/convergence/stopping/
> escalation policy; the §1 MLIP-screen→DFT-validate step obeys **ADR-026's** trust/OOD gate (an out-of-domain
> candidate must hit DFT, never skip). This ADR keeps the *mechanism*; the *policy* lives in ADR-025 and the
> *trust decision* in ADR-026.

The new layer is `crystalmath.control` (a `CampaignController`). Its sole output is a **proposed jobflow
`Flow`** assembled *only* from ADR-011's typed `make_*_flow` factories and from ADR-021 `CalculatorStage`s —
it has no API to emit a raw `Job` or hand-written deck. Adaptive loops are expressed as the controller
returning, from inside a running coordinator job, a jobflow `Response`:

- `Response(detour=make_static_flow(...))` to insert DFT validation of MLIP-screened survivors;
- `Response(replace=...)` to re-materialize the next screen→validate→retrain round.

The canonical loop — **propose → MLIP-screen → DFT-validate → retrain** — is a coordinator `@job` that
(a) draws candidates from a `CandidateSource` (§4), (b) detours each through an ADR-021 `MlipCalculatorStage`,
(c) detours the survivors through a DFT `CalculatorStage` (`make_static_flow`/`make_relax_flow`), and
(d) optionally detours a fine-tune/Δ-ML stage and loops. This **amends** ADR-011's framing that the factories
are the top of the stack: they remain the typed building blocks, now *composed* by the controller rather than
called directly by `api.py`. It does **not** reopen ADR-011 Alternative B's rejection of quacc/Parsl-as-orchestrator:
execution still goes to the ADR-012 `ExecutionBackend`; the controller only decides *which Flows to build*.

### 2. A guarded MCP tool-server over the ADR-014 transport, with typed verbs only

> **Superseded in part by Amendment §1 (2026-06-03).** The core is now a Python **Agent → proposed typed
> Flow → TUI approval → ADR-024 validation → execution** seam; the MCP tool-server below is **one optional
> adapter** over that seam, not the agent's only interface. The six-verb table remains the adapter's surface
> and the typed-schema-only / no-free-text-deck / no-raw-shell guarantees still hold for the seam itself.

The agent never sees Python objects or free text on the submission path. It sees an **MCP tool-server**
(`crystalmath.control.mcp`) riding the [ADR-014](adr-014-ipc-boundary-stdio-jsonrpc-delete-pyo3.md) stdio
JSON-RPC transport, exposing a **closed set of typed verbs**:

| Verb | Input schema | Output | Mutates? |
|---|---|---|---|
| `propose_structure` | target properties / parent structure | candidate `Structure` + provenance | no |
| `generate_deck` | `Structure` + code + typed params | a `CalculatorStage` spec (ADR-021), never raw deck text | no |
| `validate_workflow` | proposed `Flow` | ADR-024 static report + ADR-016 wire check | no |
| `submit_campaign` | validated `Flow` | campaign id | **YES — gated** |
| `query_status` | campaign/job id | `JobState` (ADR-009) | no |
| `fetch_result` | job id | `TaskDocument` (ADR-009) | no |

Every input and output is a pydantic model exported through the ADR-016 wire contract — **there is no
raw-shell, no free-text deck, and no `eval`-style verb anywhere on the surface.** `generate_deck` returns a
*typed `CalculatorStage` spec*, not deck bytes, so the actual deck is still produced by ADR-008's
`CodeDeckGenerator` from validated parameters; the agent cannot inject deck text. This is the structural
defense against prompt-poisoning / injection: the attack surface is the typed schema, and the typed schema
is exactly what ADR-016 already drift-checks.

### 3. `submit_campaign` is gated behind MCP elicitation, rendered in the Ratatui TUI

The only mutating verb, `submit_campaign`, **cannot fire without human approval.** It triggers an **MCP
elicitation** (form-mode) request that the Rust/Ratatui TUI ([ADR-006]) renders as an approval panel showing
the proposed Flow's static-validation report (ADR-024), the deck diffs (ADR-008), the content-address
closure that *will* be hashed (ADR-022), and the AI provenance (§5) of how the plan was produced. The human
approves, edits, or rejects in the form. This is the same explicit-gate posture as `allow_stub_execution`
(`adr-011…:112`) and `allow_restart_skew` (`adr-013…:227`): **opt-in, logged, never silent.** Approval is
*tiered* — a read-only verb (`query_status`, `fetch_result`) needs none; `submit_campaign` always needs at
least one human approval; a high-cost campaign (large core-hour estimate, or a `CandidateSource`-generated
novel structure) escalates to a stricter tier. No agent path bypasses the gate; an agent that tries to
submit an un-elicited campaign gets a hard `ElicitationRequiredError`, the analogue of ADR-013's
`RestartValidationError`.

### 4. A pluggable generative `CandidateSource` feeds the screen→validate loop

Structure proposal is a **protocol**, not a hard dependency on any one model:

```python
class CandidateSource(Protocol):
    def propose(self, target: PropertyTarget, n: int) -> list[CandidateStructure]: ...
```

The reference implementation wraps **MatterGen** (Zeni et al., *Nature* 2025; arXiv:2312.03687) — a diffusion
model that proposes structures conditioned on target properties — behind this protocol. **Candidates are
hypotheses, not results.** A `CandidateStructure` carries its generative provenance (§5) and is *required* to
pass through the MLIP-screen → DFT-validate loop of §1 before it can become a published `TaskDocument`; a
candidate may never short-circuit straight to the store. Other sources (enumeration, substitution, an
elemental-substitution heuristic) implement the same protocol, so the generator stays swappable as the
fast-moving generative-model landscape changes.

### 5. An LLM-diagnosis step ABOVE the ADR-018 custodian catalogue — proposing, never auto-applying

[ADR-018](adr-018-error-recovery-custodian-handlers.md) deletes substring-grep diagnosis and adopts custodian's
signature-matched `ErrorHandler` catalogue, but it has **no handler for novel/unknown failures**
(`adr-018…:76-90`). This ADR slots an **LLM-diagnosis step above that catalogue**: when *no* `ErrorHandler`
matches a failure, the controller may invoke an agent to *propose a candidate patch* (a typed parameter
delta or a typed corrective Flow). The patch is **gated exactly like `submit_campaign`** (§3) and **never
auto-applied** — it is rendered for human approval, validated by ADR-024, and only then re-submitted. This
keeps the fail-loud contract: an unknown failure surfaces a *proposed* fix, it does not silently mutate and
re-run.

### 6. AI provenance is first-class, folded into ADR-009 and hashed by ADR-022

> **Superseded by Amendment §3–§4 (2026-06-03).** The record below is upgraded to **audit-grade**: it adds a
> `transcript_cas_key` (the full redacted prompt/tool-call transcript stored in the ADR-022 CAS, not just a
> hash) and a `redaction_policy_id`; `model_id`/`model_version` strings are replaced by an ADR-027
> `ModelIdentifier`; and `acquisition_function: str` becomes a typed ADR-025 strategy reference. See
> Amendment §3–§4 for the corrected `AIProvenance`.

Every artifact an agent produces or modifies carries an `AIProvenance` record, added to ADR-009's
`ProvenanceDoc`:

```python
class AIProvenance(BaseModel):
    model_id: str                 # pinned, e.g. "claude-opus-4-8" or "mattergen@<rev>"
    model_version: str            # exact, pinned — no floating "latest"
    prompt_hash: str              # hash of the exact prompt/template, not the free text
    tool_call: str                # which MCP verb (§2)
    agent_identity: str           # which agent/role issued it
    acquisition_function: str | None  # for active-learning candidate selection
    human_approval: ApprovalRecord    # who approved at which tier, when (§3)
```

This record is written into the ADR-009 schema and **folded into the ADR-022 content-address closure**, so a
checkpoint/model bump or a prompt change *invalidates the cache* of dependent artifacts (per ADR-022's
"checkpoint bump invalidates dependent surrogates"). Consistent with ADR-022's treatment of agentic nodes:
**LLM/agent nodes are un-cached** (closed-model versions drift; bitwise agent replay is impossible) **but
their deterministic child stages are cached** — the agent decision is recorded as provenance, the DFT/MLIP
work it triggers is content-addressed and memoized normally.

### 7. Security is non-negotiable

- **Typed schemas only** (§2) — no raw shell, no free-text deck, no injection surface; the existing
  free-text `ai/service.py:31 AIService` is **deleted/reframed** as the guarded MCP server, not a parallel
  un-gated path.
- **Pinned model and tool versions** (§6) — `model_id@version` is recorded and is part of the hash; floating
  "latest" is rejected.
- **Signing** — proposed Flows and approval records are signed so the audit trail (which agent proposed,
  which human approved) is tamper-evident.
- **Tiered approval** (§3) — read-only verbs ungated, `submit_campaign` always gated, high-cost/novel-structure
  campaigns escalated.

## Alternatives Considered

**A. Keep `ai/service.py` as a free-text LLM chat that can suggest/apply deck changes (status quo).** The
current `AIService` (`ai/service.py:31`) emits natural-language parameter suggestions and diagnoses. *Why not:*
it is the un-typed, un-gated, un-provenanced surface this ADR exists to kill — a model that can put free text
on a submission path is a prompt-injection and silent-wrong-science vector, the agentic analogue of the
`simulated: True` leak ADR-011 deleted. With zero users there is no reason to preserve it; it is reframed into
the guarded MCP server.

**B. Let the agent emit raw jobflow `Flow`s / `Job`s directly (skip the composition constraint).** Maximal
flexibility — the agent writes any DAG. *Why not:* it discards every safety property the redesign built. A raw
`Job` bypasses ADR-008's `CodeDeckGenerator` (the agent could emit arbitrary deck bytes), bypasses ADR-013's
typed handoff edges, and is not guaranteed to be ADR-024-checkable. Constraining the agent to *compose* the
typed `make_*_flow` factories (§1) is what makes its output statically validatable and keeps ADR-011's typed
building blocks load-bearing. The planner-separated-from-executable-workflow architecture — an agent that
proposes a typed, inspectable plan that a deterministic engine executes — is precisely this constraint.

**C. A custom JSON/REST agent API instead of MCP.** We could expose the verbs over a bespoke HTTP API. *Why
not:* MCP is a converged, documented standard for typed agent↔engine tool surfaces
(modelcontextprotocol.io), and ADR-014 *already* chose JSON-RPC over stdio *because it is the LSP/MCP
pattern* (`adr-014…` title). Riding the existing transport with the MCP tool/elicitation vocabulary is
strictly less new surface than a parallel REST stack, and gives us elicitation-based approval (§3) for free
rather than reinventing an approval protocol. (Per Amendment 1, MCP is one *optional adapter* over the
Agent→proposed-Flow→approval seam, not the only entry point.)

**D. Auto-apply LLM-proposed patches when no custodian handler matches (closed-loop self-healing).**
Fully autonomous recovery. *Why not:* it reintroduces exactly the non-determinism and silent-mutation the
fail-loud posture forbids (`adr-011…:112`, `adr-013…:139-142`). An LLM patch is a *hypothesis* about a novel
failure; auto-applying it can burn compute on a wrong fix or, worse, publish a wrong result. §5 keeps the
diagnosis but gates the patch behind the same human approval as `submit_campaign`.

**E. Hard-wire MatterGen as *the* generator rather than a `CandidateSource` protocol.** Simpler — one import,
no abstraction. *Why not:* generative materials models are the fastest-moving part of the stack; pinning the
architecture to one model would date the ADR within a release. The protocol (§4) keeps MatterGen as the
reference implementation while leaving enumeration/substitution/future-diffusion sources swappable — the same
"adopt a contract, keep implementations pluggable" pattern ADR-012 used for `ExecutionBackend` and ADR-013
used for `RestartValidation`.

**F. No control layer — leave campaigns as manual sequences of ADR-011 factory calls.** *Why not:* it leaves
the active-learning / generative-screening loop (the highest-value, highest-compute-savings use case — an
MLIP pre-filter lets the campaign spend scarce DFT budget only on the survivors, the regime where active
learning earns its keep; Matbench Discovery, arXiv:2308.14920) with no home, exactly the gap ADR-011
Alternative B left open. The screen→validate→retrain loop is genuinely *dynamic* (its shape depends on
results) and cannot be a static factory composition; it needs a controller emitting `Response` detours.
Per Amendment 1, that controller is *configured with* an ADR-025 strategy object rather than holding the
acquisition/stopping policy itself.

## Consequences

### Positive
- **The campaign brain gets a home above the executable DAG.** The propose→screen→validate→retrain loop is a
  first-class `CampaignController` emitting jobflow `Response` detours, closing the gap ADR-011 Alternative B
  left and turning jobflow's dynamic-DAG capability (used only for recovery in ADR-018) into the intended
  adaptive-loop primitive.
- **Agent output is safe by construction.** Every proposed Flow is composed from typed factories (§1), wire-checked
  by ADR-016, statically DAG-checked by ADR-024, and human-approved via MCP elicitation (§3) before a single
  job queues — the agent can never execute unvalidated, and never emits raw deck text or shell.
- **Standardized, not bespoke.** Riding ADR-014's transport with the MCP tool/elicitation vocabulary
  (modelcontextprotocol.io) reuses a documented, converged standard and adds *less* new surface than a
  parallel API — and, per Amendment 1, MCP is an *optional adapter* over the same Agent→proposed-Flow→approval
  seam the TUI uses directly.
- **Full auditability.** AI provenance (model/prompt/tool-call/agent/acquisition/approval) on every artifact
  (§6), folded into ADR-009 and hashed by ADR-022, means "which model and which human produced this result?"
  is always answerable — and a model/prompt change correctly invalidates downstream caches.
- **Novel-failure diagnosis without auto-mutation.** ADR-018's catalogue gains a gated LLM fallback for the
  failures no handler matches (§5), without reopening the silent-self-heal anti-pattern.
- **Generative screening pays off the cache.** Active-learning loops re-evaluate near-identical structures;
  with ADR-022 caching the deterministic child stages (and only the agent node un-cached), the loop reuses
  prior DFT/MLIP work — the regime where MLIP-pre-filtered active learning realizes its compute savings.

### Negative / Tradeoffs
- **Bitwise agent replay is impossible.** Closed-model versions drift; the same prompt may yield a different
  plan next month. Mitigation: we record `model_id@version` + `prompt_hash` (§6) and un-cache agent nodes
  (ADR-022) so the *decision* is auditable even though it is not bitwise-reproducible; the deterministic
  compute it triggers *is* reproducible.
- **A new attack surface (LLM-in-the-loop) must be defended continuously.** Prompt poisoning and injection are
  real. Mitigation: typed-schemas-only (§2,§7), signing, pinned versions, tiered human approval (§3) — the
  surface is the typed schema, which ADR-016 already drift-checks; there is no free-text or shell path.
- **Human-in-the-loop adds latency to autonomous campaigns.** `submit_campaign` always blocks on elicitation.
  This is *intended* — it is the `allow_stub_execution`-style gate — but it bounds how "hands-off" a campaign
  can be. Tiering (§3) keeps read-only verbs and low-cost steps fast.
- **New optional dependency surface.** MatterGen + an MCP server library + the agent runtime are heavier,
  GPU-leaning deps. Mitigation: they live behind an optional extra and the `CandidateSource`/MCP-server seams,
  so the laptop-first TUI user pays nothing unless they opt into the agentic extra.
- **Coordinator-job complexity.** Adaptive `Response`-detour loops are harder to reason about than static
  Flows and must be re-validated when materialized (ADR-024 explicitly re-checks dynamically-spawned sub-DAGs).

### Migration impact
1. Add `crystalmath.control` (`CampaignController`) that composes ADR-011 `make_*_flow` factories and emits
   `Response` detours; implement the propose→MLIP-screen→DFT-validate→retrain coordinator over ADR-021
   `CalculatorStage`s. **Configure** the controller with an ADR-025 `AcquisitionStrategy` + `CampaignStrategy`
   (no embedded policy) and route the screen→validate escalation through ADR-026's trust/OOD gate (Amendment
   §2).
1a. Add `crystalmath.control.agent` — the in-process **Agent → proposed typed Flow → TUI approval →
   ADR-024 validation → execution** seam (Amendment §1). This is the core; it is testable with no MCP server
   present.
2. Add `crystalmath.control.mcp` as an **optional adapter** over the §1a seam (Amendment §1) — the guarded MCP
   tool-server over the ADR-014 transport, exposing the six typed verbs (§2) to external MCP clients; the
   approval gate is the seam's, reused, not a second submission path.
3. **Delete/reframe** `python/crystalmath/ai/service.py`'s free-text `AIService`: its diagnosis capability moves
   behind the gated LLM-diagnosis step (§5); its parameter-suggestion capability moves behind typed
   `generate_deck` (§2). No un-gated free-text path remains.
4. Add the `CandidateSource` protocol with a MatterGen reference implementation behind an optional extra (§4),
   resolving MatterGen as a **fetched/pinned ADR-027 `ModelIdentifier`** (Amendment §4), not an ad-hoc import.
5. Extend ADR-009's `ProvenanceDoc` with the **audit-grade** `AIProvenance` (§6 as corrected by Amendment
   §3–§4: `transcript_cas_key` + `redaction_policy_id`, `ModelIdentifier`, typed `acquisition_strategy` ref)
   and include it — transcript CAS key and all — in the ADR-022 content-address closure; mark agent nodes
   un-cached, child stages cached.
6. Slot the LLM-diagnosis fallback above the ADR-018 custodian catalogue, gated and never auto-applied (§5).

## References

- Zeni, C., Pinsler, R., Zügner, D., et al. (2025). "A generative model for inorganic materials design"
  (MatterGen). *Nature* 639, 624–632. DOI:10.1038/s41586-025-08628-5, arXiv:2312.03687. — Reference diffusion
  `CandidateSource`; property-conditioned structure proposal whose outputs are hypotheses requiring DFT
  validation (§4).
- Rosen, A. S., Ganose, A. M., et al. (2024). "Jobflow: Computational Workflows Made Simple." *Journal of Open
  Source Software* 9(93), 5995. DOI:10.21105/joss.05995. — `Response(detour/replace)` dynamic-DAG primitive the
  `CampaignController` emits for the adaptive loop (§1).
- Model Context Protocol specification. https://modelcontextprotocol.io/specification — The tool-server +
  elicitation vocabulary §2–§3 layer over the ADR-014 transport; the elicitation page is the basis for the
  form-mode human-approval gate (§3).
- Riebesell, J., Goodall, R. E. A., et al. (2024). "Matbench Discovery." arXiv:2308.14920. — uMLIPs as DFT
  pre-filters on OOD discovery splits (F1 leaderboard ~0.57–0.82), the quantitative basis for the MLIP-screen
  step of the loop (§1; see also ADR-021 and the measured-trust gate of ADR-026).

> **Removed references (2026-06-03):** the prior draft cited "Catalyst-Agent" (arXiv:2603.01311), "Pham et al.
> / Aurora" (arXiv:2604.07681), "SparksMatter" (arXiv:2508.02956), "MASTER" (arXiv:2512.13930), and "Kosmos"
> (arXiv:2511.02824). None could be verified against the known-canonical set; several carried future-dated or
> mislabeled identifiers and one ("MASTER, ~90% fewer simulations") an unverifiable quantitative claim. Per the
> project's citation-integrity invariant these are deleted rather than reworded around a possibly-fabricated ID.
> The architectural claims they supported (planner/executor separation; per-artifact AI provenance; MLIP-as-DFT-
> pre-filter compute savings) are retained on the strength of the verified anchors above.
- Depends on/amends: [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md) (AI provenance in
  `ProvenanceDoc`), [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) (the composed factories; amends
  its static-factory framing), [ADR-014](adr-014-ipc-boundary-stdio-jsonrpc-delete-pyo3.md) (the MCP transport),
  [ADR-016](adr-016-wire-contract-codegen-no-drift.md) (wire-check of proposed Flows),
  [ADR-018](adr-018-error-recovery-custodian-handlers.md) (LLM-diagnosis above the catalogue),
  [ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md) (the MLIP/DFT `CalculatorStage`s the loop
  screens and validates against), [ADR-022](adr-022-content-addressed-execution-cache-replay.md) (AI provenance in
  the hash, now including the transcript CAS key; agent nodes un-cached, children cached),
  [ADR-024](adr-024-static-typed-workflow-dag-validation.md) (offline DAG validation gating every proposed
  Flow; its executor-rejects-unsigned-jobs boundary is what makes approval enforceable),
  [ADR-025](adr-025-campaign-acquisition-strategy.md) (the `AcquisitionStrategy`+`CampaignStrategy` the
  controller is configured with — *answers "what next / when to spend DFT budget"*),
  [ADR-026](adr-026-trustworthy-mlip-evaluation-applicability-domain.md) (measured surrogate trust:
  `EvaluationHarness`, calibrated `UncertaintyEstimate`, applicability-domain/OOD gate, escalation thresholds
  — *answers "is the surrogate trustworthy enough to act on"*), [ADR-027](adr-027-model-dataset-registry-lineage.md)
  (`ModelRegistry`/`DatasetRegistry` over the ADR-022 CAS and the single unified `ModelIdentifier` — *answers
  "what exactly is this model/dataset and where did it come from"*).
- CrystalMath internal: `python/crystalmath/ai/service.py:31` (`AIService`, the free-text LLM client reframed
  into the guarded Agent + optional MCP adapter); `python/crystalmath/server/` (the ADR-014 JSON-RPC server the
  MCP adapter rides); `python/crystalmath/control/` (new — `CampaignController` + `control.agent` core +
  `control.mcp` optional adapter).

## Amendment (2026-06-03): consensus-review fixes

This amendment is **surgical**: it preserves the original Decision (a planner/campaign layer above the
ADR-011 factories that emits *proposed, validated* Flows under human approval, with first-class AI
provenance). It re-centers four things the two-reviewer consensus flagged as over-engineered or under-
specified, and wires this ADR to the three new ADRs added this round (025/026/027). The locked decisions of
ADR-011/021/022/024 are **consumed, not re-litigated**.

The single principle behind all four fixes: *pull every implicit scientific-judgment policy out of LLM
prompts and inert provenance strings and make it a typed, testable, pluggable object — then cross-reference
it, do not re-embed it.*

### 1. Re-center: the core is a Python **Agent → proposed typed Flow → TUI approval → ADR-024 validation → execution**. MCP is **one optional adapter** behind that seam, not the center.

The original §2–§3 placed a closed-verb MCP tool-server at the architectural center. For a zero-user system,
standing up a six-verb closed MCP server *as the primary surface* is over-engineering. The corrected shape:

- **The seam is the core, and it is plain Python.** `crystalmath.control.agent` is an `Agent` whose only
  output is a **proposed typed `Flow`** (composed from ADR-011 `make_*_flow` factories and ADR-021
  `CalculatorStage`s, exactly as §1 specifies). That proposed Flow flows through one fixed pipeline:

  ```
  Agent.propose() → ProposedFlow
       → TUI yes/no/edit approval (the §3 elicitation panel, rendered directly by the Ratatui TUI)
       → ADR-024 static DAG validation  (+ ADR-016 wire check)
       → executor (ADR-012), which rejects any unsigned/unapproved job per ADR-024's enforcement boundary
  ```

  This pipeline exists and is testable **with no MCP server present at all** — a local agent, a CLI driver,
  or the TUI itself can drive `Agent.propose()` directly.

- **MCP is demoted to an optional transport adapter over that same seam.** `crystalmath.control.mcp` is
  *one* adapter that lets an *external* MCP client reach `Agent.propose()` and the approval pipeline; it adds
  no policy and no second submission path. The six verbs of the original §2 table are retained as the
  adapter's surface (they remain useful as a typed external API), but they are now described as
  "the optional MCP adapter's verbs," not "the agent's only interface." The TUI approval gate (§3) is the
  *same* gate whether the proposal arrives via the in-process Agent or via the MCP adapter — approval is a
  property of the seam, not of MCP.

- **Why:** removes the over-engineering (MCP-as-center with a single adapter for zero users) while keeping
  every safety property — the proposal is *always* a typed Flow, *always* statically validated, *always*
  human-approved before execution, regardless of transport. ADR-024's **executor-rejects-unsigned-jobs**
  boundary (cross-referenced here) is what makes the approval gate enforceable rather than advisory: an
  unapproved/unsigned Flow is rejected at execution, so no adapter — present or future — can bypass it.

**Reads-as-superseding §2–§3:** wherever §2–§3 say "the agent never sees Python objects … it sees an MCP
tool-server," read instead "the agent yields a proposed typed Flow into the in-process approval seam; an
optional MCP adapter exposes that seam to external clients." The typed-schema-only, no-free-text-deck,
no-raw-shell guarantees of §2 are unchanged and apply to the seam itself.

### 2. Delegate campaign logic to **ADR-025**: the `CampaignController` is *configured with* a strategy; it holds no embedded acquisition/escalation policy.

The original §1/§4 left the controller as the implicit holder of "what to propose next" and "when to spend
DFT budget." That scientific-judgment policy is now a typed, pluggable object owned by **ADR-025**:

- The `CampaignController` is **configured with** an ADR-025 `AcquisitionStrategy` (scores candidates over an
  ADR-026 `UncertaintyEstimate`) **and** an ADR-025 `CampaignStrategy` (the loop's budget / convergence /
  stopping rules and DFT-budget control). The controller *runs the loop*; it does **not** contain the
  acquisition function, the stopping criterion, or any escalation threshold.
- The **MLIP-screen → DFT-validate** step of §1 obeys **ADR-026's trust gate**, not an ad-hoc controller
  threshold. A candidate that ADR-026's applicability-domain / OOD check flags as out-of-domain **must** be
  escalated to DFT — it can never skip validation on a controller-local heuristic. The escalation boundary is
  one-directional and explicit: §1's loop **consumes** ADR-026's `UncertaintyEstimate` + escalation threshold
  at exactly the screen→validate boundary.
- The `acquisition_function: str | None` field in the original §6 `AIProvenance` is **superseded** by a typed
  reference to the ADR-025 strategy that selected the candidate (see §4 of this amendment for the record
  shape); a free string is no longer the system of record for *which* acquisition policy ran.

**Why:** moves the campaign brain to ADR-025 so the controller is *configured-with* a strategy rather than
*being* the policy holder. This ADR keeps only the **mechanism** (composing factories, emitting `Response`
detours, gating submission); the **policy** (acquisition/convergence/stopping/DFT-budget) lives in ADR-025
and the **trust decision** in ADR-026.

### 3. Make AI provenance **audit-grade**: store the actual prompt/tool-call **transcript** in the ADR-022 CAS, not just a hash.

The original §6 recorded only a `prompt_hash`. A hash proves *that* a prompt was used but is useless for
*auditing what the agent actually did* — you cannot review a decision you cannot read. Corrected:

- `AIProvenance` carries a **`transcript_cas_key`** alongside `prompt_hash`. The full prompt + tool-call
  transcript (the messages, the tool calls and their typed arguments, the model's responses) is written into
  the **ADR-022 content-addressed store** and referenced by its CAS key. The `prompt_hash` remains for fast
  equality/cache-invalidation; the `transcript_cas_key` makes the decision **reviewable**.
- **Redaction policy (stated, not implied):** secrets and credentials (API keys, tokens, SSH material) are
  **redacted before** the transcript is written to the CAS — redaction happens pre-hash, so the stored object
  and its CAS key are over the redacted transcript. User-supplied structure/target data is retained (it is
  scientific input, part of the audit trail). The redaction transform is itself recorded (a
  `redaction_policy_id`) so a reviewer knows *what class* of content was removed. Nothing un-redacted is ever
  written to the CAS.
- The transcript CAS key is **folded into the ADR-022 content-address closure** for the agent node's
  provenance exactly as `prompt_hash` was, so the audit record travels with the artifact and a changed
  transcript correctly participates in cache identity.

**Why:** "which model and which human produced this, and *what was actually said*" must be answerable from
the store, not merely attested by a hash. This is the audit-grade upgrade the consensus required.

### 4. Adopt the unified **`ModelIdentifier`** (ADR-027) for the agent/generative model identity, and fetch/pin MatterGen as an ADR-027 model.

The original §6 used loose `model_id: str` + `model_version: str` strings. These are replaced by ADR-027's
**single unified `ModelIdentifier`**, the same identity type used across 025/026/027:

- `AIProvenance.model` is a `ModelIdentifier` (ADR-027) — it resolves the agent/generative model and its
  pinned version through ADR-027's `ModelRegistry`, eliminating the free-string `model_id@version` and the
  floating-"latest" risk the original §7 only forbade by convention.
- The §4 **MatterGen** `CandidateSource` resolves MatterGen as a **fetched/pinned ADR-027 model** (a
  `ModelIdentifier` into the `ModelRegistry` over the ADR-022 CAS), not an ad-hoc import or rev string. Its
  checkpoint identity is therefore the same kind of object as every other model in the system, and a
  checkpoint bump invalidates dependent caches through the normal ADR-022 closure.

The corrected §6 record (superseding lines 167–168 and the `acquisition_function` string of the original):

```python
class AIProvenance(BaseModel):
    model: ModelIdentifier          # ADR-027 — agent/generative model + pinned version, registry-resolved
    prompt_hash: str                # fast equality / cache key for the exact prompt/template
    transcript_cas_key: str         # ADR-022 CAS key of the redacted prompt+tool-call transcript (§3)
    redaction_policy_id: str        # which redaction transform was applied before hashing (§3)
    tool_call: str                  # which seam verb / adapter verb (§2, §1-of-amendment)
    agent_identity: str             # which agent/role issued it
    acquisition_strategy: StrategyRef | None  # ADR-025 strategy that selected the candidate (was a free str)
    human_approval: ApprovalRecord  # who approved at which tier, when (§3)
```

**Why:** a single typed identity for every model/dataset (resolved through ADR-027) makes provenance,
caching, and trust evaluation agree on *what exactly* a model is — no parallel string conventions to drift.

### 5. Citation-integrity fixes (correctness invariant)

Treated as a correctness invariant, not a stylistic note. The following changes were applied inline and in
the References section:

- **Removed** the five unverifiable/fabrication-risk references — "Catalyst-Agent" (arXiv:2603.01311),
  "Pham et al. / Aurora" (arXiv:2604.07681), "SparksMatter" (arXiv:2508.02956), "MASTER" (arXiv:2512.13930,
  whose "~90% fewer simulations" quantitative claim was likewise unverifiable), and "Kosmos"
  (arXiv:2511.02824). Two were mislabeled/wrong-title and four were future-dated relative to the verifiable
  record. Per the project rule, an unverifiable citation is **deleted**, not reworded around a possibly-
  fabricated identifier; the architectural claims stand on the verified anchors.
- **Corrected** the MCP reference to point at the **specification/elicitation** page
  (modelcontextprotocol.io/specification) where the form-mode human-approval gate (§3) is defined, rather than
  the bare site root.
- **Anchored** the MLIP-pre-filter compute-savings claim on **Matbench Discovery** (Riebesell et al.,
  arXiv:2308.14920; F1 leaderboard ~0.57–0.82) — a known-canonical source — rather than the removed "MASTER"
  figure.
- Retained the canonical anchors already present: **MatterGen** (Zeni et al., *Nature* 2025,
  arXiv:2312.03687) and **jobflow** (Rosen et al., JOSS 2024).

Verifiability tags for the citations now in this ADR: MatterGen — *canonical*; jobflow — *canonical*;
Matbench Discovery — *canonical*; MCP specification/elicitation — *docs-url*. No *uncertain* citation
remains.

### Net effect on the Decision

The Decision is unchanged in spirit and stricter in form: a Python **Agent yields a proposed typed Flow**;
the **TUI approves**; **ADR-024 validates** and its executor **rejects unsigned jobs**; **ADR-022** hashes
the closure **including an audit-grade transcript**; campaign **policy** lives in **ADR-025**, surrogate
**trust** in **ADR-026**, model **identity** in **ADR-027**; and **MCP is one optional adapter** over the
seam, no longer its center.
