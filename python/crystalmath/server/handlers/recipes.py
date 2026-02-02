"""RPC handlers for recipes.* namespace."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from crystalmath.server.handlers import register_handler

if TYPE_CHECKING:
    from crystalmath.api import CrystalController


@register_handler("recipes.list")
async def handle_recipes_list(
    controller: CrystalController | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    """List available quacc VASP recipes.

    Returns:
        {
            "recipes": [
                {
                    "name": "relax_job",
                    "module": "quacc.recipes.vasp.core",
                    "fullname": "quacc.recipes.vasp.core.relax_job",
                    "docstring": "Relax structure...",
                    "signature": "(atoms, ...)",
                    "type": "job"
                },
                ...
            ],
            "quacc_version": "0.11.2" | null,
            "error": null | "error message"
        }
    """
    try:
        from crystalmath.quacc.discovery import discover_vasp_recipes

        recipes = discover_vasp_recipes()

        # Get quacc version if available
        try:
            import quacc

            quacc_version = getattr(quacc, "__version__", "unknown")
        except ImportError:
            quacc_version = None

        return {
            "recipes": recipes,
            "quacc_version": quacc_version,
            "error": None,
        }
    except ImportError as e:
        return {
            "recipes": [],
            "quacc_version": None,
            "error": f"quacc not available: {e}",
        }
    except Exception as e:
        return {
            "recipes": [],
            "quacc_version": None,
            "error": f"Error discovering recipes: {e}",
        }
