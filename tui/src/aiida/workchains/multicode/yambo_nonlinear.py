"""
YAMBO Nonlinear Optics WorkChain.

Provides workflow for calculating nonlinear optical properties:
- Second-harmonic generation (SHG)
- Third-harmonic generation (THG)
- Optical Kerr effect
- Two-photon absorption

Uses YAMBO's real-time TDDFT approach for nonlinear response.

Example:
    >>> from src.aiida.workchains.multicode import YamboNonlinearWorkChain
    >>>
    >>> builder = YamboNonlinearWorkChain.get_builder()
    >>> builder.structure = structure
    >>> builder.crystal_code = crystal_code
    >>> builder.yambo_code = yambo_code
    >>> builder.nl_parameters = orm.Dict(dict={
    ...     "response_order": 2,  # SHG
    ...     "field_intensity": 1e5,
    ...     "field_direction": [1, 0, 0],
    ... })
    >>> result = engine.run(builder)
    >>> chi2 = result["nonlinear_susceptibility"]
"""

from __future__ import annotations

from typing import ClassVar

from aiida import orm
from aiida.engine import ToContext, calcfunction

from .base import PostSCFWorkChain
from .converters import crystal_to_yambo_input

# Check for aiida-yambo availability
try:
    from aiida_yambo.workflows.yambo_workflow import YamboWorkflow

    YAMBO_AVAILABLE = True
except ImportError:
    YAMBO_AVAILABLE = False
    YamboWorkflow = None


class YamboNonlinearWorkChain(PostSCFWorkChain):
    """
    Nonlinear optical response workflow using YAMBO.

    Calculates nonlinear optical susceptibilities using real-time TDDFT
    approach implemented in YAMBO.

    Workflow Steps:
        1. Run CRYSTAL23 SCF (or use provided wavefunction)
        2. Optionally run GW for improved band structure
        3. Run YAMBO nonlinear optics calculation
        4. Extract nonlinear susceptibilities

    Supported Nonlinear Processes:
        - χ⁽²⁾: Second-order susceptibility (SHG, OR, etc.)
        - χ⁽³⁾: Third-order susceptibility (THG, Kerr, TPA, etc.)

    Inputs:
        structure: Crystal structure
        crystal_code: CRYSTAL23 code
        yambo_code: YAMBO code
        nl_parameters: Nonlinear optics parameters

    Outputs:
        nonlinear_susceptibility: Frequency-dependent χ⁽ⁿ⁾
        polarization_dynamics: Time-dependent polarization
        optical_response: Linear/nonlinear optical spectra
    """

    REQUIRED_CODES: ClassVar[list[str]] = ["crystal_code", "yambo_code"]

    @classmethod
    def define(cls, spec):
        """Define the process specification."""
        super().define(spec)

        # YAMBO code
        spec.input(
            "yambo_code",
            valid_type=orm.AbstractCode,
            help="YAMBO code for nonlinear optics calculation.",
        )

        # Nonlinear parameters
        spec.input(
            "nl_parameters",
            valid_type=orm.Dict,
            default=lambda: orm.Dict(
                dict={
                    "type": "nonlinear",
                    "response_order": 2,  # 2=SHG, 3=THG
                    "field_intensity": 1e5,  # V/cm
                    "field_direction": [1, 0, 0],
                    "field_kind": "DELTA",  # DELTA, SIN, ANTIRES
                    "nl_time": [-1, 100],  # Time steps [fs]
                    "damping": 0.1,  # Dephasing [eV]
                    "correlation": "SEX",  # IPA, RPA, SEX, etc.
                }
            ),
            help="Nonlinear optics calculation parameters.",
        )

        # Energy range for spectral analysis
        spec.input(
            "energy_range",
            valid_type=orm.List,
            default=lambda: orm.List(list=[0.0, 5.0]),
            help="Energy range for susceptibility [eV].",
        )

        # Include GW corrections
        spec.input(
            "include_gw",
            valid_type=orm.Bool,
            default=lambda: orm.Bool(False),
            help="Include GW corrections before nonlinear calculation.",
        )

        # Outputs
        spec.output(
            "nonlinear_susceptibility",
            valid_type=orm.Dict,
            help="Nonlinear optical susceptibility χ⁽ⁿ⁾.",
        )
        spec.output(
            "polarization_dynamics",
            valid_type=orm.XyData,
            required=False,
            help="Time-dependent polarization P(t).",
        )
        spec.output(
            "optical_response",
            valid_type=orm.XyData,
            required=False,
            help="Linear/nonlinear optical spectrum.",
        )
        spec.output(
            "tensor_components",
            valid_type=orm.Dict,
            required=False,
            help="Individual tensor components of χ⁽ⁿ⁾.",
        )

        # Exit codes
        spec.exit_code(
            330,
            "ERROR_YAMBO_NOT_AVAILABLE",
            message="aiida-yambo plugin is not installed.",
        )
        spec.exit_code(
            331,
            "ERROR_NONLINEAR_CALCULATION_FAILED",
            message="YAMBO nonlinear optics calculation failed.",
        )
        spec.exit_code(
            332,
            "ERROR_SUSCEPTIBILITY_PARSING_FAILED",
            message="Failed to parse nonlinear susceptibility.",
        )
        spec.exit_code(
            333,
            "ERROR_INVALID_RESPONSE_ORDER",
            message="Invalid nonlinear response order (must be 2 or 3).",
        )

    def validate_inputs(self):
        """Validate inputs."""
        result = super().validate_inputs()
        if result:
            return result

        if not YAMBO_AVAILABLE:
            self.report("aiida-yambo plugin not installed. Install with: pip install aiida-yambo")
            return self.exit_codes.ERROR_YAMBO_NOT_AVAILABLE

        # Validate response order
        nl_params = self.inputs.nl_parameters.get_dict()
        response_order = nl_params.get("response_order", 2)
        if response_order not in [2, 3]:
            self.report(f"Invalid response order: {response_order}")
            return self.exit_codes.ERROR_INVALID_RESPONSE_ORDER

    def convert_for_postprocessing(self):
        """Convert CRYSTAL23 output for YAMBO nonlinear calculation."""
        result = self._check_scf_result()
        if result:
            return result

        self.report("Preparing YAMBO nonlinear optics input")

        # Get SCF parameters
        if "scf_workchain" in self.ctx:
            scf_params = self.ctx.scf_workchain.outputs.output_parameters
        else:
            scf_params = orm.Dict(dict={})

        # Generate YAMBO input for nonlinear calculation
        yambo_input = crystal_to_yambo_input(
            crystal_parameters=scf_params,
            gw_parameters=self.inputs.nl_parameters,
            structure=self.inputs.structure,
        )

        self.ctx.yambo_input = yambo_input
        self.ctx.conversion_completed = True

    def run_postprocessing(self):
        """Run YAMBO nonlinear optics calculation."""
        if not self.ctx.conversion_completed:
            return self.exit_codes.ERROR_CONVERSION_FAILED

        self.report("Submitting YAMBO nonlinear optics calculation")

        if not YAMBO_AVAILABLE:
            self.report("YAMBO not available - returning simulated results")
            self.ctx.nl_result = self._simulate_nl_result()
            return

        # Get nonlinear parameters
        nl_params = self.inputs.nl_parameters.get_dict()

        # Build YAMBO workflow
        builder = YamboWorkflow.get_builder()
        builder.yambo.yambo.code = self.inputs.yambo_code

        # Configure for nonlinear calculation
        builder.workflow_settings = orm.Dict(
            dict={
                "type": "NL",  # Nonlinear optics
            }
        )

        # Set up nonlinear-specific parameters
        nl_settings = {
            "NLverbosity": "high",
            "NLtime": nl_params.get("nl_time", [-1, 100]),
            "NLintegrator": "INVINT",
            "NLCorrelation": nl_params.get("correlation", "SEX"),
            "NLDamping": nl_params.get("damping", 0.1),
            "Field1_Int": nl_params.get("field_intensity", 1e5),
            "Field1_Dir": nl_params.get("field_direction", [1, 0, 0]),
            "Field1_kind": nl_params.get("field_kind", "DELTA"),
        }

        # Response order determines which susceptibility
        response_order = nl_params.get("response_order", 2)
        if response_order == 2:
            nl_settings["NL2nd"] = True
        elif response_order == 3:
            nl_settings["NL3rd"] = True

        builder.additional_parameters = orm.Dict(dict=nl_settings)
        builder.metadata.call_link_label = "yambo_nl"

        return ToContext(nl_workchain=self.submit(builder))

    def _simulate_nl_result(self) -> orm.Dict:
        """Create simulated nonlinear result for testing."""
        nl_params = self.inputs.nl_parameters.get_dict()
        response_order = nl_params.get("response_order", 2)

        if response_order == 2:
            return orm.Dict(
                dict={
                    "status": "simulated",
                    "message": "YAMBO not available - simulated result",
                    "response_order": 2,
                    "chi2_xyz": {
                        "magnitude_pm_V": 10.5,
                        "phase_deg": 45.0,
                    },
                    "shg_intensity": 1.5e-6,
                }
            )
        else:
            return orm.Dict(
                dict={
                    "status": "simulated",
                    "message": "YAMBO not available - simulated result",
                    "response_order": 3,
                    "chi3_xxxx": {
                        "magnitude_esu": 1.2e-12,
                    },
                    "n2_cm2_W": 3.5e-16,
                }
            )

    def parse_results(self):
        """Parse YAMBO nonlinear results."""
        if not YAMBO_AVAILABLE and hasattr(self.ctx, "nl_result"):
            self.out("nonlinear_susceptibility", self.ctx.nl_result)
            return

        nl_wc = self.ctx.nl_workchain
        if not nl_wc.is_finished_ok:
            self.report(f"Nonlinear calculation failed: {nl_wc.exit_status}")
            return self.exit_codes.ERROR_NONLINEAR_CALCULATION_FAILED

        # Extract nonlinear susceptibility
        if "output_parameters" in nl_wc.outputs:
            nl_params = nl_wc.outputs.output_parameters.get_dict()
            response_order = self.inputs.nl_parameters.get_dict().get("response_order", 2)

            susceptibility = {
                "source": "yambo_nl",
                "response_order": response_order,
            }

            # Second-order (χ²)
            if response_order == 2:
                susceptibility["type"] = "chi2"
                susceptibility["unit"] = "pm/V"
                # Extract tensor components
                for comp in ["xxx", "xyy", "xzz", "xyz", "xzy", "yxx", "yxy", "yxz"]:
                    key = f"chi2_{comp}"
                    if key in nl_params:
                        susceptibility[key] = nl_params[key]

            # Third-order (χ³)
            elif response_order == 3:
                susceptibility["type"] = "chi3"
                susceptibility["unit"] = "esu"
                # Extract tensor components
                for comp in ["xxxx", "xxyy", "xyxy", "xyyx"]:
                    key = f"chi3_{comp}"
                    if key in nl_params:
                        susceptibility[key] = nl_params[key]

                # Derive nonlinear refractive index
                if "n2" in nl_params:
                    susceptibility["n2_cm2_W"] = nl_params["n2"]

            self.out("nonlinear_susceptibility", orm.Dict(dict=susceptibility))

            # Store individual tensor components
            tensor_components = {
                k: v for k, v in nl_params.items() if k.startswith("chi2_") or k.startswith("chi3_")
            }
            if tensor_components:
                self.out("tensor_components", orm.Dict(dict=tensor_components))
        else:
            return self.exit_codes.ERROR_SUSCEPTIBILITY_PARSING_FAILED

        # Extract polarization dynamics if available
        if "polarization" in nl_wc.outputs:
            self.out("polarization_dynamics", nl_wc.outputs.polarization)

        # Extract optical spectrum if available
        if "spectrum" in nl_wc.outputs:
            self.out("optical_response", nl_wc.outputs.spectrum)

        self.ctx.postprocessing_completed = True


@calcfunction
def analyze_shg_symmetry(
    structure: orm.StructureData,
    susceptibility: orm.Dict,
) -> orm.Dict:
    """
    Analyze SHG susceptibility based on crystal symmetry.

    Determines which tensor components are allowed by symmetry
    and identifies the crystal class and point group.

    Args:
        structure: Crystal structure.
        susceptibility: Calculated χ² tensor.

    Returns:
        Dict with symmetry analysis results.
    """
    # This is a placeholder for symmetry analysis
    # Full implementation would use spglib or similar

    analysis = {
        "centrosymmetric": False,  # SHG requires non-centrosymmetric
        "allowed_components": [],
        "point_group": "unknown",
        "crystal_class": "unknown",
    }

    # Non-zero components suggest non-centrosymmetric structure
    chi2 = susceptibility.get_dict()
    nonzero = [k for k in chi2 if k.startswith("chi2_") and abs(chi2[k]) > 1e-10]
    if nonzero:
        analysis["allowed_components"] = nonzero
        analysis["centrosymmetric"] = False
    else:
        analysis["centrosymmetric"] = True

    return orm.Dict(dict=analysis)
