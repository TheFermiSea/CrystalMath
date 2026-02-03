"""
SQLite database interface for job history and state management.

Includes support for:
- Local and remote job execution
- Cluster configurations (SSH, SLURM)
- Job dependencies and workflows
- Schema versioning and migrations
"""

import sqlite3
import json
import warnings
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from queue import SimpleQueue
from contextlib import contextmanager


class RunnerType(Enum):
    """Job execution backend types."""
    LOCAL = "local"
    SSH = "ssh"
    SLURM = "slurm"


class ClusterType(Enum):
    """Remote cluster types."""
    SSH = "ssh"
    SLURM = "slurm"


class DependencyType(Enum):
    """Job dependency relationship types."""
    AFTER_OK = "after_ok"  # Run after successful completion
    AFTER_ANY = "after_any"  # Run after completion (any status)
    AFTER_FAILED = "after_failed"  # Run only if dependency failed


@dataclass
class Job:
    """Represents a DFT calculation job."""
    id: Optional[int]
    name: str
    work_dir: str
    status: str
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    pid: Optional[int] = None
    input_file: Optional[str] = None
    final_energy: Optional[float] = None
    key_results: Optional[Dict[str, Any]] = None
    # Phase 2 fields
    cluster_id: Optional[int] = None
    runner_type: str = "local"
    parallelism_config: Optional[Dict[str, Any]] = None
    queue_time: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    # Phase 3 field - DFT code type
    dft_code: str = "crystal"  # crystal, quantum_espresso, vasp


@dataclass
class Cluster:
    """Represents a remote cluster configuration."""
    id: Optional[int]
    name: str
    type: str  # ssh or slurm
    hostname: str
    port: int
    username: str
    connection_config: Dict[str, Any]  # JSON: key_file, password, etc.
    status: str  # active, inactive, error
    cry23_root: Optional[str] = None
    vasp_root: Optional[str] = None
    setup_commands: Optional[List[str]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class RemoteJob:
    """Represents remote job execution details."""
    id: Optional[int]
    job_id: int
    cluster_id: int
    remote_handle: str  # Remote job ID (PID for SSH, job ID for SLURM)
    submission_time: Optional[str] = None
    queue_name: Optional[str] = None
    node_list: Optional[str] = None
    working_directory: str = ""
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class JobDependency:
    """Represents a dependency between two jobs."""
    id: Optional[int]
    job_id: int
    depends_on_job_id: int
    dependency_type: str


@dataclass
class JobResult:
    """Represents detailed job results (normalized from jobs table)."""
    id: Optional[int]
    job_id: int
    key_results: Optional[Dict[str, Any]] = None
    convergence_status: Optional[str] = None
    scf_cycles: Optional[int] = None
    cpu_time_seconds: Optional[float] = None
    wall_time_seconds: Optional[float] = None
    created_at: Optional[str] = None


class Database:
    """Manages the SQLite database for DFT-TUI project."""

    # Schema version for migrations
    # Note: Must match the highest version after all migrations are applied
    SCHEMA_VERSION = 8

    # Base schema (version 1 - Phase 1)
    # Note: CANCELLED added in v4, but included here for new databases
    SCHEMA_V1 = """
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        work_dir TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL CHECK(status IN ('PENDING', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        started_at TIMESTAMP,
        completed_at TIMESTAMP,
        pid INTEGER,
        input_file TEXT,
        final_energy REAL,
        key_results TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);
    CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs (created_at DESC);

    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    # Migration to version 2 (Phase 2 - Remote execution)
    MIGRATION_V1_TO_V2 = """
    -- Add remote execution columns to jobs table
    ALTER TABLE jobs ADD COLUMN cluster_id INTEGER REFERENCES clusters(id) ON DELETE SET NULL;
    ALTER TABLE jobs ADD COLUMN runner_type TEXT DEFAULT 'local' CHECK(runner_type IN ('local', 'ssh', 'slurm'));
    ALTER TABLE jobs ADD COLUMN parallelism_config TEXT;
    ALTER TABLE jobs ADD COLUMN queue_time TIMESTAMP;
    ALTER TABLE jobs ADD COLUMN start_time TIMESTAMP;
    ALTER TABLE jobs ADD COLUMN end_time TIMESTAMP;

    -- Clusters table
    CREATE TABLE IF NOT EXISTS clusters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        type TEXT NOT NULL CHECK(type IN ('ssh', 'slurm')),
        hostname TEXT NOT NULL,
        port INTEGER NOT NULL DEFAULT 22,
        username TEXT NOT NULL,
        connection_config TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'inactive', 'error')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_clusters_status ON clusters (status);
    CREATE INDEX IF NOT EXISTS idx_clusters_type ON clusters (type);

    -- Remote jobs table
    CREATE TABLE IF NOT EXISTS remote_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        cluster_id INTEGER NOT NULL,
        remote_handle TEXT NOT NULL,
        submission_time TIMESTAMP,
        queue_name TEXT,
        node_list TEXT,
        working_directory TEXT NOT NULL,
        stdout_path TEXT,
        stderr_path TEXT,
        metadata TEXT,
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
        FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_remote_jobs_job_id ON remote_jobs (job_id);
    CREATE INDEX IF NOT EXISTS idx_remote_jobs_cluster_id ON remote_jobs (cluster_id);
    CREATE INDEX IF NOT EXISTS idx_remote_jobs_handle ON remote_jobs (remote_handle);

    -- Job dependencies table
    CREATE TABLE IF NOT EXISTS job_dependencies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL,
        depends_on_job_id INTEGER NOT NULL,
        dependency_type TEXT NOT NULL CHECK(dependency_type IN ('after_ok', 'after_any', 'after_failed')),
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
        FOREIGN KEY (depends_on_job_id) REFERENCES jobs(id) ON DELETE CASCADE,
        UNIQUE(job_id, depends_on_job_id)
    );

    CREATE INDEX IF NOT EXISTS idx_dependencies_job_id ON job_dependencies (job_id);
    CREATE INDEX IF NOT EXISTS idx_dependencies_depends_on ON job_dependencies (depends_on_job_id);
    """

    # Migration to version 3 (Phase 3 - Multi-DFT code support)
    MIGRATION_V2_TO_V3 = """
    -- Add DFT code type column to jobs table
    ALTER TABLE jobs ADD COLUMN dft_code TEXT DEFAULT 'crystal' CHECK(dft_code IN ('crystal', 'quantum_espresso', 'vasp'));
    """

    # Migration to version 4 (Add CANCELLED status to jobs CHECK constraint)
    # SQLite doesn't support ALTER TABLE to modify CHECK constraints,
    # so we must recreate the table with the updated constraint.
    MIGRATION_V3_TO_V4 = """
    -- Step 1: Create new table with updated CHECK constraint
    CREATE TABLE jobs_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        work_dir TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL CHECK(status IN ('PENDING', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        started_at TIMESTAMP,
        completed_at TIMESTAMP,
        pid INTEGER,
        input_file TEXT,
        final_energy REAL,
        key_results TEXT,
        cluster_id INTEGER REFERENCES clusters(id) ON DELETE SET NULL,
        runner_type TEXT DEFAULT 'local' CHECK(runner_type IN ('local', 'ssh', 'slurm')),
        parallelism_config TEXT,
        queue_time TIMESTAMP,
        start_time TIMESTAMP,
        end_time TIMESTAMP,
        dft_code TEXT DEFAULT 'crystal' CHECK(dft_code IN ('crystal', 'quantum_espresso', 'vasp'))
    );

    -- Step 2: Copy data from old table
    INSERT INTO jobs_new SELECT * FROM jobs;

    -- Step 3: Drop old table
    DROP TABLE jobs;

    -- Step 4: Rename new table to original name
    ALTER TABLE jobs_new RENAME TO jobs;

    -- Step 5: Recreate indexes
    CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);
    CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs (created_at DESC);
    """

    # Migration to version 5 (Normalize job results into separate table)
    # This creates a separate job_results table for detailed computation results,
    # normalizing the large key_results JSON out of the main jobs table.
    MIGRATION_V4_TO_V5 = """
    CREATE TABLE IF NOT EXISTS job_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL UNIQUE,
        key_results TEXT,
        convergence_status TEXT,
        scf_cycles INTEGER,
        cpu_time_seconds REAL,
        wall_time_seconds REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_job_results_job_id ON job_results (job_id);

    INSERT OR IGNORE INTO job_results (job_id, key_results, created_at)
    SELECT id, key_results, CURRENT_TIMESTAMP
    FROM jobs
    WHERE key_results IS NOT NULL;
    """

    # Migration to version 6 (Materials database cache tables)
    # These tables cache materials data from external APIs (Materials Project, MPContribs, OPTIMADE)
    MIGRATION_V5_TO_V6 = """
    -- Raw query cache for API responses
    CREATE TABLE IF NOT EXISTS materials_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL CHECK(source IN ('mp', 'mpcontribs', 'optimade')),
        cache_key TEXT NOT NULL,
        query_json TEXT NOT NULL,
        response_json TEXT NOT NULL,
        base_url TEXT,
        etag TEXT,
        fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_materials_cache_key ON materials_cache (source, cache_key);

    -- Canonical structure cache for parsed material structures
    CREATE TABLE IF NOT EXISTS materials_structures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL CHECK(source IN ('mp', 'mpcontribs', 'optimade')),
        material_id TEXT NOT NULL,
        formula TEXT,
        structure_json TEXT NOT NULL,
        cif_text TEXT,
        d12_text TEXT,
        fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_materials_structures_unique ON materials_structures (source, material_id);

    -- MPContribs project data cache
    CREATE TABLE IF NOT EXISTS mpcontribs_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project TEXT NOT NULL,
        contribution_id TEXT,
        material_id TEXT,
        data_json TEXT NOT NULL,
        fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_mpcontribs_project ON mpcontribs_cache (project);
    """

    MIGRATION_V6_TO_V7 = """
        -- Record version
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (7,)
        )
        conn.execute("COMMIT")
    """

    # Migration to version 8 (Add environment paths to clusters)
    MIGRATION_V7_TO_V8 = """
    ALTER TABLE clusters ADD COLUMN cry23_root TEXT;
    ALTER TABLE clusters ADD COLUMN vasp_root TEXT;
    ALTER TABLE clusters ADD COLUMN setup_commands TEXT;
    """

    def __init__(self, db_path: Path, pool_size: int = 4):
        """
        Initialize database with connection pooling for concurrent access.

        Args:
            db_path: Path to SQLite database file
            pool_size: Number of connections in the pool (default: 4)
        """
        self.db_path = db_path
        self.pool_size = pool_size

        # Initialize connection pool
        self._pool: SimpleQueue = SimpleQueue()
        for _ in range(pool_size):
            conn = self._new_conn()
            self._pool.put(conn)

        # Initialize schema using a connection from the pool
        with self.connection() as conn:
            self._initialize_schema(conn)
            self._apply_migrations(conn)

    def _new_conn(self) -> sqlite3.Connection:
        """
        Create a new connection with proper PRAGMA settings for concurrent access.

        Returns:
            Configured SQLite connection
        """
        conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=30.0  # 30 seconds timeout for lock acquisition
        )
        conn.row_factory = sqlite3.Row

        # Configure for concurrent access with WAL mode
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")  # 10 seconds
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA wal_autocheckpoint=1000")  # Checkpoint every 1000 pages
        conn.execute("PRAGMA cache_size=-64000")  # 64MB cache

        return conn

    @contextmanager
    def connection(self):
        """
        Context manager that provides a connection from the pool.

        Usage:
            with self.connection() as conn:
                conn.execute("SELECT ...")

        Yields:
            SQLite connection from the pool
        """
        conn = self._pool.get()
        try:
            yield conn
        finally:
            self._pool.put(conn)

    @property
    def conn(self) -> sqlite3.Connection:
        """
        DEPRECATED: Provides a single shared connection for backward compatibility.

        This property exists for backward compatibility with existing code that
        accesses self.conn directly. New code should use the connection() context
        manager instead for proper connection pooling.

        Returns a connection from the pool and stores it for subsequent access.
        The connection is returned to the pool when close() is called or when
        the object is garbage collected.

        .. deprecated:: 0.2.0
            Use :meth:`connection` context manager instead.
        """
        warnings.warn(
            "Database.conn is deprecated. Use 'with db.connection() as conn:' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if not hasattr(self, '_shared_conn'):
            self._shared_conn = self._pool.get()
        return self._shared_conn

    def _initialize_schema(self, conn: sqlite3.Connection) -> None:
        """Create base schema if database is new."""
        # Check if schema_version table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if not cursor.fetchone():
            # New database - apply base schema atomically
            # Use explicit BEGIN/COMMIT/ROLLBACK for true atomicity
            conn.execute("BEGIN TRANSACTION")
            try:
                # Parse and execute each statement individually
                statements = [
                    stmt.strip() for stmt in self.SCHEMA_V1.split(';')
                    if stmt.strip()
                ]
                for stmt in statements:
                    conn.execute(stmt)
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (1,)
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

    def _apply_migrations(self, conn: sqlite3.Connection) -> None:
        """Apply database migrations to reach current schema version."""
        current_version = self._get_schema_version(conn)

        if current_version < 2:
            self._migrate_v1_to_v2(conn)

        if current_version < 3:
            self._migrate_v2_to_v3(conn)

        if current_version < 4:
            self._migrate_v3_to_v4(conn)

        if current_version < 5:
            self._migrate_v4_to_v5(conn)

        if current_version < 6:
            self._migrate_v5_to_v6(conn)

        if current_version < 7:
            self._migrate_v6_to_v7(conn)

        if current_version < 8:
            self._migrate_v7_to_v8(conn)

    def _get_schema_version(self, conn: sqlite3.Connection) -> int:
        """Get current schema version."""
        try:
            cursor = conn.execute("SELECT MAX(version) FROM schema_version")
            result = cursor.fetchone()
            return result[0] if result[0] else 0
        except sqlite3.OperationalError:
            return 0

    def _migrate_v1_to_v2(self, conn: sqlite3.Connection) -> None:
        """Migrate from version 1 to version 2 atomically."""
        try:
            # Use explicit BEGIN/COMMIT/ROLLBACK for true atomicity
            conn.execute("BEGIN TRANSACTION")
            try:
                # Parse and execute each statement individually
                statements = [
                    stmt.strip() for stmt in self.MIGRATION_V1_TO_V2.split(';')
                    if stmt.strip()
                ]
                for stmt in statements:
                    conn.execute(stmt)
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (2,)
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        except sqlite3.OperationalError as e:
            # Migration may have been partially applied - check and skip if needed
            if "duplicate column name" not in str(e).lower():
                raise

    def _migrate_v2_to_v3(self, conn: sqlite3.Connection) -> None:
        """Migrate from version 2 to version 3 atomically (add dft_code column)."""
        try:
            # Use explicit BEGIN/COMMIT/ROLLBACK for true atomicity
            conn.execute("BEGIN TRANSACTION")
            try:
                # Parse and execute each statement individually
                statements = [
                    stmt.strip() for stmt in self.MIGRATION_V2_TO_V3.split(';')
                    if stmt.strip()
                ]
                for stmt in statements:
                    conn.execute(stmt)
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (3,)
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        except sqlite3.OperationalError as e:
            # Migration may have been partially applied - check and skip if needed
            if "duplicate column name" not in str(e).lower():
                raise

    def _migrate_v3_to_v4(self, conn: sqlite3.Connection) -> None:
        """Migrate from version 3 to version 4 (add CANCELLED to status CHECK constraint).

        SQLite doesn't support modifying CHECK constraints via ALTER TABLE,
        so we must recreate the jobs table with the updated constraint.

        For new databases created with updated SCHEMA_V1 (which already has CANCELLED),
        this migration just records version 4 without modifying the table.
        """
        # For databases created with the new SCHEMA_V1 that already includes CANCELLED,
        # the migration SQL will try to copy data but the table already has the right schema.
        # We need to check if migration is actually needed.
        try:
            # Test if CANCELLED is already allowed in the CHECK constraint
            # by parsing the table schema
            cursor = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='jobs'"
            )
            schema_sql = cursor.fetchone()
            if schema_sql and "'CANCELLED'" in schema_sql[0]:
                # CANCELLED already in schema - just record version 4
                try:
                    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (4,))
                    conn.commit()
                except sqlite3.IntegrityError:
                    pass  # Version already recorded
                return

            # Migration is needed - recreate the table
            conn.execute("BEGIN TRANSACTION")
            try:
                # Parse and execute each statement individually
                statements = [
                    stmt.strip() for stmt in self.MIGRATION_V3_TO_V4.split(';')
                    if stmt.strip() and not stmt.strip().startswith('--')
                ]
                for stmt in statements:
                    conn.execute(stmt)
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (4,)
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        except sqlite3.OperationalError as e:
            # Migration may have been partially applied - check and skip if needed
            if "table jobs_new already exists" in str(e).lower():
                # Clean up partial migration attempt
                try:
                    conn.execute("DROP TABLE IF EXISTS jobs_new")
                except Exception:
                    pass
                raise

    def _migrate_v4_to_v5(self, conn: sqlite3.Connection) -> None:
        """Migrate from version 4 to version 5 (normalize job_results table).

        Creates a separate job_results table for detailed computation results,
        reducing the main jobs table width and improving query performance.
        """
        try:
            # Check if job_results table already exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='job_results'"
            )
            if cursor.fetchone():
                # Table already exists - just record version 5
                try:
                    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (5,))
                    conn.commit()
                except sqlite3.IntegrityError:
                    pass  # Version already recorded
                return

            # Check if key_results column exists in jobs table
            cursor = conn.execute("PRAGMA table_info(jobs)")
            columns = {row[1] for row in cursor.fetchall()}
            has_key_results = 'key_results' in columns

            # Migration is needed - create table and migrate data
            conn.execute("BEGIN TRANSACTION")
            try:
                # Create the job_results table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS job_results (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        job_id INTEGER NOT NULL UNIQUE,
                        key_results TEXT,
                        convergence_status TEXT,
                        scf_cycles INTEGER,
                        cpu_time_seconds REAL,
                        wall_time_seconds REAL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_job_results_job_id ON job_results (job_id)"
                )

                # Only migrate existing data if key_results column exists
                if has_key_results:
                    conn.execute("""
                        INSERT OR IGNORE INTO job_results (job_id, key_results, created_at)
                        SELECT id, key_results, CURRENT_TIMESTAMP
                        FROM jobs
                        WHERE key_results IS NOT NULL
                    """)

                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (5,)
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        except sqlite3.OperationalError as e:
            # Migration may have been partially applied
            if "table job_results already exists" not in str(e).lower():
                raise

    def _migrate_v5_to_v6(self, conn: sqlite3.Connection) -> None:
        """Migrate from version 5 to version 6 (add materials cache tables).

        Creates three tables for caching materials data from external APIs:
        - materials_cache: Raw API query/response cache
        - materials_structures: Parsed structure data cache
        - mpcontribs_cache: MPContribs project data cache
        """
        try:
            # Check if materials_cache table already exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='materials_cache'"
            )
            if cursor.fetchone():
                # Table already exists - just record version 6
                try:
                    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (6,))
                    conn.commit()
                except sqlite3.IntegrityError:
                    pass  # Version already recorded
                return

            # Migration is needed - create tables
            conn.execute("BEGIN TRANSACTION")
            try:
                # Parse and execute each statement individually
                # First remove comment lines, then split by semicolon
                lines = [
                    line for line in self.MIGRATION_V5_TO_V6.split('\n')
                    if not line.strip().startswith('--')
                ]
                sql_no_comments = '\n'.join(lines)
                statements = [
                    stmt.strip() for stmt in sql_no_comments.split(';')
                    if stmt.strip()
                ]
                for stmt in statements:
                    conn.execute(stmt)
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (6,)
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        except sqlite3.OperationalError as e:
            # Migration may have been partially applied
            if "table materials_cache already exists" not in str(e).lower():
                raise

    def _migrate_v6_to_v7(self, conn: sqlite3.Connection) -> None:
        """Migrate from version 6 to version 7 (add TTL to structure/contrib caches).

        Adds expires_at column to materials_structures and mpcontribs_cache tables
        for consistent TTL-based cache invalidation.
        """
        try:
            conn.execute("BEGIN TRANSACTION")
            try:
                # Add expires_at to materials_structures
                conn.execute(
                    "ALTER TABLE materials_structures ADD COLUMN expires_at TEXT"
                )
                # Add expires_at to mpcontribs_cache
                conn.execute(
                    "ALTER TABLE mpcontribs_cache ADD COLUMN expires_at TEXT"
                )
                # Record version
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (7,)
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        except sqlite3.OperationalError as e:
            # Column may already exist from partial migration
            if "duplicate column name" not in str(e).lower():
                raise

    def _migrate_v7_to_v8(self, conn: sqlite3.Connection) -> None:
        """Migrate from version 7 to version 8 (add environment paths to clusters)."""
        try:
            conn.execute("BEGIN TRANSACTION")
            try:
                # Parse and execute each statement individually
                statements = [
                    stmt.strip() for stmt in self.MIGRATION_V7_TO_V8.split(';')
                    if stmt.strip()
                ]
                for stmt in statements:
                    conn.execute(stmt)
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (8,)
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        except sqlite3.OperationalError as e:
            # Migration may have been partially applied
            if "duplicate column name" not in str(e).lower():
                raise

    def get_schema_version(self) -> int:
        """Public method to get current schema version."""
        with self.connection() as conn:
            return self._get_schema_version(conn)

    # ==================== Job Methods (Phase 1 + Extensions) ====================

    def create_job(
        self,
        name: str,
        work_dir: str,
        input_content: str,
        cluster_id: Optional[int] = None,
        runner_type: str = "local",
        parallelism_config: Optional[Dict[str, Any]] = None,
        dft_code: str = "crystal"
    ) -> int:
        """Create a new job entry."""
        parallelism_json = json.dumps(parallelism_config) if parallelism_config else None

        with self.connection() as conn:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO jobs (name, work_dir, status, input_file, cluster_id, runner_type, parallelism_config, dft_code)
                    VALUES (?, ?, 'PENDING', ?, ?, ?, ?, ?)
                    """,
                    (name, work_dir, input_content, cluster_id, runner_type, parallelism_json, dft_code)
                )
                job_id = cursor.lastrowid
                if job_id is None:
                    raise RuntimeError("Failed to create job: lastrowid is None")
                return job_id

    def get_job(self, job_id: int) -> Optional[Job]:
        """Get a job by ID."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()

            if not row:
                return None

            return self._row_to_job(row)

    def get_all_jobs(self) -> List[Job]:
        """Get all jobs ordered by creation date."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC"
            ).fetchall()

            return [self._row_to_job(row) for row in rows]

    def get_job_statuses_batch(self, job_ids: List[int]) -> Dict[int, str]:
        """
        Get statuses for multiple jobs in a single batch query.

        This is the primary optimization for the N+1 query problem in the scheduler.

        Args:
            job_ids: List of job IDs to fetch statuses for

        Returns:
            Dictionary mapping job_id -> status string
        """
        if not job_ids:
            return {}

        with self.connection() as conn:
            # Convert to list if needed (handles sets) and create placeholders
            job_ids_list = list(job_ids)
            placeholders = ','.join('?' * len(job_ids_list))
            cursor = conn.execute(
                f"SELECT id, status FROM jobs WHERE id IN ({placeholders})",
                tuple(job_ids_list)
            )
            return {row[0]: row[1] for row in cursor.fetchall()}

    def job_exists_batch(self, job_ids: List[int]) -> Dict[int, bool]:
        """
        Check if multiple jobs exist in a single batch query.

        Optimizes the N+1 query pattern when validating job dependencies.

        Args:
            job_ids: List of job IDs to check

        Returns:
            Dictionary mapping job_id -> True if exists, False otherwise
        """
        if not job_ids:
            return {}

        with self.connection() as conn:
            # Create placeholders for parameterized query
            placeholders = ','.join('?' * len(job_ids))
            cursor = conn.execute(
                f"SELECT id FROM jobs WHERE id IN ({placeholders})",
                job_ids
            )
            existing_ids = {row[0] for row in cursor.fetchall()}

            # Return dict with True for existing jobs, False for non-existent
            return {job_id: job_id in existing_ids for job_id in job_ids}

    def get_jobs_by_cluster(self, cluster_id: int) -> List[Job]:
        """Get all jobs for a specific cluster."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE cluster_id = ? ORDER BY created_at DESC",
                (cluster_id,)
            ).fetchall()

            return [self._row_to_job(row) for row in rows]

    def get_jobs_by_status(self, status: str) -> List[Job]:
        """Get all jobs with a specific status."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC",
                (status,)
            ).fetchall()

            return [self._row_to_job(row) for row in rows]

    def update_status(
        self,
        job_id: int,
        status: str,
        pid: Optional[int] = None
    ) -> None:
        """Update job status and optionally PID."""
        timestamp_field = None
        if status == "RUNNING":
            timestamp_field = "started_at"
        elif status in ("COMPLETED", "FAILED", "CANCELLED"):
            timestamp_field = "completed_at"

        with self.connection() as conn:
            with conn:
                if timestamp_field:
                    conn.execute(
                        f"""
                        UPDATE jobs
                        SET status = ?, pid = ?, {timestamp_field} = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (status, pid, job_id)
                    )
                else:
                    conn.execute(
                        "UPDATE jobs SET status = ?, pid = ? WHERE id = ?",
                        (status, pid, job_id)
                    )

    def update_results(
        self,
        job_id: int,
        final_energy: Optional[float] = None,
        key_results: Optional[Dict[str, Any]] = None
    ) -> None:
        """Update job results after completion."""
        results_json = json.dumps(key_results) if key_results else None
        with self.connection() as conn:
            with conn:
                conn.execute(
                    """
                    UPDATE jobs
                    SET final_energy = ?, key_results = ?
                    WHERE id = ?
                    """,
                    (final_energy, results_json, job_id)
                )

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        """Convert database row to Job object."""
        key_results = None
        if row["key_results"]:
            key_results = json.loads(row["key_results"])

        parallelism_config = None
        if "parallelism_config" in row.keys() and row["parallelism_config"]:
            parallelism_config = json.loads(row["parallelism_config"])

        # Handle Phase 2 columns with backward compatibility
        # sqlite3.Row doesn't have .get(), so we check column existence
        def safe_get(col_name, default=None):
            try:
                return row[col_name] if col_name in row.keys() else default
            except IndexError:
                return default

        return Job(
            id=row["id"],
            name=row["name"],
            work_dir=row["work_dir"],
            status=row["status"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            pid=row["pid"],
            input_file=row["input_file"],
            final_energy=row["final_energy"],
            key_results=key_results,
            cluster_id=safe_get("cluster_id"),
            runner_type=safe_get("runner_type", "local"),
            parallelism_config=parallelism_config,
            queue_time=safe_get("queue_time"),
            start_time=safe_get("start_time"),
            end_time=safe_get("end_time"),
            dft_code=safe_get("dft_code", "crystal")
        )

    # ==================== Cluster Methods (Phase 2) ====================

    def create_cluster(
        self,
        name: str,
        type: str,
        hostname: str,
        username: str,
        port: int = 22,
        connection_config: Optional[Dict[str, Any]] = None,
        cry23_root: Optional[str] = None,
        vasp_root: Optional[str] = None,
        setup_commands: Optional[List[str]] = None
    ) -> int:
        """Create a new cluster configuration."""
        config_json = json.dumps(connection_config or {})
        setup_json = json.dumps(setup_commands or [])

        with self.connection() as conn:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO clusters (name, type, hostname, port, username, connection_config,
                                         cry23_root, vasp_root, setup_commands)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (name, type, hostname, port, username, config_json, cry23_root, vasp_root, setup_json)
                )
                cluster_id = cursor.lastrowid
                if cluster_id is None:
                    raise RuntimeError("Failed to create cluster: lastrowid is None")
                return cluster_id

    def get_cluster(self, cluster_id: int) -> Optional[Cluster]:
        """Get a cluster by ID."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM clusters WHERE id = ?", (cluster_id,)
            ).fetchone()

            if not row:
                return None

            return self._row_to_cluster(row)

    def get_cluster_by_name(self, name: str) -> Optional[Cluster]:
        """Get a cluster by name."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM clusters WHERE name = ?", (name,)
            ).fetchone()

            if not row:
                return None

            return self._row_to_cluster(row)

    def get_all_clusters(self) -> List[Cluster]:
        """Get all clusters ordered by name."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM clusters ORDER BY name"
            ).fetchall()

            return [self._row_to_cluster(row) for row in rows]

    def get_active_clusters(self) -> List[Cluster]:
        """Get all active clusters."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM clusters WHERE status = 'active' ORDER BY name"
            ).fetchall()

            return [self._row_to_cluster(row) for row in rows]

    def update_cluster(
        self,
        cluster_id: int,
        name: Optional[str] = None,
        hostname: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        connection_config: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
        cry23_root: Optional[str] = None,
        vasp_root: Optional[str] = None,
        setup_commands: Optional[List[str]] = None
    ) -> None:
        """Update cluster configuration."""
        updates = []
        params = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if hostname is not None:
            updates.append("hostname = ?")
            params.append(hostname)
        if port is not None:
            updates.append("port = ?")
            params.append(port)
        if username is not None:
            updates.append("username = ?")
            params.append(username)
        if connection_config is not None:
            updates.append("connection_config = ?")
            params.append(json.dumps(connection_config))
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if cry23_root is not None:
            updates.append("cry23_root = ?")
            params.append(cry23_root)
        if vasp_root is not None:
            updates.append("vasp_root = ?")
            params.append(vasp_root)
        if setup_commands is not None:
            updates.append("setup_commands = ?")
            params.append(json.dumps(setup_commands))

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(cluster_id)

            with self.connection() as conn:
                with conn:
                    query = f"UPDATE clusters SET {', '.join(updates)} WHERE id = ?"
                    conn.execute(query, params)

    def delete_cluster(self, cluster_id: int) -> None:
        """Delete a cluster configuration."""
        with self.connection() as conn:
            with conn:
                conn.execute("DELETE FROM clusters WHERE id = ?", (cluster_id,))

    def _row_to_cluster(self, row: sqlite3.Row) -> Cluster:
        """Convert database row to Cluster object."""
        connection_config = json.loads(row["connection_config"])

        setup_commands = None
        if "setup_commands" in row.keys() and row["setup_commands"]:
            try:
                setup_commands = json.loads(row["setup_commands"])
            except json.JSONDecodeError:
                setup_commands = []

        def safe_get(col_name, default=None):
            try:
                return row[col_name] if col_name in row.keys() else default
            except IndexError:
                return default

        return Cluster(
            id=row["id"],
            name=row["name"],
            type=row["type"],
            hostname=row["hostname"],
            port=row["port"],
            username=row["username"],
            connection_config=connection_config,
            status=row["status"],
            cry23_root=safe_get("cry23_root"),
            vasp_root=safe_get("vasp_root"),
            setup_commands=setup_commands,
            created_at=row["created_at"],
            updated_at=row["updated_at"]
        )

    # ==================== Remote Job Methods (Phase 2) ====================

    def create_remote_job(
        self,
        job_id: int,
        cluster_id: int,
        remote_handle: str,
        working_directory: str,
        queue_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """Create a remote job tracking entry."""
        metadata_json = json.dumps(metadata or {})

        with self.connection() as conn:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO remote_jobs (job_id, cluster_id, remote_handle, working_directory,
                                            queue_name, metadata, submission_time)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (job_id, cluster_id, remote_handle, working_directory, queue_name, metadata_json)
                )
                remote_job_id = cursor.lastrowid
                if remote_job_id is None:
                    raise RuntimeError("Failed to create remote job: lastrowid is None")
                return remote_job_id

    def get_remote_job(self, remote_job_id: int) -> Optional[RemoteJob]:
        """Get a remote job by ID."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM remote_jobs WHERE id = ?", (remote_job_id,)
            ).fetchone()

            if not row:
                return None

            return self._row_to_remote_job(row)

    def get_remote_job_by_job_id(self, job_id: int) -> Optional[RemoteJob]:
        """Get a remote job by job ID."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM remote_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()

            if not row:
                return None

            return self._row_to_remote_job(row)

    def update_remote_job(
        self,
        remote_job_id: int,
        node_list: Optional[str] = None,
        stdout_path: Optional[str] = None,
        stderr_path: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Update remote job details."""
        updates = []
        params = []

        if node_list is not None:
            updates.append("node_list = ?")
            params.append(node_list)
        if stdout_path is not None:
            updates.append("stdout_path = ?")
            params.append(stdout_path)
        if stderr_path is not None:
            updates.append("stderr_path = ?")
            params.append(stderr_path)
        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(metadata))

        if updates:
            params.append(remote_job_id)
            with self.connection() as conn:
                with conn:
                    query = f"UPDATE remote_jobs SET {', '.join(updates)} WHERE id = ?"
                    conn.execute(query, params)

    def _row_to_remote_job(self, row: sqlite3.Row) -> RemoteJob:
        """Convert database row to RemoteJob object."""
        metadata = None
        if row["metadata"]:
            metadata = json.loads(row["metadata"])

        return RemoteJob(
            id=row["id"],
            job_id=row["job_id"],
            cluster_id=row["cluster_id"],
            remote_handle=row["remote_handle"],
            submission_time=row["submission_time"],
            queue_name=row["queue_name"],
            node_list=row["node_list"],
            working_directory=row["working_directory"],
            stdout_path=row["stdout_path"],
            stderr_path=row["stderr_path"],
            metadata=metadata
        )

    # ==================== Job Dependency Methods (Phase 2) ====================

    def add_job_dependency(
        self,
        job_id: int,
        depends_on_job_id: int,
        dependency_type: str = "after_ok"
    ) -> int:
        """Add a dependency between two jobs."""
        with self.connection() as conn:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO job_dependencies (job_id, depends_on_job_id, dependency_type)
                    VALUES (?, ?, ?)
                    """,
                    (job_id, depends_on_job_id, dependency_type)
                )
                dep_id = cursor.lastrowid
                if dep_id is None:
                    raise RuntimeError("Failed to create job dependency: lastrowid is None")
                return dep_id

    def get_job_dependencies(self, job_id: int) -> List[JobDependency]:
        """Get all dependencies for a job."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM job_dependencies WHERE job_id = ?", (job_id,)
            ).fetchall()

            return [self._row_to_job_dependency(row) for row in rows]

    def get_dependent_jobs(self, job_id: int) -> List[JobDependency]:
        """Get all jobs that depend on this job."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM job_dependencies WHERE depends_on_job_id = ?", (job_id,)
            ).fetchall()

            return [self._row_to_job_dependency(row) for row in rows]

    def remove_job_dependency(self, dependency_id: int) -> None:
        """Remove a job dependency."""
        with self.connection() as conn:
            with conn:
                conn.execute("DELETE FROM job_dependencies WHERE id = ?", (dependency_id,))

    def can_job_run(self, job_id: int) -> Tuple[bool, List[str]]:
        """
        Check if a job can run based on its dependencies.

        Returns:
            Tuple of (can_run: bool, blocking_reasons: List[str])
        """
        dependencies = self.get_job_dependencies(job_id)
        if not dependencies:
            return True, []

        blocking_reasons = []

        for dep in dependencies:
            parent_job = self.get_job(dep.depends_on_job_id)
            if not parent_job:
                blocking_reasons.append(f"Dependency job {dep.depends_on_job_id} not found")
                continue

            if dep.dependency_type == "after_ok":
                if parent_job.status != "COMPLETED":
                    blocking_reasons.append(
                        f"Waiting for job '{parent_job.name}' to complete successfully"
                    )
            elif dep.dependency_type == "after_any":
                if parent_job.status not in ("COMPLETED", "FAILED"):
                    blocking_reasons.append(
                        f"Waiting for job '{parent_job.name}' to finish"
                    )
            elif dep.dependency_type == "after_failed":
                if parent_job.status != "FAILED":
                    blocking_reasons.append(
                        f"Waiting for job '{parent_job.name}' to fail"
                    )

        return len(blocking_reasons) == 0, blocking_reasons

    def _row_to_job_dependency(self, row: sqlite3.Row) -> JobDependency:
        """Convert database row to JobDependency object."""
        return JobDependency(
            id=row["id"],
            job_id=row["job_id"],
            depends_on_job_id=row["depends_on_job_id"],
            dependency_type=row["dependency_type"]
        )

    # ==================== Job Results Methods (Phase 5 - Normalized) ====================

    def save_job_result(
        self,
        job_id: int,
        key_results: Optional[Dict[str, Any]] = None,
        convergence_status: Optional[str] = None,
        scf_cycles: Optional[int] = None,
        cpu_time_seconds: Optional[float] = None,
        wall_time_seconds: Optional[float] = None
    ) -> int:
        """
        Save detailed job results to normalized job_results table.

        Also updates the legacy key_results column in jobs table for backward compatibility.
        """
        results_json = json.dumps(key_results) if key_results else None

        with self.connection() as conn:
            with conn:
                # Upsert into job_results table
                cursor = conn.execute(
                    """
                    INSERT INTO job_results (job_id, key_results, convergence_status,
                                            scf_cycles, cpu_time_seconds, wall_time_seconds)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id) DO UPDATE SET
                        key_results = excluded.key_results,
                        convergence_status = excluded.convergence_status,
                        scf_cycles = excluded.scf_cycles,
                        cpu_time_seconds = excluded.cpu_time_seconds,
                        wall_time_seconds = excluded.wall_time_seconds
                    """,
                    (job_id, results_json, convergence_status, scf_cycles,
                     cpu_time_seconds, wall_time_seconds)
                )

                # Also update legacy column for backward compatibility
                conn.execute(
                    "UPDATE jobs SET key_results = ? WHERE id = ?",
                    (results_json, job_id)
                )

                result_id = cursor.lastrowid
                if result_id is None:
                    # Upsert updated existing row, get the ID
                    row = conn.execute(
                        "SELECT id FROM job_results WHERE job_id = ?", (job_id,)
                    ).fetchone()
                    result_id = row[0] if row else 0
                return result_id

    def get_job_result(self, job_id: int) -> Optional[JobResult]:
        """Get detailed job results from normalized table."""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM job_results WHERE job_id = ?", (job_id,)
            ).fetchone()

            if not row:
                return None

            return self._row_to_job_result(row)

    def get_job_with_results(self, job_id: int) -> Optional[Tuple[Job, Optional[JobResult]]]:
        """
        Get a job with its detailed results in a single operation.

        Returns:
            Tuple of (Job, JobResult) or None if job doesn't exist
        """
        job = self.get_job(job_id)
        if not job:
            return None

        result = self.get_job_result(job_id)
        return (job, result)

    def _row_to_job_result(self, row: sqlite3.Row) -> JobResult:
        """Convert database row to JobResult object."""
        key_results = None
        if row["key_results"]:
            key_results = json.loads(row["key_results"])

        return JobResult(
            id=row["id"],
            job_id=row["job_id"],
            key_results=key_results,
            convergence_status=row["convergence_status"],
            scf_cycles=row["scf_cycles"],
            cpu_time_seconds=row["cpu_time_seconds"],
            wall_time_seconds=row["wall_time_seconds"],
            created_at=row["created_at"]
        )

    # ==================== Utility Methods ====================

    def close(self) -> None:
        """Close all database connections in the pool."""
        # Return shared connection to pool if it exists
        if hasattr(self, '_shared_conn'):
            self._pool.put(self._shared_conn)
            delattr(self, '_shared_conn')

        # Close all connections in the pool
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except Exception:
                # Pool is empty, we're done
                break
