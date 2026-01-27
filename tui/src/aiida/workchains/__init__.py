"""
CRYSTAL23 WorkChain implementations.

This module contains AiiDA WorkChains for CRYSTAL23 workflows:

Core Workflows:
    - CrystalBaseWorkChain: Self-healing base workflow with adaptive error recovery
    - CrystalGeometryOptimizationWorkChain: Geometry optimization workflow
    - CrystalBandStructureWorkChain: Electronic band structure calculation
    - CrystalDOSWorkChain: Density of states calculation

Multi-Code Workflows (requires external plugins):
    - YamboGWWorkChain: GW quasi-particle corrections (requires aiida-yambo)
    - YamboBSEWorkChain: BSE exciton calculation (requires aiida-yambo)
    - YamboNonlinearWorkChain: Nonlinear optics (requires aiida-yambo)
    - BerkeleyGWWorkChain: BerkeleyGW GW+BSE calculations

Diagnostics utilities:
    - analyze_scf_from_parsed_output: Analyze SCF from parsed params (preferred)
    - analyze_scf_convergence: Analyze SCF from raw output (fallback)
    - recommend_parameter_modifications: Get adaptive parameter suggestions
    - ConvergencePattern: Enum for convergence behavior classification
    - FailureReason: Enum for root cause identification
"""

from .crystal_bands import CrystalBandStructureWorkChain
from .crystal_base import CrystalBaseWorkChain
from .crystal_dos import CrystalDOSWorkChain
from .crystal_geopt import CrystalGeometryOptimizationWorkChain
from .diagnostics import (
    ConvergencePattern,
    FailureReason,
    SCFDiagnostics,
    analyze_scf_convergence,
    analyze_scf_from_parsed_output,
    estimate_resources,
    recommend_parameter_modifications,
)

# Multi-code workflows (lazy imports to avoid requiring external plugins)
try:
    from .multicode import (
        BerkeleyGWWorkChain,
        MultiCodeWorkChain,
        PostSCFWorkChain,
        YamboBSEWorkChain,
        YamboGWWorkChain,
        YamboNonlinearWorkChain,
        crystal_bands_to_wannier90,
        crystal_to_qe_wavefunction,
        crystal_to_yambo_input,
    )

    MULTICODE_AVAILABLE = True
except ImportError:
    MULTICODE_AVAILABLE = False
    MultiCodeWorkChain = None
    PostSCFWorkChain = None
    YamboGWWorkChain = None
    YamboBSEWorkChain = None
    YamboNonlinearWorkChain = None
    BerkeleyGWWorkChain = None
    crystal_to_qe_wavefunction = None
    crystal_to_yambo_input = None
    crystal_bands_to_wannier90 = None

__all__ = [
    # Core CRYSTAL23 workflows
    "CrystalBaseWorkChain",
    "CrystalGeometryOptimizationWorkChain",
    "CrystalBandStructureWorkChain",
    "CrystalDOSWorkChain",
    # Multi-code workflows
    "MultiCodeWorkChain",
    "PostSCFWorkChain",
    "YamboGWWorkChain",
    "YamboBSEWorkChain",
    "YamboNonlinearWorkChain",
    "BerkeleyGWWorkChain",
    # Converters
    "crystal_to_qe_wavefunction",
    "crystal_to_yambo_input",
    "crystal_bands_to_wannier90",
    # Diagnostics
    "analyze_scf_from_parsed_output",
    "analyze_scf_convergence",
    "recommend_parameter_modifications",
    "estimate_resources",
    "ConvergencePattern",
    "FailureReason",
    "SCFDiagnostics",
    # Availability flags
    "MULTICODE_AVAILABLE",
]
