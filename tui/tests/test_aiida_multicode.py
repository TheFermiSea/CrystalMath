"""
Tests for multi-code workflow infrastructure.

Tests the YAMBO and BerkeleyGW workflow orchestration:
    - Base class functionality
    - Converter functions
    - Workflow definitions
    - Simulated results (when external codes unavailable)
"""

from unittest.mock import MagicMock

import pytest

# Check if aiida is available
try:
    from aiida import orm

    AIIDA_AVAILABLE = True
except ImportError:
    AIIDA_AVAILABLE = False
    orm = None

# Check if numpy is available
try:
    import numpy as np

    NUMPY_AVAILABLE = True
except ImportError:
    np = None
    NUMPY_AVAILABLE = False

pytestmark = pytest.mark.skipif(not AIIDA_AVAILABLE, reason="AiiDA not installed")


class TestConverterFunctions:
    """Test converter calcfunctions."""

    def test_crystal_to_yambo_input_gw(self):
        """Test GW input generation."""
        from src.aiida.workchains.multicode.converters import crystal_to_yambo_input

        crystal_params = orm.Dict(
            dict={
                "n_electrons": 20,
                "n_bands": 50,
                "band_gap_ev": 1.5,
                "spin_polarized": False,
            }
        )

        gw_params = orm.Dict(
            dict={
                "type": "gw",
                "exchange_cutoff": 10.0,
                "bands_range": [1, 50],
            }
        )

        mock_structure = MagicMock()

        result = crystal_to_yambo_input(crystal_params, gw_params, mock_structure)

        assert result["type"] == "gw"
        assert "em1d" in result["runlevels"]
        assert "gw0" in result["runlevels"]
        assert "parameters" in result

    def test_crystal_to_yambo_input_bse(self):
        """Test BSE input generation."""
        from src.aiida.workchains.multicode.converters import crystal_to_yambo_input

        crystal_params = orm.Dict(
            dict={
                "n_electrons": 20,
                "band_gap_ev": 2.0,
            }
        )

        bse_params = orm.Dict(
            dict={
                "type": "bse",
                "bse_bands": [1, 20],
                "energy_steps": 100,
                "energy_range": [0.0, 10.0],
            }
        )

        mock_structure = MagicMock()

        result = crystal_to_yambo_input(crystal_params, bse_params, mock_structure)

        assert result["type"] == "bse"
        assert "bse" in result["runlevels"]
        assert "optics" in result["runlevels"]

    def test_crystal_to_yambo_input_nonlinear(self):
        """Test nonlinear optics input generation."""
        from src.aiida.workchains.multicode.converters import crystal_to_yambo_input

        crystal_params = orm.Dict(
            dict={
                "n_electrons": 20,
            }
        )

        nl_params = orm.Dict(
            dict={
                "type": "nonlinear",
                "nl_time": [-1, 100],
                "damping": 0.1,
                "correlation": "SEX",
            }
        )

        mock_structure = MagicMock()

        result = crystal_to_yambo_input(crystal_params, nl_params, mock_structure)

        assert result["type"] == "nonlinear"
        assert "nl" in result["runlevels"]
        assert result["parameters"]["NLCorrelation"] == "SEX"

    def test_crystal_to_berkeleygw(self):
        """Test BerkeleyGW input generation."""
        from src.aiida.workchains.multicode.converters import crystal_to_berkeleygw

        crystal_params = orm.Dict(
            dict={
                "n_electrons": 20,
                "fermi_energy_ev": 5.0,
                "n_kpoints": 64,
            }
        )

        gw_params = orm.Dict(
            dict={
                "epsilon_bands": 100,
                "epsilon_cutoff": 10.0,
                "sigma_bands": 50,
                "do_bse": False,
            }
        )

        mock_structure = MagicMock()

        result = crystal_to_berkeleygw(crystal_params, mock_structure, gw_params)

        assert "epsilon" in result
        assert "sigma" in result
        assert result["epsilon"]["number_bands"] == 100
        assert result["sigma"]["number_bands"] == 50

    def test_crystal_to_berkeleygw_with_bse(self):
        """Test BerkeleyGW input with BSE enabled."""
        from src.aiida.workchains.multicode.converters import crystal_to_berkeleygw

        crystal_params = orm.Dict(
            dict={
                "fermi_energy_ev": 5.0,
            }
        )

        gw_params = orm.Dict(
            dict={
                "epsilon_bands": 100,
                "do_bse": True,
                "kernel_val_bands": 4,
                "abs_val_bands": 4,
            }
        )

        mock_structure = MagicMock()

        result = crystal_to_berkeleygw(crystal_params, mock_structure, gw_params)

        assert "kernel" in result
        assert "absorption" in result
        assert result["kernel"]["number_val_bands"] == 4

    def test_extract_band_edges(self):
        """Test band edge extraction."""
        from src.aiida.workchains.multicode.converters import extract_band_edges

        crystal_params = orm.Dict(
            dict={
                "fermi_energy_ev": 5.0,
                "band_gap_ev": 1.5,
                "gap_type": "direct",
                "vbm_ev": 4.25,
                "cbm_ev": 5.75,
            }
        )

        result = extract_band_edges(crystal_params)

        assert result["fermi_energy_ev"] == 5.0
        assert result["band_gap_ev"] == 1.5
        assert result["gap_type"] == "direct"
        assert result["is_metal"] is False
        assert "recommended_dis_froz_min" in result

    def test_extract_band_edges_metal(self):
        """Test band edge extraction for metal."""
        from src.aiida.workchains.multicode.converters import extract_band_edges

        crystal_params = orm.Dict(
            dict={
                "fermi_energy_ev": 5.0,
                "band_gap_ev": 0.0,
            }
        )

        result = extract_band_edges(crystal_params)

        assert result["is_metal"] is True

    @pytest.mark.skipif(not NUMPY_AVAILABLE, reason="numpy not installed")
    def test_crystal_bands_to_wannier90(self):
        """Test Wannier90 input generation."""
        from src.aiida.workchains.multicode.converters import crystal_bands_to_wannier90

        # Create mock BandsData
        mock_bands = MagicMock()
        mock_bands.get_kpoints.return_value = np.array([[0, 0, 0], [0.5, 0, 0]])
        mock_bands.get_bands.return_value = np.array(
            [
                [-5.0, -4.0, -3.0, 1.0, 2.0],
                [-4.5, -3.5, -2.5, 1.5, 2.5],
            ]
        )

        # Create mock structure
        mock_structure = MagicMock()
        mock_structure.cell = [[5.0, 0, 0], [0, 5.0, 0], [0, 0, 5.0]]
        mock_site = MagicMock()
        mock_site.kind_name = "Si"
        mock_site.position = [0, 0, 0]
        mock_structure.sites = [mock_site]
        mock_structure.get_kind_names.return_value = ["Si"]

        wannier_params = orm.Dict(
            dict={
                "num_wann": 4,
                "mp_grid": [4, 4, 4],
                "dis_num_iter": 200,
            }
        )

        result = crystal_bands_to_wannier90(mock_bands, mock_structure, wannier_params)

        assert result["num_wann"] == 4
        assert result["mp_grid"] == [4, 4, 4]
        assert result["dis_num_iter"] == 200
        assert len(result["atoms_frac"]) == 1


class TestYamboWorkChainDefinitions:
    """Test YAMBO WorkChain class definitions."""

    def test_yambo_gw_workchain_spec(self):
        """Test YamboGWWorkChain specification."""
        from src.aiida.workchains.multicode.yambo_gw import YamboGWWorkChain

        spec = YamboGWWorkChain.spec()

        # Check inputs
        assert "structure" in spec.inputs
        assert "crystal_code" in spec.inputs
        assert "yambo_code" in spec.inputs
        assert "gw_parameters" in spec.inputs

        # Check outputs
        assert "qp_corrections" in spec.outputs
        assert "qp_bandstructure" in spec.outputs

        # Check exit codes
        assert 310 in spec.exit_codes  # ERROR_YAMBO_NOT_AVAILABLE
        assert 311 in spec.exit_codes  # ERROR_GW_CALCULATION_FAILED

    def test_yambo_bse_workchain_spec(self):
        """Test YamboBSEWorkChain specification."""
        from src.aiida.workchains.multicode.yambo_gw import YamboBSEWorkChain

        spec = YamboBSEWorkChain.spec()

        # Check inputs
        assert "bse_parameters" in spec.inputs
        assert "do_gw" in spec.inputs
        assert "scissor_ev" in spec.inputs

        # Check outputs
        assert "excitons" in spec.outputs
        assert "optical_spectrum" in spec.outputs

        # Check exit codes
        assert 320 in spec.exit_codes  # ERROR_BSE_CALCULATION_FAILED

    def test_yambo_nonlinear_workchain_spec(self):
        """Test YamboNonlinearWorkChain specification."""
        from src.aiida.workchains.multicode.yambo_nonlinear import YamboNonlinearWorkChain

        spec = YamboNonlinearWorkChain.spec()

        # Check inputs
        assert "nl_parameters" in spec.inputs
        assert "energy_range" in spec.inputs
        assert "include_gw" in spec.inputs

        # Check outputs
        assert "nonlinear_susceptibility" in spec.outputs
        assert "polarization_dynamics" in spec.outputs
        assert "tensor_components" in spec.outputs

        # Check exit codes
        assert 333 in spec.exit_codes  # ERROR_INVALID_RESPONSE_ORDER


class TestBerkeleyGWWorkChainDefinition:
    """Test BerkeleyGW WorkChain class definition."""

    def test_berkeleygw_workchain_spec(self):
        """Test BerkeleyGWWorkChain specification."""
        from src.aiida.workchains.multicode.berkeleygw import BerkeleyGWWorkChain

        spec = BerkeleyGWWorkChain.spec()

        # Check inputs
        assert "bgw_epsilon_code" in spec.inputs
        assert "bgw_sigma_code" in spec.inputs
        assert "bgw_kernel_code" in spec.inputs
        assert "bgw_absorption_code" in spec.inputs
        assert "gw_parameters" in spec.inputs
        assert "do_bse" in spec.inputs

        # Check outputs
        assert "qp_corrections" in spec.outputs
        assert "dielectric" in spec.outputs
        assert "absorption_spectrum" in spec.outputs

        # Check exit codes
        assert 340 in spec.exit_codes  # ERROR_EPSILON_FAILED
        assert 341 in spec.exit_codes  # ERROR_SIGMA_FAILED


class TestBaseClasses:
    """Test base class functionality."""

    def test_multicode_workchain_required_codes(self):
        """Test REQUIRED_CODES class variable."""
        from src.aiida.workchains.multicode.base import MultiCodeWorkChain

        assert hasattr(MultiCodeWorkChain, "REQUIRED_CODES")
        assert isinstance(MultiCodeWorkChain.REQUIRED_CODES, list)

    def test_postscf_workchain_inherits_multicode(self):
        """Test PostSCFWorkChain inheritance."""
        from src.aiida.workchains.multicode.base import (
            MultiCodeWorkChain,
            PostSCFWorkChain,
        )

        assert issubclass(PostSCFWorkChain, MultiCodeWorkChain)
        assert "crystal_code" in PostSCFWorkChain.REQUIRED_CODES

    def test_yambo_gw_inherits_postscf(self):
        """Test YamboGWWorkChain inheritance."""
        from src.aiida.workchains.multicode.base import PostSCFWorkChain
        from src.aiida.workchains.multicode.yambo_gw import YamboGWWorkChain

        assert issubclass(YamboGWWorkChain, PostSCFWorkChain)
        assert "yambo_code" in YamboGWWorkChain.REQUIRED_CODES


class TestModuleImports:
    """Test module-level imports and availability flags."""

    def test_multicode_module_import(self):
        """Test multicode module imports correctly."""
        from src.aiida.workchains import multicode

        assert hasattr(multicode, "YamboGWWorkChain")
        assert hasattr(multicode, "YamboBSEWorkChain")
        assert hasattr(multicode, "YamboNonlinearWorkChain")
        assert hasattr(multicode, "BerkeleyGWWorkChain")

    def test_multicode_available_flag(self):
        """Test MULTICODE_AVAILABLE flag."""
        from src.aiida.workchains import MULTICODE_AVAILABLE

        # Should be True since we can import the module
        assert MULTICODE_AVAILABLE is True

    def test_converter_imports(self):
        """Test converter function imports."""
        from src.aiida.workchains.multicode import (
            crystal_bands_to_wannier90,
            crystal_to_qe_wavefunction,
            crystal_to_yambo_input,
        )

        assert callable(crystal_to_qe_wavefunction)
        assert callable(crystal_to_yambo_input)
        assert callable(crystal_bands_to_wannier90)


class TestDefaultParameters:
    """Test default parameter values."""

    def test_gw_default_parameters(self):
        """Test YamboGWWorkChain default parameters."""
        from src.aiida.workchains.multicode.yambo_gw import YamboGWWorkChain

        spec = YamboGWWorkChain.spec()

        # Get default gw_parameters - call the stored default callable
        default_callable = spec.inputs["gw_parameters"]["default"]
        default_gw = default_callable()
        params = default_gw.get_dict()

        assert "type" in params
        assert params["type"] == "gw"
        assert "bands_range" in params
        assert "exchange_cutoff" in params

    def test_bse_default_parameters(self):
        """Test YamboBSEWorkChain default parameters."""
        from src.aiida.workchains.multicode.yambo_gw import YamboBSEWorkChain

        spec = YamboBSEWorkChain.spec()

        # Get default bse_parameters - call the stored default callable
        default_callable = spec.inputs["bse_parameters"]["default"]
        default_bse = default_callable()
        params = default_bse.get_dict()

        assert params["type"] == "bse"
        assert "bse_bands" in params
        assert "energy_range" in params

    def test_nonlinear_default_parameters(self):
        """Test YamboNonlinearWorkChain default parameters."""
        from src.aiida.workchains.multicode.yambo_nonlinear import YamboNonlinearWorkChain

        spec = YamboNonlinearWorkChain.spec()

        # Get default nl_parameters - call the stored default callable
        default_callable = spec.inputs["nl_parameters"]["default"]
        default_nl = default_callable()
        params = default_nl.get_dict()

        assert params["type"] == "nonlinear"
        assert params["response_order"] == 2
        assert "field_intensity" in params
        assert "field_direction" in params

    def test_berkeleygw_default_parameters(self):
        """Test BerkeleyGWWorkChain default parameters."""
        from src.aiida.workchains.multicode.berkeleygw import BerkeleyGWWorkChain

        spec = BerkeleyGWWorkChain.spec()

        # Get default gw_parameters - call the stored default callable
        default_callable = spec.inputs["gw_parameters"]["default"]
        default_gw = default_callable()
        params = default_gw.get_dict()

        assert "epsilon_bands" in params
        assert "sigma_bands" in params
        assert "freq_dep" in params


class TestCodeCompatibility:
    """Test code compatibility validation."""

    def test_validate_code_compatibility(self):
        """Test code compatibility validation function."""
        from src.aiida.workchains.multicode.base import validate_code_compatibility

        mock_structure = MagicMock()
        mock_structure.get_kind_names.return_value = ["Si", "O"]

        result = validate_code_compatibility(
            mock_structure,
            orm.Str("crystal23"),
            orm.Str("yambo"),
        )

        assert result["valid"] is True
        assert isinstance(result["warnings"], list)
        assert isinstance(result["errors"], list)

    def test_validate_code_compatibility_heavy_elements(self):
        """Test warning for heavy elements."""
        from src.aiida.workchains.multicode.base import validate_code_compatibility

        mock_structure = MagicMock()
        mock_structure.get_kind_names.return_value = ["U", "O"]  # Uranium

        result = validate_code_compatibility(
            mock_structure,
            orm.Str("crystal23"),
            orm.Str("yambo"),
        )

        # Should have warning about heavy elements
        assert len(result["warnings"]) > 0
        assert any("heavy" in w.lower() for w in result["warnings"])
