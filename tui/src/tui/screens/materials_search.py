"""
Modal screen for searching Materials Project and importing structures.

Provides formula-based search with async loading and CRYSTAL23 .d12 generation.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, LoadingIndicator, Static

if TYPE_CHECKING:
    from ...core.materials_api.models import MaterialRecord


class StructureSelected(Message):
    """Message posted when a structure is selected for import."""

    def __init__(self, material_id: str, formula: str, d12_content: str) -> None:
        self.material_id = material_id
        self.formula = formula
        self.d12_content = d12_content
        super().__init__()


class MaterialsSearchScreen(ModalScreen[dict | None]):
    """Modal screen for searching Materials Project structures."""

    CSS = """
    MaterialsSearchScreen {
        align: center middle;
    }

    #search_container {
        width: 100;
        height: auto;
        max-height: 40;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #search_title {
        width: 100%;
        content-align: center middle;
        text-style: bold;
        color: $primary;
        padding: 1 0;
    }

    #search_row {
        width: 100%;
        height: auto;
        padding: 1 0;
    }

    #formula_input {
        width: 1fr;
        margin: 0 1 0 0;
    }

    #search_button {
        width: auto;
    }

    #status_message {
        width: 100%;
        padding: 1 0;
        color: $text-muted;
        text-style: italic;
    }

    #status_message.error {
        color: $error;
    }

    #results_container {
        width: 100%;
        height: 20;
        border: solid $accent-darken-1;
        margin: 1 0;
    }

    #results_table {
        width: 100%;
        height: 100%;
    }

    #loading_container {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 2;
        display: none;
    }

    #loading_container.visible {
        display: block;
    }

    #button_row {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0;
    }

    Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "search", "Search", show=False),
    ]

    def __init__(self, name: str | None = None, id: str | None = None) -> None:
        super().__init__(name=name, id=id)
        self._records: list[MaterialRecord] = []
        self._search_task: asyncio.Task | None = None
        self._import_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        """Compose the search modal layout."""
        with Container(id="search_container"):
            yield Static("Import from Materials Project", id="search_title")

            # Search input row
            with Horizontal(id="search_row"):
                yield Input(
                    placeholder="Enter formula (e.g., MoS2, Si, LiFePO4)",
                    id="formula_input",
                )
                yield Button("Search", variant="primary", id="search_button")

            yield Static(
                "Enter a chemical formula and press Search to find structures",
                id="status_message",
            )

            # Loading indicator
            with Vertical(id="loading_container"):
                yield LoadingIndicator()
                yield Static("Searching Materials Project...")

            # Results table
            with ScrollableContainer(id="results_container"):
                yield DataTable(id="results_table", cursor_type="row")

            # Action buttons
            with Horizontal(id="button_row"):
                yield Button(
                    "Import Selected", variant="success", id="import_button", disabled=True
                )
                yield Button("Cancel", variant="default", id="cancel_button")

    def on_mount(self) -> None:
        """Set up the results table columns."""
        table = self.query_one("#results_table", DataTable)
        table.add_columns("ID", "Formula", "Space Group", "Band Gap (eV)", "Stability")
        table.cursor_type = "row"

        # Focus search input
        self.query_one("#formula_input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "search_button":
            self.action_search()
        elif event.button.id == "import_button":
            self._import_selected()
        elif event.button.id == "cancel_button":
            self.action_cancel()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in search input."""
        if event.input.id == "formula_input":
            self.action_search()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enable import button when a row is selected."""
        import_button = self.query_one("#import_button", Button)
        import_button.disabled = False

    def action_cancel(self) -> None:
        """Cancel and close the modal."""
        if self._search_task and not self._search_task.done():
            self._search_task.cancel()
        if self._import_task and not self._import_task.done():
            self._import_task.cancel()
        self.dismiss(None)

    def action_search(self) -> None:
        """Start the search."""
        formula_input = self.query_one("#formula_input", Input)
        formula = formula_input.value.strip()

        if not formula:
            self._show_status("Please enter a formula to search", error=True)
            return

        # Cancel any existing search
        if self._search_task and not self._search_task.done():
            self._search_task.cancel()

        # Show loading state
        self._show_loading(True)
        self._show_status(f"Searching for {formula}...")

        # Start async search
        self._search_task = asyncio.create_task(self._do_search(formula))

    async def _do_search(self, formula: str) -> None:
        """Perform the search asynchronously."""
        try:
            # Import here to avoid circular imports and lazy-load
            from ...core.materials_api.service import MaterialsService
            from ...core.materials_api.settings import MaterialsSettings

            settings = MaterialsSettings.get_instance()

            if not settings.has_mp_api_key:
                self._show_loading(False)
                self._show_status(
                    "MP_API_KEY not set. Get your key at materialsproject.org/api",
                    error=True,
                )
                return

            async with MaterialsService(settings=settings) as service:
                result = await service.search_by_formula(formula, limit=20)

            self._records = result.records
            self._populate_table()

            if result.records:
                self._show_status(f"Found {len(result.records)} structures")
            else:
                self._show_status(f"No structures found for {formula}", error=True)

        except ImportError as e:
            self._clear_results()
            self._show_status(f"Materials API not available: {e}", error=True)
        except Exception as e:
            self._clear_results()
            self._show_status(f"Search failed: {e}", error=True)
        finally:
            self._show_loading(False)

    def _populate_table(self) -> None:
        """Populate the results table with search results."""
        table = self.query_one("#results_table", DataTable)
        table.clear()

        for record in self._records:
            # Extract properties safely
            band_gap = record.properties.get("band_gap")
            band_gap_str = f"{band_gap:.2f}" if band_gap is not None else "-"

            space_group = record.metadata.get("space_group", "-")
            if isinstance(space_group, dict):
                space_group = space_group.get("symbol", "-")

            # Check stability
            e_above_hull = record.properties.get("energy_above_hull")
            if e_above_hull is not None:
                stability = "Stable" if e_above_hull < 0.025 else f"+{e_above_hull:.3f} eV"
            else:
                stability = "-"

            table.add_row(
                record.material_id,
                record.formula or record.formula_pretty or "-",
                str(space_group),
                band_gap_str,
                stability,
            )

    def _clear_results(self) -> None:
        """Clear the results table and records list."""
        self._records = []
        table = self.query_one("#results_table", DataTable)
        table.clear()
        # Disable import button since there's nothing to import
        import_button = self.query_one("#import_button", Button)
        import_button.disabled = True

    def _import_selected(self) -> None:
        """Import the selected structure."""
        table = self.query_one("#results_table", DataTable)

        if table.cursor_row is None or table.cursor_row >= len(self._records):
            self._show_status("Please select a structure first", error=True)
            return

        record = self._records[table.cursor_row]

        # Show loading while generating .d12
        self._show_loading(True)
        self._show_status(f"Generating CRYSTAL23 input for {record.material_id}...")

        # Track task for cancellation
        self._import_task = asyncio.create_task(self._generate_and_import(record))

    async def _generate_and_import(self, record: MaterialRecord) -> None:
        """Generate .d12 content and dismiss with result dictionary."""
        try:
            from ...core.materials_api.service import MaterialsService
            from ...core.materials_api.settings import MaterialsSettings

            settings = MaterialsSettings.get_instance()

            async with MaterialsService(settings=settings) as service:
                d12_content = await service.generate_crystal_input(
                    record.material_id,
                    config={
                        "functional": "PBE",
                        "basis_set": "POB-TZVP-REV2",
                        "shrink": (8, 8),
                        "optimize": False,
                    },
                )

            formula = record.formula or record.formula_pretty or "unknown"

            # Dismiss with dictionary for callback handling
            self.dismiss(
                {
                    "d12_content": d12_content,
                    "material_id": record.material_id,
                    "formula": formula,
                    "space_group": record.space_group or "",
                    "band_gap": record.band_gap,
                    "energy_above_hull": record.energy_above_hull,
                    "source": "materials_project",
                }
            )

        except Exception as e:
            self._show_loading(False)
            self._show_status(f"Failed to generate input: {e}", error=True)

    def _show_loading(self, visible: bool) -> None:
        """Show or hide the loading indicator."""
        loading = self.query_one("#loading_container")
        if visible:
            loading.add_class("visible")
        else:
            loading.remove_class("visible")

    def _show_status(self, message: str, error: bool = False) -> None:
        """Update the status message."""
        status = self.query_one("#status_message", Static)
        status.update(message)
        if error:
            status.add_class("error")
        else:
            status.remove_class("error")
