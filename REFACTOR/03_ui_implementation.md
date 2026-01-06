# UI Implementation: Python Textual (Primary) + Rust Cockpit (Secondary)

This plan reflects the **accepted decision**: Python/Textual is the primary UI for all workflows. The Rust/Ratatui UI is secondary/experimental and must not expand until a stable IPC boundary exists.

## 1. Primary UI: Python/Textual

### Goals
- The TUI is a **view/controller** layer only.
- All business logic lives in `python/crystalmath`.
- `tui/src/` should not contain duplicate orchestration, parsing, or runner logic.

### Requirements
- TUI must import and call `python/crystalmath` APIs.
- TUI does not write to the DB directly unless via the core API.

### Implementation Steps
1. **Install core package in editable mode** from the TUI:
   ```bash
   cd tui
   uv pip install -e ../python
   ```
2. **Replace references to `tui/src/core/**`** with imports from `crystalmath`.
3. **Move orchestration logic** (queue manager, orchestrator, parsing, runners) into the core package.

### Acceptance Criteria
- `tui/` contains UI widgets/screens only.
- All workflows, runners, and parsers are pulled from `python/crystalmath`.
- No new logic added to `tui/src/core`.

## 2. Secondary UI: Rust/Ratatui (Optional)

### Scope
- Monitoring, dashboards, and log viewing.
- Optional editor panel (minimal, no custom LSP implementation).

### Constraints
- **No new PyO3 coupling.** The Rust TUI must consume core functionality via a stable IPC boundary.
- Feature work is blocked until IPC is defined.

### IPC Options (in priority order)
1. Local socket JSON-RPC
2. HTTP API (FastAPI)
3. CLI JSON interface

### Acceptance Criteria
- Rust UI does not embed Python directly for new features.
- IPC contract exists before expanding Rust UI scope.
