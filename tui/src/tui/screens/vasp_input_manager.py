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
import re
from pathlib import Path
from typing import Optional, Dict, List, Tuple

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


# Valid element symbols (subset commonly used in VASP)
VALID_ELEMENTS = {
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar",
    "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr",
    "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
    "In", "Sn", "Sb", "Te", "I", "Xe",
    "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy",
    "Ho", "Er", "Tm", "Yb", "Lu",
    "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn",
    "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu",
}

# POTCAR library types available in common VASP distributions
POTCAR_TYPES = [
    ("PBE (recommended)", "potpaw_PBE"),
    ("PBE.52", "potpaw_PBE.52"),
    ("PBE.54", "potpaw_PBE.54"),
    ("PW91", "potpaw_GGA"),
    ("LDA", "potpaw_LDA"),
    ("LDA.52", "potpaw_LDA.52"),
]


def parse_elements_from_poscar(poscar_content: str) -> Tuple[List[str], str]:
    """Parse element symbols and counts from POSCAR content.

    POSCAR format (VASP 5+):
    Line 1: Comment
    Line 2: Scale factor
    Lines 3-5: Lattice vectors
    Line 6: Element symbols (VASP 5+) OR element counts (VASP 4)
    Line 7: Element counts (if line 6 has symbols)

    Args:
        poscar_content: Content of POSCAR file.

    Returns:
        Tuple of (list of element symbols, error message or empty string).
    """
    lines = poscar_content.strip().split('\n')

    if len(lines) < 7:
        return [], "POSCAR too short - needs at least 7 lines"

    # Line 6 contains either element symbols (VASP 5+) or counts (VASP 4)
    line6 = lines[5].split()

    # Check if line 6 contains element symbols or numbers
    try:
        # If all tokens are numbers, this is VASP 4 format (no element line)
        [int(x) for x in line6]
        return [], "POSCAR uses VASP 4 format - element symbols not found. Add element symbols on line 6."
    except ValueError:
        # Line 6 contains element symbols (VASP 5+ format)
        elements = []
        for token in line6:
            # Normalize element symbol (capitalize first letter)
            elem = token.strip().capitalize()
            if elem not in VALID_ELEMENTS:
                return [], f"Unknown element symbol: '{token}'"
            elements.append(elem)

        if not elements:
            return [], "No element symbols found on line 6"

        return elements, ""


class VASPFilesReady(Message):
    """Message posted when VASP input files are ready."""

    def __init__(
        self,
        poscar: str,
        incar: str,
        kpoints: str,
        potcar_elements: List[str],
        potcar_type: str,
        job_name: str
    ):
        self.poscar = poscar
        self.incar = incar
        self.kpoints = kpoints
        self.potcar_elements = potcar_elements  # List of elements in POSCAR order
        self.potcar_type = potcar_type  # POTCAR library type (e.g., "potpaw_PBE")
        self.job_name = job_name
        super().__init__()

    @property
    def potcar_element(self) -> str:
        """Backward compatibility: return first element or comma-separated list."""
        return ",".join(self.potcar_elements) if self.potcar_elements else "Si"


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

    #detected_elements {
        padding: 1;
        border: solid $accent;
        background: $surface-darken-1;
    }

    #potcar_actions {
        height: 3;
        padding: 1 0;
    }

    #potcar_preview {
        padding: 1;
        color: $text-muted;
        border: dashed $accent-darken-2;
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
        self._potcar_elements: List[str] = []  # Elements detected from POSCAR
        self._potcar_type = "potpaw_PBE"  # Default POTCAR library type

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
                    yield Label("Detected Elements from POSCAR:", classes="field_label")
                    yield Static(
                        "⚠️ Enter POSCAR first to detect elements",
                        id="detected_elements",
                        classes="file_info"
                    )
                    with Horizontal(id="potcar_actions"):
                        yield Button("Refresh Elements", id="refresh_elements_btn", variant="default")

                    yield Label("POTCAR Library Type:", classes="field_label")
                    yield Select(
                        options=[(label, value) for label, value in POTCAR_TYPES],
                        value="potpaw_PBE",
                        id="potcar_type_select",
                    )

                    yield Static(
                        "POTCARs will be concatenated in element order from VASP_PP_PATH on cluster",
                        classes="file_info"
                    )
                    yield Static(
                        "",
                        id="potcar_preview",
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

    async def on_mount(self) -> None:
        """Initialize screen when mounted."""
        # Parse elements from initial POSCAR if provided
        if self.initial_poscar:
            self._update_detected_elements()

    @on(Select.Changed, "#potcar_type_select")
    def _on_potcar_type_changed(self, event: Select.Changed) -> None:
        """Handle POTCAR type selection."""
        self._potcar_type = str(event.value)
        self._update_potcar_preview()

    @on(Button.Pressed, "#refresh_elements_btn")
    def _on_refresh_elements(self, event: Button.Pressed) -> None:
        """Refresh element detection from POSCAR."""
        self._update_detected_elements()

    def _update_detected_elements(self) -> None:
        """Parse POSCAR and update the detected elements display."""
        poscar_textarea = self.query_one("#poscar_textarea", TextArea)
        detected_elements = self.query_one("#detected_elements", Static)
        status = self.query_one("#status_message", Static)

        poscar_content = poscar_textarea.text.strip()

        if not poscar_content:
            detected_elements.update("⚠️ Enter POSCAR first to detect elements")
            self._potcar_elements = []
            self._update_potcar_preview()
            return

        elements, error = parse_elements_from_poscar(poscar_content)

        if error:
            detected_elements.update(f"❌ {error}")
            self._potcar_elements = []
            status.update(f"⚠️ POSCAR element parsing: {error}")
        else:
            self._potcar_elements = elements
            elem_list = ", ".join(elements)
            detected_elements.update(f"✅ Detected {len(elements)} element(s): {elem_list}")
            status.update("")

        self._update_potcar_preview()

    def _update_potcar_preview(self) -> None:
        """Update the POTCAR path preview."""
        preview = self.query_one("#potcar_preview", Static)

        if not self._potcar_elements:
            preview.update("")
            return

        # Show which POTCARs will be concatenated
        paths = []
        for elem in self._potcar_elements:
            paths.append(f"$VASP_PP_PATH/{self._potcar_type}/{elem}/POTCAR")

        preview_text = "Will concatenate:\n" + "\n".join(f"  → {p}" for p in paths)
        preview.update(preview_text)

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

        # Ensure elements are parsed from POSCAR
        if not self._potcar_elements:
            self._update_detected_elements()

        # Validate elements were detected
        if not self._potcar_elements:
            status.update("❌ Could not detect elements from POSCAR. Check format (VASP 5+ required).")
            return

        # Post message with files (POTCAR will be retrieved from cluster)
        self.post_message(VASPFilesReady(
            poscar=poscar,
            incar=incar,
            kpoints=kpoints,
            potcar_elements=self._potcar_elements,
            potcar_type=self._potcar_type,
            job_name=job_name
        ))

        elem_list = ", ".join(self._potcar_elements)
        status.update(f"✅ VASP job '{job_name}' created! POTCARs: {elem_list}")

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
