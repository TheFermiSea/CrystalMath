"""
Quantum ESPRESSO Pseudopotential (UPF) Manager Screen.

Handles QE's pseudopotential requirements:
- UPF file selection/upload for each element in the structure
- PSEUDO_DIR path configuration per cluster
- Validation that all elements have assigned pseudopotentials
- Generation of ATOMIC_SPECIES block for QE input

Provides UI for:
- Listing elements detected from structure
- Selecting UPF files from library or uploading custom
- Configuring cluster-specific PSEUDO_DIR paths
- Validating pseudopotential coverage
"""

import asyncio
import logging
from dataclasses import dataclass

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.validation import ValidationResult, Validator
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    Select,
    Static,
)

from ...core.database import Database

logger = logging.getLogger(__name__)


# Standard atomic masses for common elements
ATOMIC_MASSES = {
    "H": 1.008,
    "He": 4.003,
    "Li": 6.941,
    "Be": 9.012,
    "B": 10.81,
    "C": 12.01,
    "N": 14.01,
    "O": 16.00,
    "F": 19.00,
    "Ne": 20.18,
    "Na": 22.99,
    "Mg": 24.31,
    "Al": 26.98,
    "Si": 28.09,
    "P": 30.97,
    "S": 32.07,
    "Cl": 35.45,
    "Ar": 39.95,
    "K": 39.10,
    "Ca": 40.08,
    "Sc": 44.96,
    "Ti": 47.87,
    "V": 50.94,
    "Cr": 52.00,
    "Mn": 54.94,
    "Fe": 55.85,
    "Co": 58.93,
    "Ni": 58.69,
    "Cu": 63.55,
    "Zn": 65.38,
    "Ga": 69.72,
    "Ge": 72.63,
    "As": 74.92,
    "Se": 78.97,
    "Br": 79.90,
    "Kr": 83.80,
    "Rb": 85.47,
    "Sr": 87.62,
    "Y": 88.91,
    "Zr": 91.22,
    "Nb": 92.91,
    "Mo": 95.95,
    "Tc": 98.00,
    "Ru": 101.1,
    "Rh": 102.9,
    "Pd": 106.4,
    "Ag": 107.9,
    "Cd": 112.4,
    "In": 114.8,
    "Sn": 118.7,
    "Sb": 121.8,
    "Te": 127.6,
    "I": 126.9,
    "Xe": 131.3,
}

# Common UPF library prefixes (from SSSP, PSlibrary, etc.)
UPF_LIBRARIES = {
    "SSSP Efficiency": "sssp_efficiency",
    "SSSP Precision": "sssp_precision",
    "PSlibrary PAW": "pslibrary_paw",
    "PSlibrary US": "pslibrary_us",
    "Custom": "custom",
}


@dataclass
class ElementPseudopotential:
    """Pseudopotential assignment for a single element."""

    element: str
    mass: float
    upf_filename: str = ""
    library: str = "SSSP Efficiency"
    custom_content: str | None = None
    validated: bool = False


class QEPseudopotentialsReady(Message):
    """Message posted when QE pseudopotentials are configured."""

    def __init__(
        self,
        pseudo_dir: str,
        element_pseudos: dict[str, str],  # element -> UPF filename
        atomic_species_block: str,
        job_name: str,
    ):
        self.pseudo_dir = pseudo_dir
        self.element_pseudos = element_pseudos
        self.atomic_species_block = atomic_species_block
        self.job_name = job_name
        super().__init__()


class PseudoDirValidator(Validator):
    """Validates PSEUDO_DIR path format."""

    def validate(self, value: str) -> ValidationResult:
        """Check if path looks valid."""
        if not value.strip():
            return self.failure("PSEUDO_DIR path is required")

        # Basic path validation
        if not value.startswith("/") and not value.startswith("~"):
            return self.failure("Path should be absolute (start with / or ~)")

        return self.success()


class QEPseudopotentialManagerScreen(ModalScreen):
    """
    Screen for managing Quantum ESPRESSO pseudopotentials.

    Allows users to:
    - See elements detected from structure
    - Assign UPF files to each element
    - Configure PSEUDO_DIR path for the cluster
    - Validate all elements have pseudopotentials
    - Generate ATOMIC_SPECIES block
    """

    CSS = """
    QEPseudopotentialManagerScreen {
        align: center middle;
    }

    #modal_container {
        width: 110;
        height: 45;
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

    #pseudo_dir_section {
        height: auto;
        padding: 1 0;
    }

    #pseudo_dir_input {
        width: 100%;
    }

    #elements_section {
        height: 1fr;
        padding: 1 0;
    }

    #elements_table {
        height: 100%;
        border: solid $accent;
    }

    .section_label {
        padding: 0 0 1 0;
        color: $text;
        text-style: bold;
    }

    .info_text {
        padding: 1;
        color: $text-muted;
    }

    #library_select {
        width: 40;
    }

    #upf_input_section {
        height: auto;
        padding: 1 0;
    }

    #upf_filename_input {
        width: 60;
    }

    #actions {
        height: 3;
        align: center middle;
    }

    #actions Button {
        margin-right: 1;
    }

    #status_message {
        padding: 1;
        text-align: center;
        color: $text;
    }

    #atomic_species_preview {
        height: 6;
        border: solid $accent;
        background: $surface-darken-1;
        padding: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "dismiss", "Close"),
    ]

    def __init__(
        self,
        db: Database,
        elements: list[str],
        cluster_id: int | None = None,
        default_pseudo_dir: str = "/usr/share/espresso/pseudo",
    ):
        """
        Initialize QE pseudopotential manager.

        Args:
            db: Database instance
            elements: List of element symbols from structure
            cluster_id: Optional cluster ID for storing PSEUDO_DIR
            default_pseudo_dir: Default PSEUDO_DIR path
        """
        super().__init__()
        self.db = db
        self.cluster_id = cluster_id
        self.default_pseudo_dir = default_pseudo_dir

        # Initialize pseudopotential assignments
        self.element_pseudos: dict[str, ElementPseudopotential] = {}
        unique_elements = sorted(set(elements))
        for elem in unique_elements:
            mass = ATOMIC_MASSES.get(elem, 1.0)
            self.element_pseudos[elem] = ElementPseudopotential(
                element=elem,
                mass=mass,
                upf_filename=self._get_default_upf_name(elem),
            )

        self._selected_element: str | None = None
        self._current_library = "SSSP Efficiency"

    def _get_default_upf_name(self, element: str) -> str:
        """Generate default UPF filename based on SSSP naming convention."""
        # SSSP efficiency naming: Element.pbe-spn-kjpaw_psl.1.0.0.UPF
        return f"{element}.pbe-n-kjpaw_psl.1.0.0.UPF"

    def compose(self) -> ComposeResult:
        """Create the UI layout."""
        with Container(id="modal_container"):
            yield Static("Quantum ESPRESSO Pseudopotential Manager", id="modal_title")

            yield Static(
                "Configure UPF pseudopotentials for each element in your structure",
                classes="info_text",
            )

            # PSEUDO_DIR configuration
            with Vertical(id="pseudo_dir_section"):
                yield Label("PSEUDO_DIR Path:", classes="section_label")
                yield Input(
                    value=self.default_pseudo_dir,
                    placeholder="/path/to/pseudopotentials",
                    id="pseudo_dir_input",
                )

            # Elements table
            with Vertical(id="elements_section"):
                yield Label("Element Pseudopotentials:", classes="section_label")
                yield DataTable(id="elements_table")

            # UPF configuration for selected element
            with Vertical(id="upf_input_section"):
                with Horizontal():
                    yield Label("Library:", classes="section_label")
                    yield Select(
                        options=[(name, key) for name, key in UPF_LIBRARIES.items()],
                        value="sssp_efficiency",
                        id="library_select",
                    )

                with Horizontal():
                    yield Label("UPF Filename:", classes="section_label")
                    yield Input(
                        placeholder="Element.pbe-xxx.UPF",
                        id="upf_filename_input",
                    )
                    yield Button("Apply", id="apply_upf_btn", variant="primary")

            # Preview of ATOMIC_SPECIES block
            yield Label("Generated ATOMIC_SPECIES block:", classes="section_label")
            yield Static("", id="atomic_species_preview")

            # Job name input
            with Horizontal():
                yield Label("Job Name:", classes="section_label")
                yield Input(placeholder="e.g., silicon_scf", id="job_name_input")

            # Actions
            with Horizontal(id="actions"):
                yield Button("Validate All", id="validate_btn", variant="default")
                yield Button("Apply & Continue", id="continue_btn", variant="success")
                yield Button("Cancel", id="cancel_btn")

            # Status messages
            yield Static("", id="status_message")

    def on_mount(self) -> None:
        """Initialize the elements table."""
        table = self.query_one("#elements_table", DataTable)
        table.add_columns("Element", "Mass", "UPF Filename", "Status")
        table.cursor_type = "row"

        for elem, pseudo in self.element_pseudos.items():
            status = "✅" if pseudo.validated else "⚠️ Unverified"
            table.add_row(elem, f"{pseudo.mass:.3f}", pseudo.upf_filename, status, key=elem)

        self._update_atomic_species_preview()

    def _update_atomic_species_preview(self) -> None:
        """Update the ATOMIC_SPECIES block preview."""
        preview = self.query_one("#atomic_species_preview", Static)

        lines = ["ATOMIC_SPECIES"]
        for elem, pseudo in sorted(self.element_pseudos.items()):
            lines.append(f"  {elem}  {pseudo.mass:.4f}  {pseudo.upf_filename}")

        preview.update("\n".join(lines))

    @on(DataTable.RowSelected, "#elements_table")
    def _on_element_selected(self, event: DataTable.RowSelected) -> None:
        """Handle element selection in table."""
        if event.row_key is not None:
            elem = str(event.row_key.value)
            self._selected_element = elem

            # Update UPF input with current value
            upf_input = self.query_one("#upf_filename_input", Input)
            if elem in self.element_pseudos:
                upf_input.value = self.element_pseudos[elem].upf_filename

            status = self.query_one("#status_message", Static)
            status.update(f"Selected: {elem}")

    @on(Select.Changed, "#library_select")
    def _on_library_changed(self, event: Select.Changed) -> None:
        """Handle library selection change."""
        library_key = str(event.value)

        # Map key back to display name
        for name, key in UPF_LIBRARIES.items():
            if key == library_key:
                self._current_library = name
                break

        # Update UPF filename suggestion if element is selected
        if self._selected_element:
            elem = self._selected_element
            upf_input = self.query_one("#upf_filename_input", Input)

            if library_key == "sssp_efficiency":
                upf_input.value = f"{elem}.pbe-n-kjpaw_psl.1.0.0.UPF"
            elif library_key == "sssp_precision":
                upf_input.value = f"{elem}.pbe-n-rrkjus_psl.1.0.0.UPF"
            elif library_key == "pslibrary_paw":
                upf_input.value = f"{elem}.pbe-n-kjpaw_psl.0.1.UPF"
            elif library_key == "pslibrary_us":
                upf_input.value = f"{elem}.pbe-n-rrkjus_psl.0.1.UPF"
            # Custom keeps current value

    @on(Button.Pressed, "#apply_upf_btn")
    def _apply_upf(self, event: Button.Pressed) -> None:
        """Apply UPF filename to selected element."""
        status = self.query_one("#status_message", Static)

        if not self._selected_element:
            status.update("❌ Select an element first")
            return

        upf_input = self.query_one("#upf_filename_input", Input)
        upf_filename = upf_input.value.strip()

        if not upf_filename:
            status.update("❌ UPF filename is required")
            return

        if not upf_filename.endswith(".UPF") and not upf_filename.endswith(".upf"):
            status.update("❌ UPF filename should end with .UPF or .upf")
            return

        # Update the pseudopotential assignment
        elem = self._selected_element
        self.element_pseudos[elem].upf_filename = upf_filename
        self.element_pseudos[elem].library = self._current_library

        # Update table
        table = self.query_one("#elements_table", DataTable)
        pseudo = self.element_pseudos[elem]
        table.update_cell(elem, "UPF Filename", upf_filename)

        self._update_atomic_species_preview()
        status.update(f"✅ Applied {upf_filename} to {elem}")

    @on(Button.Pressed, "#validate_btn")
    def _validate_all(self, event: Button.Pressed) -> None:
        """Validate all pseudopotential assignments."""
        status = self.query_one("#status_message", Static)
        table = self.query_one("#elements_table", DataTable)

        # Validate PSEUDO_DIR
        pseudo_dir_input = self.query_one("#pseudo_dir_input", Input)
        validator = PseudoDirValidator()
        result = validator.validate(pseudo_dir_input.value)

        if not result.is_valid:
            error_msg = (
                result.failure_descriptions[0] if result.failure_descriptions else "Invalid path"
            )
            status.update(f"❌ PSEUDO_DIR: {error_msg}")
            return

        # Validate all elements have UPF assignments
        missing = []
        for elem, pseudo in self.element_pseudos.items():
            if not pseudo.upf_filename:
                missing.append(elem)
                table.update_cell(elem, "Status", "❌ Missing")
            else:
                pseudo.validated = True
                table.update_cell(elem, "Status", "✅ OK")

        if missing:
            status.update(f"❌ Missing pseudopotentials for: {', '.join(missing)}")
            return

        status.update(
            f"✅ All {len(self.element_pseudos)} elements have valid pseudopotential assignments!"
        )

    @on(Button.Pressed, "#continue_btn")
    async def _continue(self, event: Button.Pressed) -> None:
        """Apply configuration and continue."""
        status = self.query_one("#status_message", Static)

        # Get job name
        job_name_input = self.query_one("#job_name_input", Input)
        job_name = job_name_input.value.strip()

        if not job_name:
            status.update("❌ Job name is required")
            return

        # Validate PSEUDO_DIR
        pseudo_dir_input = self.query_one("#pseudo_dir_input", Input)
        pseudo_dir = pseudo_dir_input.value.strip()

        validator = PseudoDirValidator()
        result = validator.validate(pseudo_dir)
        if not result.is_valid:
            error_msg = (
                result.failure_descriptions[0] if result.failure_descriptions else "Invalid path"
            )
            status.update(f"❌ PSEUDO_DIR: {error_msg}")
            return

        # Check all elements have assignments
        missing = [e for e, p in self.element_pseudos.items() if not p.upf_filename]
        if missing:
            status.update(f"❌ Missing pseudopotentials for: {', '.join(missing)}")
            return

        # Build element -> filename mapping
        element_pseudos = {
            elem: pseudo.upf_filename for elem, pseudo in self.element_pseudos.items()
        }

        # Generate ATOMIC_SPECIES block
        lines = ["ATOMIC_SPECIES"]
        for elem, pseudo in sorted(self.element_pseudos.items()):
            lines.append(f"  {elem}  {pseudo.mass:.4f}  {pseudo.upf_filename}")
        atomic_species_block = "\n".join(lines)

        # Post message
        self.post_message(
            QEPseudopotentialsReady(
                pseudo_dir=pseudo_dir,
                element_pseudos=element_pseudos,
                atomic_species_block=atomic_species_block,
                job_name=job_name,
            )
        )

        status.update(f"✅ Pseudopotentials configured for job '{job_name}'")

        # Dismiss after brief delay
        await asyncio.sleep(1)
        self.dismiss()

    @on(Button.Pressed, "#cancel_btn")
    def _cancel(self, event: Button.Pressed) -> None:
        """Cancel and close the screen."""
        self.dismiss()

    def action_dismiss(self) -> None:
        """Dismiss the screen."""
        self.dismiss()
