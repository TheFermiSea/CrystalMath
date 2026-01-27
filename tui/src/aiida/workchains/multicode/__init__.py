"""
Multi-code workflow infrastructure for post-SCF calculations.

This module provides orchestration WorkChains that combine CRYSTAL23 SCF
calculations with external codes for advanced electronic structure:

GW/BSE Codes:
    - YAMBO: GW quasi-particle corrections, BSE excitons, nonlinear optics
    - BerkeleyGW: GW and BSE calculations

Wannierization:
    - Wannier90: Maximally-localized Wannier functions

Architecture:
    These workflows use a two-stage approach:
    1. CRYSTAL23 SCF to obtain ground-state wavefunction
    2. Post-processing code for excited-state properties

    The workflows leverage existing AiiDA plugins (aiida-yambo, aiida-wannier90)
    when available, with converters to prepare CRYSTAL23 output.

Example:
    >>> from src.aiida.workchains.multicode import (
    ...     YamboGWWorkChain,
    ...     BerkeleyGWWorkChain,
    ...     YamboNonlinearWorkChain,
    ... )
    >>>
    >>> # GW calculation on top of CRYSTAL23 SCF
    >>> builder = YamboGWWorkChain.get_builder()
    >>> builder.structure = structure
    >>> builder.crystal_code = crystal_code
    >>> builder.yambo_code = yambo_code
    >>> result = engine.run(builder)

Note:
    These workflows require the corresponding AiiDA plugins to be installed:
    - pip install aiida-yambo  (for YAMBO workflows)
    - pip install aiida-wannier90 (for Wannier90 workflows)
"""

from .base import MultiCodeWorkChain, PostSCFWorkChain
from .berkeleygw import BerkeleyGWWorkChain
from .converters import (
    crystal_bands_to_wannier90,
    crystal_to_qe_wavefunction,
    crystal_to_yambo_input,
)
from .yambo_gw import YamboBSEWorkChain, YamboGWWorkChain
from .yambo_nonlinear import YamboNonlinearWorkChain

__all__ = [
    # Base classes
    "MultiCodeWorkChain",
    "PostSCFWorkChain",
    # Converters
    "crystal_to_qe_wavefunction",
    "crystal_to_yambo_input",
    "crystal_bands_to_wannier90",
    # YAMBO workflows
    "YamboGWWorkChain",
    "YamboBSEWorkChain",
    "YamboNonlinearWorkChain",
    # BerkeleyGW workflows
    "BerkeleyGWWorkChain",
]
