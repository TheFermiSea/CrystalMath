"""JSON-RPC handler modules for crystalmath-server.

This package contains the handler registry and namespace-based handler modules.
Each module registers its handlers using the @register_handler decorator.

The HANDLER_REGISTRY and register_handler are re-exported from _handlers.py
for backwards compatibility with existing code that imports from this module.

Import order matters - importing this package auto-registers all handlers.
"""

# Re-export from private module for backwards compatibility
from crystalmath.server._handlers import (
    HANDLER_REGISTRY,
    Handler,
    register_handler,
)

__all__ = ["HANDLER_REGISTRY", "Handler", "register_handler"]

# Import handler modules to trigger registration
from . import clusters
from . import jobs
from . import recipes
