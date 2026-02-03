"""Mock runner for testing job submission without real workflow engines.

This module provides a MockRunner that simulates job lifecycle for testing
without requiring Parsl/Covalent dependencies.

Example:
    >>> runner = MockRunner()
    >>> job_id = runner.submit("relax_job", atoms, "local")
    >>> runner.get_status(job_id)  # Returns RUNNING (first call advances state)
    JobState.RUNNING
    >>> runner.get_status(job_id)  # Returns COMPLETED (second call)
    JobState.COMPLETED
"""

import uuid
from enum import Enum
from typing import Any, Dict, Optional, Set

from crystalmath.quacc.runner import JobRunner, JobState


class MockJobState(str, Enum):
    """Internal state for mock jobs."""

    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MockRunner(JobRunner):
    """Mock runner for testing.

    Jobs follow a predictable lifecycle:
    - submit() -> PENDING
    - First get_status() -> RUNNING
    - Second get_status() -> COMPLETED (or FAILED if fail_job_ids contains job)

    This allows testing without Parsl/Covalent dependencies.

    Attributes:
        fail_job_ids: Set of job IDs that should fail on completion
        custom_results: Dict of job_id -> custom result dict

    Example:
        >>> runner = MockRunner()
        >>> job_id = runner.submit("relax_job", atoms, "local")
        >>> # Mark job to fail
        >>> runner.set_fail(job_id)
        >>> runner.get_status(job_id)  # RUNNING
        >>> runner.get_status(job_id)  # FAILED
    """

    def __init__(self):
        """Initialize mock runner with empty state."""
        self._jobs: Dict[str, MockJobState] = {}
        self._status_calls: Dict[str, int] = {}
        self._results: Dict[str, Dict] = {}
        self._recipes: Dict[str, str] = {}
        # Job IDs that should fail
        self.fail_job_ids: Set[str] = set()
        # Custom results per job
        self.custom_results: Dict[str, Dict] = {}

    def submit(
        self,
        recipe_fullname: str,
        atoms: Any,
        cluster_name: str,
        **kwargs,
    ) -> str:
        """Submit mock job, returns UUID.

        Args:
            recipe_fullname: Full path to recipe (stored but not imported)
            atoms: ASE Atoms object (used for formula in results)
            cluster_name: Cluster name (ignored in mock)
            **kwargs: Additional parameters (ignored in mock)

        Returns:
            Job ID (UUID string)
        """
        job_id = str(uuid.uuid4())
        self._jobs[job_id] = MockJobState.SUBMITTED
        self._status_calls[job_id] = 0
        self._recipes[job_id] = recipe_fullname

        # Store mock result
        formula = "MockFormula"
        if hasattr(atoms, "get_chemical_formula"):
            formula = atoms.get_chemical_formula()

        self._results[job_id] = {
            "results": {"energy": -123.456, "forces": [[0.01, 0.02, 0.03]]},
            "formula_pretty": formula,
            "dir_name": f"/tmp/mock_job_{job_id}",
        }

        return job_id

    def get_status(self, job_id: str) -> JobState:
        """Get mock job status, advancing state each call.

        State machine: SUBMITTED -> RUNNING -> COMPLETED/FAILED

        Args:
            job_id: Job ID from submit()

        Returns:
            Current job state

        Raises:
            ValueError: If job_id is unknown
        """
        if job_id not in self._jobs:
            raise ValueError(f"Unknown job: {job_id}")

        self._status_calls[job_id] += 1
        current = self._jobs[job_id]

        # State machine: SUBMITTED -> RUNNING -> COMPLETED/FAILED
        if current == MockJobState.SUBMITTED:
            self._jobs[job_id] = MockJobState.RUNNING
            return JobState.RUNNING
        elif current == MockJobState.RUNNING:
            if job_id in self.fail_job_ids:
                self._jobs[job_id] = MockJobState.FAILED
                return JobState.FAILED
            else:
                self._jobs[job_id] = MockJobState.COMPLETED
                return JobState.COMPLETED
        elif current == MockJobState.COMPLETED:
            return JobState.COMPLETED
        elif current == MockJobState.FAILED:
            return JobState.FAILED
        elif current == MockJobState.CANCELLED:
            return JobState.CANCELLED

        return JobState.PENDING

    def get_result(self, job_id: str) -> Optional[Dict]:
        """Get mock result if complete.

        Args:
            job_id: Job ID from submit()

        Returns:
            Result dict if completed, error dict if failed, None if still running

        Raises:
            ValueError: If job_id is unknown
        """
        if job_id not in self._jobs:
            raise ValueError(f"Unknown job: {job_id}")

        if self._jobs[job_id] == MockJobState.COMPLETED:
            if job_id in self.custom_results:
                return self.custom_results[job_id]
            return self._results.get(job_id)
        elif self._jobs[job_id] == MockJobState.FAILED:
            return {"error": "Mock job failed intentionally"}

        return None

    def cancel(self, job_id: str) -> bool:
        """Cancel mock job.

        Args:
            job_id: Job ID from submit()

        Returns:
            True if job was cancelled, False if not cancellable
        """
        if job_id not in self._jobs:
            return False

        current = self._jobs[job_id]
        if current in (MockJobState.SUBMITTED, MockJobState.RUNNING):
            self._jobs[job_id] = MockJobState.CANCELLED
            return True
        return False

    # ===== Test Helpers =====

    def set_fail(self, job_id: str) -> None:
        """Mark job to fail on next status check.

        Args:
            job_id: Job ID to mark for failure
        """
        self.fail_job_ids.add(job_id)

    def force_state(self, job_id: str, state: MockJobState) -> None:
        """Force job into specific state for testing.

        Args:
            job_id: Job ID to modify
            state: Target state
        """
        self._jobs[job_id] = state

    def set_custom_result(self, job_id: str, result: Dict) -> None:
        """Set custom result for a job.

        Args:
            job_id: Job ID
            result: Custom result dict
        """
        self.custom_results[job_id] = result

    def get_recipe(self, job_id: str) -> Optional[str]:
        """Get the recipe used for a job.

        Args:
            job_id: Job ID

        Returns:
            Recipe fullname or None if not found
        """
        return self._recipes.get(job_id)

    def clear(self) -> None:
        """Clear all job state (for test isolation)."""
        self._jobs.clear()
        self._status_calls.clear()
        self._results.clear()
        self._recipes.clear()
        self.fail_job_ids.clear()
        self.custom_results.clear()
