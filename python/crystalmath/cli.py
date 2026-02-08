"""
CrystalMath CLI: Command-line interface for job submission and management.

This module provides a Typer-based CLI wrapper around the CrystalController API.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from crystalmath.api import CrystalController
from crystalmath.models import DftCode, JobSubmission, RunnerType

app = typer.Typer(
    name="crystal",
    help="CrystalMath CLI - DFT calculation job management",
    no_args_is_help=True,
)
console = Console()


def _get_controller(use_aiida: bool = False) -> CrystalController:
    """Create a CrystalController instance with auto-detected database."""
    return CrystalController(use_aiida=use_aiida, db_path=None)


@app.command()
def run(
    input_file: str = typer.Argument(..., help="Input file name (without .d12 extension)"),
    ranks: Optional[int] = typer.Argument(None, help="Number of MPI ranks (serial if not specified)"),
    explain: bool = typer.Option(False, "--explain", help="Show execution plan without running"),
    dft_code: str = typer.Option("crystal", help="DFT code to use (crystal, vasp, quantum_espresso)"),
    runner: str = typer.Option("local", help="Execution backend (local, ssh, slurm)"),
) -> None:
    """
    Submit a calculation job.

    Examples:
        crystal run mgo              # Run MgO calculation (serial)
        crystal run mgo 4            # Run with 4 MPI ranks
        crystal run mgo --explain    # Show execution plan
    """
    # Validate input file exists
    input_path = Path(f"{input_file}.d12")
    if not input_path.exists():
        console.print(f"[red]Error:[/red] Input file not found: {input_path}")
        raise typer.Exit(1)

    # Read input content
    try:
        input_content = input_path.read_text()
    except Exception as e:
        console.print(f"[red]Error reading input file:[/red] {e}")
        raise typer.Exit(1)

    # Parse enums
    try:
        dft_code_enum = DftCode(dft_code.lower())
    except ValueError:
        console.print(f"[red]Error:[/red] Invalid DFT code: {dft_code}")
        console.print(f"Valid codes: {', '.join([c.value for c in DftCode])}")
        raise typer.Exit(1)

    try:
        runner_enum = RunnerType(runner.lower())
    except ValueError:
        console.print(f"[red]Error:[/red] Invalid runner type: {runner}")
        console.print(f"Valid runners: {', '.join([r.value for r in RunnerType])}")
        raise typer.Exit(1)

    # Show execution plan if --explain
    if explain:
        console.print(f"[bold]Execution Plan:[/bold]")
        console.print(f"  Input file:   {input_path.absolute()}")
        console.print(f"  Job name:     {input_file}")
        console.print(f"  DFT code:     {dft_code_enum.value}")
        console.print(f"  Runner:       {runner_enum.value}")
        console.print(f"  Parallelism:  {'serial' if ranks is None else f'{ranks} MPI ranks'}")

        # Estimate binary selection
        if dft_code_enum == DftCode.CRYSTAL:
            binary = "crystalOMP" if ranks is None else f"crystal23 (MPI: {ranks} ranks)"
            console.print(f"  Binary:       {binary}")

        # Scratch directory info
        scratch_base = Path.home() / "tmp_crystal"
        console.print(f"  Scratch base: {scratch_base}")
        console.print(f"  Work dir:     {scratch_base / f'crystal_tui_{input_file}_<pid>'}")

        console.print("\n[dim]Note: Use without --explain to submit the job[/dim]")
        return

    # Create job submission
    submission = JobSubmission(
        name=input_file,
        dft_code=dft_code_enum,
        runner_type=runner_enum,
        input_content=input_content,
        mpi_ranks=ranks,
    )

    # Submit job
    try:
        controller = _get_controller()
        job_pk = controller.submit_job(submission)
        console.print(f"[green]Job submitted successfully![/green]")
        console.print(f"  Job ID: {job_pk}")
        console.print(f"  Name:   {input_file}")
        console.print(f"\nUse 'crystal status {job_pk}' to check progress")
    except Exception as e:
        console.print(f"[red]Job submission failed:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def list(
    limit: int = typer.Option(100, help="Maximum number of jobs to show"),
) -> None:
    """
    List all jobs.

    Examples:
        crystal list            # Show last 100 jobs
        crystal list --limit 10 # Show last 10 jobs
    """
    try:
        controller = _get_controller()
        jobs = controller.get_jobs(limit=limit)

        if not jobs:
            console.print("[yellow]No jobs found[/yellow]")
            return

        # Create rich table
        table = Table(title=f"Jobs (showing {len(jobs)})")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Name", style="white")
        table.add_column("State", style="magenta")
        table.add_column("Code", style="blue")
        table.add_column("Runner", style="green")
        table.add_column("Progress", style="yellow")
        table.add_column("Created", style="dim")

        for job in jobs:
            # Color state based on status
            state_color = {
                "COMPLETED": "green",
                "RUNNING": "blue",
                "FAILED": "red",
                "CANCELLED": "yellow",
                "QUEUED": "cyan",
            }.get(job.state.value, "white")

            state_str = f"[{state_color}]{job.state.value}[/{state_color}]"
            progress_str = f"{job.progress_percent:.0f}%"
            created_str = job.created_at.strftime("%Y-%m-%d %H:%M") if job.created_at else "N/A"

            table.add_row(
                str(job.pk),
                job.name,
                state_str,
                job.dft_code.value,
                job.runner_type.value,
                progress_str,
                created_str,
            )

        console.print(table)

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def status(
    pk: int = typer.Argument(..., help="Job ID"),
) -> None:
    """
    Show detailed job status.

    Examples:
        crystal status 42    # Show details for job 42
    """
    try:
        controller = _get_controller()
        details = controller.get_job_details(pk)

        if details is None:
            console.print(f"[red]Error:[/red] Job {pk} not found")
            raise typer.Exit(1)

        # Basic info
        console.print(f"\n[bold]Job {pk}: {details.name}[/bold]")
        console.print(f"  UUID:         {details.uuid or 'N/A'}")
        console.print(f"  State:        [{_state_color(details.state.value)}]{details.state.value}[/]")
        console.print(f"  DFT Code:     {details.dft_code.value}")

        # Results
        if details.final_energy is not None:
            console.print(f"\n[bold]Results:[/bold]")
            console.print(f"  Energy:       {details.final_energy:.6f} Ha")
            if details.bandgap_ev is not None:
                console.print(f"  Bandgap:      {details.bandgap_ev:.3f} eV")
            console.print(f"  Convergence:  {'✓ Met' if details.convergence_met else '✗ Not met'}")
            if details.scf_cycles is not None:
                console.print(f"  SCF cycles:   {details.scf_cycles}")

        # Timing
        if details.wall_time_seconds is not None or details.cpu_time_seconds is not None:
            console.print(f"\n[bold]Timing:[/bold]")
            if details.wall_time_seconds is not None:
                console.print(f"  Wall time:    {_format_seconds(details.wall_time_seconds)}")
            if details.cpu_time_seconds is not None:
                console.print(f"  CPU time:     {_format_seconds(details.cpu_time_seconds)}")

        # Diagnostics
        if details.warnings:
            console.print(f"\n[bold yellow]Warnings ({len(details.warnings)}):[/bold yellow]")
            for warning in details.warnings:
                console.print(f"  • {warning}")

        if details.errors:
            console.print(f"\n[bold red]Errors ({len(details.errors)}):[/bold red]")
            for error in details.errors:
                console.print(f"  • {error}")

        # Work directory
        if details.work_dir:
            console.print(f"\n[bold]Files:[/bold]")
            console.print(f"  Work dir:     {details.work_dir}")

        console.print()  # Blank line

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def log(
    pk: int = typer.Argument(..., help="Job ID"),
    lines: int = typer.Option(100, "--lines", "-n", help="Number of lines to show"),
) -> None:
    """
    View job output log.

    Examples:
        crystal log 42           # Show last 100 lines
        crystal log 42 -n 50     # Show last 50 lines
    """
    try:
        controller = _get_controller()
        log_data = controller.get_job_log(pk, tail_lines=lines)

        if "stdout" not in log_data and "stderr" not in log_data:
            console.print(f"[yellow]No log output available for job {pk}[/yellow]")
            return

        # Show stdout
        stdout_lines = log_data.get("stdout", [])
        if stdout_lines:
            console.print(f"[bold]STDOUT (last {len(stdout_lines)} lines):[/bold]")
            for line in stdout_lines:
                console.print(line)

        # Show stderr
        stderr_lines = log_data.get("stderr", [])
        if stderr_lines:
            console.print(f"\n[bold red]STDERR (last {len(stderr_lines)} lines):[/bold red]")
            for line in stderr_lines:
                console.print(f"[red]{line}[/red]")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def cancel(
    pk: int = typer.Argument(..., help="Job ID"),
) -> None:
    """
    Cancel a running job.

    Examples:
        crystal cancel 42    # Cancel job 42
    """
    try:
        controller = _get_controller()
        success = controller.cancel_job(pk)

        if success:
            console.print(f"[green]Job {pk} cancelled successfully[/green]")
        else:
            console.print(f"[yellow]Failed to cancel job {pk} (may already be finished)[/yellow]")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


# Utility functions

def _state_color(state: str) -> str:
    """Map job state to color."""
    return {
        "COMPLETED": "green",
        "RUNNING": "blue",
        "FAILED": "red",
        "CANCELLED": "yellow",
        "QUEUED": "cyan",
        "SUBMITTED": "cyan",
        "CREATED": "dim",
    }.get(state, "white")


def _format_seconds(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
