"""Async wrapper for Materials Project API (mp-api).

This module provides an async client for the Materials Project API that wraps
the synchronous MPRester with asyncio.to_thread for non-blocking TUI operation.

Example:
    client = MpApiClient(api_key="your_key")
    structure = await client.get_structure("mp-149")
    records = await client.search_by_formula("MoS2")
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import TYPE_CHECKING, Any

from ..errors import (
    AuthenticationError,
    MaterialsAPIError,
    NetworkError,
    RateLimitError,
    StructureNotFoundError,
    ValidationError,
)
from ..models import MaterialRecord
from ..settings import MaterialsSettings

if TYPE_CHECKING:
    from pymatgen.core import Structure

logger = logging.getLogger(__name__)

# Source identifier for MaterialRecord
_SOURCE = "mp"


class MpApiClient:
    """Async client for Materials Project API.

    Wraps the synchronous MPRester with asyncio.to_thread for non-blocking operation.
    Uses semaphore for rate limiting.

    Attributes:
        api_key: Materials Project API key
        max_concurrent: Maximum concurrent requests

    Example:
        async with MpApiClient(api_key="your_key") as client:
            structure = await client.get_structure("mp-149")
    """

    def __init__(
        self,
        api_key: str | None = None,
        max_concurrent: int | None = None,
        settings: MaterialsSettings | None = None,
    ) -> None:
        """Initialize client.

        Args:
            api_key: MP API key (falls back to MP_API_KEY env var or settings)
            max_concurrent: Max concurrent requests (defaults to settings value)
            settings: Optional MaterialsSettings instance
        """
        self._settings = settings or MaterialsSettings.get_instance()

        # API key resolution: explicit > env var > settings
        self._api_key = (
            api_key
            or os.getenv("MP_API_KEY")
            or self._settings.mp_api_key
        )

        # Concurrency control
        self._max_concurrent = max_concurrent or self._settings.max_concurrent_requests
        self._semaphore = asyncio.Semaphore(self._max_concurrent)

        # Lazy-loaded MPRester instance (avoid import overhead at module load)
        self._mpr: Any = None
        self._mpr_lock = asyncio.Lock()
        # Thread-safe lock for serializing MPRester access within worker threads
        # (MPRester may not be thread-safe when accessed concurrently)
        self._mpr_thread_lock = threading.Lock()

    async def _get_mpr(self) -> Any:
        """Lazy-load and return MPRester instance.

        Thread-safe initialization of the MPRester client.

        Returns:
            MPRester instance

        Raises:
            AuthenticationError: If API key is not configured
            NetworkError: If connection to MP API fails
        """
        async with self._mpr_lock:
            if self._mpr is None:
                if not self._api_key:
                    raise AuthenticationError(
                        _SOURCE,
                        "MP_API_KEY not configured. Set via environment variable "
                        "or pass api_key to MpApiClient."
                    )

                try:
                    # Import and instantiate MPRester in thread to avoid blocking
                    def _create_mpr():
                        from mp_api.client import MPRester
                        return MPRester(api_key=self._api_key)

                    self._mpr = await asyncio.to_thread(_create_mpr)
                    logger.debug("MPRester client initialized")
                except ImportError as e:
                    raise MaterialsAPIError(
                        f"mp-api package not installed. Install with: pip install mp-api",
                        source=_SOURCE,
                    ) from e
                except Exception as e:
                    raise self._convert_exception(e)

            return self._mpr

    def _convert_exception(self, exc: Exception) -> MaterialsAPIError:
        """Convert mp-api exceptions to our error types.

        Args:
            exc: Exception from mp-api

        Returns:
            Appropriate MaterialsAPIError subclass
        """
        exc_str = str(exc).lower()

        # Check for authentication errors
        if "401" in exc_str or "unauthorized" in exc_str or "invalid api key" in exc_str:
            return AuthenticationError(_SOURCE)

        # Check for rate limiting
        if "429" in exc_str or "rate limit" in exc_str or "too many requests" in exc_str:
            # Try to extract retry-after if available
            retry_after = None
            if "retry" in exc_str:
                import re
                match = re.search(r"(\d+)\s*(?:second|sec|s)", exc_str)
                if match:
                    retry_after = int(match.group(1))
            return RateLimitError(_SOURCE, retry_after=retry_after)

        # Check for network errors
        if any(s in exc_str for s in ["connection", "timeout", "network", "unreachable"]):
            return NetworkError(_SOURCE, original_error=exc)

        # Check for not found
        if "404" in exc_str or "not found" in exc_str:
            return StructureNotFoundError("unknown", source=_SOURCE)

        # Generic API error
        return MaterialsAPIError(str(exc), source=_SOURCE)

    async def _run_sync(self, func, *args, **kwargs) -> Any:
        """Run a synchronous function with rate limiting and thread safety.

        Wraps the sync call with semaphore for concurrency control
        and asyncio.to_thread for non-blocking execution. Uses a threading
        lock inside the worker thread to serialize MPRester access.

        Args:
            func: Synchronous function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result of the function call

        Raises:
            MaterialsAPIError: On API errors
        """
        # Wrap the function to acquire thread lock before calling MPRester
        def _thread_safe_call():
            with self._mpr_thread_lock:
                return func(*args, **kwargs)

        async with self._semaphore:
            try:
                return await asyncio.to_thread(_thread_safe_call)
            except Exception as e:
                # Don't re-wrap our own exceptions
                if isinstance(e, MaterialsAPIError):
                    raise
                raise self._convert_exception(e)

    async def get_structure(self, material_id: str) -> Structure | None:
        """Fetch structure by material ID (e.g., 'mp-149').

        Args:
            material_id: Materials Project ID (e.g., 'mp-149')

        Returns:
            pymatgen Structure if found, None otherwise

        Raises:
            AuthenticationError: If API key is invalid
            RateLimitError: If rate limit exceeded
            NetworkError: On connection issues
        """
        mpr = await self._get_mpr()

        def _fetch():
            try:
                # Use the summary endpoint which includes structure
                docs = mpr.materials.summary.search(
                    material_ids=[material_id],
                    fields=["structure"],
                )
                if docs and len(docs) > 0 and docs[0].structure:
                    return docs[0].structure
                return None
            except Exception as e:
                if "not found" in str(e).lower() or "no materials" in str(e).lower():
                    return None
                raise

        try:
            return await self._run_sync(_fetch)
        except StructureNotFoundError:
            return None

    async def search_by_formula(
        self,
        formula: str,
        fields: list[str] | None = None,
        limit: int = 50,
    ) -> list[MaterialRecord]:
        """Search materials by formula (e.g., 'MoS2', 'Li-Fe-O').

        Args:
            formula: Chemical formula or chemsys (e.g., 'MoS2', 'Li-Fe-O')
            fields: Optional list of fields to retrieve
            limit: Maximum number of results (default 50)

        Returns:
            List of MaterialRecord objects

        Raises:
            AuthenticationError: If API key is invalid
            RateLimitError: If rate limit exceeded
            NetworkError: On connection issues
        """
        mpr = await self._get_mpr()

        # Default fields for MaterialRecord construction
        default_fields = [
            "material_id",
            "formula_pretty",
            "structure",
            "band_gap",
            "formation_energy_per_atom",
            "energy_above_hull",
            "symmetry",
        ]
        query_fields = list(set(default_fields + (fields or [])))

        def _search():
            # Determine if this is a chemsys (contains hyphens) or formula
            if "-" in formula:
                # Chemsys search (e.g., "Li-Fe-O")
                docs = mpr.materials.summary.search(
                    chemsys=formula,
                    fields=query_fields,
                    num_chunks=1,
                )
            else:
                # Formula search
                docs = mpr.materials.summary.search(
                    formula=formula,
                    fields=query_fields,
                    num_chunks=1,
                )

            # Apply limit
            docs = docs[:limit] if docs else []
            return docs

        docs = await self._run_sync(_search)
        return [self._doc_to_record(doc) for doc in docs]

    async def search_by_elements(
        self,
        elements: list[str],
        exclude_elements: list[str] | None = None,
        limit: int = 50,
    ) -> list[MaterialRecord]:
        """Search by element composition.

        Args:
            elements: Required elements (e.g., ['Mo', 'S'])
            exclude_elements: Elements to exclude
            limit: Maximum number of results

        Returns:
            List of MaterialRecord objects

        Raises:
            AuthenticationError: If API key is invalid
            RateLimitError: If rate limit exceeded
            NetworkError: On connection issues
        """
        mpr = await self._get_mpr()

        default_fields = [
            "material_id",
            "formula_pretty",
            "structure",
            "band_gap",
            "formation_energy_per_atom",
            "energy_above_hull",
            "symmetry",
        ]

        def _search():
            kwargs = {
                "elements": elements,
                "fields": default_fields,
                "num_chunks": 1,
            }
            if exclude_elements:
                kwargs["exclude_elements"] = exclude_elements

            docs = mpr.materials.summary.search(**kwargs)
            docs = docs[:limit] if docs else []
            return docs

        docs = await self._run_sync(_search)
        return [self._doc_to_record(doc) for doc in docs]

    async def get_properties(
        self,
        material_id: str,
        properties: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch computed properties for a material.

        Args:
            material_id: Materials Project ID (e.g., 'mp-149')
            properties: Optional list of specific properties to retrieve.
                       If None, returns common properties.

        Returns:
            Dictionary of property name -> value

        Raises:
            StructureNotFoundError: If material not found
            AuthenticationError: If API key is invalid
            RateLimitError: If rate limit exceeded
        """
        mpr = await self._get_mpr()

        # Common properties if none specified
        default_properties = [
            "band_gap",
            "formation_energy_per_atom",
            "energy_above_hull",
            "is_stable",
            "density",
            "volume",
            "nsites",
            "nelements",
            "symmetry",
            "total_magnetization",
            "is_magnetic",
        ]
        query_fields = properties or default_properties

        def _fetch():
            docs = mpr.materials.summary.search(
                material_ids=[material_id],
                fields=query_fields,
            )
            if not docs:
                return None
            return docs[0]

        doc = await self._run_sync(_fetch)

        if doc is None:
            raise StructureNotFoundError(material_id, source=_SOURCE)

        # Convert doc to dict, handling both dict and object responses
        result = {}
        for prop in query_fields:
            try:
                if hasattr(doc, prop):
                    value = getattr(doc, prop)
                elif isinstance(doc, dict):
                    value = doc.get(prop)
                else:
                    continue

                # Skip None values
                if value is not None:
                    # Handle nested objects (like symmetry)
                    if hasattr(value, "dict"):
                        result[prop] = value.dict()
                    elif hasattr(value, "__dict__") and not isinstance(value, (str, int, float, bool)):
                        result[prop] = dict(value.__dict__)
                    else:
                        result[prop] = value
            except Exception:
                # Skip properties that fail to retrieve
                continue

        return result

    def _doc_to_record(self, doc: Any) -> MaterialRecord:
        """Convert an MP API document to MaterialRecord.

        Args:
            doc: MPRester document (SummaryDoc or similar)

        Returns:
            MaterialRecord instance
        """
        # Extract material_id
        material_id = str(getattr(doc, "material_id", "unknown"))

        # Extract formula
        formula = getattr(doc, "formula_pretty", None) or str(getattr(doc, "composition", ""))

        # Extract structure if available
        structure = getattr(doc, "structure", None)

        # Build properties dict
        properties = {}
        prop_names = [
            "band_gap",
            "formation_energy_per_atom",
            "energy_above_hull",
            "is_stable",
            "density",
            "volume",
            "nsites",
            "total_magnetization",
        ]
        for prop in prop_names:
            val = getattr(doc, prop, None)
            if val is not None:
                properties[prop] = val

        # Build metadata dict
        metadata = {}

        # Add symmetry info
        symmetry = getattr(doc, "symmetry", None)
        if symmetry:
            if hasattr(symmetry, "symbol"):
                metadata["symmetry"] = {
                    "symbol": symmetry.symbol,
                    "number": getattr(symmetry, "number", None),
                    "crystal_system": getattr(symmetry, "crystal_system", None),
                }
            elif isinstance(symmetry, dict):
                metadata["symmetry"] = symmetry

        return MaterialRecord(
            material_id=material_id,
            source=_SOURCE,
            formula=formula,
            formula_pretty=formula,
            structure=structure,
            properties=properties,
            metadata=metadata,
        )

    async def close(self) -> None:
        """Close the client and release resources.

        Safe to call multiple times.
        """
        async with self._mpr_lock:
            if self._mpr is not None:
                # MPRester doesn't have an explicit close method,
                # but we clear the reference to allow garbage collection
                self._mpr = None
                logger.debug("MPRester client closed")

    async def __aenter__(self) -> "MpApiClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
