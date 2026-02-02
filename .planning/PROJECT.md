# CrystalMath

## What This Is

A unified Rust TUI frontend for quacc, enabling VASP users to create, validate, submit, and track calculations on SLURM clusters. The Rust TUI handles all user interaction while the Python backend (quacc, ASE, pymatgen) provides business logic, VASP recipes, and workflow orchestration.

## Core Value

Streamlined VASP workflow — from structure to validated submission to tracked results — leveraging quacc's pre-built recipes and flexible workflow engine integration through a fast, maintainable Rust interface.

## Requirements

### Validated

<!-- Existing capabilities from the codebase -->

- ✓ CLI for local CRYSTAL23 execution — existing (`cli/bin/runcrystal`)
- ✓ Rust TUI basic structure — existing (60fps event loop, tabs, dirty-flag rendering)
- ✓ PyO3 bridge to Python backend — existing (`src/bridge.rs`)
- ✓ Python API facade — existing (`python/crystalmath/api.py`)
- ✓ Materials Project API integration — existing (structure search)
- ✓ LSP client for editor diagnostics — existing (`src/lsp.rs`)
- ✓ Job list display in Rust TUI — existing (`src/ui/jobs.rs`)
- ✓ Editor with syntax highlighting — existing (`src/ui/editor.rs`)

### Active

<!-- v1 scope: Unified Rust TUI for VASP on SLURM via quacc -->

**Input Creation:**
- [ ] Generate VASP inputs via quacc recipes (relaxation, static, band structure)
- [ ] Manual VASP file creation/editing in TUI
- [ ] Input validation via ASE/pymatgen
- [ ] Recipe browser with presets (MP-compatible, QMOF, custom)
- [ ] Custom user recipes (save/load)

**Structure Handling:**
- [ ] Import structure files (POSCAR, CIF, etc.)
- [ ] Search Materials Project by formula/ID
- [ ] Structure preview in TUI

**Cluster Management:**
- [ ] Configure multiple SLURM clusters in TUI
- [ ] Cluster selection at job submission
- [ ] Connection testing/validation
- [ ] Workflow engine executor configuration (Parsl/Covalent)

**Job Submission (via quacc + workflow engine):**
- [ ] Submit VASP jobs through quacc recipes
- [ ] Workflow engine handles HPC execution (Parsl pilot jobs or Covalent SLURM)
- [ ] Job queueing and status polling

**Job Tracking:**
- [ ] View past jobs (history)
- [ ] View running/queued jobs
- [ ] Job detail view with metadata
- [ ] Results display (energy, forces, etc.)
- [ ] Results storage via `results_to_db` or local JSON

**Migration:**
- [ ] Remove Python TUI (Textual)
- [ ] Replace AiiDA integration with quacc
- [ ] Update PyO3 bridge for quacc workflow status

### Out of Scope

- **Pure Rust migration** — Python backend is permanent (quacc/ASE/pymatgen ecosystem)
- **AiiDA integration** — Using quacc's simpler approach instead
- **CRYSTAL23/QE support for v1** — VASP users are first priority; other codes later
- **Python TUI maintenance** — Will be deleted, not maintained alongside Rust TUI
- **Mobile/web interface** — Desktop TUI only
- **High-throughput (10K+ jobs)** — Focused on individual researcher workflow

## Context

**Brownfield project:** Existing codebase with CLI, two TUIs (Python primary, Rust secondary), and Python backend. This project consolidates to a single Rust TUI.

**Existing architecture being changed:**
- Python TUI (Textual) is currently primary — will be deleted
- Rust TUI is currently secondary/monitoring only — becomes the only UI
- SQLite database (`.crystal_tui.db`) — simplified storage via quacc results_to_db
- Feature freeze on Rust TUI (ADR-002) — being lifted
- AiiDA integration — being replaced with quacc

**Leveraging quacc ecosystem:**
- quacc for VASP recipes and workflow orchestration
- Parsl or Covalent for HPC/SLURM execution
- ASE for calculator interface
- pymatgen for structure handling
- Materials Project API for structure search

**Target users:** Computational materials scientists running VASP calculations on HPC clusters with SLURM.

## Constraints

- **Python backend permanent**: quacc/ASE/pymatgen are Python libraries; no Rust alternatives exist
- **SLURM clusters**: Target environment is HPC clusters with SLURM batch system
- **VASP license**: Users must have their own VASP license and binaries on their clusters
- **Workflow engine choice**: User selects Parsl (pilot jobs) or Covalent (SLURM executor)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Rust TUI as only UI | Cleaner, more maintainable codebase; single language for UI | ✓ Decided |
| Python backend permanent | quacc/ASE/pymatgen ecosystem is mature; no Rust equivalents | ✓ Decided |
| quacc over atomate2+AiiDA | Simpler setup, no PostgreSQL, workflow-engine-agnostic | ✓ Decided |
| Parsl/Covalent for execution | quacc-native, handles SLURM without AiiDA daemon | ✓ Decided |
| VASP first, other codes later | First users are VASP users; CRYSTAL23/QE support deferred | ✓ Decided |
| JSON-RPC IPC over PyO3 embedding | Avoids GIL deadlocks, cleaner process separation | — Pending |

## Technology Stack

### Rust (TUI Layer)
- ratatui 0.30+ — TUI rendering
- crossterm 0.28+ — Terminal events
- tokio — Async runtime
- serde — JSON serialization for IPC

### Python (Backend Layer)
- quacc — VASP recipes and workflow orchestration
- Parsl or Covalent — HPC job execution
- ASE — Calculator interface
- pymatgen — Structure handling
- Materials Project API — Structure search

### IPC
- JSON-RPC 2.0 over Unix domain sockets (preferred)
- PyO3 bridge (existing, may be replaced)

---
*Last updated: 2026-02-02 after quacc pivot*
