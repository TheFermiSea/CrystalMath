"""
Converters for multi-code workflows.

Transforms CRYSTAL23 output to formats compatible with external codes:
- YAMBO (GW, BSE, nonlinear optics)
- BerkeleyGW (GW, BSE)
- Wannier90 (maximally-localized Wannier functions)

These converters handle:
- Wavefunction format conversion
- k-point mesh transformation
- Band structure data mapping
- Structural data conversion
"""

from __future__ import annotations

from aiida import orm
from aiida.engine import calcfunction

# numpy is optional - used for Wannier90 conversion
try:
    import numpy as np

    NUMPY_AVAILABLE = True
except ImportError:
    np = None
    NUMPY_AVAILABLE = False


@calcfunction
def crystal_to_qe_wavefunction(
    crystal_wavefunction: orm.SinglefileData,
    structure: orm.StructureData,
    parameters: orm.Dict,
) -> orm.Dict:
    """
    Convert CRYSTAL23 wavefunction to Quantum ESPRESSO-compatible format.

    YAMBO typically uses QE wavefunctions as input. This converter
    extracts the necessary information from CRYSTAL23 fort.9/fort.98
    files and prepares them for YAMBO.

    Note:
        Full wavefunction conversion requires running p2y (YAMBO utility)
        or using the CRYSTAL23 output to generate QE-compatible files.
        This function prepares the metadata needed for that conversion.

    Args:
        crystal_wavefunction: CRYSTAL23 wavefunction file (fort.9).
        structure: Crystal structure.
        parameters: CRYSTAL23 output parameters.

    Returns:
        Dict with conversion metadata and paths.
    """
    params = parameters.get_dict()

    # Extract electronic structure info from CRYSTAL23 output
    conversion_info = {
        "source_format": "crystal23",
        "target_format": "qe",
        "n_electrons": params.get("n_electrons", 0),
        "n_bands": params.get("n_bands", 0),
        "spin_polarized": params.get("spin_polarized", False),
        "fermi_energy_ev": params.get("fermi_energy_ev"),
        "band_gap_ev": params.get("band_gap_ev"),
        "n_kpoints": params.get("n_kpoints", 0),
        "needs_p2y": True,  # YAMBO's p2y needed for full conversion
        "status": "metadata_prepared",
    }

    # Lattice parameters for conversion
    cell = structure.cell
    conversion_info["cell_parameters"] = [list(v) for v in cell]

    return orm.Dict(dict=conversion_info)


@calcfunction
def crystal_to_yambo_input(
    crystal_parameters: orm.Dict,
    gw_parameters: orm.Dict,
    structure: orm.StructureData,
) -> orm.Dict:
    """
    Generate YAMBO input parameters from CRYSTAL23 output.

    Creates YAMBO input configuration based on CRYSTAL23 electronic
    structure results and requested GW/BSE parameters.

    Args:
        crystal_parameters: CRYSTAL23 output parameters.
        gw_parameters: GW/BSE calculation parameters.
        structure: Crystal structure.

    Returns:
        Dict with YAMBO input configuration.
    """
    crystal_params = crystal_parameters.get_dict()
    gw_params = gw_parameters.get_dict()

    # Determine calculation type
    calc_type = gw_params.get("type", "gw")  # gw, bse, or nonlinear

    # Base YAMBO parameters
    yambo_input = {
        "type": calc_type,
        "runlevels": [],
        "parameters": {},
    }

    # GW-specific parameters
    if calc_type in ["gw", "bse"]:
        # Set appropriate runlevels
        yambo_input["runlevels"] = ["em1d", "ppa", "HF_and_locXC", "gw0"]

        # Energy cutoffs (converted from CRYSTAL23 basis)
        yambo_input["parameters"]["EXXRLvcs"] = gw_params.get("exchange_cutoff", 10.0)
        yambo_input["parameters"]["BndsRnXp"] = gw_params.get("bands_range", [1, 50])
        yambo_input["parameters"]["NGsBlkXp"] = gw_params.get("response_block", 1.0)

        # GW self-energy parameters
        yambo_input["parameters"]["GWoIter"] = 1  # One-shot G0W0
        yambo_input["parameters"]["GTermKind"] = "BG"  # Bruneval-Gonze terminator

        # Use CRYSTAL23 gap as starting point
        if "band_gap_ev" in crystal_params:
            yambo_input["parameters"]["initial_gap_ev"] = crystal_params["band_gap_ev"]

    # BSE-specific parameters
    if calc_type == "bse":
        yambo_input["runlevels"].extend(["optics", "bse", "bsk"])

        # BSE kernel parameters
        yambo_input["parameters"]["BSEBands"] = gw_params.get("bse_bands", [1, 20])
        yambo_input["parameters"]["BEnSteps"] = gw_params.get("energy_steps", 100)
        yambo_input["parameters"]["BEnRange"] = gw_params.get("energy_range", [0.0, 10.0])

    # Nonlinear optics parameters
    if calc_type == "nonlinear":
        yambo_input["runlevels"] = ["em1d", "ppa", "HF_and_locXC", "gw0", "nl"]

        # Nonlinear response parameters
        yambo_input["parameters"]["NLverbosity"] = "high"
        yambo_input["parameters"]["NLtime"] = gw_params.get("nl_time", [-1, 100])
        yambo_input["parameters"]["NLintegrator"] = gw_params.get("integrator", "INVINT")
        yambo_input["parameters"]["NLCorrelation"] = gw_params.get("correlation", "SEX")
        yambo_input["parameters"]["NLDamping"] = gw_params.get("damping", 0.1)

        # Field parameters
        yambo_input["parameters"]["Field1_Int"] = gw_params.get("field_intensity", 1e5)
        yambo_input["parameters"]["Field1_Dir"] = gw_params.get("field_direction", [1, 0, 0])
        yambo_input["parameters"]["Field1_kind"] = gw_params.get("field_kind", "DELTA")

    # k-point mesh info from CRYSTAL23
    if "n_kpoints" in crystal_params:
        yambo_input["parameters"]["source_nk"] = crystal_params["n_kpoints"]

    # Spin polarization
    if crystal_params.get("spin_polarized", False):
        yambo_input["parameters"]["SpnPol"] = "collinear"

    return orm.Dict(dict=yambo_input)


@calcfunction
def crystal_bands_to_wannier90(
    bands: orm.BandsData,
    structure: orm.StructureData,
    wannier_parameters: orm.Dict,
) -> orm.Dict:
    """
    Prepare Wannier90 input from CRYSTAL23 band structure.

    Creates input for Wannier90 maximally-localized Wannier function
    calculation based on CRYSTAL23 band structure data.

    Args:
        bands: CRYSTAL23 band structure (BandsData).
        structure: Crystal structure.
        wannier_parameters: Wannier90 parameters.

    Returns:
        Dict with Wannier90 input configuration.

    Note:
        Requires numpy for coordinate conversion.
    """
    if not NUMPY_AVAILABLE:
        return orm.Dict(
            dict={
                "error": "numpy not available",
                "message": "Install numpy for Wannier90 conversion",
            }
        )

    wannier_params = wannier_parameters.get_dict()

    # Get band structure info
    band_kpoints = bands.get_kpoints()
    band_data = bands.get_bands()

    n_bands = band_data.shape[0] if len(band_data.shape) == 2 else band_data.shape[1]

    # Wannier90 input structure
    w90_input = {
        "num_bands": n_bands,
        "num_wann": wannier_params.get("num_wann", n_bands // 2),
        "unit_cell_cart": [list(v) for v in structure.cell],
        "atoms_frac": [],
        "projections": [],
        "kpoints": [],
        "mp_grid": wannier_params.get("mp_grid", [4, 4, 4]),
    }

    # Add atomic positions
    for site in structure.sites:
        # Convert to fractional coordinates
        cart = site.position
        frac = np.linalg.solve(np.array(structure.cell).T, cart)
        w90_input["atoms_frac"].append(
            {
                "symbol": site.kind_name,
                "position": list(frac),
            }
        )

    # Set up projections based on element types
    # Default: use atomic orbitals as initial projections
    for kind in structure.get_kind_names():
        # Default projections - can be customized
        w90_input["projections"].append(
            {
                "site": kind,
                "orbital": wannier_params.get("projection_type", "random"),
            }
        )

    # Energy windows
    if "dis_froz_min" in wannier_params:
        w90_input["dis_froz_min"] = wannier_params["dis_froz_min"]
    if "dis_froz_max" in wannier_params:
        w90_input["dis_froz_max"] = wannier_params["dis_froz_max"]
    if "dis_win_min" in wannier_params:
        w90_input["dis_win_min"] = wannier_params["dis_win_min"]
    if "dis_win_max" in wannier_params:
        w90_input["dis_win_max"] = wannier_params["dis_win_max"]

    # Disentanglement parameters
    w90_input["dis_num_iter"] = wannier_params.get("dis_num_iter", 200)
    w90_input["num_iter"] = wannier_params.get("num_iter", 100)

    # Output options
    w90_input["write_hr"] = wannier_params.get("write_hr", True)
    w90_input["bands_plot"] = wannier_params.get("bands_plot", True)
    w90_input["wannier_plot"] = wannier_params.get("wannier_plot", False)

    return orm.Dict(dict=w90_input)


@calcfunction
def crystal_to_berkeleygw(
    crystal_parameters: orm.Dict,
    structure: orm.StructureData,
    gw_parameters: orm.Dict,
) -> orm.Dict:
    """
    Generate BerkeleyGW input from CRYSTAL23 output.

    Creates BerkeleyGW input configuration based on CRYSTAL23 electronic
    structure results.

    Args:
        crystal_parameters: CRYSTAL23 output parameters.
        structure: Crystal structure.
        gw_parameters: GW calculation parameters.

    Returns:
        Dict with BerkeleyGW input configuration.
    """
    crystal_params = crystal_parameters.get_dict()
    gw_params = gw_parameters.get_dict()

    # BerkeleyGW input structure
    bgw_input = {
        "epsilon": {},
        "sigma": {},
        "kernel": {},
        "absorption": {},
    }

    # Epsilon (dielectric screening) parameters
    bgw_input["epsilon"] = {
        "number_bands": gw_params.get("epsilon_bands", 100),
        "cutoff": gw_params.get("epsilon_cutoff", 10.0),
        "frequency_dependence": gw_params.get("freq_dep", 0),  # 0=static, 2=full
        "frequency_low_cutoff": gw_params.get("freq_low_cutoff", 0.0),
        "frequency_high_cutoff": gw_params.get("freq_high_cutoff", 100.0),
    }

    # Sigma (self-energy) parameters
    bgw_input["sigma"] = {
        "number_bands": gw_params.get("sigma_bands", 50),
        "screened_coulomb_cutoff": gw_params.get("screened_cutoff", 10.0),
        "bare_coulomb_cutoff": gw_params.get("bare_cutoff", 60.0),
        "band_index_min": gw_params.get("band_min", 1),
        "band_index_max": gw_params.get("band_max", 20),
    }

    # Use CRYSTAL23 Fermi energy if available
    if "fermi_energy_ev" in crystal_params:
        bgw_input["sigma"]["fermi_level"] = crystal_params["fermi_energy_ev"]

    # BSE parameters (if doing BSE)
    if gw_params.get("do_bse", False):
        bgw_input["kernel"] = {
            "number_val_bands": gw_params.get("kernel_val_bands", 4),
            "number_cond_bands": gw_params.get("kernel_cond_bands", 4),
            "screened_coulomb_cutoff": gw_params.get("kernel_cutoff", 10.0),
        }

        bgw_input["absorption"] = {
            "number_val_bands_coarse": gw_params.get("abs_val_bands", 4),
            "number_cond_bands_coarse": gw_params.get("abs_cond_bands", 4),
            "energy_resolution": gw_params.get("energy_resolution", 0.05),
            "gaussian_broadening": gw_params.get("broadening", 0.1),
        }

    # k-point info from CRYSTAL23
    if "n_kpoints" in crystal_params:
        bgw_input["source_nkpts"] = crystal_params["n_kpoints"]

    return orm.Dict(dict=bgw_input)


@calcfunction
def extract_band_edges(
    crystal_parameters: orm.Dict,
) -> orm.Dict:
    """
    Extract band edge information for GW/BSE calculations.

    Identifies valence band maximum (VBM), conduction band minimum (CBM),
    and related information needed for setting up excited-state calculations.

    Args:
        crystal_parameters: CRYSTAL23 output parameters.

    Returns:
        Dict with band edge information.
    """
    params = crystal_parameters.get_dict()

    band_edges = {
        "fermi_energy_ev": params.get("fermi_energy_ev"),
        "band_gap_ev": params.get("band_gap_ev", 0.0),
        "gap_type": params.get("gap_type", "unknown"),  # direct or indirect
        "is_metal": params.get("band_gap_ev", 0.0) < 0.01,
    }

    # VBM and CBM if available
    if "vbm_ev" in params:
        band_edges["vbm_ev"] = params["vbm_ev"]
    if "cbm_ev" in params:
        band_edges["cbm_ev"] = params["cbm_ev"]

    # k-point locations of VBM and CBM
    if "vbm_kpoint" in params:
        band_edges["vbm_kpoint"] = params["vbm_kpoint"]
    if "cbm_kpoint" in params:
        band_edges["cbm_kpoint"] = params["cbm_kpoint"]

    # Recommended energy windows for disentanglement (Wannier90)
    if band_edges["fermi_energy_ev"] is not None:
        fermi = band_edges["fermi_energy_ev"]
        gap = band_edges["band_gap_ev"]

        # Frozen window: around the gap
        band_edges["recommended_dis_froz_min"] = fermi - 5.0
        band_edges["recommended_dis_froz_max"] = fermi + gap + 2.0

        # Outer window: broader range
        band_edges["recommended_dis_win_min"] = fermi - 10.0
        band_edges["recommended_dis_win_max"] = fermi + gap + 10.0

    return orm.Dict(dict=band_edges)
