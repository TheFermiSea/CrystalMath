"""RPC handlers for jobs.* namespace (quacc job tracking)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from crystalmath.server.handlers import register_handler

if TYPE_CHECKING:
    from crystalmath.api import CrystalController


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
