# Architecture & Migration Strategy: Python Core + Optional Rust Cockpit

## 1. High-Level Architecture

**Primary UI:** Python/Textual (`tui/`)  
**Core Logic:** Python package (`python/crystalmath`)  
**Secondary UI:** Rust/Ratatui (`src/`), optional/experimental

The Python core is the single source of truth for business logic, storage, and DFT workflows. The Rust TUI is optional and should communicate over a stable IPC boundary rather than embedding Python.

```
User
 ├── Python TUI (Textual)  ──> python/crystalmath (core)
 ├── Python CLI            ──> python/crystalmath (core)
 └── Rust TUI (optional)   ──> IPC ──> python/crystalmath (core)
```

## 2. Core Principles

1. **Single Source of Truth:** `python/crystalmath` owns all business logic.
2. **UI as View/Controller:** `tui/` should not contain orchestration logic.
3. **Optional Rust UI:** Rust features must sit behind an IPC boundary.
4. **LSP via Upstream:** Use `dft-language-server` (no custom LSP).

## 3. Current State Assessment

| Component | Status | Notes |
|-----------|--------|-------|
| CLI (Bash) | ✅ Production | To be wrapped by Python CLI |
| Python TUI | ✅ Production | Primary UI |
| Rust TUI | ⚠️ Experimental | Optional, must use IPC |
| Python Core | 🔨 In Progress | Needs to absorb `tui/src/core` |
| AiiDA | ✅ Optional | Must remain optional |

## 4. Target Structure

```
crystalmath/
├── python/                 # Core package (source of truth)
│   └── crystalmath/
├── tui/                    # Primary Textual UI (no core logic)
├── src/                    # Optional Rust UI (IPC only)
├── cli/                    # Legacy bash CLI (thin wrapper target)
└── REFACTOR/               # Migration plans
```

## 5. Migration Phases (High-Level)

1. **Core extraction:** move orchestration, runners, parsers, templates into `python/crystalmath`.
2. **TUI refactor:** update `tui/` to import only from `python/crystalmath`.
3. **CLI refactor:** create Python CLI that wraps core; bash CLI becomes thin wrapper.
4. **Rust IPC:** define IPC contract; keep Rust optional.
5. **AiiDA adapter:** provide SQLite vs AiiDA backend selection.
