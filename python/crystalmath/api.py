"""
CrystalController: Facade for AiiDA interaction from Rust TUI.

This module provides the single point of entry for the Rust application.
All methods return JSON strings to simplify the PyO3 FFI boundary.

Usage from Rust (via PyO3):
    let controller = py.import("crystalmath.api")?.getattr("CrystalController")?.call0()?;
    let jobs_json: String = controller.call_method0("get_jobs_json")?.extract()?;
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import uuid as uuid_module

from crystalmath.models import (
    DftCode,
    JobDetails,
    JobState,
    JobStatus,
    JobSubmission,
    RunnerType,
)

logger = logging.getLogger(__name__)


# ========== Structured Error Response Helpers ==========

def _ok_response(data: Any) -> str:
    """Wrap successful data in structured response."""
    return json.dumps({"ok": True, "data": data})


def _error_response(code: str, message: str) -> str:
    """Create structured error response JSON."""
    return json.dumps({
        "ok": False,
        "error": {
            "code": code,
            "message": message,
        }
    })


class CrystalController:
    """
    Facade class exposing AiiDA operations to Rust via JSON.

    This class handles:
    - AiiDA profile initialization
    - Job submission and monitoring
    - Result retrieval
    - State mapping between AiiDA and UI

    All public methods return JSON strings for PyO3 simplicity.
    """

    def __init__(
        self,
        profile_name: str = "default",
        use_aiida: bool = True,
        db_path: Optional[str] = None,
    ) -> None:
        """
        Initialize the controller.

        Args:
            profile_name: AiiDA profile to load (ignored if use_aiida=False)
            use_aiida: If False, use SQLite fallback instead of AiiDA
            db_path: Path to SQLite database (for fallback mode)
        """
        self._use_aiida = use_aiida
        self._profile_name = profile_name
        self._db_path = db_path

        # Try to initialize AiiDA if requested
        if use_aiida:
            self._aiida_available = self._init_aiida(profile_name)
        else:
            self._aiida_available = False

        # Fallback to SQLite if AiiDA not available
        if not self._aiida_available and db_path:
            self._init_sqlite(db_path)
        elif not self._aiida_available:
            logger.warning("No backend available - running in demo mode")
            self._demo_jobs: List[Dict[str, Any]] = []

    def _init_aiida(self, profile_name: str) -> bool:
        """
        Initialize AiiDA profile.

        Returns:
            True if AiiDA is available and loaded successfully
        """
        try:
            import aiida
            from aiida import orm

            aiida.load_profile(profile_name)
            self._aiida = aiida
            self._orm = orm
            logger.info(f"Loaded AiiDA profile: {profile_name}")
            return True
        except ImportError:
            logger.info("AiiDA not installed - using fallback mode")
            return False
        except Exception as e:
            logger.warning(f"Failed to load AiiDA profile '{profile_name}': {e}")
            return False

    def _init_sqlite(self, db_path: str) -> None:
        """Initialize SQLite database for fallback mode."""
        try:
            # Import the existing TUI database module
            import sys
            tui_path = Path(__file__).parent.parent.parent.parent / "tui" / "src"
            if str(tui_path) not in sys.path:
                sys.path.insert(0, str(tui_path))

            from core.database import Database
            self._db = Database(Path(db_path))
            logger.info(f"Loaded SQLite database: {db_path}")
        except Exception as e:
            logger.warning(f"Failed to load SQLite database: {e}")
            self._db = None

    # ========== Public API Methods (called from Rust) ==========

    def get_jobs_json(self, limit: int = 100) -> str:
        """
        Get list of jobs as JSON string.

        Returns:
            JSON array of JobStatus objects
        """
        if self._aiida_available:
            return self._get_aiida_jobs_json(limit)
        elif hasattr(self, "_db") and self._db:
            return self._get_sqlite_jobs_json(limit)
        else:
            return self._get_demo_jobs_json()

    def get_job_details_json(self, pk: int) -> str:
        """
        Get detailed job information as JSON string.

        Args:
            pk: Job primary key

        Returns:
            JSON object with "ok": true and "data" containing JobDetails,
            or "ok": false with "error" if not found or error occurred.
        """
        if self._aiida_available:
            return self._get_aiida_job_details_json(pk)
        elif hasattr(self, "_db") and self._db:
            return self._get_sqlite_job_details_json(pk)
        else:
            return self._get_demo_job_details_json(pk)

    def submit_job_json(self, json_payload: str) -> int:
        """
        Submit a new job from JSON payload.

        Args:
            json_payload: JSON string matching JobSubmission schema

        Returns:
            Job primary key (pk)

        Raises:
            RuntimeError: If submission fails
        """
        try:
            submission = JobSubmission.model_validate_json(json_payload)

            if self._aiida_available:
                return self._submit_aiida_job(submission)
            elif hasattr(self, "_db") and self._db:
                return self._submit_sqlite_job(submission)
            else:
                return self._submit_demo_job(submission)
        except Exception as e:
            raise RuntimeError(f"Job submission failed: {e}") from e

    def cancel_job(self, pk: int) -> bool:
        """
        Cancel a running job.

        Args:
            pk: Job primary key

        Returns:
            True if cancellation succeeded
        """
        if self._aiida_available:
            return self._cancel_aiida_job(pk)
        elif hasattr(self, "_db") and self._db:
            return self._cancel_sqlite_job(pk)
        else:
            return self._cancel_demo_job(pk)

    def get_job_log_json(self, pk: int, tail_lines: int = 100) -> str:
        """
        Get job stdout/stderr log as JSON.

        Args:
            pk: Job primary key
            tail_lines: Number of lines from end of log

        Returns:
            JSON object with "stdout" and "stderr" arrays
        """
        if self._aiida_available:
            return self._get_aiida_job_log_json(pk, tail_lines)
        else:
            return json.dumps({"stdout": [], "stderr": []})

    # ========== AiiDA Backend Implementation ==========

    def _get_aiida_jobs_json(self, limit: int) -> str:
        """Query AiiDA for job list."""
        from aiida import orm

        qb = orm.QueryBuilder()
        qb.append(
            orm.CalcJobNode,
            project=["id", "uuid", "label", "attributes.process_state", "attributes.exit_status", "ctime"],
        )
        qb.order_by({orm.CalcJobNode: {"ctime": "desc"}})
        qb.limit(limit)

        results: List[Dict[str, Any]] = []
        for pk, uuid, label, state, exit_status, ctime in qb.all():
            # Map AiiDA process state to UI state
            if state == "finished":
                ui_state = JobState.COMPLETED if exit_status == 0 else JobState.FAILED
            elif state in ("excepted", "killed"):
                ui_state = JobState.FAILED
            elif state == "running":
                ui_state = JobState.RUNNING
            elif state == "waiting":
                ui_state = JobState.QUEUED
            else:
                ui_state = JobState.CREATED

            job = JobStatus(
                pk=pk,
                uuid=uuid,
                name=label or f"Job {pk}",
                state=ui_state,
                dft_code=DftCode.CRYSTAL,  # TODO: detect from node type
                runner_type=RunnerType.AIIDA,
                progress_percent=100.0 if ui_state == JobState.COMPLETED else 0.0,
                created_at=ctime,
            )
            results.append(job.model_dump(mode="json"))

        return json.dumps(results)

    def _get_aiida_job_details_json(self, pk: int) -> str:
        """Get detailed job info from AiiDA."""
        from aiida import orm
        from aiida.common import NotExistent

        try:
            node = orm.load_node(pk)

            # Get output parameters if available
            output_params: Dict[str, Any] = {}
            if "output_parameters" in node.outputs:
                output_params = node.outputs.output_parameters.get_dict()

            # Get stdout
            stdout_lines: List[str] = []
            if "retrieved" in node.outputs:
                try:
                    stdout = node.outputs.retrieved.get_object_content("_scheduler-stdout.txt")
                    stdout_lines = stdout.splitlines()[-50:]
                except Exception:
                    pass

            # Map state
            state = node.process_state.value if node.process_state else "created"
            exit_status = node.exit_status

            if state == "finished":
                ui_state = JobState.COMPLETED if exit_status == 0 else JobState.FAILED
            elif state in ("excepted", "killed"):
                ui_state = JobState.FAILED
            elif state == "running":
                ui_state = JobState.RUNNING
            else:
                ui_state = JobState.QUEUED

            details = JobDetails(
                pk=pk,
                uuid=str(node.uuid),
                name=node.label or f"Job {pk}",
                state=ui_state,
                final_energy=output_params.get("energy"),
                convergence_met=output_params.get("converged", False),
                scf_cycles=output_params.get("scf_cycles"),
                warnings=[],
                stdout_tail=stdout_lines,
                key_results=output_params,
            )
            return _ok_response(details.model_dump(mode="json"))

        except NotExistent:
            return _error_response("NOT_FOUND", f"Job with pk={pk} not found")
        except Exception as e:
            logger.error(f"Error getting job details for pk={pk}: {e}")
            return _error_response("INTERNAL_ERROR", str(e))

    def _submit_aiida_job(self, submission: JobSubmission) -> int:
        """Submit job to AiiDA."""
        from aiida import orm
        from aiida.engine import submit

        # For now, create a simple CalcJob
        # In production, this would use Crystal23Calculation or similar
        try:
            code = orm.load_code("crystal@localhost")
        except Exception:
            raise RuntimeError("CRYSTAL code not configured in AiiDA. Run 'verdi code setup' first.")

        # Create a builder
        # This is a placeholder - actual implementation depends on AiiDA plugin
        builder = code.get_builder()
        builder.metadata.label = submission.name
        builder.metadata.options.resources = {"num_machines": 1, "num_mpiprocs_per_machine": 1}

        node = submit(builder)
        return node.pk

    def _cancel_aiida_job(self, pk: int) -> bool:
        """Cancel AiiDA job."""
        from aiida import orm
        from aiida.engine import processes

        try:
            node = orm.load_node(pk)
            processes.control.kill_processes([node])
            return True
        except Exception as e:
            logger.error(f"Failed to cancel job {pk}: {e}")
            return False

    def _get_aiida_job_log_json(self, pk: int, tail_lines: int) -> str:
        """Get job logs from AiiDA."""
        from aiida import orm

        try:
            node = orm.load_node(pk)
            stdout_lines: List[str] = []
            stderr_lines: List[str] = []

            if "retrieved" in node.outputs:
                try:
                    stdout = node.outputs.retrieved.get_object_content("_scheduler-stdout.txt")
                    stdout_lines = stdout.splitlines()[-tail_lines:]
                except Exception:
                    pass
                try:
                    stderr = node.outputs.retrieved.get_object_content("_scheduler-stderr.txt")
                    stderr_lines = stderr.splitlines()[-tail_lines:]
                except Exception:
                    pass

            return json.dumps({"stdout": stdout_lines, "stderr": stderr_lines})
        except Exception:
            return json.dumps({"stdout": [], "stderr": []})

    # ========== SQLite Backend Implementation ==========

    def _get_sqlite_jobs_json(self, limit: int) -> str:
        """Query SQLite for job list."""
        jobs = self._db.get_all_jobs()[:limit]
        results: List[Dict[str, Any]] = []

        for job in jobs:
            # Map database status to JobState
            state_map = {
                "PENDING": JobState.CREATED,
                "QUEUED": JobState.QUEUED,
                "RUNNING": JobState.RUNNING,
                "COMPLETED": JobState.COMPLETED,
                "FAILED": JobState.FAILED,
                "CANCELLED": JobState.CANCELLED,
            }

            status = JobStatus(
                pk=job.id,
                uuid=str(job.id),  # SQLite doesn't have UUID
                name=job.name,
                state=state_map.get(job.status, JobState.CREATED),
                dft_code=DftCode(job.dft_code) if job.dft_code else DftCode.CRYSTAL,
                runner_type=RunnerType(job.runner_type) if job.runner_type else RunnerType.LOCAL,
                progress_percent=100.0 if job.status == "COMPLETED" else 0.0,
                created_at=datetime.fromisoformat(job.created_at) if job.created_at else None,
            )
            results.append(status.model_dump(mode="json"))

        return json.dumps(results)

    def _get_sqlite_job_details_json(self, pk: int) -> str:
        """Get job details from SQLite."""
        try:
            job = self._db.get_job(pk)
            if not job:
                return _error_response("NOT_FOUND", f"Job with pk={pk} not found")

            # Get additional results if available
            result = self._db.get_job_result(pk)

            state_map = {
                "PENDING": JobState.CREATED,
                "QUEUED": JobState.QUEUED,
                "RUNNING": JobState.RUNNING,
                "COMPLETED": JobState.COMPLETED,
                "FAILED": JobState.FAILED,
                "CANCELLED": JobState.CANCELLED,
            }

            details = JobDetails(
                pk=job.id,
                uuid=str(job.id),
                name=job.name,
                state=state_map.get(job.status, JobState.CREATED),
                dft_code=DftCode(job.dft_code) if job.dft_code else DftCode.CRYSTAL,
                final_energy=job.final_energy,
                convergence_met=result.convergence_status == "converged" if result else False,
                scf_cycles=result.scf_cycles if result else None,
                cpu_time_seconds=result.cpu_time_seconds if result else None,
                wall_time_seconds=result.wall_time_seconds if result else None,
                key_results=result.key_results if result else None,
                work_dir=job.work_dir,
                input_file=job.input_file,
            )
            return _ok_response(details.model_dump(mode="json"))
        except Exception as e:
            logger.error(f"Error getting job details for pk={pk}: {e}")
            return _error_response("INTERNAL_ERROR", str(e))

    def _submit_sqlite_job(self, submission: JobSubmission) -> int:
        """Submit job via SQLite."""
        work_dir = f"/tmp/crystal_{submission.name}_{uuid_module.uuid4().hex[:8]}"

        job_id = self._db.create_job(
            name=submission.name,
            work_dir=work_dir,
            input_content=submission.input_content or json.dumps(submission.parameters),
            cluster_id=submission.cluster_id,
            runner_type=submission.runner_type.value,
            dft_code=submission.dft_code.value,
        )
        return job_id

    def _cancel_sqlite_job(self, pk: int) -> bool:
        """Cancel SQLite job."""
        try:
            self._db.update_status(pk, "CANCELLED")
            return True
        except Exception:
            return False

    # ========== Demo Mode Implementation ==========

    def _get_demo_jobs_json(self) -> str:
        """Return demo jobs for testing."""
        if not self._demo_jobs:
            # Create some sample jobs
            self._demo_jobs = [
                {
                    "pk": 1,
                    "uuid": "demo-001",
                    "name": "MgO-SCF",
                    "state": JobState.COMPLETED.value,
                    "dft_code": DftCode.CRYSTAL.value,
                    "runner_type": RunnerType.LOCAL.value,
                    "progress_percent": 100.0,
                    "wall_time_seconds": 45.2,
                    "created_at": datetime.now().isoformat(),
                },
                {
                    "pk": 2,
                    "uuid": "demo-002",
                    "name": "MoS2-OPTGEOM",
                    "state": JobState.RUNNING.value,
                    "dft_code": DftCode.CRYSTAL.value,
                    "runner_type": RunnerType.LOCAL.value,
                    "progress_percent": 65.0,
                    "wall_time_seconds": 120.0,
                    "created_at": datetime.now().isoformat(),
                },
            ]
        return json.dumps(self._demo_jobs)

    def _get_demo_job_details_json(self, pk: int) -> str:
        """Return demo job details."""
        for job in self._demo_jobs:
            if job["pk"] == pk:
                details = JobDetails(
                    pk=pk,
                    uuid=job["uuid"],
                    name=job["name"],
                    state=JobState(job["state"]),
                    dft_code=DftCode(job["dft_code"]),
                    final_energy=-275.123456 if job["state"] == "COMPLETED" else None,
                    convergence_met=job["state"] == "COMPLETED",
                    scf_cycles=15 if job["state"] == "COMPLETED" else None,
                    stdout_tail=["TOTAL ENERGY -275.123456 AU", "SCF CONVERGED"] if job["state"] == "COMPLETED" else [],
                )
                return _ok_response(details.model_dump(mode="json"))
        return _error_response("NOT_FOUND", f"Job with pk={pk} not found")

    def _submit_demo_job(self, submission: JobSubmission) -> int:
        """Submit demo job."""
        pk = len(self._demo_jobs) + 1
        self._demo_jobs.append({
            "pk": pk,
            "uuid": f"demo-{pk:03d}",
            "name": submission.name,
            "state": JobState.QUEUED.value,
            "dft_code": submission.dft_code.value,
            "runner_type": submission.runner_type.value,
            "progress_percent": 0.0,
            "wall_time_seconds": None,
            "created_at": datetime.now().isoformat(),
        })
        return pk

    def _cancel_demo_job(self, pk: int) -> bool:
        """Cancel demo job."""
        for job in self._demo_jobs:
            if job["pk"] == pk:
                job["state"] = JobState.CANCELLED.value
                return True
        return False


# Convenience function for Rust initialization
def create_controller(
    profile_name: str = "default",
    use_aiida: bool = True,
    db_path: Optional[str] = None,
) -> CrystalController:
    """
    Factory function to create a CrystalController.

    This is the entry point called from Rust via PyO3.

    Args:
        profile_name: AiiDA profile name
        use_aiida: Whether to use AiiDA backend
        db_path: SQLite database path for fallback

    Returns:
        Configured CrystalController instance
    """
    return CrystalController(
        profile_name=profile_name,
        use_aiida=use_aiida,
        db_path=db_path,
    )
