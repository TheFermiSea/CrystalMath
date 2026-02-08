"""RPC handlers for clusters.* namespace."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from crystalmath.server.handlers import register_handler

if TYPE_CHECKING:
    from crystalmath.api import CrystalController


@register_handler("clusters.list")
async def handle_clusters_list(
    controller: CrystalController | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    """List configured clusters and workflow engine status.

    Delegates to CrystalController.get_quacc_clusters_list() if available,
    otherwise falls back to direct query.

    Returns:
        {
            "clusters": [...],
            "workflow_engine": {
                "configured": "parsl" | null,
                "installed": ["parsl", "dask"],
                "quacc_installed": true | false
            }
        }
    """
    if controller is not None:
        return controller.get_quacc_clusters_list()

    # Fallback if controller not available
    from crystalmath.quacc.config import ClusterConfigStore
    from crystalmath.quacc.engines import get_engine_status

    store = ClusterConfigStore()

    return {
        "clusters": store.list_clusters(),
        "workflow_engine": get_engine_status(),
    }
