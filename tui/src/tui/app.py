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
from ..core.connection_manager import ConnectionManager
from ..runners import LocalRunner, LocalRunnerError, InputFileError
from ..runners.ssh_runner import SSHRunner
from ..core.codes import DFTCode
from .screens import NewJobScreen, BatchSubmissionScreen, TemplateBrowserScreen, ClusterManagerScreen, VASPFilesReady, SLURMQueueScreen
from .screens.new_job import JobCreated
from .screens.batch_submission import BatchJobsCreated
from .screens.template_browser import TemplateSelected
from .widgets import InputPreview, ResultsSummary
from .messages import JobProgressUpdate


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
        Binding("c", "cluster_manager", "Clusters", show=True),
        Binding("u", "slurm_queue", "Queue", show=True),
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
        self.connection_manager: Optional[ConnectionManager] = None
        # Track active SSH runners for remote jobs (job_id -> (runner, job_handle))
        self._active_ssh_jobs: dict[int, tuple[SSHRunner, str]] = {}
        # Track progress monitoring tasks
        self._progress_monitors: dict[int, asyncio.Task] = {}

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

    async def on_mount(self) -> None:
        """Initialize the application on startup."""
        # Ensure project structure exists
        self.calculations_dir.mkdir(parents=True, exist_ok=True)

        # Ensure runner is configured and env vars are set from config
        self._ensure_runner()

        # Initialize database
        self.db = Database(self.db_path)

        # Initialize connection manager for remote execution
        self.connection_manager = ConnectionManager()
        await self.connection_manager.start()

        # Register existing clusters from database
        clusters = self.db.get_active_clusters()
        for cluster in clusters:
            if cluster.id is None:
                continue
            config = cluster.connection_config
            key_file = Path(config.get("key_file")).expanduser() if config.get("key_file") else None
            self.connection_manager.register_cluster(
                cluster_id=cluster.id,
                host=cluster.hostname,
                port=cluster.port,
                username=cluster.username,
                key_file=key_file,
                use_agent=config.get("use_agent", True),
                strict_host_key_checking=config.get("strict_host_key_checking", True),
            )

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

    async def on_unmount(self) -> None:
        """Clean up resources when shutting down."""
        # Stop connection manager
        if self.connection_manager:
            await self.connection_manager.stop()

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

    def action_cluster_manager(self) -> None:
        """Open cluster manager screen."""
        if not self.db or not self.connection_manager:
            return

        # Push the cluster manager screen
        self.push_screen(
            ClusterManagerScreen(
                db=self.db,
                connection_manager=self.connection_manager
            )
        )

    def action_slurm_queue(self) -> None:
        """Open SLURM queue management screen."""
        if not self.db or not self.connection_manager:
            return

        log = self.query_one("#log_view", Log)

        # Get available SLURM clusters
        clusters = self.db.get_active_clusters()
        slurm_clusters = [c for c in clusters if c.type == "slurm"]

        if not slurm_clusters:
            log.write_line("[yellow]No SLURM clusters configured. Press 'c' to add a cluster.[/yellow]")
            return

        # For now, use the first SLURM cluster
        # TODO: Add cluster selection if multiple SLURM clusters exist
        cluster = slurm_clusters[0]
        if cluster.id is None:
            log.write_line("[red]Invalid cluster configuration[/red]")
            return

        log.write_line(f"[cyan]Opening SLURM queue for: {cluster.name}[/cyan]")

        # Push the SLURM queue screen
        self.push_screen(
            SLURMQueueScreen(
                db=self.db,
                connection_manager=self.connection_manager,
                cluster_id=cluster.id
            )
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

        # Get job details to check DFT code
        job = self.db.get_job(job_id) if self.db else None
        if not job:
            return

        # Check if this is a VASP job (requires remote execution)
        is_vasp = False
        if hasattr(job, 'dft_code') and job.dft_code == "vasp":
            is_vasp = True
        elif Path(job.work_dir).joinpath("POSCAR").exists():
            is_vasp = True

        if is_vasp:
            # VASP jobs require a cluster selection
            self._run_vasp_job_with_cluster_selection(job_id)
            return

        # Update status to queued for local jobs
        if self.db:
            self.db.update_status(job_id, "QUEUED")

        # Start worker for CRYSTAL (local execution)
        self.run_worker(
            self._run_crystal_job(job_id),
            name=f"job_{job_id}",
            group=f"job_{job_id}"
        )

    def _run_vasp_job_with_cluster_selection(self, job_id: int) -> None:
        """Handle VASP job execution with cluster selection."""
        if not self.db:
            return

        log = self.query_one("#log_view", Log)

        # Get available clusters
        clusters = self.db.get_active_clusters()
        if not clusters:
            log.write_line("[bold red]No clusters configured. Press 'c' to add a cluster.[/bold red]")
            return

        # For now, use the first available cluster
        # TODO: Add cluster selection UI
        cluster = clusters[0]
        if cluster.id is None:
            log.write_line("[bold red]Invalid cluster configuration[/bold red]")
            return

        log.write_line(f"[cyan]Using cluster: {cluster.name} ({cluster.hostname})[/cyan]")

        # Update status to queued
        self.db.update_status(job_id, "QUEUED")

        # Start remote VASP worker
        self.run_worker(
            self._run_remote_vasp_job(job_id, cluster.id),
            name=f"vasp_job_{job_id}",
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

    def on_vasp_files_ready(self, message: VASPFilesReady) -> None:
        """Handle VASP multi-file input ready - create job with all files."""
        if not self.db:
            return

        log = self.query_one("#log_view", Log)
        log.write_line(f"[cyan]Creating VASP job: {message.job_name}[/cyan]")

        try:
            # Generate next job ID
            existing_jobs = self.db.get_all_jobs()
            next_id = max([job.id for job in existing_jobs], default=0) + 1

            # Create work directory
            work_dir_name = f"{next_id:04d}_{message.job_name}"
            work_dir = self.calculations_dir / work_dir_name
            work_dir.mkdir(parents=True, exist_ok=False)

            # Write all VASP input files
            (work_dir / "POSCAR").write_text(message.poscar)
            (work_dir / "INCAR").write_text(message.incar)
            (work_dir / "KPOINTS").write_text(message.kpoints)

            # Note: POTCAR will be retrieved from cluster during job submission
            # Store POTCAR element in job metadata
            import json
            metadata = {
                "potcar_element": message.potcar_element,
                "dft_code": "vasp"
            }
            (work_dir / "vasp_metadata.json").write_text(json.dumps(metadata, indent=2))

            # Create combined input content for database storage
            input_content = f"# VASP Job: {message.job_name}\n"
            input_content += f"# POTCAR Element: {message.potcar_element}\n\n"
            input_content += "=== POSCAR ===\n" + message.poscar + "\n\n"
            input_content += "=== INCAR ===\n" + message.incar + "\n\n"
            input_content += "=== KPOINTS ===\n" + message.kpoints

            # Add job to database
            job_id = self.db.create_job(
                name=message.job_name,
                work_dir=str(work_dir),
                input_content=input_content,
                dft_code="vasp"
            )

            # Refresh job list and log
            self._refresh_job_list()
            log.write_line(f"[bold green]Created VASP job {job_id}: {message.job_name}[/bold green]")
            log.write_line(f"  POSCAR: {len(message.poscar.split(chr(10)))} lines")
            log.write_line(f"  INCAR: {len(message.incar.split(chr(10)))} lines")
            log.write_line(f"  KPOINTS: {len(message.kpoints.split(chr(10)))} lines")
            log.write_line(f"  POTCAR: {message.potcar_element} (will retrieve from cluster)")
            log.write_line(f"  Work dir: {work_dir_name}")

        except Exception as e:
            log.write_line(f"[red]Failed to create VASP job: {str(e)}[/red]")
            import traceback
            log.write_line(f"[red]{traceback.format_exc()}[/red]")

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

    # --- VASP Progress Monitoring ---
    async def _monitor_vasp_progress(
        self,
        job_id: int,
        runner: SSHRunner,
        job_handle: str,
        poll_interval: float = 10.0
    ) -> None:
        """
        Background task that monitors VASP job progress.

        Periodically polls the remote OUTCAR file and posts progress updates.

        Args:
            job_id: Database ID of the job
            runner: SSHRunner instance for this job
            job_handle: Handle returned by submit_job()
            poll_interval: Seconds between progress checks
        """
        log = self.query_one("#log_view", Log)
        log.write_line(f"[cyan]Starting VASP progress monitor for job {job_id}[/cyan]")

        try:
            while True:
                # Check if job is still running
                try:
                    status = await runner.get_status(job_handle)
                    if status not in ("running", "RUNNING"):
                        log.write_line(
                            f"[cyan]VASP job {job_id} finished with status: {status}[/cyan]"
                        )
                        break
                except Exception as e:
                    log.write_line(f"[yellow]Error checking job status: {e}[/yellow]")
                    break

                # Get progress update
                try:
                    progress = await runner.get_vasp_progress(job_handle)
                    if progress:
                        # Post progress message
                        self.post_message(JobProgressUpdate(
                            job_id=job_id,
                            job_handle=job_handle,
                            progress_data=progress.to_dict(),
                            status_text=progress.status_summary()
                        ))
                except Exception as e:
                    log.write_line(f"[yellow]Error getting VASP progress: {e}[/yellow]")

                # Wait before next check
                await asyncio.sleep(poll_interval)

        except asyncio.CancelledError:
            log.write_line(f"[cyan]VASP progress monitor for job {job_id} cancelled[/cyan]")
            raise
        finally:
            # Cleanup
            self._progress_monitors.pop(job_id, None)

    def _start_vasp_progress_monitor(
        self,
        job_id: int,
        runner: SSHRunner,
        job_handle: str
    ) -> None:
        """Start background progress monitoring for a VASP job."""
        # Cancel existing monitor if any
        if job_id in self._progress_monitors:
            self._progress_monitors[job_id].cancel()

        # Create and track new monitor task
        task = asyncio.create_task(
            self._monitor_vasp_progress(job_id, runner, job_handle)
        )
        self._progress_monitors[job_id] = task

    def _stop_vasp_progress_monitor(self, job_id: int) -> None:
        """Stop progress monitoring for a job."""
        if job_id in self._progress_monitors:
            self._progress_monitors[job_id].cancel()
            self._progress_monitors.pop(job_id, None)

    def on_job_progress_update(self, message: JobProgressUpdate) -> None:
        """Handle VASP job progress updates."""
        log = self.query_one("#log_view", Log)

        # Extract progress data
        data = message.progress_data
        ionic_step = data.get("ionic_step", 0)
        scf_iter = data.get("scf_iteration", 0)
        energy = data.get("current_energy")
        progress_pct = data.get("progress_percentage", 0)

        # Format progress line
        if energy is not None:
            progress_line = (
                f"[dim]Job {message.job_id}:[/dim] "
                f"Ion:{ionic_step} SCF:{scf_iter} "
                f"E={energy:.6f} eV ({progress_pct:.1f}%)"
            )
        else:
            progress_line = (
                f"[dim]Job {message.job_id}:[/dim] "
                f"Ion:{ionic_step} SCF:{scf_iter} ({progress_pct:.1f}%)"
            )

        log.write_line(progress_line)

        # Check for errors
        if data.get("error_detected"):
            error_msg = data.get("error_message", "Unknown error")
            log.write_line(f"[bold red]VASP Error detected: {error_msg}[/bold red]")

        # Update table status with progress info if job is selected
        table = self.query_one("#job_list", DataTable)
        row_key = str(message.job_id)
        if row_key in table.rows:
            status_text = f"RUNNING ({progress_pct:.0f}%)"
            table.update_cell(row_key, "status", status_text)

    # --- Remote VASP Job Execution ---
    async def _run_remote_vasp_job(self, job_id: int, cluster_id: int) -> None:
        """
        Worker that runs a VASP job on a remote cluster via SSH.

        Args:
            job_id: Database ID of the job
            cluster_id: Database ID of the cluster to run on
        """
        if not self.db or not self.connection_manager:
            return

        job = self.db.get_job(job_id)
        if not job:
            return

        work_dir = Path(job.work_dir)
        log = self.query_one("#log_view", Log)

        self.post_message(JobStatus(job_id, "RUNNING"))
        self.post_message(JobLog(job_id, f"[bold green]Starting VASP job {job_id}: {job.name}[/bold green]"))
        self.post_message(JobLog(job_id, f"[cyan]Cluster: {cluster_id}[/cyan]"))

        runner = None
        job_handle = None

        try:
            # Create SSH runner for VASP
            runner = SSHRunner(
                connection_manager=self.connection_manager,
                cluster_id=cluster_id,
                dft_code=DFTCode.VASP,
                cleanup_on_success=False,
            )

            # Find input file (POSCAR is the main input for VASP)
            input_file = work_dir / "POSCAR"
            if not input_file.exists():
                raise FileNotFoundError(f"POSCAR not found in {work_dir}")

            # Submit job
            self.post_message(JobLog(job_id, "[cyan]Uploading files to cluster...[/cyan]"))
            job_handle = await runner.submit_job(
                job_id=job_id,
                work_dir=work_dir,
                input_file=input_file,
                threads=4,  # Default OpenMP threads
            )

            self.post_message(JobLog(job_id, f"[cyan]Job submitted with handle: {job_handle}[/cyan]"))

            # Track active SSH job
            self._active_ssh_jobs[job_id] = (runner, job_handle)

            # Start progress monitoring
            self._start_vasp_progress_monitor(job_id, runner, job_handle)

            # Poll for completion
            while True:
                await asyncio.sleep(30)  # Check every 30 seconds

                status = await runner.get_status(job_handle)
                if status not in ("running", "RUNNING"):
                    self.post_message(JobLog(job_id, f"[cyan]Job finished with status: {status}[/cyan]"))
                    break

            # Stop progress monitor
            self._stop_vasp_progress_monitor(job_id)

            # Retrieve results
            self.post_message(JobLog(job_id, "[cyan]Retrieving results...[/cyan]"))
            result = await runner.retrieve_results(job_handle, work_dir)

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
                self.post_message(JobLog(job_id, "[bold green]VASP job completed successfully[/bold green]"))
                if result.final_energy is not None:
                    self.post_message(JobLog(job_id, f"[cyan]Final energy: {result.final_energy:.10f} eV[/cyan]"))
                self.post_message(JobLog(job_id, f"[cyan]Convergence: {result.convergence_status}[/cyan]"))

                # Display benchmark data if available
                benchmark = result.metadata.get("benchmark", {})
                if benchmark:
                    self.post_message(JobLog(job_id, "[cyan]─── Benchmark Data ───[/cyan]"))
                    if "elapsed_time_sec" in benchmark:
                        elapsed = benchmark["elapsed_time_sec"]
                        mins, secs = divmod(elapsed, 60)
                        self.post_message(JobLog(job_id, f"  Wall time: {int(mins)}m {secs:.1f}s"))
                    if "total_cpu_time_sec" in benchmark:
                        cpu = benchmark["total_cpu_time_sec"]
                        mins, secs = divmod(cpu, 60)
                        self.post_message(JobLog(job_id, f"  CPU time: {int(mins)}m {secs:.1f}s"))
                    if "cpu_to_wall_ratio" in benchmark:
                        self.post_message(JobLog(job_id, f"  Efficiency ratio: {benchmark['cpu_to_wall_ratio']:.2f}x"))
                    if "loop_count" in benchmark:
                        self.post_message(JobLog(job_id, f"  SCF loops: {benchmark['loop_count']}"))
                    parallel_info = []
                    if "npar" in benchmark:
                        parallel_info.append(f"NPAR={benchmark['npar']}")
                    if "ncore" in benchmark:
                        parallel_info.append(f"NCORE={benchmark['ncore']}")
                    if "kpar" in benchmark:
                        parallel_info.append(f"KPAR={benchmark['kpar']}")
                    if parallel_info:
                        self.post_message(JobLog(job_id, f"  Parallel: {', '.join(parallel_info)}"))

                for warning in result.warnings:
                    self.post_message(JobLog(job_id, f"[yellow]Warning: {warning}[/yellow]"))
                self.post_message(JobStatus(job_id, "COMPLETED"))
                self.post_message(JobResults(job_id, result.final_energy))
            else:
                self.post_message(JobLog(job_id, "[bold red]VASP job failed[/bold red]"))
                for error in result.errors:
                    self.post_message(JobLog(job_id, f"[red]Error: {error}[/red]"))

                # Analyze VASP errors and provide recovery suggestions
                outcar_path = work_dir / "OUTCAR"
                if outcar_path.exists():
                    try:
                        from ..runners.vasp_errors import analyze_vasp_errors
                        outcar_content = outcar_path.read_text()
                        vasp_errors, _ = analyze_vasp_errors(outcar_content)

                        if vasp_errors:
                            self.post_message(JobLog(job_id, "[yellow]─── Error Analysis ───[/yellow]"))
                            for verr in vasp_errors:
                                severity_color = "red" if verr.severity.value == "fatal" else "yellow"
                                self.post_message(JobLog(
                                    job_id,
                                    f"[{severity_color}][{verr.code}] {verr.message}[/{severity_color}]"
                                ))
                                for suggestion in verr.suggestions[:3]:  # Limit to 3 suggestions
                                    self.post_message(JobLog(job_id, f"  → {suggestion}"))
                                if verr.incar_changes:
                                    changes = ", ".join(f"{k}={v}" for k, v in verr.incar_changes.items())
                                    self.post_message(JobLog(job_id, f"  [cyan]Try: {changes}[/cyan]"))
                    except Exception as e:
                        log.write_line(f"[dim]Error analysis failed: {e}[/dim]")

                self.post_message(JobStatus(job_id, "FAILED"))

        except asyncio.CancelledError:
            self._stop_vasp_progress_monitor(job_id)
            if runner and job_handle:
                await runner.cancel_job(job_handle)
            self.post_message(JobLog(job_id, "[red]VASP job was cancelled[/red]"))
            self.post_message(JobStatus(job_id, "FAILED"))
            raise
        except Exception as e:
            self._stop_vasp_progress_monitor(job_id)
            self.post_message(JobLog(job_id, f"[bold red]VASP job error: {e}[/bold red]"))
            self.post_message(JobStatus(job_id, "FAILED"))
        finally:
            # Cleanup tracking
            self._active_ssh_jobs.pop(job_id, None)
            self._refresh_job_list()
