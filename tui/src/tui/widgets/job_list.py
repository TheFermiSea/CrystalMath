"""
Enhanced job list widget with structured data and real-time updates.
"""

from datetime import datetime
from typing import Optional, Sequence

from textual.widgets import DataTable
from textual.widgets._data_table import CellDoesNotExist
from textual.reactive import reactive
from rich.text import Text

from crystalmath.models import JobState, JobStatus


class JobListWidget(DataTable):
    """
    DataTable-powered job list tailored for JobStatus models.

    Provides:
    - Iconified status badges
    - Progress bar based on percentage
    - Runtime derived from wall_time_seconds
    - Resource hint (runner type)
    """

    STATUS_COLORS = {
        "PENDING": "dim",
        "QUEUED": "yellow",
        "RUNNING": "cyan bold",
        "COMPLETED": "green bold",
        "FAILED": "red bold",
        "CANCELLED": "red",
    }

    STATUS_ICONS = {
        "PENDING": "⏸",
        "QUEUED": "⏳",
        "RUNNING": "▶",
        "COMPLETED": "✓",
        "FAILED": "✗",
        "CANCELLED": "✗",
    }

    filter_state: reactive[Optional[JobState]] = reactive(None)
    sort_column: reactive[str] = reactive("created_at")
    sort_ascending: reactive[bool] = reactive(False)

    def __init__(self, **kwargs):
        super().__init__(zebra_stripes=True, cursor_type="row", **kwargs)
        self._jobs_cache: dict[int, JobStatus] = {}

    def on_mount(self) -> None:
        self.add_columns(
            "ID",
            "Name",
            "Status",
            "Progress",
            "Runtime",
            "Resources",
            "Energy (Ha)",
            "Created",
        )

    def update_jobs(self, jobs: Sequence[JobStatus]) -> None:
        """Refresh the table using a list of JobStatus models."""
        table = self
        desired_rows: dict[str, tuple[str, str, Text, str, str, str, str, str]] = {}
        desired_order: list[str] = []

        filtered_jobs = (
            [job for job in jobs if job.state == self.filter_state]
            if self.filter_state
            else list(jobs)
        )

        sorted_jobs = self._sort_jobs(filtered_jobs)

        for job in sorted_jobs:
            row_key = str(job.pk)
            desired_order.append(row_key)
            desired_rows[row_key] = self._build_row(job)

        desired_keys = set(desired_rows.keys())
        for existing_row_key in list(table.rows.keys()):
            if existing_row_key.value not in desired_keys:
                table.remove_row(existing_row_key)

        for row_key in desired_order:
            desired = desired_rows[row_key]
            if row_key not in table.rows:
                table.add_row(*desired, key=row_key)
                continue

            current = table.get_row(row_key)
            if len(current) != len(desired):
                table.remove_row(row_key)
                table.add_row(*desired, key=row_key)
                continue

            for column_key, current_value, desired_value in zip(
                ("id", "name", "status", "progress", "runtime", "resources", "energy (ha)", "created"),
                current,
                desired,
            ):
                if current_value != desired_value:
                    table.update_cell(row_key, column_key, desired_value)

        table.sort("created", "id", reverse=True)
        self._jobs_cache = {int(key): job for key, job in zip(desired_order, sorted_jobs)}

    def _build_row(self, job: JobStatus) -> tuple[str, str, Text, str, str, str, str, str]:
        status_text = self._format_status(job.state)
        progress = self._format_progress(job)
        runtime = self._format_runtime(job)
        resources = self._format_resources(job)
        energy = "N/A"
        created = (
            job.created_at.strftime("%Y-%m-%d %H:%M")
            if job.created_at
            else "N/A"
        )

        return (
            str(job.pk),
            job.name,
            status_text,
            progress,
            runtime,
            resources,
            energy,
            created,
        )

    def update_job_status(self, job_id: int, status: JobState, pid: Optional[int] = None) -> None:
        row_key = str(job_id)
        if row_key not in self.rows:
            return

        job = self._jobs_cache.get(job_id)
        if job:
            job.state = status

        progress = self._format_progress(job) if job else "N/A"
        try:
            self.update_cell(row_key, "Status", self._format_status(status), update_width=True)
            self.update_cell(row_key, "Progress", progress, update_width=True)
        except CellDoesNotExist:
            pass

    def update_job_runtime(self, job_id: int) -> None:
        row_key = str(job_id)
        job = self._jobs_cache.get(job_id)
        if not job or row_key not in self.rows:
            return
        runtime = self._format_runtime(job)
        try:
            self.update_cell(row_key, "Runtime", runtime, update_width=True)
        except CellDoesNotExist:
            pass

    def update_job_energy(self, job_id: int, energy: float) -> None:
        row_key = str(job_id)
        if row_key not in self.rows:
            return
        energy_str = f"{energy:.6f}"
        try:
            self.update_cell(row_key, "Energy (Ha)", energy_str, update_width=True)
        except CellDoesNotExist:
            pass

    def set_filter(self, state: Optional[JobState]) -> None:
        self.filter_state = state

    def set_sort(self, column: str, ascending: bool = True) -> None:
        self.sort_column = column
        self.sort_ascending = ascending

    def _format_status(self, state: JobState) -> Text:
        label = state.value
        icon = self.STATUS_ICONS.get(label, "?")
        color = self.STATUS_COLORS.get(label, "white")
        return Text(f"{icon} {label}", style=color)

    def _format_progress(self, job: Optional[JobStatus]) -> str:
        if job is None:
            return "N/A"

        percent = int(round(job.progress_percent))
        percent = max(0, min(100, percent))
        filled = percent // 10
        return "⣿" * filled + "⣀" * (10 - filled) + f" {percent}%"

    def _format_runtime(self, job: JobStatus) -> str:
        if job.wall_time_seconds is not None:
            return self._format_duration(job.wall_time_seconds)
        return "N/A"

    def _format_duration(self, seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}s"
        if seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        if seconds < 86400:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}h {minutes}m"
        days = int(seconds / 86400)
        hours = int((seconds % 86400) / 3600)
        return f"{days}d {hours}h"

    def _format_resources(self, job: JobStatus) -> str:
        return job.runner_type.value.upper()

    def _sort_jobs(self, jobs: Sequence[JobStatus]) -> list[JobStatus]:
        reverse = not self.sort_ascending
        if self.sort_column == "id":
            return sorted(jobs, key=lambda j: j.pk, reverse=reverse)
        if self.sort_column == "name":
            return sorted(jobs, key=lambda j: j.name.lower(), reverse=reverse)
        if self.sort_column == "status":
            return sorted(jobs, key=lambda j: j.state.value, reverse=reverse)
        if self.sort_column == "runtime":
            return sorted(
                jobs,
                key=lambda j: j.wall_time_seconds or 0.0,
                reverse=reverse,
            )
        if self.sort_column == "energy":
            return sorted(jobs, key=lambda j: 0.0, reverse=reverse)
        return sorted(
            jobs,
            key=lambda j: j.created_at or datetime.min,
            reverse=reverse,
        )
