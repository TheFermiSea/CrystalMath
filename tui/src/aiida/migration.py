"""
SQLite to AiiDA migration utility.

This module provides the DatabaseMigrator class for migrating existing
CRYSTAL-TOOLS TUI job data from SQLite to AiiDA.

The migration preserves:
    - Job metadata (name, creation time)
    - Input files
    - Results (stored as extras)
    - Status history

Example:
    >>> from src.aiida.migration import DatabaseMigrator
    >>> migrator = DatabaseMigrator(
    ...     sqlite_path="~/.crystal_tui/jobs.db",
    ...     aiida_profile="crystal-tui"
    ... )
    >>> migrator.migrate_all()
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiida.orm import Node


class DatabaseMigrator:
    """
    Migrate TUI SQLite jobs to AiiDA nodes.

    Jobs are migrated as Dict nodes with full metadata preserved
    in extras. The migration is non-destructive - the SQLite
    database is not modified.

    Attributes:
        sqlite_path: Path to SQLite database.
        aiida_profile: AiiDA profile name.
        dry_run: If True, don't actually create nodes.
    """

    def __init__(
        self,
        sqlite_path: str | Path,
        aiida_profile: str = "crystal-tui",
        dry_run: bool = False,
    ):
        """
        Initialize migrator.

        Args:
            sqlite_path: Path to SQLite database.
            aiida_profile: AiiDA profile to load.
            dry_run: If True, simulate migration without creating nodes.
        """
        self.sqlite_path = Path(sqlite_path).expanduser()
        self.aiida_profile = aiida_profile
        self.dry_run = dry_run
        self._profile_loaded = False

        # Migration statistics
        self.stats = {
            "jobs_found": 0,
            "jobs_migrated": 0,
            "jobs_skipped": 0,
            "jobs_failed": 0,
            "clusters_migrated": 0,
            "workflows_migrated": 0,
        }

    def _ensure_profile(self) -> None:
        """Load AiiDA profile if not already loaded."""
        if not self._profile_loaded and not self.dry_run:
            from aiida import load_profile

            load_profile(self.aiida_profile)
            self._profile_loaded = True

    def _get_connection(self) -> sqlite3.Connection:
        """Get SQLite database connection."""
        if not self.sqlite_path.exists():
            raise FileNotFoundError(f"Database not found: {self.sqlite_path}")

        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def migrate_all(self, skip_failed: bool = True) -> dict:
        """
        Migrate all data from SQLite to AiiDA.

        Args:
            skip_failed: If True, continue on individual failures.

        Returns:
            Migration statistics dictionary.
        """
        self._ensure_profile()

        print(f"Starting migration from {self.sqlite_path}")
        print(f"AiiDA profile: {self.aiida_profile}")
        print(f"Dry run: {self.dry_run}")
        print("-" * 50)

        # Migrate clusters first (they're referenced by jobs)
        self.migrate_clusters()

        # Migrate jobs
        self.migrate_jobs(skip_failed=skip_failed)

        # Migrate workflows
        self.migrate_workflows(skip_failed=skip_failed)

        # Print summary
        self._print_summary()

        return self.stats

    def migrate_jobs(self, skip_failed: bool = True) -> None:
        """Migrate all jobs from SQLite."""
        conn = self._get_connection()

        try:
            cursor = conn.execute("""
                SELECT id, name, status, runner_type, cluster_id,
                       input_content, results_json, work_dir,
                       created_at, updated_at
                FROM jobs
                ORDER BY id
            """)

            for row in cursor:
                self.stats["jobs_found"] += 1
                try:
                    self._migrate_single_job(dict(row))
                    self.stats["jobs_migrated"] += 1
                except Exception as e:
                    self.stats["jobs_failed"] += 1
                    print(f"  ERROR migrating job {row['id']}: {e}")
                    if not skip_failed:
                        raise

        finally:
            conn.close()

    def _migrate_single_job(self, job_data: dict) -> "Node | None":
        """
        Migrate a single job to AiiDA.

        Args:
            job_data: Job row from SQLite.

        Returns:
            Created AiiDA node or None if dry run.
        """
        job_id = job_data["id"]
        job_name = job_data["name"] or f"Job {job_id}"

        print(f"  Migrating job {job_id}: {job_name}...", end=" ")

        if self.dry_run:
            print("[DRY RUN]")
            return None

        from aiida import orm

        # Create input file node if content exists
        input_file = None
        if job_data.get("input_content"):
            input_file = orm.SinglefileData.from_string(
                job_data["input_content"],
                filename="INPUT",
            )
            input_file.label = f"{job_name}_input"
            input_file.store()

        # Create metadata node
        metadata = orm.Dict(dict={
            "migrated_from": "sqlite",
            "original_id": job_id,
            "name": job_name,
            "status": job_data.get("status", "unknown"),
            "runner_type": job_data.get("runner_type", "local"),
            "cluster_id": job_data.get("cluster_id"),
            "work_dir": job_data.get("work_dir"),
            "created_at": job_data.get("created_at"),
            "updated_at": job_data.get("updated_at"),
        })
        metadata.label = job_name
        metadata.description = f"Migrated from SQLite job ID {job_id}"

        # Store results in extras
        if job_data.get("results_json"):
            try:
                results = json.loads(job_data["results_json"])
                metadata.base.extras.set("tui_results", results)
            except json.JSONDecodeError:
                pass

        # Link to input file if created
        if input_file:
            metadata.base.extras.set("input_file_pk", input_file.pk)

        metadata.store()

        print(f"OK (PK: {metadata.pk})")
        return metadata

    def migrate_clusters(self) -> None:
        """Migrate cluster configurations to AiiDA computers."""
        conn = self._get_connection()

        try:
            # Check if clusters table exists
            cursor = conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='clusters'
            """)
            if not cursor.fetchone():
                print("No clusters table found, skipping cluster migration")
                return

            cursor = conn.execute("""
                SELECT id, name, hostname, username, queue_type, max_concurrent
                FROM clusters
                ORDER BY id
            """)

            for row in cursor:
                try:
                    self._migrate_single_cluster(dict(row))
                    self.stats["clusters_migrated"] += 1
                except Exception as e:
                    print(f"  WARNING: Could not migrate cluster {row['name']}: {e}")

        finally:
            conn.close()

    def _migrate_single_cluster(self, cluster_data: dict) -> None:
        """
        Migrate a cluster to AiiDA computer.

        Note: This creates a basic computer entry that may need
        manual configuration for SSH credentials.

        Args:
            cluster_data: Cluster row from SQLite.
        """
        cluster_name = cluster_data["name"]
        hostname = cluster_data.get("hostname", "localhost")

        print(f"  Migrating cluster '{cluster_name}' ({hostname})...", end=" ")

        if self.dry_run:
            print("[DRY RUN]")
            return

        from aiida import orm

        # Check if computer already exists
        try:
            existing = orm.Computer.collection.get(label=cluster_name)
            print(f"SKIPPED (exists as PK {existing.pk})")
            self.stats["jobs_skipped"] += 1
            return
        except Exception:
            pass

        # Map queue type to scheduler
        queue_type = cluster_data.get("queue_type", "direct")
        scheduler_map = {
            "slurm": "core.slurm",
            "pbs": "core.pbspro",
            "sge": "core.sge",
            "direct": "core.direct",
        }
        scheduler_type = scheduler_map.get(queue_type, "core.direct")

        # Determine transport type
        transport_type = "core.local" if hostname == "localhost" else "core.ssh"

        # Create computer
        computer = orm.Computer(
            label=cluster_name,
            hostname=hostname,
            description=f"Migrated from TUI cluster ID {cluster_data['id']}",
            transport_type=transport_type,
            scheduler_type=scheduler_type,
            workdir=f"/home/{cluster_data.get('username', 'user')}/aiida_work/",
        )
        computer.store()

        # Store original metadata in extras
        computer.base.extras.set("migrated_from", "sqlite")
        computer.base.extras.set("original_id", cluster_data["id"])
        computer.base.extras.set("original_username", cluster_data.get("username"))
        computer.base.extras.set("max_concurrent", cluster_data.get("max_concurrent", 10))

        print(f"OK (PK: {computer.pk})")
        print(f"    NOTE: Computer requires configuration: verdi computer configure {cluster_name}")

    def migrate_workflows(self, skip_failed: bool = True) -> None:
        """Migrate workflow definitions."""
        conn = self._get_connection()

        try:
            # Check if workflows table exists
            cursor = conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='workflows'
            """)
            if not cursor.fetchone():
                print("No workflows table found, skipping workflow migration")
                return

            cursor = conn.execute("""
                SELECT id, name, dag_json, status, created_at
                FROM workflows
                ORDER BY id
            """)

            for row in cursor:
                try:
                    self._migrate_single_workflow(dict(row))
                    self.stats["workflows_migrated"] += 1
                except Exception as e:
                    print(f"  WARNING: Could not migrate workflow {row['name']}: {e}")
                    if not skip_failed:
                        raise

        finally:
            conn.close()

    def _migrate_single_workflow(self, workflow_data: dict) -> "Node | None":
        """Migrate a workflow definition to AiiDA."""
        workflow_name = workflow_data["name"]

        print(f"  Migrating workflow '{workflow_name}'...", end=" ")

        if self.dry_run:
            print("[DRY RUN]")
            return None

        from aiida import orm

        # Store workflow as Dict node with DAG preserved
        try:
            dag = json.loads(workflow_data.get("dag_json", "{}"))
        except json.JSONDecodeError:
            dag = {}

        workflow_node = orm.Dict(dict={
            "migrated_from": "sqlite",
            "original_id": workflow_data["id"],
            "name": workflow_name,
            "dag": dag,
            "status": workflow_data.get("status", "unknown"),
            "created_at": workflow_data.get("created_at"),
        })
        workflow_node.label = f"workflow_{workflow_name}"
        workflow_node.description = f"Migrated workflow from SQLite"
        workflow_node.store()

        print(f"OK (PK: {workflow_node.pk})")
        return workflow_node

    def _print_summary(self) -> None:
        """Print migration summary."""
        print("-" * 50)
        print("Migration Summary:")
        print(f"  Jobs found:      {self.stats['jobs_found']}")
        print(f"  Jobs migrated:   {self.stats['jobs_migrated']}")
        print(f"  Jobs skipped:    {self.stats['jobs_skipped']}")
        print(f"  Jobs failed:     {self.stats['jobs_failed']}")
        print(f"  Clusters:        {self.stats['clusters_migrated']}")
        print(f"  Workflows:       {self.stats['workflows_migrated']}")
        print("-" * 50)

        if self.dry_run:
            print("DRY RUN - No data was actually migrated")

    def verify_migration(self) -> dict:
        """
        Verify that migration was successful.

        Returns:
            Dictionary with verification results.
        """
        self._ensure_profile()
        from aiida import orm

        results = {
            "migrated_nodes": 0,
            "jobs_with_input": 0,
            "jobs_with_results": 0,
            "computers_configured": 0,
        }

        # Count migrated nodes
        qb = orm.QueryBuilder()
        qb.append(orm.Dict, filters={"extras.migrated_from": "sqlite"})
        results["migrated_nodes"] = qb.count()

        # Check input files
        qb = orm.QueryBuilder()
        qb.append(orm.Dict, filters={"extras.input_file_pk": {"!==": None}})
        results["jobs_with_input"] = qb.count()

        # Check results
        qb = orm.QueryBuilder()
        qb.append(orm.Dict, filters={"extras.tui_results": {"!==": None}})
        results["jobs_with_results"] = qb.count()

        # Check computers
        for computer in orm.Computer.collection.all():
            if computer.is_configured:
                results["computers_configured"] += 1

        return results


def main():
    """Command-line interface for migration."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Migrate CRYSTAL-TUI SQLite database to AiiDA"
    )
    parser.add_argument(
        "--sqlite-db",
        type=str,
        default="~/.crystal_tui/jobs.db",
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--aiida-profile",
        type=str,
        default="crystal-tui",
        help="AiiDA profile name",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate migration without creating nodes",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify existing migration",
    )

    args = parser.parse_args()

    migrator = DatabaseMigrator(
        sqlite_path=args.sqlite_db,
        aiida_profile=args.aiida_profile,
        dry_run=args.dry_run,
    )

    if args.verify:
        results = migrator.verify_migration()
        print("Migration Verification:")
        for key, value in results.items():
            print(f"  {key}: {value}")
    else:
        migrator.migrate_all()


if __name__ == "__main__":
    main()
