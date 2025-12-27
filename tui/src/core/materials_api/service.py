"""MaterialsService: Unified orchestrator for Materials Project API integration.

This module provides a high-level service that coordinates between multiple
Materials Project API clients, handles caching, rate limiting, and fallback
strategies. It serves as the main entry point for the TUI to interact with
Materials Project data sources.

Key Features:
- Unified interface to MP API, MPContribs, and OPTIMADE
- Lazy client initialization (only creates clients when needed)
- Cache-first strategy with configurable TTL
- Automatic fallback: MP API -> OPTIMADE when structure not found
- Rate limiting via semaphore
- Async context manager for proper resource cleanup

Example:
    async with MaterialsService() as service:
        # Search by formula
        result = await service.search_by_formula("MoS2")
        for record in result:
            print(record.material_id, record.formula)

        # Get structure and generate CRYSTAL23 input
        record = await service.get_structure("mp-2815")
        if record and record.structure:
            d12_content = await service.generate_crystal_input("mp-2815")
            print(d12_content)
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .cache import generate_cache_key
from .clients.mp_api import MpApiClient
from .clients.mpcontribs import MpContribsClient
from .clients.optimade import OptimadeClient
from .errors import (
    CacheError,
    MaterialsAPIError,
    NetworkError,
    StructureNotFoundError,
    ValidationError,
)
from .models import ContributionRecord, MaterialRecord, StructureResult
from .settings import MaterialsSettings
from .transforms.crystal_d12 import CrystalD12Generator, OptimizationConfig

if TYPE_CHECKING:
    from pymatgen.core import Structure

logger = logging.getLogger(__name__)


@runtime_checkable
class CacheRepositoryProtocol(Protocol):
    """Protocol for cache repository implementations.

    This protocol defines the interface that cache repositories must implement.
    The actual implementation (e.g., SQLite-based) will be in cache.py.
    """

    async def get(self, cache_key: str) -> dict[str, Any] | None:
        """Retrieve cached data by key.

        Args:
            cache_key: Unique cache key

        Returns:
            Cached data as dictionary, or None if not found/expired
        """
        ...

    async def set(
        self,
        cache_key: str,
        data: dict[str, Any],
        source: str,
        ttl_days: int | None = None,
    ) -> None:
        """Store data in cache.

        Args:
            cache_key: Unique cache key
            data: Data to cache (must be JSON-serializable)
            source: API source identifier
            ttl_days: Time-to-live in days (None for default)
        """
        ...

    async def invalidate(self, cache_key: str) -> None:
        """Remove entry from cache.

        Args:
            cache_key: Cache key to invalidate
        """
        ...

    async def clear_expired(self) -> int:
        """Remove all expired entries from cache.

        Returns:
            Number of entries removed
        """
        ...


class MaterialsService:
    """Unified orchestrator for Materials Project API integration.

    This service provides a single entry point for all Materials Project
    interactions, coordinating between multiple API clients and handling
    caching, rate limiting, and fallback strategies.

    The service uses lazy initialization for API clients, only creating
    them when first needed. This minimizes resource usage and startup time.

    Attributes:
        settings: MaterialsSettings configuration
        cache: Optional CacheRepositoryProtocol for caching responses

    Example:
        # Basic usage with context manager
        async with MaterialsService() as service:
            result = await service.search_by_formula("Si")
            print(f"Found {len(result)} materials")

        # With custom settings
        settings = MaterialsSettings(cache_ttl_days=7)
        async with MaterialsService(settings=settings) as service:
            record = await service.get_structure("mp-149")
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        settings: MaterialsSettings | None = None,
        cache: CacheRepositoryProtocol | None = None,
    ) -> None:
        """Initialize the MaterialsService.

        Args:
            db_path: Optional path to SQLite database for caching.
                     If provided and cache is None, will attempt to create
                     a CacheRepository from cache.py (if available).
            settings: MaterialsSettings instance (uses singleton if None)
            cache: Optional cache repository implementing CacheRepositoryProtocol
        """
        self._settings = settings or MaterialsSettings.get_instance()
        self._db_path = Path(db_path) if db_path else None
        self._cache = cache

        # Rate limiting semaphore
        self._semaphore = asyncio.Semaphore(self._settings.max_concurrent_requests)

        # Lazy-initialized API clients
        self._mp_client: MpApiClient | None = None
        self._mpcontribs_client: MpContribsClient | None = None
        self._optimade_client: OptimadeClient | None = None

        # Locks for client initialization
        self._mp_client_lock = asyncio.Lock()
        self._mpcontribs_client_lock = asyncio.Lock()
        self._optimade_client_lock = asyncio.Lock()

        # Track if we're in context manager
        self._entered = False

    async def __aenter__(self) -> "MaterialsService":
        """Enter async context manager.

        Initializes the cache repository if db_path was provided.

        Returns:
            Self for use in async with statement
        """
        self._entered = True

        # Initialize cache if db_path provided and no cache given
        if self._db_path and self._cache is None:
            try:
                # Try to import and create CacheRepository
                # This will be implemented in cache.py
                from .cache import CacheRepository

                self._cache = await CacheRepository.create(self._db_path)
                logger.debug("Cache repository initialized at %s", self._db_path)
            except ImportError:
                logger.debug("CacheRepository not available, caching disabled")
            except Exception as e:
                logger.warning("Failed to initialize cache: %s", e)

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit async context manager.

        Cleans up all initialized API clients and the cache repository.
        """
        self._entered = False

        # Close MP API client
        if self._mp_client is not None:
            await self._mp_client.close()
            self._mp_client = None

        # MPContribs client doesn't have explicit close
        self._mpcontribs_client = None

        # Close OPTIMADE client
        if self._optimade_client is not None:
            await self._optimade_client.__aexit__(exc_type, exc_val, exc_tb)
            self._optimade_client = None

        # Close cache if it has a close method
        if self._cache is not None and hasattr(self._cache, "close"):
            try:
                await self._cache.close()
            except Exception as e:
                logger.warning("Error closing cache: %s", e)
            self._cache = None

        logger.debug("MaterialsService resources cleaned up")

    @property
    def settings(self) -> MaterialsSettings:
        """Get the current settings."""
        return self._settings

    @property
    def cache(self) -> CacheRepositoryProtocol | None:
        """Get the cache repository, if available."""
        return self._cache

    async def _get_mp_client(self) -> MpApiClient:
        """Get or create the MP API client.

        Returns:
            Initialized MpApiClient

        Raises:
            RuntimeError: If not in context manager
        """
        if not self._entered:
            raise RuntimeError(
                "MaterialsService must be used as async context manager: "
                "async with MaterialsService() as service: ..."
            )

        async with self._mp_client_lock:
            if self._mp_client is None:
                self._mp_client = MpApiClient(settings=self._settings)
                logger.debug("MpApiClient initialized")
            return self._mp_client

    async def _get_mpcontribs_client(self) -> MpContribsClient:
        """Get or create the MPContribs client.

        Returns:
            Initialized MpContribsClient

        Raises:
            RuntimeError: If not in context manager
        """
        if not self._entered:
            raise RuntimeError(
                "MaterialsService must be used as async context manager"
            )

        async with self._mpcontribs_client_lock:
            if self._mpcontribs_client is None:
                self._mpcontribs_client = MpContribsClient()
                logger.debug("MpContribsClient initialized")
            return self._mpcontribs_client

    async def _get_optimade_client(self) -> OptimadeClient:
        """Get or create the OPTIMADE client.

        Returns:
            Initialized OptimadeClient (entered into context)

        Raises:
            RuntimeError: If not in context manager
        """
        if not self._entered:
            raise RuntimeError(
                "MaterialsService must be used as async context manager"
            )

        async with self._optimade_client_lock:
            if self._optimade_client is None:
                client = OptimadeClient(settings=self._settings)
                await client.__aenter__()
                self._optimade_client = client
                logger.debug("OptimadeClient initialized")
            return self._optimade_client

    def _generate_cache_key(self, prefix: str, **kwargs: Any) -> str:
        """Generate a deterministic cache key from parameters.

        Uses the shared generate_cache_key function for consistency with
        CacheRepository and external callers.

        Args:
            prefix: Cache key prefix (e.g., 'search_formula', 'get_structure')
            **kwargs: Parameters to include in the key

        Returns:
            Prefixed cache key string (e.g., 'search_formula:a1b2c3d4')
        """
        return generate_cache_key(kwargs, prefix=prefix)

    async def _check_cache(self, cache_key: str) -> dict[str, Any] | None:
        """Check cache for existing data.

        Args:
            cache_key: Cache key to look up

        Returns:
            Cached data or None if not found/expired
        """
        if self._cache is None:
            return None

        try:
            return await self._cache.get(cache_key)
        except Exception as e:
            logger.warning("Cache read error for %s: %s", cache_key, e)
            return None

    async def _store_cache(
        self,
        cache_key: str,
        data: dict[str, Any],
        source: str,
    ) -> None:
        """Store data in cache.

        Args:
            cache_key: Cache key
            data: Data to cache
            source: API source identifier
        """
        if self._cache is None:
            return

        try:
            await self._cache.set(
                cache_key,
                data,
                source,
                ttl_days=self._settings.cache_ttl_days,
            )
        except Exception as e:
            logger.warning("Cache write error for %s: %s", cache_key, e)

    def _records_to_dict(self, records: list[MaterialRecord]) -> list[dict[str, Any]]:
        """Convert MaterialRecord list to JSON-serializable dicts."""
        return [r.to_dict() for r in records]

    def _dict_to_records(self, data: list[dict[str, Any]]) -> list[MaterialRecord]:
        """Convert dict list back to MaterialRecord objects."""
        return [MaterialRecord.from_dict(d) for d in data]

    async def search_by_formula(
        self,
        formula: str,
        include_contributions: bool = False,
        limit: int = 50,
    ) -> StructureResult:
        """Search for materials by chemical formula.

        Searches the Materials Project API for materials matching the given
        formula. Optionally includes MPContribs data for matching materials.

        Implements cache-first strategy: checks cache before making API calls.

        Args:
            formula: Chemical formula (e.g., 'MoS2', 'Si', 'Li-Fe-O')
            include_contributions: If True, fetch MPContribs data for results
            limit: Maximum number of results to return

        Returns:
            StructureResult containing matching MaterialRecord objects

        Raises:
            AuthenticationError: If API key is invalid
            RateLimitError: If rate limit exceeded
            NetworkError: On connection issues
            MaterialsAPIError: For other API errors

        Example:
            result = await service.search_by_formula("MoS2")
            for record in result:
                print(f"{record.material_id}: {record.formula}")
        """
        # Generate cache key
        cache_key = self._generate_cache_key(
            "search_formula",
            formula=formula,
            include_contributions=include_contributions,
            limit=limit,
        )

        # Check cache first
        cached = await self._check_cache(cache_key)
        if cached is not None:
            logger.debug("Cache hit for formula search: %s", formula)
            records = self._dict_to_records(cached.get("records", []))
            return StructureResult(
                records=records,
                total_count=cached.get("total_count", len(records)),
                source="mp",
                query={"formula": formula, "limit": limit},
                cached=True,
                cache_age_seconds=cached.get("cache_age_seconds"),
            )

        # Cache miss - fetch from API
        async with self._semaphore:
            client = await self._get_mp_client()
            records = await client.search_by_formula(formula, limit=limit)

        # Optionally fetch contributions
        if include_contributions and records:
            records = await self._enrich_with_contributions(records)

        # Build result
        result = StructureResult(
            records=records,
            total_count=len(records),
            source="mp",
            query={"formula": formula, "limit": limit},
            cached=False,
        )

        # Store in cache
        cache_data = {
            "records": self._records_to_dict(records),
            "total_count": len(records),
        }
        await self._store_cache(cache_key, cache_data, "mp")

        return result

    async def search_by_elements(
        self,
        elements: list[str],
        include_contributions: bool = False,
        exclude_elements: list[str] | None = None,
        limit: int = 50,
    ) -> StructureResult:
        """Search for materials containing specific elements.

        Searches the Materials Project API for materials that contain all
        specified elements. Optionally excludes materials with certain elements.

        Args:
            elements: Required elements (e.g., ['Mo', 'S'])
            include_contributions: If True, fetch MPContribs data for results
            exclude_elements: Elements to exclude from results
            limit: Maximum number of results

        Returns:
            StructureResult containing matching MaterialRecord objects

        Raises:
            AuthenticationError: If API key is invalid
            RateLimitError: If rate limit exceeded
            NetworkError: On connection issues

        Example:
            result = await service.search_by_elements(
                elements=['Li', 'Fe', 'O'],
                exclude_elements=['F'],
                limit=20,
            )
        """
        # Validate elements
        if not elements:
            raise ValidationError("elements", "At least one element is required")

        # Generate cache key
        cache_key = self._generate_cache_key(
            "search_elements",
            elements=sorted(elements),
            exclude_elements=sorted(exclude_elements or []),
            include_contributions=include_contributions,
            limit=limit,
        )

        # Check cache first
        cached = await self._check_cache(cache_key)
        if cached is not None:
            logger.debug("Cache hit for element search: %s", elements)
            records = self._dict_to_records(cached.get("records", []))
            return StructureResult(
                records=records,
                total_count=cached.get("total_count", len(records)),
                source="mp",
                query={"elements": elements, "limit": limit},
                cached=True,
                cache_age_seconds=cached.get("cache_age_seconds"),
            )

        # Cache miss - fetch from API
        async with self._semaphore:
            client = await self._get_mp_client()
            records = await client.search_by_elements(
                elements,
                exclude_elements=exclude_elements,
                limit=limit,
            )

        # Optionally fetch contributions
        if include_contributions and records:
            records = await self._enrich_with_contributions(records)

        # Build result
        result = StructureResult(
            records=records,
            total_count=len(records),
            source="mp",
            query={"elements": elements, "limit": limit},
            cached=False,
        )

        # Store in cache
        cache_data = {
            "records": self._records_to_dict(records),
            "total_count": len(records),
        }
        await self._store_cache(cache_key, cache_data, "mp")

        return result

    async def get_structure(
        self,
        material_id: str,
        fallback_to_optimade: bool = True,
    ) -> MaterialRecord | None:
        """Fetch a specific structure by material ID.

        Retrieves the structure for a given Materials Project ID. If not found
        and fallback_to_optimade is True, attempts to find it via OPTIMADE.

        Args:
            material_id: Materials Project ID (e.g., 'mp-149', 'mp-2815')
            fallback_to_optimade: If True, try OPTIMADE when MP API fails

        Returns:
            MaterialRecord with structure, or None if not found

        Raises:
            AuthenticationError: If API key is invalid
            RateLimitError: If rate limit exceeded
            NetworkError: On connection issues

        Example:
            record = await service.get_structure("mp-149")
            if record and record.structure:
                print(f"Found {record.formula} with {len(record.structure)} sites")
        """
        # Validate material_id format
        if not material_id.startswith("mp-"):
            raise ValidationError(
                "material_id",
                f"Invalid Materials Project ID format: {material_id}. "
                "Expected format: 'mp-XXXXX'",
            )

        # Generate cache key
        cache_key = self._generate_cache_key("get_structure", material_id=material_id)

        # Check cache first
        cached = await self._check_cache(cache_key)
        if cached is not None:
            logger.debug("Cache hit for structure: %s", material_id)
            return MaterialRecord.from_dict(cached)

        # Cache miss - try MP API first
        record: MaterialRecord | None = None

        try:
            async with self._semaphore:
                client = await self._get_mp_client()
                structure = await client.get_structure(material_id)

            if structure:
                # Fetch additional properties to build MaterialRecord
                properties = await client.get_properties(material_id)
                record = MaterialRecord(
                    material_id=material_id,
                    source="mp",
                    formula=structure.composition.reduced_formula,
                    formula_pretty=structure.composition.reduced_formula,
                    structure=structure,
                    properties=properties,
                    metadata={},
                )
        except (StructureNotFoundError, NetworkError) as e:
            logger.debug("MP API failed for %s: %s", material_id, e)

        # Fallback to OPTIMADE if MP API didn't return a structure
        if record is None and fallback_to_optimade:
            logger.debug("Falling back to OPTIMADE for %s", material_id)
            record = await self._fetch_from_optimade(material_id)

        # Cache the result if found
        if record is not None:
            await self._store_cache(cache_key, record.to_dict(), record.source)

        return record

    async def _fetch_from_optimade(self, material_id: str) -> MaterialRecord | None:
        """Fetch structure from OPTIMADE as fallback.

        Args:
            material_id: Materials Project ID

        Returns:
            MaterialRecord or None if not found
        """
        try:
            async with self._semaphore:
                client = await self._get_optimade_client()
                # OPTIMADE uses different ID format; try without 'mp-' prefix
                optimade_id = material_id
                record = await client.get_structure_by_id(optimade_id, provider="mp")
                return record
        except Exception as e:
            logger.debug("OPTIMADE fallback failed for %s: %s", material_id, e)
            return None

    async def _enrich_with_contributions(
        self,
        records: list[MaterialRecord],
    ) -> list[MaterialRecord]:
        """Enrich MaterialRecords with MPContribs data.

        Args:
            records: List of MaterialRecord to enrich

        Returns:
            Records with contribution data added to metadata
        """
        client = await self._get_mpcontribs_client()

        async def fetch_contributions(record: MaterialRecord) -> MaterialRecord:
            """Fetch contributions for a single record."""
            try:
                async with self._semaphore:
                    contributions = await client.search_by_material_id(
                        record.material_id
                    )
                if contributions:
                    record.metadata["contributions"] = [
                        c.to_dict() for c in contributions
                    ]
            except Exception as e:
                logger.debug(
                    "Failed to fetch contributions for %s: %s",
                    record.material_id,
                    e,
                )
            return record

        # Fetch contributions in parallel, respecting rate limits
        tasks = [fetch_contributions(r) for r in records]
        enriched = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions and return valid records
        return [
            r for r in enriched
            if isinstance(r, MaterialRecord)
        ]

    async def get_contributions(
        self,
        material_id: str,
        project: str | None = None,
    ) -> list[ContributionRecord]:
        """Fetch MPContribs contributions for a material.

        Retrieves user-contributed data (experimental results, computed
        properties, etc.) associated with a Materials Project ID.

        Args:
            material_id: Materials Project ID (e.g., 'mp-149')
            project: Optional project name to filter contributions

        Returns:
            List of ContributionRecord objects

        Raises:
            AuthenticationError: If API key is invalid
            MaterialsAPIError: For other API errors

        Example:
            contributions = await service.get_contributions("mp-149")
            for contrib in contributions:
                print(f"Project: {contrib.project}, Data: {contrib.data}")
        """
        # Generate cache key
        cache_key = self._generate_cache_key(
            "get_contributions",
            material_id=material_id,
            project=project,
        )

        # Check cache first
        cached = await self._check_cache(cache_key)
        if cached is not None:
            logger.debug("Cache hit for contributions: %s", material_id)
            return [ContributionRecord.from_dict(c) for c in cached.get("contributions", [])]

        # Cache miss - fetch from API
        async with self._semaphore:
            client = await self._get_mpcontribs_client()

            if project:
                # Fetch from specific project
                contributions = await client.get_contributions(
                    project,
                    material_id=material_id,
                )
            else:
                # Search across all projects
                contributions = await client.search_by_material_id(material_id)

        # Store in cache
        cache_data = {"contributions": [c.to_dict() for c in contributions]}
        await self._store_cache(cache_key, cache_data, "mpcontribs")

        return contributions

    async def search_optimade(
        self,
        formula: str,
        providers: list[str] | None = None,
        limit: int = 50,
    ) -> StructureResult:
        """Search structures across OPTIMADE providers.

        Queries the OPTIMADE API for structures matching a formula.
        Can search across multiple providers (Materials Project, OQMD,
        AFLOW, COD, etc.) in parallel.

        Args:
            formula: Chemical formula to search
            providers: List of provider keys (default: ['mp'])
                      Available: 'mp', 'oqmd', 'aflow', 'cod', 'mc3d', 'mc2d'
            limit: Maximum results per provider

        Returns:
            StructureResult aggregating results from all providers

        Raises:
            NetworkError: On connection issues
            MaterialsAPIError: For other API errors

        Example:
            # Search Materials Project only
            result = await service.search_optimade("MoS2")

            # Search multiple providers
            result = await service.search_optimade(
                "Si",
                providers=["mp", "oqmd", "cod"],
                limit=20,
            )
        """
        # Generate cache key
        cache_key = self._generate_cache_key(
            "search_optimade",
            formula=formula,
            providers=sorted(providers or ["mp"]),
            limit=limit,
        )

        # Check cache first
        cached = await self._check_cache(cache_key)
        if cached is not None:
            logger.debug("Cache hit for OPTIMADE search: %s", formula)
            records = self._dict_to_records(cached.get("records", []))
            return StructureResult(
                records=records,
                total_count=cached.get("total_count", len(records)),
                source="optimade",
                query={"formula": formula, "providers": providers},
                cached=True,
                cache_age_seconds=cached.get("cache_age_seconds"),
            )

        # Cache miss - fetch from API
        async with self._semaphore:
            client = await self._get_optimade_client()

            if providers and len(providers) > 1:
                # Multi-provider search
                result = await client.search_across_providers(
                    formula=formula,
                    providers=providers,
                    limit_per_provider=limit,
                )
            else:
                # Single provider search
                result = await client.search_structures(
                    formula=formula,
                    limit=limit,
                )

        # Store in cache
        cache_data = {
            "records": self._records_to_dict(result.records),
            "total_count": result.total_count,
        }
        await self._store_cache(cache_key, cache_data, "optimade")

        return result

    async def generate_crystal_input(
        self,
        material_id: str,
        config: dict[str, Any] | None = None,
    ) -> str:
        """Generate CRYSTAL23 .d12 input file for a material.

        Fetches the structure from the Materials Project (or cache) and
        generates a CRYSTAL23 input file using the configured parameters.

        Args:
            material_id: Materials Project ID (e.g., 'mp-149')
            config: Optional configuration dictionary with keys:
                - title: Custom title (default: uses MP ID and formula)
                - functional: DFT functional (default: 'PBE')
                - basis_set: Basis set library (default: 'POB-TZVP-REV2')
                - shrink: k-point mesh tuple (default: (8, 8))
                - optimize: Enable geometry optimization (default: False)
                - opt_type: Optimization type (default: 'FULLOPTG')
                - maxcycle: Max SCF iterations (default: 200)
                - toldee: Energy convergence (default: 8)
                - grid: Integration grid (default: 'XLGRID')
                - tolinteg: Integration tolerances (default: (7,7,7,7,14))
                - fmixing: Fock matrix mixing (default: None)
                - levshift: Level shift parameters (default: None)

        Returns:
            Complete .d12 input file content as string

        Raises:
            StructureNotFoundError: If material not found
            ValidationError: If material has no structure data

        Example:
            d12 = await service.generate_crystal_input(
                "mp-2815",
                config={
                    "functional": "B3LYP",
                    "shrink": (12, 12),
                    "optimize": True,
                    "opt_type": "ATOMONLY",
                },
            )
            with open("input.d12", "w") as f:
                f.write(d12)
        """
        # Fetch the structure
        record = await self.get_structure(material_id, fallback_to_optimade=True)

        if record is None:
            raise StructureNotFoundError(
                material_id,
                source="mp",
                message=f"Material {material_id} not found in any data source",
            )

        if record.structure is None:
            raise ValidationError(
                "structure",
                f"Material {material_id} has no structure data available",
            )

        # Build configuration from defaults and user overrides
        config = config or {}

        # Default configuration values
        functional = config.get("functional", "PBE")
        basis_set = config.get("basis_set", "POB-TZVP-REV2")
        shrink = config.get("shrink", (8, 8))
        optimize = config.get("optimize", False)
        opt_type = config.get("opt_type", "FULLOPTG")
        maxcycle = config.get("maxcycle", 200)
        toldee = config.get("toldee", 8)
        grid = config.get("grid", "XLGRID")
        tolinteg = config.get("tolinteg", (7, 7, 7, 7, 14))
        fmixing = config.get("fmixing")
        levshift = config.get("levshift")

        # Build title if not provided
        title = config.get("title")
        if title is None:
            title = f"{record.formula} ({material_id}) - {functional}"

        # Create optimization config if needed
        optimization = None
        if optimize:
            optimization = OptimizationConfig(
                enabled=True,
                opt_type=opt_type,
                toldee=toldee,
            )

        # Generate .d12 content
        d12_content = CrystalD12Generator.generate_full_input(
            record.structure,
            title=title,
            basis_set=basis_set,
            functional=functional,
            shrink=shrink,
            tolinteg=tolinteg,
            maxcycle=maxcycle,
            toldee=toldee,
            fmixing=fmixing,
            levshift=levshift,
            grid=grid,
            optimization=optimization,
        )

        return d12_content
