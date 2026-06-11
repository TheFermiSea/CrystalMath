import json
import logging
import subprocess

from crystalmath.models import SlurmJobModel, SlurmQueueResponse

logger = logging.getLogger("crystalmath.server")


def handle_slurm_queue_request(payload: dict) -> dict:
    """
    Natively parses squeue outputs inside the HPC cluster environment context.
    Bypasses local frontend command dependencies to fulfill ADR-006.
    """
    try:
        # Run squeue JSON telemetry export via local process loop forks
        res = subprocess.run(
            ["squeue", "--all", "--json"], capture_output=True, text=True, check=True
        )
        raw_data = json.loads(res.stdout)

        parsed_jobs = []
        # Safely parse Slurm's standard core scheduler output matrix
        for raw_job in raw_data.get("jobs", []):
            parsed_jobs.append(
                SlurmJobModel(
                    job_id=raw_job.get("job_id"),
                    partition=raw_job.get("partition"),
                    name=raw_job.get("name"),
                    user=raw_job.get("user_name"),
                    state=raw_job.get("job_state"),
                    time_used=raw_job.get("time_used", "0:00"),
                    stdout_path=raw_job.get("standard_output", ""),
                )
            )

        return SlurmQueueResponse(success=True, jobs=parsed_jobs).model_dump()
    except Exception as e:
        logger.error(f"Failed to fetch Slurm metrics from cluster controller: {str(e)}")
        return SlurmQueueResponse(success=False, jobs=[], error_message=str(e)).model_dump()
