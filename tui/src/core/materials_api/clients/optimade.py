"""Native async OPTIMADE client for cross-database queries.

This module provides an async client for OPTIMADE API endpoints.
Since the official optimade-python-tools client has issues with existing
event loops (defers to sync mode), we implement a custom async HTTP client
using httpx that directly queries OPTIMADE REST APIs.

References:
- OPTIMADE specification: https://github.com/Materials-Consortia/OPTIMADE
- Materials Project OPTIMADE: https://optimade.materialsproject.org
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

try:
    from optimade.adapters.structures.pymatgen import get_pymatgen
    from optimade.models import StructureResource
except ImportError:
    get_pymatgen = None  # type: ignore
    StructureResource = None  # type: ignore

if TYPE_CHECKING:
    from pymatgen.core import Structure

from ..errors import (
    MaterialsAPIError,
    NetworkError,
    RateLimitError,
    ValidationError,
)
from ..models import MaterialRecord, StructureResult
from ..settings import MaterialsSettings

logger = logging.getLogger(__name__)


@dataclass
class ProviderInfo:
    """Information about an OPTIMADE provider."""

    name: str
    base_url: str
    homepage: str | None = None
    description: str | None = None
    is_available: bool = True


class OptimadeClient:
    """Native async client for OPTIMADE API.

    OPTIMADE provides a standardized interface to query multiple materials databases.
    This client primarily queries the Materials Project OPTIMADE endpoint but can
    fall back to other providers (OQMD, AFLOW, COD) for broader searches.

    Unlike the official optimade-python-tools client, this implementation:
    - Uses native async/await with httpx for proper event loop integration
    - Works seamlessly in Textual apps, pytest, Jupyter notebooks
    - Provides consistent error handling with our error classes

    Example:
        async with OptimadeClient() as client:
            result = await client.search_structures(formula="MoS2")
            for record in result:
                print(record.material_id, record.formula)
    """

    # Known OPTIMADE providers with their base URLs
    PROVIDERS = {
        "mp": "https://optimade.materialsproject.org",
        "oqmd": "https://oqmd.org/optimade",
        "aflow": "https://aflow.org/API/optimade",
        "cod": "https://www.crystallography.net/cod/optimade",
        "mc3d": "https://aiida.materialscloud.org/mc3d/optimade",
        "mc2d": "https://aiida.materialscloud.org/mc2d/optimade",
    }

    # OPTIMADE API version prefix
    API_VERSION = "v1"

    def __init__(
        self,
        base_url: str | None = None,
        providers: list[str] | None = None,
        settings: MaterialsSettings | None = None,
    ) -> None:
        """Initialize client.

        Args:
            base_url: Primary OPTIMADE endpoint (default: MP endpoint)
            providers: List of provider keys to query (default: ['mp'])
            settings: Optional MaterialsSettings instance
        """
        self._check_dependencies()

        self.settings = settings or MaterialsSettings.get_instance()
        self.base_url = base_url or self.settings.optimade_mp_base_url
        self.providers = providers or ["mp"]

        # Validate providers
        for provider in self.providers:
            if provider not in self.PROVIDERS:
                logger.warning(
                    f"Unknown OPTIMADE provider: {provider}. "
                    f"Known providers: {list(self.PROVIDERS.keys())}"
                )

        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(self.settings.max_concurrent_requests)

    def _check_dependencies(self) -> None:
        """Verify required dependencies are installed."""
        if httpx is None:
            raise ImportError(
                "httpx is required for async OPTIMADE queries. "
                "Install with: pip install httpx"
            )
        if get_pymatgen is None or StructureResource is None:
            raise ImportError(
                "optimade-python-tools is required for structure conversion. "
                "Install with: pip install optimade[http_client]"
            )

    async def __aenter__(self) -> OptimadeClient:
        """Async context manager entry."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.request_timeout_seconds),
            follow_redirects=True,
            headers={
                "Accept": "application/vnd.api+json",
                "User-Agent": "CrystalMath-TUI/0.1.0",
            },
        )
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get HTTP client, raising if not in context manager."""
        if self._client is None:
            raise RuntimeError(
                "OptimadeClient must be used as async context manager: "
                "async with OptimadeClient() as client: ..."
            )
        return self._client

    def _build_url(self, base_url: str, endpoint: str = "structures") -> str:
        """Build full API URL for endpoint.

        Args:
            base_url: Provider base URL
            endpoint: API endpoint (structures, references, info)

        Returns:
            Full URL with version prefix
        """
        # Normalize base URL
        base = base_url.rstrip("/")
        return f"{base}/{self.API_VERSION}/{endpoint}"

    def _formula_to_filter(self, formula: str) -> str:
        """Convert a formula string to OPTIMADE filter syntax.

        Args:
            formula: Chemical formula (e.g., "MoS2", "Si", "Fe2O3")

        Returns:
            OPTIMADE filter string
        """
        # Simple formula matching - use reduced formula for best compatibility
        # Escape any special characters and quote the formula
        safe_formula = formula.strip()
        return f'chemical_formula_reduced="{safe_formula}"'

    def _elements_to_filter(self, elements: list[str]) -> str:
        """Convert element list to OPTIMADE filter syntax.

        Args:
            elements: List of element symbols (e.g., ["Mo", "S"])

        Returns:
            OPTIMADE filter string
        """
        if not elements:
            return ""

        # Use HAS ALL for structures containing all specified elements
        element_list = ", ".join(f'"{e}"' for e in elements)
        return f"elements HAS ALL {element_list}"

    def _build_filter(
        self,
        filter_query: str | None = None,
        formula: str | None = None,
        elements: list[str] | None = None,
    ) -> str | None:
        """Combine filter parameters into single OPTIMADE filter.

        Args:
            filter_query: Raw OPTIMADE filter
            formula: Formula for reduced formula search
            elements: Element list for composition search

        Returns:
            Combined OPTIMADE filter string or None
        """
        filters = []

        if filter_query:
            filters.append(f"({filter_query})")

        if formula:
            filters.append(f"({self._formula_to_filter(formula)})")

        if elements:
            filters.append(f"({self._elements_to_filter(elements)})")

        if not filters:
            return None

        return " AND ".join(filters)

    async def _fetch_with_retry(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fetch URL with retry logic and error handling.

        Args:
            url: Full URL to fetch
            params: Query parameters

        Returns:
            JSON response as dictionary

        Raises:
            NetworkError: On connection issues
            RateLimitError: When rate limited
            MaterialsAPIError: On other API errors
        """
        last_error: Exception | None = None

        for attempt in range(self.settings.max_retries):
            try:
                async with self._semaphore:
                    response = await self.client.get(url, params=params)

                # Handle rate limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    if attempt < self.settings.max_retries - 1:
                        logger.warning(
                            f"Rate limited by {url}, waiting {retry_after}s..."
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    raise RateLimitError("optimade", retry_after=retry_after)

                # Handle other errors
                if response.status_code >= 400:
                    error_msg = f"OPTIMADE API error: {response.status_code}"
                    try:
                        error_data = response.json()
                        if "errors" in error_data:
                            error_msg = "; ".join(
                                e.get("detail", str(e))
                                for e in error_data["errors"]
                            )
                    except Exception:
                        pass
                    raise MaterialsAPIError(error_msg, source="optimade")

                return response.json()

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < self.settings.max_retries - 1:
                    wait_time = self.settings.retry_delay_seconds * (attempt + 1)
                    logger.warning(f"Timeout on {url}, retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)

            except httpx.RequestError as e:
                last_error = e
                if attempt < self.settings.max_retries - 1:
                    wait_time = self.settings.retry_delay_seconds * (attempt + 1)
                    logger.warning(f"Request error on {url}: {e}, retrying...")
                    await asyncio.sleep(wait_time)

        raise NetworkError("optimade", original_error=last_error)

    def _parse_structure_response(
        self,
        data: dict[str, Any],
        provider: str,
    ) -> list[MaterialRecord]:
        """Parse OPTIMADE structures response into MaterialRecord list.

        Args:
            data: Raw OPTIMADE JSON response
            provider: Provider name for source tracking

        Returns:
            List of MaterialRecord objects
        """
        records = []

        entries = data.get("data", [])
        if not entries:
            return records

        for entry in entries:
            try:
                record = self._entry_to_record(entry, provider)
                if record:
                    records.append(record)
            except Exception as e:
                logger.warning(f"Failed to parse OPTIMADE entry: {e}")
                continue

        return records

    def _entry_to_record(
        self,
        entry: dict[str, Any],
        provider: str,
    ) -> MaterialRecord | None:
        """Convert single OPTIMADE entry to MaterialRecord.

        Args:
            entry: Single structure entry from OPTIMADE response
            provider: Provider name

        Returns:
            MaterialRecord or None if conversion fails
        """
        try:
            # Extract basic info
            entry_id = entry.get("id", "unknown")
            attributes = entry.get("attributes", {})

            # Get formula - try different fields
            formula = (
                attributes.get("chemical_formula_reduced")
                or attributes.get("chemical_formula_descriptive")
                or attributes.get("chemical_formula_hill")
                or ""
            )

            formula_pretty = attributes.get("chemical_formula_descriptive", formula)

            # Try to convert to pymatgen structure
            structure: Structure | None = None
            try:
                # Create StructureResource from entry for conversion
                resource = StructureResource(**entry)
                pmg_obj = get_pymatgen(resource)
                # get_pymatgen may return Structure or Molecule
                # We only want Structure for solid-state materials
                if hasattr(pmg_obj, "lattice"):
                    structure = pmg_obj
            except Exception as e:
                logger.debug(f"Could not convert structure {entry_id}: {e}")

            # Extract properties
            properties: dict[str, Any] = {}

            # Band gap if available
            if "band_gap" in attributes:
                properties["band_gap"] = attributes["band_gap"]

            # Formation energy
            if "formation_energy_per_atom" in attributes:
                properties["formation_energy_per_atom"] = attributes[
                    "formation_energy_per_atom"
                ]

            # Number of sites
            if "nsites" in attributes:
                properties["nsites"] = attributes["nsites"]

            # Elements
            if "elements" in attributes:
                properties["elements"] = attributes["elements"]

            # Extract metadata
            metadata: dict[str, Any] = {
                "provider": provider,
            }

            # Space group info
            if "space_group_symbol" in attributes:
                metadata["symmetry"] = {
                    "symbol": attributes.get("space_group_symbol"),
                    "number": attributes.get("space_group_number"),
                }

            # Dimension info for 2D materials
            if "dimension_types" in attributes:
                metadata["dimension_types"] = attributes["dimension_types"]
            if "nperiodic_dimensions" in attributes:
                metadata["nperiodic_dimensions"] = attributes["nperiodic_dimensions"]

            # Lattice parameters
            if "lattice_vectors" in attributes:
                metadata["lattice_vectors"] = attributes["lattice_vectors"]

            # Species info
            if "species" in attributes:
                metadata["species"] = attributes["species"]

            return MaterialRecord(
                material_id=f"{provider}:{entry_id}",
                source="optimade",
                formula=formula,
                formula_pretty=formula_pretty,
                structure=structure,
                properties=properties,
                metadata=metadata,
            )

        except Exception as e:
            logger.warning(f"Failed to create MaterialRecord from entry: {e}")
            return None

    async def search_structures(
        self,
        filter_query: str | None = None,
        formula: str | None = None,
        elements: list[str] | None = None,
        limit: int = 50,
        response_fields: list[str] | None = None,
    ) -> StructureResult:
        """Search structures using OPTIMADE filter syntax.

        Args:
            filter_query: Raw OPTIMADE filter (e.g., 'chemical_formula_reduced="MoS2"')
            formula: Simplified formula search (converted to filter)
            elements: Element list for composition search
            limit: Max results (default 50, max depends on provider)
            response_fields: Specific fields to request (None for all)

        Returns:
            StructureResult with matching MaterialRecord objects

        Example:
            # Search by formula
            result = await client.search_structures(formula="MoS2")

            # Search by elements
            result = await client.search_structures(elements=["Mo", "S"])

            # Raw OPTIMADE filter
            result = await client.search_structures(
                filter_query='nelements=2 AND elements HAS ALL "Mo","S"'
            )
        """
        combined_filter = self._build_filter(filter_query, formula, elements)

        # Build query parameters
        params: dict[str, Any] = {
            "page_limit": min(limit, 100),  # Most providers cap at 100
        }

        if combined_filter:
            params["filter"] = combined_filter

        if response_fields:
            params["response_fields"] = ",".join(response_fields)

        # Use primary provider (first in list)
        primary_provider = self.providers[0]
        base_url = self.PROVIDERS.get(primary_provider, self.base_url)
        url = self._build_url(base_url)

        logger.debug(f"OPTIMADE query: {url} params={params}")

        errors: dict[str, str] = {}
        try:
            data = await self._fetch_with_retry(url, params)
        except NetworkError as e:
            # Record the error instead of silently returning empty results
            error_msg = str(e.original_error) if e.original_error else str(e)
            logger.error(f"Network error querying OPTIMADE provider {primary_provider}: {e}")
            errors[primary_provider] = f"Network error: {error_msg}"
            return StructureResult(
                records=[],
                total_count=0,
                source="optimade",
                query={"filter": combined_filter, "limit": limit},
                errors=errors,
            )
        except MaterialsAPIError as e:
            # Also track non-network API errors
            logger.error(f"API error querying OPTIMADE provider {primary_provider}: {e}")
            errors[primary_provider] = str(e)
            return StructureResult(
                records=[],
                total_count=0,
                source="optimade",
                query={"filter": combined_filter, "limit": limit},
                errors=errors,
            )

        records = self._parse_structure_response(data, primary_provider)

        # Get total count from meta
        meta = data.get("meta", {})
        total_count = meta.get("data_returned", len(records))

        return StructureResult(
            records=records,
            total_count=total_count,
            source="optimade",
            query={"filter": combined_filter, "limit": limit},
        )

    async def get_structure_by_id(
        self,
        structure_id: str,
        provider: str = "mp",
    ) -> MaterialRecord | None:
        """Fetch a specific structure by ID.

        Args:
            structure_id: Structure ID (provider-specific format)
            provider: Provider key (default: "mp")

        Returns:
            MaterialRecord or None if not found

        Example:
            # Fetch specific MP structure
            record = await client.get_structure_by_id("mp-2534", provider="mp")
        """
        base_url = self.PROVIDERS.get(provider)
        if not base_url:
            raise ValidationError(
                "provider",
                f"Unknown provider: {provider}. "
                f"Known: {list(self.PROVIDERS.keys())}",
            )

        url = self._build_url(base_url, f"structures/{structure_id}")

        try:
            data = await self._fetch_with_retry(url)
        except MaterialsAPIError as e:
            if "404" in str(e) or "not found" in str(e).lower():
                return None
            raise

        # Single structure response has 'data' as object, not list
        entry = data.get("data")
        if not entry:
            return None

        return self._entry_to_record(entry, provider)

    async def search_across_providers(
        self,
        formula: str | None = None,
        elements: list[str] | None = None,
        filter_query: str | None = None,
        providers: list[str] | None = None,
        limit_per_provider: int = 20,
    ) -> StructureResult:
        """Search across multiple OPTIMADE providers in parallel.

        Use this for fallback when structure not found in primary provider,
        or for comprehensive searches across databases.

        Args:
            formula: Formula to search
            elements: Element list for composition search
            filter_query: Raw OPTIMADE filter
            providers: Provider keys to query (default: all configured)
            limit_per_provider: Max results per provider

        Returns:
            StructureResult aggregating results from all providers

        Example:
            # Search across all major providers
            result = await client.search_across_providers(
                formula="MoS2",
                providers=["mp", "oqmd", "cod"],
                limit_per_provider=10,
            )
        """
        target_providers = providers or self.providers

        combined_filter = self._build_filter(filter_query, formula, elements)

        async def query_provider(
            provider: str,
        ) -> tuple[str, list[MaterialRecord], str | None]:
            """Query single provider and return (provider, records, error_msg)."""
            base_url = self.PROVIDERS.get(provider)
            if not base_url:
                logger.warning(f"Unknown provider: {provider}")
                return provider, [], f"Unknown provider: {provider}"

            url = self._build_url(base_url)
            params: dict[str, Any] = {
                "page_limit": min(limit_per_provider, 100),
            }
            if combined_filter:
                params["filter"] = combined_filter

            try:
                data = await self._fetch_with_retry(url, params)
                records = self._parse_structure_response(data, provider)
                return provider, records, None
            except NetworkError as e:
                error_msg = str(e.original_error) if e.original_error else str(e)
                logger.warning(f"Network error querying provider {provider}: {e}")
                return provider, [], f"Network error: {error_msg}"
            except MaterialsAPIError as e:
                logger.warning(f"API error querying provider {provider}: {e}")
                return provider, [], str(e)
            except Exception as e:
                logger.warning(f"Unexpected error querying provider {provider}: {e}")
                return provider, [], f"Unexpected error: {e}"

        # Query all providers in parallel
        tasks = [query_provider(p) for p in target_providers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Aggregate results and track errors
        all_records: list[MaterialRecord] = []
        provider_counts: dict[str, int] = {}
        errors: dict[str, str] = {}

        for result in results:
            if isinstance(result, Exception):
                # Should not happen since we catch in query_provider, but safety net
                logger.warning(f"Provider query raised exception: {result}")
                continue
            provider, records, error_msg = result
            all_records.extend(records)
            provider_counts[provider] = len(records)
            if error_msg:
                errors[provider] = error_msg

        logger.info(f"OPTIMADE multi-provider results: {provider_counts}, errors: {list(errors.keys())}")

        return StructureResult(
            records=all_records,
            total_count=len(all_records),
            source="optimade",
            query={
                "filter": combined_filter,
                "providers": target_providers,
                "limit_per_provider": limit_per_provider,
            },
            errors=errors,
        )

    async def get_provider_info(self, provider: str) -> ProviderInfo | None:
        """Get information about an OPTIMADE provider.

        Args:
            provider: Provider key

        Returns:
            ProviderInfo or None if unavailable
        """
        base_url = self.PROVIDERS.get(provider)
        if not base_url:
            return None

        url = self._build_url(base_url, "info")

        try:
            data = await self._fetch_with_retry(url)
            info = data.get("data", {}).get("attributes", {})
            return ProviderInfo(
                name=info.get("name", provider),
                base_url=base_url,
                homepage=info.get("homepage"),
                description=info.get("description"),
                is_available=True,
            )
        except Exception as e:
            logger.warning(f"Could not get info for provider {provider}: {e}")
            return ProviderInfo(
                name=provider,
                base_url=base_url,
                is_available=False,
            )

    async def list_available_providers(self) -> list[ProviderInfo]:
        """Check availability of all known providers.

        Returns:
            List of ProviderInfo for all providers (with availability status)
        """
        tasks = [self.get_provider_info(p) for p in self.PROVIDERS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        providers = []
        for result in results:
            if isinstance(result, ProviderInfo):
                providers.append(result)

        return providers
