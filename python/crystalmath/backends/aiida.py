"""
AiiDA ORM backend for job storage and execution.

Requires AiiDA to be installed and configured with a profile.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from crystalmath.backends import Backend
from crystalmath.models import (
    DftCode,
    JobDetails,
    JobState,
    JobStatus,
    JobSubmission,
    RunnerType,
)

logger = logging.getLogger(__name__)


class AiiDABackend(Backend):
    """
    AiiDA ORM backend for production HPC workflows.

    Uses AiiDA's QueryBuilder for job queries and its engine for submission.
    """

    def __init__(self, profile_name: str = "default") -> None:
        self._profile_name = profile_name
        self._available = False
        self._aiida: Any = None
        self._orm: Any = None
        self._init_aiida()

    def _init_aiida(self) -> None:
        """Initialize AiiDA profile."""
        try:
            import aiida
            from aiida import orm

            aiida.load_profile(self._profile_name)
            self._aiida = aiida
            self._orm = orm
            self._available = True
            logger.info(f"Loaded AiiDA profile: {self._profile_name}")

        except ImportError:
            logger.info("AiiDA not installed - backend unavailable")
            self._available = False
        except Exception as e:
            logger.warning(f"Failed to load AiiDA profile '{self._profile_name}': {e}")
            self._available = False

    @property
    def name(self) -> str:
        return "aiida"

    @property
    def is_available(self) -> bool:
        return self._available

    def _map_process_state(self, state: str, exit_status: Optional[int]) -> JobState:
        """Map AiiDA process state to JobState."""
        if state == "finished":
            return JobState.COMPLETED if exit_status == 0 else JobState.FAILED
        elif state in ("excepted", "killed"):
            return JobState.FAILED
        elif state == "running":
            return JobState.RUNNING
        elif state == "waiting":
            return JobState.QUEUED
        else:
            return JobState.CREATED

    def get_jobs(self, limit: int = 100) -> List[JobStatus]:
        """Query AiiDA for job list."""
        if not self._available or not self._orm:
            return []

        try:
            from aiida import orm

            qb = orm.QueryBuilder()
            qb.append(
                orm.CalcJobNode,
                project=[
                    "id",
                    "uuid",
                    "label",
                    "attributes.process_state",
                    "attributes.exit_status",
                    "ctime",
                ],
            )
            qb.order_by({orm.CalcJobNode: {"ctime": "desc"}})
            qb.limit(limit)

            results: List[JobStatus] = []
            for pk, uuid, label, state, exit_status, ctime in qb.all():
                ui_state = self._map_process_state(state, exit_status)

                results.append(
                    JobStatus(
                        pk=pk,
                        uuid=uuid,
                        name=label or f"Job {pk}",
                        state=ui_state,
                        dft_code=DftCode.CRYSTAL,  # TODO: detect from node type
                        runner_type=RunnerType.AIIDA,
                        progress_percent=100.0 if ui_state == JobState.COMPLETED else 0.0,
                        created_at=ctime,
                    )
                )

            return results

        except Exception as e:
            logger.error(f"Error querying AiiDA jobs: {e}")
            return []

    def get_job_details(self, pk: int) -> Optional[JobDetails]:
        """Get detailed job info from AiiDA."""
        if not self._available or not self._orm:
            return None

        try:
            from aiida import orm
            from aiida.common import NotExistent

            try:
                node = orm.load_node(pk)
            except NotExistent:
                return None

            # Get output parameters if available
            output_params: Dict[str, Any] = {}
            if "output_parameters" in node.outputs:
                output_params = node.outputs.output_parameters.get_dict()

            # Get stdout
            stdout_lines: List[str] = []
            if "retrieved" in node.outputs:
                try:
                    stdout = node.outputs.retrieved.get_object_content(
                        "_scheduler-stdout.txt"
                    )
                    stdout_lines = stdout.splitlines()[-50:]
                except Exception:
                    pass

            # Map state
            state = node.process_state.value if node.process_state else "created"
            exit_status = node.exit_status
            ui_state = self._map_process_state(state, exit_status)

            return JobDetails(
                pk=pk,
                uuid=str(node.uuid),
                name=node.label or f"Job {pk}",
                state=ui_state,
                final_energy=output_params.get("energy"),
                convergence_met=output_params.get("converged", False),
                scf_cycles=output_params.get("scf_cycles"),
                warnings=[],
                stdout_tail=stdout_lines,
                key_results=output_params,
            )

        except Exception as e:
            logger.error(f"Error getting job details for pk={pk}: {e}")
            return None

    def submit_job(self, submission: JobSubmission) -> int:
        """Submit job to AiiDA."""
        if not self._available or not self._orm:
            raise RuntimeError("AiiDA backend not available")

        try:
            from aiida import orm
            from aiida.engine import submit

            # Try to load crystal code
            try:
                code = orm.load_code("crystal@localhost")
            except Exception:
                raise RuntimeError(
                    "CRYSTAL code not configured in AiiDA. "
                    "Run 'verdi code setup' first."
                )

            # Create a builder
            builder = code.get_builder()
            builder.metadata.label = submission.name
            builder.metadata.options.resources = {
                "num_machines": 1,
                "num_mpiprocs_per_machine": submission.mpi_ranks or 1,
            }

            node = submit(builder)
            return node.pk

        except Exception as e:
            logger.error(f"Failed to submit job: {e}")
            raise RuntimeError(f"AiiDA job submission failed: {e}")

    def cancel_job(self, pk: int) -> bool:
        """Cancel AiiDA job."""
        if not self._available or not self._orm:
            return False

        try:
            from aiida import orm
            from aiida.engine import processes

            node = orm.load_node(pk)
            processes.control.kill_processes([node])
            return True

        except Exception as e:
            logger.error(f"Failed to cancel job {pk}: {e}")
            return False

    def get_job_log(self, pk: int, tail_lines: int = 100) -> Dict[str, List[str]]:
        """Get job logs from AiiDA."""
        if not self._available or not self._orm:
            return {"stdout": [], "stderr": []}

        try:
            from aiida import orm

            node = orm.load_node(pk)
            stdout_lines: List[str] = []
            stderr_lines: List[str] = []

            if "retrieved" in node.outputs:
                try:
                    stdout = node.outputs.retrieved.get_object_content(
                        "_scheduler-stdout.txt"
                    )
                    stdout_lines = stdout.splitlines()[-tail_lines:]
                except Exception:
                    pass
                try:
                    stderr = node.outputs.retrieved.get_object_content(
                        "_scheduler-stderr.txt"
                    )
                    stderr_lines = stderr.splitlines()[-tail_lines:]
                except Exception:
                    pass

            return {"stdout": stdout_lines, "stderr": stderr_lines}

        except Exception:
            return {"stdout": [], "stderr": []}
