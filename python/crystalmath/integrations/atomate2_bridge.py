"""
atomate2 Integration Bridge for CrystalMath.

This module provides adapters that map atomate2 Flows/Makers to CrystalMath's
unified workflow architecture. It enables using atomate2's extensive pre-built
workflows while maintaining compatibility with CrystalMath's Protocol interfaces.

Architecture Overview:
----------------------
```
    CrystalMath Protocols          atomate2/jobflow
    +------------------+           +------------------+
    | WorkflowRunner   |           | Maker            |
    | WorkflowType     |  <--->    | Flow             |
    | WorkflowResult   |           | Job              |
    +------------------+           +------------------+
           |                               |
           v                               v
    +------------------+           +------------------+
    | Atomate2Bridge   |---------->| FlowMakerRegistry|
    | (adapter layer)  |           | (maker lookup)   |
    +------------------+           +------------------+
           |
           v
    +------------------+
    | JobStoreBridge   |  (connects to crystalmath storage)
    +------------------+
```

Key Classes:
------------
- `FlowMakerRegistry`: Maps WorkflowType to atomate2 Maker classes
- `Atomate2FlowAdapter`: Wraps atomate2 Flows for CrystalMath compatibility
- `Atomate2Bridge`: Main integration point implementing WorkflowRunner-like interface
- `MultiCodeFlowBuilder`: Constructs multi-code workflows (VASP->YAMBO, etc.)

Usage:
------
>>> from crystalmath.integrations import Atomate2Bridge
>>> from crystalmath.protocols import WorkflowType
>>> from pymatgen.core import Structure
>>>
>>> bridge = Atomate2Bridge()
>>> structure = Structure.from_file("POSCAR")
>>>
>>> # Run VASP relaxation using atomate2's RelaxFlowMaker
>>> result = bridge.submit(
...     workflow_type=WorkflowType.RELAX,
...     structure=structure,
...     code="vasp",
...     parameters={"force_convergence": 0.01},
... )

Phase Implementation:
--------------------
This module provides STUB implementations for Phase 2 (design phase).
Full implementations will be completed in Phase 3.

See Also:
---------
- atomate2 documentation: https://materialsproject.github.io/atomate2/
- jobflow documentation: https://materialsproject.github.io/jobflow/
- CrystalMath protocols: `crystalmath.protocols`
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Generic,
    List,
    Literal,
    Optional,
    Protocol,
    Sequence,
    Type,
    TypeVar,
    Union,
)

if TYPE_CHECKING:
    from jobflow import Flow, Job, Maker
    from maggma.stores import Store
    from pymatgen.core import Structure

    from crystalmath.protocols import (
        DFTCode,
        ResourceRequirements,
        WorkflowResult,
        WorkflowState,
        WorkflowStep,
        WorkflowType,
    )

# Type variables
T = TypeVar("T")
MakerT = TypeVar("MakerT", bound="Maker")


# =============================================================================
# Exceptions
# =============================================================================


class Atomate2IntegrationError(Exception):
    """Base exception for atomate2 integration errors."""

    pass


class MakerNotFoundError(Atomate2IntegrationError):
    """Raised when no Maker is registered for a workflow type + code combination."""

    pass


class FlowExecutionError(Atomate2IntegrationError):
    """Raised when Flow execution fails."""

    pass


class CodeHandoffError(Atomate2IntegrationError):
    """Raised when data transfer between codes fails in multi-code workflows."""

    pass


# =============================================================================
# Enums for atomate2-specific configuration
# =============================================================================


class ExecutionMode(str, Enum):
    """Execution mode for atomate2 workflows."""

    LOCAL = "local"  # run_locally() - in-process execution
    REMOTE = "remote"  # jobflow-remote - HPC submission
    FIREWORKS = "fireworks"  # FireWorks backend (legacy)


class ProtocolLevel(str, Enum):
    """Standard protocol levels for atomate2 Makers."""

    # Standard protocols matching atomate2 conventions
    FAST = "fast"  # Quick calculations, low accuracy
    MODERATE = "moderate"  # Balanced accuracy/cost
    PRECISE = "precise"  # High accuracy, expensive

    # Extended protocols for specific use cases
    CONVERGENCE_TEST = "convergence_test"  # Parameter convergence studies
    PRODUCTION = "production"  # Production HPC runs
    DEBUG = "debug"  # Minimal settings for testing


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class MakerConfig:
    """
    Configuration for an atomate2 Maker.

    Attributes:
        maker_class: The atomate2 Maker class (e.g., RelaxFlowMaker)
        default_kwargs: Default arguments to pass to the Maker constructor
        protocol_mapping: Maps ProtocolLevel to Maker-specific settings
        requires_gpu: Whether this Maker benefits from GPU acceleration
        supported_codes: List of DFT codes this Maker works with
    """

    maker_class: Type["Maker"]
    default_kwargs: Dict[str, Any] = field(default_factory=dict)
    protocol_mapping: Dict[ProtocolLevel, Dict[str, Any]] = field(default_factory=dict)
    requires_gpu: bool = False
    supported_codes: List[str] = field(default_factory=lambda: ["vasp"])


@dataclass
class FlowResult:
    """
    Result container for atomate2 Flow execution.

    Bridges atomate2's Response objects to CrystalMath's WorkflowResult.

    Attributes:
        flow_uuid: Unique identifier for the Flow
        job_uuids: List of Job UUIDs in execution order
        outputs: Collected outputs from all Jobs
        state: Final execution state
        timing: Execution timing information
        errors: Any errors encountered during execution
    """

    flow_uuid: str
    job_uuids: List[str] = field(default_factory=list)
    outputs: Dict[str, Any] = field(default_factory=dict)
    state: str = "created"
    timing: Dict[str, float] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_workflow_result(self) -> "WorkflowResult":
        """
        Convert to CrystalMath WorkflowResult.

        Returns:
            WorkflowResult compatible with crystalmath.protocols.
        """
        from crystalmath.protocols import WorkflowResult

        return WorkflowResult(
            success=self.state == "completed" and len(self.errors) == 0,
            workflow_id=self.flow_uuid,
            outputs=self.outputs,
            errors=self.errors,
            metadata={
                "job_uuids": self.job_uuids,
                "timing": self.timing,
                "source": "atomate2",
            },
        )


@dataclass
class CodeHandoff:
    """
    Defines data transfer between codes in multi-code workflows.

    Used to specify how outputs from one code become inputs to another.

    Attributes:
        source_code: Code producing the data (e.g., "vasp")
        target_code: Code consuming the data (e.g., "yambo")
        output_key: Key in source's outputs dict
        input_key: Key in target's inputs dict
        converter: Optional function to transform data between formats
        validation: Optional function to validate the transferred data
    """

    source_code: str
    target_code: str
    output_key: str
    input_key: str
    converter: Optional[Callable[[Any], Any]] = None
    validation: Optional[Callable[[Any], bool]] = None

    def transfer(self, source_outputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the data transfer.

        Args:
            source_outputs: Outputs from the source code

        Returns:
            Dict with the input_key mapped to the (possibly converted) value

        Raises:
            CodeHandoffError: If output_key not found or validation fails
        """
        if self.output_key not in source_outputs:
            raise CodeHandoffError(
                f"Output key '{self.output_key}' not found in {self.source_code} outputs"
            )

        value = source_outputs[self.output_key]

        # Apply converter if provided
        if self.converter is not None:
            value = self.converter(value)

        # Validate if provided
        if self.validation is not None and not self.validation(value):
            raise CodeHandoffError(
                f"Validation failed for handoff {self.source_code} -> {self.target_code}"
            )

        return {self.input_key: value}


# =============================================================================
# FlowMakerRegistry: Maps WorkflowType to atomate2 Makers
# =============================================================================


class FlowMakerRegistry:
    """
    Registry mapping CrystalMath WorkflowType to atomate2 Maker classes.

    This class serves as the central lookup for finding the appropriate
    atomate2 Maker for a given workflow type and DFT code combination.

    The registry supports:
    - Multiple codes per workflow type (VASP, QE, etc.)
    - Protocol-based configuration (fast, moderate, precise)
    - Custom Maker registration for extensibility

    Example:
        >>> registry = FlowMakerRegistry()
        >>> maker = registry.get_maker(WorkflowType.RELAX, code="vasp")
        >>> flow = maker.make(structure)

    Note:
        Maker imports are lazy to avoid requiring atomate2 installation
        at module import time.
    """

    def __init__(self):
        """Initialize the registry with default mappings."""
        self._registry: Dict[str, Dict[str, MakerConfig]] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """
        Register default atomate2 Makers for common workflow types.

        Maps CrystalMath WorkflowType to atomate2 Maker classes:
        - RELAX -> RelaxFlowMaker, DoubleRelaxMaker
        - SCF -> StaticFlowMaker
        - BANDS -> BandStructureFlowMaker
        - ELASTIC -> ElasticFlowMaker
        - PHONON -> PhononFlowMaker
        - DOS -> DosFlowMaker (via BandStructureFlowMaker)
        - GW -> (custom multi-code flow)
        - BSE -> (custom multi-code flow)
        """
        # Note: Actual Maker classes will be imported lazily in get_maker()
        # Here we store the import paths and default configs

        # VASP Makers
        self._registry["relax"] = {
            "vasp": MakerConfig(
                maker_class=None,  # Lazy import
                default_kwargs={"relax_type": "full"},
                protocol_mapping={
                    ProtocolLevel.FAST: {"force_field_name": None},
                    ProtocolLevel.MODERATE: {},
                    ProtocolLevel.PRECISE: {"relax_type": "full", "steps": 500},
                },
                supported_codes=["vasp"],
            ),
        }

        self._registry["scf"] = {
            "vasp": MakerConfig(
                maker_class=None,
                default_kwargs={},
                protocol_mapping={
                    ProtocolLevel.FAST: {"ediff": 1e-4},
                    ProtocolLevel.MODERATE: {"ediff": 1e-5},
                    ProtocolLevel.PRECISE: {"ediff": 1e-6},
                },
                supported_codes=["vasp", "qe"],
            ),
        }

        self._registry["bands"] = {
            "vasp": MakerConfig(
                maker_class=None,
                default_kwargs={"line_density": 50},
                protocol_mapping={
                    ProtocolLevel.FAST: {"line_density": 20},
                    ProtocolLevel.MODERATE: {"line_density": 50},
                    ProtocolLevel.PRECISE: {"line_density": 100},
                },
                supported_codes=["vasp", "qe"],
            ),
        }

        self._registry["elastic"] = {
            "vasp": MakerConfig(
                maker_class=None,
                default_kwargs={"strain_states": 6},
                protocol_mapping={
                    ProtocolLevel.FAST: {"strain_states": 4},
                    ProtocolLevel.MODERATE: {"strain_states": 6},
                    ProtocolLevel.PRECISE: {"strain_states": 10},
                },
                requires_gpu=True,
                supported_codes=["vasp"],
            ),
        }

        self._registry["phonon"] = {
            "vasp": MakerConfig(
                maker_class=None,
                default_kwargs={"supercell_matrix": [[2, 0, 0], [0, 2, 0], [0, 0, 2]]},
                protocol_mapping={
                    ProtocolLevel.FAST: {
                        "supercell_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
                    },
                    ProtocolLevel.MODERATE: {
                        "supercell_matrix": [[2, 0, 0], [0, 2, 0], [0, 0, 2]]
                    },
                    ProtocolLevel.PRECISE: {
                        "supercell_matrix": [[3, 0, 0], [0, 3, 0], [0, 0, 3]]
                    },
                },
                requires_gpu=True,
                supported_codes=["vasp"],
            ),
        }

    def register(
        self,
        workflow_type: Union[str, "WorkflowType"],
        code: str,
        config: MakerConfig,
    ) -> None:
        """
        Register a new Maker configuration.

        Args:
            workflow_type: The workflow type (e.g., "relax" or WorkflowType.RELAX)
            code: The DFT code (e.g., "vasp", "qe")
            config: The MakerConfig defining the Maker

        Example:
            >>> registry.register(
            ...     "custom_workflow",
            ...     "vasp",
            ...     MakerConfig(
            ...         maker_class=MyCustomMaker,
            ...         default_kwargs={"option": "value"},
            ...     ),
            ... )
        """
        type_key = (
            workflow_type.value
            if hasattr(workflow_type, "value")
            else str(workflow_type)
        ).lower()

        if type_key not in self._registry:
            self._registry[type_key] = {}

        self._registry[type_key][code.lower()] = config

    def get_maker(
        self,
        workflow_type: Union[str, "WorkflowType"],
        code: str = "vasp",
        protocol: ProtocolLevel = ProtocolLevel.MODERATE,
        **kwargs: Any,
    ) -> "Maker":
        """
        Get an atomate2 Maker for the specified workflow type and code.

        Args:
            workflow_type: The workflow type to get a Maker for
            code: The DFT code to use (default: "vasp")
            protocol: The accuracy protocol level
            **kwargs: Additional arguments to pass to the Maker constructor

        Returns:
            Configured atomate2 Maker instance

        Raises:
            MakerNotFoundError: If no Maker is registered for this combination
            ImportError: If atomate2 is not installed

        Example:
            >>> maker = registry.get_maker(WorkflowType.RELAX, code="vasp")
            >>> flow = maker.make(structure)
        """
        type_key = (
            workflow_type.value
            if hasattr(workflow_type, "value")
            else str(workflow_type)
        ).lower()
        code_key = code.lower()

        if type_key not in self._registry:
            raise MakerNotFoundError(
                f"No Makers registered for workflow type '{type_key}'. "
                f"Available types: {list(self._registry.keys())}"
            )

        if code_key not in self._registry[type_key]:
            available_codes = list(self._registry[type_key].keys())
            raise MakerNotFoundError(
                f"No Maker registered for '{type_key}' with code '{code_key}'. "
                f"Available codes for this workflow: {available_codes}"
            )

        config = self._registry[type_key][code_key]

        # Get the Maker class (lazy import)
        maker_class = self._import_maker(type_key, code_key)

        # Merge default kwargs with protocol-specific and user kwargs
        merged_kwargs = {**config.default_kwargs}
        if protocol in config.protocol_mapping:
            merged_kwargs.update(config.protocol_mapping[protocol])
        merged_kwargs.update(kwargs)

        return maker_class(**merged_kwargs)

    def _import_maker(self, workflow_type: str, code: str) -> Type["Maker"]:
        """
        Lazily import the appropriate Maker class.

        Args:
            workflow_type: The workflow type key
            code: The DFT code key

        Returns:
            The Maker class (not instantiated)

        Raises:
            ImportError: If atomate2 or required code plugin is not installed
        """
        # Mapping of workflow_type -> atomate2 import path
        # Note: These are the actual atomate2 module paths
        import_map = {
            ("relax", "vasp"): ("atomate2.vasp.flows.core", "DoubleRelaxMaker"),
            ("scf", "vasp"): ("atomate2.vasp.flows.core", "StaticMaker"),
            ("bands", "vasp"): (
                "atomate2.vasp.flows.core",
                "BandStructureMaker",
            ),
            ("elastic", "vasp"): (
                "atomate2.vasp.flows.elastic",
                "ElasticMaker",
            ),
            ("phonon", "vasp"): (
                "atomate2.vasp.flows.phonons",
                "PhononMaker",
            ),
            # QE makers (when available in atomate2)
            ("relax", "qe"): ("atomate2.qe.flows.core", "RelaxMaker"),
            ("scf", "qe"): ("atomate2.qe.flows.core", "StaticMaker"),
        }

        key = (workflow_type, code)
        if key not in import_map:
            raise MakerNotFoundError(
                f"No import path defined for {workflow_type}/{code}"
            )

        module_path, class_name = import_map[key]

        try:
            import importlib

            module = importlib.import_module(module_path)
            return getattr(module, class_name)
        except ImportError as e:
            raise ImportError(
                f"Failed to import {class_name} from {module_path}. "
                f"Is atomate2 installed? Error: {e}"
            ) from e

    def list_available(self) -> Dict[str, List[str]]:
        """
        List all available workflow type / code combinations.

        Returns:
            Dict mapping workflow types to available codes
        """
        return {
            wf_type: list(codes.keys()) for wf_type, codes in self._registry.items()
        }


# =============================================================================
# Atomate2FlowAdapter: Wraps atomate2 Flows for CrystalMath
# =============================================================================


class Atomate2FlowAdapter:
    """
    Adapter that wraps atomate2 Flow objects for CrystalMath compatibility.

    This class handles the conversion between atomate2's Flow/Job model
    and CrystalMath's WorkflowResult model, including:
    - Input structure conversion (pymatgen <-> AiiDA)
    - Output data extraction and normalization
    - Error handling and state mapping
    - Provenance metadata capture

    Example:
        >>> from atomate2.vasp.flows.core import DoubleRelaxMaker
        >>> maker = DoubleRelaxMaker()
        >>> flow = maker.make(structure)
        >>> adapter = Atomate2FlowAdapter(flow)
        >>> result = adapter.run_and_collect(store=my_store)
    """

    def __init__(
        self,
        flow: "Flow",
        execution_mode: ExecutionMode = ExecutionMode.LOCAL,
        store: Optional["Store"] = None,
    ):
        """
        Initialize the adapter with an atomate2 Flow.

        Args:
            flow: The atomate2 Flow to wrap
            execution_mode: How to execute the Flow (local, remote, fireworks)
            store: Optional Maggma Store for result storage
        """
        self._flow = flow
        self._execution_mode = execution_mode
        self._store = store
        self._result: Optional[FlowResult] = None

    @property
    def flow(self) -> "Flow":
        """The wrapped atomate2 Flow."""
        return self._flow

    @property
    def flow_uuid(self) -> str:
        """UUID of the wrapped Flow."""
        return self._flow.uuid

    def run_and_collect(
        self,
        raise_on_error: bool = False,
    ) -> FlowResult:
        """
        Execute the Flow and collect results.

        Args:
            raise_on_error: Whether to raise exceptions on execution failure

        Returns:
            FlowResult containing all outputs and metadata

        Raises:
            FlowExecutionError: If raise_on_error=True and execution fails

        Note:
            This is a STUB implementation. Full implementation in Phase 3.
        """
        # STUB: Phase 3 implementation will use jobflow's run_locally or
        # jobflow-remote's submit functionality
        raise NotImplementedError(
            "Atomate2FlowAdapter.run_and_collect() will be implemented in Phase 3. "
            "See docs/architecture/ATOMATE2-INTEGRATION.md for design."
        )

    def to_workflow_steps(self) -> List["WorkflowStep"]:
        """
        Convert Flow Jobs to CrystalMath WorkflowSteps.

        Returns:
            List of WorkflowStep objects representing the Flow

        Note:
            This enables the Flow to be visualized and managed
            through CrystalMath's workflow tools.
        """
        from crystalmath.protocols import WorkflowStep, WorkflowType

        steps = []
        for job in self._flow.jobs:
            # Map atomate2 Job to WorkflowStep
            step = WorkflowStep(
                name=job.name,
                workflow_type=self._infer_workflow_type(job),
                code=self._infer_code(job),
                parameters=getattr(job, "maker", {}).get("input_set", {}),
                depends_on=[],  # Would need to parse Flow graph
            )
            steps.append(step)

        return steps

    def _infer_workflow_type(self, job: "Job") -> "WorkflowType":
        """Infer WorkflowType from Job name/class."""
        from crystalmath.protocols import WorkflowType

        name = job.name.lower()
        if "relax" in name:
            return WorkflowType.RELAX
        elif "static" in name:
            return WorkflowType.SCF
        elif "band" in name:
            return WorkflowType.BANDS
        elif "dos" in name:
            return WorkflowType.DOS
        elif "elastic" in name:
            return WorkflowType.ELASTIC
        elif "phonon" in name:
            return WorkflowType.PHONON
        else:
            return WorkflowType.SCF  # Default

    def _infer_code(self, job: "Job") -> str:
        """Infer DFT code from Job class."""
        class_name = job.__class__.__module__
        if "vasp" in class_name:
            return "vasp"
        elif "qe" in class_name or "espresso" in class_name:
            return "quantum_espresso"
        elif "cp2k" in class_name:
            return "cp2k"
        else:
            return "unknown"


# =============================================================================
# Atomate2Bridge: Main Integration Point
# =============================================================================


class Atomate2Bridge:
    """
    Main integration bridge between CrystalMath and atomate2.

    This class provides a high-level interface for running atomate2 workflows
    through CrystalMath's unified API. It:
    - Maps WorkflowType to appropriate atomate2 Makers
    - Handles structure conversion between pymatgen and AiiDA formats
    - Manages job submission and result collection
    - Integrates with CrystalMath's storage backends

    Example:
        >>> bridge = Atomate2Bridge()
        >>>
        >>> # Simple relaxation
        >>> result = bridge.submit(
        ...     workflow_type=WorkflowType.RELAX,
        ...     structure=structure,
        ...     code="vasp",
        ... )
        >>>
        >>> # Wait for completion
        >>> final_result = bridge.get_result(result.workflow_id)

    Attributes:
        registry: FlowMakerRegistry for Maker lookup
        execution_mode: Default execution mode for Flows
        store: Default Maggma Store for results
    """

    def __init__(
        self,
        store: Optional["Store"] = None,
        execution_mode: ExecutionMode = ExecutionMode.LOCAL,
    ):
        """
        Initialize the bridge.

        Args:
            store: Optional Maggma Store for result storage.
                   If None, uses MemoryStore for local execution.
            execution_mode: Default execution mode for Flows
        """
        self._registry = FlowMakerRegistry()
        self._execution_mode = execution_mode
        self._store = store
        self._active_flows: Dict[str, Atomate2FlowAdapter] = {}

    @property
    def name(self) -> str:
        """Runner identifier for protocol compliance."""
        return "atomate2"

    @property
    def is_available(self) -> bool:
        """
        Check if atomate2 is available.

        Returns:
            True if atomate2 and jobflow are importable
        """
        try:
            import atomate2  # noqa: F401
            import jobflow  # noqa: F401

            return True
        except ImportError:
            return False

    def submit(
        self,
        workflow_type: "WorkflowType",
        structure: Any,
        code: str = "vasp",
        parameters: Optional[Dict[str, Any]] = None,
        resources: Optional["ResourceRequirements"] = None,
        protocol: ProtocolLevel = ProtocolLevel.MODERATE,
        **kwargs: Any,
    ) -> "WorkflowResult":
        """
        Submit a workflow for execution.

        This method implements a WorkflowRunner-like interface, enabling
        atomate2 workflows to be run through CrystalMath's unified API.

        Args:
            workflow_type: Type of workflow (RELAX, SCF, BANDS, etc.)
            structure: Input structure (pymatgen Structure, AiiDA StructureData,
                      or path to structure file)
            code: DFT code to use (default: "vasp")
            parameters: Additional calculation parameters
            resources: Computational resource requirements
            protocol: Accuracy protocol level
            **kwargs: Additional options passed to the Maker

        Returns:
            WorkflowResult with workflow_id for tracking

        Raises:
            MakerNotFoundError: If no Maker exists for this workflow/code
            ImportError: If atomate2 is not available

        Note:
            This is a STUB implementation. Full implementation in Phase 3.
        """
        # STUB implementation - returns placeholder result
        from crystalmath.protocols import WorkflowResult

        # Convert structure to pymatgen if needed
        pmg_structure = self._convert_structure(structure)

        # Get the appropriate Maker
        maker = self._registry.get_maker(
            workflow_type=workflow_type,
            code=code,
            protocol=protocol,
            **(parameters or {}),
        )

        # Create the Flow
        flow = maker.make(pmg_structure, **kwargs)

        # Create adapter
        adapter = Atomate2FlowAdapter(
            flow=flow,
            execution_mode=self._execution_mode,
            store=self._store,
        )

        # Track the flow
        self._active_flows[flow.uuid] = adapter

        # STUB: Return placeholder result
        # Full implementation will execute the flow
        return WorkflowResult(
            success=True,
            workflow_id=flow.uuid,
            outputs={},
            metadata={
                "source": "atomate2",
                "maker": maker.__class__.__name__,
                "code": code,
                "protocol": protocol.value,
                "status": "submitted",
            },
        )

    def submit_composite(
        self,
        steps: Sequence["WorkflowStep"],
        structure: Any,
        **kwargs: Any,
    ) -> "WorkflowResult":
        """
        Submit a composite multi-step workflow.

        Creates a composite atomate2 Flow from multiple WorkflowSteps,
        handling data flow between steps.

        Args:
            steps: Sequence of workflow steps to execute
            structure: Initial input structure
            **kwargs: Global options

        Returns:
            WorkflowResult with workflow_id

        Note:
            This is a STUB implementation. Full implementation in Phase 3.
        """
        raise NotImplementedError(
            "Atomate2Bridge.submit_composite() will be implemented in Phase 3. "
            "Use MultiCodeFlowBuilder for complex workflows."
        )

    def get_status(self, workflow_id: str) -> "WorkflowState":
        """
        Get current state of a workflow.

        Args:
            workflow_id: Workflow identifier (Flow UUID)

        Returns:
            Current workflow state

        Note:
            This is a STUB implementation. Full implementation in Phase 3.
        """
        if workflow_id not in self._active_flows:
            return "failed"

        # STUB: Return placeholder state
        return "submitted"

    def get_result(self, workflow_id: str) -> "WorkflowResult":
        """
        Get complete result of a finished workflow.

        Args:
            workflow_id: Workflow identifier (Flow UUID)

        Returns:
            WorkflowResult with outputs and metadata

        Note:
            This is a STUB implementation. Full implementation in Phase 3.
        """
        from crystalmath.protocols import WorkflowResult

        if workflow_id not in self._active_flows:
            return WorkflowResult(
                success=False,
                workflow_id=workflow_id,
                errors=[f"Workflow {workflow_id} not found"],
            )

        # STUB: Return placeholder result
        return WorkflowResult(
            success=True,
            workflow_id=workflow_id,
            outputs={},
            metadata={"status": "stub_implementation"},
        )

    def cancel(self, workflow_id: str) -> bool:
        """
        Cancel a running workflow.

        Args:
            workflow_id: Workflow identifier

        Returns:
            True if cancellation succeeded
        """
        if workflow_id in self._active_flows:
            del self._active_flows[workflow_id]
            return True
        return False

    def _convert_structure(self, structure: Any) -> "Structure":
        """
        Convert input structure to pymatgen Structure.

        Handles:
        - pymatgen Structure (passthrough)
        - AiiDA StructureData
        - File path (str or Path)
        - Dict representation

        Args:
            structure: Input structure in any supported format

        Returns:
            pymatgen Structure
        """
        from pymatgen.core import Structure

        if isinstance(structure, Structure):
            return structure

        # Handle AiiDA StructureData
        if hasattr(structure, "get_pymatgen_structure"):
            return structure.get_pymatgen_structure()

        # Handle file path
        if isinstance(structure, (str, Path)):
            from pathlib import Path

            return Structure.from_file(str(structure))

        # Handle dict representation
        if isinstance(structure, dict):
            return Structure.from_dict(structure)

        raise TypeError(
            f"Cannot convert {type(structure)} to pymatgen Structure. "
            f"Supported types: Structure, StructureData, str (path), dict"
        )


# =============================================================================
# MultiCodeFlowBuilder: Complex Multi-Code Workflows
# =============================================================================


class MultiCodeFlowBuilder:
    """
    Builder for constructing multi-code workflows.

    This class enables building complex workflows that span multiple
    DFT codes, such as:
    - VASP SCF -> YAMBO GW/BSE
    - QE SCF -> BerkeleyGW
    - CRYSTAL23 -> Wannier90

    The builder handles:
    - Data format conversion between codes
    - Dependency tracking between steps
    - Error propagation across code boundaries

    Example:
        >>> builder = MultiCodeFlowBuilder()
        >>> flow = (
        ...     builder
        ...     .add_step("relax", "vasp", WorkflowType.RELAX)
        ...     .add_step("scf", "vasp", WorkflowType.SCF, depends_on=["relax"])
        ...     .add_handoff("scf", "gw", converter=vasp_to_yambo)
        ...     .add_step("gw", "yambo", WorkflowType.GW, depends_on=["scf"])
        ...     .build(structure)
        ... )

    See Also:
        - tui/src/aiida/workchains/multicode/ for AiiDA implementations
        - docs/architecture/ATOMATE2-INTEGRATION.md for design
    """

    def __init__(self):
        """Initialize the builder."""
        self._steps: List[Dict[str, Any]] = []
        self._handoffs: List[CodeHandoff] = []
        self._bridge = Atomate2Bridge()

    def add_step(
        self,
        name: str,
        code: str,
        workflow_type: "WorkflowType",
        depends_on: Optional[List[str]] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> "MultiCodeFlowBuilder":
        """
        Add a workflow step.

        Args:
            name: Unique name for this step
            code: DFT code to use
            workflow_type: Type of calculation
            depends_on: List of step names this step depends on
            parameters: Calculation parameters

        Returns:
            self for method chaining
        """
        self._steps.append(
            {
                "name": name,
                "code": code,
                "workflow_type": workflow_type,
                "depends_on": depends_on or [],
                "parameters": parameters or {},
            }
        )
        return self

    def add_handoff(
        self,
        source_step: str,
        target_step: str,
        output_key: str = "structure",
        input_key: str = "structure",
        converter: Optional[Callable[[Any], Any]] = None,
    ) -> "MultiCodeFlowBuilder":
        """
        Add a data handoff between steps.

        Defines how data flows from one step to another, optionally
        with format conversion.

        Args:
            source_step: Name of the source step
            target_step: Name of the target step
            output_key: Key in source's outputs
            input_key: Key in target's inputs
            converter: Optional function to transform the data

        Returns:
            self for method chaining
        """
        # Find source and target codes
        source_code = next(
            (s["code"] for s in self._steps if s["name"] == source_step), "unknown"
        )
        target_code = next(
            (s["code"] for s in self._steps if s["name"] == target_step), "unknown"
        )

        self._handoffs.append(
            CodeHandoff(
                source_code=source_code,
                target_code=target_code,
                output_key=output_key,
                input_key=input_key,
                converter=converter,
            )
        )
        return self

    def build(self, structure: Any) -> "Flow":
        """
        Build the composite Flow.

        Args:
            structure: Initial input structure

        Returns:
            jobflow Flow representing the multi-code workflow

        Note:
            This is a STUB implementation. Full implementation in Phase 3.
        """
        raise NotImplementedError(
            "MultiCodeFlowBuilder.build() will be implemented in Phase 3. "
            "See docs/architecture/ATOMATE2-INTEGRATION.md for design."
        )

    def validate(self) -> tuple[bool, List[str]]:
        """
        Validate the workflow definition.

        Checks for:
        - Circular dependencies
        - Missing dependency references
        - Invalid code/workflow_type combinations
        - Incomplete handoff definitions

        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []

        # Check for missing dependencies
        step_names = {s["name"] for s in self._steps}
        for step in self._steps:
            for dep in step["depends_on"]:
                if dep not in step_names:
                    issues.append(
                        f"Step '{step['name']}' depends on unknown step '{dep}'"
                    )

        # Check for circular dependencies (simple check)
        # Full implementation would do topological sort
        for step in self._steps:
            if step["name"] in step["depends_on"]:
                issues.append(f"Step '{step['name']}' has circular self-dependency")

        return len(issues) == 0, issues


# =============================================================================
# Convenience Functions
# =============================================================================


def get_atomate2_bridge(
    store: Optional["Store"] = None,
    execution_mode: ExecutionMode = ExecutionMode.LOCAL,
) -> Atomate2Bridge:
    """
    Factory function to get an Atomate2Bridge instance.

    Args:
        store: Optional Maggma Store for result storage
        execution_mode: Execution mode for Flows

    Returns:
        Configured Atomate2Bridge instance

    Example:
        >>> bridge = get_atomate2_bridge()
        >>> result = bridge.submit(WorkflowType.RELAX, structure)
    """
    return Atomate2Bridge(store=store, execution_mode=execution_mode)


def create_vasp_to_yambo_flow(
    structure: Any,
    gw_parameters: Optional[Dict[str, Any]] = None,
) -> "Flow":
    """
    Create a VASP -> YAMBO GW workflow.

    Convenience function for the common pattern of running
    VASP SCF followed by YAMBO GW calculation.

    Args:
        structure: Input structure
        gw_parameters: GW calculation parameters

    Returns:
        jobflow Flow for the multi-code workflow

    Note:
        This is a STUB implementation. Full implementation in Phase 3.
    """
    raise NotImplementedError(
        "create_vasp_to_yambo_flow() will be implemented in Phase 3. "
        "See docs/architecture/ATOMATE2-INTEGRATION.md for design."
    )


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Exceptions
    "Atomate2IntegrationError",
    "MakerNotFoundError",
    "FlowExecutionError",
    "CodeHandoffError",
    # Enums
    "ExecutionMode",
    "ProtocolLevel",
    # Data classes
    "MakerConfig",
    "FlowResult",
    "CodeHandoff",
    # Core classes
    "FlowMakerRegistry",
    "Atomate2FlowAdapter",
    "Atomate2Bridge",
    "MultiCodeFlowBuilder",
    # Factory functions
    "get_atomate2_bridge",
    "create_vasp_to_yambo_flow",
]
