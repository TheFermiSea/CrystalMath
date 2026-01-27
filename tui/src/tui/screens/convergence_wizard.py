"""
Convergence Wizard screen for automated parameter convergence testing.

Provides an interactive UI for:
- Selecting parameters to converge (ENCUT, k-points, basis set)
- Configuring sweep ranges and thresholds
- Visualizing convergence in real-time
- Detecting and recommending optimal values
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    ProgressBar,
    Select,
    Static,
)

from ...core.codes import DFTCode
from ...core.database import Database
from ...core.templates import TemplateManager


class ConvergenceParameter(Enum):
    """Parameters that can be tested for convergence."""

    ENCUT = "encut"
    KPOINTS = "kpoints"
    BASIS_SET = "basis_set"
    ECUTWFC = "ecutwfc"  # QE wavefunction cutoff
    ECUTRHO = "ecutrho"  # QE density cutoff


@dataclass
class ConvergenceResult:
    """Result from a single convergence test point."""

    parameter_value: float
    total_energy: float
    energy_per_atom: float
    delta: float | None = None
    converged: bool = False
    job_id: int | None = None
    status: str = "pending"  # pending, running, completed, failed


@dataclass
class ConvergenceConfig:
    """Configuration for convergence test."""

    parameter: ConvergenceParameter
    dft_code: DFTCode
    structure_file: Path
    values: list[float]
    threshold: float = 0.001  # eV/atom
    reference_kpoints: str = "8 8 8"
    reference_encut: float = 600.0
    max_parallel: int = 5


class ConvergenceComplete(Message):
    """Message posted when convergence test is complete."""

    def __init__(
        self,
        converged_value: float | None,
        results: list[ConvergenceResult],
    ) -> None:
        self.converged_value = converged_value
        self.results = results
        super().__init__()


class ConvergenceProgress(Message):
    """Message posted when a convergence step completes."""

    def __init__(self, completed: int, total: int, result: ConvergenceResult) -> None:
        self.completed = completed
        self.total = total
        self.result = result
        super().__init__()


class ConvergenceChart(Widget):
    """ASCII chart widget for visualizing convergence."""

    results: reactive[list[ConvergenceResult]] = reactive([], recompose=True)
    threshold: reactive[float] = reactive(0.001)
    converged_value: reactive[float | None] = reactive(None)

    def __init__(
        self,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)

    def compose(self) -> ComposeResult:
        """Compose the convergence chart."""
        if not self.results:
            yield Label(
                "No results yet. Start convergence test to see data.", classes="chart_placeholder"
            )
            return

        # Build ASCII chart
        chart_lines = self._build_chart()
        yield Static("\n".join(chart_lines), classes="convergence_chart")

    def _build_chart(self) -> list[str]:
        """Build ASCII chart of convergence results."""
        lines = []

        if not self.results:
            return ["No data"]

        # Get energy values
        energies = [r.energy_per_atom for r in self.results if r.status == "completed"]
        params = [r.parameter_value for r in self.results if r.status == "completed"]

        if not energies:
            return ["Waiting for results..."]

        # Find range
        e_min, e_max = min(energies), max(energies)
        e_range = e_max - e_min if e_max > e_min else 0.001

        # Chart dimensions
        width = 60
        height = 15

        # Header
        lines.append("Energy per Atom (eV) vs Parameter Value")
        lines.append("=" * width)

        # Y-axis labels and chart area
        for row in range(height):
            e_val = e_max - (row / (height - 1)) * e_range
            label = f"{e_val:10.6f} |"

            # Plot points
            chart_row = [" "] * width
            for p, e in zip(params, energies, strict=False):
                # X position
                if params:
                    p_min, p_max = min(params), max(params)
                    if p_max > p_min:
                        x = int((p - p_min) / (p_max - p_min) * (width - 1))
                    else:
                        x = width // 2
                else:
                    x = 0

                # Y position check
                if abs(e - e_val) < e_range / height:
                    chart_row[x] = "*"

            lines.append(label + "".join(chart_row))

        # X-axis
        lines.append(" " * 11 + "+" + "-" * width)

        # X-axis labels
        if params:
            p_min, p_max = min(params), max(params)
            x_label = f"{' ' * 11}{p_min:<{width // 2}}{p_max:>{width // 2}}"
            lines.append(x_label)

        # Legend and summary
        lines.append("")
        lines.append(f"Threshold: {self.threshold} eV/atom")

        if self.converged_value:
            lines.append(f"[CONVERGED] Recommended value: {self.converged_value}")
        else:
            lines.append("[NOT CONVERGED] Consider testing higher values")

        return lines


class ConvergenceWizard(Screen):
    """Interactive convergence testing wizard screen."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+r", "run_test", "Run Test"),
    ]

    CSS = """
    ConvergenceWizard {
        layout: grid;
        grid-size: 2;
        grid-columns: 1fr 1fr;
        padding: 1;
    }

    .config_panel {
        height: 100%;
        border: solid green;
        padding: 1;
    }

    .results_panel {
        height: 100%;
        border: solid blue;
        padding: 1;
    }

    .section_title {
        text-style: bold;
        margin-bottom: 1;
    }

    .form_field {
        margin-bottom: 1;
    }

    .form_label {
        margin-bottom: 0;
    }

    .convergence_chart {
        height: 20;
        border: solid cyan;
        padding: 1;
    }

    .chart_placeholder {
        color: gray;
        text-align: center;
        margin-top: 5;
    }

    .results_table {
        height: 10;
        margin-top: 1;
    }

    .progress_section {
        margin-top: 1;
    }

    .action_buttons {
        dock: bottom;
        height: 3;
        margin-top: 1;
    }

    .converged_badge {
        color: green;
        text-style: bold;
    }

    .not_converged_badge {
        color: red;
    }
    """

    def __init__(
        self,
        db: Database,
        template_manager: TemplateManager,
        name: str | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id)
        self.db = db
        self.template_manager = template_manager
        self.results: list[ConvergenceResult] = []
        self.converged_value: float | None = None
        self._running = False

    def compose(self) -> ComposeResult:
        """Compose the convergence wizard UI."""
        # Configuration panel (left)
        with Vertical(classes="config_panel"):
            yield Label("Convergence Test Configuration", classes="section_title")

            # DFT Code selection
            with Vertical(classes="form_field"):
                yield Label("DFT Code", classes="form_label")
                yield Select(
                    options=[
                        ("VASP", "vasp"),
                        ("Quantum ESPRESSO", "qe"),
                        ("CRYSTAL", "crystal"),
                    ],
                    value="vasp",
                    id="dft_code",
                )

            # Parameter selection
            with Vertical(classes="form_field"):
                yield Label("Parameter to Converge", classes="form_label")
                yield Select(
                    options=[
                        ("Energy Cutoff (ENCUT)", "encut"),
                        ("K-point Mesh", "kpoints"),
                        ("Wavefunction Cutoff (ecutwfc)", "ecutwfc"),
                    ],
                    value="encut",
                    id="parameter",
                )

            # Values to test
            with Vertical(classes="form_field"):
                yield Label("Values to Test (comma-separated)", classes="form_label")
                yield Input(
                    value="400,450,500,550,600,650,700",
                    placeholder="e.g., 400,450,500,550,600",
                    id="test_values",
                )

            # Convergence threshold
            with Vertical(classes="form_field"):
                yield Label("Convergence Threshold (eV/atom)", classes="form_label")
                yield Input(
                    value="0.001",
                    placeholder="0.001",
                    type="number",
                    id="threshold",
                )

            # Reference k-points
            with Vertical(classes="form_field"):
                yield Label("Reference K-points (for cutoff tests)", classes="form_label")
                yield Input(
                    value="8 8 8",
                    placeholder="8 8 8",
                    id="ref_kpoints",
                )

            # Reference cutoff
            with Vertical(classes="form_field"):
                yield Label("Reference Cutoff (for k-point tests)", classes="form_label")
                yield Input(
                    value="600",
                    placeholder="600",
                    type="number",
                    id="ref_encut",
                )

            # Structure file
            with Vertical(classes="form_field"):
                yield Label("Structure File (POSCAR)", classes="form_label")
                yield Input(
                    value="",
                    placeholder="Path to POSCAR or CIF",
                    id="structure_file",
                )

            # Max parallel jobs
            with Vertical(classes="form_field"):
                yield Label("Max Parallel Jobs", classes="form_label")
                yield Input(
                    value="5",
                    type="integer",
                    id="max_parallel",
                )

            # Action buttons
            with Horizontal(classes="action_buttons"):
                yield Button("Run Convergence Test", id="run_test", variant="primary")
                yield Button("Cancel", id="cancel", variant="error")

        # Results panel (right)
        with Vertical(classes="results_panel"):
            yield Label("Convergence Results", classes="section_title")

            # Progress section
            with Vertical(classes="progress_section"):
                yield Label("Progress: 0/0", id="progress_label")
                yield ProgressBar(id="progress_bar", show_eta=True)

            # Chart
            yield ConvergenceChart(id="convergence_chart")

            # Results table
            yield DataTable(id="results_table", classes="results_table")

            # Status/recommendation
            yield Label("", id="status_label", classes="converged_badge")

    async def on_mount(self) -> None:
        """Initialize the screen on mount."""
        # Setup results table
        table = self.query_one("#results_table", DataTable)
        table.add_columns("Value", "E/atom (eV)", "Delta (eV)", "Status")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "run_test":
            await self._run_convergence_test()
        elif event.button.id == "cancel":
            self.app.pop_screen()

    def action_cancel(self) -> None:
        """Cancel and return to previous screen."""
        self._running = False
        self.app.pop_screen()

    def action_run_test(self) -> None:
        """Trigger convergence test from keybinding."""
        asyncio.create_task(self._run_convergence_test())

    async def _run_convergence_test(self) -> None:
        """Execute the convergence test."""
        if self._running:
            return

        self._running = True
        self.results = []
        self.converged_value = None

        # Get configuration from form
        try:
            config = self._get_config_from_form()
        except ValueError as e:
            self.query_one("#status_label", Label).update(f"Error: {e}")
            self._running = False
            return

        # Update UI
        total = len(config.values)
        self.query_one("#progress_label", Label).update(f"Progress: 0/{total}")
        progress_bar = self.query_one("#progress_bar", ProgressBar)
        progress_bar.update(total=total, progress=0)

        # Clear table
        table = self.query_one("#results_table", DataTable)
        table.clear()

        # Initialize results
        for val in config.values:
            result = ConvergenceResult(
                parameter_value=val,
                total_energy=0.0,
                energy_per_atom=0.0,
                status="pending",
            )
            self.results.append(result)
            table.add_row(str(val), "---", "---", "pending")

        # Simulate running calculations
        # In production, this would submit actual jobs via the orchestrator
        for i, val in enumerate(config.values):
            if not self._running:
                break

            # Update status to running
            self.results[i].status = "running"
            table.update_cell_at((i, 3), "running")

            # Simulate calculation (in production: await job completion)
            await asyncio.sleep(0.5)  # Simulate delay

            # Generate mock result (in production: parse actual output)
            # This simulates typical VASP convergence behavior
            base_energy = -150.0 - (val / 100) * 0.5
            noise = (700 - val) * 0.0001  # Less noise at higher cutoffs
            self.results[i].total_energy = base_energy + noise
            self.results[i].energy_per_atom = (base_energy + noise) / 8  # Assume 8 atoms
            self.results[i].status = "completed"

            # Calculate delta from previous
            if i > 0 and self.results[i - 1].status == "completed":
                delta = abs(self.results[i].energy_per_atom - self.results[i - 1].energy_per_atom)
                self.results[i].delta = delta

                # Check convergence
                if delta < config.threshold and self.converged_value is None:
                    self.converged_value = self.results[i - 1].parameter_value

            # Update table
            delta_str = f"{self.results[i].delta:.6f}" if self.results[i].delta else "---"
            table.update_cell_at((i, 1), f"{self.results[i].energy_per_atom:.6f}")
            table.update_cell_at((i, 2), delta_str)
            table.update_cell_at((i, 3), "completed")

            # Update progress
            self.query_one("#progress_label", Label).update(f"Progress: {i + 1}/{total}")
            progress_bar.update(progress=i + 1)

            # Update chart
            chart = self.query_one("#convergence_chart", ConvergenceChart)
            chart.results = self.results.copy()
            chart.threshold = config.threshold
            chart.converged_value = self.converged_value

        # Final status
        if self.converged_value:
            status_label = self.query_one("#status_label", Label)
            status_label.update(f"CONVERGED! Recommended value: {self.converged_value}")
            status_label.set_class(True, "converged_badge")
            status_label.set_class(False, "not_converged_badge")
        else:
            status_label = self.query_one("#status_label", Label)
            status_label.update("NOT CONVERGED - try higher values")
            status_label.set_class(False, "converged_badge")
            status_label.set_class(True, "not_converged_badge")

        self._running = False

        # Post completion message
        self.post_message(ConvergenceComplete(self.converged_value, self.results))

    def _get_config_from_form(self) -> ConvergenceConfig:
        """Extract configuration from form inputs."""
        # Parse values
        values_str = self.query_one("#test_values", Input).value
        values = [float(v.strip()) for v in values_str.split(",") if v.strip()]

        if not values:
            raise ValueError("No test values provided")

        # Parse threshold
        threshold_str = self.query_one("#threshold", Input).value
        threshold = float(threshold_str) if threshold_str else 0.001

        # Parse references
        ref_kpoints = self.query_one("#ref_kpoints", Input).value or "8 8 8"
        ref_encut_str = self.query_one("#ref_encut", Input).value
        ref_encut = float(ref_encut_str) if ref_encut_str else 600.0

        # Parse max parallel
        max_parallel_str = self.query_one("#max_parallel", Input).value
        max_parallel = int(max_parallel_str) if max_parallel_str else 5

        # Structure file
        structure_str = self.query_one("#structure_file", Input).value
        structure_file = Path(structure_str) if structure_str else Path("POSCAR")

        # Get selections
        dft_code_val = self.query_one("#dft_code", Select).value
        param_val = self.query_one("#parameter", Select).value

        # Map to enums
        code_map = {
            "vasp": DFTCode.VASP,
            "qe": DFTCode.QUANTUM_ESPRESSO,
            "crystal": DFTCode.CRYSTAL,
        }
        param_map = {
            "encut": ConvergenceParameter.ENCUT,
            "kpoints": ConvergenceParameter.KPOINTS,
            "ecutwfc": ConvergenceParameter.ECUTWFC,
        }

        return ConvergenceConfig(
            parameter=param_map.get(param_val, ConvergenceParameter.ENCUT),
            dft_code=code_map.get(dft_code_val, DFTCode.VASP),
            structure_file=structure_file,
            values=values,
            threshold=threshold,
            reference_kpoints=ref_kpoints,
            reference_encut=ref_encut,
            max_parallel=max_parallel,
        )


__all__ = [
    "ConvergenceWizard",
    "ConvergenceParameter",
    "ConvergenceConfig",
    "ConvergenceResult",
    "ConvergenceComplete",
    "ConvergenceProgress",
]
