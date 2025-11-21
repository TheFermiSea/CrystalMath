"""
Directed Acyclic Graph (DAG) system for multi-step calculation workflows.

This module provides the core infrastructure for defining, validating, and
executing complex workflows of CRYSTAL calculations with dependencies.
"""

import asyncio
import json
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Set
from enum import Enum
from pathlib import Path
from datetime import datetime
import re


class NodeStatus(Enum):
    """Status of a workflow node."""
    PENDING = "PENDING"
    READY = "READY"  # Dependencies met, ready to run
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"  # Skipped due to upstream failure


class WorkflowStatus(Enum):
    """Overall workflow status."""
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    VALID = "VALID"
    INVALID = "INVALID"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"  # Some nodes completed, some failed


class NodeType(Enum):
    """Type of workflow node."""
    CALCULATION = "CALCULATION"  # CRYSTAL calculation job
    DATA_TRANSFER = "DATA_TRANSFER"  # Copy files between jobs
    CONDITION = "CONDITION"  # Branch based on results
    AGGREGATION = "AGGREGATION"  # Combine results from multiple nodes


@dataclass
class WorkflowNode:
    """Represents a single step in a workflow."""

    node_id: str
    node_type: NodeType
    job_template: Optional[str] = None  # For CALCULATION nodes
    parameters: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)  # List of node_ids
    status: NodeStatus = NodeStatus.PENDING
    result_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 0

    # For DATA_TRANSFER nodes
    source_node: Optional[str] = None
    source_files: List[str] = field(default_factory=list)
    target_node: Optional[str] = None

    # For CONDITION nodes
    condition_expr: Optional[str] = None  # Python expression to eval
    true_branch: List[str] = field(default_factory=list)  # Node IDs
    false_branch: List[str] = field(default_factory=list)  # Node IDs

    # For AGGREGATION nodes
    aggregation_func: Optional[str] = None  # "mean", "min", "max", "collect"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data["node_type"] = self.node_type.value
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowNode":
        """Create from dictionary (deserialization)."""
        data["node_type"] = NodeType(data["node_type"])
        data["status"] = NodeStatus(data["status"])
        return cls(**data)


@dataclass
class WorkflowEdge:
    """Represents a dependency edge in the workflow DAG."""
    from_node: str
    to_node: str
    condition: Optional[str] = None  # Optional condition for edge activation


class Workflow:
    """
    Directed Acyclic Graph (DAG) for multi-step calculation workflows.

    Example:
        workflow = Workflow("opt_freq", "Optimization followed by frequency")
        opt = workflow.add_node("optimization", {"basis": "sto-3g"}, node_id="opt")
        freq = workflow.add_node("frequency", {"basis": "sto-3g"}, node_id="freq")
        workflow.add_dependency("opt", "freq")

        errors = workflow.validate()
        if not errors:
            await workflow.execute()
    """

    def __init__(
        self,
        workflow_id: str,
        name: str,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Initialize a new workflow."""
        self.workflow_id = workflow_id
        self.name = name
        self.description = description
        self.metadata = metadata or {}
        self.nodes: Dict[str, WorkflowNode] = {}
        self.edges: List[WorkflowEdge] = []
        self.status = WorkflowStatus.CREATED
        self.created_at = datetime.now().isoformat()
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None
        self.execution_order: List[str] = []

        # Execution state
        self._running_nodes: Set[str] = set()
        self._completed_nodes: Set[str] = set()
        self._failed_nodes: Set[str] = set()

    def add_node(
        self,
        template: str,
        params: Dict[str, Any],
        node_id: Optional[str] = None,
        node_type: NodeType = NodeType.CALCULATION,
        max_retries: int = 0,
        **kwargs
    ) -> WorkflowNode:
        """
        Add a calculation node to the workflow.

        Args:
            template: Job template name (for CALCULATION nodes)
            params: Parameters for the node (can include Jinja2 templates)
            node_id: Unique identifier (auto-generated if not provided)
            node_type: Type of node (CALCULATION, DATA_TRANSFER, etc.)
            max_retries: Maximum retry attempts on failure
            **kwargs: Additional node properties

        Returns:
            The created WorkflowNode

        Raises:
            ValueError: If node_id already exists
        """
        if node_id is None:
            node_id = f"{template}_{len(self.nodes)}"

        if node_id in self.nodes:
            raise ValueError(f"Node with ID '{node_id}' already exists")

        node = WorkflowNode(
            node_id=node_id,
            node_type=node_type,
            job_template=template,
            parameters=params,
            max_retries=max_retries,
            **kwargs
        )

        self.nodes[node_id] = node
        return node

    def add_data_transfer_node(
        self,
        node_id: str,
        source_node: str,
        source_files: List[str],
        target_node: str
    ) -> WorkflowNode:
        """
        Add a data transfer node that copies files between jobs.

        Args:
            node_id: Unique identifier for this transfer node
            source_node: Node ID to copy files from
            source_files: List of file patterns to copy
            target_node: Node ID to copy files to

        Returns:
            The created WorkflowNode
        """
        node = WorkflowNode(
            node_id=node_id,
            node_type=NodeType.DATA_TRANSFER,
            source_node=source_node,
            source_files=source_files,
            target_node=target_node,
            dependencies=[source_node]
        )

        self.nodes[node_id] = node
        return node

    def add_condition_node(
        self,
        node_id: str,
        condition_expr: str,
        true_branch: List[str],
        false_branch: List[str],
        dependencies: List[str]
    ) -> WorkflowNode:
        """
        Add a conditional branching node.

        Args:
            node_id: Unique identifier
            condition_expr: Python expression to evaluate (uses node results)
            true_branch: Node IDs to activate if condition is True
            false_branch: Node IDs to activate if condition is False
            dependencies: Node IDs this condition depends on

        Returns:
            The created WorkflowNode
        """
        node = WorkflowNode(
            node_id=node_id,
            node_type=NodeType.CONDITION,
            condition_expr=condition_expr,
            true_branch=true_branch,
            false_branch=false_branch,
            dependencies=dependencies
        )

        self.nodes[node_id] = node
        return node

    def add_aggregation_node(
        self,
        node_id: str,
        aggregation_func: str,
        dependencies: List[str]
    ) -> WorkflowNode:
        """
        Add an aggregation node that combines results from multiple nodes.

        Args:
            node_id: Unique identifier
            aggregation_func: Aggregation function ("mean", "min", "max", "collect")
            dependencies: Node IDs to aggregate results from

        Returns:
            The created WorkflowNode
        """
        if aggregation_func not in ["mean", "min", "max", "collect"]:
            raise ValueError(f"Invalid aggregation function: {aggregation_func}")

        node = WorkflowNode(
            node_id=node_id,
            node_type=NodeType.AGGREGATION,
            aggregation_func=aggregation_func,
            dependencies=dependencies
        )

        self.nodes[node_id] = node
        return node

    def add_dependency(self, from_node: str, to_node: str, condition: Optional[str] = None) -> None:
        """
        Add a dependency edge from one node to another.

        Args:
            from_node: Node ID that must complete first
            to_node: Node ID that depends on from_node
            condition: Optional condition for edge activation

        Raises:
            ValueError: If either node doesn't exist
        """
        if from_node not in self.nodes:
            raise ValueError(f"Source node '{from_node}' does not exist")
        if to_node not in self.nodes:
            raise ValueError(f"Target node '{to_node}' does not exist")

        # Add edge
        edge = WorkflowEdge(from_node, to_node, condition)
        self.edges.append(edge)

        # Update node's dependency list
        if from_node not in self.nodes[to_node].dependencies:
            self.nodes[to_node].dependencies.append(from_node)

    def validate(self) -> List[str]:
        """
        Validate the workflow DAG.

        Checks for:
        - Cycles in the graph
        - Missing dependencies
        - Invalid parameter references
        - Disconnected components

        Returns:
            List of error messages (empty if valid)
        """
        errors = []
        self.status = WorkflowStatus.VALIDATING

        # Check for cycles using DFS
        if self._has_cycle():
            errors.append("Workflow contains a cycle")

        # Check for missing dependencies
        for node in self.nodes.values():
            for dep in node.dependencies:
                if dep not in self.nodes:
                    errors.append(f"Node '{node.node_id}' has missing dependency '{dep}'")

        # Check for orphaned nodes (nodes with no path to/from any other node)
        if len(self.nodes) > 1:
            orphans = self._find_orphaned_nodes()
            if orphans:
                errors.append(f"Orphaned nodes detected: {', '.join(orphans)}")

        # Validate parameter templates
        for node in self.nodes.values():
            param_errors = self._validate_parameter_templates(node)
            errors.extend(param_errors)

        # Validate condition nodes
        for node in self.nodes.values():
            if node.node_type == NodeType.CONDITION:
                if not node.condition_expr:
                    errors.append(f"Condition node '{node.node_id}' has no condition expression")
                if not node.true_branch and not node.false_branch:
                    errors.append(f"Condition node '{node.node_id}' has no branches")

        # Validate data transfer nodes
        for node in self.nodes.values():
            if node.node_type == NodeType.DATA_TRANSFER:
                if not node.source_node or node.source_node not in self.nodes:
                    errors.append(f"Data transfer node '{node.node_id}' has invalid source")
                if not node.source_files:
                    errors.append(f"Data transfer node '{node.node_id}' has no source files")

        # Update status
        self.status = WorkflowStatus.VALID if not errors else WorkflowStatus.INVALID

        return errors

    def _has_cycle(self) -> bool:
        """Detect cycles using DFS."""
        visited = set()
        rec_stack = set()

        def dfs(node_id: str) -> bool:
            visited.add(node_id)
            rec_stack.add(node_id)

            # Get all dependent nodes
            for edge in self.edges:
                if edge.from_node == node_id:
                    if edge.to_node not in visited:
                        if dfs(edge.to_node):
                            return True
                    elif edge.to_node in rec_stack:
                        return True

            rec_stack.remove(node_id)
            return False

        for node_id in self.nodes:
            if node_id not in visited:
                if dfs(node_id):
                    return True

        return False

    def _find_orphaned_nodes(self) -> List[str]:
        """Find nodes with no connections to other nodes."""
        orphans = []

        for node_id in self.nodes:
            has_incoming = any(edge.to_node == node_id for edge in self.edges)
            has_outgoing = any(edge.from_node == node_id for edge in self.edges)

            if not has_incoming and not has_outgoing:
                orphans.append(node_id)

        return orphans

    def _validate_parameter_templates(self, node: WorkflowNode) -> List[str]:
        """Validate Jinja2 template references in parameters."""
        errors = []

        # Pattern to match {{ node_id.field }} references
        template_pattern = r'\{\{\s*(\w+)\.(\w+)\s*\}\}'

        for key, value in node.parameters.items():
            if isinstance(value, str):
                matches = re.findall(template_pattern, value)
                for ref_node, field in matches:
                    if ref_node not in self.nodes:
                        errors.append(
                            f"Node '{node.node_id}' parameter '{key}' references "
                            f"non-existent node '{ref_node}'"
                        )
                    elif ref_node not in node.dependencies:
                        errors.append(
                            f"Node '{node.node_id}' parameter '{key}' references "
                            f"node '{ref_node}' but has no dependency on it"
                        )

        return errors

    def _topological_sort(self) -> List[str]:
        """
        Perform topological sort to determine execution order.

        Returns:
            List of node IDs in execution order

        Raises:
            ValueError: If graph has cycles
        """
        in_degree = {node_id: 0 for node_id in self.nodes}

        # Calculate in-degrees
        for edge in self.edges:
            in_degree[edge.to_node] += 1

        # Queue of nodes with no dependencies
        queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            node_id = queue.pop(0)
            result.append(node_id)

            # Reduce in-degree for dependent nodes
            for edge in self.edges:
                if edge.from_node == node_id:
                    in_degree[edge.to_node] -= 1
                    if in_degree[edge.to_node] == 0:
                        queue.append(edge.to_node)

        if len(result) != len(self.nodes):
            raise ValueError("Graph has cycles - cannot perform topological sort")

        return result

    def get_ready_nodes(self) -> List[WorkflowNode]:
        """
        Get nodes that are ready to execute.

        A node is ready if:
        - Status is PENDING or READY
        - All dependencies are COMPLETED
        - Not currently running

        Returns:
            List of ready WorkflowNode objects
        """
        ready = []

        for node in self.nodes.values():
            if node.status not in [NodeStatus.PENDING, NodeStatus.READY]:
                continue

            if node.node_id in self._running_nodes:
                continue

            # Check if all dependencies are completed
            deps_met = all(
                dep in self._completed_nodes
                for dep in node.dependencies
            )

            if deps_met:
                node.status = NodeStatus.READY
                ready.append(node)

        return ready

    def get_status(self) -> WorkflowStatus:
        """
        Get overall workflow status.

        Returns:
            Current WorkflowStatus
        """
        return self.status

    def _resolve_parameters(self, node: WorkflowNode) -> Dict[str, Any]:
        """
        Resolve parameter templates using results from dependency nodes.

        Args:
            node: Node whose parameters to resolve

        Returns:
            Dictionary with resolved parameters
        """
        resolved = {}
        template_pattern = r'\{\{\s*(\w+)\.(\w+)\s*\}\}'

        for key, value in node.parameters.items():
            if isinstance(value, str):
                def replacer(match):
                    ref_node = match.group(1)
                    field = match.group(2)

                    if ref_node in self.nodes:
                        dep_node = self.nodes[ref_node]
                        if dep_node.result_data and field in dep_node.result_data:
                            return str(dep_node.result_data[field])

                    return match.group(0)  # Return original if not found

                resolved[key] = re.sub(template_pattern, replacer, value)
            else:
                resolved[key] = value

        return resolved

    async def execute(self, max_parallel: int = 4) -> None:
        """
        Execute the workflow.

        Args:
            max_parallel: Maximum number of nodes to run in parallel

        Raises:
            ValueError: If workflow is invalid
        """
        # Validate first
        errors = self.validate()
        if errors:
            raise ValueError(f"Workflow validation failed: {', '.join(errors)}")

        self.status = WorkflowStatus.RUNNING
        self.started_at = datetime.now().isoformat()
        self.execution_order = self._topological_sort()

        try:
            # Execute nodes in topological order with parallelism
            while len(self._completed_nodes) + len(self._failed_nodes) < len(self.nodes):
                ready_nodes = self.get_ready_nodes()

                if not ready_nodes and not self._running_nodes:
                    # No nodes ready and none running - stuck or done
                    break

                # Limit parallelism
                available_slots = max_parallel - len(self._running_nodes)
                nodes_to_run = ready_nodes[:available_slots]

                if nodes_to_run:
                    # Execute ready nodes in parallel
                    tasks = [self._execute_node(node) for node in nodes_to_run]
                    await asyncio.gather(*tasks, return_exceptions=True)
                else:
                    # Wait a bit before checking again
                    await asyncio.sleep(0.5)

            # Determine final status
            if len(self._completed_nodes) == len(self.nodes):
                self.status = WorkflowStatus.COMPLETED
            elif len(self._failed_nodes) > 0:
                if len(self._completed_nodes) > 0:
                    self.status = WorkflowStatus.PARTIAL
                else:
                    self.status = WorkflowStatus.FAILED

            self.completed_at = datetime.now().isoformat()

        except Exception as e:
            self.status = WorkflowStatus.FAILED
            self.completed_at = datetime.now().isoformat()
            raise

    async def _execute_node(self, node: WorkflowNode) -> None:
        """
        Execute a single workflow node.

        Args:
            node: The node to execute
        """
        self._running_nodes.add(node.node_id)
        node.status = NodeStatus.RUNNING
        node.started_at = datetime.now().isoformat()

        try:
            if node.node_type == NodeType.CALCULATION:
                await self._execute_calculation_node(node)
            elif node.node_type == NodeType.DATA_TRANSFER:
                await self._execute_data_transfer_node(node)
            elif node.node_type == NodeType.CONDITION:
                await self._execute_condition_node(node)
            elif node.node_type == NodeType.AGGREGATION:
                await self._execute_aggregation_node(node)

            node.status = NodeStatus.COMPLETED
            node.completed_at = datetime.now().isoformat()
            self._completed_nodes.add(node.node_id)

        except Exception as e:
            node.error_message = str(e)

            # Retry logic
            if node.retry_count < node.max_retries:
                node.retry_count += 1
                node.status = NodeStatus.PENDING
            else:
                node.status = NodeStatus.FAILED
                node.completed_at = datetime.now().isoformat()
                self._failed_nodes.add(node.node_id)

                # Mark dependent nodes as skipped
                self._skip_dependent_nodes(node.node_id)

        finally:
            self._running_nodes.remove(node.node_id)

    async def _execute_calculation_node(self, node: WorkflowNode) -> None:
        """Execute a CRYSTAL calculation node (stub for now)."""
        # Resolve parameter templates
        resolved_params = self._resolve_parameters(node)

        # TODO: Actually execute the calculation
        # For now, just simulate with a delay
        await asyncio.sleep(0.1)

        # Store mock results
        node.result_data = {
            "energy": -123.456,
            "f9": f"/path/to/{node.node_id}.f9",
            "converged": True
        }

    async def _execute_data_transfer_node(self, node: WorkflowNode) -> None:
        """Execute a data transfer node (stub for now)."""
        # TODO: Actually copy files
        await asyncio.sleep(0.05)

        node.result_data = {
            "files_copied": len(node.source_files),
            "success": True
        }

    async def _execute_condition_node(self, node: WorkflowNode) -> None:
        """Execute a conditional branching node."""
        # Build context with results from dependencies
        context = {}
        for dep_id in node.dependencies:
            dep_node = self.nodes[dep_id]
            if dep_node.result_data:
                context[dep_id] = dep_node.result_data

        # Evaluate condition
        try:
            result = eval(node.condition_expr, {"__builtins__": {}}, context)
            node.result_data = {"condition_result": bool(result)}

            # Activate appropriate branch
            # (In real implementation, would dynamically add edges)

        except Exception as e:
            raise ValueError(f"Condition evaluation failed: {e}")

    async def _execute_aggregation_node(self, node: WorkflowNode) -> None:
        """Execute an aggregation node."""
        values = []

        # Collect values from dependencies
        for dep_id in node.dependencies:
            dep_node = self.nodes[dep_id]
            if dep_node.result_data and "energy" in dep_node.result_data:
                values.append(dep_node.result_data["energy"])

        # Apply aggregation function
        if node.aggregation_func == "mean":
            result = sum(values) / len(values) if values else 0.0
        elif node.aggregation_func == "min":
            result = min(values) if values else 0.0
        elif node.aggregation_func == "max":
            result = max(values) if values else 0.0
        elif node.aggregation_func == "collect":
            result = values
        else:
            result = None

        node.result_data = {"aggregated_value": result, "count": len(values)}

    def _skip_dependent_nodes(self, failed_node_id: str) -> None:
        """Mark all nodes dependent on a failed node as SKIPPED."""
        to_skip = set()

        def find_dependents(node_id: str):
            for edge in self.edges:
                if edge.from_node == node_id:
                    if edge.to_node not in to_skip:
                        to_skip.add(edge.to_node)
                        find_dependents(edge.to_node)

        find_dependents(failed_node_id)

        for node_id in to_skip:
            self.nodes[node_id].status = NodeStatus.SKIPPED
            self._failed_nodes.add(node_id)

    def to_dict(self) -> Dict[str, Any]:
        """Convert workflow to dictionary for JSON serialization."""
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "metadata": self.metadata,
            "nodes": {nid: node.to_dict() for nid, node in self.nodes.items()},
            "edges": [{"from": e.from_node, "to": e.to_node, "condition": e.condition}
                     for e in self.edges],
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "execution_order": self.execution_order
        }

    def to_json(self, filepath: Path) -> None:
        """Save workflow to JSON file."""
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Workflow":
        """Create workflow from dictionary (deserialization)."""
        workflow = cls(
            workflow_id=data["workflow_id"],
            name=data["name"],
            description=data.get("description", ""),
            metadata=data.get("metadata")
        )

        workflow.status = WorkflowStatus(data["status"])
        workflow.created_at = data["created_at"]
        workflow.started_at = data.get("started_at")
        workflow.completed_at = data.get("completed_at")
        workflow.execution_order = data.get("execution_order", [])

        # Restore nodes
        for node_id, node_data in data["nodes"].items():
            workflow.nodes[node_id] = WorkflowNode.from_dict(node_data)

        # Restore edges
        for edge_data in data["edges"]:
            workflow.edges.append(WorkflowEdge(
                from_node=edge_data["from"],
                to_node=edge_data["to"],
                condition=edge_data.get("condition")
            ))

        return workflow

    @classmethod
    def from_json(cls, filepath: Path) -> "Workflow":
        """Load workflow from JSON file."""
        with open(filepath, 'r') as f:
            data = json.load(f)
        return cls.from_dict(data)

    def to_graphviz(self) -> str:
        """
        Generate GraphViz DOT format for workflow visualization.

        Returns:
            DOT format string
        """
        lines = ["digraph Workflow {"]
        lines.append("    rankdir=TB;")
        lines.append("    node [shape=box, style=rounded];")
        lines.append("")

        # Add nodes with status colors
        for node_id, node in self.nodes.items():
            color = {
                NodeStatus.PENDING: "lightgray",
                NodeStatus.READY: "lightyellow",
                NodeStatus.RUNNING: "lightblue",
                NodeStatus.COMPLETED: "lightgreen",
                NodeStatus.FAILED: "lightcoral",
                NodeStatus.SKIPPED: "gray"
            }.get(node.status, "white")

            label = f"{node_id}\\n({node.node_type.value})"
            lines.append(f'    "{node_id}" [label="{label}", fillcolor={color}, style="rounded,filled"];')

        lines.append("")

        # Add edges
        for edge in self.edges:
            if edge.condition:
                lines.append(f'    "{edge.from_node}" -> "{edge.to_node}" [label="{edge.condition}"];')
            else:
                lines.append(f'    "{edge.from_node}" -> "{edge.to_node}";')

        lines.append("}")
        return "\n".join(lines)

    def to_ascii(self) -> str:
        """
        Generate ASCII art representation of workflow.

        Returns:
            ASCII art string
        """
        lines = [f"Workflow: {self.name} ({self.status.value})"]
        lines.append("=" * 60)

        if self.execution_order:
            for i, node_id in enumerate(self.execution_order, 1):
                node = self.nodes[node_id]
                status_symbol = {
                    NodeStatus.PENDING: "○",
                    NodeStatus.READY: "◐",
                    NodeStatus.RUNNING: "●",
                    NodeStatus.COMPLETED: "✓",
                    NodeStatus.FAILED: "✗",
                    NodeStatus.SKIPPED: "⊘"
                }.get(node.status, "?")

                deps = f" (depends on: {', '.join(node.dependencies)})" if node.dependencies else ""
                lines.append(f"{i}. {status_symbol} {node_id} [{node.node_type.value}]{deps}")
        else:
            for node_id, node in self.nodes.items():
                status_symbol = {
                    NodeStatus.PENDING: "○",
                    NodeStatus.READY: "◐",
                    NodeStatus.RUNNING: "●",
                    NodeStatus.COMPLETED: "✓",
                    NodeStatus.FAILED: "✗",
                    NodeStatus.SKIPPED: "⊘"
                }.get(node.status, "?")

                deps = f" (depends on: {', '.join(node.dependencies)})" if node.dependencies else ""
                lines.append(f"  {status_symbol} {node_id} [{node.node_type.value}]{deps}")

        return "\n".join(lines)

    def get_progress(self) -> Dict[str, Any]:
        """
        Get workflow execution progress.

        Returns:
            Dictionary with progress metrics
        """
        total = len(self.nodes)
        completed = len([n for n in self.nodes.values() if n.status == NodeStatus.COMPLETED])
        failed = len([n for n in self.nodes.values() if n.status == NodeStatus.FAILED])
        running = len([n for n in self.nodes.values() if n.status == NodeStatus.RUNNING])
        pending = len([n for n in self.nodes.values() if n.status in [NodeStatus.PENDING, NodeStatus.READY]])

        return {
            "total_nodes": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "pending": pending,
            "skipped": len([n for n in self.nodes.values() if n.status == NodeStatus.SKIPPED]),
            "percent_complete": (completed / total * 100) if total > 0 else 0,
            "status": self.status.value
        }
