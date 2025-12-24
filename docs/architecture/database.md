# Database Migration Guide

This document describes the database schema evolution for the CRYSTAL-TUI project and provides guidance for migrating existing databases.

## Overview

The CRYSTAL-TUI database schema has evolved through the following versions:

- **Version 1 (Phase 1)**: Local job execution only
- **Version 2 (Phase 2)**: Remote execution with clusters, job dependencies, and workflows

All migrations are **automatic** and **backward compatible**. Existing Phase 1 databases will be upgraded seamlessly when opened with Phase 2 code.

## Schema Version 1 (Phase 1)

Phase 1 schema supports local job execution with the following structure:

### Tables

**jobs**
- `id` - Primary key
- `name` - Job name
- `work_dir` - Working directory (unique)
- `status` - Job status (PENDING, QUEUED, RUNNING, COMPLETED, FAILED)
- `created_at` - Creation timestamp
- `started_at` - Start timestamp
- `completed_at` - Completion timestamp
- `pid` - Process ID
- `input_file` - Input file content
- `final_energy` - Final energy result
- `key_results` - JSON results dictionary

**schema_version**
- `version` - Schema version number
- `applied_at` - Migration timestamp

### Indexes
- `idx_jobs_status` - Index on status field
- `idx_jobs_created` - Index on created_at (descending)

## Schema Version 2 (Phase 2)

Phase 2 extends the schema with remote execution capabilities:

### New Columns in jobs Table

- `cluster_id` - Foreign key to clusters table (nullable)
- `runner_type` - Execution backend: 'local', 'ssh', or 'slurm' (default: 'local')
- `parallelism_config` - JSON config for MPI ranks, threads, nodes
- `queue_time` - Time job was queued (for SLURM)
- `start_time` - Actual start time on remote system
- `end_time` - Actual end time on remote system

### New Tables

**clusters**
```sql
CREATE TABLE clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK(type IN ('ssh', 'slurm')),
    hostname TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 22,
    username TEXT NOT NULL,
    connection_config TEXT NOT NULL,  -- JSON
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'inactive', 'error')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**remote_jobs**
```sql
CREATE TABLE remote_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    cluster_id INTEGER NOT NULL,
    remote_handle TEXT NOT NULL,  -- PID for SSH, job ID for SLURM
    submission_time TIMESTAMP,
    queue_name TEXT,
    node_list TEXT,
    working_directory TEXT NOT NULL,
    stdout_path TEXT,
    stderr_path TEXT,
    metadata TEXT,  -- JSON
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE CASCADE
);
```

**job_dependencies**
```sql
CREATE TABLE job_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    depends_on_job_id INTEGER NOT NULL,
    dependency_type TEXT NOT NULL CHECK(dependency_type IN ('after_ok', 'after_any', 'after_failed')),
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on_job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    UNIQUE(job_id, depends_on_job_id)
);
```

### New Indexes

- `idx_clusters_status` - Index on cluster status
- `idx_clusters_type` - Index on cluster type
- `idx_remote_jobs_job_id` - Index on job_id
- `idx_remote_jobs_cluster_id` - Index on cluster_id
- `idx_remote_jobs_handle` - Index on remote_handle
- `idx_dependencies_job_id` - Index on job_id
- `idx_dependencies_depends_on` - Index on depends_on_job_id

## Migration Process

### Automatic Migration

When you open a Phase 1 database with Phase 2 code, the migration happens automatically:

```python
from src.core.database import Database
from pathlib import Path

# Open existing Phase 1 database
db = Database(Path("my_project/.crystal-tui.db"))

# Migration happens automatically on __init__
# Check version
print(f"Database version: {db.get_schema_version()}")  # Output: 2
```

### Migration Steps

The migration performs the following operations:

1. **Add new columns to jobs table**
   - Adds `cluster_id`, `runner_type`, `parallelism_config`, etc.
   - Sets default values for existing rows

2. **Create new tables**
   - Creates `clusters`, `remote_jobs`, `job_dependencies` tables
   - Creates all indexes

3. **Update schema_version table**
   - Inserts version 2 record

4. **Enable foreign key constraints**
   - Ensures referential integrity

### Rollback Safety

The migration is designed to be safe:

- **Idempotent**: Can be run multiple times without errors
- **Non-destructive**: Never deletes or modifies existing data
- **Partial recovery**: If migration fails partway, it can detect and skip completed steps

### Data Preservation

All existing Phase 1 data is preserved:

- **Jobs**: All job records remain intact
- **Status**: Job statuses and timestamps unchanged
- **Results**: Energy and key_results data preserved
- **Indexes**: Original indexes maintained

New fields are set to sensible defaults:
- `runner_type` defaults to 'local'
- `cluster_id` defaults to NULL
- Other new fields default to NULL

## Backward Compatibility

### Code Compatibility

Phase 1 code patterns continue to work:

```python
# Phase 1 style - still works
job_id = db.create_job(
    name="my_job",
    work_dir="/calculations/my_job",
    input_content="CRYSTAL\nEND\n"
)

# Job has default values for Phase 2 fields
job = db.get_job(job_id)
assert job.runner_type == "local"
assert job.cluster_id is None
```

### Query Compatibility

Phase 1 queries work unchanged:

```python
# Get all jobs (works with v1 and v2 databases)
all_jobs = db.get_all_jobs()

# Get jobs by status (works with v1 and v2 databases)
running_jobs = db.get_jobs_by_status("RUNNING")

# Update status (works with v1 and v2 databases)
db.update_status(job_id, "COMPLETED")
```

## Using Phase 2 Features

### Creating Remote Jobs

```python
# Create a cluster configuration
cluster_id = db.create_cluster(
    name="hpc_cluster",
    type="slurm",
    hostname="hpc.example.com",
    username="myuser",
    port=22,
    connection_config={
        "key_file": "/home/myuser/.ssh/id_rsa",
        "partition": "gpu",
        "qos": "high"
    }
)

# Create a job with cluster assignment
job_id = db.create_job(
    name="remote_job",
    work_dir="/scratch/calculations/job001",
    input_content="CRYSTAL\nEND\n",
    cluster_id=cluster_id,
    runner_type="slurm",
    parallelism_config={
        "mpi_ranks": 64,
        "threads_per_rank": 4,
        "nodes": 4
    }
)

# Track remote execution details
remote_job_id = db.create_remote_job(
    job_id=job_id,
    cluster_id=cluster_id,
    remote_handle="12345678",  # SLURM job ID
    working_directory="/scratch/user/job001",
    queue_name="gpu",
    metadata={
        "partition": "gpu",
        "time_limit": "24:00:00",
        "account": "research_group"
    }
)
```

### Creating Job Dependencies

```python
# Create a workflow: job1 -> job2 -> job3
job1_id = db.create_job("prep", "/tmp/prep", "input1")
job2_id = db.create_job("compute", "/tmp/compute", "input2")
job3_id = db.create_job("analysis", "/tmp/analysis", "input3")

# Set up dependencies
db.add_job_dependency(job2_id, job1_id, "after_ok")  # job2 after job1 succeeds
db.add_job_dependency(job3_id, job2_id, "after_ok")  # job3 after job2 succeeds

# Check if a job can run
can_run, reasons = db.can_job_run(job2_id)
if not can_run:
    print(f"Job blocked: {reasons}")
```

## Testing Migrations

### Unit Tests

The test suite includes comprehensive migration tests:

```bash
cd tui
pytest tests/test_database_remote.py::TestSchemaMigration -v
```

Tests verify:
- New databases start at version 2
- Version 1 databases migrate to version 2
- Migration preserves existing data
- Foreign keys are enforced

### Manual Testing

Create a test database and verify migration:

```python
import tempfile
from pathlib import Path
from src.core.database import Database

# Create a Phase 1 database manually
db_path = Path(tempfile.mktemp(suffix=".db"))
db = Database(db_path)

# Add some Phase 1 data
job_id = db.create_job("test", "/tmp/test", "input")
db.update_status(job_id, "COMPLETED")
db.close()

# Reopen - should auto-migrate
db = Database(db_path)
assert db.get_schema_version() == 2

# Verify Phase 1 data preserved
job = db.get_job(job_id)
assert job.name == "test"
assert job.status == "COMPLETED"
assert job.runner_type == "local"  # New field with default value

db.close()
db_path.unlink()
```

## Troubleshooting

### Migration Fails with "duplicate column name"

This error occurs if the migration is run multiple times. The migration system detects this and skips already-applied steps. This is safe and expected.

### Foreign Key Constraint Violations

If you see foreign key errors:

1. Check that foreign keys are enabled:
   ```python
   result = db.conn.execute("PRAGMA foreign_keys").fetchone()
   print(f"Foreign keys: {result[0]}")  # Should be 1
   ```

2. Verify cluster exists before assigning to job:
   ```python
   cluster = db.get_cluster(cluster_id)
   if cluster is None:
       print(f"Cluster {cluster_id} not found")
   ```

### Performance Issues After Migration

If queries are slow after migration:

1. Verify indexes were created:
   ```python
   cursor = db.conn.execute(
       "SELECT name FROM sqlite_master WHERE type='index'"
   )
   indexes = [row[0] for row in cursor.fetchall()]
   print(f"Indexes: {indexes}")
   ```

2. Run ANALYZE to update statistics:
   ```python
   db.conn.execute("ANALYZE")
   db.conn.commit()
   ```

## Best Practices

### When Creating New Jobs

1. **Use default runner_type for local jobs**:
   ```python
   # Implicit local execution
   job_id = db.create_job(name="local", work_dir="/tmp/local", input_content="input")
   ```

2. **Specify cluster for remote jobs**:
   ```python
   # Explicit remote execution
   job_id = db.create_job(
       name="remote",
       work_dir="/tmp/remote",
       input_content="input",
       cluster_id=cluster_id,
       runner_type="ssh"
   )
   ```

3. **Include parallelism config for parallel jobs**:
   ```python
   job_id = db.create_job(
       name="parallel",
       work_dir="/tmp/parallel",
       input_content="input",
       parallelism_config={"mpi_ranks": 16, "threads_per_rank": 4}
   )
   ```

### When Managing Clusters

1. **Mark inactive clusters**:
   ```python
   db.update_cluster(cluster_id, status="inactive")
   ```

2. **Store connection details securely**:
   ```python
   connection_config = {
       "key_file": "/secure/path/to/key",  # Not password!
       "timeout": 30
   }
   ```

3. **Clean up unused clusters**:
   ```python
   # Check for jobs on cluster before deleting
   jobs = db.get_jobs_by_cluster(cluster_id)
   if not jobs:
       db.delete_cluster(cluster_id)
   ```

### When Building Workflows

1. **Check dependencies before submission**:
   ```python
   can_run, reasons = db.can_job_run(job_id)
   if can_run:
       # Submit job
       pass
   else:
       print(f"Waiting: {reasons}")
   ```

2. **Use appropriate dependency types**:
   - `after_ok`: Most common, run after success
   - `after_any`: Run after completion (success or failure)
   - `after_failed`: Conditional execution for error handling

3. **Query dependency graph**:
   ```python
   # What does this job depend on?
   dependencies = db.get_job_dependencies(job_id)

   # What depends on this job?
   dependents = db.get_dependent_jobs(job_id)
   ```

## Future Migrations

When adding future schema versions:

1. **Increment SCHEMA_VERSION**:
   ```python
   SCHEMA_VERSION = 3
   ```

2. **Add migration SQL**:
   ```python
   MIGRATION_V2_TO_V3 = """
   ALTER TABLE jobs ADD COLUMN new_field TEXT;
   -- Other changes...
   """
   ```

3. **Update _apply_migrations()**:
   ```python
   def _apply_migrations(self) -> None:
       current_version = self._get_schema_version()
       if current_version < 2:
           self._migrate_v1_to_v2()
       if current_version < 3:
           self._migrate_v2_to_v3()
   ```

4. **Add migration tests**:
   ```python
   def test_v2_database_migrates_to_v3(self, temp_db_v2):
       db = Database(temp_db_v2)
       assert db.get_schema_version() == 3
       # Verify migration...
   ```

## References

- Database module: `src/core/database.py`
- Phase 1 tests: `tests/test_database.py`
- Phase 2 tests: `tests/test_database_remote.py`
- Schema documentation: This file

## Support

For issues or questions about database migrations:

1. Check test suite for examples: `tests/test_database*.py`
2. Review database module docstrings: `src/core/database.py`
3. File an issue with database version and error details
