import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("crystalmath.server.registry")


class UnifiedDispatchRegistry:
    """
    Centralized domain.verb JSON-RPC lookup matrix.
    Resolves crystalmath-oho.4 and crystalmath-dew.
    """

    def __init__(self):
        self._registry: dict[str, Callable[..., Any]] = {}

    def register(self, method_name: str):
        """Decorator to cleanly bind incoming backend capabilities."""

        def decorator(func: Callable[..., Any]):
            self._registry[method_name] = func
            return func

        return decorator

    def dispatch(self, method_name: str, *args, **kwargs) -> Any:
        if method_name not in self._registry:
            logger.error(f"Method resolution failure: '{method_name}' not found in unified table.")
            raise ValueError(f"Method '{method_name}' not found.")
        return self._registry[method_name](*args, **kwargs)


# Global singleton router
rpc_registry = UnifiedDispatchRegistry()
