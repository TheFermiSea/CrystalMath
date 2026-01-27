"""Workflow automation for CrystalMath.

This module provides automated workflow pipelines for common DFT calculations:
- Convergence studies (k-points, basis sets, cutoffs)
- Band structure + DOS calculations
- Phonon calculations (phonopy integration)
- Equation of state fitting

Two approaches are available:
1. **Standalone workflows** - JSON-serializable classes that can be used without AiiDA
2. **AiiDA launcher** - Bridges to existing AiiDA workchains for full provenance

Workflows can be launched from the Rust TUI via the bridge API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bands import BandStructureWorkflow
    from .convergence import ConvergenceWorkflow
    from .eos import EOSWorkflow
    from .phonon import PhononWorkflow

# Graceful import with availability flag
try:
    from .bands import BandStructureWorkflow
    from .convergence import ConvergenceWorkflow
    from .eos import EOSWorkflow
    from .phonon import PhononWorkflow

    WORKFLOWS_AVAILABLE = True
except ImportError as e:
    import logging

    logging.getLogger(__name__).debug(f"Workflow import failed: {e}")
    ConvergenceWorkflow = None  # type: ignore[assignment, misc]
    BandStructureWorkflow = None  # type: ignore[assignment, misc]
    PhononWorkflow = None  # type: ignore[assignment, misc]
    EOSWorkflow = None  # type: ignore[assignment, misc]
    WORKFLOWS_AVAILABLE = False

# AiiDA launcher (separate availability check)
try:
    from .aiida_launcher import (
        WorkflowLaunchResult,
        WorkflowType,
        check_aiida_available,
        check_common_workflows_available,
        extract_restart_geometry,
        get_available_workflows,
        get_workflow_status,
        launch_band_structure,
        launch_eos,
        launch_geometry_optimization,
    )

    AIIDA_LAUNCHER_AVAILABLE = True
except ImportError:
    AIIDA_LAUNCHER_AVAILABLE = False
    check_aiida_available = None  # type: ignore
    get_available_workflows = None  # type: ignore
    launch_geometry_optimization = None  # type: ignore
    launch_band_structure = None  # type: ignore
    launch_eos = None  # type: ignore

__all__ = [
    # Standalone workflows
    "ConvergenceWorkflow",
    "BandStructureWorkflow",
    "PhononWorkflow",
    "EOSWorkflow",
    "WORKFLOWS_AVAILABLE",
    # AiiDA launcher
    "AIIDA_LAUNCHER_AVAILABLE",
    "check_aiida_available",
    "check_common_workflows_available",
    "get_available_workflows",
    "launch_geometry_optimization",
    "launch_band_structure",
    "launch_eos",
    "get_workflow_status",
    "extract_restart_geometry",
    "WorkflowType",
    "WorkflowLaunchResult",
]
