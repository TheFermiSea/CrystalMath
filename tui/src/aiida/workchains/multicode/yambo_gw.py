"""
YAMBO GW and BSE WorkChains.

Provides workflows for:
- G0W0 quasi-particle corrections
- BSE (Bethe-Salpeter Equation) for excitonic properties

These workflows chain CRYSTAL23 SCF calculations with YAMBO post-processing.
Requires aiida-yambo plugin for the YAMBO CalcJob.

Example:
    >>> from src.aiida.workchains.multicode import YamboGWWorkChain
    >>>
    >>> builder = YamboGWWorkChain.get_builder()
    >>> builder.structure = structure
    >>> builder.crystal_code = crystal_code
    >>> builder.yambo_code = yambo_code
    >>> builder.gw_parameters = orm.Dict(dict={
    ...     "bands_range": [1, 50],
    ...     "exchange_cutoff": 10.0,
    ... })
    >>> result = engine.run(builder)
    >>> qp_corrections = result["qp_corrections"]
"""

from __future__ import annotations

from aiida import orm
from aiida.engine import ToContext, if_

from .base import PostSCFWorkChain
from .converters import crystal_to_yambo_input, extract_band_edges

# Check for aiida-yambo availability
try:
    from aiida_yambo.workflows.yambo_workflow import YamboWorkflow

    YAMBO_AVAILABLE = True
except ImportError:
    YAMBO_AVAILABLE = False
    YamboWorkflow = None


class YamboGWWorkChain(PostSCFWorkChain):
    """
    GW quasi-particle correction workflow.

    Performs G0W0 calculation on top of CRYSTAL23 SCF wavefunction.

    Workflow Steps:
        1. Run CRYSTAL23 SCF (or use provided wavefunction)
        2. Convert CRYSTAL23 output to YAMBO format
        3. Run YAMBO GW calculation
        4. Extract quasi-particle corrections

    Inputs:
        structure: Crystal structure
        crystal_code: CRYSTAL23 code
        yambo_code: YAMBO code (requires aiida-yambo)
        gw_parameters: GW calculation parameters

    Outputs:
        qp_corrections: Quasi-particle energy corrections
        qp_bandstructure: Corrected band structure
        scf_parameters: CRYSTAL23 SCF results
    """

    REQUIRED_CODES = ["crystal_code", "yambo_code"]

    @classmethod
    def define(cls, spec):
        """Define the process specification."""
        super().define(spec)

        # YAMBO code
        spec.input(
            "yambo_code",
            valid_type=orm.AbstractCode,
            help="YAMBO code for GW calculation.",
        )

        # GW parameters
        spec.input(
            "gw_parameters",
            valid_type=orm.Dict,
            default=lambda: orm.Dict(
                dict={
                    "bands_range": [1, 50],
                    "exchange_cutoff": 10.0,
                    "response_block": 1.0,
                    "type": "gw",
                }
            ),
            help="GW calculation parameters.",
        )

        # K-point mesh for GW (can be different from SCF)
        spec.input(
            "gw_kpoints",
            valid_type=orm.KpointsData,
            required=False,
            help="K-point mesh for GW calculation.",
        )

        # Outputs
        spec.output(
            "qp_corrections",
            valid_type=orm.Dict,
            help="Quasi-particle energy corrections.",
        )
        spec.output(
            "qp_bandstructure",
            valid_type=orm.BandsData,
            required=False,
            help="Quasi-particle corrected band structure.",
        )
        spec.output(
            "band_edges",
            valid_type=orm.Dict,
            required=False,
            help="Band edge information (VBM, CBM, gap).",
        )

        # Exit codes
        spec.exit_code(
            310,
            "ERROR_YAMBO_NOT_AVAILABLE",
            message="aiida-yambo plugin is not installed.",
        )
        spec.exit_code(
            311,
            "ERROR_GW_CALCULATION_FAILED",
            message="YAMBO GW calculation failed.",
        )
        spec.exit_code(
            312,
            "ERROR_QP_PARSING_FAILED",
            message="Failed to parse quasi-particle results.",
        )

    def validate_inputs(self):
        """Validate inputs including YAMBO availability."""
        result = super().validate_inputs()
        if result:
            return result

        if not YAMBO_AVAILABLE:
            self.report("aiida-yambo plugin not installed. Install with: pip install aiida-yambo")
            return self.exit_codes.ERROR_YAMBO_NOT_AVAILABLE

    def convert_for_postprocessing(self):
        """Convert CRYSTAL23 output to YAMBO format."""
        result = self._check_scf_result()
        if result:
            return result

        self.report("Preparing YAMBO GW input from CRYSTAL23 output")

        # Get SCF parameters
        if "scf_workchain" in self.ctx:
            scf_params = self.ctx.scf_workchain.outputs.output_parameters
        else:
            # Create minimal params if wavefunction was provided directly
            scf_params = orm.Dict(dict={"n_electrons": 0, "n_bands": 0})

        # Extract band edges for energy window determination
        band_edges = extract_band_edges(scf_params)
        self.out("band_edges", band_edges)

        # Generate YAMBO input
        yambo_input = crystal_to_yambo_input(
            crystal_parameters=scf_params,
            gw_parameters=self.inputs.gw_parameters,
            structure=self.inputs.structure,
        )

        self.ctx.yambo_input = yambo_input
        self.ctx.conversion_completed = True

    def run_postprocessing(self):
        """Run YAMBO GW calculation."""
        if not self.ctx.conversion_completed:
            return self.exit_codes.ERROR_CONVERSION_FAILED

        self.report("Submitting YAMBO GW calculation")

        if not YAMBO_AVAILABLE:
            # Simulation mode for testing without aiida-yambo
            self.report("YAMBO not available - returning simulated results")
            self.ctx.gw_result = self._simulate_gw_result()
            return

        # Build YAMBO workflow using aiida-yambo
        builder = YamboWorkflow.get_builder()
        builder.yambo.yambo.code = self.inputs.yambo_code

        # Set up YAMBO inputs from converted parameters
        yambo_params = self.ctx.yambo_input.get_dict()

        # Configure runlevels
        builder.workflow_settings = orm.Dict(
            dict={
                "type": "GW",
                "gwp1_conv": False,
                "qp_correction": True,
            }
        )

        # K-point mesh
        if "gw_kpoints" in self.inputs:
            builder.kpoints = self.inputs.gw_kpoints

        builder.metadata.call_link_label = "yambo_gw"

        return ToContext(gw_workchain=self.submit(builder))

    def _simulate_gw_result(self) -> orm.Dict:
        """Create simulated GW result for testing."""
        return orm.Dict(
            dict={
                "status": "simulated",
                "message": "YAMBO not available - simulated result",
                "qp_corrections": {
                    "vbm_correction_ev": 0.5,
                    "cbm_correction_ev": 0.3,
                    "gap_correction_ev": 0.2,
                },
            }
        )

    def parse_results(self):
        """Parse YAMBO GW results."""
        if not YAMBO_AVAILABLE and hasattr(self.ctx, "gw_result"):
            # Simulated result
            self.out("qp_corrections", self.ctx.gw_result)
            return

        gw_wc = self.ctx.gw_workchain
        if not gw_wc.is_finished_ok:
            self.report(f"GW calculation failed: {gw_wc.exit_status}")
            return self.exit_codes.ERROR_GW_CALCULATION_FAILED

        # Extract quasi-particle corrections
        if "output_parameters" in gw_wc.outputs:
            qp_params = gw_wc.outputs.output_parameters.get_dict()

            # Structure QP corrections
            qp_corrections = {
                "source": "yambo_gw",
                "method": "G0W0",
            }

            # Add available QP data
            for key in [
                "gap_GW",
                "gap_DFT",
                "homo_GW",
                "homo_DFT",
                "lumo_GW",
                "lumo_DFT",
            ]:
                if key in qp_params:
                    qp_corrections[key] = qp_params[key]

            self.out("qp_corrections", orm.Dict(dict=qp_corrections))
        else:
            return self.exit_codes.ERROR_QP_PARSING_FAILED

        # Extract QP-corrected band structure if available
        if "bands" in gw_wc.outputs:
            self.out("qp_bandstructure", gw_wc.outputs.bands)

        self.ctx.postprocessing_completed = True


class YamboBSEWorkChain(PostSCFWorkChain):
    """
    BSE (Bethe-Salpeter Equation) workflow for excitonic properties.

    Performs BSE calculation on top of GW quasi-particle energies.
    Can optionally skip GW and use scissor operator.

    Workflow Steps:
        1. Run CRYSTAL23 SCF (or use provided wavefunction)
        2. Optionally run GW for quasi-particle corrections
        3. Run BSE calculation
        4. Extract excitonic properties (binding energy, optical spectrum)

    Inputs:
        structure: Crystal structure
        crystal_code: CRYSTAL23 code
        yambo_code: YAMBO code
        bse_parameters: BSE calculation parameters
        do_gw: Whether to do GW before BSE (default: True)

    Outputs:
        excitons: Excitonic states and binding energies
        optical_spectrum: Optical absorption spectrum
        qp_corrections: GW corrections (if do_gw=True)
    """

    REQUIRED_CODES = ["crystal_code", "yambo_code"]

    @classmethod
    def define(cls, spec):
        """Define the process specification."""
        super().define(spec)

        # YAMBO code
        spec.input(
            "yambo_code",
            valid_type=orm.AbstractCode,
            help="YAMBO code for BSE calculation.",
        )

        # BSE parameters
        spec.input(
            "bse_parameters",
            valid_type=orm.Dict,
            default=lambda: orm.Dict(
                dict={
                    "type": "bse",
                    "bse_bands": [1, 20],
                    "energy_steps": 100,
                    "energy_range": [0.0, 10.0],
                }
            ),
            help="BSE calculation parameters.",
        )

        # Whether to do GW first
        spec.input(
            "do_gw",
            valid_type=orm.Bool,
            default=lambda: orm.Bool(True),
            help="Run GW calculation before BSE.",
        )

        # Scissor operator (alternative to GW)
        spec.input(
            "scissor_ev",
            valid_type=orm.Float,
            required=False,
            help="Scissor operator in eV (if not doing GW).",
        )

        # Outputs
        spec.output(
            "excitons",
            valid_type=orm.Dict,
            help="Excitonic states and binding energies.",
        )
        spec.output(
            "optical_spectrum",
            valid_type=orm.XyData,
            required=False,
            help="Optical absorption spectrum.",
        )
        spec.output(
            "qp_corrections",
            valid_type=orm.Dict,
            required=False,
            help="GW quasi-particle corrections.",
        )

        # Exit codes
        spec.exit_code(
            320,
            "ERROR_BSE_CALCULATION_FAILED",
            message="YAMBO BSE calculation failed.",
        )
        spec.exit_code(
            321,
            "ERROR_EXCITON_PARSING_FAILED",
            message="Failed to parse excitonic results.",
        )

        # Modify outline for optional GW step
        spec.outline(
            cls.setup,
            cls.validate_inputs,
            cls.run_scf_if_needed,
            if_(cls.should_do_gw)(
                cls.run_gw,
            ),
            cls.convert_for_postprocessing,
            cls.run_postprocessing,
            cls.parse_results,
            cls.finalize,
        )

    def should_do_gw(self):
        """Check if GW calculation should be performed."""
        return self.inputs.do_gw.value

    def run_gw(self):
        """Run GW calculation before BSE."""
        self.report("Running GW calculation before BSE")

        # Create and submit YamboGWWorkChain
        builder = YamboGWWorkChain.get_builder()
        builder.structure = self.inputs.structure
        builder.crystal_code = self.inputs.crystal_code
        builder.yambo_code = self.inputs.yambo_code

        if "wavefunction" in self.inputs:
            builder.wavefunction = self.inputs.wavefunction

        builder.gw_parameters = orm.Dict(dict={"type": "gw"})
        builder.metadata.call_link_label = "gw_for_bse"

        return ToContext(gw_workchain=self.submit(builder))

    def convert_for_postprocessing(self):
        """Convert for BSE calculation."""
        result = self._check_scf_result()
        if result:
            return result

        self.report("Preparing YAMBO BSE input")

        # Get SCF or GW parameters
        if hasattr(self.ctx, "gw_workchain") and self.ctx.gw_workchain.is_finished_ok:
            if "qp_corrections" in self.ctx.gw_workchain.outputs:
                self.out("qp_corrections", self.ctx.gw_workchain.outputs.qp_corrections)

        # Get SCF parameters
        if "scf_workchain" in self.ctx:
            scf_params = self.ctx.scf_workchain.outputs.output_parameters
        else:
            scf_params = orm.Dict(dict={})

        # Generate YAMBO BSE input
        yambo_input = crystal_to_yambo_input(
            crystal_parameters=scf_params,
            gw_parameters=self.inputs.bse_parameters,
            structure=self.inputs.structure,
        )

        self.ctx.yambo_input = yambo_input
        self.ctx.conversion_completed = True

    def run_postprocessing(self):
        """Run YAMBO BSE calculation."""
        if not self.ctx.conversion_completed:
            return self.exit_codes.ERROR_CONVERSION_FAILED

        self.report("Submitting YAMBO BSE calculation")

        if not YAMBO_AVAILABLE:
            self.report("YAMBO not available - returning simulated results")
            self.ctx.bse_result = self._simulate_bse_result()
            return

        # Build YAMBO BSE workflow
        builder = YamboWorkflow.get_builder()
        builder.yambo.yambo.code = self.inputs.yambo_code

        builder.workflow_settings = orm.Dict(
            dict={
                "type": "BSE",
                "bse_kernel": True,
                "absorption": True,
            }
        )

        # Apply scissor if not doing GW
        if not self.inputs.do_gw.value and "scissor_ev" in self.inputs:
            builder.additional_parameters = orm.Dict(dict={"SCISSOR": self.inputs.scissor_ev.value})

        builder.metadata.call_link_label = "yambo_bse"

        return ToContext(bse_workchain=self.submit(builder))

    def _simulate_bse_result(self) -> orm.Dict:
        """Create simulated BSE result for testing."""
        return orm.Dict(
            dict={
                "status": "simulated",
                "message": "YAMBO not available - simulated result",
                "excitons": [
                    {"energy_ev": 1.5, "binding_ev": 0.3, "oscillator_strength": 0.8},
                    {"energy_ev": 2.0, "binding_ev": 0.2, "oscillator_strength": 0.4},
                ],
            }
        )

    def parse_results(self):
        """Parse YAMBO BSE results."""
        if not YAMBO_AVAILABLE and hasattr(self.ctx, "bse_result"):
            self.out("excitons", self.ctx.bse_result)
            return

        bse_wc = self.ctx.bse_workchain
        if not bse_wc.is_finished_ok:
            self.report(f"BSE calculation failed: {bse_wc.exit_status}")
            return self.exit_codes.ERROR_BSE_CALCULATION_FAILED

        # Extract excitonic properties
        if "output_parameters" in bse_wc.outputs:
            bse_params = bse_wc.outputs.output_parameters.get_dict()

            excitons = {
                "source": "yambo_bse",
                "n_excitons": bse_params.get("n_excitons", 0),
                "lowest_exciton_ev": bse_params.get("lowest_exciton_ev"),
                "optical_gap_ev": bse_params.get("optical_gap_ev"),
                "exciton_binding_ev": bse_params.get("exciton_binding_ev"),
            }

            self.out("excitons", orm.Dict(dict=excitons))
        else:
            return self.exit_codes.ERROR_EXCITON_PARSING_FAILED

        # Extract optical spectrum if available
        if "absorption" in bse_wc.outputs:
            self.out("optical_spectrum", bse_wc.outputs.absorption)

        self.ctx.postprocessing_completed = True
