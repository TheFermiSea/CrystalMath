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

from ..core.backend import get_database, BackendMode
from ..core.core_adapter import CrystalCoreClient
from ..core.environment import CrystalConfig, get_crystal_config
from ..core.queue_manager import QueueManager, Priority
from ..runners import LocalRunner, LocalRunnerError, InputFileError
from ..runners.base import JobResult
from .screens import NewJobScreen, SLURMQueueScreen
from .screens.new_job import JobCreated
from .widgets import InputPreview, ResultsSummary, JobListWidget, JobStatsWidget
from ..core.database import Database as CoreDatabase, Cluster, Job
from ..core.connection_manager import ConnectionManager


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

    TITLE = "CRYSTAL-TUI"

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

    /* Fix tab visibility */
    TabbedContent Tabs {
        height: 3;
    }

    TabbedContent Tab {
        padding: 0 2;
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
        Binding("u", "slurm_queue", "Queue", show=True),
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
        # QueueManager for priority-based scheduling
        self.queue_manager: Optional[QueueManager] = None
        self._job_executor_task: Optional[asyncio.Task] = None
        self._executor_running = False
        # ConnectionManager for SSH connections (SLURM queue)
        self.connection_manager: Optional[ConnectionManager] = None
        self._core_db: Optional[CoreDatabase] = None
        self._core_client: Optional[CrystalCoreClient] = None

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

    async def on_mount(self) -> None:
        """Initialize the application on startup."""
        # Ensure project structure exists
        self.calculations_dir.mkdir(parents=True, exist_ok=True)

        # Ensure runner is configured and env vars are set from config
        self._ensure_runner()

        # Initialize database using backend abstraction
        # This allows switching between SQLite (legacy) and AiiDA backends
        self.db = get_database(mode=BackendMode.LEGACY, db_path=self.db_path)

        # Initialize CoreDatabase for SLURM queue (shares same db file)
        self._core_db = CoreDatabase(self.db_path)
        self._core_client = CrystalCoreClient(self.db_path)

        # Initialize ConnectionManager for SSH connections
        self.connection_manager = ConnectionManager()

        # Initialize and start QueueManager
        self.queue_manager = QueueManager(
            database=self.db,
            default_max_concurrent=4,
            scheduling_interval=1.0
        )
        await self.queue_manager.start()

        # Start job executor background task
        self._executor_running = True
        self._job_executor_task = asyncio.create_task(self._job_executor_worker())

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
        log.write_line("[dim]QueueManager active with priority scheduling[/dim]")
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
        """Reload all jobs into the table using the core adapter when possible."""
        job_list = self.query_one("#job_list", JobListWidget)
        job_stats = self.query_one("#job_stats", JobStatsWidget)

        jobs = self._get_jobs_for_ui()
        if jobs is None:
            return

        job_list.update_jobs(jobs)
        job_stats.update_stats(jobs)

    def _update_running_jobs(self) -> None:
        """Update runtime display for running jobs (called every second)."""
        job_list = self.query_one("#job_list", JobListWidget)
        jobs = self._get_jobs_for_ui()
        if jobs is None:
            return

        # Update runtime for all running jobs
        for job in jobs:
            if job.status == "RUNNING" and job.id:
                job_list.update_job_runtime(job.id)

    def _get_jobs_for_ui(self):
        """Fetch jobs via core adapter, falling back to legacy database."""
        if self._core_client is not None:
            try:
                return self._core_client.list_jobs()
            except Exception:
                pass

        if self.db is not None:
            return self.db.get_all_jobs()

        return None

    def _resolve_job(self, job_id: int) -> Job | None:
        """Try to get a Job dataclass from the core adapter before falling back to the database."""
        if self._core_client is not None:
            try:
                for job in self._core_client.list_jobs():
                    if job.id == job_id:
                        return job
            except Exception:
                pass

        if self.db:
            return self.db.get_job(job_id)

        return None

    def action_new_job(self) -> None:
        """Create a new job via modal screen."""
        if not self.db:
            return

        # Push the new job modal screen
            self.push_screen(
                NewJobScreen(
                    database=self.db,
                    calculations_dir=self.calculations_dir,
                    core_client=self._core_client
                )
            )

    async def action_run_job(self) -> None:
        """Run the selected job via QueueManager."""
        job_list = self.query_one("#job_list", JobListWidget)

        if not job_list.cursor_row:
            return

        row_key = job_list.cursor_row
        row_data = job_list.get_row(row_key)
        job_id = int(row_data[0])

        # Get job status from core adapter (fallbacks to DB)
        if not self.queue_manager:
            return

        job = self._resolve_job(job_id)
        if not job:
            return

        # Only run pending or failed jobs
        if job.status not in ("PENDING", "FAILED"):
            log = self.query_one("#log_view", Log)
            log.write_line(f"[yellow]Job {job_id} is already {job.status}[/yellow]")
            return

        # Enqueue the job via QueueManager (handles priority, dependencies, etc.)
        try:
            await self.queue_manager.enqueue(
                job_id=job_id,
                priority=Priority.NORMAL,
                runner_type="local"
            )
            log = self.query_one("#log_view", Log)
            log.write_line(f"[cyan]Job {job_id} queued for execution[/cyan]")
            self._refresh_job_list()
        except Exception as e:
            log = self.query_one("#log_view", Log)
            log.write_line(f"[red]Failed to queue job {job_id}: {e}[/red]")

    async def action_stop_job(self) -> None:
        """Stop the selected running or queued job."""
        job_list = self.query_one("#job_list", JobListWidget)

        if not job_list.cursor_row:
            return

        row_key = job_list.cursor_row
        row_data = job_list.get_row(row_key)
        job_id = int(row_data[0])

        # Get job status from core adapter (fallbacks to DB)
        if not self.queue_manager:
            return

        job = self._resolve_job(job_id)
        if not job:
            return

        # Can cancel QUEUED or RUNNING jobs
        if job.status not in ("RUNNING", "QUEUED"):
            log = self.query_one("#log_view", Log)
            log.write_line(f"[yellow]Job {job_id} is not running or queued[/yellow]")
            return

        # Cancel via QueueManager (handles queue removal and status update)
        cancelled = await self.queue_manager.cancel_job(job_id)

        log = self.query_one("#log_view", Log)
        if cancelled:
            log.write_line(f"[red]Job {job_id} cancelled by user[/red]")
            # Also stop the runner if job was running
            if job.status == "RUNNING" and self.runner:
                await self.runner.stop_job(job_id)
            self._refresh_job_list()
        else:
            log.write_line(f"[yellow]Could not cancel job {job_id}[/yellow]")

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

    def action_slurm_queue(self) -> None:
        """Open the SLURM queue manager screen."""
        if not self._core_db or not self.connection_manager:
            self.notify("Database or connection manager not initialized", severity="error")
            return

        # Get available SLURM clusters
        clusters = self._core_db.get_all_clusters()
        slurm_clusters = [c for c in clusters if c.type == "slurm"]

        if not slurm_clusters:
            self.notify("No SLURM clusters configured", severity="warning")
            return

        # Use the first SLURM cluster (could add selection dialog later)
        cluster = slurm_clusters[0]

        # Register cluster with ConnectionManager (required for SSH access)
        config = cluster.connection_config
        key_file = config.get("key_file")
        if key_file:
            key_file = Path(key_file).expanduser()

        self.connection_manager.register_cluster(
            cluster_id=cluster.id,
            host=cluster.hostname,
            port=cluster.port,
            username=cluster.username,
            key_file=key_file,
            use_agent=config.get("use_agent", True),
            strict_host_key_checking=config.get("strict_host_key_checking", True),
        )

        log = self.query_one("#log_view", Log)
        log.write_line(f"[cyan]Opening SLURM queue: {cluster.name}[/cyan]")

        # Push the SLURM queue screen
        self.push_screen(
            SLURMQueueScreen(
                db=self._core_db,
                connection_manager=self.connection_manager,
                cluster_id=cluster.id,
            )
        )

    # --- Event Handlers ---
    def on_job_list_widget_row_highlighted(self, event) -> None:
        """Handle row selection in job table - update input and results views."""
        if (not self.db and not self._core_client) or not hasattr(event, "row_key") or event.row_key is None:
            return

        try:
            job_id = int(event.row_key.value)
            job = self._resolve_job(job_id)

            if not job:
                return

            # Update input preview
            input_preview = self.query_one("#input_preview", InputPreview)
            work_dir = Path(job.work_dir) if job.work_dir else None
            input_file = work_dir / "input.d12" if work_dir else None

            job_details = None
            if self._core_client:
                try:
                    job_details = self._core_client.get_job_details(job_id)
                except Exception as err:
                    self.query_one("#log_view", Log).write_line(
                        f"[yellow]Failed to load job details for {job_id}: {err}[/yellow]"
                    )

            if job_details and job_details.input_file:
                input_preview.update_content(job_details.input_file, file_path=input_file)
            elif input_file and input_file.exists():
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
                if job_details:
                    results_view.display_results(
                        job_id=job_details.pk,
                        job_name=job_details.name,
                        work_dir=work_dir,
                        status=job_details.state.value,
                        final_energy=job_details.final_energy,
                        key_results=job_details.key_results,
                        created_at=job_details.created_at.strftime("%Y-%m-%d %H:%M:%S")
                        if job_details.created_at
                        else None,
                        completed_at=None,
                    )
                else:
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
                self._display_job_log_snapshot(job_id)
            else:
                results_view.display_no_results()

        except Exception as e:
            # Log error but don't crash
            log = self.query_one("#log_view", Log)
            log.write_line(f"[red]Error updating views: {e}[/red]")

    def _display_job_log_snapshot(self, job_id: int) -> None:
        """Append a short log snapshot for the selected job."""
        if not self._core_client:
            return

        try:
            logs = self._core_client.get_job_log(job_id, tail_lines=50)
        except Exception:
            return

        log_widget = self.query_one("#log_view", Log)
        stdout = logs.get("stdout", [])
        stderr = logs.get("stderr", [])

        if stdout:
            log_widget.write_line(f"[dim]Job {job_id} stdout (last {len(stdout)} lines):[/dim]")
            for line in stdout:
                log_widget.write_line(line.rstrip())

        if stderr:
            log_widget.write_line(f"[dim]Job {job_id} stderr (last {len(stderr)} lines):[/dim]")
            for line in stderr:
                log_widget.write_line(line.rstrip())

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
        jobs = self._get_jobs_for_ui()
        if jobs is None and self.db:
            jobs = self.db.get_all_jobs()
        if jobs:
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
        job_list = self.query_one("#job_list", JobListWidget)
        if job_list.cursor_row:
            row_data = job_list.get_row(job_list.cursor_row)
            selected_job_id = int(row_data[0])

            if selected_job_id == message.job_id:
                results_view = self.query_one("#results_view", ResultsSummary)
                job = self._resolve_job(message.job_id)
                job_details = None
                if self._core_client:
                    try:
                        job_details = self._core_client.get_job_details(message.job_id)
                    except Exception as err:
                        self.query_one("#log_view", Log).write_line(
                            f"[yellow]Failed to refresh job details: {err}[/yellow]"
                        )

                work_dir = Path(job.work_dir) if job and job.work_dir else None

                if job_details:
                    results_view.display_results(
                        job_id=job_details.pk,
                        job_name=job_details.name,
                        work_dir=work_dir,
                        status=job_details.state.value,
                        final_energy=job_details.final_energy,
                        key_results=job_details.key_results,
                        created_at=job_details.created_at.strftime("%Y-%m-%d %H:%M:%S")
                        if job_details.created_at
                        else None,
                        completed_at=None,
                    )
                elif job and job.status in ("COMPLETED", "FAILED"):
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

    # --- Job Execution Worker ---
    async def _run_crystal_job(self, job_id: int) -> None:
        """
        Worker that runs a CRYSTAL job in a subprocess.

        This method properly handles the LocalRunner.run_job() async generator
        which yields string lines during execution and a JobResult object as
        the final yield. The JobResult is captured directly to avoid race
        conditions with get_last_result().
        """
        if not self.db:
            return

        job = self.db.get_job(job_id)
        if not job:
            return

        # CRITICAL: Check if job was cancelled between dequeue and execution start
        # This prevents race condition where cancel_job() runs after dequeue()
        # but before we start the runner
        if job.status == "CANCELLED":
            self.post_message(JobLog(job_id, "[yellow]Job was cancelled before execution started[/yellow]"))
            return

        work_dir = Path(job.work_dir)
        runner = self._ensure_runner()
        pid_reported = False
        result: Optional[JobResult] = None  # Capture result directly

        self.post_message(JobStatus(job_id, "RUNNING"))
        self.post_message(JobLog(job_id, f"[bold green]Starting job {job_id}: {job.name}[/bold green]"))

        try:
            async for item in runner.run_job(job_id, work_dir):
                # run_job yields strings during execution, then JobResult at the end
                if isinstance(item, JobResult):
                    # Capture the result directly - avoids race condition
                    result = item
                else:
                    # Regular output line
                    if not pid_reported:
                        pid = runner.get_process_pid(job_id)
                        if pid:
                            self.post_message(JobStatus(job_id, "RUNNING", pid))
                            pid_reported = True
                    self.post_message(JobLog(job_id, item))

            if result is None:
                raise LocalRunnerError("Job finished but no result was yielded")

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
                # Notify queue manager of successful completion
                if self.queue_manager:
                    await self.queue_manager.handle_job_completion(job_id, success=True)
            else:
                self.post_message(JobLog(job_id, "[bold red]Job failed[/bold red]"))
                if result.metadata.get("return_code") is not None:
                    self.post_message(JobLog(job_id, f"[red]Return code: {result.metadata['return_code']}[/red]"))
                for error in result.errors:
                    self.post_message(JobLog(job_id, f"[red]Error: {error}[/red]"))
                self.post_message(JobStatus(job_id, "FAILED"))
                # Notify queue manager of failure (may trigger retry)
                if self.queue_manager:
                    await self.queue_manager.handle_job_completion(job_id, success=False)

        except asyncio.CancelledError:
            await runner.stop_job(job_id)
            self.post_message(JobLog(job_id, "[red]Job was cancelled[/red]"))
            self.post_message(JobStatus(job_id, "FAILED"))
            if self.queue_manager:
                await self.queue_manager.handle_job_completion(job_id, success=False)
            raise
        except InputFileError as e:
            self.post_message(JobLog(job_id, f"[bold red]Input error: {e}[/bold red]"))
            self.post_message(JobStatus(job_id, "FAILED"))
            if self.queue_manager:
                await self.queue_manager.handle_job_completion(job_id, success=False)
        except LocalRunnerError as e:
            self.post_message(JobLog(job_id, f"[bold red]Runner error: {e}[/bold red]"))
            self.post_message(JobStatus(job_id, "FAILED"))
            if self.queue_manager:
                await self.queue_manager.handle_job_completion(job_id, success=False)
        except Exception as e:
            self.post_message(JobLog(job_id, f"[bold red]Unexpected error: {e}[/bold red]"))
            self.post_message(JobStatus(job_id, "FAILED"))
            if self.queue_manager:
                await self.queue_manager.handle_job_completion(job_id, success=False)
        finally:
            # Refresh grid to reflect final status and results
            self._refresh_job_list()

    async def _job_executor_worker(self) -> None:
        """
        Background worker that consumes jobs from QueueManager and executes them.

        This worker:
        1. Polls the queue manager for ready jobs
        2. Executes them using the appropriate runner
        3. Reports completion back to the queue manager

        This decouples job scheduling (priority, dependencies) from execution,
        allowing the QueueManager to handle queuing logic while this worker
        handles actual job execution.
        """
        while self._executor_running:
            try:
                if not self.queue_manager:
                    await asyncio.sleep(1.0)
                    continue

                # Try to dequeue a job for the local runner
                job_id = await self.queue_manager.dequeue("local")

                if job_id is not None:
                    # Execute the job (this handles the full lifecycle)
                    await self._run_crystal_job(job_id)
                else:
                    # No jobs ready, wait before checking again
                    await asyncio.sleep(0.5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log error but keep worker alive
                log = self.query_one("#log_view", Log)
                log.write_line(f"[red]Job executor error: {e}[/red]")
                await asyncio.sleep(1.0)

    async def action_quit(self) -> None:
        """Cleanly shutdown the application."""
        # Stop job executor
        self._executor_running = False
        if self._job_executor_task:
            self._job_executor_task.cancel()
            try:
                await self._job_executor_task
            except asyncio.CancelledError:
                pass

        # Stop queue manager
        if self.queue_manager:
            await self.queue_manager.stop()

        # Close database connection to ensure WAL checkpoint
        if self.db:
            self.db.close()

        # Exit the app
        self.exit()
