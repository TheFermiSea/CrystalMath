"""
Main Textual application for CRYSTAL-TUI.
"""

import asyncio
import os
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import DataTable, Header, Footer, Log, Static, TabbedContent, TabPane
from textual.worker import Worker
from textual.message import Message
from textual.binding import Binding

from ..core.database import Database
from ..core.environment import CrystalConfig, get_crystal_config
from ..runners import LocalRunner, LocalRunnerError, InputFileError
from .screens import NewJobScreen, BatchSubmissionScreen, TemplateBrowserScreen
from .screens.new_job import JobCreated
from .screens.batch_submission import BatchJobsCreated
from .screens.template_browser import TemplateSelected
from .widgets import InputPreview, ResultsSummary


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

    #job_list {
        width: 50%;
        border: solid $primary;
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

    InputPreview {
        height: 1fr;
        overflow-y: auto;
        scrollbar-gutter: stable;
    }

    #input_preview {
        border: solid $accent;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("n", "new_job", "New Job", show=True),
        Binding("t", "template_browser", "Templates", show=True),
        Binding("b", "batch_submission", "Batch", show=True),
        Binding("r", "run_job", "Run", show=True),
        Binding("s", "stop_job", "Stop", show=True),
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

    def compose(self) -> ComposeResult:
        """Compose the UI layout."""
        yield Header()

        with Container(id="main_container"):
            yield DataTable(id="job_list", zebra_stripes=True, cursor_type="row")

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

        # Set up job table with explicit column keys for reliable updates
        table = self.query_one("#job_list", DataTable)
        table.add_column("ID", key="id")
        table.add_column("Name", key="name")
        table.add_column("Status", key="status")
        table.add_column("Energy (Ha)", key="energy")
        table.add_column("Created", key="created")

        # Load existing jobs
        self._refresh_job_list()

        # Welcome message
        log = self.query_one("#log_view", Log)
        log.write_line("[bold cyan]CRYSTAL-TUI Started[/bold cyan]")
        log.write_line(f"Project: {self.project_dir}")
        log.write_line(f"Database: {self.db_path}")
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
        """Refresh job list with incremental updates (add/update/remove)."""
        if not self.db:
            return

        table = self.query_one("#job_list", DataTable)
        jobs = self.db.get_all_jobs()

        desired_rows: dict[str, tuple[str, str, str, str, str]] = {}
        desired_order: list[str] = []
        for job in jobs:
            if job.id is None:
                continue
            row_key = str(job.id)
            desired_order.append(row_key)
            desired_rows[row_key] = self._format_job_row(job)

        # Remove rows that no longer exist in the database.
        desired_key_set = set(desired_rows.keys())
        for existing_row_key in list(table.rows.keys()):
            if existing_row_key.value not in desired_key_set:
                table.remove_row(existing_row_key)

        # Add missing rows and update changed cells.
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
                ("id", "name", "status", "energy", "created"),
                current,
                desired,
            ):
                if current_value != desired_value:
                    table.update_cell(row_key, column_key, desired_value)

        # Keep ordering consistent with database ordering (created_at DESC).
        table.sort("created", "id", reverse=True)

    @staticmethod
    def _format_job_row(job) -> tuple[str, str, str, str, str]:
        energy_str = f"{job.final_energy:.6f}" if job.final_energy is not None else "N/A"
        created_str = job.created_at[:19] if job.created_at else "N/A"
        return (str(job.id), job.name, job.status, energy_str, created_str)

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

    def action_batch_submission(self) -> None:
        """Open batch submission screen."""
        if not self.db:
            return

        # Push the batch submission modal screen
        self.push_screen(
            BatchSubmissionScreen(
                database=self.db,
                calculations_dir=self.calculations_dir
            )
        )

    def action_template_browser(self) -> None:
        """Open template browser screen."""
        if not self.db:
            return

        # Push the template browser modal screen
        def handle_template_result(result):
            if result:
                template, params, rendered_input = result
                # Create a new job with the rendered input
                self._create_job_from_template(template.name, rendered_input, params)

        self.push_screen(
            TemplateBrowserScreen(
                database=self.db,
                calculations_dir=self.calculations_dir
            ),
            callback=handle_template_result
        )

    def _create_job_from_template(self, template_name: str, input_content: str, params: dict) -> None:
        """Create a job from a template."""
        if not self.db:
            return

        # Generate job name from template name and timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        job_name = f"{template_name.lower().replace(' ', '_')}_{timestamp}"

        # Generate next job ID
        existing_jobs = self.db.get_all_jobs()
        next_id = max([job.id for job in existing_jobs], default=0) + 1

        # Create work directory
        work_dir_name = f"{next_id:04d}_{job_name}"
        work_dir = self.calculations_dir / work_dir_name

        try:
            work_dir.mkdir(parents=True, exist_ok=False)

            # Write input file
            input_file = work_dir / "input.d12"
            input_file.write_text(input_content)

            # Write template metadata
            import json
            metadata_file = work_dir / "template_metadata.json"
            metadata_file.write_text(json.dumps({
                "template_name": template_name,
                "parameters": params
            }, indent=2))

            # Add job to database
            job_id = self.db.create_job(
                name=job_name,
                work_dir=str(work_dir),
                input_content=input_content
            )

            # Refresh job list and log
            self._refresh_job_list()
            log = self.query_one("#log_view", Log)
            log.write_line(f"[bold green]Created job {job_id} from template: {template_name}[/bold green]")

        except Exception as e:
            log = self.query_one("#log_view", Log)
            log.write_line(f"[bold red]Failed to create job from template: {str(e)}[/bold red]")

    def action_run_job(self) -> None:
        """Run the selected job."""
        table = self.query_one("#job_list", DataTable)

        if not table.cursor_row:
            return

        row_key = table.cursor_row
        row_data = table.get_row(row_key)
        job_id = int(row_data[0])
        status = row_data[2]

        # Only run pending or failed jobs
        if status not in ("PENDING", "FAILED"):
            log = self.query_one("#log_view", Log)
            log.write_line(f"[yellow]Job {job_id} is already {status}[/yellow]")
            return

        # Update status to queued
        if self.db:
            self.db.update_status(job_id, "QUEUED")

        # Start worker
        self.run_worker(
            self._run_crystal_job(job_id),
            name=f"job_{job_id}",
            group=f"job_{job_id}"
        )

    def action_stop_job(self) -> None:
        """Stop the selected running job."""
        table = self.query_one("#job_list", DataTable)

        if not table.cursor_row:
            return

        row_key = table.cursor_row
        row_data = table.get_row(row_key)
        job_id = int(row_data[0])
        status = row_data[2]

        if status != "RUNNING":
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

    # --- Event Handlers ---
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle row selection in job table - update input and results views."""
        if not self.db or event.row_key is None:
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
            elif job.status == "RUNNING" or job.status == "QUEUED":
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

    def on_batch_jobs_created(self, message: BatchJobsCreated) -> None:
        """Handle batch job creation - refresh the job list and log."""
        self._refresh_job_list()
        log = self.query_one("#log_view", Log)
        log.write_line(f"[bold green]Batch submission complete: {len(message.job_ids)} jobs created[/bold green]")
        for job_id, job_name in zip(message.job_ids, message.job_names):
            log.write_line(f"  - Job {job_id}: {job_name}")

    def on_template_selected(self, message: TemplateSelected) -> None:
        """Handle template selection - create job from template."""
        log = self.query_one("#log_view", Log)
        log.write_line(f"[cyan]Template selected: {message.template.name}[/cyan]")

    def on_job_log(self, message: JobLog) -> None:
        """Write a line to the log viewer."""
        log = self.query_one("#log_view", Log)
        log.write_line(message.line.rstrip())

    def on_job_status(self, message: JobStatus) -> None:
        """Update the status in the DataTable."""
        if self.db:
            self.db.update_status(message.job_id, message.status, message.pid)

        table = self.query_one("#job_list", DataTable)
        row_key = str(message.job_id)

        if row_key in table.rows:
            table.update_cell(row_key, "status", message.status)

    def on_job_results(self, message: JobResults) -> None:
        """Update results in the DataTable and results view if this job is selected."""
        if self.db:
            self.db.update_results(message.job_id, final_energy=message.final_energy)

        table = self.query_one("#job_list", DataTable)
        row_key = str(message.job_id)

        if row_key in table.rows and message.final_energy is not None:
            energy_str = f"{message.final_energy:.6f}"
            table.update_cell(row_key, "energy", energy_str)

        # Update results view if this job is currently selected
        if table.cursor_row and str(table.cursor_row.value) == row_key:
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
