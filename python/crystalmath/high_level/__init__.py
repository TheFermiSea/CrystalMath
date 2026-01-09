"""High-Level "Batteries Included" API for CrystalMath.

This module provides a simplified, one-liner interface for common materials
science workflows. It wraps the protocol-based architecture defined in
`crystalmath.protocols` to provide:

1. **HighThroughput** - One-liner workflows from structure to publication results
2. **WorkflowBuilder** - Fluent interface for custom workflow construction
3. **AnalysisResults** - Unified results with export to pandas, matplotlib, LaTeX

Example:
    # One-liner workflow
    from crystalmath import HighThroughput

    results = HighThroughput.run_standard_analysis(
        structure="NbOCl2.cif",
        properties=["bands", "dos", "phonon"],
        cluster="beefcake2"
    )

    # Export to publication formats
    results.to_dataframe().to_csv("results.csv")
    results.plot_bands().savefig("bands.png")

    # Fluent builder pattern
    from crystalmath import WorkflowBuilder

    workflow = (
        WorkflowBuilder()
        .from_file("structure.cif")
        .relax(code="vasp")
        .then_bands()
        .on_cluster("beefcake2")
        .build()
    )
    result = workflow.run()

Design Philosophy:
    - Wrap protocols, don't duplicate them
    - Smart defaults with easy overrides
    - Progress tracking for interactive use
    - Publication-quality output

See Also:
    - crystalmath.protocols: Core protocol definitions
    - docs/architecture/HIGH-LEVEL-API.md: Full design documentation
    - docs/architecture/UNIFIED-WORKFLOW-ARCHITECTURE.md: Architecture overview
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Version info
__version__ = "0.1.0"
__status__ = "stub"  # Will be "alpha" after Phase 3 implementation

# Availability flags (set based on import success)
HIGH_LEVEL_API_AVAILABLE = False

if TYPE_CHECKING:
    from .api import HighThroughput, HighThroughputConfig
    from .builder import Workflow, WorkflowBuilder
    from .clusters import ClusterProfile, get_cluster_profile
    from .progress import (
        ConsoleProgressCallback,
        JupyterProgressCallback,
        ProgressUpdate,
    )
    from .registry import PropertyCalculator
    from .results import AnalysisResults

# Graceful import with availability tracking
try:
    from .api import HighThroughput, HighThroughputConfig
    from .builder import Workflow, WorkflowBuilder
    from .clusters import CLUSTER_PROFILES, ClusterProfile, get_cluster_profile
    from .progress import (
        ConsoleProgressCallback,
        JupyterProgressCallback,
        ProgressUpdate,
    )
    from .registry import PropertyCalculator
    from .results import AnalysisResults

    HIGH_LEVEL_API_AVAILABLE = True

except ImportError as e:
    import logging

    logging.getLogger(__name__).debug(f"High-level API import failed: {e}")

    # Provide stubs for type checking
    HighThroughput = None  # type: ignore[assignment, misc]
    HighThroughputConfig = None  # type: ignore[assignment, misc]
    WorkflowBuilder = None  # type: ignore[assignment, misc]
    Workflow = None  # type: ignore[assignment, misc]
    AnalysisResults = None  # type: ignore[assignment, misc]
    ClusterProfile = None  # type: ignore[assignment, misc]
    PropertyCalculator = None  # type: ignore[assignment, misc]
    ProgressUpdate = None  # type: ignore[assignment, misc]
    ConsoleProgressCallback = None  # type: ignore[assignment, misc]
    JupyterProgressCallback = None  # type: ignore[assignment, misc]
    get_cluster_profile = None  # type: ignore[assignment]
    CLUSTER_PROFILES = {}  # type: ignore[assignment]


__all__ = [
    # Version info
    "__version__",
    "__status__",
    "HIGH_LEVEL_API_AVAILABLE",
    # Main API classes
    "HighThroughput",
    "HighThroughputConfig",
    "WorkflowBuilder",
    "Workflow",
    # Results and export
    "AnalysisResults",
    # Cluster configuration
    "ClusterProfile",
    "CLUSTER_PROFILES",
    "get_cluster_profile",
    # Property registry
    "PropertyCalculator",
    # Progress tracking
    "ProgressUpdate",
    "ConsoleProgressCallback",
    "JupyterProgressCallback",
]
