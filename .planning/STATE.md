# CrystalMath Project State

**Last updated:** 2026-02-03T03:00:00Z
**Status:** Active development

## Current Position

**Phase:** 4 of 6 (Workflow Execution)
**Plan:** 0 of ? complete
**Status:** READY TO PLAN
**Last activity:** 2026-02-03 - Completed Phase 3 (Structure & Input Handling)

**Progress:**
```
Phase 1 [##########] 100% (3/3 plans) COMPLETE
Phase 2 [##########] 100% (4/4 plans) COMPLETE
Phase 3 [##########] 100% (4/4 plans) COMPLETE
Phase 4 [----------] 0%
Phase 5 [----------] 0%
Phase 6 [----------] 0%
```

## Accumulated Decisions

| Phase | Decision | Rationale |
|-------|----------|-----------|
| 01-01 | Use asyncio stdlib for IPC server | No external deps, simple deployment |
| 01-01 | Content-Length framing (LSP-style) | Matches existing lsp.rs, debuggable |
| 01-01 | Handler registry pattern | Extensible, system.* handled locally |
| 01-01 | Lazy controller initialization | Faster server startup |
| 01-02 | Use dirs crate for socket path | Avoids libc dep, cross-platform |
| 01-02 | 30s default timeout | Matches ADR-003 specification |
| 01-02 | Reuse bridge.rs JSON-RPC types | DRY, no type duplication |
| 01-03 | 5s server startup timeout | Allows for Python interpreter startup |
| 01-03 | lib.rs for test access | Standard pattern for integration tests |
| 01-03 | Per-test unique socket paths | Prevents test interference |
| 02-01 | Pydantic for cluster/job config validation | Type safety with clear error messages |
| 02-01 | JSON file storage in ~/.crystalmath/ | Simple persistence without database deps |
| 02-01 | Two-level ImportError handling | Graceful degradation for partial quacc installs |
| 02-01 | DEBUG level logging for skipped modules | Avoids noise while preserving debuggability |
| 02-02 | Rename handlers.py to _handlers.py | Resolves Python naming conflict with handlers/ package |
| 02-02 | Re-export registry in handlers/__init__.py | Maintains backwards compatibility for imports |
| 02-02 | Lazy imports inside handlers | Graceful degradation and faster startup |
| 02-03 | Separate QuaccClusterConfig from ClusterConfig | Different domains (Parsl vs SSH/SLURM direct) |
| 02-03 | Recipe browser as modal overlay | Follows workflow_state pattern for consistency |
| 02-03 | Serde defaults for optional fields | Handle partial API responses gracefully |
| 02-04 | ApiResponse wrapper for fetch_clusters | Python API uses {"ok": true, "data": ...} envelope |
| 03-01 | Lazy numpy import in KpointsBuilder | Avoids import error when numpy not installed |
| 03-01 | ENMAX table for ENCUT estimation | Reasonable defaults without POTCAR lookup |
| 03-01 | POTCAR symbols only (no content) | POTCAR requires VASP license, user provides |
| 03-02 | JSON-RPC for VASP generation | Follows thin IPC pattern, no new bridge variants |
| 03-02 | Combined VASP files in editor | Simple view for initial implementation |
| 03-02 | 'v' keybinding for VASP | Keep Enter for D12, backwards compatible |
| 03-03 | 60/40 split for results/preview | Enough room for preview without crowding table |
| 03-03 | Auto-trigger preview on selection | Reduces user clicks, natural exploration flow |
| 03-04 | 'p' and 'K' keybindings | Match existing single-key pattern for modal actions |
| 03-04 | KPPRA cycling (500→1000→2000→4000) | Common values for different accuracy needs |

## Blockers / Concerns

None currently. Phase 3 complete:
- All 4 plans delivered (Python VASP + Rust wiring + Preview UI + Integration tests)
- VASP generation requires pymatgen (optional dependency)
- 127 tests passing (103 unit + 7 quacc + 6 VASP integration + 11 others)
- Integration tests gracefully skip when pymatgen not installed

## Session Continuity

**Last session:** 2026-02-03T03:00:00Z
**Stopped at:** Completed Phase 3 (all 4 plans)
**Resume with:** Phase 4 planning (Workflow Execution)

## Completed Summaries

Phase 1 (IPC Foundation):
- [01-01-SUMMARY.md](.planning/phases/01-ipc-foundation/01-01-SUMMARY.md) - Python JSON-RPC server
- [01-02-SUMMARY.md](.planning/phases/01-ipc-foundation/01-02-SUMMARY.md) - Rust IPC client module
- [01-03-SUMMARY.md](.planning/phases/01-ipc-foundation/01-03-SUMMARY.md) - Auto-start and integration tests

Phase 2 (quacc Integration):
- [02-01-SUMMARY.md](.planning/phases/02-quacc-integration/02-01-SUMMARY.md) - Python quacc module
- [02-02-SUMMARY.md](.planning/phases/02-quacc-integration/02-02-SUMMARY.md) - RPC handlers for quacc
- [02-03-SUMMARY.md](.planning/phases/02-quacc-integration/02-03-SUMMARY.md) - Recipe browser UI
- [02-04-SUMMARY.md](.planning/phases/02-quacc-integration/02-04-SUMMARY.md) - Integration tests and bug fixes

Phase 3 (Structure & Input Handling):
- [03-01-SUMMARY.md](.planning/phases/03-structure-input/03-01-SUMMARY.md) - Python VASP utilities
- [03-02-PLAN.md](.planning/phases/03-structure-input/03-02-PLAN.md) - Rust TUI VASP wiring (complete)
- [03-03-PLAN.md](.planning/phases/03-structure-input/03-03-PLAN.md) - Structure preview UI (complete)
- [03-04-PLAN.md](.planning/phases/03-structure-input/03-04-PLAN.md) - VASP config form and integration tests (complete)

## Key Files for Context

Created in Phase 1:
- `python/crystalmath/server/__init__.py` - JsonRpcServer, main()
- `python/crystalmath/server/_handlers.py` - HANDLER_REGISTRY, system.ping (renamed from handlers.py)
- `python/pyproject.toml` - crystalmath-server entry point
- `src/lib.rs` - Library root exposing ipc, bridge, models
- `src/ipc.rs` - Module root with pub exports
- `src/ipc/client.rs` - IpcClient with connect/call/ping/auto-start
- `src/ipc/framing.rs` - Content-Length codec
- `tests/ipc_integration.rs` - 7 integration tests

Created in Phase 2 Plan 1:
- `python/crystalmath/quacc/__init__.py` - Package exports
- `python/crystalmath/quacc/discovery.py` - discover_vasp_recipes()
- `python/crystalmath/quacc/engines.py` - get_engine_status()
- `python/crystalmath/quacc/config.py` - ParslClusterConfig, ClusterConfigStore
- `python/crystalmath/quacc/store.py` - JobStatus, JobMetadata, JobStore
- `python/tests/test_quacc.py` - 28 unit tests

Created in Phase 2 Plan 2:
- `python/crystalmath/server/handlers/__init__.py` - Auto-imports, re-exports registry
- `python/crystalmath/server/handlers/recipes.py` - recipes.list handler
- `python/crystalmath/server/handlers/clusters.py` - clusters.list handler
- `python/crystalmath/server/handlers/jobs.py` - jobs.list handler
- `python/tests/test_handlers_quacc.py` - 17 handler tests

Created in Phase 2 Plan 3:
- `src/models.rs` - Recipe, RecipesListResponse, WorkflowEngineStatus, QuaccClusterConfig, QuaccJobMetadata models
- `src/ui/recipes.rs` - RecipeBrowserState, render function, modal layout
- `src/ui/mod.rs` - recipes module export, modal render integration
- `src/app.rs` - recipe_browser field added to App

Created in Phase 2 Plan 4:
- `tests/quacc_integration.rs` - 7 integration tests for quacc RPC handlers
- `src/app.rs` - Fixed cluster deserialization with ApiResponse wrapper

Created in Phase 3 Plan 1:
- `python/crystalmath/vasp/__init__.py` - Module exports
- `python/crystalmath/vasp/incar.py` - IncarBuilder, IncarPreset
- `python/crystalmath/vasp/kpoints.py` - KpointsBuilder, KpointsMesh
- `python/crystalmath/vasp/generator.py` - VaspInputGenerator, VaspInputs
- `python/crystalmath/integrations/pymatgen_bridge.py` - Added structure_to_poscar()
- `python/crystalmath/api.py` - Added vasp.* and structures.* RPC handlers
- `python/tests/test_vasp_generator.py` - VASP generation tests

Created in Phase 3 Plan 2:
- `src/models.rs` - Added VaspPreset, VaspGenerationConfig, GeneratedVaspInputs, StructurePreview
- `src/state/mod.rs` - Added vasp_config to MaterialsSearchState
- `src/app.rs` - Added vasp_request_id, request_generate_vasp_from_mp(), VASP response handler
- `src/main.rs` - Added 'v' keybinding for VASP generation in materials modal

Created in Phase 3 Plan 3:
- `src/models.rs` - Added VaspPreset::next() cycling method
- `src/state/mod.rs` - Added preview state fields, clear_preview(), set_preview_loading(), set_preview()
- `src/app.rs` - Added request_structure_preview(), preview response handler
- `src/ui/materials.rs` - Added render_preview_panel() with full structure preview display

Created in Phase 3 Plan 4:
- `src/state/mod.rs` - Added cycle_vasp_preset(), cycle_kppra() methods
- `src/main.rs` - Added 'p' and 'K' keybindings for config cycling
- `src/ui/materials.rs` - Added VASP config section to preview panel, updated button hints
- `tests/vasp_integration.rs` - 6 integration tests for VASP generation and config

## Next Steps

1. Plan Phase 4 (Workflow Execution)
2. Future: Separate files view for POSCAR/INCAR/KPOINTS
