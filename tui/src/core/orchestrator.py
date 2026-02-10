"""
Workflow orchestration for CRYSTAL calculations.

This module provides the WorkflowOrchestrator class which coordinates
the execution of multi-step workflows by managing job dependencies,
parameter resolution, and error handling.
"""

import asyncio
import atexit
import json
import logging
import os
import re
import shlex
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Set
from jinja2 import Template, TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment

logger = logging.getLogger(__name__)


# Security: Pattern for sanitizing IDs used in filesystem paths
# Allows alphanumeric, dashes, and underscores only
_SAFE_ID_PATTERN = re.compile(r'[^a-zA-Z0-9_-]')


def _sanitize_path_component(value: str) -> str:
    """
    Sanitize a string for safe use as a filesystem path component.

    Removes or replaces characters that could be used for path traversal
    or command injection (/, .., etc.).

    Args:
        value: The string to sanitize

    Returns:
        A safe string containing only alphanumeric chars, dashes, and underscores
    """
    # Replace any unsafe characters with underscores
    sanitized = _SAFE_ID_PATTERN.sub('_', str(value))
    # Collapse multiple underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    # Strip leading/trailing underscores
    return sanitized.strip('_') or 'unknown'

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


class NodeType(Enum):
    """Type of workflow node."""
    JOB = "job"  # Single DFT calculation job (default)
    BATCH = "batch"  # Expands to N parallel jobs (foreach, parameter_sweep)
    SCRIPT = "script"  # Run a shell script or command
    DATA_TRANSFER = "data_transfer"  # Transfer files between steps


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

    For batch nodes (node_type=BATCH), the node expands to multiple parallel
    jobs based on foreach or parameter_sweep configuration.

    For script nodes (node_type=SCRIPT), the command is executed directly
    without DFT code invocation.

    For data_transfer nodes (node_type=DATA_TRANSFER), files are copied
    between directories with optional renaming.
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

    # Node type configuration
    node_type: NodeType = NodeType.JOB

    # Batch node configuration (node_type=BATCH)
    foreach: Optional[str] = None  # Glob pattern to expand (e.g., "POSCAR-*")
    parameter_sweep: Optional[List[Dict[str, Any]]] = None  # List of parameter variations
    max_parallel: int = 0  # Max concurrent batch jobs (0 = unlimited)
    batch_jobs: List[int] = field(default_factory=list)  # Job IDs of expanded batch jobs
    batch_results: List[Dict[str, Any]] = field(default_factory=list)  # Results from batch jobs

    # Script node configuration (node_type=SCRIPT)
    command: Optional[str] = None  # Shell command to execute
    script: Optional[str] = None  # Path to script file

    # Data transfer configuration (node_type=DATA_TRANSFER)
    source_files: List[str] = field(default_factory=list)  # Files to copy
    file_renames: Dict[str, str] = field(default_factory=dict)  # Rename mapping

    # Conditional execution
    condition: Optional[str] = None  # Jinja2 expression for conditional execution

    # DFT code (for multi-code workflows)
    code: Optional[str] = None  # DFT code name (e.g., "vasp", "qe", "yambo")


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

    # -------------------------------------------------------------------------
    # Async database wrappers to prevent blocking the event loop
    # -------------------------------------------------------------------------

    async def _db_get_job(self, job_id: int) -> Optional[Job]:
        """Get job from database without blocking the event loop."""
        return await asyncio.to_thread(self.database.get_job, job_id)

    async def _db_create_job(self, name: str, work_dir: str, input_content: str) -> int:
        """Create job in database without blocking the event loop."""
        return await asyncio.to_thread(self.database.create_job, name, work_dir, input_content)

    async def _db_update_status(self, job_id: int, status: str) -> None:
        """Update job status in database without blocking the event loop."""
        await asyncio.to_thread(self.database.update_status, job_id, status)

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

        Note:
            For glob patterns with multiple matches, uses deterministic sorting:
            alphabetical by name (to ensure reproducible behavior), then by
            modification time as tie-breaker.
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
                # Glob pattern - use deterministic sorting
                matches = list(work_dir.glob(pattern))
                if matches:
                    # Sort by name first (deterministic), then by mtime (tie-breaker)
                    # This ensures reproducible behavior even with multiple .out files
                    sorted_matches = sorted(
                        matches,
                        key=lambda p: (p.name, -p.stat().st_mtime)
                    )
                    # Prefer files that look like main output (not slurm logs, etc.)
                    for match in sorted_matches:
                        name = match.name.lower()
                        # Skip SLURM job output files (these are scheduler logs)
                        if name.startswith("slurm-") or name.startswith("job."):
                            continue
                        return match
                    # Fall back to first match if no preferred files found
                    return sorted_matches[0]
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

        Uses memory-efficient tail reading to avoid loading multi-GB files entirely.

        Args:
            work_dir: Job work directory containing output file

        Returns:
            Dictionary with "final_energy" key if found, empty dict otherwise
        """
        output_file = self._find_output_file(work_dir)
        if output_file is None:
            return {}

        try:
            # Memory-efficient: read only last 100KB where final energy appears
            # DFT outputs can be multi-GB, but SCF results are near the end
            tail_bytes = 100 * 1024  # 100 KB should be enough for final output
            file_size = output_file.stat().st_size

            with open(output_file, "r") as f:
                if file_size > tail_bytes:
                    f.seek(file_size - tail_bytes)
                    f.readline()  # Skip partial line after seek
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
            logger.warning(f"Failed to parse energy from {output_file}: {e}")
            return {}

    async def _parse_bandgap(self, work_dir: Path) -> Dict[str, Any]:
        """
        Extract band gap from CRYSTAL output.

        Searches for band structure analysis lines in the output.
        Typical format: "ENERGY BAND GAP:     X.XXX eV"

        Uses memory-efficient tail reading to avoid loading multi-GB files entirely.

        Args:
            work_dir: Job work directory containing output file

        Returns:
            Dictionary with "bandgap" key if found, empty dict otherwise
        """
        output_file = self._find_output_file(work_dir)
        if output_file is None:
            return {}

        try:
            # Memory-efficient: read only last 200KB where band gap info appears
            # Band gap analysis is typically near the end of the output
            tail_bytes = 200 * 1024  # 200 KB for band structure section
            file_size = output_file.stat().st_size

            with open(output_file, "r") as f:
                if file_size > tail_bytes:
                    f.seek(file_size - tail_bytes)
                    f.readline()  # Skip partial line after seek
                lines = f.readlines()

            # Search for band gap line
            # Check for direct/indirect first (more specific pattern)
            for line in lines:
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
            logger.warning(f"Failed to parse band gap from {output_file}: {e}")
            return {}

    async def _parse_lattice(self, work_dir: Path) -> Dict[str, Any]:
        """
        Extract lattice parameters from CRYSTAL output.

        Searches for the final geometry section with cell parameters.
        Typical format:
        "FINAL OPTIMIZED GEOMETRY"
        "PRIMITIVE CELL"
        "A      B      C   ALPHA  BETA  GAMMA"

        Uses memory-efficient tail reading to avoid loading multi-GB files entirely.

        Args:
            work_dir: Job work directory containing output file

        Returns:
            Dictionary with lattice parameter keys if found, empty dict otherwise
        """
        output_file = self._find_output_file(work_dir)
        if output_file is None:
            return {}

        try:
            # Memory-efficient: read only last 500KB where final geometry appears
            # Final optimized geometry is at the end of the output
            tail_bytes = 500 * 1024  # 500 KB for final geometry section
            file_size = output_file.stat().st_size

            with open(output_file, "r") as f:
                if file_size > tail_bytes:
                    f.seek(file_size - tail_bytes)
                    f.readline()  # Skip partial line after seek
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
            logger.warning(f"Failed to parse lattice parameters from {output_file}: {e}")
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
            ValueError: If path validation fails (path traversal attempt)
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        pid = os.getpid()

        # Security: Sanitize IDs to prevent path traversal attacks
        # This prevents "../" or other dangerous path components
        safe_workflow_id = _sanitize_path_component(str(workflow_id))
        safe_node_id = _sanitize_path_component(node_id)

        dir_name = f"workflow_{safe_workflow_id}_node_{safe_node_id}_{timestamp}_{pid}"
        work_dir = self._scratch_base / dir_name

        # Security: Validate that the resolved path is within scratch_base
        # This is defense-in-depth against path traversal
        resolved_work_dir = work_dir.resolve()
        resolved_scratch_base = self._scratch_base.resolve()
        if not str(resolved_work_dir).startswith(str(resolved_scratch_base) + os.sep):
            raise ValueError(
                f"Security violation: work directory '{work_dir}' escapes scratch base. "
                f"Possible path traversal attempt with workflow_id={workflow_id}, node_id={node_id}"
            )

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

        # Get job from database (async to prevent event loop blocking)
        job = await self._db_get_job(job_id)
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

        This method dispatches to type-specific handlers based on node_type:
        - JOB: Submit a single DFT calculation
        - BATCH: Expand and submit multiple parallel jobs
        - SCRIPT: Execute a shell command
        - DATA_TRANSFER: Copy files between directories

        Args:
            workflow_id: Workflow containing node
            node: Node to submit
        """
        workflow = self._workflows[workflow_id]
        state = self._workflow_states[workflow_id]

        # Check conditional execution
        if node.condition:
            try:
                if not await self._evaluate_condition(workflow_id, node):
                    # Condition not met - skip this node
                    node.status = NodeStatus.SKIPPED
                    logger.info(f"Skipping node {node.node_id}: condition not met")
                    await self._check_workflow_completion(workflow_id)
                    return
            except Exception as e:
                logger.warning(f"Error evaluating condition for {node.node_id}: {e}")

        # Dispatch based on node type
        if node.node_type == NodeType.BATCH:
            await self._submit_batch_node(workflow_id, node)
            return
        elif node.node_type == NodeType.SCRIPT:
            await self._submit_script_node(workflow_id, node)
            return
        elif node.node_type == NodeType.DATA_TRANSFER:
            await self._submit_data_transfer_node(workflow_id, node)
            return

        # Default: JOB type
        try:
            # Resolve parameters
            resolved_params = await self._resolve_parameters(workflow_id, node)
            node.resolved_parameters = resolved_params

            # Render input template
            input_content = self._render_template(node.template, resolved_params)

            # Create work directory using environment-based scratch location
            work_dir = self._create_work_directory(workflow_id, node.node_id)

            # Create database job (async to prevent event loop blocking)
            job_id = await self._db_create_job(
                name=node.job_name,
                work_dir=str(work_dir),
                input_content=input_content
            )

            node.job_id = job_id
            node.status = NodeStatus.QUEUED

            # Update state
            state.running_nodes.add(node.node_id)

            # Get job from database to access cluster_id and runner_type
            job = await self._db_get_job(job_id)
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
            await self._db_update_status(job_id, "QUEUED")

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
                    logger.warning(f"Parser '{parser_name}' not found in registry, skipping")
                    continue

                try:
                    # Execute parser and merge results
                    parsed = await parser(work_dir)
                    if parsed:
                        results.update(parsed)
                except Exception as e:
                    # Log error but don't fail the workflow
                    logger.warning(f"Parser '{parser_name}' failed for job {job.id}: {e}")
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

            # Clean up in-memory state to prevent memory leaks
            # Schedule cleanup after a short delay to allow event handlers to complete
            asyncio.get_event_loop().call_later(
                5.0,  # 5 second delay
                self._cleanup_completed_workflow,
                workflow_id
            )

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
                logger.error(f"Error in workflow monitor: {e}")
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
                job = await self._db_get_job(node.job_id)

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
                logger.error(f"Error in event callback: {e}")

    # -------------------------------------------------------------------------
    # Batch, Script, and Data Transfer Node Handlers
    # -------------------------------------------------------------------------

    async def _evaluate_condition(self, workflow_id: int, node: WorkflowNode) -> bool:
        """
        Evaluate a node's conditional expression.

        The condition is a Jinja2 expression that has access to:
        - Global workflow parameters
        - Results from completed dependency nodes

        Args:
            workflow_id: Workflow containing the node
            node: Node with condition to evaluate

        Returns:
            True if condition is met, False otherwise
        """
        if not node.condition:
            return True

        workflow = self._workflows[workflow_id]

        # Build context with all available data
        context = dict(workflow.global_parameters)

        # Add dependency results
        for dep_id in node.dependencies:
            dep_node = self._node_lookup[workflow_id].get(dep_id)
            if dep_node and dep_node.results:
                context[dep_id] = dep_node.results

        # Evaluate condition
        try:
            template = self._jinja_env.from_string("{{ " + node.condition + " }}")
            result = template.render(context)
            # Convert string result to boolean
            return result.lower() in ("true", "1", "yes")
        except Exception as e:
            logger.warning(f"Condition evaluation failed for {node.node_id}: {e}")
            return True  # Default to executing on error

    async def _submit_batch_node(self, workflow_id: int, node: WorkflowNode) -> None:
        """
        Expand and submit a batch node as multiple parallel jobs.

        Batch nodes can expand based on:
        - foreach: Glob pattern matching files (e.g., "POSCAR-*")
        - parameter_sweep: List of parameter dictionaries

        Args:
            workflow_id: Workflow containing the node
            node: Batch node to expand
        """
        workflow = self._workflows[workflow_id]
        state = self._workflow_states[workflow_id]

        try:
            # Determine expansion source
            items_to_process: List[Dict[str, Any]] = []

            if node.foreach:
                # Expand glob pattern from dependency work directory
                items_to_process = await self._expand_foreach(workflow_id, node)

            elif node.parameter_sweep:
                # Use parameter sweep list directly
                items_to_process = node.parameter_sweep

            if not items_to_process:
                logger.warning(f"Batch node {node.node_id} has nothing to expand")
                node.status = NodeStatus.COMPLETED
                node.results = {"batch_count": 0}
                state.completed_nodes.add(node.node_id)
                await self._check_workflow_completion(workflow_id)
                return

            logger.info(f"Expanding batch node {node.node_id} to {len(items_to_process)} jobs")

            # Track this as a batch node in progress
            node.status = NodeStatus.RUNNING
            state.running_nodes.add(node.node_id)
            node.batch_jobs = []
            node.batch_results = []

            # Submit each batch item
            for idx, item_params in enumerate(items_to_process):
                # Merge base parameters with item-specific params
                merged_params = dict(node.parameters)
                merged_params.update(item_params)
                merged_params["_batch_index"] = idx
                merged_params["_batch_total"] = len(items_to_process)

                # Create sub-job
                sub_node = WorkflowNode(
                    node_id=f"{node.node_id}_batch_{idx}",
                    job_name=f"{node.job_name}_{idx}",
                    template=node.template,
                    parameters=merged_params,
                    dependencies=[],  # Already satisfied
                    node_type=NodeType.JOB,
                    failure_policy=node.failure_policy,
                    output_parsers=node.output_parsers,
                    code=node.code,
                )

                # Resolve and submit
                resolved_params = await self._resolve_parameters(workflow_id, sub_node)
                sub_node.resolved_parameters = resolved_params

                # Render input template
                input_content = self._render_template(node.template, resolved_params)

                # Create work directory
                work_dir = self._create_work_directory(workflow_id, sub_node.node_id)

                # Create database job (async to prevent event loop blocking)
                job_id = await self._db_create_job(
                    name=sub_node.job_name,
                    work_dir=str(work_dir),
                    input_content=input_content
                )

                node.batch_jobs.append(job_id)
                sub_node.job_id = job_id

                # Register temporary node for tracking
                self._node_lookup[workflow_id][sub_node.node_id] = sub_node

                # Get job for cluster info
                job = await self._db_get_job(job_id)
                if not job:
                    continue

                # Create batch completion callback
                async def batch_job_callback(
                    completed_job_id: int,
                    status: str,
                    parent_node: WorkflowNode = node,
                    batch_idx: int = idx
                ) -> None:
                    await self._process_batch_job_completion(
                        workflow_id, parent_node, completed_job_id, status, batch_idx
                    )

                # Submit to queue
                await self.queue_manager.enqueue(
                    job_id=job_id,
                    priority=2,
                    dependencies=None,
                    runner_type=job.runner_type or "local",
                    cluster_id=job.cluster_id,
                    user_id=None
                )
                self.queue_manager.register_callback(job_id, batch_job_callback)
                await self._db_update_status(job_id, "QUEUED")

            # Emit batch start event
            self._emit_event(NodeStarted(
                workflow_id=workflow_id,
                node_id=node.node_id,
                job_id=node.batch_jobs[0] if node.batch_jobs else 0
            ))

        except Exception as e:
            await self._handle_node_failure(workflow_id, node.node_id, 0, str(e))

    async def _expand_foreach(
        self,
        workflow_id: int,
        node: WorkflowNode
    ) -> List[Dict[str, Any]]:
        """
        Expand a foreach glob pattern into parameter dictionaries.

        Searches in the work directories of dependency nodes.

        Args:
            workflow_id: Workflow containing the node
            node: Node with foreach pattern

        Returns:
            List of parameter dictionaries with _file key
        """
        if not node.foreach:
            return []

        items = []
        pattern = node.foreach

        # Search dependency work directories for matching files
        for dep_id in node.dependencies:
            dep_node = self._node_lookup[workflow_id].get(dep_id)
            if not dep_node or not dep_node.job_id:
                continue

            dep_job = await self._db_get_job(dep_node.job_id)
            if not dep_job:
                continue

            dep_work_dir = Path(dep_job.work_dir)
            matches = list(dep_work_dir.glob(pattern))

            for match in sorted(matches):
                items.append({
                    "_file": str(match),
                    "_filename": match.name,
                    "_stem": match.stem,
                    "_source_dir": str(dep_work_dir),
                })

        return items

    async def _process_batch_job_completion(
        self,
        workflow_id: int,
        node: WorkflowNode,
        job_id: int,
        status: str,
        batch_idx: int
    ) -> None:
        """
        Process completion of a single batch sub-job.

        Checks if all batch jobs are complete and updates parent node status.

        Args:
            workflow_id: Workflow containing the node
            node: Parent batch node
            job_id: Completed sub-job ID
            status: Job status ("COMPLETED" or "FAILED")
            batch_idx: Index of the batch item
        """
        state = self._workflow_states[workflow_id]

        # Get job results (async to prevent event loop blocking)
        job = await self._db_get_job(job_id)
        if job and status == "COMPLETED":
            result = {
                "batch_idx": batch_idx,
                "job_id": job_id,
                "final_energy": job.final_energy,
                "key_results": job.key_results,
            }
            node.batch_results.append(result)

        # Check if all batch jobs are complete
        completed_count = 0
        failed_count = 0

        for batch_job_id in node.batch_jobs:
            batch_job = await self._db_get_job(batch_job_id)
            if batch_job:
                if batch_job.status == "COMPLETED":
                    completed_count += 1
                elif batch_job.status == "FAILED":
                    failed_count += 1

        total = len(node.batch_jobs)
        logger.debug(
            f"Batch {node.node_id}: {completed_count}/{total} completed, "
            f"{failed_count} failed"
        )

        # Check if batch is complete
        if completed_count + failed_count == total:
            # All jobs finished
            if failed_count > 0 and node.failure_policy == FailurePolicy.ABORT:
                # Batch failed
                node.status = NodeStatus.FAILED
                state.failed_nodes.add(node.node_id)
                state.running_nodes.discard(node.node_id)
                await self._handle_node_failure(
                    workflow_id,
                    node.node_id,
                    0,
                    f"{failed_count}/{total} batch jobs failed"
                )
            else:
                # Batch completed (possibly with some failures)
                node.status = NodeStatus.COMPLETED
                node.results = {
                    "batch_count": total,
                    "completed": completed_count,
                    "failed": failed_count,
                    "items": node.batch_results,
                }
                state.completed_nodes.add(node.node_id)
                state.running_nodes.discard(node.node_id)

                self._emit_event(NodeCompleted(
                    workflow_id=workflow_id,
                    node_id=node.node_id,
                    job_id=0,
                    results=node.results
                ))

                # Submit dependent nodes
                await self._submit_ready_nodes(workflow_id)
                await self._check_workflow_completion(workflow_id)

    async def _submit_script_node(self, workflow_id: int, node: WorkflowNode) -> None:
        """
        Execute a script or shell command node.

        Script nodes run a command without DFT code invocation.
        Useful for pre/post-processing, format conversion, etc.

        Args:
            workflow_id: Workflow containing the node
            node: Script node to execute
        """
        workflow = self._workflows[workflow_id]
        state = self._workflow_states[workflow_id]

        try:
            # Resolve parameters
            resolved_params = await self._resolve_parameters(workflow_id, node)
            node.resolved_parameters = resolved_params

            # Get command
            command = node.command
            if not command and node.script:
                # Read script file and use as command
                command = f"bash {node.script}"

            if not command:
                raise OrchestratorError(f"Script node {node.node_id} has no command")

            # Render command template
            command = self._jinja_env.from_string(command).render(resolved_params)

            # Security: Validate executable against allowlist
            _SAFE_EXECUTABLES = {
                "bash", "sh",
                "crystal", "crystalOMP", "properties",
                "vasp", "vasp_std", "vasp_gam", "vasp_ncl",
                "pw.x", "ph.x", "pp.x", "bands.x", "dos.x", "projwfc.x",
                "mpirun", "mpiexec", "srun",
                "yambo", "p2y",
                "cp", "mv", "cat", "mkdir", "echo", "grep", "sed", "awk",
            }
            cmd_parts = shlex.split(command)
            executable = Path(cmd_parts[0]).name if cmd_parts else ""
            if executable not in _SAFE_EXECUTABLES:
                raise OrchestratorError(
                    f"Script node {node.node_id}: executable '{executable}' "
                    f"not in allowlist. Allowed: {sorted(_SAFE_EXECUTABLES)}"
                )

            # Determine working directory (use last dependency's work_dir)
            work_dir = None
            for dep_id in reversed(node.dependencies):
                dep_node = self._node_lookup[workflow_id].get(dep_id)
                if dep_node and dep_node.job_id:
                    dep_job = await self._db_get_job(dep_node.job_id)
                    if dep_job:
                        work_dir = Path(dep_job.work_dir)
                        break

            if not work_dir:
                work_dir = self._create_work_directory(workflow_id, node.node_id)

            node.status = NodeStatus.RUNNING
            state.running_nodes.add(node.node_id)

            # Execute command using async subprocess (exec, not shell)
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd_parts,
                    cwd=str(work_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=3600  # 1 hour timeout
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    raise asyncio.TimeoutError("Script execution timed out")

                returncode = process.returncode
                stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
                stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""
            except asyncio.TimeoutError:
                await self._handle_node_failure(
                    workflow_id, node.node_id, 0, "Script timed out"
                )
                return

            if returncode == 0:
                node.status = NodeStatus.COMPLETED
                node.results = {
                    "returncode": 0,
                    "stdout": stdout_text[:10000],  # Truncate
                    "stderr": stderr_text[:10000],
                }
                state.completed_nodes.add(node.node_id)
                state.running_nodes.discard(node.node_id)

                self._emit_event(NodeCompleted(
                    workflow_id=workflow_id,
                    node_id=node.node_id,
                    job_id=0,
                    results=node.results
                ))

                await self._submit_ready_nodes(workflow_id)
                await self._check_workflow_completion(workflow_id)
            else:
                await self._handle_node_failure(
                    workflow_id,
                    node.node_id,
                    0,
                    f"Script failed: {stderr_text[:500]}"
                )

        except asyncio.TimeoutError:
            await self._handle_node_failure(
                workflow_id, node.node_id, 0, "Script timed out"
            )
        except Exception as e:
            await self._handle_node_failure(workflow_id, node.node_id, 0, str(e))

    async def _submit_data_transfer_node(
        self,
        workflow_id: int,
        node: WorkflowNode
    ) -> None:
        """
        Execute a data transfer node.

        Copies files between workflow step directories, optionally renaming them.

        Args:
            workflow_id: Workflow containing the node
            node: Data transfer node to execute
        """
        workflow = self._workflows[workflow_id]
        state = self._workflow_states[workflow_id]

        try:
            node.status = NodeStatus.RUNNING
            state.running_nodes.add(node.node_id)

            # Get source directory from last dependency
            source_dir = None
            for dep_id in reversed(node.dependencies):
                dep_node = self._node_lookup[workflow_id].get(dep_id)
                if dep_node and dep_node.job_id:
                    dep_job = await self._db_get_job(dep_node.job_id)
                    if dep_job:
                        source_dir = Path(dep_job.work_dir)
                        break

            if not source_dir:
                raise OrchestratorError(
                    f"Data transfer node {node.node_id} has no source directory"
                )

            # Create destination directory
            dest_dir = self._create_work_directory(workflow_id, node.node_id)

            # Copy files using asyncio.to_thread to avoid blocking event loop
            copied_files = []
            for pattern in node.source_files:
                matches = list(source_dir.glob(pattern))
                for src_file in matches:
                    if src_file.is_file():
                        # Apply rename if specified
                        dest_name = node.file_renames.get(src_file.name, src_file.name)
                        dest_file = dest_dir / dest_name

                        await asyncio.to_thread(shutil.copy2, src_file, dest_file)
                        copied_files.append({
                            "source": str(src_file),
                            "dest": str(dest_file),
                            "renamed": src_file.name != dest_name,
                        })

            # Mark as completed
            node.status = NodeStatus.COMPLETED
            node.results = {
                "source_dir": str(source_dir),
                "dest_dir": str(dest_dir),
                "files_copied": len(copied_files),
                "files": copied_files,
            }
            state.completed_nodes.add(node.node_id)
            state.running_nodes.discard(node.node_id)

            # Create a dummy job entry for work_dir tracking (async)
            job_id = await self._db_create_job(
                name=node.job_name,
                work_dir=str(dest_dir),
                input_content=""
            )
            node.job_id = job_id
            await self._db_update_status(job_id, "COMPLETED")

            self._emit_event(NodeCompleted(
                workflow_id=workflow_id,
                node_id=node.node_id,
                job_id=job_id,
                results=node.results
            ))

            await self._submit_ready_nodes(workflow_id)
            await self._check_workflow_completion(workflow_id)

        except Exception as e:
            await self._handle_node_failure(workflow_id, node.node_id, 0, str(e))

    def _cleanup_completed_workflow(self, workflow_id: int) -> None:
        """
        Clean up in-memory state for a completed workflow.

        This prevents memory leaks by removing workflow data structures
        after the workflow reaches a terminal state.

        Args:
            workflow_id: ID of the completed workflow
        """
        # Remove from in-memory tracking
        self._workflows.pop(workflow_id, None)
        self._workflow_states.pop(workflow_id, None)
        self._node_lookup.pop(workflow_id, None)

        # Clean up callback tracking for this workflow's jobs
        callbacks_to_remove = [
            job_id for job_id, (wf_id, _) in self._node_callbacks.items()
            if wf_id == workflow_id
        ]
        for job_id in callbacks_to_remove:
            self._node_callbacks.pop(job_id, None)

        # Clean up work directories for this workflow
        dirs_to_remove = [
            work_dir for work_dir, wf_id in self._work_dirs.items()
            if wf_id == workflow_id
        ]
        for work_dir in dirs_to_remove:
            try:
                if work_dir.exists():
                    shutil.rmtree(work_dir, ignore_errors=True)
                self._work_dirs.pop(work_dir, None)
            except Exception:
                pass

        logger.info(f"Cleaned up completed workflow {workflow_id}")

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
