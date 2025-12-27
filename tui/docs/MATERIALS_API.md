# Materials Project API Integration

**Module**: `src/core/materials_api`
**Status**: Core Implementation Complete
**Created**: 2025-12-27

---

## Overview

The Materials API module provides unified access to the Materials Project ecosystem for fetching crystal structures and generating CRYSTAL23 input files. It integrates three complementary APIs:

| API | Purpose | Authentication |
|-----|---------|----------------|
| **MP API** (mp-api) | Primary source for structures, properties, thermodynamics | API key required |
| **MPContribs** | User contributions, experimental data | Same API key |
| **OPTIMADE** | Cross-database federation (OQMD, AFLOW, COD) | No auth needed |

---

## Quick Start

### 1. Set API Key

Get your free API key from [materialsproject.org/api](https://materialsproject.org/api).

```bash
# Create .env in tui/ directory
echo "MP_API_KEY=your_key_here" > tui/.env
```

### 2. Install Dependencies

```bash
cd tui/
uv pip install -e ".[materials]"
```

### 3. Basic Usage

```python
from src.core.materials_api import MaterialsService

async with MaterialsService(db_path="crystal_tui.db") as service:
    # Search by formula
    result = await service.search_by_formula("MoS2")
    for record in result:
        print(f"{record.material_id}: {record.formula}")
        print(f"  Band gap: {record.band_gap} eV")
        print(f"  Stable: {record.is_stable}")

    # Generate CRYSTAL23 input file
    d12_content = await service.generate_crystal_input(
        "mp-2815",
        config={
            "functional": "B3LYP",
            "shrink": (12, 12),
            "optimize": True,
            "opt_type": "ATOMONLY",
        }
    )
    with open("MoS2.d12", "w") as f:
        f.write(d12_content)
```

---

## Architecture

```
src/core/materials_api/
├── __init__.py          # Public exports
├── settings.py          # Environment config
├── errors.py            # Custom exceptions
├── models.py            # Data classes
├── cache.py             # SQLite cache with TTL
├── service.py           # Main orchestrator
├── clients/
│   ├── __init__.py      # Lazy imports
│   ├── mp_api.py        # Materials Project API
│   ├── mpcontribs.py    # User contributions
│   └── optimade.py      # OPTIMADE federation
└── transforms/
    ├── __init__.py
    └── crystal_d12.py   # pymatgen → .d12 converter
```

### Design Principles

1. **Async-First**: All I/O operations are async
2. **Cache-First**: Check SQLite cache before API calls (30-day TTL)
3. **Lazy Loading**: API clients initialized only when needed
4. **Rate Limiting**: Semaphore-based concurrent request control
5. **Graceful Fallback**: MP API → OPTIMADE when structure not found

---

## API Reference

### MaterialsService

The main orchestrator for all Materials Project interactions.

```python
class MaterialsService:
    def __init__(
        self,
        db_path: Path | str | None = None,  # SQLite cache path
        settings: MaterialsSettings | None = None,
        cache: CacheRepositoryProtocol | None = None,
    ) -> None: ...
```

**Must be used as async context manager:**

```python
async with MaterialsService() as service:
    # Use service here
    ...
# All resources automatically cleaned up
```

#### Methods

| Method | Description | Returns |
|--------|-------------|---------|
| `search_by_formula(formula, include_contributions, limit)` | Search by chemical formula | `StructureResult` |
| `search_by_elements(elements, exclude_elements, limit)` | Search by element composition | `StructureResult` |
| `get_structure(material_id, fallback_to_optimade)` | Fetch single structure | `MaterialRecord \| None` |
| `get_contributions(material_id, project)` | Fetch MPContribs data | `list[ContributionRecord]` |
| `search_optimade(formula, providers, limit)` | Cross-database search | `StructureResult` |
| `generate_crystal_input(material_id, config)` | Generate .d12 file | `str` |

---

### MaterialRecord

Represents a material from any API source.

```python
@dataclass
class MaterialRecord:
    material_id: str           # e.g., "mp-149"
    source: str                # "mp", "mpcontribs", "optimade"
    formula: str               # "Si", "MoS2"
    formula_pretty: str | None
    structure: Structure | None  # pymatgen Structure
    properties: dict[str, Any]
    metadata: dict[str, Any]

    # Convenience properties
    @property
    def band_gap(self) -> float | None: ...
    @property
    def formation_energy(self) -> float | None: ...
    @property
    def energy_above_hull(self) -> float | None: ...
    @property
    def is_stable(self) -> bool | None: ...
    @property
    def space_group(self) -> str | None: ...
```

---

### StructureResult

Container for search results with pagination info.

```python
@dataclass
class StructureResult:
    records: list[MaterialRecord]
    total_count: int
    source: str
    query: dict[str, Any]
    cached: bool
    cache_age_seconds: float | None

    # Iterable interface
    def __len__(self) -> int: ...
    def __iter__(self): ...
    def __getitem__(self, index: int) -> MaterialRecord: ...
```

---

### CacheRepository

Async SQLite cache with TTL-based invalidation.

```python
async with CacheRepository(db_path) as cache:
    # Check cache
    entry = await cache.get_cached_response(cache_key, "mp")
    if entry and not entry.is_expired:
        return entry.get_response()

    # Store in cache
    await cache.set_cached_response(
        cache_key, "mp", query_dict, response_dict, ttl_days=30
    )

    # Maintenance
    deleted = await cache.invalidate_expired()
    await cache.clear_cache(source="mp")  # Clear MP cache only
    stats = await cache.get_cache_stats()
```

---

### CrystalD12Generator

Converts pymatgen structures to CRYSTAL23 .d12 input files.

```python
from src.core.materials_api import CrystalD12Generator, OptimizationConfig

# From pymatgen Structure
d12 = CrystalD12Generator.generate_full_input(
    structure,
    title="MoS2 monolayer",
    basis_set="POB-TZVP-REV2",
    functional="PBE",
    shrink=(8, 8),
    tolinteg=(7, 7, 7, 7, 14),
    maxcycle=200,
    toldee=8,
    grid="XLGRID",
    optimization=OptimizationConfig(
        enabled=True,
        opt_type="ATOMONLY",
    ),
)
```

**Supported structure types:**
- 3D crystals (CRYSTAL keyword)
- 2D slabs (SLAB keyword)
- 1D polymers (POLYMER keyword)
- 0D molecules (MOLECULE keyword)

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MP_API_KEY` | (required) | Materials Project API key |
| `MPCONTRIBS_API_KEY` | = MP_API_KEY | MPContribs key (usually same) |
| `OPTIMADE_MP_BASE_URL` | `https://optimade.materialsproject.org` | OPTIMADE endpoint |
| `MATERIALS_CACHE_TTL_DAYS` | 30 | Cache expiration in days |
| `MATERIALS_MAX_CONCURRENT` | 8 | Max parallel API requests |
| `MATERIALS_REQUEST_TIMEOUT` | 30 | Request timeout in seconds |
| `MATERIALS_MAX_RETRIES` | 3 | Retry count for failed requests |

### MaterialsSettings

```python
from src.core.materials_api import MaterialsSettings

# From environment (recommended)
settings = MaterialsSettings.from_env()

# Singleton access
settings = MaterialsSettings.get_instance()

# Validate configuration
warnings = settings.validate()
for w in warnings:
    print(f"Warning: {w}")
```

---

## Error Handling

All errors inherit from `MaterialsAPIError`:

```python
from src.core.materials_api import (
    MaterialsAPIError,
    AuthenticationError,
    RateLimitError,
    StructureNotFoundError,
    NetworkError,
    CacheError,
    ValidationError,
)

try:
    async with MaterialsService() as service:
        record = await service.get_structure("mp-149")
except AuthenticationError as e:
    print(f"Invalid API key for {e.source}")
except RateLimitError as e:
    print(f"Rate limited. Retry after {e.retry_after} seconds")
except StructureNotFoundError as e:
    print(f"Material {e.identifier} not found")
except NetworkError as e:
    print(f"Connection failed: {e.original_error}")
```

---

## Database Schema

The cache uses three tables (Migration V6):

```sql
-- Raw API response cache with TTL
CREATE TABLE materials_cache (
    cache_key TEXT NOT NULL,
    source TEXT NOT NULL,
    query_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    expires_at TEXT,
    etag TEXT,
    PRIMARY KEY (source, cache_key)
);

-- Parsed structure cache
CREATE TABLE materials_structures (
    material_id TEXT NOT NULL,
    source TEXT NOT NULL,
    formula TEXT NOT NULL,
    structure_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source, material_id)
);

-- MPContribs contributions cache
CREATE TABLE mpcontribs_cache (
    contribution_id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    material_id TEXT,
    data_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
```

---

## OPTIMADE Providers

The OPTIMADE client supports cross-database queries:

| Provider | Key | Description |
|----------|-----|-------------|
| Materials Project | `mp` | Primary MP database |
| OQMD | `oqmd` | Open Quantum Materials Database |
| AFLOW | `aflow` | Automatic FLOW for materials |
| COD | `cod` | Crystallography Open Database |
| Materials Cloud 3D | `mc3d` | Materials Cloud 3D structures |
| Materials Cloud 2D | `mc2d` | Materials Cloud 2D materials |

```python
# Search across multiple providers
result = await service.search_optimade(
    "Si",
    providers=["mp", "oqmd", "cod"],
    limit=20,
)
for record in result:
    print(f"[{record.source}] {record.material_id}: {record.formula}")
```

---

## Examples

### Search and Filter

```python
async with MaterialsService() as service:
    # Find stable materials with specific elements
    result = await service.search_by_elements(
        elements=["Li", "Fe", "O"],
        exclude_elements=["F", "Cl"],
        limit=50,
    )

    # Filter for stable materials
    stable = [r for r in result if r.is_stable]
    print(f"Found {len(stable)} stable Li-Fe-O compounds")
```

### Generate Multiple Inputs

```python
async with MaterialsService() as service:
    result = await service.search_by_formula("TiO2", limit=10)

    for record in result:
        if record.is_stable:
            d12 = await service.generate_crystal_input(
                record.material_id,
                config={"functional": "PBE0", "optimize": True}
            )
            filename = f"{record.material_id.replace('-', '_')}.d12"
            with open(filename, "w") as f:
                f.write(d12)
            print(f"Created {filename}")
```

### With Contributions Data

```python
async with MaterialsService() as service:
    # Get structure with experimental data
    result = await service.search_by_formula(
        "MoS2",
        include_contributions=True,
    )

    for record in result:
        if "contributions" in record.metadata:
            for contrib in record.metadata["contributions"]:
                print(f"Project: {contrib['project']}")
                print(f"Data: {contrib['data']}")
```

---

## Testing

Unit tests are planned for mp4.13-mp4.14. Run with:

```bash
cd tui/
pytest tests/test_materials_*.py -v
```

---

## Troubleshooting

### "Authentication failed for mp"
- Verify `MP_API_KEY` is set in `.env`
- Check key validity at [materialsproject.org/api](https://materialsproject.org/api)

### "Rate limit exceeded"
- Reduce `MATERIALS_MAX_CONCURRENT` in `.env`
- Wait for `retry_after` seconds before retrying

### "Structure not found"
- Check material ID format (`mp-XXXXX`)
- Try enabling OPTIMADE fallback: `get_structure(id, fallback_to_optimade=True)`

### Cache Issues
```python
async with CacheRepository(db_path) as cache:
    # Clear expired entries
    await cache.invalidate_expired()

    # Clear all cache
    await cache.clear_cache()

    # Check cache stats
    stats = await cache.get_cache_stats()
    print(stats)
```

---

## Related Documentation

- [AiiDA Integration](./AIIDA_SETUP.md) - Workflow management
- [CRYSTAL23 Guide](../../CLAUDE.md) - Input file format
- [MoS2 Optimization](../../TESTBED/MoS2/MoS2_OPTIMIZATION_GUIDE.md) - 2D materials

---

## Changelog

### 2025-12-27 - Initial Implementation
- Core module structure with async clients
- MP API, MPContribs, OPTIMADE integration
- SQLite cache with 30-day TTL
- pymatgen to .d12 converter
- MaterialsService orchestrator
