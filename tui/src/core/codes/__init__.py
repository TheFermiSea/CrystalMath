"""DFT code abstraction layer exports."""

from .base import DFTCode, DFTCodeConfig, InvocationStyle
from .parsers.base import OutputParser, ParsingResult, get_parser, register_parser
from .registry import DFT_CODE_REGISTRY, get_code_config, register_code, list_available_codes

__all__ = [
    # Enums and Config
    "DFTCode",
    "DFTCodeConfig",
    "InvocationStyle",
    # Parser classes
    "OutputParser",
    "ParsingResult",
    # Registry functions
    "get_code_config",
    "register_code",
    "list_available_codes",
    "get_parser",
    "register_parser",
    "DFT_CODE_REGISTRY",
]

# Register built-in code configurations
from . import crystal  # noqa: F401  pylint: disable=wrong-import-position
from . import quantum_espresso  # noqa: F401  pylint: disable=wrong-import-position
from . import vasp  # noqa: F401  pylint: disable=wrong-import-position
