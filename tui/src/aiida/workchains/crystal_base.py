"""
Base WorkChain for CRYSTAL23 calculations with self-healing capabilities.

This module provides the CrystalBaseWorkChain that handles:
    - Input validation
    - SCF calculation execution
    - Automatic restart on recoverable errors
    - **Self-healing with adaptive parameter modification**
    - Result validation and output

Self-healing features:
    - SCF convergence pattern analysis (oscillation, slow, divergent)
    - Adaptive FMIXING adjustment for charge mixing issues
    - Level shifting for small-gap systems
    - Automatic resource scaling for memory/timeout failures
    - Wavefunction restart with GUESSP

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

from copy import deepcopy

from aiida import orm
from aiida.engine import ToContext, WorkChain, calcfunction, while_

from .diagnostics import (
    FailureReason,
    SCFDiagnostics,
    analyze_scf_convergence,
    recommend_parameter_modifications,
)


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
            dist = (
                sum((a - b) ** 2 for a, b in zip(site_i.position, site_j.position, strict=False))
                ** 0.5
            )
            if dist < 0.5:  # Angstrom
                issues.append(f"Atoms {i} and {j} are too close ({dist:.2f} Angstrom)")

    return orm.Dict(
        dict={
            "valid": len(issues) == 0,
            "issues": issues,
            "volume": volume,
            "num_atoms": len(sites),
        }
    )


class CrystalBaseWorkChain(WorkChain):
    """
    Self-healing WorkChain for CRYSTAL23 calculations.

    This WorkChain implements intelligent error recovery:
        1. Validates inputs and estimates resources
        2. Submits CRYSTAL23 CalcJob
        3. Analyzes convergence patterns on failure
        4. Applies adaptive parameter modifications
        5. Restarts with corrected parameters

    Self-healing strategies:
        - Charge sloshing → increase FMIXING
        - Small HOMO-LUMO gap → apply level shifting
        - Slow convergence → adjust mixing, increase MAXCYCLE
        - Memory failure → scale up resources
        - Poor initial guess → use GUESSP with previous wavefunction

    Attributes:
        ctx.restart_count: Number of restart attempts.
        ctx.max_restarts: Maximum allowed restarts.
        ctx.current_structure: Structure for current calculation.
        ctx.current_parameters: Parameters (may be modified on restart).
        ctx.diagnostics_history: List of SCFDiagnostics from each attempt.
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
        spec.input(
            "enable_self_healing",
            valid_type=orm.Bool,
            required=False,
            default=lambda: orm.Bool(True),
            help="Enable adaptive parameter modification on failure",
        )
        spec.input(
            "auto_scale_resources",
            valid_type=orm.Bool,
            required=False,
            default=lambda: orm.Bool(True),
            help="Automatically scale resources on memory/timeout failures",
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
        spec.output(
            "diagnostics_report",
            valid_type=orm.Dict,
            required=False,
            help="Self-healing diagnostics report",
        )

        # Workflow outline with while loop for restarts
        spec.outline(
            cls.setup,
            cls.validate_inputs,
            while_(cls.should_run_calculation)(
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
            message="SCF did not converge after {restarts} restart attempts. "
            "Diagnosis: {diagnosis}",
        )
        spec.exit_code(
            303,
            "ERROR_UNRECOVERABLE",
            message="Unrecoverable error: {message}",
        )
        spec.exit_code(
            304,
            "ERROR_RESOURCE_LIMIT",
            message="Resource limit ({resource}) exceeded after {restarts} attempts",
        )

    def setup(self) -> None:
        """Initialize workflow context."""
        self.ctx.restart_count = 0
        self.ctx.max_restarts = self.inputs.max_restarts.value
        self.ctx.current_structure = self.inputs.structure
        self.ctx.current_parameters = deepcopy(self.inputs.parameters.get_dict())
        self.ctx.current_wavefunction = self.inputs.get("wavefunction")
        self.ctx.current_options = deepcopy(self.inputs.options.get_dict())
        self.ctx.calculation_finished = False
        self.ctx.diagnostics_history = []
        self.ctx.modifications_applied = []
        self.ctx.enable_self_healing = self.inputs.enable_self_healing.value
        self.ctx.auto_scale_resources = self.inputs.auto_scale_resources.value

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
        """Submit CRYSTAL23 CalcJob with current (potentially modified) parameters."""
        attempt = self.ctx.restart_count + 1
        max_attempts = self.ctx.max_restarts + 1

        self.report(f"Submitting CRYSTAL23 calculation (attempt {attempt}/{max_attempts})")

        # Report any parameter modifications applied
        if self.ctx.modifications_applied:
            mods = self.ctx.modifications_applied[-1] if self.ctx.modifications_applied else []
            for mod in mods:
                self.report(f"  Modified {mod['parameter']}: {mod['old']} → {mod['new']}")

        # Import CalcJob
        from src.aiida.calcjobs.crystal23 import Crystal23Calculation

        # Use current parameters (may have been modified by self-healing)
        parameters_node = orm.Dict(dict=self.ctx.current_parameters)

        # Build inputs
        inputs = {
            "code": self.inputs.code,
            "crystal": {
                "structure": self.ctx.current_structure,
                "parameters": parameters_node,
            },
            "metadata": {
                "options": self._get_calculation_options(),
                "label": self.inputs.structure.label or "CRYSTAL23 calculation",
            },
        }

        # Add restart wavefunction if available (enables GUESSP)
        if self.ctx.current_wavefunction:
            inputs["crystal"]["wavefunction"] = self.ctx.current_wavefunction
            self.report("  Using wavefunction restart (GUESSP)")

        # Submit calculation
        future = self.submit(Crystal23Calculation, **inputs)
        self.report(f"Submitted CalcJob <{future.pk}>")

        return ToContext(calculation=future)

    def inspect_calculation(self):
        """Inspect calculation results and apply self-healing if needed."""
        calc = self.ctx.calculation

        if calc.is_finished_ok:
            self.report(f"Calculation <{calc.pk}> completed successfully")
            self.ctx.calculation_finished = True
            return

        # Get output content for diagnostics
        output_content = self._get_output_content(calc)
        exit_status = calc.exit_status

        # Analyze convergence behavior
        diagnostics = None
        if output_content and self.ctx.enable_self_healing:
            diagnostics = analyze_scf_convergence(output_content)
            self.ctx.diagnostics_history.append(
                {
                    "attempt": self.ctx.restart_count + 1,
                    "pattern": diagnostics.pattern.name,
                    "reason": diagnostics.reason.name,
                    "confidence": diagnostics.confidence,
                    "energy_history": diagnostics.energy_history[-10:],  # Last 10
                    "recommendations": diagnostics.recommendations,
                }
            )
            self.report(
                f"Convergence analysis: {diagnostics.pattern.name} "
                f"(reason: {diagnostics.reason.name}, confidence: {diagnostics.confidence:.0%})"
            )

        # Handle specific error codes with self-healing
        if exit_status == 302:  # ERROR_SCF_NOT_CONVERGED
            return self._handle_scf_failure(diagnostics)

        if exit_status in (304, 305):  # Memory/timeout
            return self._handle_resource_failure(exit_status)

        # Generic failure handling
        if calc.is_failed:
            return self._handle_generic_failure(exit_status, diagnostics)

    def _get_output_content(self, calc) -> str | None:
        """Retrieve output file content for diagnostics."""
        try:
            retrieved = calc.outputs.retrieved
            output_filename = calc.get_option("output_filename")
            return retrieved.get_object_content(output_filename)
        except (AttributeError, FileNotFoundError, KeyError):
            return None

    def _handle_scf_failure(self, diagnostics: SCFDiagnostics | None):
        """Handle SCF convergence failure with adaptive parameter modification."""
        if self.ctx.restart_count >= self.ctx.max_restarts:
            diagnosis = "unknown"
            if diagnostics:
                diagnosis = f"{diagnostics.pattern.name}/{diagnostics.reason.name}"
            return self.exit_codes.ERROR_SCF_NOT_CONVERGED.format(
                restarts=self.ctx.restart_count,
                diagnosis=diagnosis,
            )

        self.report("SCF did not converge, applying self-healing strategies")

        # Apply adaptive modifications if diagnostics available
        modifications_applied = []

        if diagnostics and self.ctx.enable_self_healing:
            # Get recommended parameter modifications
            recommended = recommend_parameter_modifications(
                diagnostics,
                self.ctx.current_parameters,
                self.ctx.restart_count,
            )

            # Apply modifications to current parameters
            for mod in recommended:
                self._apply_parameter_modification(mod)
                modifications_applied.append(
                    {
                        "parameter": mod.parameter,
                        "old": mod.old_value,
                        "new": mod.new_value,
                        "reason": mod.reason,
                    }
                )
                self.report(f"  → {mod.parameter}: {mod.old_value} → {mod.new_value}")
                self.report(f"    Reason: {mod.reason}")

        else:
            # Fallback: simple parameter escalation
            self._apply_fallback_scf_fixes()
            modifications_applied.append(
                {
                    "parameter": "scf.maxcycle",
                    "old": self.ctx.current_parameters.get("scf", {}).get("maxcycle", 100),
                    "new": self.ctx.current_parameters.get("scf", {}).get("maxcycle", 150),
                    "reason": "Fallback: increase max cycles",
                }
            )

        self.ctx.modifications_applied.append(modifications_applied)

        # Use wavefunction from failed calculation as restart
        calc = self.ctx.calculation
        if hasattr(calc.outputs, "wavefunction"):
            self.ctx.current_wavefunction = calc.outputs.wavefunction
            self.report("  → Using failed calculation wavefunction for restart")

        self.ctx.restart_count += 1

    def _apply_parameter_modification(self, mod):
        """Apply a single parameter modification to current parameters."""
        params = self.ctx.current_parameters

        # Parse nested parameter path (e.g., "scf.fmixing")
        parts = mod.parameter.split(".")
        target = params

        # Navigate to parent
        for part in parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]

        # Set value
        target[parts[-1]] = mod.new_value

    def _apply_fallback_scf_fixes(self):
        """Apply simple fallback fixes when diagnostics unavailable."""
        params = self.ctx.current_parameters
        scf = params.setdefault("scf", {})

        # Increase MAXCYCLE
        current_maxcycle = scf.get("maxcycle", 100)
        scf["maxcycle"] = min(current_maxcycle + 50, 500)

        # Increase FMIXING slightly
        current_fmixing = scf.get("fmixing", 30)
        scf["fmixing"] = min(current_fmixing + 10, 80)

    def _handle_resource_failure(self, exit_status: int):
        """Handle memory/timeout failures with optional auto-scaling."""
        resource_type = "memory" if exit_status == 304 else "walltime"

        if self.ctx.restart_count >= self.ctx.max_restarts:
            return self.exit_codes.ERROR_RESOURCE_LIMIT.format(
                resource=resource_type,
                restarts=self.ctx.restart_count,
            )

        self.report(f"Resource limit exceeded ({resource_type})")

        if self.ctx.auto_scale_resources:
            self._scale_resources(resource_type)
        else:
            self.report("Auto-scaling disabled; manual resource adjustment required")

        # Preserve wavefunction for restart
        calc = self.ctx.calculation
        if hasattr(calc.outputs, "wavefunction"):
            self.ctx.current_wavefunction = calc.outputs.wavefunction

        self.ctx.restart_count += 1

    def _scale_resources(self, resource_type: str):
        """Scale up computational resources."""
        options = self.ctx.current_options
        resources = options.setdefault("resources", {})

        if resource_type == "memory":
            # Increase memory per node (if supported by scheduler)
            current_mem = resources.get("memory_mb", 4000)
            new_mem = int(current_mem * 1.5)
            resources["memory_mb"] = new_mem
            self.report(f"  → Scaling memory: {current_mem} MB → {new_mem} MB")

            # Also try increasing MPI ranks to distribute memory
            current_mpi = resources.get("num_mpiprocs_per_machine", 1)
            if current_mpi < 4:
                new_mpi = current_mpi * 2
                resources["num_mpiprocs_per_machine"] = new_mpi
                self.report(f"  → Scaling MPI ranks: {current_mpi} → {new_mpi}")

        elif resource_type == "walltime":
            current_wall = options.get("max_wallclock_seconds", 3600)
            new_wall = int(current_wall * 2)
            options["max_wallclock_seconds"] = new_wall
            self.report(f"  → Scaling walltime: {current_wall}s → {new_wall}s")

        self.ctx.modifications_applied.append(
            [
                {
                    "parameter": f"options.{resource_type}",
                    "old": "previous",
                    "new": "scaled",
                    "reason": f"Auto-scaling {resource_type} after failure",
                }
            ]
        )

    def _handle_generic_failure(self, exit_status: int, diagnostics: SCFDiagnostics | None):
        """Handle unclassified failures."""
        if self.ctx.restart_count >= self.ctx.max_restarts:
            return self.exit_codes.ERROR_CALCULATION_FAILED.format(restarts=self.ctx.restart_count)

        self.report(f"Calculation failed with exit code {exit_status}, attempting restart")

        # Try to salvage wavefunction
        calc = self.ctx.calculation
        if hasattr(calc.outputs, "wavefunction"):
            self.ctx.current_wavefunction = calc.outputs.wavefunction

        # Apply conservative parameter changes
        if diagnostics and diagnostics.reason != FailureReason.UNKNOWN:
            recommended = recommend_parameter_modifications(
                diagnostics,
                self.ctx.current_parameters,
                self.ctx.restart_count,
            )
            for mod in recommended[:2]:  # Apply only top 2 recommendations
                self._apply_parameter_modification(mod)
        else:
            self._apply_fallback_scf_fixes()

        self.ctx.restart_count += 1

    def results(self):
        """Collect and expose outputs including diagnostics report."""
        calc = self.ctx.calculation

        if not calc.is_finished_ok:
            # Still output diagnostics report even on failure
            self._output_diagnostics_report()
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

        # Diagnostics report
        self._output_diagnostics_report()

        self.report("WorkChain completed successfully")

    def _output_diagnostics_report(self):
        """Create and output the diagnostics report."""
        report = {
            "total_attempts": self.ctx.restart_count + 1,
            "max_restarts": self.ctx.max_restarts,
            "self_healing_enabled": self.ctx.enable_self_healing,
            "auto_scale_resources": self.ctx.auto_scale_resources,
            "diagnostics_history": self.ctx.diagnostics_history,
            "modifications_applied": self.ctx.modifications_applied,
            "final_parameters": self.ctx.current_parameters,
        }

        # Add summary statistics
        if self.ctx.diagnostics_history:
            patterns = [d["pattern"] for d in self.ctx.diagnostics_history]
            reasons = [d["reason"] for d in self.ctx.diagnostics_history]
            report["summary"] = {
                "patterns_observed": list(set(patterns)),
                "reasons_identified": list(set(reasons)),
                "total_modifications": sum(len(m) for m in self.ctx.modifications_applied),
            }

        self.out("diagnostics_report", orm.Dict(dict=report))

    def _get_calculation_options(self) -> dict:
        """Get calculation options with defaults, using potentially scaled values."""
        # Use current_options which may have been modified by auto-scaling
        options = deepcopy(self.ctx.current_options)

        defaults = {
            "resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1},
            "max_wallclock_seconds": 3600,
            "withmpi": False,
        }

        for key, value in defaults.items():
            options.setdefault(key, value)

        return options
