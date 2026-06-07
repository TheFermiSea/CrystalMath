# Project Research Summary

**Project:** VASP TUI with quacc Backend
**Domain:** Scientific workflow management for computational materials science
**Researched:** 2026-02-02 (updated after quacc pivot)
**Confidence:** MEDIUM-HIGH

## Executive Summary

This project is a Rust-based terminal UI for VASP (Vienna Ab initio Simulation Package) calculations that integrates with quacc for workflow orchestration. Research shows quacc provides a **simpler, more flexible alternative** to the original atomate2+AiiDA approach: it offers workflow-engine-agnostic recipes that work with Parsl, Covalent, Dask, or Prefect while requiring no database infrastructure.

The key architectural decision is to **use quacc with Parsl or Covalent for HPC execution**, eliminating AiiDA complexity (no PostgreSQL, no daemon processes). The Rust TUI communicates with Python via JSON-RPC over Unix domain sockets, maintaining the clean IPC boundary from the original design.

The most critical risks are: (1) POTCAR file management (VASP license compliance), (2) workflow engine configuration per cluster, and (3) results persistence strategy (quacc's `results_to_db` vs local JSON). All are manageable through careful configuration and user documentation.

## Key Findings

### Recommended Stack (Updated)

The stack splits responsibility: **Rust for UI performance, Python for domain complexity via quacc**.

**Core technologies:**
- **ratatui 0.30**: TUI rendering framework (60fps, zero-cost abstractions)
- **JSON-RPC over Unix sockets**: IPC boundary between Rust and Python
- **quacc**: VASP recipes and workflow-engine-agnostic orchestration
- **Parsl or Covalent**: HPC job execution (user choice based on cluster setup)
- **ASE**: Calculator interface (quacc is built on ASE)
- **pymatgen**: Structure manipulation and VASP I/O
- **Python 3.12**: Runtime environment

**Why quacc over atomate2+AiiDA:**
| Aspect | quacc | atomate2+AiiDA |
|--------|-------|----------------|
| Setup complexity | pip install | PostgreSQL + AiiDA daemon + profile setup |
| Workflow engines | Parsl, Covalent, Dask, Prefect | FireWorks, AiiDA native |
| VASP recipes | Built-in (MP-compatible) | atomate2 Makers |
| Provenance | Optional (via results_to_db) | Built-in (AiiDA DB) |
| HPC execution | Parsl pilot jobs, Covalent SLURM | AiiDA daemon + SSH transport |

**Critical version constraints:**
- Pin `quacc>=0.11,<1.0` (active development, API may change)
- Choose ONE workflow engine and stick with it (mixing adds complexity)
- Use Parsl for pilot job model (efficient for many small jobs)
- Use Covalent for traditional SLURM (one job = one SLURM submission)

### Expected Features

**Must have (table stakes):**
- VASP input generation (quacc recipes: relaxation, static, band structure)
- Job submission to SLURM (via Parsl/Covalent executors)
- Job status tracking (workflow engine provides status)
- Output viewing (parse OUTCAR for energy, forces, convergence)
- Error detection and reporting (custodian integration via quacc)
- Structure import (CIF, POSCAR via ASE/pymatgen)

**Should have (competitive differentiators):**
- Materials Project integration (import by mp-id, existing `materials_api/` module)
- Recipe browser (quacc's MP-compatible, QMOF, custom presets)
- Automatic error recovery (custodian-style fixes via quacc)
- Convergence testing workflows (quacc's phonon/elastic recipes)
- Custom recipe definitions (save/load user presets)

**Defer (v2+):**
- Full AiiDA provenance (stick with simpler quacc approach for v1)
- High-throughput batch submission (10K+ jobs needs careful resource management)
- 3D structure visualization (export to VESTA/Avogadro)

### Architecture Approach (Updated)

The architecture uses **IPC boundaries** to separate concerns: Rust TUI communicates with a Python service via JSON-RPC 2.0 over Unix domain sockets. The Python service is a stateless API that dispatches requests to quacc recipes and the chosen workflow engine.

**Major components:**
1. **Rust TUI (ratatui)** - 60fps event loop, keyboard input, state management
2. **IPC Client (Rust)** - JSON-RPC request/response over Unix socket
3. **Python Service (asyncio)** - Request dispatcher, quacc recipe executor
4. **quacc Recipes** - Pre-built VASP workflows (RelaxJob, StaticJob, BandStructureJob)
5. **Workflow Engine** - Parsl or Covalent for HPC execution
6. **Results Store** - Local JSON or optional database via `results_to_db`

**Simplified data flow:**
```
User Input → Rust TUI → JSON-RPC → Python Service → quacc Recipe
                                                        ↓
                                              Parsl/Covalent Executor
                                                        ↓
                                                  SLURM Cluster
                                                        ↓
                                              Results → JSON/DB
```

### Critical Pitfalls (Updated for quacc)

1. **POTCAR Management** - VASP POTCAR files are licensed. quacc uses `VASP_PP_PATH` environment variable. **Mitigation**: Document setup clearly, validate path exists before job submission, never distribute POTCARs.

2. **Workflow Engine Lock-in** - Different workflow engines have different configuration patterns. **Mitigation**: Pick one (recommend Parsl for flexibility), document setup thoroughly, avoid engine-specific code in TUI.

3. **Results Persistence** - quacc doesn't require a database; results can be lost. **Mitigation**: Implement local JSON store with job metadata, offer optional `results_to_db` for users wanting persistence.

4. **Parsl Configuration Complexity** - Parsl's provider/launcher model is powerful but confusing. **Mitigation**: Provide sensible defaults for common SLURM setups, allow expert users to provide custom configs.

5. **Covalent Server Management** - Covalent requires a running server process. **Mitigation**: If using Covalent, auto-start server like the Python service, or document manual setup.

## Implications for Roadmap

### Simplified Phase Structure

**Phase 1: IPC Foundation** (unchanged)
- JSON-RPC server skeleton
- Rust IPC client
- Auto-start logic
- Integration tests

**Phase 2: quacc Integration (Read-Only)**
- List available quacc recipes
- List configured clusters/executors
- Display existing results (if any)
- Validate Parsl/Covalent configuration

**Phase 3: Structure & Input Handling**
- Structure import (POSCAR, CIF via ASE)
- Materials Project search integration
- Recipe parameter configuration
- Input preview in TUI

**Phase 4: Job Submission & Monitoring**
- Submit jobs via quacc recipes
- Workflow engine executor configuration
- Status polling from workflow engine
- Results retrieval and display

**Phase 5: Advanced Features**
- Custom recipe definitions
- Convergence workflows
- Error recovery with user approval
- Results database integration (optional)

### Research Flags (Updated)

Phases needing research during planning:
- **Phase 2 (quacc Integration):** Parsl vs Covalent tradeoffs for specific cluster configurations
- **Phase 4 (Job Submission):** POTCAR validation patterns, executor error handling

Standard patterns (skip research-phase):
- **Phase 1 (IPC):** JSON-RPC 2.0 is well-documented
- **Phase 3 (Structure):** ASE/pymatgen I/O is mature
- **Phase 5 (Advanced):** quacc recipes are documented

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | quacc is actively maintained, Parsl/Covalent are mature |
| Features | HIGH | quacc recipes cover all table stakes features |
| Architecture | MEDIUM-HIGH | IPC boundary unchanged; quacc simplifies backend significantly |
| Pitfalls | MEDIUM | Workflow engine configuration varies by cluster; needs per-site tuning |

**Overall confidence:** MEDIUM-HIGH

The quacc pivot significantly reduces complexity compared to atomate2+AiiDA. Main uncertainties are around workflow engine configuration (site-specific) and POTCAR management (license-dependent).

## Sources

### Primary (HIGH confidence)
- [quacc documentation](https://quantum-accelerators.github.io/quacc/) - Recipes, workflow engines, executors
- [quacc GitHub](https://github.com/Quantum-Accelerators/quacc) - Active development, issues
- [Parsl documentation](https://parsl.readthedocs.io/) - Pilot job model, providers
- [Covalent documentation](https://docs.covalent.xyz/) - SLURM executor, server management
- [ratatui 0.30.0 docs](https://docs.rs/ratatui/0.30.0/ratatui/) - TUI framework API
- [ASE documentation](https://wiki.fysik.dtu.dk/ase/) - Calculator interface
- [pymatgen VASP I/O](https://pymatgen.org/pymatgen.io.vasp.html) - Structure handling

### Secondary (MEDIUM confidence)
- [quacc PyPI](https://pypi.org/project/quacc/) - Version history, dependencies
- [Parsl GitHub issues](https://github.com/Parsl/parsl/issues) - Configuration gotchas
- [Covalent plugins](https://github.com/AgnostiqHQ/covalent-slurm-plugin) - SLURM integration

---
*Research completed: 2026-02-02 (updated after quacc pivot)*
*Ready for roadmap: yes*
