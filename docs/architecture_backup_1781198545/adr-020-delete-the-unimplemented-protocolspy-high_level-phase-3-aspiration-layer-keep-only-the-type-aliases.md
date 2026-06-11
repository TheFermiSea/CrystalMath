---
adr_id: 020
title: "Delete The Unimplemented Protocolspy High_level Phase 3 Aspiration Layer Keep Only The Type Aliases"
status: "Accepted"
date: "2026-06-11"
macro_context: "crystalmath-tui-core"
---

# ADR-020: Delete The Unimplemented Protocolspy High_level Phase 3 Aspiration Layer Keep Only The Type Aliases



**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** none
**Depends on:** [ADR-007](adr-007-redesign-overview-adopt-ecosystem.md) (redesign overview — delete homegrown machinery, adopt the ecosystem)
**Relates to:** [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) (workflow engine — jobflow `Flow`s as the one orchestration model)

## Context

`python/crystalmath/protocols.py` and `python/crystalmath/high_level/api.py` define an
ambitious "Phase 3" orchestration layer that was never implemented. It now competes with —
and actively confuses navigation against — the code that actually runs work today
(`decks/`, `quacc/`, `workflows/`, and the jobflow/atomate2 bridges).

Concretely:

- **`protocols.py` declares a speculative `Protocol` surface** —
  `WorkflowRunner`, `StructureProvider`, `ParameterGenerator`, `ResultsCollector`,
  `WorkflowComposer` — and a set of factory functions to obtain implementations of them
  (`get_runner`, `get_structure_provider`, `get_parameter_generator`). Those factories do
  not return anything: they `raise NotImplementedError("Phase 3")`. No production code path
  ever obtains a live object through them.

- **`high_level/api.py` is a self-described stub.** Its `HighThroughput` one-liner API drives
  a "mock path" through `integrations/atomate2_bridge.py` (`Atomate2Bridge`,
  `MultiCodeFlowBuilder.build`, `create_vasp_to_yambo_flow`), several methods of which are
  themselves `raise NotImplementedError("Phase 3")` stubs. It is aspiration, not a working
  surface.

- **The aspiration layer duplicates — poorly — what already works.** `protocols.WorkflowRunner`
  is a thinner, never-implemented version of the orchestration that `quacc/runner.py`
  (`JobRunner` over Parsl/Covalent), `integrations/slurm_runner.py` (`SLURMWorkflowRunner`),
  and the jobflow path already provide. `StructureProvider`/`ParameterGenerator` overlap the
  real, working `decks/` seam (`InputDeck` + `CodeDeckGenerator` + `get_deck_generator` +
  `stage()`), which is the canonical input-generation layer per
  [ADR-008](adr-008-structure-and-deck-io-on-ase-pymatgen.md).
  `ResultsCollector`/`WorkflowComposer` overlap the result/flow handling the jobflow engine
  owns ([ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md)). Maintaining a parallel,
  hollow vocabulary for these concerns is pure drag.

- **It is not free-floating; a few real modules import from it.** `integrations/atomate2_bridge.py`
  and `high_level/clusters.py` import names from `protocols`, so deletion is not a single
  `git rm` — the import edges must be pruned and redirected.

- **Some of the names in `protocols.py` *are* load-bearing.** The module also exports the type
  aliases `WorkflowType`, `DFTCode`, and `ResourceRequirements`, which are used widely across
  the codebase. These are not the aspiration; they are the shared vocabulary. They must survive
  the deletion.

This ADR is the protocols/high_level instance of the broader "delete the homegrown machinery"
program governed by [ADR-007](adr-007-redesign-overview-adopt-ecosystem.md). The workflow-engine
ADR ([ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md)) establishes *where* the one
remaining protocol that pays its way — `WorkflowRunner` — actually lives: it is subsumed by the
jobflow engine. Once that home exists, the speculative `Protocol` surface has no reason to remain.

With **zero active users**, there is no backward-compatibility constraint (see the project
charter). Deleting an unimplemented layer is cheap and clarifying: it removes a false second
"how do I run a workflow?" answer from the tree and points every reader at the working reality.

## Decision

1. **Delete the speculative `Protocol` classes and their factories from
   `python/crystalmath/protocols.py`.** Remove `WorkflowRunner`, `StructureProvider`,
   `ParameterGenerator`, `ResultsCollector`, and `WorkflowComposer`, together with the
   `get_runner` / `get_structure_provider` / `get_parameter_generator` factories that
   `raise NotImplementedError("Phase 3")`. None of them is implemented; none is on a live path.

2. **Delete the self-described stub `python/crystalmath/high_level/api.py`** (the `HighThroughput`
   "Phase 3" mock surface) and the dead multi-code stubs it leans on in
   `integrations/atomate2_bridge.py` (`MultiCodeFlowBuilder.build`,
   `create_vasp_to_yambo_flow`, `submit_composite`, and any other
   `raise NotImplementedError("Phase 3")` entry points). Real multi-code handoffs become typed
   dataflow edges in the jobflow graph (per
   [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) and the typed-edge validation of
   [ADR-013](adr-013-multi-code-handoff-and-restart-validation.md)), not stub functions in a
   bridge.

3. **Preserve the type aliases** `WorkflowType`, `DFTCode`, and `ResourceRequirements`.
   They are used widely and are not part of the aspiration. They **migrate to the canonical
   data model defined in [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md)**
   (the single versioned schema and state vocabulary), with `DFTCode`/`WorkflowType` aligned to
   the per-code seam of [ADR-008](adr-008-structure-and-deck-io-on-ase-pymatgen.md):
   `protocols.py` either re-exports them from the canonical location (a thin shim during the
   transition) or is reduced to the alias definitions alone. The single-schema-everywhere goal of
   ADR-009 is the long-term home; this ADR's obligation is only to not break those names while
   removing everything around them.

4. **Prune and redirect the import edges.** Update `integrations/atomate2_bridge.py` and
   `high_level/clusters.py` (and any other importers surfaced by a tree-wide search) so they
   import the surviving type aliases from their canonical location and no longer reference the
   deleted `Protocol` classes or factories. `high_level/clusters.py`'s cluster-profile data is
   real and stays; only its dependency on the deleted protocol surface is removed.

5. **The one protocol that pays its way is not reintroduced here — it already has a home.**
   `WorkflowRunner` (the only member with a genuine reason to exist) is subsumed by the jobflow
   engine and its pluggable executor interface
   ([ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md), and the `ExecutionBackend` seam
   of [ADR-012](adr-012-hpc-execution-jobflow-remote-aiida-optional.md)). We do not keep a
   vestigial `WorkflowRunner` `Protocol` in `protocols.py` "for later"; "later" is the jobflow
   engine, and a second declaration would re-create the very confusion this ADR removes.

### Scope (what is deleted vs kept)

| Symbol | Location | Disposition |
|--------|----------|-------------|
| `WorkflowRunner` (Protocol) | `protocols.py` | **Deleted** — subsumed by the jobflow engine (ADR-011/012) |
| `StructureProvider` (Protocol) | `protocols.py` | **Deleted** — overlaps the working `decks/` seam (ADR-008) |
| `ParameterGenerator` (Protocol) | `protocols.py` | **Deleted** — overlaps `decks/` + canonical schema (ADR-008/009) |
| `ResultsCollector` (Protocol) | `protocols.py` | **Deleted** — owned by the jobflow result layer (ADR-010/011) |
| `WorkflowComposer` (Protocol) | `protocols.py` | **Deleted** — owned by jobflow `Flow` composition (ADR-011) |
| `get_runner` / `get_structure_provider` / `get_parameter_generator` | `protocols.py` | **Deleted** — all raise `NotImplementedError("Phase 3")` |
| `WorkflowType`, `DFTCode`, `ResourceRequirements` | `protocols.py` | **Kept**, migrated to the canonical data model (ADR-009) / deck seam (ADR-008) |
| `HighThroughput` "Phase 3" API | `high_level/api.py` | **Deleted** — self-described stub |
| `MultiCodeFlowBuilder.build`, `create_vasp_to_yambo_flow`, `submit_composite` | `integrations/atomate2_bridge.py` | **Deleted** — `NotImplementedError("Phase 3")` stubs |
| Cluster-profile data | `high_level/clusters.py` | **Kept** — only the protocol import edge is pruned |

## Consequences

### Positive

- **One answer to "how do I run a workflow?"** Removing the hollow `WorkflowRunner`/`Composer`
  vocabulary leaves `decks/` + `quacc/` + the jobflow engine (ADR-011) as the single, navigable
  reality.
- **Less dead code and fewer `NotImplementedError("Phase 3")` traps.** Readers (human and agent)
  stop following factory calls that can never return an object.
- **The `decks/` seam stops competing with a phantom.** `StructureProvider`/`ParameterGenerator`
  no longer present a second, never-built spelling of input generation (ADR-008).
- **Cheap to do now.** Zero users means no deprecation window; the surviving type aliases keep
  every real call site compiling.
- **Aligns the tree with the ADR-008/009/011 direction** before those refactors land, so they do
  not have to thread through a dead aspiration layer.

### Negative / Risks

- **Import-edge churn.** `integrations/atomate2_bridge.py` and `high_level/clusters.py` (and any
  other importers) must be edited in lockstep with the deletion, or imports break. Mitigation: a
  tree-wide `grep` for `from .protocols`, `from crystalmath.protocols`, and `high_level.api`
  before deleting, and a green `uv run pytest` after.
- **Loss of a written "north star."** The Protocol surface documented an *intended* shape of the
  system. Mitigation: that intent is now carried by the workflow-engine and data-model ADRs
  (ADR-011 jobflow engine, ADR-009 canonical schema, ADR-008 deck seam), which describe the same
  goals as *decisions with implementations*, not as unimplemented `Protocol`s.
- **Alias migration must be exact.** If `WorkflowType`/`DFTCode`/`ResourceRequirements` are moved
  rather than re-exported, every importer must be updated. Mitigation: keep `protocols.py` as a
  thin re-export shim of the canonical data model until ADR-009's schema consolidation completes,
  then drop the shim.

## Alternatives Considered

1. **Implement the Protocol layer ("finish Phase 3").** Rejected. Building out
   `WorkflowRunner`/`StructureProvider`/`ParameterGenerator`/`ResultsCollector`/`WorkflowComposer`
   would re-implement, in CrystalMath-specific abstractions, exactly what jobflow/atomate2,
   quacc, and the `decks/` seam already do robustly. The research is unanimous that the
   hand-rolled orchestration paths are worse reimplementations of mature ecosystem tools
   (jobflow's dynamic DAG, custodian's error recovery, the pymatgen `InputSet`/`InputGenerator`
   base classes) — the core finding of [ADR-007](adr-007-redesign-overview-adopt-ecosystem.md).
   Spending effort to make the aspiration real would deepen the duplication this program is trying
   to remove.

2. **Keep the Protocols as documentation-only "interfaces" (no factories).** Rejected. A
   `Protocol` with no implementations and no live call sites is documentation that pretends to be
   code; it still shows up in navigation, import graphs, and type-checker output as a parallel
   way to do things. ADRs are the right home for intent; an unimplemented `Protocol` is not.

3. **Keep only `WorkflowRunner` as a vestigial Protocol "for later."** Rejected. `WorkflowRunner`
   is the one member with a real reason to exist, but its home is the jobflow engine's pluggable
   executor interface (ADR-011/012), not `protocols.py`. A second declaration would re-create the
   "two answers" confusion. If a thin Python-side runner facade is ever wanted over the jobflow
   executor, it should be defined where the engine lives, with an implementation, at that time.

4. **Delete `protocols.py` wholesale, type aliases included.** Rejected. `WorkflowType`,
   `DFTCode`, and `ResourceRequirements` are used widely; deleting them outright would force a
   large, mechanical, error-prone churn across unrelated modules in the same change. Preserving
   them (migrated to the ADR-009 canonical data model) keeps this ADR's blast radius confined to
   the actually-dead aspiration layer.

## References

### Prior decisions in this repo

- [ADR-007](adr-007-redesign-overview-adopt-ecosystem.md) — Redesign overview: delete the
  homegrown machinery, adopt the ecosystem, collapse N-way facades to one. This ADR is that
  rule applied to the protocols/high_level aspiration layer.
- [ADR-006](adr-006-unify-on-rust-tui.md) — Unify on the Rust TUI over an IPC backend; the Python
  core (`python/crystalmath/`) is the single source of business-logic truth. This ADR removes one
  of that core's two competing orchestration vocabularies.
- [ADR-008](adr-008-structure-and-deck-io-on-ase-pymatgen.md) — Structure + deck I/O on
  pymatgen/ASE; the working `decks/` seam that `StructureProvider`/`ParameterGenerator` shadow,
  and the home for the `DFTCode`/`WorkflowType` vocabulary.
- [ADR-009](adr-009-canonical-data-model-emmet-pydantic-taskdocs.md) — Canonical, versioned
  data model; the destination for the preserved type aliases.
- [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) /
  [ADR-012](adr-012-hpc-execution-jobflow-remote-aiida-optional.md) — jobflow `Flow`s as the
  single orchestration model and the pluggable execution backend that subsume `WorkflowRunner`.

### Code grounding (this repo)

- `python/crystalmath/protocols.py` — the speculative `WorkflowRunner`/`StructureProvider`/
  `ParameterGenerator`/`ResultsCollector`/`WorkflowComposer` surface and the
  `get_runner`/`get_structure_provider`/`get_parameter_generator` factories that
  `raise NotImplementedError("Phase 3")`; also the surviving type aliases `WorkflowType`,
  `DFTCode`, `ResourceRequirements`.
- `python/crystalmath/high_level/api.py` — the self-described `HighThroughput` "Phase 3" stub.
- `python/crystalmath/high_level/clusters.py` — real cluster-profile data that imports from
  `protocols`; its import edge is pruned.
- `python/crystalmath/integrations/atomate2_bridge.py` — `Atomate2Bridge`,
  `MultiCodeFlowBuilder.build`, `create_vasp_to_yambo_flow`, `submit_composite` — the
  `NotImplementedError("Phase 3")` multi-code stubs and a protocol importer.
- `python/crystalmath/decks/__init__.py` — `InputDeck` + `CodeDeckGenerator` +
  `get_deck_generator` + `stage()`, the working input-generation seam that
  `StructureProvider`/`ParameterGenerator` shadow.
- `python/crystalmath/quacc/runner.py` — `JobRunner` over Parsl/Covalent, part of the working
  orchestration reality that `WorkflowRunner` shadows.

### Literature / ecosystem (why the working reality wins)

- A. M. Ganose, J. Sahasrabuddhe, … A. S. Rosen, A. Jain, et al., "Atomate2: modular workflows
  for materials science," *Digital Discovery*, 2025 — defines the current Materials Project stack
  (abstract jobflow `Flow`s of `Maker`s, custodian-based error handling, jobflow-remote/FireWorks
  execution); the model CrystalMath's `atomate2_bridge` half-targets and should fully adopt
  instead of a bespoke Protocol layer.
- jobflow (materialsproject/jobflow), docs at materialsproject.github.io/jobflow — `Job`/`Flow`
  graph with reference-based dataflow and dynamic `Response(replace=…, addition=…)` expansion;
  the home for `WorkflowRunner`/`WorkflowComposer`/`ResultsCollector` concerns.
- A. S. Rosen et al., quacc — The Quantum Accelerator, docs at
  quantum-accelerators.github.io/quacc; Zenodo 10.5281/zenodo.10460657 — the `@job`/`@flow`
  recipe + pluggable-executor pattern already partially wired in `quacc/runner.py`, the working
  realization of `WorkflowRunner`.
- S. P. Ong, W. D. Richards, A. Jain, G. Hautier, M. Kocher, S. Cholia, D. Gunter, V. L. Chevrier,
  K. A. Persson, G. Ceder, "Python Materials Genomics (pymatgen): A robust, open-source python
  library for materials analysis," *Computational Materials Science* 68 (2013) 314–319 — the
  `io.core` `InputFile → InputSet → InputGenerator` three-tier abstraction that the `decks/` seam
  subclasses, making `StructureProvider`/`ParameterGenerator` redundant.
- M. Uhrin, S. P. Huber, J. Yu, N. Marzari, G. Pizzi, "Workflows in AiiDA: Engineering a
  high-throughput, event-based engine for robust and modular computational workflows,"
  *Computational Materials Science* 187 (2021) 110086 (arXiv:2007.10312) — the event-based,
  checkpoint-on-transition engine model; cited as evidence that durable orchestration is a solved
  ecosystem problem, not something a CrystalMath `Protocol` layer should re-specify.
