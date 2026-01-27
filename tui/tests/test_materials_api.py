"""Unit tests for Materials API module.

Tests cover:
- Error classes
- Data models (MaterialRecord, StructureResult, CacheEntry, ContributionRecord)
- Client wrappers (MpApiClient, MPContribsClient, OptimadeClient)
- Cache repository
- CRYSTAL23 input generator (CrystalD12Generator)
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import errors
from src.core.materials_api.errors import (
    AuthenticationError,
    CacheError,
    MaterialsAPIError,
    NetworkError,
    RateLimitError,
    StructureNotFoundError,
    ValidationError,
)

# Import models
from src.core.materials_api.models import (
    CacheEntry,
    ContributionRecord,
    MaterialRecord,
    StructureResult,
)

# Import settings
from src.core.materials_api.settings import MaterialsSettings

# =============================================================================
# Error Tests
# =============================================================================


class TestMaterialsAPIError:
    """Tests for base MaterialsAPIError."""

    def test_basic_error(self):
        """Error stores message and source."""
        err = MaterialsAPIError("test error", source="mp")
        assert str(err) == "test error"
        assert err.source == "mp"

    def test_error_without_source(self):
        """Error works without source."""
        err = MaterialsAPIError("test error")
        assert str(err) == "test error"
        assert err.source is None


class TestAuthenticationError:
    """Tests for AuthenticationError."""

    def test_default_message(self):
        """Default message includes source."""
        err = AuthenticationError("mp")
        assert "mp" in str(err)
        assert "API key" in str(err)
        assert err.source == "mp"

    def test_custom_message(self):
        """Custom message overrides default."""
        err = AuthenticationError("mp", "Custom auth error")
        assert str(err) == "Custom auth error"


class TestRateLimitError:
    """Tests for RateLimitError."""

    def test_without_retry_after(self):
        """Error without retry_after."""
        err = RateLimitError("mp")
        assert "mp" in str(err)
        assert "Rate limit" in str(err)
        assert err.retry_after is None

    def test_with_retry_after(self):
        """Error with retry_after includes wait time."""
        err = RateLimitError("mp", retry_after=60)
        assert "60" in str(err)
        assert err.retry_after == 60

    def test_custom_message(self):
        """Custom message overrides default."""
        err = RateLimitError("mp", message="Custom rate limit")
        assert str(err) == "Custom rate limit"


class TestStructureNotFoundError:
    """Tests for StructureNotFoundError."""

    def test_basic_not_found(self):
        """Error includes identifier."""
        err = StructureNotFoundError("mp-149")
        assert "mp-149" in str(err)
        assert err.identifier == "mp-149"

    def test_with_source(self):
        """Error includes source when provided."""
        err = StructureNotFoundError("mp-149", source="mp")
        assert "mp-149" in str(err)
        assert "mp" in str(err)
        assert err.source == "mp"


class TestNetworkError:
    """Tests for NetworkError."""

    def test_without_original(self):
        """Error without original exception."""
        err = NetworkError("mp")
        assert "mp" in str(err)
        assert err.original_error is None

    def test_with_original(self):
        """Error wraps original exception."""
        original = ConnectionError("Connection refused")
        err = NetworkError("mp", original_error=original)
        assert "mp" in str(err)
        assert "Connection refused" in str(err)
        assert err.original_error is original


class TestCacheError:
    """Tests for CacheError."""

    def test_operation_stored(self):
        """Error stores operation type."""
        err = CacheError("write")
        assert err.operation == "write"
        assert "write" in str(err)

    def test_custom_message(self):
        """Custom message is used."""
        err = CacheError("read", "Disk full")
        assert "Disk full" in str(err)


class TestValidationError:
    """Tests for ValidationError."""

    def test_field_stored(self):
        """Error stores field name."""
        err = ValidationError("band_gap")
        assert err.field == "band_gap"
        assert "band_gap" in str(err)

    def test_custom_message(self):
        """Custom message is used."""
        err = ValidationError("energy", "Must be negative")
        assert "Must be negative" in str(err)


# =============================================================================
# Model Tests
# =============================================================================


class TestMaterialRecord:
    """Tests for MaterialRecord dataclass."""

    def test_basic_creation(self):
        """Create record with required fields."""
        record = MaterialRecord(
            material_id="mp-149",
            source="mp",
            formula="Si",
        )
        assert record.material_id == "mp-149"
        assert record.source == "mp"
        assert record.formula == "Si"
        assert record.properties == {}
        assert record.metadata == {}

    def test_with_properties(self):
        """Record stores properties correctly."""
        record = MaterialRecord(
            material_id="mp-149",
            source="mp",
            formula="Si",
            properties={
                "band_gap": 1.1,
                "formation_energy_per_atom": -0.5,
                "energy_above_hull": 0.0,
            },
        )
        assert record.band_gap == 1.1
        assert record.formation_energy == -0.5
        assert record.energy_above_hull == 0.0

    def test_is_stable_property(self):
        """is_stable calculated from energy_above_hull."""
        # Stable material (on hull)
        stable = MaterialRecord(
            material_id="mp-1",
            source="mp",
            formula="Si",
            properties={"energy_above_hull": 0.0},
        )
        assert stable.is_stable is True

        # Unstable material (above hull)
        unstable = MaterialRecord(
            material_id="mp-2",
            source="mp",
            formula="X",
            properties={"energy_above_hull": 0.1},
        )
        assert unstable.is_stable is False

        # Unknown stability
        unknown = MaterialRecord(
            material_id="mp-3",
            source="mp",
            formula="Y",
        )
        assert unknown.is_stable is None

    def test_space_group_from_metadata(self):
        """space_group extracted from symmetry metadata."""
        record = MaterialRecord(
            material_id="mp-149",
            source="mp",
            formula="Si",
            metadata={
                "symmetry": {
                    "symbol": "Fd-3m",
                    "number": 227,
                }
            },
        )
        assert record.space_group == "Fd-3m"
        assert record.space_group_number == 227

    def test_to_dict_without_structure(self):
        """to_dict serializes record without structure."""
        record = MaterialRecord(
            material_id="mp-149",
            source="mp",
            formula="Si",
            formula_pretty="Si",
            properties={"band_gap": 1.1},
            metadata={"symmetry": {"symbol": "Fd-3m"}},
        )
        data = record.to_dict()
        assert data["material_id"] == "mp-149"
        assert data["source"] == "mp"
        assert data["properties"]["band_gap"] == 1.1
        assert "structure" not in data

    def test_from_dict(self):
        """from_dict reconstructs record."""
        data = {
            "material_id": "mp-149",
            "source": "mp",
            "formula": "Si",
            "formula_pretty": "Si",
            "properties": {"band_gap": 1.1},
            "metadata": {},
        }
        record = MaterialRecord.from_dict(data)
        assert record.material_id == "mp-149"
        assert record.band_gap == 1.1


class TestStructureResult:
    """Tests for StructureResult dataclass."""

    def test_empty_result(self):
        """Empty result has correct properties."""
        result = StructureResult()
        assert len(result) == 0
        assert result.is_empty is True
        assert result.has_errors is False
        assert result.partial_failure is False

    def test_with_records(self):
        """Result with records is iterable."""
        records = [
            MaterialRecord(material_id="mp-1", source="mp", formula="Si"),
            MaterialRecord(material_id="mp-2", source="mp", formula="Ge"),
        ]
        result = StructureResult(records=records, total_count=2, source="mp")

        assert len(result) == 2
        assert result.is_empty is False
        assert result[0].material_id == "mp-1"
        assert list(result) == records

    def test_with_errors(self):
        """Result tracks query errors."""
        result = StructureResult(errors={"oqmd": "Connection timeout", "aflow": "404 Not Found"})
        assert result.has_errors is True
        assert "oqmd" in result.errors

    def test_partial_failure(self):
        """Partial failure when some providers fail."""
        records = [MaterialRecord(material_id="mp-1", source="mp", formula="Si")]
        result = StructureResult(records=records, errors={"oqmd": "Timeout"})
        assert result.partial_failure is True

    def test_cache_metadata(self):
        """Cache metadata stored correctly."""
        result = StructureResult(cached=True, cache_age_seconds=3600.0)
        assert result.cached is True
        assert result.cache_age_seconds == 3600.0


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_basic_creation(self):
        """Create cache entry."""
        entry = CacheEntry(
            cache_key="abc123",
            source="mp",
            query_json='{"formula": "Si"}',
            response_json='{"records": []}',
        )
        assert entry.cache_key == "abc123"
        assert entry.source == "mp"

    def test_is_expired(self):
        """is_expired checks expiration time."""
        # Not expired
        future = datetime.now() + timedelta(hours=1)
        entry = CacheEntry(
            cache_key="key",
            source="mp",
            query_json="{}",
            response_json="{}",
            expires_at=future,
        )
        assert entry.is_expired is False

        # Expired
        past = datetime.now() - timedelta(hours=1)
        expired = CacheEntry(
            cache_key="key",
            source="mp",
            query_json="{}",
            response_json="{}",
            expires_at=past,
        )
        assert expired.is_expired is True

        # No expiration
        no_expire = CacheEntry(
            cache_key="key",
            source="mp",
            query_json="{}",
            response_json="{}",
        )
        assert no_expire.is_expired is False

    def test_get_response(self):
        """get_response parses JSON."""
        entry = CacheEntry(
            cache_key="key",
            source="mp",
            query_json="{}",
            response_json='{"data": [1, 2, 3]}',
        )
        response = entry.get_response()
        assert response == {"data": [1, 2, 3]}

    def test_get_query(self):
        """get_query parses JSON."""
        entry = CacheEntry(
            cache_key="key",
            source="mp",
            query_json='{"formula": "MoS2"}',
            response_json="{}",
        )
        query = entry.get_query()
        assert query == {"formula": "MoS2"}

    def test_age_seconds(self):
        """age_seconds calculates time since fetch."""
        past = datetime.now() - timedelta(seconds=60)
        entry = CacheEntry(
            cache_key="key",
            source="mp",
            query_json="{}",
            response_json="{}",
            fetched_at=past,
        )
        # Allow some tolerance for test execution time
        assert 59 < entry.age_seconds < 62


class TestContributionRecord:
    """Tests for ContributionRecord dataclass."""

    def test_basic_creation(self):
        """Create contribution record."""
        record = ContributionRecord(
            contribution_id="contrib123",
            project="my_project",
        )
        assert record.contribution_id == "contrib123"
        assert record.project == "my_project"
        assert record.material_id is None
        assert record.data == {}

    def test_with_all_fields(self):
        """Create record with all fields."""
        record = ContributionRecord(
            contribution_id="contrib123",
            project="my_project",
            material_id="mp-149",
            identifier="sample1",
            formula="Si",
            data={"property": 42},
            tables=[{"name": "data_table"}],
            structures=[{"lattice": {}}],
        )
        assert record.material_id == "mp-149"
        assert record.data["property"] == 42

    def test_to_dict(self):
        """to_dict serializes record."""
        record = ContributionRecord(
            contribution_id="c1",
            project="p1",
            data={"x": 1},
        )
        data = record.to_dict()
        assert data["contribution_id"] == "c1"
        assert data["data"] == {"x": 1}

    def test_from_dict(self):
        """from_dict reconstructs record."""
        data = {
            "contribution_id": "c1",
            "project": "p1",
            "material_id": "mp-1",
            "data": {"x": 1},
        }
        record = ContributionRecord.from_dict(data)
        assert record.contribution_id == "c1"
        assert record.data["x"] == 1


# =============================================================================
# Settings Tests
# =============================================================================


class TestMaterialsSettings:
    """Tests for MaterialsSettings."""

    def test_singleton_pattern(self):
        """Settings uses singleton pattern."""
        s1 = MaterialsSettings.get_instance()
        s2 = MaterialsSettings.get_instance()
        assert s1 is s2

    def test_default_values(self):
        """Default values are set."""
        settings = MaterialsSettings.get_instance()
        assert settings.cache_ttl_days == 30
        assert settings.max_concurrent_requests == 8

    def test_cache_ttl_days_in_settings(self):
        """cache_ttl_days is configurable."""
        settings = MaterialsSettings.get_instance()
        # Cache TTL is stored in days
        assert isinstance(settings.cache_ttl_days, int)
        assert settings.cache_ttl_days > 0


# =============================================================================
# MpApiClient Tests (with mocks)
# =============================================================================


class TestMpApiClient:
    """Tests for MpApiClient async wrapper."""

    @pytest.fixture
    def mock_mprester(self):
        """Create mock MPRester."""
        mock = MagicMock()
        mock.materials = MagicMock()
        mock.materials.summary = MagicMock()
        return mock

    @pytest.mark.asyncio
    async def test_requires_api_key(self):
        """Client raises AuthenticationError without API key."""
        from src.core.materials_api.clients.mp_api import MpApiClient

        # Clear environment and create client with no key
        with patch.dict("os.environ", {}, clear=True):
            with patch.object(MaterialsSettings, "get_instance") as mock_settings:
                mock_settings.return_value = MagicMock(mp_api_key=None, max_concurrent_requests=8)
                client = MpApiClient(api_key=None)

                with pytest.raises(AuthenticationError):
                    await client._get_mpr()

    @pytest.mark.asyncio
    async def test_convert_exception_auth_error(self):
        """_convert_exception handles 401 errors."""
        from src.core.materials_api.clients.mp_api import MpApiClient

        client = MpApiClient(api_key="test_key")
        exc = Exception("401 Unauthorized: Invalid API key")
        converted = client._convert_exception(exc)
        assert isinstance(converted, AuthenticationError)

    @pytest.mark.asyncio
    async def test_convert_exception_rate_limit(self):
        """_convert_exception handles 429 errors."""
        from src.core.materials_api.clients.mp_api import MpApiClient

        client = MpApiClient(api_key="test_key")
        exc = Exception("429 Too Many Requests. Retry after 60 seconds")
        converted = client._convert_exception(exc)
        assert isinstance(converted, RateLimitError)
        assert converted.retry_after == 60

    @pytest.mark.asyncio
    async def test_convert_exception_network_error(self):
        """_convert_exception handles network errors."""
        from src.core.materials_api.clients.mp_api import MpApiClient

        client = MpApiClient(api_key="test_key")
        exc = Exception("Connection timeout")
        converted = client._convert_exception(exc)
        assert isinstance(converted, NetworkError)

    @pytest.mark.asyncio
    async def test_convert_exception_not_found(self):
        """_convert_exception handles 404 errors."""
        from src.core.materials_api.clients.mp_api import MpApiClient

        client = MpApiClient(api_key="test_key")
        exc = Exception("404 Not Found")
        converted = client._convert_exception(exc)
        assert isinstance(converted, StructureNotFoundError)

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Client works as async context manager."""
        from src.core.materials_api.clients.mp_api import MpApiClient

        async with MpApiClient(api_key="test_key") as client:
            assert client is not None

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        """close() is safe to call multiple times."""
        from src.core.materials_api.clients.mp_api import MpApiClient

        client = MpApiClient(api_key="test_key")
        await client.close()
        await client.close()  # Should not raise


# =============================================================================
# OptimadeClient Tests (with mocks)
# =============================================================================


class TestOptimadeClient:
    """Tests for OptimadeClient async client."""

    @pytest.mark.asyncio
    async def test_providers_dict(self):
        """Client has PROVIDERS class attribute with known providers."""
        from src.core.materials_api.clients.optimade import OptimadeClient

        # PROVIDERS is a class-level dict, not a method
        assert "mp" in OptimadeClient.PROVIDERS
        assert "oqmd" in OptimadeClient.PROVIDERS
        assert "aflow" in OptimadeClient.PROVIDERS

    @pytest.mark.asyncio
    async def test_formula_to_filter(self):
        """_formula_to_filter creates formula filter."""
        from src.core.materials_api.clients.optimade import OptimadeClient

        # Mock dependency check to avoid requiring optimade package
        with patch.object(OptimadeClient, "_check_dependencies"):
            client = OptimadeClient()
            filter_str = client._formula_to_filter("MoS2")
            assert "chemical_formula_reduced" in filter_str
            assert "MoS2" in filter_str

    @pytest.mark.asyncio
    async def test_elements_to_filter(self):
        """_elements_to_filter creates elements filter."""
        from src.core.materials_api.clients.optimade import OptimadeClient

        # Mock dependency check to avoid requiring optimade package
        with patch.object(OptimadeClient, "_check_dependencies"):
            client = OptimadeClient()
            filter_str = client._elements_to_filter(["Mo", "S"])
            assert "elements" in filter_str
            assert "Mo" in filter_str
            assert "S" in filter_str

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Client works as async context manager (skipped if deps unavailable)."""
        from src.core.materials_api.clients.optimade import OptimadeClient

        # Skip test if optimade dependencies aren't available
        try:
            async with OptimadeClient() as client:
                assert client is not None
        except ImportError:
            pytest.skip("optimade-python-tools not installed")


# =============================================================================
# CrystalD12Generator Tests
# =============================================================================


class TestCrystalD12Generator:
    """Tests for CRYSTAL23 input generator."""

    @pytest.fixture
    def mock_structure(self):
        """Create mock pymatgen Structure."""
        # Create a simple mock structure
        mock = MagicMock()
        mock.lattice = MagicMock()
        mock.lattice.a = 5.43
        mock.lattice.b = 5.43
        mock.lattice.c = 5.43
        mock.lattice.alpha = 90.0
        mock.lattice.beta = 90.0
        mock.lattice.gamma = 90.0
        mock.lattice.matrix = [[5.43, 0, 0], [0, 5.43, 0], [0, 0, 5.43]]

        # Mock sites with Silicon
        site = MagicMock()
        site.specie = MagicMock()
        site.specie.symbol = "Si"
        site.frac_coords = [0.0, 0.0, 0.0]
        mock.sites = [site]

        # Mock space group
        mock.get_space_group_info = MagicMock(return_value=("Fd-3m", 227))

        return mock

    def test_crystal_system_enum(self):
        """CrystalSystem enum has correct values."""
        from src.core.materials_api.transforms import CrystalSystem

        assert CrystalSystem.CRYSTAL.value == "CRYSTAL"
        assert CrystalSystem.SLAB.value == "SLAB"
        assert CrystalSystem.POLYMER.value == "POLYMER"
        assert CrystalSystem.MOLECULE.value == "MOLECULE"

    def test_basis_set_config(self):
        """BasisSetConfig dataclass works."""
        from src.core.materials_api.transforms import BasisSetConfig

        # BasisSetConfig has: use_internal, library_name, custom_basis
        config = BasisSetConfig(use_internal=True, library_name="POB-TZVP-REV2")
        assert config.use_internal is True
        assert config.library_name == "POB-TZVP-REV2"

    def test_hamiltonian_config(self):
        """HamiltonianConfig dataclass works."""
        from src.core.materials_api.transforms import HamiltonianConfig

        # HamiltonianConfig has: method, functional, grid, tolinteg, maxcycle, toldee, fmixing, levshift
        config = HamiltonianConfig(
            method="DFT",
            functional="PBE",
            maxcycle=200,
        )
        assert config.functional == "PBE"
        assert config.method == "DFT"
        assert config.maxcycle == 200

    def test_optimization_config(self):
        """OptimizationConfig dataclass works."""
        from src.core.materials_api.transforms import OptimizationConfig

        # OptimizationConfig has: enabled, opt_type, toldeg, toldee, maxcycle
        config = OptimizationConfig(
            enabled=True,
            opt_type="FULLOPTG",
            maxcycle=100,
        )
        assert config.enabled is True
        assert config.opt_type == "FULLOPTG"
        assert config.maxcycle == 100

    def test_element_to_atomic_number(self):
        """Module-level ELEMENT_TO_Z maps elements to atomic numbers."""
        from src.core.materials_api.transforms.crystal_d12 import ELEMENT_TO_Z

        # ELEMENT_TO_Z is a module-level constant
        assert ELEMENT_TO_Z["Si"] == 14
        assert ELEMENT_TO_Z["Mo"] == 42
        assert ELEMENT_TO_Z["S"] == 16

    def test_structure_to_geometry(self, mock_structure):
        """structure_to_geometry creates valid CRYSTAL geometry block."""
        from src.core.materials_api.transforms import (
            CrystalD12Generator,
            CrystalSystem,
        )

        # The method is structure_to_geometry, not generate_geometry_block
        block = CrystalD12Generator.structure_to_geometry(
            mock_structure, system=CrystalSystem.CRYSTAL
        )
        assert "CRYSTAL" in block
        # Should contain lattice parameters and END keyword
        assert "END" in block


# =============================================================================
# Cache Repository Tests
# =============================================================================


class TestCacheRepository:
    """Tests for async cache repository."""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database file."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            yield f.name
        # Cleanup handled by OS temp file deletion

    @pytest.mark.asyncio
    async def test_generate_cache_key(self):
        """generate_cache_key produces deterministic keys."""
        from src.core.materials_api.cache import generate_cache_key

        # Signature: generate_cache_key(query: dict, prefix: str | None = None)
        key1 = generate_cache_key({"formula": "Si"}, "mp_search")
        key2 = generate_cache_key({"formula": "Si"}, "mp_search")
        key3 = generate_cache_key({"formula": "Ge"}, "mp_search")

        assert key1 == key2  # Same inputs -> same key
        assert key1 != key3  # Different inputs -> different key
        # Key format: "prefix:hash16" - 16 chars hash + prefix
        assert "mp_search:" in key1
        assert len(key1.split(":")[1]) == 16  # Truncated SHA-256 hash

    @pytest.mark.asyncio
    async def test_cache_key_order_independent(self):
        """Cache key is order-independent for dict params."""
        from src.core.materials_api.cache import generate_cache_key

        # Same query with different key ordering should produce same hash
        key1 = generate_cache_key({"a": 1, "b": 2}, "test")
        key2 = generate_cache_key({"b": 2, "a": 1}, "test")
        assert key1 == key2


# =============================================================================
# Integration helpers
# =============================================================================


@pytest.mark.asyncio
async def test_error_hierarchy():
    """All error types inherit from MaterialsAPIError."""
    errors = [
        AuthenticationError("mp"),
        RateLimitError("mp"),
        StructureNotFoundError("mp-149"),
        NetworkError("mp"),
        CacheError("read"),
        ValidationError("field"),
    ]
    for err in errors:
        assert isinstance(err, MaterialsAPIError)


# =============================================================================
# MaterialsService Integration Tests
# =============================================================================


class TestMaterialsService:
    """Integration tests for MaterialsService orchestrator."""

    @pytest.mark.asyncio
    async def test_context_manager_basic(self):
        """Service works as async context manager."""
        from src.core.materials_api.service import MaterialsService

        async with MaterialsService() as service:
            assert service is not None
            assert service._entered is True

    @pytest.mark.asyncio
    async def test_context_manager_sets_entered_flag(self):
        """Service sets _entered flag correctly."""
        from src.core.materials_api.service import MaterialsService

        service = MaterialsService()
        assert service._entered is False

        async with service:
            assert service._entered is True

        # After exit, entered flag should be False
        assert service._entered is False

    @pytest.mark.asyncio
    async def test_lazy_client_initialization(self):
        """Clients are not initialized until first use."""
        from src.core.materials_api.service import MaterialsService

        async with MaterialsService() as service:
            # Initially, no clients should be created
            assert service._mp_client is None
            assert service._mpcontribs_client is None
            assert service._optimade_client is None

    @pytest.mark.asyncio
    async def test_settings_property(self):
        """Service exposes settings via property."""
        from src.core.materials_api.service import MaterialsService

        async with MaterialsService() as service:
            settings = service.settings
            assert settings is not None
            assert hasattr(settings, "cache_ttl_days")
            assert hasattr(settings, "max_concurrent_requests")

    @pytest.mark.asyncio
    async def test_cache_key_generation(self):
        """Service generates deterministic cache keys."""
        from src.core.materials_api.service import MaterialsService

        async with MaterialsService() as service:
            key1 = service._generate_cache_key("search", formula="Si")
            key2 = service._generate_cache_key("search", formula="Si")
            key3 = service._generate_cache_key("search", formula="Ge")

            assert key1 == key2  # Same params -> same key
            assert key1 != key3  # Different params -> different key

    @pytest.mark.asyncio
    async def test_cache_key_order_independent(self):
        """Cache key is order-independent for params."""
        from src.core.materials_api.service import MaterialsService

        async with MaterialsService() as service:
            key1 = service._generate_cache_key("test", a=1, b=2, c=3)
            key2 = service._generate_cache_key("test", c=3, b=2, a=1)
            assert key1 == key2

    @pytest.mark.asyncio
    async def test_check_cache_returns_none_without_cache(self):
        """_check_cache returns None when no cache configured."""
        from src.core.materials_api.service import MaterialsService

        async with MaterialsService() as service:
            # No cache repository configured
            assert service._cache is None
            result = await service._check_cache("any_key")
            assert result is None

    @pytest.mark.asyncio
    async def test_store_cache_noop_without_cache(self):
        """_store_cache is no-op when no cache configured."""
        from src.core.materials_api.service import MaterialsService

        async with MaterialsService() as service:
            # Should not raise even without cache
            await service._store_cache("key", {"data": "test"}, "mp")
            assert service._cache is None

    @pytest.mark.asyncio
    async def test_records_to_dict_conversion(self):
        """_records_to_dict converts MaterialRecords correctly."""
        from src.core.materials_api.service import MaterialsService

        records = [
            MaterialRecord(material_id="mp-1", source="mp", formula="Si"),
            MaterialRecord(material_id="mp-2", source="mp", formula="Ge"),
        ]

        async with MaterialsService() as service:
            dicts = service._records_to_dict(records)
            assert len(dicts) == 2
            assert dicts[0]["material_id"] == "mp-1"
            assert dicts[1]["formula"] == "Ge"

    @pytest.mark.asyncio
    async def test_dict_to_records_conversion(self):
        """_dict_to_records converts dicts back to MaterialRecords."""
        from src.core.materials_api.service import MaterialsService

        data = [
            {
                "material_id": "mp-1",
                "source": "mp",
                "formula": "Si",
                "properties": {},
                "metadata": {},
            },
            {
                "material_id": "mp-2",
                "source": "mp",
                "formula": "Ge",
                "properties": {},
                "metadata": {},
            },
        ]

        async with MaterialsService() as service:
            records = service._dict_to_records(data)
            assert len(records) == 2
            assert records[0].material_id == "mp-1"
            assert records[1].formula == "Ge"

    @pytest.mark.asyncio
    async def test_runtime_error_outside_context(self):
        """Methods raise RuntimeError when not in context manager."""
        from src.core.materials_api.service import MaterialsService

        service = MaterialsService()
        # Not in context manager - should raise RuntimeError
        with pytest.raises(RuntimeError):
            await service._get_mp_client()

    @pytest.mark.asyncio
    async def test_validate_material_id_format(self):
        """get_structure validates material ID format."""
        from src.core.materials_api.service import MaterialsService

        async with MaterialsService() as service:
            # Mock the MP client to avoid actual API calls
            with patch.object(service, "_get_mp_client") as mock_get_client:
                mock_client = AsyncMock()
                mock_get_client.return_value = mock_client

                # Invalid format should raise ValidationError
                with pytest.raises(ValidationError) as exc_info:
                    await service.get_structure("invalid-id")
                assert "mp-" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_search_by_formula_with_cache_hit(self):
        """search_by_formula returns cached data when available."""
        from src.core.materials_api.service import MaterialsService

        # Create mock cache
        mock_cache = AsyncMock()
        cached_data = {
            "records": [
                {
                    "material_id": "mp-1",
                    "source": "mp",
                    "formula": "Si",
                    "properties": {},
                    "metadata": {},
                }
            ],
            "total_count": 1,
        }
        mock_cache.get.return_value = cached_data

        async with MaterialsService(cache=mock_cache) as service:
            result = await service.search_by_formula("Si")

            # Should return cached result
            assert result.cached is True
            assert len(result.records) == 1
            assert result.records[0].formula == "Si"

            # Should have checked cache
            mock_cache.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_by_elements_validates_input(self):
        """search_by_elements raises ValidationError for empty elements."""
        from src.core.materials_api.service import MaterialsService

        async with MaterialsService() as service:
            with pytest.raises(ValidationError) as exc_info:
                await service.search_by_elements([])
            assert "element" in str(exc_info.value).lower()


class TestMaterialsServiceMockedClients:
    """Tests with mocked API clients."""

    @pytest.fixture
    def mock_mp_client(self):
        """Create mock MpApiClient."""
        mock = AsyncMock()
        mock.search_by_formula.return_value = [
            MaterialRecord(
                material_id="mp-149",
                source="mp",
                formula="Si",
                properties={"band_gap": 1.1},
            )
        ]
        mock.close = AsyncMock()
        return mock

    @pytest.mark.asyncio
    async def test_search_by_formula_cache_miss(self, mock_mp_client):
        """search_by_formula fetches from API on cache miss."""
        from src.core.materials_api.service import MaterialsService

        # Create mock cache that returns None (cache miss)
        mock_cache = AsyncMock()
        mock_cache.get.return_value = None
        mock_cache.set = AsyncMock()

        async with MaterialsService(cache=mock_cache) as service:
            # Inject mock client
            with patch.object(service, "_get_mp_client", return_value=mock_mp_client):
                result = await service.search_by_formula("Si")

            # Should return API result
            assert result.cached is False
            assert len(result.records) == 1
            assert result.records[0].material_id == "mp-149"

            # Should have stored in cache
            mock_cache.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_on_exit(self, mock_mp_client):
        """Service cleans up clients on context exit."""
        from src.core.materials_api.service import MaterialsService

        service = MaterialsService()
        await service.__aenter__()

        # Manually set a mock client
        service._mp_client = mock_mp_client

        # Exit context
        await service.__aexit__(None, None, None)

        # Client should have been closed
        mock_mp_client.close.assert_called_once()

        # Client reference should be cleared
        assert service._mp_client is None
