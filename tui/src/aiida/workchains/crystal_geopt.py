"""
Geometry Optimization WorkChain for CRYSTAL23.

This module provides the CrystalGeometryOptimizationWorkChain that handles:
    - Multi-step geometry optimization
    - Convergence monitoring
    - Automatic restart from last good geometry
    - Trajectory tracking

Example:
    >>> from aiida import engine, orm
    >>> from src.aiida.workchains import CrystalGeometryOptimizationWorkChain
    >>>
    >>> builder = CrystalGeometryOptimizationWorkChain.get_builder()
    >>> builder.structure = structure_data
    >>> builder.parameters = orm.Dict(dict={"optgeom": {"fulloptg": True}})
    >>> builder.code = orm.load_code("crystalOMP@localhost")
    >>> result = engine.run(builder)
"""

from __future__ import annotations

from aiida import orm
from aiida.engine import ToContext, WorkChain, while_

from .crystal_base import CrystalBaseWorkChain


class CrystalGeometryOptimizationWorkChain(WorkChain):
    """
    Geometry optimization WorkChain for CRYSTAL23.

    Runs iterative geometry optimization with:
        - Automatic convergence detection
        - Multi-stage optimization (optional)
        - Trajectory tracking
        - Restart capability

    Optimization modes:
        - FULLOPTG: Full optimization (lattice + atoms)
        - ATOMONLY: Atomic positions only (fixed lattice)
        - CELLONLY: Lattice parameters only (fixed atoms)
        - ITATOCEL: Iterative atom-then-cell optimization
    """

    @classmethod
    def define(cls, spec) -> None:
        """Define WorkChain specification."""
        super().define(spec)

        # Inputs
        spec.input(
            "structure",
            valid_type=orm.StructureData,
            help="Initial crystal structure",
        )
        spec.input(
            "parameters",
            valid_type=orm.Dict,
            help="CRYSTAL23 input parameters with 'optgeom' section",
        )
        spec.input(
            "code",
            valid_type=orm.AbstractCode,
            help="CRYSTAL23 code",
        )
        spec.input(
            "options",
            valid_type=orm.Dict,
            required=False,
            default=lambda: orm.Dict(dict={}),
            help="Calculation options",
        )
        spec.input(
            "optimization_mode",
            valid_type=orm.Str,
            required=False,
            default=lambda: orm.Str("fulloptg"),
            help="Optimization mode: fulloptg, atomonly, cellonly, itatocel",
        )
        spec.input(
            "max_iterations",
            valid_type=orm.Int,
            required=False,
            default=lambda: orm.Int(10),
            help="Maximum optimization iterations (for multi-stage modes)",
        )
        spec.input(
            "force_threshold",
            valid_type=orm.Float,
            required=False,
            default=lambda: orm.Float(0.00045),
            help="Force convergence threshold (Hartree/Bohr)",
        )
        spec.input(
            "displacement_threshold",
            valid_type=orm.Float,
            required=False,
            default=lambda: orm.Float(0.0018),
            help="Displacement convergence threshold (Bohr)",
        )

        # Outputs
        spec.output(
            "output_structure",
            valid_type=orm.StructureData,
            help="Optimized crystal structure",
        )
        spec.output(
            "output_parameters",
            valid_type=orm.Dict,
            help="Optimization results and convergence info",
        )
        spec.output(
            "trajectory",
            valid_type=orm.TrajectoryData,
            required=False,
            help="Optimization trajectory",
        )
        spec.output(
            "wavefunction",
            valid_type=orm.SinglefileData,
            required=False,
            help="Final converged wavefunction",
        )

        # Workflow outline
        spec.outline(
            cls.setup,
            while_(cls.should_continue_optimization)(
                cls.run_optimization_step,
                cls.inspect_optimization,
            ),
            cls.results,
        )

        # Exit codes
        spec.exit_code(
            400,
            "ERROR_OPTIMIZATION_FAILED",
            message="Geometry optimization failed: {message}",
        )
        spec.exit_code(
            401,
            "ERROR_MAX_ITERATIONS",
            message="Maximum optimization iterations ({max_iter}) exceeded",
        )

    def setup(self) -> None:
        """Initialize workflow context."""
        self.ctx.current_structure = self.inputs.structure
        self.ctx.current_wavefunction = None
        self.ctx.iteration = 0
        self.ctx.max_iterations = self.inputs.max_iterations.value
        self.ctx.converged = False
        self.ctx.optimization_mode = self.inputs.optimization_mode.value.lower()
        self.ctx.trajectory_structures = []
        self.ctx.trajectory_energies = []
        self.ctx.calculations = []

        # For itatocel mode, track alternation
        self.ctx.current_phase = "atoms"  # atoms or cell

        self.report(
            f"Starting geometry optimization "
            f"(mode: {self.ctx.optimization_mode}, max_iter: {self.ctx.max_iterations})"
        )

    def should_continue_optimization(self) -> bool:
        """Check if optimization should continue."""
        if self.ctx.converged:
            return False
        if self.ctx.iteration >= self.ctx.max_iterations:
            return False
        return True

    def run_optimization_step(self):
        """Run a single optimization step using base WorkChain."""
        self.ctx.iteration += 1
        self.report(f"Running optimization step {self.ctx.iteration}/{self.ctx.max_iterations}")

        # Prepare parameters based on optimization mode
        params = self._prepare_optimization_parameters()

        # Build inputs for base WorkChain
        inputs = {
            "structure": self.ctx.current_structure,
            "parameters": orm.Dict(dict=params),
            "code": self.inputs.code,
            "options": self.inputs.options,
            "max_restarts": orm.Int(2),
        }

        # Add restart wavefunction if available
        if self.ctx.current_wavefunction:
            inputs["wavefunction"] = self.ctx.current_wavefunction

        # Submit base WorkChain
        future = self.submit(CrystalBaseWorkChain, **inputs)
        self.report(f"Submitted optimization WorkChain <{future.pk}>")

        return ToContext(workchain=future)

    def inspect_optimization(self):
        """Inspect optimization results and update state."""
        workchain = self.ctx.workchain
        self.ctx.calculations.append(workchain.pk)

        if not workchain.is_finished_ok:
            # Check if it's a recoverable error
            if workchain.exit_status in (302, 303):
                self.report("Optimization step did not converge, checking if recoverable...")

                # Try to get last good structure
                if hasattr(workchain.outputs, "output_structure"):
                    self.ctx.current_structure = workchain.outputs.output_structure
                    self.report("Using last good structure for next iteration")
                    return

            return self.exit_codes.ERROR_OPTIMIZATION_FAILED.format(
                message=f"WorkChain <{workchain.pk}> failed with exit code {workchain.exit_status}"
            )

        # Extract results
        output_params = workchain.outputs.output_parameters.get_dict()

        # Check convergence
        self.ctx.converged = output_params.get("geom_converged", False)

        # Update structure
        if hasattr(workchain.outputs, "output_structure"):
            self.ctx.current_structure = workchain.outputs.output_structure
        elif hasattr(workchain.outputs, "wavefunction"):
            # Structure might be in extras or need to be extracted
            pass

        # Update wavefunction for restart
        if hasattr(workchain.outputs, "wavefunction"):
            self.ctx.current_wavefunction = workchain.outputs.wavefunction

        # Track trajectory
        self.ctx.trajectory_structures.append(self.ctx.current_structure)
        if "final_energy_hartree" in output_params:
            self.ctx.trajectory_energies.append(output_params["final_energy_hartree"])

        # Report progress
        energy = output_params.get("final_energy_hartree", "N/A")
        opt_steps = output_params.get("optimization_steps", "N/A")
        self.report(
            f"Step {self.ctx.iteration}: "
            f"E = {energy} Ha, "
            f"opt_steps = {opt_steps}, "
            f"converged = {self.ctx.converged}"
        )

        # Handle itatocel mode
        if self.ctx.optimization_mode == "itatocel" and not self.ctx.converged:
            self._alternate_itatocel_phase()

    def results(self):
        """Collect and expose final results."""
        if not self.ctx.converged:
            if self.ctx.iteration >= self.ctx.max_iterations:
                return self.exit_codes.ERROR_MAX_ITERATIONS.format(max_iter=self.ctx.max_iterations)

        # Output structure
        self.out("output_structure", self.ctx.current_structure)

        # Compile output parameters
        output_params = {
            "converged": self.ctx.converged,
            "iterations": self.ctx.iteration,
            "optimization_mode": self.ctx.optimization_mode,
            "calculations": self.ctx.calculations,
            "energies": self.ctx.trajectory_energies,
        }

        # Add final energy
        if self.ctx.trajectory_energies:
            output_params["final_energy_hartree"] = self.ctx.trajectory_energies[-1]
            output_params["energy_change_hartree"] = (
                self.ctx.trajectory_energies[-1] - self.ctx.trajectory_energies[0]
            )

        self.out("output_parameters", orm.Dict(dict=output_params))

        # Output wavefunction
        if self.ctx.current_wavefunction:
            self.out("wavefunction", self.ctx.current_wavefunction)

        # Create trajectory if multiple structures
        if len(self.ctx.trajectory_structures) > 1:
            try:
                trajectory = self._create_trajectory()
                if trajectory:
                    self.out("trajectory", trajectory)
            except Exception as e:
                self.report(f"Could not create trajectory: {e}")

        self.report(
            f"Geometry optimization completed: "
            f"converged = {self.ctx.converged}, "
            f"iterations = {self.ctx.iteration}"
        )

    def _prepare_optimization_parameters(self) -> dict:
        """Prepare parameters for current optimization step."""
        params = self.inputs.parameters.get_dict()

        # Ensure optgeom section exists
        optgeom = params.setdefault("optgeom", {})

        # Set optimization mode
        mode = self.ctx.optimization_mode

        # Clear any existing mode flags
        for flag in ["fulloptg", "atomonly", "cellonly"]:
            optgeom.pop(flag, None)

        if mode == "fulloptg":
            optgeom["fulloptg"] = True
        elif mode == "atomonly":
            optgeom["atomonly"] = True
        elif mode == "cellonly":
            optgeom["cellonly"] = True
        elif mode == "itatocel":
            # Alternate between atom and cell
            if self.ctx.current_phase == "atoms":
                optgeom["atomonly"] = True
            else:
                optgeom["cellonly"] = True

        # Set convergence thresholds
        optgeom["toldeg"] = self.inputs.force_threshold.value
        optgeom["toldex"] = self.inputs.displacement_threshold.value

        return params

    def _alternate_itatocel_phase(self) -> None:
        """Switch between atom and cell optimization in itatocel mode."""
        if self.ctx.current_phase == "atoms":
            self.ctx.current_phase = "cell"
            self.report("Switching to cell optimization phase")
        else:
            self.ctx.current_phase = "atoms"
            self.report("Switching to atom optimization phase")

    def _create_trajectory(self) -> orm.TrajectoryData | None:
        """Create TrajectoryData from optimization steps."""
        try:
            import numpy as np

            cells = []
            positions = []
            symbols = []

            for structure in self.ctx.trajectory_structures:
                cells.append(structure.cell)

                site_positions = []
                site_symbols = []
                for site in structure.sites:
                    site_positions.append(site.position)
                    site_symbols.append(site.kind_name)

                positions.append(site_positions)
                if not symbols:
                    symbols = site_symbols

            trajectory = orm.TrajectoryData()
            trajectory.set_trajectory(
                stepids=np.arange(len(cells)),
                cells=np.array(cells),
                positions=np.array(positions),
                symbols=symbols,
            )

            return trajectory

        except Exception as e:
            self.report(f"Failed to create trajectory: {e}")
            return None
