"""Specialized workflow runner implementations for analysis types.

This module provides workflow runner classes for different analysis types,
implementing the Task 3.2 high-level API design. Each runner orchestrates
complete workflows from structure input to results output.

Runners Available:
    - BaseAnalysisRunner: Abstract base class for all runners
    - StandardAnalysis: Electronic structure (SCF, relax, bands, DOS)
    - OpticalAnalysis: Many-body perturbation theory (GW, BSE)
    - PhononAnalysis: Phonon dispersion and thermodynamics
    - ElasticAnalysis: Elastic constants and mechanical properties
    - TransportAnalysis: BoltzTraP2 transport properties

Example:
    from crystalmath.high_level.runners import StandardAnalysis
    from crystalmath.high_level.clusters import get_cluster_profile

    cluster = get_cluster_profile("beefcake2")
    runner = StandardAnalysis(
        cluster=cluster,
        protocol="moderate",
        output_dir="./results/Si"
    )
    results = runner.run("mp-149")  # Silicon from Materials Project

Multi-code Workflow Example (VASP -> YAMBO):
    from crystalmath.high_level.runners import OpticalAnalysis

    runner = OpticalAnalysis(
        cluster=get_cluster_profile("beefcake2"),
        protocol="gw0",
        dft_code="vasp",
        gw_code="yambo"
    )
    results = runner.run("NbOCl2.cif", n_bands_gw=100, n_val_bse=4, n_cond_bse=4)

See Also:
    - crystalmath.protocols: Core protocol definitions
    - crystalmath.high_level.api: HighThroughput API
    - crystalmath.high_level.clusters: Cluster configuration
    - docs/architecture/UNIFIED-WORKFLOW-ARCHITECTURE.md
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from crystalmath.protocols import (
    DFTCode,
    ErrorRecoveryStrategy,
    ProgressCallback,
    ResourceRequirements,
    StructureInfo,
    WorkflowResult,
    WorkflowRunner,
    WorkflowStep,
    WorkflowState,
    WorkflowType,
)

if TYPE_CHECKING:
    from pymatgen.core import Structure

    from .clusters import ClusterProfile
    from .progress import ProgressUpdate
    from .results import AnalysisResults


logger = logging.getLogger(__name__)


# =============================================================================
# Exceptions
# =============================================================================


class RunnerError(Exception):
    """Base exception for runner errors."""

    pass


class StructureLoadError(RunnerError):
    """Failed to load input structure."""

    pass


class WorkflowBuildError(RunnerError):
    """Failed to build workflow steps."""

    pass


class WorkflowExecutionError(RunnerError):
    """Workflow execution failed."""

    pass


class CodeNotAvailableError(RunnerError):
    """Required DFT code not available on cluster."""

    pass


class MultiCodeHandoffError(RunnerError):
    """Failed to transfer data between DFT codes."""

    pass


# =============================================================================
# Runner Configuration
# =============================================================================


@dataclass
class RunnerConfig:
    """Configuration for analysis runners.

    Attributes:
        protocol: Accuracy level (fast, moderate, precise)
        output_dir: Directory for output files
        progress_callback: Progress notification handler
        recovery_strategy: Error recovery strategy
        checkpoint_interval: Steps between checkpoint saves
        max_retries: Maximum retry attempts for failed steps
        preserve_intermediates: Keep intermediate calculation files
        dry_run: Validate workflow without execution
    """

    protocol: str = "moderate"
    output_dir: Optional[Path] = None
    progress_callback: Optional[ProgressCallback] = None
    recovery_strategy: ErrorRecoveryStrategy = ErrorRecoveryStrategy.ADAPTIVE
    checkpoint_interval: int = 1
    max_retries: int = 3
    preserve_intermediates: bool = False
    dry_run: bool = False

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        valid_protocols = {"fast", "moderate", "precise"}
        if self.protocol not in valid_protocols:
            raise ValueError(
                f"Invalid protocol: '{self.protocol}'. "
                f"Valid options: {valid_protocols}"
            )
        if self.output_dir:
            self.output_dir = Path(self.output_dir)


@dataclass
class StepResult:
    """Result of a single workflow step.

    Attributes:
        step_name: Name of the step
        success: Whether step completed successfully
        outputs: Output data dictionary
        errors: List of error messages
        wall_time_seconds: Wall clock time for step
        cpu_time_seconds: CPU time for step
        output_files: List of output file paths
        checkpoint_path: Path to checkpoint file (if saved)
    """

    step_name: str
    success: bool
    outputs: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    wall_time_seconds: Optional[float] = None
    cpu_time_seconds: Optional[float] = None
    output_files: List[Path] = field(default_factory=list)
    checkpoint_path: Optional[Path] = None


# =============================================================================
# Base Analysis Runner
# =============================================================================


class BaseAnalysisRunner(ABC):
    """Abstract base class for specialized workflow runners.

    Provides common functionality for loading structures, building workflows,
    executing steps, and collecting results. Subclasses implement specific
    workflow step configurations for different analysis types.

    Architecture:
        BaseAnalysisRunner
            |
            +-- StandardAnalysis (SCF, relax, bands, DOS)
            +-- OpticalAnalysis (GW, BSE)
            +-- PhononAnalysis (phonons, thermodynamics)
            +-- ElasticAnalysis (elastic constants)
            +-- TransportAnalysis (BoltzTraP2)

    Attributes:
        cluster: Cluster profile with hardware specs and available codes
        config: Runner configuration
        workflow_runner: Underlying WorkflowRunner protocol implementation
        structure: Loaded input structure
        workflow_id: Unique workflow identifier
        steps: List of workflow steps
        step_results: Results from completed steps

    Example Subclass Implementation:
        class MyAnalysis(BaseAnalysisRunner):
            def _build_workflow_steps(self) -> List[WorkflowStep]:
                return [
                    WorkflowStep(
                        name="my_step",
                        workflow_type=WorkflowType.SCF,
                        code=self._select_code(),
                        parameters=self._get_parameters(),
                    )
                ]
    """

    def __init__(
        self,
        cluster: Optional["ClusterProfile"] = None,
        runner: Optional[WorkflowRunner] = None,
        protocol: str = "moderate",
        output_dir: Optional[Union[str, Path]] = None,
        progress_callback: Optional[ProgressCallback] = None,
        recovery_strategy: ErrorRecoveryStrategy = ErrorRecoveryStrategy.ADAPTIVE,
        **kwargs: Any,
    ) -> None:
        """Initialize the analysis runner.

        Args:
            cluster: Cluster profile with hardware specs and available codes.
                If None, uses local execution profile.
            runner: WorkflowRunner implementation. If None, auto-selects based
                on available backends (AiiDA > jobflow > local).
            protocol: Accuracy level:
                - "fast": Quick screening, coarse k-mesh
                - "moderate": Production quality (recommended)
                - "precise": Publication quality, fine k-mesh
            output_dir: Directory for output files. Creates timestamped
                subdirectory if not specified.
            progress_callback: Progress notification handler for UI updates
            recovery_strategy: Error recovery behavior:
                - FAIL_FAST: Stop immediately on error
                - RETRY: Retry with same parameters
                - ADAPTIVE: Self-healing parameter adjustment
                - CHECKPOINT: Restart from last checkpoint
            **kwargs: Additional configuration options passed to RunnerConfig
        """
        # Store cluster profile
        self._cluster = cluster

        # Create configuration
        self._config = RunnerConfig(
            protocol=protocol,
            output_dir=Path(output_dir) if output_dir else None,
            progress_callback=progress_callback,
            recovery_strategy=recovery_strategy,
            **kwargs,
        )

        # Workflow runner - auto-select SLURM if cluster is provided
        if runner is not None:
            self._runner = runner
        elif cluster is not None and cluster.scheduler == "slurm":
            # Auto-select SLURM runner when cluster with SLURM is configured
            self._runner = self._create_slurm_runner(cluster)
        else:
            # No runner - will use stub/simulation mode
            self._runner = None

        # State
        self._structure: Optional["Structure"] = None
        self._structure_info: Optional[StructureInfo] = None
        self._workflow_id: Optional[str] = None
        self._steps: List[WorkflowStep] = []
        self._step_results: List[StepResult] = []
        self._started_at: Optional[datetime] = None
        self._completed_at: Optional[datetime] = None

        logger.debug(
            f"Initialized {self.__class__.__name__} with "
            f"protocol={protocol}, cluster={cluster.name if cluster else 'local'}"
        )

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def cluster(self) -> Optional["ClusterProfile"]:
        """Get cluster profile."""
        return self._cluster

    @property
    def config(self) -> RunnerConfig:
        """Get runner configuration."""
        return self._config

    @property
    def workflow_id(self) -> Optional[str]:
        """Get workflow ID (set after run starts)."""
        return self._workflow_id

    @property
    def structure(self) -> Optional["Structure"]:
        """Get loaded structure."""
        return self._structure

    @property
    def structure_info(self) -> Optional[StructureInfo]:
        """Get structure metadata."""
        return self._structure_info

    @property
    def steps(self) -> List[WorkflowStep]:
        """Get workflow steps."""
        return self._steps

    @property
    def step_results(self) -> List[StepResult]:
        """Get results from completed steps."""
        return self._step_results

    @property
    def available_codes(self) -> List[DFTCode]:
        """Get list of available DFT codes on cluster."""
        if self._cluster:
            return list(self._cluster.available_codes)
        return ["crystal23"]  # Default for local

    # =========================================================================
    # Runner Selection
    # =========================================================================

    def _create_slurm_runner(
        self,
        cluster: "ClusterProfile",
    ) -> Optional[WorkflowRunner]:
        """Create a SLURMWorkflowRunner for the given cluster.

        This method is called automatically when a cluster with SLURM scheduler
        is provided and no explicit runner is specified. It ensures all
        computational tasks go through SLURM batch scheduling.

        Args:
            cluster: ClusterProfile with SLURM configuration

        Returns:
            SLURMWorkflowRunner instance, or None if unavailable

        Note:
            CRITICAL: This ensures compliance with the beefcake2 cluster policy
            that ALL computational tasks MUST use sbatch for job submission.
        """
        try:
            from crystalmath.integrations.slurm_runner import SLURMWorkflowRunner

            # Determine default code based on cluster's available codes
            default_code = "vasp"
            if cluster.available_codes:
                # Prefer VASP > QE > CRYSTAL23
                for code in ["vasp", "quantum_espresso", "crystal23"]:
                    if code in cluster.available_codes:
                        default_code = code
                        break

            runner = SLURMWorkflowRunner.from_cluster_profile(
                profile=cluster,
                default_code=default_code,
            )

            logger.info(
                f"Auto-selected SLURMWorkflowRunner for cluster '{cluster.name}'"
            )
            return runner

        except ImportError as e:
            logger.warning(
                f"SLURMWorkflowRunner not available: {e}. "
                f"Jobs will be simulated, NOT submitted to SLURM."
            )
            return None
        except Exception as e:
            logger.error(
                f"Failed to create SLURMWorkflowRunner: {e}. "
                f"Jobs will be simulated, NOT submitted to SLURM."
            )
            return None

    # =========================================================================
    # Abstract Methods
    # =========================================================================

    @abstractmethod
    def _build_workflow_steps(self) -> List[WorkflowStep]:
        """Build the workflow step sequence.

        Subclasses implement this to define their specific workflow steps.
        Steps should include proper dependencies and code selection.

        Returns:
            List of WorkflowStep objects in execution order

        Example:
            def _build_workflow_steps(self) -> List[WorkflowStep]:
                return [
                    WorkflowStep(
                        name="scf",
                        workflow_type=WorkflowType.SCF,
                        code="vasp",
                        parameters={"kpoints": [8, 8, 8]},
                    ),
                    WorkflowStep(
                        name="bands",
                        workflow_type=WorkflowType.BANDS,
                        code="vasp",
                        parameters={"kpath": "auto"},
                        depends_on=["scf"],
                    ),
                ]
        """
        ...

    @abstractmethod
    def _get_default_resources(self) -> ResourceRequirements:
        """Get default resource requirements for this analysis type.

        Returns:
            ResourceRequirements with appropriate defaults

        Example:
            def _get_default_resources(self) -> ResourceRequirements:
                return ResourceRequirements(
                    num_nodes=1,
                    num_mpi_ranks=20,
                    walltime_hours=12,
                )
        """
        ...

    # =========================================================================
    # Structure Loading
    # =========================================================================

    def _load_structure(
        self,
        source: Union[str, Path, "Structure"],
    ) -> "Structure":
        """Load structure from various input formats.

        Args:
            source: Structure source. Can be:
                - File path (str/Path) to CIF, POSCAR, XYZ, etc.
                - Materials Project ID (e.g., "mp-149")
                - AiiDA node (PK or UUID as string starting with "aiida:")
                - pymatgen Structure object

        Returns:
            pymatgen Structure object

        Raises:
            StructureLoadError: If structure cannot be loaded
        """
        try:
            from pymatgen.core import Structure
        except ImportError:
            raise StructureLoadError(
                "pymatgen is required for structure loading. "
                "Install with: pip install pymatgen"
            )

        # Already a Structure
        if isinstance(source, Structure):
            logger.debug("Using provided pymatgen Structure")
            return source

        source_str = str(source)

        # Materials Project ID
        if source_str.startswith("mp-"):
            return self._load_from_mp(source_str)

        # AiiDA node
        if source_str.startswith("aiida:"):
            pk_or_uuid = source_str[6:]
            return self._load_from_aiida(pk_or_uuid)

        # File path
        path = Path(source_str)
        if path.exists():
            return self._load_from_file(path)

        # Try as MP ID without prefix
        if source_str.isdigit() or (
            len(source_str) < 10 and source_str.replace("-", "").isalnum()
        ):
            try:
                return self._load_from_mp(f"mp-{source_str}")
            except Exception:
                pass

        raise StructureLoadError(
            f"Cannot load structure from: {source}. "
            f"Expected: file path, 'mp-XXX' ID, or pymatgen Structure."
        )

    def _load_from_file(self, path: Path) -> "Structure":
        """Load structure from file.

        Args:
            path: Path to structure file (CIF, POSCAR, etc.)

        Returns:
            pymatgen Structure

        Raises:
            StructureLoadError: If file cannot be read
        """
        from pymatgen.core import Structure

        try:
            structure = Structure.from_file(str(path))
            logger.info(f"Loaded structure from {path}: {structure.formula}")
            return structure
        except Exception as e:
            raise StructureLoadError(f"Failed to load structure from {path}: {e}")

    def _load_from_mp(self, material_id: str) -> "Structure":
        """Fetch structure from Materials Project.

        Args:
            material_id: Materials Project ID (e.g., "mp-149")

        Returns:
            pymatgen Structure

        Raises:
            StructureLoadError: If MP lookup fails
        """
        try:
            from mp_api.client import MPRester
        except ImportError:
            raise StructureLoadError(
                "mp-api is required for Materials Project access. "
                "Install with: pip install mp-api"
            )

        try:
            with MPRester() as mpr:
                structure = mpr.get_structure_by_material_id(material_id)
                if structure is None:
                    raise StructureLoadError(
                        f"Material {material_id} not found in Materials Project"
                    )
                logger.info(f"Fetched structure from MP: {material_id}")
                return structure
        except Exception as e:
            raise StructureLoadError(f"Failed to fetch {material_id} from MP: {e}")

    def _load_from_aiida(self, pk_or_uuid: str) -> "Structure":
        """Load structure from AiiDA database.

        Args:
            pk_or_uuid: AiiDA node PK (numeric) or UUID

        Returns:
            pymatgen Structure

        Raises:
            StructureLoadError: If AiiDA lookup fails
        """
        try:
            from aiida.orm import load_node
        except ImportError:
            raise StructureLoadError(
                "AiiDA is required for loading structures from AiiDA database. "
                "Install with: pip install aiida-core"
            )

        try:
            # Try as PK (integer) first
            try:
                pk = int(pk_or_uuid)
                node = load_node(pk)
            except ValueError:
                # UUID
                node = load_node(pk_or_uuid)

            # Get pymatgen structure
            structure = node.get_pymatgen_structure()
            logger.info(f"Loaded structure from AiiDA node: {pk_or_uuid}")
            return structure
        except Exception as e:
            raise StructureLoadError(f"Failed to load AiiDA node {pk_or_uuid}: {e}")

    def _get_structure_info(self, structure: "Structure") -> StructureInfo:
        """Extract metadata from structure.

        Args:
            structure: pymatgen Structure

        Returns:
            StructureInfo with formula, symmetry, etc.
        """
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

        try:
            sga = SpacegroupAnalyzer(structure)
            spg_number = sga.get_space_group_number()
            spg_symbol = sga.get_space_group_symbol()
        except Exception:
            spg_number = None
            spg_symbol = None

        return StructureInfo(
            formula=structure.composition.reduced_formula,
            num_atoms=len(structure),
            space_group_number=spg_number,
            space_group_symbol=spg_symbol,
            volume=structure.volume,
            is_magnetic=self._check_magnetic(structure),
            dimensionality=self._get_dimensionality(structure),
        )

    def _check_magnetic(self, structure: "Structure") -> bool:
        """Check if structure likely has magnetic ordering.

        Args:
            structure: pymatgen Structure

        Returns:
            True if structure contains magnetic elements
        """
        magnetic_elements = {
            "Fe", "Co", "Ni", "Mn", "Cr", "V", "Ti",
            "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
            "Nd", "Sm", "Eu", "Ce", "Pr",
        }
        elements = {str(el) for el in structure.composition.elements}
        return bool(elements & magnetic_elements)

    def _get_dimensionality(self, structure: "Structure") -> int:
        """Determine structure dimensionality (3D, 2D, 1D, 0D).

        Args:
            structure: pymatgen Structure

        Returns:
            Dimensionality (3, 2, 1, or 0)
        """
        # Simple heuristic based on vacuum in lattice
        lattice = structure.lattice
        abc = sorted([lattice.a, lattice.b, lattice.c], reverse=True)

        # Check for large vacuum (> 15 Angstrom suggests lower dimension)
        vacuum_threshold = 15.0
        n_large = sum(1 for x in abc if x > vacuum_threshold)

        if n_large >= 2:
            return 1  # Wire/polymer
        elif n_large >= 1:
            return 2  # Slab/2D material
        else:
            return 3  # Bulk

    # =========================================================================
    # Code Selection
    # =========================================================================

    def _select_code(
        self,
        workflow_type: WorkflowType,
        preference: Optional[DFTCode] = None,
        previous_code: Optional[DFTCode] = None,
    ) -> DFTCode:
        """Select appropriate DFT code for a workflow step.

        Uses PropertyCalculator registry for intelligent selection based on:
        1. User preference
        2. Cluster availability
        3. Code compatibility with previous step

        Args:
            workflow_type: Type of workflow step
            preference: User-specified preference
            previous_code: Code used in previous step

        Returns:
            Selected DFT code

        Raises:
            CodeNotAvailableError: If no compatible code available
        """
        from .registry import NoCompatibleCodeError, PropertyCalculator

        try:
            return PropertyCalculator.select_code(
                property_name=workflow_type.value,
                available_codes=self.available_codes,
                user_preference=preference,
                previous_code=previous_code,
            )
        except NoCompatibleCodeError as e:
            raise CodeNotAvailableError(str(e))

    # =========================================================================
    # Parameter Generation
    # =========================================================================

    def _get_parameters(
        self,
        workflow_type: WorkflowType,
        code: DFTCode,
        **overrides: Any,
    ) -> Dict[str, Any]:
        """Generate calculation parameters.

        Args:
            workflow_type: Type of calculation
            code: Target DFT code
            **overrides: Parameter overrides

        Returns:
            Complete parameter dictionary
        """
        # Base parameters based on protocol
        params = self._get_protocol_parameters(workflow_type)

        # Add code-specific parameters
        code_params = self._get_code_parameters(code, workflow_type)
        params.update(code_params)

        # Apply overrides
        params.update(overrides)

        return params

    def _get_protocol_parameters(self, workflow_type: WorkflowType) -> Dict[str, Any]:
        """Get parameters based on protocol level.

        Args:
            workflow_type: Type of calculation

        Returns:
            Protocol-appropriate parameters
        """
        protocol = self._config.protocol

        # K-point density (1/Angstrom)
        kpoint_densities = {
            "fast": 0.08,
            "moderate": 0.04,
            "precise": 0.02,
        }

        # Energy convergence (eV)
        energy_conv = {
            "fast": 1e-4,
            "moderate": 1e-5,
            "precise": 1e-6,
        }

        # Force convergence (eV/Angstrom)
        force_conv = {
            "fast": 0.05,
            "moderate": 0.01,
            "precise": 0.001,
        }

        return {
            "kpoint_density": kpoint_densities[protocol],
            "energy_convergence": energy_conv[protocol],
            "force_convergence": force_conv[protocol],
        }

    def _get_code_parameters(
        self,
        code: DFTCode,
        workflow_type: WorkflowType,
    ) -> Dict[str, Any]:
        """Get code-specific parameters.

        Args:
            code: DFT code
            workflow_type: Type of calculation

        Returns:
            Code-specific parameters
        """
        params: Dict[str, Any] = {}

        if code == "vasp":
            params.update({
                "prec": "Accurate",
                "algo": "Normal",
                "ismear": 0,
                "sigma": 0.05,
            })
            if workflow_type == WorkflowType.RELAX:
                params["ibrion"] = 2
                params["isif"] = 3
                params["nsw"] = 200

        elif code == "crystal23":
            params.update({
                "dft_type": "PBE",
                "spinpol": "AUTO",
            })

        elif code == "quantum_espresso":
            params.update({
                "calculation": "scf",
                "ecutwfc": 60.0,  # Ry
                "ecutrho": 480.0,  # Ry
            })

        elif code == "yambo":
            params.update({
                "gw_mode": "GW0",
                "screening_bands": "auto",
            })

        return params

    # =========================================================================
    # Workflow Execution
    # =========================================================================

    def run(
        self,
        structure: Union[str, Path, "Structure"],
        **kwargs: Any,
    ) -> "AnalysisResults":
        """Run the analysis workflow synchronously.

        This is the main entry point for workflow execution. It:
        1. Loads and validates the input structure
        2. Builds workflow steps via _build_workflow_steps()
        3. Validates step dependencies and code compatibility
        4. Submits workflow to runner and monitors progress
        5. Collects and returns unified results

        Args:
            structure: Input structure source (file, MP ID, or Structure object)
            **kwargs: Additional parameters passed to step builders

        Returns:
            AnalysisResults with all computed properties

        Raises:
            StructureLoadError: If structure cannot be loaded
            WorkflowBuildError: If workflow construction fails
            WorkflowExecutionError: If workflow execution fails

        Example:
            runner = StandardAnalysis(cluster=cluster, protocol="moderate")
            results = runner.run("mp-149")  # Silicon
            print(f"Band gap: {results.band_gap_ev:.2f} eV")
        """
        # Generate workflow ID
        self._workflow_id = str(uuid.uuid4())
        self._started_at = datetime.now()

        logger.info(
            f"Starting {self.__class__.__name__} workflow [{self._workflow_id[:8]}...]"
        )

        try:
            # Load structure
            self._structure = self._load_structure(structure)
            self._structure_info = self._get_structure_info(self._structure)

            logger.info(
                f"Structure: {self._structure_info.formula} "
                f"({self._structure_info.num_atoms} atoms, "
                f"SG {self._structure_info.space_group_symbol})"
            )

            # Build workflow steps
            self._steps = self._build_workflow_steps()
            logger.info(f"Built workflow with {len(self._steps)} steps")

            # Validate workflow
            self._validate_workflow()

            # Setup output directory
            self._setup_output_dir()

            # Report progress start
            if self._config.progress_callback:
                self._config.progress_callback.on_started(
                    self._workflow_id,
                    self._steps[0].workflow_type if self._steps else WorkflowType.SCF,
                )

            # Execute workflow
            if self._config.dry_run:
                logger.info("Dry run mode - skipping execution")
                result = self._create_dry_run_result()
            else:
                result = self._execute_workflow(**kwargs)

            self._completed_at = datetime.now()

            # Report completion
            if self._config.progress_callback:
                self._config.progress_callback.on_completed(self._workflow_id, result)

            # Convert to AnalysisResults
            return self._create_analysis_results(result)

        except Exception as e:
            self._completed_at = datetime.now()

            # Report failure
            if self._config.progress_callback:
                self._config.progress_callback.on_failed(
                    self._workflow_id,
                    str(e),
                    recoverable=isinstance(e, WorkflowExecutionError),
                )

            raise

    async def run_async(
        self,
        structure: Union[str, Path, "Structure"],
        **kwargs: Any,
    ) -> AsyncIterator["ProgressUpdate"]:
        """Run workflow asynchronously with progress updates.

        Yields ProgressUpdate objects for each step, enabling real-time
        progress monitoring in Jupyter notebooks and async applications.

        Args:
            structure: Input structure source
            **kwargs: Additional parameters

        Yields:
            ProgressUpdate objects with step progress and intermediate results

        Example:
            async for update in runner.run_async("mp-149"):
                print(f"Step: {update.step_name}, Progress: {update.percent}%")
                if update.status == "completed":
                    final_results = update.intermediate_result
        """
        from .builder import ProgressUpdate

        # Generate workflow ID
        self._workflow_id = str(uuid.uuid4())
        self._started_at = datetime.now()

        try:
            # Load structure
            self._structure = self._load_structure(structure)
            self._structure_info = self._get_structure_info(self._structure)

            # Build workflow
            self._steps = self._build_workflow_steps()
            self._validate_workflow()
            self._setup_output_dir()

            # Execute steps with progress
            total_steps = len(self._steps)
            start_time = datetime.now()

            for idx, step in enumerate(self._steps):
                step_start = datetime.now()

                # Yield progress for step start
                yield ProgressUpdate(
                    workflow_id=self._workflow_id,
                    step_name=step.name,
                    step_index=idx,
                    total_steps=total_steps,
                    percent=(idx / total_steps) * 100,
                    status="running",
                    message=f"Starting {step.name}",
                    elapsed_seconds=(datetime.now() - start_time).total_seconds(),
                )

                # Execute step (in thread pool for blocking operations)
                try:
                    step_result = await asyncio.to_thread(
                        self._execute_step, step, **kwargs
                    )
                    self._step_results.append(step_result)

                    # Yield progress for step completion
                    yield ProgressUpdate(
                        workflow_id=self._workflow_id,
                        step_name=step.name,
                        step_index=idx,
                        total_steps=total_steps,
                        percent=((idx + 1) / total_steps) * 100,
                        status="completed" if step_result.success else "failed",
                        message=f"Completed {step.name}",
                        has_intermediate_result=True,
                        intermediate_result=step_result.outputs,
                        elapsed_seconds=(datetime.now() - start_time).total_seconds(),
                    )

                    if not step_result.success:
                        raise WorkflowExecutionError(
                            f"Step {step.name} failed: {step_result.errors}"
                        )

                except Exception as e:
                    yield ProgressUpdate(
                        workflow_id=self._workflow_id,
                        step_name=step.name,
                        step_index=idx,
                        total_steps=total_steps,
                        percent=((idx + 1) / total_steps) * 100,
                        status="failed",
                        message=str(e),
                        elapsed_seconds=(datetime.now() - start_time).total_seconds(),
                    )
                    raise

            # Final update with complete results
            self._completed_at = datetime.now()
            final_result = self._aggregate_results()

            yield ProgressUpdate(
                workflow_id=self._workflow_id,
                step_name="complete",
                step_index=total_steps,
                total_steps=total_steps,
                percent=100.0,
                status="completed",
                message="Workflow complete",
                has_intermediate_result=True,
                intermediate_result=self._create_analysis_results(final_result),
                elapsed_seconds=(self._completed_at - start_time).total_seconds(),
            )

        except Exception:
            self._completed_at = datetime.now()
            raise

    def _validate_workflow(self) -> None:
        """Validate workflow configuration.

        Raises:
            WorkflowBuildError: If validation fails
        """
        from .registry import PropertyCalculator

        issues: List[str] = []

        # Check we have steps
        if not self._steps:
            issues.append("No workflow steps defined")

        # Check step names are unique
        names = [s.name for s in self._steps]
        if len(names) != len(set(names)):
            issues.append("Duplicate step names found")

        # Check dependencies exist
        for step in self._steps:
            for dep in step.depends_on:
                if dep not in names:
                    issues.append(
                        f"Step '{step.name}' depends on unknown step '{dep}'"
                    )

        # Check code compatibility
        is_valid, code_issues = PropertyCalculator.validate_workflow_codes(self._steps)
        if not is_valid:
            issues.extend(code_issues)

        if issues:
            raise WorkflowBuildError(
                f"Workflow validation failed:\n" + "\n".join(f"  - {i}" for i in issues)
            )

    def _setup_output_dir(self) -> None:
        """Setup output directory."""
        if self._config.output_dir is None:
            # Create timestamped directory
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            formula = (
                self._structure_info.formula
                if self._structure_info
                else "unknown"
            )
            self._config.output_dir = Path(f"./results/{formula}_{timestamp}")

        self._config.output_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Output directory: {self._config.output_dir}")

    def _execute_workflow(self, **kwargs: Any) -> WorkflowResult:
        """Execute the workflow steps.

        Args:
            **kwargs: Additional execution parameters

        Returns:
            Aggregated WorkflowResult
        """
        for step in self._steps:
            # Report progress
            step_idx = self._steps.index(step)
            total_steps = len(self._steps)

            if self._config.progress_callback:
                progress = (step_idx / total_steps) * 100
                self._config.progress_callback.on_progress(
                    self._workflow_id,
                    step.name,
                    progress,
                    f"Executing {step.workflow_type.value}",
                )

            # Execute step with retry logic
            step_result = self._execute_step_with_retry(step, **kwargs)
            self._step_results.append(step_result)

            # Check for failure
            if not step_result.success:
                if self._config.recovery_strategy == ErrorRecoveryStrategy.FAIL_FAST:
                    raise WorkflowExecutionError(
                        f"Step '{step.name}' failed: {step_result.errors}"
                    )
                elif self._config.recovery_strategy == ErrorRecoveryStrategy.ADAPTIVE:
                    # Try adaptive recovery
                    step_result = self._attempt_adaptive_recovery(step, step_result)
                    if not step_result.success:
                        raise WorkflowExecutionError(
                            f"Step '{step.name}' failed after recovery attempt"
                        )

        return self._aggregate_results()

    def _execute_step(self, step: WorkflowStep, **kwargs: Any) -> StepResult:
        """Execute a single workflow step.

        Args:
            step: Workflow step to execute
            **kwargs: Additional parameters

        Returns:
            StepResult with outputs or errors
        """
        logger.info(f"Executing step: {step.name} ({step.code})")
        start_time = datetime.now()

        try:
            # In real implementation, this would submit to runner
            # For now, return stub result
            if self._runner is None:
                # Stub execution for development
                logger.warning(
                    f"No runner configured - step {step.name} will be simulated"
                )
                return StepResult(
                    step_name=step.name,
                    success=True,
                    outputs={"simulated": True},
                    wall_time_seconds=(datetime.now() - start_time).total_seconds(),
                )

            # Real execution via runner
            result = self._runner.submit(
                workflow_type=step.workflow_type,
                structure=self._structure,
                parameters=step.parameters,
                code=step.code,
                resources=step.resources or self._get_default_resources(),
            )

            return StepResult(
                step_name=step.name,
                success=result.success,
                outputs=result.outputs,
                errors=result.errors,
                wall_time_seconds=result.wall_time_seconds,
                cpu_time_seconds=result.cpu_time_seconds,
            )

        except Exception as e:
            logger.error(f"Step {step.name} failed: {e}")
            return StepResult(
                step_name=step.name,
                success=False,
                errors=[str(e)],
                wall_time_seconds=(datetime.now() - start_time).total_seconds(),
            )

    def _execute_step_with_retry(
        self,
        step: WorkflowStep,
        **kwargs: Any,
    ) -> StepResult:
        """Execute step with retry logic.

        Args:
            step: Workflow step
            **kwargs: Additional parameters

        Returns:
            StepResult from successful attempt or last failure
        """
        max_retries = self._config.max_retries
        last_result: Optional[StepResult] = None

        for attempt in range(max_retries + 1):
            if attempt > 0:
                logger.info(f"Retry attempt {attempt}/{max_retries} for {step.name}")

            result = self._execute_step(step, **kwargs)
            last_result = result

            if result.success:
                return result

            # Check if error is retryable
            if not self._is_retryable_error(result):
                break

        return last_result or StepResult(
            step_name=step.name,
            success=False,
            errors=["Unknown error"],
        )

    def _is_retryable_error(self, result: StepResult) -> bool:
        """Check if step failure is retryable.

        Args:
            result: Step result to check

        Returns:
            True if error might succeed on retry
        """
        # Transient errors that might succeed on retry
        retryable_patterns = [
            "timeout",
            "connection",
            "temporary",
            "resource",
            "memory",
        ]

        error_text = " ".join(result.errors).lower()
        return any(p in error_text for p in retryable_patterns)

    def _attempt_adaptive_recovery(
        self,
        step: WorkflowStep,
        failed_result: StepResult,
    ) -> StepResult:
        """Attempt adaptive recovery for failed step.

        Analyzes failure and adjusts parameters to retry.

        Args:
            step: Failed step
            failed_result: Result from failed attempt

        Returns:
            StepResult from recovery attempt
        """
        logger.info(f"Attempting adaptive recovery for {step.name}")

        # Analyze error
        error_text = " ".join(failed_result.errors).lower()

        # Memory issues - reduce parallelization
        if "memory" in error_text or "oom" in error_text:
            logger.info("Detected memory issue - reducing parallelization")
            if step.resources:
                step.resources.num_mpi_ranks = max(1, step.resources.num_mpi_ranks // 2)

        # Convergence issues - relax parameters
        if "convergence" in error_text or "scf" in error_text:
            logger.info("Detected convergence issue - adjusting parameters")
            step.parameters["energy_convergence"] = step.parameters.get(
                "energy_convergence", 1e-5
            ) * 10

        # Retry with adjusted parameters
        return self._execute_step(step)

    def _aggregate_results(self) -> WorkflowResult:
        """Aggregate results from all steps into single WorkflowResult.

        Returns:
            Combined WorkflowResult
        """
        # Merge all outputs
        all_outputs: Dict[str, Any] = {}
        all_errors: List[str] = []
        all_warnings: List[str] = []
        total_wall_time = 0.0
        total_cpu_time = 0.0

        for result in self._step_results:
            all_outputs[result.step_name] = result.outputs
            all_errors.extend(result.errors)
            if result.wall_time_seconds:
                total_wall_time += result.wall_time_seconds
            if result.cpu_time_seconds:
                total_cpu_time += result.cpu_time_seconds

        # Extract top-level properties
        if self._structure_info:
            all_outputs["formula"] = self._structure_info.formula
            all_outputs["space_group"] = self._structure_info.space_group_symbol

        return WorkflowResult(
            success=all(r.success for r in self._step_results),
            workflow_id=self._workflow_id,
            outputs=all_outputs,
            errors=all_errors,
            warnings=all_warnings,
            started_at=self._started_at,
            completed_at=self._completed_at,
            wall_time_seconds=total_wall_time,
            cpu_time_seconds=total_cpu_time,
        )

    def _create_dry_run_result(self) -> WorkflowResult:
        """Create placeholder result for dry run mode.

        Returns:
            WorkflowResult with simulated data
        """
        return WorkflowResult(
            success=True,
            workflow_id=self._workflow_id,
            outputs={
                "dry_run": True,
                "steps": [s.name for s in self._steps],
                "formula": self._structure_info.formula if self._structure_info else "",
            },
            metadata={"mode": "dry_run"},
            started_at=self._started_at,
            completed_at=datetime.now(),
        )

    def _create_analysis_results(
        self,
        workflow_result: WorkflowResult,
    ) -> "AnalysisResults":
        """Convert WorkflowResult to AnalysisResults.

        Args:
            workflow_result: Raw workflow result

        Returns:
            AnalysisResults with structured data
        """
        from .results import AnalysisResults

        outputs = workflow_result.outputs

        return AnalysisResults(
            formula=outputs.get("formula", ""),
            structure=self._structure,
            space_group=outputs.get("space_group", ""),
            band_gap_ev=outputs.get("band_gap_ev"),
            is_direct_gap=outputs.get("is_direct_gap"),
            fermi_energy_ev=outputs.get("fermi_energy_ev"),
            is_metal=outputs.get("is_metal", False),
            gw_gap_ev=outputs.get("gw_gap_ev"),
            optical_gap_ev=outputs.get("optical_gap_ev"),
            exciton_binding_ev=outputs.get("exciton_binding_ev"),
            bulk_modulus_gpa=outputs.get("bulk_modulus_gpa"),
            shear_modulus_gpa=outputs.get("shear_modulus_gpa"),
            youngs_modulus_gpa=outputs.get("youngs_modulus_gpa"),
            poisson_ratio=outputs.get("poisson_ratio"),
            static_dielectric=outputs.get("static_dielectric"),
            has_imaginary_modes=outputs.get("has_imaginary_modes"),
            seebeck_coefficient=outputs.get("seebeck_coefficient"),
            electrical_conductivity=outputs.get("electrical_conductivity"),
            thermal_conductivity=outputs.get("thermal_conductivity"),
            workflow_id=workflow_result.workflow_id,
            completed_at=workflow_result.completed_at,
            total_cpu_hours=(
                workflow_result.cpu_time_seconds / 3600
                if workflow_result.cpu_time_seconds
                else None
            ),
        )


# =============================================================================
# Standard Analysis Runner
# =============================================================================


class StandardAnalysis(BaseAnalysisRunner):
    """Workflow runner for standard electronic structure analysis.

    Performs ground-state DFT calculations including:
    - Structure relaxation (optional)
    - Self-consistent field (SCF) calculation
    - Band structure along high-symmetry path
    - Density of states (total and projected)

    This is the most common workflow for initial material characterization.

    Attributes:
        include_relax: Whether to relax structure before SCF
        include_bands: Whether to calculate band structure
        include_dos: Whether to calculate DOS
        kpath: K-point path specification
        dos_mesh: K-point mesh for DOS
        dft_code: DFT code to use (auto-selected if None)

    Example:
        runner = StandardAnalysis(
            cluster=get_cluster_profile("beefcake2"),
            protocol="moderate",
            include_relax=True,
            include_bands=True,
            include_dos=True,
        )
        results = runner.run("mp-149")
        print(f"Band gap: {results.band_gap_ev:.2f} eV")
        fig = results.plot_bands_dos()
    """

    def __init__(
        self,
        include_relax: bool = True,
        include_bands: bool = True,
        include_dos: bool = True,
        kpath: Union[str, List[Tuple[str, List[float]]]] = "auto",
        dos_mesh: Optional[List[int]] = None,
        dft_code: Optional[DFTCode] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize standard analysis runner.

        Args:
            include_relax: Whether to relax structure before SCF
            include_bands: Whether to calculate band structure
            include_dos: Whether to calculate DOS
            kpath: K-point path for bands. Options:
                - "auto": Auto-detect from structure symmetry
                - "cubic", "fcc", "bcc", etc.: Use preset path
                - Custom list: [("Gamma", [0,0,0]), ("X", [0.5,0,0]), ...]
            dos_mesh: K-point mesh for DOS (auto if None)
            dft_code: DFT code preference (None for auto-selection)
            **kwargs: Base runner options (protocol, cluster, output_dir, etc.)
        """
        super().__init__(**kwargs)
        self._include_relax = include_relax
        self._include_bands = include_bands
        self._include_dos = include_dos
        self._kpath = kpath
        self._dos_mesh = dos_mesh
        self._dft_code = dft_code

    def _build_workflow_steps(self) -> List[WorkflowStep]:
        """Build standard analysis workflow steps.

        Returns:
            List of WorkflowStep objects
        """
        steps: List[WorkflowStep] = []
        previous_step: Optional[str] = None
        previous_code: Optional[DFTCode] = None

        # Select DFT code
        code = self._dft_code or self._select_code(WorkflowType.SCF)

        # Relaxation step
        if self._include_relax:
            relax_step = WorkflowStep(
                name="relax",
                workflow_type=WorkflowType.RELAX,
                code=code,
                parameters=self._get_parameters(WorkflowType.RELAX, code),
                resources=self._get_default_resources(),
            )
            steps.append(relax_step)
            previous_step = "relax"
            previous_code = code

        # SCF step
        scf_step = WorkflowStep(
            name="scf",
            workflow_type=WorkflowType.SCF,
            code=code,
            parameters=self._get_parameters(WorkflowType.SCF, code),
            depends_on=[previous_step] if previous_step else [],
            resources=self._get_default_resources(),
        )
        steps.append(scf_step)
        previous_step = "scf"

        # Band structure step
        if self._include_bands:
            band_params = self._get_parameters(WorkflowType.BANDS, code)
            band_params["kpath"] = self._kpath
            band_params["kpoints_per_segment"] = 50

            bands_step = WorkflowStep(
                name="bands",
                workflow_type=WorkflowType.BANDS,
                code=code,
                parameters=band_params,
                depends_on=[previous_step],
                outputs_to_pass=["wavefunction"],
                resources=self._get_default_resources(),
            )
            steps.append(bands_step)

        # DOS step
        if self._include_dos:
            dos_params = self._get_parameters(WorkflowType.DOS, code)
            dos_params["mesh"] = self._dos_mesh
            dos_params["projected"] = True
            dos_params["smearing"] = 0.05

            dos_step = WorkflowStep(
                name="dos",
                workflow_type=WorkflowType.DOS,
                code=code,
                parameters=dos_params,
                depends_on=[previous_step],
                outputs_to_pass=["wavefunction"],
                resources=self._get_default_resources(),
            )
            steps.append(dos_step)

        return steps

    def _get_default_resources(self) -> ResourceRequirements:
        """Get default resources for standard analysis.

        Returns:
            ResourceRequirements
        """
        if self._cluster:
            # Use cluster preset
            try:
                return self._cluster.get_preset("medium")
            except KeyError:
                pass

        # Default resources
        return ResourceRequirements(
            num_nodes=1,
            num_mpi_ranks=20,
            num_threads_per_rank=2,
            memory_gb=64,
            walltime_hours=12,
            gpus=0,
        )


# =============================================================================
# Optical Analysis Runner
# =============================================================================


class OpticalAnalysis(BaseAnalysisRunner):
    """Workflow runner for optical properties via many-body perturbation theory.

    Performs multi-code workflow: DFT (VASP/QE) -> GW (YAMBO) -> BSE (YAMBO)

    Steps:
    1. DFT ground state with fine k-mesh
    2. G0W0/GW0 quasiparticle corrections
    3. BSE optical absorption with excitonic effects

    This workflow requires wavefunctions to be passed between codes,
    handled automatically via p2y/yambo converters.

    Attributes:
        dft_code: DFT code for ground state (vasp, quantum_espresso)
        gw_code: Many-body code (yambo, berkeleygw)
        gw_protocol: GW flavor (g0w0, gw0, evgw)
        n_bands_gw: Number of bands for GW
        n_valence_bse: Number of valence bands for BSE
        n_conduction_bse: Number of conduction bands for BSE
        include_bse: Whether to calculate BSE optical spectrum

    Example:
        runner = OpticalAnalysis(
            cluster=get_cluster_profile("beefcake2"),
            dft_code="vasp",
            gw_code="yambo",
            gw_protocol="gw0",
            n_bands_gw=100,
            n_valence_bse=4,
            n_conduction_bse=4,
        )
        results = runner.run("NbOCl2.cif")
        print(f"GW gap: {results.gw_gap_ev:.2f} eV")
        print(f"Optical gap: {results.optical_gap_ev:.2f} eV")
        print(f"Exciton binding: {results.exciton_binding_ev:.3f} eV")
    """

    def __init__(
        self,
        dft_code: DFTCode = "vasp",
        gw_code: DFTCode = "yambo",
        gw_protocol: str = "gw0",
        n_bands_gw: Optional[int] = None,
        n_valence_bse: int = 4,
        n_conduction_bse: int = 4,
        include_bse: bool = True,
        **kwargs: Any,
    ) -> None:
        """Initialize optical analysis runner.

        Args:
            dft_code: DFT code for ground state
            gw_code: Many-body code (yambo, berkeleygw)
            gw_protocol: GW flavor:
                - "g0w0": Single-shot (fastest)
                - "gw0": Partially self-consistent (recommended)
                - "evgw": Eigenvalue self-consistent
            n_bands_gw: Number of bands for GW (auto if None)
            n_valence_bse: Valence bands for BSE
            n_conduction_bse: Conduction bands for BSE
            include_bse: Calculate BSE optical spectrum
            **kwargs: Base runner options
        """
        super().__init__(**kwargs)
        self._dft_code = dft_code
        self._gw_code = gw_code
        self._gw_protocol = gw_protocol
        self._n_bands_gw = n_bands_gw
        self._n_valence_bse = n_valence_bse
        self._n_conduction_bse = n_conduction_bse
        self._include_bse = include_bse

        # Validate code availability
        if self._cluster:
            if dft_code not in self._cluster.available_codes:
                raise CodeNotAvailableError(
                    f"DFT code '{dft_code}' not available on cluster"
                )
            if gw_code not in self._cluster.available_codes:
                raise CodeNotAvailableError(
                    f"GW code '{gw_code}' not available on cluster"
                )

    def _build_workflow_steps(self) -> List[WorkflowStep]:
        """Build GW/BSE workflow steps.

        Returns:
            List of WorkflowStep objects
        """
        steps: List[WorkflowStep] = []

        # DFT ground state with dense k-mesh
        dft_params = self._get_parameters(WorkflowType.SCF, self._dft_code)
        dft_params["kpoint_density"] = 0.03  # Denser for GW
        dft_params["nbands"] = self._n_bands_gw or "auto"

        scf_step = WorkflowStep(
            name="dft_scf",
            workflow_type=WorkflowType.SCF,
            code=self._dft_code,
            parameters=dft_params,
            resources=self._get_dft_resources(),
        )
        steps.append(scf_step)

        # GW calculation
        gw_params = self._get_parameters(WorkflowType.GW, self._gw_code)
        gw_params["protocol"] = self._gw_protocol
        gw_params["n_bands"] = self._n_bands_gw
        gw_params["screening_bands"] = "auto"
        gw_params["w_bands"] = "auto"

        gw_step = WorkflowStep(
            name="gw",
            workflow_type=WorkflowType.GW,
            code=self._gw_code,
            parameters=gw_params,
            depends_on=["dft_scf"],
            outputs_to_pass=["wavefunction", "eigenvalues"],
            resources=self._get_gw_resources(),
        )
        steps.append(gw_step)

        # BSE calculation
        if self._include_bse:
            bse_params = self._get_parameters(WorkflowType.BSE, self._gw_code)
            bse_params["n_valence"] = self._n_valence_bse
            bse_params["n_conduction"] = self._n_conduction_bse
            bse_params["coupling"] = True  # Resonant + anti-resonant

            bse_step = WorkflowStep(
                name="bse",
                workflow_type=WorkflowType.BSE,
                code=self._gw_code,
                parameters=bse_params,
                depends_on=["gw"],
                outputs_to_pass=["qp_corrections"],
                resources=self._get_bse_resources(),
            )
            steps.append(bse_step)

        return steps

    def _get_dft_resources(self) -> ResourceRequirements:
        """Get resources for DFT step."""
        if self._cluster:
            try:
                return self._cluster.get_preset("medium")
            except KeyError:
                pass

        return ResourceRequirements(
            num_nodes=1,
            num_mpi_ranks=20,
            walltime_hours=4,
        )

    def _get_gw_resources(self) -> ResourceRequirements:
        """Get resources for GW step (GPU preferred)."""
        if self._cluster:
            try:
                return self._cluster.get_preset("gpu-single")
            except KeyError:
                try:
                    return self._cluster.get_preset("large")
                except KeyError:
                    pass

        return ResourceRequirements(
            num_nodes=1,
            num_mpi_ranks=1,
            num_threads_per_rank=4,
            memory_gb=128,
            walltime_hours=24,
            gpus=1,
            partition="gpu",
        )

    def _get_bse_resources(self) -> ResourceRequirements:
        """Get resources for BSE step (GPU preferred)."""
        return self._get_gw_resources()

    def _get_default_resources(self) -> ResourceRequirements:
        """Get default resources."""
        return self._get_gw_resources()


# =============================================================================
# Phonon Analysis Runner
# =============================================================================


class PhononAnalysis(BaseAnalysisRunner):
    """Workflow runner for phonon dispersion and thermodynamics.

    Calculates phonon properties using the finite displacement method:
    1. Relaxation to get equilibrium structure
    2. Generate displaced supercells
    3. Calculate forces for each displacement
    4. Construct force constants
    5. Calculate phonon dispersion and DOS

    Optionally calculates thermodynamic properties:
    - Heat capacity
    - Helmholtz free energy
    - Entropy
    - Zero-point energy

    Attributes:
        supercell: Supercell dimensions [nx, ny, nz]
        displacement: Displacement amplitude (Angstrom)
        include_thermodynamics: Calculate thermodynamic properties
        temperature_range: Temperature range for thermodynamics (K)
        dft_code: DFT code to use

    Example:
        runner = PhononAnalysis(
            cluster=get_cluster_profile("beefcake2"),
            supercell=[2, 2, 2],
            displacement=0.01,
            include_thermodynamics=True,
            temperature_range=(0, 1000, 10),
        )
        results = runner.run("Si.cif")

        if results.has_imaginary_modes:
            print("Structure is dynamically unstable!")
        else:
            fig = results.plot_phonons()
    """

    def __init__(
        self,
        supercell: Optional[List[int]] = None,
        displacement: float = 0.01,
        include_thermodynamics: bool = True,
        temperature_range: Tuple[float, float, float] = (0, 1000, 10),
        dft_code: Optional[DFTCode] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize phonon analysis runner.

        Args:
            supercell: Supercell dimensions (auto if None)
            displacement: Finite displacement amplitude (Angstrom)
            include_thermodynamics: Calculate thermodynamic properties
            temperature_range: (T_min, T_max, T_step) in Kelvin
            dft_code: DFT code preference
            **kwargs: Base runner options
        """
        super().__init__(**kwargs)
        self._supercell = supercell or [2, 2, 2]
        self._displacement = displacement
        self._include_thermodynamics = include_thermodynamics
        self._temperature_range = temperature_range
        self._dft_code = dft_code

    def _build_workflow_steps(self) -> List[WorkflowStep]:
        """Build phonon workflow steps.

        Returns:
            List of WorkflowStep objects
        """
        steps: List[WorkflowStep] = []

        # Select code
        code = self._dft_code or self._select_code(WorkflowType.PHONON)

        # Relaxation
        relax_params = self._get_parameters(WorkflowType.RELAX, code)
        relax_params["force_convergence"] = 0.001  # Tight for phonons

        relax_step = WorkflowStep(
            name="relax",
            workflow_type=WorkflowType.RELAX,
            code=code,
            parameters=relax_params,
            resources=self._get_default_resources(),
        )
        steps.append(relax_step)

        # Phonon calculation
        phonon_params = self._get_parameters(WorkflowType.PHONON, code)
        phonon_params["supercell"] = self._supercell
        phonon_params["displacement"] = self._displacement
        phonon_params["symmetry"] = True  # Use symmetry to reduce displacements

        phonon_step = WorkflowStep(
            name="phonon",
            workflow_type=WorkflowType.PHONON,
            code=code,
            parameters=phonon_params,
            depends_on=["relax"],
            resources=self._get_phonon_resources(),
        )
        steps.append(phonon_step)

        return steps

    def _get_phonon_resources(self) -> ResourceRequirements:
        """Get resources for phonon calculations.

        Phonon calculations involve many force calculations, so we use
        larger resources.
        """
        if self._cluster:
            try:
                return self._cluster.get_preset("large")
            except KeyError:
                pass

        # Estimate number of displacements
        n_atoms_primitive = 10  # Estimate
        n_displacements = n_atoms_primitive * 2 * 3  # 2 displacements per direction

        return ResourceRequirements(
            num_nodes=2,
            num_mpi_ranks=80,
            memory_gb=128,
            walltime_hours=48,
        )

    def _get_default_resources(self) -> ResourceRequirements:
        """Get default resources."""
        if self._cluster:
            try:
                return self._cluster.get_preset("medium")
            except KeyError:
                pass

        return ResourceRequirements(
            num_nodes=1,
            num_mpi_ranks=20,
            walltime_hours=12,
        )


# =============================================================================
# Elastic Analysis Runner
# =============================================================================


class ElasticAnalysis(BaseAnalysisRunner):
    """Workflow runner for elastic constants and mechanical properties.

    Calculates elastic properties via the stress-strain method:
    1. Relaxation to get equilibrium structure
    2. Apply small strains in different directions
    3. Calculate stress tensor for each strain
    4. Fit to get elastic tensor C_ij

    Derives mechanical properties:
    - Bulk modulus (Voigt, Reuss, Hill averages)
    - Shear modulus
    - Young's modulus
    - Poisson ratio
    - Anisotropy index

    Attributes:
        strain_magnitude: Strain amplitude for elastic calculation
        num_strains: Number of strain steps (for fitting)
        dft_code: DFT code to use (VASP recommended)

    Example:
        runner = ElasticAnalysis(
            cluster=get_cluster_profile("beefcake2"),
            strain_magnitude=0.01,
            num_strains=6,
        )
        results = runner.run("TiO2.cif")

        print(f"Bulk modulus: {results.bulk_modulus_gpa:.1f} GPa")
        print(f"Shear modulus: {results.shear_modulus_gpa:.1f} GPa")
        print(f"Young's modulus: {results.youngs_modulus_gpa:.1f} GPa")
    """

    def __init__(
        self,
        strain_magnitude: float = 0.01,
        num_strains: int = 6,
        dft_code: Optional[DFTCode] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize elastic analysis runner.

        Args:
            strain_magnitude: Maximum strain amplitude (default 1%)
            num_strains: Number of strain points for linear fit
            dft_code: DFT code preference (VASP recommended)
            **kwargs: Base runner options
        """
        super().__init__(**kwargs)
        self._strain_magnitude = strain_magnitude
        self._num_strains = num_strains
        self._dft_code = dft_code or "vasp"

    def _build_workflow_steps(self) -> List[WorkflowStep]:
        """Build elastic workflow steps.

        Returns:
            List of WorkflowStep objects
        """
        steps: List[WorkflowStep] = []
        code = self._dft_code

        # Relaxation (tight convergence)
        relax_params = self._get_parameters(WorkflowType.RELAX, code)
        relax_params["force_convergence"] = 0.001
        relax_params["stress_convergence"] = 0.01  # kbar

        relax_step = WorkflowStep(
            name="relax",
            workflow_type=WorkflowType.RELAX,
            code=code,
            parameters=relax_params,
            resources=self._get_default_resources(),
        )
        steps.append(relax_step)

        # Elastic calculation
        elastic_params = self._get_parameters(WorkflowType.ELASTIC, code)
        elastic_params["strain_magnitude"] = self._strain_magnitude
        elastic_params["num_strains"] = self._num_strains
        elastic_params["symmetry"] = True

        elastic_step = WorkflowStep(
            name="elastic",
            workflow_type=WorkflowType.ELASTIC,
            code=code,
            parameters=elastic_params,
            depends_on=["relax"],
            resources=self._get_elastic_resources(),
        )
        steps.append(elastic_step)

        return steps

    def _get_elastic_resources(self) -> ResourceRequirements:
        """Get resources for elastic calculations."""
        if self._cluster:
            try:
                return self._cluster.get_preset("medium")
            except KeyError:
                pass

        # Elastic requires ~24 strain calculations
        return ResourceRequirements(
            num_nodes=1,
            num_mpi_ranks=20,
            memory_gb=64,
            walltime_hours=24,
        )

    def _get_default_resources(self) -> ResourceRequirements:
        """Get default resources."""
        return ResourceRequirements(
            num_nodes=1,
            num_mpi_ranks=20,
            walltime_hours=8,
        )


# =============================================================================
# Transport Analysis Runner
# =============================================================================


class TransportAnalysis(BaseAnalysisRunner):
    """Workflow runner for electronic transport properties.

    Uses BoltzTraP2 to calculate transport coefficients from DFT band structure:
    - Seebeck coefficient (thermopower)
    - Electrical conductivity
    - Thermal conductivity (electronic contribution)
    - Power factor

    Workflow:
    1. DFT relaxation and SCF
    2. Dense k-mesh calculation for accurate DOS
    3. BoltzTraP2 post-processing

    Attributes:
        doping_levels: Carrier concentrations to calculate (cm^-3)
        temperature_range: Temperature range (K)
        interpolation_factor: BoltzTraP interpolation factor
        dft_code: DFT code for ground state

    Example:
        runner = TransportAnalysis(
            cluster=get_cluster_profile("beefcake2"),
            doping_levels=[1e18, 1e19, 1e20],
            temperature_range=(300, 800, 50),
        )
        results = runner.run("Bi2Te3.cif")

        print(f"Seebeck (300K, 1e19 cm-3): {results.seebeck_coefficient} uV/K")
    """

    def __init__(
        self,
        doping_levels: Optional[List[float]] = None,
        temperature_range: Tuple[float, float, float] = (300, 800, 50),
        interpolation_factor: int = 5,
        dft_code: Optional[DFTCode] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize transport analysis runner.

        Args:
            doping_levels: Carrier concentrations (cm^-3)
            temperature_range: (T_min, T_max, T_step) in Kelvin
            interpolation_factor: BoltzTraP k-mesh interpolation
            dft_code: DFT code preference
            **kwargs: Base runner options
        """
        super().__init__(**kwargs)
        self._doping_levels = doping_levels or [1e18, 1e19, 1e20]
        self._temperature_range = temperature_range
        self._interpolation_factor = interpolation_factor
        self._dft_code = dft_code or "vasp"

    def _build_workflow_steps(self) -> List[WorkflowStep]:
        """Build transport workflow steps.

        Returns:
            List of WorkflowStep objects
        """
        steps: List[WorkflowStep] = []
        code = self._dft_code

        # Relaxation
        relax_step = WorkflowStep(
            name="relax",
            workflow_type=WorkflowType.RELAX,
            code=code,
            parameters=self._get_parameters(WorkflowType.RELAX, code),
            resources=self._get_default_resources(),
        )
        steps.append(relax_step)

        # Dense SCF for transport
        scf_params = self._get_parameters(WorkflowType.SCF, code)
        scf_params["kpoint_density"] = 0.02  # Very dense
        scf_params["nbands"] = "auto"  # Include empty bands

        scf_step = WorkflowStep(
            name="scf_dense",
            workflow_type=WorkflowType.SCF,
            code=code,
            parameters=scf_params,
            depends_on=["relax"],
            resources=self._get_transport_resources(),
        )
        steps.append(scf_step)

        # Note: BoltzTraP2 post-processing would be added here
        # as a separate step in full implementation

        return steps

    def _get_transport_resources(self) -> ResourceRequirements:
        """Get resources for transport calculations.

        Dense k-mesh requires more memory.
        """
        if self._cluster:
            try:
                return self._cluster.get_preset("large")
            except KeyError:
                pass

        return ResourceRequirements(
            num_nodes=1,
            num_mpi_ranks=20,
            memory_gb=128,
            walltime_hours=24,
        )

    def _get_default_resources(self) -> ResourceRequirements:
        """Get default resources."""
        return ResourceRequirements(
            num_nodes=1,
            num_mpi_ranks=20,
            walltime_hours=8,
        )


# =============================================================================
# Module Exports
# =============================================================================


__all__ = [
    # Exceptions
    "RunnerError",
    "StructureLoadError",
    "WorkflowBuildError",
    "WorkflowExecutionError",
    "CodeNotAvailableError",
    "MultiCodeHandoffError",
    # Configuration
    "RunnerConfig",
    "StepResult",
    # Base class
    "BaseAnalysisRunner",
    # Specialized runners
    "StandardAnalysis",
    "OpticalAnalysis",
    "PhononAnalysis",
    "ElasticAnalysis",
    "TransportAnalysis",
]
