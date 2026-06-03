"""
Registry for DFT code configurations.

This module keeps a simple in-memory mapping from `DFTCode` identifiers to
`DFTCodeConfig` instances. Registrations are typically performed by individual
code-specific modules during import time.
"""

from __future__ import annotations

from typing import Dict, List

from .base import DFTCode, DFTCodeConfig

# Global registry populated by code modules
DFT_CODE_REGISTRY: Dict[DFTCode, DFTCodeConfig] = {}


def register_code(code: DFTCode, config: DFTCodeConfig) -> None:
    """Register a code configuration.

    Args:
        code: Identifier for the DFT code.
        config: Configuration describing invocation and parsing defaults.
    """

    DFT_CODE_REGISTRY[code] = config


def get_code_config(code: DFTCode) -> DFTCodeConfig:
    """Return the configuration for a given DFT code.

    Raises:
        KeyError: If the code has not been registered.
    """

    return DFT_CODE_REGISTRY[code]


def list_available_codes() -> List[DFTCode]:
    """Return a list of registered DFT codes."""

    return list(DFT_CODE_REGISTRY.keys())


__all__ = [
    "DFT_CODE_REGISTRY",
    "register_code",
    "get_code_config",
    "list_available_codes",
]
