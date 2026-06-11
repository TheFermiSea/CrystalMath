# AiiDA Integration Design

## Overview

This document outlines the architecture for migrating CRYSTAL-TOOLS TUI from a lightweight SQLite backend to a full AiiDA backend, providing enterprise-grade provenance tracking, workflow management, and integration with the computational materials science ecosystem.

## Executive Summary

**Goal**: Replace TUI's custom workflow engine with AiiDA's mature infrastructure while preserving the terminal UI experience.

**Timeline**: 8-12 weeks (phased approach)

**Benefits**:
- ✅ Full provenance tracking (who, when, why, how)
- ✅ Mature workflow engine with WorkChains
- ✅ Integration with aiida-crystal-dft plugin ecosystem
- ✅ Web interface via AiiDA Lab (future)
- ✅ REST API for external integrations
- ✅ PostgreSQL-backed data management
- ✅ Community-standard approach

**Trade-offs**:
- ⚠️ Requires PostgreSQL + RabbitMQ infrastructure
- ⚠️ Heavier resource footprint
- ⚠️ Steeper learning curve for developers
- ⚠️ Migration complexity for existing data

---

## Architecture Comparison

### Current TUI Architecture

```
┌─────────────────────────────────────────────────────┐
│                   TUI (Textual)                     │
│  ┌──────────┐  ┌───────────┐  ┌─────────────────┐ │
│  │  Screens │  │  Widgets  │  │  App Controller  │ │
│  └────┬─────┘  └─────┬─────┘  └────────┬─────────┘ │
└───────┼──────────────┼─────────────────┼───────────┘
        │              │                 │
┌───────▼──────────────▼─────────────────▼───────────┐
│                Core Logic Layer                     │
│  ┌──────────┐  ┌─────────────┐  ┌───────────────┐ │
│  │ Database │  │ Orchestrator│  │ Queue Manager │ │
│  │(SQLite)  │  │  (Custom)   │  │   (Custom)    │ │
│  └────┬─────┘  └──────┬──────┘  └───────┬───────┘ │
└───────┼────────────────┼──────────────────┼─────────┘
        │                │                  │
┌───────▼────────────────▼──────────────────▼─────────┐
│               Runner Layer                          │
│  ┌──────────┐  ┌──────────┐  ┌─────────────────┐  │
│  │  Local   │  │   SSH    │  │     SLURM       │  │
│  │  Runner  │  │  Runner  │  │     Runner      │  │
│  └──────────┘  └──────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### Target AiiDA-Integrated Architecture

```
┌─────────────────────────────────────────────────────┐
│                 TUI (Textual) - UNCHANGED           │
│  ┌──────────┐  ┌───────────┐  ┌─────────────────┐ │
│  │  Screens │  │  Widgets  │  │  App Controller  │ │
│  └────┬─────┘  └─────┬─────┘  └────────┬─────────┘ │
└───────┼──────────────┼─────────────────┼───────────┘
        │              │                 │
┌───────▼──────────────▼─────────────────▼───────────┐
│            AiiDA Adapter Layer (NEW)                │
│  ┌─────────────────┐  ┌──────────────────────────┐ │
│  │   AiiDA Query   │  │  WorkChain Submitter     │ │
│  │     Builder     │  │     (replaces            │ │
│  │  (replaces DB)  │  │   Orchestrator)          │ │
│  └────────┬────────┘  └────────┬─────────────────┘ │
└───────────┼──────────────────────┼───────────────────┘
            │                      │
┌───────────▼──────────────────────▼───────────────────┐
│               AiiDA Core (2.7.1)                     │
│  ┌─────────────┐  ┌───────────────┐  ┌───────────┐ │
│  │ PostgreSQL  │  │   RabbitMQ    │  │  Daemon   │ │
│  │   (ORM)     │  │  (messaging)  │  │  (jobs)   │ │
│  └──────┬──────┘  └───────┬───────┘  └─────┬─────┘ │
└─────────┼──────────────────┼──────────────────┼─────┘
          │                  │                  │
┌─────────▼──────────────────▼──────────────────▼─────┐
│           AiiDA Process Layer                       │
│  ┌────────────────┐  ┌──────────────────────────┐  │
│  │   CalcJobs     │  │      WorkChains          │  │
│  │  (CRYSTAL23)   │  │   (Workflow logic)       │  │
│  └───────┬────────┘  └────────┬─────────────────┘  │
└──────────┼──────────────────────┼────────────────────┘
           │                      │
┌──────────▼──────────────────────▼────────────────────┐
│         AiiDA Computer/Transport Layer               │
│  ┌──────────┐  ┌──────────┐  ┌─────────────────┐   │
│  │  Local   │  │   SSH    │  │     SLURM       │   │
│  │ Computer │  │Transport │  │    Scheduler    │   │
│  └──────────┘  └──────────┘  └─────────────────┘   │
└──────────────────────────────────────────────────────┘
```

---

## Phase 1: Infrastructure Setup (Week 1-2)

### 1.1 Install AiiDA and Dependencies

**New Dependencies**:
```toml
# tui/pyproject.toml [dependencies]
aiida-core = "~=2.7"
aiida-crystal-dft = {git = "https://github.com/tilde-lab/aiida-crystal-dft.git"}
psycopg2-binary = "^2.9"  # PostgreSQL adapter
```

**Infrastructure Requirements**:
- PostgreSQL 12+ database
- RabbitMQ message broker (optional but recommended for daemon)
- AiiDA profile configuration

**Installation Steps**:
```bash
# Install PostgreSQL (macOS)
brew install postgresql@14
brew services start postgresql@14

# Install RabbitMQ
brew install rabbitmq
brew services start rabbitmq

# Create AiiDA profile
verdi quicksetup
```

### 1.2 Profile Configuration

**AiiDA Profile** (`~/.aiida/config.json`):
```json
{
  "profiles": {
    "crystal-tui": {
      "database_hostname": "localhost",
      "database_port": 5432,
      "database_name": "aiida_crystal_tui",
      "database_username": "aiida_user",
      "database_password": "<secure-password>",
      "broker_protocol": "amqp",
      "broker_host": "127.0.0.1",
      "broker_port": 5672
    }
  }
}
```

**TUI Configuration Update**:
```python
# tui/src/core/config.py
class AiiDAConfig:
    """AiiDA-specific configuration."""
    profile_name: str = "crystal-tui"
    daemon_enabled: bool = True
    computer_name: str = "localhost"
    code_label: str = "crystalOMP"
```

---

## Phase 2: AiiDA Adapter Layer (Week 3-4)

### 2.1 Replace Database Layer

**Current**: `src/core/database.py` (SQLite-based)
**Target**: `src/aiida/query_adapter.py` (AiiDA QueryBuilder wrapper)

```python
# tui/src/aiida/query_adapter.py
"""
AiiDA QueryBuilder adapter to maintain TUI's database interface.
"""
from aiida import load_profile, orm
from aiida.orm import QueryBuilder
from typing import List, Dict, Optional
from datetime import datetime

class AiiDAQueryAdapter:
    """
    Adapter that translates TUI database calls to AiiDA QueryBuilder queries.
    Maintains compatibility with existing TUI code.
    """

    def __init__(self, profile_name: str = "crystal-tui"):
        """Initialize AiiDA and load profile."""
        load_profile(profile_name)
        self.profile = profile_name

    def list_jobs(self, status: Optional[str] = None) -> List[Dict]:
        """
        List jobs (replaces database.list_jobs()).

        Maps to AiiDA CalcJobNodes.
        """
        qb = QueryBuilder()
        qb.append(orm.CalcJobNode, tag="calc")

        if status:
            # Map TUI status to AiiDA process state
            aiida_state = self._map_status_to_aiida_state(status)
            qb.add_filter(orm.CalcJobNode, {"attributes.process_state": aiida_state})

        qb.add_projection(orm.CalcJobNode, ["id", "label", "ctime", "mtime"])

        jobs = []
        for node in qb.all():
            jobs.append({
                "id": node[0],
                "name": node[1],
                "created_at": node[2],
                "updated_at": node[3],
                "status": self._aiida_state_to_status(node),
            })

        return jobs

    def get_job(self, job_id: int) -> Optional[Dict]:
        """Get job details by ID."""
        try:
            node = orm.load_node(job_id)
            if not isinstance(node, orm.CalcJobNode):
                return None

            return {
                "id": node.pk,
                "name": node.label,
                "status": self._aiida_state_to_status(node),
                "input_content": self._extract_input_content(node),
                "results_json": self._extract_results(node),
                "work_dir": node.get_remote_workdir() if node.is_finished else None,
                "created_at": node.ctime,
                "updated_at": node.mtime,
            }
        except Exception:
            return None

    def create_job(self, name: str, input_content: str, **kwargs) -> int:
        """
        Create a new job (replaces database.create_job()).

        Returns AiiDA CalcJobNode PK.
        """
        # This will be replaced by WorkChain submission in Phase 3
        # For now, store as draft node
        from aiida.plugins import DataFactory

        # Create StructureData (if geometry provided)
        # Create input parameters
        # Return node PK
        pass

    def update_status(self, job_id: int, status: str):
        """Update job status (monitoring only - AiiDA manages state)."""
        # AiiDA manages CalcJob state automatically
        # This becomes a no-op or read-only status query
        pass

    @staticmethod
    def _map_status_to_aiida_state(status: str) -> str:
        """Map TUI status to AiiDA ProcessState."""
        mapping = {
            "pending": "created",
            "queued": "created",
            "running": "running",
            "completed": "finished",
            "failed": "excepted",
            "cancelled": "killed",
        }
        return mapping.get(status, "created")

    @staticmethod
    def _aiida_state_to_status(node) -> str:
        """Map AiiDA ProcessState to TUI status."""
        state = node.process_state
        if state in ["created", "waiting"]:
            return "pending"
        elif state == "running":
            return "running"
        elif state == "finished":
            return "completed" if node.is_finished_ok else "failed"
        elif state in ["excepted", "killed"]:
            return "failed"
        else:
            return "unknown"

    @staticmethod
    def _extract_input_content(node) -> str:
        """Extract d12 input file from AiiDA node inputs."""
        # Extract from node.inputs.parameters or stored files
        return ""

    @staticmethod
    def _extract_results(node) -> str:
        """Extract results JSON from AiiDA node outputs."""
        if not node.is_finished_ok:
            return "{}"

        # Extract from node.outputs
        return "{}"
```

### 2.2 Database Migration Utility

```python
# tui/src/aiida/migration.py
"""Migrate existing SQLite database to AiiDA."""

class DatabaseMigrator:
    """Migrate TUI SQLite jobs to AiiDA nodes."""

    def __init__(self, sqlite_path: str, aiida_profile: str):
        self.sqlite_conn = sqlite3.connect(sqlite_path)
        load_profile(aiida_profile)

    def migrate_jobs(self):
        """Migrate all jobs from SQLite to AiiDA."""
        cursor = self.sqlite_conn.execute("SELECT * FROM jobs")
        for row in cursor:
            self._migrate_single_job(row)

    def _migrate_single_job(self, row):
        """Migrate a single job to AiiDA CalcJobNode."""
        # Create node with provenance
        # Link inputs/outputs
        # Preserve timestamps
        pass
```

---

## Phase 3: CalcJob Implementation (Week 5-6)

### 3.1 CRYSTAL23 CalcJob

**Option A**: Use `aiida-crystal-dft` plugin (if mature)
**Option B**: Implement custom CalcJob (more control)

```python
# tui/src/aiida/calcjobs/crystal23.py
"""
AiiDA CalcJob for CRYSTAL23 calculations.
"""
from aiida import orm
from aiida.engine import CalcJob
from aiida.common import datastructures

class Crystal23Calculation(CalcJob):
    """
    AiiDA CalcJob for running CRYSTAL23 crystalOMP/PcrystalOMP.

    Replaces: src/runners/local.py, ssh_runner.py, slurm_runner.py
    """

    @classmethod
    def define(cls, spec):
        """Define inputs, outputs, and exit codes."""
        super().define(spec)

        # Inputs
        spec.input("structure", valid_type=orm.StructureData,
                   help="Crystal structure")
        spec.input("parameters", valid_type=orm.Dict,
                   help="CRYSTAL23 input parameters")
        spec.input("settings", valid_type=orm.Dict, required=False,
                   help="Additional settings (basis set, etc.)")
        spec.input("metadata.options.resources", valid_type=dict,
                   default={"num_machines": 1, "num_mpiprocs_per_machine": 1})

        # Outputs
        spec.output("output_parameters", valid_type=orm.Dict,
                    help="Parsed results (energy, convergence)")
        spec.output("output_structure", valid_type=orm.StructureData,
                    required=False,
                    help="Optimized structure (if geometry optimization)")
        spec.output("remote_folder", valid_type=orm.RemoteData,
                    help="Remote work directory")

        # Exit codes
        spec.exit_code(300, "ERROR_NO_CONVERGENCE",
                       message="SCF did not converge")
        spec.exit_code(400, "ERROR_OUTPUT_PARSING",
                       message="Failed to parse output file")

    def prepare_for_submission(self, folder):
        """
        Create input files and configure job submission.

        Replaces: runners/*.py submit() methods
        """
        from aiida.common import InputValidationError

        # Generate d12 input file
        input_filename = self.options.input_filename
        with folder.open(input_filename, "w") as f:
            f.write(self._generate_d12_input())

        # Setup calculation
        codeinfo = datastructures.CodeInfo()
        codeinfo.code_uuid = self.inputs.code.uuid
        codeinfo.stdin_name = input_filename
        codeinfo.stdout_name = self.options.output_filename

        # Setup job resources
        calcinfo = datastructures.CalcInfo()
        calcinfo.codes_info = [codeinfo]
        calcinfo.local_copy_list = []
        calcinfo.remote_copy_list = []
        calcinfo.retrieve_list = [
            self.options.output_filename,
            "fort.9",   # Wave function
            "fort.98",  # Formatted wave function
            ["*.hessopt", ".", 0],  # Hessian files (optional)
        ]

        return calcinfo

    def _generate_d12_input(self) -> str:
        """Generate CRYSTAL23 d12 input file from AiiDA inputs."""
        structure = self.inputs.structure
        parameters = self.inputs.parameters.get_dict()

        # Generate input using templates or direct generation
        # Similar to current template system but structured
        lines = []
        lines.append(structure.get_crystal_input())
        lines.append(parameters.get("basis_set", ""))
        lines.append(parameters.get("hamiltonian", "DFT\nB3LYP"))
        # ... more input generation logic

        return "\n".join(lines)


class Crystal23Parser(orm.Parser):
    """
    Parser for CRYSTAL23 output files.

    Replaces: src/runners/local.py:_parse_results()
    """

    def parse(self, **kwargs):
        """
        Parse CRYSTAL23 output file.

        Uses CRYSTALpytools if available, fallback to manual parsing.
        """
        try:
            from CRYSTALpytools.crystal_io import Crystal_output
        except ImportError:
            return self._fallback_parse()

        output_filename = self.node.get_option("output_filename")

        try:
            with self.retrieved.open(output_filename, "r") as f:
                cry_out = Crystal_output(f.read())

            # Extract results
            results = {
                "final_energy": cry_out.get_final_energy(),
                "convergence_achieved": cry_out.is_converged(),
                "scf_iterations": cry_out.get_scf_iterations(),
            }

            # Store as output node
            self.out("output_parameters", orm.Dict(dict=results))

            return 0  # Success
        except Exception as e:
            self.logger.error(f"Failed to parse output: {e}")
            return self.exit_codes.ERROR_OUTPUT_PARSING

    def _fallback_parse(self):
        """Fallback parser if CRYSTALpytools unavailable."""
        # Manual regex-based parsing
        pass
```

---

## Phase 4: WorkChain Implementation (Week 7-8)

### 4.1 CRYSTAL23 Base WorkChain

```python
# tui/src/aiida/workchains/crystal_base.py
"""
Base WorkChain for CRYSTAL23 calculations.

Replaces: src/core/orchestrator.py
"""
from aiida import orm
from aiida.engine import WorkChain, ToContext, if_

class CrystalBaseWorkChain(WorkChain):
    """
    Base WorkChain for CRYSTAL23 with error handling and restarts.

    Provides:
    - Automatic restart on recoverable errors
    - SCF convergence handling
    - Result validation
    """

    @classmethod
    def define(cls, spec):
        """Define WorkChain specification."""
        super().define(spec)

        # Inputs
        spec.input("structure", valid_type=orm.StructureData)
        spec.input("parameters", valid_type=orm.Dict)
        spec.input("code", valid_type=orm.Code)
        spec.input("options", valid_type=orm.Dict)

        # Outputs
        spec.output("output_parameters", valid_type=orm.Dict)
        spec.output("output_structure", valid_type=orm.StructureData, required=False)

        # Workflow outline
        spec.outline(
            cls.setup,
            cls.validate_inputs,
            if_(cls.should_run_scf)(
                cls.run_scf,
                cls.inspect_scf,
            ),
            cls.results,
        )

        # Exit codes
        spec.exit_code(400, "ERROR_SCF_FAILED",
                       message="SCF calculation failed")

    def setup(self):
        """Initialize context."""
        self.ctx.restart_count = 0
        self.ctx.max_restarts = 3

    def validate_inputs(self):
        """Validate input parameters."""
        # Check structure validity
        # Check parameters consistency
        pass

    def should_run_scf(self):
        """Determine if SCF should run."""
        return True

    def run_scf(self):
        """Submit CRYSTAL23 CalcJob."""
        inputs = {
            "code": self.inputs.code,
            "structure": self.inputs.structure,
            "parameters": self.inputs.parameters,
            "metadata": {
                "options": self.inputs.options.get_dict(),
            },
        }

        future = self.submit(Crystal23Calculation, **inputs)
        return ToContext(scf_calc=future)

    def inspect_scf(self):
        """Inspect SCF results and handle errors."""
        calc = self.ctx.scf_calc

        if not calc.is_finished_ok:
            if self.ctx.restart_count < self.ctx.max_restarts:
                self.report("SCF failed, attempting restart")
                self.ctx.restart_count += 1
                # Modify parameters for restart
                return self.run_scf()
            else:
                return self.exit_codes.ERROR_SCF_FAILED

        return 0

    def results(self):
        """Collect and validate results."""
        calc = self.ctx.scf_calc
        self.out("output_parameters", calc.outputs.output_parameters)
        if "output_structure" in calc.outputs:
            self.out("output_structure", calc.outputs.output_structure)
```

### 4.2 Geometry Optimization WorkChain

```python
# tui/src/aiida/workchains/crystal_geopt.py
"""
Geometry optimization WorkChain.

Replaces: src/core/workflow.py optimization workflows
"""
from aiida.engine import WorkChain, while_

class CrystalGeometryOptimizationWorkChain(WorkChain):
    """Multi-step geometry optimization."""

    @classmethod
    def define(cls, spec):
        super().define(spec)

        spec.input("structure", valid_type=orm.StructureData)
        spec.input("parameters", valid_type=orm.Dict)
        spec.input("code", valid_type=orm.Code)

        spec.output("output_structure", valid_type=orm.StructureData)
        spec.output("optimization_trajectory", valid_type=orm.TrajectoryData)

        spec.outline(
            cls.setup,
            while_(cls.should_continue_optimization)(
                cls.run_optimization_step,
                cls.check_convergence,
            ),
            cls.results,
        )

    def should_continue_optimization(self):
        """Check if more optimization steps needed."""
        return not self.ctx.get("converged", False)

    def run_optimization_step(self):
        """Run single optimization step."""
        # Submit CrystalBaseWorkChain with OPTGEOM
        pass

    def check_convergence(self):
        """Check geometry convergence."""
        # Parse forces, displacements
        # Set self.ctx.converged = True if converged
        pass
```

---

## Phase 5: TUI Screen Adaptation (Week 9-10)

### 5.1 Update Screens to Use AiiDA Adapter

```python
# tui/src/tui/screens/job_list.py
"""
Job list screen - updated to use AiiDA adapter.
"""
from ..aiida.query_adapter import AiiDAQueryAdapter

class JobListScreen(Screen):
    """Display list of jobs (now from AiiDA)."""

    def __init__(self):
        super().__init__()
        self.db = AiiDAQueryAdapter()  # Changed from Database()

    async def on_mount(self):
        """Load jobs from AiiDA."""
        jobs = self.db.list_jobs()  # Still same interface!
        self.update_job_table(jobs)
```

### 5.2 Job Submission via WorkChain

```python
# tui/src/tui/screens/new_job.py
"""
New job submission - now submits AiiDA WorkChain.
"""
from aiida import engine, orm
from ..aiida.workchains.crystal_base import CrystalBaseWorkChain

class NewJobModal(Screen):
    """Job submission modal."""

    async def submit_job(self, job_data: Dict):
        """Submit job via AiiDA WorkChain."""
        # Get AiiDA Code
        code = orm.load_code(job_data["code_label"])

        # Prepare inputs
        structure = self._create_structure(job_data["structure_data"])
        parameters = orm.Dict(dict=job_data["parameters"])
        options = orm.Dict(dict=job_data["options"])

        # Submit WorkChain
        builder = CrystalBaseWorkChain.get_builder()
        builder.structure = structure
        builder.parameters = parameters
        builder.code = code
        builder.options = options

        # Submit and get PK
        workchain_node = engine.submit(builder)

        self.notify(f"Submitted WorkChain {workchain_node.pk}")
        return workchain_node.pk
```

---

## Phase 6: Computer and Code Setup (Week 11)

### 6.1 Computer Configuration

```python
# tui/src/aiida/setup/computers.py
"""Setup AiiDA Computers for CRYSTAL23."""

def setup_localhost_computer():
    """Setup localhost Computer."""
    from aiida import orm
    from aiida.orm import Computer

    computer = Computer(
        label="localhost",
        hostname="localhost",
        description="Local machine",
        transport_type="core.local",
        scheduler_type="core.direct",
        workdir="/tmp/aiida_work/",
    )
    computer.store()
    computer.configure()

    return computer

def setup_ssh_computer(hostname: str, username: str):
    """Setup remote SSH Computer."""
    computer = Computer(
        label=f"ssh_{hostname}",
        hostname=hostname,
        description=f"SSH remote: {hostname}",
        transport_type="core.ssh",
        scheduler_type="core.slurm",  # or pbs, sge
        workdir=f"/home/{username}/aiida_work/",
    )
    computer.store()
    computer.configure(
        username=username,
        port=22,
        key_filename="~/.ssh/id_rsa",
    )

    return computer
```

### 6.2 Code Setup

```python
# tui/src/aiida/setup/codes.py
"""Setup AiiDA Codes for CRYSTAL23 executables."""

def setup_crystal23_code(
    computer: Computer,
    executable_path: str,
    mpi_enabled: bool = False
):
    """Setup CRYSTAL23 Code."""
    from aiida import orm

    code_label = "crystalOMP" if not mpi_enabled else "PcrystalOMP"

    code = orm.Code(
        label=code_label,
        description=f"CRYSTAL23 {code_label}",
        input_plugin_name="crystal23.crystal",  # Our CalcJob entry point
        remote_computer_exec=[computer, executable_path],
    )

    if mpi_enabled:
        code.set_prepend_text("export OMP_NUM_THREADS=4")

    code.store()
    return code
```

---

## Phase 7: Testing & Migration (Week 12)

### 7.1 Test Suite Updates

```python
# tui/tests/test_aiida_adapter.py
"""Tests for AiiDA adapter layer."""

def test_aiida_query_adapter():
    """Test AiiDA QueryAdapter maintains database interface."""
    adapter = AiiDAQueryAdapter()

    # Test list_jobs
    jobs = adapter.list_jobs()
    assert isinstance(jobs, list)

    # Test create_job
    job_id = adapter.create_job(
        name="test_job",
        input_content="test input",
    )
    assert isinstance(job_id, int)

    # Test get_job
    job = adapter.get_job(job_id)
    assert job["name"] == "test_job"
```

### 7.2 Data Migration Script

```bash
# scripts/migrate_to_aiida.sh
#!/bin/bash
# Migrate existing TUI database to AiiDA

set -euo pipefail

echo "Starting migration to AiiDA..."

# Backup existing database
cp ~/.crystal_tui/jobs.db ~/.crystal_tui/jobs.db.backup

# Run migration
python -m tui.aiida.migration \
    --sqlite-db ~/.crystal_tui/jobs.db \
    --aiida-profile crystal-tui

echo "Migration complete!"
```

---

## Configuration Management

### Environment Configuration

```python
# tui/src/core/config.py
"""
Configuration supporting both legacy and AiiDA modes.
"""
from enum import Enum
from pydantic import BaseSettings

class BackendMode(str, Enum):
    """Backend mode selection."""
    LEGACY = "legacy"  # SQLite + custom workflow
    AIIDA = "aiida"    # Full AiiDA backend

class Config(BaseSettings):
    """Application configuration."""

    backend_mode: BackendMode = BackendMode.AIIDA

    # Legacy mode settings
    database_path: str = "~/.crystal_tui/jobs.db"

    # AiiDA mode settings
    aiida_profile: str = "crystal-tui"
    aiida_daemon: bool = True

    class Config:
        env_prefix = "CRYSTAL_TUI_"
```

---

## Deployment Checklist

### Infrastructure

- [ ] PostgreSQL 12+ installed and running
- [ ] RabbitMQ installed and running (optional but recommended)
- [ ] AiiDA profile created: `verdi quicksetup`
- [ ] AiiDA daemon started: `verdi daemon start`

### Setup

- [ ] Computers configured: `python -m tui.aiida.setup.computers`
- [ ] Codes registered: `python -m tui.aiida.setup.codes`
- [ ] Test calculation runs: `verdi process list`

### Migration

- [ ] Existing data backed up
- [ ] Migration script tested on subset
- [ ] Full migration completed: `scripts/migrate_to_aiida.sh`
- [ ] Data integrity verified

### Testing

- [ ] Unit tests pass: `pytest tests/test_aiida_*`
- [ ] Integration tests pass: `pytest tests/integration/`
- [ ] Manual TUI smoke tests completed

---

## Rollback Plan

If migration encounters critical issues:

1. **Restore SQLite Database**:
   ```bash
   cp ~/.crystal_tui/jobs.db.backup ~/.crystal_tui/jobs.db
   ```

2. **Switch to Legacy Mode**:
   ```bash
   export CRYSTAL_TUI_BACKEND_MODE=legacy
   crystal-tui
   ```

3. **Keep AiiDA for New Jobs**:
   - Hybrid mode: Query both SQLite (old) and AiiDA (new)
   - Gradual migration as old jobs complete

---

## Benefits Realized

### For Users

- ✅ Full provenance tracking of all calculations
- ✅ Web interface via AiiDA Lab (future)
- ✅ Integration with aiida-crystal-dft ecosystem
- ✅ Reproducible workflows with versioning
- ✅ Export/share workflows with collaborators

### For Developers

- ✅ Mature workflow engine (no reinventing wheels)
- ✅ Active community support
- ✅ Plugin ecosystem access
- ✅ REST API for external integrations
- ✅ Database migrations handled by AiiDA

### For Research Groups

- ✅ Centralized data management
- ✅ Multi-user support (PostgreSQL)
- ✅ HPC cluster integration
- ✅ Compliance with FAIR principles
- ✅ Long-term data preservation

---

## Success Criteria

- [ ] All TUI screens functional with AiiDA backend
- [ ] Job submission works (local/SSH/SLURM)
- [ ] Provenance graph visible via `verdi process show`
- [ ] Query performance acceptable (<100ms for job lists)
- [ ] Existing users migrated successfully
- [ ] Documentation complete and tested

---

## Future Enhancements (Post-Integration)

### Phase 8: Advanced Features

1. **AiiDA Lab Integration**
   - Web-based UI for workflows
   - Jupyter notebook interface
   - Real-time monitoring dashboard

2. **Advanced WorkChains**
   - Equation of State (EOS)
   - Phonon calculations with CRYSTAL + Phonopy
   - High-throughput screening

3. **Data Analysis**
   - Query across all calculations
   - Trend analysis and visualization
   - Machine learning on results

4. **Collaboration**
   - Multi-user profiles
   - Shared project spaces
   - Permission management

---

## References

- [AiiDA Documentation](https://aiida.readthedocs.io/)
- [AiiDA Tutorials](https://aiida-tutorials.readthedocs.io/)
- [aiida-crystal-dft Plugin](https://github.com/tilde-lab/aiida-crystal-dft)
- [AiiDA Plugin Registry](https://aiidateam.github.io/aiida-registry/)
- [CRYSTAL Solutions](https://www.crystal.unito.it/)

---

**Document Version**: 1.0
**Last Updated**: 2025-11-23
**Author**: Claude Code AI
**Status**: Design Phase
