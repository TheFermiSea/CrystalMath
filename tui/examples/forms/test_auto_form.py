#!/usr/bin/env python3
"""
Test application for AutoForm widget.

This demonstrates the AutoForm widget with various field types and features.
"""

import json
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static
from textual.containers import Container

# Add parent directory to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.tui.widgets.auto_form import AutoForm


class AutoFormTestApp(App):
    """Test application for AutoForm widget."""

    CSS = """
    Screen {
        background: $surface;
    }

    .container {
        width: 100%;
        height: 1fr;
        align: center middle;
    }

    AutoForm {
        width: 80%;
        max-width: 120;
        height: auto;
        max-height: 80%;
        border: thick $primary;
        padding: 1;
    }

    .title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin: 1 0;
    }

    .result {
        width: 80%;
        max-width: 120;
        height: auto;
        border: solid $success;
        padding: 1;
        margin: 1 0;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("1", "load_simple", "Simple Form"),
        ("2", "load_complex", "Complex Form"),
        ("3", "load_conditional", "Conditional Form"),
    ]

    def __init__(self, schema_file: str = "simple_form.json"):
        super().__init__()
        self.schema_file = schema_file
        self.form_container_id = "form-container"
        self.result_display_id = "result-display"

    def compose(self) -> ComposeResult:
        """Compose the application."""
        yield Header()

        with Container(classes="container"):
            yield Static(
                f"AutoForm Test - {self.schema_file}",
                classes="title"
            )

            # Load initial form
            schema = self._load_schema(self.schema_file)
            form = AutoForm.from_schema(schema)
            form.on_submit(self.handle_submit)
            yield form

            # Result display
            yield Static(
                "Submit form to see results here",
                id=self.result_display_id,
                classes="result"
            )

        yield Footer()

    def _load_schema(self, filename: str) -> dict:
        """Load JSON schema from file."""
        schema_path = Path(__file__).parent / filename
        with open(schema_path) as f:
            return json.load(f)

    def handle_submit(self, values: dict) -> None:
        """Handle form submission."""
        # Format values for display
        result_lines = ["Form Submitted Successfully!", ""]
        for key, value in values.items():
            result_lines.append(f"  {key}: {value}")

        result_text = "\n".join(result_lines)

        # Update result display
        result_display = self.query_one(f"#{self.result_display_id}", Static)
        result_display.update(result_text)

        self.notify("Form submitted!", severity="information")

    def on_auto_form_submitted(self, message: AutoForm.Submitted) -> None:
        """Handle AutoForm.Submitted message."""
        self.handle_submit(message.values)

    def on_auto_form_changed(self, message: AutoForm.Changed) -> None:
        """Handle field changes."""
        self.notify(
            f"Field '{message.field_name}' changed to: {message.value}",
            severity="information",
            timeout=2
        )

    async def action_load_simple(self) -> None:
        """Load simple form example."""
        await self._reload_form("simple_form.json")

    async def action_load_complex(self) -> None:
        """Load complex form example."""
        await self._reload_form("complex_form.json")

    async def action_load_conditional(self) -> None:
        """Load conditional form example."""
        await self._reload_form("conditional_form.json")

    async def _reload_form(self, filename: str) -> None:
        """Reload form with new schema."""
        self.schema_file = filename

        # Update title
        title = self.query_one(".title", Static)
        title.update(f"AutoForm Test - {filename}")

        # Remove old form
        old_form = self.query_one(AutoForm)
        await old_form.remove()

        # Load new schema
        schema = self._load_schema(filename)

        # Create new form
        form = AutoForm.from_schema(schema)
        form.on_submit(self.handle_submit)

        # Mount new form
        container = self.query_one(".container")
        await container.mount(form, before=self.result_display_id)

        self.notify(f"Loaded {filename}", severity="information")


def main():
    """Run the test application."""
    import argparse

    parser = argparse.ArgumentParser(description="Test AutoForm widget")
    parser.add_argument(
        "schema",
        nargs="?",
        default="simple_form.json",
        choices=["simple_form.json", "complex_form.json", "conditional_form.json"],
        help="Schema file to load"
    )

    args = parser.parse_args()

    app = AutoFormTestApp(schema_file=args.schema)
    app.run()


if __name__ == "__main__":
    main()
