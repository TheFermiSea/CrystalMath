"""
Enhanced job list widget with rich formatting and real-time updates.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional, Literal

from textual.app import ComposeResult
from textual.widgets import DataTable
from textual.reactive import reactive
from rich.text import Text

from ...core.database import Job


StatusType = Literal["PENDING", "QUEUED", "RUNNING", "COMPLETED", "FAILED"]


class JobListWidget(DataTable):
    """
    Enhanced DataTable for displaying jobs with color-coded status.

    Features:
    - Color-coded status indicators
    - Progress indicators for running jobs
    - Estimated time remaining
    - Resource usage display
    - Filtering and sorting capabilities
    """

    # Reactive properties for real-time updates
    filter_status: reactive[Optional[StatusType]] = reactive(None)
    sort_column: reactive[str] = reactive("created_at")
    sort_ascending: reactive[bool] = reactive(False)

    STATUS_COLORS = {
        "PENDING": "dim",
        "QUEUED": "yellow",
        "RUNNING": "cyan bold",
        "COMPLETED": "green bold",
        "FAILED": "red bold",
    }

    STATUS_ICONS = {
        "PENDING": "⏸",
        "QUEUED": "⏳",
        "RUNNING": "▶",
        "COMPLETED": "✓",
        "FAILED": "✗",
    }

    def __init__(self, **kwargs):
        """Initialize the job list widget."""
        super().__init__(
            zebra_stripes=True,
            cursor_type="row",
            **kwargs
        )
        self._jobs_cache: dict[int, Job] = {}
        self._running_start_times: dict[int, datetime] = {}

    def on_mount(self) -> None:
        """Set up columns when widget is mounted."""
        self.add_columns(
            "ID",
            "Name",
            "Status",
            "Progress",
            "Runtime",
            "Resources",
            "Energy (Ha)",
            "Created"
        )

    def update_jobs(self, jobs: list[Job]) -> None:
        """
        Update the job list with new data.

        Args:
            jobs: List of Job objects to display
        """
        # Clear existing rows
        self.clear()
        self._jobs_cache.clear()

        # Apply filtering
        if self.filter_status:
            jobs = [j for j in jobs if j.status == self.filter_status]

        # Apply sorting
        jobs = self._sort_jobs(jobs)

        # Add rows
        for job in jobs:
            self._jobs_cache[job.id] = job
            self._add_job_row(job)

    def update_job_status(self, job_id: int, status: StatusType, pid: Optional[int] = None) -> None:
        """
        Update a single job's status in the table.

        Args:
            job_id: Job ID to update
            status: New status
            pid: Optional process ID
        """
        row_key = str(job_id)
        if row_key not in self.rows:
            return

        # Update cache
        if job_id in self._jobs_cache:
            job = self._jobs_cache[job_id]
            job.status = status
            job.pid = pid

            # Track start time for running jobs
            if status == "RUNNING" and job_id not in self._running_start_times:
                self._running_start_times[job_id] = datetime.now()

        # Update status cell with color and icon
        status_text = self._format_status(status)
        self.update_cell(row_key, "Status", status_text, update_width=True)

        # Update progress for running jobs
        if status == "RUNNING":
            self.update_cell(row_key, "Progress", "⣿⣿⣿⣿⣿⣀⣀⣀⣀⣀", update_width=True)
        elif status == "COMPLETED":
            self.update_cell(row_key, "Progress", "⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿", update_width=True)
        elif status == "FAILED":
            self.update_cell(row_key, "Progress", "⣿⣿⣀⣀⣀⣀⣀⣀⣀⣀", update_width=True)
        else:
            self.update_cell(row_key, "Progress", "⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀", update_width=True)

    def update_job_runtime(self, job_id: int) -> None:
        """
        Update runtime display for a running job.

        Args:
            job_id: Job ID to update
        """
        row_key = str(job_id)
        if row_key not in self.rows:
            return

        if job_id not in self._running_start_times:
            return

        start_time = self._running_start_times[job_id]
        elapsed = datetime.now() - start_time
        runtime_str = self._format_duration(elapsed.total_seconds())

        self.update_cell(row_key, "Runtime", runtime_str, update_width=True)

    def update_job_energy(self, job_id: int, energy: float) -> None:
        """
        Update energy display for a job.

        Args:
            job_id: Job ID to update
            energy: Final energy in Hartrees
        """
        row_key = str(job_id)
        if row_key not in self.rows:
            return

        energy_str = f"{energy:.8f}"
        self.update_cell(row_key, "Energy (Ha)", energy_str, update_width=True)

    def set_filter(self, status: Optional[StatusType]) -> None:
        """
        Filter jobs by status.

        Args:
            status: Status to filter by, or None for all jobs
        """
        self.filter_status = status

    def set_sort(self, column: str, ascending: bool = True) -> None:
        """
        Set sorting column and order.

        Args:
            column: Column name to sort by
            ascending: Sort ascending if True, descending if False
        """
        self.sort_column = column
        self.sort_ascending = ascending

    def _add_job_row(self, job: Job) -> None:
        """
        Add a job as a new row in the table.

        Args:
            job: Job object to add
        """
        # Format status with color and icon
        status_text = self._format_status(job.status)

        # Format progress indicator
        progress = self._format_progress(job)

        # Calculate runtime
        runtime = self._calculate_runtime(job)

        # Format resources
        resources = self._format_resources(job)

        # Format energy
        energy_str = f"{job.final_energy:.8f}" if job.final_energy else "N/A"

        # Format created timestamp
        created_str = self._format_timestamp(job.created_at) if job.created_at else "N/A"

        # Add row
        self.add_row(
            str(job.id),
            job.name,
            status_text,
            progress,
            runtime,
            resources,
            energy_str,
            created_str,
            key=str(job.id)
        )

    def _format_status(self, status: StatusType) -> Text:
        """
        Format status with color and icon.

        Args:
            status: Job status

        Returns:
            Rich Text object with colored status
        """
        icon = self.STATUS_ICONS.get(status, "?")
        color = self.STATUS_COLORS.get(status, "white")
        return Text(f"{icon} {status}", style=color)

    def _format_progress(self, job: Job) -> str:
        """
        Format progress indicator based on job status.

        Args:
            job: Job object

        Returns:
            Unicode progress bar
        """
        if job.status == "COMPLETED":
            return "⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿"  # Full bar
        elif job.status == "RUNNING":
            return "⣿⣿⣿⣿⣿⣀⣀⣀⣀⣀"  # 50% bar (animated in real updates)
        elif job.status == "FAILED":
            return "⣿⣿⣀⣀⣀⣀⣀⣀⣀⣀"  # 20% bar
        else:
            return "⣀⣀⣀⣀⣀⣀⣀⣀⣀⣀"  # Empty bar

    def _calculate_runtime(self, job: Job) -> str:
        """
        Calculate and format job runtime.

        Args:
            job: Job object

        Returns:
            Formatted runtime string
        """
        if job.status == "RUNNING" and job.started_at:
            # Calculate elapsed time
            start = datetime.fromisoformat(job.started_at)
            elapsed = (datetime.now() - start).total_seconds()
            return self._format_duration(elapsed)

        elif job.status in ("COMPLETED", "FAILED") and job.started_at and job.completed_at:
            # Calculate total runtime
            start = datetime.fromisoformat(job.started_at)
            end = datetime.fromisoformat(job.completed_at)
            total = (end - start).total_seconds()
            return self._format_duration(total)

        return "N/A"

    def _format_duration(self, seconds: float) -> str:
        """
        Format duration in seconds to human-readable string.

        Args:
            seconds: Duration in seconds

        Returns:
            Formatted string (e.g., "1h 23m", "45s", "2d 3h")
        """
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}h {minutes}m"
        else:
            days = int(seconds / 86400)
            hours = int((seconds % 86400) / 3600)
            return f"{days}d {hours}h"

    def _format_resources(self, job: Job) -> str:
        """
        Format resource usage (MPI ranks, threads, etc.).

        Args:
            job: Job object

        Returns:
            Formatted resource string
        """
        if job.key_results and isinstance(job.key_results, dict):
            metadata = job.key_results.get("metadata", {})

            # Try to extract resource info from metadata
            threads = metadata.get("omp_threads")
            ranks = metadata.get("mpi_ranks")

            if ranks and threads:
                return f"{ranks}R×{threads}T"
            elif threads:
                return f"{threads}T"

        # Fallback: show PID if available
        if job.pid:
            return f"PID:{job.pid}"

        return "N/A"

    def _format_timestamp(self, timestamp: str) -> str:
        """
        Format ISO timestamp to readable format.

        Args:
            timestamp: ISO format timestamp string

        Returns:
            Formatted timestamp (e.g., "2024-01-15 14:23")
        """
        try:
            dt = datetime.fromisoformat(timestamp)
            return dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, AttributeError):
            return timestamp[:16] if len(timestamp) >= 16 else timestamp

    def _sort_jobs(self, jobs: list[Job]) -> list[Job]:
        """
        Sort jobs based on current sort settings.

        Args:
            jobs: List of jobs to sort

        Returns:
            Sorted list of jobs
        """
        reverse = not self.sort_ascending

        if self.sort_column == "id":
            return sorted(jobs, key=lambda j: j.id or 0, reverse=reverse)
        elif self.sort_column == "name":
            return sorted(jobs, key=lambda j: j.name, reverse=reverse)
        elif self.sort_column == "status":
            return sorted(jobs, key=lambda j: j.status, reverse=reverse)
        elif self.sort_column == "created_at":
            return sorted(jobs, key=lambda j: j.created_at or "", reverse=reverse)
        elif self.sort_column == "runtime":
            # Sort by runtime duration
            def get_runtime(job: Job) -> float:
                if job.started_at and job.completed_at:
                    start = datetime.fromisoformat(job.started_at)
                    end = datetime.fromisoformat(job.completed_at)
                    return (end - start).total_seconds()
                return 0.0
            return sorted(jobs, key=get_runtime, reverse=reverse)
        elif self.sort_column == "energy":
            return sorted(jobs, key=lambda j: j.final_energy or 0.0, reverse=reverse)
        else:
            # Default: sort by created_at descending
            return sorted(jobs, key=lambda j: j.created_at or "", reverse=True)
