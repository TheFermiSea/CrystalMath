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

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Protocol,
    Sequence,
    TypeVar,
    runtime_checkable,
)

if TYPE_CHECKING:
    from crystalmath.models import JobDetails, JobStatus, JobSubmission


# =============================================================================
# Type Variables and Basic Types
# =============================================================================

T = TypeVar("T")
R = TypeVar("R")  # Result type
S = TypeVar("S")  # Structure type

# Workflow states
WorkflowState = Literal[
    "created", "submitted", "running", "completed", "failed", "cancelled", "paused"
]

# Supported DFT codes
DFTCode = Literal[
    "crystal23", "vasp", "quantum_espresso", "yambo", "berkeleygw", "wannier90"
]

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


class CalculationPriority(int, Enum):
    """Priority levels for job scheduling."""

    LOW = 1
    NORMAL = 5
    HIGH = 10
    URGENT = 20


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
    partition: Optional[str] = None
    account: Optional[str] = None
    qos: Optional[str] = None

    # Custom SLURM/scheduler directives
    extra_directives: Dict[str, str] = field(default_factory=dict)

    def to_slurm_dict(self) -> Dict[str, Any]:
        """Convert to SLURM resource specification."""
        resources = {
            "num_machines": self.num_nodes,
            "num_mpiprocs_per_machine": self.num_mpi_ranks // self.num_nodes,
            "num_cores_per_mpiproc": self.num_threads_per_rank,
        }
        if self.gpus > 0:
            resources["num_gpus_per_machine"] = self.gpus // self.num_nodes
        return resources

    def to_aiida_dict(self) -> Dict[str, Any]:
        """Convert to AiiDA resource specification."""
        return {
            "resources": self.to_slurm_dict(),
            "max_wallclock_seconds": int(self.walltime_hours * 3600),
        }


@dataclass
class WorkflowResult:
    """Standard result container for workflow outputs."""

    success: bool
    workflow_id: Optional[str] = None
    workflow_pk: Optional[int] = None
    outputs: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Timing information
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    wall_time_seconds: Optional[float] = None
    cpu_time_seconds: Optional[float] = None

    # Recovery information
    checkpoints: List[Dict[str, Any]] = field(default_factory=list)
    can_restart: bool = False
    restart_info: Optional[Dict[str, Any]] = None


@dataclass
class StructureInfo:
    """Metadata about a crystal structure."""

    formula: str
    num_atoms: int
    space_group_number: Optional[int] = None
    space_group_symbol: Optional[str] = None
    volume: Optional[float] = None
    is_magnetic: bool = False
    dimensionality: int = 3  # 3D, 2D (slab), 1D (polymer), 0D (molecule)
    source: Optional[str] = None  # "mp", "cif", "poscar", "manual"
    source_id: Optional[str] = None  # Materials Project ID, etc.


@dataclass
class WorkflowStep:
    """Represents a single step in a composite workflow."""

    name: str
    workflow_type: WorkflowType
    code: DFTCode
    parameters: Dict[str, Any] = field(default_factory=dict)
    resources: Optional[ResourceRequirements] = None
    depends_on: List[str] = field(default_factory=list)  # Step names
    outputs_to_pass: List[str] = field(default_factory=list)  # Output keys


# =============================================================================
# Protocol: StructureProvider
# =============================================================================


@runtime_checkable
class StructureProvider(Protocol):
    """
    Protocol for structure data sources.

    Implementations provide crystal structures from various sources:
    - Materials Project API
    - Local CIF/POSCAR files
    - AiiDA StructureData nodes
    - pymatgen Structure objects
    - Manual input
    """

    def get_structure(self, identifier: str) -> Any:
        """
        Retrieve a structure by identifier.

        Args:
            identifier: Structure ID (MP ID, file path, AiiDA PK, etc.)

        Returns:
            Structure object (implementation-specific type)
        """
        ...

    def to_aiida_structure(self, structure: Any) -> Any:
        """
        Convert structure to AiiDA StructureData.

        Args:
            structure: Source structure object

        Returns:
            aiida.orm.StructureData node (not stored)
        """
        ...

    def to_pymatgen_structure(self, structure: Any) -> Any:
        """
        Convert structure to pymatgen Structure.

        Args:
            structure: Source structure object

        Returns:
            pymatgen.core.Structure object
        """
        ...

    def get_info(self, structure: Any) -> StructureInfo:
        """
        Extract metadata from structure.

        Args:
            structure: Structure object

        Returns:
            StructureInfo with formula, symmetry, etc.
        """
        ...

    def validate(self, structure: Any) -> tuple[bool, List[str]]:
        """
        Validate structure for DFT calculations.

        Args:
            structure: Structure object

        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        ...


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
        parameters: Dict[str, Any],
        code: DFTCode,
        resources: Optional[ResourceRequirements] = None,
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
        state: Optional[WorkflowState] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
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

    def get_jobs(self, limit: int = 100) -> List["JobStatus"]:
        """Get list of jobs."""
        ...

    def get_job_details(self, pk: int) -> Optional["JobDetails"]:
        """Get detailed information for a specific job."""
        ...

    def submit_job(self, submission: "JobSubmission") -> int:
        """Submit a new job."""
        ...

    def cancel_job(self, pk: int) -> bool:
        """Cancel a running job."""
        ...

    def get_job_log(self, pk: int, tail_lines: int = 100) -> Dict[str, List[str]]:
        """Get job stdout/stderr logs."""
        ...


# =============================================================================
# Protocol: ResultsCollector
# =============================================================================


@runtime_checkable
class ResultsCollector(Protocol):
    """
    Protocol for collecting and aggregating workflow results.

    Implementations handle result extraction from various backends:
    - Parsing DFT code outputs
    - Extracting key quantities (energy, bandgap, etc.)
    - Aggregating results from multi-step workflows
    - Storing results in databases or files
    """

    def collect(self, workflow_result: WorkflowResult) -> Dict[str, Any]:
        """
        Collect and parse results from a workflow.

        Args:
            workflow_result: Result from WorkflowRunner

        Returns:
            Parsed results dictionary
        """
        ...

    def get_energy(self, workflow_result: WorkflowResult) -> Optional[float]:
        """Extract total energy from results (Hartree)."""
        ...

    def get_bandgap(self, workflow_result: WorkflowResult) -> Optional[float]:
        """Extract band gap from results (eV)."""
        ...

    def get_structure(self, workflow_result: WorkflowResult) -> Optional[Any]:
        """Extract optimized/final structure from results."""
        ...

    def get_bands(self, workflow_result: WorkflowResult) -> Optional[Any]:
        """Extract band structure data."""
        ...

    def get_dos(self, workflow_result: WorkflowResult) -> Optional[Any]:
        """Extract DOS data."""
        ...

    def export_json(
        self,
        workflow_result: WorkflowResult,
        output_path: Path,
    ) -> None:
        """Export results to JSON file."""
        ...


# =============================================================================
# Protocol: ParameterGenerator
# =============================================================================


@runtime_checkable
class ParameterGenerator(Protocol):
    """
    Protocol for generating DFT calculation parameters.

    Implementations provide default parameters for different:
    - DFT codes (CRYSTAL23, VASP, QE)
    - Workflow types (SCF, relax, bands)
    - Accuracy levels (fast, moderate, precise)
    """

    def generate(
        self,
        structure: Any,
        workflow_type: WorkflowType,
        code: DFTCode,
        protocol: str = "moderate",
        **overrides: Any,
    ) -> Dict[str, Any]:
        """
        Generate calculation parameters.

        Args:
            structure: Input structure
            workflow_type: Type of calculation
            code: Target DFT code
            protocol: Accuracy level
            **overrides: Parameter overrides

        Returns:
            Complete parameter dictionary
        """
        ...

    def get_k_points(
        self,
        structure: Any,
        density: float = 0.04,  # 1/Angstrom
    ) -> Any:
        """Generate k-point mesh based on structure."""
        ...

    def get_basis_set(
        self,
        elements: List[str],
        code: DFTCode,
        quality: str = "moderate",
    ) -> Dict[str, Any]:
        """Get basis set configuration for elements."""
        ...


# =============================================================================
# Protocol: ErrorHandler
# =============================================================================


@runtime_checkable
class ErrorHandler(Protocol):
    """
    Protocol for workflow error handling and recovery.

    Implementations provide strategies for:
    - Diagnosing calculation failures
    - Recommending parameter adjustments
    - Implementing self-healing workflows
    - Managing restarts from checkpoints
    """

    def diagnose(self, workflow_result: WorkflowResult) -> Dict[str, Any]:
        """
        Diagnose failure cause.

        Args:
            workflow_result: Failed workflow result

        Returns:
            Diagnosis dict with cause, severity, recommendations
        """
        ...

    def can_recover(self, workflow_result: WorkflowResult) -> bool:
        """Check if workflow can be recovered."""
        ...

    def get_recovery_strategy(
        self,
        workflow_result: WorkflowResult,
    ) -> ErrorRecoveryStrategy:
        """Determine best recovery strategy."""
        ...

    def apply_recovery(
        self,
        workflow_result: WorkflowResult,
        runner: WorkflowRunner,
    ) -> WorkflowResult:
        """
        Apply recovery and resubmit workflow.

        Args:
            workflow_result: Failed workflow result
            runner: Runner to use for resubmission

        Returns:
            New WorkflowResult from recovery attempt
        """
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
        message: Optional[str] = None,
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
# Protocol: WorkflowComposer (for chaining workflows)
# =============================================================================


@runtime_checkable
class WorkflowComposer(Protocol):
    """
    Protocol for composing complex multi-step workflows.

    Enables declarative workflow definition:
        workflow = composer.create()
            .add_step("relax", WorkflowType.RELAX, code="vasp")
            .add_step("scf", WorkflowType.SCF, depends_on=["relax"])
            .add_step("bands", WorkflowType.BANDS, depends_on=["scf"])
            .build()
    """

    def create(self) -> "WorkflowComposer":
        """Create new composition context."""
        ...

    def add_step(
        self,
        name: str,
        workflow_type: WorkflowType,
        code: DFTCode = "crystal23",
        parameters: Optional[Dict[str, Any]] = None,
        depends_on: Optional[List[str]] = None,
        outputs_to_pass: Optional[List[str]] = None,
    ) -> "WorkflowComposer":
        """Add a step to the workflow."""
        ...

    def build(self) -> Sequence[WorkflowStep]:
        """Build the workflow definition."""
        ...

    def validate(self) -> tuple[bool, List[str]]:
        """Validate workflow is well-formed (no cycles, etc.)."""
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
    # Phase 3 implementation - runners not yet created
    raise NotImplementedError(
        f"WorkflowRunner for '{backend_type}' will be implemented in Phase 3. "
        f"See docs/architecture/UNIFIED-WORKFLOW-ARCHITECTURE.md for design."
    )


def get_structure_provider(source: str = "auto") -> StructureProvider:
    """
    Factory function to get appropriate StructureProvider.

    Args:
        source: Source type ("mp", "aiida", "file", "auto")

    Returns:
        Configured StructureProvider instance

    Raises:
        NotImplementedError: If provider not yet implemented (Phase 3)

    Note:
        Provider implementations will be created in Phase 3:
        - crystalmath.providers.auto_provider.AutoStructureProvider
        - crystalmath.providers.mp_provider.MaterialsProjectProvider
        - crystalmath.providers.aiida_provider.AiiDAStructureProvider
        - crystalmath.providers.file_provider.FileStructureProvider
    """
    # Phase 3 implementation - providers not yet created
    raise NotImplementedError(
        f"StructureProvider for '{source}' will be implemented in Phase 3. "
        f"See docs/architecture/UNIFIED-WORKFLOW-ARCHITECTURE.md for design."
    )


def get_parameter_generator(code: DFTCode = "crystal23") -> ParameterGenerator:
    """
    Factory function to get appropriate ParameterGenerator.

    Args:
        code: Target DFT code

    Returns:
        Configured ParameterGenerator instance

    Raises:
        NotImplementedError: If generator not yet implemented (Phase 3)

    Note:
        Generator implementations will be created in Phase 3:
        - crystalmath.generators.crystal_params.CrystalParameterGenerator
        - crystalmath.generators.vasp_params.VASPParameterGenerator
        - crystalmath.generators.qe_params.QEParameterGenerator
    """
    # Phase 3 implementation - generators not yet created
    raise NotImplementedError(
        f"ParameterGenerator for '{code}' will be implemented in Phase 3. "
        f"See docs/architecture/UNIFIED-WORKFLOW-ARCHITECTURE.md for design."
    )


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Enums
    "WorkflowType",
    "CalculationPriority",
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
    "StructureProvider",
    "WorkflowRunner",
    "Backend",
    "ResultsCollector",
    "ParameterGenerator",
    "ErrorHandler",
    "ProgressCallback",
    "WorkflowComposer",
    # Factory functions
    "get_runner",
    "get_structure_provider",
    "get_parameter_generator",
]
