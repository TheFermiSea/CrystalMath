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

    Returns:
        {
            "clusters": [
                {
                    "name": "nersc-perlmutter",
                    "partition": "regular",
                    "account": "m1234",
                    ...
                },
                ...
            ],
            "workflow_engine": {
                "configured": "parsl" | null,
                "installed": ["parsl", "dask"],
                "quacc_installed": true | false
            }
        }
    """
    from crystalmath.quacc.config import ClusterConfigStore
    from crystalmath.quacc.engines import get_engine_status

    store = ClusterConfigStore()

    return {
        "clusters": store.list_clusters(),
        "workflow_engine": get_engine_status(),
    }
