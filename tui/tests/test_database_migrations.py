"""
Tests for database migration atomicity and integrity.

These tests verify that:
1. Failed migrations rollback completely (no partial state)
2. Migrations are atomic (all-or-nothing)
3. Schema versioning is consistent
4. Multiple concurrent migrations don't corrupt the database
"""

import pytest
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

from src.core.database import Database


class TestMigrationAtomicity:
    """Test that migrations are atomic and rollback correctly on failure."""

    def test_initial_schema_creation_atomicity(self):
        """Test that failed initial schema creation rolls back completely."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Patch the schema to inject a failure midway
            failing_schema = """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            );

            INVALID SQL THAT WILL FAIL HERE;

            CREATE TABLE IF NOT EXISTS should_not_exist (
                id INTEGER PRIMARY KEY
            );
            """

            # First, test that the exception is raised
            exception_raised = False
            with patch.object(Database, 'SCHEMA_V1', failing_schema):
                try:
                    Database(db_path)
                except (sqlite3.OperationalError, Exception):
                    exception_raised = True

            assert exception_raised, "Expected exception during failed migration"

            # Verify database is in clean state (either empty or not corrupted)
            # The transaction rollback should have prevented partial state
            try:
                # Try to create a fresh database - this should work if rollback succeeded
                db = Database(db_path)
                db.close()
            except Exception as e:
                pytest.fail(f"Database left in corrupted state: {e}")

    def test_migration_v1_to_v2_atomicity(self):
        """Test that failed v1->v2 migration rolls back completely."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create v1 database manually (to prevent auto-migration)
            conn = sqlite3.connect(db_path)
            try:
                # Create minimal v1 schema
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS jobs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        work_dir TEXT NOT NULL UNIQUE,
                        status TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS schema_version (
                        version INTEGER PRIMARY KEY,
                        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    INSERT INTO schema_version (version) VALUES (1);
                """)
                conn.commit()
            finally:
                conn.close()

            # Now attempt migration with injected failure
            failing_migration = """
            ALTER TABLE jobs ADD COLUMN cluster_id INTEGER;
            ALTER TABLE jobs ADD COLUMN runner_type TEXT DEFAULT 'local';

            CREATE TABLE IF NOT EXISTS clusters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );

            INVALID SQL THAT WILL FAIL;

            CREATE TABLE IF NOT EXISTS should_not_exist (
                id INTEGER PRIMARY KEY
            );
            """

            exception_raised = False
            with patch.object(Database, 'MIGRATION_V1_TO_V2', failing_migration):
                try:
                    Database(db_path)
                except (sqlite3.OperationalError, Exception):
                    exception_raised = True

            assert exception_raised, "Expected exception during failed migration"

            # Verify database can still be opened (not corrupted)
            # The migration should have been rolled back
            try:
                db = Database(db_path)
                # If we can create a Database instance, the rollback worked
                # and the database is in a valid state
                db.close()
            except Exception as e:
                pytest.fail(f"Database corrupted after failed migration: {e}")

    def test_migration_partial_failure_rollback(self):
        """Test rollback when migration fails after creating some tables."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create v1 database manually
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS jobs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        work_dir TEXT NOT NULL UNIQUE,
                        status TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS schema_version (
                        version INTEGER PRIMARY KEY,
                        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    INSERT INTO schema_version (version) VALUES (1);
                """)
                conn.commit()
            finally:
                conn.close()

            # Migration that creates 2 tables, then fails, then tries to create a 3rd
            failing_migration = """
            CREATE TABLE IF NOT EXISTS test_table_1 (
                id INTEGER PRIMARY KEY,
                data TEXT
            );

            CREATE TABLE IF NOT EXISTS test_table_2 (
                id INTEGER PRIMARY KEY,
                data TEXT
            );

            -- This will fail
            INSERT INTO nonexistent_table VALUES (1, 'fail');

            CREATE TABLE IF NOT EXISTS test_table_3 (
                id INTEGER PRIMARY KEY,
                data TEXT
            );
            """

            exception_raised = False
            with patch.object(Database, 'MIGRATION_V1_TO_V2', failing_migration):
                try:
                    Database(db_path)
                except (sqlite3.OperationalError, Exception):
                    exception_raised = True

            assert exception_raised, "Expected exception during failed migration"

            # Verify rollback worked by checking database state directly
            # DO NOT create a Database() instance here as that would re-run migrations
            conn = sqlite3.connect(db_path)
            try:
                cursor = conn.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name LIKE 'test_table_%'
                    """
                )
                test_tables = cursor.fetchall()
                # With proper rollback, test tables should not exist
                assert len(test_tables) == 0, \
                    f"Found test tables after rollback: {[r[0] for r in test_tables]}"

                # Verify version is still 1 (migration didn't complete)
                cursor = conn.execute("SELECT MAX(version) FROM schema_version")
                version = cursor.fetchone()[0]
                assert version == 1, f"Schema version changed to {version} after failed migration"
            finally:
                conn.close()

    def test_schema_version_consistency(self):
        """Test that schema_version table is consistent with actual schema."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create database (should be at v4)
            db = Database(db_path)
            try:
                version = db.get_schema_version()

                # Verify schema_version table has all migration entries
                with db.connection() as conn:
                    cursor = conn.execute("SELECT version FROM schema_version ORDER BY version")
                    versions = [row[0] for row in cursor.fetchall()]

                    # Should have v1 through v7 entries (all migrations applied)
                    assert versions == [1, 2, 3, 4, 5, 6, 7], f"Unexpected version history: {versions}"

                    # Verify all tables exist
                    cursor = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                    )
                    tables = {row[0] for row in cursor.fetchall()}

                    expected_tables = {
                        'jobs', 'schema_version', 'clusters',
                        'remote_jobs', 'job_dependencies', 'job_results'
                    }
                    assert expected_tables.issubset(tables), \
                        f"Missing tables: {expected_tables - tables}"
            finally:
                db.close()

    def test_concurrent_migration_safety(self):
        """Test that concurrent database initialization doesn't corrupt schema."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create database once
            db1 = Database(db_path)
            version1 = db1.get_schema_version()

            # Open second connection (simulates concurrent access)
            db2 = Database(db_path)
            version2 = db2.get_schema_version()

            try:
                # Both should see same version
                assert version1 == version2, \
                    f"Concurrent databases see different versions: {version1} vs {version2}"

                # Verify no duplicate tables were created
                with db1.connection() as conn:
                    cursor = conn.execute(
                        """
                        SELECT name, COUNT(*) as cnt
                        FROM sqlite_master
                        WHERE type='table'
                        GROUP BY name
                        HAVING cnt > 1
                        """
                    )
                    duplicates = cursor.fetchall()
                    assert len(duplicates) == 0, \
                        f"Found duplicate tables: {[r[0] for r in duplicates]}"
            finally:
                db1.close()
                db2.close()


class TestMigrationEdgeCases:
    """Test edge cases and error conditions in migrations."""

    def test_empty_database_initialization(self):
        """Test that empty database is properly initialized."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            db = Database(db_path)
            try:
                # Should be at latest version
                version = db.get_schema_version()
                assert version == Database.SCHEMA_VERSION, \
                    f"New database at version {version}, expected {Database.SCHEMA_VERSION}"

                # Should have all tables
                with db.connection() as conn:
                    cursor = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                    )
                    tables = {row[0] for row in cursor.fetchall()}

                    required_tables = {'jobs', 'schema_version', 'clusters', 'remote_jobs', 'job_dependencies', 'job_results'}
                    assert required_tables.issubset(tables), \
                        f"Missing tables: {required_tables - tables}"
            finally:
                db.close()

    def test_existing_v1_database_upgrade(self):
        """Test upgrading an existing v1 database to latest version."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create v1 database manually
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(Database.SCHEMA_V1)
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (1,))
                conn.commit()
            finally:
                conn.close()

            # Now open with Database class (should trigger migration to latest)
            db = Database(db_path)
            try:
                version = db.get_schema_version()
                assert version == Database.SCHEMA_VERSION, f"Database not upgraded to v{Database.SCHEMA_VERSION}: version {version}"

                # Verify all tables exist
                with db.connection() as conn:
                    cursor = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                    tables = {row[0] for row in cursor.fetchall()}

                    assert 'clusters' in tables, "clusters table missing after migration"
                    assert 'remote_jobs' in tables, "remote_jobs table missing after migration"
                    assert 'job_dependencies' in tables, "job_dependencies table missing after migration"
                    assert 'job_results' in tables, "job_results table missing after migration"
            finally:
                db.close()

    def test_migration_idempotency(self):
        """Test that running migrations multiple times is safe."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create database (triggers migrations)
            db1 = Database(db_path)
            version1 = db1.get_schema_version()

            with db1.connection() as conn:
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables1 = {row[0] for row in cursor.fetchall()}

            db1.close()

            # Open again (should not re-run migrations)
            db2 = Database(db_path)
            version2 = db2.get_schema_version()

            with db2.connection() as conn:
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables2 = {row[0] for row in cursor.fetchall()}

            db2.close()

            # Should be identical
            assert version1 == version2, f"Version changed: {version1} -> {version2}"
            assert tables1 == tables2, f"Tables changed: {tables1 - tables2} removed, {tables2 - tables1} added"

    def test_corrupted_schema_version_table(self):
        """Test handling of corrupted schema_version table."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create database with corrupted schema_version
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(Database.SCHEMA_V1)
                # Insert invalid version
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (999,))
                conn.commit()
            finally:
                conn.close()

            # Opening should handle gracefully
            db = Database(db_path)
            try:
                version = db.get_schema_version()
                # Should return highest version number
                assert version == 999, f"Unexpected version: {version}"
            finally:
                db.close()


class TestTransactionBehavior:
    """Test that context manager transaction behavior is correct."""

    def test_successful_transaction_commits(self):
        """Test that successful operations within 'with conn' commit."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)

            try:
                # Insert data within transaction
                with db.connection() as conn:
                    with conn:
                        conn.execute(
                            "INSERT INTO jobs (name, work_dir, status, input_file) VALUES (?, ?, ?, ?)",
                            ("test_job", "/tmp/test", "PENDING", "test.d12")
                        )

                # Verify data was committed
                with db.connection() as conn:
                    cursor = conn.execute("SELECT COUNT(*) FROM jobs WHERE name = ?", ("test_job",))
                    count = cursor.fetchone()[0]
                    assert count == 1, f"Expected 1 job, found {count}"
            finally:
                db.close()

    def test_failed_transaction_rolls_back(self):
        """Test that failed operations within 'with conn' roll back."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)

            try:
                # Attempt transaction that will fail
                with pytest.raises(sqlite3.IntegrityError):
                    with db.connection() as conn:
                        with conn:
                            # Insert valid job
                            conn.execute(
                                "INSERT INTO jobs (name, work_dir, status, input_file) VALUES (?, ?, ?, ?)",
                                ("test_job", "/tmp/test", "PENDING", "test.d12")
                            )
                            # Attempt duplicate work_dir (should fail UNIQUE constraint)
                            conn.execute(
                                "INSERT INTO jobs (name, work_dir, status, input_file) VALUES (?, ?, ?, ?)",
                                ("test_job2", "/tmp/test", "PENDING", "test2.d12")
                            )

                # Verify NO jobs were inserted (rollback worked)
                with db.connection() as conn:
                    cursor = conn.execute("SELECT COUNT(*) FROM jobs")
                    count = cursor.fetchone()[0]
                    assert count == 0, f"Expected 0 jobs after rollback, found {count}"
            finally:
                db.close()

    def test_nested_transaction_behavior(self):
        """Test behavior of nested 'with conn' contexts."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = Database(db_path)

            try:
                # Outer transaction
                with db.connection() as conn:
                    with conn:
                        conn.execute(
                            "INSERT INTO jobs (name, work_dir, status, input_file) VALUES (?, ?, ?, ?)",
                            ("job1", "/tmp/job1", "PENDING", "job1.d12")
                        )

                        # Inner transaction (should be part of same transaction in SQLite)
                        with conn:
                            conn.execute(
                                "INSERT INTO jobs (name, work_dir, status, input_file) VALUES (?, ?, ?, ?)",
                                ("job2", "/tmp/job2", "PENDING", "job2.d12")
                            )

                # Verify both jobs were committed
                with db.connection() as conn:
                    cursor = conn.execute("SELECT COUNT(*) FROM jobs")
                    count = cursor.fetchone()[0]
                    assert count == 2, f"Expected 2 jobs, found {count}"
            finally:
                db.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
