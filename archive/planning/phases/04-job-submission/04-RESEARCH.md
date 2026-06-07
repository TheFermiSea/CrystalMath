# Phase 4: Job Submission & Monitoring - Research

**Researched:** 2026-02-02
**Domain:** quacc recipe invocation, workflow engine dispatch, job status polling
**Confidence:** HIGH

## Summary

This phase implements job submission through quacc and status monitoring via workflow engines (Parsl/Covalent). The key insight is that quacc recipes are regular Python functions that return futures when used with a workflow engine. Job status polling differs significantly between Parsl (futures with `.done()` and `.result()`) and Covalent (`ct.get_result()` with status polling).

The existing codebase has solid foundations:
- `python/crystalmath/quacc/` already provides recipe discovery, engine detection, cluster configuration, and job metadata storage
- IPC layer (Phase 1) is complete
- Recipe browser and cluster status (Phase 2) provide the UI foundation

**Primary recommendation:** Implement a workflow-engine-agnostic `JobRunner` abstraction that wraps Parsl futures and Covalent dispatches behind a common interface. Store job references (future handles or dispatch IDs) in the existing `JobStore` for status polling. Use custodian integration for VASP error recovery.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard | Confidence |
|---------|---------|---------|--------------|------------|
| quacc | 0.11+ | Recipe framework, VASP jobs | Core dependency, provides @job decorator | HIGH |
| parsl | 2024.5+ | Pilot job executor | HPC/SLURM with HighThroughputExecutor | HIGH |
| covalent | 0.238+ | Dispatch executor | Simple SLURM via SlurmExecutor | MEDIUM |
| custodian | 2024+ | VASP error handling | Auto-recovery from common VASP errors | HIGH |
| ase | 3.22+ | Structure handling | Required by quacc recipes | HIGH |
| pymatgen | 2024+ | VASP I/O, POTCAR | Structure manipulation, input validation | HIGH |

### Supporting

| Library | Version | Purpose | When to Use | Confidence |
|---------|---------|---------|-------------|------------|
| concurrent.futures | stdlib | as_completed() polling | Parsl future management | HIGH |
| asyncio | stdlib | Async status updates | Non-blocking TUI updates | HIGH |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Parsl | Prefect | Prefect has better UI but overkill for single-machine dispatch |
| Covalent | Dask | Dask better for interactive; Covalent better for HPC |
| custodian | Manual error handling | custodian handles 20+ VASP errors automatically |

### Installation

```bash
# With Parsl (recommended for HPC)
pip install quacc[parsl] custodian

# With Covalent
pip install quacc[covalent] custodian covalent-slurm-plugin
```

---

## Architecture Patterns

### Recommended Project Structure

```
python/crystalmath/
  server/handlers/
    jobs.py               # Extend with jobs.submit, jobs.status, jobs.cancel
  quacc/
    runner.py             # NEW: JobRunner abstraction
    parsl_runner.py       # NEW: Parsl-specific implementation
    covalent_runner.py    # NEW: Covalent-specific implementation
    store.py              # Extend JobMetadata with future_ref/dispatch_id
    potcar.py             # NEW: POTCAR validation utilities
```

### Pattern 1: Programmatic Recipe Invocation

**What:** Invoke quacc recipes as regular Python functions with ASE Atoms objects.

**When to use:** `jobs.submit` RPC handler.

**Why:**
- quacc recipes are decorated functions that accept `atoms` + kwargs
- Returns dict with results when no workflow engine is configured
- Returns future when workflow engine is active

**Example:**
```python
# Source: quacc documentation (Intro to Jobs, Deploying Calculations)
from ase.io import read
from quacc.recipes.vasp.core import relax_job, static_job

# Load structure
atoms = read("POSCAR")

# Invoke recipe - with workflow engine, returns future
future = relax_job(
    atoms,
    preset="DefaultSetGGA",
    relax_cell=True,
    kpts=[4, 4, 4],
    encut=520,
)

# Or chain recipes (quacc handles @flow decoration)
def my_workflow(atoms):
    relax_output = relax_job(atoms, relax_cell=True)
    return static_job(relax_output["atoms"])
```

**Confidence:** HIGH - Verified from quacc documentation

### Pattern 2: Parsl Dispatch and Status Polling

**What:** Use Parsl futures to track job state with non-blocking checks.

**When to use:** When `WORKFLOW_ENGINE == "parsl"`.

**Why:**
- Parsl futures inherit from `concurrent.futures.Future`
- `.done()` provides non-blocking status check
- `.result()` blocks until completion or raises exception

**Example:**
```python
# Source: Parsl Futures documentation
import parsl
from parsl.config import Config
from parsl.executors import HighThroughputExecutor
from parsl.providers import SlurmProvider
from parsl.launchers import SrunLauncher
from concurrent.futures import as_completed

# Configure Parsl with SLURM
config = Config(
    strategy="htex_auto_scale",
    executors=[
        HighThroughputExecutor(
            label="vasp_htex",
            max_workers_per_node=1,  # One VASP job per node
            cores_per_worker=1,      # Parsl worker overhead
            provider=SlurmProvider(
                partition="regular",
                account="m1234",
                walltime="01:00:00",
                nodes_per_block=2,
                init_blocks=0,
                min_blocks=0,
                max_blocks=10,
                launcher=SrunLauncher(),  # For MPI jobs
                worker_init="module load vasp && export VASP_PP_PATH=/path/to/potcar",
            ),
        )
    ],
)
parsl.load(config)

# Submit and track
futures = [relax_job(atoms) for atoms in structures]

# Non-blocking status check
for f in futures:
    if f.done():
        try:
            result = f.result()
            print(f"Complete: {result['formula_pretty']}")
        except Exception as e:
            print(f"Failed: {e}")
    else:
        print("Still running...")

# Or use as_completed for progress tracking
from tqdm import tqdm
for f in tqdm(as_completed(futures), total=len(futures)):
    result = f.result()
```

**Confidence:** HIGH - Standard Parsl pattern

### Pattern 3: Covalent Dispatch and Status Polling

**What:** Use `ct.dispatch()` and `ct.get_result()` for job management.

**When to use:** When `WORKFLOW_ENGINE == "covalent"`.

**Why:**
- Covalent handles SLURM submission via SSH
- Provides dispatch_id for tracking
- Supports `wait=False` for non-blocking status checks

**Example:**
```python
# Source: Covalent Results API documentation
import covalent as ct

# Define executor
slurm_executor = ct.executor.SlurmExecutor(
    username="user",
    address="perlmutter-p1.nersc.gov",
    ssh_key_file="~/.ssh/id_rsa",
    conda_env="quacc_env",
    options={
        "nodes": 1,
        "qos": "regular",
        "constraint": "cpu",
        "account": "m1234",
        "job-name": "vasp_relax",
        "time": "01:00:00",
    },
    remote_workdir="/scratch/user/covalent",
    create_unique_workdir=True,
)

# Dispatch workflow
@ct.lattice(executor=slurm_executor)
def my_lattice(atoms):
    return relax_job(atoms)

dispatch_id = ct.dispatch(my_lattice)(atoms)

# Poll for status (non-blocking)
result = ct.get_result(dispatch_id, wait=False)
print(f"Status: {result.status}")  # PENDING, RUNNING, COMPLETED, FAILED

# Wait for completion
result = ct.get_result(dispatch_id, wait=True)
if result.status == "COMPLETED":
    print(result.result)  # Final output
else:
    print(result.error)  # Error details
```

**Confidence:** HIGH - Verified from Covalent Results API

### Pattern 4: JobRunner Abstraction

**What:** Unified interface for job submission/polling across workflow engines.

**When to use:** `jobs.submit`, `jobs.status`, `jobs.cancel` handlers.

**Why:**
- Abstracts Parsl vs Covalent differences
- Single API for TUI to consume
- Enables future engine additions

**Example:**
```python
# Source: Design pattern for CrystalMath
from abc import ABC, abstractmethod
from typing import Any
from enum import Enum

class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class JobRunner(ABC):
    """Abstract base for workflow engine runners."""

    @abstractmethod
    def submit(
        self,
        recipe_fullname: str,
        atoms: Any,
        cluster_name: str,
        **kwargs,
    ) -> str:
        """Submit job, return job_id."""
        pass

    @abstractmethod
    def get_status(self, job_id: str) -> JobState:
        """Get current job state."""
        pass

    @abstractmethod
    def get_result(self, job_id: str) -> dict | None:
        """Get result if complete, None otherwise."""
        pass

    @abstractmethod
    def cancel(self, job_id: str) -> bool:
        """Cancel job if possible."""
        pass

class ParslRunner(JobRunner):
    def __init__(self):
        self._futures: dict[str, Any] = {}

    def submit(self, recipe_fullname, atoms, cluster_name, **kwargs) -> str:
        recipe_func = self._get_recipe(recipe_fullname)
        future = recipe_func(atoms, **kwargs)
        job_id = str(uuid.uuid4())
        self._futures[job_id] = future
        return job_id

    def get_status(self, job_id: str) -> JobState:
        future = self._futures.get(job_id)
        if future is None:
            raise ValueError(f"Unknown job: {job_id}")
        if not future.done():
            return JobState.RUNNING
        try:
            future.result()  # Check for exception
            return JobState.COMPLETED
        except Exception:
            return JobState.FAILED

    def get_result(self, job_id: str) -> dict | None:
        future = self._futures.get(job_id)
        if future and future.done():
            try:
                return future.result()
            except Exception as e:
                return {"error": str(e)}
        return None

class CovalentRunner(JobRunner):
    def __init__(self):
        self._dispatch_ids: dict[str, str] = {}

    def submit(self, recipe_fullname, atoms, cluster_name, **kwargs) -> str:
        import covalent as ct
        # Build lattice dynamically
        recipe_func = self._get_recipe(recipe_fullname)
        executor = self._get_executor(cluster_name)

        @ct.lattice(executor=executor)
        def job_lattice(a, **kw):
            return recipe_func(a, **kw)

        dispatch_id = ct.dispatch(job_lattice)(atoms, **kwargs)
        job_id = str(uuid.uuid4())
        self._dispatch_ids[job_id] = dispatch_id
        return job_id

    def get_status(self, job_id: str) -> JobState:
        import covalent as ct
        dispatch_id = self._dispatch_ids.get(job_id)
        if not dispatch_id:
            raise ValueError(f"Unknown job: {job_id}")
        result = ct.get_result(dispatch_id, wait=False)
        status_map = {
            "NEW_OBJ": JobState.PENDING,
            "RUNNING": JobState.RUNNING,
            "COMPLETED": JobState.COMPLETED,
            "FAILED": JobState.FAILED,
            "CANCELLED": JobState.CANCELLED,
        }
        return status_map.get(str(result.status), JobState.PENDING)
```

**Confidence:** MEDIUM - Architecture clear, implementation needs validation

### Pattern 5: POTCAR Validation

**What:** Verify VASP pseudopotentials are available before submission.

**When to use:** Pre-flight check in `jobs.submit`.

**Why:**
- VASP requires POTCARs but they can't be distributed
- Fail fast with clear error instead of cryptic VASP crash
- Support `VASP_PP_PATH` environment variable or quacc settings

**Example:**
```python
# Source: pymatgen POTCAR documentation + quacc settings
import os
from pathlib import Path
from typing import Set

def validate_potcars(elements: Set[str]) -> tuple[bool, str | None]:
    """
    Check if POTCARs are available for given elements.

    Returns:
        (valid, error_message) - True if all POTCARs found, else False with message.
    """
    # Get POTCAR path from environment or quacc settings
    potcar_path = os.environ.get("VASP_PP_PATH")
    if not potcar_path:
        try:
            from quacc import SETTINGS
            potcar_path = getattr(SETTINGS, "VASP_PP_PATH", None)
        except ImportError:
            pass

    if not potcar_path:
        return False, "VASP_PP_PATH not set. Set environment variable or configure in ~/.quacc.yaml"

    potcar_dir = Path(potcar_path)
    if not potcar_dir.exists():
        return False, f"VASP_PP_PATH does not exist: {potcar_path}"

    # Check for PBE POTCARs (most common)
    pbe_dirs = list(potcar_dir.glob("potpaw_PBE*")) + list(potcar_dir.glob("PBE*"))
    if not pbe_dirs:
        return False, f"No PBE POTCAR directory found in {potcar_path}"

    potcar_base = pbe_dirs[0]

    missing = []
    for elem in elements:
        # Check standard POTCAR naming: element or element_suffix
        elem_dirs = list(potcar_base.glob(f"{elem}")) + list(potcar_base.glob(f"{elem}_*"))
        if not elem_dirs:
            missing.append(elem)

    if missing:
        return False, f"Missing POTCARs for elements: {', '.join(sorted(missing))}"

    return True, None
```

**Confidence:** HIGH - Standard pymatgen pattern, adapted for quacc

### Anti-Patterns to Avoid

- **Blocking status polls in TUI thread:** Always use non-blocking checks (`.done()` or `wait=False`)
- **Storing futures in JobStore JSON:** Futures are not serializable. Store job_id and use in-memory registry.
- **Ignoring workflow engine state:** Check `WORKFLOW_ENGINE` setting - if None, jobs run locally and block.
- **Hardcoding cluster configuration:** Use `ClusterConfigStore` for persistence.
- **Skipping POTCAR validation:** VASP will fail cryptically without POTCARs.
- **Polling too frequently:** 30-60 second intervals are sufficient; don't hammer the scheduler.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| VASP input generation | Custom templates | quacc recipes + presets | Validated, community-maintained |
| Error recovery | Manual INCAR fixes | custodian handlers | Handles 20+ known VASP errors |
| SLURM submission | subprocess + sbatch | Parsl SlurmProvider or Covalent SlurmExecutor | Handles retries, monitoring, cleanup |
| Future tracking | Custom state machine | concurrent.futures or Covalent Result | Tested, handles edge cases |
| POTCAR concatenation | Manual file ops | pymatgen Potcar class | Handles order, validation |

**Key insight:** quacc and workflow engines abstract the complexity of HPC job management. Use their interfaces directly.

---

## Common Pitfalls

### Pitfall 1: Parsl Future Memory Leak

**What goes wrong:** Futures accumulate in memory if not cleaned up.

**Why it happens:** Parsl holds references to all submitted futures.

**How to avoid:**
1. Call `.result()` or `.exception()` to mark futures as consumed
2. Implement periodic cleanup of completed job references
3. Use `app_cache=False` if resubmitting same computation

**Warning signs:** Memory usage grows over time, old job IDs still resolvable.

### Pitfall 2: Covalent Server Not Running

**What goes wrong:** `ct.dispatch()` fails silently or hangs.

**Why it happens:** Covalent requires `covalent start` before use.

**How to avoid:**
```python
import subprocess
result = subprocess.run(["covalent", "status"], capture_output=True, text=True)
if "stopped" in result.stdout.lower():
    subprocess.run(["covalent", "start"], check=True)
```

**Warning signs:** Dispatch hangs, no dispatch_id returned.

### Pitfall 3: Wrong Launcher for MPI Jobs

**What goes wrong:** VASP processes fail to start on SLURM nodes.

**Why it happens:** Using `SingleNodeLauncher` instead of `SrunLauncher` for MPI.

**How to avoid:**
- For MPI VASP: Use `SrunLauncher()` or `SimpleLauncher()` with `VASP_PARALLEL_CMD`
- Set `export QUACC_VASP_PARALLEL_CMD='srun -N 1 --ntasks-per-node 48'`
- Match `cores_per_worker` in Parsl to actual VASP parallelism

**Warning signs:** Workers start but VASP crashes with "cannot allocate memory" or MPI errors.

### Pitfall 4: POTCAR Functional Mismatch

**What goes wrong:** Calculation produces incorrect energies or crashes.

**Why it happens:** Using LDA POTCARs with GGA/PBE functional or vice versa.

**How to avoid:**
1. Check `VASP_PP_VERSION` setting matches desired functional
2. Validate POTCAR headers contain expected functional string
3. Use quacc presets which handle this automatically

**Warning signs:** pymatgen warning "POTCAR with symbol X has metadata that does not match any VASP POTCAR known to pymatgen."

### Pitfall 5: Job Status Drift

**What goes wrong:** TUI shows "RUNNING" but job already completed/failed.

**Why it happens:** Polling interval too long, or worker crashed without update.

**How to avoid:**
1. Check job status on every TUI refresh (if not too expensive)
2. Store last_checked timestamp, show warning if stale
3. For Parsl: also check block/worker status
4. For Covalent: check SLURM job directly if status stuck

**Warning signs:** Status "RUNNING" for hours, no output files appearing.

---

## Code Examples

### Example 1: jobs.submit RPC Handler

```python
# Source: CrystalMath pattern from existing handlers
from crystalmath.server.handlers import register_handler
from crystalmath.quacc.store import JobStore, JobMetadata, JobStatus
from crystalmath.quacc.potcar import validate_potcars
from datetime import datetime, timezone
import uuid

@register_handler("jobs.submit")
async def handle_jobs_submit(controller, params: dict) -> dict:
    """Submit a VASP job via quacc recipe.

    Params:
        recipe (str): Full recipe path (e.g., "quacc.recipes.vasp.core.relax_job")
        structure (dict): Structure in ASE dict format or POSCAR string
        cluster (str): Cluster name from clusters.json
        params (dict): Recipe parameters (kpts, encut, etc.)

    Returns:
        {"job_id": "uuid", "status": "pending", "error": null}
    """
    from crystalmath.quacc.engines import get_workflow_engine
    from crystalmath.quacc.runner import get_runner

    # Get workflow engine
    engine = get_workflow_engine()
    if engine is None:
        return {"job_id": None, "status": "error",
                "error": "No workflow engine configured. Set QUACC_WORKFLOW_ENGINE."}

    # Load structure
    try:
        atoms = _parse_structure(params["structure"])
    except Exception as e:
        return {"job_id": None, "status": "error",
                "error": f"Failed to parse structure: {e}"}

    # Validate POTCARs
    elements = set(str(s) for s in atoms.get_chemical_symbols())
    valid, potcar_error = validate_potcars(elements)
    if not valid:
        return {"job_id": None, "status": "error", "error": potcar_error}

    # Get runner for configured engine
    runner = get_runner(engine)

    # Submit job
    try:
        job_id = runner.submit(
            recipe_fullname=params["recipe"],
            atoms=atoms,
            cluster_name=params.get("cluster", "local"),
            **params.get("params", {}),
        )
    except Exception as e:
        return {"job_id": None, "status": "error",
                "error": f"Submission failed: {e}"}

    # Store job metadata
    store = JobStore()
    job = JobMetadata(
        id=job_id,
        recipe=params["recipe"],
        status=JobStatus.pending,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        cluster=params.get("cluster"),
        work_dir=None,  # Set when job starts
    )
    store.save_job(job)

    return {"job_id": job_id, "status": "pending", "error": None}

def _parse_structure(structure_data):
    """Parse structure from POSCAR string or dict."""
    from ase.io import read
    from io import StringIO

    if isinstance(structure_data, str):
        # POSCAR string
        return read(StringIO(structure_data), format="vasp")
    elif isinstance(structure_data, dict):
        # ASE Atoms dict format
        from ase import Atoms
        return Atoms(**structure_data)
    else:
        raise ValueError(f"Unknown structure format: {type(structure_data)}")
```

**Confidence:** HIGH - Follows existing handler patterns

### Example 2: jobs.status RPC Handler

```python
@register_handler("jobs.status")
async def handle_jobs_status(controller, params: dict) -> dict:
    """Get current status of a job.

    Params:
        job_id (str): Job UUID

    Returns:
        {"job_id": "...", "status": "running", "error": null, "result": null}
    """
    from crystalmath.quacc.engines import get_workflow_engine
    from crystalmath.quacc.runner import get_runner
    from crystalmath.quacc.store import JobStore

    job_id = params.get("job_id")
    if not job_id:
        return {"error": "job_id required"}

    store = JobStore()
    job = store.get_job(job_id)
    if job is None:
        return {"error": f"Job not found: {job_id}"}

    # If already terminal state, return cached status
    if job.status in (JobStatus.completed, JobStatus.failed):
        return {
            "job_id": job_id,
            "status": job.status.value,
            "error": job.error_message,
            "result": job.results_summary,
        }

    # Poll live status from runner
    engine = get_workflow_engine()
    if engine is None:
        return {"job_id": job_id, "status": job.status.value, "error": None, "result": None}

    runner = get_runner(engine)

    try:
        current_status = runner.get_status(job_id)

        # Update stored status if changed
        if current_status.value != job.status.value:
            job.status = JobStatus(current_status.value)
            job.updated_at = datetime.now(timezone.utc)

            # If complete, fetch result
            if current_status == JobState.COMPLETED:
                result = runner.get_result(job_id)
                if result:
                    job.results_summary = _summarize_result(result)

            # If failed, fetch error
            elif current_status == JobState.FAILED:
                result = runner.get_result(job_id)
                if result and "error" in result:
                    job.error_message = result["error"]

            store.save_job(job)

        return {
            "job_id": job_id,
            "status": job.status.value,
            "error": job.error_message,
            "result": job.results_summary,
        }
    except Exception as e:
        return {"job_id": job_id, "status": job.status.value, "error": str(e), "result": None}

def _summarize_result(result: dict) -> dict:
    """Extract key values from quacc result schema."""
    summary = {}

    # Energy
    if "results" in result and "energy" in result["results"]:
        summary["energy_ev"] = result["results"]["energy"]

    # Forces (max magnitude)
    if "results" in result and "forces" in result["results"]:
        import numpy as np
        forces = np.array(result["results"]["forces"])
        summary["max_force_ev_ang"] = float(np.max(np.linalg.norm(forces, axis=1)))

    # Formula
    if "formula_pretty" in result:
        summary["formula"] = result["formula_pretty"]

    # Working directory
    if "dir_name" in result:
        summary["work_dir"] = result["dir_name"]

    return summary
```

**Confidence:** HIGH - Standard polling pattern

### Example 3: Rust TUI Status Display

```rust
// Source: Pattern for Rust TUI display
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobStatusResponse {
    pub job_id: String,
    pub status: String,  // "pending", "running", "completed", "failed"
    pub error: Option<String>,
    pub result: Option<JobResultSummary>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobResultSummary {
    pub energy_ev: Option<f64>,
    pub max_force_ev_ang: Option<f64>,
    pub formula: Option<String>,
    pub work_dir: Option<String>,
}

impl App {
    /// Poll job status for active jobs
    pub fn poll_job_statuses(&mut self) {
        // Only poll if enough time has passed (30s interval)
        if self.last_poll.elapsed() < Duration::from_secs(30) {
            return;
        }

        // Get running jobs
        let running_jobs: Vec<_> = self.jobs
            .iter()
            .filter(|j| j.status == "pending" || j.status == "running")
            .map(|j| j.id.clone())
            .collect();

        for job_id in running_jobs {
            // Non-blocking IPC call
            if let Some(client) = &mut self.ipc_client {
                match client.call("jobs.status", json!({"job_id": job_id})) {
                    Ok(response) => {
                        if let Ok(status) = serde_json::from_value::<JobStatusResponse>(response) {
                            self.update_job_status(status);
                        }
                    }
                    Err(e) => {
                        tracing::warn!("Failed to poll job {}: {}", job_id, e);
                    }
                }
            }
        }

        self.last_poll = Instant::now();
    }

    fn update_job_status(&mut self, status: JobStatusResponse) {
        if let Some(job) = self.jobs.iter_mut().find(|j| j.id == status.job_id) {
            job.status = status.status;
            job.error = status.error;
            if let Some(result) = status.result {
                job.energy = result.energy_ev;
                job.formula = result.formula;
            }
        }
    }
}
```

**Confidence:** HIGH - Follows existing TUI patterns

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| FireWorks for workflow | quacc with Parsl/Covalent | 2024 | Simpler setup, no MongoDB |
| Manual SLURM scripts | Workflow engine dispatch | 2024 | Automatic retry, monitoring |
| Check vasprun.xml | Use quacc VaspSchema | 2024+ | Consistent result format |
| Hardcoded error fixes | custodian handlers | 2020+ | Community-maintained recovery |

**Deprecated/outdated:**
- **quacc STORE setting:** Removed in v0.7.0. Use `results_to_db()` function instead.
- **`quacc_results.json.gz`:** No longer written automatically.
- **Old VaspErrorHandler:** Use custodian 2024+ with updated error patterns.

---

## Open Questions

1. **In-memory future storage persistence**
   - What we know: Parsl futures cannot be serialized
   - What's unclear: How to restore job tracking after server restart
   - Recommendation: Store dispatch metadata (recipe, cluster, timestamp), mark as "orphaned" on restart

2. **Covalent server lifecycle**
   - What we know: Covalent requires `covalent start`
   - What's unclear: Should crystalmath-server manage Covalent lifecycle?
   - Recommendation: Check status and start if needed, but warn user about dependency

3. **Cancel semantics**
   - What we know: Parsl futures can be cancelled, Covalent has cancel API
   - What's unclear: Do SLURM jobs get killed or just abandoned?
   - Recommendation: Implement cancel, document that SLURM jobs may need manual cleanup

4. **Results storage location**
   - What we know: quacc writes to SCRATCH_DIR or RESULTS_DIR
   - What's unclear: Should we copy key files to ~/.crystalmath/results/?
   - Recommendation: Store path in JobMetadata, don't copy files

---

## Sources

### Primary (HIGH confidence)

- [quacc Deploying Calculations](https://quantum-accelerators.github.io/quacc/user/wflow_engine/executors.html) - Workflow engine setup
- [quacc Settings List](https://quantum-accelerators.github.io/quacc/user/settings/settings_list.html) - VASP configuration
- [quacc VASP Core Recipes](https://quantum-accelerators.github.io/quacc/reference/quacc/recipes/vasp/core.html) - Recipe signatures
- [Parsl Futures Documentation](https://parsl.readthedocs.io/en/stable/userguide/futures.html) - Status checking
- [Parsl NERSC Documentation](https://docs.nersc.gov/jobs/workflow/parsl/) - HPC configuration
- [Covalent Results API](https://docs.covalent.xyz/docs/user-documentation/api-reference/results/) - Status polling
- [Covalent SLURM Plugin](https://github.com/AgnostiqHQ/covalent-slurm-plugin) - Executor setup
- [Custodian Documentation](https://materialsproject.github.io/custodian/) - Error handling

### Secondary (MEDIUM confidence)

- [pymatgen VASP I/O](https://pymatgen.org/pymatgen.io.vasp.html) - POTCAR handling
- [Tom Demeyere - Parsl for DFT](https://tomdemeyere.github.io/blog/2024/workflows-manager-for-dft/) - Community tutorial

### Tertiary (LOW confidence)

- Existing `python/crystalmath/quacc/` modules - Local implementation patterns

---

## Metadata

**Confidence breakdown:**
- Recipe invocation: HIGH - Verified from quacc documentation
- Parsl dispatch: HIGH - Standard concurrent.futures pattern
- Covalent dispatch: HIGH - Verified from Covalent Results API
- JobRunner abstraction: MEDIUM - Architecture clear, needs validation
- POTCAR validation: HIGH - Standard pymatgen approach
- Pitfalls: MEDIUM - Based on docs + community experience

**Research date:** 2026-02-02
**Valid until:** 60 days (quacc releases monthly; check changelog)

---

## Roadmap Implications

Based on research, recommended Phase 4 plan structure:

1. **POTCAR validation module** (Low risk)
   - Path detection from env/quacc settings
   - Element POTCAR existence check
   - ~1-2 hours

2. **JobRunner abstraction** (Medium risk)
   - Base class and factory function
   - In-memory job registry
   - ~2-3 hours

3. **ParslRunner implementation** (Medium risk)
   - Future-based dispatch
   - Status polling via `.done()`/`.result()`
   - ~3-4 hours

4. **CovalentRunner implementation** (Medium risk)
   - Dispatch ID tracking
   - `ct.get_result()` polling
   - ~2-3 hours

5. **RPC handlers** (Low risk)
   - `jobs.submit`, `jobs.status`, `jobs.cancel`
   - Integrate with existing JobStore
   - ~3-4 hours

6. **Rust TUI updates** (Medium risk)
   - Cluster selection widget
   - Job submission form
   - Status polling loop
   - Progress display
   - ~4-6 hours

7. **Integration tests** (Medium effort)
   - Mock workflow engines
   - End-to-end submission flow
   - ~3-4 hours

**Estimated total:** 3-4 days focused work.

**Research flags resolved:**
- POTCAR validation: Check `VASP_PP_PATH`, verify element directories exist
- Parsl vs Covalent errors: Both return exceptions via result/get_result, capture in JobMetadata.error_message
