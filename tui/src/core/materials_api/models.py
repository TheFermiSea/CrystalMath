"""Data models for Materials API responses and cache entries."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from pymatgen.core import Structure


@dataclass
class MaterialRecord:
    """Represents a material from any API source.

    Attributes:
        material_id: Unique identifier (e.g., 'mp-149', 'oqmd-12345')
        source: API source ('mp', 'mpcontribs', 'optimade')
        formula: Chemical formula (e.g., 'MoS2')
        formula_pretty: Pretty-printed formula
        structure: Optional pymatgen Structure object
        properties: Dictionary of computed/experimental properties
        metadata: Additional source-specific metadata
    """

    material_id: str
    source: str
    formula: str
    formula_pretty: str | None = None
    structure: Structure | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Common properties with convenient accessors
    @property
    def band_gap(self) -> float | None:
        """Band gap in eV, if available."""
        return self.properties.get("band_gap")

    @property
    def formation_energy(self) -> float | None:
        """Formation energy per atom in eV, if available."""
        return self.properties.get("formation_energy_per_atom")

    @property
    def energy_above_hull(self) -> float | None:
        """Energy above convex hull in eV/atom, if available."""
        return self.properties.get("energy_above_hull")

    @property
    def is_stable(self) -> bool | None:
        """Whether material is thermodynamically stable (on hull)."""
        eah = self.energy_above_hull
        if eah is None:
            return None
        return eah < 0.001  # Effectively zero

    @property
    def space_group(self) -> str | None:
        """Space group symbol, if available."""
        return self.metadata.get("symmetry", {}).get("symbol")

    @property
    def space_group_number(self) -> int | None:
        """Space group number, if available."""
        return self.metadata.get("symmetry", {}).get("number")

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        data = {
            "material_id": self.material_id,
            "source": self.source,
            "formula": self.formula,
            "formula_pretty": self.formula_pretty,
            "properties": self.properties,
            "metadata": self.metadata,
        }
        if self.structure is not None:
            data["structure"] = self.structure.as_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MaterialRecord:
        """Create from dictionary."""
        structure = None
        if "structure" in data and data["structure"]:
            try:
                from pymatgen.core import Structure
                structure = Structure.from_dict(data["structure"])
            except Exception:
                pass  # Structure reconstruction failed

        return cls(
            material_id=data["material_id"],
            source=data["source"],
            formula=data["formula"],
            formula_pretty=data.get("formula_pretty"),
            structure=structure,
            properties=data.get("properties", {}),
            metadata=data.get("metadata", {}),
        )


@dataclass
class StructureResult:
    """Result of a structure search or fetch operation.

    Attributes:
        records: List of matching MaterialRecord objects
        total_count: Total number of matches (may exceed len(records) if paginated)
        source: API source queried
        query: Original query parameters
        cached: Whether result was served from cache
        cache_age_seconds: Age of cached result, if applicable
        errors: Dict of provider/source -> error message for failed queries.
                Allows distinguishing empty results from network failures.
    """

    records: list[MaterialRecord] = field(default_factory=list)
    total_count: int = 0
    source: str = ""
    query: dict[str, Any] = field(default_factory=dict)
    cached: bool = False
    cache_age_seconds: float | None = None
    errors: dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self):
        return iter(self.records)

    def __getitem__(self, index: int) -> MaterialRecord:
        return self.records[index]

    @property
    def is_empty(self) -> bool:
        """Check if no results were found."""
        return len(self.records) == 0

    @property
    def has_errors(self) -> bool:
        """Check if any providers failed during the query."""
        return len(self.errors) > 0

    @property
    def partial_failure(self) -> bool:
        """Check if some providers succeeded but others failed."""
        return self.has_errors and len(self.records) > 0


@dataclass
class CacheEntry:
    """Represents a cached API response.

    Attributes:
        cache_key: Unique key for this cache entry
        source: API source ('mp', 'mpcontribs', 'optimade')
        query_json: JSON-serialized query parameters
        response_json: JSON-serialized response data
        fetched_at: When the data was fetched
        expires_at: When the cache entry expires
        etag: Optional HTTP ETag for conditional requests
    """

    cache_key: str
    source: str
    query_json: str
    response_json: str
    fetched_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime | None = None
    etag: str | None = None

    @property
    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at

    @property
    def age_seconds(self) -> float:
        """Age of cache entry in seconds."""
        return (datetime.now() - self.fetched_at).total_seconds()

    def get_response(self) -> dict[str, Any]:
        """Parse and return the cached response."""
        return json.loads(self.response_json)

    def get_query(self) -> dict[str, Any]:
        """Parse and return the original query."""
        return json.loads(self.query_json)


@dataclass
class ContributionRecord:
    """Represents an MPContribs contribution.

    Attributes:
        contribution_id: Unique contribution ID
        project: MPContribs project name
        material_id: Associated MP material ID
        identifier: User-provided identifier
        formula: Chemical formula
        data: Contribution data dictionary
        tables: Associated data tables
        structures: Associated structure data
    """

    contribution_id: str
    project: str
    material_id: str | None = None
    identifier: str | None = None
    formula: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    tables: list[dict[str, Any]] = field(default_factory=list)
    structures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "contribution_id": self.contribution_id,
            "project": self.project,
            "material_id": self.material_id,
            "identifier": self.identifier,
            "formula": self.formula,
            "data": self.data,
            "tables": self.tables,
            "structures": self.structures,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContributionRecord:
        """Create from dictionary."""
        return cls(
            contribution_id=data["contribution_id"],
            project=data["project"],
            material_id=data.get("material_id"),
            identifier=data.get("identifier"),
            formula=data.get("formula"),
            data=data.get("data", {}),
            tables=data.get("tables", []),
            structures=data.get("structures", []),
        )
