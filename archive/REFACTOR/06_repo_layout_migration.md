# Repository Layout Migration Plan (Python Core First)

This plan defines the target layout and an incremental migration path that
minimizes breakage while consolidating logic into `python/crystalmath`.

## 1. Target Structure (Phase 1)

```
crystalmath/
├── python/                  # Core package (source of truth)
│   └── crystalmath/
├── tui/                     # Primary Textual UI (no core logic)
├── src/                     # Optional Rust UI (IPC only)
├── cli/                     # Legacy bash CLI (thin wrapper target)
├── templates/               # Shared templates (migrated later)
└── REFACTOR/                # Migration docs
```

## 2. Path Mapping (Current -> Target)

| Current path | Target path | Notes |
|---|---|---|
| `tui/src/core/*` | `python/crystalmath/*` | Move logic (runners, db, parsers, workflows) |
| `tui/src/tui/*` | `tui/src/tui/*` | UI-only; keep, but refactor imports |
| `tui/templates/*` | `templates/*` | Shared templates (post-core) |
| `cli/*` | `cli/*` | Keep; later wrap python core |
| `src/*` | `src/*` | Rust UI remains optional; no new features |

## 3. Migration Phases (Ordered)

### Phase A: Core Extraction (Blocking)
1. Create or move modules into `python/crystalmath/`:
   - `tui/src/core/database.py` -> `python/crystalmath/db/`
   - `tui/src/core/orchestrator.py` -> `python/crystalmath/workflows/`
   - `tui/src/core/queue_manager.py` -> `python/crystalmath/scheduling/`
   - `tui/src/core/runners/*` -> `python/crystalmath/runners/`
2. Ensure core APIs return native objects (Pydantic models, dicts).
3. Add `python/crystalmath/rust_bridge.py` for JSON adapters.

### Phase B: TUI Refactor (Primary UI)
1. Update `tui/pyproject.toml` to depend on `../python` (editable).
2. Replace imports in `tui/src/` to use `crystalmath.*`.
3. Remove or stub `tui/src/core` to avoid drift.

### Phase C: Template Consolidation
1. Move templates into `templates/`.
2. Update both CLI and Python TUI to load from the shared path.

### Phase D: CLI Consolidation
1. Add a Python CLI wrapper (`python -m crystalmath.cli`).
2. Make bash CLI a thin wrapper calling the Python core.

### Phase E: Rust UI (Optional)
1. Define IPC boundary.
2. Replace PyO3 usage with IPC calls.
3. Keep Rust UI focused on monitoring.

## 4. Compatibility Shims

To avoid breaking users:
- Keep `cli/` operational with existing flags during migration.
- Provide a temporary import shim in `tui/src/core` that forwards to
  `python/crystalmath` where needed.

## 5. Success Criteria

- Python TUI imports only `crystalmath.*` for logic.
- Core logic lives only in `python/crystalmath`.
- Rust UI does not expand without IPC.
- Templates are shared between CLI and TUI.
