"""
Results summary widget for displaying CRYSTAL job results.

This widget parses and displays key results from completed CRYSTAL calculations,
including energy, convergence, warnings, errors, and structural parameters.
"""

from pathlib import Path
from typing import Optional, Dict, Any
from textual.widgets import Static
from textual.containers import VerticalScroll, Vertical
from textual.binding import Binding
from rich.text import Text
from rich.table import Table
from rich.panel import Panel
from rich.console import Group
from datetime import datetime
import json


class ResultsSummary(Static):
    """
    Widget for displaying structured results from a completed CRYSTAL job.

    Features:
    - Parses output files using CRYSTALpytools
    - Displays final energy, convergence status, and calculation time
    - Shows warnings and errors in a clean format
    - Handles missing or corrupted files gracefully
    - Supports export to text file
    """

    BINDINGS = [
        Binding("e", "export_results", "Export Results", show=True),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._current_job_id: Optional[int] = None
        self._current_results: Optional[Dict[str, Any]] = None
        self._work_dir: Optional[Path] = None

    def display_results(
        self,
        job_id: int,
        job_name: str,
        work_dir: Path,
        status: str,
        final_energy: Optional[float] = None,
        key_results: Optional[Dict[str, Any]] = None,
        created_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> None:
        """
        Display results for a completed job.

        Args:
            job_id: Job database ID
            job_name: Job name
            work_dir: Path to job working directory
            status: Job status (COMPLETED, FAILED, etc.)
            final_energy: Final energy in Hartree (if available)
            key_results: Dictionary of parsed results from database
            created_at: Job creation timestamp
            completed_at: Job completion timestamp
        """
        self._current_job_id = job_id
        self._work_dir = work_dir
        self._current_results = {
            "job_id": job_id,
            "job_name": job_name,
            "status": status,
            "final_energy": final_energy,
            "key_results": key_results,
            "created_at": created_at,
            "completed_at": completed_at,
        }

        # Parse output file if available
        output_file = work_dir / "output.out"
        parsed_results = None

        if output_file.exists():
            parsed_results = self._parse_output_file(output_file)

        # Build the display
        content = self._build_results_display(
            job_name,
            status,
            final_energy,
            key_results,
            parsed_results,
            created_at,
            completed_at,
        )

        self.update(content)

    def _parse_output_file(self, output_file: Path) -> Optional[Dict[str, Any]]:
        """
        Parse CRYSTAL output file using CRYSTALpytools.

        Args:
            output_file: Path to output.out file

        Returns:
            Dictionary of parsed results, or None if parsing fails
        """
        try:
            from CRYSTALpytools.crystal_io import Crystal_output

            cry_out = Crystal_output(str(output_file))
            results: Dict[str, Any] = {}

            # Extract final energy
            if hasattr(cry_out, "get_final_energy"):
                try:
                    results["final_energy"] = cry_out.get_final_energy()
                except Exception:
                    pass

            # Extract SCF cycles information
            if hasattr(cry_out, "get_scf_convergence"):
                try:
                    scf_data = cry_out.get_scf_convergence()
                    if scf_data:
                        results["scf_cycles"] = len(scf_data)
                except Exception:
                    pass

            # Check convergence
            if hasattr(cry_out, "is_converged"):
                try:
                    results["is_converged"] = cry_out.is_converged()
                except Exception:
                    pass

            # Extract geometry optimization data (if applicable)
            if hasattr(cry_out, "get_geometry_optimization"):
                try:
                    geo_opt = cry_out.get_geometry_optimization()
                    if geo_opt:
                        results["geometry_optimization"] = {
                            "converged": geo_opt.get("converged", False),
                            "cycles": geo_opt.get("cycles", 0),
                            "final_gradient": geo_opt.get("final_gradient"),
                        }
                except Exception:
                    pass

            # Extract lattice parameters (if periodic system)
            if hasattr(cry_out, "get_lattice_parameters"):
                try:
                    lattice = cry_out.get_lattice_parameters()
                    if lattice:
                        results["lattice_parameters"] = lattice
                except Exception:
                    pass

            # Extract system information
            if hasattr(cry_out, "get_system_info"):
                try:
                    sys_info = cry_out.get_system_info()
                    if sys_info:
                        results["system_info"] = sys_info
                except Exception:
                    pass

            # Extract timing information
            if hasattr(cry_out, "get_timing"):
                try:
                    timing = cry_out.get_timing()
                    if timing:
                        results["timing"] = timing
                except Exception:
                    pass

            # Get errors
            if hasattr(cry_out, "get_errors"):
                try:
                    errors = cry_out.get_errors()
                    if errors:
                        results["errors"] = errors
                except Exception:
                    pass

            # Get warnings
            if hasattr(cry_out, "get_warnings"):
                try:
                    warnings = cry_out.get_warnings()
                    if warnings:
                        results["warnings"] = warnings
                except Exception:
                    pass

            return results if results else None

        except ImportError:
            # CRYSTALpytools not available, use fallback parser
            return self._fallback_parse(output_file)
        except Exception:
            # Parsing failed, use fallback
            return self._fallback_parse(output_file)

    def _fallback_parse(self, output_file: Path) -> Dict[str, Any]:
        """
        Fallback parser for when CRYSTALpytools is not available.

        Uses basic pattern matching to extract key information.

        Args:
            output_file: Path to output.out file

        Returns:
            Dictionary of extracted results
        """
        results: Dict[str, Any] = {}

        try:
            with output_file.open("r") as f:
                content = f.read()
                lines = content.split("\n")

            # Extract final energy
            for line in lines:
                if "TOTAL ENERGY" in line and "AU" in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        try:
                            # Look for negative or positive number with decimal
                            if ("." in part or "E" in part.upper() or "e" in part) and part[0] in "-+0123456789":
                                energy = float(part)
                                results["final_energy"] = energy
                                break
                        except ValueError:
                            continue

            # Count SCF cycles
            scf_cycles = 0
            for line in lines:
                if "CYC" in line and "ETOT" in line:
                    scf_cycles += 1
            if scf_cycles > 0:
                results["scf_cycles"] = scf_cycles

            # Check convergence
            if "CONVERGENCE" in content:
                results["is_converged"] = "CONVERGENCE REACHED" in content or "SCF ENDED" in content

            # Extract timing (last occurrence of "TOTAL CPU TIME")
            for line in reversed(lines):
                if "TOTAL CPU TIME" in line or "TTTTTTTT" in line:
                    results["timing"] = {"raw_line": line.strip()}
                    break

            # Extract errors
            errors = []
            for line in lines:
                line_upper = line.upper()
                if any(pattern in line_upper for pattern in ["ERROR", "FATAL", "ABNORMAL"]):
                    errors.append(line.strip())
            if errors:
                results["errors"] = errors[:10]  # Limit to first 10 errors

            # Extract warnings
            warnings = []
            for line in lines:
                line_upper = line.upper()
                if "WARNING" in line_upper:
                    warnings.append(line.strip())
            if warnings:
                results["warnings"] = warnings[:10]  # Limit to first 10 warnings

        except Exception:
            results["parse_error"] = "Failed to parse output file"

        return results

    def _build_results_display(
        self,
        job_name: str,
        status: str,
        final_energy: Optional[float],
        key_results: Optional[Dict[str, Any]],
        parsed_results: Optional[Dict[str, Any]],
        created_at: Optional[str],
        completed_at: Optional[str],
    ) -> Group:
        """
        Build the rich display for results.

        Args:
            job_name: Job name
            status: Job status
            final_energy: Final energy (from database)
            key_results: Key results from database
            parsed_results: Results from output file parsing
            created_at: Creation timestamp
            completed_at: Completion timestamp

        Returns:
            Rich Group with formatted results
        """
        renderables = []

        # Header
        header = Text()
        header.append("Results for: ", style="bold cyan")
        header.append(job_name, style="bold white")
        renderables.append(header)
        renderables.append("")

        # Status indicator
        status_text = Text()
        if status == "COMPLETED":
            status_text.append("● ", style="bold green")
            status_text.append("COMPLETED", style="bold green")
        elif status == "FAILED":
            status_text.append("● ", style="bold red")
            status_text.append("FAILED", style="bold red")
        elif status == "RUNNING":
            status_text.append("● ", style="bold yellow")
            status_text.append("RUNNING", style="bold yellow")
        else:
            status_text.append("● ", style="bold")
            status_text.append(status, style="bold")
        renderables.append(status_text)
        renderables.append("")

        # Core results table
        results_table = Table(title="Key Results", show_header=False, box=None)
        results_table.add_column("Property", style="cyan", no_wrap=True)
        results_table.add_column("Value", style="white")

        # Final energy (prefer parsed over database)
        display_energy = parsed_results.get("final_energy") if parsed_results else None
        if display_energy is None:
            display_energy = final_energy

        if display_energy is not None:
            results_table.add_row("Final Energy", f"{display_energy:.10f} Ha")
        else:
            results_table.add_row("Final Energy", "N/A")

        # Convergence
        if parsed_results:
            is_converged = parsed_results.get("is_converged")
            if is_converged is not None:
                conv_str = "CONVERGED" if is_converged else "NOT CONVERGED"
                conv_style = "green" if is_converged else "red"
                results_table.add_row(
                    "Convergence",
                    Text(conv_str, style=conv_style)
                )
        elif key_results and "convergence" in key_results:
            results_table.add_row("Convergence", key_results["convergence"])

        # SCF cycles
        if parsed_results and "scf_cycles" in parsed_results:
            results_table.add_row("SCF Cycles", str(parsed_results["scf_cycles"]))

        # Calculation time
        if created_at and completed_at:
            try:
                start = datetime.fromisoformat(created_at)
                end = datetime.fromisoformat(completed_at)
                duration = end - start
                results_table.add_row("Calculation Time", str(duration).split(".")[0])
            except Exception:
                pass
        elif parsed_results and "timing" in parsed_results:
            timing = parsed_results["timing"]
            if isinstance(timing, dict) and "raw_line" in timing:
                results_table.add_row("CPU Time", timing["raw_line"])

        renderables.append(results_table)
        renderables.append("")

        # Geometry optimization results (if applicable)
        if parsed_results and "geometry_optimization" in parsed_results:
            geo_opt = parsed_results["geometry_optimization"]
            geo_table = Table(title="Geometry Optimization", show_header=False, box=None)
            geo_table.add_column("Property", style="cyan", no_wrap=True)
            geo_table.add_column("Value", style="white")

            if "converged" in geo_opt:
                conv_str = "YES" if geo_opt["converged"] else "NO"
                conv_style = "green" if geo_opt["converged"] else "red"
                geo_table.add_row("Converged", Text(conv_str, style=conv_style))

            if "cycles" in geo_opt:
                geo_table.add_row("Optimization Cycles", str(geo_opt["cycles"]))

            if "final_gradient" in geo_opt and geo_opt["final_gradient"]:
                geo_table.add_row("Final Gradient", f"{geo_opt['final_gradient']:.6e}")

            renderables.append(geo_table)
            renderables.append("")

        # Lattice parameters (if periodic system)
        if parsed_results and "lattice_parameters" in parsed_results:
            lattice = parsed_results["lattice_parameters"]
            lat_table = Table(title="Lattice Parameters", show_header=False, box=None)
            lat_table.add_column("Parameter", style="cyan", no_wrap=True)
            lat_table.add_column("Value", style="white")

            if isinstance(lattice, dict):
                for key, value in lattice.items():
                    if isinstance(value, float):
                        lat_table.add_row(key, f"{value:.6f}")
                    else:
                        lat_table.add_row(key, str(value))

            renderables.append(lat_table)
            renderables.append("")

        # Warnings
        warnings = []
        if parsed_results and "warnings" in parsed_results:
            warnings = parsed_results["warnings"]
        elif key_results and "warnings" in key_results:
            warnings = key_results["warnings"]

        if warnings:
            warn_text = Text()
            warn_text.append(f"Warnings ({len(warnings)}):", style="bold yellow")
            renderables.append(warn_text)
            for warning in warnings[:5]:  # Show first 5 warnings
                warn_line = Text()
                warn_line.append("  ⚠ ", style="yellow")
                warn_line.append(warning, style="yellow")
                renderables.append(warn_line)
            if len(warnings) > 5:
                renderables.append(Text(f"  ... and {len(warnings) - 5} more", style="dim"))
            renderables.append("")

        # Errors
        errors = []
        if parsed_results and "errors" in parsed_results:
            errors = parsed_results["errors"]
        elif key_results and "errors" in key_results:
            errors = key_results["errors"]

        if errors:
            err_text = Text()
            err_text.append(f"Errors ({len(errors)}):", style="bold red")
            renderables.append(err_text)
            for error in errors[:5]:  # Show first 5 errors
                err_line = Text()
                err_line.append("  ✗ ", style="red")
                err_line.append(error, style="red")
                renderables.append(err_line)
            if len(errors) > 5:
                renderables.append(Text(f"  ... and {len(errors) - 5} more", style="dim"))
            renderables.append("")

        # Export hint
        hint = Text()
        hint.append("Press ", style="dim")
        hint.append("e", style="bold cyan")
        hint.append(" to export results to file", style="dim")
        renderables.append("")
        renderables.append(hint)

        return Group(*renderables)

    def display_no_results(self) -> None:
        """Display a message when no results are available."""
        self._current_job_id = None
        self._current_results = None
        self._work_dir = None

        message = Text()
        message.append("No results available\n\n", style="dim italic")
        message.append("Select a completed or failed job to view results", style="dim")

        self.update(message)

    def display_pending(self, job_name: str) -> None:
        """Display a message for pending jobs."""
        self._current_job_id = None
        self._current_results = None
        self._work_dir = None

        message = Text()
        message.append(f"Job: {job_name}\n\n", style="bold cyan")
        message.append("● ", style="bold yellow")
        message.append("PENDING\n\n", style="bold yellow")
        message.append("This job has not been run yet.\n", style="dim")
        message.append("Press ", style="dim")
        message.append("r", style="bold cyan")
        message.append(" to run the job.", style="dim")

        self.update(message)

    def display_running(self, job_name: str) -> None:
        """Display a message for running jobs."""
        message = Text()
        message.append(f"Job: {job_name}\n\n", style="bold cyan")
        message.append("● ", style="bold yellow")
        message.append("RUNNING\n\n", style="bold yellow")
        message.append("This job is currently running.\n", style="dim")
        message.append("Check the Log tab for real-time output.", style="dim")

        self.update(message)

    def display_error(self, error_message: str) -> None:
        """Display an error message."""
        self._current_job_id = None
        self._current_results = None
        self._work_dir = None

        message = Text()
        message.append("Error\n\n", style="bold red")
        message.append(error_message, style="red")

        self.update(message)

    async def action_export_results(self) -> None:
        """Export results to a text file."""
        if not self._current_results or not self._work_dir:
            return

        try:
            job_name = self._current_results["job_name"]
            export_file = self._work_dir / f"{job_name}_summary.txt"

            with export_file.open("w") as f:
                f.write("=" * 80 + "\n")
                f.write(f"CRYSTAL Results Summary\n")
                f.write(f"Job: {job_name}\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 80 + "\n\n")

                # Write status
                f.write(f"Status: {self._current_results['status']}\n\n")

                # Write energy
                final_energy = self._current_results.get("final_energy")
                if final_energy is not None:
                    f.write(f"Final Energy: {final_energy:.10f} Ha\n\n")

                # Write key results
                key_results = self._current_results.get("key_results")
                if key_results:
                    f.write("Key Results:\n")
                    f.write(json.dumps(key_results, indent=2))
                    f.write("\n\n")

                # Write timestamps
                if self._current_results.get("created_at"):
                    f.write(f"Created: {self._current_results['created_at']}\n")
                if self._current_results.get("completed_at"):
                    f.write(f"Completed: {self._current_results['completed_at']}\n")

                f.write("\n" + "=" * 80 + "\n")

            # Notify user
            self.app.post_message_no_wait(
                self.app.notify(f"Results exported to: {export_file.name}", severity="information")
            )

        except Exception as e:
            self.app.post_message_no_wait(
                self.app.notify(f"Export failed: {e}", severity="error")
            )
