"""
Workflow orchestration for CRYSTAL calculations.

This module provides the WorkflowOrchestrator class which coordinates
the execution of multi-step workflows by managing job dependencies,
parameter resolution, and error handling.
"""

import asyncio
import atexit
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Set
from jinja2 import Template, TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment

from .database import Database, Job
from .dependency_utils import assert_acyclic, CircularDependencyError as DependencyUtilsCircularError


class NodeStatus(Enum):
    """Status of a workflow node."""
    PENDING = "pending"
    READY = "ready"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStatus(Enum):
    """Status of the entire workflow."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FailurePolicy(Enum):
    """Policy for handling node failures."""
    ABORT = "abort"  # Stop entire workflow
    SKIP_DEPENDENTS = "skip_dependents"  # Skip nodes that depend on failed node
    RETRY = "retry"  # Retry failed node N times
    CONTINUE = "continue"  # Mark failed, continue with independent nodes


@dataclass
class WorkflowNode:
    """
    Represents a single node in a workflow DAG.

    Each node corresponds to a CRYSTAL calculation job with its own
    input parameters, dependencies, and execution state.
    """
    node_id: str
    job_name: str
    template: str  # Input template with Jinja2 placeholders
    parameters: Dict[str, Any]  # Initial parameters
    dependencies: List[str] = field(default_factory=list)  # Node IDs this depends on
    status: NodeStatus = NodeStatus.PENDING
    job_id: Optional[int] = None  # Database job ID when submitted
    resolved_parameters: Optional[Dict[str, Any]] = None
    retry_count: int = 0
    max_retries: int = 0
    failure_policy: FailurePolicy = FailurePolicy.ABORT
    output_parsers: List[str] = field(default_factory=list)  # Names of result extractors
    results: Optional[Dict[str, Any]] = None  # Extracted results from job output


@dataclass
class WorkflowDefinition:
    """
    Defines a complete workflow as a DAG of nodes.

    A workflow represents a multi-step calculation where some steps
    depend on the results of previous steps.
    """
    workflow_id: int
    name: str
    description: str
    nodes: List[WorkflowNode]
    global_parameters: Dict[str, Any] = field(default_factory=dict)
    default_failure_policy: FailurePolicy = FailurePolicy.ABORT


@dataclass
class WorkflowState:
    """
    Runtime state of a workflow execution.

    Tracks which nodes have completed, which are running,
    and maintains the overall workflow status.
    """
    workflow_id: int
    status: WorkflowStatus
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    paused_at: Optional[datetime] = None
    completed_nodes: Set[str] = field(default_factory=set)
    failed_nodes: Set[str] = field(default_factory=set)
    running_nodes: Set[str] = field(default_factory=set)
    progress: float = 0.0  # Percentage of nodes completed


# Event types for workflow lifecycle
@dataclass
class WorkflowEvent:
    """Base class for workflow events."""
    workflow_id: int
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class WorkflowStarted(WorkflowEvent):
    """Emitted when a workflow starts execution."""
    def __init__(self, workflow_id: int):
        super().__init__(workflow_id=workflow_id)


@dataclass
class NodeStarted(WorkflowEvent):
    """Emitted when a node starts execution."""
    node_id: str = ""
    job_id: int = 0

    def __init__(self, workflow_id: int, node_id: str, job_id: int):
        super().__init__(workflow_id=workflow_id)
        self.node_id = node_id
        self.job_id = job_id


@dataclass
class NodeCompleted(WorkflowEvent):
    """Emitted when a node completes successfully."""
    node_id: str = ""
    job_id: int = 0
    results: Optional[Dict[str, Any]] = None

    def __init__(self, workflow_id: int, node_id: str, job_id: int, results: Optional[Dict[str, Any]] = None):
        super().__init__(workflow_id=workflow_id)
        self.node_id = node_id
        self.job_id = job_id
        self.results = results


@dataclass
class NodeFailed(WorkflowEvent):
    """Emitted when a node fails."""
    node_id: str = ""
    job_id: int = 0
    error: str = ""
    retry_count: int = 0

    def __init__(self, workflow_id: int, node_id: str, job_id: int, error: str, retry_count: int):
        super().__init__(workflow_id=workflow_id)
        self.node_id = node_id
        self.job_id = job_id
        self.error = error
        self.retry_count = retry_count


@dataclass
class WorkflowCompleted(WorkflowEvent):
    """Emitted when entire workflow completes."""
    total_nodes: int = 0
    successful_nodes: int = 0
    failed_nodes: int = 0

    def __init__(self, workflow_id: int, total_nodes: int, successful_nodes: int, failed_nodes: int):
        super().__init__(workflow_id=workflow_id)
        self.total_nodes = total_nodes
        self.successful_nodes = successful_nodes
        self.failed_nodes = failed_nodes


@dataclass
class WorkflowFailed(WorkflowEvent):
    """Emitted when workflow fails."""
    reason: str = ""

    def __init__(self, workflow_id: int, reason: str):
        super().__init__(workflow_id=workflow_id)
        self.reason = reason


@dataclass
class WorkflowCancelled(WorkflowEvent):
    """Emitted when workflow is cancelled by user."""
    reason: str = ""

    def __init__(self, workflow_id: int, reason: str):
        super().__init__(workflow_id=workflow_id)
        self.reason = reason


class OrchestratorError(Exception):
    """Base exception for orchestrator errors."""
    pass


class WorkflowNotFoundError(OrchestratorError):
    """Raised when workflow ID doesn't exist."""
    pass


class CircularDependencyError(OrchestratorError):
    """Raised when workflow contains circular dependencies."""
    pass


class ParameterResolutionError(OrchestratorError):
    """Raised when parameter templates cannot be resolved."""
    pass


class WorkflowOrchestrator:
    """
    Orchestrates the execution of multi-step calculation workflows.

    The orchestrator:
    - Validates workflow DAGs for circular dependencies
    - Resolves parameter templates using results from completed nodes
    - Submits jobs to the queue manager in dependency order
    - Monitors job completion and triggers dependent nodes
    - Handles failures according to configured policies
    - Tracks workflow progress and emits lifecycle events

    Example:
        >>> orchestrator = WorkflowOrchestrator(database, queue_manager)
        >>> workflow = WorkflowDefinition(...)
        >>> await orchestrator.start_workflow(workflow.workflow_id)
        >>> status = await orchestrator.get_workflow_status(workflow.workflow_id)
    """

    def __init__(
        self,
        database: Database,
        queue_manager: Any,  # Will be QueueManager when implemented
        event_callback: Optional[Callable[[WorkflowEvent], None]] = None,
        scratch_base: Optional[Path] = None
    ):
        """
        Initialize the orchestrator.

        Args:
            database: Database instance for persistence
            queue_manager: Queue manager for job submission
            event_callback: Optional callback for workflow events
            scratch_base: Optional base directory for workflow scratch space.
                         If not provided, uses CRY_SCRATCH_BASE, CRY23_SCRDIR, or tempfile.gettempdir()
        """
        self.database = database
        self.queue_manager = queue_manager
        self.event_callback = event_callback

        # Configure scratch base directory with proper fallback chain
        self._scratch_base = scratch_base or self._get_scratch_base()

        # Track cleanup handlers for proper resource cleanup
        # Maps work_dir -> workflow_id for conditional cleanup
        self._work_dirs: Dict[Path, int] = {}
        atexit.register(self._cleanup_work_dirs)

        # In-memory state for active workflows
        self._workflows: Dict[int, WorkflowDefinition] = {}
        self._workflow_states: Dict[int, WorkflowState] = {}
        self._node_lookup: Dict[int, Dict[str, WorkflowNode]] = {}  # workflow_id -> node_id -> node

        # Callback tracking for job completions
        # Maps job_id -> (workflow_id, node_id)
        self._node_callbacks: Dict[int, tuple] = {}

        # Background monitoring task
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False

        # SECURITY: Use sandboxed Jinja2 environment to prevent code execution attacks
        # SandboxedEnvironment restricts access to dangerous Python builtins and attributes
        # This prevents template injection attacks like:
        # {{ ''.__class__.__mro__[1].__subclasses__()[104].__init__.__globals__['os'].system('rm -rf /') }}
        self._jinja_env = SandboxedEnvironment(autoescape=False)

        # Output parser registry
        # Maps parser name -> async callable that takes (work_dir: Path) -> Dict[str, Any]
        self._output_parsers: Dict[str, Callable[[Path], Dict[str, Any]]] = {}
        self._register_builtin_parsers()

    def register_parser(self, name: str, parser_func: Callable[[Path], Dict[str, Any]]) -> None:
        """
        Register a custom output parser.

        Parsers are async functions that extract specific information from job output files.
        They receive the work directory path and return a dictionary of extracted values.

        Args:
            name: Unique name for the parser (e.g., "energy", "bandgap")
            parser_func: Async function with signature (work_dir: Path) -> Dict[str, Any]

        Example:
            >>> async def my_parser(work_dir: Path) -> Dict[str, Any]:
            ...     output_file = work_dir / "job.out"
            ...     # Parse output_file
            ...     return {"my_value": 42}
            >>> orchestrator.register_parser("my_parser", my_parser)
        """
        self._output_parsers[name] = parser_func

    def _get_output_parser(self, name: str) -> Optional[Callable[[Path], Dict[str, Any]]]:
        """
        Retrieve a registered output parser by name.

        Args:
            name: Name of the parser to retrieve

        Returns:
            Parser function if found, None otherwise
        """
        return self._output_parsers.get(name)

    def _register_builtin_parsers(self) -> None:
        """
        Register built-in output parsers for common CRYSTAL outputs.

        Built-in parsers:
        - "energy": Extracts final SCF energy from output
        - "bandgap": Extracts band gap if available
        - "lattice": Extracts lattice parameters
        """
        self.register_parser("energy", self._parse_energy)
        self.register_parser("bandgap", self._parse_bandgap)
        self.register_parser("lattice", self._parse_lattice)

    def _find_output_file(self, work_dir: Path) -> Optional[Path]:
        """
        Find the output file in a work directory.

        Searches for common output file patterns used by different runners:
        - LocalRunner: output.d12, output.out, *.out
        - SSHRunner: output.log
        - SLURMRunner: output.log, slurm-*.out

        Args:
            work_dir: Job work directory

        Returns:
            Path to output file if found, None otherwise
        """
        # Priority order of output file patterns
        patterns = [
            "output.d12",      # LocalRunner with CRYSTAL
            "output.out",      # LocalRunner generic
            "output.log",      # SSHRunner
            "job.out",         # Legacy pattern
            "*.out",           # Fallback glob
        ]

        for pattern in patterns:
            if "*" in pattern:
                # Glob pattern
                matches = list(work_dir.glob(pattern))
                if matches:
                    # Return the most recently modified .out file
                    return max(matches, key=lambda p: p.stat().st_mtime)
            else:
                # Exact filename
                candidate = work_dir / pattern
                if candidate.exists():
                    return candidate

        return None

    async def _parse_energy(self, work_dir: Path) -> Dict[str, Any]:
        """
        Extract final SCF energy from CRYSTAL output.

        Searches for the final energy line in the output file.
        Typical format: "== SCF ENDED - CONVERGENCE ON ENERGY      E(AU) = -XXX.XXXXXXXX"

        Args:
            work_dir: Job work directory containing output file

        Returns:
            Dictionary with "final_energy" key if found, empty dict otherwise
        """
        output_file = self._find_output_file(work_dir)
        if output_file is None:
            return {}

        try:
            with open(output_file, "r") as f:
                lines = f.readlines()

            # Search backwards for final energy (last occurrence)
            for line in reversed(lines):
                if "SCF ENDED" in line and "E(AU)" in line:
                    # Extract energy value
                    parts = line.split("E(AU)")
                    if len(parts) > 1:
                        energy_str = parts[1].strip().split()[1]
                        return {"final_energy": float(energy_str)}

            return {}
        except Exception as e:
            # Log error but don't fail the workflow
            print(f"Warning: Failed to parse energy from {output_file}: {e}")
            return {}

    async def _parse_bandgap(self, work_dir: Path) -> Dict[str, Any]:
        """
        Extract band gap from CRYSTAL output.

        Searches for band structure analysis lines in the output.
        Typical format: "ENERGY BAND GAP:     X.XXX eV"

        Args:
            work_dir: Job work directory containing output file

        Returns:
            Dictionary with "bandgap" key if found, empty dict otherwise
        """
        output_file = self._find_output_file(work_dir)
        if output_file is None:
            return {}

        try:
            with open(output_file, "r") as f:
                content = f.read()

            # Search for band gap line
            # Check for direct/indirect first (more specific pattern)
            for line in content.split("\n"):
                if "DIRECT ENERGY BAND GAP" in line or "INDIRECT ENERGY BAND GAP" in line:
                    parts = line.split(":")
                    if len(parts) > 1:
                        gap_str = parts[1].strip().split()[0]
                        gap_type = "direct" if "DIRECT" in line else "indirect"
                        return {"bandgap": float(gap_str), "bandgap_type": gap_type}

                # Generic band gap format (fallback)
                if "ENERGY BAND GAP" in line and "DIRECT" not in line and "INDIRECT" not in line:
                    parts = line.split(":")
                    if len(parts) > 1:
                        gap_str = parts[1].strip().split()[0]
                        return {"bandgap": float(gap_str)}

            return {}
        except Exception as e:
            print(f"Warning: Failed to parse band gap from {output_file}: {e}")
            return {}

    async def _parse_lattice(self, work_dir: Path) -> Dict[str, Any]:
        """
        Extract lattice parameters from CRYSTAL output.

        Searches for the final geometry section with cell parameters.
        Typical format:
        "FINAL OPTIMIZED GEOMETRY"
        "PRIMITIVE CELL"
        "A      B      C   ALPHA  BETA  GAMMA"

        Args:
            work_dir: Job work directory containing output file

        Returns:
            Dictionary with lattice parameter keys if found, empty dict otherwise
        """
        output_file = self._find_output_file(work_dir)
        if output_file is None:
            return {}

        try:
            with open(output_file, "r") as f:
                lines = f.readlines()

            results = {}

            # Search for lattice parameter section
            for i, line in enumerate(lines):
                # Look for optimized or initial geometry
                if "PRIMITIVE CELL" in line or "CRYSTALLOGRAPHIC CELL" in line:
                    # Check next few lines for parameter headers
                    for j in range(i + 1, min(i + 10, len(lines))):
                        if "A" in lines[j] and "B" in lines[j] and "C" in lines[j]:
                            # Next line should have values
                            if j + 1 < len(lines):
                                values_line = lines[j + 1].strip()
                                values = values_line.split()
                                if len(values) >= 6:
                                    try:
                                        results["lattice_a"] = float(values[0])
                                        results["lattice_b"] = float(values[1])
                                        results["lattice_c"] = float(values[2])
                                        results["lattice_alpha"] = float(values[3])
                                        results["lattice_beta"] = float(values[4])
                                        results["lattice_gamma"] = float(values[5])
                                        return results
                                    except (ValueError, IndexError):
                                        continue

            return results
        except Exception as e:
            print(f"Warning: Failed to parse lattice parameters from {output_file}: {e}")
            return {}

    @staticmethod
    def _get_scratch_base() -> Path:
        """
        Get the scratch base directory following the configured fallback chain.

        Priority:
        1. CRY_SCRATCH_BASE environment variable (newer convention)
        2. CRY23_SCRDIR environment variable (CRYSTAL23 convention)
        3. tempfile.gettempdir() system default

        Returns:
            Path object for the scratch base directory
        """
        # Try CRY_SCRATCH_BASE first (preferred newer convention)
        scratch_base = os.environ.get('CRY_SCRATCH_BASE')
        if scratch_base:
            return Path(scratch_base)

        # Fall back to CRY23_SCRDIR (CRYSTAL23 convention)
        scratch_dir = os.environ.get('CRY23_SCRDIR')
        if scratch_dir:
            return Path(scratch_dir)

        # Fall back to system temp directory
        return Path(tempfile.gettempdir())

    def _create_work_directory(self, workflow_id: int, node_id: str) -> Path:
        """
        Create a unique work directory for a workflow node.

        Creates a directory with format:
        <scratch_base>/workflow_<workflow_id>_node_<node_id>_<timestamp>_<pid>

        The directory is registered for cleanup on exit.

        Args:
            workflow_id: ID of the workflow
            node_id: ID of the node

        Returns:
            Path object for the created directory

        Raises:
            OSError: If directory creation fails
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        pid = os.getpid()
        dir_name = f"workflow_{workflow_id}_node_{node_id}_{timestamp}_{pid}"
        work_dir = self._scratch_base / dir_name

        # Create directory
        work_dir.mkdir(parents=True, exist_ok=True)

        # Register for cleanup with workflow_id for conditional cleanup
        self._work_dirs[work_dir] = workflow_id

        return work_dir

    def _cleanup_work_dirs(self) -> None:
        """
        Clean up work directories for workflows in terminal state only.

        This method is registered as an atexit handler to ensure
        cleanup occurs even if the orchestrator is not explicitly stopped.

        SAFETY: Only cleans up directories for workflows that have reached
        a terminal state (COMPLETED, FAILED, CANCELLED). Directories for
        running workflows are preserved to prevent data loss.
        """
        terminal_states = {
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }

        dirs_to_remove = []
        for work_dir, workflow_id in self._work_dirs.items():
            # Check if workflow is in a terminal state
            state = self._workflow_states.get(workflow_id)
            if state is None or state.status in terminal_states:
                dirs_to_remove.append(work_dir)

        for work_dir in dirs_to_remove:
            try:
                if work_dir.exists():
                    shutil.rmtree(work_dir, ignore_errors=True)
                # Remove from tracking dict
                self._work_dirs.pop(work_dir, None)
            except Exception:
                # Silently ignore cleanup errors to prevent atexit issues
                pass

    def register_workflow(self, workflow: WorkflowDefinition) -> None:
        """
        Register a workflow definition for execution.

        Args:
            workflow: Workflow definition with DAG structure

        Raises:
            CircularDependencyError: If workflow contains circular dependencies
        """
        # Validate DAG structure
        self._validate_dag(workflow)

        # Store workflow
        self._workflows[workflow.workflow_id] = workflow

        # Create node lookup
        self._node_lookup[workflow.workflow_id] = {
            node.node_id: node for node in workflow.nodes
        }

        # Initialize state
        self._workflow_states[workflow.workflow_id] = WorkflowState(
            workflow_id=workflow.workflow_id,
            status=WorkflowStatus.PENDING
        )

    def _validate_dag(self, workflow: WorkflowDefinition) -> None:
        """
        Validate that workflow DAG has no circular dependencies.

        Preflight check for cycles - queue_manager is the enforcement point for dependencies.

        Args:
            workflow: Workflow to validate

        Raises:
            CircularDependencyError: If circular dependency detected
        """
        # Build graph from workflow nodes
        graph = {node.node_id: node.dependencies for node in workflow.nodes}

        # Delegate to shared dependency_utils module for cycle detection
        try:
            assert_acyclic(graph, error_context=f"workflow '{workflow.name}'")
        except DependencyUtilsCircularError as e:
            # Re-raise as orchestrator's CircularDependencyError for API compatibility
            raise CircularDependencyError(str(e)) from e

    async def start_workflow(self, workflow_id: int) -> None:
        """
        Start executing a registered workflow.

        Args:
            workflow_id: ID of workflow to start

        Raises:
            WorkflowNotFoundError: If workflow_id not registered
        """
        if workflow_id not in self._workflows:
            raise WorkflowNotFoundError(f"Workflow {workflow_id} not registered")

        state = self._workflow_states[workflow_id]

        if state.status != WorkflowStatus.PENDING:
            raise OrchestratorError(
                f"Cannot start workflow in state {state.status.value}"
            )

        # Update state
        state.status = WorkflowStatus.RUNNING
        state.started_at = datetime.now()

        # Emit event
        self._emit_event(WorkflowStarted(workflow_id))

        # Start background monitor if not running
        if not self._running:
            self._running = True
            self._monitor_task = asyncio.create_task(self._monitor_workflows())

        # Submit initial nodes (those with no dependencies)
        await self._submit_ready_nodes(workflow_id)

    async def pause_workflow(self, workflow_id: int) -> None:
        """
        Pause a running workflow.

        Running jobs continue, but no new jobs are submitted.

        Args:
            workflow_id: ID of workflow to pause
        """
        if workflow_id not in self._workflow_states:
            raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")

        state = self._workflow_states[workflow_id]

        if state.status != WorkflowStatus.RUNNING:
            raise OrchestratorError(
                f"Cannot pause workflow in state {state.status.value}"
            )

        state.status = WorkflowStatus.PAUSED
        state.paused_at = datetime.now()

    async def resume_workflow(self, workflow_id: int) -> None:
        """
        Resume a paused workflow.

        Args:
            workflow_id: ID of workflow to resume
        """
        if workflow_id not in self._workflow_states:
            raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")

        state = self._workflow_states[workflow_id]

        if state.status != WorkflowStatus.PAUSED:
            raise OrchestratorError(
                f"Cannot resume workflow in state {state.status.value}"
            )

        state.status = WorkflowStatus.RUNNING
        state.paused_at = None

        # Resume submitting ready nodes
        await self._submit_ready_nodes(workflow_id)

    async def cancel_workflow(self, workflow_id: int, reason: str = "User cancelled") -> None:
        """
        Cancel a workflow and stop all running jobs.

        Args:
            workflow_id: ID of workflow to cancel
            reason: Reason for cancellation
        """
        if workflow_id not in self._workflow_states:
            raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")

        state = self._workflow_states[workflow_id]
        workflow = self._workflows[workflow_id]

        # Update state
        state.status = WorkflowStatus.CANCELLED
        state.completed_at = datetime.now()

        # Stop all running jobs
        for node_id in list(state.running_nodes):
            node = self._node_lookup[workflow_id][node_id]
            if node.job_id:
                await self.queue_manager.cancel_job(node.job_id)

        # Also cancel any pending jobs that haven't started yet
        for node_id, node in self._node_lookup[workflow_id].items():
            if node.job_id and node_id not in state.running_nodes:
                await self.queue_manager.cancel_job(node.job_id)

        # Emit event
        self._emit_event(WorkflowCancelled(workflow_id, reason=reason))

    async def cancel_job(self, job_id: int) -> bool:
        """
        Cancel a single job.

        This method cancels a job via the queue manager and updates the
        database status to CANCELLED.

        Args:
            job_id: Database ID of the job to cancel

        Returns:
            True if job was cancelled, False if job was already completed/failed
            or not found
        """
        return await self.queue_manager.cancel_job(job_id)

    async def get_workflow_status(self, workflow_id: int) -> WorkflowState:
        """
        Get current status of a workflow.

        Args:
            workflow_id: ID of workflow

        Returns:
            Current workflow state

        Raises:
            WorkflowNotFoundError: If workflow not found
        """
        if workflow_id not in self._workflow_states:
            raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")

        return self._workflow_states[workflow_id]

    async def process_node_completion(self, workflow_id: int, node_id: str, job_id: int) -> None:
        """
        Process completion of a workflow node.

        This method:
        1. Updates node status
        2. Extracts results from job output
        3. Checks if dependent nodes are ready
        4. Submits newly ready nodes
        5. Checks if workflow is complete

        Args:
            workflow_id: Workflow containing the node
            node_id: ID of completed node
            job_id: Database job ID
        """
        if workflow_id not in self._workflows:
            return

        workflow = self._workflows[workflow_id]
        state = self._workflow_states[workflow_id]
        node = self._node_lookup[workflow_id][node_id]

        # Get job from database
        job = self.database.get_job(job_id)
        if not job:
            return

        # Check if job was successful
        if job.status == "COMPLETED":
            # Extract results
            results = await self._extract_node_results(node, job)
            node.results = results
            node.status = NodeStatus.COMPLETED

            # Update state
            state.completed_nodes.add(node_id)
            state.running_nodes.discard(node_id)

            # Emit event
            self._emit_event(NodeCompleted(
                workflow_id=workflow_id,
                node_id=node_id,
                job_id=job_id,
                results=results
            ))

            # Submit dependent nodes that are now ready
            await self._submit_ready_nodes(workflow_id)

            # Check if workflow is complete
            await self._check_workflow_completion(workflow_id)

        elif job.status == "FAILED":
            # Handle failure
            await self._handle_node_failure(workflow_id, node_id, job_id, "Job failed")

    async def _submit_ready_nodes(self, workflow_id: int) -> None:
        """
        Submit all nodes that are ready to execute.

        A node is ready if all its dependencies have completed.

        Args:
            workflow_id: Workflow to process
        """
        if workflow_id not in self._workflows:
            return

        workflow = self._workflows[workflow_id]
        state = self._workflow_states[workflow_id]

        # Don't submit if paused or not running
        if state.status not in (WorkflowStatus.RUNNING,):
            return

        for node in workflow.nodes:
            # Skip if already processed
            if node.status != NodeStatus.PENDING:
                continue

            # Check if dependencies are met
            if self._dependencies_met(workflow_id, node):
                await self._submit_node(workflow_id, node)

    def _dependencies_met(self, workflow_id: int, node: WorkflowNode) -> bool:
        """
        Check if all dependencies for a node are satisfied.

        Args:
            workflow_id: Workflow containing node
            node: Node to check

        Returns:
            True if all dependencies completed successfully
        """
        state = self._workflow_states[workflow_id]

        for dep_id in node.dependencies:
            if dep_id not in state.completed_nodes:
                return False

        return True

    async def _submit_node(self, workflow_id: int, node: WorkflowNode) -> None:
        """
        Submit a single node for execution.

        This method:
        1. Resolves parameter templates
        2. Creates input file from template
        3. Creates database job entry
        4. Submits to queue manager

        Args:
            workflow_id: Workflow containing node
            node: Node to submit
        """
        workflow = self._workflows[workflow_id]
        state = self._workflow_states[workflow_id]

        try:
            # Resolve parameters
            resolved_params = await self._resolve_parameters(workflow_id, node)
            node.resolved_parameters = resolved_params

            # Render input template
            input_content = self._render_template(node.template, resolved_params)

            # Create work directory using environment-based scratch location
            work_dir = self._create_work_directory(workflow_id, node.node_id)

            # Create database job
            job_id = self.database.create_job(
                name=node.job_name,
                work_dir=str(work_dir),
                input_content=input_content
            )

            node.job_id = job_id
            node.status = NodeStatus.QUEUED

            # Update state
            state.running_nodes.add(node.node_id)

            # Get job from database to access cluster_id and runner_type
            job = self.database.get_job(job_id)
            if not job:
                raise OrchestratorError(f"Failed to retrieve job {job_id} from database")

            # Prepare dependencies: get job_ids from dependent nodes
            dep_job_ids = []
            for dep_node_id in node.dependencies:
                dep_node = self._node_lookup[workflow_id].get(dep_node_id)
                if dep_node and dep_node.job_id:
                    dep_job_ids.append(dep_node.job_id)

            # Submit to queue manager with dependencies
            await self.queue_manager.enqueue(
                job_id=job_id,
                priority=2,  # Default NORMAL priority
                dependencies=dep_job_ids if dep_job_ids else None,
                runner_type=job.runner_type or "local",
                cluster_id=job.cluster_id,
                user_id=None
            )

            # Register completion callback with queue manager
            # This creates a callback that will be invoked when the job reaches terminal status
            async def job_completion_callback(completed_job_id: int, status: str) -> None:
                """Callback invoked by queue manager when job completes."""
                await self._on_node_complete(workflow_id, node, status)

            self.queue_manager.register_callback(job_id, job_completion_callback)

            # Also store in local tracking dict for debugging/monitoring
            if not hasattr(self, '_node_callbacks'):
                self._node_callbacks = {}
            self._node_callbacks[job_id] = (workflow_id, node.node_id)

            # Update database status (queue manager will manage from here)
            self.database.update_status(job_id, "QUEUED")

            # Emit event
            self._emit_event(NodeStarted(
                workflow_id=workflow_id,
                node_id=node.node_id,
                job_id=job_id
            ))

        except Exception as e:
            await self._handle_node_failure(
                workflow_id,
                node.node_id,
                node.job_id or 0,
                str(e)
            )

    async def _on_node_complete(self, workflow_id: int, node: WorkflowNode, job_status: str) -> None:
        """
        Handle completion of a workflow node.

        This callback is triggered when a job submitted by _submit_node completes.
        It processes the job results and updates workflow state.

        Args:
            workflow_id: ID of the workflow
            node: The workflow node that completed
            job_status: Status of the completed job ("COMPLETED" or "FAILED")
        """
        if not node.job_id:
            return

        if job_status == "COMPLETED":
            await self.process_node_completion(workflow_id, node.node_id, node.job_id)
        elif job_status == "FAILED":
            await self._handle_node_failure(
                workflow_id,
                node.node_id,
                node.job_id,
                "Job execution failed"
            )

    async def _resolve_parameters(
        self,
        workflow_id: int,
        node: WorkflowNode
    ) -> Dict[str, Any]:
        """
        Resolve parameter templates using results from completed dependencies.

        Args:
            workflow_id: Workflow containing node
            node: Node whose parameters to resolve

        Returns:
            Resolved parameters dictionary

        Raises:
            ParameterResolutionError: If templates cannot be resolved
        """
        workflow = self._workflows[workflow_id]

        # Start with node's base parameters
        params = dict(node.parameters)

        # Add global parameters
        params.update(workflow.global_parameters)

        # Add results from dependencies as nested dicts
        # This allows Jinja2 to access them with dot notation: {{ dep_id.result_key }}
        for dep_id in node.dependencies:
            dep_node = self._node_lookup[workflow_id][dep_id]
            if dep_node.results:
                # Make dependency results available as nested dict
                params[dep_id] = dep_node.results

        # Resolve any Jinja2 templates in parameter values
        resolved = {}
        for key, value in params.items():
            if isinstance(value, str):
                try:
                    template = self._jinja_env.from_string(value)
                    resolved[key] = template.render(params)
                except TemplateSyntaxError as e:
                    raise ParameterResolutionError(
                        f"Template syntax error in parameter '{key}': {e}"
                    )
                except Exception as e:
                    raise ParameterResolutionError(
                        f"Error resolving parameter '{key}': {e}"
                    )
            else:
                resolved[key] = value

        return resolved

    def _render_template(self, template: str, parameters: Dict[str, Any]) -> str:
        """
        Render an input file template with resolved parameters.

        Args:
            template: Input file template with Jinja2 syntax
            parameters: Resolved parameters

        Returns:
            Rendered input file content

        Raises:
            ParameterResolutionError: If rendering fails
        """
        try:
            jinja_template = self._jinja_env.from_string(template)
            return jinja_template.render(parameters)
        except Exception as e:
            raise ParameterResolutionError(
                f"Error rendering template: {e}"
            )

    async def _extract_node_results(
        self,
        node: WorkflowNode,
        job: Job
    ) -> Dict[str, Any]:
        """
        Extract results from completed job output.

        Applies custom output parsers specified in the node configuration.
        Results from multiple parsers are merged into a single dictionary.

        Args:
            node: Node configuration with output_parsers
            job: Completed job with results

        Returns:
            Dictionary of extracted results
        """
        results: Dict[str, Any] = {}

        # Get results from database
        if job.key_results:
            results.update(job.key_results)

        if job.final_energy is not None:
            results["final_energy"] = job.final_energy

        # Apply custom output parsers if specified
        if node.output_parsers:
            work_dir = Path(job.work_dir)

            for parser_name in node.output_parsers:
                parser = self._get_output_parser(parser_name)

                if parser is None:
                    # Log warning but continue with other parsers
                    print(f"Warning: Parser '{parser_name}' not found in registry, skipping")
                    continue

                try:
                    # Execute parser and merge results
                    parsed = await parser(work_dir)
                    if parsed:
                        results.update(parsed)
                except Exception as e:
                    # Log error but don't fail the workflow
                    print(f"Warning: Parser '{parser_name}' failed for job {job.id}: {e}")
                    continue

        return results

    async def _handle_node_failure(
        self,
        workflow_id: int,
        node_id: str,
        job_id: int,
        error: str
    ) -> None:
        """
        Handle failure of a workflow node according to its failure policy.

        Args:
            workflow_id: Workflow containing node
            node_id: ID of failed node
            job_id: Database job ID
            error: Error message
        """
        workflow = self._workflows[workflow_id]
        state = self._workflow_states[workflow_id]
        node = self._node_lookup[workflow_id][node_id]

        # Get failure policy (node-specific or workflow default)
        policy = node.failure_policy or workflow.default_failure_policy

        # Handle based on policy
        if policy == FailurePolicy.RETRY and node.retry_count < node.max_retries:
            # Increment retry count first
            node.retry_count += 1

            # Emit event with updated retry count
            self._emit_event(NodeFailed(
                workflow_id=workflow_id,
                node_id=node_id,
                job_id=job_id,
                error=error,
                retry_count=node.retry_count
            ))

            # Retry the node
            node.status = NodeStatus.PENDING
            state.running_nodes.discard(node_id)
            await self._submit_node(workflow_id, node)

        elif policy == FailurePolicy.SKIP_DEPENDENTS:
            # Emit event
            self._emit_event(NodeFailed(
                workflow_id=workflow_id,
                node_id=node_id,
                job_id=job_id,
                error=error,
                retry_count=node.retry_count
            ))

            # Mark node as failed
            node.status = NodeStatus.FAILED
            state.failed_nodes.add(node_id)
            state.running_nodes.discard(node_id)

            # Skip all dependent nodes
            await self._skip_dependent_nodes(workflow_id, node_id)

            # Check if workflow can continue
            await self._check_workflow_completion(workflow_id)

        elif policy == FailurePolicy.CONTINUE:
            # Emit event
            self._emit_event(NodeFailed(
                workflow_id=workflow_id,
                node_id=node_id,
                job_id=job_id,
                error=error,
                retry_count=node.retry_count
            ))

            # Mark as failed but continue
            node.status = NodeStatus.FAILED
            state.failed_nodes.add(node_id)
            state.running_nodes.discard(node_id)

            # Continue with independent nodes
            await self._submit_ready_nodes(workflow_id)
            await self._check_workflow_completion(workflow_id)

        else:  # ABORT
            # Emit event
            self._emit_event(NodeFailed(
                workflow_id=workflow_id,
                node_id=node_id,
                job_id=job_id,
                error=error,
                retry_count=node.retry_count
            ))

            # Abort entire workflow
            node.status = NodeStatus.FAILED
            state.failed_nodes.add(node_id)
            state.running_nodes.discard(node_id)
            state.status = WorkflowStatus.FAILED
            state.completed_at = datetime.now()

            self._emit_event(WorkflowFailed(
                workflow_id=workflow_id,
                reason=f"Node {node_id} failed: {error}"
            ))

    async def _skip_dependent_nodes(self, workflow_id: int, failed_node_id: str) -> None:
        """
        Skip all nodes that depend on a failed node.

        Args:
            workflow_id: Workflow containing nodes
            failed_node_id: ID of failed node
        """
        workflow = self._workflows[workflow_id]
        state = self._workflow_states[workflow_id]

        # Find all nodes that depend on failed_node_id
        to_skip = []
        for node in workflow.nodes:
            if failed_node_id in node.dependencies:
                to_skip.append(node)

        # Recursively skip dependent nodes
        while to_skip:
            node = to_skip.pop(0)
            if node.status == NodeStatus.PENDING:
                node.status = NodeStatus.SKIPPED

                # Find nodes that depend on this skipped node
                for other in workflow.nodes:
                    if node.node_id in other.dependencies:
                        if other not in to_skip:
                            to_skip.append(other)

    async def _check_workflow_completion(self, workflow_id: int) -> None:
        """
        Check if workflow has completed (all nodes processed).

        Args:
            workflow_id: Workflow to check
        """
        workflow = self._workflows[workflow_id]
        state = self._workflow_states[workflow_id]

        # Count node statuses
        total_nodes = len(workflow.nodes)
        processed_nodes = len(state.completed_nodes) + len(state.failed_nodes)

        # Calculate progress
        state.progress = (processed_nodes / total_nodes) * 100 if total_nodes > 0 else 0

        # Check if all nodes are in terminal state
        all_done = all(
            node.status in (
                NodeStatus.COMPLETED,
                NodeStatus.FAILED,
                NodeStatus.SKIPPED
            )
            for node in workflow.nodes
        )

        if all_done and state.status == WorkflowStatus.RUNNING:
            # Workflow is complete
            state.completed_at = datetime.now()

            if len(state.failed_nodes) == 0:
                state.status = WorkflowStatus.COMPLETED
                self._emit_event(WorkflowCompleted(
                    workflow_id=workflow_id,
                    total_nodes=total_nodes,
                    successful_nodes=len(state.completed_nodes),
                    failed_nodes=0
                ))
            else:
                state.status = WorkflowStatus.FAILED
                self._emit_event(WorkflowFailed(
                    workflow_id=workflow_id,
                    reason=f"{len(state.failed_nodes)} nodes failed"
                ))

    async def _monitor_workflows(self) -> None:
        """
        Background task that monitors active workflows.

        This task runs continuously and:
        - Polls database for job status updates
        - Processes completed jobs
        - Triggers dependent nodes
        - Updates workflow state
        """
        while self._running:
            try:
                # Get all active workflows
                active_workflows = [
                    wf_id for wf_id, state in self._workflow_states.items()
                    if state.status == WorkflowStatus.RUNNING
                ]

                # Process each workflow
                for workflow_id in active_workflows:
                    await self._process_workflow_updates(workflow_id)

                # Sleep before next check
                await asyncio.sleep(5.0)

            except Exception as e:
                # Log error but continue monitoring
                print(f"Error in workflow monitor: {e}")
                await asyncio.sleep(5.0)

    async def _process_workflow_updates(self, workflow_id: int) -> None:
        """
        Process job status updates for a single workflow.

        Args:
            workflow_id: Workflow to process
        """
        if workflow_id not in self._workflows:
            return

        state = self._workflow_states[workflow_id]

        # Check running nodes
        for node_id in list(state.running_nodes):
            node = self._node_lookup[workflow_id][node_id]

            if node.job_id:
                job = self.database.get_job(node.job_id)

                if job and job.status in ("COMPLETED", "FAILED"):
                    # Process completion
                    await self.process_node_completion(workflow_id, node_id, node.job_id)

    def _emit_event(self, event: WorkflowEvent) -> None:
        """
        Emit a workflow lifecycle event.

        Args:
            event: Event to emit
        """
        if self.event_callback:
            try:
                self.event_callback(event)
            except Exception as e:
                # Log error but don't let it break orchestration
                print(f"Error in event callback: {e}")

    async def stop(self) -> None:
        """Stop the orchestrator and background monitoring."""
        self._running = False

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
