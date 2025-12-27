"""
Modal screen for creating new DFT calculation jobs.

Supports multiple DFT codes: CRYSTAL23, Quantum Espresso, VASP.
"""

from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Container, Vertical, Horizontal, ScrollableContainer
from textual.widgets import Input, TextArea, Button, Static, Label, Select, RadioSet, RadioButton, Checkbox
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
    """Modal screen for creating a new DFT calculation job."""

    CSS = """
    NewJobScreen {
        align: center middle;
    }

    #modal_container {
        width: 90;
        height: auto;
        max-height: 45;
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

    #form_scroll {
        width: 100%;
        height: auto;
        max-height: 35;
        padding: 1 0;
    }

    .form_section {
        width: 100%;
        height: auto;
        padding: 0 0 1 0;
        border: solid $accent-darken-1;
        margin: 0 0 1 0;
        padding: 1;
    }

    .section_title {
        width: 100%;
        text-style: bold;
        color: $accent;
        padding: 0 0 1 0;
    }

    .field_label {
        width: 100%;
        padding: 0 0 1 0;
        color: $text;
    }

    .field_input {
        width: 100%;
        margin: 0 0 1 0;
    }

    #input_textarea {
        width: 100%;
        height: 12;
        border: solid $accent;
    }

    #aux_files_container {
        width: 100%;
        height: auto;
        padding: 0 0 1 0;
    }

    .aux_file_row {
        width: 100%;
        height: auto;
        layout: horizontal;
        padding: 0 0 1 0;
    }

    .aux_checkbox {
        width: auto;
        margin: 0 2 0 0;
    }

    .aux_file_input {
        width: 1fr;
    }

    #parallelism_container {
        width: 100%;
        height: auto;
    }

    RadioSet {
        width: 100%;
        height: auto;
        padding: 0 0 1 0;
    }

    #mpi_ranks_input {
        width: 20;
        margin: 0 0 1 0;
    }

    #work_dir_input {
        width: 100%;
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

    #info_message {
        width: 100%;
        color: $accent;
        padding: 1 0;
        text-style: italic;
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
            yield Static("Create New DFT Job", id="modal_title")

            with ScrollableContainer(id="form_scroll"):
                # Section 1: Job Configuration
                with Vertical(classes="form_section"):
                    yield Label("Job Configuration", classes="section_title")

                    # DFT Code selector
                    yield Label("DFT Code:", classes="field_label")
                    yield Select(
                        [
                            ("CRYSTAL23", "crystal"),
                            ("Quantum Espresso", "quantum_espresso"),
                            ("VASP", "vasp"),
                        ],
                        value="crystal",
                        id="dft_code_select",
                        classes="field_input"
                    )

                    yield Label("Job Name (letters, numbers, hyphens, underscores only):", classes="field_label")
                    yield Input(
                        placeholder="e.g., mgo_bulk_optimization",
                        id="job_name_input",
                        classes="field_input"
                    )

                # Section 2: Input File
                with Vertical(classes="form_section"):
                    yield Label("Input File", classes="section_title", id="input_section_title")
                    yield Static(
                        "Paste your input content below or use 'Browse Files' to load from disk",
                        id="info_message"
                    )
                    yield TextArea(
                        id="input_textarea",
                        language="text",
                        theme="monokai",
                        show_line_numbers=True
                    )
                    yield Button("Browse Files...", variant="default", id="browse_button")

                # Section 3: Auxiliary Files
                with Vertical(classes="form_section"):
                    yield Label("Auxiliary Files (Optional)", classes="section_title")
                    with Vertical(id="aux_files_container"):
                        # .gui file
                        with Horizontal(classes="aux_file_row"):
                            yield Checkbox("Use .gui file", id="gui_checkbox", classes="aux_checkbox")
                            yield Input(
                                placeholder="Path to .gui file (EXTERNAL geometry)",
                                id="gui_file_input",
                                classes="aux_file_input",
                                disabled=True
                            )
                        # .f9 file
                        with Horizontal(classes="aux_file_row"):
                            yield Checkbox("Use .f9 file", id="f9_checkbox", classes="aux_checkbox")
                            yield Input(
                                placeholder="Path to .f9 file (wave function guess)",
                                id="f9_file_input",
                                classes="aux_file_input",
                                disabled=True
                            )
                        # .hessopt file
                        with Horizontal(classes="aux_file_row"):
                            yield Checkbox("Use .hessopt file", id="hessopt_checkbox", classes="aux_checkbox")
                            yield Input(
                                placeholder="Path to .hessopt file (Hessian restart)",
                                id="hessopt_file_input",
                                classes="aux_file_input",
                                disabled=True
                            )

                # Section 4: Parallelism Settings
                with Vertical(classes="form_section"):
                    yield Label("Parallelism Settings", classes="section_title")
                    with Vertical(id="parallelism_container"):
                        with RadioSet(id="parallel_mode"):
                            yield RadioButton("Serial (single process, OpenMP only)", id="serial_radio", value=True)
                            yield RadioButton("Parallel (MPI + OpenMP hybrid)", id="parallel_radio")

                        yield Label("MPI Ranks (if parallel):", classes="field_label")
                        yield Input(
                            placeholder="e.g., 4, 8, 16",
                            id="mpi_ranks_input",
                            disabled=True,
                            value="1"
                        )

                # Section 5: Working Directory
                with Vertical(classes="form_section"):
                    yield Label("Working Directory", classes="section_title")
                    yield Static(
                        "Will be auto-generated as: calculations/XXXX_jobname",
                        classes="field_label"
                    )
                    yield Input(
                        id="work_dir_input",
                        classes="field_input",
                        disabled=True
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
        self._update_work_dir_preview()
        # Initialize UI for default DFT code
        self._update_ui_for_dft_code("crystal")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input field changes."""
        if event.input.id == "job_name_input":
            self._update_work_dir_preview()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle checkbox state changes to enable/disable file inputs."""
        checkbox_id = event.checkbox.id

        if checkbox_id == "gui_checkbox":
            gui_input = self.query_one("#gui_file_input", Input)
            gui_input.disabled = not event.value
            if not event.value:
                gui_input.value = ""
        elif checkbox_id == "f9_checkbox":
            f9_input = self.query_one("#f9_file_input", Input)
            f9_input.disabled = not event.value
            if not event.value:
                f9_input.value = ""
        elif checkbox_id == "hessopt_checkbox":
            hessopt_input = self.query_one("#hessopt_file_input", Input)
            hessopt_input.disabled = not event.value
            if not event.value:
                hessopt_input.value = ""

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        """Handle parallelism mode changes."""
        if event.radio_set.id == "parallel_mode":
            mpi_input = self.query_one("#mpi_ranks_input", Input)
            is_parallel = event.index == 1  # Index 1 is parallel mode
            mpi_input.disabled = not is_parallel
            if not is_parallel:
                mpi_input.value = "1"

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle DFT code selection changes."""
        if event.select.id == "dft_code_select":
            self._update_ui_for_dft_code(str(event.value))

    def _update_ui_for_dft_code(self, dft_code: str) -> None:
        """Update UI elements based on selected DFT code."""
        input_section_title = self.query_one("#input_section_title", Label)
        info_message = self.query_one("#info_message", Static)

        # DFT code display names and file extensions
        code_info = {
            "crystal": ("CRYSTAL23 Input File (.d12)", "Paste your .d12 input content below"),
            "quantum_espresso": ("Quantum Espresso Input File (.in)", "Paste your .in input content below (QE stub - not yet implemented)"),
            "vasp": ("VASP Input Files", "VASP uses POSCAR/INCAR/KPOINTS/POTCAR - paste POSCAR below (VASP stub - not yet implemented)"),
        }

        display_name, hint = code_info.get(dft_code, ("Input File", "Paste input content below"))
        input_section_title.update(display_name)
        info_message.update(hint)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "create_button":
            self.action_submit()
        elif event.button.id == "cancel_button":
            self.action_cancel()
        elif event.button.id == "browse_button":
            self._browse_for_input_file()

    def _update_work_dir_preview(self) -> None:
        """Update the working directory preview based on job name."""
        job_name_input = self.query_one("#job_name_input", Input)
        work_dir_input = self.query_one("#work_dir_input", Input)
        job_name = job_name_input.value.strip()

        if job_name:
            existing_jobs = self.database.get_all_jobs()
            next_id = max([job.id for job in existing_jobs], default=0) + 1
            work_dir_name = f"{next_id:04d}_{job_name}"
            work_dir_input.value = f"calculations/{work_dir_name}"
        else:
            work_dir_input.value = "calculations/XXXX_jobname"

    def _browse_for_input_file(self) -> None:
        """Browse for an input file and load its content."""
        # For now, show a message - full file browser would require a separate screen
        error_message = self.query_one("#error_message", Static)
        error_message.update("File browser: Use the input path in auxiliary files section")
        error_message.add_class("visible")
        # In a full implementation, this would open a file selection dialog

    def action_cancel(self) -> None:
        """Cancel and close the modal."""
        self.dismiss(None)

    def action_submit(self) -> None:
        """Validate and create the job."""
        # Get inputs
        job_name_input = self.query_one("#job_name_input", Input)
        input_textarea = self.query_one("#input_textarea", TextArea)
        error_message = self.query_one("#error_message", Static)
        dft_code_select = self.query_one("#dft_code_select", Select)

        dft_code = str(dft_code_select.value) if dft_code_select.value else "crystal"

        # For VASP, open multi-file input manager
        if dft_code == "vasp":
            self._open_vasp_input_manager()
            return

        # Auxiliary files
        gui_checkbox = self.query_one("#gui_checkbox", Checkbox)
        gui_file_input = self.query_one("#gui_file_input", Input)
        f9_checkbox = self.query_one("#f9_checkbox", Checkbox)
        f9_file_input = self.query_one("#f9_file_input", Input)
        hessopt_checkbox = self.query_one("#hessopt_checkbox", Checkbox)
        hessopt_file_input = self.query_one("#hessopt_file_input", Input)

        # Parallelism
        parallel_mode = self.query_one("#parallel_mode", RadioSet)
        mpi_ranks_input = self.query_one("#mpi_ranks_input", Input)

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

        # Basic validation: check for required sections (DFT code specific)
        validation_error = self._validate_input(dft_code, input_content)
        if validation_error:
            self._show_error(validation_error)
            input_textarea.focus()
            return

        # Validate auxiliary files if checked
        aux_files = {}
        if gui_checkbox.value:
            gui_path = gui_file_input.value.strip()
            if gui_path and not Path(gui_path).is_file():
                self._show_error(f"GUI file not found: {gui_path}")
                gui_file_input.focus()
                return
            if gui_path:
                aux_files['gui'] = gui_path

        if f9_checkbox.value:
            f9_path = f9_file_input.value.strip()
            if f9_path and not Path(f9_path).is_file():
                self._show_error(f"F9 file not found: {f9_path}")
                f9_file_input.focus()
                return
            if f9_path:
                aux_files['f9'] = f9_path

        if hessopt_checkbox.value:
            hessopt_path = hessopt_file_input.value.strip()
            if hessopt_path and not Path(hessopt_path).is_file():
                self._show_error(f"Hessopt file not found: {hessopt_path}")
                hessopt_file_input.focus()
                return
            if hessopt_path:
                aux_files['hessopt'] = hessopt_path

        # Validate MPI ranks if parallel mode
        mpi_ranks = 1
        if parallel_mode.pressed_index == 1:  # Parallel mode
            try:
                mpi_ranks = int(mpi_ranks_input.value.strip())
                if mpi_ranks < 1:
                    raise ValueError()
            except ValueError:
                self._show_error("MPI ranks must be a positive integer")
                mpi_ranks_input.focus()
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

        # Copy auxiliary files
        try:
            for file_type, file_path in aux_files.items():
                src_path = Path(file_path)
                if file_type == 'gui':
                    dst_path = work_dir / f"{job_name}.gui"
                elif file_type == 'f9':
                    dst_path = work_dir / f"{job_name}.f9"
                elif file_type == 'hessopt':
                    dst_path = work_dir / f"{job_name}.hessopt"
                else:
                    continue

                # Copy file content
                dst_path.write_bytes(src_path.read_bytes())
        except Exception as e:
            self._show_error(f"Failed to copy auxiliary file: {str(e)}")
            # Clean up
            try:
                import shutil
                shutil.rmtree(work_dir)
            except:
                pass
            return

        # Write job metadata file
        metadata = {
            "dft_code": dft_code,
            "mpi_ranks": mpi_ranks,
            "parallel_mode": "parallel" if parallel_mode.pressed_index == 1 else "serial",
            "auxiliary_files": list(aux_files.keys())
        }
        metadata_file = work_dir / "job_metadata.json"
        try:
            import json
            metadata_file.write_text(json.dumps(metadata, indent=2))
        except Exception as e:
            # Non-critical, just log
            pass

        # Add job to database
        try:
            job_id = self.database.create_job(
                name=job_name,
                work_dir=str(work_dir),
                input_content=input_content,
                dft_code=dft_code
            )
        except Exception as e:
            self._show_error(f"Failed to create job in database: {str(e)}")
            # Clean up files
            try:
                import shutil
                shutil.rmtree(work_dir)
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

    def _validate_input(self, dft_code: str, content: str) -> Optional[str]:
        """
        Perform basic validation on DFT input content based on the selected code.
        Returns error message if invalid, None if valid.
        """
        if dft_code == "crystal":
            return self._validate_crystal_input(content)
        elif dft_code == "quantum_espresso":
            return self._validate_qe_input(content)
        elif dft_code == "vasp":
            return self._validate_vasp_input(content)
        else:
            return None  # Unknown code - skip validation

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

    def _validate_qe_input(self, content: str) -> Optional[str]:
        """
        Perform basic validation on Quantum Espresso input content (stub).
        Returns error message if invalid, None if valid.
        """
        # Stub validation - minimal checks
        if len(content.strip()) < 10:
            return "Input file too short"

        # QE inputs typically have &CONTROL, &SYSTEM, &ELECTRONS namelists
        content_upper = content.upper()
        if "&CONTROL" not in content_upper:
            return "QE input should contain &CONTROL namelist (stub validation)"

        return None

    def _validate_vasp_input(self, content: str) -> Optional[str]:
        """
        Perform basic validation on VASP POSCAR content (stub).
        Returns error message if invalid, None if valid.
        """
        # Stub validation - minimal checks
        lines = content.strip().split('\n')
        if len(lines) < 5:
            return "POSCAR file too short - needs at least comment, scale, lattice vectors"

        return None

    def _open_vasp_input_manager(self) -> None:
        """Open VASP multi-file input manager screen."""
        from .vasp_input_manager import VASPInputManagerScreen

        # Get initial POSCAR content from text area if provided
        input_textarea = self.query_one("#input_textarea", TextArea)
        initial_poscar = input_textarea.text.strip() if input_textarea.text else None

        # Open VASP input manager
        self.app.push_screen(
            VASPInputManagerScreen(
                db=self.database,
                calculations_dir=self.calculations_dir,
                initial_poscar=initial_poscar
            )
        )
