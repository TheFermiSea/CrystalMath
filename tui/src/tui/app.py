"""
Main Textual application for CRYSTAL-TUI.
"""

import asyncio
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import DataTable, Header, Footer, Log, Static, TabbedContent, TabPane
from textual.worker import Worker
from textual.message import Message
from textual.binding import Binding

from ..core.database import Database
from .screens import NewJobScreen
from .screens.new_job import JobCreated


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
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("n", "new_job", "New Job", show=True),
        Binding("r", "run_job", "Run", show=True),
        Binding("s", "stop_job", "Stop", show=True),
    ]

    def __init__(self, project_dir: Path):
        super().__init__()
        self.project_dir = project_dir
        self.db_path = project_dir / ".crystal_tui.db"
        self.calculations_dir = project_dir / "calculations"
        self.db: Optional[Database] = None
        self.active_workers: dict[int, Worker] = {}

    def compose(self) -> ComposeResult:
        """Compose the UI layout."""
        yield Header()

        with Container(id="main_container"):
            yield DataTable(id="job_list", zebra_stripes=True, cursor_type="row")

            with TabbedContent(id="content_tabs"):
                with TabPane("Log", id="tab_log"):
                    yield Log(id="log_view", auto_scroll=True, highlight=True)

                with TabPane("Input", id="tab_input"):
                    yield Static("No input file selected", id="input_preview")

                with TabPane("Results", id="tab_results"):
                    yield Static("No results available", id="results_view")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize the application on startup."""
        # Ensure project structure exists
        self.calculations_dir.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self.db = Database(self.db_path)

        # Set up job table
        table = self.query_one("#job_list", DataTable)
        table.add_columns("ID", "Name", "Status", "Energy (Ha)", "Created")

        # Load existing jobs
        self._refresh_job_list()

        # Welcome message
        log = self.query_one("#log_view", Log)
        log.write_line("[bold cyan]CRYSTAL-TUI Started[/bold cyan]")
        log.write_line(f"Project: {self.project_dir}")
        log.write_line(f"Database: {self.db_path}")
        log.write_line("")

    def _refresh_job_list(self) -> None:
        """Reload all jobs from database into the table."""
        if not self.db:
            return

        table = self.query_one("#job_list", DataTable)
        table.clear()

        jobs = self.db.get_all_jobs()
        for job in jobs:
            energy_str = f"{job.final_energy:.6f}" if job.final_energy else "N/A"
            created_str = job.created_at[:19] if job.created_at else "N/A"

            table.add_row(
                str(job.id),
                job.name,
                job.status,
                energy_str,
                created_str,
                key=str(job.id)
            )

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
        """Update the status in the DataTable."""
        if self.db:
            self.db.update_status(message.job_id, message.status, message.pid)

        table = self.query_one("#job_list", DataTable)
        row_key = str(message.job_id)

        if row_key in table.rows:
            table.update_cell(row_key, "Status", message.status)

    def on_job_results(self, message: JobResults) -> None:
        """Update results in the DataTable."""
        if self.db:
            self.db.update_results(message.job_id, final_energy=message.final_energy)

        table = self.query_one("#job_list", DataTable)
        row_key = str(message.job_id)

        if row_key in table.rows and message.final_energy:
            energy_str = f"{message.final_energy:.6f}"
            table.update_cell(row_key, "Energy (Ha)", energy_str)

    # --- Job Execution Worker ---
    async def _run_crystal_job(self, job_id: int) -> None:
        """
        Worker that runs a CRYSTAL job in a subprocess.
        This is a mock implementation for the MVP skeleton.
        """
        if not self.db:
            return

        job = self.db.get_job(job_id)
        if not job:
            return

        self.post_message(JobStatus(job_id, "RUNNING"))
        self.post_message(JobLog(job_id, f"[bold green]Starting job {job_id}: {job.name}[/bold green]"))

        # Mock subprocess for demonstration
        # In real implementation, this would run the CRYSTAL executable
        work_dir = Path(job.work_dir)

        try:
            process = await asyncio.create_subprocess_shell(
                'for i in {1..10}; do echo "SCF cycle $i..."; sleep 0.3; done; echo "CONVERGENCE ACHIEVED"',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=work_dir
            )

            self.post_message(JobStatus(job_id, "RUNNING", process.pid))

            # Stream output
            if process.stdout:
                while line_bytes := await process.stdout.readline():
                    line = line_bytes.decode("utf-8")
                    self.post_message(JobLog(job_id, line))

            await process.wait()

            # Mock parsing of results
            final_energy = -289.123456  # Mock value

            if process.returncode == 0:
                self.post_message(JobLog(job_id, "[bold green]Job completed successfully[/bold green]"))
                self.post_message(JobStatus(job_id, "COMPLETED"))
                self.post_message(JobResults(job_id, final_energy))
            else:
                self.post_message(JobLog(job_id, f"[bold red]Job failed with return code {process.returncode}[/bold red]"))
                self.post_message(JobStatus(job_id, "FAILED"))

        except asyncio.CancelledError:
            self.post_message(JobLog(job_id, "[red]Job was cancelled[/red]"))
            raise
        except Exception as e:
            self.post_message(JobLog(job_id, f"[bold red]Error: {e}[/bold red]"))
            self.post_message(JobStatus(job_id, "FAILED"))
