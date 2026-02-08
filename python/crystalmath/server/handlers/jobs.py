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


# ==================== VASP Error Analysis ====================

# Inline VASP error patterns (fallback when tui.runners.vasp_errors not available)
_VASP_ERROR_PATTERNS_FALLBACK: list[tuple[str, str, str, str, list[str], dict[str, str]]] = [
    # (pattern, code, severity, message, suggestions, incar_changes)
    (
        r"ZBRENT: fatal error in bracketing",
        "ZBRENT",
        "recoverable",
        "Brent algorithm failed to bracket the minimum during line search",
        [
            "Reduce POTIM (e.g., from 0.5 to 0.1-0.2)",
            "Switch optimizer: try IBRION=1 (quasi-Newton) or IBRION=3 (damped MD)",
            "Check for unreasonable starting geometry",
        ],
        {"POTIM": "0.1", "IBRION": "1"},
    ),
    (
        r"Error EDDDAV",
        "EDDDAV",
        "recoverable",
        "Electronic self-consistency (SCF) did not converge",
        [
            "Increase NELM (max electronic iterations, e.g., 200)",
            "Try different algorithm: ALGO=All or ALGO=Damped",
            "Reduce EDIFF (looser convergence, e.g., 1E-5)",
        ],
        {"NELM": "200", "ALGO": "All"},
    ),
    (
        r"POSMAP internal error",
        "POSMAP",
        "fatal",
        "Internal error in position mapping - likely overlapping atoms",
        [
            "Check POSCAR for overlapping or too-close atoms",
            "Verify all atomic positions are within cell bounds",
        ],
        {},
    ),
    (
        r"VERY BAD NEWS",
        "VERYBAD",
        "fatal",
        "Serious internal VASP error detected",
        [
            "Check OUTCAR for details above this message",
            "Review input structure for anomalies",
        ],
        {},
    ),
    (
        r"SGRCON.*group",
        "SGRCON",
        "recoverable",
        "Symmetry detection failed",
        [
            "Set ISYM=0 to disable symmetry",
            "Or increase SYMPREC to be more tolerant",
        ],
        {"ISYM": "0"},
    ),
    (
        r"BRIONS problems",
        "BRIONS",
        "recoverable",
        "Ionic relaxation algorithm encountered problems",
        [
            "Reduce POTIM (smaller ionic steps)",
            "Try different optimizer: IBRION=1, 2, or 3",
        ],
        {"POTIM": "0.1", "IBRION": "1"},
    ),
    (
        r"allocation.*failed|cannot allocate",
        "MEMORY",
        "fatal",
        "Memory allocation failed - job ran out of memory",
        [
            "Reduce NCORE/NPAR to use less memory per node",
            "Request more memory or fewer cores per node",
            "For very large systems: use LREAL=Auto",
        ],
        {"LREAL": "Auto"},
    ),
    (
        r"BRMIX.*internal error",
        "BRMIX",
        "recoverable",
        "Charge density mixing failed",
        [
            "Reduce AMIX and/or BMIX (e.g., 0.1)",
            "Try different mixing: IMIX=1 with smaller AMIX",
        ],
        {"AMIX": "0.1", "BMIX": "0.0001"},
    ),
    (
        r"DENTET",
        "DENTET",
        "recoverable",
        "Tetrahedron method (ISMEAR=-5) failed",
        [
            "Use Gaussian smearing instead: ISMEAR=0, SIGMA=0.05",
            "Increase k-point density",
        ],
        {"ISMEAR": "0", "SIGMA": "0.05"},
    ),
]


def _analyze_vasp_errors_fallback(content: str) -> list[dict[str, Any]]:
    """Analyze VASP errors using inline fallback patterns.

    Args:
        content: OUTCAR file content

    Returns:
        List of error dictionaries
    """
    import re

    errors = []
    seen_codes: set[str] = set()

    for line in content.split("\n"):
        for pattern, code, severity, message, suggestions, incar_changes in _VASP_ERROR_PATTERNS_FALLBACK:
            if code in seen_codes:
                continue
            if re.search(pattern, line, re.IGNORECASE):
                seen_codes.add(code)
                errors.append({
                    "code": code,
                    "severity": severity,
                    "message": message,
                    "line_content": line.strip()[:100],
                    "suggestions": suggestions,
                    "incar_changes": incar_changes,
                })
                break  # Only match first pattern per line

    return errors


def _analyze_vasp_errors(content: str) -> list[dict[str, Any]]:
    """Analyze VASP errors, trying the full handler first then fallback.

    Args:
        content: OUTCAR file content

    Returns:
        List of error dictionaries
    """
    # Try to use the full VASPErrorHandler from tui
    try:
        from tui.src.runners.vasp_errors import VASPErrorHandler

        handler = VASPErrorHandler()
        vasp_errors = handler.analyze_outcar(content)

        return [
            {
                "code": err.code,
                "severity": err.severity.value,
                "message": err.message,
                "line_content": err.line_content,
                "suggestions": err.suggestions,
                "incar_changes": err.incar_changes,
            }
            for err in vasp_errors
        ]
    except ImportError:
        # Fall back to inline patterns
        logger.debug("VASPErrorHandler not available, using fallback patterns")
        return _analyze_vasp_errors_fallback(content)
    except Exception as e:
        logger.warning("VASPErrorHandler failed, using fallback: %s", e)
        return _analyze_vasp_errors_fallback(content)


def _read_file_with_tail(file_path: str, tail_lines: int | None) -> dict[str, Any]:
    """Read file content with optional tail limiting.

    Uses memory-efficient streaming with deque when tail_lines is specified.

    Args:
        file_path: Path to the file to read
        tail_lines: If specified, return only the last N lines

    Returns:
        Dict with content, truncated flag, and total_lines count
    """
    from collections import deque

    total_lines = 0
    truncated = False

    if tail_lines is not None and tail_lines > 0:
        # Use deque for memory-efficient tail reading
        dq: deque[str] = deque(maxlen=tail_lines)
        with open(file_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                total_lines += 1
                dq.append(line)
        lines = list(dq)
        truncated = total_lines > tail_lines
    else:
        # Read entire file
        with open(file_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        total_lines = len(lines)

    content = "".join(lines)
    return {
        "content": content,
        "truncated": truncated,
        "total_lines": total_lines,
    }


@register_handler("jobs.analyze_errors")
async def handle_jobs_analyze_errors(
    controller: CrystalController | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Analyze VASP job output for errors and return recovery suggestions.

    Args:
        controller: The crystal controller instance
        params: RPC parameters containing:
            - job_pk: Job primary key

    Returns:
        JSON-RPC response with:
            ok: True if analysis succeeded
            data: {
                job_pk: int,
                errors: List of error objects with:
                    - code: str (e.g., "ZBRENT", "EDDDAV")
                    - severity: str ("fatal", "recoverable", "warning")
                    - message: str (human-readable description)
                    - line_content: str | None (actual line from OUTCAR)
                    - suggestions: List[str] (recovery suggestions)
                    - incar_changes: Dict[str, str] (suggested INCAR changes)
                has_errors: bool,
                summary: str (brief summary message)
            }
    """
    import asyncio
    from pathlib import Path

    job_pk = params.get("job_pk")
    if job_pk is None:
        return {"ok": False, "error": {"message": "job_pk is required"}}

    # Get job details to find work directory
    if controller is None:
        return {"ok": False, "error": {"message": "Controller not available"}}

    try:
        job_details = controller.get_job_details(job_pk)
        if job_details is None:
            return {"ok": False, "error": {"message": f"Job {job_pk} not found"}}
    except Exception as e:
        logger.exception("Failed to get job details for pk=%s", job_pk)
        return {"ok": False, "error": {"message": f"Failed to get job details: {e}"}}

    # Get work directory
    work_dir = getattr(job_details, "work_dir", None)
    if not work_dir:
        return {"ok": False, "error": {"message": f"Job {job_pk} has no work directory"}}

    # Build path to OUTCAR
    work_dir_resolved = Path(work_dir).resolve()
    outcar_path = work_dir_resolved / "OUTCAR"

    if not outcar_path.exists():
        return {
            "ok": True,
            "data": {
                "job_pk": job_pk,
                "errors": [],
                "has_errors": False,
                "summary": "No OUTCAR file found - job may not be a VASP calculation",
            },
        }

    # Read OUTCAR content (async for non-blocking)
    def _read_outcar() -> str:
        with open(outcar_path, encoding="utf-8", errors="replace") as f:
            return f.read()

    try:
        content = await asyncio.to_thread(_read_outcar)
    except Exception as e:
        logger.exception("Failed to read OUTCAR for job %s", job_pk)
        return {"ok": False, "error": {"message": f"Failed to read OUTCAR: {e}"}}

    # Analyze for errors
    errors = _analyze_vasp_errors(content)

    # Build summary
    if not errors:
        summary = "No errors detected in OUTCAR"
    else:
        fatal_count = sum(1 for e in errors if e["severity"] == "fatal")
        recoverable_count = sum(1 for e in errors if e["severity"] == "recoverable")
        warning_count = sum(1 for e in errors if e["severity"] == "warning")

        parts = []
        if fatal_count:
            parts.append(f"{fatal_count} fatal")
        if recoverable_count:
            parts.append(f"{recoverable_count} recoverable")
        if warning_count:
            parts.append(f"{warning_count} warning")
        summary = f"Found {len(errors)} error(s): {', '.join(parts)}"

    return {
        "ok": True,
        "data": {
            "job_pk": job_pk,
            "errors": errors,
            "has_errors": len(errors) > 0,
            "summary": summary,
        },
    }


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
    import asyncio
    from pathlib import Path

    job_pk = params.get("job_pk")
    if job_pk is None:
        return {"ok": False, "error": {"message": "job_pk parameter is required"}}

    file_type = params.get("file_type", "OUTCAR")
    tail_lines = params.get("tail_lines")

    # Validate tail_lines parameter
    if tail_lines is not None:
        if not isinstance(tail_lines, int):
            return {"ok": False, "error": {"message": "tail_lines must be an integer"}}
        if tail_lines < 0:
            return {"ok": False, "error": {"message": "tail_lines must be non-negative"}}

    # Get job details to find work directory
    if controller is None:
        return {"ok": False, "error": {"message": "Controller not available"}}

    try:
        job_details = controller.get_job_details(job_pk)
        if job_details is None:
            return {"ok": False, "error": {"message": f"Job {job_pk} not found"}}
    except Exception as e:
        logger.exception("Failed to get job details for pk=%s", job_pk)
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
        # Use is_relative_to() for secure path containment check
        if not file_path.is_relative_to(work_dir_resolved):
            return {"ok": False, "error": {"message": "Invalid file path"}}
    except Exception as e:
        return {"ok": False, "error": {"message": f"Path resolution error: {e}"}}

    # Check file exists
    if not file_path.exists():
        return {"ok": False, "error": {"message": f"File not found: {file_type}"}}

    if not file_path.is_file():
        return {"ok": False, "error": {"message": f"Not a file: {file_type}"}}

    # Read file content in a thread to avoid blocking the event loop
    try:
        result = await asyncio.to_thread(
            _read_file_with_tail, str(file_path), tail_lines
        )
        return {"ok": True, "data": result}
    except Exception as e:
        logger.exception("Failed to read file %s", file_path)
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
