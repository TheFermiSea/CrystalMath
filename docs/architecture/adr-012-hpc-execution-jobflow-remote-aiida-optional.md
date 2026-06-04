# ADR-012: HPC Execution Layer — jobflow-remote (Outbound-SSH Polling Daemon) as Default, AiiDA Opt-In; Delete the Bespoke SLURM/SSH Stack

**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Project maintainers
**Supersedes:** none
**Depends on:** [ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) (jobflow/quacc as the workflow model)

## Context

CrystalMath's job is to take a workflow defined in the Python core, push it across an SSH
boundary to a SLURM cluster, stage files, submit with `sbatch`, poll until done, and pull
results back. Today it does this with **three hand-rolled SLURM-over-SSH implementations plus a
vendored SSH transport**, and the connectivity model that should drive the whole design is never
stated explicitly — it is rediscovered, partially, in each copy.

**The three implementations (measured):**

- `python/crystalmath/_vendor/runners/slurm_runner.py` — **1,758 LOC**, `SLURMRunner(RemoteBaseRunner)`
  (`:95`). Parses both `squeue --json` and formatted output (`:897`, `:965`), carries its own
  job-ID regex (`:1578`) and `SLURMJobState` enum (`:36`).
- `python/crystalmath/integrations/slurm_runner.py` — **1,549 LOC**, `SLURMWorkflowRunner` (`:252`),
  a *second* `sbatch` path that implements the `WorkflowRunner` protocol instead of `RemoteBaseRunner`.
  It opens `asyncssh` directly (`:497`) and even contains runtime fallback logic — "TUI connection
  manager not available, using direct asyncssh" (`:689-699`).
- `python/crystalmath/tui/src/runners/slurm_runner.py` — the deprecated original both of the above
  forked from (slated for deletion with `tui/` per ADR-006).

Transport is fragmented the same way: `python/crystalmath/_vendor/core/connection_manager.py`
(**806 LOC**) is a vendored `ConnectionManager` (a frozen fork-copy of the deprecated `tui/`, which
`_vendor/__init__.py` forbids editing), used alongside the direct `asyncssh` calls in
`integrations/slurm_runner.py`. Net: **~3.3k LOC of core SLURM submission code plus ~0.8k LOC of
vendored SSH transport** reimplement, three times over, what the ecosystem ships as maintained
libraries — `_generate_slurm_script()` string-building, "Submitted batch job" regex parsing, and
hand-rolled `squeue`/`sacct` polling and JSON state files.

This is the friction catalog's single largest reinvention (§2, "Three independent SLURM-over-SSH
submission implementations"), and it sits underneath the five-way runner sprawl (§1) that
[ADR-011](adr-011-workflow-engine-jobflow-atomate2-quacc.md) collapses onto jobflow. Requirements E1–E5
make the deployment reality concrete: **all compute, including init steps (p2y, ypp, `yambo -i`,
SCF), must run via `sbatch`** — never directly on compute nodes over SSH, which "bypasses cgroup
pinning" (beefcake2 `CLAUDE.md:6`); the cluster is reached over SSH/Tailscale to a submit node;
the SLURM controller's DB is **not** reachable from the user's machine; partitions may be offline
(`qe-node1..3` stopped); and state sync must hybridize `squeue` (active) + `sacct` (completed).

**The ecosystem state of the art has already settled the decisive design axis: network
connectivity.** There are two families of execution layer, and they differ on which direction
connections flow:

1. **Inbound-callback executors** — Parsl's `HighThroughputExecutor` and Dask-Distributed run
   workers on compute nodes that open connections *back* to a coordinator (Parsl HTEX uses ZeroMQ
   on `worker_ports`/`interchange` in the 54000–56000 range). This is best-in-class for
   *in-allocation* throughput (Babuji et al. 2019), but the inbound callback ports are routinely
   firewalled at HPC centers and are hostile to a TUI behind NAT.
2. **Outbound-SSH polling daemons** — AiiDA (Huber et al. 2020) and **jobflow-remote** (Matgenix)
   run a daemon that submits and polls the scheduler over **outbound SSH only**, explicitly
   designed for the case where the workflow DB is *not* reachable from the compute center. This is
   exactly CrystalMath's reality (E2).

On top of raw submission, the community has standardized the per-scheduler layer itself: **PSI/J**
(Hategan-Marandiuc et al. 2023) is a portable submit/monitor/cancel API across SLURM/PBS/LSF/Flux,
created specifically to retire the bespoke per-scheduler shell-and-regex parsing CrystalMath
hand-rolls in `_parse_job_id`/`_generate_slurm_script`. Choosing a daemon-based engine gets a
PSI/J-grade abstraction "for free" rather than as another dependency to wire up.

## Decision

**Adopt `jobflow-remote` as CrystalMath's default remote-execution backend, expose it (and AiiDA)
behind a single `ExecutionBackend` protocol with exactly two implementations, and delete all three
bespoke SLURM-over-SSH implementations and the vendored `ConnectionManager`.**

Concretely:

### 1. One seam: the `ExecutionBackend` protocol

Define a single protocol in `python/crystalmath/execution/` — the only execution seam in the core,
replacing the five overlapping runner families (`WorkflowRunner`, `RemoteBaseRunner`, `JobRunner`,
`BaseAnalysisRunner`, the vendored `BaseRunner`):

```python
class ExecutionBackend(Protocol):
    def submit(self, flow: jobflow.Flow, *, worker: str) -> SubmissionHandle: ...
    def status(self, handle: SubmissionHandle) -> JobState: ...     # single JobState enum
    def result(self, handle: SubmissionHandle) -> TaskDocument: ...  # ADR-009 typed doc
    def cancel(self, handle: SubmissionHandle) -> None: ...
    def adopt(self, external_job_id: str, *, worker: str) -> SubmissionHandle: ...  # E5
```

Workflows are jobflow `Flow`s (per ADR-011); the backend submits the Flow, it does not build
`sbatch` strings. There are **two** implementations, no more:

### 2. `JobflowRemoteBackend` — the default

A thin adapter over `jobflow-remote`'s daemon and `Runner`. The daemon (started/managed by the
Python core, supervised over the IPC boundary, never by the Rust TUI) submits to configured
**workers** (HPC front-ends, local) over **outbound SSH**, stages files, calls `sbatch`, polls
`squeue`/`sacct`, retries, and pulls results into the jobflow `JobStore` (ADR-010). The Rust TUI
queries job state from that store over IPC; it never parses `squeue` output itself. The
beefcake2 topology maps directly onto jobflow-remote *workers* (one per partition: `vasp`, `qe`),
its `pre_run`/`resources` config (account, qos, time, modules — all whitelist-validated per F4),
and shared-vs-local scratch (E2: NFS `/cluster/...` vs per-node ZFS `/scratch`) onto its
file-staging configuration. Because every compute step is a jobflow `Job` submitted via the
daemon, requirement E1 ("all compute via `sbatch`", including p2y/ypp/`yambo -i` init steps) holds
**by construction** — there is no code path that runs compute over a bare SSH channel.

### 3. `AiiDABackend` — opt-in, for full provenance

The existing `python/crystalmath/backends/aiida.py` is promoted to the second `ExecutionBackend`
impl. When enabled, AiiDA owns its outbound-SSH transport, scheduler plugins, and the immutable
provenance DAG (PostgreSQL + disk-objectstore; AiiDA 2.x `sqlite_dos` profiles for lightweight
use). It is **never the default**: its PostgreSQL/RabbitMQ operational tax (Huber et al. 2020,
flagged as a trade-off in the repo's own 33 KB integration doc) is not imposed on the laptop-first
TUI user. Results round-trip back into the ADR-009 `TaskDocument`s so the TUI stays backend-agnostic.

### 4. Delete the bespoke stack

Remove `_vendor/runners/slurm_runner.py`, `integrations/slurm_runner.py`,
`_vendor/core/connection_manager.py`, and (with `tui/`, per ADR-006) `tui/src/runners/`. The single
validated SLURM-script generation path required by F4 (`SLURMJobConfig` + `_generate_slurm_script`,
whitelist validation, no string concatenation) is satisfied by jobflow-remote's maintained,
schema-driven submission template; the security invariant moves from "our regex-and-concat code is
correct" to "validated config fields fed to a maintained submitter," which is strictly safer.
SSH host-key verification (F2) and Jinja2 `SandboxedEnvironment` (F1) remain enforced at the seam.

### 5. Parsl/Dask are reserved as *in-allocation* executors only

They are **not** the SSH submission boundary. A future high-throughput screening flow may launch a
Parsl `HighThroughputExecutor` (or Dask) *inside* a single batch allocation, where the
inbound-callback model is satisfied within one allocation — submitted *to* the cluster via
`JobflowRemoteBackend`, not *across* SSH by Parsl itself.

## Alternatives Considered

**AiiDA as the default execution backend.** AiiDA is the most mature outbound-SSH daemon with
automatic file staging, scheduler plugins, restart/retry, and gold-standard provenance (Huber et
al., *Sci. Data* 7, 300, 2020; Uhrin et al., *Comput. Mater. Sci.* 187, 110086, 2021), and it
already has a CRYSTAL plugin (`aiida-crystal-dft`) and a partial integration in the repo. **Why
not the default:** it mandates a PostgreSQL service (and historically RabbitMQ) and an opinionated
"everything is a node" ORM — a real operational tax for a single-user, laptop-first TUI with zero
current users. We keep it as the opt-in heavyweight backend (Decision §3), which is exactly where
its provenance strengths pay off without taxing the default path.

**Parsl `SlurmProvider` + `HighThroughputExecutor`.** Best-in-class in-allocation throughput,
elastic block provisioning, ms-overhead, and native quacc support (Babuji et al., *HPDC '19*,
arXiv:1905.02158). **Why not the boundary:** HTEX requires **inbound** connections from compute
nodes back to the coordinator on ports 54000–56000, which firewalled HPC centers block and which a
NAT'd TUI cannot receive; quacc's own matrix flags Parsl monitoring as "challenging." It is built
for a long-lived driver co-located near the cluster, not an interactive TUI that comes and goes.
Reserved for in-allocation fan-out (Decision §5). This is the open requirement `crystalmath-4m6`
notes already bites us: `parsl_runner.py:25,31` — futures aren't serializable, so "jobs become
orphaned on restart"; a polling daemon with a persistent store does not have this failure mode.

**Dask-Jobqueue + Dask Distributed.** Mature, simple, good for embarrassingly-parallel arrays,
quacc-integrated. **Why not the boundary:** same inbound/co-location constraint as Parsl — workers
must connect back to a Dask scheduler — plus weaker job-level provenance and staging for
long-running heterogeneous DFT jobs with restarts. Reasonable only as an optional in-allocation
executor.

**Covalent + `covalent-hpc-plugin`.** Clean executor abstraction over heterogeneous backends, and
its HPC plugin is built on PSI/J. **Why not:** it requires a self-hosted Covalent dispatcher
server, which **duplicates `crystalmath-server`'s role** (ADR-003/006), and its value-add
(cloud-bursting, dashboard) is not the core need. The interesting part is the PSI/J basis, not
Covalent itself — and jobflow-remote/AiiDA give us PSI/J-grade scheduler abstraction without a
second long-running server.

**Keep a bespoke submitter, but rebuild it on PSI/J.** If a hand-rolled submitter had to survive,
it should generate jobs via **PSI/J** (Hategan-Marandiuc et al., *IEEE e-Science* 2023,
arXiv:2307.07895) rather than raw `sbatch` strings and regex — PSI/J exists precisely to retire
that bespoke per-scheduler parsing, and underpins ExaWorks/RADICAL and `covalent-hpc-plugin`.
**Why not:** PSI/J assumes execution local to the scheduler, so pairing it with SSH still needs a
daemon/agent — i.e. we would be rebuilding a thinner jobflow-remote. Choosing jobflow-remote makes
this moot: we inherit PSI/J-equivalent abstraction *and* the outbound-SSH daemon, maintained
upstream, instead of owning ~4k LOC of it.

**FireWorks (LaunchPad + workers).** Proven at scale (Jain et al., *CCPE* 27(17), 2015). **Why
not:** its pull-based worker model wants a MongoDB LaunchPad reachable from the compute center,
which conflicts with E2 (DB not reachable from the cluster) and is heavier than jobflow-remote's
outbound-only model; it is effectively superseded by jobflow/jobflow-remote for the
jobflow/atomate2 stack ADR-011 commits to.

## Consequences

### Positive
- **Deletes ~3.3k LOC of bespoke SLURM submission + ~0.8k LOC of vendored SSH transport**, plus
  the duplicated `SLURMJobState`/job-ID-regex/state-file machinery — the friction catalog's
  largest single reinvention (§2) — and removes the security-sensitive hand-rolled
  `known_hosts`/`asyncssh` handling in favor of the engine's tested transport.
- **Matches firewalled-HPC reality (E2):** outbound-SSH-only polling is exactly what beefcake2 and
  real centers allow; no inbound worker-callback ports.
- **Satisfies E1 by construction:** every compute step is a jobflow `Job` submitted via `sbatch`
  through the daemon; there is no SSH-direct-execution path to misuse.
- **Native to the ADR-011 stack:** jobflow-remote consumes jobflow `Flow`s and writes the same
  `JobStore`, so execution and the data model agree; the Rust TUI reads state from one store over
  IPC instead of parsing `squeue` (E3) itself.
- **Persistence across restart:** the daemon + store eliminate the "orphaned jobs on restart"
  failure mode of the serialized-futures runner (`crystalmath-4m6`); `slurm.adopt`/`slurm.sync`
  (E5) map onto `adopt()`/the daemon's reconciliation.
- **Shrinks the test matrix:** two backends behind one protocol replace the
  {storage}×{engine}×{transport} cross-product of availability-detected runners (friction §9).

### Negative / Tradeoffs
- **New core dependency** (`jobflow-remote`), younger and smaller-community than AiiDA/FireWorks;
  its API is still evolving. Mitigated by the thin adapter (the seam is ours; the engine is swappable).
- **A managed daemon** is a new lifecycle the Python core must supervise (start/stop/health),
  reported over IPC; the Rust TUI must never drive it directly.
- **Provenance in the default path is lighter than AiiDA's DAG.** Per ADR-009, lineage (parent-job
  uuids, input hashes, content-addressed raw-file paths) is carried as first-class fields on the
  `TaskDocument`, so the default path is still reproducible; users needing immutable provenance
  graphs opt into `AiiDABackend`.
- **Restart-file correctness still owned by us.** jobflow-remote handles transport/staging, but the
  multi-code handoff contract (CRYSTAL `.f9`/`.f98`, VASP `WAVECAR`/`CHGCAR`; C1/C2, PITFALLS #4 —
  stale restart files silently corrupt results) must enforce positive file-matching +
  checksum/timestamp validation at the seam regardless of backend.

### Migration impact
1. Land ADR-011 (jobflow/quacc workflow model + `JobStore`) first — this ADR depends on it.
2. Introduce `python/crystalmath/execution/` with the `ExecutionBackend` protocol and
   `JobflowRemoteBackend`; configure beefcake2 workers (partitions, scratch, modules) via the
   ADR-015/pydantic-settings config (H1), routing one validated SSH path and the unified socket/db
   resolution through it (D4).
3. Re-point `api.py`/`server/handlers` job-submission methods at the new seam (one dispatch table
   per the dual-dispatch fix), so `jobs.submit`/`slurm.*` resolve to `ExecutionBackend`.
4. Promote `backends/aiida.py` to `AiiDABackend` behind the same protocol; detect the actual code
   rather than hardcoding CRYSTAL (`crystalmath-rpl`); fix the broken launcher imports
   (`crystalmath-hnq`).
5. **Delete** `_vendor/runners/slurm_runner.py`, `integrations/slurm_runner.py`,
   `_vendor/core/connection_manager.py`; delete `tui/src/runners/` with `tui/` (ADR-006).
6. Preserve F1/F2/F4 security invariants and the F5 stub-execution opt-in gate at the new seam.

## References

- Jobflow-remote documentation (Matgenix) — outbound-SSH daemon model; the workflow DB is not
  reachable from the HPC center; workers, staging, retries. https://matgenix.github.io/jobflow-remote/
- M. Hategan-Marandiuc et al., "PSI/J: A Portable Interface for Submitting, Monitoring, and
  Managing Jobs," *IEEE 19th Int. Conf. on e-Science*, 2023. arXiv:2307.07895,
  DOI:10.1109/e-Science58273.2023.10254912
- S. P. Huber et al., "AiiDA 1.0, a scalable computational infrastructure for automated
  reproducible workflows and data provenance," *Scientific Data* 7, 300 (2020).
  DOI:10.1038/s41597-020-00638-4, arXiv:2003.12476
- M. Uhrin, S. P. Huber, J. Yu, N. Marzari, G. Pizzi, "Workflows in AiiDA: Engineering a
  high-throughput, event-based engine for robust and modular computational workflows,"
  *Comput. Mater. Sci.* 187, 110086 (2021). DOI:10.1016/j.commatsci.2020.110086, arXiv:2007.10312
- Y. Babuji et al., "Parsl: Pervasive Parallel Programming in Python," *HPDC '19*. arXiv:1905.02158,
  DOI:10.1145/3307681.3325400 — `HighThroughputExecutor`'s inbound worker-callback model.
- A. Jain et al., "FireWorks: a dynamic workflow system designed for high-throughput applications,"
  *Concurrency Computat.: Pract. Exper.* 27(17), 5037–5059 (2015). DOI:10.1002/cpe.3505
- A. S. Rosen et al., "Jobflow: Computational Workflows Made Simple," *JOSS* 9(93), 5995 (2024).
  DOI:10.21105/joss.05995
- quacc workflow-engine support matrix (Dask/Parsl/Prefect/Covalent/Jobflow; HPC/server/monitoring
  trade-offs). https://quantum-accelerators.github.io/quacc/user/basics/wflow_overview.html
- Friction catalog §2 (three SLURM-over-SSH implementations; transport fragmentation) and
  Requirements E1–E5 (all compute via `sbatch`; firewalled outbound-SSH topology; hybrid
  `squeue`/`sacct` sync; job adoption). In-repo evidence: `python/crystalmath/_vendor/runners/slurm_runner.py`,
  `python/crystalmath/integrations/slurm_runner.py`, `python/crystalmath/_vendor/core/connection_manager.py`.
