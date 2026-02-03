"""Covalent-based JobRunner implementation.

This module implements job submission and tracking using Covalent's
dispatch/result API.
"""

from typing import Any, Dict, Optional
import logging

from crystalmath.quacc.runner import JobRunner, JobState

logger = logging.getLogger(__name__)


class CovalentRunner(JobRunner):
    """JobRunner implementation using Covalent workflow engine.

    Covalent uses a dispatch/result pattern:
    - ct.dispatch() returns a dispatch_id
    - ct.get_result(dispatch_id, wait=False) for status polling
    - ct.cancel(dispatch_id) for cancellation

    Unlike Parsl futures, Covalent dispatch IDs are strings that can be
    persisted, but require the Covalent server to be running.
    """

    def __init__(self):
        """Initialize the Covalent runner."""
        # Map job_id -> covalent dispatch_id
        self._dispatch_ids: Dict[str, str] = {}
        self._job_metadata: Dict[str, Dict] = {}

        # Status mapping from Covalent to JobState
        self._status_map = {
            "NEW_OBJECT": JobState.PENDING,
            "PENDING_APPROVAL": JobState.PENDING,
            "PENDING": JobState.PENDING,
            "STARTING": JobState.RUNNING,
            "RUNNING": JobState.RUNNING,
            "POSTPROCESSING": JobState.RUNNING,
            "COMPLETED": JobState.COMPLETED,
            "FAILED": JobState.FAILED,
            "CANCELLED": JobState.CANCELLED,
        }

    def submit(
        self,
        recipe_fullname: str,
        atoms: Any,
        cluster_name: str,
        **kwargs,
    ) -> str:
        """Submit a job via Covalent.

        Args:
            recipe_fullname: Full path to quacc recipe
            atoms: ASE Atoms object
            cluster_name: Name of cluster configuration (for executor selection)
            **kwargs: Additional recipe parameters

        Returns:
            Job ID (UUID string)
        """
        try:
            import covalent as ct
        except ImportError as e:
            raise RuntimeError(
                "Covalent is not installed. Install with: pip install covalent"
            ) from e

        # Import recipe dynamically
        recipe_func = self._import_recipe(recipe_fullname)

        # Generate job ID
        job_id = self.generate_job_id()

        # Create a lattice wrapper for dispatch
        # The recipe is already decorated with @job by quacc
        @ct.lattice
        def job_lattice(a, **kw):
            return recipe_func(a, **kw)

        # Dispatch the job
        try:
            dispatch_id = ct.dispatch(job_lattice)(atoms, **kwargs)
        except Exception as e:
            logger.error(f"Failed to dispatch Covalent job {job_id}: {e}")
            raise RuntimeError(f"Job dispatch failed: {e}") from e

        # Store dispatch ID and metadata
        self._dispatch_ids[job_id] = dispatch_id
        self._job_metadata[job_id] = {
            "recipe": recipe_fullname,
            "cluster": cluster_name,
            "kwargs": kwargs,
            "dispatch_id": dispatch_id,
        }

        logger.info(
            f"Dispatched Covalent job {job_id} "
            f"(dispatch_id={dispatch_id}) for recipe {recipe_fullname}"
        )
        return job_id

    def get_status(self, job_id: str) -> JobState:
        """Get job status from Covalent.

        Uses non-blocking ct.get_result(..., wait=False).
        """
        if job_id not in self._dispatch_ids:
            raise KeyError(f"Unknown job ID: {job_id}")

        try:
            import covalent as ct
        except ImportError:
            # Covalent not available - return unknown state
            logger.error("Covalent not installed, cannot check status")
            return JobState.PENDING

        dispatch_id = self._dispatch_ids[job_id]

        try:
            result = ct.get_result(dispatch_id, wait=False)
            status_str = str(result.status)

            # Map to JobState
            return self._status_map.get(status_str, JobState.PENDING)
        except Exception as e:
            logger.warning(f"Error getting status for job {job_id}: {e}")
            return JobState.PENDING

    def get_result(self, job_id: str) -> Optional[Dict]:
        """Get job result from Covalent.

        Returns None if job is still running.
        """
        if job_id not in self._dispatch_ids:
            raise KeyError(f"Unknown job ID: {job_id}")

        try:
            import covalent as ct
        except ImportError:
            logger.error("Covalent not installed, cannot get result")
            return None

        dispatch_id = self._dispatch_ids[job_id]

        try:
            result = ct.get_result(dispatch_id, wait=False)
            status_str = str(result.status)

            if status_str == "COMPLETED":
                # Get the actual result
                value = result.result
                return value if isinstance(value, dict) else {"result": value}
            elif status_str == "FAILED":
                # Get error information
                error = getattr(result, "error", "Unknown error")
                return {"error": str(error)}
            else:
                # Still running
                return None
        except Exception as e:
            logger.warning(f"Error getting result for job {job_id}: {e}")
            return None

    def cancel(self, job_id: str) -> bool:
        """Attempt to cancel a Covalent job.

        Uses ct.cancel() API. Note that SLURM jobs may require manual cleanup.
        """
        if job_id not in self._dispatch_ids:
            raise KeyError(f"Unknown job ID: {job_id}")

        try:
            import covalent as ct
        except ImportError:
            logger.error("Covalent not installed, cannot cancel")
            return False

        dispatch_id = self._dispatch_ids[job_id]

        try:
            ct.cancel(dispatch_id)
            logger.info(f"Requested cancellation for Covalent job {job_id}")
            return True
        except Exception as e:
            logger.error(f"Error cancelling job {job_id}: {e}")
            return False

    def get_dispatch_id(self, job_id: str) -> Optional[str]:
        """Get the Covalent dispatch ID for a job.

        Useful for debugging or external tools.
        """
        return self._dispatch_ids.get(job_id)
