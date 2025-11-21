"""
Modal screen for creating new CRYSTAL calculation jobs.
"""

from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Input, TextArea, Button, Static, Label
from textual.message import Message
from textual.binding import Binding

from ...core.database import Database


class JobCreated(Message):
    """Message posted when a new job is successfully created."""

    def __init__(self, job_id: int, job_name: str) -> None:
        self.job_id = job_id
        self.job_name = job_name
        super().__init__()


class NewJobScreen(ModalScreen):
    """Modal screen for creating a new CRYSTAL calculation job."""

    CSS = """
    NewJobScreen {
        align: center middle;
    }

    #modal_container {
        width: 80;
        height: auto;
        max-height: 40;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #modal_title {
        width: 100%;
        content-align: center middle;
        text-style: bold;
        color: $primary;
        padding: 1 0;
    }

    #input_section {
        width: 100%;
        height: auto;
        padding: 1 0;
    }

    #job_name_container {
        width: 100%;
        height: auto;
        padding: 0 0 1 0;
    }

    #job_name_label {
        width: 100%;
        padding: 0 0 1 0;
    }

    #job_name_input {
        width: 100%;
    }

    #textarea_container {
        width: 100%;
        height: auto;
        padding: 0 0 1 0;
    }

    #textarea_label {
        width: 100%;
        padding: 0 0 1 0;
    }

    #input_textarea {
        width: 100%;
        height: 20;
        border: solid $accent;
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
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+s", "submit", "Submit", show=False),
    ]

    def __init__(
        self,
        database: Database,
        calculations_dir: Path,
        name: Optional[str] = None,
        id: Optional[str] = None
    ):
        super().__init__(name=name, id=id)
        self.database = database
        self.calculations_dir = calculations_dir

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(id="modal_container"):
            yield Static("Create New CRYSTAL Job", id="modal_title")

            with Vertical(id="input_section"):
                # Job name input
                with Vertical(id="job_name_container"):
                    yield Label("Job Name:", id="job_name_label")
                    yield Input(
                        placeholder="Enter unique job name (e.g., mgo_bulk)",
                        id="job_name_input"
                    )

                # Input file text area
                with Vertical(id="textarea_container"):
                    yield Label("CRYSTAL Input File (.d12):", id="textarea_label")
                    yield TextArea(
                        id="input_textarea",
                        language="text",
                        theme="monokai",
                        show_line_numbers=True
                    )

            # Error message (hidden by default)
            yield Static("", id="error_message")

            # Action buttons
            with Horizontal(id="button_container"):
                with Horizontal(id="button_row"):
                    yield Button("Create Job", variant="success", id="create_button")
                    yield Button("Cancel", variant="default", id="cancel_button")

    def on_mount(self) -> None:
        """Focus the job name input when the modal opens."""
        job_name_input = self.query_one("#job_name_input", Input)
        job_name_input.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "create_button":
            self.action_submit()
        elif event.button.id == "cancel_button":
            self.action_cancel()

    def action_cancel(self) -> None:
        """Cancel and close the modal."""
        self.dismiss(None)

    def action_submit(self) -> None:
        """Validate and create the job."""
        # Get inputs
        job_name_input = self.query_one("#job_name_input", Input)
        input_textarea = self.query_one("#input_textarea", TextArea)
        error_message = self.query_one("#error_message", Static)

        job_name = job_name_input.value.strip()
        input_content = input_textarea.text.strip()

        # Clear previous error
        error_message.update("")
        error_message.remove_class("visible")

        # Validate job name
        if not job_name:
            self._show_error("Job name cannot be empty")
            job_name_input.focus()
            return

        # Check for invalid characters in job name
        if not all(c.isalnum() or c in "_-" for c in job_name):
            self._show_error("Job name can only contain letters, numbers, hyphens, and underscores")
            job_name_input.focus()
            return

        # Check if job name already exists
        existing_jobs = self.database.get_all_jobs()
        if any(job.name == job_name for job in existing_jobs):
            self._show_error(f"Job name '{job_name}' already exists")
            job_name_input.focus()
            return

        # Validate input content
        if not input_content:
            self._show_error("Input file content cannot be empty")
            input_textarea.focus()
            return

        # Basic validation: check for required sections
        validation_error = self._validate_crystal_input(input_content)
        if validation_error:
            self._show_error(validation_error)
            input_textarea.focus()
            return

        # Generate next job ID
        next_id = max([job.id for job in existing_jobs], default=0) + 1

        # Create work directory
        work_dir_name = f"{next_id:04d}_{job_name}"
        work_dir = self.calculations_dir / work_dir_name

        try:
            work_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            self._show_error(f"Work directory already exists: {work_dir_name}")
            return
        except Exception as e:
            self._show_error(f"Failed to create work directory: {str(e)}")
            return

        # Write input file
        input_file = work_dir / "input.d12"
        try:
            input_file.write_text(input_content)
        except Exception as e:
            self._show_error(f"Failed to write input file: {str(e)}")
            # Clean up directory
            try:
                work_dir.rmdir()
            except:
                pass
            return

        # Add job to database
        try:
            job_id = self.database.create_job(
                name=job_name,
                work_dir=str(work_dir),
                input_content=input_content
            )
        except Exception as e:
            self._show_error(f"Failed to create job in database: {str(e)}")
            # Clean up files
            try:
                input_file.unlink()
                work_dir.rmdir()
            except:
                pass
            return

        # Success - post message and close modal
        self.dismiss(job_id)
        self.post_message(JobCreated(job_id, job_name))

    def _show_error(self, message: str) -> None:
        """Display an error message."""
        error_message = self.query_one("#error_message", Static)
        error_message.update(f"Error: {message}")
        error_message.add_class("visible")

    def _validate_crystal_input(self, content: str) -> Optional[str]:
        """
        Perform basic validation on CRYSTAL input content.
        Returns error message if invalid, None if valid.
        """
        lines = content.strip().split('\n')

        if len(lines) < 5:
            return "Input file too short - must contain at least title, geometry, and basis set"

        # Check for required keywords (case insensitive)
        content_upper = content.upper()

        # Must have either CRYSTAL, SLAB, POLYMER, or MOLECULE keyword
        if not any(keyword in content_upper for keyword in ['CRYSTAL', 'SLAB', 'POLYMER', 'MOLECULE', 'EXTERNAL']):
            return "Input must contain geometry type keyword (CRYSTAL, SLAB, POLYMER, or MOLECULE)"

        # Must have END keyword
        if 'END' not in content_upper:
            return "Input must contain END keyword"

        # Count END keywords - should have at least 2 (geometry + basis set)
        end_count = content_upper.count('END')
        if end_count < 2:
            return "Input must contain at least 2 END keywords (geometry and basis set sections)"

        return None
