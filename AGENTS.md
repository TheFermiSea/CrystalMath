# CrystalMath — Canonical Agent Guide

> **This is the single source of truth for agent instructions in this repo.** `CLAUDE.md` and
> `GEMINI.md` are thin pointers to this file; keep guidance here, not there. (`cli/CLAUDE.md`
> holds CLI-module detail only and links up to this file.)

CrystalMath is a monorepo of tools for managing **multi-code DFT calculations** — CRYSTAL23,
VASP, Quantum ESPRESSO, Yambo, and phonopy (see `python/crystalmath/backends/`). It is **not**
CRYSTAL23-only.

## 1. Architecture & Direction (read this first)

**Canonical direction — [ADR-006](docs/architecture/adr-006-unify-on-rust-tui.md) (2026-05-31):**
the project is unifying on a **single Rust/Ratatui TUI** that talks to the Python core over an
**IPC boundary** ([ADR-003](docs/architecture/adr-003-ipc-boundary-design.md)). ADR-006
**supersedes ADR-001 and ADR-002** — the old "Python TUI primary, Rust TUI secondary under a
feature freeze" policy no longer applies.

| Component | Path | Status |
|-----------|------|--------|
| **CLI** (Bash) | `cli/` | ✅ Production. Thin `bin/runcrystal` orchestrator + `lib/` modules. |
| **Rust TUI** (Ratatui) — *primary UI* | `src/` | 🔨 Becoming the single UI; freeze rescinded. May add screens/deps/features. |
| **Python core** (`crystalmath`) — business logic SSOT | `python/` | ✅ Models, API, templates, backends, `crystalmath-server` IPC service. |
| **Python TUI** (Textual) — *deprecated* | `tui/` | ⚠️ Maintenance-only; being phased out per ADR-006. No new features. |

**Rust↔Python boundary:** the IPC service ([ADR-003](docs/architecture/adr-003-ipc-boundary-design.md))
is the target. It is **built but not yet the live transport** — the running TUI still uses PyO3
via `src/bridge.rs`. Cutting over to `src/ipc/client.rs` and deleting PyO3 is the keystone
follow-up. **Do not delete `bridge.rs` or expand it; do not add new PyO3 bindings** — new
boundary work goes through the IPC client/server.

**Workflow backends:** `quacc` (`python/crystalmath/quacc/`) and **AiiDA**
(`python/crystalmath/aiida_plugin/`, `tui/src/aiida/`) are **both supported, co-equal** engines.
Neither is being removed.

**Shared database:** all tools read/write the same `.crystal_tui.db` SQLite file, located via
`find_database_path()` in `src/bridge.rs` (env `CRYSTAL_TUI_DB` wins).

## 2. Build, Test & Lint

### Python workspace (uv)
This is a **uv workspace**; members are `python/` (`crystalmath`) and `tui/` (`crystal-tui`).
Run from the repo root:
```bash
uv sync                       # install core + TUI
uv sync --all-extras          # + dev, aiida, materials extras
uv run pytest                 # all Python tests
uv run --package crystalmath pytest    # core only
uv run --package crystal-tui pytest    # TUI only
uv run black python/ tui/ && uv run ruff check python/ tui/
```
Prefer the workspace commands above over per-package `pip install -e .`.

### Rust TUI
Run from the **repo root** (not `tui/`):
```bash
./scripts/build-tui.sh            # default (PyO3) build with the correct PYO3_PYTHON
./scripts/build-tui.sh --clean    # after a Python version change ("SRE module mismatch")
cargo test                        # ~242 tests
cargo test lsp                    # one module
cargo clippy && cargo fmt --check
./target/release/crystalmath      # run the TUI

# IPC transport (ADR-006 cutover, opt-in until it becomes the default): talks to
# crystalmath-server over a socket, needs NO PYO3_PYTHON. The server is auto-spawned.
cargo build --no-default-features
cargo test  --no-default-features
```
`build-tui.sh` exists because PyO3 must be compiled against the exact runtime Python (the venv
is 3.12; system Python may be 3.14+). Once the IPC cutover lands (ADR-006), this requirement and
the script go away.

### CLI (Bash, ≥4.0)
```bash
cd cli/
bats tests/unit/*.bats                  # ~173 tests total across unit+integration
bats tests/integration/*.bats
bats tests/unit/cry-parallel_test.bats  # single file
bin/runcrystal --explain my_job         # dry-run / educational mode
```

### LSP server (editor diagnostics, optional)
The Rust TUI editor spawns the vendored language server at
`third_party/vasp-language-server/` over JSON-RPC/stdio (it is referred to in code as the
"dft-language-server"). Node is resolved from `CRYSTAL_NODE_PATH` (default `node`). Diagnostics
degrade gracefully if the server is missing. See
[ADR-004](docs/architecture/adr-004-editor-lsp-strategy.md).

## 3. Code Style

- **Commits:** Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`), present tense, small scope.
- **Bash (`cli/`):** 4-space indent; `local` vars, snake_case; `[[ ... ]]`, quote `"${VAR}"`;
  functions return exit codes, the main script owns traps/cleanup; logic lives in `lib/`, not `bin/`.
- **Python (`python/`, `tui/`):** Black **100 columns** (both packages), Ruff (E, F, W, I, N, UP,
  B, A, C4, SIM), MyPy type hints on new code, async-safe (no blocking calls in the event loop).
- **Rust (`src/`):** `cargo fmt` + `cargo clippy` clean; `src/models.rs` must match the Python
  Pydantic models via `serde`; dirty-flag rendering (`app.needs_redraw()`); non-fatal errors via
  `app.set_error()`; LSP/monitor use non-blocking `mpsc` channels.

### Security (non-negotiable)
- Jinja2: `SandboxedEnvironment` only.
- SSH: never disable host-key verification (`known_hosts=None` is forbidden).
- No raw `eval()` — use AST-whitelisted `_safe_eval_condition()` for workflow conditions.
- Escape shell when building SLURM/remote command strings.
- Stub execution requires explicit `metadata["allow_stub_execution"] = True`.

## 4. Issue Tracking (beads / `bd`)

This repo uses **`bd` (beads) backed by a Dolt database** under `.beads/` — **not** the old
`.beads/issues.jsonl` (that file was removed during the Dolt migration; do not recreate or commit
it). `bd` auto-commits to Dolt; you just `git push` your code at session end.

```bash
bd ready                     # available work (start here)
bd list --status=open
bd show <id>
bd create --title="..." --description="..." --type=task --priority=2   # priority 0-4, not high/med/low
bd update <id> --status=in_progress     # claim
bd close <id1> <id2> ...
bd dolt push / bd dolt pull             # sync the Dolt-backed issue DB
```
Use `bd` for task tracking (not TodoWrite or markdown files). **Never run `bd edit`** — it opens
`$EDITOR` and blocks. If `bd` reports "database not initialized," run `bd bootstrap` (or
`bd init --prefix <prefix>`) before relying on it.

## 5. Directory Reference

```text
.
├── cli/        # Bash CLI (bin/ entry, lib/ modules, tests/ .bats)
├── src/        # Rust TUI (primary): app.rs, bridge.rs (PyO3, being retired),
│               #   ipc/ (IPC client — target transport), lsp.rs, monitor.rs,
│               #   prometheus.rs, state/, ui/ (one file per screen)
├── python/     # crystalmath core: api.py, models.py, server/ (IPC service),
│               #   backends/ (crystal, vasp, qe, yambo, phonopy), quacc/,
│               #   aiida_plugin/, integrations/, vasp/, templates/, workflows/
├── tui/        # Python Textual TUI (DEPRECATED): src/core, src/runners, src/tui
├── docs/architecture/   # ADRs (see adr-006 for current direction)
├── .beads/     # Dolt-backed issue DB
└── scripts/    # build-tui.sh
```

## 6. Agent "Do Not" List

1. **Do not** restate policy in `CLAUDE.md`/`GEMINI.md` — edit *this* file; they are stubs.
2. **Do not** add new PyO3 bindings or expand `src/bridge.rs`; route new boundary work through
   the IPC client/server (ADR-003/006).
3. **Do not** add features to the deprecated Python TUI (`tui/`); target the Rust TUI + core.
4. **Do not** bypass `scripts/build-tui.sh` while PyO3 is still the live transport.
5. **Do not** recreate or commit `.beads/issues.jsonl` (beads is Dolt-backed now).
6. **Do not** hardcode machine paths (`/Users/...`); use env vars (`CRY23_ROOT`,
   `CRY_SCRATCH_BASE`, `CRYSTAL_TUI_DB`).
7. **Do not** leave tests broken; update tests when you change behavior, and add deps to the
   correct `pyproject.toml` / `Cargo.toml`.

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
