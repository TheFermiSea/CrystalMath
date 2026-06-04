# Issue tracker: Beads (`bd`)

Issues and PRDs for this repo live in **beads** (`bd`), a Dolt-backed issue tracker under
`.beads/`. This is the canonical tracker per [`AGENTS.md`](../../AGENTS.md) §4 — do **NOT** use
GitHub Issues, `TodoWrite`, or markdown TODO files for task tracking. Use the `bd` CLI for all
operations.

## Conventions

- **Create an issue**:
  `bd create --title "..." --description "..." --type=task|bug|feature --priority=2`
  Priority is `0`–`4` / `P0`–`P4` (0 = critical) — **not** high/med/low. Add `--acceptance "..."`
  for acceptance criteria and `--labels a,b` for labels.
- **Read an issue**: `bd show <id>` (description, dependencies, blocks / blocked-by).
- **List / find work**: `bd ready` (unblocked work — start here), `bd list --status=open`,
  `bd list --status=in_progress`, `bd search <query>`.
- **Claim / update**: `bd update <id> --claim` (or `--status=in_progress`);
  `bd update <id> --notes "..." | --design "..." | --title "..." | --description "..."`.
  Do **not** use `bd edit` — it opens `$EDITOR` and blocks agents.
- **Labels**: `bd label add <id> <label>` / `bd label list <id>`. See
  [`triage-labels.md`](./triage-labels.md).
- **Dependencies**: `bd dep add <issue> <depends-on>` (issue depends on depends-on);
  `bd blocked` lists blocked issues.
- **Close**: `bd close <id> --reason "..."` (close several at once: `bd close <id1> <id2> ...`).
- **Persistent knowledge**: `bd remember "insight"` / `bd memories <keyword>` — not `MEMORY.md`.

`bd` auto-commits issue state to its Dolt DB; commit and `git push` your **code** at session end
(the issue DB syncs via `refs/dolt/data` / `bd dolt push`). Do not hand-edit or commit
`.beads/issues.jsonl` — it is a passive export.

## When a skill says "publish to the issue tracker"

Run `bd create ...` with `--description`, and (where relevant) `--acceptance`, `--type`, `--priority`.

## When a skill says "fetch the relevant ticket"

Run `bd show <id>`.

## When a skill says "apply the `<role>` triage label"

Run `bd label add <id> <label>` using the mapping in [`triage-labels.md`](./triage-labels.md).
