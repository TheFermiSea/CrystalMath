"""
Job statistics footer widget.
"""

from textual.app import ComposeResult
from textual.widgets import Static
from textual.reactive import reactive
from rich.text import Text

from crystalmath.models import JobState, JobStatus


class JobStatsWidget(Static):
    """
    Footer widget displaying job statistics.

    Shows:
    - Total jobs
    - Running jobs
    - Completed jobs
    - Failed jobs
    - Success rate
    """

    # Reactive properties
    total_jobs: reactive[int] = reactive(0)
    pending_jobs: reactive[int] = reactive(0)
    queued_jobs: reactive[int] = reactive(0)
    running_jobs: reactive[int] = reactive(0)
    completed_jobs: reactive[int] = reactive(0)
    failed_jobs: reactive[int] = reactive(0)

    def __init__(self, **kwargs):
        """Initialize the stats widget."""
        super().__init__("", **kwargs)

    def update_stats(self, jobs: list[JobStatus]) -> None:
        """
        Update statistics from job list.

        Args:
            jobs: List of all jobs
        """
        self.total_jobs = len(jobs)
        self.pending_jobs = sum(1 for j in jobs if j.state == JobState.CREATED)
        self.queued_jobs = sum(1 for j in jobs if j.state == JobState.QUEUED)
        self.running_jobs = sum(1 for j in jobs if j.state == JobState.RUNNING)
        self.completed_jobs = sum(1 for j in jobs if j.state == JobState.COMPLETED)
        self.failed_jobs = sum(1 for j in jobs if j.state == JobState.FAILED)

        # Update display
        self._render_stats()

    def _render_stats(self) -> None:
        """Render the statistics display."""
        # Calculate success rate
        finished_jobs = self.completed_jobs + self.failed_jobs
        success_rate = (
            (self.completed_jobs / finished_jobs * 100) if finished_jobs > 0 else 0.0
        )

        # Build the stats text
        stats_text = Text()

        # Total jobs
        stats_text.append("Total: ", style="dim")
        stats_text.append(f"{self.total_jobs}", style="bold")
        stats_text.append("  ")

        # Pending jobs
        if self.pending_jobs > 0:
            stats_text.append("⏸ Pending: ", style="dim")
            stats_text.append(f"{self.pending_jobs}", style="dim")
            stats_text.append("  ")

        # Queued jobs
        if self.queued_jobs > 0:
            stats_text.append("⏳ Queued: ", style="yellow")
            stats_text.append(f"{self.queued_jobs}", style="yellow bold")
            stats_text.append("  ")

        # Running jobs
        if self.running_jobs > 0:
            stats_text.append("▶ Running: ", style="cyan")
            stats_text.append(f"{self.running_jobs}", style="cyan bold")
            stats_text.append("  ")

        # Completed jobs
        if self.completed_jobs > 0:
            stats_text.append("✓ Completed: ", style="green")
            stats_text.append(f"{self.completed_jobs}", style="green bold")
            stats_text.append("  ")

        # Failed jobs
        if self.failed_jobs > 0:
            stats_text.append("✗ Failed: ", style="red")
            stats_text.append(f"{self.failed_jobs}", style="red bold")
            stats_text.append("  ")

        # Success rate
        if finished_jobs > 0:
            stats_text.append("  Success Rate: ", style="dim")
            rate_style = "green bold" if success_rate >= 80 else "yellow bold" if success_rate >= 50 else "red bold"
            stats_text.append(f"{success_rate:.1f}%", style=rate_style)

        # Update the widget
        self.update(stats_text)
