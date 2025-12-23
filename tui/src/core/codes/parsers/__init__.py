"""Parser registry exports for DFT codes."""

from .base import OutputParser, ParsingResult, get_parser, register_parser, PARSER_REGISTRY

__all__ = [
    "OutputParser",
    "ParsingResult",
    "get_parser",
    "register_parser",
    "PARSER_REGISTRY",
]

# Register built-in parsers
from . import crystal  # noqa: F401  pylint: disable=wrong-import-position
from . import quantum_espresso  # noqa: F401  pylint: disable=wrong-import-position
from . import vasp  # noqa: F401  pylint: disable=wrong-import-position
