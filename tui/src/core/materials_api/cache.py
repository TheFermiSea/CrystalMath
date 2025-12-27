"""Async cache repository for Materials API responses.

Provides persistent caching of API responses using aiosqlite with TTL-based
invalidation. Designed to work with the database schema defined in
`src/core/database.py` (migration V6).

Usage:
    from src.core.materials_api.cache import CacheRepository

    async with CacheRepository(db_path) as cache:
        # Check cache first
        entry = await cache.get_cached_response(key, "mp")
        if entry and not entry.is_expired:
            return entry.get_response()

        # Fetch from API and cache
        response = await api.fetch(...)
        await cache.set_cached_response(key, "mp", query, response)
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

from .errors import CacheError
from .models import CacheEntry, ContributionRecord, MaterialRecord
from .settings import MaterialsSettings


def generate_cache_key(query: dict[str, Any], prefix: str | None = None) -> str:
    """Generate a deterministic cache key from a query dictionary.

    Uses SHA-256 hash of JSON-serialized query with sorted keys for consistency.
    This matches the key generation used by MaterialsService for cache lookups.

    Args:
        query: Query parameters to hash
        prefix: Optional prefix for the cache key (e.g., 'search_formula')

    Returns:
        Cache key string, optionally prefixed (e.g., 'search_formula:a1b2c3d4')
    """
    serialized = json.dumps(query, sort_keys=True, separators=(",", ":"), default=str)
    key_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
    if prefix:
        return f"{prefix}:{key_hash}"
    return key_hash


class CacheRepository:
    """Async repository for caching Materials API responses.

    Implements TTL-based cache invalidation with support for:
    - Raw API response caching (materials_cache table)
    - Parsed material records (materials_structures table)
    - MPContribs contributions (mpcontribs_cache table)

    Supports two usage patterns:

    1. Async context manager (recommended for direct use):
        async with CacheRepository(Path("crystal_tui.db")) as cache:
            entry = await cache.get_cached_response("key", "mp")

    2. Factory pattern (for MaterialsService integration):
        cache = await CacheRepository.create(Path("crystal_tui.db"))
        try:
            data = await cache.get("key")
        finally:
            await cache.close()

    Attributes:
        db_path: Path to SQLite database file
        settings: MaterialsSettings instance for configuration
        default_ttl_days: Default cache TTL from settings

    Example:
        async with CacheRepository(Path("crystal_tui.db")) as cache:
            # Store response
            await cache.set_cached_response(
                cache_key="abc123",
                source="mp",
                query={"formula": "MoS2"},
                response={"data": [...]},
                ttl_days=30
            )

            # Retrieve cached response
            entry = await cache.get_cached_response("abc123", "mp")
            if entry and not entry.is_expired:
                data = entry.get_response()
    """

    def __init__(
        self,
        db_path: Path | str,
        settings: MaterialsSettings | None = None,
    ) -> None:
        """Initialize cache repository.

        Args:
            db_path: Path to SQLite database file
            settings: Optional MaterialsSettings; defaults to singleton instance
        """
        self.db_path = Path(db_path)
        self.settings = settings or MaterialsSettings.get_instance()
        self.default_ttl_days = self.settings.cache_ttl_days
        self._connection: aiosqlite.Connection | None = None

    @classmethod
    async def create(
        cls,
        db_path: Path | str,
        settings: MaterialsSettings | None = None,
    ) -> "CacheRepository":
        """Factory method to create and initialize a CacheRepository.

        This is the preferred way to create a CacheRepository when using it
        with MaterialsService, as it handles connection initialization.

        Args:
            db_path: Path to SQLite database file
            settings: Optional MaterialsSettings; defaults to singleton instance

        Returns:
            Initialized CacheRepository with open database connection

        Example:
            cache = await CacheRepository.create("crystal_tui.db")
            try:
                data = await cache.get("my_key")
            finally:
                await cache.close()
        """
        instance = cls(db_path, settings)
        await instance.__aenter__()
        return instance

    async def __aenter__(self) -> CacheRepository:
        """Enter async context manager, opening database connection."""
        self._connection = await aiosqlite.connect(str(self.db_path))
        self._connection.row_factory = aiosqlite.Row
        # Enable WAL mode for better concurrent access
        await self._connection.execute("PRAGMA journal_mode=WAL")
        await self._connection.execute("PRAGMA foreign_keys=ON")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit async context manager, closing database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None

    def _ensure_connection(self) -> aiosqlite.Connection:
        """Ensure database connection is available.

        Returns:
            Active database connection

        Raises:
            CacheError: If not in async context manager
        """
        if self._connection is None:
            raise CacheError(
                "read",
                "CacheRepository must be used as async context manager. "
                "Use: async with CacheRepository(db_path) as cache: ..."
            )
        return self._connection

    # ==================== Raw Response Cache ====================

    async def get_cached_response(
        self,
        cache_key: str,
        source: str,
    ) -> CacheEntry | None:
        """Retrieve a cached API response.

        Args:
            cache_key: Unique cache key (typically MD5 of query)
            source: API source ('mp', 'mpcontribs', 'optimade')

        Returns:
            CacheEntry if found, None otherwise. Caller should check
            `entry.is_expired` before using the cached data.

        Raises:
            CacheError: On database read failure
        """
        conn = self._ensure_connection()

        try:
            async with conn.execute(
                """
                SELECT cache_key, source, query_json, response_json,
                       fetched_at, expires_at, etag
                FROM materials_cache
                WHERE cache_key = ? AND source = ?
                """,
                (cache_key, source),
            ) as cursor:
                row = await cursor.fetchone()

            if not row:
                return None

            # Parse datetime strings
            fetched_at = datetime.fromisoformat(row["fetched_at"])
            expires_at = (
                datetime.fromisoformat(row["expires_at"])
                if row["expires_at"]
                else None
            )

            return CacheEntry(
                cache_key=row["cache_key"],
                source=row["source"],
                query_json=row["query_json"],
                response_json=row["response_json"],
                fetched_at=fetched_at,
                expires_at=expires_at,
                etag=row["etag"],
            )

        except aiosqlite.Error as e:
            raise CacheError("read", f"Failed to read cache: {e}") from e

    async def set_cached_response(
        self,
        cache_key: str,
        source: str,
        query: dict[str, Any],
        response: dict[str, Any],
        ttl_days: int | None = None,
        etag: str | None = None,
    ) -> None:
        """Store an API response in the cache.

        Args:
            cache_key: Unique cache key (use generate_cache_key() helper)
            source: API source ('mp', 'mpcontribs', 'optimade')
            query: Original query parameters
            response: API response to cache
            ttl_days: Optional TTL override; defaults to settings.cache_ttl_days
            etag: Optional HTTP ETag for conditional requests

        Raises:
            CacheError: On database write failure
        """
        conn = self._ensure_connection()

        ttl = ttl_days if ttl_days is not None else self.default_ttl_days
        now = datetime.now()
        expires_at = now + timedelta(days=ttl)

        query_json = json.dumps(query, sort_keys=True)
        response_json = json.dumps(response)

        try:
            await conn.execute(
                """
                INSERT INTO materials_cache
                    (cache_key, source, query_json, response_json,
                     fetched_at, expires_at, etag)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, cache_key) DO UPDATE SET
                    query_json = excluded.query_json,
                    response_json = excluded.response_json,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at,
                    etag = excluded.etag
                """,
                (
                    cache_key,
                    source,
                    query_json,
                    response_json,
                    now.isoformat(),
                    expires_at.isoformat(),
                    etag,
                ),
            )
            await conn.commit()

        except aiosqlite.Error as e:
            raise CacheError("write", f"Failed to write cache: {e}") from e

    # ==================== Material Records Cache ====================

    async def get_material_record(
        self,
        material_id: str,
        source: str,
    ) -> MaterialRecord | None:
        """Retrieve a cached material record.

        Args:
            material_id: Material identifier (e.g., 'mp-149')
            source: API source ('mp', 'mpcontribs', 'optimade')

        Returns:
            MaterialRecord if found and not expired, None otherwise

        Raises:
            CacheError: On database read failure
        """
        conn = self._ensure_connection()

        try:
            async with conn.execute(
                """
                SELECT material_id, source, formula, structure_json,
                       fetched_at, updated_at, expires_at
                FROM materials_structures
                WHERE material_id = ? AND source = ?
                """,
                (material_id, source),
            ) as cursor:
                row = await cursor.fetchone()

            if not row:
                return None

            # Check expiry if set
            expires_at = row["expires_at"]
            if expires_at:
                expires_dt = datetime.fromisoformat(expires_at)
                if datetime.now() >= expires_dt:
                    # Expired - treat as cache miss
                    return None

            # Parse structure JSON which contains full MaterialRecord data
            structure_data = json.loads(row["structure_json"])

            # Reconstruct MaterialRecord from stored data
            return MaterialRecord.from_dict(structure_data)

        except aiosqlite.Error as e:
            raise CacheError("read", f"Failed to read material record: {e}") from e
        except (json.JSONDecodeError, KeyError):
            # Corrupted cache entry - treat as cache miss
            return None

    async def set_material_record(
        self,
        record: MaterialRecord,
        ttl_days: int | None = None,
    ) -> None:
        """Store a material record in the cache.

        Args:
            record: MaterialRecord to cache
            ttl_days: Optional TTL override; defaults to settings.cache_ttl_days

        Raises:
            CacheError: On database write failure
        """
        conn = self._ensure_connection()

        ttl = ttl_days if ttl_days is not None else self.default_ttl_days
        now = datetime.now()
        expires_at = now + timedelta(days=ttl)

        # Serialize full record to JSON for storage
        structure_json = json.dumps(record.to_dict())

        try:
            await conn.execute(
                """
                INSERT INTO materials_structures
                    (material_id, source, formula, structure_json,
                     fetched_at, updated_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, material_id) DO UPDATE SET
                    formula = excluded.formula,
                    structure_json = excluded.structure_json,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at
                """,
                (
                    record.material_id,
                    record.source,
                    record.formula,
                    structure_json,
                    now.isoformat(),
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )
            await conn.commit()

        except aiosqlite.Error as e:
            raise CacheError("write", f"Failed to write material record: {e}") from e

    # ==================== Contribution Records Cache ====================

    async def get_contribution(
        self,
        contribution_id: str,
    ) -> ContributionRecord | None:
        """Retrieve a cached MPContribs contribution.

        Args:
            contribution_id: MPContribs contribution ID

        Returns:
            ContributionRecord if found and not expired, None otherwise

        Raises:
            CacheError: On database read failure
        """
        conn = self._ensure_connection()

        try:
            async with conn.execute(
                """
                SELECT contribution_id, project, material_id, data_json,
                       fetched_at, expires_at
                FROM mpcontribs_cache
                WHERE contribution_id = ?
                """,
                (contribution_id,),
            ) as cursor:
                row = await cursor.fetchone()

            if not row:
                return None

            # Check expiry if set
            expires_at = row["expires_at"]
            if expires_at:
                expires_dt = datetime.fromisoformat(expires_at)
                if datetime.now() >= expires_dt:
                    # Expired - treat as cache miss
                    return None

            # Parse data JSON which contains full ContributionRecord data
            data = json.loads(row["data_json"])

            return ContributionRecord.from_dict(data)

        except aiosqlite.Error as e:
            raise CacheError("read", f"Failed to read contribution: {e}") from e
        except (json.JSONDecodeError, KeyError):
            # Corrupted cache entry - treat as cache miss
            return None

    async def set_contribution(
        self,
        record: ContributionRecord,
        ttl_days: int | None = None,
    ) -> None:
        """Store an MPContribs contribution in the cache.

        Args:
            record: ContributionRecord to cache
            ttl_days: Optional TTL override; defaults to settings.cache_ttl_days

        Raises:
            CacheError: On database write failure
        """
        conn = self._ensure_connection()

        ttl = ttl_days if ttl_days is not None else self.default_ttl_days
        now = datetime.now()
        expires_at = now + timedelta(days=ttl)

        # Serialize full record to JSON for storage
        data_json = json.dumps(record.to_dict())

        try:
            await conn.execute(
                """
                INSERT INTO mpcontribs_cache
                    (contribution_id, project, material_id, data_json, fetched_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(contribution_id) DO UPDATE SET
                    project = excluded.project,
                    material_id = excluded.material_id,
                    data_json = excluded.data_json,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at
                """,
                (
                    record.contribution_id,
                    record.project,
                    record.material_id,
                    data_json,
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )
            await conn.commit()

        except aiosqlite.Error as e:
            raise CacheError("write", f"Failed to write contribution: {e}") from e

    # ==================== Cache Maintenance ====================

    async def invalidate_expired(self) -> int:
        """Remove all expired cache entries.

        Removes entries from all cache tables where expires_at < now.

        Returns:
            Total number of expired entries removed across all tables

        Raises:
            CacheError: On database operation failure
        """
        conn = self._ensure_connection()

        now = datetime.now().isoformat()
        total_deleted = 0

        try:
            # Clean materials_cache
            async with conn.execute(
                """
                DELETE FROM materials_cache
                WHERE expires_at IS NOT NULL AND expires_at < ?
                """,
                (now,),
            ) as cursor:
                total_deleted += cursor.rowcount

            # Clean materials_structures
            async with conn.execute(
                """
                DELETE FROM materials_structures
                WHERE expires_at IS NOT NULL AND expires_at < ?
                """,
                (now,),
            ) as cursor:
                total_deleted += cursor.rowcount

            # Clean mpcontribs_cache
            async with conn.execute(
                """
                DELETE FROM mpcontribs_cache
                WHERE expires_at IS NOT NULL AND expires_at < ?
                """,
                (now,),
            ) as cursor:
                total_deleted += cursor.rowcount

            await conn.commit()
            return total_deleted

        except aiosqlite.Error as e:
            raise CacheError("expire", f"Failed to invalidate expired entries: {e}") from e

    async def clear_cache(self, source: str | None = None) -> int:
        """Clear cache entries.

        Args:
            source: Optional source to clear ('mp', 'mpcontribs', 'optimade').
                   If None, clears all cached data.

        Returns:
            Total number of entries removed across all tables

        Raises:
            CacheError: On database operation failure
        """
        conn = self._ensure_connection()

        total_deleted = 0

        try:
            if source:
                # Clear specific source from materials_cache
                async with conn.execute(
                    "DELETE FROM materials_cache WHERE source = ?",
                    (source,),
                ) as cursor:
                    total_deleted += cursor.rowcount

                # Clear specific source from materials_structures
                async with conn.execute(
                    "DELETE FROM materials_structures WHERE source = ?",
                    (source,),
                ) as cursor:
                    total_deleted += cursor.rowcount

                # mpcontribs_cache only applies to 'mpcontribs' source
                if source == "mpcontribs":
                    async with conn.execute(
                        "DELETE FROM mpcontribs_cache"
                    ) as cursor:
                        total_deleted += cursor.rowcount

            else:
                # Clear all caches
                async with conn.execute("DELETE FROM materials_cache") as cursor:
                    total_deleted += cursor.rowcount

                async with conn.execute("DELETE FROM materials_structures") as cursor:
                    total_deleted += cursor.rowcount

                async with conn.execute("DELETE FROM mpcontribs_cache") as cursor:
                    total_deleted += cursor.rowcount

            await conn.commit()
            return total_deleted

        except aiosqlite.Error as e:
            raise CacheError("clear", f"Failed to clear cache: {e}") from e

    # ==================== Utility Methods ====================

    async def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics:
            - total_responses: Number of cached API responses
            - total_structures: Number of cached material structures
            - total_contributions: Number of cached contributions
            - expired_responses: Number of expired response entries
            - by_source: Breakdown by API source

        Raises:
            CacheError: On database read failure
        """
        conn = self._ensure_connection()

        now = datetime.now().isoformat()

        try:
            stats: dict[str, Any] = {}

            # Count materials_cache entries
            async with conn.execute(
                "SELECT COUNT(*) FROM materials_cache"
            ) as cursor:
                row = await cursor.fetchone()
                stats["total_responses"] = row[0] if row else 0

            # Count expired entries
            async with conn.execute(
                """
                SELECT COUNT(*) FROM materials_cache
                WHERE expires_at IS NOT NULL AND expires_at < ?
                """,
                (now,),
            ) as cursor:
                row = await cursor.fetchone()
                stats["expired_responses"] = row[0] if row else 0

            # Count materials_structures entries
            async with conn.execute(
                "SELECT COUNT(*) FROM materials_structures"
            ) as cursor:
                row = await cursor.fetchone()
                stats["total_structures"] = row[0] if row else 0

            # Count mpcontribs_cache entries
            async with conn.execute(
                "SELECT COUNT(*) FROM mpcontribs_cache"
            ) as cursor:
                row = await cursor.fetchone()
                stats["total_contributions"] = row[0] if row else 0

            # Breakdown by source for materials_cache
            async with conn.execute(
                "SELECT source, COUNT(*) FROM materials_cache GROUP BY source"
            ) as cursor:
                rows = await cursor.fetchall()
                stats["by_source"] = {row[0]: row[1] for row in rows}

            return stats

        except aiosqlite.Error as e:
            raise CacheError("read", f"Failed to get cache stats: {e}") from e

    # ==================== CacheRepositoryProtocol Adapters ====================
    # These methods provide the simplified interface expected by MaterialsService

    async def get(self, cache_key: str) -> dict[str, Any] | None:
        """Retrieve cached data by key (CacheRepositoryProtocol interface).

        This is a simplified wrapper around get_cached_response that returns
        the raw response data as a dictionary, automatically checking expiration.

        Args:
            cache_key: Unique cache key

        Returns:
            Cached data as dictionary, or None if not found/expired
        """
        # Try each source - in practice the key should be unique across sources
        for source in ("mp", "optimade", "mpcontribs"):
            entry = await self.get_cached_response(cache_key, source)
            if entry is not None and not entry.is_expired:
                return entry.get_response()
        return None

    async def set(
        self,
        cache_key: str,
        data: dict[str, Any],
        source: str,
        ttl_days: int | None = None,
    ) -> None:
        """Store data in cache (CacheRepositoryProtocol interface).

        This is a simplified wrapper around set_cached_response.

        Args:
            cache_key: Unique cache key
            data: Data to cache (must be JSON-serializable)
            source: API source identifier ('mp', 'mpcontribs', 'optimade')
            ttl_days: Time-to-live in days (None for default)
        """
        await self.set_cached_response(
            cache_key=cache_key,
            source=source,
            query={"cache_key": cache_key},  # Minimal query for audit trail
            response=data,
            ttl_days=ttl_days,
        )

    async def invalidate(self, cache_key: str) -> None:
        """Remove a specific entry from cache (CacheRepositoryProtocol interface).

        Args:
            cache_key: Cache key to invalidate

        Raises:
            CacheError: On database operation failure
        """
        conn = self._ensure_connection()

        try:
            await conn.execute(
                "DELETE FROM materials_cache WHERE cache_key = ?",
                (cache_key,),
            )
            await conn.commit()
        except aiosqlite.Error as e:
            raise CacheError("invalidate", f"Failed to invalidate cache key: {e}") from e

    async def clear_expired(self) -> int:
        """Remove all expired entries from cache (CacheRepositoryProtocol interface).

        This is an alias for invalidate_expired() for protocol compatibility.

        Returns:
            Number of entries removed
        """
        return await self.invalidate_expired()

    async def close(self) -> None:
        """Close the database connection (CacheRepositoryProtocol interface).

        This method enables explicit cleanup when using the factory pattern
        (CacheRepository.create) instead of the async context manager.

        Safe to call multiple times; subsequent calls are no-ops.
        """
        await self.__aexit__(None, None, None)
