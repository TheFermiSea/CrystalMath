"""
Batch job submission screen for creating multiple CRYSTAL calculation jobs.
"""

import os
from pathlib import Path
from typing import Optional, List, Dict, Any, Set
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual.widgets import Input, Button, Static, Label, Select, DataTable
from textual.message import Message
from textual.binding import Binding

from ...core.core_adapter import CrystalCoreClient, job_record_to_status
from ...core.database import Database
from crystalmath.models import DftCode, JobSubmission, RunnerType, SchedulerOptions, JobStatus


@dataclass
class BatchJobConfig:
    """Configuration for a single job in the batch."""
    name: str
    input_file: Path
    cluster: str = "local"
    mpi_ranks: int = 1
    threads: int = 4
    partition: str = "compute"
    time_limit: str = "24:00:00"


class BatchJobsCreated(Message):
    """Message posted when batch jobs are successfully created."""

    def __init__(self, job_ids: List[int], job_names: List[str]) -> None:
        self.job_ids = job_ids
        self.job_names = job_names
        super().__init__()


class BatchSubmissionScreen(ModalScreen):
    """Modal screen for batch submission of multiple CRYSTAL calculation jobs."""

    CSS = """
    BatchSubmissionScreen {
        align: center middle;
    }

    #batch_modal_container {
        width: 100;
        height: 50;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #batch_modal_title {
        width: 100%;
        content-align: center middle;
        text-style: bold;
        color: $primary;
        padding: 1 0;
    }

    #settings_section {
        width: 100%;
        height: auto;
        border: solid $accent-darken-1;
        padding: 1;
        margin: 0 0 1 0;
    }

    .settings_row {
        width: 100%;
        height: auto;
        layout: horizontal;
        padding: 0 0 1 0;
    }

    .settings_label {
        width: 20;
        content-align: left middle;
    }

    .settings_input {
        width: 1fr;
        margin: 0 1 0 0;
    }

    #jobs_section {
        width: 100%;
        height: 1fr;
        border: solid $accent-darken-1;
        padding: 1;
        margin: 0 0 1 0;
    }

    #jobs_table {
        width: 100%;
        height: 1fr;
    }

    #status_section {
        width: 100%;
        height: auto;
        border: solid $accent-darken-1;
        padding: 1;
        margin: 0 0 1 0;
    }

    #status_message {
        width: 100%;
        color: $text;
    }

    #progress_message {
        width: 100%;
        color: $accent;
        text-style: italic;
        display: none;
    }

    #progress_message.visible {
        display: block;
    }

    #button_container {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
    }

    #button_row {
        width: auto;
        height: auto;
    }

    Button {
        margin: 0 1;
        min-width: 15;
    }

    #error_message {
        width: 100%;
        color: $error;
        text-style: bold;
        padding: 1 0;
        display: none;
    }

    #error_message.visible {
        display: block;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("a", "add_job", "Add Job", show=True),
        Binding("d", "delete_job", "Delete", show=True),
        Binding("enter", "submit_all", "Submit All", show=True),
    ]

    def __init__(
        self,
        database: Database,
        calculations_dir: Path,
        core_client: CrystalCoreClient | None = None,
        name: Optional[str] = None,
        id: Optional[str] = None
    ):
        super().__init__(name=name, id=id)
        self.database = database
        self.calculations_dir = calculations_dir
        self.core_client = core_client
        self.job_configs: List[BatchJobConfig] = []
        self.submitting = False

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(id="batch_modal_container"):
            yield Static("Batch Job Submission", id="batch_modal_title")

            # Common Settings Section
            with Vertical(id="settings_section"):
                yield Label("Common Settings:")

                with Horizontal(classes="settings_row"):
                    yield Label("Cluster:", classes="settings_label")
                    yield Select(
                        [("Local", "local"), ("HPC-Cluster", "hpc")],
                        value="local",
                        id="cluster_select",
                        classes="settings_input"
                    )
                    yield Label("Partition:", classes="settings_label")
                    yield Input(
                        placeholder="compute",
                        value="compute",
                        id="partition_input",
                        classes="settings_input"
                    )

                with Horizontal(classes="settings_row"):
                    yield Label("MPI Ranks:", classes="settings_label")
                    yield Input(
                        placeholder="14",
                        value="14",
                        id="mpi_ranks_input",
                        classes="settings_input"
                    )
                    yield Label("Threads:", classes="settings_label")
                    yield Input(
                        placeholder="4",
                        value="4",
                        id="threads_input",
                        classes="settings_input"
                    )
                    yield Label("Time Limit:", classes="settings_label")
                    yield Input(
                        placeholder="24:00:00",
                        value="24:00:00",
                        id="time_limit_input",
                        classes="settings_input"
                    )

            # Jobs List Section
            with Vertical(id="jobs_section"):
                yield Label(f"Jobs ({len(self.job_configs)} total):", id="jobs_count_label")
                yield DataTable(id="jobs_table", zebra_stripes=True, cursor_type="row")

            # Status Section
            with Vertical(id="status_section"):
                yield Static("", id="status_message")
                yield Static("", id="progress_message")

            # Error message (hidden by default)
            yield Static("", id="error_message")

            # Action buttons
            with Horizontal(id="button_container"):
                with Horizontal(id="button_row"):
                    yield Button("Add Job", variant="primary", id="add_job_button")
                    yield Button("Remove", variant="default", id="remove_button")
                    yield Button("Submit All", variant="success", id="submit_button")
                    yield Button("Cancel", variant="default", id="cancel_button")

    def on_mount(self) -> None:
        """Initialize the table when the modal opens."""
        table = self.query_one("#jobs_table", DataTable)
        table.add_columns("Name", "Input File", "Status", "Cluster", "Resources")
        self._update_job_count()
        self._update_status("Ready to add jobs. Press 'a' or click 'Add Job'.")

    def action_add_job(self) -> None:
        """Open file picker to add a job to the batch."""
        if self.submitting:
            return

        # For now, we'll use a simple input dialog approach
        # In production, this would open a file picker dialog
        self._show_status("Enter job details in the new job modal (coming soon)...")

        # Simulate adding a job for demonstration
        # In production, this would open a NewJobScreen or file picker
        self._add_demo_job()

    def _add_demo_job(self) -> None:
        """Add a demo job for testing (placeholder for file picker)."""
        # Generate unique job name
        job_num = len(self.job_configs) + 1
        job_name = f"batch_job_{job_num}"

        # Check if input files exist in current directory
        possible_inputs = list(Path.cwd().glob("*.d12"))
        if possible_inputs:
            input_file = possible_inputs[0]
        else:
            # Create a placeholder
            input_file = Path(f"/tmp/demo_{job_num}.d12")

        # Get common settings
        cluster = self.query_one("#cluster_select", Select).value

        try:
            mpi_ranks = int(self.query_one("#mpi_ranks_input", Input).value)
        except ValueError:
            mpi_ranks = 1

        try:
            threads = int(self.query_one("#threads_input", Input).value)
        except ValueError:
            threads = 4

        partition = self.query_one("#partition_input", Input).value or "compute"
        time_limit = self.query_one("#time_limit_input", Input).value or "24:00:00"

        # Create job config
        config = BatchJobConfig(
            name=job_name,
            input_file=input_file,
            cluster=str(cluster),
            mpi_ranks=mpi_ranks,
            threads=threads,
            partition=partition,
            time_limit=time_limit
        )

        self.job_configs.append(config)
        self._refresh_jobs_table()
        self._update_job_count()
        self._show_status(f"Added job '{job_name}'. Total jobs: {len(self.job_configs)}")

    def action_delete_job(self) -> None:
        """Delete the selected job from the batch."""
        if self.submitting:
            return

        table = self.query_one("#jobs_table", DataTable)

        if not table.cursor_row:
            self._show_error("No job selected. Use arrow keys to select a job.")
            return

        row_key = table.cursor_row
        row_index = list(table.rows.keys()).index(row_key)

        if 0 <= row_index < len(self.job_configs):
            removed_job = self.job_configs.pop(row_index)
            self._refresh_jobs_table()
            self._update_job_count()
            self._show_status(f"Removed job '{removed_job.name}'. Total jobs: {len(self.job_configs)}")

    def action_submit_all(self) -> None:
        """Validate and submit all jobs in the batch."""
        if self.submitting:
            return

        if not self.job_configs:
            self._show_error("No jobs to submit. Add jobs first.")
            return

        # Validate all jobs
        validation_errors = self._validate_batch()
        if validation_errors:
            self._show_error(f"Validation failed: {validation_errors[0]}")
            return

        # Start submission
        self.submitting = True
        self._disable_buttons()
        self._show_progress("Submitting jobs...")

        # Submit jobs asynchronously
        self.run_worker(self._submit_jobs_worker(), exclusive=True)

    async def _submit_jobs_worker(self) -> None:
        """Worker to submit all jobs in the batch."""
        try:
            job_ids = []
            job_names = []

            for i, config in enumerate(self.job_configs):
                # Update progress
                progress_msg = f"Submitting job {i+1}/{len(self.job_configs)}: {config.name}"
                self._show_progress(progress_msg)
                self._update_job_status(i, "SUBMITTING")

                if self.core_client:
                    input_content = self._read_input_content(config)
                    if input_content is None:
                        self._update_job_status(i, "ERROR: Missing input")
                        continue

                    try:
                        submission = self._build_submission_from_config(config, input_content)
                        job_id = self.core_client.submit_job(submission)
                        job_ids.append(job_id)
                        job_names.append(config.name)
                        self._update_job_status(i, "PENDING")
                        continue
                    except Exception as exc:
                        self._update_job_status(i, f"ERROR: {exc}")
                        continue

                existing_jobs = self.database.get_all_jobs()
                next_id = max([job.id for job in existing_jobs], default=0) + 1 + i
                work_dir_name = f"{next_id:04d}_{config.name}"
                work_dir = self.calculations_dir / work_dir_name

                try:
                    work_dir.mkdir(parents=True, exist_ok=False)
                except FileExistsError:
                    self._update_job_status(i, "ERROR: Dir exists")
                    continue

                input_content = self._read_input_content(config, allow_placeholder=True)
                if input_content is None:
                    self._update_job_status(i, "ERROR: Missing input")
                    try:
                        import shutil

                        shutil.rmtree(work_dir)
                    except Exception:
                        pass
                    continue

                dest_input = work_dir / "input.d12"
                dest_input.write_text(input_content)

                import json
                metadata = {
                    "mpi_ranks": config.mpi_ranks,
                    "threads": config.threads,
                    "cluster": config.cluster,
                    "partition": config.partition,
                    "time_limit": config.time_limit,
                    "parallel_mode": "parallel" if config.mpi_ranks > 1 else "serial"
                }
                metadata_file = work_dir / "job_metadata.json"
                metadata_file.write_text(json.dumps(metadata, indent=2))

                job_id = self.database.create_job(
                    name=config.name,
                    work_dir=str(work_dir),
                    input_content=input_content
                )

                job_ids.append(job_id)
                job_names.append(config.name)
                self._update_job_status(i, "PENDING")

            # All jobs submitted successfully
            self._show_progress(f"Successfully submitted {len(job_ids)} jobs!")
            self._show_status(f"Batch submission complete. Created {len(job_ids)} jobs.")

            # Post message and close
            self.post_message(BatchJobsCreated(job_ids, job_names))

            # Wait a moment for user to see success message
            import asyncio
            await asyncio.sleep(1.5)

            self.dismiss(job_ids)

        except Exception as e:
            self._show_error(f"Batch submission failed: {str(e)}")
            self.submitting = False
            self._enable_buttons()

    def _validate_batch(self) -> List[str]:
        """Validate all jobs in the batch. Returns list of error messages."""
        errors = []

        # Check for duplicate names
        names = [job.name for job in self.job_configs]
        if len(names) != len(set(names)):
            errors.append("Duplicate job names found in batch")

        # Check each job
        existing_names = self._existing_job_names()
        for i, config in enumerate(self.job_configs):
            # Validate name
            if not config.name or not config.name.strip():
                errors.append(f"Job {i+1}: Name is empty")

            if not all(c.isalnum() or c in "_-" for c in config.name):
                errors.append(f"Job {i+1}: Invalid characters in name '{config.name}'")

            # Check if name conflicts with existing jobs
            if config.name in existing_names:
                errors.append(f"Job {i+1}: Name '{config.name}' already exists")

            # Validate resources
            if config.mpi_ranks < 1:
                errors.append(f"Job {i+1}: MPI ranks must be >= 1")

            if config.threads < 1:
                errors.append(f"Job {i+1}: Threads must be >= 1")

        return errors

    def _existing_job_names(self) -> Set[str]:
        """Return existing job names using the latest job statuses."""
        return {status.name for status in self._list_all_job_statuses()}

    def _list_all_job_statuses(self) -> list[JobStatus]:
        """Helper: fetch statuses via core client or fallback to legacy DB."""
        if self.core_client:
            try:
                return self.core_client.list_jobs()
            except Exception:
                pass

        if self.database:
            return [job_record_to_status(job) for job in self.database.get_all_jobs()]

        return []

    def _read_input_content(self, config: BatchJobConfig, allow_placeholder: bool = False) -> Optional[str]:
        """Read input content for a job config, returning None if missing."""
        if config.input_file.exists():
            return config.input_file.read_text()
        if allow_placeholder:
            return "# Placeholder input\nEND\nEND\n"
        return None

    def _build_submission_from_config(
        self,
        config: BatchJobConfig,
        input_content: str
    ) -> JobSubmission:
        """Construct a JobSubmission object from a batch config."""
        runner_type = self._map_runner_type(config.cluster)
        scheduler_options = None
        if runner_type == RunnerType.SLURM:
            scheduler_options = SchedulerOptions(
                walltime=config.time_limit,
                memory_gb="32",
                cpus_per_task=config.threads,
                nodes=1,
            )

        return JobSubmission(
            name=config.name,
            dft_code=DftCode.CRYSTAL,
            runner_type=runner_type,
            parameters={},
            input_content=input_content,
            auxiliary_files=None,
            scheduler_options=scheduler_options,
            mpi_ranks=config.mpi_ranks if config.mpi_ranks > 0 else 1,
            parallel_mode="parallel" if config.mpi_ranks > 1 else "serial",
        )

    def _map_runner_type(self, cluster: str) -> RunnerType:
        """Map the batch cluster selection to RunnerType."""
        if cluster == "hpc":
            return RunnerType.SLURM
        if cluster == "ssh":
            return RunnerType.SSH
        return RunnerType.LOCAL

    def _refresh_jobs_table(self) -> None:
        """Refresh the jobs table with current job configs."""
        table = self.query_one("#jobs_table", DataTable)
        table.clear()

        for config in self.job_configs:
            resources = f"{config.mpi_ranks}×{config.threads}"
            input_file_name = config.input_file.name if config.input_file else "N/A"

            table.add_row(
                config.name,
                input_file_name,
                "READY",
                config.cluster,
                resources
            )

    def _update_job_status(self, job_index: int, status: str) -> None:
        """Update the status of a specific job in the table."""
        table = self.query_one("#jobs_table", DataTable)

        if job_index < len(table.rows):
            row_key = list(table.rows.keys())[job_index]
            table.update_cell(row_key, "Status", status)

    def _update_job_count(self) -> None:
        """Update the job count label."""
        label = self.query_one("#jobs_count_label", Label)
        label.update(f"Jobs ({len(self.job_configs)} total):")

    def _show_status(self, message: str) -> None:
        """Show a status message."""
        status = self.query_one("#status_message", Static)
        status.update(message)

    def _show_progress(self, message: str) -> None:
        """Show a progress message."""
        progress = self.query_one("#progress_message", Static)
        progress.update(message)
        progress.add_class("visible")

    def _show_error(self, message: str) -> None:
        """Display an error message."""
        error_message = self.query_one("#error_message", Static)
        error_message.update(f"Error: {message}")
        error_message.add_class("visible")

        # Clear after 5 seconds
        self.set_timer(5.0, self._clear_error)

    def _clear_error(self) -> None:
        """Clear the error message."""
        error_message = self.query_one("#error_message", Static)
        error_message.update("")
        error_message.remove_class("visible")

    def _update_status(self, message: str) -> None:
        """Update status message (alias for _show_status)."""
        self._show_status(message)

    def _disable_buttons(self) -> None:
        """Disable all buttons during submission."""
        for button_id in ["add_job_button", "remove_button", "submit_button", "cancel_button"]:
            button = self.query_one(f"#{button_id}", Button)
            button.disabled = True

    def _enable_buttons(self) -> None:
        """Re-enable all buttons after submission."""
        for button_id in ["add_job_button", "remove_button", "submit_button", "cancel_button"]:
            button = self.query_one(f"#{button_id}", Button)
            button.disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "add_job_button":
            self.action_add_job()
        elif event.button.id == "remove_button":
            self.action_delete_job()
        elif event.button.id == "submit_button":
            self.action_submit_all()
        elif event.button.id == "cancel_button":
            self.action_cancel()

    def action_cancel(self) -> None:
        """Cancel and close the modal."""
        if not self.submitting:
            self.dismiss(None)
