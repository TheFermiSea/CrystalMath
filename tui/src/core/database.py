"""
SQLite database interface for job history and state management.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


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


class Database:
    """Manages the SQLite database for a CRYSTAL-TUI project."""

    SCHEMA = """
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
    """

    def __init__(self, db_path: Path):
        """Initialize database connection."""
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        """Create tables if they don't exist."""
        self.conn.executescript(self.SCHEMA)
        self.conn.commit()

    def create_job(self, name: str, work_dir: str, input_content: str) -> int:
        """Create a new job entry."""
        cursor = self.conn.execute(
            """
            INSERT INTO jobs (name, work_dir, status, input_file)
            VALUES (?, ?, 'PENDING', ?)
            """,
            (name, work_dir, input_content)
        )
        self.conn.commit()
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
        self.conn.commit()

    def update_results(
        self,
        job_id: int,
        final_energy: Optional[float] = None,
        key_results: Optional[Dict[str, Any]] = None
    ) -> None:
        """Update job results after completion."""
        results_json = json.dumps(key_results) if key_results else None
        self.conn.execute(
            """
            UPDATE jobs
            SET final_energy = ?, key_results = ?
            WHERE id = ?
            """,
            (final_energy, results_json, job_id)
        )
        self.conn.commit()

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        """Convert database row to Job object."""
        key_results = None
        if row["key_results"]:
            key_results = json.loads(row["key_results"])

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
            key_results=key_results
        )

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()
