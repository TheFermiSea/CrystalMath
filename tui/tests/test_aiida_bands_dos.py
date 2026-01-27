"""
Tests for Band Structure and DOS WorkChains.

Tests:
    - K-path generation for different crystal systems
    - Band structure parsing
    - DOS parameter parsing
    - XyData creation
    - WorkChain input validation
"""

from unittest.mock import MagicMock, patch

import pytest

# Check if aiida and numpy are available
try:
    import numpy as np
    from aiida import orm

    AIIDA_AVAILABLE = True
except ImportError:
    AIIDA_AVAILABLE = False
    orm = None
    np = None

pytestmark = pytest.mark.skipif(not AIIDA_AVAILABLE, reason="AiiDA and/or numpy not installed")


class TestKPathGeneration:
    """Test k-path generation for band structure."""

    def test_seekpath_availability_flag(self):
        """Test that SEEKPATH_AVAILABLE flag is set."""
        from src.aiida.workchains.crystal_bands import SEEKPATH_AVAILABLE

        # Should be a boolean
        assert isinstance(SEEKPATH_AVAILABLE, bool)

    def test_cubic_high_symmetry_points(self):
        """Test cubic system high-symmetry points."""
        from src.aiida.workchains.crystal_bands import HIGH_SYMMETRY_POINTS

        cubic = HIGH_SYMMETRY_POINTS["cubic"]

        assert cubic["Gamma"] == [0.0, 0.0, 0.0]
        assert cubic["X"] == [0.5, 0.0, 0.0]
        assert cubic["M"] == [0.5, 0.5, 0.0]
        assert cubic["R"] == [0.5, 0.5, 0.5]

    def test_fcc_high_symmetry_points(self):
        """Test FCC system high-symmetry points."""
        from src.aiida.workchains.crystal_bands import HIGH_SYMMETRY_POINTS

        fcc = HIGH_SYMMETRY_POINTS["fcc"]

        assert fcc["Gamma"] == [0.0, 0.0, 0.0]
        assert fcc["L"] == [0.5, 0.5, 0.5]
        assert "K" in fcc
        assert "W" in fcc

    def test_hexagonal_high_symmetry_points(self):
        """Test hexagonal system high-symmetry points."""
        from src.aiida.workchains.crystal_bands import HIGH_SYMMETRY_POINTS

        hex_pts = HIGH_SYMMETRY_POINTS["hexagonal"]

        assert hex_pts["Gamma"] == [0.0, 0.0, 0.0]
        assert hex_pts["A"] == [0.0, 0.0, 0.5]
        # K point at 1/3, 1/3, 0
        assert abs(hex_pts["K"][0] - 1.0 / 3.0) < 0.01
        assert abs(hex_pts["K"][1] - 1.0 / 3.0) < 0.01

    def test_standard_paths_defined(self):
        """Test that standard paths are defined for all systems."""
        from src.aiida.workchains.crystal_bands import STANDARD_PATHS

        for system in ["cubic", "fcc", "bcc", "hexagonal", "tetragonal"]:
            assert system in STANDARD_PATHS
            path = STANDARD_PATHS[system]
            assert len(path) >= 4
            assert path[0] == "Gamma"

    def test_crystal_system_detection_cubic(self):
        """Test detection of cubic crystal system."""
        from src.aiida.workchains.crystal_bands import _detect_crystal_system

        mock_structure = MagicMock()
        # Cubic cell: a = b = c, all angles 90
        mock_structure.cell = [
            [5.0, 0.0, 0.0],
            [0.0, 5.0, 0.0],
            [0.0, 0.0, 5.0],
        ]

        result = _detect_crystal_system(mock_structure)
        assert result == "cubic"

    def test_crystal_system_detection_hexagonal(self):
        """Test detection of hexagonal crystal system."""
        import math

        from src.aiida.workchains.crystal_bands import _detect_crystal_system

        mock_structure = MagicMock()
        # Hexagonal cell: a = b, gamma = 120
        a = 3.0
        mock_structure.cell = [
            [a, 0.0, 0.0],
            [a * math.cos(math.radians(120)), a * math.sin(math.radians(120)), 0.0],
            [0.0, 0.0, 5.0],
        ]

        result = _detect_crystal_system(mock_structure)
        assert result == "hexagonal"


class TestBandStructureParsing:
    """Test band structure result parsing."""

    def test_parse_band_structure_basic(self):
        """Test basic band structure parsing."""
        with patch("src.aiida.workchains.crystal_bands.orm") as mock_orm:
            from src.aiida.workchains.crystal_bands import parse_band_structure

            # Mock output parameters
            mock_output = MagicMock()
            mock_output.get_dict.return_value = {
                "fermi_energy_ev": 5.0,
                "n_bands": 10,
                "band_gap_ev": 1.5,
                "band_gap_type": "indirect",
                "vbm_ev": 4.25,
                "cbm_ev": 5.75,
            }

            # Mock kpoints
            mock_kpoints = MagicMock()
            mock_kpoints.get_kpoints.return_value = [[0, 0, 0], [0.5, 0, 0]]
            mock_kpoints.base.extras.get.side_effect = lambda k, d=[]: {
                "labels": ["Gamma", "X"],
                "label_indices": [0, 1],
                "crystal_system": "cubic",
            }.get(k, d)

            # Mock structure
            mock_structure = MagicMock()

            # Mock orm.Dict return
            result_dict = {}

            def mock_dict_init(**kwargs):
                result = MagicMock()
                result_dict.update(kwargs.get("dict", {}))
                return result

            mock_orm.Dict.side_effect = mock_dict_init

            parse_band_structure(mock_output, mock_kpoints, mock_structure)

            # Verify Dict was created with expected values
            assert "fermi_energy_ev" in result_dict
            assert result_dict["fermi_energy_ev"] == 5.0
            assert result_dict["band_gap_ev"] == 1.5
            assert result_dict["band_gap_type"] == "indirect"

    def test_metal_detection(self):
        """Test detection of metallic system."""
        with patch("src.aiida.workchains.crystal_bands.orm") as mock_orm:
            from src.aiida.workchains.crystal_bands import parse_band_structure

            mock_output = MagicMock()
            mock_output.get_dict.return_value = {
                "fermi_energy_ev": 5.0,
                "n_bands": 10,
                "band_gap_ev": 0.0,  # Zero gap = metal
            }

            mock_kpoints = MagicMock()
            mock_kpoints.get_kpoints.return_value = [[0, 0, 0]]
            mock_kpoints.base.extras.get.return_value = []

            mock_structure = MagicMock()

            result_dict = {}

            def mock_dict_init(**kwargs):
                result = MagicMock()
                result_dict.update(kwargs.get("dict", {}))
                return result

            mock_orm.Dict.side_effect = mock_dict_init

            parse_band_structure(mock_output, mock_kpoints, mock_structure)

            assert result_dict["is_metal"] is True


class TestDOSParsing:
    """Test DOS result parsing."""

    def test_parse_dos_output_basic(self):
        """Test basic DOS parsing."""
        with patch("src.aiida.workchains.crystal_dos.orm") as mock_orm:
            from src.aiida.workchains.crystal_dos import parse_dos_output

            mock_output = MagicMock()
            mock_output.get_dict.return_value = {
                "fermi_energy_ev": 5.0,
                "n_electrons": 20,
                "dos_energy_min": -10.0,
                "dos_energy_max": 5.0,
                "dos_energy_step": 0.01,
                "dos_n_points": 1501,
                "band_gap_ev": 1.5,
                "dos_at_fermi": 0.0,
            }

            mock_structure = MagicMock()
            mock_structure.sites = [MagicMock() for _ in range(4)]

            result_dict = {}

            def mock_dict_init(**kwargs):
                result = MagicMock()
                result_dict.update(kwargs.get("dict", {}))
                return result

            mock_orm.Dict.side_effect = mock_dict_init

            parse_dos_output(mock_output, mock_structure)

            assert result_dict["fermi_energy_ev"] == 5.0
            assert result_dict["n_atoms"] == 4
            assert result_dict["energy_min_ev"] == -10.0
            assert result_dict["is_metal"] is False

    def test_spin_polarized_dos(self):
        """Test spin-polarized DOS parsing."""
        with patch("src.aiida.workchains.crystal_dos.orm") as mock_orm:
            from src.aiida.workchains.crystal_dos import parse_dos_output

            mock_output = MagicMock()
            mock_output.get_dict.return_value = {
                "fermi_energy_ev": 5.0,
                "n_electrons": 20,
                "spin_polarized": True,
                "n_up_electrons": 12,
                "n_down_electrons": 8,
                "magnetic_moment": 4.0,
            }

            mock_structure = MagicMock()
            mock_structure.sites = [MagicMock(), MagicMock()]

            result_dict = {}

            def mock_dict_init(**kwargs):
                result = MagicMock()
                result_dict.update(kwargs.get("dict", {}))
                return result

            mock_orm.Dict.side_effect = mock_dict_init

            parse_dos_output(mock_output, mock_structure)

            assert result_dict["spin_polarized"] is True
            assert result_dict["magnetic_moment"] == 4.0

    def test_metallic_detection_from_dos(self):
        """Test metal detection from DOS at Fermi level."""
        with patch("src.aiida.workchains.crystal_dos.orm") as mock_orm:
            from src.aiida.workchains.crystal_dos import parse_dos_output

            mock_output = MagicMock()
            mock_output.get_dict.return_value = {
                "fermi_energy_ev": 5.0,
                "n_electrons": 20,
                "dos_at_fermi": 2.5,  # Non-zero DOS at Fermi = metal
            }

            mock_structure = MagicMock()
            mock_structure.sites = [MagicMock()]

            result_dict = {}

            def mock_dict_init(**kwargs):
                result = MagicMock()
                result_dict.update(kwargs.get("dict", {}))
                return result

            mock_orm.Dict.side_effect = mock_dict_init

            parse_dos_output(mock_output, mock_structure)

            assert result_dict["is_metal"] is True


class TestDOSKpoints:
    """Test DOS k-point mesh generation."""

    def test_compute_dos_kpoints(self):
        """Test dense k-mesh generation for DOS."""
        with patch("src.aiida.workchains.crystal_dos.orm") as mock_orm:
            from src.aiida.workchains.crystal_dos import compute_dos_kpoints

            mock_structure = MagicMock()
            mock_structure.cell = [
                [5.0, 0.0, 0.0],
                [0.0, 5.0, 0.0],
                [0.0, 0.0, 5.0],
            ]

            mock_kpoints_density = MagicMock()
            mock_kpoints_density.value = 0.1  # Dense mesh

            # Track what mesh is set
            set_mesh_args = {}
            mock_kpoints = MagicMock()

            def capture_mesh(mesh, offset):
                set_mesh_args["mesh"] = mesh
                set_mesh_args["offset"] = offset

            mock_kpoints.set_kpoints_mesh = capture_mesh
            mock_orm.KpointsData.return_value = mock_kpoints

            compute_dos_kpoints(mock_structure, mock_kpoints_density)

            # Verify mesh was set
            assert "mesh" in set_mesh_args
            mesh = set_mesh_args["mesh"]
            # All elements should be odd and > 1
            assert all(m > 1 for m in mesh)
            assert all(m % 2 == 1 for m in mesh)


class TestBandStructureWorkChain:
    """Test CrystalBandStructureWorkChain."""

    def test_workchain_define(self):
        """Test WorkChain definition."""
        from src.aiida.workchains.crystal_bands import CrystalBandStructureWorkChain

        # Should have expected inputs
        spec = CrystalBandStructureWorkChain.spec()

        assert "structure" in spec.inputs
        assert "code" in spec.inputs
        assert "kpoints_distance" in spec.inputs
        assert "protocol" in spec.inputs

        # Should have expected outputs
        assert "bands" in spec.outputs
        assert "band_parameters" in spec.outputs
        assert "kpoints" in spec.outputs

    def test_default_scf_parameters(self):
        """Test default SCF parameter generation."""
        from src.aiida.workchains.crystal_bands import CrystalBandStructureWorkChain

        workchain = MagicMock(spec=CrystalBandStructureWorkChain)
        workchain.inputs = MagicMock()
        workchain.inputs.protocol.value = "moderate"

        # Call the method
        params = CrystalBandStructureWorkChain._get_default_scf_parameters(workchain)

        assert "scf" in params
        assert "kpoints" in params
        assert params["scf"]["maxcycle"] == 100
        assert params["scf"]["toldee"] == 7


class TestDOSWorkChain:
    """Test CrystalDOSWorkChain."""

    def test_workchain_define(self):
        """Test WorkChain definition."""
        from src.aiida.workchains.crystal_dos import CrystalDOSWorkChain

        spec = CrystalDOSWorkChain.spec()

        # Inputs
        assert "structure" in spec.inputs
        assert "code" in spec.inputs
        assert "energy_range" in spec.inputs
        assert "smearing" in spec.inputs
        assert "compute_pdos" in spec.inputs

        # Outputs
        assert "dos" in spec.outputs
        assert "dos_parameters" in spec.outputs
        assert "kpoints" in spec.outputs

    def test_default_scf_parameters_precise(self):
        """Test precise protocol SCF parameters."""
        from src.aiida.workchains.crystal_dos import CrystalDOSWorkChain

        workchain = MagicMock(spec=CrystalDOSWorkChain)
        workchain.inputs = MagicMock()
        workchain.inputs.protocol.value = "precise"

        params = CrystalDOSWorkChain._get_default_scf_parameters(workchain)

        # Precise should have denser k-mesh
        assert params["kpoints"]["mesh"] == [12, 12, 12]
        assert params["scf"]["toldee"] == 8


class TestWorkChainExitCodes:
    """Test WorkChain exit codes."""

    def test_band_structure_exit_codes(self):
        """Test band structure exit codes are defined."""
        from src.aiida.workchains.crystal_bands import CrystalBandStructureWorkChain

        spec = CrystalBandStructureWorkChain.spec()

        assert 300 in spec.exit_codes  # ERROR_SCF_FAILED
        assert 301 in spec.exit_codes  # ERROR_BAND_CALCULATION_FAILED
        assert 302 in spec.exit_codes  # ERROR_NO_BANDS_PARSED

    def test_dos_exit_codes(self):
        """Test DOS exit codes are defined."""
        from src.aiida.workchains.crystal_dos import CrystalDOSWorkChain

        spec = CrystalDOSWorkChain.spec()

        assert 300 in spec.exit_codes  # ERROR_SCF_FAILED
        assert 301 in spec.exit_codes  # ERROR_DOS_CALCULATION_FAILED
        assert 302 in spec.exit_codes  # ERROR_NO_DOS_PARSED


class TestProtocolIntegration:
    """Test protocol-based configuration."""

    def test_fast_protocol_settings(self):
        """Test fast protocol uses relaxed settings."""
        from src.aiida.workchains.crystal_bands import CrystalBandStructureWorkChain

        workchain = MagicMock(spec=CrystalBandStructureWorkChain)
        workchain.inputs = MagicMock()
        workchain.inputs.protocol.value = "fast"

        params = CrystalBandStructureWorkChain._get_default_scf_parameters(workchain)

        assert params["scf"]["maxcycle"] == 50
        assert params["kpoints"]["mesh"] == [4, 4, 4]

    def test_precise_protocol_settings(self):
        """Test precise protocol uses tight settings."""
        from src.aiida.workchains.crystal_bands import CrystalBandStructureWorkChain

        workchain = MagicMock(spec=CrystalBandStructureWorkChain)
        workchain.inputs = MagicMock()
        workchain.inputs.protocol.value = "precise"

        params = CrystalBandStructureWorkChain._get_default_scf_parameters(workchain)

        assert params["scf"]["maxcycle"] == 200
        assert params["scf"]["toldee"] == 8
        assert params["kpoints"]["mesh"] == [8, 8, 8]
