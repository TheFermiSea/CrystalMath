# Archived planning & refactor documents

These directories hold **pre-redesign planning artifacts**, archived on 2026-06-05 during the
ADR-007–027 redesign audit. They are kept for provenance only and are **not authoritative**.

- **`planning/`** — the old 6-phase GSD plan (IPC → quacc → structure → workflow → …) that
  predates the ADR-007–027 "adopt the ecosystem" redesign. Superseded by
  [`docs/architecture/REDESIGN.md`](../docs/architecture/REDESIGN.md) and the beads epics.
- **`REFACTOR/`** — the original refactor strategy docs ("Python primary, Rust frozen"). Superseded
  by [ADR-006](../docs/architecture/adr-006-unify-on-rust-tui.md) /
  [ADR-007](../docs/architecture/adr-007-redesign-overview-adopt-ecosystem.md) and the redesign ADRs.

**Authoritative direction** lives in [`AGENTS.md`](../AGENTS.md) and `docs/architecture/` (the ADRs
+ `REDESIGN.md`). **Live status** is tracked in beads (`bd ready` / `bd list`), not in markdown.

> Note: [ADR-013](../docs/architecture/adr-013-multi-code-handoff-and-restart-validation.md) still
> cites `planning/research/PITFALLS.md` (Pitfall #4, restart-file confusion) as a real reference —
> that file is retained here on purpose.
