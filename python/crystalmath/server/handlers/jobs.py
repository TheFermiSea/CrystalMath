"""RPC handlers for jobs.* namespace (quacc job tracking).

This module provides handlers for:
- jobs.list: List jobs from local metadata store
- jobs.submit: Submit a new job via quacc recipe
- jobs.status: Get current status of a job
- jobs.cancel: Cancel a running job
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
from typing import TYPE_CHECKING, Any
import logging

from crystalmath.server.handlers import register_handler

if TYPE_CHECKING:
    from crystalmath.api import CrystalController

logger = logging.getLogger(__name__)


@register_handler("jobs.list")
async def handle_jobs_list(
    controller: CrystalController | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    """List jobs from local metadata store.

    Params:
        status (str, optional): Filter by status ("pending", "running", etc.)
        limit (int, optional): Max results (default 100)

    Returns:
        {
            "jobs": [
                {
                    "id": "uuid",
                    "recipe": "quacc.recipes.vasp.core.relax_job",
                    "status": "running",
                    "created_at": "2026-02-02T12:00:00Z",
                    "updated_at": "2026-02-02T12:05:00Z",
                    "cluster": "nersc-perlmutter",
                    "work_dir": "/scratch/...",
                    "error_message": null,
                    "results_summary": null
                },
                ...
            ],
            "total": 42
        }
    """
    from crystalmath.quacc.store import JobStatus, JobStore

    store = JobStore()

    # Parse params
    status_str = params.get("status")
    status = JobStatus(status_str) if status_str else None
    limit = params.get("limit", 100)

    jobs = store.list_jobs(status=status, limit=limit)

    return {
        "jobs": [j.model_dump(mode="json") for j in jobs],
        "total": len(jobs),
    }


@register_handler("jobs.submit")
async def handle_jobs_submit(
    controller: CrystalController | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Submit a VASP job via quacc recipe.

    Params:
        recipe (str): Full recipe path (e.g., "quacc.recipes.vasp.core.relax_job")
        structure (str | dict): POSCAR string or ASE Atoms dict
        cluster (str, optional): Cluster name from configuration
        params (dict, optional): Recipe parameters (kpts, encut, etc.)

    Returns:
        {
            "job_id": "uuid" | null,
            "status": "pending" | "error",
            "error": null | "error message"
        }
    """
    from crystalmath.quacc.engines import get_workflow_engine
    from crystalmath.quacc.runner import get_or_create_runner
    from crystalmath.quacc.potcar import validate_potcars
    from crystalmath.quacc.store import JobStatus, JobMetadata, JobStore

    # Check workflow engine is configured
    engine = get_workflow_engine()
    if engine is None:
        return {
            "job_id": None,
            "status": "error",
            "error": (
                "No workflow engine configured. "
                "Set QUACC_WORKFLOW_ENGINE environment variable to 'parsl' or 'covalent'."
            ),
        }

    # Validate required params
    recipe = params.get("recipe")
    if not recipe:
        return {
            "job_id": None,
            "status": "error",
            "error": "recipe parameter is required",
        }

    structure_data = params.get("structure")
    if not structure_data:
        return {
            "job_id": None,
            "status": "error",
            "error": "structure parameter is required",
        }

    # Parse structure
    try:
        atoms = _parse_structure(structure_data)
    except Exception as e:
        logger.warning(f"Failed to parse structure: {e}")
        return {
            "job_id": None,
            "status": "error",
            "error": f"Failed to parse structure: {e}",
        }

    # Validate POTCARs
    elements = set(str(s) for s in atoms.get_chemical_symbols())
    valid, potcar_error = validate_potcars(elements)
    if not valid:
        return {
            "job_id": None,
            "status": "error",
            "error": potcar_error,
        }

    # Get runner for configured engine
    try:
        runner = get_or_create_runner(engine)
    except Exception as e:
        logger.error(f"Failed to create runner for {engine}: {e}")
        return {
            "job_id": None,
            "status": "error",
            "error": f"Failed to create runner: {e}",
        }

    # Submit job
    cluster_name = params.get("cluster", "local")
    recipe_params = params.get("params", {})

    try:
        job_id = runner.submit(
            recipe_fullname=recipe,
            atoms=atoms,
            cluster_name=cluster_name,
            **recipe_params,
        )
    except Exception as e:
        logger.error(f"Job submission failed: {e}")
        return {
            "job_id": None,
            "status": "error",
            "error": f"Submission failed: {e}",
        }

    # Store job metadata
    store = JobStore()
    job = JobMetadata(
        id=job_id,
        recipe=recipe,
        status=JobStatus.pending,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        cluster=cluster_name,
        work_dir=None,
    )
    store.save_job(job)

    logger.info(f"Submitted job {job_id} for recipe {recipe}")

    return {
        "job_id": job_id,
        "status": "pending",
        "error": None,
    }


@register_handler("jobs.status")
async def handle_jobs_status(
    controller: CrystalController | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Get current status of a job.

    Params:
        job_id (str): Job UUID

    Returns:
        {
            "job_id": "uuid",
            "status": "pending" | "running" | "completed" | "failed" | "cancelled",
            "error": null | "error message",
            "result": null | {...}
        }
    """
    from crystalmath.quacc.engines import get_workflow_engine
    from crystalmath.quacc.runner import get_or_create_runner, JobState
    from crystalmath.quacc.store import JobStatus, JobStore

    job_id = params.get("job_id")
    if not job_id:
        return {"error": "job_id parameter is required"}

    store = JobStore()
    job = store.get_job(job_id)
    if job is None:
        return {"error": f"Job not found: {job_id}"}

    # If already in terminal state, return cached status
    if job.status in (JobStatus.completed, JobStatus.failed):
        return {
            "job_id": job_id,
            "status": job.status.value,
            "error": job.error_message,
            "result": job.results_summary,
        }

    # Poll live status from runner
    engine = get_workflow_engine()
    if engine is None:
        # No engine - return stored status
        return {
            "job_id": job_id,
            "status": job.status.value,
            "error": job.error_message,
            "result": job.results_summary,
        }

    try:
        runner = get_or_create_runner(engine)
        current_state = runner.get_status(job_id)
    except KeyError:
        # Job not in runner (orphaned on restart)
        return {
            "job_id": job_id,
            "status": job.status.value,
            "error": "Job tracking lost (server restart?)",
            "result": job.results_summary,
        }
    except Exception as e:
        logger.warning(f"Error polling job {job_id}: {e}")
        return {
            "job_id": job_id,
            "status": job.status.value,
            "error": str(e),
            "result": job.results_summary,
        }

    # Map JobState to JobStatus
    status_map = {
        JobState.PENDING: JobStatus.pending,
        JobState.RUNNING: JobStatus.running,
        JobState.COMPLETED: JobStatus.completed,
        JobState.FAILED: JobStatus.failed,
        JobState.CANCELLED: JobStatus.cancelled,
    }
    new_status = status_map.get(current_state, JobStatus.pending)

    # Update if status changed
    if new_status != job.status:
        job.status = new_status
        job.updated_at = datetime.now(timezone.utc)

        # Fetch result if complete
        if current_state == JobState.COMPLETED:
            try:
                result = runner.get_result(job_id)
                if result:
                    job.results_summary = _summarize_result(result)
            except Exception as e:
                logger.warning(f"Failed to get result for {job_id}: {e}")

        # Fetch error if failed
        elif current_state == JobState.FAILED:
            try:
                result = runner.get_result(job_id)
                if result and "error" in result:
                    job.error_message = result["error"]
            except Exception as e:
                logger.warning(f"Failed to get error for {job_id}: {e}")

        store.save_job(job)

    return {
        "job_id": job_id,
        "status": job.status.value,
        "error": job.error_message,
        "result": job.results_summary,
    }


@register_handler("jobs.cancel")
async def handle_jobs_cancel(
    controller: CrystalController | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Cancel a running job.

    Params:
        job_id (str): Job UUID

    Returns:
        {
            "job_id": "uuid",
            "cancelled": true | false,
            "error": null | "error message"
        }
    """
    from crystalmath.quacc.engines import get_workflow_engine
    from crystalmath.quacc.runner import get_or_create_runner
    from crystalmath.quacc.store import JobStatus, JobStore

    job_id = params.get("job_id")
    if not job_id:
        return {"error": "job_id parameter is required"}

    store = JobStore()
    job = store.get_job(job_id)
    if job is None:
        return {"error": f"Job not found: {job_id}"}

    # Check if already in terminal state
    if job.status in (JobStatus.completed, JobStatus.failed, JobStatus.cancelled):
        return {
            "job_id": job_id,
            "cancelled": False,
            "error": f"Job already in terminal state: {job.status.value}",
        }

    # Get engine and runner
    engine = get_workflow_engine()
    if engine is None:
        return {
            "job_id": job_id,
            "cancelled": False,
            "error": "No workflow engine configured",
        }

    try:
        runner = get_or_create_runner(engine)
        cancelled = runner.cancel(job_id)
    except KeyError:
        return {
            "job_id": job_id,
            "cancelled": False,
            "error": "Job not found in runner (may have been orphaned)",
        }
    except Exception as e:
        logger.error(f"Error cancelling job {job_id}: {e}")
        return {
            "job_id": job_id,
            "cancelled": False,
            "error": str(e),
        }

    if cancelled:
        job.status = JobStatus.cancelled
        job.updated_at = datetime.now(timezone.utc)
        store.save_job(job)
        logger.info(f"Cancelled job {job_id}")

    return {
        "job_id": job_id,
        "cancelled": cancelled,
        "error": None,
    }


def _parse_structure(structure_data: str | dict) -> Any:
    """Parse structure from POSCAR string or ASE Atoms dict.

    Args:
        structure_data: Either a POSCAR string or an ASE Atoms dict

    Returns:
        ASE Atoms object

    Raises:
        ValueError: If structure format is unknown
    """
    from ase.io import read
    from ase import Atoms

    if isinstance(structure_data, str):
        # POSCAR string
        return read(StringIO(structure_data), format="vasp")
    elif isinstance(structure_data, dict):
        # ASE Atoms dict format
        return Atoms(**structure_data)
    else:
        raise ValueError(f"Unknown structure format: {type(structure_data)}")


@register_handler("jobs.get_output_file")
async def handle_jobs_get_output_file(
    controller: CrystalController | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Get contents of a job output file (OUTCAR, vasprun.xml, etc.).

    Params:
        job_pk (int): Job primary key
        file_type (str): Output file name ("OUTCAR", "vasprun.xml", "OSZICAR", etc.)
        tail_lines (int, optional): Return only last N lines (default: all)

    Returns:
        {
            "ok": true,
            "data": {
                "content": "file contents as string",
                "truncated": false,
                "total_lines": 1234
            }
        }
    """
    import os
    from pathlib import Path

    job_pk = params.get("job_pk")
    if job_pk is None:
        return {"ok": False, "error": {"message": "job_pk parameter is required"}}

    file_type = params.get("file_type", "OUTCAR")
    tail_lines = params.get("tail_lines")

    # Get job details to find work directory
    if controller is None:
        return {"ok": False, "error": {"message": "Controller not available"}}

    try:
        job_details = controller.get_job_details(job_pk)
        if job_details is None:
            return {"ok": False, "error": {"message": f"Job {job_pk} not found"}}
    except Exception as e:
        logger.error(f"Failed to get job details for pk={job_pk}: {e}")
        return {"ok": False, "error": {"message": f"Failed to get job details: {e}"}}

    # Get work directory
    work_dir = getattr(job_details, "work_dir", None)
    if not work_dir:
        return {"ok": False, "error": {"message": f"Job {job_pk} has no work directory"}}

    # Construct file path
    file_path = Path(work_dir) / file_type

    # Security check: ensure file is within work_dir (prevent path traversal)
    try:
        file_path = file_path.resolve()
        work_dir_resolved = Path(work_dir).resolve()
        if not str(file_path).startswith(str(work_dir_resolved)):
            return {"ok": False, "error": {"message": "Invalid file path"}}
    except Exception as e:
        return {"ok": False, "error": {"message": f"Path resolution error: {e}"}}

    # Check file exists
    if not file_path.exists():
        return {"ok": False, "error": {"message": f"File not found: {file_type}"}}

    if not file_path.is_file():
        return {"ok": False, "error": {"message": f"Not a file: {file_type}"}}

    # Read file content
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total_lines = len(lines)
        truncated = False

        # Apply tail limit if specified
        if tail_lines is not None and tail_lines > 0 and total_lines > tail_lines:
            lines = lines[-tail_lines:]
            truncated = True

        content = "".join(lines)

        return {
            "ok": True,
            "data": {
                "content": content,
                "truncated": truncated,
                "total_lines": total_lines,
            },
        }

    except Exception as e:
        logger.error(f"Failed to read file {file_path}: {e}")
        return {"ok": False, "error": {"message": f"Failed to read file: {e}"}}


def _summarize_result(result: dict) -> dict:
    """Extract key values from quacc result schema.

    Args:
        result: quacc result dictionary

    Returns:
        Summary dictionary with key values
    """
    summary = {}

    # Energy
    if "results" in result and "energy" in result["results"]:
        summary["energy_ev"] = result["results"]["energy"]

    # Forces (max magnitude)
    if "results" in result and "forces" in result["results"]:
        try:
            import numpy as np
            forces = np.array(result["results"]["forces"])
            summary["max_force_ev_ang"] = float(np.max(np.linalg.norm(forces, axis=1)))
        except Exception:
            pass

    # Formula
    if "formula_pretty" in result:
        summary["formula"] = result["formula_pretty"]

    # Working directory
    if "dir_name" in result:
        summary["work_dir"] = result["dir_name"]

    return summary
