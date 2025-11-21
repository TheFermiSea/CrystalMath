#!/usr/bin/env python3
"""
Quick test script for the NewJobScreen modal.
Tests that all widgets render and behave correctly.
"""

from pathlib import Path
import tempfile
import shutil

from textual.app import App, ComposeResult
from textual.widgets import Button

# Add src to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent / "src"))

from tui.screens.new_job import NewJobScreen
from core.database import Database


class TestApp(App):
    """Test application for the new job modal."""

    CSS = """
    Screen {
        align: center middle;
    }
    """

    def compose(self) -> ComposeResult:
        yield Button("Open New Job Modal", id="open_modal")

    def on_mount(self) -> None:
        # Create temporary database and calculations directory
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db_path = self.temp_dir / ".crystal_tui.db"
        self.calculations_dir = self.temp_dir / "calculations"
        self.calculations_dir.mkdir()

        self.db = Database(self.db_path)

        self.title = "Test: New Job Modal"
        self.sub_title = "Press 'Open New Job Modal' or 'n' key"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open_modal":
            self.action_show_modal()

    def action_show_modal(self) -> None:
        """Show the new job modal."""
        self.push_screen(
            NewJobScreen(
                database=self.db,
                calculations_dir=self.calculations_dir
            ),
            self.handle_job_created
        )

    def handle_job_created(self, job_id) -> None:
        """Handle the result from the modal."""
        if job_id is not None:
            self.notify(f"Job created with ID: {job_id}", title="Success", severity="information")

            # Show job details
            job = self.db.get_job(job_id)
            if job:
                self.notify(
                    f"Name: {job.name}\nWork Dir: {job.work_dir}\nStatus: {job.status}",
                    title="Job Details",
                    severity="information",
                    timeout=10
                )
        else:
            self.notify("Job creation cancelled", severity="warning")

    def on_unmount(self) -> None:
        """Clean up temporary directory."""
        if hasattr(self, 'temp_dir') and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)


if __name__ == "__main__":
    app = TestApp()
    app.run()
