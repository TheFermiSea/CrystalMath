"""
Comprehensive unit tests for remote execution database features.

Tests cover:
- Database schema migrations (v1 to v2)
- Cluster CRUD operations
- Remote job tracking
- Job dependencies and workflows
- Backward compatibility with Phase 1 databases
- Complex workflow scenarios
"""

import json
import sqlite3
import tempfile
from pathlib import Path
import pytest

from src.core.database import (
    Database, Job, Cluster, RemoteJob, JobDependency,
    RunnerType, ClusterType, DependencyType
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    db = Database(db_path)
    yield db

    db.close()
    db_path.unlink(missing_ok=True)


@pytest.fixture
def temp_db_v1():
    """Create a temporary database with Phase 1 schema only."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    # Create v1 database manually
    conn = sqlite3.connect(str(db_path))
    conn.executescript(Database.SCHEMA_V1)
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (1,))
    conn.commit()
    conn.close()

    yield db_path

    db_path.unlink(missing_ok=True)


class TestSchemaMigration:
    """Tests for database schema migrations."""

    def test_new_database_creates_v2_schema(self, temp_db):
        """Test that new databases are created with current schema."""
        from src.core.database import Database
        assert temp_db.get_schema_version() == Database.SCHEMA_VERSION

        # Verify all tables exist
        cursor = temp_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}

        expected_tables = {"jobs", "clusters", "remote_jobs", "job_dependencies", "job_results", "schema_version"}
        assert expected_tables.issubset(tables)

    def test_v1_database_migrates_to_v2(self, temp_db_v1):
        """Test that v1 databases are automatically migrated to latest."""
        # Open v1 database - should trigger migration
        db = Database(temp_db_v1)

        assert db.get_schema_version() == Database.SCHEMA_VERSION

        # Verify Phase 2 columns exist in jobs table
        cursor = db.conn.execute("PRAGMA table_info(jobs)")
        columns = {row[1] for row in cursor.fetchall()}

        phase2_columns = {
            'cluster_id', 'runner_type', 'parallelism_config',
            'queue_time', 'start_time', 'end_time'
        }
        assert phase2_columns.issubset(columns)

        db.close()

    def test_migration_preserves_existing_data(self, temp_db_v1):
        """Test that migration preserves existing Phase 1 job data."""
        # Add job to v1 database
        conn = sqlite3.connect(str(temp_db_v1))
        cursor = conn.execute(
            "INSERT INTO jobs (name, work_dir, status, input_file) VALUES (?, ?, ?, ?)",
            ("test_job", "/tmp/test", "PENDING", "input data")
        )
        job_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Open and migrate
        db = Database(temp_db_v1)

        # Verify job still exists with data
        job = db.get_job(job_id)
        assert job is not None
        assert job.name == "test_job"
        assert job.work_dir == "/tmp/test"
        assert job.runner_type == "local"  # Default value

        db.close()

    def test_foreign_keys_enabled(self, temp_db):
        """Test that foreign key constraints are enforced."""
        result = temp_db.conn.execute("PRAGMA foreign_keys").fetchone()
        assert result[0] == 1  # Foreign keys enabled


class TestClusterOperations:
    """Tests for cluster CRUD operations."""

    def test_create_ssh_cluster(self, temp_db):
        """Test creating an SSH cluster configuration."""
        cluster_id = temp_db.create_cluster(
            name="test_cluster",
            type="ssh",
            hostname="cluster.example.com",
            username="testuser",
            port=22,
            connection_config={"key_file": "/path/to/key"}
        )

        assert isinstance(cluster_id, int)
        assert cluster_id > 0

    def test_create_slurm_cluster(self, temp_db):
        """Test creating a SLURM cluster configuration."""
        cluster_id = temp_db.create_cluster(
            name="hpc_cluster",
            type="slurm",
            hostname="hpc.example.com",
            username="hpcuser",
            port=22,
            connection_config={
                "key_file": "/path/to/key",
                "partition": "gpu",
                "qos": "high"
            }
        )

        cluster = temp_db.get_cluster(cluster_id)
        assert cluster is not None
        assert cluster.type == "slurm"
        assert cluster.connection_config["partition"] == "gpu"

    def test_get_cluster_by_id(self, temp_db):
        """Test retrieving cluster by ID."""
        cluster_id = temp_db.create_cluster(
            name="test", type="ssh", hostname="host", username="user"
        )

        cluster = temp_db.get_cluster(cluster_id)
        assert cluster.id == cluster_id
        assert cluster.name == "test"

    def test_get_cluster_by_name(self, temp_db):
        """Test retrieving cluster by name."""
        temp_db.create_cluster(
            name="named_cluster", type="ssh", hostname="host", username="user"
        )

        cluster = temp_db.get_cluster_by_name("named_cluster")
        assert cluster is not None
        assert cluster.name == "named_cluster"

    def test_get_nonexistent_cluster(self, temp_db):
        """Test retrieving a cluster that doesn't exist."""
        assert temp_db.get_cluster(99999) is None
        assert temp_db.get_cluster_by_name("nonexistent") is None

    def test_get_all_clusters(self, temp_db):
        """Test retrieving all clusters."""
        names = ["cluster_a", "cluster_b", "cluster_c"]
        for name in names:
            temp_db.create_cluster(
                name=name, type="ssh", hostname="host", username="user"
            )

        clusters = temp_db.get_all_clusters()
        assert len(clusters) == 3
        assert {c.name for c in clusters} == set(names)

    def test_get_active_clusters_only(self, temp_db):
        """Test retrieving only active clusters."""
        cluster1_id = temp_db.create_cluster(
            name="active1", type="ssh", hostname="host", username="user"
        )
        temp_db.create_cluster(
            name="active2", type="ssh", hostname="host", username="user"
        )
        cluster3_id = temp_db.create_cluster(
            name="inactive", type="ssh", hostname="host", username="user"
        )

        # Mark one cluster as inactive
        temp_db.update_cluster(cluster3_id, status="inactive")

        active = temp_db.get_active_clusters()
        assert len(active) == 2
        assert all(c.status == "active" for c in active)

    def test_update_cluster_hostname(self, temp_db):
        """Test updating cluster hostname."""
        cluster_id = temp_db.create_cluster(
            name="test", type="ssh", hostname="old.example.com", username="user"
        )

        temp_db.update_cluster(cluster_id, hostname="new.example.com")

        cluster = temp_db.get_cluster(cluster_id)
        assert cluster.hostname == "new.example.com"

    def test_update_cluster_config(self, temp_db):
        """Test updating cluster connection configuration."""
        cluster_id = temp_db.create_cluster(
            name="test", type="ssh", hostname="host", username="user",
            connection_config={"key_file": "/old/key"}
        )

        new_config = {"key_file": "/new/key", "timeout": 30}
        temp_db.update_cluster(cluster_id, connection_config=new_config)

        cluster = temp_db.get_cluster(cluster_id)
        assert cluster.connection_config == new_config

    def test_update_cluster_status(self, temp_db):
        """Test updating cluster status."""
        cluster_id = temp_db.create_cluster(
            name="test", type="ssh", hostname="host", username="user"
        )

        temp_db.update_cluster(cluster_id, status="error")

        cluster = temp_db.get_cluster(cluster_id)
        assert cluster.status == "error"

    def test_delete_cluster(self, temp_db):
        """Test deleting a cluster."""
        cluster_id = temp_db.create_cluster(
            name="test", type="ssh", hostname="host", username="user"
        )

        temp_db.delete_cluster(cluster_id)

        assert temp_db.get_cluster(cluster_id) is None

    def test_duplicate_cluster_name_fails(self, temp_db):
        """Test that duplicate cluster names are rejected."""
        temp_db.create_cluster(
            name="duplicate", type="ssh", hostname="host", username="user"
        )

        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            temp_db.create_cluster(
                name="duplicate", type="ssh", hostname="host2", username="user2"
            )


class TestRemoteJobOperations:
    """Tests for remote job tracking."""

    def test_create_job_with_cluster(self, temp_db):
        """Test creating a job with cluster assignment."""
        cluster_id = temp_db.create_cluster(
            name="test_cluster", type="ssh", hostname="host", username="user"
        )

        job_id = temp_db.create_job(
            name="remote_job",
            work_dir="/tmp/remote",
            input_content="CRYSTAL\nEND\n",
            cluster_id=cluster_id,
            runner_type="ssh"
        )

        job = temp_db.get_job(job_id)
        assert job.cluster_id == cluster_id
        assert job.runner_type == "ssh"

    def test_create_job_with_parallelism_config(self, temp_db):
        """Test creating a job with parallelism configuration."""
        parallelism = {
            "mpi_ranks": 16,
            "threads_per_rank": 4,
            "nodes": 2
        }

        job_id = temp_db.create_job(
            name="parallel_job",
            work_dir="/tmp/parallel",
            input_content="input",
            parallelism_config=parallelism
        )

        job = temp_db.get_job(job_id)
        assert job.parallelism_config == parallelism

    def test_get_jobs_by_cluster(self, temp_db):
        """Test retrieving all jobs for a specific cluster."""
        cluster1_id = temp_db.create_cluster(
            name="cluster1", type="ssh", hostname="host1", username="user"
        )
        cluster2_id = temp_db.create_cluster(
            name="cluster2", type="ssh", hostname="host2", username="user"
        )

        # Create jobs on different clusters
        for i in range(3):
            temp_db.create_job(
                name=f"job_c1_{i}", work_dir=f"/tmp/c1/{i}", input_content="input",
                cluster_id=cluster1_id
            )

        temp_db.create_job(
            name="job_c2", work_dir="/tmp/c2/0", input_content="input",
            cluster_id=cluster2_id
        )

        cluster1_jobs = temp_db.get_jobs_by_cluster(cluster1_id)
        assert len(cluster1_jobs) == 3

        cluster2_jobs = temp_db.get_jobs_by_cluster(cluster2_id)
        assert len(cluster2_jobs) == 1

    def test_create_remote_job_tracking(self, temp_db):
        """Test creating remote job tracking entry."""
        cluster_id = temp_db.create_cluster(
            name="cluster", type="slurm", hostname="host", username="user"
        )
        job_id = temp_db.create_job(
            name="test", work_dir="/tmp/test", input_content="input"
        )

        remote_job_id = temp_db.create_remote_job(
            job_id=job_id,
            cluster_id=cluster_id,
            remote_handle="12345",
            working_directory="/scratch/user/job",
            queue_name="gpu",
            metadata={"partition": "gpu", "time_limit": "24:00:00"}
        )

        assert isinstance(remote_job_id, int)
        assert remote_job_id > 0

    def test_get_remote_job_by_id(self, temp_db):
        """Test retrieving remote job by ID."""
        cluster_id = temp_db.create_cluster(
            name="cluster", type="ssh", hostname="host", username="user"
        )
        job_id = temp_db.create_job(
            name="test", work_dir="/tmp/test", input_content="input"
        )

        remote_job_id = temp_db.create_remote_job(
            job_id=job_id,
            cluster_id=cluster_id,
            remote_handle="54321",
            working_directory="/remote/work"
        )

        remote_job = temp_db.get_remote_job(remote_job_id)
        assert remote_job is not None
        assert remote_job.remote_handle == "54321"

    def test_get_remote_job_by_job_id(self, temp_db):
        """Test retrieving remote job by job ID."""
        cluster_id = temp_db.create_cluster(
            name="cluster", type="ssh", hostname="host", username="user"
        )
        job_id = temp_db.create_job(
            name="test", work_dir="/tmp/test", input_content="input"
        )

        temp_db.create_remote_job(
            job_id=job_id,
            cluster_id=cluster_id,
            remote_handle="99999",
            working_directory="/remote/work"
        )

        remote_job = temp_db.get_remote_job_by_job_id(job_id)
        assert remote_job is not None
        assert remote_job.job_id == job_id

    def test_update_remote_job_node_list(self, temp_db):
        """Test updating remote job node allocation."""
        cluster_id = temp_db.create_cluster(
            name="cluster", type="slurm", hostname="host", username="user"
        )
        job_id = temp_db.create_job(
            name="test", work_dir="/tmp/test", input_content="input"
        )
        remote_job_id = temp_db.create_remote_job(
            job_id=job_id,
            cluster_id=cluster_id,
            remote_handle="12345",
            working_directory="/work"
        )

        temp_db.update_remote_job(
            remote_job_id,
            node_list="node[01-04]",
            stdout_path="/logs/job.out",
            stderr_path="/logs/job.err"
        )

        remote_job = temp_db.get_remote_job(remote_job_id)
        assert remote_job.node_list == "node[01-04]"
        assert remote_job.stdout_path == "/logs/job.out"

    def test_remote_job_metadata_json(self, temp_db):
        """Test that remote job metadata is properly serialized."""
        cluster_id = temp_db.create_cluster(
            name="cluster", type="slurm", hostname="host", username="user"
        )
        job_id = temp_db.create_job(
            name="test", work_dir="/tmp/test", input_content="input"
        )

        metadata = {
            "partition": "gpu",
            "qos": "high",
            "modules": ["gcc/11.2.0", "cuda/11.4"],
            "environment": {"OMP_NUM_THREADS": "4"}
        }

        remote_job_id = temp_db.create_remote_job(
            job_id=job_id,
            cluster_id=cluster_id,
            remote_handle="12345",
            working_directory="/work",
            metadata=metadata
        )

        remote_job = temp_db.get_remote_job(remote_job_id)
        assert remote_job.metadata == metadata

    def test_delete_cluster_cascades_to_remote_jobs(self, temp_db):
        """Test that deleting cluster removes associated remote jobs."""
        cluster_id = temp_db.create_cluster(
            name="cluster", type="ssh", hostname="host", username="user"
        )
        job_id = temp_db.create_job(
            name="test", work_dir="/tmp/test", input_content="input"
        )
        remote_job_id = temp_db.create_remote_job(
            job_id=job_id,
            cluster_id=cluster_id,
            remote_handle="12345",
            working_directory="/work"
        )

        # Delete cluster should cascade to remote_jobs
        temp_db.delete_cluster(cluster_id)

        assert temp_db.get_remote_job(remote_job_id) is None


class TestJobDependencies:
    """Tests for job dependencies and workflows."""

    def test_add_simple_dependency(self, temp_db):
        """Test adding a simple job dependency."""
        job1_id = temp_db.create_job("job1", "/tmp/job1", "input1")
        job2_id = temp_db.create_job("job2", "/tmp/job2", "input2")

        dep_id = temp_db.add_job_dependency(job2_id, job1_id, "after_ok")

        assert isinstance(dep_id, int)
        assert dep_id > 0

    def test_get_job_dependencies(self, temp_db):
        """Test retrieving dependencies for a job."""
        job1_id = temp_db.create_job("job1", "/tmp/job1", "input1")
        job2_id = temp_db.create_job("job2", "/tmp/job2", "input2")
        job3_id = temp_db.create_job("job3", "/tmp/job3", "input3")

        # job3 depends on job1 and job2
        temp_db.add_job_dependency(job3_id, job1_id, "after_ok")
        temp_db.add_job_dependency(job3_id, job2_id, "after_ok")

        deps = temp_db.get_job_dependencies(job3_id)
        assert len(deps) == 2
        depends_on_ids = {d.depends_on_job_id for d in deps}
        assert depends_on_ids == {job1_id, job2_id}

    def test_get_dependent_jobs(self, temp_db):
        """Test retrieving jobs that depend on a given job."""
        job1_id = temp_db.create_job("job1", "/tmp/job1", "input1")
        job2_id = temp_db.create_job("job2", "/tmp/job2", "input2")
        job3_id = temp_db.create_job("job3", "/tmp/job3", "input3")

        # Both job2 and job3 depend on job1
        temp_db.add_job_dependency(job2_id, job1_id, "after_ok")
        temp_db.add_job_dependency(job3_id, job1_id, "after_ok")

        dependents = temp_db.get_dependent_jobs(job1_id)
        assert len(dependents) == 2
        dependent_job_ids = {d.job_id for d in dependents}
        assert dependent_job_ids == {job2_id, job3_id}

    def test_remove_job_dependency(self, temp_db):
        """Test removing a job dependency."""
        job1_id = temp_db.create_job("job1", "/tmp/job1", "input1")
        job2_id = temp_db.create_job("job2", "/tmp/job2", "input2")

        dep_id = temp_db.add_job_dependency(job2_id, job1_id, "after_ok")
        temp_db.remove_job_dependency(dep_id)

        deps = temp_db.get_job_dependencies(job2_id)
        assert len(deps) == 0

    def test_duplicate_dependency_fails(self, temp_db):
        """Test that duplicate dependencies are rejected."""
        job1_id = temp_db.create_job("job1", "/tmp/job1", "input1")
        job2_id = temp_db.create_job("job2", "/tmp/job2", "input2")

        temp_db.add_job_dependency(job2_id, job1_id, "after_ok")

        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            temp_db.add_job_dependency(job2_id, job1_id, "after_ok")

    def test_can_job_run_no_dependencies(self, temp_db):
        """Test that jobs without dependencies can run."""
        job_id = temp_db.create_job("job", "/tmp/job", "input")

        can_run, reasons = temp_db.can_job_run(job_id)
        assert can_run is True
        assert reasons == []

    def test_can_job_run_after_ok_completed(self, temp_db):
        """Test after_ok dependency with completed parent."""
        job1_id = temp_db.create_job("job1", "/tmp/job1", "input1")
        job2_id = temp_db.create_job("job2", "/tmp/job2", "input2")

        temp_db.add_job_dependency(job2_id, job1_id, "after_ok")

        # Parent not completed yet
        can_run, reasons = temp_db.can_job_run(job2_id)
        assert can_run is False
        assert len(reasons) > 0

        # Complete parent job
        temp_db.update_status(job1_id, "COMPLETED")

        can_run, reasons = temp_db.can_job_run(job2_id)
        assert can_run is True
        assert reasons == []

    def test_can_job_run_after_ok_failed(self, temp_db):
        """Test after_ok dependency blocks when parent failed."""
        job1_id = temp_db.create_job("job1", "/tmp/job1", "input1")
        job2_id = temp_db.create_job("job2", "/tmp/job2", "input2")

        temp_db.add_job_dependency(job2_id, job1_id, "after_ok")
        temp_db.update_status(job1_id, "FAILED")

        can_run, reasons = temp_db.can_job_run(job2_id)
        assert can_run is False
        assert "complete successfully" in reasons[0]

    def test_can_job_run_after_any(self, temp_db):
        """Test after_any dependency allows run after any completion."""
        job1_id = temp_db.create_job("job1", "/tmp/job1", "input1")
        job2_id = temp_db.create_job("job2", "/tmp/job2", "input2")

        temp_db.add_job_dependency(job2_id, job1_id, "after_any")

        # Completed
        temp_db.update_status(job1_id, "COMPLETED")
        can_run, _ = temp_db.can_job_run(job2_id)
        assert can_run is True

        # Reset and test with failed
        temp_db.conn.execute("UPDATE jobs SET status = 'PENDING' WHERE id = ?", (job1_id,))
        temp_db.conn.commit()
        temp_db.update_status(job1_id, "FAILED")
        can_run, _ = temp_db.can_job_run(job2_id)
        assert can_run is True

    def test_can_job_run_after_failed(self, temp_db):
        """Test after_failed dependency requires parent to fail."""
        job1_id = temp_db.create_job("job1", "/tmp/job1", "input1")
        job2_id = temp_db.create_job("job2", "/tmp/job2", "input2")

        temp_db.add_job_dependency(job2_id, job1_id, "after_failed")

        # Parent completed successfully - should block
        temp_db.update_status(job1_id, "COMPLETED")
        can_run, reasons = temp_db.can_job_run(job2_id)
        assert can_run is False

        # Reset and fail parent
        temp_db.conn.execute("UPDATE jobs SET status = 'PENDING' WHERE id = ?", (job1_id,))
        temp_db.conn.commit()
        temp_db.update_status(job1_id, "FAILED")
        can_run, _ = temp_db.can_job_run(job2_id)
        assert can_run is True

    def test_can_job_run_multiple_dependencies(self, temp_db):
        """Test job with multiple dependencies."""
        job1_id = temp_db.create_job("job1", "/tmp/job1", "input1")
        job2_id = temp_db.create_job("job2", "/tmp/job2", "input2")
        job3_id = temp_db.create_job("job3", "/tmp/job3", "input3")

        # job3 depends on both job1 and job2
        temp_db.add_job_dependency(job3_id, job1_id, "after_ok")
        temp_db.add_job_dependency(job3_id, job2_id, "after_ok")

        # Only job1 completed
        temp_db.update_status(job1_id, "COMPLETED")
        can_run, reasons = temp_db.can_job_run(job3_id)
        assert can_run is False
        assert len(reasons) == 1  # job2 still pending

        # Complete job2
        temp_db.update_status(job2_id, "COMPLETED")
        can_run, reasons = temp_db.can_job_run(job3_id)
        assert can_run is True
        assert reasons == []


class TestWorkflowScenarios:
    """Integration tests for complex workflow scenarios."""

    def test_linear_workflow(self, temp_db):
        """Test a linear workflow: job1 -> job2 -> job3."""
        job_ids = []
        for i in range(1, 4):
            job_id = temp_db.create_job(f"job{i}", f"/tmp/job{i}", f"input{i}")
            job_ids.append(job_id)

        # Create linear dependencies
        for i in range(1, 3):
            temp_db.add_job_dependency(job_ids[i], job_ids[i-1], "after_ok")

        # Initially only job1 can run
        assert temp_db.can_job_run(job_ids[0])[0] is True
        assert temp_db.can_job_run(job_ids[1])[0] is False
        assert temp_db.can_job_run(job_ids[2])[0] is False

        # Complete job1, now job2 can run
        temp_db.update_status(job_ids[0], "COMPLETED")
        assert temp_db.can_job_run(job_ids[1])[0] is True
        assert temp_db.can_job_run(job_ids[2])[0] is False

        # Complete job2, now job3 can run
        temp_db.update_status(job_ids[1], "COMPLETED")
        assert temp_db.can_job_run(job_ids[2])[0] is True

    def test_fan_out_workflow(self, temp_db):
        """Test fan-out workflow: job1 -> [job2, job3, job4]."""
        job1_id = temp_db.create_job("job1", "/tmp/job1", "input1")
        parallel_jobs = []
        for i in range(2, 5):
            job_id = temp_db.create_job(f"job{i}", f"/tmp/job{i}", f"input{i}")
            temp_db.add_job_dependency(job_id, job1_id, "after_ok")
            parallel_jobs.append(job_id)

        # All parallel jobs blocked until job1 completes
        for job_id in parallel_jobs:
            assert temp_db.can_job_run(job_id)[0] is False

        # Complete job1 - all parallel jobs can run
        temp_db.update_status(job1_id, "COMPLETED")
        for job_id in parallel_jobs:
            assert temp_db.can_job_run(job_id)[0] is True

    def test_fan_in_workflow(self, temp_db):
        """Test fan-in workflow: [job1, job2, job3] -> job4."""
        parent_jobs = []
        for i in range(1, 4):
            job_id = temp_db.create_job(f"job{i}", f"/tmp/job{i}", f"input{i}")
            parent_jobs.append(job_id)

        final_job_id = temp_db.create_job("job4", "/tmp/job4", "input4")

        # Add dependencies from all parents
        for parent_id in parent_jobs:
            temp_db.add_job_dependency(final_job_id, parent_id, "after_ok")

        # Final job can't run until all parents complete
        assert temp_db.can_job_run(final_job_id)[0] is False

        # Complete first two parents
        temp_db.update_status(parent_jobs[0], "COMPLETED")
        temp_db.update_status(parent_jobs[1], "COMPLETED")
        assert temp_db.can_job_run(final_job_id)[0] is False

        # Complete final parent
        temp_db.update_status(parent_jobs[2], "COMPLETED")
        assert temp_db.can_job_run(final_job_id)[0] is True

    def test_mixed_cluster_workflow(self, temp_db):
        """Test workflow with jobs on different clusters."""
        local_cluster = temp_db.create_cluster(
            name="local", type="ssh", hostname="localhost", username="user"
        )
        hpc_cluster = temp_db.create_cluster(
            name="hpc", type="slurm", hostname="hpc.example.com", username="user"
        )

        # Create workflow: local prep -> HPC compute -> local analysis
        prep_job = temp_db.create_job(
            name="prep", work_dir="/tmp/prep", input_content="prep",
            cluster_id=local_cluster, runner_type="ssh"
        )

        compute_job = temp_db.create_job(
            name="compute", work_dir="/tmp/compute", input_content="compute",
            cluster_id=hpc_cluster, runner_type="slurm",
            parallelism_config={"mpi_ranks": 64, "nodes": 4}
        )

        analysis_job = temp_db.create_job(
            name="analysis", work_dir="/tmp/analysis", input_content="analysis",
            cluster_id=local_cluster, runner_type="ssh"
        )

        # Set up dependencies
        temp_db.add_job_dependency(compute_job, prep_job, "after_ok")
        temp_db.add_job_dependency(analysis_job, compute_job, "after_ok")

        # Verify workflow executes in order
        assert temp_db.can_job_run(prep_job)[0] is True
        assert temp_db.can_job_run(compute_job)[0] is False

        temp_db.update_status(prep_job, "COMPLETED")
        assert temp_db.can_job_run(compute_job)[0] is True

        # Verify cluster assignments
        jobs_on_hpc = temp_db.get_jobs_by_cluster(hpc_cluster)
        assert len(jobs_on_hpc) == 1
        assert jobs_on_hpc[0].name == "compute"


class TestBackwardCompatibility:
    """Tests for backward compatibility with Phase 1 databases."""

    def test_phase1_jobs_work_after_migration(self, temp_db_v1):
        """Test that Phase 1 job operations still work after migration."""
        # Add Phase 1 job before migration
        conn = sqlite3.connect(str(temp_db_v1))
        cursor = conn.execute(
            "INSERT INTO jobs (name, work_dir, status, input_file) VALUES (?, ?, ?, ?)",
            ("old_job", "/tmp/old", "PENDING", "old input")
        )
        job_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Migrate
        db = Database(temp_db_v1)

        # Test Phase 1 operations
        job = db.get_job(job_id)
        assert job.name == "old_job"

        db.update_status(job_id, "RUNNING", pid=12345)
        job = db.get_job(job_id)
        assert job.status == "RUNNING"

        db.update_results(job_id, final_energy=-100.0, key_results={"converged": True})
        job = db.get_job(job_id)
        assert job.final_energy == -100.0

        db.close()

    def test_mixed_phase1_and_phase2_jobs(self, temp_db):
        """Test database with both local and remote jobs."""
        # Create local job (Phase 1 style)
        local_job_id = temp_db.create_job(
            name="local_job",
            work_dir="/tmp/local",
            input_content="input"
        )

        # Create remote job (Phase 2 style)
        cluster_id = temp_db.create_cluster(
            name="cluster", type="ssh", hostname="host", username="user"
        )
        remote_job_id = temp_db.create_job(
            name="remote_job",
            work_dir="/tmp/remote",
            input_content="input",
            cluster_id=cluster_id,
            runner_type="ssh"
        )

        # Verify both jobs exist and are retrievable
        all_jobs = temp_db.get_all_jobs()
        assert len(all_jobs) == 2

        local_job = temp_db.get_job(local_job_id)
        assert local_job.runner_type == "local"
        assert local_job.cluster_id is None

        remote_job = temp_db.get_job(remote_job_id)
        assert remote_job.runner_type == "ssh"
        assert remote_job.cluster_id == cluster_id


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
