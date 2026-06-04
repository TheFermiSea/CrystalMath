"""Materials Project API integration for CrystalMath TUI.

This module provides unified access to:
- Materials Project API (mp-api): Primary source for crystal structures and properties
- MPContribs: User contributions and specialized data
- OPTIMADE: Cross-database federation for fallback searches

Usage:
    from src.core.materials_api import MaterialsService

    async with MaterialsService(db_path="crystal_tui.db") as service:
        result = await service.search_by_formula("MoS2")
        for record in result:
            print(record.material_id, record.formula)

        # Generate CRYSTAL23 input
        d12 = await service.generate_crystal_input("mp-2815")
"""

from __future__ import annotations

from .cache import CacheRepository, generate_cache_key
from .errors import (
    AuthenticationError,
    CacheError,
    MaterialsAPIError,
    NetworkError,
    RateLimitError,
    StructureNotFoundError,
    ValidationError,
)
from .models import CacheEntry, ContributionRecord, MaterialRecord, StructureResult
from .service import MaterialsService
from .settings import MaterialsSettings
from .transforms import (
    BasisSetConfig,
    CrystalD12Generator,
    CrystalSystem,
    HamiltonianConfig,
    OptimizationConfig,
)

__all__ = [
    # Service (main entry point)
    "MaterialsService",
    # Settings
    "MaterialsSettings",
    # Cache
    "CacheRepository",
    "generate_cache_key",
    # Errors
    "MaterialsAPIError",
    "RateLimitError",
    "AuthenticationError",
    "StructureNotFoundError",
    "NetworkError",
    "CacheError",
    "ValidationError",
    # Models
    "MaterialRecord",
    "StructureResult",
    "CacheEntry",
    "ContributionRecord",
    # Transforms
    "BasisSetConfig",
    "CrystalD12Generator",
    "CrystalSystem",
    "HamiltonianConfig",
    "OptimizationConfig",
]
