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
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum


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
    """Represents a CRYSTAL calculation job."""
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


class Database:
    """Manages the SQLite database for a CRYSTAL-TUI project."""

    # Schema version for migrations
    SCHEMA_VERSION = 2

    # Base schema (version 1 - Phase 1)
    SCHEMA_V1 = """
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        work_dir TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL CHECK(status IN ('PENDING', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED')),
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

    def __init__(self, db_path: Path):
        """Initialize database connection and apply migrations."""
        self.db_path = db_path
        # Allow check_same_thread=False for async/threaded use
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5.0)
        self.conn.row_factory = sqlite3.Row

        # Configure for concurrent access
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")  # 5 seconds
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

        self._initialize_schema()
        self._apply_migrations()

    def _initialize_schema(self) -> None:
        """Create base schema if database is new."""
        # Check if schema_version table exists
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if not cursor.fetchone():
            # New database - apply base schema
            with self.conn:
                self.conn.executescript(self.SCHEMA_V1)
                self.conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (1,)
                )

    def _apply_migrations(self) -> None:
        """Apply database migrations to reach current schema version."""
        current_version = self._get_schema_version()

        if current_version < 2:
            self._migrate_v1_to_v2()

    def _get_schema_version(self) -> int:
        """Get current schema version."""
        try:
            cursor = self.conn.execute("SELECT MAX(version) FROM schema_version")
            result = cursor.fetchone()
            return result[0] if result[0] else 0
        except sqlite3.OperationalError:
            return 0

    def _migrate_v1_to_v2(self) -> None:
        """Migrate from version 1 to version 2."""
        try:
            with self.conn:
                self.conn.executescript(self.MIGRATION_V1_TO_V2)
                self.conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (2,)
                )
        except sqlite3.OperationalError as e:
            # Migration may have been partially applied - check and skip if needed
            if "duplicate column name" not in str(e).lower():
                raise

    def get_schema_version(self) -> int:
        """Public method to get current schema version."""
        return self._get_schema_version()

    # ==================== Job Methods (Phase 1 + Extensions) ====================

    def create_job(
        self,
        name: str,
        work_dir: str,
        input_content: str,
        cluster_id: Optional[int] = None,
        runner_type: str = "local",
        parallelism_config: Optional[Dict[str, Any]] = None
    ) -> int:
        """Create a new job entry."""
        parallelism_json = json.dumps(parallelism_config) if parallelism_config else None

        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO jobs (name, work_dir, status, input_file, cluster_id, runner_type, parallelism_config)
                VALUES (?, ?, 'PENDING', ?, ?, ?, ?)
                """,
                (name, work_dir, input_content, cluster_id, runner_type, parallelism_json)
            )
            job_id = cursor.lastrowid
            if job_id is None:
                raise RuntimeError("Failed to create job: lastrowid is None")
            return job_id

    def get_job(self, job_id: int) -> Optional[Job]:
        """Get a job by ID."""
        row = self.conn.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()

        if not row:
            return None

        return self._row_to_job(row)

    def get_all_jobs(self) -> List[Job]:
        """Get all jobs ordered by creation date."""
        rows = self.conn.execute(
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

        # Create placeholders for parameterized query
        placeholders = ','.join('?' * len(job_ids))
        cursor = self.conn.execute(
            f"SELECT id, status FROM jobs WHERE id IN ({placeholders})",
            job_ids
        )
        return {row[0]: row[1] for row in cursor.fetchall()}

    def get_jobs_by_cluster(self, cluster_id: int) -> List[Job]:
        """Get all jobs for a specific cluster."""
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE cluster_id = ? ORDER BY created_at DESC",
            (cluster_id,)
        ).fetchall()

        return [self._row_to_job(row) for row in rows]

    def get_jobs_by_status(self, status: str) -> List[Job]:
        """Get all jobs with a specific status."""
        rows = self.conn.execute(
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
        elif status in ("COMPLETED", "FAILED"):
            timestamp_field = "completed_at"

        with self.conn:
            if timestamp_field:
                self.conn.execute(
                    f"""
                    UPDATE jobs
                    SET status = ?, pid = ?, {timestamp_field} = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (status, pid, job_id)
                )
            else:
                self.conn.execute(
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
        with self.conn:
            self.conn.execute(
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
            end_time=safe_get("end_time")
        )

    # ==================== Cluster Methods (Phase 2) ====================

    def create_cluster(
        self,
        name: str,
        type: str,
        hostname: str,
        username: str,
        port: int = 22,
        connection_config: Optional[Dict[str, Any]] = None
    ) -> int:
        """Create a new cluster configuration."""
        config_json = json.dumps(connection_config or {})

        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO clusters (name, type, hostname, port, username, connection_config)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, type, hostname, port, username, config_json)
            )
            cluster_id = cursor.lastrowid
            if cluster_id is None:
                raise RuntimeError("Failed to create cluster: lastrowid is None")
            return cluster_id

    def get_cluster(self, cluster_id: int) -> Optional[Cluster]:
        """Get a cluster by ID."""
        row = self.conn.execute(
            "SELECT * FROM clusters WHERE id = ?", (cluster_id,)
        ).fetchone()

        if not row:
            return None

        return self._row_to_cluster(row)

    def get_cluster_by_name(self, name: str) -> Optional[Cluster]:
        """Get a cluster by name."""
        row = self.conn.execute(
            "SELECT * FROM clusters WHERE name = ?", (name,)
        ).fetchone()

        if not row:
            return None

        return self._row_to_cluster(row)

    def get_all_clusters(self) -> List[Cluster]:
        """Get all clusters ordered by name."""
        rows = self.conn.execute(
            "SELECT * FROM clusters ORDER BY name"
        ).fetchall()

        return [self._row_to_cluster(row) for row in rows]

    def get_active_clusters(self) -> List[Cluster]:
        """Get all active clusters."""
        rows = self.conn.execute(
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
        status: Optional[str] = None
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

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(cluster_id)

            with self.conn:
                query = f"UPDATE clusters SET {', '.join(updates)} WHERE id = ?"
                self.conn.execute(query, params)

    def delete_cluster(self, cluster_id: int) -> None:
        """Delete a cluster configuration."""
        with self.conn:
            self.conn.execute("DELETE FROM clusters WHERE id = ?", (cluster_id,))

    def _row_to_cluster(self, row: sqlite3.Row) -> Cluster:
        """Convert database row to Cluster object."""
        connection_config = json.loads(row["connection_config"])

        return Cluster(
            id=row["id"],
            name=row["name"],
            type=row["type"],
            hostname=row["hostname"],
            port=row["port"],
            username=row["username"],
            connection_config=connection_config,
            status=row["status"],
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

        with self.conn:
            cursor = self.conn.execute(
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
        row = self.conn.execute(
            "SELECT * FROM remote_jobs WHERE id = ?", (remote_job_id,)
        ).fetchone()

        if not row:
            return None

        return self._row_to_remote_job(row)

    def get_remote_job_by_job_id(self, job_id: int) -> Optional[RemoteJob]:
        """Get a remote job by job ID."""
        row = self.conn.execute(
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
            with self.conn:
                query = f"UPDATE remote_jobs SET {', '.join(updates)} WHERE id = ?"
                self.conn.execute(query, params)

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
        with self.conn:
            cursor = self.conn.execute(
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
        rows = self.conn.execute(
            "SELECT * FROM job_dependencies WHERE job_id = ?", (job_id,)
        ).fetchall()

        return [self._row_to_job_dependency(row) for row in rows]

    def get_dependent_jobs(self, job_id: int) -> List[JobDependency]:
        """Get all jobs that depend on this job."""
        rows = self.conn.execute(
            "SELECT * FROM job_dependencies WHERE depends_on_job_id = ?", (job_id,)
        ).fetchall()

        return [self._row_to_job_dependency(row) for row in rows]

    def remove_job_dependency(self, dependency_id: int) -> None:
        """Remove a job dependency."""
        with self.conn:
            self.conn.execute("DELETE FROM job_dependencies WHERE id = ?", (dependency_id,))

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

    # ==================== Utility Methods ====================

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()
