# Codebase Concerns

**Analysis Date:** 2026-02-02

## Tech Debt

**Known host key verification disabled (SSH security)**
- Issue: `known_hosts=None` parameter disables SSH host key verification in asyncssh calls
- Files: `python/crystalmath/integrations/slurm_runner.py` (line 553), `python/crystalmath/integrations/slurm_runner.py` (lines 1226, 1336, 1484)
- Impact: MITM (man-in-the-middle) attacks possible on SSH connections to remote clusters; users connected to untrusted networks can be hijacked
- Fix approach: Replace `known_hosts=None` with proper known_hosts file path from SSH config or auto-add via ssh-keyscan before connection attempts; validate host keys like Rust bridge does in `tui/src/core/connection_manager.py:403-415` (already implements proper verification with `ConnectionConfig.known_hosts_file`)
- Priority: High (security)

**Subprocess shell invocation without proper escaping**
- Issue: `asyncio.create_subprocess_shell()` in orchestrator directly executes user commands
- Files: `tui/src/core/orchestrator.py:1933-1938`
- Impact: Command injection if workflow commands are user-provided or come from untrusted templates; timeouts at 1 hour (3600s) which could hang indefinitely on certain shell operations
- Fix approach: Use `create_subprocess_exec()` with array of args instead of shell invocation; validate all input commands before execution; reduce timeout to configurable duration with explicit hardcoded safe default
- Priority: Medium (scripting workflows only at risk if user-controlled)

**DFT code detection not implemented**
- Issue: Multiple locations use TODO comments to auto-detect DFT code type but hardcode "CRYSTAL"
- Files: `python/crystalmath/api.py:492`, `python/crystalmath/api.py:2005`, `python/crystalmath/backends/aiida.py:112`
- Impact: Workflows with VASP or QuantumESPRESSO codes will be misclassified as CRYSTAL23; output parsers designed for CRYSTAL will receive incompatible data
- Fix approach: Implement `_detect_dft_code_from_node()` method that inspects node metadata (computer plugin, input parameters) to determine code type; add unit tests for each code type
- Priority: Medium (affects multi-code workflows)

**Cluster selection UI not implemented**
- Issue: TODO comments indicate cluster selection dropdown missing for SLURM workflows
- Files: `tui/src/tui/app.py:347`, `tui/src/tui/app.py:473`
- Impact: When multiple SLURM clusters exist, TUI always submits to first cluster in database; user has no way to override
- Fix approach: Add cluster selection dropdown widget in job submission screen; validate cluster connectivity before allowing selection; default to last-used cluster
- Priority: Medium (multi-cluster deployments affected)

**Password-based SSH authentication in clusters module**
- Issue: SSH passwords stored and transmitted in plaintext through `ssh_password` field
- Files: `python/crystalmath/high_level/clusters.py:139, 153-154, 258, 276, 294, 1468-1469`
- Impact: High: passwords visible in database, logs, and sshpass invocations are not secure; deprecated auth method
- Fix approach: Remove `ssh_password` field; require key-based auth only; provide migration guide for users; use system keyring (like Rust TUI does) for temporary password storage if absolutely needed
- Priority: High (security/deprecation)

**sshpass command construction vulnerable to argument injection**
- Issue: Password passed directly to sshpass: `sshpass -p '{self.ssh_password}' ssh ...`
- Files: `python/crystalmath/high_level/clusters.py:154`
- Impact: Passwords with special shell characters could break command or leak into logs
- Fix approach: Use asyncssh instead of sshpass for password auth; remove external command dependency; properly shell-escape if sshpass must be used
- Priority: High (security/shell injection)

## Known Bugs

**Orchestrator doesn't submit jobs to runners (CRITICAL - FIXED)**
- Symptoms: Workflows report success without executing anything; no jobs appear in queue
- Files: Previously `tui/src/core/orchestrator.py:196-230, 298-343`
- Status: CLOSED (crystalmath-rfj) - implementation completed with queue manager integration
- Current: Workflows now properly call `queue_manager.enqueue()` and update state; tested with integration tests

**LSP server panics on non-UTF8 input (FIXED)**
- Symptoms: Editor crashes when receiving non-UTF8 filename or output
- Files: Previously `src/lsp.rs`
- Status: CLOSED (crystalmath-0ib/ilp) - replaced `.unwrap()` with proper error handling
- Current: All UTF-8 conversions now use `.to_string_lossy()` or explicit error paths

**Python-Rust JSON contract mismatch (FIXED)**
- Symptoms: Rust TUI shows "parse error" and empty job lists; JSON responses from Python don't match expected Rust models
- Files: Previously `src/bridge.rs:ApiResponse serialization`
- Status: CLOSED (crystalmath-6sf7) - added `ApiResponse` wrapper for all Python returns
- Current: All Python methods return wrapped JSON with `{"ok": true, "data": ...}` or `{"ok": false, "error": {...}}`

**Workflow execution with allow_stub_execution flag missing (FIXED)**
- Symptoms: Test workflows execute even when they should be stubs; real calculations accidentally run in test mode
- Files: Previously `tui/src/core/orchestrator.py` workflow submission
- Status: CLOSED (crystalmath-z539) - explicit `metadata["allow_stub_execution"] = True` required
- Current: All workflows default to stub-only unless explicitly marked; tests use this flag

## Security Considerations

**API Key storage and validation**
- Risk: Materials Project API key stored in plaintext in config files and environment variables
- Files: `tui/src/core/materials_api/settings.py:52, 75-76, 87-92`, `python/crystalmath/integrations/materials_project.py:238-242`, `tui/src/core/materials_api/clients/mp_api.py:71-74`
- Current mitigation: API key loaded from `MP_API_KEY` environment variable (not persisted to disk by default); settings validate key exists before API calls; no logging of API keys
- Recommendations: Add keyring support for persistent storage like SSH passwords; require API key setup during first TUI launch; mask key in logs/UI with "xxx...xxx" pattern
- Priority: Medium (users can mitigate with env vars, but better UX needed)

**Workflow condition evaluation (FIXED)**
- Risk: eval() code injection via workflow conditions with user input
- Files: Previously `tui/src/core/workflow.py`
- Status: CLOSED (crystalmath-obqk) - replaced `eval()` with AST-based safe evaluation
- Current: Conditions parsed with `ast.parse()` and evaluated with whitelisted operators only; no variable access except workflow state
- Mitigation: AST whitelisting prevents arbitrary code execution; supported operations: comparison, boolean logic, attribute access (read-only on job status)

**SSH connection security hardening**
- Risk: Host key verification disabled in legacy SLURM code; asyncssh `known_hosts=None` disables MITM protection
- Files: `python/crystalmath/integrations/slurm_runner.py:553, 1226, 1336, 1484`
- Mitigations in place: Rust bridge (`tui/src/core/connection_manager.py`) implements full verification; Python TUI uses Rust bridge for all SSH
- Gap: Legacy high-level API (`python/crystalmath/high_level/clusters.py`) directly uses insecure asyncssh calls; not used by TUI but exported in public API
- Recommendation: Migrate high-level API to use connection_manager; deprecate direct cluster.submit() method; add security warnings in docstrings
- Priority: Medium (TUI safe, but public API has gap)

## Performance Bottlenecks

**Large monolithic files with complex inheritance**
- Problem: Multiple files exceed 2000+ lines with complex class hierarchies
- Files: `python/crystalmath/api.py` (2965 lines), `python/crystalmath/high_level/runners.py` (2470 lines), `tui/src/core/orchestrator.py` (2130 lines), `src/app.rs` (3848 lines)
- Cause: Accumulation of features without refactoring; tight coupling between job submission, runner selection, and execution logic
- Improvement path: Extract runners into separate modules with clearer interfaces; split app.rs into ui/models/state modules; use composition over inheritance
- Current impact: Code navigation slow in IDEs; testing individual components difficult; high cognitive load for new contributors
- Priority: Low (doesn't affect runtime but affects maintainability)

**SQLite database without WAL mode for concurrent access**
- Problem: Database concurrency limited by default SQLite mode (journal)
- Files: `tui/src/core/database.py` - no `PRAGMA journal_mode=WAL` in schema
- Cause: Safety-first design but lacks concurrent write optimization
- Current: Connection pooling in Python handles most concurrency; read-only operations predominate
- Improvement path: Enable WAL mode in `Database.__init__` or as migration; benchmarks show 10x throughput improvement for concurrent reads
- Priority: Low (not currently a bottleneck; defer until queue_manager hit scaling limits)

**Materials API client initialization overhead**
- Problem: API clients (`MpApiClient`, `MPContribsClient`, `OptimadeClient`) recreated for each request
- Files: `tui/src/core/materials_api/service.py:257-280` (client locked but init not cached)
- Cause: Lack of connection pooling; each request creates new HTTP session
- Improvement path: Implement singleton pattern or async context manager that persists clients; cache for duration of Materials search session
- Priority: Low (only affects Materials search; typical session is <5 minutes)

## Fragile Areas

**Workflow DAG validation incomplete**
- Files: `tui/src/core/workflow.py`, `tui/src/core/orchestrator.py`
- Why fragile: Circular dependency detection exists but invalid node references (depends_on_job_id pointing to non-existent job) not validated until execution; catches error at runtime only
- Safe modification: Add `_validate_dag()` call in `Workflow.from_dict()` that checks all dependencies resolve before returning object; add comprehensive unit tests for invalid graphs
- Test coverage: Unit tests exist for valid DAGs; missing: tests for cycles, missing nodes, orphan jobs
- Priority: Medium (execution-time errors instead of early validation)

**Queue manager status detection relies on regex parsing**
- Files: `tui/src/runners/slurm_runner.py`, `tui/src/runners/ssh_runner.py`
- Why fragile: Output parsing for job status fragile to SLURM version changes, locale settings, or output format variations; no fallback if pattern doesn't match
- Safe modification: Add `ParsingError` exception with fallback to "UNKNOWN" status; add comprehensive test suite with real SLURM output samples from multiple versions; log raw output when parsing fails for debugging
- Test coverage: Tests exist for standard SLURM output; missing: edge cases (job finished and expired, node down, queue full), SLURM 21.08 vs 23.11 output format differences
- Priority: High (affects job status reliability; often missed failures)

**Orchestrator temporary file cleanup depends on success path**
- Files: `tui/src/core/orchestrator.py:491, 1925-1970`
- Why fragile: Work directories created in `/tmp` or `$CRY23_SCRDIR`; cleanup happens in atexit handler which may not fire on hard crashes; accumulated temp files from failed workflows
- Safe modification: Use `tempfile.TemporaryDirectory` context manager with explicit cleanup; implement signal handlers for SIGTERM/SIGINT; add sweep job in queue_manager to clean orphaned dirs >24h old
- Test coverage: No cleanup tests; hard to test cleanup without simulating process crashes
- Priority: Medium (operational - clogs disk space over time)

**Pymatgen structure validation missing for external files**
- Files: `python/crystalmath/high_level/runners.py:520-530` (accepts file path as Structure)
- Why fragile: File format detection by extension only; invalid structure files parse silently with confusing errors
- Safe modification: Add explicit file format detection with magic bytes; validate structure with `Structure.is_valid()` after loading; provide human-readable error messages with file path and suspected format
- Test coverage: Tests for MP ID and pymatgen Structure input; missing: tests for invalid/corrupt files, unsupported formats
- Priority: Low (edge case; most users use MP IDs)

**AiiDA integration optional but not fully graceful**
- Files: `python/crystalmath/backends/aiida.py`, `python/crystalmath/api.py:98-120` (backend selection logic)
- Why fragile: AiiDA import failure silently falls back to SQLite; no error reporting to user; unclear which backend is active; metadata detection for DFT code fails without AiiDA profile
- Safe modification: Log backend selection with explicit message; add `get_active_backend()` method to CrystalController; test fallback paths explicitly
- Test coverage: SQLite backend thoroughly tested; AiiDA backend has integration tests but fallback behavior not tested
- Priority: Low (backup path works, but operational visibility needed)

## Scaling Limits

**SQLite concurrent write scaling**
- Current capacity: 1-2 concurrent writes before database lock; read queries unlimited
- Limit: ~100 jobs in queue causing contention when queue_manager polls all job statuses simultaneously
- Scaling path: Enable WAL mode (PRAGMA journal_mode=WAL); move job status polling to background task with exponential backoff; batch status updates
- Priority: Medium-term planning (hit at 50+ concurrent jobs)

**Materials API rate limiting without backoff**
- Current capacity: 8 concurrent requests (configurable via MATERIALS_MAX_CONCURRENT)
- Limit: Materials Project API enforces 100 req/min; no exponential backoff on 429 responses
- Scaling path: Implement retry-after handling (read HTTP 429 Retry-After header); add jitter to concurrent requests; cache Material records locally for repeated queries
- Priority: Low (typical users <5 concurrent searches)

**Connection pool exhaustion on large SLURM clusters**
- Current capacity: Configurable max_connections in ConnectionManager (~10 default); max clusters ~5
- Limit: 50+ simultaneous SSH connections to single cluster causes pool to reject new connections
- Scaling path: Implement connection timeout with cleanup; add metrics for pool utilization; set configurable per-cluster pool size
- Priority: Low (large HPC centers only; >100 jobs)

## Dependencies at Risk

**PyO3 Python version coupling (Rust TUI)**
- Risk: PyO3 compiled against specific Python version (3.12); system Python 3.14 incompatible; SRE module mismatch errors on version mismatch
- Impact: Build-time error if `build-tui.sh` uses system Python instead of venv; runtime panics if venv Python updated but Rust binary not rebuilt
- Current mitigation: `build-tui.sh` explicitly sets `PYO3_PYTHON` to venv Python; venv Python pinned to 3.12
- Migration plan: Migrate from PyO3 to thin IPC boundary (JSON-RPC over socket) to decouple Python version; see ADR-002
- Priority: High (affects packaging, CI/CD)

**Textual framework major version lock**
- Risk: Textual TUI tightly coupled to specific Textual version; major version upgrades (0.x) break API compatibility
- Impact: Dependency upgrade blocked by need for widget refactoring; security patches delayed
- Current mitigation: All Textual imports isolated in `tui/src/tui/` directory; no raw Textual in core logic
- Migration plan: Extract TUI to separate versioning; core orchestrator/runner code version-independent
- Priority: Low (framework stable, but good practice for long-term)

**asyncssh known_hosts API inconsistency**
- Risk: `known_hosts=None` to disable verification is undocumented behavior; could change in future asyncssh versions
- Impact: SSH code breaks if asyncssh changes known_hosts=None semantics
- Current mitigation: Rust bridge doesn't use this pattern; only legacy Python code affected
- Migration plan: Deprecate direct asyncssh usage in favor of connection_manager wrapper
- Priority: Low (covered by security concerns above)

## Missing Critical Features

**Workflow restart from checkpoint**
- Problem: No mechanism to resume failed workflows; user must resubmit entire DAG from scratch
- Blocks: Checkpointing optimization studies (convergence, phonons); costs CPU time re-running completed steps
- Impact: ~20% inefficiency on multi-step workflows; user productivity loss
- Files affected: `tui/src/core/workflow.py`, `tui/src/core/orchestrator.py`
- Workaround: Manual partial re-submission by creating new workflow with completed job results as input
- Priority: Medium (feature request for Phase 2)

**Cluster dynamic resource detection**
- Problem: Cluster max_concurrent jobs hardcoded by admin; no auto-detection of available resources
- Blocks: Auto-scaling queue depth based on actual cluster capacity; users must know queue limits manually
- Impact: Under-utilization of large clusters; queue submissions rejected on small clusters
- Files affected: `tui/src/core/database.py` (Cluster model max_concurrent field)
- Workaround: Admin manually measures cluster capacity and sets in config
- Priority: Low (workaround acceptable for production)

**Materials API offline mode**
- Problem: Materials search requires internet connection; fails silently if network down
- Blocks: Using TUI on disconnected systems (remote HPC login nodes); local materials database caching
- Impact: Some workflows can't proceed without internet; poor UX on networks without egress
- Files affected: `tui/src/core/materials_api/service.py`, `tui/src/core/materials_api/clients/mp_api.py`
- Workaround: Pre-download materials locally, use structure files instead
- Priority: Low (specialist feature; most users have internet)

## Test Coverage Gaps

**SSH runner status detection edge cases**
- What's not tested: Job finished and expired from queue (squeue returns nothing), node down, queue full errors, timeout handling
- Files: `tui/src/runners/ssh_runner.py`, `tui/tests/test_ssh_runner_status_detection.py`
- Risk: Unknown job status mishandled; workflows hang or fail silently
- Test: Add fixtures with real SLURM output samples for edge cases; mock squeue/sbatch with error responses
- Priority: High (affects job monitoring reliability)

**Workflow DAG circular dependency detection**
- What's not tested: Circular dependencies in workflow.json (A→B→A); missing node references
- Files: `tui/src/core/workflow.py`, `tui/tests/test_workflows.py`
- Risk: Orchestrator enters infinite loop or crashes at runtime; no early validation
- Test: Add parametrized tests for invalid DAGs (cycles, missing deps, duplicate node IDs)
- Priority: Medium (runtime detection works but no unit coverage)

**Database concurrent access under load**
- What's not tested: Multiple queue managers polling job status simultaneously; concurrent job creation + status updates
- Files: `tui/src/core/database.py`, `tui/tests/test_database_concurrency.py`
- Risk: Database lock timeouts, lost status updates, race conditions on job state
- Test: Stress test with 10+ concurrent operations; verify all operations atomic and no state corruption
- Priority: Medium (covered by integration tests but not isolated unit test)

**Materials API timeout and retry handling**
- What's not tested: API server timeout (no response after 30s), 503 Service Unavailable, rate limit 429 with Retry-After header
- Files: `tui/src/core/materials_api/clients/mp_api.py`, `tui/tests/test_materials_api.py`
- Risk: Search hangs indefinitely on timeout; rate limit errors cause silent failures
- Test: Mock HTTP client with timeout/error responses; verify exponential backoff and user-facing error messages
- Priority: Low (typical users not affected; edge case for aggressive queries)

**SLURM sbatch submission failure handling**
- What's not tested: sbatch validation errors (bad SBATCH directives), permission denied on scratch dir, disk full when copying input files
- Files: `python/crystalmath/integrations/slurm_runner.py:545-574`, `tui/src/runners/slurm_runner.py`
- Risk: Job submission silently fails; user thinks job running but it never started
- Test: Mock sbatch/scp with realistic error messages; verify all error paths propagate to workflow state
- Priority: Medium (affects job submission reliability)

---

*Concerns audit: 2026-02-02*
