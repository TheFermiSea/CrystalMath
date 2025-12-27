"""
TUI message classes for inter-component communication.

This module defines custom Textual messages used for communication
between different parts of the application (screens, widgets, workers).
"""

from typing import Optional, Dict, Any
from textual.message import Message


class JobProgressUpdate(Message):
    """
    Message posted when job progress is updated (VASP calculations).

    Attributes:
        job_id: Database ID of the job
        job_handle: Runner job handle
        progress_data: Progress information dictionary
        status_text: Human-readable status summary
    """

    def __init__(
        self,
        job_id: int,
        job_handle: str,
        progress_data: Dict[str, Any],
        status_text: str
    ):
        self.job_id = job_id
        self.job_handle = job_handle
        self.progress_data = progress_data
        self.status_text = status_text
        super().__init__()


class JobStatusChanged(Message):
    """
    Message posted when job status changes.

    Attributes:
        job_id: Database ID of the job
        old_status: Previous status
        new_status: New status
        job_handle: Runner job handle (optional)
    """

    def __init__(
        self,
        job_id: int,
        old_status: str,
        new_status: str,
        job_handle: Optional[str] = None
    ):
        self.job_id = job_id
        self.old_status = old_status
        self.new_status = new_status
        self.job_handle = job_handle
        super().__init__()


class JobCompleted(Message):
    """
    Message posted when a job completes (success or failure).

    Attributes:
        job_id: Database ID of the job
        success: Whether job completed successfully
        job_handle: Runner job handle
    """

    def __init__(self, job_id: int, success: bool, job_handle: str):
        self.job_id = job_id
        self.success = success
        self.job_handle = job_handle
        super().__init__()


class QueueUpdated(Message):
    """
    Message posted when SLURM queue data is updated.

    Used by SLURMQueueWidget to notify of queue refresh completion.

    Attributes:
        jobs: List of job dictionaries from SLURMRunner.get_queue_status()
    """

    def __init__(self, jobs: list[Dict[str, Any]]):
        self.jobs = jobs
        super().__init__()


class JobCancelled(Message):
    """
    Message posted when a SLURM job is cancelled.

    Attributes:
        slurm_job_id: SLURM job ID that was cancelled
        success: Whether cancellation succeeded
        message: Status message (error reason if failed)
    """

    def __init__(self, slurm_job_id: str, success: bool, message: str = ""):
        self.slurm_job_id = slurm_job_id
        self.success = success
        self.message = message
        super().__init__()
