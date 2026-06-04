# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the
codebase. This repo is **single-context**: one `CONTEXT.md` at the root, with ADRs in
`docs/architecture/`.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — the project's domain glossary.
- **`docs/architecture/`** — read the ADRs (`adr-NNN-*.md`) that touch the area you're about to
  work in. **This repo keeps ADRs in `docs/architecture/`, NOT `docs/adr/`.**
- **[`AGENTS.md`](../../AGENTS.md)** — the canonical agent guide (architecture, build/test/lint,
  security rules, the beads workflow, current direction). Treat it as authoritative over docstrings
  and older docs when they disagree.

If `CONTEXT.md` doesn't exist yet, **proceed silently**. Don't flag its absence or suggest creating
it upfront — the producer skills (`/grill-with-docs`, `/improve-codebase-architecture`) create and
extend it lazily when terms or decisions actually get resolved.

## File structure (single-context)

```
/
├── AGENTS.md                  ← canonical agent guide (CLAUDE.md / GEMINI.md point here)
├── CONTEXT.md                 ← domain glossary (created lazily)
├── docs/architecture/         ← ADRs (adr-001 … adr-006, …) + design docs
└── src/  python/  cli/  tui/  ← Rust TUI, Python core, Bash CLI, deprecated Textual TUI
```

## Use the glossary's vocabulary

When your output names a domain concept (an issue title, a refactor proposal, a hypothesis, a test
name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language
the project doesn't use (reconsider), or there's a real gap (note it for `/grill-with-docs`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-006 (unify on the Rust/Ratatui TUI) — but worth reopening because…_
