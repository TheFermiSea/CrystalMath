"""
Base interfaces for DFT code output parsing.

Parsers convert raw output files into structured `ParsingResult` objects that
feed downstream workflows and UI components.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..base import DFTCode


@dataclass
class ParsingResult:
    """Normalized results extracted from a DFT calculation output."""

    success: bool
    final_energy: Optional[float]
    energy_unit: str
    convergence_status: str
    scf_cycles: Optional[int] = None
    geometry_converged: Optional[bool] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class OutputParser(ABC):
    """Abstract interface for code-specific output parsers."""

    @abstractmethod
    async def parse(self, output_file: Path) -> ParsingResult:
        """Parse a code output file into a structured `ParsingResult`."""

    @abstractmethod
    def get_energy_unit(self) -> str:
        """Return the energy unit the parser reports (e.g., Hartree, eV)."""


PARSER_REGISTRY: Dict[DFTCode, OutputParser] = {}


def register_parser(code: DFTCode, parser: OutputParser) -> None:
    """Register an output parser for a given DFT code."""

    PARSER_REGISTRY[code] = parser


def get_parser(code: DFTCode) -> OutputParser:
    """Retrieve the parser associated with the provided DFT code.

    Raises:
        KeyError: If no parser has been registered for the code.
    """

    return PARSER_REGISTRY[code]


__all__ = [
    "ParsingResult",
    "OutputParser",
    "PARSER_REGISTRY",
    "register_parser",
    "get_parser",
]
