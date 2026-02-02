# CrystalMath

## What This Is

A unified Rust TUI frontend for AiiDA and atomate2, enabling VASP users to create, validate, submit, and track calculations on SLURM clusters. The Rust TUI handles all user interaction while the Python backend (atomate2, AiiDA, ASE) provides business logic, input validation, and workflow orchestration.

## Core Value

Streamlined VASP workflow — from structure to validated submission to tracked results — leveraging the mature Python scientific computing ecosystem through a fast, maintainable Rust interface.

## Requirements

### Validated

<!-- Existing capabilities from the codebase -->

- ✓ CLI for local CRYSTAL23 execution — existing (`cli/bin/runcrystal`)
- ✓ Rust TUI basic structure — existing (60fps event loop, tabs, dirty-flag rendering)
- ✓ PyO3 bridge to Python backend — existing (`src/bridge.rs`)
- ✓ Python API facade — existing (`python/crystalmath/api.py`)
- ✓ AiiDA integration — existing (Phase 3, optional backend)
- ✓ Materials Project API integration — existing (structure search)
- ✓ LSP client for editor diagnostics — existing (`src/lsp.rs`)
- ✓ Job list display in Rust TUI — existing (`src/ui/jobs.rs`)
- ✓ Editor with syntax highlighting — existing (`src/ui/editor.rs`)

### Active

<!-- v1 scope: Unified Rust TUI for VASP on SLURM -->

**Input Creation:**
- [ ] Generate VASP inputs via atomate2 input sets (INCAR, KPOINTS, POTCAR config)
- [ ] Manual VASP file creation/editing in TUI
- [ ] Input validation via Pydantic (atomate2)
- [ ] Template browser with presets (relaxation, static, band structure)
- [ ] Custom user templates (save/load)

**Structure Handling:**
- [ ] Import structure files (POSCAR, CIF, etc.)
- [ ] Search Materials Project by formula/ID
- [ ] Structure preview in TUI

**Cluster Management:**
- [ ] Configure multiple SLURM clusters in TUI
- [ ] Cluster selection at job submission
- [ ] Connection testing/validation

**Job Submission (via AiiDA):**
- [ ] Submit VASP jobs through AiiDA workflow engine
- [ ] All jobs tracked in AiiDA database
- [ ] Job queueing and status polling

**Job Tracking:**
- [ ] View past jobs (history)
- [ ] View running/queued jobs
- [ ] Job detail view with metadata
- [ ] Results display (energy, forces, etc.)

**Migration:**
- [ ] Remove Python TUI (Textual)
- [ ] Migrate from SQLite to AiiDA database
- [ ] Update PyO3 bridge for AiiDA queries

### Out of Scope

- **Pure Rust migration** — Python backend is permanent (atomate2/AiiDA/ASE ecosystem)
- **Direct SLURM submission** — All jobs through AiiDA (no bypassing workflow engine)
- **CRYSTAL23/QE support for v1** — VASP users are first priority; other codes later
- **Python TUI maintenance** — Will be deleted, not maintained alongside Rust TUI
- **Mobile/web interface** — Desktop TUI only

## Context

**Brownfield project:** Existing codebase with CLI, two TUIs (Python primary, Rust secondary), and Python backend. This project consolidates to a single Rust TUI.

**Existing architecture being changed:**
- Python TUI (Textual) is currently primary — will be deleted
- Rust TUI is currently secondary/monitoring only — becomes the only UI
- SQLite database (`.crystal_tui.db`) — migrating to AiiDA database
- Feature freeze on Rust TUI (ADR-002) — being lifted

**Leveraging existing Python ecosystem:**
- atomate2 for VASP input sets and Pydantic validation
- AiiDA for workflow orchestration and job tracking
- ASE/pymatgen for structure handling
- Materials Project API for structure search

**Target users:** Computational materials scientists running VASP calculations on HPC clusters with SLURM.

## Constraints

- **Python backend permanent**: atomate2/AiiDA/ASE are Python libraries; no Rust alternatives exist with comparable maturity
- **AiiDA required**: All job submission goes through AiiDA; requires AiiDA profile setup
- **SLURM clusters**: Target environment is HPC clusters with SLURM batch system
- **VASP license**: Users must have their own VASP license and binaries on their clusters

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Rust TUI as only UI | Cleaner, more maintainable codebase; single language for UI | — Pending |
| Python backend permanent | atomate2/AiiDA/ASE ecosystem is mature; no Rust equivalents | — Pending |
| AiiDA for all jobs | Unified workflow engine; better tracking than direct SLURM | — Pending |
| AiiDA database as source of truth | Single database; no sync issues with SQLite | — Pending |
| VASP first, other codes later | First users are VASP users; CRYSTAL23/QE support deferred | — Pending |
| atomate2 for input validation | Battle-tested Pydantic models; no need to reinvent | — Pending |

---
*Last updated: 2026-02-02 after initialization*
