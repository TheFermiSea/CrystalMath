# Technology Stack

**Project:** VASP TUI with AiiDA/atomate2 Backend
**Researched:** 2026-02-02
**Overall Confidence:** MEDIUM-HIGH

## Executive Summary

This stack recommendation is for a Rust TUI frontend interfacing with a Python backend for VASP job submission to SLURM clusters. The architecture uses PyO3 for Rust-Python FFI with JSON-RPC over the bridge, leveraging atomate2 for VASP input generation and AiiDA for workflow orchestration.

The key design principle: **Python owns workflow complexity, Rust owns UI performance.**

---

## Recommended Stack

### Rust TUI Framework

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| ratatui | 0.30 | TUI rendering framework | Only mature Rust TUI framework with active development. v0.30 adds modular workspace for faster compilation. 60fps rendering with zero-cost abstractions. | HIGH |
| crossterm | 0.28 | Terminal backend | Default ratatui backend, cross-platform (macOS/Linux), works in tmux/screen. Handles raw mode, keyboard, mouse. | HIGH |
| tokio | 1.49 | Async runtime | Required for async FFI operations, file I/O, and potential SSH monitoring. Full features needed for background tasks. | HIGH |
| tui-textarea | 0.7 | Editor widget | Only mature multi-line text editor for ratatui. Supports syntax highlighting hooks, line numbers, search. | HIGH |

### Rust-Python FFI

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| PyO3 | 0.28 | Rust-Python bindings | De facto standard, no real alternatives. v0.28 adds Python 3.14 support and free-threaded Python compatibility. Requires exact Python version match at build time. | HIGH |
| serde | 1.0 | JSON serialization | Bridge uses JSON strings over FFI for type safety. Serde is standard for Rust JSON handling. | HIGH |
| serde_json | 1.0 | JSON parsing | Required for JSON-RPC request/response parsing across bridge. | HIGH |

**Critical Note:** PyO3 must be compiled against the exact same Python version used at runtime. Use `./scripts/build-tui.sh` or set `PYO3_PYTHON` explicitly. Python 3.12 recommended for stability.

### Python Backend - Core

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| Python | 3.12 | Runtime | Sweet spot: modern features, wide library support, stable. Avoid 3.14 (too new for scientific stack). | HIGH |
| Pydantic | >=2.0 | Data validation | atomate2 schemas are Pydantic models. Type-safe validation for VASP inputs and API contracts. | HIGH |
| pymatgen | 2025.10+ | Structure handling | Materials Project standard. Powers atomate2 input sets. Handles CIF, POSCAR, structure manipulation. | HIGH |

### Python Backend - Workflow Orchestration

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| atomate2 | 0.0.23 | VASP input generation | Materials Project standard for VASP workflows. Pydantic-based input sets, custodian error handling. Actively developed. | HIGH |
| jobflow | 0.3.0 | Workflow definition | atomate2's workflow language. Defines Jobs and Flows with dynamic composition. | HIGH |
| jobflow-remote | 1.0.0 | Remote execution | Recommended for HPC. Orchestrates jobflow on SLURM clusters. Handles file staging, queue monitoring. | MEDIUM |

**OR** (alternative orchestration path):

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| aiida-core | 2.7.3 | Workflow engine | Superior provenance tracking. Full computational graph stored in PostgreSQL. Live monitoring (new in 2026). | HIGH |
| aiida-vasp | 5.0.0 | VASP plugin | Mature plugin with InputGenerator, POTCAR management, convergence workflows. Major v5 overhaul. | MEDIUM |

### Python Backend - Supporting Libraries

| Library | Version | Purpose | When to Use | Confidence |
|---------|---------|---------|-------------|------------|
| ASE | 3.27 | Atomic structures | Atoms object, calculators, visualization. Use alongside pymatgen for simulation setup. | HIGH |
| custodian | latest | Error recovery | atomate2 uses internally. Handles VASP crashes, restarts, corrections. | HIGH |
| asyncssh | 2.14+ | SSH connections | Remote cluster access. TUI already uses this for SSH runner. | HIGH |
| aiosqlite | 0.20+ | Async SQLite | Local job/cache database. Already used in TUI. | HIGH |

---

## Architecture Decision: atomate2 vs AiiDA

**Recommendation: Use atomate2 + jobflow-remote as primary, with AiiDA as optional integration.**

### Why atomate2 Primary

1. **Lower barrier to entry**: No PostgreSQL/RabbitMQ infrastructure required
2. **Pydantic-native**: Input sets are Pydantic models, natural fit for typed Rust bridge
3. **Materials Project alignment**: Same defaults, compatible with MP database
4. **Active development**: School held March 2025, continuous workflow additions

### When to Add AiiDA

1. **Provenance requirements**: Legal/publication need for full audit trail
2. **Institutional infrastructure**: Group already runs AiiDA daemon
3. **Multi-code workflows**: AiiDA excels at VASP -> QE -> CP2K chains
4. **Live monitoring**: AiiDA 2.7+ can check running calculations mid-flight

### Integration Strategy

```
User creates job in TUI
         |
         v
  atomate2 InputSet (Pydantic model)
         |
         +---> jobflow-remote (simple HPC)
         |
         +---> AiiDA (provenance tracking, if enabled)
                  |
                  v
              PostgreSQL (full audit trail)
```

---

## Alternatives Considered

### TUI Framework

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| TUI Framework | ratatui | cursive, tuirealm | ratatui dominates ecosystem, better docs, more widgets |
| Terminal Backend | crossterm | termion, termwiz | crossterm is default, best Windows support if needed |
| Editor Widget | tui-textarea | custom | tui-textarea is battle-tested, supports search/highlighting |

### Rust-Python Bridge

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| FFI | PyO3 | rust-cpython | rust-cpython unmaintained, developers recommend PyO3 |
| IPC | JSON over PyO3 | Unix sockets | Sockets add complexity, JSON-RPC over PyO3 works well |
| Protocol | JSON-RPC 2.0 | Custom | JSON-RPC is standard, supports batching, error codes |

### Workflow Orchestration

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Input Generation | atomate2 | raw pymatgen | atomate2 wraps pymatgen with custodian, error handling |
| Job Execution | jobflow-remote | FireWorks | FireWorks older, jobflow-remote is modern successor |
| Provenance | optional AiiDA | atomate2 only | AiiDA overkill for simple submissions, add when needed |

### Structure Libraries

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Structure I/O | pymatgen | ASE only | pymatgen integrates with Materials Project, atomate2 |
| Simulations | ASE | pymatgen only | ASE better for MD, calculators; use both |

---

## What NOT to Use

### Deprecated/Abandoned

| Technology | Why Avoid |
|------------|-----------|
| atomate (v1) | Superseded by atomate2, different input set defaults |
| rust-cpython | Unmaintained, PyO3 is the maintained fork |
| tui-rs | Dead project, ratatui is the maintained fork |
| FireWorks (for new projects) | jobflow-remote is modern successor |

### Premature/Unstable

| Technology | Why Avoid |
|------------|-----------|
| Python 3.14 | Too new for scientific stack (pymatgen, atomate2 test only through 3.12) |
| PyO3 free-threaded mode | Interesting but experimental, stick to GIL mode |
| ratatui async-widgets | Experimental feature, use tokio manually |

### Wrong Tool for Job

| Technology | Why Avoid |
|------------|-----------|
| Electron/Tauri | Overkill for HPC TUI, SSH complexity, no benefit |
| Web UI | HPC users work in terminals, TUI is correct choice |
| Direct VASP calls | Always use custodian wrapper for error handling |

---

## Installation

### Rust Dependencies (Cargo.toml)

```toml
[dependencies]
# TUI Framework
ratatui = "0.30"
crossterm = "0.28"

# Async Runtime
tokio = { version = "1.49", features = ["full"] }

# Serialization
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"

# Python Integration
pyo3 = { version = "0.28", features = ["auto-initialize"] }

# Editor Widget
tui-textarea = { version = "0.7", features = ["search"] }

# Error Handling
anyhow = "1.0"
thiserror = "2.0"

# Logging
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter"] }
```

### Python Dependencies (pyproject.toml)

```toml
[project]
requires-python = ">=3.10,<3.14"

dependencies = [
    "pydantic>=2.0.0",
    "pymatgen>=2025.10.0",
]

[project.optional-dependencies]
# atomate2 workflow stack (recommended)
atomate2 = [
    "atomate2>=0.0.23",
    "jobflow>=0.3.0",
    "jobflow-remote>=1.0.0",
    "custodian",
]

# AiiDA workflow stack (optional, requires PostgreSQL)
aiida = [
    "aiida-core>=2.7,<3.0",
    "aiida-vasp>=5.0.0",
    "psycopg2-binary>=2.9",
]

# Structure manipulation
materials = [
    "ase>=3.27.0",
    "mp-api>=0.45",
]
```

### Build Commands

```bash
# Python environment
uv sync --all-extras

# Rust build (MUST use correct Python)
PYO3_PYTHON=$(pwd)/.venv/bin/python cargo build --release

# Or use provided script
./scripts/build-tui.sh
```

---

## Version Pinning Strategy

### Pin Tightly (breaking changes likely)

- `ratatui = "0.30"` - Major releases break widget APIs
- `pyo3 = "0.28"` - FFI changes can break builds
- `atomate2 = "0.0.23"` - Pre-1.0, breaking changes common

### Pin Loosely (stable APIs)

- `tokio = "1"` - Stable since 1.0
- `serde = "1.0"` - Extremely stable
- `pymatgen>=2025.10` - Calendar versioning, usually compatible

### Lock File Strategy

- **Rust:** `Cargo.lock` in version control (binary project)
- **Python:** `uv.lock` in version control (monorepo)
- **CI:** Test against both locked and latest monthly

---

## Sources

### Rust Libraries (HIGH confidence - docs.rs)
- [ratatui 0.30.0](https://docs.rs/ratatui/0.30.0/ratatui/) - Verified 2026-02-02
- [PyO3 0.28.0](https://docs.rs/pyo3/0.28.0/pyo3/) - Verified 2026-02-02
- [tokio 1.49.0](https://docs.rs/tokio/1.49.0/tokio/) - Verified 2026-02-02
- [tui-textarea 0.7.0](https://docs.rs/tui-textarea/0.7.0/tui_textarea/) - Verified 2026-02-02

### Python Libraries (HIGH confidence - PyPI)
- [atomate2 0.0.23](https://pypi.org/project/atomate2/) - Released 2025-12-03
- [aiida-core 2.7.3](https://pypi.org/project/aiida-core/) - Released 2026-01-23
- [jobflow 0.3.0](https://pypi.org/project/jobflow/) - Released 2026-02-01
- [jobflow-remote 1.0.0](https://pypi.org/project/jobflow-remote/) - Released 2026-01-14
- [pymatgen 2025.10.7](https://pypi.org/project/pymatgen/) - Released 2025-10-07

### Plugin Versions (MEDIUM confidence - GitHub releases)
- [aiida-vasp 5.0.0](https://github.com/aiida-vasp/aiida-vasp/releases) - Released 2025-11-18

### Ecosystem Research (MEDIUM confidence - WebSearch verified)
- [PyO3 vs alternatives](https://www.libhunt.com/r/pyo3) - PyO3 is de facto standard
- [atomate2 vs AiiDA](https://pubs.rsc.org/en/content/articlehtml/2025/dd/d5dd00019j) - Both viable, different use cases
- [pymatgen vs ASE](https://matsci.org/t/different-surface-structures-from-pymatgen-and-ase/58248) - Complementary, use both

---

## Roadmap Implications

### Phase 1: Core Infrastructure
- Set up PyO3 bridge with JSON-RPC protocol (existing pattern)
- Integrate pymatgen for structure I/O
- Basic VASP input display in TUI

### Phase 2: atomate2 Integration
- Add atomate2 InputSet generation
- Pydantic model validation in bridge
- Template selection UI

### Phase 3: Job Submission
- jobflow-remote integration for SLURM
- Job status polling
- Results parsing

### Phase 4: Optional AiiDA
- PostgreSQL setup (optional)
- AiiDA daemon integration
- Provenance querying UI

**Rationale:** Start with simpler atomate2 stack, add AiiDA when provenance needed.
