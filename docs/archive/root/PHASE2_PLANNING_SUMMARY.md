# Phase 2 Planning Summary

**Date:** 2025-11-20
**Status:** Planning Complete ✅
**Created By:** Strategic Planning Agent

## Overview

Phase 2 planning is complete for CRYSTAL-TUI. This document summarizes the planning deliverables, created issues, and next steps for implementation.

## Deliverables Created

### 1. Phase 2 Design Document
**Location:** `tui/docs/PHASE2_DESIGN.md`

Comprehensive technical design covering:
- **Remote Execution Architecture** - SSH and SLURM runners with asyncssh
- **Batch Job Management** - Queue manager and multi-select UI
- **Workflow Chaining** - DAG-based multi-step calculations
- **Template Library** - Jinja2-based template system
- **Database Schema Extensions** - Tables for clusters, remote jobs, workflows
- **Testing Strategy** - Unit, integration, and manual testing plans
- **Security Considerations** - Key-based auth, input sanitization
- **Performance Optimization** - Connection pooling, async everything

**Key Architectural Decisions:**
- Use asyncssh (not paramiko) for async SSH operations
- BaseRunner abstract interface for all execution backends
- Connection pooling for SSH efficiency
- Jinja2 for flexible template rendering
- DAG model for workflow dependencies
- SQLite extensions for provenance tracking

### 2. Phase 2 Roadmap
**Location:** `tui/docs/PHASE2_ROADMAP.md`

Detailed 18-week implementation plan with:
- **Week-by-week breakdown** of implementation tasks
- **Issue dependencies** and blocking relationships
- **Testing milestones** for each major component
- **Risk assessment** and mitigation strategies
- **Success metrics** (quantitative and qualitative)
- **Rollout strategy** (alpha → beta → production)
- **Documentation requirements** for users and developers

**Timeline:**
- Weeks 1-8: Core remote execution (SSH + SLURM)
- Weeks 9-10: Batch job management
- Weeks 11-14: Workflow system
- Weeks 15-16: Template library
- Weeks 17-18: Polish and testing

### 3. Issue Tracker (bd/beads)
**Location:** `.beads/beads.db`

Created **12 new issues** for Phase 2 implementation:

#### P0: Core Remote Execution (5 issues)
- **crystalmath-as9** - Create BaseRunner abstract interface
- **crystalmath-fcq** - Extend database schema for remote jobs
- **crystalmath-7o7** - Implement Connection Manager
- **crystalmath-sro** - Implement SSH Runner for remote execution
- **crystalmath-a9n** - Implement SLURM Runner for batch submission

#### P1: Advanced Features (6 issues)
- **crystalmath-d9k** - Implement Queue Manager for job scheduling
- **crystalmath-xev** - Implement Batch Job Submission UI
- **crystalmath-8gv** - Implement Workflow DAG System
- **crystalmath-8bp** - Implement Workflow Orchestrator
- **crystalmath-bj8** - Implement Template System with Jinja2
- **crystalmath-28a** - Implement Template Browser UI

#### P2: Polish (1 issue)
- **crystalmath-168** - Implement Auto-Generated Parameter Forms

All issues include:
- Detailed descriptions
- Implementation guidance
- Testing requirements
- References to design document sections
- Appropriate labels (phase-2, component tags)

## Key Research Findings

### Remote Execution Patterns
- **asyncssh** is the clear choice for async SSH operations (not paramiko)
- Connection pooling provides ~10x performance improvement
- SLURM monitoring via periodic polling (30-60s intervals)
- rsync for efficient large file transfers
- Non-blocking subprocess execution with asyncio

### Workflow Orchestration
- DAG model is industry standard (AiiDA, Fireworks, Snakemake)
- Job chaining requires output parsers between steps
- Conditional execution enables adaptive workflows
- Parameter sweeps best handled with SLURM job arrays

### Batch Job Management
- Priority-based queues prevent scheduler overload
- Rate limiting between submissions (2-5s delay)
- Background workers for async submission
- Progress indicators crucial for user experience

### Template Systems
- Jinja2 provides flexibility and power
- Metadata in template comments enables auto-form generation
- Common patterns: optimization, SCF, bands, DOS, phonons
- Parameter validation prevents invalid inputs

## Architecture Highlights

### Runner Abstraction
```
BaseRunner (abstract)
├── LocalRunner (exists)
├── SSHRunner (new)
│   └── SLURMRunner (new)
└── PBSRunner (future)
```

### Data Flow
```
User Action → Connection Manager → Runner
                                   ↓
                            Remote Host/Scheduler
                                   ↓
                            Result Retrieval
                                   ↓
                            Database Update → UI Refresh
```

### Workflow Execution
```
Workflow Definition (DAG)
    ↓
Orchestrator
    ↓
┌─────────────────────┐
│ Step 1 (no deps)    │ → Execute → Parse Output
└─────────────────────┘
         ↓ (data passes)
┌─────────────────────┐
│ Step 2 (depends: 1) │ → Execute → Parse Output
└─────────────────────┘
         ↓ (data passes)
┌─────────────────────┐
│ Step 3 (depends: 2) │ → Execute → Results
└─────────────────────┘
```

## Implementation Priorities

### Must-Have (P0)
1. SSH remote execution
2. SLURM batch submission
3. Connection management
4. Database extensions

**Without these, Phase 2 cannot function.**

### Should-Have (P1)
5. Batch job UI
6. Queue manager
7. Workflow DAG system
8. Template library

**These provide the major value-add of Phase 2.**

### Nice-to-Have (P2)
9. Auto-generated parameter forms
10. Advanced visualization (future)

**Improves usability but not blocking.**

## Testing Strategy

### Unit Tests
- Mock asyncssh connections
- Test workflow DAG resolution
- Test template rendering
- Test queue priority sorting

### Integration Tests
- Docker SSH server for remote execution
- Mock SLURM commands (sbatch, squeue)
- End-to-end workflow with mock jobs
- Template → Input → Job creation flow

### Manual Testing
- Real SLURM cluster submission
- 3-step workflow (geo opt → SCF → bands)
- 50+ job batch submission
- Connection failure scenarios

## Documentation Created

### For Developers
- `PHASE2_DESIGN.md` - Complete technical design
- `PHASE2_ROADMAP.md` - Implementation plan
- Issue descriptions with code examples

### For Users (To Be Created)
- Remote Cluster Setup Guide
- SSH Configuration Guide
- SLURM Quick Start
- Workflow Creation Guide
- Template Usage Guide

## Success Criteria

Phase 2 will be considered complete when:
- [ ] All 12 issues closed
- [ ] User can submit job to remote SLURM cluster
- [ ] User can execute 3-step workflow
- [ ] User can create job from template
- [ ] Batch submit 50+ jobs without errors
- [ ] Test coverage ≥ 80% on new code
- [ ] All documentation complete
- [ ] At least 3 researchers using remote features

## Risk Mitigation

### Technical Risks
1. **asyncssh complexity** → Study docs, start simple, test early
2. **SLURM access** → Use Docker for testing, community cluster access
3. **Performance** → Connection pooling, rsync, async everything

### Process Risks
4. **Scope creep** → Stick to roadmap, defer nice-to-haves
5. **Testing difficulty** → Set up proper test environments early
6. **Documentation lag** → Write docs as features are implemented

## Next Steps (Immediate)

### Week 1-2 (Foundation)
1. ✅ Review Phase 2 design document
2. ✅ Review Phase 2 roadmap
3. ✅ Create all bd issues (12 issues)
4. ⏳ Assign issues to developers
5. ⏳ Set up test environments:
   - Docker SSH server
   - Access to SLURM test cluster
   - Python asyncssh development environment

### Week 3 (Start Implementation)
6. ⏳ Begin: BaseRunner interface (crystalmath-as9)
7. ⏳ Begin: Database extensions (crystalmath-fcq)
8. ⏳ Research asyncssh API and best practices
9. ⏳ Set up development branch: `feature/phase-2-remote-execution`

## Integration with Phase 1

Phase 2 builds on Phase 1 foundation:
- **Extends LocalRunner** with remote capabilities
- **Enhances Database** with new tables
- **Adds to UI** without breaking existing workflows
- **Backward compatible** - local execution still works

Phase 1 blockers must be resolved first:
- crystalmath-xjk: Complete Core Job Runner
- crystalmath-qt1: Implement New Job Modal Screen
- crystalmath-jmt: Integrate cry23.bashrc Environment

## Long-Term Vision (Phase 3+)

Phase 2 enables future features:
- **PBS/Torque Support** - Additional batch systems
- **Multi-cloud Execution** - AWS, Azure, GCP runners
- **Workflow Templates** - Pre-built calculation sequences
- **Result Analysis** - Compare multiple jobs
- **AiiDA Integration** - Export/import workflows
- **REST API** - Web interface to TUI
- **Collaboration** - Shared projects and results

## Resource Requirements

### Development
- **Time:** 18 weeks (4-5 months)
- **Developers:** 1-2 full-time
- **Test Infrastructure:** SSH server, SLURM cluster access

### Testing
- Docker host for SSH testing
- Access to SLURM cluster (university/lab)
- Sample CRYSTAL input files for workflows

### Documentation
- Technical writer (optional, can be developers)
- User testing feedback sessions
- Tutorial creation and validation

## Acknowledgments

This planning effort included:
- **Research:** Remote execution patterns, workflow systems, batch schedulers
- **Architecture:** Runner abstraction, async patterns, database design
- **Design:** UI mockups, interaction flows, error handling
- **Documentation:** 2 major documents (design + roadmap)
- **Issue Creation:** 12 detailed implementation issues

Special thanks to:
- Gemini-2.5-pro for remote execution research
- asyncssh documentation and community
- AiiDA, Fireworks, Snakemake for workflow inspiration

## Conclusion

Phase 2 planning is **complete and ready for implementation**. The design is sound, the roadmap is detailed, and all issues are tracked. Implementation can begin immediately.

**Key Takeaway:** Phase 2 transforms CRYSTAL-TUI from a local job manager into a comprehensive remote workflow orchestration platform, enabling researchers to manage complex multi-step calculations across local and remote resources from a single, intuitive interface.

---

**View Planning Documents:**
- Design: `tui/docs/PHASE2_DESIGN.md`
- Roadmap: `tui/docs/PHASE2_ROADMAP.md`
- Issues: `bd list -l phase-2`

**Questions?** See CONTRIBUTING.md or open a discussion in the issue tracker.
