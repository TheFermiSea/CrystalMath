"""
Main Textual application for CRYSTAL-TUI with enhanced job status display.
"""

import asyncio
import os
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Header, Footer, Log, TabbedContent, TabPane
from textual.worker import Worker
from textual.message import Message
from textual.binding import Binding

from ..core.database import Database
from ..core.environment import CrystalConfig, get_crystal_config
from ..runners import LocalRunner, LocalRunnerError, InputFileError
from .screens import NewJobScreen
from .screens.new_job import JobCreated
from .widgets import InputPreview, ResultsSummary, JobListWidget, JobStatsWidget


# --- Custom Messages ---
class JobLog(Message):
    """A message containing a line of output from a job."""
    def __init__(self, job_id: int, line: str) -> None:
        self.job_id = job_id
        self.line = line
        super().__init__()


class JobStatus(Message):
    """A message indicating a job's status has changed."""
    def __init__(self, job_id: int, status: str, pid: Optional[int] = None) -> None:
        self.job_id = job_id
        self.status = status
        self.pid = pid
        super().__init__()


class JobResults(Message):
    """A message with job results after completion."""
    def __init__(self, job_id: int, final_energy: Optional[float] = None) -> None:
        self.job_id = job_id
        self.final_energy = final_energy
        super().__init__()


class CrystalTUI(App):
    """A TUI for managing CRYSTAL calculations."""

    CSS = """
    Screen {
        layout: vertical;
    }

    #main_container {
        layout: horizontal;
        height: 1fr;
    }

    #left_panel {
        width: 50%;
        layout: vertical;
    }

    #job_list {
        height: 1fr;
        border: solid $primary;
    }

    #job_stats {
        height: 3;
        border: solid $primary;
        padding: 0 1;
        background: $panel;
    }

    #content_tabs {
        width: 50%;
    }

    Log {
        border: solid $accent;
    }

    Static {
        border: solid $accent;
        padding: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("n", "new_job", "New Job", show=True),
        Binding("r", "run_job", "Run", show=True),
        Binding("s", "stop_job", "Stop", show=True),
        Binding("f", "filter_status", "Filter", show=True),
        Binding("t", "sort_toggle", "Sort", show=True),
    ]

    def __init__(self, project_dir: Path, config: Optional[CrystalConfig] = None):
        super().__init__()
        self.project_dir = project_dir
        self.db_path = project_dir / ".crystal_tui.db"
        self.calculations_dir = project_dir / "calculations"
        self.db: Optional[Database] = None
        self.active_workers: dict[int, Worker] = {}
        self.config = config
        self.runner: Optional[LocalRunner] = None
        self._update_timer_running = False

    def compose(self) -> ComposeResult:
        """Compose the UI layout."""
        yield Header()

        with Container(id="main_container"):
            with Vertical(id="left_panel"):
                yield JobListWidget(id="job_list")
                yield JobStatsWidget(id="job_stats")

            with TabbedContent(id="content_tabs"):
                with TabPane("Log", id="tab_log"):
                    yield Log(id="log_view", auto_scroll=True, highlight=True)

                with TabPane("Input", id="tab_input"):
                    yield InputPreview(id="input_preview")

                with TabPane("Results", id="tab_results"):
                    yield ResultsSummary(id="results_view")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize the application on startup."""
        # Ensure project structure exists
        self.calculations_dir.mkdir(parents=True, exist_ok=True)

        # Ensure runner is configured and env vars are set from config
        self._ensure_runner()

        # Initialize database
        self.db = Database(self.db_path)

        # Load existing jobs
        self._refresh_job_list()

        # Start real-time update timer
        self.set_interval(1.0, self._update_running_jobs)
        self._update_timer_running = True

        # Welcome message
        log = self.query_one("#log_view", Log)
        log.write_line("[bold cyan]CRYSTAL-TUI Started (Enhanced)[/bold cyan]")
        log.write_line(f"Project: {self.project_dir}")
        log.write_line(f"Database: {self.db_path}")
        log.write_line("")
        log.write_line("[dim]Keyboard shortcuts:[/dim]")
        log.write_line("[dim]  n - New Job  |  r - Run  |  s - Stop  |  f - Filter  |  t - Sort[/dim]")
        log.write_line("")

    def _ensure_runner(self) -> LocalRunner:
        """Instantiate the LocalRunner once and propagate env configuration."""
        if self.runner is None:
            if self.config is None:
                # Try cached loader; will raise if env invalid
                try:
                    self.config = get_crystal_config()
                except Exception:
                    self.config = None

            if self.config:
                os.environ.setdefault("CRY23_EXEDIR", str(self.config.executable_dir))
                os.environ.setdefault("CRY23_SCRDIR", str(self.config.scratch_dir))

            exe_path = self.config.executable_path if self.config else None
            self.runner = LocalRunner(executable_path=exe_path)

        return self.runner

    def _refresh_job_list(self) -> None:
        """Reload all jobs from database into the table."""
        if not self.db:
            return

        job_list = self.query_one("#job_list", JobListWidget)
        job_stats = self.query_one("#job_stats", JobStatsWidget)

        jobs = self.db.get_all_jobs()
        job_list.update_jobs(jobs)
        job_stats.update_stats(jobs)

    def _update_running_jobs(self) -> None:
        """Update runtime display for running jobs (called every second)."""
        if not self.db:
            return

        job_list = self.query_one("#job_list", JobListWidget)
        jobs = self.db.get_all_jobs()

        # Update runtime for all running jobs
        for job in jobs:
            if job.status == "RUNNING" and job.id:
                job_list.update_job_runtime(job.id)

    def action_new_job(self) -> None:
        """Create a new job via modal screen."""
        if not self.db:
            return

        # Push the new job modal screen
        self.push_screen(
            NewJobScreen(
                database=self.db,
                calculations_dir=self.calculations_dir
            )
        )

    def action_run_job(self) -> None:
        """Run the selected job."""
        job_list = self.query_one("#job_list", JobListWidget)

        if not job_list.cursor_row:
            return

        row_key = job_list.cursor_row
        row_data = job_list.get_row(row_key)
        job_id = int(row_data[0])

        # Get job from database to check status
        if not self.db:
            return

        job = self.db.get_job(job_id)
        if not job:
            return

        # Only run pending or failed jobs
        if job.status not in ("PENDING", "FAILED"):
            log = self.query_one("#log_view", Log)
            log.write_line(f"[yellow]Job {job_id} is already {job.status}[/yellow]")
            return

        # Update status to queued
        self.db.update_status(job_id, "QUEUED")

        # Start worker
        self.run_worker(
            self._run_crystal_job(job_id),
            name=f"job_{job_id}",
            group=f"job_{job_id}"
        )

    def action_stop_job(self) -> None:
        """Stop the selected running job."""
        job_list = self.query_one("#job_list", JobListWidget)

        if not job_list.cursor_row:
            return

        row_key = job_list.cursor_row
        row_data = job_list.get_row(row_key)
        job_id = int(row_data[0])

        # Get job from database to check status
        if not self.db:
            return

        job = self.db.get_job(job_id)
        if not job:
            return

        if job.status != "RUNNING":
            log = self.query_one("#log_view", Log)
            log.write_line(f"[yellow]Job {job_id} is not running[/yellow]")
            return

        # Cancel the worker
        worker_name = f"job_{job_id}"
        for worker in self.workers:
            if worker.name == worker_name:
                worker.cancel()

                log = self.query_one("#log_view", Log)
                log.write_line(f"[red]Job {job_id} cancelled by user[/red]")

                if self.db:
                    self.db.update_status(job_id, "FAILED")

                break

    def action_filter_status(self) -> None:
        """Toggle status filtering."""
        job_list = self.query_one("#job_list", JobListWidget)

        # Cycle through filters: None -> RUNNING -> COMPLETED -> FAILED -> PENDING -> None
        current_filter = job_list.filter_status

        if current_filter is None:
            job_list.set_filter("RUNNING")
            self.notify("Filter: RUNNING")
        elif current_filter == "RUNNING":
            job_list.set_filter("COMPLETED")
            self.notify("Filter: COMPLETED")
        elif current_filter == "COMPLETED":
            job_list.set_filter("FAILED")
            self.notify("Filter: FAILED")
        elif current_filter == "FAILED":
            job_list.set_filter("PENDING")
            self.notify("Filter: PENDING")
        else:
            job_list.set_filter(None)
            self.notify("Filter: ALL")

        # Refresh list
        self._refresh_job_list()

    def action_sort_toggle(self) -> None:
        """Toggle sort column."""
        job_list = self.query_one("#job_list", JobListWidget)

        # Cycle through sort columns: created_at -> name -> status -> runtime -> energy
        current_sort = job_list.sort_column

        if current_sort == "created_at":
            job_list.set_sort("name")
            self.notify("Sort: Name")
        elif current_sort == "name":
            job_list.set_sort("status")
            self.notify("Sort: Status")
        elif current_sort == "status":
            job_list.set_sort("runtime", ascending=False)
            self.notify("Sort: Runtime")
        elif current_sort == "runtime":
            job_list.set_sort("energy", ascending=False)
            self.notify("Sort: Energy")
        else:
            job_list.set_sort("created_at", ascending=False)
            self.notify("Sort: Created")

        # Refresh list
        self._refresh_job_list()

    # --- Event Handlers ---
    def on_job_list_widget_row_highlighted(self, event) -> None:
        """Handle row selection in job table - update input and results views."""
        if not self.db or not hasattr(event, 'row_key') or event.row_key is None:
            return

        try:
            job_id = int(event.row_key.value)
            job = self.db.get_job(job_id)

            if not job:
                return

            # Update input preview
            input_preview = self.query_one("#input_preview", InputPreview)
            work_dir = Path(job.work_dir)
            input_file = work_dir / "input.d12"

            if input_file.exists():
                input_preview.display_input(job.name, input_file)
            else:
                input_preview.display_no_input()

            # Update results view based on job status
            results_view = self.query_one("#results_view", ResultsSummary)

            if job.status == "PENDING":
                results_view.display_pending(job.name)
            elif job.status in ("RUNNING", "QUEUED"):
                results_view.display_running(job.name)
            elif job.status in ("COMPLETED", "FAILED"):
                results_view.display_results(
                    job_id=job.id,
                    job_name=job.name,
                    work_dir=work_dir,
                    status=job.status,
                    final_energy=job.final_energy,
                    key_results=job.key_results,
                    created_at=job.created_at,
                    completed_at=job.completed_at,
                )
            else:
                results_view.display_no_results()

        except Exception as e:
            # Log error but don't crash
            log = self.query_one("#log_view", Log)
            log.write_line(f"[red]Error updating views: {e}[/red]")

    # --- Message Handlers ---
    def on_job_created(self, message: JobCreated) -> None:
        """Handle new job creation - refresh the job list and log."""
        self._refresh_job_list()
        log = self.query_one("#log_view", Log)
        log.write_line(f"[bold green]Created new job {message.job_id}: {message.job_name}[/bold green]")

    def on_job_log(self, message: JobLog) -> None:
        """Write a line to the log viewer."""
        log = self.query_one("#log_view", Log)
        log.write_line(message.line.rstrip())

    def on_job_status(self, message: JobStatus) -> None:
        """Update the status in the job list."""
        if self.db:
            self.db.update_status(message.job_id, message.status, message.pid)

        job_list = self.query_one("#job_list", JobListWidget)
        job_list.update_job_status(message.job_id, message.status, message.pid)

        # Update stats
        if self.db:
            jobs = self.db.get_all_jobs()
            job_stats = self.query_one("#job_stats", JobStatsWidget)
            job_stats.update_stats(jobs)

    def on_job_results(self, message: JobResults) -> None:
        """Update results in the job list."""
        if self.db:
            self.db.update_results(message.job_id, final_energy=message.final_energy)

        if message.final_energy:
            job_list = self.query_one("#job_list", JobListWidget)
            job_list.update_job_energy(message.job_id, message.final_energy)

        # Update results view if this job is currently selected
        if self.db:
            job_list = self.query_one("#job_list", JobListWidget)
            if job_list.cursor_row:
                row_data = job_list.get_row(job_list.cursor_row)
                selected_job_id = int(row_data[0])

                if selected_job_id == message.job_id:
                    job = self.db.get_job(message.job_id)
                    if job and job.status in ("COMPLETED", "FAILED"):
                        results_view = self.query_one("#results_view", ResultsSummary)
                        results_view.display_results(
                            job_id=job.id,
                            job_name=job.name,
                            work_dir=Path(job.work_dir),
                            status=job.status,
                            final_energy=job.final_energy,
                            key_results=job.key_results,
                            created_at=job.created_at,
                            completed_at=job.completed_at,
                        )

    # --- Job Execution Worker ---
    async def _run_crystal_job(self, job_id: int) -> None:
        """
        Worker that runs a CRYSTAL job in a subprocess.
        """
        if not self.db:
            return

        job = self.db.get_job(job_id)
        if not job:
            return

        work_dir = Path(job.work_dir)
        runner = self._ensure_runner()
        pid_reported = False

        self.post_message(JobStatus(job_id, "RUNNING"))
        self.post_message(JobLog(job_id, f"[bold green]Starting job {job_id}: {job.name}[/bold green]"))

        try:
            async for line in runner.run_job(job_id, work_dir):
                if not pid_reported:
                    pid = runner.get_process_pid(job_id)
                    if pid:
                        self.post_message(JobStatus(job_id, "RUNNING", pid))
                        pid_reported = True
                self.post_message(JobLog(job_id, line))

            result = runner.get_last_result()
            if result is None:
                raise LocalRunnerError("Job finished but no result was recorded")

            # Persist results
            if self.db:
                key_results = {
                    "convergence": result.convergence_status,
                    "errors": result.errors,
                    "warnings": result.warnings,
                    "metadata": result.metadata,
                }
                self.db.update_results(
                    job_id,
                    final_energy=result.final_energy,
                    key_results=key_results,
                )

            if result.success:
                self.post_message(JobLog(job_id, "[bold green]Job completed successfully[/bold green]"))
                if result.final_energy is not None:
                    self.post_message(JobLog(job_id, f"[cyan]Final energy: {result.final_energy:.10f} Ha[/cyan]"))
                self.post_message(JobLog(job_id, f"[cyan]Convergence: {result.convergence_status}[/cyan]"))
                if result.warnings:
                    for warning in result.warnings:
                        self.post_message(JobLog(job_id, f"[yellow]Warning: {warning}[/yellow]"))
                self.post_message(JobStatus(job_id, "COMPLETED"))
                self.post_message(JobResults(job_id, result.final_energy))
            else:
                self.post_message(JobLog(job_id, "[bold red]Job failed[/bold red]"))
                if result.metadata.get("return_code") is not None:
                    self.post_message(JobLog(job_id, f"[red]Return code: {result.metadata['return_code']}[/red]"))
                for error in result.errors:
                    self.post_message(JobLog(job_id, f"[red]Error: {error}[/red]"))
                self.post_message(JobStatus(job_id, "FAILED"))

        except asyncio.CancelledError:
            await runner.stop_job(job_id)
            self.post_message(JobLog(job_id, "[red]Job was cancelled[/red]"))
            self.post_message(JobStatus(job_id, "FAILED"))
            raise
        except InputFileError as e:
            self.post_message(JobLog(job_id, f"[bold red]Input error: {e}[/bold red]"))
            self.post_message(JobStatus(job_id, "FAILED"))
        except LocalRunnerError as e:
            self.post_message(JobLog(job_id, f"[bold red]Runner error: {e}[/bold red]"))
            self.post_message(JobStatus(job_id, "FAILED"))
        except Exception as e:
            self.post_message(JobLog(job_id, f"[bold red]Unexpected error: {e}[/bold red]"))
            self.post_message(JobStatus(job_id, "FAILED"))
        finally:
            # Refresh grid to reflect final status and results
            self._refresh_job_list()
