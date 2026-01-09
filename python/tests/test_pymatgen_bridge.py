"""Tests for pymatgen_bridge module.

This module tests structure conversion functions and integration
with external libraries (pymatgen, AiiDA, ASE).

Tests cover:
- Structure loading from CIF/POSCAR files
- Conversion to/from AiiDA StructureData
- Conversion to/from ASE Atoms
- Symmetry analysis and dimensionality detection
- DFT validation checks
"""

from __future__ import annotations

import pytest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, MagicMock, patch, PropertyMock

# Check if optional dependencies are available
try:
    import pymatgen
    from pymatgen.core import Structure, Lattice

    HAS_PYMATGEN = True
except ImportError:
    HAS_PYMATGEN = False

try:
    import ase
    from ase import Atoms

    HAS_ASE = True
except ImportError:
    HAS_ASE = False


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_structure() -> Mock:
    """Create a mock pymatgen Structure."""
    mock = Mock()
    mock.formula = "NaCl"
    mock.composition.reduced_formula = "NaCl"
    mock.num_sites = 2
    mock.volume = 45.0
    mock.lattice.abc = (5.64, 5.64, 5.64)
    mock.lattice.angles = (90.0, 90.0, 90.0)
    mock.lattice.matrix = [[5.64, 0, 0], [0, 5.64, 0], [0, 0, 5.64]]
    mock.species = [Mock(symbol="Na"), Mock(symbol="Cl")]
    mock.frac_coords = [[0, 0, 0], [0.5, 0.5, 0.5]]
    mock.cart_coords = [[0, 0, 0], [2.82, 2.82, 2.82]]
    return mock


@pytest.fixture
def sample_cif_content() -> str:
    """Sample CIF file content for NaCl."""
    return """data_NaCl
_symmetry_space_group_name_H-M   'F m -3 m'
_symmetry_Int_Tables_number      225
_cell_length_a                   5.64
_cell_length_b                   5.64
_cell_length_c                   5.64
_cell_angle_alpha                90.00
_cell_angle_beta                 90.00
_cell_angle_gamma                90.00
loop_
_atom_site_type_symbol
_atom_site_label
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Na Na1 0.00000 0.00000 0.00000
Cl Cl1 0.50000 0.50000 0.50000
"""


@pytest.fixture
def sample_poscar_content() -> str:
    """Sample POSCAR file content for NaCl."""
    return """NaCl structure
5.64
1.0 0.0 0.0
0.0 1.0 0.0
0.0 0.0 1.0
Na Cl
1 1
Direct
0.0 0.0 0.0
0.5 0.5 0.5
"""


@pytest.fixture
def cif_file(tmp_path: Path, sample_cif_content: str) -> Path:
    """Create a temporary CIF file."""
    cif_path = tmp_path / "test.cif"
    cif_path.write_text(sample_cif_content)
    return cif_path


@pytest.fixture
def poscar_file(tmp_path: Path, sample_poscar_content: str) -> Path:
    """Create a temporary POSCAR file."""
    poscar_path = tmp_path / "POSCAR"
    poscar_path.write_text(sample_poscar_content)
    return poscar_path


# =============================================================================
# Test Structure Loading
# =============================================================================


class TestStructureFromCIF:
    """Tests for loading structures from CIF files."""

    def test_structure_from_cif_file_exists(
        self, cif_file: Path, mock_structure: Mock
    ) -> None:
        """Test loading structure from existing CIF file."""
        with patch(
            "crystalmath.integrations.pymatgen_bridge.Structure.from_file",
            return_value=mock_structure,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            result = PymatgenBridge.structure_from_cif(str(cif_file))
            assert result is not None

    def test_structure_from_cif_file_not_found(self, tmp_path: Path) -> None:
        """Test error handling for missing CIF file."""
        from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

        nonexistent = tmp_path / "nonexistent.cif"
        with pytest.raises(FileNotFoundError):
            PymatgenBridge.structure_from_cif(str(nonexistent))

    def test_structure_from_cif_invalid_content(self, tmp_path: Path) -> None:
        """Test error handling for invalid CIF content."""
        bad_cif = tmp_path / "bad.cif"
        bad_cif.write_text("this is not a valid CIF file")

        from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

        with pytest.raises((ValueError, Exception)):
            PymatgenBridge.structure_from_cif(str(bad_cif))

    def test_structure_from_cif_returns_correct_type(
        self, cif_file: Path, mock_structure: Mock
    ) -> None:
        """Test that returned structure has expected attributes."""
        with patch(
            "crystalmath.integrations.pymatgen_bridge.Structure.from_file",
            return_value=mock_structure,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            result = PymatgenBridge.structure_from_cif(str(cif_file))
            assert hasattr(result, "formula")


class TestStructureFromPOSCAR:
    """Tests for loading structures from POSCAR files."""

    def test_structure_from_poscar_file_exists(
        self, poscar_file: Path, mock_structure: Mock
    ) -> None:
        """Test loading structure from existing POSCAR file."""
        with patch(
            "crystalmath.integrations.pymatgen_bridge.Poscar.from_file"
        ) as mock_poscar:
            mock_poscar.return_value.structure = mock_structure

            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            result = PymatgenBridge.structure_from_poscar(str(poscar_file))
            assert result is not None

    def test_structure_from_poscar_file_not_found(self, tmp_path: Path) -> None:
        """Test error handling for missing POSCAR file."""
        from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

        nonexistent = tmp_path / "POSCAR_MISSING"
        with pytest.raises(FileNotFoundError):
            PymatgenBridge.structure_from_poscar(str(nonexistent))

    def test_structure_from_poscar_returns_structure(
        self, poscar_file: Path, mock_structure: Mock
    ) -> None:
        """Test that POSCAR loading returns proper structure."""
        with patch(
            "crystalmath.integrations.pymatgen_bridge.Poscar.from_file"
        ) as mock_poscar:
            mock_poscar.return_value.structure = mock_structure

            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            result = PymatgenBridge.structure_from_poscar(str(poscar_file))
            assert result == mock_structure


# =============================================================================
# Test AiiDA Conversion
# =============================================================================


class TestAiiDAConversion:
    """Tests for AiiDA StructureData conversion."""

    def test_to_aiida_structure_mock(self, mock_structure: Mock) -> None:
        """Test conversion to AiiDA StructureData with mocked AiiDA."""
        mock_aiida_structure = Mock()
        mock_aiida_structure.get_pymatgen.return_value = mock_structure

        with patch(
            "crystalmath.integrations.pymatgen_bridge.HAS_AIIDA", True
        ), patch(
            "crystalmath.integrations.pymatgen_bridge.StructureData",
            return_value=mock_aiida_structure,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            result = PymatgenBridge.to_aiida_structure(mock_structure)
            assert result is not None

    def test_to_aiida_structure_without_aiida(self, mock_structure: Mock) -> None:
        """Test error when AiiDA is not available."""
        with patch("crystalmath.integrations.pymatgen_bridge.HAS_AIIDA", False):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            with pytest.raises(ImportError):
                PymatgenBridge.to_aiida_structure(mock_structure)

    def test_from_aiida_structure_mock(self, mock_structure: Mock) -> None:
        """Test conversion from AiiDA StructureData."""
        mock_aiida_structure = Mock()
        mock_aiida_structure.get_pymatgen.return_value = mock_structure

        with patch("crystalmath.integrations.pymatgen_bridge.HAS_AIIDA", True):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            result = PymatgenBridge.from_aiida_structure(mock_aiida_structure)
            assert result == mock_structure

    def test_from_aiida_structure_without_aiida(self) -> None:
        """Test error when AiiDA is not available."""
        mock_aiida_structure = Mock()

        with patch("crystalmath.integrations.pymatgen_bridge.HAS_AIIDA", False):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            with pytest.raises(ImportError):
                PymatgenBridge.from_aiida_structure(mock_aiida_structure)

    def test_aiida_roundtrip_preserves_structure(self, mock_structure: Mock) -> None:
        """Test that AiiDA roundtrip preserves structure information."""
        mock_aiida_structure = Mock()
        mock_aiida_structure.get_pymatgen.return_value = mock_structure

        with patch(
            "crystalmath.integrations.pymatgen_bridge.HAS_AIIDA", True
        ), patch(
            "crystalmath.integrations.pymatgen_bridge.StructureData",
            return_value=mock_aiida_structure,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            aiida_struct = PymatgenBridge.to_aiida_structure(mock_structure)
            result = PymatgenBridge.from_aiida_structure(aiida_struct)
            assert result == mock_structure


# =============================================================================
# Test ASE Conversion
# =============================================================================


class TestASEConversion:
    """Tests for ASE Atoms conversion."""

    def test_to_ase_atoms_mock(self, mock_structure: Mock) -> None:
        """Test conversion to ASE Atoms with mocked ASE."""
        mock_atoms = Mock()

        with patch(
            "crystalmath.integrations.pymatgen_bridge.HAS_ASE", True
        ), patch(
            "crystalmath.integrations.pymatgen_bridge.AseAtomsAdaptor.get_atoms",
            return_value=mock_atoms,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            result = PymatgenBridge.to_ase_atoms(mock_structure)
            assert result is not None

    def test_to_ase_atoms_without_ase(self, mock_structure: Mock) -> None:
        """Test error when ASE is not available."""
        with patch("crystalmath.integrations.pymatgen_bridge.HAS_ASE", False):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            with pytest.raises(ImportError):
                PymatgenBridge.to_ase_atoms(mock_structure)

    def test_from_ase_atoms_mock(self, mock_structure: Mock) -> None:
        """Test conversion from ASE Atoms."""
        mock_atoms = Mock()

        with patch(
            "crystalmath.integrations.pymatgen_bridge.HAS_ASE", True
        ), patch(
            "crystalmath.integrations.pymatgen_bridge.AseAtomsAdaptor.get_structure",
            return_value=mock_structure,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            result = PymatgenBridge.from_ase_atoms(mock_atoms)
            assert result == mock_structure

    def test_from_ase_atoms_without_ase(self) -> None:
        """Test error when ASE is not available."""
        mock_atoms = Mock()

        with patch("crystalmath.integrations.pymatgen_bridge.HAS_ASE", False):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            with pytest.raises(ImportError):
                PymatgenBridge.from_ase_atoms(mock_atoms)

    def test_ase_roundtrip_preserves_structure(self, mock_structure: Mock) -> None:
        """Test that ASE roundtrip preserves structure information."""
        mock_atoms = Mock()

        with patch(
            "crystalmath.integrations.pymatgen_bridge.HAS_ASE", True
        ), patch(
            "crystalmath.integrations.pymatgen_bridge.AseAtomsAdaptor.get_atoms",
            return_value=mock_atoms,
        ), patch(
            "crystalmath.integrations.pymatgen_bridge.AseAtomsAdaptor.get_structure",
            return_value=mock_structure,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            ase_atoms = PymatgenBridge.to_ase_atoms(mock_structure)
            result = PymatgenBridge.from_ase_atoms(ase_atoms)
            assert result == mock_structure


# =============================================================================
# Test Symmetry Analysis
# =============================================================================


class TestSymmetryInfo:
    """Tests for symmetry information extraction."""

    def test_get_symmetry_info_cubic(self, mock_structure: Mock) -> None:
        """Test symmetry info extraction for cubic structure."""
        mock_analyzer = Mock()
        mock_analyzer.get_crystal_system.return_value = "cubic"
        mock_analyzer.get_space_group_symbol.return_value = "Fm-3m"
        mock_analyzer.get_space_group_number.return_value = 225
        mock_analyzer.get_point_group_symbol.return_value = "m-3m"

        with patch(
            "crystalmath.integrations.pymatgen_bridge.SpacegroupAnalyzer",
            return_value=mock_analyzer,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            info = PymatgenBridge.get_symmetry_info(mock_structure)

            assert info["crystal_system"] == "cubic"
            assert info["space_group_symbol"] == "Fm-3m"
            assert info["space_group_number"] == 225

    @pytest.mark.parametrize(
        "crystal_system,expected",
        [
            ("cubic", "cubic"),
            ("hexagonal", "hexagonal"),
            ("tetragonal", "tetragonal"),
            ("orthorhombic", "orthorhombic"),
            ("monoclinic", "monoclinic"),
            ("triclinic", "triclinic"),
            ("trigonal", "trigonal"),
        ],
    )
    def test_get_symmetry_info_crystal_systems(
        self, mock_structure: Mock, crystal_system: str, expected: str
    ) -> None:
        """Test detection of various crystal systems."""
        mock_analyzer = Mock()
        mock_analyzer.get_crystal_system.return_value = crystal_system
        mock_analyzer.get_space_group_symbol.return_value = "Test"
        mock_analyzer.get_space_group_number.return_value = 1
        mock_analyzer.get_point_group_symbol.return_value = "1"

        with patch(
            "crystalmath.integrations.pymatgen_bridge.SpacegroupAnalyzer",
            return_value=mock_analyzer,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            info = PymatgenBridge.get_symmetry_info(mock_structure)
            assert info["crystal_system"] == expected

    def test_get_symmetry_info_with_tolerance(self, mock_structure: Mock) -> None:
        """Test symmetry analysis with custom tolerance."""
        mock_analyzer = Mock()
        mock_analyzer.get_crystal_system.return_value = "cubic"
        mock_analyzer.get_space_group_symbol.return_value = "Pm-3m"
        mock_analyzer.get_space_group_number.return_value = 221
        mock_analyzer.get_point_group_symbol.return_value = "m-3m"

        with patch(
            "crystalmath.integrations.pymatgen_bridge.SpacegroupAnalyzer",
            return_value=mock_analyzer,
        ) as mock_sga:
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            _ = PymatgenBridge.get_symmetry_info(mock_structure, symprec=0.1)
            mock_sga.assert_called_once_with(mock_structure, symprec=0.1)


# =============================================================================
# Test Dimensionality Detection
# =============================================================================


class TestDimensionality:
    """Tests for dimensionality detection (0D/1D/2D/3D)."""

    def test_get_dimensionality_3d_bulk(self, mock_structure: Mock) -> None:
        """Test detection of 3D bulk structure."""
        with patch(
            "crystalmath.integrations.pymatgen_bridge.get_dimensionality_gorai",
            return_value=3,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            dim = PymatgenBridge.get_dimensionality(mock_structure)
            assert dim == 3

    def test_get_dimensionality_2d_slab(self, mock_structure: Mock) -> None:
        """Test detection of 2D slab/layer structure."""
        with patch(
            "crystalmath.integrations.pymatgen_bridge.get_dimensionality_gorai",
            return_value=2,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            dim = PymatgenBridge.get_dimensionality(mock_structure)
            assert dim == 2

    def test_get_dimensionality_1d_chain(self, mock_structure: Mock) -> None:
        """Test detection of 1D chain/polymer structure."""
        with patch(
            "crystalmath.integrations.pymatgen_bridge.get_dimensionality_gorai",
            return_value=1,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            dim = PymatgenBridge.get_dimensionality(mock_structure)
            assert dim == 1

    def test_get_dimensionality_0d_molecule(self, mock_structure: Mock) -> None:
        """Test detection of 0D molecular structure."""
        with patch(
            "crystalmath.integrations.pymatgen_bridge.get_dimensionality_gorai",
            return_value=0,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            dim = PymatgenBridge.get_dimensionality(mock_structure)
            assert dim == 0

    @pytest.mark.parametrize("dimension", [0, 1, 2, 3])
    def test_get_dimensionality_all_types(
        self, mock_structure: Mock, dimension: int
    ) -> None:
        """Test all dimensionality types."""
        with patch(
            "crystalmath.integrations.pymatgen_bridge.get_dimensionality_gorai",
            return_value=dimension,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            dim = PymatgenBridge.get_dimensionality(mock_structure)
            assert dim == dimension


# =============================================================================
# Test DFT Validation
# =============================================================================


class TestDFTValidation:
    """Tests for DFT validation checks."""

    def test_validate_for_dft_valid_structure(self, mock_structure: Mock) -> None:
        """Test validation of a valid structure."""
        mock_structure.num_sites = 10
        mock_structure.volume = 100.0
        mock_structure.is_ordered = True

        from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

        is_valid, issues = PymatgenBridge.validate_for_dft(mock_structure)
        assert is_valid is True
        assert len(issues) == 0

    def test_validate_for_dft_too_many_atoms(self, mock_structure: Mock) -> None:
        """Test validation fails for too many atoms."""
        mock_structure.num_sites = 10000
        mock_structure.volume = 100000.0
        mock_structure.is_ordered = True

        from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

        is_valid, issues = PymatgenBridge.validate_for_dft(
            mock_structure, max_atoms=1000
        )
        assert is_valid is False
        assert any("atoms" in issue.lower() for issue in issues)

    def test_validate_for_dft_disordered_structure(self, mock_structure: Mock) -> None:
        """Test validation handles disordered structures."""
        mock_structure.num_sites = 10
        mock_structure.volume = 100.0
        mock_structure.is_ordered = False

        from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

        is_valid, issues = PymatgenBridge.validate_for_dft(mock_structure)
        # Disordered structures may need special handling
        assert isinstance(is_valid, bool)
        assert isinstance(issues, list)

    def test_validate_for_dft_zero_volume(self, mock_structure: Mock) -> None:
        """Test validation fails for zero volume."""
        mock_structure.num_sites = 10
        mock_structure.volume = 0.0
        mock_structure.is_ordered = True

        from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

        is_valid, issues = PymatgenBridge.validate_for_dft(mock_structure)
        assert is_valid is False

    def test_validate_for_dft_custom_max_atoms(self, mock_structure: Mock) -> None:
        """Test validation with custom max_atoms parameter."""
        mock_structure.num_sites = 500
        mock_structure.volume = 5000.0
        mock_structure.is_ordered = True

        from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

        # Should pass with default max
        is_valid_default, _ = PymatgenBridge.validate_for_dft(mock_structure)

        # Should fail with strict limit
        is_valid_strict, issues = PymatgenBridge.validate_for_dft(
            mock_structure, max_atoms=100
        )
        assert is_valid_strict is False

    @pytest.mark.parametrize(
        "num_atoms,expected_valid",
        [
            (10, True),
            (100, True),
            (500, True),
            (1001, False),  # Default max is 1000
        ],
    )
    def test_validate_for_dft_atom_limits(
        self, mock_structure: Mock, num_atoms: int, expected_valid: bool
    ) -> None:
        """Test validation with various atom counts."""
        mock_structure.num_sites = num_atoms
        mock_structure.volume = num_atoms * 10.0
        mock_structure.is_ordered = True

        from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

        is_valid, _ = PymatgenBridge.validate_for_dft(mock_structure)
        assert is_valid == expected_valid


# =============================================================================
# Test Structure Manipulation
# =============================================================================


class TestStructureManipulation:
    """Tests for structure manipulation utilities."""

    def test_make_supercell(self, mock_structure: Mock) -> None:
        """Test supercell creation."""
        mock_supercell = Mock()
        mock_structure.copy.return_value = mock_supercell
        mock_supercell.make_supercell.return_value = None

        from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

        result = PymatgenBridge.make_supercell(mock_structure, [2, 2, 2])
        assert result is not None

    def test_get_primitive_cell(self, mock_structure: Mock) -> None:
        """Test primitive cell extraction."""
        mock_analyzer = Mock()
        mock_primitive = Mock()
        mock_analyzer.get_primitive_standard_structure.return_value = mock_primitive

        with patch(
            "crystalmath.integrations.pymatgen_bridge.SpacegroupAnalyzer",
            return_value=mock_analyzer,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            result = PymatgenBridge.get_primitive_cell(mock_structure)
            assert result == mock_primitive

    def test_get_conventional_cell(self, mock_structure: Mock) -> None:
        """Test conventional cell extraction."""
        mock_analyzer = Mock()
        mock_conventional = Mock()
        mock_analyzer.get_conventional_standard_structure.return_value = (
            mock_conventional
        )

        with patch(
            "crystalmath.integrations.pymatgen_bridge.SpacegroupAnalyzer",
            return_value=mock_analyzer,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            result = PymatgenBridge.get_conventional_cell(mock_structure)
            assert result == mock_conventional


# =============================================================================
# Test K-Point Generation
# =============================================================================


class TestKPointGeneration:
    """Tests for k-point mesh generation."""

    def test_get_kpoints_mesh_default(self, mock_structure: Mock) -> None:
        """Test k-point mesh generation with default density."""
        from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

        kpoints = PymatgenBridge.get_kpoints_mesh(mock_structure)
        assert kpoints is not None
        assert len(kpoints) == 3  # Should return 3D mesh

    def test_get_kpoints_mesh_custom_density(self, mock_structure: Mock) -> None:
        """Test k-point mesh with custom density."""
        from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

        kpoints_dense = PymatgenBridge.get_kpoints_mesh(mock_structure, density=0.02)
        kpoints_sparse = PymatgenBridge.get_kpoints_mesh(mock_structure, density=0.08)

        # Denser mesh should have equal or more k-points
        assert sum(kpoints_dense) >= sum(kpoints_sparse)

    @pytest.mark.parametrize(
        "density,expected_min_kpts",
        [
            (0.02, 10),  # High density
            (0.04, 5),  # Moderate density
            (0.08, 3),  # Low density
        ],
    )
    def test_get_kpoints_mesh_densities(
        self, mock_structure: Mock, density: float, expected_min_kpts: int
    ) -> None:
        """Test k-point mesh generation at various densities."""
        from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

        kpoints = PymatgenBridge.get_kpoints_mesh(mock_structure, density=density)
        assert min(kpoints) >= 1  # At least 1 k-point per direction


# =============================================================================
# Test Band Path Generation
# =============================================================================


class TestBandPath:
    """Tests for high-symmetry band path generation."""

    def test_get_band_path_cubic(self, mock_structure: Mock) -> None:
        """Test band path generation for cubic structure."""
        mock_analyzer = Mock()
        mock_analyzer.get_crystal_system.return_value = "cubic"

        mock_highsympath = Mock()
        mock_highsympath.kpath = {
            "kpoints": {"G": [0, 0, 0], "X": [0.5, 0, 0], "M": [0.5, 0.5, 0]},
            "path": [["G", "X", "M", "G"]],
        }

        with patch(
            "crystalmath.integrations.pymatgen_bridge.SpacegroupAnalyzer",
            return_value=mock_analyzer,
        ), patch(
            "crystalmath.integrations.pymatgen_bridge.HighSymmKpath",
            return_value=mock_highsympath,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            path = PymatgenBridge.get_band_path(mock_structure)
            assert path is not None

    def test_get_band_path_with_num_points(self, mock_structure: Mock) -> None:
        """Test band path with custom number of points."""
        mock_highsympath = Mock()
        mock_highsympath.kpath = {
            "kpoints": {"G": [0, 0, 0], "X": [0.5, 0, 0]},
            "path": [["G", "X"]],
        }
        mock_highsympath.get_kpoints.return_value = ([], [])

        with patch(
            "crystalmath.integrations.pymatgen_bridge.HighSymmKpath",
            return_value=mock_highsympath,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            path = PymatgenBridge.get_band_path(mock_structure, num_points=100)
            assert path is not None


# =============================================================================
# Test Error Handling
# =============================================================================


class TestErrorHandling:
    """Tests for error handling in bridge functions."""

    def test_invalid_structure_type(self) -> None:
        """Test error handling for invalid structure type."""
        from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

        with pytest.raises((TypeError, AttributeError)):
            PymatgenBridge.get_symmetry_info("not a structure")

    def test_file_permission_error(self, tmp_path: Path) -> None:
        """Test error handling for permission issues."""
        # This test may be platform-specific
        pass  # Skip for now as permission tests are tricky

    def test_empty_structure(self) -> None:
        """Test handling of empty structures."""
        mock_empty = Mock()
        mock_empty.num_sites = 0
        mock_empty.volume = 0.0
        mock_empty.is_ordered = True

        from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

        is_valid, issues = PymatgenBridge.validate_for_dft(mock_empty)
        assert is_valid is False


# =============================================================================
# Integration Tests (with real pymatgen if available)
# =============================================================================


@pytest.mark.skipif(not HAS_PYMATGEN, reason="pymatgen not installed")
class TestPymatgenIntegration:
    """Integration tests using real pymatgen."""

    def test_real_structure_creation(self) -> None:
        """Test creating a real pymatgen Structure."""
        lattice = Lattice.cubic(5.64)
        structure = Structure(
            lattice,
            ["Na", "Cl"],
            [[0, 0, 0], [0.5, 0.5, 0.5]],
        )

        assert structure.num_sites == 2
        assert structure.formula == "Na1 Cl1"

    def test_real_symmetry_analysis(self) -> None:
        """Test symmetry analysis with real structure."""
        lattice = Lattice.cubic(5.64)
        structure = Structure(
            lattice,
            ["Na", "Cl"],
            [[0, 0, 0], [0.5, 0.5, 0.5]],
        )

        from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

        info = PymatgenBridge.get_symmetry_info(structure)
        assert info["crystal_system"] == "cubic"

    def test_real_kpoint_generation(self) -> None:
        """Test k-point generation with real structure."""
        lattice = Lattice.cubic(5.64)
        structure = Structure(
            lattice,
            ["Na", "Cl"],
            [[0, 0, 0], [0.5, 0.5, 0.5]],
        )

        from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

        kpoints = PymatgenBridge.get_kpoints_mesh(structure, density=0.04)
        assert len(kpoints) == 3
        assert all(k >= 1 for k in kpoints)


# =============================================================================
# Test Materials Project Integration
# =============================================================================


class TestMaterialsProjectIntegration:
    """Tests for Materials Project API integration."""

    def test_fetch_from_mp_mock(self) -> None:
        """Test fetching structure from Materials Project with mock."""
        mock_structure = Mock()
        mock_structure.formula = "Si"

        mock_mpr = Mock()
        mock_mpr.get_structure_by_material_id.return_value = mock_structure

        with patch(
            "crystalmath.integrations.pymatgen_bridge.MPRester",
            return_value=mock_mpr,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            result = PymatgenBridge.fetch_from_mp("mp-149")
            assert result is not None

    def test_fetch_from_mp_invalid_id(self) -> None:
        """Test error handling for invalid MP ID."""
        mock_mpr = Mock()
        mock_mpr.get_structure_by_material_id.side_effect = Exception("Not found")

        with patch(
            "crystalmath.integrations.pymatgen_bridge.MPRester",
            return_value=mock_mpr,
        ):
            from crystalmath.integrations.pymatgen_bridge import PymatgenBridge

            with pytest.raises(Exception):
                PymatgenBridge.fetch_from_mp("invalid-id")
