"""
Quacc integration module for CrystalMath.

This module provides the foundation for quacc workflow integration:

- **Recipe Discovery**: Introspect quacc.recipes.vasp to find available
  job and flow functions dynamically.

- **Engine Detection**: Detect installed and configured workflow engines
  (Parsl, Dask, Prefect, Covalent, Jobflow).

- **Cluster Configuration**: Store and retrieve Parsl cluster configurations
  for SLURM job submission.

- **Job Tracking**: Track job metadata and status for monitoring purposes.

All functions gracefully handle the case where quacc is not installed,
returning empty results rather than raising exceptions.

Example:
    >>> from crystalmath.quacc import discover_vasp_recipes, get_engine_status
    >>> recipes = discover_vasp_recipes()
    >>> status = get_engine_status()
    >>> print(f"Found {len(recipes)} recipes, quacc installed: {status['quacc_installed']}")
"""

from crystalmath.quacc.discovery import discover_vasp_recipes
from crystalmath.quacc.engines import (
    get_workflow_engine,
    get_installed_engines,
    get_engine_status,
)

__all__ = [
    "discover_vasp_recipes",
    "get_workflow_engine",
    "get_installed_engines",
    "get_engine_status",
]
