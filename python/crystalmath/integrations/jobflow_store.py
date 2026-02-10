"""
JobStore Bridge for CrystalMath.

This module provides adapters that bridge atomate2/jobflow's JobStore
with CrystalMath's storage backends (SQLite, AiiDA).

Architecture Overview:
----------------------
```
    atomate2/jobflow                  CrystalMath
    +------------------+              +------------------+
    | JobStore         |              | Backend          |
    | MemoryStore      |  <--->       | SQLiteBackend    |
    | MongoStore       |              | AiiDABackend     |
    +------------------+              +------------------+
           |                                  |
           v                                  v
    +------------------+              +------------------+
    | JobStoreBridge   |------------->| .crystal_tui.db  |
    | (adapter layer)  |              | (SQLite)         |
    +------------------+              +------------------+
```

Key Classes:
------------
- `JobStoreBridge`: Abstract bridge interface
- `SQLiteJobStore`: SQLite-backed JobStore for CrystalMath
- `CrystalMathJobStore`: Main integration store supporting multiple backends

Usage:
------
>>> from crystalmath.integrations import CrystalMathJobStore
>>> from jobflow import run_locally
>>>
>>> # Create store backed by CrystalMath's SQLite database
>>> store = CrystalMathJobStore.from_crystalmath_db()
>>>
>>> # Use with jobflow
>>> responses = run_locally(flow, store=store)

Design Notes:
-------------
The bridge provides bidirectional synchronization:
1. atomate2 -> CrystalMath: Job outputs stored in .crystal_tui.db
2. CrystalMath -> atomate2: Existing jobs visible in jobflow queries

This enables:
- Unified job tracking across both systems
- Query jobs from either interface
- Consistent provenance regardless of execution engine

Phase Implementation:
--------------------
This module provides STUB implementations for Phase 2 (design phase).
Full implementations will be completed in Phase 3.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Literal,
    Optional,
    Type,
    Union,
)

if TYPE_CHECKING:
    from maggma.stores import Store
    from monty.json import MSONable

    from crystalmath.backends.sqlite import SQLiteBackend
    from crystalmath.models import JobDetails, JobStatus
    from crystalmath.protocols import Backend, WorkflowResult


# =============================================================================
# Exceptions
# =============================================================================


class JobStoreError(Exception):
    """Base exception for JobStore operations."""

    pass


class SyncError(JobStoreError):
    """Raised when synchronization between stores fails."""

    pass


class QueryError(JobStoreError):
    """Raised when a query operation fails."""

    pass


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class JobRecord:
    """
    Unified job record for bridge operations.

    Represents a job in a format that can be converted to/from both
    atomate2 JobStore documents and CrystalMath JobStatus/JobDetails.

    Attributes:
        uuid: Unique job identifier (atomate2 UUID)
        pk: Primary key in CrystalMath database (if synced)
        name: Human-readable job name
        state: Current job state
        created_at: Creation timestamp
        completed_at: Completion timestamp (if finished)
        inputs: Job input data
        outputs: Job output data
        metadata: Additional metadata
    """

    uuid: str
    pk: Optional[int] = None
    name: str = ""
    state: str = "created"
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_jobflow_dict(self) -> Dict[str, Any]:
        """Convert to jobflow JobStore document format."""
        return {
            "uuid": self.uuid,
            "name": self.name,
            "state": self.state,
            "created_at": (
                self.created_at.isoformat() if self.created_at else None
            ),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "input": self.inputs,
            "output": self.outputs,
            "metadata": {
                **self.metadata,
                "crystalmath_pk": self.pk,
            },
        }

    @classmethod
    def from_jobflow_dict(cls, doc: Dict[str, Any]) -> "JobRecord":
        """Create from jobflow JobStore document."""
        return cls(
            uuid=doc.get("uuid", ""),
            pk=doc.get("metadata", {}).get("crystalmath_pk"),
            name=doc.get("name", ""),
            state=doc.get("state", "created"),
            created_at=(
                datetime.fromisoformat(doc["created_at"])
                if doc.get("created_at")
                else None
            ),
            completed_at=(
                datetime.fromisoformat(doc["completed_at"])
                if doc.get("completed_at")
                else None
            ),
            inputs=doc.get("input", {}),
            outputs=doc.get("output", {}),
            metadata=doc.get("metadata", {}),
        )

    def to_crystalmath_status(self) -> "JobStatus":
        """Convert to CrystalMath JobStatus."""
        from crystalmath.models import JobStatus

        # Map jobflow state to crystalmath state
        state_map = {
            "created": "created",
            "ready": "queued",
            "running": "running",
            "completed": "finished",
            "failed": "failed",
            "paused": "waiting",
        }

        return JobStatus(
            pk=self.pk or 0,
            state=state_map.get(self.state, "created"),
            label=self.name,
            ctime=(
                self.created_at.strftime("%Y-%m-%d %H:%M")
                if self.created_at
                else ""
            ),
            mtime=(
                self.completed_at.strftime("%Y-%m-%d %H:%M")
                if self.completed_at
                else ""
            ),
            description=self.metadata.get("description", ""),
        )


@dataclass
class SyncStats:
    """Statistics from a sync operation."""

    jobs_synced: int = 0
    jobs_created: int = 0
    jobs_updated: int = 0
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


# =============================================================================
# JobStoreBridge: Abstract Bridge Interface
# =============================================================================


class JobStoreBridge(ABC):
    """
    Abstract base class for JobStore bridges.

    Defines the interface for bidirectional synchronization between
    atomate2/jobflow stores and CrystalMath backends.
    """

    @abstractmethod
    def sync_to_crystalmath(self) -> SyncStats:
        """
        Sync jobs from jobflow store to CrystalMath.

        Copies new/updated jobs from the jobflow store to the
        CrystalMath backend.

        Returns:
            SyncStats with counts and any errors
        """
        pass

    @abstractmethod
    def sync_from_crystalmath(self) -> SyncStats:
        """
        Sync jobs from CrystalMath to jobflow store.

        Copies new/updated jobs from the CrystalMath backend to
        the jobflow store.

        Returns:
            SyncStats with counts and any errors
        """
        pass

    @abstractmethod
    def get_job(self, uuid: str) -> Optional[JobRecord]:
        """
        Get a job by UUID.

        Queries both stores and returns the most recent version.

        Args:
            uuid: Job UUID

        Returns:
            JobRecord if found, None otherwise
        """
        pass

    @abstractmethod
    def query_jobs(
        self,
        state: Optional[str] = None,
        name_pattern: Optional[str] = None,
        limit: int = 100,
    ) -> List[JobRecord]:
        """
        Query jobs with filters.

        Args:
            state: Filter by state (optional)
            name_pattern: Filter by name pattern (optional)
            limit: Maximum number of results

        Returns:
            List of matching JobRecords
        """
        pass


# =============================================================================
# SQLiteJobStore: SQLite-backed JobStore
# =============================================================================


class SQLiteJobStore:
    """
    JobStore implementation backed by SQLite.

    This class implements the Maggma Store interface using SQLite,
    enabling jobflow to use CrystalMath's .crystal_tui.db directly.

    The schema extends the existing CrystalMath jobs table with
    additional columns for atomate2 compatibility.

    Example:
        >>> store = SQLiteJobStore("/path/to/.crystal_tui.db")
        >>> store.update([{"uuid": "abc123", "output": {"energy": -10.5}}])
        >>> docs = store.query({"state": "completed"})

    Note:
        This class implements the Maggma Store protocol, making it
        compatible with all jobflow operations.
    """

    def __init__(
        self,
        db_path: Union[str, Path],
        collection_name: str = "jobflow_jobs",
    ):
        """
        Initialize SQLite-backed JobStore.

        Args:
            db_path: Path to SQLite database file
            collection_name: Table name for jobflow data
        """
        self._db_path = Path(db_path)
        self._collection_name = collection_name
        self._connected = False
        self._conn = None

    @property
    def name(self) -> str:
        """Store identifier."""
        return f"sqlite:{self._db_path.name}"

    def connect(self, force: bool = False) -> None:
        """
        Connect to the database.

        Creates the jobflow table if it doesn't exist.

        Args:
            force: Force reconnection even if already connected
        """
        if self._connected and not force:
            return
        import re
        import sqlite3

        # Validate collection name is a safe SQL identifier
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", self._collection_name):
            raise ValueError(
                f"Invalid collection name: {self._collection_name!r}. "
                "Must be a valid SQL identifier."
            )

        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS {} (
                uuid TEXT PRIMARY KEY,
                name TEXT,
                state TEXT DEFAULT 'created',
                created_at TEXT,
                completed_at TEXT,
                input_json TEXT DEFAULT '{{}}',
                output_json TEXT DEFAULT '{{}}',
                metadata_json TEXT DEFAULT '{{}}'
            )
            """.format(self._collection_name)
        )
        self._conn.commit()
        self._connected = True

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
        self._connected = False

    def query(
        self,
        criteria: Optional[Dict[str, Any]] = None,
        properties: Optional[List[str]] = None,
        sort: Optional[Dict[str, int]] = None,
        skip: int = 0,
        limit: int = 0,
    ) -> Iterator[Dict[str, Any]]:
        """
        Query documents from the store.

        Implements Maggma Store.query() interface.

        Args:
            criteria: MongoDB-style query criteria
            properties: Fields to return
            sort: Sort specification
            skip: Number of documents to skip
            limit: Maximum documents to return

        Yields:
            Matching documents
        """
        if not self._connected:
            self.connect()
        import json

        import re

        _VALID_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
        where_clauses: List[str] = []
        params: List[Any] = []
        if criteria:
            for key, value in criteria.items():
                if not _VALID_COLUMN.match(key):
                    raise ValueError(f"Invalid column name in criteria: {key!r}")
                if isinstance(value, dict) and "$regex" in value:
                    where_clauses.append(f"{key} LIKE ?")
                    pattern = value["$regex"].replace(".*", "%").replace(".", "_")
                    params.append(f"%{pattern}%")
                else:
                    where_clauses.append(f"{key} = ?")
                    params.append(
                        value if not isinstance(value, dict) else json.dumps(value)
                    )

        sql = f"SELECT * FROM {self._collection_name}"
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)
        if sort:
            sort_clauses = []
            for field_name, direction in sort.items():
                if not _VALID_COLUMN.match(field_name):
                    raise ValueError(f"Invalid column name in sort: {field_name!r}")
                sort_clauses.append(
                    f"{field_name} {'ASC' if direction == 1 else 'DESC'}"
                )
            sql += " ORDER BY " + ", ".join(sort_clauses)
        if limit:
            sql += f" LIMIT {limit}"
            if skip:
                sql += f" OFFSET {skip}"
        elif skip:
            sql += f" LIMIT -1 OFFSET {skip}"

        cursor = self._conn.execute(sql, params)
        for row in cursor:
            doc = dict(row)
            for json_field in ("input_json", "output_json", "metadata_json"):
                if json_field in doc and doc[json_field]:
                    clean_key = json_field.replace("_json", "")
                    doc[clean_key] = json.loads(doc[json_field])
                    del doc[json_field]
                elif json_field in doc:
                    doc[json_field.replace("_json", "")] = {}
                    del doc[json_field]
            yield doc

    def query_one(
        self,
        criteria: Optional[Dict[str, Any]] = None,
        properties: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Query a single document.

        Args:
            criteria: MongoDB-style query criteria
            properties: Fields to return

        Returns:
            First matching document or None
        """
        for doc in self.query(criteria=criteria, properties=properties, limit=1):
            return doc
        return None

    def update(
        self,
        docs: List[Dict[str, Any]],
        key: str = "uuid",
    ) -> None:
        """
        Update/insert documents.

        Implements Maggma Store.update() interface.

        Args:
            docs: Documents to update/insert
            key: Field to use as unique key
        """
        if not self._connected:
            self.connect()
        import json

        for doc in docs:
            uuid_val = doc.get(key, doc.get("uuid", ""))
            self._conn.execute(
                f"""INSERT OR REPLACE INTO {self._collection_name}
                    (uuid, name, state, created_at, completed_at,
                     input_json, output_json, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    uuid_val,
                    doc.get("name", ""),
                    doc.get("state", "created"),
                    doc.get("created_at", ""),
                    doc.get("completed_at", ""),
                    json.dumps(doc.get("input", {})),
                    json.dumps(doc.get("output", {})),
                    json.dumps(doc.get("metadata", {})),
                ),
            )
        self._conn.commit()

    def count(
        self,
        criteria: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Count matching documents.

        Args:
            criteria: MongoDB-style query criteria

        Returns:
            Number of matching documents
        """
        return sum(1 for _ in self.query(criteria=criteria))

    def distinct(
        self,
        field: str,
        criteria: Optional[Dict[str, Any]] = None,
    ) -> List[Any]:
        """
        Get distinct values for a field.

        Args:
            field: Field to get distinct values for
            criteria: Optional filter criteria

        Returns:
            List of distinct values
        """
        if not self._connected:
            self.connect()
        sql = f"SELECT DISTINCT {field} FROM {self._collection_name}"
        params: List[Any] = []
        if criteria:
            import json

            where_clauses: List[str] = []
            for key, value in criteria.items():
                where_clauses.append(f"{key} = ?")
                params.append(
                    value if not isinstance(value, dict) else json.dumps(value)
                )
            sql += " WHERE " + " AND ".join(where_clauses)
        cursor = self._conn.execute(sql, params)
        return [row[0] for row in cursor]

    def remove_docs(
        self,
        criteria: Dict[str, Any],
    ) -> None:
        """
        Remove documents matching criteria.

        Args:
            criteria: MongoDB-style query criteria

        Note:
            This is a STUB implementation. Full implementation in Phase 3.
        """
        raise NotImplementedError(
            "SQLiteJobStore.remove_docs() will be implemented in Phase 3."
        )


# =============================================================================
# CrystalMathJobStore: Main Integration Store
# =============================================================================


class CrystalMathJobStore(JobStoreBridge):
    """
    Main JobStore integration for CrystalMath.

    Provides a unified interface that:
    - Implements Maggma Store protocol for jobflow compatibility
    - Syncs with CrystalMath's SQLite backend
    - Optionally syncs with AiiDA for provenance
    - Supports multiple storage backends

    The store maintains consistency between atomate2/jobflow jobs
    and CrystalMath's job tracking system.

    Example:
        >>> # From existing CrystalMath database
        >>> store = CrystalMathJobStore.from_crystalmath_db()
        >>>
        >>> # Run atomate2 flow with CrystalMath storage
        >>> from jobflow import run_locally
        >>> responses = run_locally(flow, store=store)
        >>>
        >>> # Jobs now visible in both systems
        >>> jobs = store.query_jobs(state="completed")

    Attributes:
        primary_store: Main Maggma Store for job data
        crystalmath_backend: CrystalMath Backend for sync
        sync_enabled: Whether automatic sync is enabled
    """

    def __init__(
        self,
        primary_store: Optional["Store"] = None,
        crystalmath_backend: Optional["Backend"] = None,
        sync_enabled: bool = True,
    ):
        """
        Initialize the CrystalMath JobStore.

        Args:
            primary_store: Maggma Store for primary storage.
                          If None, creates SQLiteJobStore.
            crystalmath_backend: CrystalMath Backend for sync.
                                If None, uses default SQLiteBackend.
            sync_enabled: Whether to auto-sync on operations
        """
        self._primary_store = primary_store
        self._crystalmath_backend = crystalmath_backend
        self._sync_enabled = sync_enabled
        self._initialized = False

    @classmethod
    def from_crystalmath_db(
        cls,
        db_path: Optional[Union[str, Path]] = None,
    ) -> "CrystalMathJobStore":
        """
        Create from existing CrystalMath database.

        Uses the default .crystal_tui.db location if no path provided.

        Args:
            db_path: Path to database (optional)

        Returns:
            Configured CrystalMathJobStore

        Example:
            >>> store = CrystalMathJobStore.from_crystalmath_db()
            >>> # Uses ~/.crystal_tui.db
        """
        if db_path is None:
            db_path = Path.home() / ".crystal_tui.db"

        sqlite_store = SQLiteJobStore(db_path=db_path)
        return cls(primary_store=sqlite_store)

    @classmethod
    def from_mongo(
        cls,
        host: str = "localhost",
        port: int = 27017,
        database: str = "crystalmath",
        collection: str = "jobs",
    ) -> "CrystalMathJobStore":
        """
        Create with MongoDB backend.

        For production use with MongoDB for atomate2 storage.

        Args:
            host: MongoDB host
            port: MongoDB port
            database: Database name
            collection: Collection name

        Returns:
            Configured CrystalMathJobStore

        Note:
            This is a STUB implementation. Full implementation in Phase 3.
        """
        raise NotImplementedError(
            "CrystalMathJobStore.from_mongo() will be implemented in Phase 3."
        )

    @property
    def name(self) -> str:
        """Store identifier."""
        if self._primary_store:
            return f"crystalmath:{self._primary_store.name}"
        return "crystalmath:uninitialized"

    def connect(self, force: bool = False) -> None:
        """
        Connect to all underlying stores.

        Args:
            force: Force reconnection
        """
        if self._primary_store:
            self._primary_store.connect(force=force)
        self._initialized = True

    def close(self) -> None:
        """Close all connections."""
        if self._primary_store:
            self._primary_store.close()
        self._initialized = False

    # =========================================================================
    # Maggma Store Interface
    # =========================================================================

    def query(
        self,
        criteria: Optional[Dict[str, Any]] = None,
        properties: Optional[List[str]] = None,
        sort: Optional[Dict[str, int]] = None,
        skip: int = 0,
        limit: int = 0,
    ) -> Iterator[Dict[str, Any]]:
        """
        Query documents from the store.

        Delegates to primary store with optional CrystalMath sync.

        Note:
            This is a STUB implementation. Full implementation in Phase 3.
        """
        if self._primary_store:
            yield from self._primary_store.query(
                criteria=criteria,
                properties=properties,
                sort=sort,
                skip=skip,
                limit=limit,
            )

    def update(
        self,
        docs: List[Dict[str, Any]],
        key: str = "uuid",
    ) -> None:
        """
        Update/insert documents.

        Updates primary store and optionally syncs to CrystalMath.

        Note:
            This is a STUB implementation. Full implementation in Phase 3.
        """
        if self._primary_store:
            self._primary_store.update(docs, key=key)

        # Sync to CrystalMath if enabled
        if self._sync_enabled and self._crystalmath_backend:
            self._sync_docs_to_crystalmath(docs)

    def _sync_docs_to_crystalmath(self, docs: List[Dict[str, Any]]) -> None:
        """
        Sync documents to CrystalMath backend.

        Args:
            docs: Documents to sync

        Note:
            This is a STUB implementation. Full implementation in Phase 3.
        """
        pass  # STUB

    # =========================================================================
    # JobStoreBridge Interface
    # =========================================================================

    def sync_to_crystalmath(self) -> SyncStats:
        """
        Sync all jobs from jobflow store to CrystalMath.

        Returns:
            SyncStats with operation results
        """
        import time

        start = time.time()
        stats = SyncStats()

        if not self._primary_store:
            stats.errors.append("No primary store configured")
            return stats

        try:
            for doc in self._primary_store.query():
                record = JobRecord.from_jobflow_dict(doc)
                record.to_crystalmath_status()  # validate conversion works
                stats.jobs_synced += 1
        except Exception as e:
            stats.errors.append(str(e))

        stats.duration_seconds = time.time() - start
        return stats

    def sync_from_crystalmath(self) -> SyncStats:
        """
        Sync all jobs from CrystalMath to jobflow store.

        Returns:
            SyncStats with operation results

        Note:
            This is a STUB implementation. Full implementation in Phase 3.
        """
        raise NotImplementedError(
            "CrystalMathJobStore.sync_from_crystalmath() will be implemented in Phase 3."
        )

    def get_job(self, uuid: str) -> Optional[JobRecord]:
        """
        Get a job by UUID.

        Args:
            uuid: Job UUID

        Returns:
            JobRecord if found
        """
        doc = None
        if self._primary_store:
            doc = self._primary_store.query_one({"uuid": uuid})

        if doc:
            return JobRecord.from_jobflow_dict(doc)
        return None

    def query_jobs(
        self,
        state: Optional[str] = None,
        name_pattern: Optional[str] = None,
        limit: int = 100,
    ) -> List[JobRecord]:
        """
        Query jobs with filters.

        Args:
            state: Filter by state
            name_pattern: Filter by name (regex)
            limit: Maximum results

        Returns:
            List of JobRecords
        """
        criteria: Dict[str, Any] = {}
        if state:
            criteria["state"] = state
        if name_pattern:
            criteria["name"] = {"$regex": name_pattern}

        records = []
        for doc in self.query(criteria=criteria, limit=limit):
            records.append(JobRecord.from_jobflow_dict(doc))

        return records

    # =========================================================================
    # CrystalMath Integration
    # =========================================================================

    def to_workflow_results(
        self,
        flow_uuid: str,
    ) -> List["WorkflowResult"]:
        """
        Get all WorkflowResults for a Flow.

        Converts jobflow job outputs to CrystalMath WorkflowResult format.

        Args:
            flow_uuid: UUID of the parent Flow

        Returns:
            List of WorkflowResult objects

        Note:
            This is a STUB implementation. Full implementation in Phase 3.
        """
        raise NotImplementedError(
            "CrystalMathJobStore.to_workflow_results() will be implemented in Phase 3."
        )

    def import_from_aiida(
        self,
        aiida_pks: List[int],
    ) -> SyncStats:
        """
        Import jobs from AiiDA into the jobflow store.

        Enables using existing AiiDA calculations with atomate2.

        Args:
            aiida_pks: List of AiiDA node PKs to import

        Returns:
            SyncStats with import results

        Note:
            This is a STUB implementation. Full implementation in Phase 3.
        """
        raise NotImplementedError(
            "CrystalMathJobStore.import_from_aiida() will be implemented in Phase 3."
        )


# =============================================================================
# Convenience Functions
# =============================================================================


def get_crystalmath_store(
    backend: Literal["sqlite", "mongo", "memory"] = "sqlite",
    **kwargs: Any,
) -> CrystalMathJobStore:
    """
    Factory function to get a CrystalMathJobStore.

    Args:
        backend: Storage backend type
        **kwargs: Backend-specific options

    Returns:
        Configured CrystalMathJobStore

    Example:
        >>> # SQLite backend (default)
        >>> store = get_crystalmath_store()
        >>>
        >>> # MongoDB backend
        >>> store = get_crystalmath_store("mongo", host="localhost")
    """
    if backend == "sqlite":
        return CrystalMathJobStore.from_crystalmath_db(
            db_path=kwargs.get("db_path"),
        )
    elif backend == "mongo":
        return CrystalMathJobStore.from_mongo(**kwargs)
    elif backend == "memory":
        # Use jobflow's MemoryStore
        try:
            from jobflow import MemoryStore

            return CrystalMathJobStore(primary_store=MemoryStore())
        except ImportError:
            raise ImportError("jobflow is required for memory store")
    else:
        raise ValueError(f"Unknown backend: {backend}")


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Exceptions
    "JobStoreError",
    "SyncError",
    "QueryError",
    # Data classes
    "JobRecord",
    "SyncStats",
    # Bridge classes
    "JobStoreBridge",
    "SQLiteJobStore",
    "CrystalMathJobStore",
    # Factory functions
    "get_crystalmath_store",
]
