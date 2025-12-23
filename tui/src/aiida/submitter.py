"""
AiiDA WorkChain submitter for CRYSTAL-TOOLS TUI.

This module provides the AiiDASubmitter class that handles
job submission through AiiDA's workflow engine.

Replaces the functionality in:
    - src/core/orchestrator.py
    - src/runners/local.py
    - src/runners/ssh_runner.py
    - src/runners/slurm_runner.py

Example:
    >>> from src.aiida.submitter import AiiDASubmitter
    >>>
    >>> submitter = AiiDASubmitter()
    >>> job_pk = await submitter.submit_job(
    ...     name="MgO SCF",
    ...     input_content="CRYSTAL\n...",
    ...     code_label="crystalOMP@localhost",
    ... )
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiida.orm import Node


class AiiDASubmitter:
    """
    Job submitter using AiiDA WorkChains.

    Provides an async interface compatible with the TUI's
    existing submission patterns.

    Attributes:
        profile_name: AiiDA profile to use.
    """

    def __init__(self, profile_name: str = "crystal-tui"):
        """
        Initialize submitter.

        Args:
            profile_name: AiiDA profile name.
        """
        self.profile_name = profile_name
        self._profile_loaded = False

    def _ensure_profile(self) -> None:
        """Load AiiDA profile if not already loaded."""
        if not self._profile_loaded:
            from aiida import load_profile

            load_profile(self.profile_name)
            self._profile_loaded = True

    async def submit_job(
        self,
        name: str,
        input_content: str,
        code_label: str = "crystalOMP@localhost",
        structure_data: dict | None = None,
        parameters: dict | None = None,
        optimization: bool = False,
        resources: dict | None = None,
    ) -> int:
        """
        Submit a CRYSTAL23 job via AiiDA.

        Args:
            name: Job name/label.
            input_content: CRYSTAL23 d12 input file content.
            code_label: AiiDA code label (e.g., "crystalOMP@localhost").
            structure_data: Structure data dict (alternative to input_content).
            parameters: Calculation parameters (used with structure_data).
            optimization: If True, use geometry optimization WorkChain.
            resources: Computational resources (num_machines, walltime, etc.).

        Returns:
            AiiDA node PK of submitted WorkChain.
        """
        self._ensure_profile()

        from aiida import engine, orm

        # Load code
        try:
            code = orm.load_code(code_label)
        except Exception as e:
            raise RuntimeError(f"Code '{code_label}' not found: {e}")

        # Determine submission method
        if structure_data:
            # Submit with structured inputs
            return await self._submit_structured(
                name=name,
                code=code,
                structure_data=structure_data,
                parameters=parameters or {},
                optimization=optimization,
                resources=resources,
            )
        else:
            # Submit with raw input file
            return await self._submit_raw(
                name=name,
                code=code,
                input_content=input_content,
                optimization=optimization,
                resources=resources,
            )

    async def _submit_raw(
        self,
        name: str,
        code: "Node",
        input_content: str,
        optimization: bool,
        resources: dict | None,
    ) -> int:
        """Submit job with raw input file."""
        from aiida import engine, orm

        from src.aiida.calcjobs.crystal23 import Crystal23Calculation

        # Create input file node
        input_file = orm.SinglefileData.from_string(
            input_content,
            filename="INPUT",
        )

        # Build inputs
        inputs = {
            "code": code,
            "crystal": {
                "input_file": input_file,
            },
            "metadata": {
                "label": name,
                "description": f"CRYSTAL23 calculation: {name}",
                "options": self._build_options(resources),
            },
        }

        # Submit (run in thread pool to avoid blocking)
        loop = asyncio.get_event_loop()
        node = await loop.run_in_executor(
            None,
            lambda: engine.submit(Crystal23Calculation, **inputs),
        )

        return node.pk

    async def _submit_structured(
        self,
        name: str,
        code: "Node",
        structure_data: dict,
        parameters: dict,
        optimization: bool,
        resources: dict | None,
    ) -> int:
        """Submit job with structured inputs."""
        from aiida import engine, orm

        # Convert structure data to StructureData
        structure = self._create_structure(structure_data)

        # Choose WorkChain
        if optimization:
            from src.aiida.workchains.crystal_geopt import (
                CrystalGeometryOptimizationWorkChain,
            )

            WorkChainClass = CrystalGeometryOptimizationWorkChain
        else:
            from src.aiida.workchains.crystal_base import CrystalBaseWorkChain

            WorkChainClass = CrystalBaseWorkChain

        # Build inputs
        inputs = {
            "structure": structure,
            "parameters": orm.Dict(dict=parameters),
            "code": code,
            "options": orm.Dict(dict=self._build_options(resources)),
        }

        # Add optimization-specific inputs
        if optimization:
            opt_mode = parameters.get("optgeom", {}).get("mode", "fulloptg")
            inputs["optimization_mode"] = orm.Str(opt_mode)

        # Submit
        loop = asyncio.get_event_loop()
        node = await loop.run_in_executor(
            None,
            lambda: engine.submit(WorkChainClass, **inputs),
        )

        return node.pk

    def _create_structure(self, data: dict) -> "Node":
        """Create StructureData from dictionary."""
        from aiida import orm

        cell = data.get("cell", [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        structure = orm.StructureData(cell=cell)

        for atom in data.get("atoms", []):
            structure.append_atom(
                position=atom.get("position", [0, 0, 0]),
                symbols=atom.get("symbol", "H"),
            )

        return structure

    def _build_options(self, resources: dict | None) -> dict:
        """Build calculation options with defaults."""
        options = {
            "resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1},
            "max_wallclock_seconds": 3600,
            "withmpi": False,
        }

        if resources:
            if "num_machines" in resources:
                options["resources"]["num_machines"] = resources["num_machines"]
            if "num_mpiprocs" in resources:
                options["resources"]["num_mpiprocs_per_machine"] = resources[
                    "num_mpiprocs"
                ]
            if "walltime" in resources:
                options["max_wallclock_seconds"] = resources["walltime"]
            if "withmpi" in resources:
                options["withmpi"] = resources["withmpi"]

        return options

    async def get_status(self, job_pk: int) -> dict:
        """
        Get job status.

        Args:
            job_pk: AiiDA node PK.

        Returns:
            Status dictionary with keys:
                - status: TUI status string
                - process_state: AiiDA process state
                - exit_status: Exit code (if finished)
                - exit_message: Exit message (if failed)
        """
        self._ensure_profile()
        from aiida import orm

        try:
            node = orm.load_node(job_pk)
        except Exception:
            return {"status": "unknown", "error": "Node not found"}

        # Map process state to TUI status
        state = node.process_state.value if node.process_state else "unknown"
        status_map = {
            "created": "pending",
            "waiting": "pending",
            "running": "running",
            "finished": "completed",
            "excepted": "failed",
            "killed": "cancelled",
        }
        tui_status = status_map.get(state, "unknown")

        # Check if actually failed (finished with non-zero exit)
        if state == "finished" and hasattr(node, "exit_status"):
            if node.exit_status != 0:
                tui_status = "failed"

        result = {
            "status": tui_status,
            "process_state": state,
        }

        if hasattr(node, "exit_status"):
            result["exit_status"] = node.exit_status
        if hasattr(node, "exit_message"):
            result["exit_message"] = node.exit_message

        return result

    async def get_output(self, job_pk: int) -> str:
        """
        Get job output content.

        Args:
            job_pk: AiiDA node PK.

        Returns:
            Output file content or empty string.
        """
        self._ensure_profile()
        from aiida import orm

        try:
            node = orm.load_node(job_pk)

            if hasattr(node, "outputs") and hasattr(node.outputs, "retrieved"):
                try:
                    return node.outputs.retrieved.get_object_content("OUTPUT")
                except FileNotFoundError:
                    pass

        except Exception:
            pass

        return ""

    async def cancel_job(self, job_pk: int) -> bool:
        """
        Cancel a running job.

        Args:
            job_pk: AiiDA node PK.

        Returns:
            True if cancellation was requested.
        """
        self._ensure_profile()
        from aiida import engine, orm

        try:
            node = orm.load_node(job_pk)

            if node.process_state.value in ["created", "waiting", "running"]:
                # Request kill through AiiDA
                engine.process.Process.kill(node)
                return True

        except Exception:
            pass

        return False

    def list_codes(self) -> list[dict]:
        """
        List available CRYSTAL23 codes.

        Returns:
            List of code info dictionaries.
        """
        self._ensure_profile()
        from aiida.orm import Code, QueryBuilder

        codes = []
        qb = QueryBuilder()
        qb.append(Code, project=["label", "description"])

        for label, description in qb.all():
            if "crystal" in label.lower():
                codes.append({
                    "label": label,
                    "description": description,
                })

        return codes

    def list_computers(self) -> list[dict]:
        """
        List available computers.

        Returns:
            List of computer info dictionaries.
        """
        self._ensure_profile()
        from aiida.orm import Computer

        computers = []
        for computer in Computer.collection.all():
            computers.append({
                "label": computer.label,
                "hostname": computer.hostname,
                "scheduler": computer.scheduler_type,
                "is_configured": computer.is_configured,
            })

        return computers
