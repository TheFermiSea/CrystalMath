# Phase 2 Implementation Roadmap

**Status:** Planning Complete
**Created:** 2025-11-20
**Target Completion:** Q2 2025

## Overview

This document provides a detailed, prioritized roadmap for implementing Phase 2 features of CRYSTAL-TUI. All issues have been created in the bd (beads) issue tracker with appropriate labels and priorities.

## Issue Summary

**Total Phase 2 Issues:** 12
- **P0 (Critical):** 5 issues - Core remote execution
- **P1 (High):** 6 issues - Batch, workflow, templates
- **P2 (Medium):** 1 issue - Advanced UI

**Issue Labels:**
- `phase-2` - All Phase 2 issues
- `remote-execution` - SSH/SLURM runners
- `batch` - Batch job management
- `workflow` - DAG workflow system
- `templates` - Template library
- `core` - Core infrastructure
- `ui` - User interface components

## Implementation Phases

### Phase 2.1: Core Remote Execution (4-6 weeks)

**Goal:** Enable basic remote job submission and monitoring

**Issues (5):**
1. **crystalmath-as9** - Create BaseRunner abstract interface (P0)
   - **Duration:** 2-3 days
   - **Dependencies:** None
   - **Blocks:** All other runner implementations
   - **Deliverable:** Abstract base class in `src/runners/base.py`

2. **crystalmath-fcq** - Extend database schema for remote jobs (P0)
   - **Duration:** 3-4 days
   - **Dependencies:** None
   - **Blocks:** Connection Manager
   - **Deliverable:** New tables (clusters, remote_jobs), migration logic

3. **crystalmath-7o7** - Implement Connection Manager (P0)
   - **Duration:** 4-5 days
   - **Dependencies:** Database extensions
   - **Blocks:** SSH Runner
   - **Deliverable:** Connection pooling and cluster registry

4. **crystalmath-sro** - Implement SSH Runner for remote execution (P0)
   - **Duration:** 1-2 weeks
   - **Dependencies:** BaseRunner interface, Connection Manager
   - **Blocks:** SLURM Runner
   - **Deliverable:** Full SSH execution with file transfer
   - **Testing:** Requires access to test remote host

5. **crystalmath-a9n** - Implement SLURM Runner for batch submission (P0)
   - **Duration:** 1-2 weeks
   - **Dependencies:** SSH Runner
   - **Blocks:** None (enables batch features)
   - **Deliverable:** SLURM integration with status polling
   - **Testing:** Requires access to SLURM cluster

**Success Criteria:**
- [ ] User can register a remote cluster via database
- [ ] Jobs execute on remote host via SSH
- [ ] SLURM jobs submit and status updates appear in TUI
- [ ] Results automatically download when job completes
- [ ] All remote operations are async (no UI freezing)

**Testing Strategy:**
- Unit tests with mocked asyncssh
- Integration tests with Docker SSH container
- Manual testing on real SLURM cluster

**Risks:**
- asyncssh learning curve
- SLURM cluster access for testing
- File transfer performance for large jobs

**Mitigation:**
- Study asyncssh documentation and examples
- Set up local SSH test server with Docker
- Implement rsync for large file transfers

### Phase 2.2: Batch Job Management (2-3 weeks)

**Goal:** Enable multi-job submission and queue management

**Issues (2):**
6. **crystalmath-d9k** - Implement Queue Manager for job scheduling (P1)
   - **Duration:** 1 week
   - **Dependencies:** SSH/SLURM runners
   - **Blocks:** Batch submission UI
   - **Deliverable:** Priority queue with automatic submission

7. **crystalmath-xev** - Implement Batch Job Submission UI (P1)
   - **Duration:** 1-2 weeks
   - **Dependencies:** Queue Manager
   - **Blocks:** None
   - **Deliverable:** Multi-select UI with batch actions
   - **Testing:** UI snapshot tests

**Success Criteria:**
- [ ] User can select multiple jobs
- [ ] Batch submit works for 10+ jobs
- [ ] Progress indicator shows submission status
- [ ] Queue manager respects priorities
- [ ] Automatic delay between submissions

**Testing Strategy:**
- Mock queue operations
- Test priority sorting
- UI snapshot testing
- Manual testing with 20+ jobs

### Phase 2.3: Workflow System (3-4 weeks)

**Goal:** Enable multi-step calculation workflows

**Issues (2):**
8. **crystalmath-8gv** - Implement Workflow DAG System (P1)
   - **Duration:** 1-2 weeks
   - **Dependencies:** None
   - **Blocks:** Workflow Orchestrator
   - **Deliverable:** DAG model and dependency resolution

9. **crystalmath-8bp** - Implement Workflow Orchestrator (P1)
   - **Duration:** 2 weeks
   - **Dependencies:** Workflow DAG, runners
   - **Blocks:** None
   - **Deliverable:** Multi-step workflow execution
   - **Testing:** Mock workflows with 3-5 steps

**Success Criteria:**
- [ ] User can define 3-step workflow
- [ ] Workflow executes with proper dependency ordering
- [ ] Output from step N passes to step N+1
- [ ] Failed step halts dependent steps
- [ ] Workflow status visible in UI

**Testing Strategy:**
- Unit tests for DAG resolution
- Mock job execution for integration tests
- Manual testing with real workflow (geo opt → SCF → bands)

**Example Workflow:**
```python
workflow = Workflow(
    name="optimization_bands",
    steps=[
        WorkflowStep("geom_opt", "optimization.d12.j2", {}, []),
        WorkflowStep("single_point", "scf.d12.j2", {}, ["geom_opt"]),
        WorkflowStep("bands", "bands.d12.j2", {}, ["single_point"])
    ]
)
```

### Phase 2.4: Template Library (2 weeks)

**Goal:** Enable template-based job creation

**Issues (3):**
10. **crystalmath-bj8** - Implement Template System with Jinja2 (P1)
    - **Duration:** 1 week
    - **Dependencies:** None
    - **Blocks:** Template Browser, Parameter Forms
    - **Deliverable:** Jinja2 template rendering and management

11. **crystalmath-28a** - Implement Template Browser UI (P1)
    - **Duration:** 3-4 days
    - **Dependencies:** Template System
    - **Blocks:** None
    - **Deliverable:** Template selection UI

12. **crystalmath-168** - Implement Auto-Generated Parameter Forms (P2)
    - **Duration:** 4-5 days
    - **Dependencies:** Template System, Template Browser
    - **Blocks:** None
    - **Deliverable:** Dynamic form generation from template metadata

**Success Criteria:**
- [ ] Templates render with Jinja2
- [ ] User can browse template library
- [ ] Parameter form auto-generates from metadata
- [ ] Job created with rendered input
- [ ] At least 5 common templates included

**Template Library (Minimum Viable):**
- `optimization.d12.j2` - Geometry optimization
- `scf.d12.j2` - Single point calculation
- `bands.d12.j2` - Band structure
- `dos.d12.j2` - Density of states
- `phonon.d12.j2` - Phonon calculation

**Testing Strategy:**
- Test template rendering with various parameters
- Test parameter validation
- UI testing for form generation

## Implementation Order (Recommended)

### Week 1-2: Foundation
1. ✅ Create Phase 2 design document
2. ✅ Create all bd issues with detailed descriptions
3. Start: BaseRunner interface (crystalmath-as9)
4. Start: Database extensions (crystalmath-fcq)

### Week 3-4: Remote Execution Core
5. Finish: BaseRunner interface
6. Finish: Database extensions
7. Start: Connection Manager (crystalmath-7o7)
8. Start: SSH Runner (crystalmath-sro)

### Week 5-6: SSH Runner Complete
9. Finish: SSH Runner with file transfer
10. Test: SSH Runner on local Docker container
11. Test: SSH Runner on real remote host
12. Document: SSH configuration guide

### Week 7-8: SLURM Integration
13. Start: SLURM Runner (crystalmath-a9n)
14. Test: SLURM script generation
15. Test: Job submission and monitoring
16. Document: SLURM configuration guide

### Week 9-10: Batch Management
17. Start: Queue Manager (crystalmath-d9k)
18. Start: Batch Submission UI (crystalmath-xev)
19. Test: Batch submission with 20+ jobs
20. Test: Priority queue behavior

### Week 11-12: Workflow Foundation
21. Start: Workflow DAG (crystalmath-8gv)
22. Test: Dependency resolution
23. Start: Workflow Orchestrator (crystalmath-8bp)

### Week 13-14: Workflow Complete
24. Finish: Workflow Orchestrator
25. Test: 3-step workflow (geo opt → SCF → bands)
26. Document: Workflow creation guide

### Week 15-16: Templates
27. Start: Template System (crystalmath-bj8)
28. Create: 5 base templates
29. Start: Template Browser (crystalmath-28a)
30. Start: Parameter Forms (crystalmath-168)

### Week 17-18: Polish & Testing
31. Integration testing across all features
32. Documentation updates
33. User guide creation
34. Performance optimization

## Dependencies Between Issues

```
as9 (BaseRunner) ─┬─> sro (SSH Runner) ─┬─> a9n (SLURM Runner)
                  │                      │
                  └─> 7o7 (Connection)  ─┘
                      └─> fcq (Database)

sro, a9n ─┬─> d9k (Queue Manager) ─> xev (Batch UI)
          │
          └─> 8gv (Workflow DAG) ─> 8bp (Orchestrator)

bj8 (Templates) ─┬─> 28a (Browser)
                 └─> 168 (Forms)
```

## Testing Milestones

### Milestone 1: SSH Execution (Week 6)
- [ ] SSH connection established
- [ ] File transfer works (upload/download)
- [ ] Remote process executes
- [ ] Output streams to TUI

### Milestone 2: SLURM Integration (Week 8)
- [ ] Job submits to SLURM
- [ ] Status polls correctly
- [ ] Job completion detected
- [ ] Results download automatically

### Milestone 3: Batch Operations (Week 10)
- [ ] 20 jobs submit successfully
- [ ] Queue respects priorities
- [ ] UI shows batch progress
- [ ] No scheduler overload

### Milestone 4: Workflow Execution (Week 14)
- [ ] 3-step workflow completes
- [ ] Dependencies resolve correctly
- [ ] Data passes between steps
- [ ] Failed step halts workflow

### Milestone 5: Template System (Week 16)
- [ ] 5 templates available
- [ ] Template browser works
- [ ] Parameter form generates
- [ ] Job created from template

## Documentation Requirements

### User Documentation
- [ ] **Remote Cluster Setup Guide** - How to register clusters
- [ ] **SSH Configuration Guide** - Key setup, known_hosts, etc.
- [ ] **SLURM Quick Start** - First remote job
- [ ] **Batch Submission Guide** - Multi-job workflows
- [ ] **Workflow Creation Guide** - Building multi-step calculations
- [ ] **Template Usage Guide** - Using and creating templates

### Developer Documentation
- [ ] **Runner Interface Spec** - Implementing new runners
- [ ] **Workflow Provenance** - Database schema for workflows
- [ ] **Template Format Spec** - Creating templates
- [ ] **Testing Guide** - Setting up test environments

## Configuration Files

### User Config: `~/.config/crystal-tui/config.toml`
```toml
[clusters.mylab]
hostname = "cluster.example.edu"
username = "username"
key_path = "~/.ssh/id_rsa"
runner_type = "slurm"
default_partition = "compute"

[clusters.hpc_center]
hostname = "login.hpc.edu"
username = "username"
key_path = "~/.ssh/id_ed25519"
runner_type = "ssh"
```

### Template Directory: `~/.config/crystal-tui/templates/`
- User-created templates stored here
- Shipped templates in package data

## Success Metrics

### Quantitative
- [ ] All 12 Phase 2 issues closed
- [ ] Test coverage ≥ 80% on new code
- [ ] No UI freezing during remote operations
- [ ] Batch submit 50+ jobs without errors
- [ ] Workflow with 5 steps completes successfully

### Qualitative
- [ ] SSH connection "just works" with key-based auth
- [ ] SLURM job status updates feel responsive
- [ ] Template system feels intuitive
- [ ] Workflow creation is straightforward
- [ ] Documentation is clear and complete

### User Acceptance
- [ ] At least 3 researchers use remote execution
- [ ] At least 2 researchers use workflow system
- [ ] At least 1 researcher creates custom template
- [ ] No critical bugs reported in first month

## Risk Assessment

### High Risk
1. **asyncssh complexity** - Mitigate: Study docs, start simple
2. **SLURM cluster access** - Mitigate: Docker test environment
3. **File transfer performance** - Mitigate: Use rsync for large files

### Medium Risk
4. **Workflow DAG complexity** - Mitigate: Start with linear workflows
5. **Template parameter validation** - Mitigate: Simple validation first
6. **Connection pooling bugs** - Mitigate: Thorough testing

### Low Risk
7. **UI performance with many jobs** - Mitigate: Pagination
8. **Database schema migration** - Mitigate: Test with backup

## Rollout Strategy

### Alpha Release (Internal Testing)
- Remote execution only (SSH + SLURM)
- Limited to 1-2 test users
- Gather feedback on reliability

### Beta Release (Early Adopters)
- All Phase 2 features enabled
- 5-10 test users
- Focus on usability feedback

### Production Release
- Full documentation complete
- All tests passing
- User guide and tutorials available

## Maintenance Plan

### Post-Release Support
- Monitor for asyncssh issues
- Collect user feedback on workflows
- Add templates as requested
- Bug fixes and performance improvements

### Future Enhancements (Phase 3)
- PBS/Torque support (additional batch systems)
- Parameter sweep UI (visual parameter space)
- Result comparison (side-by-side analysis)
- Export to AiiDA (workflow integration)
- REST API (web interface)

## Appendices

### A. Similar Tools for Inspiration
- **AiiDA** - Workflow provenance and DAG execution
- **Fireworks** - High-throughput workflow management
- **Parsl** - Parallel scripting library
- **Snakemake** - Scientific workflow management

### B. Python Libraries
- **asyncssh** - Async SSH client (primary)
- **Jinja2** - Template rendering
- **SQLite** - Database (already in use)
- **Textual** - TUI framework (already in use)

### C. Design Documents
- `PHASE2_DESIGN.md` - Complete technical design
- `PROJECT_STATUS.md` - Overall project status
- `ARCHITECTURE.md` - System architecture

### D. Issue Tracker
```bash
# View all Phase 2 issues
bd list -l phase-2

# View by priority
bd list -p P0 -l phase-2  # Critical issues
bd list -p P1 -l phase-2  # High priority

# View by component
bd list -l remote-execution
bd list -l workflow
bd list -l templates
```

---

**Next Steps:**
1. Review roadmap with team
2. Assign issues to developers
3. Set up test environments (Docker SSH, SLURM cluster access)
4. Begin implementation with BaseRunner interface
5. Update roadmap as implementation progresses

**Questions? Contact:** See project maintainers in CONTRIBUTING.md
