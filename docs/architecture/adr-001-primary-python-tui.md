# ADR-001: Python Textual as Primary TUI; Rust Ratatui as Secondary

**Status:** Accepted  
**Date:** 2026-01-06  
**Deciders:** Project maintainers

## Context

The repository currently contains three overlapping interfaces:

- Bash CLI (`cli/`)
- Python Textual TUI (`tui/`)
- Rust Ratatui TUI (`src/` with PyO3)

This split causes duplicated logic, unclear ownership, and high maintenance cost. The backend logic (AiiDA integration, pymatgen/ASE, parsers, database access) is Python-heavy, which makes embedding Python into a Rust TUI (via PyO3) fragile and expensive to maintain.

We still value Rust/Ratatui for high-performance monitoring, but the project needs a single **primary** UI path for feature development and user workflows.

## Decision

1. **Python/Textual is the primary TUI** for all user workflows (job creation, configuration, templates, workflows).
2. **Rust/Ratatui is secondary/experimental**, focused on optional monitoring use cases.
3. **No new Rust TUI feature work without a stable IPC boundary.** PyO3 embedding should not expand; Rust should communicate with a Python service over a defined protocol.
4. The **Python core library** becomes the single source of truth for business logic.

## Consequences

### Positive
- Faster iteration on core features (single primary UI stack).
- Eliminates duplicated logic between Rust and Python UIs.
- Keeps Rust UI available for performance-sensitive monitoring without blocking core progress.

### Negative / Tradeoffs
- Rust TUI may lag feature parity until IPC is established.
- Requires clear documentation to avoid user confusion about which UI is primary.

## Implementation Notes

- Update docs to mark Python TUI as primary and Rust TUI as secondary.
- Create and maintain a Rust↔Python IPC contract before expanding Rust features.
- Centralize templates and core logic in Python so both UIs (and CLI) share behavior.

## Follow-ups

- ADR-002 (planned): IPC boundary design for Rust TUI.
- Migration plan for repo layout and core extraction.
