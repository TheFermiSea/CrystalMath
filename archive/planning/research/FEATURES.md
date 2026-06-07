# Feature Landscape: VASP TUI with AiiDA/atomate2 Backend

**Domain:** VASP workflow management TUI for computational materials scientists
**Researched:** 2026-02-02
**Confidence:** MEDIUM-HIGH (verified against atomate2, AiiDA-VASP, custodian official docs)

## Table Stakes

Features users expect. Missing = product feels incomplete or users revert to CLI.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **VASP Input Generation** | All workflow tools provide this | Medium | Use pymatgen InputSets (MPRelaxSet, etc.) - already standard |
| **Input Validation (Pre-submission)** | Prevents wasted queue time from obvious errors | Medium | Check INCAR tag validity, POSCAR structure, POTCAR match |
| **Job Submission to SLURM** | HPC is the only realistic environment | Low | Existing SLURM runner in codebase handles this |
| **Job Status Tracking** | Users need to know job state without SSH | Low | Poll SLURM `squeue`, parse job state |
| **Output Viewing** | Users need to see results | Low | Parse OUTCAR for energy, bandgap, convergence |
| **Error Detection & Reporting** | 90%+ of VASP runs encounter errors | Medium | Existing `vasp_errors.py` covers 15+ patterns |
| **Cluster Configuration** | Multi-cluster environments are standard | Low | Existing ClusterConfig model handles this |
| **POTCAR Management** | Required for every VASP run | Medium | Respect license, concatenate per POSCAR order |
| **K-point Mesh Generation** | Every VASP run needs KPOINTS | Low | pymatgen automatic Gamma/Monkhorst-Pack |
| **Structure Import (CIF, POSCAR)** | Scientists start from structures | Low | pymatgen handles all common formats |

### Why These Are Table Stakes

Based on atomate2, AiiDA-VASP, and VASPKIT feature sets, these are the minimum expected by computational materials scientists who currently use CLI tools. Without them, users have no reason to adopt a TUI over their current workflow.

**Critical insight:** Scientists currently use a combination of:
- Manual file editing (INCAR, POSCAR, KPOINTS)
- `sbatch` scripts for submission
- `squeue` for monitoring
- Manual OUTCAR inspection

A TUI must at minimum replicate this workflow with less friction.

## Differentiators

Features that set the product apart. Not expected, but highly valued.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Automatic Error Recovery** | Apply custodian-style fixes without user intervention | High | Detect error, suggest INCAR change, offer one-click restart |
| **Convergence Testing Workflows** | Systematic k-points/ENCUT testing in single submission | High | atomate2 and AiiDA-VASP both provide this as premium feature |
| **Materials Project Integration** | Import structures by mp-id, compare results to MP data | Medium | Existing `materials_api/` module partially implements |
| **Real-time Progress Monitoring** | SCF cycle-level progress during run | Medium | Tail OSZICAR/OUTCAR via SSH, existing `vasp_progress.py` |
| **Template Library** | Pre-built workflows for common calculation types | Medium | atomate2's Makers pattern - RelaxMaker, BandStructureMaker, etc. |
| **Input Syntax Highlighting** | Visual feedback in INCAR editor | Low | VS Code extension exists, tui-textarea with highlighting |
| **Batch Submission** | Submit multiple similar calculations at once | Medium | High-throughput workflows - vary one parameter across jobs |
| **DAG-based Workflows** | Relaxation -> Static -> Band Structure chains | High | AiiDA core strength, existing workflow orchestrator |
| **Provenance Tracking** | Full history of calculation lineage | High | AiiDA's defining feature - optional but valuable |
| **Smart POTCAR Selection** | Auto-recommend POTCARs based on system (GW vs standard) | Low | pymatgen POTCAR recommendations exist |
| **SLURM Resource Estimation** | Suggest walltime/memory based on system size | Medium | Historical data + heuristics |
| **Interactive Convergence Plots** | Visualize energy vs k-points in TUI | Medium | ratatui charts, tui-chart crate |

### Differentiator Analysis

**Highest value / medium complexity:**
1. **Materials Project Integration** - Existing codebase has foundation, unique among TUIs
2. **Real-time Progress Monitoring** - Existing `vasp_progress.py` makes this achievable
3. **Automatic Error Recovery** - Custodian patterns documented, `vasp_errors.py` has foundation

**Highest value / high complexity:**
1. **Convergence Testing Workflows** - AiiDA-VASP's `ConvergeWorkchain` and atomate2's convergence patterns
2. **DAG-based Workflows** - Already have orchestrator, need VASP-specific flows

## Anti-Features

Features to explicitly NOT build. Common mistakes in this domain.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Built-in DFT Engine** | VASP is licensed, complex, HPC-only | Always submit to external VASP binary via SLURM |
| **Full Output Parsing** | Massive scope creep, pymatgen/py4vasp already do this | Parse only key results (energy, bandgap, convergence, forces) |
| **3D Structure Visualization** | TUI cannot compete with VESTA/Avogadro | Export to CIF, let user visualize externally |
| **Automatic Magnetic Moment Detection** | Notoriously unreliable for complex systems | Provide reasonable defaults, let user override |
| **"One-click" High-throughput** | Requires deep AiiDA setup, PostgreSQL, daemon | Offer batch submission (10-50 jobs), not 10K jobs |
| **Custom Pseudopotential Generation** | Highly specialized, POTCAR files are provided | Use official POTCAR files only |
| **Universal Input Validation** | VASP has thousands of tag combinations | Validate common errors, accept unknown tags |
| **Automatic Functional Selection** | Highly system-dependent (PBE vs HSE vs r2SCAN) | Provide templates, let user select |
| **Live VASP Process Attachment** | Requires complex terminal multiplexing | Show tail of output, link to SSH for full terminal |
| **Competing with VASPKIT** | Mature tool with 5+ years of development | Focus on workflow orchestration, not post-processing |
| **GUI Electron App** | Cross-platform complexity, HPC network restrictions | TUI works over SSH, runs on headnode |

### Anti-Feature Rationale

**The key insight:** Users already have excellent tools for:
- Structure manipulation (pymatgen, ASE, VESTA)
- Output analysis (py4vasp, VASPKIT, pymatgen)
- High-throughput (atomate2, AiiDA)

The TUI's value is **workflow orchestration and monitoring** - the glue between these tools. Don't rebuild what exists.

## Feature Dependencies

```
                    ┌─────────────────────────┐
                    │  Structure Import       │
                    │  (CIF, POSCAR, mp-id)   │
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │  Input Generation       │
                    │  (pymatgen InputSets)   │
                    └───────────┬─────────────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          │                     │                     │
┌─────────▼────────┐ ┌─────────▼────────┐ ┌─────────▼────────┐
│ Input Validation │ │ POTCAR Assembly  │ │ K-point Mesh     │
│ (INCAR checks)   │ │ (concatenate)    │ │ (automatic)      │
└─────────┬────────┘ └─────────┬────────┘ └─────────┬────────┘
          │                    │                     │
          └────────────────────┼─────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   Job Submission    │
                    │   (SLURM sbatch)    │
                    └──────────┬──────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
┌─────────▼────────┐ ┌────────▼────────┐ ┌────────▼────────┐
│ Status Tracking  │ │ Progress Monitor│ │ Error Detection │
│ (squeue poll)    │ │ (OSZICAR tail)  │ │ (OUTCAR parse)  │
└─────────┬────────┘ └────────┬────────┘ └────────┬────────┘
          │                   │                    │
          └───────────────────┼────────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │  Result Parsing   │
                    │  (key values)     │
                    └─────────┬─────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
┌────────▼────────┐ ┌────────▼────────┐ ┌────────▼────────┐
│Error Recovery   │ │Convergence Viz  │ │MP Comparison    │
│(auto-fix)       │ │(charts)         │ │(vs DB values)   │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

**Critical path for MVP:**
Structure Import -> Input Generation -> Job Submission -> Status Tracking -> Result Parsing

**Phase 2 additions:**
Input Validation, Error Detection, Progress Monitoring

**Phase 3 additions:**
Error Recovery, Convergence Workflows, MP Comparison

## MVP Recommendation

For MVP, prioritize these table stakes (in order):

1. **VASP Input Generation** - Core value proposition
   - Use pymatgen InputSets (MPRelaxSet, MPStaticSet)
   - Support manual INCAR override
   - Auto-generate KPOINTS based on structure

2. **Job Submission to SLURM** - Already implemented in codebase
   - Use existing `slurm_runner.py`
   - Generate SLURM script from template

3. **Job Status Tracking** - Already implemented
   - Use existing `SlurmQueueEntry` model
   - Real-time status in TUI job list

4. **Output Viewing** - Basic results
   - Parse final energy, convergence status
   - Show error summary if failed

5. **Error Detection** - Already implemented
   - Use existing `VASPErrorHandler`
   - Show suggestions for recovery

**One differentiator for MVP:**
- **Materials Project Integration** - Import structures by mp-id
  - Foundation exists in `materials_api/` module
  - Unique value vs CLI workflow

### Defer to Post-MVP

| Feature | Reason to Defer |
|---------|-----------------|
| Convergence Testing Workflows | Requires workflow orchestrator changes |
| Automatic Error Recovery | Needs robust testing, risky to auto-modify jobs |
| DAG-based Workflows | Complex, AiiDA integration path preferred |
| Batch Submission | Single-job workflow must work first |
| Interactive Plots | Cosmetic, core functionality first |
| Provenance Tracking | Requires AiiDA backend commitment |
| Template Library | Need user feedback on which workflows needed |

## Competitive Landscape

| Tool | Strengths | Weaknesses | Our Opportunity |
|------|-----------|------------|-----------------|
| **atomate2** | 100+ workflows, MP-backed | Python-only, no TUI, complex setup | TUI for atomate2 workflows |
| **AiiDA-VASP** | Provenance, robust workflows | PostgreSQL dependency, learning curve | Simpler entry point |
| **VASPKIT** | Comprehensive post-processing | CLI-only, no workflow management | Complement, don't compete |
| **VASPilot (2025)** | Multi-agent AI, web UI | New/unproven, agent complexity | Simpler, proven approach |
| **py4vasp** | Modern VASP output parsing | Output-only, no submission | Use for result parsing |
| **Manual CLI** | Full control | Tedious, error-prone | Primary replacement target |

**Our unique position:** A TUI that sits on top of pymatgen/atomate2 for input generation, integrates with SLURM for submission, and provides Materials Project structure import - without requiring full AiiDA/PostgreSQL setup.

## Sources

### HIGH Confidence (Official Documentation)
- [atomate2 VASP Documentation](https://materialsproject.github.io/atomate2/user/codes/vasp.html)
- [AiiDA-VASP Workflows](https://aiida-vasp.readthedocs.io/en/latest/concepts/workflows.html)
- [Custodian VASP Handlers](http://materialsproject.github.io/custodian/custodian.vasp.handlers.html)
- [pymatgen VASP IO](https://pymatgen.org/pymatgen.io.vasp.html)

### MEDIUM Confidence (Verified with Multiple Sources)
- atomate2 GitHub: 100+ workflows, PBE_54 defaults
- AiiDA live monitoring (Jan 2026 release): Real-time calculation monitoring
- VASPKIT features: Pre/post-processing, convergence testing
- Custodian error patterns: 20+ known VASP error types

### LOW Confidence (WebSearch Only - Validate)
- VASPilot multi-agent platform (2025): New tool, limited adoption data
- VASP GUI Streamlit app: Community tool, stability unknown
- Specific user workflow pain points: Based on forum discussions
