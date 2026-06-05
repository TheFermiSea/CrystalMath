# ADR-015: Unified Configuration — pydantic-settings as the Single Resolver

**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** [ADR-005](adr-005-unified-configuration.md)
**Depends on:** [ADR-014](adr-014-ipc-boundary-stdio-jsonrpc-delete-pyo3.md) (one JSON-RPC dispatch table over the IPC stdio boundary)

## Context

The project resolves configuration in at least **three overlapping mechanisms**, plus a bespoke
loader sketched but never ratified by [ADR-005](adr-005-unified-configuration.md):

1. **CLI (Bash)** — `cli/lib/cry-config.sh` reads env vars (`CRY23_ROOT`, `CRY_SCRATCH_BASE`,
   `CRY_VERSION`, `CRY_ARCH`) and an optional `~/.config/cry/cry.conf`.
2. **Python TUI legacy** — the deprecated `tui/` tree sources `cry23.bashrc` via a subprocess to
   extract env vars and hand-builds a `CrystalConfig` dataclass; YAML cluster files are loaded by a
   *separate* `config_loader.py`.
3. **Per-resolver hand-mirroring across the language boundary** — there is no shared config layer
   at all for the two paths that matter most. `python/crystalmath/backends/__init__.py:60`
   (`find_database_path`) carries the comment *"Mirrors the Rust resolver in
   `src/bridge.rs::find_database_path` so the Python CLI/server open the SAME database the Rust TUI
   uses"* — a six-step resolution order duplicated in two languages. The socket path is in the same
   state: `src/ipc/client.rs:164` documents *"This MUST stay in sync with `get_default_socket_path()`
   in"* the Python server. ADR-005 chose dataclasses + `tomllib` and never landed; `pyproject.toml`
   still lists `dependencies = []` and no `config.py` exists.

This hand-mirroring is the root cause of the **socket-path mismatch** that
[ADR-003](adr-003-ipc-boundary-design.md) flags as a known bug: the Rust client historically fell
back to `/tmp/crystalmath.sock` while the Python server falls back to `/tmp/crystalmath-{uid}.sock`
(`python/crystalmath/server/__init__.py:64,79`). Two resolvers that "MUST stay in sync" by hand
are two resolvers that will drift; ADR-003 itself asks for the fix to come "via the ADR-005 config
loader so both sides read one resolved value." The same class of bug lurks in the database path,
scratch dirs (`CRY_SCRATCH_BASE`, NFS-shared vs node-local `/scratch`; see beefcake2's cluster
reality), and `VASP_PP_PATH`.

The Friction catalog (item H1–H3) makes the requirement concrete: a single TOML config across CLI +
Python core + Rust, with documented precedence (env > project > user > defaults), per-code sections,
and **no hardcoded machine paths** (AGENTS.md "Do Not" #6). ADR-005's intent is correct; its
*mechanism* — a hand-rolled dataclass loader with grep-based Bash parsing — reinvents a solved
problem and leaves the precedence/validation logic to be written and tested by hand.

**Ecosystem state of the art.** `pydantic-settings` is the mature, maintained layered configuration
loader for Python. It natively composes a **TOML source** (`TomlConfigSettingsSource`), environment
variables, dotenv, and secrets, with a fully customizable precedence chain via the
`settings_customise_sources` classmethod, and it gives typed defaults + validation for free
(Pydantic Settings docs). Pydantic is already the core's model layer (`models.py`), and ADR-014
makes the Python server the single source of truth that the Rust TUI talks to over JSON-RPC — so
making the **server the single config resolver** and having every other consumer read *resolved*
values is the natural shape, not a new coupling.

## Decision

**Ratify `pydantic-settings` as the single configuration resolver in the Python core. There is
exactly one resolver; the Rust TUI and the Bash CLI never parse TOML independently — they read
resolved values from the Python core.**

### 1. One schema, one resolver: `crystalmath/config.py`

Define the config as `pydantic_settings.BaseSettings` models (one root `CrystalMathSettings`, with
nested `Crystal23Settings`, `VaspSettings`, `QeSettings`, `ClustersSettings`, and a `RuntimeSettings`
section that owns the resolved **socket path**, **database path**, and **scratch base**). Wire the
layered sources explicitly:

```python
class CrystalMathSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CRYSTALMATH_",
        env_nested_delimiter="__",      # CRYSTALMATH_VASP__POTCAR_DIR
        toml_file=[user_toml(), project_toml()],  # later entries win in TomlConfigSettingsSource;
                                                  # toml_file=[user_toml(), project_toml()] yields
                                                  # project TOML overriding user TOML (matching env > project > user)
    )

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings,
                                   env_settings, dotenv_settings, file_secret_settings):
        # Documented precedence: env > project TOML > user TOML > package defaults.
        return (
            env_settings,
            TomlConfigSettingsSource(settings_cls),  # processes toml_file with "later entries win"
            init_settings,                           # in-code defaults
        )
```

- **User TOML:** `${XDG_CONFIG_HOME:-~/.config}/crystalmath/config.toml`.
- **Project TOML:** nearest-ancestor `.crystalmath.toml` (walk up from CWD), mirroring how
  `find_database_path` already finds the project root.
- **Precedence (documented, single source of truth):** environment variables **>** project
  `.crystalmath.toml` **>** user `config.toml` **>** package defaults. This is ADR-005's precedence
  table, now realized by `settings_customise_sources` instead of hand-coded merge logic.
- Legacy aliases (`CRY23_ROOT`, `CRY_SCRATCH_BASE`, `CRYSTAL_TUI_DB`, `VASP_PP_PATH`) are accepted as
  Pydantic field `validation_alias`es so existing environments keep working with **no hardcoded
  paths** (H2) and a clean deprecation path.

### 2. The resolver owns the contested paths (kills the mismatch)

`RuntimeSettings` is the **only** place the socket path, database path, and scratch base are
resolved. The bespoke resolvers (`backends.find_database_path`, `server.get_default_socket_path`,
and the Rust `src/bridge.rs::find_database_path` / `src/ipc/client.rs` fallback) collapse into one
Pydantic computed resolution that picks the **uid-scoped** socket form
(`/tmp/crystalmath-{uid}.sock`) as the unconditional fallback, ending the `/tmp` divergence ADR-003
documents. The Python server resolves these once at startup; both halves of the IPC boundary then
agree by construction rather than by a "MUST stay in sync" comment.

### 3. Rust and Bash read resolved values via a `config --export` shim

Neither non-Python consumer parses TOML:

- **Bash CLI** (`cli/lib/cry-config.sh`) replaces its grep/`cry.conf` logic with
  `eval "$(python3 -m crystalmath config --export-bash)"`, which prints validated, shell-escaped
  `KEY=value` exports (e.g. `CRY23_ROOT=...`, `VASP_PP_PATH=...`, `CRYSTALMATH_SOCKET=...`). A
  minimal grep fallback remains only for the bootstrap case where Python is unavailable.
- **Rust TUI** does **not** read config files at all. It obtains the resolved socket path the same
  way it spawns the server (ADR-014's stdio child handshake), and for any other config it needs it
  calls a single JSON-RPC method on the one dispatch table — `config.get` (returning the resolved
  `RuntimeSettings` and per-code sections as a typed document). The serde↔pydantic contract for that
  document is kept honest by the JSON-Schema codegen ADR-014 mandates, not by hand-mirroring.

`crystalmath config --export` (JSON), `--export-bash` (shell), and `config.get` (JSON-RPC) are three
renderings of the **same** resolved settings object — one resolver, three read paths.

### 4. Migration

Delete `tui/`'s `environment.py`/`config_loader.py` and the `cry23.bashrc`-sourcing subprocess; add
`pydantic-settings` to `pyproject.toml` `dependencies`; replace `find_database_path` and the two
socket-path resolvers with `RuntimeSettings`; rewrite `cry-config.sh` around the `--export-bash`
shim. ADR-005's dataclass `config.py` sketch is superseded by the `BaseSettings` schema above.

## Alternatives Considered

- **Hand-rolled dataclass + `tomllib` loader (ADR-005 as written).** Rejected: it reinvents
  precedence-merging, env-var coercion, and validation that `pydantic-settings` provides and tests
  upstream, and it still leaves Bash to grep TOML directly (ADR-005 §5 Option B). With Pydantic
  already the model layer, a second config object type is pure drift surface. ADR-005's *goals* are
  adopted; only its mechanism is replaced. (Pydantic Settings docs, layered sources via
  `settings_customise_sources`: https://docs.pydantic.dev/latest/concepts/pydantic_settings/)

- **`dynaconf`.** A capable layered settings library (TOML/env/`.env`, environments, validators).
  Rejected because it introduces a *second* schema/validation system alongside Pydantic, which the
  core already standardizes on for every model and for the JSON-RPC wire contract (ADR-014). Using
  `pydantic-settings` lets one schema serve config, the IPC document, and the `--export` shim. (Dynaconf
  docs: https://www.dynaconf.com/)

- **Each language keeps its own resolver, synchronized by tests.** This is the status quo —
  `find_database_path` "Mirrors the Rust resolver" and `client.rs` "MUST stay in sync." Rejected on
  the evidence: the socket-path mismatch (ADR-003) is exactly what hand-synchronized resolvers
  produce. A single resolver in the source-of-truth process (ADR-006/014) is the only structural
  fix; tests catch drift after it ships, not before.

- **Rust-side config crate (`config-rs`/`figment`) as the authority.** Rejected: it inverts ADR-006,
  which makes the Python core — not the Rust TUI — the single source of truth for all business
  logic. The TUI "holds UI state and rendering only." Config resolution (paths, per-code env, cluster
  profiles) is core logic the server already needs at startup, so the resolver belongs there. (Ratatui
  TEA pattern / ADR-006 decision 5.)

- **TOML-only, no env layer.** Rejected: CI/container overrides and the existing `CRY*` env vars are
  hard requirements (H1 precedence table, H2 no-hardcoded-paths), and beefcake2's HPC reality drives
  scratch/POTCAR paths from the environment. `pydantic-settings` gives the env layer with documented
  precedence for free.

## Consequences

### Positive

- **The socket-path mismatch is fixed structurally** — one resolver picks the uid-scoped path; the
  Rust/Python fallback divergence (ADR-003 ⚠️) cannot recur.
- **Three config mechanisms collapse to one**; the Bash `cry.conf`, the `cry23.bashrc` subprocess
  sourcing, and the YAML cluster loader are replaced by layered TOML + env through one schema.
- **No hand-mirrored resolvers** — `find_database_path`'s "Mirrors the Rust resolver" comment and
  `client.rs`'s "MUST stay in sync" comment both go away.
- **Validation + typed defaults for free**, and one schema serves the server, the CLI shim, and the
  `config.get` IPC document.
- Directly realizes ADR-005's intent (unified TOML, documented precedence, per-code sections,
  no hardcoded paths) with a maintained library instead of bespoke code.

### Negative / Tradeoffs

- **Python becomes the config authority the Bash CLI depends on.** The `--export-bash` shim is now on
  the CLI's critical path; a grep fallback covers the Python-absent bootstrap only.
- A new runtime dependency (`pydantic-settings`) is added to the core wheel.
- Env-var naming must be standardized (`CRYSTALMATH_*` with `__` nesting) and legacy `CRY*` names
  carried as documented aliases during transition.

### Migration impact

- `pyproject.toml`: add `pydantic-settings`; create `crystalmath/config.py`.
- Delete `tui/environment.py`, `tui/config_loader.py` (already deprecated by ADR-006).
- Replace `backends.find_database_path`, `server.get_default_socket_path`, and the Rust
  `find_database_path`/socket fallbacks with reads of `RuntimeSettings` (Rust via the IPC handshake +
  `config.get`).
- Rewrite `cli/lib/cry-config.sh` around `python3 -m crystalmath config --export-bash`; add `bats`
  coverage for the export contract.
- Add a `config.get` method to the single JSON-RPC dispatch table (ADR-014) and the serde type to the
  codegen set so the wire contract cannot drift.

## References

- Pydantic Settings documentation — layered sources (`TomlConfigSettingsSource`, env, dotenv,
  secrets) with customizable precedence via `settings_customise_sources`:
  https://docs.pydantic.dev/latest/concepts/pydantic_settings/
- [ADR-003](adr-003-ipc-boundary-design.md) — IPC boundary; documents the socket-path fallback
  mismatch this ADR resolves (`src/ipc/client.rs:164`, `server/__init__.py:64`).
- [ADR-005](adr-005-unified-configuration.md) — Unified configuration (superseded): goals adopted,
  dataclass/`tomllib` mechanism replaced.
- [ADR-006](adr-006-unify-on-rust-tui.md) — Single Rust TUI over IPC; establishes the Python core as
  the single source of truth and the TUI as UI-state-only.
- [ADR-014](adr-014-ipc-boundary-stdio-jsonrpc-delete-pyo3.md) — One JSON-RPC dispatch table over the
  stdio IPC boundary; provides the `config.get` method and the JSON-Schema codegen that keeps the
  resolved-config wire contract in serde↔pydantic parity.
- Codebase evidence: `python/crystalmath/backends/__init__.py:60` (`find_database_path`, "Mirrors the
  Rust resolver"); `src/ipc/client.rs:160-164` ("MUST stay in sync"); `python/crystalmath/server/
  __init__.py:62-79` (socket fallback `/tmp/crystalmath-{uid}.sock`); `pyproject.toml:24`
  (`dependencies = []`); Friction catalog H1–H3 (three config mechanisms, no-hardcoded-paths rule).
