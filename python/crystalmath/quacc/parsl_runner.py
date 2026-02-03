"""Parsl-based JobRunner implementation.

This module implements job submission and tracking using Parsl's
futures-based execution model.
"""

from typing import Any, Dict, Optional
import logging

from crystalmath.quacc.runner import JobRunner, JobState

logger = logging.getLogger(__name__)


class ParslRunner(JobRunner):
    """JobRunner implementation using Parsl workflow engine.

    Parsl returns AppFuture objects from decorated functions. These futures
    follow the concurrent.futures.Future interface:
    - .done() for non-blocking status check
    - .result() for blocking result retrieval
    - .cancel() for cancellation (if supported)

    Job IDs are UUIDs that map to in-memory future storage. Note that
    futures cannot be serialized, so job tracking is lost on server restart.
    """

    def __init__(self):
        """Initialize the Parsl runner."""
        # In-memory storage for futures
        # Note: Not persistent - jobs become "orphaned" on restart
        self._futures: Dict[str, Any] = {}
        self._job_metadata: Dict[str, Dict] = {}

    def submit(
        self,
        recipe_fullname: str,
        atoms: Any,
        cluster_name: str,
        **kwargs,
    ) -> str:
        """Submit a job via Parsl.

        Args:
            recipe_fullname: Full path to quacc recipe
            atoms: ASE Atoms object
            cluster_name: Name of cluster configuration (for executor selection)
            **kwargs: Additional recipe parameters

        Returns:
            Job ID (UUID string)
        """
        # Import recipe dynamically
        recipe_func = self._import_recipe(recipe_fullname)

        # Generate job ID
        job_id = self.generate_job_id()

        # Submit to Parsl - returns AppFuture when Parsl is configured
        try:
            future = recipe_func(atoms, **kwargs)
        except Exception as e:
            logger.error(f"Failed to submit job {job_id}: {e}")
            raise RuntimeError(f"Job submission failed: {e}") from e

        # Store future and metadata
        self._futures[job_id] = future
        self._job_metadata[job_id] = {
            "recipe": recipe_fullname,
            "cluster": cluster_name,
            "kwargs": kwargs,
        }

        logger.info(f"Submitted Parsl job {job_id} for recipe {recipe_fullname}")
        return job_id

    def get_status(self, job_id: str) -> JobState:
        """Get job status from Parsl future.

        Uses non-blocking .done() check followed by exception check.
        """
        if job_id not in self._futures:
            raise KeyError(f"Unknown job ID: {job_id}")

        future = self._futures[job_id]

        # Check if future has a done() method (AppFuture/Future interface)
        if not hasattr(future, "done"):
            # Direct result (no workflow engine configured)
            return JobState.COMPLETED

        if not future.done():
            return JobState.RUNNING

        # Job is done - check if it succeeded or failed
        try:
            # Don't actually get result, just check for exception
            future.exception(timeout=0)
            return JobState.COMPLETED
        except Exception:
            return JobState.FAILED

    def get_result(self, job_id: str) -> Optional[Dict]:
        """Get job result from Parsl future.

        Returns None if job is still running.
        """
        if job_id not in self._futures:
            raise KeyError(f"Unknown job ID: {job_id}")

        future = self._futures[job_id]

        # Check if this is a direct result (no workflow engine)
        if not hasattr(future, "done"):
            return future if isinstance(future, dict) else {"result": future}

        if not future.done():
            return None

        try:
            result = future.result()
            return result if isinstance(result, dict) else {"result": result}
        except Exception as e:
            logger.warning(f"Job {job_id} failed: {e}")
            return {"error": str(e)}

    def cancel(self, job_id: str) -> bool:
        """Attempt to cancel a Parsl job.

        Parsl futures support cancellation, but it may not be immediate
        for jobs already running on remote executors.
        """
        if job_id not in self._futures:
            raise KeyError(f"Unknown job ID: {job_id}")

        future = self._futures[job_id]

        # Check if future supports cancel
        if not hasattr(future, "cancel"):
            logger.warning(f"Job {job_id} does not support cancellation")
            return False

        try:
            cancelled = future.cancel()
            if cancelled:
                logger.info(f"Cancelled Parsl job {job_id}")
            else:
                logger.info(f"Could not cancel Parsl job {job_id} (may be running)")
            return cancelled
        except Exception as e:
            logger.error(f"Error cancelling job {job_id}: {e}")
            return False

    def cleanup_completed(self) -> int:
        """Remove completed/failed jobs from memory.

        Returns:
            Number of jobs cleaned up.
        """
        to_remove = []
        for job_id in self._futures:
            status = self.get_status(job_id)
            if status.is_terminal():
                to_remove.append(job_id)

        for job_id in to_remove:
            del self._futures[job_id]
            self._job_metadata.pop(job_id, None)

        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} completed jobs")

        return len(to_remove)
