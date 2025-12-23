"""
CRYSTAL23 CalcJob implementations.

This module contains AiiDA CalcJob classes for running CRYSTAL23 calculations:
    - Crystal23Calculation: Main CalcJob for crystalOMP/PcrystalOMP
    - Crystal23Parser: Output parser for CRYSTAL23 results
"""

from .crystal23 import Crystal23Calculation
from .parser import Crystal23Parser

__all__ = ["Crystal23Calculation", "Crystal23Parser"]
