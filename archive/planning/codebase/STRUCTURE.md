# Codebase Structure

**Analysis Date:** 2026-02-02

## Directory Layout

```
crystalmath/
├── cli/                          # Bash CLI tool for job execution
│   ├── bin/
│   │   ├── runcrystal           # Main executable (130 lines, thin orchestrator)
│   │   └── cry-docs             # Documentation browser (planned)
│   ├── lib/                     # 9 modular library modules
│   │   ├── cry-config.sh        # Configuration & environment setup
│   │   ├── cry-logging.sh       # Logging infrastructure (cry_log, cry_warn, etc)
│   │   ├── core.sh              # Module loader system (cry_require)
│   │   ├── cry-ui.sh            # Visual components (gum wrappers)
│   │   ├── cry-parallel.sh      # MPI/OpenMP parallelism logic
│   │   ├── cry-scratch.sh       # Scratch directory lifecycle management
│   │   ├── cry-stage.sh         # File staging (input/output)
│   │   ├── cry-exec.sh          # CRYSTAL23 binary execution
│   │   └── cry-help.sh          # Help system
│   ├── tests/
│   │   ├── unit/                # 76 unit tests per module
│   │   │   ├── cry-config_test.bats
│   │   │   ├── cry-parallel_test.bats
│   │   │   └── ...
│   │   ├── integration/         # Full workflow tests
│   │   │   └── full_workflow_test.bats
│   │   ├── mocks/               # Mock binaries for testing
│   │   └── helpers.bash         # Common test utilities
│   └── share/tutorials/         # CRYSTAL documentation mirror (generated)
│
├── python/                       # Python core package (crystalmath)
│   ├── crystalmath/
│   │   ├── __init__.py
│   │   ├── api.py              # CrystalController main API facade (114k)
│   │   ├── models.py           # Pydantic data models (JobDetails, JobStatus, etc)
│   │   ├── protocols.py        # Protocol definitions for runners/backends
│   │   ├── rust_bridge.py      # Rust FFI helpers
│   │   ├── backends/           # Database/state backends
│   │   │   ├── __init__.py
│   │   │   ├── sqlite.py       # SQLite backend implementation
│   │   │   ├── aiida.py        # AiiDA backend (optional)
│   │   │   └── demo.py         # Demo backend for testing
│   │   ├── high_level/         # High-level API (builder, registry, results)
│   │   │   ├── api.py          # High-level facade
│   │   │   ├── builder.py      # Job builder pattern
│   │   │   ├── registry.py     # Code/template registry
│   │   │   ├── clusters.py     # Cluster configuration
│   │   │   ├── runners.py      # Runner registry
│   │   │   └── results.py      # Results parsing
│   │   ├── integrations/       # External integrations
│   │   │   ├── materials_project.py   # Materials Project API
│   │   │   ├── pymatgen_bridge.py     # pymatgen integration
│   │   │   ├── atomate2_bridge.py     # atomate2 integration
│   │   │   ├── aiida_enhanced.py      # AiiDA enhancements
│   │   │   ├── slurm_runner.py        # SLURM backend
│   │   │   ├── pwd_bridge.py          # pwd integration
│   │   │   └── jobflow_store.py       # jobflow storage
│   │   ├── ai/                 # AI features (LLM diagnosis)
│   │   │   └── service.py      # AI service
│   │   ├── workflows/          # Workflow templates
│   │   │   ├── convergence.py  # Convergence study workflow
│   │   │   ├── phonon.py       # Phonon calculation workflow
│   │   │   ├── bands.py        # Band structure workflow
│   │   │   ├── eos.py          # Equation of state workflow
│   │   │   ├── aiida_launcher.py
│   │   │   └── __init__.py
│   │   ├── templates/          # DFT input templates
│   │   │   ├── __init__.py
│   │   │   ├── basic/          # CRYSTAL23 basic templates
│   │   │   ├── advanced/       # CRYSTAL23 advanced templates
│   │   │   ├── qe/             # Quantum Espresso templates
│   │   │   ├── vasp/           # VASP templates
│   │   │   └── slurm/          # SLURM submission templates
│   │   └── aiida_plugin/       # AiiDA plugin interface
│   │       └── __init__.py
│   ├── tests/
│   │   ├── test_api.py
│   │   ├── test_models.py
│   │   ├── test_jsonrpc_dispatch.py
│   │   ├── test_workflows.py
│   │   └── ...
│   ├── pyproject.toml          # Package definition
│   └── README.md
│
├── tui/                         # Python TUI package (crystal-tui, primary)
│   ├── src/
│   │   ├── main.py            # Entry point (uv run crystal-tui)
│   │   ├── core/              # TUI-specific business logic
│   │   │   ├── __init__.py
│   │   │   ├── database.py    # SQLite schema and migrations (52k)
│   │   │   ├── backend.py     # Backend selection logic
│   │   │   ├── core_adapter.py  # Adapter for crystalmath API
│   │   │   ├── orchestrator.py  # Workflow DAG executor (77k)
│   │   │   ├── queue_manager.py # Job queue and polling (48k)
│   │   │   ├── workflow.py    # Workflow definitions (53k)
│   │   │   ├── connection_manager.py  # SSH connection pooling (30k)
│   │   │   ├── templates.py   # Template rendering and security (22k)
│   │   │   ├── config_loader.py      # Configuration loading
│   │   │   ├── environment.py        # Environment setup
│   │   │   ├── constants.py          # TUI constants
│   │   │   ├── dependency_utils.py   # Dependency checking
│   │   │   ├── codes/               # DFT code-specific logic
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base.py
│   │   │   │   ├── crystal.py
│   │   │   │   ├── qe.py
│   │   │   │   └── vasp.py
│   │   │   └── materials_api/       # Materials Project integration
│   │   │       ├── __init__.py
│   │   │       ├── client.py
│   │   │       └── cache.py
│   │   ├── runners/           # Job execution backends
│   │   │   ├── __init__.py
│   │   │   ├── base.py        # BaseRunner interface (28k)
│   │   │   ├── local.py       # Local subprocess runner (36k)
│   │   │   ├── ssh_runner.py  # SSH remote execution (48k)
│   │   │   ├── slurm_runner.py # SLURM batch submission (66k)
│   │   │   ├── container_runner.py   # Container support (27k)
│   │   │   ├── exceptions.py         # Runner exceptions
│   │   │   ├── vasp_errors.py        # VASP error detection
│   │   │   ├── vasp_progress.py      # VASP progress parsing
│   │   │   └── slurm_templates.py    # SLURM script generation
│   │   ├── tui/               # Textual UI components
│   │   │   ├── __init__.py
│   │   │   ├── app.py         # Main TUI application (42k)
│   │   │   ├── app_enhanced.py # Enhanced features (32k)
│   │   │   ├── messages.py    # Event messages
│   │   │   ├── screens/       # Textual screens
│   │   │   │   ├── __init__.py
│   │   │   │   ├── jobs.py    # Jobs list screen
│   │   │   │   ├── new_job.py # Job creation screen
│   │   │   │   ├── results.py # Results view
│   │   │   │   ├── logs.py    # Log streaming
│   │   │   │   └── ...
│   │   │   └── widgets/       # Reusable widgets
│   │   │       ├── __init__.py
│   │   │       ├── auto_form.py
│   │   │       ├── table.py
│   │   │       └── ...
│   │   ├── aiida/             # AiiDA integration (Phase 3)
│   │   │   ├── __init__.py
│   │   │   ├── adapter.py     # AiiDA query adapter
│   │   │   ├── converters.py  # Data conversion
│   │   │   ├── diagnostics.py # Error diagnostics
│   │   │   ├── parser.py      # Output parsing
│   │   │   ├── protocols.py   # AiiDA protocols
│   │   │   └── submitter.py   # Job submission
│   │   └── postprocessing/    # Results analysis
│   │       ├── __init__.py
│   │       ├── parser.py      # Output parser registry
│   │       └── ...
│   ├── tests/
│   │   ├── test_app.py
│   │   ├── test_database.py
│   │   ├── test_orchestrator.py
│   │   ├── test_local_runner.py
│   │   ├── test_ssh_runner.py
│   │   ├── test_slurm_runner.py
│   │   ├── test_queue_manager.py
│   │   ├── test_templates.py
│   │   ├── test_aiida_*.py     # AiiDA tests
│   │   ├── test_materials_api.py
│   │   └── ...
│   ├── templates/             # DFT input templates (symlink to python/)
│   ├── config/                # User configuration directory
│   │   └── clusters/          # Cluster configs
│   ├── pyproject.toml         # TUI package definition
│   └── README.md
│
├── src/                        # Rust TUI (Cockpit, secondary/experimental)
│   ├── main.rs               # Entry point, terminal setup, event loop (40k)
│   ├── app.rs                # Application state management (145k)
│   ├── app_tests.rs          # App state tests (34k)
│   ├── bridge.rs             # PyO3 FFI and Python bridge (69k)
│   ├── lsp.rs                # LSP client for editor support (67k)
│   ├── models.rs             # Data models matching Python (49k, serde)
│   ├── state/                # State management modules
│   │   ├── mod.rs
│   │   ├── tab.rs
│   │   └── ...
│   └── ui/                   # Ratatui UI components
│       ├── mod.rs
│       ├── jobs.rs           # Jobs table (9k)
│       ├── editor.rs         # Editor with LSP (5k)
│       ├── results.rs        # Results detail view (5k)
│       ├── log.rs            # Log viewer (4k)
│       ├── materials.rs      # Materials search (10k)
│       ├── cluster_manager.rs # Cluster config (26k)
│       ├── slurm_queue.rs    # SLURM queue (13k)
│       ├── vasp_input.rs     # VASP input manager (15k)
│       ├── workflows.rs      # Workflow management (10k)
│       ├── new_job.rs        # New job creation (16k)
│       ├── header.rs         # Header bar (1k)
│       ├── footer.rs         # Footer bar (2k)
│       └── ...
│
├── docs/                      # Shared documentation
│   ├── architecture/          # Architecture Decision Records (ADRs)
│   │   ├── adr-001-primary-python-tui.md
│   │   ├── adr-002-rust-tui-secondary-policy.md
│   │   ├── adr-003-ipc-boundary-design.md
│   │   ├── adr-004-editor-lsp-strategy.md
│   │   ├── adr-005-unified-configuration.md
│   │   ├── overview.md        # High-level overview
│   │   ├── cli.md
│   │   ├── tui.md
│   │   ├── cli-modules.md
│   │   ├── database.md
│   │   ├── workflows.md
│   │   ├── integration.md
│   │   └── ... (20+ docs total)
│   ├── getting-started/       # Installation and setup
│   ├── user-guide/            # User documentation
│   │   ├── cli/
│   │   ├── tui/
│   │   └── dft-codes/
│   ├── development/           # Developer guides
│   └── reference/             # API reference
│
├── templates/                 # Root-level template directory
│   ├── basic/                 # Basic CRYSTAL23 templates
│   ├── advanced/              # Advanced CRYSTAL23 templates
│   └── workflows/             # Workflow definitions
│
├── examples/                  # Example calculations
│   ├── mgo/                   # MgO example
│   ├── diamond/               # Diamond example
│   └── ...
│
├── third_party/              # Git submodules
│   └── vasp-language-server/ # LSP server (Node.js)
│
├── scripts/                  # Build/utility scripts
│   ├── build-tui.sh         # Rust TUI build with Python version handling
│   └── ...
│
├── .planning/                # GSD planning documents (this location)
│   └── codebase/             # Architecture analysis docs
│       ├── ARCHITECTURE.md   # Architecture and patterns
│       └── STRUCTURE.md      # This file
│
├── Cargo.toml                # Rust workspace definition
├── Cargo.lock
├── pyproject.toml            # Python monorepo workspace config
├── uv.lock                   # Unified lockfile (uv workspaces)
├── CLAUDE.md                 # Project-specific Claude instructions
├── README.md                 # Top-level README
├── .crystal_tui.db          # Shared SQLite database
└── .beads/                  # Issue tracker
    └── issues.jsonl         # Issue database
```

## Directory Purposes

**cli/:**
- Purpose: Production-grade Bash CLI for CRYSTAL23 job execution
- Contains: Thin orchestrator + 9 modular libraries for config, logging, parallelism, file staging, execution
- Key files: `bin/runcrystal` (130 lines), `lib/*.sh` (modules)

**python/crystalmath/:**
- Purpose: Core scientific backend shared by all TUIs
- Contains: Pydantic models, API facade, database adapters, workflow engine, template system
- Key files: `api.py` (CrystalController main facade), `models.py` (data types), `protocols.py` (interfaces)

**tui/src/core/:**
- Purpose: TUI-specific business logic (jobs, workflows, templates, runners)
- Contains: Database schema/migrations, orchestrator, queue manager, runners (local/SSH/SLURM)
- Key files: `database.py` (SQLite), `orchestrator.py` (DAG execution), `runners/*.py` (backends)

**tui/src/tui/:**
- Purpose: Textual UI components and screens
- Contains: Screens (jobs, new job, results, logs), widgets, event handling
- Key files: `app.py` (main TUI), `screens/*.py` (individual screens)

**src/ (Rust):**
- Purpose: High-performance Rust TUI for read-only monitoring
- Contains: 60fps event loop, ratatui components, PyO3 bridge, LSP client
- Key files: `main.rs` (entry), `app.rs` (state), `bridge.rs` (Python bridge), `ui/*.rs` (components)

**docs/architecture/:**
- Purpose: Architecture Decision Records and detailed design docs
- Contains: 20+ markdown docs covering CLI modules, TUI design, database schema, workflow architecture
- Key files: `overview.md` (high-level), ADRs (001-005)

## Key File Locations

**Entry Points:**
- `cli/bin/runcrystal`: CLI entry point (Bash, thin orchestrator)
- `tui/src/main.py`: Python TUI entry point (Textual application)
- `src/main.rs`: Rust TUI entry point (Ratatui application)

**Configuration:**
- `cli/lib/cry-config.sh`: CLI environment and paths
- `tui/src/core/config_loader.py`: TUI configuration loading
- `python/pyproject.toml`: Python package configuration
- `Cargo.toml`: Rust package configuration

**Core Logic:**
- `python/crystalmath/api.py`: Main Python API facade (114k lines)
- `tui/src/core/orchestrator.py`: Workflow DAG execution (77k)
- `tui/src/core/queue_manager.py`: Job queue polling (48k)
- `tui/src/runners/base.py`: Runner interface definition (28k)

**Testing:**
- `cli/tests/unit/`: 76 Bash unit tests
- `cli/tests/integration/`: End-to-end workflow tests
- `python/tests/`: Core package tests
- `tui/tests/`: TUI application tests

**Shared Data:**
- `.crystal_tui.db`: SQLite database (shared between Python TUI and Rust TUI)
- `tui/src/core/database.py`: Database schema and migration functions

## Naming Conventions

**Files:**
- CLI modules: `cry-*.sh` (e.g., `cry-parallel.sh`, `cry-scratch.sh`)
- Python packages: lowercase with underscores (e.g., `queue_manager.py`, `ssh_runner.py`)
- Rust modules: lowercase with underscores (e.g., `app.rs`, `bridge.rs`)
- Test files: `test_*.py` (Python), `*_test.bats` (Bash), `*_tests.rs` (Rust)

**Directories:**
- CLI modules: `lib/` for reusable modules
- Python: `crystalmath/` (core), `tui/src/core/` (TUI-specific), `tui/src/runners/` (execution)
- Rust: `src/ui/` for ratatui components, `src/state/` for state management
- Tests: `tests/unit/`, `tests/integration/`, or alongside code in `tests/` directory

**Functions/Methods:**
- CLI: `module_function_name()` with underscore prefix for private: `_module_private()`
- Python: `snake_case` for functions, `PascalCase` for classes
- Rust: `snake_case` for functions, `PascalCase` for types/structs

## Where to Add New Code

**New Feature (CLI):**
- Primary code: Modify relevant module in `cli/lib/cry-*.sh`
- Tests: Add tests in `cli/tests/unit/<module>_test.bats`
- Example: Add parallelism feature → modify `cli/lib/cry-parallel.sh`, test in `cli/tests/unit/cry-parallel_test.bats`

**New Feature (Python TUI):**
- UI screens: `tui/src/tui/screens/<new_screen>.py`
- Business logic: `tui/src/core/<module>.py`
- Tests: `tui/tests/test_<feature>.py`
- Example: Add cluster manager → `tui/src/tui/screens/cluster_manager.py` + `tui/src/core/connection_manager.py`

**New Feature (Rust TUI):**
- UI component: `src/ui/<component>.rs`
- State changes: `src/app.rs` (central App struct)
- Tests: `src/app_tests.rs` or inline with `#[cfg(test)]`
- **CONSTRAINT**: Feature freeze in effect — only bug fixes, security patches, IPC migration prep

**New Runner Backend:**
- Implementation: `tui/src/runners/<new_runner>.py`
- Base interface: Implement `tui/src/runners/base.py::BaseRunner`
- Status enum: Use `JobStatus` from `python/crystalmath/models.py`
- Tests: `tui/tests/test_<runner>_runner.py`

**New DFT Code Support:**
- Templates: `python/crystalmath/templates/<code_name>/`
- Code logic: `tui/src/core/codes/<code_name>.py`
- Input model: Add to `python/crystalmath/models.py`
- Example: VASP support in `python/crystalmath/templates/vasp/`, `tui/src/core/codes/vasp.py`

**New Workflow Type:**
- Definition: `python/crystalmath/workflows/<workflow_name>.py`
- Template: `python/crystalmath/templates/workflows/<workflow_name>.yml`
- Tests: `tui/tests/test_<workflow_name>.py`
- Example: EOS workflow in `python/crystalmath/workflows/eos.py`, `python/crystalmath/templates/workflows/eos.yml`

**Utilities/Helpers:**
- CLI: `cli/lib/` for module functions
- Python: `python/crystalmath/high_level/` for public utilities, `tui/src/core/` for TUI-specific
- Rust: `src/` root for utility functions or dedicated module file

## Special Directories

**cli/tests/mocks/:**
- Purpose: Mock binaries for unit testing
- Generated: No (committed)
- Committed: Yes (part of test suite)
- Usage: Tests set `CRY23_ROOT` to temp directory with mock binaries

**tui/src/aiida/:**
- Purpose: AiiDA integration (Phase 3, optional)
- Generated: No
- Committed: Yes (optional dependency)
- Usage: Requires `pip install crystal-tui[aiida]`

**templates/ and tui/templates/:**
- Purpose: DFT input templates (Jinja2-based)
- Generated: No (hand-authored)
- Committed: Yes (part of repository)
- Usage: Loaded by `tui/src/core/templates.py` using `SandboxedEnvironment`

**third_party/vasp-language-server/:**
- Purpose: Git submodule for LSP server
- Generated: No (external project)
- Committed: Via git submodule
- Usage: Built with `npm install && npm run build`, used by Rust TUI

**python/crystalmath/aiida_plugin/:**
- Purpose: AiiDA plugin interface (Phase 3)
- Generated: No
- Committed: Yes
- Usage: Optional AiiDA integration

**docs/architecture/:**
- Purpose: Design documentation and ADRs
- Generated: No (hand-authored)
- Committed: Yes (reference)
- Usage: Consulted for architectural decisions

---

*Structure analysis: 2026-02-02*
