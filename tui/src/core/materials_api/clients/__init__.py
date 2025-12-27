"""API client wrappers for Materials Project services.

This module provides async wrappers around the sync API clients:
- MpApiClient: Materials Project API (mp-api)
- MpContribsClient: MPContribs user contributions
- OptimadeClient: OPTIMADE cross-database queries (native async)
"""

from __future__ import annotations

__all__ = [
    "MpApiClient",
    "MpContribsClient",
    "OptimadeClient",
]

# Lazy imports to avoid loading heavy dependencies at module import
def __getattr__(name: str):
    if name == "MpApiClient":
        from .mp_api import MpApiClient
        return MpApiClient
    elif name == "MpContribsClient":
        from .mpcontribs import MpContribsClient
        return MpContribsClient
    elif name == "OptimadeClient":
        from .optimade import OptimadeClient
        return OptimadeClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
