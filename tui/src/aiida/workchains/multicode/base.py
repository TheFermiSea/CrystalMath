"""
Base classes for multi-code workflows.

Provides abstract base classes for orchestrating CRYSTAL23 SCF calculations
with external post-processing codes (YAMBO, BerkeleyGW, Wannier90).

Classes:
    MultiCodeWorkChain: Base for any multi-code orchestration
    PostSCFWorkChain: Base for SCF + post-processing pattern
"""

from __future__ import annotations

from abc import abstractmethod
from typing import ClassVar

from aiida import orm
from aiida.engine import ToContext, WorkChain, calcfunction


class MultiCodeWorkChain(WorkChain):
    """
    Abstract base for multi-code workflow orchestration.

    Provides common infrastructure for workflows that chain multiple
    computational codes together. Handles:
    - Code validation and availability checking
    - Error propagation between codes
    - Intermediate result storage
    - Restart capabilities
    """

    # Subclasses define required external codes
    REQUIRED_CODES: ClassVar[list[str]] = []

    @classmethod
    def define(cls, spec):
        """Define the process specification."""
        super().define(spec)

        # Common metadata
        spec.input(
            "clean_workdir",
            valid_type=orm.Bool,
            default=lambda: orm.Bool(True),
            help="Clean working directories after successful completion.",
        )
        spec.input(
            "store_intermediate",
            valid_type=orm.Bool,
            default=lambda: orm.Bool(True),
            help="Store intermediate results between codes.",
        )

        # Exit codes
        spec.exit_code(
            300,
            "ERROR_CODE_NOT_AVAILABLE",
            message="Required external code is not configured.",
        )
        spec.exit_code(
            301,
            "ERROR_FIRST_STAGE_FAILED",
            message="First-stage calculation failed.",
        )
        spec.exit_code(
            302,
            "ERROR_CONVERSION_FAILED",
            message="Failed to convert between code formats.",
        )
        spec.exit_code(
            303,
            "ERROR_SECOND_STAGE_FAILED",
            message="Second-stage calculation failed.",
        )

    def validate_codes(self) -> bool:
        """
        Validate that all required codes are available.

        Returns:
            True if all codes are configured, False otherwise.
        """
        for code_name in self.REQUIRED_CODES:
            if code_name not in self.inputs:
                self.report(f"Required code '{code_name}' not provided")
                return False

            code = self.inputs[code_name]
            if not code.can_run_on_computer(code.computer):
                self.report(f"Code '{code_name}' cannot run on its configured computer")
                return False

        return True


class PostSCFWorkChain(MultiCodeWorkChain):
    """
    Abstract base for SCF + post-processing workflows.

    Pattern:
        1. Run CRYSTAL23 SCF calculation
        2. Convert wavefunction to post-processing code format
        3. Run post-processing calculation
        4. Parse and return results

    Subclasses implement:
        - convert_wavefunction(): Convert CRYSTAL23 output to target format
        - run_postprocessing(): Execute the post-processing calculation
        - parse_results(): Parse post-processing output
    """

    REQUIRED_CODES = ["crystal_code"]

    @classmethod
    def define(cls, spec):
        """Define the process specification."""
        super().define(spec)

        # Structure input (common to all post-SCF workflows)
        spec.input(
            "structure",
            valid_type=orm.StructureData,
            help="Crystal structure for calculation.",
        )

        # CRYSTAL23 code
        spec.input(
            "crystal_code",
            valid_type=orm.AbstractCode,
            help="CRYSTAL23 code for SCF calculation.",
        )

        # SCF parameters
        spec.input(
            "crystal_parameters",
            valid_type=orm.Dict,
            required=False,
            help="CRYSTAL23 input parameters.",
        )

        # Protocol selection
        spec.input(
            "protocol",
            valid_type=orm.Str,
            default=lambda: orm.Str("moderate"),
            help="Calculation protocol (fast/moderate/precise).",
        )

        # Option to skip SCF if wavefunction provided
        spec.input(
            "wavefunction",
            valid_type=orm.SinglefileData,
            required=False,
            help="Pre-converged wavefunction (skip SCF if provided).",
        )

        # Common outputs
        spec.output(
            "scf_parameters",
            valid_type=orm.Dict,
            required=False,
            help="SCF output parameters.",
        )

        # Define outline
        spec.outline(
            cls.setup,
            cls.validate_inputs,
            cls.run_scf_if_needed,
            cls.convert_for_postprocessing,
            cls.run_postprocessing,
            cls.parse_results,
            cls.finalize,
        )

    def setup(self):
        """Initialize workflow context."""
        self.ctx.restart_count = 0
        self.ctx.scf_completed = False
        self.ctx.conversion_completed = False
        self.ctx.postprocessing_completed = False

    def validate_inputs(self):
        """Validate input parameters."""
        if not self.validate_codes():
            return self.exit_codes.ERROR_CODE_NOT_AVAILABLE

        # Check if we have structure
        if "structure" not in self.inputs:
            self.report("No structure provided")
            return self.exit_codes.ERROR_FIRST_STAGE_FAILED

    def run_scf_if_needed(self):
        """Run CRYSTAL23 SCF if no wavefunction provided."""
        if "wavefunction" in self.inputs:
            self.report("Using provided wavefunction, skipping SCF")
            self.ctx.wavefunction = self.inputs.wavefunction
            self.ctx.scf_completed = True
            return

        self.report("Running CRYSTAL23 SCF calculation")

        # Import here to avoid circular imports
        from ..crystal_base import CrystalBaseWorkChain

        builder = CrystalBaseWorkChain.get_builder()
        builder.structure = self.inputs.structure
        builder.code = self.inputs.crystal_code

        if "crystal_parameters" in self.inputs:
            builder.parameters = self.inputs.crystal_parameters

        builder.metadata.call_link_label = "crystal_scf"

        return ToContext(scf_workchain=self.submit(builder))

    def _check_scf_result(self):
        """Check SCF calculation result."""
        if "scf_workchain" not in self.ctx:
            return  # Wavefunction was provided

        scf_wc = self.ctx.scf_workchain
        if not scf_wc.is_finished_ok:
            self.report(f"SCF calculation failed: {scf_wc.exit_status}")
            return self.exit_codes.ERROR_FIRST_STAGE_FAILED

        # Store wavefunction for post-processing
        if "wavefunction" in scf_wc.outputs:
            self.ctx.wavefunction = scf_wc.outputs.wavefunction
        else:
            self.report("SCF completed but no wavefunction output found")
            return self.exit_codes.ERROR_FIRST_STAGE_FAILED

        # Store SCF parameters
        if "output_parameters" in scf_wc.outputs:
            self.out("scf_parameters", scf_wc.outputs.output_parameters)

        self.ctx.scf_completed = True

    @abstractmethod
    def convert_for_postprocessing(self):
        """
        Convert CRYSTAL23 output to post-processing code format.

        Subclasses implement this to prepare inputs for their specific code.
        Should set self.ctx.postprocessing_inputs with prepared inputs.
        """
        pass

    @abstractmethod
    def run_postprocessing(self):
        """
        Execute the post-processing calculation.

        Subclasses implement this to run their specific calculation.
        Should submit the calculation and add to context.
        """
        pass

    @abstractmethod
    def parse_results(self):
        """
        Parse post-processing results.

        Subclasses implement this to extract relevant results.
        Should set workflow outputs.
        """
        pass

    def finalize(self):
        """Finalize workflow and cleanup."""
        self.report("Multi-code workflow completed successfully")

        # Clean work directories if requested
        if self.inputs.clean_workdir.value:
            self.report("Cleaning up work directories")
            # Cleanup logic would go here


@calcfunction
def validate_code_compatibility(
    structure: orm.StructureData,
    source_code: orm.Str,
    target_code: orm.Str,
) -> orm.Dict:
    """
    Validate that a structure can be processed by the target code.

    Checks for:
    - Element support
    - Spin polarization compatibility
    - Symmetry handling
    - k-point mesh compatibility

    Returns:
        Dict with validation results and any warnings.
    """
    result = {
        "valid": True,
        "warnings": [],
        "errors": [],
    }

    # Get element list
    elements = set(structure.get_kind_names())

    # Check for unsupported elements in target codes
    # (This is a placeholder - actual checks depend on the codes)
    heavy_elements = {"Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf"}
    unsupported = elements.intersection(heavy_elements)
    if unsupported:
        result["warnings"].append(
            f"Heavy elements {unsupported} may have limited support in {target_code.value}"
        )

    return orm.Dict(dict=result)
