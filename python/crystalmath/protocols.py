"""
Protocol definitions for CrystalMath Unified Workflow Architecture.

This module defines the abstract interfaces (Python Protocols) that enable
pluggable backends, workflow runners, and data providers. The architecture
supports multiple execution engines:

- AiiDA: Full provenance tracking, PostgreSQL-backed
- jobflow: Lightweight, Python-native, rapid prototyping
- Local: Direct execution for development/testing

Design Principles:
1. Backend-agnostic workflow definition
2. Unified structure handling across DFT codes
3. Composable workflow pipelines
4. Consistent error handling and recovery
5. Backward compatibility with existing CrystalController API

Architecture Layers:
    +--------------------------------------------------+
    |           High-Level Workflow API                 |
    |  (CrystalWorkflow, VASPWorkflow, HybridWorkflow) |
    +--------------------------------------------------+
                           |
    +--------------------------------------------------+
    |              Workflow Runner Layer               |
    |      (AiiDARunner, JobflowRunner, LocalRunner)   |
    +--------------------------------------------------+
                           |
    +--------------------------------------------------+
    |              Protocol Interfaces                 |
    |  (WorkflowRunner, StructureProvider, Backend)    |
    +--------------------------------------------------+
                           |
    +--------------------------------------------------+
    |              Data/Storage Layer                  |
    |    (AiiDA ORM, SQLite, MongoDB/Maggma)          |
    +--------------------------------------------------+
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Protocol,
    runtime_checkable,
)

if TYPE_CHECKING:
    from crystalmath.models import JobDetails, JobStatus, JobSubmission

# Workflow states
WorkflowState = Literal[
    "created", "submitted", "running", "completed", "failed", "cancelled", "paused"
]

# Supported DFT codes
DFTCode = Literal["crystal23", "vasp", "quantum_espresso", "yambo", "berkeleygw", "wannier90"]

# Backend types
BackendType = Literal["aiida", "jobflow", "local", "sqlite", "demo"]


# =============================================================================
# Enums for Workflow Classification
# =============================================================================


class WorkflowType(str, Enum):
    """Classification of workflow types."""

    # Single-code workflows
    SCF = "scf"
    RELAX = "relax"
    BANDS = "bands"
    DOS = "dos"
    PHONON = "phonon"
    EOS = "eos"
    ELASTIC = "elastic"
    DIELECTRIC = "dielectric"
    NEB = "neb"

    # Multi-step workflows
    RELAX_BANDS = "relax_bands"
    RELAX_DOS = "relax_dos"
    RELAX_BANDS_DOS = "relax_bands_dos"
    CONVERGENCE = "convergence"

    # Multi-code workflows
    GW = "gw"
    BSE = "bse"
    HYBRID_FUNCTIONAL = "hybrid"
    NONLINEAR_OPTICS = "nonlinear"

    # High-throughput
    HIGH_THROUGHPUT = "high_throughput"
    SCREENING = "screening"


class ErrorRecoveryStrategy(str, Enum):
    """Strategies for handling workflow failures."""

    FAIL_FAST = "fail_fast"  # Stop immediately on any failure
    RETRY = "retry"  # Retry with same parameters
    ADAPTIVE = "adaptive"  # Self-healing parameter adjustment
    CHECKPOINT_RESTART = "checkpoint"  # Restart from last checkpoint
    MANUAL = "manual"  # Pause for manual intervention


# =============================================================================
# Data Classes for Workflow Configuration
# =============================================================================


@dataclass
class ResourceRequirements:
    """Computational resource requirements for a calculation."""

    num_nodes: int = 1
    num_mpi_ranks: int = 1
    num_threads_per_rank: int = 1
    memory_gb: float = 4.0
    walltime_hours: float = 24.0
    gpus: int = 0
    partition: str | None = None
    account: str | None = None
    qos: str | None = None

    # Custom SLURM/scheduler directives
    extra_directives: dict[str, str] = field(default_factory=dict)

    def to_slurm_dict(self) -> dict[str, Any]:
        """Convert to SLURM resource specification."""
        resources = {
            "num_machines": self.num_nodes,
            "num_mpiprocs_per_machine": self.num_mpi_ranks // self.num_nodes,
            "num_cores_per_mpiproc": self.num_threads_per_rank,
        }
        if self.gpus > 0:
            resources["num_gpus_per_machine"] = self.gpus // self.num_nodes
        return resources

    def to_aiida_dict(self) -> dict[str, Any]:
        """Convert to AiiDA resource specification."""
        return {
            "resources": self.to_slurm_dict(),
            "max_wallclock_seconds": int(self.walltime_hours * 3600),
        }


@dataclass
class WorkflowResult:
    """Standard result container for workflow outputs."""

    success: bool
    workflow_id: str | None = None
    workflow_pk: int | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Timing information
    started_at: datetime | None = None
    completed_at: datetime | None = None
    wall_time_seconds: float | None = None
    cpu_time_seconds: float | None = None

    # Recovery information
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    can_restart: bool = False
    restart_info: dict[str, Any] | None = None


@dataclass
class StructureInfo:
    """Metadata about a crystal structure."""

    formula: str
    num_atoms: int
    space_group_number: int | None = None
    space_group_symbol: str | None = None
    volume: float | None = None
    is_magnetic: bool = False
    dimensionality: int = 3  # 3D, 2D (slab), 1D (polymer), 0D (molecule)
    source: str | None = None  # "mp", "cif", "poscar", "manual"
    source_id: str | None = None  # Materials Project ID, etc.


@dataclass
class WorkflowStep:
    """Represents a single step in a composite workflow."""

    name: str
    workflow_type: WorkflowType
    code: DFTCode
    parameters: dict[str, Any] = field(default_factory=dict)
    resources: ResourceRequirements | None = None
    depends_on: list[str] = field(default_factory=list)  # Step names
    outputs_to_pass: list[str] = field(default_factory=list)  # Output keys


# =============================================================================
# Protocol: WorkflowRunner
# =============================================================================


@runtime_checkable
class WorkflowRunner(Protocol):
    """
    Protocol for workflow execution engines.

    Implementations handle the actual execution of calculations:
    - AiiDARunner: Uses AiiDA WorkChains with full provenance
    - JobflowRunner: Uses jobflow for lightweight execution
    - LocalRunner: Direct subprocess execution for testing

    Key responsibilities:
    - Submit workflows to execution backend
    - Monitor progress and state
    - Handle errors and recovery
    - Collect and return results
    """

    @property
    def name(self) -> str:
        """Runner identifier (e.g., 'aiida', 'jobflow', 'local')."""
        ...

    @property
    def is_available(self) -> bool:
        """Whether this runner is ready for use."""
        ...

    def submit(
        self,
        workflow_type: WorkflowType,
        structure: Any,
        parameters: dict[str, Any],
        code: DFTCode,
        resources: ResourceRequirements | None = None,
        **kwargs: Any,
    ) -> WorkflowResult:
        """
        Submit a workflow for execution.

        Args:
            workflow_type: Type of workflow to run
            structure: Input structure (any supported format)
            parameters: Calculation parameters
            code: DFT code to use
            resources: Computational resources
            **kwargs: Additional workflow-specific options

        Returns:
            WorkflowResult with workflow_id for tracking
        """
        ...

    def submit_composite(
        self,
        steps: Sequence[WorkflowStep],
        structure: Any,
        **kwargs: Any,
    ) -> WorkflowResult:
        """
        Submit a composite multi-step workflow.

        Args:
            steps: Sequence of workflow steps
            structure: Initial input structure
            **kwargs: Global options

        Returns:
            WorkflowResult with workflow_id
        """
        ...

    def get_status(self, workflow_id: str) -> WorkflowState:
        """
        Get current state of a workflow.

        Args:
            workflow_id: Workflow identifier from submit()

        Returns:
            Current workflow state
        """
        ...

    def get_result(self, workflow_id: str) -> WorkflowResult:
        """
        Get complete result of a finished workflow.

        Args:
            workflow_id: Workflow identifier from submit()

        Returns:
            WorkflowResult with outputs and metadata
        """
        ...

    def cancel(self, workflow_id: str) -> bool:
        """
        Cancel a running workflow.

        Args:
            workflow_id: Workflow identifier

        Returns:
            True if cancellation succeeded
        """
        ...

    def list_workflows(
        self,
        state: WorkflowState | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        List workflows with optional state filter.

        Args:
            state: Filter by state (None for all)
            limit: Maximum number to return

        Returns:
            List of workflow info dicts
        """
        ...


# =============================================================================
# Protocol: Backend (Storage/Execution)
# =============================================================================


@runtime_checkable
class Backend(Protocol):
    """
    Protocol for job storage and execution backends.

    This is the existing Backend protocol from crystalmath.backends,
    included here for completeness. It provides:
    - Job CRUD operations
    - Log retrieval
    - Basic execution interface
    """

    @property
    def name(self) -> str:
        """Backend identifier (e.g., 'sqlite', 'aiida', 'demo')."""
        ...

    @property
    def is_available(self) -> bool:
        """Whether this backend is ready for use."""
        ...

    def get_jobs(self, limit: int = 100) -> list[JobStatus]:
        """Get list of jobs."""
        ...

    def get_job_details(self, pk: int) -> JobDetails | None:
        """Get detailed information for a specific job."""
        ...

    def submit_job(self, submission: JobSubmission) -> int:
        """Submit a new job."""
        ...

    def cancel_job(self, pk: int) -> bool:
        """Cancel a running job."""
        ...

    def get_job_log(self, pk: int, tail_lines: int = 100) -> dict[str, list[str]]:
        """Get job stdout/stderr logs."""
        ...


# =============================================================================
# Protocol: ProgressCallback
# =============================================================================


class ProgressCallback(Protocol):
    """
    Protocol for workflow progress notifications.

    Used for:
    - TUI progress updates
    - Logging
    - Webhook notifications
    """

    def on_started(self, workflow_id: str, workflow_type: WorkflowType) -> None:
        """Called when workflow starts."""
        ...

    def on_progress(
        self,
        workflow_id: str,
        step: str,
        progress_percent: float,
        message: str | None = None,
    ) -> None:
        """Called on progress update."""
        ...

    def on_completed(self, workflow_id: str, result: WorkflowResult) -> None:
        """Called when workflow completes successfully."""
        ...

    def on_failed(
        self,
        workflow_id: str,
        error: str,
        recoverable: bool,
    ) -> None:
        """Called when workflow fails."""
        ...


# =============================================================================
# Factory Functions
# =============================================================================


def get_runner(backend_type: BackendType = "aiida") -> WorkflowRunner:
    """
    Factory function to get appropriate WorkflowRunner.

    Args:
        backend_type: Type of backend to use

    Returns:
        Configured WorkflowRunner instance

    Raises:
        ImportError: If required backend is not available
        ValueError: If backend_type is not recognized
        NotImplementedError: If runner not yet implemented (Phase 3)

    Note:
        Runner implementations will be created in Phase 3:
        - crystalmath.runners.aiida_runner.AiiDAWorkflowRunner
        - crystalmath.runners.jobflow_runner.JobflowRunner
        - crystalmath.runners.local_runner.LocalRunner
    """
    if backend_type == "jobflow":
        from crystalmath.integrations.atomate2_bridge import Atomate2Bridge

        return Atomate2Bridge()  # type: ignore[return-value]

    raise NotImplementedError(
        f"WorkflowRunner for '{backend_type}' will be implemented in Phase 3. "
        f"See docs/architecture/UNIFIED-WORKFLOW-ARCHITECTURE.md for design."
    )


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Enums
    "WorkflowType",
    "ErrorRecoveryStrategy",
    # Type aliases
    "WorkflowState",
    "DFTCode",
    "BackendType",
    # Data classes
    "ResourceRequirements",
    "WorkflowResult",
    "StructureInfo",
    "WorkflowStep",
    # Protocols
    "WorkflowRunner",
    "Backend",
    "ProgressCallback",
    # Factory functions
    "get_runner",
]
