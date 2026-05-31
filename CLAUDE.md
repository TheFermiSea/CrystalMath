# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Canonical instructions live in [`AGENTS.md`](AGENTS.md).** To prevent the documentation drift
> that previously accumulated across multiple instruction files, this repo keeps a single source
> of truth. **Read [`AGENTS.md`](AGENTS.md)** for architecture, build/test/lint commands, code
> style, security rules, the beads (Dolt) workflow, and the project's current direction.

Quick orientation (full detail in `AGENTS.md`):

- **Direction:** Per [ADR-006](docs/architecture/adr-006-unify-on-rust-tui.md), the project is
  unifying on the **Rust/Ratatui TUI** (`src/`) over an IPC backend; the Python/Textual TUI
  (`tui/`) is **deprecated**. ADR-006 supersedes ADR-001/002 (the old "Python primary, Rust
  frozen" policy is no longer in effect).
- **Core logic** lives in the Python package `crystalmath` (`python/`), exposed over IPC by
  `crystalmath-server`. The live Rust↔Python transport is still PyO3 (`src/bridge.rs`); cutting
  over to `src/ipc/client.rs` is the keystone follow-up — do not expand PyO3.
- **Build the Rust TUI** from the repo root with `./scripts/build-tui.sh` (required while PyO3 is
  live). **Python:** `uv sync` then `uv run pytest`. **CLI:** `bats` in `cli/`.
- **Issues:** `bd` (beads), backed by Dolt under `.beads/` — not `issues.jsonl`.
- **Project status** is tracked in beads (`bd ready` / `bd list`), not in a table here, so it
  cannot go stale.
