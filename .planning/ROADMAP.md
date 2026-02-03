# CrystalMath Roadmap

**Project:** Unified Rust TUI for VASP via quacc
**Created:** 2026-02-02
**Milestone:** v1.0 - Core VASP Workflow

## Milestone Overview

Transform CrystalMath from a dual-TUI (Python primary, Rust secondary) codebase into a unified Rust TUI that leverages quacc for VASP workflow orchestration on SLURM clusters.

**Success Criteria:**
- [ ] Single Rust TUI replaces Python TUI
- [ ] User can submit VASP jobs to SLURM via quacc
- [ ] Job status visible in TUI
- [ ] Results displayed after completion
- [ ] Multiple cluster configurations supported

---

## Phase 1: IPC Foundation ✅

**Goal:** Establish reliable communication between Rust TUI and Python backend, replacing PyO3 with JSON-RPC over Unix domain sockets.

**Why first:** Eliminates GIL deadlock risk before any feature work. All subsequent phases depend on this communication layer.

**Status:** Complete
**Completed:** 2026-02-02
**Plans:** 3 plans (all complete)

Plans:
- [x] 01-01-PLAN.md — Python JSON-RPC server with system.ping endpoint
- [x] 01-02-PLAN.md — Rust IPC client module with timeout handling
- [x] 01-03-PLAN.md — Auto-start logic and integration tests

### Deliverables

- [x] Python JSON-RPC server skeleton (`python/crystalmath/server/`)
- [x] Rust IPC client module (`src/ipc.rs`, `src/ipc/client.rs`, `src/ipc/framing.rs`)
- [x] Auto-start logic (TUI spawns server if not running)
- [x] Health check endpoint (`system.ping`)
- [x] Integration tests (Rust client <-> Python server)

### Technical Notes

- Use asyncio stdlib on Python side (no external deps)
- Use existing tokio on Rust side (no new deps)
- Socket location: `$XDG_RUNTIME_DIR/crystalmath.sock` or `~/Library/Caches/crystalmath.sock` (macOS)
- 30-second timeout for requests
- Server auto-exits after 5 minutes of inactivity (optional)

### Success Criteria

- [x] `cargo test ipc` passes (17 tests)
- [x] Server starts automatically when TUI launches
- [x] Ping/pong roundtrip < 10ms (achieved ~132μs)

### Dependencies

None (foundational phase)

---

## Phase 2: quacc Integration (Read-Only) ✅

**Goal:** Connect TUI to quacc's recipe system and validate workflow engine configuration.

**Why second:** Establishes quacc patterns before implementing write operations. Low-risk exploration of the quacc API.

**Status:** Complete
**Completed:** 2026-02-02
**Plans:** 4 plans (all complete)

Plans:
- [x] 02-01-PLAN.md — Python quacc module (discovery, engines, config, store)
- [x] 02-02-PLAN.md — RPC handlers (recipes.list, clusters.list, jobs.list)
- [x] 02-03-PLAN.md — Rust models and recipe browser TUI
- [x] 02-04-PLAN.md — Integration tests and bug fixes

### Deliverables

- [x] `recipes.list` RPC handler (enumerate available quacc VASP recipes)
- [x] `clusters.list` RPC handler (list configured executors/clusters)
- [x] `jobs.list` RPC handler (list past job results if any)
- [x] Recipe browser screen in TUI
- [x] Cluster status display

### Technical Notes

- quacc recipes are decorated functions: `@job`, `@flow`, `@subflow`
- List recipes via introspection or hardcoded registry
- Workflow engine detection: check which extras are installed (parsl, covalent, etc.)
- Cluster config stored in local JSON file (not database)

### Success Criteria

- [x] TUI displays available VASP recipes
- [x] TUI shows configured clusters/executors
- [x] Workflow engine (Parsl/Covalent) detected correctly

### Dependencies

- Phase 1 (IPC Foundation)

---

## Phase 3: Structure & Input Handling ✅

**Goal:** Enable users to import structures and configure VASP calculation parameters.

**Why third:** Input handling has no side effects - safe to implement before job submission.

**Status:** Complete
**Completed:** 2026-02-02
**Plans:** 4 plans (all complete)

Plans:
- [x] 03-01-PLAN.md — Python VASP utilities (INCAR, KPOINTS, generator)
- [x] 03-02-PLAN.md — Rust TUI VASP integration
- [x] 03-03-PLAN.md — Structure preview UI
- [x] 03-04-PLAN.md — VASP config form and integration tests

### Deliverables

- [x] Structure import (POSCAR, CIF) via ASE/pymatgen
- [x] Materials Project structure search (`structures.search` RPC)
- [x] Structure preview in TUI (formula, lattice, atom count)
- [x] Recipe parameter configuration form
- [x] Input preview (show generated INCAR, KPOINTS)

### Technical Notes

- Use `ase.io.read()` for multi-format import
- Materials Project API via existing `materials_api/` module
- Recipe parameters map to quacc's calculator kwargs
- Preview generates files without submitting

### Success Criteria

- [x] Import POSCAR file and display structure info
- [x] Search Materials Project by formula
- [x] Configure recipe parameters in TUI
- [x] Preview VASP input files before submission

### Dependencies

- Phase 2 (quacc Integration)

---

## Phase 4: Job Submission & Monitoring

**Goal:** Submit VASP jobs through quacc and track their status.

**Why fourth:** Write operations only after read/input phases validated.

**Status:** Planned
**Plans:** 4 plans

Plans:
- [ ] 04-01-PLAN.md — Python job submission core (POTCAR validation, JobRunner, handlers)
- [ ] 04-02-PLAN.md — Rust TUI job submission (models, cluster selection, keybindings)
- [ ] 04-03-PLAN.md — Job status polling and display (30s interval, progress, errors)
- [ ] 04-04-PLAN.md — Integration tests (MockRunner, handler tests, Rust tests)

### Deliverables

- [ ] `jobs.submit` RPC handler (invoke quacc recipe)
- [ ] Cluster selection UI (choose from configured executors)
- [ ] Job status polling (query workflow engine)
- [ ] Progress display (PENDING -> RUNNING -> COMPLETE)
- [ ] Error display (capture workflow engine errors)

### Technical Notes

- quacc's `@job` decorator handles ASE calculator setup
- Parsl: use `python_app` with `HighThroughputExecutor`
- Covalent: use `ct.dispatch()` with SLURM executor
- Poll interval: 30-60 seconds
- Store job metadata in local JSON for TUI display
- POTCAR validation before submission (fail fast)
- JobRunner abstraction for Parsl/Covalent

### Success Criteria

- [ ] Submit relaxation job from TUI
- [ ] See job status update from PENDING to RUNNING
- [ ] See completion status and basic results
- [ ] Handle submission errors gracefully

### Dependencies

- Phase 3 (Structure & Input)

### Research Completed

- POTCAR validation strategy: Check `VASP_PP_PATH`, verify element directories exist
- Parsl vs Covalent: Both return exceptions via result/get_result, capture in JobMetadata.error_message
- JobRunner abstraction: ABC with submit/get_status/get_result/cancel interface
- MockRunner: For testing without real workflow engines

---

## Phase 5: Results & Advanced Features

**Goal:** Display calculation results and add differentiating features.

**Why fifth:** Core submission workflow validated, can add polish.

### Deliverables

- [ ] Results display (energy, forces, convergence)
- [ ] Output file viewer (OUTCAR, vasprun.xml excerpts)
- [ ] Job history with filtering
- [ ] Custom recipe saving (user presets)
- [ ] Error recovery suggestions (custodian-style)

### Technical Notes

- Parse results via `ase.io.read()` or pymatgen
- Store results in local JSON with job metadata
- Optional: `results_to_db` integration for persistence
- Error recovery: suggest INCAR changes, don't auto-apply

### Success Criteria

- [ ] View energy and forces for completed job
- [ ] Filter job history by status/date
- [ ] Save custom recipe configuration
- [ ] See actionable error suggestions

### Dependencies

- Phase 4 (Job Submission)

---

## Phase 6: Migration & Cleanup

**Goal:** Remove Python TUI and finalize unified architecture.

**Why last:** Can only delete after Rust TUI is fully functional.

### Deliverables

- [ ] Delete `tui/` directory (Python TUI)
- [ ] Remove Textual dependencies from pyproject.toml
- [ ] Update documentation for new architecture
- [ ] Migrate useful code from Python TUI to backend
- [ ] Final integration testing

### Technical Notes

- Preserve useful backend code (runners, templates) if applicable
- Update CLAUDE.md with new architecture
- Archive ADR-002 (Rust TUI secondary policy - no longer applies)

### Success Criteria

- [ ] Python TUI code removed
- [ ] All tests pass
- [ ] Documentation updated
- [ ] `cargo build --release` produces working binary

### Dependencies

- Phase 5 (Results & Advanced Features)

---

## Phase Dependencies Graph

```
Phase 1 (IPC)
    |
Phase 2 (quacc Read)
    |
Phase 3 (Structure/Input)
    |
Phase 4 (Submission)
    |
Phase 5 (Results)
    |
Phase 6 (Migration)
```

All phases are sequential - each depends on the previous.

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| POTCAR license issues | Medium | High | Validate `VASP_PP_PATH`, never distribute POTCARs |
| Workflow engine config complexity | High | Medium | Provide defaults, document thoroughly |
| quacc API changes | Medium | Medium | Pin version, track releases |
| Parsl/Covalent learning curve | Medium | Low | Start with one engine, expand later |
| Results data loss | Low | High | Implement local JSON store |

---

## Out of Scope (v1)

- AiiDA integration (using simpler quacc approach)
- CRYSTAL23/Quantum Espresso support
- High-throughput (10K+ jobs)
- 3D structure visualization
- Mobile/web interface

---

*Roadmap created: 2026-02-02*
*Methodology: GSD (Get Shit Done)*
