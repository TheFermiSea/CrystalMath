"""
AiiDA QueryBuilder adapter for CRYSTAL-TOOLS TUI.

This module provides the AiiDAQueryAdapter class that translates
the existing TUI database interface to AiiDA QueryBuilder queries,
enabling seamless migration from SQLite to AiiDA.

The adapter maintains API compatibility with src/core/database.py,
so TUI screens and widgets require minimal changes.

Example:
    # Replace Database with AiiDAQueryAdapter in TUI code:
    # OLD: from src.core.database import Database
    # NEW: from src.aiida.query_adapter import AiiDAQueryAdapter as Database

    >>> adapter = AiiDAQueryAdapter()
    >>> jobs = adapter.list_jobs(status="running")
    >>> job = adapter.get_job(42)
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from aiida.orm import ProcessNode


class AiiDAQueryAdapter:
    """
    Adapter that translates TUI database calls to AiiDA QueryBuilder queries.

    Maintains compatibility with the existing Database class interface
    in src/core/database.py, allowing gradual migration.

    Attributes:
        profile_name: AiiDA profile to use.
    """

    # Status mapping between TUI and AiiDA
    STATUS_TO_AIIDA = {
        "pending": ["created", "waiting"],
        "queued": ["created", "waiting"],
        "running": ["running"],
        "completed": ["finished"],
        "failed": ["excepted", "killed"],
        "cancelled": ["killed"],
    }

    AIIDA_TO_STATUS = {
        "created": "pending",
        "waiting": "pending",
        "running": "running",
        "finished": "completed",  # Note: check exit_status for actual success
        "excepted": "failed",
        "killed": "cancelled",
    }

    def __init__(self, profile_name: str = "crystal-tui"):
        """
        Initialize AiiDA adapter.

        Args:
            profile_name: AiiDA profile to load.
        """
        self.profile_name = profile_name
        self._profile_loaded = False

    def _ensure_profile(self) -> None:
        """Load AiiDA profile if not already loaded."""
        if not self._profile_loaded:
            from aiida import load_profile

            load_profile(self.profile_name)
            self._profile_loaded = True

    def list_jobs(
        self,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        List jobs from AiiDA database.

        Replaces database.list_jobs().

        Args:
            status: Filter by status ('pending', 'running', 'completed', 'failed').
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            List of job dictionaries with keys:
                - id: Node PK
                - name: Node label
                - status: Mapped status string
                - created_at: Creation timestamp
                - updated_at: Modification timestamp
                - runner_type: Always 'aiida' for AiiDA jobs
        """
        self._ensure_profile()
        from aiida.orm import CalcJobNode, QueryBuilder, WorkChainNode

        qb = QueryBuilder()

        # Query both CalcJobs and WorkChains
        qb.append(
            (CalcJobNode, WorkChainNode),
            tag="process",
            project=["id", "label", "ctime", "mtime", "attributes.process_state"],
        )

        # Filter by status
        if status:
            aiida_states = self.STATUS_TO_AIIDA.get(status, [status])
            qb.add_filter(
                "process",
                {"attributes.process_state": {"in": aiida_states}},
            )

        # Order by creation time (newest first)
        qb.order_by({"process": {"ctime": "desc"}})

        # Pagination
        if limit:
            qb.limit(limit)
        if offset:
            qb.offset(offset)

        jobs = []
        for pk, label, ctime, mtime, process_state in qb.all():
            jobs.append(
                {
                    "id": pk,
                    "name": label or f"Job {pk}",
                    "status": self._map_status(process_state, pk),
                    "created_at": ctime,
                    "updated_at": mtime,
                    "runner_type": "aiida",
                }
            )

        return jobs

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        """
        Get detailed job information by ID.

        Replaces database.get_job().

        Args:
            job_id: Job ID (AiiDA node PK).

        Returns:
            Job dictionary or None if not found.
        """
        self._ensure_profile()
        from aiida import orm

        try:
            node = orm.load_node(job_id)
        except Exception as e:
            logger.debug("Failed to load node %s: %s", job_id, e)
            return None

        # Only accept calculation/workflow nodes
        if not isinstance(node, (orm.CalcJobNode, orm.WorkChainNode)):
            return None

        # Extract input content (d12 file)
        input_content = self._extract_input_content(node)

        # Extract results
        results_json = self._extract_results(node)

        # Get work directory
        work_dir = None
        if hasattr(node, "get_remote_workdir"):
            try:
                work_dir = node.get_remote_workdir()
            except Exception as e:
                logger.debug("Failed to get remote workdir: %s", e)

        return {
            "id": node.pk,
            "name": node.label or f"Job {node.pk}",
            "status": self._map_status(node.process_state.value, node.pk),
            "input_content": input_content,
            "results_json": results_json,
            "work_dir": work_dir,
            "created_at": node.ctime,
            "updated_at": node.mtime,
            "runner_type": "aiida",
            "cluster_id": None,  # AiiDA uses computers, not cluster_id
            "computer": node.computer.label
            if hasattr(node, "computer") and node.computer
            else None,
        }

    def create_job(
        self,
        name: str,
        input_content: str,
        runner_type: str = "aiida",
        cluster_id: int | None = None,
        **kwargs: Any,
    ) -> int:
        """
        Create a new job.

        For AiiDA, this creates a CalcJobNode in 'created' state.
        The job must be submitted separately using engine.submit().

        Args:
            name: Job name/label.
            input_content: CRYSTAL23 input file content (d12 format).
            runner_type: Ignored (always 'aiida').
            cluster_id: Ignored (use AiiDA computer instead).
            **kwargs: Additional parameters.

        Returns:
            Node PK of the created job.
        """
        self._ensure_profile()
        from aiida import orm

        # Store input as SinglefileData
        input_file = orm.SinglefileData.from_string(
            input_content,
            filename="INPUT",
        )
        input_file.label = f"{name}_input"
        input_file.store()

        # Create a simple Dict node to hold job metadata
        # The actual CalcJob will be created when submitted
        metadata = orm.Dict(
            dict={
                "name": name,
                "input_file_pk": input_file.pk,
                "created_via": "crystal-tui",
                "status": "draft",
            }
        )
        metadata.label = name
        metadata.store()

        return metadata.pk

    def update_job(
        self,
        job_id: int,
        status: str | None = None,
        results_json: str | None = None,
        **kwargs: Any,
    ) -> bool:
        """
        Update job status/results.

        In AiiDA, job status is managed automatically by the engine.
        This method is a no-op for status updates but can add extras.

        Args:
            job_id: Job ID (node PK).
            status: Ignored (AiiDA manages status).
            results_json: Results to store in extras.
            **kwargs: Additional fields to update.

        Returns:
            True if update successful.
        """
        self._ensure_profile()
        from aiida import orm

        try:
            node = orm.load_node(job_id)
        except Exception:
            return False

        # Store additional data in extras
        if results_json:
            node.base.extras.set("tui_results", results_json)

        for key, value in kwargs.items():
            if value is not None:
                node.base.extras.set(f"tui_{key}", value)

        return True

    def delete_job(self, job_id: int) -> bool:
        """
        Delete a job.

        In AiiDA, nodes are typically not deleted to preserve provenance.
        This marks the job as 'hidden' in extras instead.

        Args:
            job_id: Job ID (node PK).

        Returns:
            True if marked as hidden.
        """
        self._ensure_profile()
        from aiida import orm

        try:
            node = orm.load_node(job_id)
            node.base.extras.set("tui_hidden", True)
            return True
        except Exception:
            return False

    def get_job_count(self, status: str | None = None) -> int:
        """
        Get count of jobs by status.

        Args:
            status: Filter by status.

        Returns:
            Number of matching jobs.
        """
        self._ensure_profile()
        from aiida.orm import CalcJobNode, QueryBuilder, WorkChainNode

        qb = QueryBuilder()
        qb.append(
            (CalcJobNode, WorkChainNode),
            tag="process",
        )

        if status:
            aiida_states = self.STATUS_TO_AIIDA.get(status, [status])
            qb.add_filter(
                "process",
                {"attributes.process_state": {"in": aiida_states}},
            )

        return qb.count()

    def list_clusters(self) -> list[dict[str, Any]]:
        """
        List configured clusters/computers.

        Maps AiiDA Computers to the TUI cluster interface.

        Returns:
            List of cluster dictionaries.
        """
        self._ensure_profile()
        from aiida.orm import Computer

        clusters = []
        for computer in Computer.collection.all():
            clusters.append(
                {
                    "id": computer.pk,
                    "name": computer.label,
                    "hostname": computer.hostname,
                    "username": computer.get_property("default_mpiprocs_per_machine", "N/A"),
                    "queue_type": computer.scheduler_type.replace("core.", ""),
                    "max_concurrent": 10,  # Default
                }
            )

        return clusters

    def _map_status(self, process_state: str, node_pk: int | None = None) -> str:
        """
        Map AiiDA process state to TUI status.

        Args:
            process_state: AiiDA process state.
            node_pk: Node PK (to check exit_status for completed jobs).

        Returns:
            TUI status string.
        """
        if process_state == "finished" and node_pk is not None:
            # Check if actually successful
            from aiida import orm

            try:
                node = orm.load_node(node_pk)
                if hasattr(node, "exit_status") and node.exit_status != 0:
                    return "failed"
            except Exception:
                pass

        return self.AIIDA_TO_STATUS.get(process_state, "unknown")

    def _extract_input_content(self, node: ProcessNode) -> str:
        """
        Extract d12 input content from node inputs.

        Args:
            node: AiiDA process node.

        Returns:
            Input file content or empty string.
        """
        try:
            # Try to get from crystal.input_file
            if hasattr(node.inputs, "crystal"):
                crystal_inputs = node.inputs.crystal
                if hasattr(crystal_inputs, "input_file"):
                    return crystal_inputs.input_file.get_content()

            # Try to get from retrieved files
            if hasattr(node, "outputs") and hasattr(node.outputs, "retrieved"):
                try:
                    return node.outputs.retrieved.get_object_content("INPUT")
                except FileNotFoundError:
                    pass

        except Exception:
            pass

        return ""

    def _extract_results(self, node: ProcessNode) -> str:
        """
        Extract results JSON from node outputs.

        Args:
            node: AiiDA process node.

        Returns:
            JSON string of results.
        """
        try:
            # Try output_parameters
            if hasattr(node, "outputs") and hasattr(node.outputs, "output_parameters"):
                return json.dumps(node.outputs.output_parameters.get_dict())

            # Try extras
            extras = node.base.extras.all
            if "tui_results" in extras:
                return extras["tui_results"]

        except Exception:
            pass

        return "{}"


# Convenience alias for drop-in replacement
Database = AiiDAQueryAdapter
