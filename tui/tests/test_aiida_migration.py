"""Unit tests for AiiDA migration utility."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest


class TestDatabaseMigrator:
    """Test suite for DatabaseMigrator class."""

    @pytest.fixture
    def temp_sqlite_db(self, tmp_path):
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
            INSERT INTO jobs (id, name, status, input_content, results_json, created_at)
            VALUES (1, 'Test Job', 'completed', 'CRYSTAL\n0 0 0\nEND', '{"energy": -100.5}', '2024-01-01 12:00:00')
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

    @pytest.fixture
    def mock_profile(self):
        """Mock AiiDA profile loading."""
        with patch("aiida.load_profile") as mock:
            yield mock

    @pytest.fixture
    def migrator(self, temp_sqlite_db, mock_profile):
        """Create DatabaseMigrator instance."""
        from src.aiida.migration import DatabaseMigrator

        return DatabaseMigrator(
            sqlite_path=temp_sqlite_db,
            aiida_profile="test-profile",
            dry_run=True,
        )

    def test_init(self, temp_sqlite_db):
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
        assert not migrator._profile_loaded
        assert migrator.stats["jobs_found"] == 0

    def test_init_expands_home(self):
        """Test that home directory is expanded."""
        from src.aiida.migration import DatabaseMigrator

        migrator = DatabaseMigrator(
            sqlite_path="~/test.db",
            aiida_profile="test",
        )

        assert str(migrator.sqlite_path).startswith("/")
        assert "~" not in str(migrator.sqlite_path)

    def test_ensure_profile_loads_once(self, migrator, mock_profile):
        """Test that profile is loaded only once."""
        migrator.dry_run = False
        migrator._ensure_profile()
        migrator._ensure_profile()

        mock_profile.assert_called_once_with("test-profile")

    def test_ensure_profile_skip_dry_run(self, migrator, mock_profile):
        """Test that profile is not loaded in dry run."""
        migrator.dry_run = True
        migrator._ensure_profile()

        mock_profile.assert_not_called()

    def test_get_connection(self, migrator, temp_sqlite_db):
        """Test getting SQLite connection."""
        conn = migrator._get_connection()

        assert isinstance(conn, sqlite3.Connection)
        assert conn.row_factory == sqlite3.Row
        conn.close()

    def test_get_connection_file_not_found(self, tmp_path):
        """Test error when database file doesn't exist."""
        from src.aiida.migration import DatabaseMigrator

        migrator = DatabaseMigrator(
            sqlite_path=tmp_path / "nonexistent.db",
            aiida_profile="test",
        )

        with pytest.raises(FileNotFoundError, match="Database not found"):
            migrator._get_connection()

    def test_migrate_jobs_dry_run(self, migrator, capsys):
        """Test job migration in dry run mode."""
        migrator.migrate_jobs()

        captured = capsys.readouterr()
        assert "Test Job" in captured.out
        assert "[DRY RUN]" in captured.out
        assert migrator.stats["jobs_found"] == 1
        assert migrator.stats["jobs_migrated"] == 1

    @patch("src.aiida.migration.orm")
    def test_migrate_single_job(self, mock_orm, migrator, capsys):
        """Test migrating a single job."""
        migrator.dry_run = False

        # Mock ORM objects
        mock_input_file = MagicMock()
        mock_input_file.pk = 1
        mock_orm.SinglefileData.from_string.return_value = mock_input_file

        mock_metadata = MagicMock()
        mock_metadata.pk = 2
        mock_metadata.base.extras.set = MagicMock()
        mock_orm.Dict.return_value = mock_metadata

        job_data = {
            "id": 1,
            "name": "Test Job",
            "status": "completed",
            "runner_type": "local",
            "cluster_id": None,
            "input_content": "CRYSTAL\n0 0 0\nEND",
            "results_json": '{"energy": -100.5}',
            "work_dir": "/tmp/test",
            "created_at": "2024-01-01 12:00:00",
            "updated_at": "2024-01-02 12:00:00",
        }

        node = migrator._migrate_single_job(job_data)

        captured = capsys.readouterr()
        assert "Migrating job 1" in captured.out
        assert "OK (PK: 2)" in captured.out

        # Verify input file created
        mock_orm.SinglefileData.from_string.assert_called_once()
        mock_input_file.store.assert_called_once()

        # Verify metadata created
        mock_orm.Dict.assert_called_once()
        assert mock_metadata.label == "Test Job"

    @patch("src.aiida.migration.orm")
    def test_migrate_single_job_no_input(self, mock_orm, migrator):
        """Test migrating job without input content."""
        migrator.dry_run = False

        mock_metadata = MagicMock()
        mock_metadata.pk = 2
        mock_orm.Dict.return_value = mock_metadata

        job_data = {
            "id": 1,
            "name": "No Input Job",
            "status": "pending",
            "input_content": None,
        }

        node = migrator._migrate_single_job(job_data)

        # Should not create input file
        mock_orm.SinglefileData.from_string.assert_not_called()

    def test_migrate_clusters_dry_run(self, migrator, capsys):
        """Test cluster migration in dry run mode."""
        migrator.migrate_clusters()

        captured = capsys.readouterr()
        assert "test-cluster" in captured.out
        assert "[DRY RUN]" in captured.out
        assert migrator.stats["clusters_migrated"] == 1

    @patch("src.aiida.migration.orm")
    def test_migrate_single_cluster(self, mock_orm, migrator, capsys):
        """Test migrating a single cluster."""
        migrator.dry_run = False

        # Mock Computer doesn't exist
        mock_orm.Computer.collection.get.side_effect = Exception("Not found")

        mock_computer = MagicMock()
        mock_computer.pk = 1
        mock_orm.Computer.return_value = mock_computer

        cluster_data = {
            "id": 1,
            "name": "test-cluster",
            "hostname": "cluster.example.com",
            "username": "testuser",
            "queue_type": "slurm",
            "max_concurrent": 10,
        }

        migrator._migrate_single_cluster(cluster_data)

        captured = capsys.readouterr()
        assert "Migrating cluster 'test-cluster'" in captured.out
        assert "OK (PK: 1)" in captured.out

        # Verify Computer created
        mock_orm.Computer.assert_called_once()
        mock_computer.store.assert_called_once()

    @patch("src.aiida.migration.orm")
    def test_migrate_single_cluster_exists(self, mock_orm, migrator, capsys):
        """Test migrating cluster that already exists."""
        migrator.dry_run = False

        # Mock existing computer
        mock_existing = MagicMock()
        mock_existing.pk = 999
        mock_orm.Computer.collection.get.return_value = mock_existing

        cluster_data = {
            "id": 1,
            "name": "existing-cluster",
            "hostname": "cluster.example.com",
        }

        migrator._migrate_single_cluster(cluster_data)

        captured = capsys.readouterr()
        assert "SKIPPED (exists" in captured.out

    def test_migrate_single_cluster_scheduler_mapping(self, migrator):
        """Test scheduler type mapping."""
        from src.aiida.migration import DatabaseMigrator

        # Test various queue types
        test_cases = [
            ("slurm", "core.slurm"),
            ("pbs", "core.pbspro"),
            ("sge", "core.sge"),
            ("direct", "core.direct"),
            ("unknown", "core.direct"),
        ]

        for queue_type, expected_scheduler in test_cases:
            cluster_data = {
                "id": 1,
                "name": "test",
                "hostname": "localhost",
                "queue_type": queue_type,
            }

            with patch("src.aiida.migration.orm") as mock_orm:
                migrator.dry_run = False
                mock_orm.Computer.collection.get.side_effect = Exception("Not found")
                mock_computer = MagicMock()
                mock_orm.Computer.return_value = mock_computer

                migrator._migrate_single_cluster(cluster_data)

                # Check scheduler_type argument
                call_kwargs = mock_orm.Computer.call_args[1]
                assert call_kwargs["scheduler_type"] == expected_scheduler

    def test_migrate_workflows_dry_run(self, migrator, capsys):
        """Test workflow migration in dry run mode."""
        migrator.migrate_workflows()

        captured = capsys.readouterr()
        assert "Test Workflow" in captured.out
        assert "[DRY RUN]" in captured.out
        assert migrator.stats["workflows_migrated"] == 1

    @patch("src.aiida.migration.orm")
    def test_migrate_single_workflow(self, mock_orm, migrator, capsys):
        """Test migrating a single workflow."""
        migrator.dry_run = False

        mock_workflow_node = MagicMock()
        mock_workflow_node.pk = 3
        mock_orm.Dict.return_value = mock_workflow_node

        workflow_data = {
            "id": 1,
            "name": "Test Workflow",
            "dag_json": '{"nodes": ["a", "b"]}',
            "status": "completed",
            "created_at": "2024-01-01 12:00:00",
        }

        node = migrator._migrate_single_workflow(workflow_data)

        captured = capsys.readouterr()
        assert "Migrating workflow 'Test Workflow'" in captured.out
        assert "OK (PK: 3)" in captured.out

        # Verify Dict node created with DAG
        mock_orm.Dict.assert_called_once()

    def test_migrate_all(self, migrator, capsys):
        """Test full migration (dry run)."""
        stats = migrator.migrate_all()

        captured = capsys.readouterr()
        assert "Starting migration" in captured.out
        assert "Migration Summary" in captured.out
        assert "DRY RUN" in captured.out

        assert stats["jobs_found"] == 1
        assert stats["jobs_migrated"] == 1
        assert stats["clusters_migrated"] == 1
        assert stats["workflows_migrated"] == 1

    def test_migrate_all_skip_failed(self, migrator):
        """Test that migration continues on individual failures."""
        with patch.object(
            migrator, "_migrate_single_job", side_effect=Exception("Test error")
        ):
            stats = migrator.migrate_all(skip_failed=True)

        assert stats["jobs_found"] == 1
        assert stats["jobs_failed"] == 1

    def test_migrate_all_no_skip_failed(self, migrator):
        """Test that migration stops on error when skip_failed=False."""
        with patch.object(
            migrator, "_migrate_single_job", side_effect=Exception("Test error")
        ):
            with pytest.raises(Exception, match="Test error"):
                migrator.migrate_all(skip_failed=False)

    @patch("src.aiida.migration.orm")
    def test_verify_migration(self, mock_orm, migrator):
        """Test migration verification."""
        migrator.dry_run = False

        # Mock QueryBuilder for counting
        mock_qb = MagicMock()
        mock_qb.count.return_value = 10
        mock_orm.QueryBuilder.return_value = mock_qb

        # Mock computers
        mock_computer = MagicMock()
        mock_computer.is_configured = True
        mock_orm.Computer.collection.all.return_value = [mock_computer]

        results = migrator.verify_migration()

        assert results["migrated_nodes"] == 10
        assert results["computers_configured"] == 1

    def test_print_summary(self, migrator, capsys):
        """Test summary printing."""
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


class TestMainCLI:
    """Test command-line interface."""

    @patch("src.aiida.migration.DatabaseMigrator")
    @patch("sys.argv", ["migration.py", "--sqlite-db", "test.db", "--dry-run"])
    def test_main_dry_run(self, mock_migrator_class):
        """Test main with dry-run flag."""
        from src.aiida.migration import main

        mock_migrator = MagicMock()
        mock_migrator_class.return_value = mock_migrator

        main()

        # Verify migrator created with dry_run=True
        mock_migrator_class.assert_called_once()
        call_kwargs = mock_migrator_class.call_args[1]
        assert call_kwargs["dry_run"] is True

        mock_migrator.migrate_all.assert_called_once()

    @patch("src.aiida.migration.DatabaseMigrator")
    @patch("sys.argv", ["migration.py", "--verify"])
    def test_main_verify(self, mock_migrator_class, capsys):
        """Test main with verify flag."""
        from src.aiida.migration import main

        mock_migrator = MagicMock()
        mock_migrator.verify_migration.return_value = {
            "migrated_nodes": 10,
            "jobs_with_input": 8,
        }
        mock_migrator_class.return_value = mock_migrator

        main()

        mock_migrator.verify_migration.assert_called_once()

        captured = capsys.readouterr()
        assert "Migration Verification" in captured.out
        assert "migrated_nodes: 10" in captured.out
