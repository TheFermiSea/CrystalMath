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


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:7510c1e2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->

## Static Analysis & Quality Gates
- Check architectural rules: `sg scan`
- Auto-fix code format style regressions: `sg run --pattern 'serde_json::from_str($BUFF)' --rewrite 'serde_json::from_slice($BUFF)' -i`
