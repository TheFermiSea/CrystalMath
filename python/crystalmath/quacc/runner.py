"""JobRunner abstraction for workflow engine dispatch.

This module provides a unified interface for submitting and tracking jobs
across different workflow engines (Parsl, Covalent). The JobRunner ABC
defines the contract, and get_runner() factory returns the appropriate
implementation based on the configured engine.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, Optional
import uuid


class JobState(str, Enum):
    """Job execution states."""

    PENDING = "pending"      # Submitted, waiting to run
    RUNNING = "running"      # Currently executing
    COMPLETED = "completed"  # Finished successfully
    FAILED = "failed"        # Finished with error
    CANCELLED = "cancelled"  # User cancelled

    def is_terminal(self) -> bool:
        """Check if this is a terminal (final) state."""
        return self in (JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED)


class JobRunner(ABC):
    """Abstract base class for workflow engine runners.

    Implementations handle job submission and status tracking for specific
    workflow engines (Parsl, Covalent, etc.).

    Example:
        >>> runner = get_runner("parsl")
        >>> job_id = runner.submit("quacc.recipes.vasp.core.relax_job", atoms)
        >>> status = runner.get_status(job_id)
        >>> if status == JobState.COMPLETED:
        ...     result = runner.get_result(job_id)
    """

    @abstractmethod
    def submit(
        self,
        recipe_fullname: str,
        atoms: Any,
        cluster_name: str,
        **kwargs,
    ) -> str:
        """Submit a job for execution.

        Args:
            recipe_fullname: Full path to quacc recipe
                (e.g., "quacc.recipes.vasp.core.relax_job")
            atoms: ASE Atoms object
            cluster_name: Name of cluster configuration to use
            **kwargs: Additional recipe parameters

        Returns:
            Job ID (UUID string) for tracking

        Raises:
            ValueError: If recipe cannot be found
            RuntimeError: If submission fails
        """
        pass

    @abstractmethod
    def get_status(self, job_id: str) -> JobState:
        """Get current job state (non-blocking).

        Args:
            job_id: Job ID returned from submit()

        Returns:
            Current job state

        Raises:
            KeyError: If job_id is unknown
        """
        pass

    @abstractmethod
    def get_result(self, job_id: str) -> Optional[Dict]:
        """Get job result if complete.

        Args:
            job_id: Job ID returned from submit()

        Returns:
            - Result dictionary if job completed successfully
            - {"error": str} if job failed
            - None if job still running

        Raises:
            KeyError: If job_id is unknown
        """
        pass

    @abstractmethod
    def cancel(self, job_id: str) -> bool:
        """Attempt to cancel a job.

        Args:
            job_id: Job ID returned from submit()

        Returns:
            True if cancellation was requested (may not be immediate)

        Raises:
            KeyError: If job_id is unknown
        """
        pass

    def _import_recipe(self, recipe_fullname: str) -> Any:
        """Import a recipe function by its full path.

        Args:
            recipe_fullname: e.g., "quacc.recipes.vasp.core.relax_job"

        Returns:
            The recipe function

        Raises:
            ValueError: If recipe cannot be imported
        """
        try:
            parts = recipe_fullname.rsplit(".", 1)
            if len(parts) != 2:
                raise ValueError(f"Invalid recipe path: {recipe_fullname}")

            module_path, func_name = parts
            module = __import__(module_path, fromlist=[func_name])
            return getattr(module, func_name)
        except (ImportError, AttributeError) as e:
            raise ValueError(f"Cannot import recipe {recipe_fullname}: {e}") from e

    @staticmethod
    def generate_job_id() -> str:
        """Generate a unique job ID."""
        return str(uuid.uuid4())


def get_runner(engine: str) -> JobRunner:
    """Factory to get runner for configured workflow engine.

    Args:
        engine: Workflow engine name ("parsl" or "covalent")

    Returns:
        JobRunner instance for the engine

    Raises:
        ValueError: If engine is not supported
        ImportError: If engine dependencies not installed

    Example:
        >>> from crystalmath.quacc.engines import get_workflow_engine
        >>> engine = get_workflow_engine()
        >>> runner = get_runner(engine)
    """
    engine_lower = engine.lower()

    if engine_lower == "parsl":
        from crystalmath.quacc.parsl_runner import ParslRunner
        return ParslRunner()
    elif engine_lower == "covalent":
        from crystalmath.quacc.covalent_runner import CovalentRunner
        return CovalentRunner()
    else:
        raise ValueError(
            f"Unsupported workflow engine: {engine}. "
            "Supported engines: parsl, covalent"
        )


# Registry of active runners (singleton pattern)
_active_runners: Dict[str, JobRunner] = {}


def get_or_create_runner(engine: str) -> JobRunner:
    """Get or create a singleton runner for the engine.

    This ensures job tracking state persists across handler calls.

    Args:
        engine: Workflow engine name

    Returns:
        JobRunner instance (cached)
    """
    engine_lower = engine.lower()
    if engine_lower not in _active_runners:
        _active_runners[engine_lower] = get_runner(engine_lower)
    return _active_runners[engine_lower]
