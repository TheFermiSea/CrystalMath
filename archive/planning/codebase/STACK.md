# Technology Stack

**Analysis Date:** 2026-02-02

## Languages

**Primary:**
- Python 3.10+ - Core backend API, Python TUI ("Workshop"), optional integrations (AiiDA, Materials API, LLM)
- Rust 2021 edition - Secondary TUI ("Cockpit"), PyO3 bridge for Python interop
- Bash 4.0+ - CLI toolkit for CRYSTAL23 job execution

**Secondary:**
- Node.js/JavaScript - Optional LSP server (dft-language-server) via subprocess

## Runtime

**Environment:**
- Python 3.10, 3.11, 3.12 (tested versions in pyproject.toml)
- Rust stable (2021 edition, checked with `cargo clippy`)
- Bash 4.0+ (macOS: Homebrew, Linux: system)

**Python Package Manager:**
- uv (recommended) - Unified workspace management for Python packages
- Lockfile: `uv.lock` (monorepo-wide, includes all workspace members)

**Rust Package Manager:**
- Cargo (standard Rust ecosystem)
- Lockfile: `Cargo.lock`

## Frameworks

**Core:**
- Pydantic 2.0+ - Data validation, models (core API, runners, Materials API)
- Textual 0.50+ - TUI framework for Python ("Workshop" UI)
- Ratatui 0.29 - TUI framework for Rust ("Cockpit" UI)

**Async Runtime:**
- Tokio 1.42+ (Rust) - Async task scheduling, channels, timer management
- asyncio (Python standard) - Async I/O for remote execution, database operations

**Serialization:**
- Serde 1.0 (Rust) - JSON serialization for FFI bridge
- serde_json 1.0 (Rust) - JSON handling
- Pydantic (Python) - JSON schema generation

**Testing:**
- pytest 7.0+ - Python test framework (core package, TUI)
- pytest-asyncio 0.21+ - Async test support
- pytest-cov 4.0+ - Coverage reporting
- cargo test - Rust built-in test runner
- bats-core - Bash testing framework for CLI

**Build/Dev:**
- Hatchling - Build backend for Python packages
- Setuptools 61.0+ - Alternative Python build (legacy support)
- cargo clippy - Rust linter
- cargo fmt - Rust formatter
- black 24.0+ - Python code formatter (100-char line length)
- ruff 0.1+ - Python linter (E, F, W, I, N, UP, B, A, C4, SIM rules)
- mypy 1.0+ - Python static type checker (strict mode)

## Key Dependencies

### Python Core (crystalmath package)

**Core:**
- pydantic>=2.0.0 - Data models (required)

**Optional - AiiDA Integration:**
- aiida-core>=2.7,<3.0 - Workflow engine (Phase 3)
- psycopg2-binary>=2.9 - PostgreSQL adapter for AiiDA
- aiida-vasp - VASP plugin
- aiida-quantumespresso - Quantum ESPRESSO plugin
- pymatgen>=2024.1.1 - Structure handling

**Optional - Materials API Integration:**
- mp-api>=0.45 - Materials Project API client (Phase 4)
- mpcontribs-client>=5.10 - Materials Project user contributions
- optimade[http_client]>=1.2 - Cross-database structure queries (native async)
- python-dotenv>=1.0.0 - .env file loading
- aiosqlite>=0.20.0 - Async SQLite for Materials API cache

**Optional - LLM Integration:**
- anthropic>=0.39.0 - Anthropic Claude API
- langchain>=0.3.0 - LLM framework
- langchain-anthropic>=0.3.0 - Anthropic provider for LangChain

### Python TUI (crystal-tui package)

**Core:**
- crystalmath>=0.2.0 - Core package (workspace dependency)
- textual>=0.50.0 - Terminal UI framework
- rich>=13.0.0 - Rich text and tables
- jinja2>=3.1.0 - Template engine (sandboxed for input generation)
- pyyaml>=6.0.0 - YAML parsing for templates
- asyncssh>=2.14.0 - SSH/SFTP for remote execution (Phase 2)
- keyring>=24.0.0 - Secure credential storage (system keyring)

**Optional:**
- CRYSTALpytools>=2023.0.0 - Structure analysis (analysis extra)
- ase>=3.22.0 - Atomic Simulation Environment

### Rust TUI (crystalmath-tui package)

**TUI & Terminal:**
- ratatui 0.29 - Terminal UI rendering
- crossterm 0.28 - Cross-platform terminal control
- tui-textarea 0.7 - Editor widget with syntax support

**Async & Concurrency:**
- tokio 1.42 (full features) - Async runtime with channels, timers
- std::sync::mpsc - Sync channels for bridge communication

**Data & Serialization:**
- serde 1.0 with derive - Serialization framework
- serde_json 1.0 - JSON handling
- pyo3 0.27 (auto-initialize) - Python FFI via PyO3

**Utilities:**
- anyhow 1.0 - Error handling
- thiserror 2.0 - Error type macros
- url 2.5 - URI handling for LSP
- chrono 0.4 with serde - Date/time handling
- dirs 5.0 - Platform-specific directories (XDG, macOS Library)
- tracing 0.1 - Structured logging
- tracing-subscriber 0.3 - Logging configuration

**Dev:**
- pretty_assertions 1.4 - Better assertion output

### CLI (cry module in Bash)

**Internal:**
- No external dependencies (pure Bash + GNU tools)

**Required External Tools:**
- gum (auto-installed) - Visual components (colors, spinners, forms)
- mpirun (from Intel MPI or OpenMPI) - MPI execution
- CRYSTAL23 binaries (crystalOMP, PcrystalOMP, properties)

## Configuration

**Environment Variables:**

Core paths (required for operation):
- `CRY23_ROOT` - CRYSTAL23 installation root (default: $HOME/CRYSTAL23)
- `CRY23_EXEDIR` - Directory containing CRYSTAL binaries
- `CRY_SCRATCH_BASE` - Scratch directory for temp files (default: ~/tmp_crystal)

Remote execution:
- `SSH_KEY_PATH` - SSH private key location (falls back to system keyring)

Materials API integration:
- `MP_API_KEY` - Materials Project API key (required for Materials API queries)
- `MPCONTRIBS_API_KEY` - MPContribs API key (falls back to MP_API_KEY)

Python/PyO3:
- `PYTHONPATH` - For Python module discovery (auto-set by build-tui.sh)
- `PYO3_PYTHON` - Path to Python interpreter for PyO3 compilation

LSP:
- `CRYSTAL_LSP_SERVER_PATH` - Path to dft-language-server (optional, auto-detected)

**Build Configuration:**

Rust:
- `Cargo.toml` - Package metadata, dependencies, release profile
  - Release profile: LTO, single codegen unit, stripped binary
- `.cargo/config.toml` (if present) - Build settings

Python:
- `pyproject.toml` (root) - Workspace configuration via uv
- `python/pyproject.toml` - Core package configuration
- `tui/pyproject.toml` - TUI package configuration
- `pyproject.toml` sections - Black, Ruff, MyPy, pytest configuration

**Workspace Configuration:**

- uv workspace members: `python/`, `tui/`
- Shared tool config in root `pyproject.toml`
  - Black: 100-char line length, Python 3.10+
  - Ruff: E, F, W, I, N, UP, B, A, C4, SIM rules
  - MyPy: strict mode, Pydantic plugin
  - pytest: `python/tests` and `tui/tests` paths

**Scripts:**
- `scripts/build-tui.sh` - Build Rust TUI with correct Python version
- `utils23/cry23.bashrc` - Environment setup for CRYSTAL23

## Platform Requirements

**Development:**
- macOS ARM64 or Linux x86_64
- Python 3.10+ (system or venv)
- Rust 1.70+ (for Cargo)
- Bash 4.0+ (macOS: Homebrew, Linux: system)
- C compiler (for cryptography, asyncssh dependencies)
- Git (for version control)

**Production:**
- CRYSTAL23 1.0.1 with OpenMP support (crystalOMP binary)
- Optional: MPI (Intel MPI, OpenMPI) for PcrystalOMP
- Optional: PostgreSQL 12+ (for AiiDA backend)
- Optional: RabbitMQ (for AiiDA distributed execution)
- Optional: dft-language-server Node.js binary (for LSP diagnostics)

**Storage:**
- Fast local SSD for scratch directory (~10-100 GB per calculation)
- SQLite database (`.crystal_tui.db`) for job history

## Architecture-Specific Notes

**PyO3 Bridge (Rust-Python):**
- Requires exact Python version match between build and runtime
- Uses JSON string FFI for robustness (not direct object serialization)
- Spawns Python worker thread with dedicated interpreter (non-blocking UI)
- Build script `scripts/build-tui.sh` handles version detection

**Database Sharing:**
- Single SQLite file (`.crystal_tui.db`) shared between Python TUI and Rust TUI
- Async queries via aiosqlite (Python) and sqlite3 (Rust, blocking in separate thread)
- Auto-discovers database path: env var → project root → `tui/` → XDG directories

**Async Patterns:**
- Python: asyncio for I/O (SSH, database), Textual event loop
- Rust: Tokio for channels, timers; 60fps event loop with non-blocking renders
- LSP: Async JSON-RPC over stdio with 200ms debounce on editor changes

---

*Stack analysis: 2026-02-02*
