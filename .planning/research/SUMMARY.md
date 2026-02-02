# Project Research Summary

**Project:** VASP TUI with AiiDA/atomate2 Backend
**Domain:** Scientific workflow management for computational materials science
**Researched:** 2026-02-02
**Confidence:** MEDIUM-HIGH

## Executive Summary

This project is a Rust-based terminal UI for VASP (Vienna Ab initio Simulation Package) calculations that integrates with Python-based workflow orchestration tools (atomate2 and AiiDA). Research shows this is a niche but well-documented domain where the recommended approach is **IPC-based separation**: Rust owns the 60fps UI rendering while Python owns workflow complexity through established libraries (pymatgen, atomate2, AiiDA).

The key architectural decision is to **abandon PyO3 embedding in favor of JSON-RPC over Unix domain sockets**. This decouples Python version dependencies from Rust builds, eliminates GIL deadlock risks, and enables standalone binary distribution. The Python backend should use atomate2 for VASP input generation (simpler, Pydantic-native) with optional AiiDA integration for provenance tracking (requires PostgreSQL but provides full audit trails).

The most critical risks are: (1) PyO3 GIL deadlocks if FFI is still used, (2) SQLite database locking under concurrent workflows, (3) stale VASP restart files producing incorrect results, and (4) AiiDA schema version mismatches losing access to calculation history. All are mitigated through architectural choices (IPC boundary, PostgreSQL backend) and validation patterns (file checksums, version checks).

## Key Findings

### Recommended Stack

The stack splits responsibility: **Rust for UI performance, Python for domain complexity**. Rust uses ratatui (0.30) for 60fps TUI rendering with crossterm as the terminal backend. The bridge layer uses JSON-RPC 2.0 over Unix domain sockets instead of PyO3, eliminating Python version coupling and GIL issues.

**Core technologies:**
- **ratatui 0.30**: TUI rendering framework (only mature option, 60fps zero-cost abstractions)
- **JSON-RPC over Unix sockets**: IPC boundary between Rust and Python (decouples versions, <1ms latency)
- **atomate2 0.0.23**: VASP input generation via Pydantic InputSets (Materials Project standard, community-maintained)
- **AiiDA 2.7+**: Optional workflow engine with provenance (requires PostgreSQL, provides full audit trail)
- **pymatgen 2025.10+**: Structure manipulation and VASP I/O (Materials Project standard, powers atomate2)
- **Python 3.12**: Runtime environment (sweet spot for library support, avoid 3.14)

**Critical version constraints:**
- Pin `atomate2>=0.0.14,<0.1.0` (pre-1.0, breaking changes common)
- Pin `aiida-core>=2.7,<2.8` (schema migrations have no downgrade path)
- Use PostgreSQL for AiiDA in production (SQLite causes concurrent write failures)

### Expected Features

Users currently manage VASP calculations through manual file editing and `sbatch` scripts. The TUI must replicate this workflow with less friction while adding value through automation.

**Must have (table stakes):**
- VASP input generation (MPRelaxSet, MPStaticSet via pymatgen InputSets)
- Job submission to SLURM (existing runner infrastructure)
- Job status tracking (poll `squeue`, parse state)
- Output viewing (parse OUTCAR for energy, forces, convergence)
- Error detection and reporting (existing `VASPErrorHandler` covers 15+ patterns)
- POTCAR management (respect license, concatenate per POSCAR order)
- Structure import (CIF, POSCAR via pymatgen)

**Should have (competitive differentiators):**
- Materials Project integration (import by mp-id, existing `materials_api/` module)
- Real-time progress monitoring (tail OSZICAR via SSH, existing `vasp_progress.py`)
- Automatic error recovery (custodian-style INCAR fixes)
- Template library (atomate2 Makers: RelaxMaker, BandStructureMaker)
- Convergence testing workflows (systematic k-points/ENCUT)
- DAG-based workflow chains (relaxation -> static -> band structure)

**Defer (v2+):**
- High-throughput batch submission (10K+ jobs, requires full AiiDA setup)
- 3D structure visualization (VESTA/Avogadro are better, export to CIF)
- Custom pseudopotential generation (highly specialized, use official POTCAR)
- Full output parsing (pymatgen/py4vasp already exist, parse key results only)

### Architecture Approach

The architecture uses **IPC boundaries** to separate concerns: Rust TUI communicates with a Python service via JSON-RPC 2.0 over Unix domain sockets. The Python service is a stateless API that dispatches requests to atomate2 (input generation), AiiDA (workflow engine), and pymatgen (structure I/O). AiiDA manages provenance in PostgreSQL and dispatches jobs to SLURM clusters via SSH.

**Major components:**
1. **Rust TUI (ratatui)** - 60fps event loop, keyboard input, state management (communicates via IPC)
2. **IPC Client (Rust)** - JSON-RPC request/response over Unix socket (non-blocking, 30s timeout)
3. **Python Service (asyncio)** - Request dispatcher, auto-started by TUI (stateless, background daemon)
4. **atomate2 InputMakers** - VASP input generation via Pydantic validators (RelaxMaker, StaticMaker)
5. **AiiDA Core** - Workflow engine, PostgreSQL ORM, daemon (optional but recommended for provenance)
6. **AiiDA Daemon** - Background job execution, SSH transport, SLURM monitoring

**Key patterns:**
- **Maker Pattern**: Use atomate2's Pydantic InputSets instead of custom templates (battle-tested validation, Materials Project defaults)
- **CalcJob Wrapping**: Wrap atomate2 jobs in AiiDA CalcJobs for provenance and workflow orchestration
- **Query Adapter**: Translate TUI queries to AiiDA QueryBuilder (single source of truth, no SQLite sync)
- **Auto-start Service**: Python daemon auto-launched by Rust TUI if not running (no manual service management)

### Critical Pitfalls

1. **PyO3 GIL Deadlocks** - Async tasks calling `Python::with_gil()` cause silent deadlocks, freezing the TUI. **Mitigation**: Eliminate PyO3 entirely, use IPC boundary with JSON-RPC. If PyO3 is unavoidable, use `Python::allow_threads()` and a dedicated GIL thread.

2. **SQLite Database Locking** - Concurrent workflow submissions hit "Database is locked" errors under write contention. **Mitigation**: Use PostgreSQL for AiiDA in production (default to `core.psql_dos`). If SQLite required, limit concurrent submissions to 1 and implement retry logic.

3. **VASP Restart File Confusion** - Stale WAVECAR/CHGCAR from failed runs produce incorrect results on restart. **Mitigation**: Use atomate2's positive file matching (copies only required files), validate timestamps and checksums, verify NBANDS/KPAR consistency.

4. **AiiDA Schema Version Mismatch** - Installing mismatched AiiDA versions makes all provenance data inaccessible with no downgrade path. **Mitigation**: Pin `aiida-core>=2.7,<2.8`, backup before upgrades (`verdi storage backup`), validate version at TUI startup.

5. **SLURM State Sync Lag** - TUI shows stale job states due to polling gaps and clock skew. **Mitigation**: Hybrid polling with `squeue` (active jobs) and `sacct` (recent completions), 30-60s poll interval, display "last synced" timestamp.

## Implications for Roadmap

Based on research, suggested phase structure emphasizes **foundation before features** and **read before write** to de-risk the IPC boundary and AiiDA integration.

### Phase 1: IPC Foundation
**Rationale:** Eliminates PyO3 GIL deadlock risk before any feature work (critical pitfall #1). Establishes reliable communication layer all subsequent phases depend on.

**Delivers:**
- Python JSON-RPC server skeleton (dispatcher, no handlers)
- Rust IPC client (Unix socket, send/receive)
- Auto-start logic (TUI spawns server if missing)
- Integration test (Rust client talks to Python server)

**Addresses:**
- Decouples Python version from Rust build (STACK.md PyO3 constraint)
- Enables standalone binary distribution

**Avoids:**
- PyO3 GIL deadlocks (PITFALLS.md #1)
- JSON contract mismatches (PITFALLS.md #9 - add roundtrip tests)

**Research flag:** Standard pattern (defined in ADR-003), skip research-phase

### Phase 2: AiiDA Integration (Read-Only)
**Rationale:** Establishes single source of truth (AiiDA database) before implementing write operations. Validates version compatibility and storage backend early.

**Delivers:**
- `jobs.list` handler (query AiiDA, return JSON)
- `clusters.list` handler (query AiiDA computers)
- `templates.list` handler (list available atomate2 InputSets)
- Rust UI updated to display from IPC responses
- PostgreSQL recommendation in setup guide

**Uses:**
- AiiDA QueryBuilder for job listing (ARCHITECTURE.md pattern #4)
- Query adapter to translate TUI filters

**Avoids:**
- AiiDA schema version mismatch (PITFALLS.md #2 - validate at startup)
- SQLite locking issues (PITFALLS.md #3 - recommend PostgreSQL)

**Research flag:** Standard pattern (AiiDA QueryBuilder documented), skip research-phase

### Phase 3: atomate2 Input Generation
**Rationale:** Input generation has no side effects (no cluster communication), safe to implement before job submission. Validates Maker pattern and Pydantic contract.

**Delivers:**
- atomate2 InputSet integration (RelaxMaker, StaticMaker)
- Input preview in TUI (INCAR, KPOINTS display)
- Structure import (POSCAR, CIF via pymatgen)
- Materials Project structure search (existing `materials_api/` module)

**Uses:**
- Maker Pattern (ARCHITECTURE.md pattern #2)
- Pydantic validators for type safety

**Avoids:**
- atomate2 deprecations (PITFALLS.md #6 - use new InputSet classes)
- Custom input validation anti-pattern (ARCHITECTURE.md anti-pattern #4)

**Research flag:** Standard pattern (atomate2 docs comprehensive), skip research-phase

### Phase 4: Job Submission and Monitoring
**Rationale:** Write operations only after read/input phases validated. SLURM integration deferred until workflow engine proven.

**Delivers:**
- VaspCalcJob definition (AiiDA CalcJob wrapping atomate2)
- `jobs.submit` handler (create nodes, submit to AiiDA)
- TUI submission flow (form -> preview -> submit)
- Status polling (AiiDA daemon updates, hybrid squeue/sacct)
- Cluster configuration UI (SSH, SLURM settings)

**Uses:**
- CalcJob Wrapping (ARCHITECTURE.md pattern #3)
- Existing SLURM runner infrastructure

**Avoids:**
- Restart file confusion (PITFALLS.md #4 - validate timestamps/checksums)
- SLURM state sync lag (PITFALLS.md #8 - hybrid polling)
- SSH .bashrc issues (PITFALLS.md #11 - validate cluster before adding)

**Research flag:** Needs research-phase for POTCAR handling strategy (license compliance, atomate2 `VASP_PP_PATH` integration)

### Phase 5: Results and Advanced Features
**Rationale:** Core submission workflow validated, can add differentiators.

**Delivers:**
- Output parser integration (pymatgen for OUTCAR/vasprun.xml)
- Results display in TUI (energy, forces, convergence)
- Automatic error recovery (custodian-style INCAR fixes)
- Convergence testing workflows (k-points/ENCUT variation)
- UI pagination (performance for large job lists)

**Uses:**
- pymatgen parsers (key results only, not full output)
- custodian error handlers (existing `VASPErrorHandler`)

**Avoids:**
- Custodian false positives (PITFALLS.md #10 - configure timeouts)
- TUI performance degradation (PITFALLS.md #12 - pagination, virtual scrolling)

**Research flag:** Needs research-phase for convergence workflow patterns (atomate2 ConvergeWorkchain, jobflow composition)

### Phase Ordering Rationale

- **IPC before features**: Eliminates GIL deadlock risk (highest severity pitfall) before any domain logic
- **Read before write**: Validates communication layer and data models with low-risk queries
- **Input generation before submission**: No side effects, safer to debug serialization issues
- **Monitoring after submission**: Can test with manually submitted jobs during development
- **Advanced features last**: Differentiators require stable base platform

This order minimizes rework if architectural issues surface and provides natural checkpoints for validation.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 4 (Job Submission):** POTCAR handling is license-sensitive, needs compliance strategy. atomate2 `VASP_PP_PATH` configuration and validation patterns.
- **Phase 5 (Convergence Workflows):** atomate2's `ConvergeWorkchain` and jobflow dynamic composition patterns need investigation for TUI integration.

Phases with standard patterns (skip research-phase):
- **Phase 1 (IPC):** ADR-003 defines pattern, JSON-RPC 2.0 is well-documented
- **Phase 2 (AiiDA Read):** QueryBuilder is core AiiDA feature, comprehensive docs
- **Phase 3 (atomate2 Input):** Maker pattern is standard, pymatgen I/O is mature

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All technologies verified via official docs, versions confirmed on PyPI/docs.rs |
| Features | MEDIUM-HIGH | Validated against atomate2, AiiDA-VASP, VASPKIT feature sets; some user workflow inference |
| Architecture | MEDIUM-HIGH | Patterns verified in AiiDA/atomate2 docs; IPC boundary defined in existing ADRs; edge cases around multi-user sockets need testing |
| Pitfalls | MEDIUM-HIGH | Critical pitfalls verified via GitHub issues and official troubleshooting; some mitigation strategies require validation |

**Overall confidence:** MEDIUM-HIGH

Research is comprehensive for core architectural decisions (IPC boundary, atomate2 vs AiiDA). Some implementation details need validation during development (POTCAR paths, multi-user socket permissions, convergence workflow composition).

### Gaps to Address

- **Multi-user socket permissions:** How to handle when multiple users share a login node? Potential: per-user socket in `$XDG_RUNTIME_DIR`, validate during Phase 1 testing.

- **AiiDA profile selection:** How does user switch between AiiDA profiles (e.g., development vs production)? Potential: server restart with different profile, or profile parameter in every request. Validate during Phase 2.

- **POTCAR license compliance:** VASP POTCAR files are licensed. atomate2 has `VASP_PP_PATH` configuration but validation strategy unclear. Research during Phase 4 planning.

- **Long-running job monitoring:** Should TUI poll periodically or should server push updates? Polling is simpler (current recommendation) but push enables real-time updates. Decide during Phase 4 based on user feedback.

- **Error recovery safety:** Custodian can auto-fix INCAR settings, but applying changes without user review is risky. Need approval UI pattern. Design during Phase 5.

## Sources

### Primary (HIGH confidence)
- [ratatui 0.30.0 docs](https://docs.rs/ratatui/0.30.0/ratatui/) - TUI framework API
- [PyO3 0.28.0 docs](https://docs.rs/pyo3/0.28.0/pyo3/) - FFI patterns and GIL handling
- [atomate2 official docs](https://materialsproject.github.io/atomate2/) - VASP workflows and InputSets
- [AiiDA core docs](https://www.aiida.net/) - Workflow engine, CalcJobs, QueryBuilder
- [pymatgen VASP I/O](https://pymatgen.org/pymatgen.io.vasp.html) - Structure handling
- [Custodian VASP handlers](http://materialsproject.github.io/custodian/custodian.vasp.handlers.html) - Error recovery
- Existing ADR-003 (IPC Boundary Design) - Architecture decision record
- Existing ADR-002 (Rust TUI Secondary Policy) - PyO3 constraints

### Secondary (MEDIUM confidence)
- [GitHub #6532](https://github.com/aiidateam/aiida-core/issues/6532) - SQLite locking issues
- [GitHub #2845](https://github.com/aiidateam/aiida-core/issues/2845) - Schema migration errors
- [PyO3 Discussion #3045](https://github.com/PyO3/pyo3/discussions/3045) - GIL deadlock patterns
- [AiiDA Discourse](https://aiida.discourse.group/) - Community troubleshooting
- [VASP Forum](https://www.vasp.at/forum/) - Restart file behavior
- [Atomate2 RSC paper (2025)](https://pubs.rsc.org/en/content/articlehtml/2025/dd/d5dd00019j) - Workflow patterns

### Tertiary (LOW confidence)
- [VASPilot multi-agent platform](https://github.com/deepmodeling/VASPilot) - New tool (2025), limited adoption data
- [Admin Magazine - TUI Tools for HPC](https://www.admin-magazine.com/Articles/More-TUI-Tools-for-HPC-Users) - General TUI patterns

---
*Research completed: 2026-02-02*
*Ready for roadmap: yes*
