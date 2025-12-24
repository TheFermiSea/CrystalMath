# Crystalmath Action Items Checklist

**Created:** December 9, 2025
**Status:** Active

---

## Priority Legend

| Priority | Description |
|----------|-------------|
| P0 | Critical - Blocking core functionality |
| P1 | High - Significant impact on usability |
| P2 | Medium - Affects maintainability |
| P3 | Low - Nice to have improvements |

---

## Phase 1: Critical Fixes (P0)

### [ ] 1.1 Consolidate Exception Hierarchy
**Issue:** CRIT-002, HIGH-001
**Files:** `tui/src/runners/base.py`, `tui/src/runners/exceptions.py`
**Effort:** 2-4 hours

Tasks:
- [ ] Remove duplicate exception classes from `base.py` (lines 516-563)
- [ ] Keep all exceptions in `exceptions.py`
- [ ] Add runner-specific exceptions (SLURMError, SSHError, LocalError) to `exceptions.py`
- [ ] Update imports in `local_runner.py`
- [ ] Update imports in `ssh_runner.py`
- [ ] Update imports in `slurm_runner.py`
- [ ] Update imports in `orchestrator.py`
- [ ] Update `runners/__init__.py` to re-export exceptions
- [ ] Run tests to verify no import errors
- [ ] Update test files if needed

**Verification:**
```bash
grep -r "class.*Error.*Exception" tui/src/runners/
# Should only show exceptions.py
```

---

### [ ] 1.2 Implement Workflow Execution
**Issue:** CRIT-001
**Files:** `tui/src/core/workflow.py`
**Effort:** 8-16 hours

Tasks:
- [ ] Implement `_get_runner()` helper method
- [ ] Implement `_prepare_work_dir()` helper method
- [ ] Implement `_stage_input_files()` helper method
- [ ] Implement `_wait_for_job()` with polling
- [ ] Implement `_parse_results()` for CRYSTAL output
- [ ] Replace stub in `_execute_node()` with real implementation
- [ ] Add cancellation support
- [ ] Add timeout handling
- [ ] Add unit tests for each helper method
- [ ] Add integration test with mock runner
- [ ] Add integration test with real CRYSTAL (optional)

**Verification:**
```python
# Should execute real calculation
node = WorkflowNode(name="test", input_file="mgo.d12")
await workflow._execute_node(node)
assert node.result_data['energy'] < 0
```

---

### [ ] 1.3 Implement Job Cancellation
**Issue:** CRIT-003
**Files:** `tui/src/core/orchestrator.py`
**Effort:** 2-4 hours

Tasks:
- [ ] Implement `cancel_job()` method in orchestrator
- [ ] Call `queue_manager.cancel_job(job_id)`
- [ ] Update job status in database
- [ ] Handle already-completed jobs gracefully
- [ ] Add notification to TUI
- [ ] Add unit test for cancellation
- [ ] Add test for cancelling completed job (should return False)

**Verification:**
```python
job_id = await orchestrator.submit_job(...)
success = await orchestrator.cancel_job(job_id)
assert success is True
job = await db.get_job(job_id)
assert job.status == JobStatus.CANCELLED
```

---

## Phase 2: High Priority Fixes (P1)

### [ ] 2.1 Fix Database Async Safety
**Issue:** HIGH-002
**Files:** `tui/src/core/database.py`
**Effort:** 4-8 hours

Tasks:
- [ ] Option A: Replace `SimpleQueue` with `asyncio.Queue`
- [ ] Option B: Migrate to `aiosqlite` for full async support
- [ ] Update all database operations to be async-safe
- [ ] Add connection timeout handling
- [ ] Add connection retry logic
- [ ] Update tests for async database operations
- [ ] Add concurrency stress test

---

### [ ] 2.2 Fix Encapsulation Violations
**Issue:** HIGH-003
**Files:** `tui/src/runners/ssh_runner.py`, `tui/src/core/connection_manager.py`
**Effort:** 1-2 hours

Tasks:
- [ ] Add `has_cluster(cluster_id: str) -> bool` method to ConnectionManager
- [ ] Add `get_cluster_config(cluster_id: str) -> Optional[ClusterConfig]` method
- [ ] Update SSHRunner to use public methods
- [ ] Update tests

---

### [ ] 2.3 Implement Custom Output Parsers
**Issue:** HIGH-004
**Files:** `tui/src/core/orchestrator.py`
**Effort:** 4-6 hours

Tasks:
- [ ] Define OutputParser protocol/interface
- [ ] Implement default CRYSTAL output parser
- [ ] Add parser registration system
- [ ] Implement parser selection in orchestrator
- [ ] Add example custom parser
- [ ] Add documentation for custom parsers

---

### [ ] 2.4 Fix Abstract Base Classes
**Issue:** HIGH-005
**Files:** `tui/src/tui/widgets/auto_form.py`, `tui/src/runners/base.py`
**Effort:** 2-4 hours

Tasks:
- [ ] Add `@abstractmethod` decorators to FormField
- [ ] Add `@abstractmethod` decorators to BaseRunner
- [ ] Import ABC from abc module
- [ ] Verify all subclasses implement required methods
- [ ] Add type hints to abstract methods

---

### [ ] 2.5 Fix BaseRunner get_output() Stub
**Issue:** HIGH-006
**Files:** `tui/src/runners/base.py`
**Effort:** 2-4 hours

Tasks:
- [ ] Make `get_output()` abstract method
- [ ] Implement in LocalRunner
- [ ] Implement in SSHRunner
- [ ] Implement in SLURMRunner
- [ ] Add tests for output streaming

---

## Phase 3: Medium Priority Fixes (P2)

### [ ] 3.1 Fix Package Discovery
**Issue:** MED-001
**Files:** `tui/pyproject.toml`
**Effort:** 1-2 hours

Tasks:
- [ ] Replace explicit package list with auto-discovery
- [ ] Test installation in fresh virtualenv
- [ ] Verify all modules are included
- [ ] Test editable install still works

---

### [ ] 3.2 Fix Entry Point Configuration
**Issue:** MED-002
**Files:** `tui/pyproject.toml`, `tui/src/main.py`
**Effort:** 1-2 hours

Tasks:
- [ ] Verify entry point matches actual module structure
- [ ] Update documentation if needed
- [ ] Test `crystal-tui` command after installation

---

### [ ] 3.3 Add Graceful Fallbacks for Optional Dependencies
**Issue:** MED-003
**Files:** Multiple (analysis, visualization modules)
**Effort:** 2-4 hours

Tasks:
- [ ] Add try/except imports for CRYSTALpytools
- [ ] Add try/except imports for pymatgen
- [ ] Add try/except imports for ase
- [ ] Display helpful error message when optional dependency missing
- [ ] Add `--check-deps` command to verify dependencies

---

### [ ] 3.4 Clean Up AiiDA Integration
**Issue:** MED-004
**Files:** `tui/src/aiida/`
**Effort:** 2-4 hours

Tasks:
- [ ] Mark AiiDA integration as experimental in README
- [ ] Add feature flag to enable/disable AiiDA
- [ ] Add graceful fallback when AiiDA not installed
- [ ] Update backend.py to handle missing AiiDA

---

### [ ] 3.5 Improve CLI Configuration Validation
**Issue:** MED-005
**Files:** `cli/lib/cry-config.sh`
**Effort:** 2-4 hours

Tasks:
- [ ] Add validation function for environment variables
- [ ] Check CRY23_ROOT exists and contains CRYSTAL
- [ ] Check CRY_SCRATCH_BASE is writable
- [ ] Add helpful error messages for missing config
- [ ] Add `--validate` flag to check configuration

---

## Phase 4: Low Priority Fixes (P3)

### [ ] 4.1 Fix Database Pool Deprecation Warning
**Issue:** LOW-001
**Files:** `tui/src/core/database.py`

Tasks:
- [ ] Remove deprecated `.conn` property
- [ ] Update all callers to use proper pool access

---

### [ ] 4.2 Clean Up Test Suite
**Issue:** LOW-002
**Files:** `tui/tests/`

Tasks:
- [ ] Identify tests that validate stub implementations
- [ ] Mark them as `@pytest.mark.xfail` until feature implemented
- [ ] Add tests for actual implementations
- [ ] Add CI/CD pipeline to run tests

---

### [ ] 4.3 Fix BASH_SOURCE Robustness
**Issue:** LOW-003
**Files:** `cli/lib/cry-config.sh`

Tasks:
- [ ] Add more robust script location detection
- [ ] Test in various sourcing scenarios

---

### [ ] 4.4 Add Keyring Fallback
**Issue:** LOW-004
**Files:** `tui/src/core/connection_manager.py`

Tasks:
- [ ] Detect if keyring backend is available
- [ ] Add fallback to encrypted file storage
- [ ] Add warning when using fallback

---

## Progress Tracking

### Phase 1 Progress
- [ ] 1.1 Exception Hierarchy: Not Started
- [ ] 1.2 Workflow Execution: Not Started
- [ ] 1.3 Job Cancellation: Not Started

### Phase 2 Progress
- [ ] 2.1 Database Async: Not Started
- [ ] 2.2 Encapsulation: Not Started
- [ ] 2.3 Output Parsers: Not Started
- [ ] 2.4 ABC Fixes: Not Started
- [ ] 2.5 get_output() Fix: Not Started

### Phase 3 Progress
- [ ] 3.1 Package Discovery: Not Started
- [ ] 3.2 Entry Point: Not Started
- [ ] 3.3 Optional Deps: Not Started
- [ ] 3.4 AiiDA Cleanup: Not Started
- [ ] 3.5 CLI Validation: Not Started

### Phase 4 Progress
- [ ] 4.1 Deprecation: Not Started
- [ ] 4.2 Test Cleanup: Not Started
- [ ] 4.3 BASH_SOURCE: Not Started
- [ ] 4.4 Keyring Fallback: Not Started

---

## Estimated Total Effort

| Phase | Hours |
|-------|-------|
| Phase 1 (Critical) | 12-24 |
| Phase 2 (High) | 13-24 |
| Phase 3 (Medium) | 8-16 |
| Phase 4 (Low) | 4-8 |
| **Total** | **37-72** |

---

## Notes

- Start with Phase 1 items before moving to Phase 2
- Phase 1.2 (Workflow Execution) is the largest single item
- Phase 1.1 (Exceptions) should be done first as other code depends on it
- Consider using beads issue tracker to track these items:
  ```bash
  cd /Users/briansquires/CRYSTAL23/crystalmath
  bd create "Consolidate Exception Hierarchy" --labels=critical,refactor
  ```

---

*Last Updated: December 9, 2025*
