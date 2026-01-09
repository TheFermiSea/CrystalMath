"""Materials Project API integration for CrystalMath.

This module provides a synchronous client wrapper for the Materials Project API
(mp-api), enabling easy retrieval of crystal structures and computed properties.

Features:
---------
- Simple structure retrieval by MP ID
- Material search by formula, elements, or properties
- Computed property access (band gap, formation energy, etc.)
- In-memory caching to reduce API calls
- Graceful rate limit handling

Example Usage:
--------------
>>> from crystalmath.integrations.materials_project import MPClient, mp_id_to_structure
>>>
>>> # Quick structure retrieval
>>> structure = mp_id_to_structure("mp-149")  # Silicon
>>>
>>> # Client with search capabilities
>>> client = MPClient()
>>> materials = client.search_structures(formula="MoS2", is_stable=True)
>>> for mat in materials:
...     print(f"{mat.mp_id}: {mat.formula} (gap={mat.band_gap} eV)")

Environment Variables:
----------------------
- MP_API_KEY: Materials Project API key (required)

Dependencies:
-------------
- mp-api (optional, install with: pip install mp-api)
- pymatgen (for Structure type)

See Also:
---------
- https://docs.materialsproject.org/downloading-data/using-the-api
- crystalmath.tui.src.core.materials_api for async TUI integration
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pymatgen.core import Structure

logger = logging.getLogger(__name__)

# MP ID validation pattern
_MP_ID_PATTERN = re.compile(r"^mp-\d+$")


# ============================================================================
# Exceptions
# ============================================================================


class MPClientError(Exception):
    """Base exception for Materials Project client errors."""

    pass


class MPAuthenticationError(MPClientError):
    """Raised when API key is missing or invalid."""

    pass


class MPRateLimitError(MPClientError):
    """Raised when API rate limit is exceeded."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class MPNotFoundError(MPClientError):
    """Raised when a material is not found."""

    def __init__(self, mp_id: str) -> None:
        super().__init__(f"Material not found: {mp_id}")
        self.mp_id = mp_id


class MPDependencyError(MPClientError):
    """Raised when mp-api package is not installed."""

    pass


# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class MPMaterial:
    """Materials Project material summary.

    Represents a material from the Materials Project database with
    essential properties for workflow decisions.

    Attributes:
        mp_id: Materials Project ID (e.g., 'mp-149')
        formula: Chemical formula (e.g., 'Si', 'MoS2')
        structure: pymatgen Structure object
        energy_above_hull: Energy above convex hull (eV/atom)
        band_gap: Electronic band gap (eV), None for metals
        is_stable: Whether material is thermodynamically stable
    """

    mp_id: str
    formula: str
    structure: "Structure"
    energy_above_hull: float
    band_gap: float | None
    is_stable: bool

    @property
    def is_metal(self) -> bool:
        """Check if material is metallic (zero band gap)."""
        return self.band_gap is not None and self.band_gap == 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "mp_id": self.mp_id,
            "formula": self.formula,
            "structure": self.structure.as_dict() if self.structure else None,
            "energy_above_hull": self.energy_above_hull,
            "band_gap": self.band_gap,
            "is_stable": self.is_stable,
        }


@dataclass
class MPProperties:
    """Computed properties from Materials Project.

    Contains DFT-computed properties for a material, useful for
    comparison with CrystalMath calculations.

    Attributes:
        mp_id: Materials Project ID
        formation_energy_per_atom: Formation energy (eV/atom)
        energy_above_hull: Energy above convex hull (eV/atom)
        band_gap: Electronic band gap (eV), None for metals
        is_metal: Whether material is metallic
        elastic_tensor: Elastic tensor data if available
        dielectric_constant: Static dielectric constant if available
    """

    mp_id: str
    formation_energy_per_atom: float
    energy_above_hull: float
    band_gap: float | None
    is_metal: bool
    elastic_tensor: dict | None = None
    dielectric_constant: float | None = None

    # Additional optional properties
    density: float | None = field(default=None)
    volume: float | None = field(default=None)
    total_magnetization: float | None = field(default=None)
    symmetry: dict | None = field(default=None)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "mp_id": self.mp_id,
            "formation_energy_per_atom": self.formation_energy_per_atom,
            "energy_above_hull": self.energy_above_hull,
            "band_gap": self.band_gap,
            "is_metal": self.is_metal,
            "elastic_tensor": self.elastic_tensor,
            "dielectric_constant": self.dielectric_constant,
            "density": self.density,
            "volume": self.volume,
            "total_magnetization": self.total_magnetization,
            "symmetry": self.symmetry,
        }


# ============================================================================
# MP Client
# ============================================================================


class MPClient:
    """Materials Project API client wrapper.

    Provides synchronous access to the Materials Project database with
    built-in caching and rate limit handling.

    Example:
        >>> client = MPClient()
        >>> structure = client.get_structure("mp-149")
        >>> print(structure.formula)
        Si2

        >>> materials = client.search_structures(
        ...     elements=["Mo", "S"],
        ...     is_stable=True,
        ...     limit=5
        ... )

    Attributes:
        api_key: Materials Project API key
        cache_enabled: Whether to use in-memory caching
    """

    def __init__(
        self,
        api_key: str | None = None,
        cache_enabled: bool = True,
        rate_limit_retries: int = 3,
    ) -> None:
        """Initialize with API key.

        Args:
            api_key: Materials Project API key. If not provided, reads from
                    MP_API_KEY environment variable.
            cache_enabled: Enable in-memory caching of structures (default True)
            rate_limit_retries: Number of retries on rate limit (default 3)

        Raises:
            MPAuthenticationError: If no API key is available
        """
        self._api_key = api_key or os.getenv("MP_API_KEY")
        if not self._api_key:
            raise MPAuthenticationError(
                "MP_API_KEY not configured. Set via environment variable or "
                "pass api_key parameter."
            )

        self._cache_enabled = cache_enabled
        self._rate_limit_retries = rate_limit_retries

        # Lazy-loaded MPRester instance
        self._mpr: Any = None

        # Simple in-memory cache: mp_id -> Structure
        self._structure_cache: dict[str, "Structure"] = {}

    def _get_mpr(self) -> Any:
        """Get or create MPRester instance.

        Returns:
            MPRester instance

        Raises:
            MPDependencyError: If mp-api is not installed
        """
        if self._mpr is None:
            try:
                from mp_api.client import MPRester

                self._mpr = MPRester(api_key=self._api_key)
                logger.debug("MPRester client initialized")
            except ImportError as e:
                raise MPDependencyError(
                    "mp-api package not installed. Install with: pip install mp-api"
                ) from e
        return self._mpr

    def _handle_rate_limit(self, exc: Exception) -> int | None:
        """Extract retry-after from rate limit error.

        Args:
            exc: Exception that may be a rate limit error

        Returns:
            Retry-after seconds if extractable, None otherwise
        """
        exc_str = str(exc).lower()
        if "429" in exc_str or "rate limit" in exc_str:
            # Try to extract retry-after
            match = re.search(r"(\d+)\s*(?:second|sec|s)", exc_str)
            if match:
                return int(match.group(1))
            return 60  # Default retry after
        return None

    def _run_with_retry(self, func, *args, **kwargs) -> Any:
        """Run function with rate limit retry logic.

        Args:
            func: Function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result

        Raises:
            MPRateLimitError: If rate limit exceeded after retries
            MPClientError: On other API errors
        """
        last_error = None
        for attempt in range(self._rate_limit_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                retry_after = self._handle_rate_limit(e)
                if retry_after is not None:
                    last_error = e
                    if attempt < self._rate_limit_retries:
                        logger.warning(
                            f"Rate limited, waiting {retry_after}s (attempt {attempt + 1})"
                        )
                        time.sleep(retry_after)
                        continue
                    raise MPRateLimitError(
                        f"Rate limit exceeded after {self._rate_limit_retries} retries",
                        retry_after=retry_after,
                    ) from e
                # Not a rate limit error, re-raise
                raise MPClientError(str(e)) from e

        # Should not reach here, but just in case
        raise MPClientError(str(last_error)) from last_error

    def get_structure(self, mp_id: str) -> "Structure":
        """Get structure by Materials Project ID.

        Args:
            mp_id: Materials Project ID (e.g., 'mp-149', 'mp-1234')

        Returns:
            pymatgen Structure object

        Raises:
            MPNotFoundError: If material not found
            MPRateLimitError: If rate limit exceeded
            MPClientError: On other API errors

        Example:
            >>> client = MPClient()
            >>> si = client.get_structure("mp-149")
            >>> print(si.composition)
            Si2
        """
        if not validate_mp_id(mp_id):
            raise MPClientError(f"Invalid MP ID format: {mp_id}")

        # Check cache
        if self._cache_enabled and mp_id in self._structure_cache:
            logger.debug(f"Cache hit for {mp_id}")
            return self._structure_cache[mp_id]

        mpr = self._get_mpr()

        def _fetch():
            docs = mpr.materials.summary.search(
                material_ids=[mp_id],
                fields=["structure"],
            )
            if not docs or not docs[0].structure:
                raise MPNotFoundError(mp_id)
            return docs[0].structure

        structure = self._run_with_retry(_fetch)

        # Cache result
        if self._cache_enabled:
            self._structure_cache[mp_id] = structure

        return structure

    def search_structures(
        self,
        formula: str | None = None,
        elements: list[str] | None = None,
        band_gap: tuple[float, float] | None = None,
        is_stable: bool | None = None,
        limit: int = 10,
    ) -> list[MPMaterial]:
        """Search for materials matching criteria.

        Args:
            formula: Chemical formula (e.g., 'MoS2') or chemsys (e.g., 'Mo-S')
            elements: Required elements (e.g., ['Mo', 'S'])
            band_gap: Band gap range in eV as (min, max) tuple
            is_stable: Filter for thermodynamically stable materials
            limit: Maximum number of results (default 10)

        Returns:
            List of MPMaterial objects matching criteria

        Raises:
            MPRateLimitError: If rate limit exceeded
            MPClientError: On API errors

        Example:
            >>> client = MPClient()
            >>> stable_mos2 = client.search_structures(
            ...     formula="MoS2",
            ...     is_stable=True,
            ...     limit=5
            ... )
        """
        mpr = self._get_mpr()

        # Build query kwargs
        query_fields = [
            "material_id",
            "formula_pretty",
            "structure",
            "energy_above_hull",
            "band_gap",
            "is_stable",
        ]

        def _search():
            kwargs: dict[str, Any] = {
                "fields": query_fields,
                "num_chunks": 1,
            }

            # Formula or chemsys
            if formula:
                if "-" in formula:
                    kwargs["chemsys"] = formula
                else:
                    kwargs["formula"] = formula

            # Element filter
            if elements:
                kwargs["elements"] = elements

            # Band gap range
            if band_gap is not None:
                min_gap, max_gap = band_gap
                kwargs["band_gap"] = (min_gap, max_gap)

            # Stability filter
            if is_stable is not None:
                kwargs["is_stable"] = is_stable

            docs = mpr.materials.summary.search(**kwargs)
            return docs[:limit] if docs else []

        docs = self._run_with_retry(_search)

        # Convert to MPMaterial objects
        materials = []
        for doc in docs:
            mp_id = str(doc.material_id)
            structure = doc.structure

            # Cache structures
            if self._cache_enabled and structure:
                self._structure_cache[mp_id] = structure

            materials.append(
                MPMaterial(
                    mp_id=mp_id,
                    formula=doc.formula_pretty or str(doc.composition),
                    structure=structure,
                    energy_above_hull=doc.energy_above_hull or 0.0,
                    band_gap=doc.band_gap,
                    is_stable=doc.is_stable if doc.is_stable is not None else False,
                )
            )

        return materials

    def get_properties(self, mp_id: str) -> MPProperties:
        """Get computed properties for a material.

        Args:
            mp_id: Materials Project ID (e.g., 'mp-149')

        Returns:
            MPProperties object with computed properties

        Raises:
            MPNotFoundError: If material not found
            MPRateLimitError: If rate limit exceeded
            MPClientError: On API errors

        Example:
            >>> client = MPClient()
            >>> props = client.get_properties("mp-149")
            >>> print(f"Band gap: {props.band_gap} eV")
        """
        if not validate_mp_id(mp_id):
            raise MPClientError(f"Invalid MP ID format: {mp_id}")

        mpr = self._get_mpr()

        query_fields = [
            "material_id",
            "formation_energy_per_atom",
            "energy_above_hull",
            "band_gap",
            "is_metal",
            "density",
            "volume",
            "total_magnetization",
            "symmetry",
        ]

        def _fetch():
            docs = mpr.materials.summary.search(
                material_ids=[mp_id],
                fields=query_fields,
            )
            if not docs:
                raise MPNotFoundError(mp_id)
            return docs[0]

        doc = self._run_with_retry(_fetch)

        # Extract symmetry dict
        symmetry_data = None
        if hasattr(doc, "symmetry") and doc.symmetry:
            sym = doc.symmetry
            symmetry_data = {
                "symbol": getattr(sym, "symbol", None),
                "number": getattr(sym, "number", None),
                "crystal_system": getattr(sym, "crystal_system", None),
            }

        return MPProperties(
            mp_id=mp_id,
            formation_energy_per_atom=doc.formation_energy_per_atom or 0.0,
            energy_above_hull=doc.energy_above_hull or 0.0,
            band_gap=doc.band_gap,
            is_metal=doc.is_metal if doc.is_metal is not None else False,
            density=getattr(doc, "density", None),
            volume=getattr(doc, "volume", None),
            total_magnetization=getattr(doc, "total_magnetization", None),
            symmetry=symmetry_data,
        )

    def get_similar_structures(
        self, structure: "Structure", limit: int = 5
    ) -> list[MPMaterial]:
        """Find similar structures in MP database.

        Uses the structure's composition to find materials with the same
        or similar chemical formula.

        Args:
            structure: pymatgen Structure to match
            limit: Maximum number of results (default 5)

        Returns:
            List of MPMaterial objects with similar structures

        Raises:
            MPRateLimitError: If rate limit exceeded
            MPClientError: On API errors

        Example:
            >>> client = MPClient()
            >>> my_structure = Structure.from_file("POSCAR")
            >>> similar = client.get_similar_structures(my_structure)
        """
        # Get reduced formula for search
        formula = structure.composition.reduced_formula

        return self.search_structures(formula=formula, limit=limit)

    def clear_cache(self) -> None:
        """Clear the structure cache."""
        self._structure_cache.clear()
        logger.debug("Structure cache cleared")

    @property
    def cache_size(self) -> int:
        """Get number of cached structures."""
        return len(self._structure_cache)


# ============================================================================
# Helper Functions
# ============================================================================


@lru_cache(maxsize=128)
def _get_cached_structure(mp_id: str, api_key: str | None = None) -> "Structure":
    """Internal cached structure retrieval.

    Uses functools.lru_cache for module-level caching.
    """
    client = MPClient(api_key=api_key, cache_enabled=False)
    return client.get_structure(mp_id)


def mp_id_to_structure(mp_id: str, api_key: str | None = None) -> "Structure":
    """Convenience function to get structure from MP ID.

    This is the simplest way to retrieve a structure from the Materials
    Project database. Uses module-level caching to avoid repeated API calls.

    Args:
        mp_id: Materials Project ID (e.g., 'mp-149')
        api_key: Optional API key (uses MP_API_KEY env var if not provided)

    Returns:
        pymatgen Structure object

    Raises:
        MPNotFoundError: If material not found
        MPAuthenticationError: If API key not configured
        MPClientError: On other API errors

    Example:
        >>> from crystalmath.integrations.materials_project import mp_id_to_structure
        >>> si = mp_id_to_structure("mp-149")
        >>> print(si.formula)
        Si2
    """
    return _get_cached_structure(mp_id, api_key)


def validate_mp_id(mp_id: str) -> bool:
    """Check if string is valid MP ID format.

    Valid MP IDs have the format 'mp-{number}', e.g., 'mp-149', 'mp-1234'.

    Args:
        mp_id: String to validate

    Returns:
        True if valid MP ID format, False otherwise

    Example:
        >>> validate_mp_id("mp-149")
        True
        >>> validate_mp_id("Si")
        False
        >>> validate_mp_id("mp-abc")
        False
    """
    if not isinstance(mp_id, str):
        return False
    return bool(_MP_ID_PATTERN.match(mp_id))


def search_by_formula(
    formula: str,
    api_key: str | None = None,
    limit: int = 10,
) -> list[MPMaterial]:
    """Convenience function to search materials by formula.

    Args:
        formula: Chemical formula (e.g., 'MoS2') or chemsys (e.g., 'Mo-S')
        api_key: Optional API key (uses MP_API_KEY env var if not provided)
        limit: Maximum number of results

    Returns:
        List of MPMaterial objects

    Example:
        >>> from crystalmath.integrations.materials_project import search_by_formula
        >>> materials = search_by_formula("MoS2", limit=5)
    """
    client = MPClient(api_key=api_key)
    return client.search_structures(formula=formula, limit=limit)


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Client
    "MPClient",
    # Data classes
    "MPMaterial",
    "MPProperties",
    # Exceptions
    "MPClientError",
    "MPAuthenticationError",
    "MPRateLimitError",
    "MPNotFoundError",
    "MPDependencyError",
    # Helper functions
    "mp_id_to_structure",
    "validate_mp_id",
    "search_by_formula",
]
