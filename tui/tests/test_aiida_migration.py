"""Unit tests for AiiDA migration utility.

These tests verify the DatabaseMigrator class for migrating SQLite data to AiiDA.
The tests are designed to work without AiiDA installed.
"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def temp_sqlite_db(tmp_path):
    """Create temporary SQLite database with test data."""
    db_path = tmp_path / "test_jobs.db"
    conn = sqlite3.connect(db_path)

    # Create tables
    conn.execute("""
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            runner_type TEXT DEFAULT 'local',
            cluster_id INTEGER,
            input_content TEXT,
            results_json TEXT,
            work_dir TEXT,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE clusters (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            hostname TEXT NOT NULL,
            username TEXT NOT NULL,
            queue_type TEXT,
            max_concurrent INTEGER DEFAULT 10
        )
    """)

    conn.execute("""
        CREATE TABLE workflows (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            dag_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TIMESTAMP
        )
    """)

    # Insert test data
    conn.execute("""
        INSERT INTO jobs (id, name, status, runner_type, input_content, results_json, created_at)
        VALUES (1, 'Test Job', 'completed', 'local', 'CRYSTAL\n0 0 0\nEND', '{"energy": -100.5}', '2024-01-01 12:00:00')
    """)

    conn.execute("""
        INSERT INTO clusters (id, name, hostname, username, queue_type)
        VALUES (1, 'test-cluster', 'cluster.example.com', 'testuser', 'slurm')
    """)

    conn.execute("""
        INSERT INTO workflows (id, name, dag_json, status, created_at)
        VALUES (1, 'Test Workflow', '{"nodes": []}', 'completed', '2024-01-01 12:00:00')
    """)

    conn.commit()
    conn.close()

    return db_path


@pytest.fixture(autouse=True)
def mock_aiida_modules():
    """Mock AiiDA modules for all tests."""
    mock_load_profile = MagicMock()
    mock_orm = MagicMock()

    # Mock ORM objects
    mock_orm.Dict = MagicMock()
    mock_orm.SinglefileData = MagicMock()
    mock_orm.Computer = MagicMock()
    mock_orm.QueryBuilder = MagicMock()

    with patch.dict(
        sys.modules,
        {
            "aiida": MagicMock(load_profile=mock_load_profile),
            "aiida.orm": mock_orm,
        },
    ):
        yield {
            "load_profile": mock_load_profile,
            "orm": mock_orm,
        }


class TestDatabaseMigratorInit:
    """Test DatabaseMigrator initialization."""

    def test_init(self, temp_sqlite_db, mock_aiida_modules):
        """Test migrator initialization."""
        from src.aiida.migration import DatabaseMigrator

        migrator = DatabaseMigrator(
            sqlite_path=temp_sqlite_db,
            aiida_profile="custom-profile",
            dry_run=True,
        )

        assert migrator.sqlite_path == Path(temp_sqlite_db)
        assert migrator.aiida_profile == "custom-profile"
        assert migrator.dry_run is True
        assert migrator._profile_loaded is False
        assert migrator.stats["jobs_found"] == 0

    def test_init_expands_home(self, mock_aiida_modules):
        """Test that home directory is expanded."""
        from src.aiida.migration import DatabaseMigrator

        migrator = DatabaseMigrator(
            sqlite_path="~/test.db",
            aiida_profile="test",
        )

        assert str(migrator.sqlite_path).startswith("/")
        assert "~" not in str(migrator.sqlite_path)


class TestDatabaseMigratorProfile:
    """Test profile loading."""

    def test_ensure_profile_loads_once(self, temp_sqlite_db, mock_aiida_modules):
        """Test that profile is loaded only once."""
        from src.aiida.migration import DatabaseMigrator

        mock_load_profile = mock_aiida_modules["load_profile"]

        migrator = DatabaseMigrator(
            sqlite_path=temp_sqlite_db,
            aiida_profile="test-profile",
            dry_run=False,
        )

        migrator._ensure_profile()
        migrator._ensure_profile()

        mock_load_profile.assert_called_once_with("test-profile")

    def test_ensure_profile_skip_dry_run(self, temp_sqlite_db, mock_aiida_modules):
        """Test that profile is not loaded in dry run."""
        from src.aiida.migration import DatabaseMigrator

        mock_load_profile = mock_aiida_modules["load_profile"]

        migrator = DatabaseMigrator(
            sqlite_path=temp_sqlite_db,
            aiida_profile="test-profile",
            dry_run=True,
        )

        migrator._ensure_profile()

        mock_load_profile.assert_not_called()


class TestDatabaseMigratorConnection:
    """Test database connection handling."""

    def test_get_connection(self, temp_sqlite_db, mock_aiida_modules):
        """Test getting SQLite connection."""
        from src.aiida.migration import DatabaseMigrator

        migrator = DatabaseMigrator(
            sqlite_path=temp_sqlite_db,
            aiida_profile="test",
        )

        conn = migrator._get_connection()

        assert isinstance(conn, sqlite3.Connection)
        assert conn.row_factory == sqlite3.Row
        conn.close()

    def test_get_connection_file_not_found(self, tmp_path, mock_aiida_modules):
        """Test error when database file doesn't exist."""
        from src.aiida.migration import DatabaseMigrator

        migrator = DatabaseMigrator(
            sqlite_path=tmp_path / "nonexistent.db",
            aiida_profile="test",
        )

        with pytest.raises(FileNotFoundError, match="Database not found"):
            migrator._get_connection()


class TestDatabaseMigratorDryRun:
    """Test dry run behavior."""

    def test_migrate_jobs_dry_run(self, temp_sqlite_db, mock_aiida_modules, capsys):
        """Test job migration in dry run mode."""
        from src.aiida.migration import DatabaseMigrator

        migrator = DatabaseMigrator(
            sqlite_path=temp_sqlite_db,
            aiida_profile="test",
            dry_run=True,
        )

        migrator.migrate_jobs()

        captured = capsys.readouterr()
        assert "Test Job" in captured.out
        assert "[DRY RUN]" in captured.out
        assert migrator.stats["jobs_found"] == 1
        assert migrator.stats["jobs_migrated"] == 1

    def test_migrate_clusters_dry_run(self, temp_sqlite_db, mock_aiida_modules, capsys):
        """Test cluster migration in dry run mode."""
        from src.aiida.migration import DatabaseMigrator

        migrator = DatabaseMigrator(
            sqlite_path=temp_sqlite_db,
            aiida_profile="test",
            dry_run=True,
        )

        migrator.migrate_clusters()

        captured = capsys.readouterr()
        assert "test-cluster" in captured.out
        assert "[DRY RUN]" in captured.out
        assert migrator.stats["clusters_migrated"] == 1

    def test_migrate_workflows_dry_run(self, temp_sqlite_db, mock_aiida_modules, capsys):
        """Test workflow migration in dry run mode."""
        from src.aiida.migration import DatabaseMigrator

        migrator = DatabaseMigrator(
            sqlite_path=temp_sqlite_db,
            aiida_profile="test",
            dry_run=True,
        )

        migrator.migrate_workflows()

        captured = capsys.readouterr()
        assert "Test Workflow" in captured.out
        assert "[DRY RUN]" in captured.out
        assert migrator.stats["workflows_migrated"] == 1

    def test_migrate_all_dry_run(self, temp_sqlite_db, mock_aiida_modules, capsys):
        """Test full migration in dry run mode."""
        from src.aiida.migration import DatabaseMigrator

        migrator = DatabaseMigrator(
            sqlite_path=temp_sqlite_db,
            aiida_profile="test",
            dry_run=True,
        )

        stats = migrator.migrate_all()

        captured = capsys.readouterr()
        assert "Starting migration" in captured.out
        assert "Migration Summary" in captured.out
        assert "DRY RUN" in captured.out

        assert stats["jobs_found"] == 1
        assert stats["jobs_migrated"] == 1
        assert stats["clusters_migrated"] == 1
        assert stats["workflows_migrated"] == 1


class TestDatabaseMigratorMigrateSingleJob:
    """Test single job migration."""

    def test_migrate_single_job_no_input(self, temp_sqlite_db, mock_aiida_modules, capsys):
        """Test migrating job without input content."""
        from src.aiida.migration import DatabaseMigrator

        mock_orm = mock_aiida_modules["orm"]
        mock_metadata = MagicMock()
        mock_metadata.pk = 2
        mock_orm.Dict.return_value = mock_metadata

        migrator = DatabaseMigrator(
            sqlite_path=temp_sqlite_db,
            aiida_profile="test",
            dry_run=False,
        )

        job_data = {
            "id": 1,
            "name": "No Input Job",
            "status": "pending",
            "input_content": None,
        }

        migrator._migrate_single_job(job_data)

        # Should not create input file
        mock_orm.SinglefileData.from_string.assert_not_called()


class TestDatabaseMigratorErrorHandling:
    """Test error handling in migration."""

    def test_migrate_all_skip_failed(self, temp_sqlite_db, mock_aiida_modules):
        """Test that migration continues on individual failures."""
        from src.aiida.migration import DatabaseMigrator

        migrator = DatabaseMigrator(
            sqlite_path=temp_sqlite_db,
            aiida_profile="test",
            dry_run=True,
        )

        with patch.object(migrator, "_migrate_single_job", side_effect=Exception("Test error")):
            stats = migrator.migrate_all(skip_failed=True)

        assert stats["jobs_found"] == 1
        assert stats["jobs_failed"] == 1

    def test_migrate_all_no_skip_failed(self, temp_sqlite_db, mock_aiida_modules):
        """Test that migration stops on error when skip_failed=False."""
        from src.aiida.migration import DatabaseMigrator

        migrator = DatabaseMigrator(
            sqlite_path=temp_sqlite_db,
            aiida_profile="test",
            dry_run=True,
        )

        with patch.object(migrator, "_migrate_single_job", side_effect=Exception("Test error")):
            with pytest.raises(Exception, match="Test error"):
                migrator.migrate_all(skip_failed=False)


class TestDatabaseMigratorSummary:
    """Test summary printing."""

    def test_print_summary(self, temp_sqlite_db, mock_aiida_modules, capsys):
        """Test summary printing."""
        from src.aiida.migration import DatabaseMigrator

        migrator = DatabaseMigrator(
            sqlite_path=temp_sqlite_db,
            aiida_profile="test",
            dry_run=True,
        )

        migrator.stats = {
            "jobs_found": 10,
            "jobs_migrated": 8,
            "jobs_skipped": 1,
            "jobs_failed": 1,
            "clusters_migrated": 2,
            "workflows_migrated": 3,
        }

        migrator._print_summary()

        captured = capsys.readouterr()
        assert "Migration Summary" in captured.out
        assert "Jobs found:      10" in captured.out
        assert "Jobs migrated:   8" in captured.out
        assert "Clusters:        2" in captured.out
