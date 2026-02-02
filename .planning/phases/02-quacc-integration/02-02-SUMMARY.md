---
phase: 02-quacc-integration
plan: 02
subsystem: api
tags: [json-rpc, ipc, handlers, quacc, vasp, recipes]

# Dependency graph
requires:
  - phase: 02-01
    provides: quacc module with discovery.py, engines.py, config.py, store.py
  - phase: 01-01
    provides: HANDLER_REGISTRY and register_handler decorator
provides:
  - recipes.list RPC handler exposing quacc recipe discovery
  - clusters.list RPC handler exposing cluster config and engine status
  - jobs.list RPC handler exposing job metadata store
  - handlers/ subpackage pattern for namespace organization
affects: [02-03, 02-04, rust-tui]

# Tech tracking
tech-stack:
  added: []
  patterns: [namespace-based handlers, auto-registration via import]

key-files:
  created:
    - python/crystalmath/server/handlers/__init__.py
    - python/crystalmath/server/handlers/recipes.py
    - python/crystalmath/server/handlers/clusters.py
    - python/crystalmath/server/handlers/jobs.py
    - python/tests/test_handlers_quacc.py
  modified:
    - python/crystalmath/server/_handlers.py (renamed from handlers.py)

key-decisions:
  - "Renamed handlers.py to _handlers.py to resolve naming conflict with handlers/ package"
  - "Handler package __init__.py re-exports HANDLER_REGISTRY for backwards compatibility"
  - "Handlers import dependencies inside function body for lazy loading"

patterns-established:
  - "Namespace handlers pattern: handlers/{namespace}.py with @register_handler decorator"
  - "Graceful error handling: return error field in response instead of raising"

# Metrics
duration: 4min
completed: 2026-02-02
---

# Phase 02 Plan 02: RPC Handlers Summary

**JSON-RPC handlers bridging Rust TUI to quacc module via recipes.list, clusters.list, and jobs.list methods**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-02T22:48:41Z
- **Completed:** 2026-02-02T22:52:54Z
- **Tasks:** 3
- **Files created:** 5
- **Tests added:** 17

## Accomplishments
- Created handlers/ subpackage with namespace-based handler organization
- Implemented recipes.list returning VASP recipe discovery with quacc version
- Implemented clusters.list returning cluster configs and workflow engine status
- Implemented jobs.list with status filtering and limit parameters
- All handlers gracefully handle missing quacc installation

## Task Commits

Each task was committed atomically:

1. **Task 1: Create handlers package and recipes.list handler** - `fa258a6` (feat)
2. **Task 2: Create clusters.list and jobs.list handlers** - `de58aa3` (feat)
3. **Task 3: Add tests for quacc RPC handlers** - `839318d` (test)

## Files Created/Modified
- `python/crystalmath/server/_handlers.py` - Renamed from handlers.py (system.* handlers, registry)
- `python/crystalmath/server/handlers/__init__.py` - Package init, re-exports registry, auto-imports
- `python/crystalmath/server/handlers/recipes.py` - recipes.list handler
- `python/crystalmath/server/handlers/clusters.py` - clusters.list handler
- `python/crystalmath/server/handlers/jobs.py` - jobs.list handler
- `python/tests/test_handlers_quacc.py` - 17 comprehensive tests

## Decisions Made
- **Renamed handlers.py to _handlers.py:** Resolved Python naming conflict between module and package. The handlers/ package needs to import from _handlers.py to get the registry.
- **Re-export pattern in __init__.py:** Maintains backwards compatibility - `from crystalmath.server.handlers import HANDLER_REGISTRY` works unchanged.
- **Lazy imports inside handlers:** Each handler imports its dependencies (discover_vasp_recipes, ClusterConfigStore, etc.) inside the function body for graceful degradation and faster startup.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Resolved handlers.py/handlers/ naming conflict**
- **Found during:** Task 1 (Create handlers package)
- **Issue:** Python treats `crystalmath.server.handlers` as either the file OR the package, not both
- **Fix:** Renamed handlers.py to _handlers.py, handlers/__init__.py re-exports registry
- **Files modified:** handlers.py -> _handlers.py, handlers/__init__.py
- **Verification:** `from crystalmath.server.handlers import HANDLER_REGISTRY` works
- **Committed in:** fa258a6 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Structural change required to make Python module system work. No scope creep.

## Issues Encountered
- Test mock paths initially pointed to handler modules instead of source modules - fixed by patching at crystalmath.quacc.* instead of crystalmath.server.handlers.*

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All three RPC handlers registered and tested
- Ready for 02-03 (jobs.submit handler) to add write operations
- Rust TUI can now query recipes, clusters, and jobs via IPC

---
*Phase: 02-quacc-integration*
*Completed: 2026-02-02*
