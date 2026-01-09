"""
Python Workflow Definition (PWD) Bridge for CrystalMath.

This module provides adapters for converting between CrystalMath's WorkflowStep
format and the PWD (Python Workflow Definition) exchange format. PWD enables
interoperability with other workflow engines including AiiDA, jobflow, and pyiron.

PWD Format Overview:
--------------------
PWD is a machine-readable workflow exchange format consisting of:
- workflow.json: Node and edge definitions
- workflow.py: Python module with function implementations
- environment.yml: Conda environment specification

The JSON structure uses:
- Nodes: Represent functions, inputs, or outputs
- Edges: Define data flow between nodes via source/target ports

Key Classes:
------------
- `PWDConverter`: Main class for bidirectional conversion
- `PWDNode`: Represents a node in the PWD graph
- `PWDEdge`: Represents an edge connecting nodes

Usage:
------
>>> from crystalmath.integrations import PWDConverter
>>> from crystalmath.protocols import WorkflowStep, WorkflowType
>>>
>>> # Create workflow steps
>>> steps = [
...     WorkflowStep(
...         name="relax",
...         workflow_type=WorkflowType.RELAX,
...         code="vasp",
...         parameters={"force_convergence": 0.01},
...     ),
...     WorkflowStep(
...         name="scf",
...         workflow_type=WorkflowType.SCF,
...         code="vasp",
...         depends_on=["relax"],
...     ),
... ]
>>>
>>> # Convert to PWD format
>>> converter = PWDConverter()
>>> pwd_json = converter.to_pwd(steps)
>>>
>>> # Save as PWD files
>>> converter.save_pwd(steps, Path("./output"), "my_workflow")
>>>
>>> # Load from PWD directory
>>> loaded_steps = converter.load_pwd(Path("./my_pwd_workflow"))

See Also:
---------
- PWD specification: https://github.com/pythonworkflow/python-workflow-definition
- CrystalMath protocols: `crystalmath.protocols`
- atomate2 bridge: `crystalmath.integrations.atomate2_bridge`
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    Union,
)

if TYPE_CHECKING:
    from crystalmath.protocols import (
        DFTCode,
        ErrorRecoveryStrategy,
        ResourceRequirements,
        WorkflowStep,
        WorkflowType,
    )

# Package version for extensions
__version__ = "1.0.0"


# =============================================================================
# Exceptions
# =============================================================================


class PWDConversionError(Exception):
    """Base exception for PWD conversion errors."""

    pass


class PWDValidationError(PWDConversionError):
    """Raised when PWD JSON fails validation."""

    pass


class PWDImportError(PWDConversionError):
    """Raised when loading PWD files fails."""

    pass


# =============================================================================
# Data Classes for PWD Format
# =============================================================================


@dataclass
class PWDNode:
    """
    Represents a node in the PWD workflow graph.

    Nodes can be one of three types:
    - input: Provides initial values to the workflow
    - function: Executes a calculation step
    - output: Collects results from the workflow

    Attributes:
        id: Unique identifier (string or int)
        type: Node type ("input", "function", or "output")
        value: For functions, the module.function path; for inputs, the default value
        name: For inputs/outputs, the parameter name

    Example:
        >>> # Function node
        >>> func_node = PWDNode(
        ...     id="func_1",
        ...     type="function",
        ...     value="crystalmath.workflows.relax",
        ... )
        >>> # Input node
        >>> input_node = PWDNode(
        ...     id="input_1",
        ...     type="input",
        ...     value={"structure": {...}},
        ...     name="structure",
        ... )
    """

    id: Union[str, int]
    type: Literal["input", "function", "output"]
    value: Any = None
    name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to PWD JSON format."""
        result: Dict[str, Any] = {
            "id": self.id,
            "type": self.type,
        }
        if self.value is not None:
            result["value"] = self.value
        if self.name is not None:
            result["name"] = self.name
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PWDNode":
        """Create from PWD JSON dict."""
        return cls(
            id=data["id"],
            type=data["type"],
            value=data.get("value"),
            name=data.get("name"),
        )


@dataclass
class PWDEdge:
    """
    Represents an edge connecting two nodes in the PWD graph.

    Edges define data flow from a source node (or specific output port)
    to a target node (or specific input port).

    Attributes:
        source: ID of the source node
        source_port: Output port name (None for single-output nodes)
        target: ID of the target node
        target_port: Input port name (None for single-input nodes)

    Example:
        >>> edge = PWDEdge(
        ...     source="relax_func",
        ...     source_port="structure",
        ...     target="scf_func",
        ...     target_port="structure",
        ... )
    """

    source: Union[str, int]
    source_port: Optional[str] = None
    target: Union[str, int] = ""
    target_port: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to PWD JSON format."""
        return {
            "source": self.source,
            "sourcePort": self.source_port,
            "target": self.target,
            "targetPort": self.target_port,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PWDEdge":
        """Create from PWD JSON dict."""
        return cls(
            source=data["source"],
            source_port=data.get("sourcePort"),
            target=data["target"],
            target_port=data.get("targetPort"),
        )


@dataclass
class CrystalMathExtensions:
    """
    CrystalMath-specific extensions for PWD workflows.

    These extensions capture information that is not part of the
    standard PWD format but is needed for CrystalMath workflows:
    - Resource requirements (nodes, GPUs, walltime)
    - Error recovery strategies
    - Protocol levels for accuracy settings

    Attributes:
        resources: Computational resource requirements
        error_recovery: Error handling strategy
        protocol_level: Accuracy protocol (fast, moderate, precise)
        code: DFT code for this step
        workflow_type: CrystalMath workflow type

    Example:
        >>> ext = CrystalMathExtensions(
        ...     resources={"num_nodes": 2, "gpus": 4, "walltime_hours": 8},
        ...     error_recovery="adaptive",
        ...     protocol_level="moderate",
        ... )
    """

    resources: Optional[Dict[str, Any]] = None
    error_recovery: Optional[str] = None
    protocol_level: Optional[str] = None
    code: Optional[str] = None
    workflow_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        result: Dict[str, Any] = {}
        if self.resources is not None:
            result["resources"] = self.resources
        if self.error_recovery is not None:
            result["error_recovery"] = self.error_recovery
        if self.protocol_level is not None:
            result["protocol_level"] = self.protocol_level
        if self.code is not None:
            result["code"] = self.code
        if self.workflow_type is not None:
            result["workflow_type"] = self.workflow_type
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CrystalMathExtensions":
        """Create from JSON dict."""
        return cls(
            resources=data.get("resources"),
            error_recovery=data.get("error_recovery"),
            protocol_level=data.get("protocol_level"),
            code=data.get("code"),
            workflow_type=data.get("workflow_type"),
        )


# =============================================================================
# PWDConverter: Main Conversion Class
# =============================================================================


class PWDConverter:
    """
    Convert between CrystalMath workflows and PWD format.

    This class provides bidirectional conversion enabling workflow
    exchange with other Python workflow engines (AiiDA, jobflow, pyiron).

    The converter handles:
    - WorkflowStep -> PWD nodes/edges
    - PWD JSON -> WorkflowStep list
    - CrystalMath extensions (resources, error recovery)
    - File I/O for PWD directories

    Example:
        >>> converter = PWDConverter()
        >>>
        >>> # Export workflow to PWD
        >>> pwd_json = converter.to_pwd(steps)
        >>> print(json.dumps(pwd_json, indent=2))
        >>>
        >>> # Export with extensions
        >>> pwd_json, extensions = converter.to_pwd_with_extensions(steps)
        >>>
        >>> # Save complete PWD package
        >>> converter.save_pwd(steps, Path("./output"), "relaxation_workflow")
        >>>
        >>> # Load from PWD directory
        >>> loaded_steps = converter.load_pwd(Path("./relaxation_workflow"))

    Attributes:
        function_prefix: Prefix for generated function paths
        include_inputs: Whether to generate input nodes
        include_outputs: Whether to generate output nodes
    """

    def __init__(
        self,
        function_prefix: str = "crystalmath.workflows",
        include_inputs: bool = True,
        include_outputs: bool = True,
    ):
        """
        Initialize the converter.

        Args:
            function_prefix: Module prefix for function node values
            include_inputs: Whether to create input nodes for workflow inputs
            include_outputs: Whether to create output nodes for workflow outputs
        """
        self._function_prefix = function_prefix
        self._include_inputs = include_inputs
        self._include_outputs = include_outputs

    def to_pwd(self, steps: Sequence["WorkflowStep"]) -> Dict[str, Any]:
        """
        Export WorkflowSteps to PWD JSON format.

        Converts a sequence of CrystalMath WorkflowSteps to the PWD
        graph format with nodes and edges.

        Args:
            steps: Sequence of WorkflowStep objects to convert

        Returns:
            PWD JSON dict with "nodes" and "edges" keys

        Raises:
            PWDConversionError: If conversion fails

        Example:
            >>> from crystalmath.protocols import WorkflowStep, WorkflowType
            >>> steps = [
            ...     WorkflowStep(
            ...         name="relax",
            ...         workflow_type=WorkflowType.RELAX,
            ...         code="vasp",
            ...     ),
            ...     WorkflowStep(
            ...         name="bands",
            ...         workflow_type=WorkflowType.BANDS,
            ...         code="vasp",
            ...         depends_on=["relax"],
            ...     ),
            ... ]
            >>> converter = PWDConverter()
            >>> pwd = converter.to_pwd(steps)
            >>> print(pwd["nodes"])  # List of node dicts
            >>> print(pwd["edges"])  # List of edge dicts
        """
        nodes: List[PWDNode] = []
        edges: List[PWDEdge] = []
        step_to_node_id: Dict[str, str] = {}

        # Create input node for structure if enabled
        if self._include_inputs:
            input_node = PWDNode(
                id="input_structure",
                type="input",
                value={},  # Placeholder for structure data
                name="structure",
            )
            nodes.append(input_node)

        # Create function nodes for each step
        for step in steps:
            node_id = f"func_{step.name}"
            step_to_node_id[step.name] = node_id

            # Construct function path
            function_path = self._get_function_path(step)

            func_node = PWDNode(
                id=node_id,
                type="function",
                value=function_path,
                name=step.name,
            )
            nodes.append(func_node)

        # Create edges based on dependencies
        for step in steps:
            node_id = step_to_node_id[step.name]

            if step.depends_on:
                # Create edges from dependencies
                for dep_name in step.depends_on:
                    if dep_name in step_to_node_id:
                        dep_node_id = step_to_node_id[dep_name]
                        edge = PWDEdge(
                            source=dep_node_id,
                            source_port="structure",  # Default output
                            target=node_id,
                            target_port="structure",  # Default input
                        )
                        edges.append(edge)
            else:
                # First step(s) connect to input node
                if self._include_inputs:
                    edge = PWDEdge(
                        source="input_structure",
                        source_port=None,
                        target=node_id,
                        target_port="structure",
                    )
                    edges.append(edge)

        # Create output node for final results if enabled
        if self._include_outputs:
            output_node = PWDNode(
                id="output_result",
                type="output",
                name="result",
            )
            nodes.append(output_node)

            # Connect leaf nodes (no dependents) to output
            leaf_steps = self._find_leaf_steps(steps)
            for leaf_step in leaf_steps:
                leaf_node_id = step_to_node_id[leaf_step.name]
                edge = PWDEdge(
                    source=leaf_node_id,
                    source_port="result",
                    target="output_result",
                    target_port=None,
                )
                edges.append(edge)

        return {
            "nodes": [node.to_dict() for node in nodes],
            "edges": [edge.to_dict() for edge in edges],
        }

    def from_pwd(self, pwd_json: Dict[str, Any]) -> List["WorkflowStep"]:
        """
        Import PWD JSON to WorkflowSteps.

        Parses a PWD graph definition and converts it to a list of
        CrystalMath WorkflowSteps.

        Args:
            pwd_json: PWD JSON dict with "nodes" and "edges" keys

        Returns:
            List of WorkflowStep objects

        Raises:
            PWDValidationError: If PWD JSON is invalid
            PWDImportError: If import fails

        Example:
            >>> pwd_json = {
            ...     "nodes": [
            ...         {"id": "func_1", "type": "function", "value": "crystalmath.workflows.relax"},
            ...         {"id": "func_2", "type": "function", "value": "crystalmath.workflows.scf"},
            ...     ],
            ...     "edges": [
            ...         {"source": "func_1", "sourcePort": None, "target": "func_2", "targetPort": "structure"}
            ...     ],
            ... }
            >>> converter = PWDConverter()
            >>> steps = converter.from_pwd(pwd_json)
            >>> print([s.name for s in steps])
        """
        from crystalmath.protocols import WorkflowStep, WorkflowType

        self._validate_pwd_json(pwd_json)

        nodes = [PWDNode.from_dict(n) for n in pwd_json.get("nodes", [])]
        edges = [PWDEdge.from_dict(e) for e in pwd_json.get("edges", [])]

        # Filter to function nodes only
        function_nodes = [n for n in nodes if n.type == "function"]

        # Build dependency map from edges
        dependency_map: Dict[Union[str, int], List[str]] = {}
        for edge in edges:
            target_id = edge.target
            source_id = edge.source

            # Skip edges from input nodes to function nodes
            source_node = next((n for n in nodes if n.id == source_id), None)
            if source_node and source_node.type == "input":
                continue

            if target_id not in dependency_map:
                dependency_map[target_id] = []

            # Get source node name
            source_func_node = next(
                (n for n in function_nodes if n.id == source_id), None
            )
            if source_func_node:
                dep_name = source_func_node.name or self._extract_name_from_value(
                    source_func_node.value
                )
                dependency_map[target_id].append(dep_name)

        # Convert function nodes to WorkflowSteps
        steps: List[WorkflowStep] = []
        for node in function_nodes:
            name = node.name or self._extract_name_from_value(node.value)
            workflow_type, code = self._parse_function_path(node.value)

            depends_on = dependency_map.get(node.id, [])

            step = WorkflowStep(
                name=name,
                workflow_type=workflow_type,
                code=code,
                parameters={},
                depends_on=depends_on,
            )
            steps.append(step)

        return steps

    def to_pwd_with_extensions(
        self, steps: Sequence["WorkflowStep"]
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Export with CrystalMath extensions in separate dict.

        Generates both the standard PWD JSON and a separate extensions
        JSON containing CrystalMath-specific information (resources,
        error recovery, protocol levels).

        Args:
            steps: Sequence of WorkflowStep objects

        Returns:
            Tuple of (pwd_json, extensions_json) where:
            - pwd_json: Standard PWD format
            - extensions_json: CrystalMath extensions

        Example:
            >>> from crystalmath.protocols import WorkflowStep, WorkflowType, ResourceRequirements
            >>> steps = [
            ...     WorkflowStep(
            ...         name="relax",
            ...         workflow_type=WorkflowType.RELAX,
            ...         code="vasp",
            ...         resources=ResourceRequirements(num_nodes=2, gpus=4),
            ...     ),
            ... ]
            >>> converter = PWDConverter()
            >>> pwd_json, extensions = converter.to_pwd_with_extensions(steps)
            >>> print(extensions)
            # {
            #     "crystalmath_version": "1.0.0",
            #     "extensions": {
            #         "func_relax": {
            #             "resources": {"num_nodes": 2, "gpus": 4, ...},
            #             "code": "vasp",
            #             "workflow_type": "relax"
            #         }
            #     }
            # }
        """
        pwd_json = self.to_pwd(steps)

        extensions: Dict[str, Dict[str, Any]] = {}

        for step in steps:
            node_id = f"func_{step.name}"
            step_ext = CrystalMathExtensions(
                code=step.code,
                workflow_type=step.workflow_type.value
                if hasattr(step.workflow_type, "value")
                else str(step.workflow_type),
            )

            # Add resource requirements if present
            if step.resources is not None:
                step_ext.resources = {
                    "num_nodes": step.resources.num_nodes,
                    "num_mpi_ranks": step.resources.num_mpi_ranks,
                    "num_threads_per_rank": step.resources.num_threads_per_rank,
                    "memory_gb": step.resources.memory_gb,
                    "walltime_hours": step.resources.walltime_hours,
                    "gpus": step.resources.gpus,
                }
                if step.resources.partition:
                    step_ext.resources["partition"] = step.resources.partition
                if step.resources.account:
                    step_ext.resources["account"] = step.resources.account

            # Extract protocol level from parameters if present
            protocol = step.parameters.get("protocol")
            if protocol:
                step_ext.protocol_level = protocol

            # Extract error recovery if present
            error_recovery = step.parameters.get("error_recovery")
            if error_recovery:
                step_ext.error_recovery = (
                    error_recovery.value
                    if hasattr(error_recovery, "value")
                    else str(error_recovery)
                )

            extensions[node_id] = step_ext.to_dict()

        extensions_json = {
            "crystalmath_version": __version__,
            "extensions": extensions,
        }

        return pwd_json, extensions_json

    def save_pwd(
        self,
        steps: Sequence["WorkflowStep"],
        output_dir: Path,
        name: str,
    ) -> None:
        """
        Save workflow as PWD files.

        Creates a PWD package directory containing:
        - workflow.json: Node and edge definitions
        - workflow.py: Python module with function stubs
        - environment.yml: Conda environment specification
        - extensions.json: CrystalMath-specific extensions

        Args:
            steps: Sequence of WorkflowStep objects
            output_dir: Directory to create the PWD package in
            name: Name for the workflow (used for directory name)

        Raises:
            OSError: If directory creation or file writing fails

        Example:
            >>> converter = PWDConverter()
            >>> converter.save_pwd(steps, Path("./workflows"), "my_relaxation")
            # Creates: ./workflows/my_relaxation/
            #   - workflow.json
            #   - workflow.py
            #   - environment.yml
            #   - extensions.json
        """
        # Create output directory
        pwd_dir = Path(output_dir) / name
        pwd_dir.mkdir(parents=True, exist_ok=True)

        # Generate PWD JSON and extensions
        pwd_json, extensions_json = self.to_pwd_with_extensions(steps)

        # Write workflow.json
        workflow_json_path = pwd_dir / "workflow.json"
        with open(workflow_json_path, "w") as f:
            json.dump(pwd_json, f, indent=2)

        # Write extensions.json
        extensions_path = pwd_dir / "extensions.json"
        with open(extensions_path, "w") as f:
            json.dump(extensions_json, f, indent=2)

        # Generate and write workflow.py
        workflow_py = self._generate_workflow_py(steps)
        workflow_py_path = pwd_dir / "workflow.py"
        with open(workflow_py_path, "w") as f:
            f.write(workflow_py)

        # Generate and write environment.yml
        environment_yml = self._generate_environment_yml(steps)
        environment_yml_path = pwd_dir / "environment.yml"
        with open(environment_yml_path, "w") as f:
            f.write(environment_yml)

    def load_pwd(self, pwd_dir: Path) -> List["WorkflowStep"]:
        """
        Load workflow from PWD directory.

        Reads a PWD package and converts it to CrystalMath WorkflowSteps,
        including any CrystalMath extensions if present.

        Args:
            pwd_dir: Path to PWD package directory

        Returns:
            List of WorkflowStep objects

        Raises:
            PWDImportError: If required files are missing or invalid

        Example:
            >>> converter = PWDConverter()
            >>> steps = converter.load_pwd(Path("./my_workflow"))
            >>> for step in steps:
            ...     print(f"{step.name}: {step.workflow_type}")
        """
        from crystalmath.protocols import ResourceRequirements, WorkflowStep

        pwd_dir = Path(pwd_dir)

        # Read workflow.json
        workflow_json_path = pwd_dir / "workflow.json"
        if not workflow_json_path.exists():
            raise PWDImportError(f"Missing workflow.json in {pwd_dir}")

        with open(workflow_json_path) as f:
            pwd_json = json.load(f)

        # Load base workflow steps
        steps = self.from_pwd(pwd_json)

        # Read extensions.json if present
        extensions_path = pwd_dir / "extensions.json"
        if extensions_path.exists():
            with open(extensions_path) as f:
                extensions_json = json.load(f)

            # Apply extensions to steps
            extensions = extensions_json.get("extensions", {})
            for step in steps:
                node_id = f"func_{step.name}"
                if node_id in extensions:
                    ext = CrystalMathExtensions.from_dict(extensions[node_id])

                    # Apply resources
                    if ext.resources:
                        step.resources = ResourceRequirements(
                            num_nodes=ext.resources.get("num_nodes", 1),
                            num_mpi_ranks=ext.resources.get("num_mpi_ranks", 1),
                            num_threads_per_rank=ext.resources.get(
                                "num_threads_per_rank", 1
                            ),
                            memory_gb=ext.resources.get("memory_gb", 4.0),
                            walltime_hours=ext.resources.get("walltime_hours", 24.0),
                            gpus=ext.resources.get("gpus", 0),
                            partition=ext.resources.get("partition"),
                            account=ext.resources.get("account"),
                        )

                    # Apply protocol to parameters
                    if ext.protocol_level:
                        step.parameters["protocol"] = ext.protocol_level

                    # Apply error recovery to parameters
                    if ext.error_recovery:
                        step.parameters["error_recovery"] = ext.error_recovery

        return steps

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_function_path(self, step: "WorkflowStep") -> str:
        """Generate function path for a workflow step."""
        workflow_type = (
            step.workflow_type.value
            if hasattr(step.workflow_type, "value")
            else str(step.workflow_type)
        )
        return f"{self._function_prefix}.{workflow_type}"

    def _find_leaf_steps(
        self, steps: Sequence["WorkflowStep"]
    ) -> List["WorkflowStep"]:
        """Find steps that have no dependents (leaf nodes)."""
        all_names = {step.name for step in steps}
        depended_on: set[str] = set()
        for step in steps:
            for dep in step.depends_on:
                if dep in all_names:
                    depended_on.add(dep)

        return [step for step in steps if step.name not in depended_on]

    def _validate_pwd_json(self, pwd_json: Dict[str, Any]) -> None:
        """Validate PWD JSON structure."""
        if not isinstance(pwd_json, dict):
            raise PWDValidationError("PWD JSON must be a dictionary")

        if "nodes" not in pwd_json:
            raise PWDValidationError("PWD JSON missing 'nodes' key")

        if "edges" not in pwd_json:
            raise PWDValidationError("PWD JSON missing 'edges' key")

        for node in pwd_json["nodes"]:
            if "id" not in node:
                raise PWDValidationError("Node missing 'id' field")
            if "type" not in node:
                raise PWDValidationError(f"Node {node.get('id')} missing 'type' field")
            if node["type"] not in ("input", "function", "output"):
                raise PWDValidationError(
                    f"Node {node['id']} has invalid type: {node['type']}"
                )

        for edge in pwd_json["edges"]:
            if "source" not in edge:
                raise PWDValidationError("Edge missing 'source' field")
            if "target" not in edge:
                raise PWDValidationError("Edge missing 'target' field")

    def _extract_name_from_value(self, value: Optional[str]) -> str:
        """Extract step name from function path value."""
        if not value:
            return "unknown"
        # Get last component of module path
        parts = value.split(".")
        return parts[-1] if parts else "unknown"

    def _parse_function_path(
        self, value: Optional[str]
    ) -> Tuple["WorkflowType", "DFTCode"]:
        """Parse workflow type and code from function path."""
        from crystalmath.protocols import WorkflowType

        if not value:
            return WorkflowType.SCF, "crystal23"

        # Extract last component as workflow type
        parts = value.split(".")
        type_str = parts[-1] if parts else "scf"

        # Try to match to WorkflowType enum
        try:
            workflow_type = WorkflowType(type_str.lower())
        except ValueError:
            workflow_type = WorkflowType.SCF

        # Default code (could be enhanced to parse from path)
        code: DFTCode = "crystal23"

        return workflow_type, code

    def _generate_workflow_py(self, steps: Sequence["WorkflowStep"]) -> str:
        """Generate Python module with workflow function stubs."""
        lines = [
            '"""',
            "Auto-generated workflow module for PWD compatibility.",
            "",
            "This module contains function stubs for CrystalMath workflow steps.",
            "These functions are placeholders; actual execution uses CrystalMath's",
            "workflow runners.",
            '"""',
            "",
            "from typing import Any, Dict",
            "",
            "",
        ]

        for step in steps:
            workflow_type = (
                step.workflow_type.value
                if hasattr(step.workflow_type, "value")
                else str(step.workflow_type)
            )
            func_name = workflow_type

            lines.append(f"def {func_name}(structure: Any, **kwargs: Any) -> Dict[str, Any]:")
            lines.append(f'    """')
            lines.append(f"    {step.name.capitalize()} calculation step.")
            lines.append(f"    ")
            lines.append(f"    Args:")
            lines.append(f"        structure: Input crystal structure")
            lines.append(f"        **kwargs: Additional calculation parameters")
            lines.append(f"    ")
            lines.append(f"    Returns:")
            lines.append(f"        Dict with calculation results")
            lines.append(f'    """')
            lines.append(f'    raise NotImplementedError("Use CrystalMath workflow runners")')
            lines.append("")
            lines.append("")

        return "\n".join(lines)

    def _generate_environment_yml(self, steps: Sequence["WorkflowStep"]) -> str:
        """Generate conda environment specification."""
        # Collect unique codes to determine dependencies
        codes = {step.code for step in steps}

        lines = [
            "# Auto-generated conda environment for CrystalMath PWD workflow",
            "name: crystalmath_workflow",
            "channels:",
            "  - conda-forge",
            "  - defaults",
            "dependencies:",
            "  - python>=3.10",
            "  - numpy",
            "  - pymatgen",
        ]

        # Add code-specific dependencies
        if "vasp" in codes:
            lines.append("  - pip:")
            lines.append("    - crystalmath[vasp]")
        elif "quantum_espresso" in codes:
            lines.append("  - pip:")
            lines.append("    - crystalmath[qe]")
        else:
            lines.append("  - pip:")
            lines.append("    - crystalmath")

        return "\n".join(lines)


# =============================================================================
# Convenience Functions
# =============================================================================


def export_to_pwd(
    steps: Sequence["WorkflowStep"],
    output_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Export workflow steps to PWD format.

    Convenience function for quick PWD export.

    Args:
        steps: Sequence of WorkflowStep objects
        output_path: Optional path to save workflow.json

    Returns:
        PWD JSON dict

    Example:
        >>> from crystalmath.protocols import WorkflowStep, WorkflowType
        >>> steps = [WorkflowStep(name="relax", workflow_type=WorkflowType.RELAX, code="vasp")]
        >>> pwd = export_to_pwd(steps)
        >>> # Or save to file:
        >>> pwd = export_to_pwd(steps, Path("./workflow.json"))
    """
    converter = PWDConverter()
    pwd_json = converter.to_pwd(steps)

    if output_path:
        with open(output_path, "w") as f:
            json.dump(pwd_json, f, indent=2)

    return pwd_json


def import_from_pwd(
    source: Union[Path, Dict[str, Any]],
) -> List["WorkflowStep"]:
    """
    Import workflow from PWD format.

    Convenience function for quick PWD import.

    Args:
        source: Either path to PWD directory/file or PWD JSON dict

    Returns:
        List of WorkflowStep objects

    Example:
        >>> # From file
        >>> steps = import_from_pwd(Path("./my_workflow"))
        >>> # From dict
        >>> steps = import_from_pwd({"nodes": [...], "edges": [...]})
    """
    converter = PWDConverter()

    if isinstance(source, dict):
        return converter.from_pwd(source)
    else:
        source = Path(source)
        if source.is_dir():
            return converter.load_pwd(source)
        else:
            # Single file
            with open(source) as f:
                pwd_json = json.load(f)
            return converter.from_pwd(pwd_json)


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Exceptions
    "PWDConversionError",
    "PWDValidationError",
    "PWDImportError",
    # Data classes
    "PWDNode",
    "PWDEdge",
    "CrystalMathExtensions",
    # Main class
    "PWDConverter",
    # Convenience functions
    "export_to_pwd",
    "import_from_pwd",
]
