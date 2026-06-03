"""Parser registry exports for DFT codes (vendored, ADR-006, crystalmath-xi1).

Minimal version of the original ``tui/src/core/codes/parsers/__init__.py``: it
re-exports only the registry primitives from ``base`` and does NOT eagerly
import the concrete crystal/quantum_espresso/vasp parser modules, which are
outside the vendored closure.
"""

from .base import OutputParser, ParsingResult, get_parser, register_parser, PARSER_REGISTRY

__all__ = [
    "OutputParser",
    "ParsingResult",
    "get_parser",
    "register_parser",
    "PARSER_REGISTRY",
]
