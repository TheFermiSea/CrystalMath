"""
VASP Multi-File Input Manager Screen.

Handles VASP's requirement for 4 input files:
- POSCAR: Atomic positions and lattice vectors
- INCAR: Calculation parameters
- KPOINTS: k-point mesh specification
- POTCAR: Pseudopotential data

Provides UI for:
- Uploading/pasting each file individually
- Validating file formats
- Staging files for remote submission
- Managing POTCAR library selections
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    Static,
    TextArea,
    Header,
    Footer,
    TabbedContent,
    TabPane,
    Select,
)
from textual.message import Message
from textual.validation import ValidationResult, Validator

from ...core.database import Database
from ...core.codes import DFTCode

logger = logging.getLogger(__name__)


class VASPFilesReady(Message):
    """Message posted when VASP input files are ready."""

    def __init__(
        self,
        poscar: str,
        incar: str,
        kpoints: str,
        potcar_element: str,
        job_name: str
    ):
        self.poscar = poscar
        self.incar = incar
        self.kpoints = kpoints
        self.potcar_element = potcar_element
        self.job_name = job_name
        super().__init__()


class POSCARValidator(Validator):
    """Validates POSCAR file format."""

    def validate(self, value: str) -> ValidationResult:
        """Check if POSCAR has minimum structure."""
        if not value.strip():
            return self.failure("POSCAR cannot be empty")

        lines = value.strip().split('\n')
        if len(lines) < 8:
            return self.failure("POSCAR needs at least 8 lines (comment, scale, lattice, elements, counts, coord type, coords)")

        # Check if line 2 is a number (scaling factor)
        try:
            float(lines[1].strip())
        except ValueError:
            return self.failure("Line 2 must be scaling factor (number)")

        return self.success()


class INCARValidator(Validator):
    """Validates INCAR file format."""

    def validate(self, value: str) -> ValidationResult:
        """Check if INCAR has valid key=value pairs."""
        if not value.strip():
            return self.failure("INCAR cannot be empty")

        lines = value.strip().split('\n')
        valid_params = False

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                valid_params = True
                break

        if not valid_params:
            return self.failure("INCAR must contain at least one parameter (KEY = VALUE)")

        return self.success()


class KPOINTSValidator(Validator):
    """Validates KPOINTS file format."""

    def validate(self, value: str) -> ValidationResult:
        """Check if KPOINTS has minimum structure."""
        if not value.strip():
            return self.failure("KPOINTS cannot be empty")

        lines = value.strip().split('\n')
        if len(lines) < 4:
            return self.failure("KPOINTS needs at least 4 lines (comment, mesh points, mesh type, k-points)")

        return self.success()


class VASPInputManagerScreen(ModalScreen):
    """
    Screen for managing VASP multi-file input.

    Allows users to:
    - Upload or paste POSCAR, INCAR, KPOINTS files
    - Select POTCAR from library
    - Validate all files before submission
    - Stage files for remote execution
    """

    CSS = """
    VASPInputManagerScreen {
        align: center middle;
    }

    #modal_container {
        width: 100;
        height: 50;
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

    #file_tabs {
        width: 100%;
        height: 1fr;
    }

    TextArea {
        width: 100%;
        height: 1fr;
        border: solid $accent;
    }

    .file_info {
        padding: 1;
        color: $text-muted;
    }

    .field_label {
        padding: 0 0 1 0;
        color: $text;
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
    """

    BINDINGS = [
        ("escape", "dismiss", "Close"),
    ]

    def __init__(
        self,
        db: Database,
        calculations_dir: Path,
        initial_poscar: Optional[str] = None,
    ):
        """
        Initialize VASP input manager screen.

        Args:
            db: Database instance
            calculations_dir: Directory for calculation files
            initial_poscar: Optional initial POSCAR content
        """
        super().__init__()
        self.db = db
        self.calculations_dir = calculations_dir
        self.initial_poscar = initial_poscar or ""

        # File contents
        self._poscar_content = ""
        self._incar_content = ""
        self._kpoints_content = ""
        self._potcar_element = "Si"  # Default element

    def compose(self) -> ComposeResult:
        """Create the UI layout."""
        with Container(id="modal_container"):
            yield Static("VASP Input File Manager", id="modal_title")

            yield Static(
                "📝 Upload or paste all 4 required VASP input files",
                classes="file_info"
            )

            with TabbedContent(id="file_tabs"):
                # POSCAR tab
                with TabPane("POSCAR", id="tab_poscar"):
                    yield Label("Atomic positions and lattice vectors:", classes="field_label")
                    yield TextArea(
                        text=self.initial_poscar,
                        id="poscar_textarea",
                        language="text",
                    )

                # INCAR tab
                with TabPane("INCAR", id="tab_incar"):
                    yield Label("Calculation parameters:", classes="field_label")
                    yield TextArea(
                        text=self._get_default_incar(),
                        id="incar_textarea",
                        language="text",
                    )

                # KPOINTS tab
                with TabPane("KPOINTS", id="tab_kpoints"):
                    yield Label("k-point mesh specification:", classes="field_label")
                    yield TextArea(
                        text=self._get_default_kpoints(),
                        id="kpoints_textarea",
                        language="text",
                    )

                # POTCAR tab
                with TabPane("POTCAR", id="tab_potcar"):
                    yield Label("Select element for pseudopotential:", classes="field_label")
                    yield Select(
                        options=[
                            ("Silicon (Si)", "Si"),
                            ("Carbon (C)", "C"),
                            ("Oxygen (O)", "O"),
                            ("Titanium (Ti)", "Ti"),
                            ("Nitrogen (N)", "N"),
                            ("Hydrogen (H)", "H"),
                        ],
                        value="Si",
                        id="potcar_element_select",
                    )
                    yield Static(
                        "Note: POTCAR will be retrieved from cluster's VASP_PP_PATH",
                        classes="file_info"
                    )

            # Job name input
            yield Label("Job Name:", classes="field_label")
            yield Input(placeholder="e.g., silicon_scf", id="job_name_input")

            # Actions
            with Horizontal(id="actions"):
                yield Button("Validate", id="validate_btn", variant="default")
                yield Button("Create Job", id="create_job_btn", variant="success")
                yield Button("Cancel", id="cancel_btn")

            # Status messages
            yield Static("", id="status_message")

    def _get_default_incar(self) -> str:
        """Get default INCAR template."""
        return """# INCAR - VASP calculation parameters
# General
SYSTEM = VASP Calculation
PREC = Accurate
ENCUT = 400
EDIFF = 1E-6
ALGO = Normal
ISMEAR = 0
SIGMA = 0.1

# Electronic relaxation
NELM = 100

# Ionic relaxation (if needed)
# IBRION = 2
# NSW = 50
# POTIM = 0.5

# Output
LWAVE = .TRUE.
LCHARG = .TRUE.
"""

    def _get_default_kpoints(self) -> str:
        """Get default KPOINTS template."""
        return """Automatic mesh
0
Gamma
4 4 4
0. 0. 0.
"""

    @on(Select.Changed, "#potcar_element_select")
    def _on_potcar_changed(self, event: Select.Changed) -> None:
        """Handle POTCAR element selection."""
        self._potcar_element = str(event.value)

    @on(Button.Pressed, "#validate_btn")
    def _validate_files(self, event: Button.Pressed) -> None:
        """Validate all VASP input files."""
        status = self.query_one("#status_message", Static)

        # Get file contents
        poscar = self.query_one("#poscar_textarea", TextArea).text
        incar = self.query_one("#incar_textarea", TextArea).text
        kpoints = self.query_one("#kpoints_textarea", TextArea).text

        # Validate POSCAR
        poscar_validator = POSCARValidator()
        poscar_result = poscar_validator.validate(poscar)
        if not poscar_result.is_valid:
            status.update(f"❌ POSCAR invalid: {poscar_result.failure_descriptions[0] if poscar_result.failure_descriptions else 'Unknown error'}")
            return

        # Validate INCAR
        incar_validator = INCARValidator()
        incar_result = incar_validator.validate(incar)
        if not incar_result.is_valid:
            status.update(f"❌ INCAR invalid: {incar_result.failure_descriptions[0] if incar_result.failure_descriptions else 'Unknown error'}")
            return

        # Validate KPOINTS
        kpoints_validator = KPOINTSValidator()
        kpoints_result = kpoints_validator.validate(kpoints)
        if not kpoints_result.is_valid:
            status.update(f"❌ KPOINTS invalid: {kpoints_result.failure_descriptions[0] if kpoints_result.failure_descriptions else 'Unknown error'}")
            return

        # All valid
        status.update("✅ All VASP input files validated successfully!")

    @on(Button.Pressed, "#create_job_btn")
    async def _create_job(self, event: Button.Pressed) -> None:
        """Create VASP job with all input files."""
        status = self.query_one("#status_message", Static)

        # Get job name
        job_name_input = self.query_one("#job_name_input", Input)
        job_name = job_name_input.value.strip()

        if not job_name:
            status.update("❌ Job name is required")
            return

        # Get file contents
        poscar = self.query_one("#poscar_textarea", TextArea).text
        incar = self.query_one("#incar_textarea", TextArea).text
        kpoints = self.query_one("#kpoints_textarea", TextArea).text

        # Validate all files first
        validators = [
            (POSCARValidator(), poscar, "POSCAR"),
            (INCARValidator(), incar, "INCAR"),
            (KPOINTSValidator(), kpoints, "KPOINTS"),
        ]

        for validator, content, name in validators:
            result = validator.validate(content)
            if not result.is_valid:
                error_msg = result.failure_descriptions[0] if result.failure_descriptions else "Unknown error"
                status.update(f"❌ {name} invalid: {error_msg}")
                return

        # Post message with files (POTCAR will be retrieved from cluster)
        self.post_message(VASPFilesReady(
            poscar=poscar,
            incar=incar,
            kpoints=kpoints,
            potcar_element=self._potcar_element,
            job_name=job_name
        ))

        status.update(f"✅ VASP job '{job_name}' created successfully!")

        # Dismiss screen
        await asyncio.sleep(1)
        self.dismiss()

    @on(Button.Pressed, "#cancel_btn")
    def _cancel(self, event: Button.Pressed) -> None:
        """Cancel and close the screen."""
        self.dismiss()

    def action_dismiss(self) -> None:
        """Dismiss the screen."""
        self.dismiss()
