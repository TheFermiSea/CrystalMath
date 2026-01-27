"""
aiida-common-workflows interface for CRYSTAL23.

This module implements the standardized interface from aiida-common-workflows
that enables multi-code interoperability. By implementing the common interface,
CRYSTAL23 can be used interchangeably with VASP, Quantum ESPRESSO, and other
codes in complex workflows.

Implemented interfaces:
    - CommonRelaxInputGenerator: Standard relaxation workflow inputs
    - CommonRelaxWorkChain: Relaxation workflow with standard outputs

Usage:
    >>> from src.aiida.common_workflows import CrystalCommonRelaxWorkChain
    >>> builder = CrystalCommonRelaxWorkChain.get_builder()
    >>> builder.structure = structure
    >>> builder.protocol = "moderate"  # or "fast", "precise"
    >>> result = engine.run(builder)

Note:
    This module follows the aiida-common-workflows specification:
    https://github.com/aiidateam/aiida-common-workflows
"""

from .relax import (
    CrystalCommonRelaxInputGenerator,
    CrystalCommonRelaxWorkChain,
    ElectronicType,
    RelaxType,
    SpinType,
)

__all__ = [
    "CrystalCommonRelaxInputGenerator",
    "CrystalCommonRelaxWorkChain",
    "RelaxType",
    "SpinType",
    "ElectronicType",
]
