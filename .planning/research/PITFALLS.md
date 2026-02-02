# Domain Pitfalls: VASP TUI with AiiDA/atomate2 Backend

**Domain:** Scientific workflow TUI for DFT calculations
**Researched:** 2026-02-02
**Confidence:** MEDIUM-HIGH (verified against official docs and issue trackers)

---

## Critical Pitfalls

Mistakes that cause rewrites, data loss, or complete workflow failures.

---

### Pitfall 1: PyO3 GIL Deadlocks in Async/Multi-threaded Context

**What goes wrong:** The Rust TUI blocks indefinitely when acquiring the Python GIL from a spawned async task. The event loop freezes, making the TUI unresponsive.

**Why it happens:** Python code already holds the GIL when called from Rust. When attempting to acquire the GIL from a different thread (e.g., within `tokio::spawn`), the new thread blocks waiting for the GIL while the original thread waits for the spawned task - creating a circular dependency.

**Consequences:**
- TUI hangs completely, requiring kill -9
- No error message (silent deadlock)
- Users lose unsaved work
- Workflow state becomes inconsistent

**Prevention:**
1. Use `Python::allow_threads()` before entering async blocks that spawn tasks
2. Dedicate a single thread for GIL acquisition; communicate via channels
3. Never call `Python::with_gil()` from within a tokio task unless the outer scope released the GIL
4. Use bounded channels (already implemented in bridge.rs with CHANNEL_BOUND=64) for backpressure

**Detection (warning signs):**
- TUI freezes after triggering Python operations
- `bridge_worker_loop` shows no activity in logs
- `strace` shows thread waiting on futex

**Phase mapping:** Must be addressed in Phase 1 (Bridge Refactoring)

**Sources:**
- [PyO3 GIL Deadlock Discussion](https://github.com/PyO3/pyo3/discussions/3045) (HIGH confidence)
- [PyO3 allow_threads docs](https://docs.rs/pyo3/latest/pyo3/marker/struct.Python.html#method.allow_threads) (HIGH confidence)
- Existing crystalmath bridge.rs implementation review

---

### Pitfall 2: AiiDA Database Schema Version Mismatch

**What goes wrong:** AiiDA refuses to start with cryptic errors about incompatible database schema versions. Users cannot access their calculation history.

**Why it happens:**
- Installing from `develop` branch instead of release version
- Downgrading AiiDA after database has been migrated forward
- Database schema version ahead of code version (no downgrade path exists)
- Multiple AiiDA installations with different versions sharing the same profile

**Consequences:**
- All provenance data becomes inaccessible
- Workflows cannot be resumed or inspected
- May require database restore from backup
- Lost researcher time and trust

**Prevention:**
1. Pin AiiDA version explicitly in requirements: `aiida-core>=2.7.0,<2.8.0`
2. Backup database before any AiiDA upgrade: `verdi storage backup`
3. Document required AiiDA version in TUI installation guide
4. Test schema compatibility during TUI startup and fail-fast with clear message
5. Never install from `develop` branch in production

**Detection (warning signs):**
- Error messages mentioning "schema version"
- `verdi status` fails with migration warnings
- Database file modified time newer than expected

**Phase mapping:** Phase 2 (AiiDA Integration) - implement version checking at startup

**Sources:**
- [AiiDA Database Migration Docs](https://aiida.readthedocs.io/projects/aiida-core/en/v1.0.0b1/developer_guide/core/modifying_the_schema.html) (HIGH confidence)
- [AiiDA Discourse - Schema Version Mismatch](https://aiida.discourse.group/t/update-aiida-core-version-ask-for-db-migration-do-it/43) (MEDIUM confidence)
- [GitHub Issue #2845](https://github.com/aiidateam/aiida-core/issues/2845) (HIGH confidence)

---

### Pitfall 3: SQLite "Database is Locked" Under Concurrent Workflow Submission

**What goes wrong:** When submitting multiple workflows simultaneously, SQLite throws "Database is locked" errors, causing workflow submissions to fail unpredictably.

**Why it happens:**
- SQLite allows only one writer at a time
- AiiDA daemon + TUI + multiple workflows all try to update the same DbSetting row for "last process state change" timestamp
- The shared database model (TUI + daemon) creates write contention

**Consequences:**
- Workflows fail to submit randomly
- Users receive confusing error messages
- Lost trust in the system's reliability
- Potential data corruption if writes overlap

**Prevention:**
1. Use PostgreSQL storage backend (`core.psql_dos`) for any production use with concurrent workflows
2. If SQLite is required: limit concurrent workflow submissions to 1
3. Implement retry logic with exponential backoff for database operations
4. AiiDA v2.7.2+ handles this more gracefully (catches and logs instead of crashing)
5. Consider separate SQLite files for TUI state vs AiiDA provenance

**Detection (warning signs):**
- Intermittent "Database is locked" in logs
- Workflow submission succeeds sometimes, fails other times
- Problems increase with submission rate

**Phase mapping:** Phase 2 (AiiDA Integration) - default to PostgreSQL recommendation, add connection pooling

**Sources:**
- [GitHub Issue #6532](https://github.com/aiidateam/aiida-core/issues/6532) (HIGH confidence)
- [AiiDA Storage Documentation](https://aiida.readthedocs.io/projects/aiida-core/en/stable/topics/storage.html) (HIGH confidence)

---

### Pitfall 4: VASP Restart File Confusion After Failed Calculations

**What goes wrong:** Restarted VASP calculations read stale WAVECAR/CHGCAR files from a previous failed run, leading to incorrect results or unexpected convergence behavior.

**Why it happens:**
- Custodian copies files from previous step, including outputs
- If VASP didn't actually run, output files (OUTCAR, vasprun.xml) appear valid but are from a previous run
- WAVECAR is only written when calculation completes, not mid-SCF
- Parallelization settings (NBANDS, KPAR) must match between restart and original run

**Consequences:**
- Silently incorrect calculation results
- Wasted compute time on doomed restarts
- Difficulty debugging why calculations behave unexpectedly
- Non-reproducible research

**Prevention:**
1. Use atomate2's positive file matching (copies only required restart files)
2. Verify timestamp of restart files matches expected run
3. Include NBANDS/KPAR in restart metadata to ensure consistency
4. Implement checksum validation for restart files
5. Use custodian's WalltimeHandler to force clean STOPCAR writes before timeout

**Detection (warning signs):**
- Restart calculation converges suspiciously fast
- OUTCAR timestamps don't match job submission time
- SCF starting from different energy than expected

**Phase mapping:** Phase 3 (atomate2 Integration) - implement restart file validation

**Sources:**
- [VASP Forum - Restart Procedures](https://www.vasp.at/forum/viewtopic.php?p=26807) (HIGH confidence)
- [Custodian VASP Handlers](http://materialsproject.github.io/custodian/custodian.vasp.handlers.html) (HIGH confidence)
- [aiida-vasp Changelog](https://aiida-vasp.readthedocs.io/en/latest/changelog.html) (HIGH confidence)

---

## Moderate Pitfalls

Mistakes that cause delays, confusion, or technical debt.

---

### Pitfall 5: Jobflow-Remote "Locked Jobs" After Runner Crash

**What goes wrong:** Jobs become stuck in a locked state after the runner process crashes, preventing further processing. Manual intervention required.

**Why it happens:**
- Runner acquires lock before processing job
- Crash occurs mid-operation (SSH timeout, OOM, etc.)
- Lock is never released because cleanup didn't run
- Job appears stuck in progress but nothing is processing it

**Prevention:**
1. Implement lock timeout with automatic cleanup
2. Add `jf admin remove-lock` to troubleshooting guide
3. Use `--break-lock` flag when rerunning stuck jobs
4. Monitor runner.log for crash patterns
5. Set up daemon auto-restart with systemd/supervisord

**Detection (warning signs):**
- `jf job list -v` shows asterisks in Locked column
- Jobs stuck in non-terminal state for longer than expected
- Runner logs show sudden termination

**Phase mapping:** Phase 4 (Workflow Orchestration) - implement lock health monitoring in TUI

**Sources:**
- [Jobflow-Remote Error Handling](https://matgenix.github.io/jobflow-remote/user/errors.html) (HIGH confidence)

---

### Pitfall 6: atomate2 Input Set Deprecation Breaking Workflows

**What goes wrong:** Workflows that worked in production suddenly fail after atomate2 upgrade due to deprecated input set generators.

**Why it happens:**
- atomate2 deprecated `MPGGARelaxSetGenerator` (deadline 2025-01-01)
- `MPMetaGGARelaxSetGenerator` also deprecated, replaced by `MPScanRelaxSet`
- Code using old class names raises DeprecationWarning then fails
- No automatic migration path for saved workflow definitions

**Prevention:**
1. Pin atomate2 version: `atomate2>=0.0.14,<0.1.0`
2. Use new input set names in all new code
3. Add deprecation warning scanner to CI
4. Document migration path when upgrading atomate2
5. Store input set by logical name, resolve to class at runtime

**Detection (warning signs):**
- DeprecationWarning in logs (often ignored)
- Workflows fail after atomate2 upgrade
- Import errors for generator classes

**Phase mapping:** Phase 3 (atomate2 Integration) - use new APIs from the start

**Sources:**
- [atomate2 VASP Documentation](https://materialsproject.github.io/atomate2/user/codes/vasp.html) (HIGH confidence)
- [atomate2 Sets Base](https://materialsproject.github.io/atomate2/reference/atomate2.vasp.sets.base.html) (HIGH confidence)

---

### Pitfall 7: AiiDA Daemon Debug Blindness

**What goes wrong:** Bugs that only appear when running via `engine.submit()` are nearly impossible to debug because breakpoints don't work in daemon processes.

**Why it happens:**
- Daemon spawns separate processes for each workflow
- Source code is loaded at daemon start, not at process execution
- Breakpoints are hit in the daemon process, but no interactive session exists
- Changes to code require daemon restart to take effect

**Prevention:**
1. Use `engine.run()` during development to debug synchronously
2. Restart daemon after code changes: `verdi daemon restart`
3. Add extensive logging at debug level
4. Use `verdi process report PK` for post-mortem analysis
5. Document daemon debugging in developer guide

**Detection (warning signs):**
- Works with `run()`, fails with `submit()`
- Code changes don't seem to take effect
- Breakpoints never trigger

**Phase mapping:** All phases - document in developer guide

**Sources:**
- [AiiDA Daemon Debugging Guide](https://www.aiida.net/news/posts/2025-02-21-how-to-debug-aiida-daemon.html) (HIGH confidence)

---

### Pitfall 8: SLURM Job State Synchronization Lag

**What goes wrong:** TUI shows job as "RUNNING" but it actually completed hours ago, or vice versa. Users make decisions based on stale information.

**Why it happens:**
- TUI polls SLURM queue periodically (not realtime)
- Clock skew between TUI host and SLURM controller
- Network latency in SSH command execution
- `squeue` only shows active jobs; need `sacct` for completed jobs
- Job state transitions can be missed between polls

**Prevention:**
1. Implement hybrid polling: `squeue` for active jobs, `sacct` for recent completions
2. Synchronize clocks using NTP across all systems
3. Add "last synced" timestamp to TUI display
4. Implement webhook/callback for critical state changes (if HPC supports it)
5. Default poll interval of 30-60s with manual refresh option

**Detection (warning signs):**
- Job output files exist but TUI shows "RUNNING"
- Timestamps in TUI don't match SLURM timestamps
- Different poll results seconds apart

**Phase mapping:** Phase 4 (SLURM Integration) - implement robust state sync

**Sources:**
- [SLURM FAQ](https://slurm.schedmd.com/faq.html) (HIGH confidence)
- [UL HPC SLURM Tutorial](https://ulhpc-tutorials.readthedocs.io/en/latest/scheduling/advanced/) (MEDIUM confidence)

---

### Pitfall 9: PyO3 FFI Data Marshaling Type Mismatches

**What goes wrong:** Rust deserializes Python JSON responses incorrectly, leading to runtime panics or silently wrong data.

**Why it happens:**
- Pydantic model in Python serializes differently than Rust expects
- Enum values have different case conventions (Python: lowercase, Rust: PascalCase)
- Optional fields serialized as null vs omitted
- Numeric types (i32 vs i64 vs f64) don't match

**Consequences:**
- Runtime panics in Rust (not caught by Python tests)
- Data corruption if fields are misinterpreted
- Difficult to debug across language boundary

**Prevention:**
1. Use `#[serde(rename_all = "lowercase")]` on Rust enums
2. Define API contract in JSON Schema, validate both sides
3. Add integration tests that exercise full Rust-Python roundtrip
4. Use ApiResponse wrapper pattern (already in crystalmath)
5. Prefer explicit Option<T> over default values

**Detection (warning signs):**
- `serde_json::from_str` errors mentioning unexpected types
- Tests pass in Python, fail in Rust
- Data appears but fields have wrong values

**Phase mapping:** Phase 1 (Bridge Refactoring) - define contract, add roundtrip tests

**Sources:**
- [PyO3 Performance Analysis](https://github.com/PyO3/pyo3/issues/1607) (HIGH confidence)
- Existing crystalmath/models.rs (ClusterType enum example)

---

## Minor Pitfalls

Issues that cause annoyance but are easily fixed.

---

### Pitfall 10: Custodian FrozenJobErrorHandler False Positives

**What goes wrong:** Custodian kills a perfectly good calculation because stdout wasn't updated within the timeout period.

**Why it happens:**
- Default timeout (3600s) too short for large systems
- Some VASP operations (Hessian computation, DOS) don't update stdout frequently
- Dense k-point grids slow each SCF step

**Prevention:**
1. Increase timeout for expensive calculations: `FrozenJobErrorHandler(timeout=21600)`
2. Document timeout configuration in workflow templates
3. Consider disabling for specific workflow types (phonons, DOS)

**Phase mapping:** Phase 3 (atomate2 Integration) - configure sensible defaults

**Sources:**
- [Custodian VASP Handlers](http://materialsproject.github.io/custodian/custodian.vasp.handlers.html) (HIGH confidence)

---

### Pitfall 11: SSH .bashrc Output Breaking AiiDA File Transfer

**What goes wrong:** AiiDA fails to transfer files with "Received message too long" error despite SSH working interactively.

**Why it happens:**
- `.bashrc` contains `echo` statements or other output
- SFTP protocol expects binary data, not text output
- AiiDA's transport layer interprets output as protocol data

**Prevention:**
1. Ensure `.bashrc` guards against non-interactive shells:
   ```bash
   [[ $- != *i* ]] && return
   ```
2. Document this requirement in cluster setup guide
3. Test cluster with `sftp user@host` before adding to AiiDA

**Phase mapping:** Phase 4 (Cluster Management) - add validation during cluster setup

**Sources:**
- [AiiDA Troubleshooting](https://aiida.readthedocs.io/projects/aiida-core/en/stable/intro/troubleshooting.html) (HIGH confidence)

---

### Pitfall 12: TUI Performance Degradation with Large Job Lists

**What goes wrong:** TUI becomes sluggish when displaying hundreds of jobs, making it frustrating to use.

**Why it happens:**
- Fetching all jobs on every refresh
- No pagination in database queries
- Rendering all rows even if not visible
- JSON serialization overhead for large lists

**Prevention:**
1. Implement lazy loading with pagination
2. Use virtual scrolling (only render visible rows)
3. Add filters to reduce result set (status, date range)
4. Cache job list with invalidation on change
5. Limit default query to recent jobs (last 7 days)

**Phase mapping:** Phase 5 (UI Polish) - implement pagination

**Sources:**
- General TUI best practices
- [Admin Magazine - TUI Tools for HPC](https://www.admin-magazine.com/Articles/More-TUI-Tools-for-HPC-Users) (LOW confidence)

---

## Phase-Specific Warnings

| Phase | Topic | Likely Pitfall | Mitigation |
|-------|-------|----------------|------------|
| 1 | Bridge Refactoring | GIL deadlocks | Use allow_threads(), dedicated GIL thread |
| 1 | JSON-RPC | Type mismatches | JSON Schema contract, roundtrip tests |
| 2 | AiiDA Integration | Schema version | Pin version, test at startup |
| 2 | AiiDA Integration | SQLite locks | Recommend PostgreSQL, retry logic |
| 3 | atomate2 | Deprecated APIs | Use new input set classes |
| 3 | atomate2 | Restart file confusion | Validate timestamps, checksums |
| 4 | SLURM | State sync lag | Hybrid squeue/sacct polling |
| 4 | Cluster Setup | SSH .bashrc issues | Validate cluster before adding |
| 5 | UI | Large job lists | Pagination, virtual scrolling |

---

## Sources Summary

### HIGH Confidence (Official Documentation)
- [AiiDA Storage Documentation](https://aiida.readthedocs.io/projects/aiida-core/en/stable/topics/storage.html)
- [Jobflow-Remote Error Handling](https://matgenix.github.io/jobflow-remote/user/errors.html)
- [atomate2 VASP Documentation](https://materialsproject.github.io/atomate2/user/codes/vasp.html)
- [Custodian VASP Handlers](http://materialsproject.github.io/custodian/custodian.vasp.handlers.html)
- [PyO3 Documentation](https://docs.rs/pyo3/latest/pyo3/)
- [AiiDA Daemon Debugging](https://www.aiida.net/news/posts/2025-02-21-how-to-debug-aiida-daemon.html)

### HIGH Confidence (GitHub Issues/Discussions)
- [GitHub #6532 - SQLite Database Locked](https://github.com/aiidateam/aiida-core/issues/6532)
- [GitHub #2845 - Database Migration Error](https://github.com/aiidateam/aiida-core/issues/2845)
- [PyO3 Discussion #3045 - GIL Deadlock](https://github.com/PyO3/pyo3/discussions/3045)

### MEDIUM Confidence (Community/Tutorials)
- [AiiDA Discourse Forums](https://aiida.discourse.group/)
- [VASP Forum](https://www.vasp.at/forum/)
- [NERSC VASP Documentation](https://docs.nersc.gov/applications/vasp/)

---

## Recommendations for Roadmap

1. **Phase 1 MUST address PyO3 GIL handling** - this is a showstopper for any TUI functionality
2. **Phase 2 should default to PostgreSQL** - SQLite issues will cause endless support burden
3. **Phase 3 needs atomate2 version pinning** - deprecations can break production suddenly
4. **Phase 4 requires robust SLURM state sync** - users will lose trust if job states are wrong
5. **All phases need integration tests** - JSON contract mismatches only surface at runtime
