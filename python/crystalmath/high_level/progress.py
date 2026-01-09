"""Progress tracking callbacks for workflow execution.

This module provides progress notification implementations for different
execution contexts (console, Jupyter, custom).

Example:
    from crystalmath.high_level.progress import ConsoleProgressCallback

    callback = ConsoleProgressCallback()
    workflow = WorkflowBuilder().from_file(...).with_progress(callback).build()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from crystalmath.protocols import ProgressCallback, WorkflowResult, WorkflowType

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# Re-export ProgressUpdate from builder (it's defined there to avoid circular imports)
from .builder import ProgressUpdate

__all__ = [
    "ProgressUpdate",
    "ConsoleProgressCallback",
    "JupyterProgressCallback",
    "LoggingProgressCallback",
]


class ConsoleProgressCallback(ProgressCallback):
    """Progress callback with console output.

    Displays a progress bar and status messages to stdout.
    Suitable for CLI and script usage.

    Example:
        callback = ConsoleProgressCallback()
        workflow.with_progress(callback).build()
    """

    def __init__(self, bar_width: int = 40) -> None:
        """Initialize console progress callback.

        Args:
            bar_width: Width of progress bar in characters
        """
        self._bar_width = bar_width

    def on_started(self, workflow_id: str, workflow_type: WorkflowType) -> None:
        """Called when workflow starts.

        Args:
            workflow_id: Unique workflow identifier
            workflow_type: Type of workflow being executed
        """
        print(f"\nStarting {workflow_type.value} workflow [{workflow_id[:8]}...]")
        print("-" * 60)

    def on_progress(
        self,
        workflow_id: str,
        step: str,
        progress_percent: float,
        message: Optional[str] = None,
    ) -> None:
        """Called on progress update.

        Args:
            workflow_id: Unique workflow identifier
            step: Current step name
            progress_percent: Overall progress (0-100)
            message: Optional status message
        """
        # Build progress bar
        filled = int(progress_percent / 100 * self._bar_width)
        bar = "=" * filled
        if filled < self._bar_width:
            bar += ">"
        bar = bar.ljust(self._bar_width)

        # Build status line
        status = f"\r[{bar}] {progress_percent:5.1f}% | {step}"
        if message:
            status += f" - {message}"

        # Print without newline (overwrite previous)
        print(status, end="", flush=True)

    def on_completed(self, workflow_id: str, result: WorkflowResult) -> None:
        """Called when workflow completes successfully.

        Args:
            workflow_id: Unique workflow identifier
            result: Workflow result
        """
        print()  # New line after progress bar
        print("-" * 60)
        print(f"Completed [{workflow_id[:8]}...]")

        # Print key results if available
        outputs = result.outputs
        if outputs.get("band_gap_ev") is not None:
            print(f"  Band gap: {outputs['band_gap_ev']:.3f} eV")
        if outputs.get("is_metal") is not None:
            print(f"  Metallic: {outputs['is_metal']}")
        if result.wall_time_seconds:
            minutes = result.wall_time_seconds / 60
            print(f"  Wall time: {minutes:.1f} min")

        print()

    def on_failed(
        self,
        workflow_id: str,
        error: str,
        recoverable: bool,
    ) -> None:
        """Called when workflow fails.

        Args:
            workflow_id: Unique workflow identifier
            error: Error message
            recoverable: Whether the error is recoverable
        """
        print()  # New line after progress bar
        print("-" * 60)
        print(f"FAILED [{workflow_id[:8]}...]")
        print(f"  Error: {error}")
        if recoverable:
            print("  (Attempting recovery...)")
        print()


class JupyterProgressCallback(ProgressCallback):
    """Progress callback with Jupyter widget display.

    Uses ipywidgets for interactive progress display in Jupyter notebooks.
    Falls back to console output if ipywidgets is not available.

    Example:
        callback = JupyterProgressCallback()
        workflow.with_progress(callback).build()
    """

    def __init__(self) -> None:
        """Initialize Jupyter progress callback."""
        self._widget = None
        self._progress_bar = None
        self._status_label = None
        self._initialized = False

        try:
            from ipywidgets import FloatProgress, HTML, VBox
            from IPython.display import display

            self._progress_bar = FloatProgress(
                min=0,
                max=100,
                description="Progress:",
                bar_style="info",
                style={"bar_color": "#2196F3"},
            )
            self._status_label = HTML(value="Initializing...")
            self._widget = VBox([self._status_label, self._progress_bar])
            display(self._widget)
            self._initialized = True
        except ImportError:
            logger.warning(
                "ipywidgets not available, falling back to console progress"
            )

    def on_started(self, workflow_id: str, workflow_type: WorkflowType) -> None:
        """Called when workflow starts."""
        if self._initialized and self._status_label:
            self._status_label.value = (
                f"<b>Starting:</b> {workflow_type.value} workflow "
                f"<code>[{workflow_id[:8]}...]</code>"
            )
        else:
            print(f"Starting {workflow_type.value} workflow [{workflow_id[:8]}...]")

    def on_progress(
        self,
        workflow_id: str,
        step: str,
        progress_percent: float,
        message: Optional[str] = None,
    ) -> None:
        """Called on progress update."""
        if self._initialized and self._progress_bar and self._status_label:
            self._progress_bar.value = progress_percent

            status = f"<b>Step:</b> {step}"
            if message:
                status += f" <i>({message})</i>"
            self._status_label.value = status
        else:
            filled = int(progress_percent / 2)
            bar = "=" * filled + ">" + " " * (50 - filled)
            print(f"\r[{bar}] {progress_percent:.1f}% - {step}", end="", flush=True)

    def on_completed(self, workflow_id: str, result: WorkflowResult) -> None:
        """Called when workflow completes successfully."""
        if self._initialized and self._progress_bar and self._status_label:
            self._progress_bar.value = 100
            self._progress_bar.bar_style = "success"

            outputs = result.outputs
            status = "<b>Completed!</b><br>"
            if outputs.get("band_gap_ev") is not None:
                status += f"Band gap: {outputs['band_gap_ev']:.3f} eV<br>"
            if result.wall_time_seconds:
                status += f"Time: {result.wall_time_seconds / 60:.1f} min"

            self._status_label.value = status
        else:
            print(f"\nCompleted [{workflow_id[:8]}...]")

    def on_failed(
        self,
        workflow_id: str,
        error: str,
        recoverable: bool,
    ) -> None:
        """Called when workflow fails."""
        if self._initialized and self._progress_bar and self._status_label:
            self._progress_bar.bar_style = "danger"

            status = f"<b style='color: red'>Failed:</b> {error}"
            if recoverable:
                status += "<br><i>Attempting recovery...</i>"

            self._status_label.value = status
        else:
            print(f"\nFailed [{workflow_id[:8]}...]: {error}")


class LoggingProgressCallback(ProgressCallback):
    """Progress callback using Python logging.

    Logs progress updates to a logger, suitable for batch processing
    and background jobs where console output is captured to logs.

    Example:
        callback = LoggingProgressCallback(logger_name="my_app.workflows")
        workflow.with_progress(callback).build()
    """

    def __init__(
        self,
        logger_name: str = "crystalmath.workflows",
        level: int = logging.INFO,
    ) -> None:
        """Initialize logging progress callback.

        Args:
            logger_name: Logger name to use
            level: Logging level for progress messages
        """
        self._logger = logging.getLogger(logger_name)
        self._level = level

    def on_started(self, workflow_id: str, workflow_type: WorkflowType) -> None:
        """Called when workflow starts."""
        self._logger.log(
            self._level,
            f"Workflow started: {workflow_type.value} [{workflow_id}]"
        )

    def on_progress(
        self,
        workflow_id: str,
        step: str,
        progress_percent: float,
        message: Optional[str] = None,
    ) -> None:
        """Called on progress update."""
        msg = f"[{workflow_id[:8]}] {progress_percent:.1f}% - {step}"
        if message:
            msg += f" ({message})"
        self._logger.log(self._level, msg)

    def on_completed(self, workflow_id: str, result: WorkflowResult) -> None:
        """Called when workflow completes successfully."""
        outputs = result.outputs
        msg = f"Workflow completed: [{workflow_id}]"
        if outputs.get("band_gap_ev") is not None:
            msg += f" | Band gap: {outputs['band_gap_ev']:.3f} eV"
        if result.wall_time_seconds:
            msg += f" | Time: {result.wall_time_seconds:.0f}s"

        self._logger.log(self._level, msg)

    def on_failed(
        self,
        workflow_id: str,
        error: str,
        recoverable: bool,
    ) -> None:
        """Called when workflow fails."""
        level = logging.WARNING if recoverable else logging.ERROR
        msg = f"Workflow failed: [{workflow_id}] - {error}"
        if recoverable:
            msg += " (recoverable)"

        self._logger.log(level, msg)


class NullProgressCallback(ProgressCallback):
    """Progress callback that does nothing.

    Useful for suppressing progress output in tests or when running
    many workflows in parallel.

    Example:
        callback = NullProgressCallback()
        workflow.with_progress(callback).build()
    """

    def on_started(self, workflow_id: str, workflow_type: WorkflowType) -> None:
        """Called when workflow starts."""
        pass

    def on_progress(
        self,
        workflow_id: str,
        step: str,
        progress_percent: float,
        message: Optional[str] = None,
    ) -> None:
        """Called on progress update."""
        pass

    def on_completed(self, workflow_id: str, result: WorkflowResult) -> None:
        """Called when workflow completes successfully."""
        pass

    def on_failed(
        self,
        workflow_id: str,
        error: str,
        recoverable: bool,
    ) -> None:
        """Called when workflow fails."""
        pass
