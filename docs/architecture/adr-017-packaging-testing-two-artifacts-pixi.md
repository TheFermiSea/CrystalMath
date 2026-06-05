# ADR-017: Packaging & Testing — Two Decoupled Artifacts, pixi for HPC, an Extras-Matrix CI

**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** none
**Depends on:** [ADR-014](adr-014-ipc-boundary-stdio-jsonrpc-delete-pyo3.md) (deletes PyO3, decoupling the Rust and Python builds), [ADR-012](adr-012-hpc-execution-jobflow-remote-aiida-optional.md) (jobflow-remote default / AiiDA optional, which fixes the heavy conda-forge dependency footprint this ADR must package)

## Context

With [ADR-014](adr-014-ipc-boundary-stdio-jsonrpc-delete-pyo3.md) deleting PyO3 and making the
Rust↔Python boundary a spawned-child JSON-RPC stream, the single largest packaging constraint in
the repo disappears, and the build *should* now split cleanly into two artifacts. It does not yet.
Today the Rust and Python builds are still entangled, the optional-dependency surface is large and
silently degrades, and a deprecated package is a load-bearing build dependency. The friction is
concrete:

1. **PyO3 build coupling (about to be removed, must not be re-introduced).** The current Rust build
   embeds CPython via `src/bridge.rs` and requires the `PYO3_PYTHON` dance in `scripts/build-tui.sh`
   (`AGENTS.md`), so every Rust CI job and every contributor needs a matching Python venv. ADR-014
   removes the cause; this ADR must lock in the *packaging* consequence — two independent artifacts —
   so the coupling cannot creep back via a "convenient" single wheel.

2. **A deprecated package is a load-bearing build dependency.** `python/crystalmath/_vendor/` is, by
   its own docstring (`python/crystalmath/_vendor/__init__.py`), a **copy-by-fork** of the
   deprecated `tui/src/` "pure-backend transitive closure" — 33 files including
   `_vendor/core/database.py` (~1,452 LOC), `connection_manager.py`, `slurm_runner.py` (1,758 LOC),
   and the `materials_api/` client — that "must NOT be hand-edited" and whose only update path is to
   re-vendor from a package ADR-006 declares dead. So the "single source of truth" Python core
   depends on frozen copies of deprecated code (Friction catalog §5; Requirement G5). The two build
   backends also fight: `tui/pyproject.toml` is `setuptools.build_meta` while `python/pyproject.toml`
   is `hatchling.build`, fragmenting the build and test config.

3. **A large, silently-degrading extras matrix.** `python/pyproject.toml` defines extras
   `vasp`, `aiida`, `quacc`, `atomate2`, `llm`, `dev` (plus `all`). The code turns missing extras
   into runtime no-ops rather than test failures — `quacc/engines.py` swallows `ImportError → None`,
   `backends/__init__.py` makes AiiDA optional, `integrations/jobflow_store.py` makes maggma
   optional. The effective test matrix is `{store} × {engine} × {transport}`, but `skipif` means an
   optional code path can be *untested in every CI cell* — the survey literature flags exactly this
   as the dominant testing gap in scientific software (Burrell et al. 2018). `AGENTS.md` already
   needs `uv sync --all-extras` plus per-package `pytest` invocations to cover it (Requirement K1).

4. **License-gated assets block IO testing.** VASP POTCAR pseudopotentials may **not** be
   redistributed under the VASP license (pymatgen Installation docs), and pymatgen reads them from
   `PMG_VASP_PSP_DIR` / ASE from `VASP_PP_PATH`. The deck/staging layer
   (`python/crystalmath/decks/__init__.py` raises `DeckStagingError` when POTCARs are missing;
   `quacc/potcar.py` assembles them) is the most bug-prone seam, yet `test_decks.py` /
   `test_vasp_generator.py` cannot exercise real POTCAR assembly in public CI.

5. **uv cannot install the heavy science stack.** The redesign's defaults — pymatgen/ase
   ([ADR-008](adr-008-structure-and-deck-io-on-ase-pymatgen.md)), jobflow/maggma
   ([ADR-010](adr-010-single-result-store-jobflow-maggma.md),
   [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md)), and optional AiiDA
   ([ADR-012](adr-012-hpc-execution-jobflow-remote-aiida-optional.md)) — pull native libraries
   (HDF5, GDAL) and AiiDA needs PostgreSQL. uv installs Python packages only; it cannot provision
   those system libraries, where PyPI wheels are fragile and conda-forge is robust.

**Ecosystem state of the art.** Scientific Python distributes through two stacks: PyPI/pip+wheels
(lightweight, Python-only) and conda-forge (native deps), with **pixi** (Fischer et al. 2025,
arXiv:2511.04827) the modern Rust-based front-end that resolves conda-forge *and* PyPI into one
cross-platform lockfile and adds a task runner. For Rust+Python, **maturin** is the de-facto build
backend, but its own User Guide *discourages shipping a binary and a library in one wheel* and its
`bin` mode is auto-selected only when there is no PyO3/cdylib target. The decoupling ADR-014 enables
is therefore the precondition for the mature pattern: ship the CLI/binary separately from the
library. Trusted publishing via OIDC (cibuildwheel/PyPA) removes long-lived release tokens.

## Decision

Adopt a **two-artifact, two-audience** packaging model and a **reality-reflecting** test matrix.

### 1. Two decoupled artifacts (do NOT fuse them)

- **Rust TUI → standalone binary.** Ship `crystalmath-tui` via **cargo-dist** as GitHub Release
  assets (Linux + macOS, x86_64 + arm64), plus a **Homebrew tap** and a **conda-forge feedstock**
  for the HPC story. The binary depends on nothing Python at *build* time (ADR-014 deleted PyO3) and
  spawns `crystalmath-server` as a child over stdio JSON-RPC at *run* time; versions are negotiated
  at the handshake.
- **Python core → pure-Python wheel.** Ship `crystalmath` to PyPI built with **hatchling**
  (already the backend in `python/pyproject.toml`). Pure-Python means **no** manylinux/cibuildwheel
  matrix, no `PYO3_PYTHON`, no embedded interpreter.
- **Reject the single fused wheel (maturin `bin`/PyO3).** maturin's docs discourage binary+library
  wheels and its `bin` mode is incompatible with a co-located PyO3 target; fusing would re-introduce
  exactly the coupling ADR-014 removed and force users to install Python merely to launch a UI.
  Keep maturin in reserve *only* for a future, separate Rust-accelerated extension crate on a Python
  hot path — never for the TUI.

### 2. Delete `tui/` and `_vendor/`

Per ADR-006 the Textual `tui/` is dead; its `setuptools` backend fragments the build. **Promote**
the genuinely-needed vendored modules into first-class `crystalmath` packages (e.g. the SSH/SLURM
transport that survives ADR-012, the SQLite layer that survives until ADR-010's store lands) and
**delete** what duplicates ecosystem libraries (the `_vendor/core/materials_api/` client re-wraps
`mp_api`/OPTIMADE that pymatgen/quacc already pull in). Then remove `tui/` and `_vendor/` together,
leaving **one** build backend (hatchling) and **one** lockfile story. This also retires the
`crystal-tui` workspace member from the root `pyproject.toml`.

### 3. Two supported environments for two audiences

- **Lightweight user (`pip install crystalmath` + download the binary):** keep the **uv** workspace
  and standard `pyproject.toml` for the "just the TUI + CRYSTAL23/QE" user. uv stays the core's
  dev/CI driver and fast resolver.
- **Developer / HPC user (`pixi install`):** adopt **pixi** as the canonical environment. A
  `pixi.toml` / `pixi.lock` pulls `aiida-core`, `pymatgen`, `ase`, `quacc`, `atomate2`, and the
  native deps (HDF5, PostgreSQL/`psycopg`) from **conda-forge**, with in-repo `crystalmath` as an
  editable PyPI dep (pixi uses uv internally for the PyPI half). Model the optional extras
  (`vasp`/`aiida`/`quacc`/`atomate2`) as **pixi features/environments**, and replace the ad-hoc
  shell scripts (`scripts/build-tui.sh`, `init-dev-session.sh`) with **pixi tasks**. One
  cross-platform lockfile gives bit-reproducible envs across the macOS-arm dev box and Linux HPC.

### 4. Make testing reflect reality

- **Extras matrix (pytest + CI).** Add a CI job that runs the suite under
  `{core-only, +vasp, +aiida, +quacc, +atomate2, all}` so every `skipif` seam is exercised in at
  least one cell instead of silently skipped everywhere. Implement as a GitHub Actions matrix that
  installs each pixi feature/environment, plus Python `3.10/3.11/3.12` on `ubuntu` + `macOS`.
- **Synthetic-POTCAR fixtures.** Ship tiny **dummy** pseudopotential files under a temporary
  `PMG_VASP_PSP_DIR` / `VASP_PP_PATH` (a pytest fixture) so `test_decks.py` /
  `test_vasp_generator.py` exercise the full deck/staging/POTCAR-assembly path **without
  redistributing VASP-licensed POTCARs**. Mark the handful of tests that need *real* POTCARs (or
  full CRYSTAL/VASP runs) and gate them behind a secret-guarded / self-hosted runner; they never
  live in public CI.
- **Trusted publishing.** Release the Python wheel via PyPI **trusted publishing (OIDC)** — no
  long-lived tokens — and the Rust binary via **cargo-dist**. Two independent release pipelines.

## Alternatives Considered

- **maturin single fused wheel (PyO3 cdylib or `bin` mode).** One `pip install`, abi3 stable-ABI
  wheels, zig cross-compilation. *Why not:* maturin's own User Guide recommends against shipping a
  binary and a library in one wheel (doubles wheel size) and `bin` mode is auto-selected only when
  there is **no** PyO3/cdylib target, so a TUI binary + bridge do not combine; more fundamentally it
  perpetuates the embedded-interpreter coupling ADR-014 exists to remove and forces Python on users
  who only want the UI. (maturin User Guide — Bindings, https://www.maturin.rs/bindings.html.)

- **uv / pip wheels for everything, no pixi.** Already in place, single tool, fastest pure-Python
  resolver — correct for the lightweight core. *Why not as the whole answer:* uv cannot install
  non-Python system libraries (HDF5/GDAL) and "has a hard time" with the pymatgen/aiida native
  stacks, and AiiDA additionally needs PostgreSQL that uv cannot provision (pydevtools, "uv vs pixi
  vs conda"; Astral uv workspaces docs). It is necessary but insufficient; pair it with pixi for the
  heavy/HPC path. (https://pydevtools.com/handbook/explanation/uv-vs-pixi-vs-conda-for-scientific-python/;
  https://docs.astral.sh/uv/concepts/workspaces/.)

- **conda/mamba directly (no pixi).** Robust conda-forge native-dep handling, the traditional HPC
  answer. *Why not:* no per-project cross-platform lockfile, no PyPI+conda unification in one
  manifest, no built-in task runner, and roughly an order of magnitude slower solves; pixi (built on
  rattler/uv) supersedes it for exactly the aiida/pymatgen/HDF5/PostgreSQL case while resolving
  conda-forge **and** PyPI in one lockfile (Fischer et al. 2025, arXiv:2511.04827; the ROOT
  experience report independently documents the conda-vs-PyPI packaging tension for complex
  multi-language scientific software, Padulano & Rembser 2025, DOI:10.1051/epjconf/202533701096).

- **Ship real POTCARs / run full DFT in public CI.** Maximal fidelity. *Why not:* VASP
  pseudopotentials may not be redistributed under the VASP license (pymatgen Installation docs), and
  real CRYSTAL/VASP runs cannot live in public CI; synthetic fixtures test the bug-prone IO layer
  legally, with real-asset tests gated behind protected runners.
  (https://pymatgen.org/installation.html.)

- **Keep `skipif` everywhere, no extras matrix.** Cheapest CI. *Why not:* optional code is then
  untested in every cell — the documented failure mode for scientific software (Burrell et al. 2018,
  arXiv:1901.00143). An extras matrix is the minimum that proves the integration seams.

## Consequences

### Positive


- Removes the worst packaging pain: no `PYO3_PYTHON`, no embedded interpreter, no Python venv in
  every Rust CI job; each side builds/tests/releases on its own cadence and platform matrix.
- A genuinely standalone, distributable Rust binary (the headline goal of ADR-006/ADR-014).
- One build backend (hatchling), one lockfile story; `tui/`+`_vendor/` deletion ends the
  re-vendoring workflow and the deprecated-but-load-bearing dependency.
- HPC/dev users get a robust, reproducible env (`pixi install`) for the aiida/HDF5/PostgreSQL stack;
  lightweight users keep a one-line `pip install`.
- CI proves the optional seams (extras matrix) and the POTCAR IO layer (synthetic fixtures) instead
  of silently skipping them; OIDC publishing removes release-token risk.

### Negative / Tradeoffs


- **Two release pipelines** (cargo-dist + trusted-publish) instead of one, with a versioned IPC
  contract and version-skew handling needed at the handshake (ADR-014).
- **Two onboarding paths** (binary + Python env, or pixi) — installer docs matter more.
- A **second environment tool** (pixi alongside uv), and conda-forge can lag PyPI for fast-moving
  packages; multi-platform lock solves churn.
- Faithful **synthetic-POTCAR fixtures** take care to build; **more CI minutes** from matrix fan-out
  (mitigated by the existing path filters).

### Migration impact


1. Land ADR-014 (PyO3 deleted) — the precondition.
2. Add `cargo-dist` config + a Homebrew tap; verify a standalone binary builds with no Python.
3. Promote the needed `_vendor/` modules into `crystalmath`; delete duplicative `materials_api`;
   delete `tui/` and `_vendor/`; drop `crystal-tui` from the workspace; standardize on hatchling.
4. Add `pixi.toml`/`pixi.lock` with features for `vasp/aiida/quacc/atomate2`; port shell scripts to
   pixi tasks.
5. Add the pytest extras-matrix CI job, the synthetic-POTCAR fixture, and Python 3.10–3.12 ×
   ubuntu/macOS; switch the wheel release to PyPI trusted publishing.

## References

- T. Fischer, W. Vollprecht, B. Zalmstra, et al., "Pixi: Unified Software Development and
  Distribution for Robotics and AI," 2025, arXiv:2511.04827.
- maturin User Guide — Bindings (`pyo3`/`bin`/`cffi`/`uniffi`; recommendation against shipping a
  binary and a library in one wheel), https://www.maturin.rs/bindings.html; Distribution
  (manylinux, abi3, zig), https://www.maturin.rs/distribution.html.
- pymatgen Installation docs — POTCAR / `PMG_VASP_PSP_DIR` setup and the VASP-license restriction
  on redistributing pseudopotentials, https://pymatgen.org/installation.html.
- A. G. Burrell, A. Halford, J. Klenzing, et al., "Snakes on a Spaceship—An Overview of Python in
  Heliophysics," JGR Space Physics, 2018, arXiv:1901.00143 (under-testing of scientific software).
- V. Padulano and J. Rembser, "pip install ROOT: Experiences making a complex multilanguage package
  accessible for Python users," EPJ Web Conf. 337:01096, 2025, DOI:10.1051/epjconf/202533701096.
- S. P. Huber et al., "AiiDA 1.0, a scalable computational infrastructure for automated reproducible
  workflows and data provenance," Scientific Data 7:300, 2020, DOI:10.1038/s41597-020-00638-4
  (PostgreSQL footprint motivating pixi/conda-forge for the optional backend).
- pypa/cibuildwheel — multi-platform wheel matrix and PyPI trusted publishing (OIDC),
  https://cibuildwheel.pypa.io/.
- pydevtools, "uv vs pixi vs conda for Scientific Python" (pixi resolves conda-forge+PyPI in one
  lockfile; uv cannot install native libs),
  https://pydevtools.com/handbook/explanation/uv-vs-pixi-vs-conda-for-scientific-python/.
- Astral uv — workspaces concept (current CrystalMath layout),
  https://docs.astral.sh/uv/concepts/workspaces/.
