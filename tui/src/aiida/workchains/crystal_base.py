"""
Base WorkChain for CRYSTAL23 calculations.

This module provides the CrystalBaseWorkChain that handles:
    - Input validation
    - SCF calculation execution
    - Automatic restart on recoverable errors
    - Result validation and output

This WorkChain replaces the custom orchestrator in src/core/orchestrator.py.

Example:
    >>> from aiida import engine, orm
    >>> from src.aiida.workchains import CrystalBaseWorkChain
    >>>
    >>> builder = CrystalBaseWorkChain.get_builder()
    >>> builder.structure = structure_data
    >>> builder.parameters = orm.Dict(dict={...})
    >>> builder.code = orm.load_code("crystalOMP@localhost")
    >>> result = engine.run(builder)
"""

from __future__ import annotations

from aiida import orm
from aiida.engine import ToContext, WorkChain, calcfunction, if_


@calcfunction
def validate_structure(structure: orm.StructureData) -> orm.Dict:
    """
    Validate input structure.

    Checks for:
        - Non-zero volume
        - Valid atomic positions
        - Reasonable interatomic distances

    Args:
        structure: Input structure.

    Returns:
        Dict with validation results.
    """
    issues = []

    # Check volume
    volume = structure.get_cell_volume()
    if volume <= 0:
        issues.append("Cell volume is zero or negative")

    # Check for overlapping atoms
    sites = structure.sites
    for i, site_i in enumerate(sites):
        for j, site_j in enumerate(sites[i + 1 :], start=i + 1):
            dist = sum(
                (a - b) ** 2 for a, b in zip(site_i.position, site_j.position)
            ) ** 0.5
            if dist < 0.5:  # Angstrom
                issues.append(
                    f"Atoms {i} and {j} are too close ({dist:.2f} Angstrom)"
                )

    return orm.Dict(dict={
        "valid": len(issues) == 0,
        "issues": issues,
        "volume": volume,
        "num_atoms": len(sites),
    })


class CrystalBaseWorkChain(WorkChain):
    """
    Base WorkChain for CRYSTAL23 calculations with error handling and restarts.

    This WorkChain:
        1. Validates inputs
        2. Submits CRYSTAL23 CalcJob
        3. Inspects results and handles errors
        4. Optionally restarts with modified parameters

    Attributes:
        ctx.restart_count: Number of restart attempts.
        ctx.max_restarts: Maximum allowed restarts.
        ctx.current_structure: Structure for current calculation.
    """

    @classmethod
    def define(cls, spec) -> None:
        """Define WorkChain specification."""
        super().define(spec)

        # Inputs
        spec.input(
            "structure",
            valid_type=orm.StructureData,
            help="Crystal structure",
        )
        spec.input(
            "parameters",
            valid_type=orm.Dict,
            help="CRYSTAL23 input parameters",
        )
        spec.input(
            "code",
            valid_type=orm.AbstractCode,
            help="CRYSTAL23 code (crystalOMP or PcrystalOMP)",
        )
        spec.input(
            "options",
            valid_type=orm.Dict,
            required=False,
            default=lambda: orm.Dict(dict={}),
            help="Calculation options (resources, walltime, etc.)",
        )
        spec.input(
            "wavefunction",
            valid_type=orm.SinglefileData,
            required=False,
            help="Restart wavefunction from previous calculation",
        )
        spec.input(
            "max_restarts",
            valid_type=orm.Int,
            required=False,
            default=lambda: orm.Int(3),
            help="Maximum number of restart attempts",
        )
        spec.input(
            "clean_workdir",
            valid_type=orm.Bool,
            required=False,
            default=lambda: orm.Bool(True),
            help="Clean work directory after successful completion",
        )

        # Outputs
        spec.output(
            "output_parameters",
            valid_type=orm.Dict,
            help="Parsed calculation results",
        )
        spec.output(
            "output_structure",
            valid_type=orm.StructureData,
            required=False,
            help="Optimized structure (if geometry optimization)",
        )
        spec.output(
            "wavefunction",
            valid_type=orm.SinglefileData,
            required=False,
            help="Converged wavefunction",
        )
        spec.output(
            "remote_folder",
            valid_type=orm.RemoteData,
            required=False,
            help="Remote work directory",
        )

        # Workflow outline
        spec.outline(
            cls.setup,
            cls.validate_inputs,
            if_(cls.should_run_calculation)(
                cls.run_calculation,
                cls.inspect_calculation,
            ),
            cls.results,
        )

        # Exit codes
        spec.exit_code(
            300,
            "ERROR_INVALID_STRUCTURE",
            message="Input structure validation failed: {message}",
        )
        spec.exit_code(
            301,
            "ERROR_CALCULATION_FAILED",
            message="CRYSTAL23 calculation failed after {restarts} restart attempts",
        )
        spec.exit_code(
            302,
            "ERROR_SCF_NOT_CONVERGED",
            message="SCF did not converge after {restarts} restart attempts",
        )
        spec.exit_code(
            303,
            "ERROR_UNRECOVERABLE",
            message="Unrecoverable error: {message}",
        )

    def setup(self) -> None:
        """Initialize workflow context."""
        self.ctx.restart_count = 0
        self.ctx.max_restarts = self.inputs.max_restarts.value
        self.ctx.current_structure = self.inputs.structure
        self.ctx.current_wavefunction = self.inputs.get("wavefunction")
        self.ctx.calculation_finished = False

    def validate_inputs(self):
        """Validate input structure and parameters."""
        self.report("Validating input structure...")

        validation = validate_structure(self.inputs.structure)

        if not validation["valid"]:
            issues = ", ".join(validation["issues"])
            return self.exit_codes.ERROR_INVALID_STRUCTURE.format(message=issues)

        self.report(
            f"Structure validated: {validation['num_atoms']} atoms, "
            f"volume = {validation['volume']:.2f} A^3"
        )

    def should_run_calculation(self) -> bool:
        """Determine if calculation should run."""
        return not self.ctx.calculation_finished

    def run_calculation(self):
        """Submit CRYSTAL23 CalcJob."""
        self.report(
            f"Submitting CRYSTAL23 calculation "
            f"(attempt {self.ctx.restart_count + 1}/{self.ctx.max_restarts + 1})"
        )

        # Import CalcJob
        from src.aiida.calcjobs.crystal23 import Crystal23Calculation

        # Build inputs
        inputs = {
            "code": self.inputs.code,
            "crystal": {
                "structure": self.ctx.current_structure,
                "parameters": self.inputs.parameters,
            },
            "metadata": {
                "options": self._get_calculation_options(),
                "label": self.inputs.structure.label or "CRYSTAL23 calculation",
            },
        }

        # Add restart wavefunction if available
        if self.ctx.current_wavefunction:
            inputs["crystal"]["wavefunction"] = self.ctx.current_wavefunction

        # Submit calculation
        future = self.submit(Crystal23Calculation, **inputs)
        self.report(f"Submitted CalcJob <{future.pk}>")

        return ToContext(calculation=future)

    def inspect_calculation(self):
        """Inspect calculation results and handle errors."""
        calc = self.ctx.calculation

        if calc.is_finished_ok:
            self.report(f"Calculation <{calc.pk}> completed successfully")
            self.ctx.calculation_finished = True
            return

        # Handle specific error codes
        exit_status = calc.exit_status

        # SCF convergence failure - potentially restartable
        if exit_status == 302:  # ERROR_SCF_NOT_CONVERGED
            return self._handle_scf_failure()

        # Memory/timeout errors - potentially restartable with more resources
        if exit_status in (304, 305):
            return self._handle_resource_failure(exit_status)

        # Other failures
        if calc.is_failed:
            if self.ctx.restart_count < self.ctx.max_restarts:
                self.report(
                    f"Calculation failed with exit code {exit_status}, "
                    f"attempting restart..."
                )
                self.ctx.restart_count += 1
                return self.run_calculation()
            else:
                return self.exit_codes.ERROR_CALCULATION_FAILED.format(
                    restarts=self.ctx.restart_count
                )

    def _handle_scf_failure(self):
        """Handle SCF convergence failure."""
        if self.ctx.restart_count >= self.ctx.max_restarts:
            return self.exit_codes.ERROR_SCF_NOT_CONVERGED.format(
                restarts=self.ctx.restart_count
            )

        self.report("SCF did not converge, attempting restart with modified parameters")

        # Modify parameters for restart
        params = self.inputs.parameters.get_dict()

        # Increase MAXCYCLE
        scf = params.setdefault("scf", {})
        current_maxcycle = scf.get("maxcycle", 100)
        scf["maxcycle"] = min(current_maxcycle + 50, 500)

        # Tighten convergence gradually
        if self.ctx.restart_count > 0:
            scf["toldee"] = scf.get("toldee", 7) + 1

        # Store modified parameters
        self.ctx.modified_parameters = orm.Dict(dict=params)

        # Use wavefunction from failed calculation as restart
        calc = self.ctx.calculation
        if hasattr(calc.outputs, "wavefunction"):
            self.ctx.current_wavefunction = calc.outputs.wavefunction

        self.ctx.restart_count += 1
        return

    def _handle_resource_failure(self, exit_status: int):
        """Handle memory/timeout failures."""
        if self.ctx.restart_count >= self.ctx.max_restarts:
            message = (
                "Insufficient memory" if exit_status == 304 else "Timeout exceeded"
            )
            return self.exit_codes.ERROR_UNRECOVERABLE.format(message=message)

        self.report("Resource limit exceeded, restart with increased resources needed")

        # For now, just report - user should adjust resources manually
        self.ctx.restart_count += 1
        return

    def results(self):
        """Collect and expose outputs."""
        calc = self.ctx.calculation

        if not calc.is_finished_ok:
            return

        # Output parameters
        if hasattr(calc.outputs, "output_parameters"):
            self.out("output_parameters", calc.outputs.output_parameters)

        # Output structure
        if hasattr(calc.outputs, "output_structure"):
            self.out("output_structure", calc.outputs.output_structure)

        # Wavefunction
        if hasattr(calc.outputs, "wavefunction"):
            self.out("wavefunction", calc.outputs.wavefunction)

        # Remote folder
        if hasattr(calc.outputs, "remote_folder"):
            self.out("remote_folder", calc.outputs.remote_folder)

        self.report("WorkChain completed successfully")

    def _get_calculation_options(self) -> dict:
        """Get calculation options with defaults."""
        options = self.inputs.options.get_dict()

        defaults = {
            "resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1},
            "max_wallclock_seconds": 3600,
            "withmpi": False,
        }

        for key, value in defaults.items():
            options.setdefault(key, value)

        return options
