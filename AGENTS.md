# Repository Guidelines

## Project Structure & Module Organization
- CLI (bash) lives in `cli/`: entrypoint `bin/runcrystal`, reusable modules under `lib/`, tests in `tests/`, docs in `docs/`, tutorials in `share/tutorials/`.
- TUI (Python/Textual) lives in `tui/`: sources in `src/crystal_tui/` (tui/ui components, core logic, runners), tests in `tests/`, packaging in `pyproject.toml`, docs in `docs/`.
- Shared assets: root `docs/`, `examples/` for sample calculations, `.beads/` for issue DB.

## Build, Test, and Development Commands
- CLI: `cd cli`; set environment `export CRY23_ROOT=~/CRYSTAL23 CRY_SCRATCH_BASE=~/tmp_crystal`; run a job `bin/runcrystal my_job [ranks]`; dry-run `bin/runcrystal my_job --explain`.
- CLI tests: `bats tests/unit/*.bats`; integration `bats tests/integration/*.bats`.
- TUI setup: `cd tui && pip install -e ".[dev]"`.
- TUI run: `crystal-tui` launches the interface.
- TUI quality: `pytest`; `black src/ tests/`; `ruff check src/ tests/`; `mypy src/`.

## Coding Style & Naming Conventions
- Bash: 4-space indent, lowercase function/file names (`cry_*`), guard against re-sourcing, prefer `local` and defensive `[[ ]]` checks.
- Python: Black/ruff defaults (88 cols), type hints where practical; modules and files snake_case; classes PascalCase; functions/tests snake_case.
- Config: Keep CRYSTAL23 paths in env vars (`CRY23_ROOT`, `CRY_SCRATCH_BASE`, `CRY_ARCH`, `CRY_VERSION`) rather than hardcoding.

## Testing Guidelines
- Mirror feature work with tests in the same tool: `.bats` files under `cli/tests/`; `test_*.py` under `tui/tests/`.
- Prefer fast unit cases; add integration bats for end-to-end CLI paths and pytest integration tests for TUI runners.
- Include fixtures/sample inputs under `tests/` or `examples/` rather than inline strings when sizeable.

## Issue Tracking with bd (beads)
- Use `bd` for ALL tracking; avoid markdown TODOs or parallel lists. Always prefer `--json` for programmatic use.
- Ready work: `bd ready --json`. List issues: `bd list` or `bd list --all`.
- Create: `bd create "Title" -t bug|feature|task -p 0-4 --json`; link discoveries with `--deps discovered-from:<id>`.
- Update/claim: `bd update bd-42 --status in_progress --priority 1 --json`; close: `bd close bd-42 --reason "Completed" --json`.
- Priorities: 0 critical, 1 high, 2 medium (default), 3 low, 4 backlog. Types: bug, feature, task, epic, chore.
- Workflow for agents: check ready → claim → work → create linked discovered-from issues → close with reason → commit code alongside `.beads/issues.jsonl`.
- Auto-sync: bd exports/imports `.beads/issues.jsonl` after changes—commit it with related code.
- MCP: `pip install beads-mcp` and add to MCP config if using Claude/MCP; then use `mcp__beads__*` instead of CLI.
- AI planning docs: store ephemeral plans (PLAN.md, DESIGN.md, etc.) under `history/`; optionally ignore via `history/` in `.gitignore` to keep root clean.

## Commit & Pull Request Guidelines
- Commit messages follow a light Conventional Commits style (e.g., `docs: ...`, `fix: ...`, `feat:`). Use present tense and keep scope small.
- PRs: describe intent and approach, list key commands/tests run (e.g., `bats ...`, `pytest`), call out env requirements, and link related beads/issue IDs when available.
- Include screenshots or brief terminal captures for TUI changes; for CLI changes, include example invocation and expected output snippet.

## Security & Configuration Tips
- Never commit CRYSTAL23 binaries or license files. Keep machine-specific paths and credentials in env vars or ignored configs.
- Scratch handling: ensure `CRY_SCRATCH_BASE` points to a writable location; cleanup is automated but verify on shared systems.
