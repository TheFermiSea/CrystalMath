---
phase: 02-quacc-integration
plan: 01
subsystem: api
tags: [quacc, parsl, slurm, pydantic, workflow-engine]

# Dependency graph
requires:
  - phase: 01-ipc-foundation
    provides: IPC server infrastructure for RPC handlers
provides:
  - python/crystalmath/quacc/ package with discovery, engines, config, store modules
  - discover_vasp_recipes() for recipe introspection
  - get_engine_status() for workflow engine detection
  - ClusterConfigStore for Parsl cluster persistence
  - JobStore for job metadata tracking
affects:
  - 02-02 (RPC handlers will delegate to these modules)
  - 02-03 (UI will consume recipe/engine data)
  - future quacc workflow execution phases

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Pydantic models for cluster/job configuration
    - JSON file persistence for cluster/job stores
    - Graceful ImportError handling for optional deps

key-files:
  created:
    - python/crystalmath/quacc/__init__.py
    - python/crystalmath/quacc/discovery.py
    - python/crystalmath/quacc/engines.py
    - python/crystalmath/quacc/config.py
    - python/crystalmath/quacc/store.py
    - python/tests/test_quacc.py
  modified: []

key-decisions:
  - "Pydantic models for cluster config and job metadata validation"
  - "JSON file storage in ~/.crystalmath/ for persistence"
  - "Two-level ImportError handling: top-level quacc + submodule level"
  - "Walltime validation with HH:MM:SS regex pattern"

patterns-established:
  - "Graceful degradation: return empty list when optional deps missing"
  - "Module introspection via pkgutil.walk_packages + inspect.getmembers"
  - "Pydantic BaseModel with field_validator for config validation"

# Metrics
duration: 8min
completed: 2026-02-02
---

# Phase 2 Plan 1: Python quacc Module Summary

**Recipe discovery via pkgutil introspection, workflow engine detection, Pydantic-validated cluster config and job metadata stores with graceful ImportError handling**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-02T22:37:26Z
- **Completed:** 2026-02-02T22:45:02Z
- **Tasks:** 3
- **Files created:** 6

## Accomplishments
- discover_vasp_recipes() walks quacc.recipes.vasp via pkgutil and extracts _job/_flow functions
- Submodule ImportErrors (e.g., MLIP modules with missing deps) caught at DEBUG level, discovery continues
- get_engine_status() returns configured engine, installed engines list, and quacc_installed flag
- ParslClusterConfig model with walltime validation (HH:MM:SS pattern)
- ClusterConfigStore persists to ~/.crystalmath/clusters.json
- JobStore with status filtering and created_at descending sort
- 28 unit tests covering all modules

## Task Commits

Each task was committed atomically:

1. **Task 1: Create quacc discovery and engines modules** - `af6b21c` (feat)
2. **Task 2: Create cluster config and job store modules** - `ea48d94` (feat)
3. **Task 3: Add unit tests for quacc module** - `b4bd2a8` (test)

## Files Created

- `python/crystalmath/quacc/__init__.py` - Package exports for discovery, engines, config, store
- `python/crystalmath/quacc/discovery.py` - discover_vasp_recipes() with pkgutil introspection
- `python/crystalmath/quacc/engines.py` - get_workflow_engine(), get_installed_engines(), get_engine_status()
- `python/crystalmath/quacc/config.py` - ParslClusterConfig model, ClusterConfigStore class
- `python/crystalmath/quacc/store.py` - JobStatus enum, JobMetadata model, JobStore class
- `python/tests/test_quacc.py` - 28 comprehensive unit tests

## Decisions Made

1. **Pydantic for validation** - Models ensure type safety and provide clear error messages
2. **JSON file storage** - Simple persistence without database dependencies
3. **~/.crystalmath/ as config dir** - Standard user-level config location
4. **Two-level ImportError handling** - Both quacc top-level and submodule errors handled gracefully
5. **DEBUG level logging for skipped modules** - Avoids log noise while preserving debuggability

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- **Test mocking complexity**: Python's import system required proper module hierarchy (types.ModuleType with parent references) to correctly mock quacc package for testing. Using MagicMock alone failed because import statements traverse the module hierarchy.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- quacc module provides all building blocks for RPC handlers
- Ready for 02-02: RPC handler implementation that delegates to these modules
- All functions work gracefully when quacc is not installed

---
*Phase: 02-quacc-integration*
*Completed: 2026-02-02*
