# Phase 2 Design Document: Remote Execution & Advanced Features

**Status:** Planning
**Target Completion:** Q2 2025
**Dependencies:** Phase 1 MVP must be complete

## Overview

Phase 2 transforms CRYSTAL-TUI from a local job manager into a comprehensive remote execution platform with workflow orchestration capabilities. This phase adds:

1. **Remote Execution** - SSH/SLURM job submission and monitoring
2. **Batch Job Management** - Multi-job submission and queue management
3. **Workflow Chaining** - DAG-based multi-step calculations
4. **Template Library** - Reusable input templates with parameter substitution
5. **Advanced Visualization** (optional) - Basic plotting and structure viewing

## Architecture Principles

### Design Goals
- **Non-blocking UI**: All remote operations use asyncio workers
- **Graceful Degradation**: Local execution still works if remote systems unavailable
- **Connection Pooling**: Reuse SSH connections for efficiency
- **Provenance Tracking**: SQLite records full workflow history
- **Extensible**: Runner abstraction supports multiple backends

### Technology Stack
- **asyncssh** - Async SSH client (not paramiko)
- **Jinja2** - Template rendering
- **SQLite** - Enhanced schema for workflows and clusters
- **Textual Workers** - Background task execution
- **asyncio.create_subprocess_exec** - For rsync and local commands

## 1. Remote Execution Architecture

### 1.1 Runner Abstraction

**Base Interface:** `src/runners/base.py`
```python
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from pathlib import Path

class BaseRunner(ABC):
    """Abstract base for all job runners."""

    @abstractmethod
    async def run_job(
        self,
        job_id: int,
        work_dir: Path,
        threads: Optional[int] = None
    ) -> AsyncIterator[str]:
        """Execute job and stream output."""
        pass

    @abstractmethod
    async def stop_job(self, job_id: int) -> bool:
        """Stop a running job."""
        pass

    @abstractmethod
    def is_job_running(self, job_id: int) -> bool:
        """Check if job is running."""
        pass
```

**Implementations:**
- `LocalRunner` (exists) - Direct subprocess execution
- `SSHRunner` (new) - Direct SSH execution on remote host
- `SLURMRunner` (new) - SLURM batch submission and polling
- `PBSRunner` (future) - PBS/Torque integration

### 1.2 SSH Runner Design

**Location:** `src/runners/ssh.py`

**Key Features:**
- Uses asyncssh for non-blocking operations
- Connection pooling (reuse connections)
- Automatic file transfer (rsync for efficiency)
- Real-time stdout/stderr streaming
- Remote process monitoring

**Implementation Pattern:**
```python
import asyncssh
from pathlib import Path
from typing import AsyncIterator, Optional, Dict

class SSHRunner(BaseRunner):
    """Execute CRYSTAL jobs on remote hosts via SSH."""

    def __init__(self, host: str, username: str, key_path: Path):
        self.host = host
        self.username = username
        self.key_path = key_path
        self._connection_pool: Dict[str, asyncssh.SSHClientConnection] = {}

    async def _get_connection(self) -> asyncssh.SSHClientConnection:
        """Get or create SSH connection."""
        key = f"{self.username}@{self.host}"
        if key in self._connection_pool:
            conn = self._connection_pool[key]
            if conn.is_open():
                return conn

        # Create new connection
        conn = await asyncssh.connect(
            self.host,
            username=self.username,
            client_keys=[str(self.key_path)],
            known_hosts=None  # Or specify path
        )
        self._connection_pool[key] = conn
        return conn

    async def _transfer_files(self, conn, local_dir: Path, remote_dir: str):
        """Transfer input files to remote host."""
        async with conn.start_sftp_client() as sftp:
            # Create remote directory
            await sftp.makedirs(remote_dir, exist_ok=True)

            # Upload input files
            for local_file in local_dir.glob("*"):
                if local_file.is_file():
                    remote_file = f"{remote_dir}/{local_file.name}"
                    await sftp.put(local_file, remote_file)

    async def run_job(
        self,
        job_id: int,
        work_dir: Path,
        threads: Optional[int] = None
    ) -> AsyncIterator[str]:
        """Execute job on remote host."""
        conn = await self._get_connection()

        # Setup remote work directory
        remote_work_dir = f"/scratch/crystal/{job_id}_{work_dir.name}"

        # Transfer files
        yield f"Transferring files to {self.host}..."
        await self._transfer_files(conn, work_dir, remote_work_dir)

        # Build command
        threads = threads or 4
        command = f"""
        cd {remote_work_dir}
        export OMP_NUM_THREADS={threads}
        crystalOMP < input.d12 > output.out 2>&1
        """

        # Execute and stream output
        result = await conn.run(command, check=False)

        async for line in result.stdout:
            yield line

        # Download results
        yield "\nDownloading results..."
        await self._download_results(conn, remote_work_dir, work_dir)

        yield f"\nJob completed with exit code {result.exit_status}"
```

### 1.3 SLURM Runner Design

**Location:** `src/runners/slurm.py`

**Key Features:**
- Generates submission scripts dynamically
- Submits jobs via `sbatch`
- Polls status with `squeue` (non-blocking background worker)
- Handles job arrays for parameter sweeps
- Automatic result retrieval when complete

**Implementation Pattern:**
```python
class SLURMRunner(BaseRunner):
    """Execute CRYSTAL jobs via SLURM batch system."""

    def __init__(self, ssh_runner: SSHRunner, partition: str = "default"):
        self.ssh_runner = ssh_runner
        self.partition = partition
        self._job_ids: Dict[int, str] = {}  # Maps our job_id to SLURM job_id

    async def run_job(
        self,
        job_id: int,
        work_dir: Path,
        threads: Optional[int] = None,
        nodes: int = 1,
        time_limit: str = "1:00:00"
    ) -> AsyncIterator[str]:
        """Submit job to SLURM and monitor."""

        # Generate submission script
        script = self._generate_slurm_script(
            work_dir.name,
            threads or 4,
            nodes,
            time_limit
        )

        # Write script locally and transfer
        script_path = work_dir / "job.slurm"
        script_path.write_text(script)

        # Submit via SSH
        conn = await self.ssh_runner._get_connection()
        remote_dir = f"/scratch/crystal/{job_id}_{work_dir.name}"

        # Transfer files
        yield "Transferring files to cluster..."
        await self.ssh_runner._transfer_files(conn, work_dir, remote_dir)

        # Submit job
        result = await conn.run(f"cd {remote_dir} && sbatch job.slurm")
        slurm_job_id = self._parse_job_id(result.stdout)
        self._job_ids[job_id] = slurm_job_id

        yield f"Job submitted: SLURM ID {slurm_job_id}"
        yield f"Status: PENDING"

        # Poll status until complete
        while True:
            status = await self._check_status(conn, slurm_job_id)
            yield f"Status: {status}"

            if status in ["COMPLETED", "FAILED", "TIMEOUT"]:
                break

            await asyncio.sleep(30)  # Poll every 30 seconds

        # Download results
        if status == "COMPLETED":
            yield "\nDownloading results..."
            await self.ssh_runner._download_results(conn, remote_dir, work_dir)

    def _generate_slurm_script(
        self,
        job_name: str,
        threads: int,
        nodes: int,
        time_limit: str
    ) -> str:
        """Generate SLURM submission script."""
        return f"""#!/bin/bash
#SBATCH --job-name={job_name}
#SBATCH --partition={self.partition}
#SBATCH --nodes={nodes}
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task={threads}
#SBATCH --time={time_limit}
#SBATCH --output=slurm-%j.out
#SBATCH --error=slurm-%j.err

# Load modules
module load crystal/23

# Set OpenMP threads
export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

# Run calculation
crystalOMP < input.d12 > output.out 2>&1
"""

    async def _check_status(self, conn, slurm_job_id: str) -> str:
        """Check SLURM job status."""
        result = await conn.run(f"squeue -j {slurm_job_id} -h -o %T")
        status_line = result.stdout.strip()
        return status_line if status_line else "COMPLETED"
```

### 1.4 Connection Management

**Location:** `src/core/connections.py`

```python
class ConnectionManager:
    """Manages SSH connections to remote clusters."""

    def __init__(self):
        self._pools: Dict[str, SSHRunner] = {}

    def add_cluster(
        self,
        name: str,
        host: str,
        username: str,
        key_path: Path
    ):
        """Register a new cluster."""
        self._pools[name] = SSHRunner(host, username, key_path)

    def get_runner(self, cluster_name: str) -> SSHRunner:
        """Get runner for a cluster."""
        return self._pools[cluster_name]

    def list_clusters(self) -> list[str]:
        """List registered clusters."""
        return list(self._pools.keys())
```

### 1.5 Database Schema Extensions

**Location:** `src/core/database.py` (additions)

```sql
-- New tables for Phase 2

CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    hostname TEXT NOT NULL,
    username TEXT NOT NULL,
    key_path TEXT NOT NULL,
    runner_type TEXT NOT NULL CHECK(runner_type IN ('ssh', 'slurm', 'pbs')),
    default_partition TEXT,
    active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS remote_jobs (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    cluster_id INTEGER NOT NULL REFERENCES clusters(id),
    scheduler_id TEXT,  -- SLURM/PBS job ID
    remote_work_dir TEXT,
    submitted_at TIMESTAMP,
    UNIQUE(job_id)
);

-- Add cluster_id column to jobs table
ALTER TABLE jobs ADD COLUMN cluster_id INTEGER REFERENCES clusters(id);
```

## 2. Batch Job Management

### 2.1 Batch Submission UI

**Location:** `src/tui/screens/batch_submit.py`

**Features:**
- Multi-select in job list (Shift+Arrow, Space to toggle)
- Batch action modal: "Submit All", "Stop All", "Delete All"
- Progress indicator showing N/M jobs submitted
- Automatic spacing between submissions (avoid overwhelming scheduler)

**Implementation:**
```python
class BatchSubmitScreen(Screen):
    """Screen for batch job submission."""

    def compose(self):
        yield Header()
        yield Label("Select jobs to submit (Space to select)")
        yield DataTable(id="batch_jobs")
        yield Button("Submit Selected", id="submit_batch")

    async def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "submit_batch":
            selected_jobs = self._get_selected_jobs()

            # Submit jobs with delay
            for i, job_id in enumerate(selected_jobs):
                self.post_message(JobSubmitted(job_id))
                self.notify(f"Submitted job {i+1}/{len(selected_jobs)}")
                await asyncio.sleep(2)  # Delay to avoid overwhelming scheduler
```

### 2.2 Queue Management

**Location:** `src/core/queue.py`

```python
class QueueManager:
    """Manages job queue and submission order."""

    def __init__(self, db: Database):
        self.db = db
        self._queue: list[int] = []

    async def enqueue(self, job_id: int, priority: int = 0):
        """Add job to queue."""
        self._queue.append(job_id)
        self._queue.sort(key=lambda j: self._get_priority(j), reverse=True)

    async def submit_next(self, runner: BaseRunner) -> Optional[int]:
        """Submit next job in queue."""
        if not self._queue:
            return None

        job_id = self._queue.pop(0)
        # Submit job...
        return job_id
```

## 3. Workflow Chaining

### 3.1 Workflow Definition

**Location:** `src/core/workflow.py`

**DAG Representation:**
```python
from dataclasses import dataclass
from typing import List, Dict, Any

@dataclass
class WorkflowStep:
    """Defines a single step in a workflow."""
    name: str
    template_name: str
    parameters: Dict[str, Any]
    dependencies: List[str]  # Names of steps this depends on
    output_parsers: List[str]  # Functions to parse this step's output

@dataclass
class Workflow:
    """Defines a multi-step calculation workflow."""
    name: str
    steps: List[WorkflowStep]

    def get_ready_steps(self, completed_steps: set[str]) -> List[WorkflowStep]:
        """Get steps with all dependencies satisfied."""
        ready = []
        for step in self.steps:
            if step.name not in completed_steps:
                deps_satisfied = all(dep in completed_steps for dep in step.dependencies)
                if deps_satisfied:
                    ready.append(step)
        return ready
```

**Example Workflow Definition:**
```python
# Geometry optimization → Single point → Band structure
geo_opt_workflow = Workflow(
    name="geo_opt_bands",
    steps=[
        WorkflowStep(
            name="geom_opt",
            template_name="optimization.d12.j2",
            parameters={"maxcyc": 100, "toldeg": 0.0003},
            dependencies=[],
            output_parsers=["extract_geometry"]
        ),
        WorkflowStep(
            name="single_point",
            template_name="scf.d12.j2",
            parameters={},
            dependencies=["geom_opt"],
            output_parsers=["extract_energy"]
        ),
        WorkflowStep(
            name="band_structure",
            template_name="bands.d12.j2",
            parameters={"kpath": "auto"},
            dependencies=["single_point"],
            output_parsers=["extract_bands"]
        )
    ]
)
```

### 3.2 Workflow Orchestrator

**Location:** `src/core/orchestrator.py`

```python
class WorkflowOrchestrator:
    """Manages workflow execution."""

    def __init__(self, db: Database, runner: BaseRunner):
        self.db = db
        self.runner = runner
        self._active_workflows: Dict[int, Workflow] = {}

    async def start_workflow(self, workflow_id: int) -> None:
        """Start executing a workflow."""
        workflow = self.db.get_workflow(workflow_id)
        completed_steps = set()

        while True:
            ready_steps = workflow.get_ready_steps(completed_steps)

            if not ready_steps:
                # Check if all steps complete
                if len(completed_steps) == len(workflow.steps):
                    self.db.update_workflow(workflow_id, status="COMPLETED")
                    break
                else:
                    # Wait for running jobs
                    await asyncio.sleep(10)
                    continue

            # Submit ready steps
            for step in ready_steps:
                job_id = await self._submit_workflow_step(workflow_id, step)
                # Mark as submitted (not completed yet)

            # Wait for some jobs to complete
            await asyncio.sleep(30)

            # Update completed steps
            completed_steps = self._get_completed_steps(workflow_id)

    async def _submit_workflow_step(
        self,
        workflow_id: int,
        step: WorkflowStep
    ) -> int:
        """Submit a single workflow step as a job."""
        # Generate input from template
        input_content = self._render_template(
            step.template_name,
            step.parameters
        )

        # Create job
        job_id = self.db.create_job(
            name=f"{workflow_id}_{step.name}",
            work_dir=f"calculations/{workflow_id}/{step.name}",
            input_content=input_content
        )

        # Link to workflow
        self.db.link_job_to_workflow(job_id, workflow_id, step.name)

        # Submit
        await self.runner.run_job(job_id, ...)

        return job_id
```

### 3.3 Database Schema for Workflows

```sql
CREATE TABLE IF NOT EXISTS workflows (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    definition TEXT NOT NULL,  -- JSON of Workflow object
    status TEXT NOT NULL CHECK(status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workflow_jobs (
    workflow_id INTEGER NOT NULL REFERENCES workflows(id),
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    step_name TEXT NOT NULL,
    PRIMARY KEY (workflow_id, job_id)
);
```

## 4. Template Library

### 4.1 Template System

**Location:** `src/core/templates.py`

**Uses Jinja2 for flexible templating:**
```python
from jinja2 import Environment, FileSystemLoader
from pathlib import Path

class TemplateManager:
    """Manages CRYSTAL input templates."""

    def __init__(self, template_dir: Path):
        self.template_dir = template_dir
        self.env = Environment(loader=FileSystemLoader(str(template_dir)))

    def render(self, template_name: str, parameters: Dict[str, Any]) -> str:
        """Render template with parameters."""
        template = self.env.get_template(template_name)
        return template.render(**parameters)

    def list_templates(self) -> List[str]:
        """List available templates."""
        return [t.name for t in self.template_dir.glob("*.j2")]

    def get_template_info(self, template_name: str) -> Dict[str, Any]:
        """Get template metadata (parameters, description)."""
        # Parse template header comments for metadata
        template_path = self.template_dir / template_name
        # ... parse metadata from comments ...
```

**Example Template:** `templates/optimization.d12.j2`
```jinja2
{# CRYSTAL Geometry Optimization Template
   Parameters:
     - maxcyc: Maximum optimization cycles (default: 100)
     - toldeg: Convergence tolerance (default: 0.0003)
     - basis_set: Basis set name (required)
     - functional: DFT functional (default: PBE)
#}
GEOM OPTIMIZATION
{{ maxcyc | default(100) }}
TOLDEG {{ toldeg | default(0.0003) }}
END
DFT
{{ functional | default('PBE') }}
END
BASIS
{{ basis_set }}
END
```

### 4.2 Template Browser UI

**Location:** `src/tui/screens/template_browser.py`

```python
class TemplateBrowserScreen(Screen):
    """Browse and select calculation templates."""

    def compose(self):
        yield Header()
        yield DataTable(id="templates")
        yield TextArea(id="template_preview", read_only=True)
        yield Button("Use Template", id="use_template")

    def on_mount(self):
        # Load templates into table
        templates = self.app.template_manager.list_templates()
        table = self.query_one("#templates", DataTable)
        table.add_columns("Name", "Description")
        for tmpl in templates:
            info = self.app.template_manager.get_template_info(tmpl)
            table.add_row(tmpl, info.get("description", ""))
```

### 4.3 Parameter Form Generation

**Location:** `src/tui/screens/template_form.py`

Auto-generate input forms from template metadata:
```python
class TemplateFormScreen(Screen):
    """Form for entering template parameters."""

    def __init__(self, template_name: str):
        super().__init__()
        self.template_name = template_name

    def compose(self):
        info = self.app.template_manager.get_template_info(self.template_name)

        yield Header()
        yield Label(f"Template: {self.template_name}")

        # Auto-generate form fields from template metadata
        for param in info["parameters"]:
            yield Label(param["name"])
            yield Input(
                placeholder=param.get("default", ""),
                id=f"param_{param['name']}"
            )

        yield Button("Generate Input", id="generate")
```

## 5. Advanced Visualization (Optional)

### 5.1 Result Plotting

**Location:** `src/visualization/plots.py`

**Dependencies:** `matplotlib`, `plotly` (for interactive plots in terminal)

**Features:**
- Energy vs. optimization step
- Band structure plots
- DOS plots
- Convergence plots (energy, forces, displacement)

**Implementation:**
```python
import matplotlib.pyplot as plt
from pathlib import Path

class ResultPlotter:
    """Generate plots from CRYSTAL results."""

    def plot_energy_convergence(self, output_file: Path) -> Path:
        """Plot energy vs. SCF cycle."""
        # Parse energies from output
        energies = self._parse_energies(output_file)

        plt.figure()
        plt.plot(energies)
        plt.xlabel("SCF Cycle")
        plt.ylabel("Energy (Ha)")
        plt.title("SCF Convergence")

        plot_path = output_file.parent / "energy_convergence.png"
        plt.savefig(plot_path)
        plt.close()

        return plot_path
```

### 5.2 Structure Viewer

**Integration with ASE GUI (separate process):**
```python
async def view_structure(self, geometry_file: Path):
    """Launch ASE GUI to view structure."""
    proc = await asyncio.create_subprocess_exec(
        "ase", "gui", str(geometry_file)
    )
    await proc.wait()
```

## Implementation Roadmap

### Priority 1: Core Remote Execution (4-6 weeks)
1. ✅ **SSH Runner** - Basic remote execution
   - Connection pooling
   - File transfer (asyncssh SFTP)
   - Remote process monitoring
   - Error handling

2. ✅ **SLURM Runner** - Batch system integration
   - Script generation
   - Job submission
   - Status polling
   - Result retrieval

3. ✅ **Connection Manager** - Cluster registration
   - Multi-cluster support
   - Key-based authentication
   - Connection health monitoring

4. ✅ **Database Extensions** - Track remote jobs
   - Clusters table
   - Remote jobs table
   - Enhanced job tracking

### Priority 2: Batch & Queue Management (2-3 weeks)
5. ✅ **Batch Submission UI** - Multi-select interface
6. ✅ **Queue Manager** - Job queue with priorities
7. ✅ **Progress Tracking** - Real-time queue status

### Priority 3: Workflow System (3-4 weeks)
8. ✅ **Workflow Definition** - DAG-based workflow model
9. ✅ **Workflow Orchestrator** - Multi-step execution
10. ✅ **Output Parsers** - Extract data between steps
11. ✅ **Conditional Execution** - Branch based on results

### Priority 4: Templates (2 weeks)
12. ✅ **Template System** - Jinja2 integration
13. ✅ **Template Library** - Common calculation types
14. ✅ **Template Browser** - UI for template selection
15. ✅ **Parameter Forms** - Auto-generated input forms

### Priority 5: Visualization (Optional, 1-2 weeks)
16. ⏳ **Result Plotting** - Energy, bands, DOS
17. ⏳ **Structure Viewer** - ASE GUI integration

## Testing Strategy

### Unit Tests
- Mock asyncssh connections
- Test workflow DAG resolution
- Test template rendering
- Test queue priority sorting

### Integration Tests
- End-to-end remote submission (requires test cluster)
- Workflow execution with mock jobs
- Template → Input generation → Job creation

### Manual Testing Checklist
- [ ] Submit job to real SLURM cluster
- [ ] Monitor job status updates
- [ ] Download results automatically
- [ ] Execute 3-step workflow
- [ ] Use template to create job
- [ ] Handle connection failures gracefully

## Configuration

**Location:** `~/.config/crystal-tui/config.toml`

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
runner_type = "slurm"
default_partition = "batch"
```

## Security Considerations

1. **SSH Keys**: Only support key-based auth (no passwords)
2. **Key Storage**: Keys stay on disk, never in database
3. **Connection Validation**: Verify host keys on first connection
4. **File Permissions**: Ensure config files are 0600
5. **Input Sanitization**: Validate all user input before shell execution

## Performance Considerations

1. **Connection Pooling**: Reuse SSH connections (10x faster)
2. **Rsync for Large Files**: Use rsync for result downloads
3. **Background Polling**: Poll SLURM every 30-60s (not per second)
4. **Async Everything**: All network I/O must be async
5. **SQLite Indexes**: Index on job status, workflow ID, cluster ID

## Migration Path from Phase 1

1. **Backward Compatibility**: Local execution still works without clusters
2. **Optional Remote**: Remote features only enabled if clusters configured
3. **Database Migration**: Add new tables, don't modify existing schema
4. **UI Changes**: Add "Cluster" column to job table (can be NULL for local)

## Future Extensions (Phase 3+)

- **PBS/Torque Support** - Additional batch systems
- **Parameter Sweep UI** - Visual parameter space exploration
- **Workflow Templates** - Pre-built multi-step workflows
- **Result Comparison** - Side-by-side job comparison
- **Export to AiiDA** - Integration with workflow management system
- **REST API** - Web interface to TUI backend
- **Multi-user Support** - Shared project database

## Success Criteria

Phase 2 is complete when:
- [ ] User can register a remote cluster via UI
- [ ] User can submit job to SLURM cluster
- [ ] TUI shows real-time status updates from cluster
- [ ] Results automatically download when job completes
- [ ] User can define and execute a 3-step workflow
- [ ] User can create job from template with parameter form
- [ ] Batch submission works for 10+ jobs
- [ ] All operations are async (UI never freezes)
- [ ] Documentation includes cluster setup guide
- [ ] At least 80% test coverage on new code

---

**Next Steps:**
1. Review this design with team
2. Create detailed issues for each component
3. Implement SSH Runner (highest priority)
4. Write tests as we go (TDD)
5. Document cluster configuration process
