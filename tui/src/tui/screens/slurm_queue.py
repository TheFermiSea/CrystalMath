"""
SLURM Queue Management Screen.

Full-screen queue management with:
- Job list with auto-refresh
- Details panel for selected job
- Cancel, logs, refresh actions
- Filtering by user, partition, state
"""

from __future__ import annotations

import logging
from typing import Optional, Dict, Any, List

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Static,
    Label,
    RichLog,
    DataTable,
)
from textual import work

from ..widgets.slurm_queue import SLURMQueueWidget
from ..messages import QueueUpdated, JobCancelled
from ...core.database import Database, Cluster
from ...core.connection_manager import ConnectionManager
from ...runners.slurm_runner import SLURMRunner

logger = logging.getLogger(__name__)


class SLURMQueueScreen(Screen):
    """Full-screen SLURM queue management view."""

    CSS = """
    SLURMQueueScreen {
        layout: vertical;
    }

    #queue-header {
        width: 100%;
        height: 3;
        background: $primary;
        padding: 0 1;
        align: left middle;
    }

    #header-label {
        width: 1fr;
        color: white;
        text-style: bold;
    }

    #filter-bar {
        width: 100%;
        height: auto;
        min-height: 3;
        padding: 1;
        background: $surface;
        layout: horizontal;
    }

    .filter-label {
        width: auto;
        margin-right: 1;
        padding: 0 1;
        background: $panel;
    }

    #refresh-btn {
        margin-left: 2;
    }

    #main-content {
        height: 1fr;
        layout: horizontal;
    }

    #job-list-container {
        width: 2fr;
        min-width: 60;
        height: 100%;
    }

    #queue-widget {
        height: 100%;
    }

    #details-panel {
        width: 1fr;
        min-width: 35;
        height: 100%;
        padding: 1;
        border-left: solid $primary;
    }

    #details-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #job-details {
        height: auto;
        min-height: 10;
        max-height: 20;
        border: solid $accent;
        padding: 1;
        margin-bottom: 1;
    }

    #detail-actions {
        height: 3;
        margin-bottom: 1;
    }

    #detail-actions Button {
        margin-right: 1;
    }

    #log-viewer {
        height: 1fr;
        border: solid $primary;
    }

    .no-selection {
        color: $text-muted;
        text-align: center;
    }
    """

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("q", "dismiss", "Quit"),
        ("c", "cancel_job", "Cancel"),
        ("l", "view_logs", "Logs"),
        ("r", "refresh", "Refresh"),
        ("f", "focus_filters", "Filters"),
    ]

    def __init__(
        self,
        db: Database,
        connection_manager: ConnectionManager,
        cluster_id: int,
    ):
        """Initialize SLURM queue screen."""
        super().__init__()
        self.db = db
        self.connection_manager = connection_manager
        self.cluster_id = cluster_id
        self._cluster: Optional[Cluster] = None
        self._runner: Optional[SLURMRunner] = None
        self._partitions: List[str] = []
        self._current_user: Optional[str] = None
        self._current_job: Optional[Dict[str, Any]] = None  # Track currently displayed job

    def compose(self) -> ComposeResult:
        """Create the UI layout."""
        # Custom header bar with cluster name (replaces standard Header)
        with Horizontal(id="queue-header"):
            yield Label("SLURM Queue: Loading...", id="header-label")

        # Filter bar - use Labels as clickable filters instead of Select
        with Horizontal(id="filter-bar"):
            yield Label("User: All", id="user-filter-label", classes="filter-label")
            yield Label("Partition: All", id="partition-filter-label", classes="filter-label")
            yield Label("State: All", id="state-filter-label", classes="filter-label")
            yield Button("Refresh", id="refresh-btn", variant="primary")

        # Main content: job list + details panel
        with Horizontal(id="main-content"):
            # Job list
            with Container(id="job-list-container"):
                yield SLURMQueueWidget(id="queue-widget", auto_refresh=False)

            # Details panel
            with Vertical(id="details-panel"):
                yield Label("Job Details", id="details-title")
                yield Static("Select a job to view details", id="job-details", classes="no-selection")

                with Horizontal(id="detail-actions"):
                    yield Button("Cancel Job", id="cancel-btn", variant="error", disabled=True)
                    yield Button("View Logs", id="logs-btn", variant="default", disabled=True)

                yield RichLog(id="log-viewer", markup=True, highlight=True)

        yield Footer()

    async def on_mount(self) -> None:
        """Initialize screen when mounted."""
        # Load cluster info
        self._cluster = self.db.get_cluster(self.cluster_id)
        if not self._cluster:
            logger.error(f"Cluster {self.cluster_id} not found")
            self.notify("Cluster not found", severity="error")
            self.dismiss()
            return

        # Update header
        header = self.query_one("#header-label", Label)
        header.update(f"SLURM Queue: {self._cluster.name}")

        # Create runner
        self._runner = SLURMRunner(
            connection_manager=self.connection_manager,
            cluster_id=self.cluster_id,
        )

        # Get current username from cluster config
        self._current_user = self._cluster.username

        # Set up queue widget
        queue_widget = self.query_one("#queue-widget", SLURMQueueWidget)
        queue_widget.set_fetch_callback(self._fetch_queue)

        # Load partitions
        self._load_partitions()

        # Do initial fetch
        self._do_initial_fetch()

    @work(group="initial_fetch", exclusive=True)
    async def _do_initial_fetch(self) -> None:
        """Do initial queue fetch with error reporting."""
        if not self._runner:
            return

        try:
            jobs = await self._runner.get_queue_status(user_only=False)

            queue_widget = self.query_one("#queue-widget", SLURMQueueWidget)
            queue_widget.update_jobs(jobs)

            self._update_summary(jobs)
            self.notify(f"Loaded {len(jobs)} jobs", severity="information")

            # Display first job details directly (don't rely on cursor selection)
            first_job = queue_widget.get_first_job()
            if first_job:
                self._display_job_details(first_job)
                self.query_one("#cancel-btn", Button).disabled = False
                self.query_one("#logs-btn", Button).disabled = False

            queue_widget.start_auto_refresh()

        except Exception as e:
            logger.exception("Failed to fetch initial queue")
            self.notify(f"Connection error: {e}", severity="error")

    def _try_update_selected_details(self) -> None:
        """Try to update details for currently selected job."""
        try:
            queue_widget = self.query_one("#queue-widget", SLURMQueueWidget)
            # Try cursor selection first, fallback to first job in cache
            job = queue_widget.get_selected_job()
            if not job:
                job = queue_widget.get_first_job()
            logger.debug(f"_try_update_selected_details: job={job}")
            if job:
                self._display_job_details(job)
                self.query_one("#cancel-btn", Button).disabled = False
                self.query_one("#logs-btn", Button).disabled = False
            else:
                # No jobs available - clear the details panel
                self._clear_job_details()
        except Exception as e:
            logger.exception(f"Failed to update selected details: {e}")

    @work(group="partitions", exclusive=True)
    async def _load_partitions(self) -> None:
        """Load available partitions from cluster."""
        if not self._runner:
            return

        try:
            partitions_info = await self._runner.get_partition_info()
            self._partitions = [p["name"] for p in partitions_info]
        except Exception as e:
            logger.warning(f"Failed to load partitions: {e}")

    async def _fetch_queue(self) -> List[Dict[str, Any]]:
        """Fetch queue data."""
        if not self._runner:
            return []

        try:
            jobs = await self._runner.get_queue_status(user_only=False)
            self._update_summary(jobs)
            return jobs
        except Exception as e:
            logger.exception("Failed to fetch queue")
            self.notify(f"Failed to fetch queue: {e}", severity="error")
            return []

    def _update_summary(self, jobs: List[Dict[str, Any]]) -> None:
        """Update header summary with job counts."""
        running = sum(1 for j in jobs if j.get("state") == "RUNNING")
        pending = sum(1 for j in jobs if j.get("state") == "PENDING")
        total = len(jobs)

        cluster_name = self._cluster.name if self._cluster else "Unknown"
        header = self.query_one("#header-label", Label)
        header.update(f"SLURM Queue: {cluster_name} - {total} jobs ({running} running, {pending} pending)")

    # Use DataTable.RowHighlighted since SLURMQueueWidget inherits from DataTable
    @on(DataTable.RowHighlighted)
    def _on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle job selection in the queue widget."""
        logger.debug(f"RowHighlighted event received: table_id={event.data_table.id}")
        # Only handle events from our queue widget
        if event.data_table.id != "queue-widget":
            return

        queue_widget = self.query_one("#queue-widget", SLURMQueueWidget)
        
        # Use event.row_key.value directly to get job (RowKey object has .value attribute)
        job = None
        if event.row_key:
            # RowKey object - extract the actual value
            key = event.row_key.value if hasattr(event.row_key, 'value') else str(event.row_key)
            job = queue_widget.get_job(str(key))
        
        if not job:
            job = queue_widget.get_selected_job() or queue_widget.get_first_job()
            
        logger.debug(f"Selected job: {job}")

        if job:
            self._display_job_details(job)
            self.query_one("#cancel-btn", Button).disabled = False
            self.query_one("#logs-btn", Button).disabled = False
        else:
            self._clear_job_details()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection (Enter/click on row)."""
        if event.data_table.id != "queue-widget":
            return
        self._try_update_selected_details()

    def _display_job_details(self, job: Dict[str, Any]) -> None:
        """Display job details in the details panel."""
        self._current_job = job  # Store for actions like View Logs, Cancel
        details = self.query_one("#job-details", Static)
        details.remove_class("no-selection")

        lines = [
            f"Job ID: {job.get('job_id', 'N/A')}",
            f"Name: {job.get('name', 'N/A')}",
            f"User: {job.get('user', 'N/A')}",
            f"State: {job.get('state', 'N/A')}",
            f"Partition: {job.get('partition', 'N/A')}",
            f"Nodes: {job.get('nodes', 'N/A')}",
            f"Node List: {job.get('node_list', 'N/A')}",
            f"GPUs: {job.get('gpus', 0)}",
            f"Time Used: {job.get('time_used', 'N/A')}",
            f"Time Limit: {job.get('time_limit', 'N/A')}",
        ]

        if job.get("state") == "PENDING" and job.get("state_reason"):
            lines.append(f"Reason: {job.get('state_reason')}")

        details.update("\n".join(lines))

    def _clear_job_details(self) -> None:
        """Clear the details panel."""
        self._current_job = None
        details = self.query_one("#job-details", Static)
        details.update("Select a job to view details")
        details.add_class("no-selection")

        self.query_one("#cancel-btn", Button).disabled = True
        self.query_one("#logs-btn", Button).disabled = True

    @on(Button.Pressed, "#refresh-btn")
    def _on_refresh_pressed(self, event: Button.Pressed) -> None:
        """Handle refresh button press."""
        self.action_refresh()

    def action_refresh(self) -> None:
        """Refresh the queue."""
        queue_widget = self.query_one("#queue-widget", SLURMQueueWidget)
        queue_widget.request_refresh()
        self.notify("Refreshing queue...")

    @on(Button.Pressed, "#cancel-btn")
    def _on_cancel_pressed(self, event: Button.Pressed) -> None:
        """Handle cancel button press."""
        self.action_cancel_job()

    def action_cancel_job(self) -> None:
        """Cancel the selected job."""
        queue_widget = self.query_one("#queue-widget", SLURMQueueWidget)
        job_id = queue_widget.get_selected_job_id()

        # Fallback to currently displayed job
        if not job_id and self._current_job:
            job_id = str(self._current_job.get("job_id", ""))

        if not job_id:
            self.notify("No job selected", severity="warning")
            return

        self._cancel_job_confirmed(job_id)

    @work(group="cancel", exclusive=True)
    async def _cancel_job_confirmed(self, job_id: str) -> None:
        """Cancel job."""
        if not self._runner:
            return

        try:
            success, message = await self._runner.cancel_slurm_job(job_id)

            if success:
                self.notify(f"Job {job_id} cancelled", severity="information")
                self.post_message(JobCancelled(job_id, True, message))
            else:
                self.notify(f"Failed to cancel job {job_id}: {message}", severity="error")
                self.post_message(JobCancelled(job_id, False, message))

            queue_widget = self.query_one("#queue-widget", SLURMQueueWidget)
            queue_widget.request_refresh()

        except Exception as e:
            logger.exception(f"Failed to cancel job {job_id}")
            self.notify(f"Error cancelling job: {e}", severity="error")

    @on(Button.Pressed, "#logs-btn")
    def _on_logs_pressed(self, event: Button.Pressed) -> None:
        """Handle logs button press."""
        self.action_view_logs()

    def action_view_logs(self) -> None:
        """View logs for the selected job."""
        queue_widget = self.query_one("#queue-widget", SLURMQueueWidget)
        job_id = queue_widget.get_selected_job_id()

        # Fallback to currently displayed job
        if not job_id and self._current_job:
            job_id = str(self._current_job.get("job_id", ""))

        log_viewer = self.query_one("#log-viewer", RichLog)

        if not job_id:
            log_viewer.clear()
            log_viewer.write("[yellow]No job selected - select a job first[/yellow]")
            self.notify("No job selected", severity="warning")
            return

        self._stream_logs(job_id)

    @work(group="logs", exclusive=True)
    async def _stream_logs(self, job_id: str) -> None:
        """Stream job logs to the log viewer."""
        if not self._runner:
            return

        log_viewer = self.query_one("#log-viewer", RichLog)
        log_viewer.clear()
        log_viewer.write(f"[bold]Fetching logs for job {job_id}...[/bold]\n")

        try:
            async for line in self._runner.get_job_logs(job_id, "stdout", tail_lines=100):
                log_viewer.write(line)
        except Exception as e:
            logger.exception(f"Failed to fetch logs for job {job_id}")
            log_viewer.write(f"[red]Error fetching logs: {e}[/red]")

    def action_focus_filters(self) -> None:
        """Focus the filter controls."""
        self.query_one("#refresh-btn", Button).focus()

    def action_dismiss(self) -> None:
        """Dismiss the screen."""
        try:
            queue_widget = self.query_one("#queue-widget", SLURMQueueWidget)
            queue_widget.stop_auto_refresh()
        except Exception:
            pass
        self.dismiss()

    def on_queue_updated(self, event: QueueUpdated) -> None:
        """Handle queue update message."""
        self._update_summary(event.jobs)
        self._try_update_selected_details()
