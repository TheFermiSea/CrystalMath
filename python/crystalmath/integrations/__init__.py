"""
CrystalMath Integration Layer.

This package provides adapters and bridges for integrating external workflow
frameworks with CrystalMath's unified workflow architecture.

Supported Integrations:
-----------------------

**atomate2 (via jobflow)**:
    Pre-built materials science workflows for VASP, QE, and other codes.
    Enables access to atomate2's extensive Maker library:
    - RelaxFlowMaker: Geometry optimization
    - StaticFlowMaker: SCF calculations
    - BandStructureFlowMaker: Band structure + DOS
    - ElasticFlowMaker: Elastic tensor calculations
    - PhononFlowMaker: Phonon properties

**jobflow Store Bridge**:
    Connects atomate2's JobStore to CrystalMath's storage backends:
    - MemoryStore -> Local development
    - MongoStore -> Production with MongoDB
    - SQLite bridge -> Integration with .crystal_tui.db

**Multi-code Workflow Adapters**:
    Bridges for code handoffs in complex workflows:
    - VASP -> YAMBO (GW/BSE)
    - QE -> BerkeleyGW
    - CRYSTAL23 -> Wannier90

Design Notes:
-------------
All integrations implement the Protocol interfaces defined in
`crystalmath.protocols`, ensuring consistent behavior regardless
of the underlying execution engine.

Example Usage:
--------------
>>> from crystalmath.integrations import Atomate2Bridge
>>> from crystalmath.protocols import WorkflowType
>>>
>>> # Create bridge with default store
>>> bridge = Atomate2Bridge()
>>>
>>> # Run a VASP relaxation using atomate2
>>> result = bridge.run_flow(
...     workflow_type=WorkflowType.RELAX,
...     structure=structure,
...     code="vasp",
... )

See Also:
---------
- `crystalmath.protocols` - Interface definitions
- `crystalmath.runners` - WorkflowRunner implementations (Phase 3)
- `docs/architecture/ATOMATE2-INTEGRATION.md` - Design documentation
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Version of the integrations package
__version__ = "0.1.0"

# Lazy imports to avoid requiring all dependencies at import time
if TYPE_CHECKING:
    from crystalmath.integrations.atomate2_bridge import (
        Atomate2Bridge,
        Atomate2FlowAdapter,
        FlowMakerRegistry,
        MultiCodeFlowBuilder,
    )
    from crystalmath.integrations.jobflow_store import (
        CrystalMathJobStore,
        JobStoreBridge,
        SQLiteJobStore,
    )


def __getattr__(name: str):
    """Lazy import of integration modules."""
    if name in (
        "Atomate2Bridge",
        "Atomate2FlowAdapter",
        "FlowMakerRegistry",
        "MultiCodeFlowBuilder",
    ):
        from crystalmath.integrations.atomate2_bridge import (
            Atomate2Bridge,
            Atomate2FlowAdapter,
            FlowMakerRegistry,
            MultiCodeFlowBuilder,
        )

        return {
            "Atomate2Bridge": Atomate2Bridge,
            "Atomate2FlowAdapter": Atomate2FlowAdapter,
            "FlowMakerRegistry": FlowMakerRegistry,
            "MultiCodeFlowBuilder": MultiCodeFlowBuilder,
        }[name]

    if name in ("CrystalMathJobStore", "JobStoreBridge", "SQLiteJobStore"):
        from crystalmath.integrations.jobflow_store import (
            CrystalMathJobStore,
            JobStoreBridge,
            SQLiteJobStore,
        )

        return {
            "CrystalMathJobStore": CrystalMathJobStore,
            "JobStoreBridge": JobStoreBridge,
            "SQLiteJobStore": SQLiteJobStore,
        }[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # atomate2 bridge classes
    "Atomate2Bridge",
    "Atomate2FlowAdapter",
    "FlowMakerRegistry",
    "MultiCodeFlowBuilder",
    # jobflow store classes
    "CrystalMathJobStore",
    "JobStoreBridge",
    "SQLiteJobStore",
]
