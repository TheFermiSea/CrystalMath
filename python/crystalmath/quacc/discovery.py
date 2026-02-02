"""
Recipe discovery for quacc VASP workflows.

This module provides introspection of quacc.recipes.vasp to discover
available job and flow recipes dynamically.
"""

import inspect
import logging
import pkgutil
from importlib import import_module
from typing import Any

logger = logging.getLogger(__name__)


def discover_vasp_recipes() -> list[dict[str, Any]]:
    """
    Discover all VASP recipes from quacc.recipes.vasp.

    Walks the quacc.recipes.vasp package and finds all functions
    ending in _job or _flow.

    Returns:
        List of recipe metadata dicts with keys:
        - name: Function name (e.g., "relax_job")
        - module: Module path (e.g., "quacc.recipes.vasp.core")
        - fullname: Full import path (e.g., "quacc.recipes.vasp.core.relax_job")
        - docstring: Function docstring or None
        - signature: String representation of function signature
        - type: "job" or "flow"

    Notes:
        Returns empty list if quacc is not installed.
        Submodule ImportErrors are caught and logged at DEBUG level,
        allowing discovery to continue for other modules.
    """
    recipes: list[dict[str, Any]] = []

    # Try to import quacc top-level
    try:
        import quacc.recipes.vasp as vasp_recipes
    except ImportError as e:
        logger.warning(f"quacc.recipes.vasp not available: {e}")
        return recipes

    # Walk all submodules of quacc.recipes.vasp
    try:
        package_path = vasp_recipes.__path__
    except AttributeError:
        logger.debug("quacc.recipes.vasp has no __path__, treating as single module")
        package_path = None

    if package_path is None:
        # Single module, not a package
        _extract_recipes_from_module(vasp_recipes, recipes)
        return recipes

    # Walk subpackages
    for importer, modname, ispkg in pkgutil.walk_packages(
        path=package_path,
        prefix="quacc.recipes.vasp.",
    ):
        try:
            module = import_module(modname)
            _extract_recipes_from_module(module, recipes)
        except ImportError as e:
            # Submodule has missing dependencies (e.g., MLIP modules)
            logger.debug(f"Skipping module {modname}: {e}")
            continue
        except Exception as e:
            # Catch any other errors during module loading
            logger.debug(f"Error loading module {modname}: {e}")
            continue

    return recipes


def _extract_recipes_from_module(
    module: Any, recipes: list[dict[str, Any]]
) -> None:
    """
    Extract recipe functions from a module.

    Args:
        module: The module to inspect
        recipes: List to append recipe dicts to (modified in place)
    """
    module_name = module.__name__

    try:
        members = inspect.getmembers(module, inspect.isfunction)
    except ImportError as e:
        # Some modules may raise ImportError when inspecting members
        logger.debug(f"Skipping member inspection for {module_name}: {e}")
        return

    for name, func in members:
        # Only include functions defined in this module (not imports)
        if getattr(func, "__module__", None) != module_name:
            continue

        # Check if it's a recipe function
        if name.endswith("_job"):
            recipe_type = "job"
        elif name.endswith("_flow"):
            recipe_type = "flow"
        else:
            continue

        # Extract signature
        try:
            sig = str(inspect.signature(func))
        except (ValueError, TypeError):
            sig = "(...)"

        # Extract docstring
        docstring = inspect.getdoc(func)

        recipes.append({
            "name": name,
            "module": module_name,
            "fullname": f"{module_name}.{name}",
            "docstring": docstring,
            "signature": sig,
            "type": recipe_type,
        })
