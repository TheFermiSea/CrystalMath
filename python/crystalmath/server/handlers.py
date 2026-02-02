"""JSON-RPC method handlers for crystalmath-server.

This module defines the handler registry for JSON-RPC methods.
Handlers follow the signature: async def handler(controller, params: dict) -> dict

The system.* namespace contains server lifecycle methods.
Other namespaces (jobs.*, clusters.*, etc.) delegate to CrystalController.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Coroutine

if TYPE_CHECKING:
    from crystalmath.api import CrystalController

# Type alias for handler functions
Handler = Callable[
    ["CrystalController | None", dict[str, Any]],
    Coroutine[Any, Any, dict[str, Any]],
]

# Handler registry: method name -> async handler function
HANDLER_REGISTRY: dict[str, Handler] = {}


def register_handler(method: str) -> Callable[[Handler], Handler]:
    """Decorator to register a JSON-RPC handler.

    Example:
        @register_handler("system.ping")
        async def handle_system_ping(controller, params):
            return {"pong": True}
    """

    def decorator(func: Handler) -> Handler:
        HANDLER_REGISTRY[method] = func
        return func

    return decorator


# =============================================================================
# System namespace handlers (server lifecycle)
# =============================================================================


@register_handler("system.ping")
async def handle_system_ping(
    controller: CrystalController | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Health check endpoint.

    Returns:
        {"pong": True, "timestamp": "ISO8601 string"}
    """
    return {
        "pong": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@register_handler("system.shutdown")
async def handle_system_shutdown(
    controller: CrystalController | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Request graceful server shutdown.

    The server will stop accepting new connections and exit after
    responding to this request.

    Returns:
        {"acknowledged": True}
    """
    # The server checks for this response and initiates shutdown
    return {"acknowledged": True, "action": "shutdown"}


@register_handler("system.version")
async def handle_system_version(
    controller: CrystalController | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Return server version information.

    Returns:
        {"version": "X.Y.Z", "protocol": "json-rpc-2.0"}
    """
    try:
        from crystalmath import __version__
    except ImportError:
        __version__ = "0.0.0"

    return {
        "version": __version__,
        "protocol": "json-rpc-2.0",
        "transport": "unix-socket",
    }
