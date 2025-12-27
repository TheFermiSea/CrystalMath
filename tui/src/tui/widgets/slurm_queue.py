"""
SLURM queue display widget with real-time updates.

Provides a DataTable-based view of SLURM queue status with:
- Auto-refresh via polling
- State colorization
- GPU allocation display
- Filtering by user/partition/state
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any, Callable, Awaitable, TYPE_CHECKING

from textual.widgets import DataTable
from textual.reactive import reactive
from textual import work
from rich.text import Text

from ..messages import QueueUpdated, JobCancelled

if TYPE_CHECKING:
    from ...runners.slurm_runner import SLURMRunner


class SLURMQueueWidget(DataTable):
    """
    Real-time SLURM queue display widget.

    Columns: JobID | User | Name | State | Partition | Nodes | GPUs | Time | NodeList

    Features:
    - Zebra stripes for readability
    - State colorization (RUNNING=cyan, PENDING=yellow, etc.)
    - GPU column parsed from tres_alloc_str
    - Auto-refresh via set_interval (configurable)
    - Row keys for stable selection during refresh
    - Filtering by user, partition, and state
    """

    # Reactive properties for filtering
    filter_user: reactive[Optional[str]] = reactive(None)
    filter_partition: reactive[Optional[str]] = reactive(None)
    filter_state: reactive[Optional[str]] = reactive(None)

    # SLURM job state colors (matching JobListWidget style)
    STATE_COLORS = {
        "RUNNING": "cyan bold",
        "PENDING": "yellow",
        "COMPLETING": "green",
        "COMPLETED": "green bold",
        "FAILED": "red bold",
        "CANCELLED": "red",
        "TIMEOUT": "magenta",
        "NODE_FAIL": "red bold",
        "PREEMPTED": "magenta",
        "SUSPENDED": "dim",
        "CONFIGURING": "blue",
        "BOOT_FAIL": "red bold",
        "DEADLINE": "magenta",
        "OUT_OF_MEMORY": "red bold",
    }

    STATE_ICONS = {
        "RUNNING": "▶",
        "PENDING": "⏳",
        "COMPLETING": "⣿",
        "COMPLETED": "✓",
        "FAILED": "✗",
        "CANCELLED": "⊘",
        "TIMEOUT": "⏱",
        "NODE_FAIL": "⚠",
        "PREEMPTED": "↓",
        "SUSPENDED": "⏸",
        "CONFIGURING": "⚙",
        "BOOT_FAIL": "⚠",
        "DEADLINE": "⏰",
        "OUT_OF_MEMORY": "⚠",
    }

    def __init__(
        self,
        runner: Optional["SLURMRunner"] = None,
        refresh_interval: float = 5.0,
        auto_refresh: bool = True,
        **kwargs
    ):
        """
        Initialize the SLURM queue widget.

        Args:
            runner: SLURMRunner instance for fetching queue data.
            refresh_interval: Seconds between auto-refresh (default 5.0).
            auto_refresh: Whether to enable auto-refresh on mount.
            **kwargs: Additional arguments passed to DataTable.
        """
        super().__init__(
            zebra_stripes=True,
            cursor_type="row",
            **kwargs
        )
        self._runner = runner
        self._refresh_interval = refresh_interval
        self._auto_refresh = auto_refresh
        self._jobs_cache: Dict[str, Dict[str, Any]] = {}
        self._refresh_timer: Optional[Any] = None
        self._fetch_callback: Optional[Callable[[], Awaitable[List[Dict[str, Any]]]]] = None

    def set_runner(self, runner: "SLURMRunner") -> None:
        """Set the SLURM runner for fetching queue data."""
        self._runner = runner

    def set_fetch_callback(
        self, callback: Callable[[], Awaitable[List[Dict[str, Any]]]]
    ) -> None:
        """
        Set a custom callback for fetching queue data.

        This allows the parent screen to control how queue data is fetched,
        including applying any necessary filtering or authentication.

        Args:
            callback: Async function that returns list of job dictionaries.
        """
        self._fetch_callback = callback

    def on_mount(self) -> None:
        """Set up columns and start auto-refresh when widget is mounted."""
        self.add_columns(
            "JobID",
            "User",
            "Name",
            "State",
            "Partition",
            "Nodes",
            "GPUs",
            "Time",
            "NodeList"
        )

        if self._auto_refresh and (self._runner or self._fetch_callback):
            self._start_auto_refresh()

    def on_unmount(self) -> None:
        """Clean up timer when widget is unmounted."""
        self.stop_auto_refresh()

    def _start_auto_refresh(self) -> None:
        """Start the auto-refresh timer."""
        self._refresh_timer = self.set_interval(
            self._refresh_interval,
            self.request_refresh
        )

    def stop_auto_refresh(self) -> None:
        """Stop the auto-refresh timer."""
        if self._refresh_timer:
            self._refresh_timer.stop()
            self._refresh_timer = None

    def start_auto_refresh(self) -> None:
        """Restart the auto-refresh timer."""
        self.stop_auto_refresh()
        self._start_auto_refresh()

    def request_refresh(self) -> None:
        """Request a queue refresh (called by timer or manually)."""
        self.refresh_queue()

    @work(group="squeue", exclusive=True, exit_on_error=False)
    async def refresh_queue(self) -> None:
        """
        Fetch and update queue data in a background worker.

        Uses exclusive=True to prevent overlapping refreshes.
        """
        jobs = await self._fetch_queue()
        self.post_message(QueueUpdated(jobs))

    async def _fetch_queue(self) -> List[Dict[str, Any]]:
        """
        Fetch queue data from SLURM.

        Returns:
            List of job dictionaries with standardized format.
        """
        if self._fetch_callback:
            return await self._fetch_callback()

        if not self._runner:
            return []

        try:
            return await self._runner.get_queue_status(
                user_only=(self.filter_user is not None),
                partition=self.filter_partition,
                states=[self.filter_state] if self.filter_state else None
            )
        except Exception:
            # Log error but don't crash the widget
            return []

    def on_queue_updated(self, event: QueueUpdated) -> None:
        """
        Handle queue update message.

        Args:
            event: QueueUpdated message with job list.
        """
        self.update_jobs(event.jobs)

    def update_jobs(self, jobs: List[Dict[str, Any]]) -> None:
        """
        Update the job list with new data.

        Uses row keys to preserve selection during updates.

        Args:
            jobs: List of job dictionaries from SLURMRunner.
        """
        # Apply client-side filtering
        filtered_jobs = self._apply_filters(jobs)

        # Track current selection (handle both Textual versions)
        selected_row_key = None
        if self.cursor_row is not None:
            try:
                # cursor_row may be RowKey or int depending on Textual version
                if hasattr(self.cursor_row, 'value'):
                    selected_row_key = str(self.cursor_row.value)
                else:
                    row_key = self.get_row_key(self.cursor_row)
                    selected_row_key = str(row_key.value) if hasattr(row_key, 'value') else str(row_key)
            except Exception:
                pass

        # Clear and rebuild table
        self.clear()
        self._jobs_cache.clear()

        for job in filtered_jobs:
            job_id = str(job.get("job_id", ""))
            self._jobs_cache[job_id] = job
            self._add_job_row(job)

        # Restore selection if possible, or select first row
        if selected_row_key:
            # Find the row index by matching against row key values
            try:
                for idx, row_key in enumerate(self.rows.keys()):
                    key_val = str(row_key.value) if hasattr(row_key, 'value') else str(row_key)
                    if key_val == selected_row_key:
                        self.move_cursor(row=idx)
                        break
                else:
                    # Key not found, select first row if available
                    if self.row_count > 0:
                        self.move_cursor(row=0)
            except Exception:
                if self.row_count > 0:
                    self.move_cursor(row=0)
        elif self.row_count > 0:
            # No previous selection - move to first row
            self.move_cursor(row=0)

    def _apply_filters(self, jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Apply client-side filters to job list.

        Args:
            jobs: List of job dictionaries.

        Returns:
            Filtered list of jobs.
        """
        result = jobs

        if self.filter_user:
            result = [j for j in result if j.get("user") == self.filter_user]

        if self.filter_partition:
            result = [j for j in result if j.get("partition") == self.filter_partition]

        if self.filter_state:
            result = [j for j in result if j.get("state") == self.filter_state]

        return result

    def _add_job_row(self, job: Dict[str, Any]) -> None:
        """
        Add a job as a new row in the table.

        Args:
            job: Job dictionary with standardized fields.
        """
        job_id = str(job.get("job_id", ""))
        user = job.get("user", "")
        name = self._truncate(job.get("name", ""), 25)
        state = job.get("state", "UNKNOWN")
        partition = job.get("partition", "")
        nodes = str(job.get("nodes", 1))
        gpus = str(job.get("gpus", 0)) if job.get("gpus", 0) > 0 else "-"
        time_used = job.get("time_used", "N/A")
        node_list = self._truncate(job.get("node_list", ""), 20)

        # Format state with color and icon
        state_text = self._format_state(state)

        self.add_row(
            job_id,
            user,
            name,
            state_text,
            partition,
            nodes,
            gpus,
            time_used,
            node_list,
            key=job_id
        )

    def _format_state(self, state: str) -> Text:
        """
        Format state with color and icon.

        Args:
            state: SLURM job state string.

        Returns:
            Rich Text object with colored state.
        """
        # Normalize state (handle variations like "RUNNING", "R", etc.)
        state_upper = state.upper()

        icon = self.STATE_ICONS.get(state_upper, "?")
        color = self.STATE_COLORS.get(state_upper, "white")

        return Text(f"{icon} {state_upper}", style=color)

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        """Truncate text with ellipsis if too long."""
        if len(text) <= max_len:
            return text
        return text[:max_len - 1] + "…"

    def get_job(self, row_key: str) -> Optional[Dict[str, Any]]:
        """
        Get job data by row key (job ID).

        Args:
            row_key: The row key (Job ID).

        Returns:
            Job dictionary or None.
        """
        return self._jobs_cache.get(str(row_key))

    def get_selected_job(self) -> Optional[Dict[str, Any]]:
        """
        Get the currently selected job's data.

        Returns:
            Job dictionary or None if no selection.
        """
        if self.cursor_row is None:
            return None

        try:
            # Handle both Textual versions: cursor_row may be RowKey or int
            if hasattr(self.cursor_row, 'value'):
                # cursor_row is a RowKey object
                key = str(self.cursor_row.value)
            else:
                # cursor_row is an int index
                row_key = self.get_row_key(self.cursor_row)
                key = str(row_key.value) if hasattr(row_key, 'value') else str(row_key)
            return self._jobs_cache.get(key)
        except Exception:
            return None

    def get_first_job(self) -> Optional[Dict[str, Any]]:
        """
        Get the first job in the cache (for initial selection).

        Returns:
            First job dictionary or None if cache is empty.
        """
        if not self._jobs_cache:
            return None
        # Return first job in cache
        first_key = next(iter(self._jobs_cache), None)
        return self._jobs_cache.get(first_key) if first_key else None

    def get_selected_job_id(self) -> Optional[str]:
        """
        Get the SLURM job ID of the currently selected job.

        Returns:
            Job ID string or None if no selection.
        """
        job = self.get_selected_job()
        if not job:
            # Fallback to first job if cursor selection fails
            job = self.get_first_job()
        if job:
            return str(job.get("job_id", ""))
        return None

    def set_user_filter(self, user: Optional[str]) -> None:
        """Set filter to show only jobs from specified user."""
        self.filter_user = user
        self.request_refresh()

    def set_partition_filter(self, partition: Optional[str]) -> None:
        """Set filter to show only jobs in specified partition."""
        self.filter_partition = partition
        self.request_refresh()

    def set_state_filter(self, state: Optional[str]) -> None:
        """Set filter to show only jobs in specified state."""
        self.filter_state = state
        self.request_refresh()

    def clear_filters(self) -> None:
        """Clear all filters."""
        self.filter_user = None
        self.filter_partition = None
        self.filter_state = None
        self.request_refresh()

    def get_job_count_summary(self) -> Dict[str, int]:
        """
        Get a summary of job counts by state.

        Returns:
            Dictionary mapping state to count.
        """
        summary: Dict[str, int] = {}
        for job in self._jobs_cache.values():
            state = job.get("state", "UNKNOWN")
            summary[state] = summary.get(state, 0) + 1
        return summary
