# ADR-023: Agentic/LLM Control Plane — a Guarded MCP Tool-Server Above jobflow, a Generative CandidateSource, and First-Class AI Provenance

**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** none — *amends* [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md)'s static-Flow-factory framing (the campaign brain moves above the factories; the factories stay) and [ADR-019](adr-019-delete-phase3-protocols-aspiration-layer.md)'s "decks + jobflow are the single answer to *how do I run a workflow*" claim (an agentic composition entry point is admitted above that answer)
**Depends on:** [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) (the `make_*_flow` factories the agent composes and the jobflow `Response` detour/replace primitive it emits), [ADR-014](adr-014-ipc-boundary-stdio-jsonrpc-delete-pyo3.md) (the stdio JSON-RPC transport the MCP tool-server rides), [ADR-016](adr-016-wire-contract-codegen-no-drift.md) (wire-contract validation of the proposed-Flow schemas), [ADR-018](adr-018-error-recovery-custodian-handlers.md) (the custodian handler catalogue the LLM-diagnosis step sits above), [ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md) (the `CalculatorStage` — DFT and MLIP — the generative loop screens and validates against), [ADR-024](adr-024-static-typed-workflow-dag-validation.md) (the offline DAG type-checker that gates every proposed Flow before submission)
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

**The field has already built and validated this layer, and standardized its interface.** Agentic
materials systems now drive real workflow engines in closed loops through Model Context Protocol (MCP)
tool-servers: Catalyst-Agent (arXiv:2603.01311) and Pham et al. on the Aurora autonomous-laboratory stack
(arXiv:2604.07681) are existence proofs of LLM agents submitting and steering materials calculations
through MCP servers. SparksMatter (arXiv:2508.02956) and MASTER (arXiv:2512.13930 — reporting up to ~90%
fewer simulations to reach a target) establish the architecture that makes this safe and efficient: the
*planner* is separated from the *executable workflow* — the agent proposes a typed, inspectable plan; a
deterministic engine executes it. On the generative side, MatterGen (Zeni et al., *Nature* 2025;
arXiv:2312.03687) is the reference diffusion model that *proposes* novel structures conditioned on target
properties — but its outputs are hypotheses, not results: they require DFT validation, which is precisely
the screen→validate loop above. And on provenance, Kosmos (arXiv:2511.02824) shows that once an agent
touches an artifact, *which* model, prompt, tool-call, agent identity, and human approval produced or
modified it must travel *with* the artifact, or the result is unauditable.

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
building blocks load-bearing. The planner-separated-from-executable-workflow architecture (SparksMatter
arXiv:2508.02956; MASTER arXiv:2512.13930) is precisely this constraint.

**C. A custom JSON/REST agent API instead of MCP.** We could expose the verbs over a bespoke HTTP API. *Why
not:* MCP is the converged standard the materials-agent literature already drives workflows through
(Catalyst-Agent arXiv:2603.01311; Pham et al. arXiv:2604.07681), and ADR-014 *already* chose JSON-RPC over
stdio *because it is the LSP/MCP pattern* (`adr-014…` title). Riding the existing transport with the MCP
tool/elicitation vocabulary is strictly less new surface than a parallel REST stack, and gives us
elicitation-based approval (§3) for free rather than reinventing an approval protocol.

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
the active-learning / generative-screening loop (the highest-value, highest-compute-savings use case —
MASTER reports up to ~90% fewer simulations, arXiv:2512.13930) with no home, exactly the gap ADR-011
Alternative B left open. The screen→validate→retrain loop is genuinely *dynamic* (its shape depends on
results) and cannot be a static factory composition; it needs a controller emitting `Response` detours.

## Consequences

### Positive
- **The campaign brain gets a home above the executable DAG.** The propose→screen→validate→retrain loop is a
  first-class `CampaignController` emitting jobflow `Response` detours, closing the gap ADR-011 Alternative B
  left and turning jobflow's dynamic-DAG capability (used only for recovery in ADR-018) into the intended
  adaptive-loop primitive.
- **Agent output is safe by construction.** Every proposed Flow is composed from typed factories (§1), wire-checked
  by ADR-016, statically DAG-checked by ADR-024, and human-approved via MCP elicitation (§3) before a single
  job queues — the agent can never execute unvalidated, and never emits raw deck text or shell.
- **Standardized, not bespoke.** Riding ADR-014's transport with MCP verbs aligns with the existence-proof
  materials-agent stacks (Catalyst-Agent, Aurora) and adds *less* new surface than a parallel API.
- **Full auditability.** AI provenance (model/prompt/tool-call/agent/acquisition/approval) on every artifact
  (§6), folded into ADR-009 and hashed by ADR-022, means "which model and which human produced this result?"
  is always answerable — and a model/prompt change correctly invalidates downstream caches.
- **Novel-failure diagnosis without auto-mutation.** ADR-018's catalogue gains a gated LLM fallback for the
  failures no handler matches (§5), without reopening the silent-self-heal anti-pattern.
- **Generative screening pays off the cache.** Active-learning loops re-evaluate near-identical structures;
  with ADR-022 caching the deterministic child stages (and only the agent node un-cached), the loop reuses
  prior DFT/MLIP work — the regime where MASTER's compute savings are realized.

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
   `CalculatorStage`s.
2. Add `crystalmath.control.mcp` — the guarded MCP tool-server over the ADR-014 transport — exposing the six
   typed verbs (§2); wire `submit_campaign` to MCP elicitation rendered by the Ratatui TUI.
3. **Delete/reframe** `python/crystalmath/ai/service.py`'s free-text `AIService`: its diagnosis capability moves
   behind the gated LLM-diagnosis step (§5); its parameter-suggestion capability moves behind typed
   `generate_deck` (§2). No un-gated free-text path remains.
4. Add the `CandidateSource` protocol with a MatterGen reference implementation behind an optional extra (§4).
5. Extend ADR-009's `ProvenanceDoc` with `AIProvenance` (§6) and include it in the ADR-022 content-address
   closure; mark agent nodes un-cached, child stages cached.
6. Slot the LLM-diagnosis fallback above the ADR-018 custodian catalogue, gated and never auto-applied (§5).

## References

- Zeni, C., Pinsler, R., Zügner, D., et al. (2025). "A generative model for inorganic materials design"
  (MatterGen). *Nature* 639, 624–632. DOI:10.1038/s41586-025-08628-5, arXiv:2312.03687. — Reference diffusion
  `CandidateSource`; property-conditioned structure proposal whose outputs are hypotheses requiring DFT
  validation (§4).
- Rosen, A. S., Ganose, A. M., et al. (2024). "Jobflow: Computational Workflows Made Simple." *Journal of Open
  Source Software* 9(93), 5995. DOI:10.21105/joss.05995. — `Response(detour/replace)` dynamic-DAG primitive the
  `CampaignController` emits for the adaptive loop (§1).
- "Catalyst-Agent: an LLM agent driving catalysis workflows through an MCP tool-server" (2026),
  arXiv:2603.01311. — Existence proof of an agent driving materials workflows through MCP servers in a closed
  loop (motivates §2).
- Pham, et al. (2026). Agentic control of the Aurora autonomous-laboratory materials workflow stack via MCP,
  arXiv:2604.07681. — Existence proof of MCP-mediated agentic materials workflows (motivates §2).
- "SparksMatter: a planner-agent architecture for materials discovery" (2025), arXiv:2508.02956. — Planner
  separated from executable workflow; the architecture §1 adopts (agent proposes a typed plan, a deterministic
  engine executes it).
- "MASTER: multi-agent scientific workflow planning with up to ~90% fewer simulations" (2025),
  arXiv:2512.13930. — Quantifies the compute savings of planner-separated agentic search; motivates the
  screen→validate→retrain loop (§1) and the cache-participation argument.
- "Kosmos: per-artifact AI provenance for autonomous scientific discovery" (2025), arXiv:2511.02824. — The
  case for recording model/prompt/tool-call/agent/approval *with* each artifact; the basis for `AIProvenance`
  (§6).
- Anthropic. "Model Context Protocol (MCP) specification" (tools, elicitation). https://modelcontextprotocol.io/
  — The tool-server + elicitation (form-mode approval) vocabulary §2–§3 layer over the ADR-014 transport.
- Riebesell, J., et al. (2025). "Matbench Discovery." *Nature Machine Intelligence*. — uMLIPs as DFT
  pre-filters (F1 0.57–0.83), the quantitative basis for the MLIP-screen step of the loop (§1; see also
  ADR-021).
- Depends on/amends: [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md) (AI provenance in
  `ProvenanceDoc`), [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) (the composed factories; amends
  its static-factory framing), [ADR-014](adr-014-ipc-boundary-stdio-jsonrpc-delete-pyo3.md) (the MCP transport),
  [ADR-016](adr-016-wire-contract-codegen-no-drift.md) (wire-check of proposed Flows),
  [ADR-018](adr-018-error-recovery-custodian-handlers.md) (LLM-diagnosis above the catalogue),
  [ADR-021](adr-021-calculatorstage-mlip-foundation-calculators.md) (the MLIP/DFT `CalculatorStage`s the loop
  screens and validates against), [ADR-022](adr-022-content-addressed-execution-cache-replay.md) (AI provenance in
  the hash; agent nodes un-cached, children cached), [ADR-024](adr-024-static-typed-workflow-dag-validation.md) (offline
  DAG validation gating every proposed Flow).
- CrystalMath internal: `python/crystalmath/ai/service.py:31` (`AIService`, the free-text LLM client reframed
  into the guarded MCP server); `python/crystalmath/server/` (the ADR-014 JSON-RPC server the MCP tool-server
  rides); `python/crystalmath/control/` (new — `CampaignController` + `control.mcp` tool-server).
