"""Fluent WorkflowBuilder for custom workflow construction.

This module provides a builder pattern API for constructing complex
multi-step workflows with explicit control over each calculation stage.

Example:
    from crystalmath.high_level import WorkflowBuilder

    workflow = (
        WorkflowBuilder()
        .from_file("NbOCl2.cif")
        .relax(code="vasp", protocol="moderate")
        .then_bands(kpath="auto", kpoints_per_segment=50)
        .then_dos(mesh=[12, 12, 12])
        .with_gw(code="yambo", protocol="gw0")
        .with_bse(n_valence=4, n_conduction=4)
        .on_cluster("beefcake2", partition="gpu")
        .with_progress(callback=my_handler)
        .build()
    )

    result = workflow.run()

Note:
    This is a STUB implementation for Phase 2.3 API design.
    Full implementation will be completed in Phase 3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

from crystalmath.protocols import (
    DFTCode,
    ErrorRecoveryStrategy,
    ProgressCallback,
    ResourceRequirements,
    WorkflowResult,
    WorkflowStep,
    WorkflowType,
)

if TYPE_CHECKING:
    from pymatgen.core import Structure

    from .clusters import ClusterProfile
    from .results import AnalysisResults

logger = logging.getLogger(__name__)


# =============================================================================
# Progress Update Data Class
# =============================================================================


@dataclass
class ProgressUpdate:
    """Progress update for async workflow execution.

    Yielded by Workflow.run_async() to report progress and provide
    access to intermediate results.

    Attributes:
        workflow_id: Unique identifier for the workflow
        step_name: Current step name
        step_index: Current step index (0-based)
        total_steps: Total number of steps
        percent: Overall completion percentage (0-100)
        status: Step status (pending, running, completed, failed)
        message: Optional status message
        has_intermediate_result: Whether intermediate results are available
        intermediate_result: Partial results (if available)
        elapsed_seconds: Elapsed time since workflow start
        estimated_remaining_seconds: Estimated time to completion
    """

    workflow_id: str
    step_name: str
    step_index: int
    total_steps: int
    percent: float
    status: str = "running"
    message: Optional[str] = None
    has_intermediate_result: bool = False
    intermediate_result: Optional[Any] = None
    elapsed_seconds: float = 0.0
    estimated_remaining_seconds: Optional[float] = None


@dataclass
class WorkflowStatus:
    """Status of a submitted workflow.

    Returned by Workflow.get_status() for non-blocking status checks.

    Attributes:
        workflow_id: Unique identifier
        state: Overall state (created, running, completed, failed, cancelled)
        current_step: Name of current step
        current_step_index: Index of current step
        total_steps: Total number of steps
        progress_percent: Overall completion percentage
        errors: List of error messages (if any)
        started_at: Timestamp when workflow started
        estimated_completion: Estimated completion time
    """

    workflow_id: str
    state: str
    current_step: Optional[str] = None
    current_step_index: int = 0
    total_steps: int = 0
    progress_percent: float = 0.0
    errors: List[str] = field(default_factory=list)
    started_at: Optional[str] = None
    estimated_completion: Optional[str] = None


# =============================================================================
# Workflow Class (Built by WorkflowBuilder)
# =============================================================================


class Workflow:
    """Executable workflow built by WorkflowBuilder.

    This class represents a fully configured workflow ready for execution.
    It provides both synchronous and asynchronous execution methods with
    progress tracking and intermediate result access.

    Note:
        Do not instantiate directly. Use WorkflowBuilder.build() instead.

    Example:
        workflow = WorkflowBuilder().from_file("struct.cif").relax().build()

        # Synchronous execution
        result = workflow.run()

        # Asynchronous with progress (Jupyter)
        async for update in workflow.run_async():
            print(f"{update.step_name}: {update.percent}%")

        # Non-blocking submission
        workflow_id = workflow.submit()
        status = Workflow.get_status(workflow_id)
    """

    def __init__(
        self,
        structure: Any,
        steps: List[WorkflowStep],
        cluster: Optional["ClusterProfile"] = None,
        resources: Optional[ResourceRequirements] = None,
        progress_callback: Optional[ProgressCallback] = None,
        output_dir: Optional[Path] = None,
        recovery_strategy: ErrorRecoveryStrategy = ErrorRecoveryStrategy.ADAPTIVE,
    ) -> None:
        """Initialize workflow (internal use).

        Args:
            structure: Input structure (pymatgen Structure or compatible)
            steps: List of workflow steps in execution order
            cluster: Cluster configuration
            resources: Resource requirements
            progress_callback: Progress notification handler
            output_dir: Output directory
            recovery_strategy: Error recovery strategy
        """
        self._structure = structure
        self._steps = steps
        self._cluster = cluster
        self._resources = resources
        self._progress_callback = progress_callback
        self._output_dir = output_dir
        self._recovery_strategy = recovery_strategy
        self._workflow_id: Optional[str] = None

    @property
    def steps(self) -> List[WorkflowStep]:
        """Get workflow steps."""
        return self._steps

    @property
    def workflow_id(self) -> Optional[str]:
        """Get workflow ID (set after submit)."""
        return self._workflow_id

    def run(self) -> "AnalysisResults":
        """Execute workflow synchronously.

        Blocks until all steps complete or an unrecoverable error occurs.

        Returns:
            AnalysisResults with all computed properties

        Raises:
            WorkflowError: If workflow fails and cannot be recovered
        """
        # Stub implementation
        raise NotImplementedError(
            "Workflow.run() will be implemented in Phase 3. "
            "See docs/architecture/HIGH-LEVEL-API.md for design specification."
        )

    async def run_async(self) -> AsyncIterator[ProgressUpdate]:
        """Execute workflow asynchronously with progress updates.

        Yields ProgressUpdate objects for each step, enabling real-time
        progress monitoring in Jupyter notebooks and async applications.

        Yields:
            ProgressUpdate objects reporting workflow progress

        Example:
            async for update in workflow.run_async():
                print(f"Step: {update.step_name}")
                print(f"Progress: {update.percent:.1f}%")

                if update.has_intermediate_result:
                    # Access partial results (e.g., for live plotting)
                    partial = update.intermediate_result
                    display(partial.plot_bands())

                if update.status == "completed":
                    final_result = update.intermediate_result
        """
        # Stub implementation
        raise NotImplementedError(
            "Workflow.run_async() will be implemented in Phase 3."
        )
        yield  # Makes this a generator (required for type checking)

    def submit(self) -> str:
        """Submit workflow without waiting for completion.

        Submits the workflow to the configured backend and returns
        immediately. Use get_status() and get_result() to check
        progress and retrieve results.

        Returns:
            Workflow ID for status tracking

        Example:
            workflow_id = workflow.submit()
            print(f"Submitted: {workflow_id}")

            # Check later
            while True:
                status = Workflow.get_status(workflow_id)
                if status.state in ("completed", "failed"):
                    break
                time.sleep(60)

            result = Workflow.get_result(workflow_id)
        """
        # Stub implementation
        raise NotImplementedError(
            "Workflow.submit() will be implemented in Phase 3."
        )

    @classmethod
    def get_status(cls, workflow_id: str) -> WorkflowStatus:
        """Get status of a submitted workflow.

        Args:
            workflow_id: Workflow ID from submit()

        Returns:
            Current workflow status

        Raises:
            WorkflowNotFoundError: If workflow_id not found
        """
        # Stub implementation
        raise NotImplementedError(
            "Workflow.get_status() will be implemented in Phase 3."
        )

    @classmethod
    def get_result(cls, workflow_id: str) -> "AnalysisResults":
        """Get results of a completed workflow.

        Args:
            workflow_id: Workflow ID from submit()

        Returns:
            AnalysisResults if workflow completed successfully

        Raises:
            WorkflowNotFoundError: If workflow_id not found
            WorkflowNotCompleteError: If workflow still running
            WorkflowFailedError: If workflow failed
        """
        # Stub implementation
        raise NotImplementedError(
            "Workflow.get_result() will be implemented in Phase 3."
        )

    @classmethod
    def cancel(cls, workflow_id: str) -> bool:
        """Cancel a running workflow.

        Args:
            workflow_id: Workflow ID from submit()

        Returns:
            True if cancellation succeeded

        Raises:
            WorkflowNotFoundError: If workflow_id not found
        """
        # Stub implementation
        raise NotImplementedError(
            "Workflow.cancel() will be implemented in Phase 3."
        )


# =============================================================================
# WorkflowBuilder Class
# =============================================================================


class WorkflowBuilder:
    """Fluent builder for custom workflow construction.

    Enables step-by-step workflow definition with explicit control
    over each calculation stage while maintaining a clean, readable API.

    Design Principles:
        - Method chaining for fluent interface
        - Each method returns self for chaining
        - Validation at build() time
        - Clear error messages for invalid configurations

    Example:
        workflow = (
            WorkflowBuilder()
            .from_file("structure.cif")
            .relax(code="vasp", protocol="moderate")
            .then_bands(kpath="auto")
            .then_dos()
            .on_cluster("beefcake2")
            .build()
        )

        result = workflow.run()

    Note:
        This is a STUB implementation. Methods configure the builder
        but build() raises NotImplementedError until Phase 3.
    """

    def __init__(self) -> None:
        """Initialize empty workflow builder."""
        # Structure
        self._structure: Optional[Any] = None
        self._structure_source: Optional[str] = None

        # Workflow steps
        self._steps: List[WorkflowStep] = []
        self._step_counter: int = 0

        # Execution configuration
        self._cluster: Optional["ClusterProfile"] = None
        self._resources: Optional[ResourceRequirements] = None
        self._progress_callback: Optional[ProgressCallback] = None
        self._output_dir: Optional[Path] = None
        self._recovery_strategy: ErrorRecoveryStrategy = ErrorRecoveryStrategy.ADAPTIVE

    # =========================================================================
    # Structure Input Methods
    # =========================================================================

    def from_file(self, path: Union[str, Path]) -> "WorkflowBuilder":
        """Load structure from file.

        Supports CIF, POSCAR, XYZ, and other formats recognized by pymatgen.

        Args:
            path: Path to structure file

        Returns:
            Self for method chaining

        Example:
            builder.from_file("NbOCl2.cif")
            builder.from_file("POSCAR")
            builder.from_file("/path/to/structure.xyz")
        """
        self._structure_source = f"file:{path}"
        logger.debug(f"WorkflowBuilder: structure from file {path}")
        return self

    def from_mp(self, material_id: str) -> "WorkflowBuilder":
        """Fetch structure from Materials Project.

        Uses the MaterialsService to fetch the structure from the
        Materials Project database.

        Args:
            material_id: Materials Project ID (e.g., "mp-1234")

        Returns:
            Self for method chaining

        Example:
            builder.from_mp("mp-149")  # Silicon
            builder.from_mp("mp-2815") # MoS2
        """
        self._structure_source = f"mp:{material_id}"
        logger.debug(f"WorkflowBuilder: structure from MP {material_id}")
        return self

    def from_structure(self, structure: "Structure") -> "WorkflowBuilder":
        """Use pymatgen Structure directly.

        For users who already have a pymatgen Structure object in memory.

        Args:
            structure: pymatgen Structure object

        Returns:
            Self for method chaining

        Example:
            from pymatgen.core import Structure
            struct = Structure.from_file("POSCAR")
            builder.from_structure(struct)
        """
        self._structure = structure
        self._structure_source = "pymatgen"
        logger.debug("WorkflowBuilder: structure from pymatgen object")
        return self

    def from_aiida(self, pk_or_uuid: Union[int, str]) -> "WorkflowBuilder":
        """Load structure from AiiDA database.

        Args:
            pk_or_uuid: AiiDA StructureData node PK (int) or UUID (str)

        Returns:
            Self for method chaining

        Example:
            builder.from_aiida(12345)
            builder.from_aiida("a1b2c3d4-e5f6-...")
        """
        self._structure_source = f"aiida:{pk_or_uuid}"
        logger.debug(f"WorkflowBuilder: structure from AiiDA {pk_or_uuid}")
        return self

    # =========================================================================
    # DFT Workflow Steps
    # =========================================================================

    def _add_step(
        self,
        name: str,
        workflow_type: WorkflowType,
        code: Optional[DFTCode],
        parameters: Dict[str, Any],
        depends_on: Optional[List[str]] = None,
    ) -> None:
        """Internal method to add a workflow step."""
        step = WorkflowStep(
            name=name,
            workflow_type=workflow_type,
            code=code or "vasp",  # Default
            parameters=parameters,
            depends_on=depends_on or [],
        )
        self._steps.append(step)
        self._step_counter += 1

    def relax(
        self,
        code: Optional[DFTCode] = None,
        protocol: str = "moderate",
        force_threshold: float = 0.01,
        stress_threshold: float = 0.1,
        max_steps: int = 200,
        **params: Any,
    ) -> "WorkflowBuilder":
        """Add geometry optimization step.

        Relaxes atomic positions and/or cell parameters to minimize
        forces and stresses.

        Args:
            code: DFT code (vasp, crystal23, quantum_espresso). Auto-selected if None.
            protocol: Accuracy level (fast, moderate, precise)
            force_threshold: Force convergence criterion (eV/Angstrom)
            stress_threshold: Stress convergence criterion (kbar)
            max_steps: Maximum optimization steps
            **params: Additional code-specific parameters

        Returns:
            Self for method chaining

        Example:
            builder.relax(code="vasp", force_threshold=0.001)
        """
        parameters = {
            "protocol": protocol,
            "force_threshold": force_threshold,
            "stress_threshold": stress_threshold,
            "max_steps": max_steps,
            **params,
        }
        self._add_step("relax", WorkflowType.RELAX, code, parameters)
        return self

    def scf(
        self,
        code: Optional[DFTCode] = None,
        protocol: str = "moderate",
        **params: Any,
    ) -> "WorkflowBuilder":
        """Add SCF (self-consistent field) calculation step.

        Single-point energy calculation without geometry optimization.

        Args:
            code: DFT code. Auto-selected if None.
            protocol: Accuracy level
            **params: Additional parameters

        Returns:
            Self for method chaining

        Example:
            builder.scf(code="crystal23", protocol="precise")
        """
        parameters = {"protocol": protocol, **params}
        self._add_step("scf", WorkflowType.SCF, code, parameters)
        return self

    def then_bands(
        self,
        kpath: Union[str, List[Tuple[str, List[float]]]] = "auto",
        kpoints_per_segment: int = 50,
        **params: Any,
    ) -> "WorkflowBuilder":
        """Add band structure calculation (depends on previous SCF).

        Calculates band structure along high-symmetry k-point path.

        Args:
            kpath: K-point path specification:
                - "auto": Auto-detect from structure symmetry
                - Preset name: "cubic", "fcc", "bcc", "hexagonal", etc.
                - Custom: [("Gamma", [0,0,0]), ("X", [0.5,0,0]), ...]
            kpoints_per_segment: Number of k-points per path segment
            **params: Additional parameters

        Returns:
            Self for method chaining

        Example:
            builder.then_bands(kpath="auto", kpoints_per_segment=100)
            builder.then_bands(kpath="hexagonal")
        """
        # Find previous SCF/relax step to depend on
        depends_on = self._find_scf_dependency()

        parameters = {
            "kpath": kpath,
            "kpoints_per_segment": kpoints_per_segment,
            **params,
        }
        self._add_step("bands", WorkflowType.BANDS, None, parameters, depends_on)
        return self

    def then_dos(
        self,
        mesh: Optional[List[int]] = None,
        smearing: float = 0.05,
        projected: bool = False,
        **params: Any,
    ) -> "WorkflowBuilder":
        """Add DOS calculation (depends on previous SCF).

        Calculates density of states.

        Args:
            mesh: K-point mesh for DOS (auto if None, typically denser than SCF)
            smearing: Gaussian smearing width (eV)
            projected: Calculate orbital-projected DOS
            **params: Additional parameters

        Returns:
            Self for method chaining

        Example:
            builder.then_dos(mesh=[16, 16, 16], projected=True)
        """
        depends_on = self._find_scf_dependency()

        parameters = {
            "mesh": mesh,
            "smearing": smearing,
            "projected": projected,
            **params,
        }
        self._add_step("dos", WorkflowType.DOS, None, parameters, depends_on)
        return self

    def then_phonon(
        self,
        supercell: Optional[List[int]] = None,
        displacement: float = 0.01,
        **params: Any,
    ) -> "WorkflowBuilder":
        """Add phonon calculation (depends on relaxed structure).

        Calculates phonon dispersion using finite displacement method.

        Args:
            supercell: Supercell dimensions (auto if None)
            displacement: Finite displacement amplitude (Angstrom)
            **params: Additional parameters

        Returns:
            Self for method chaining

        Example:
            builder.then_phonon(supercell=[2, 2, 2])
        """
        depends_on = self._find_relax_dependency()

        parameters = {
            "supercell": supercell,
            "displacement": displacement,
            **params,
        }
        self._add_step("phonon", WorkflowType.PHONON, None, parameters, depends_on)
        return self

    def then_elastic(self, **params: Any) -> "WorkflowBuilder":
        """Add elastic constants calculation.

        Calculates elastic tensor via strain-stress method.

        Args:
            **params: Additional parameters

        Returns:
            Self for method chaining

        Example:
            builder.then_elastic()
        """
        depends_on = self._find_relax_dependency()
        self._add_step("elastic", WorkflowType.ELASTIC, None, params, depends_on)
        return self

    def then_dielectric(self, **params: Any) -> "WorkflowBuilder":
        """Add dielectric tensor calculation.

        Args:
            **params: Additional parameters

        Returns:
            Self for method chaining
        """
        depends_on = self._find_scf_dependency()
        self._add_step("dielectric", WorkflowType.DIELECTRIC, None, params, depends_on)
        return self

    # =========================================================================
    # Many-Body Perturbation Theory
    # =========================================================================

    def with_gw(
        self,
        code: DFTCode = "yambo",
        protocol: str = "gw0",
        n_bands: Optional[int] = None,
        **params: Any,
    ) -> "WorkflowBuilder":
        """Add GW quasiparticle calculation.

        Requires SCF step with compatible code. Corrects DFT band energies
        using many-body perturbation theory.

        Args:
            code: Many-body code (yambo, berkeleygw)
            protocol: GW flavor:
                - "g0w0": Single-shot G0W0 (fastest)
                - "gw0": Partially self-consistent (recommended)
                - "evgw": Eigenvalue self-consistent
            n_bands: Number of bands for GW (auto if None)
            **params: Additional parameters

        Returns:
            Self for method chaining

        Example:
            builder.with_gw(code="yambo", protocol="gw0", n_bands=100)
        """
        depends_on = self._find_scf_dependency()

        parameters = {
            "protocol": protocol,
            "n_bands": n_bands,
            **params,
        }
        self._add_step("gw", WorkflowType.GW, code, parameters, depends_on)
        return self

    def with_bse(
        self,
        code: DFTCode = "yambo",
        n_valence: int = 4,
        n_conduction: int = 4,
        **params: Any,
    ) -> "WorkflowBuilder":
        """Add BSE optical calculation.

        Requires GW step for quasiparticle corrections. Calculates
        optical absorption including excitonic effects.

        Args:
            code: Many-body code (yambo, berkeleygw)
            n_valence: Number of valence bands to include
            n_conduction: Number of conduction bands to include
            **params: Additional parameters

        Returns:
            Self for method chaining

        Example:
            builder.with_bse(n_valence=6, n_conduction=6)
        """
        # BSE depends on GW
        depends_on = self._find_gw_dependency()

        parameters = {
            "n_valence": n_valence,
            "n_conduction": n_conduction,
            **params,
        }
        self._add_step("bse", WorkflowType.BSE, code, parameters, depends_on)
        return self

    # =========================================================================
    # Cluster and Execution Configuration
    # =========================================================================

    def on_cluster(
        self,
        cluster: str,
        partition: Optional[str] = None,
        resources: Optional[ResourceRequirements] = None,
    ) -> "WorkflowBuilder":
        """Configure cluster execution.

        Args:
            cluster: Cluster profile name:
                - "beefcake2": 6-node V100S cluster
                - "local": Local execution
            partition: SLURM partition (None for cluster default)
            resources: Custom resource requirements

        Returns:
            Self for method chaining

        Example:
            builder.on_cluster("beefcake2", partition="gpu")
            builder.on_cluster("local")
        """
        # Will load ClusterProfile in Phase 3
        logger.debug(f"WorkflowBuilder: cluster={cluster}, partition={partition}")
        self._resources = resources
        return self

    def with_progress(
        self,
        callback: Optional[ProgressCallback] = None,
    ) -> "WorkflowBuilder":
        """Enable progress tracking.

        Args:
            callback: Progress callback. If None, uses ConsoleProgressCallback.

        Returns:
            Self for method chaining

        Example:
            builder.with_progress()  # Console output
            builder.with_progress(callback=my_custom_callback)
        """
        self._progress_callback = callback
        logger.debug("WorkflowBuilder: progress tracking enabled")
        return self

    def with_output(self, output_dir: Union[str, Path]) -> "WorkflowBuilder":
        """Set output directory for results.

        Args:
            output_dir: Directory for output files

        Returns:
            Self for method chaining

        Example:
            builder.with_output("./results/NbOCl2")
        """
        self._output_dir = Path(output_dir)
        return self

    def with_recovery(
        self,
        strategy: ErrorRecoveryStrategy,
    ) -> "WorkflowBuilder":
        """Configure error recovery strategy.

        Args:
            strategy: Recovery strategy:
                - FAIL_FAST: Stop on first error
                - RETRY: Retry with same parameters
                - ADAPTIVE: Self-healing parameter adjustment
                - CHECKPOINT: Restart from last checkpoint

        Returns:
            Self for method chaining

        Example:
            builder.with_recovery(ErrorRecoveryStrategy.ADAPTIVE)
        """
        self._recovery_strategy = strategy
        return self

    # =========================================================================
    # Build and Validate
    # =========================================================================

    def build(self) -> Workflow:
        """Build the workflow for execution.

        Validates the workflow configuration and returns an executable
        Workflow object.

        Returns:
            Configured Workflow ready for execution

        Raises:
            WorkflowValidationError: If configuration is invalid

        Example:
            workflow = builder.from_file("struct.cif").relax().build()
            result = workflow.run()
        """
        # Validate first
        is_valid, issues = self.validate()
        if not is_valid:
            from .api import WorkflowValidationError

            raise WorkflowValidationError(f"Invalid workflow: {'; '.join(issues)}")

        # Resolve structure if needed
        structure = self._structure
        if structure is None and self._structure_source:
            if self._structure_source.startswith("file:"):
                from .api import HighThroughput

                path = self._structure_source[5:]
                structure = HighThroughput._load_structure(path)
            elif self._structure_source.startswith("mp:"):
                from .api import HighThroughput

                mp_id = self._structure_source[3:]
                structure = HighThroughput._load_structure_from_mp(mp_id)

        return Workflow(
            structure=structure,
            steps=self._steps,
            cluster=self._cluster,
            resources=self._resources,
            progress_callback=self._progress_callback,
            output_dir=self._output_dir,
            recovery_strategy=self._recovery_strategy,
        )

    def validate(self) -> Tuple[bool, List[str]]:
        """Validate workflow configuration.

        Checks for:
        - Structure source is specified
        - At least one workflow step
        - Valid step dependencies
        - Code compatibility

        Returns:
            Tuple of (is_valid, list_of_issues)

        Example:
            is_valid, issues = builder.validate()
            if not is_valid:
                print("\\n".join(issues))
        """
        issues: List[str] = []

        # Check structure
        if self._structure is None and self._structure_source is None:
            issues.append("No structure specified. Use from_file(), from_mp(), etc.")

        # Check steps
        if not self._steps:
            issues.append("No workflow steps. Add at least one step (relax, scf, etc.)")

        # Check step names are unique
        names = [s.name for s in self._steps]
        if len(names) != len(set(names)):
            issues.append("Duplicate step names found")

        # Check dependencies exist
        for step in self._steps:
            for dep in step.depends_on:
                if dep not in names:
                    issues.append(f"Step '{step.name}' depends on unknown step '{dep}'")

        return len(issues) == 0, issues

    # =========================================================================
    # Internal Helper Methods
    # =========================================================================

    def _find_scf_dependency(self) -> List[str]:
        """Find the most recent SCF or relax step to depend on."""
        for step in reversed(self._steps):
            if step.workflow_type in (WorkflowType.SCF, WorkflowType.RELAX):
                return [step.name]
        return []

    def _find_relax_dependency(self) -> List[str]:
        """Find the most recent relax step to depend on."""
        for step in reversed(self._steps):
            if step.workflow_type == WorkflowType.RELAX:
                return [step.name]
        return []

    def _find_gw_dependency(self) -> List[str]:
        """Find the GW step to depend on (for BSE)."""
        for step in reversed(self._steps):
            if step.workflow_type == WorkflowType.GW:
                return [step.name]
        return []

    def __repr__(self) -> str:
        """String representation showing workflow configuration."""
        steps_str = " -> ".join(s.name for s in self._steps) if self._steps else "none"
        return f"WorkflowBuilder(source={self._structure_source}, steps=[{steps_str}])"
