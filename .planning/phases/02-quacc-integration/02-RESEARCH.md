# Phase 2: quacc Integration (Read-Only) - Research

**Researched:** 2026-02-02
**Domain:** quacc recipe discovery, workflow engine detection, job tracking
**Confidence:** HIGH

## Summary

This phase integrates the TUI with quacc's recipe system for VASP calculations. quacc is a workflow-engine-agnostic framework that wraps ASE calculators with `@job`, `@flow`, and `@subflow` decorators. The framework supports five workflow engines (Parsl, Dask, Prefect, Covalent, and Jobflow), each requiring different executor configurations.

The primary challenge is that quacc does not provide a built-in registry of recipes. Recipes must be discovered via Python introspection of the `quacc.recipes` package. Job results are not persistently stored by quacc itself - storage requires either the `results_to_db()` function or workflow engine-specific mechanisms.

**Primary recommendation:** Implement recipe discovery via `pkgutil.walk_packages()` introspection of `quacc.recipes.vasp.*` modules. Use `QuaccSettings.WORKFLOW_ENGINE` for engine detection. Store job metadata in a local JSON file (not SQLite) for simplicity in this read-only phase.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard | Confidence |
|---------|---------|---------|--------------|------------|
| quacc | 0.11+ | Recipe framework | Core dependency, provides VASP recipes | HIGH |
| ase | 3.22+ | Atoms/Calculator | Required by quacc for structure handling | HIGH |
| pymatgen | 2024+ | Structure utilities | Required by quacc for VASP input generation | HIGH |

### Workflow Engines (Optional - one required)

| Library | Version | Purpose | When to Use | Confidence |
|---------|---------|---------|-------------|------------|
| parsl | 2024.5+ | Pilot job executor | HPC/SLURM with many small jobs | HIGH |
| covalent | 0.238+ | Dispatch executor | Simple cloud/SLURM workflows | MEDIUM |
| dask | 2023.12+ | Distributed computing | Interactive work, Jupyter | HIGH |
| prefect | 3.3+ | Orchestration | Complex dependencies, UI | MEDIUM |
| jobflow | 0.1.14+ | Materials Project style | AiiDA-like provenance | HIGH |

### Installation

```bash
# Core (no workflow engine)
pip install quacc

# With Parsl (recommended for SLURM)
pip install quacc[parsl]

# With multiple engines
pip install quacc[parsl,dask]
```

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| quacc | atomate2 | atomate2 is more heavyweight, requires jobflow |
| Parsl | Covalent | Covalent has simpler API but less HPC flexibility |
| Local JSON store | SQLite | SQLite adds complexity; JSON suffices for read-only |

---

## Architecture Patterns

### Recommended Project Structure

```
python/crystalmath/
  server/
    handlers.py           # Existing - add new handlers here
    handlers/             # New namespace-based handler modules
      __init__.py
      recipes.py          # recipes.* RPC handlers
      clusters.py         # clusters.* RPC handlers
      jobs.py             # jobs.* RPC handlers (quacc)
  quacc/                  # New quacc integration module
    __init__.py
    discovery.py          # Recipe introspection
    engines.py            # Workflow engine detection
    config.py             # Cluster/executor configuration
    store.py              # Job metadata storage (JSON)
```

### Pattern 1: Recipe Discovery via Introspection

**What:** Dynamically discover quacc VASP recipes by walking the `quacc.recipes.vasp` package.

**When to use:** `recipes.list` RPC handler.

**Why:**
- quacc has no built-in recipe registry
- Recipes are decorated functions in known locations
- Introspection provides current, accurate list

**Example:**
```python
# Source: Pattern derived from quacc docs + pkgutil standard library
import pkgutil
import importlib
import inspect
from typing import Any

def discover_vasp_recipes() -> list[dict[str, Any]]:
    """Discover all VASP recipes in quacc.recipes.vasp.*"""
    recipes = []

    # Import the vasp recipes package
    import quacc.recipes.vasp as vasp_pkg

    # Walk all submodules
    for importer, modname, ispkg in pkgutil.walk_packages(
        vasp_pkg.__path__,
        prefix="quacc.recipes.vasp.",
    ):
        if ispkg:
            continue  # Skip packages, only want modules

        try:
            module = importlib.import_module(modname)
        except ImportError:
            continue

        # Find @job decorated functions
        for name, obj in inspect.getmembers(module, inspect.isfunction):
            if name.startswith("_"):
                continue
            if not name.endswith(("_job", "_flow")):
                continue

            recipes.append({
                "name": name,
                "module": modname,
                "fullname": f"{modname}.{name}",
                "docstring": inspect.getdoc(obj) or "",
                "signature": str(inspect.signature(obj)),
                "type": "job" if name.endswith("_job") else "flow",
            })

    return recipes
```

**Confidence:** HIGH - Standard Python introspection, verified module structure

### Pattern 2: Workflow Engine Detection

**What:** Detect which workflow engine is configured in quacc settings.

**When to use:** `clusters.list`, TUI status display.

**Why:**
- quacc's behavior changes based on `WORKFLOW_ENGINE` setting
- Executor configuration differs per engine
- TUI needs to show relevant status

**Example:**
```python
# Source: quacc.settings.QuaccSettings documentation
from typing import Literal

def get_workflow_engine() -> str | None:
    """Get the configured workflow engine from quacc settings."""
    try:
        from quacc import SETTINGS
        return SETTINGS.WORKFLOW_ENGINE  # "parsl", "dask", "prefect", etc. or None
    except ImportError:
        return None

def get_installed_engines() -> list[str]:
    """Detect which workflow engine extras are installed."""
    engines = []

    engine_checks = {
        "parsl": "parsl",
        "dask": "dask.distributed",
        "prefect": "prefect",
        "covalent": "covalent",
        "jobflow": "jobflow",
    }

    for engine, module_name in engine_checks.items():
        try:
            importlib.import_module(module_name)
            engines.append(engine)
        except ImportError:
            pass

    return engines

def get_engine_status() -> dict:
    """Get workflow engine status for TUI display."""
    return {
        "configured": get_workflow_engine(),
        "installed": get_installed_engines(),
        "quacc_installed": _check_quacc_installed(),
    }

def _check_quacc_installed() -> bool:
    try:
        import quacc
        return True
    except ImportError:
        return False
```

**Confidence:** HIGH - Verified via quacc source code (settings.py)

### Pattern 3: Parsl Executor Configuration

**What:** Store and validate Parsl executor configurations for SLURM clusters.

**When to use:** `clusters.list`, cluster configuration UI.

**Why:**
- Parsl's HighThroughputExecutor is recommended for HPC
- Configuration requires provider, launcher, and executor settings
- Need to persist across sessions

**Example:**
```python
# Source: Parsl documentation + quacc deployment docs
from pydantic import BaseModel, Field
from pathlib import Path
import json

class ParslClusterConfig(BaseModel):
    """Configuration for a Parsl SLURM cluster."""

    name: str = Field(..., description="Cluster display name")
    partition: str = Field(..., description="SLURM partition name")
    account: str | None = Field(None, description="SLURM account")
    nodes_per_block: int = Field(1, ge=1)
    cores_per_node: int = Field(32, ge=1)
    mem_per_node: int | None = Field(None, description="Memory in GB")
    walltime: str = Field("01:00:00", pattern=r"\d{2}:\d{2}:\d{2}")
    max_blocks: int = Field(10, ge=1)
    worker_init: str = Field("", description="Module loads, conda activate, etc.")
    scheduler_options: str = Field("", description="Additional #SBATCH directives")

    def to_parsl_config(self):
        """Generate Parsl Config object for this cluster."""
        from parsl.config import Config
        from parsl.executors import HighThroughputExecutor
        from parsl.providers import SlurmProvider
        from parsl.launchers import SrunLauncher
        from parsl.addresses import address_by_hostname

        return Config(
            executors=[
                HighThroughputExecutor(
                    label=self.name,
                    address=address_by_hostname(),
                    max_workers_per_node=1,
                    provider=SlurmProvider(
                        partition=self.partition,
                        account=self.account,
                        nodes_per_block=self.nodes_per_block,
                        cores_per_node=self.cores_per_node,
                        mem_per_node=self.mem_per_node,
                        walltime=self.walltime,
                        max_blocks=self.max_blocks,
                        init_blocks=1,
                        min_blocks=0,
                        worker_init=self.worker_init,
                        scheduler_options=self.scheduler_options,
                        launcher=SrunLauncher(),
                    ),
                )
            ],
        )

class ClusterConfigStore:
    """Persist cluster configurations in local JSON file."""

    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or Path.home() / ".crystalmath" / "clusters.json"
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

    def list_clusters(self) -> list[dict]:
        """List all configured clusters."""
        if not self.config_path.exists():
            return []

        with open(self.config_path) as f:
            data = json.load(f)

        return data.get("clusters", [])

    def get_cluster(self, name: str) -> ParslClusterConfig | None:
        """Get a specific cluster configuration."""
        for cluster in self.list_clusters():
            if cluster.get("name") == name:
                return ParslClusterConfig(**cluster)
        return None
```

**Confidence:** MEDIUM - Configuration structure verified, persistence pattern is convention

### Pattern 4: Job Metadata Store (JSON)

**What:** Store job metadata locally for TUI display. No quacc integration - purely local tracking.

**When to use:** `jobs.list` RPC handler.

**Why:**
- quacc removed `STORE` setting - no automatic persistence
- Full workflow engine integration is complex (Phase 4)
- JSON suffices for read-only display

**Example:**
```python
# Source: quacc changelog + standard JSON patterns
import json
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel
from enum import Enum

class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class JobMetadata(BaseModel):
    """Lightweight job tracking for TUI display."""

    id: str
    recipe: str  # e.g., "quacc.recipes.vasp.core.relax_job"
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    cluster: str | None = None
    work_dir: Path | None = None
    error_message: str | None = None
    results_summary: dict | None = None  # energy, forces, etc.

class JobStore:
    """Local JSON store for job metadata."""

    def __init__(self, store_path: Path | None = None):
        self.store_path = store_path or Path.home() / ".crystalmath" / "jobs.json"
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    def list_jobs(
        self,
        status: JobStatus | None = None,
        limit: int = 100,
    ) -> list[JobMetadata]:
        """List jobs, optionally filtered by status."""
        if not self.store_path.exists():
            return []

        with open(self.store_path) as f:
            data = json.load(f)

        jobs = [JobMetadata(**j) for j in data.get("jobs", [])]

        if status:
            jobs = [j for j in jobs if j.status == status]

        # Sort by created_at descending
        jobs.sort(key=lambda j: j.created_at, reverse=True)

        return jobs[:limit]
```

**Confidence:** HIGH - Standard pattern, minimal complexity

### Anti-Patterns to Avoid

- **Hardcoding recipe list:** Recipes change between quacc versions. Always introspect.
- **Assuming WORKFLOW_ENGINE is set:** Many users run without workflow engine (local mode).
- **Importing all quacc modules eagerly:** Lazy-load to avoid startup delays.
- **Storing full results in TUI database:** Store summary only; full results stay in work_dir.
- **Tight coupling to specific workflow engine:** Use abstraction layer for engine-specific code.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Recipe discovery | Hardcoded recipe list | `pkgutil.walk_packages()` + inspect | Stays current with quacc updates |
| Workflow engine detection | Manual module checks | `quacc.SETTINGS.WORKFLOW_ENGINE` | Authoritative source |
| VASP input generation | Custom templates | quacc recipe functions | Validated, community-maintained |
| Parsl config serialization | Custom format | Pydantic models + JSON | Type safety, validation |

**Key insight:** quacc is designed to be used via its recipe functions. Don't bypass the decorators or replicate their logic.

---

## Common Pitfalls

### Pitfall 1: Missing quacc Installation

**What goes wrong:** ImportError when calling RPC handlers.

**Why it happens:** quacc is optional; user may not have it installed.

**How to avoid:**
```python
@register_handler("recipes.list")
async def handle_recipes_list(controller, params):
    try:
        from crystalmath.quacc.discovery import discover_vasp_recipes
        return {"recipes": discover_vasp_recipes()}
    except ImportError:
        return {"recipes": [], "error": "quacc not installed"}
```

**Warning signs:** `ModuleNotFoundError: No module named 'quacc'`

### Pitfall 2: No Workflow Engine Configured

**What goes wrong:** Jobs submitted but nothing happens.

**Why it happens:** quacc defaults to `WORKFLOW_ENGINE=None` (local execution only).

**How to avoid:**
1. Check `SETTINGS.WORKFLOW_ENGINE` before allowing job submission
2. Display clear status in TUI: "No workflow engine configured"
3. Provide configuration guidance in error messages

**Warning signs:** Jobs run locally instead of on cluster.

### Pitfall 3: Parsl Launcher Mismatch

**What goes wrong:** Workers fail to start on SLURM nodes.

**Why it happens:** Using `SingleNodeLauncher` instead of `SrunLauncher` on SLURM.

**How to avoid:**
- Default to `SrunLauncher` when SLURM detected
- Document launcher requirements per cluster type
- Validate configuration before saving

**Warning signs:** "Worker failed to start" errors, no jobs running.

### Pitfall 4: Recipe Import Failures

**What goes wrong:** Some recipes fail to import during discovery.

**Why it happens:** Missing optional dependencies (e.g., MLIP recipes need `mace`).

**How to avoid:**
```python
try:
    module = importlib.import_module(modname)
except ImportError as e:
    # Log but continue - recipe requires missing optional dep
    logger.debug(f"Skipping {modname}: {e}")
    continue
```

**Warning signs:** Incomplete recipe list, silent failures.

### Pitfall 5: Stale QuaccSettings

**What goes wrong:** Configuration changes not reflected in running server.

**Why it happens:** quacc caches settings at import time.

**How to avoid:**
- Document that server restart may be needed after config changes
- Or use `quacc.wflow_tools.customizers.change_settings()` context manager

**Warning signs:** Old settings used despite `.quacc.yaml` changes.

---

## Code Examples

### Example 1: recipes.list RPC Handler

```python
# Source: Pattern from existing handlers.py + introspection pattern
from crystalmath.server.handlers import register_handler, Handler

@register_handler("recipes.list")
async def handle_recipes_list(
    controller,
    params: dict,
) -> dict:
    """List available quacc VASP recipes.

    Returns:
        {
            "recipes": [...],
            "quacc_version": "0.11.2",
            "error": null
        }
    """
    try:
        from crystalmath.quacc.discovery import discover_vasp_recipes
        import quacc

        recipes = discover_vasp_recipes()
        return {
            "recipes": recipes,
            "quacc_version": getattr(quacc, "__version__", "unknown"),
            "error": None,
        }
    except ImportError as e:
        return {
            "recipes": [],
            "quacc_version": None,
            "error": f"quacc not available: {e}",
        }
```

**Confidence:** HIGH - Follows existing handler pattern

### Example 2: clusters.list RPC Handler

```python
@register_handler("clusters.list")
async def handle_clusters_list(
    controller,
    params: dict,
) -> dict:
    """List configured clusters and workflow engine status.

    Returns:
        {
            "clusters": [...],
            "workflow_engine": {
                "configured": "parsl",
                "installed": ["parsl", "dask"],
            }
        }
    """
    from crystalmath.quacc.engines import get_engine_status
    from crystalmath.quacc.config import ClusterConfigStore

    store = ClusterConfigStore()

    return {
        "clusters": store.list_clusters(),
        "workflow_engine": get_engine_status(),
    }
```

**Confidence:** HIGH - Simple delegation pattern

### Example 3: Rust TUI Recipe Display (Reference)

```rust
// Example of how Rust TUI might display recipe data
// This is for planning context, not implementation in this phase

#[derive(Debug, Deserialize)]
pub struct Recipe {
    pub name: String,
    pub module: String,
    pub fullname: String,
    pub docstring: String,
    pub signature: String,
    #[serde(rename = "type")]
    pub recipe_type: String,  // "job" or "flow"
}

#[derive(Debug, Deserialize)]
pub struct RecipesListResponse {
    pub recipes: Vec<Recipe>,
    pub quacc_version: Option<String>,
    pub error: Option<String>,
}
```

**Confidence:** HIGH - Matches Python handler output structure

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| quacc STORE setting | `results_to_db()` function | v0.7.0 (2024) | No automatic persistence |
| Covalent as default | Workflow-engine-agnostic | v0.6.0 (2024) | User chooses engine |
| schemas as functions | schemas as classes | v0.10.0 (2025) | Better maintainability |
| `quacc_results.json.gz` | No automatic file | v0.7.0 (2024) | Simpler, less overhead |

**Deprecated/outdated:**
- **STORE setting:** Removed in v0.7.0. Don't use.
- **`quacc_results.json.gz`:** No longer written. Don't rely on it.
- **Old schema function API:** Classes now. Check for v0.10+ patterns.

---

## Open Questions

1. **Recipe parameter extraction**
   - What we know: Recipes have `**calc_kwargs` and specific parameters
   - What's unclear: How to extract default values and valid options programmatically
   - Recommendation: Parse docstrings or use type hints; defer full parameter UI to Phase 3

2. **Parsl monitoring integration**
   - What we know: Parsl has optional `[monitoring]` extra with dashboard
   - What's unclear: Should TUI display Parsl monitoring data?
   - Recommendation: Defer to Phase 4; focus on basic status in Phase 2

3. **Cluster config validation**
   - What we know: Invalid configs cause runtime errors
   - What's unclear: How to validate cluster reachability before save
   - Recommendation: Add optional SSH test in Phase 4 (write operations)

4. **Job results schema**
   - What we know: VaspSchema includes energy, forces, structure
   - What's unclear: Exact schema for displaying in TUI (what fields to show)
   - Recommendation: Start with energy, forces, convergence; expand based on user feedback

---

## VASP Recipe Reference

Based on quacc documentation, available VASP recipe modules:

| Module | Key Recipes | Purpose |
|--------|-------------|---------|
| `core` | `relax_job`, `static_job`, `ase_relax_job`, `double_relax_flow`, `freq_job`, `non_scf_job` | Basic calculations |
| `matpes` | `matpes_static_job` | MatPES-compatible static |
| `mp24` | MP 2024 recipes | Materials Project workflows |
| `mp_legacy` | Legacy MP recipes | Backward compatibility |
| `qmof` | QMOF recipes | MOF calculations |
| `slabs` | Slab recipes | Surface calculations |
| `fairchem` | ML-accelerated | Machine learning potentials |

---

## Sources

### Primary (HIGH confidence)

- [quacc GitHub - settings.py](https://github.com/Quantum-Accelerators/quacc/blob/main/src/quacc/settings.py) - QuaccSettings class definition
- [quacc GitHub - pyproject.toml](https://github.com/Quantum-Accelerators/quacc/blob/main/pyproject.toml) - Optional extras definition
- [quacc Intro to Jobs](https://quantum-accelerators.github.io/quacc/user/recipes/recipes_intro.html) - Recipe structure
- [quacc VASP Core Recipes](https://quantum-accelerators.github.io/quacc/reference/quacc/recipes/vasp/core.html) - VASP recipe documentation
- [quacc Decorators](https://quantum-accelerators.github.io/quacc/reference/quacc/wflow_tools/decorators.html) - @job, @flow, @subflow
- [Parsl HighThroughputExecutor](https://parsl.readthedocs.io/en/stable/stubs/parsl.executors.HighThroughputExecutor.html) - Executor configuration
- [Parsl SlurmProvider](https://parsl.readthedocs.io/en/stable/stubs/parsl.providers.SlurmProvider.html) - SLURM provider docs
- [NERSC Parsl Documentation](https://docs.nersc.gov/jobs/workflow/parsl/) - HPC configuration examples

### Secondary (MEDIUM confidence)

- [quacc Deploying Calculations](https://quantum-accelerators.github.io/quacc/user/wflow_engine/executors.html) - Workflow engine setup
- [quacc Changelog](https://quantum-accelerators.github.io/quacc/about/changelog.html) - Version history, breaking changes
- [quacc GitHub Releases](https://github.com/Quantum-Accelerators/quacc/releases) - Recent updates

### Tertiary (LOW confidence)

- [Tom Demeyere - Parsl for DFT](https://tomdemeyere.github.io/blog/2024/workflows-manager-for-dft/) - Community tutorial
- [Python pkgutil docs](https://docs.python.org/3/library/pkgutil.html) - Standard library reference

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - quacc is well-documented, Parsl is mature
- Architecture: HIGH - Follows existing IPC patterns from Phase 1
- Recipe discovery: HIGH - Standard Python introspection
- Workflow engine detection: HIGH - Verified from quacc source
- Pitfalls: MEDIUM - Based on docs + community experience

**Research date:** 2026-02-02
**Valid until:** 60 days (quacc releases monthly; check changelog)

---

## Roadmap Implications

Based on research, recommended Phase 2 plan structure:

1. **quacc discovery module** (Low risk)
   - Recipe introspection
   - Engine detection
   - ~2 hours

2. **Cluster config store** (Low risk)
   - JSON persistence
   - Pydantic models
   - ~2 hours

3. **RPC handlers** (Low risk)
   - `recipes.list`
   - `clusters.list`
   - `jobs.list` (local store only)
   - ~3 hours

4. **TUI screens** (Medium risk)
   - Recipe browser widget
   - Cluster status display
   - ~4 hours

5. **Integration tests** (Low risk)
   - Handler tests with mocked quacc
   - ~2 hours

**Estimated total:** 1-2 days focused work.

**No deeper research flags needed** - quacc patterns are well-documented and the read-only scope limits complexity.
