# Architecture & Migration Strategy: CrystalMath v2 (Rust + AiiDA)

## 1. High-Level Architecture: The "Hybrid Bridge"

To achieve the 60fps performance of a Rust TUI while leveraging the massive scientific ecosystem of Python (AiiDA, Pymatgen, ASE), we will adopt an **Embedded Python Architecture** using PyO3.

### The Concept

Instead of rewriting your scientific logic in Rust (which is immature for DFT workflows compared to Python), the Rust binary will act as a high-performance **Frontend and Process Manager**. It will embed a Python interpreter to load AiiDA and your existing logic.

```mermaid
graph TD
    User[User Input] -->|Events (Crossterm)| RustApp[Rust/Ratatui Binary]
    RustApp -->|Render (60fps)| TUI[Terminal UI]
    
    subgraph "Rust Domain (Frontend)"
        RustApp -->|Spawns| LSP[LSP Client Thread]
        RustApp -->|Calls via PyO3| PyBridge[Python Bridge Module]
        RustApp -->|Shared State| State[Arc<Mutex<AppState>>]
    end
    
    subgraph "External Processes"
        LSP -->|Stdio JSON-RPC| DftServer[dft-language-server (Node.js)]
        SSH[SSH Client] -->|Exec| HPC[HPC Cluster (Slurm)]
    end
    
    subgraph "Python Domain (Backend)"
        PyBridge -->|Imports| Controller[AiiDA Controller Class]
        Controller -->|Submits| AiiDA[AiiDA Engine]
        Controller -->|Validates| Pydantic[Pydantic Models]
        AiiDA -->|Persists| Postgres[(PostgreSQL)]
    end
```

## 2. Current State Assessment

### What's Already Complete

| Component | Status | Notes |
|-----------|--------|-------|
| **CLI** | ✅ Production | Bash modular architecture, 76 tests |
| **TUI (Python)** | ✅ Production | Textual-based, SSH/SLURM/orchestration |
| **dft-language-server** | ✅ Phase 1-2 Complete | VASP + CRYSTAL23 support, 79 tests |
| **AiiDA Integration** | ✅ Phase 3 Complete | Optional PostgreSQL backend |
| **Materials API** | 🔨 In Progress | MP/OPTIMADE integration |

### dft-language-server Features (v1.1.0)

The LSP has been upgraded from VASP-only to multi-code support:

- **VASP**: INCAR, POSCAR, KPOINTS, POTCAR validation
- **CRYSTAL23**: `.d12` file parsing, validation, completions, hover docs, semantic tokens
- **50+ CRYSTAL23 keywords** with full metadata
- **Levenshtein-based typo suggestions**
- **Space group validation** (1-230 for CRYSTAL, 1-80 for SLAB)

## 3. Directory Structure Migration

We will move from a pure Python layout to a Rust workspace that contains a Python package.

### Current Structure

```
crystalmath/
├── cli/                    # Bash scripts (Production)
├── tui/                    # Python Textual App (Production)
│   ├── src/core            # Logic mixed with UI
│   └── src/tui             # UI Widgets
└── REFACTOR/               # Migration planning docs
```

### Target Structure

```
crystalmath/
├── Cargo.toml              # Rust Workspace
├── src/                    # Rust Source (The New UI)
│   ├── main.rs             # Entry point
│   ├── app.rs              # State management
│   ├── ui/                 # Ratatui widgets
│   ├── bridge.rs           # PyO3 bindings to Python
│   └── lsp.rs              # LSP Client logic
├── python/                 # The Scientific Backend
│   ├── crystalmath/        # Python Package
│   │   ├── api.py          # The "Facade" class used by Rust
│   │   ├── models.py       # Pydantic Schemas
│   │   └── aiida_plugin/   # Your Crystal23 CalcJob/Parsers
├── dft-language-server/    # Multi-code LSP (submodule)
│   └── src/
│       ├── features/crystal/   # CRYSTAL23 support
│       ├── features/incar/     # VASP INCAR support
│       └── data/crystal-tags.ts
└── pyproject.toml          # Python dependencies
```

## 4. Migration Phases

### Phase 1: The Data Contract (Python Side)

**Goal:** Strict types for data exchange.

- Define `JobConfig`, `JobStatus`, and `CalculationResult` in Pydantic
- Ensure these models serialize to JSON exactly how Rust's serde expects them

### Phase 2: The AiiDA Facade (Python Side)

**Goal:** Abstract AiiDA complexity behind a simple API.

- Create `class CrystalController` in Python
- Implement methods: `submit_job`, `get_active_jobs`, `get_job_details`
- **Crucial:** This class must handle AiiDA's async loop or threading internally, returning simple results to Rust

### Phase 3: The Rust Foundation

**Goal:** Basic TUI running.

- Set up ratatui + crossterm
- Implement the `App` struct and Event Loop
- Create the specific layout: Sidebar (Jobs), Main (Tabs: Log/Input/Results)

### Phase 4: Integration & Tooling

- **PyO3 Binding:** Initialize Python in `main.rs` and load the `CrystalController`
- **LSP:** Spawn the `dft-language-server` Node.js process from Rust and pipe stdin/stdout to a widget
- **Deployment:** Use maturin to build the Rust binary and bundle the Python dependencies

## 5. Risk Assessment

| Risk | Mitigation |
|------|------------|
| PyO3 complexity | Start with JSON-over-FFI boundary (simpler than native types) |
| Python TUI works fine | Keep Python TUI as fallback; Rust version is performance upgrade |
| LSP Node.js dependency | Bundle with pkg or use Bun for single binary |
| AiiDA PostgreSQL requirement | Keep SQLite fallback for local-only mode |
