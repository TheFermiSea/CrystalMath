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
import tempfile

# Import the module under test
from crystalmath.integrations import pymatgen_bridge

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
# Test Exceptions
# =============================================================================


class TestExceptions:
    """Tests for custom exceptions in pymatgen_bridge."""

    def test_pymatgen_bridge_error_exists(self) -> None:
        """Test PymatgenBridgeError exception exists."""
        assert hasattr(pymatgen_bridge, "PymatgenBridgeError")
        exc = pymatgen_bridge.PymatgenBridgeError("test")
        assert str(exc) == "test"

    def test_structure_load_error_exists(self) -> None:
        """Test StructureLoadError exception exists."""
        assert hasattr(pymatgen_bridge, "StructureLoadError")
        exc = pymatgen_bridge.StructureLoadError("file not found")
        assert "file not found" in str(exc)
        assert isinstance(exc, pymatgen_bridge.PymatgenBridgeError)

    def test_structure_conversion_error_exists(self) -> None:
        """Test StructureConversionError exception exists."""
        assert hasattr(pymatgen_bridge, "StructureConversionError")
        exc = pymatgen_bridge.StructureConversionError("conversion failed")
        assert isinstance(exc, pymatgen_bridge.PymatgenBridgeError)

    def test_validation_error_exists(self) -> None:
        """Test ValidationError exception exists."""
        assert hasattr(pymatgen_bridge, "ValidationError")
        exc = pymatgen_bridge.ValidationError("validation failed")
        assert isinstance(exc, pymatgen_bridge.PymatgenBridgeError)

    def test_dependency_error_exists(self) -> None:
        """Test DependencyError exception exists."""
        assert hasattr(pymatgen_bridge, "DependencyError")
        exc = pymatgen_bridge.DependencyError("missing dependency")
        assert isinstance(exc, pymatgen_bridge.PymatgenBridgeError)


# =============================================================================
# Test Enums
# =============================================================================


class TestEnums:
    """Tests for enum classes."""

    def test_crystal_system_enum(self) -> None:
        """Test CrystalSystem enum values."""
        from crystalmath.integrations.pymatgen_bridge import CrystalSystem

        assert CrystalSystem.CUBIC.value == "cubic"
        assert CrystalSystem.HEXAGONAL.value == "hexagonal"
        assert CrystalSystem.TETRAGONAL.value == "tetragonal"
        assert CrystalSystem.ORTHORHOMBIC.value == "orthorhombic"
        assert CrystalSystem.MONOCLINIC.value == "monoclinic"
        assert CrystalSystem.TRICLINIC.value == "triclinic"
        assert CrystalSystem.TRIGONAL.value == "trigonal"

    def test_dimensionality_enum(self) -> None:
        """Test Dimensionality enum values."""
        from crystalmath.integrations.pymatgen_bridge import Dimensionality

        assert Dimensionality.MOLECULE == 0
        assert Dimensionality.POLYMER == 1
        assert Dimensionality.SLAB == 2
        assert Dimensionality.BULK == 3


# =============================================================================
# Test Data Classes
# =============================================================================


class TestDataClasses:
    """Tests for data classes."""

    def test_symmetry_info_creation(self) -> None:
        """Test SymmetryInfo dataclass creation."""
        from crystalmath.integrations.pymatgen_bridge import (
            SymmetryInfo,
            CrystalSystem,
        )

        info = SymmetryInfo(
            space_group_number=225,
            space_group_symbol="Fm-3m",
            point_group="m-3m",
            crystal_system=CrystalSystem.CUBIC,
        )

        assert info.space_group_number == 225
        assert info.space_group_symbol == "Fm-3m"
        assert info.point_group == "m-3m"
        assert info.crystal_system == CrystalSystem.CUBIC

    def test_symmetry_info_defaults(self) -> None:
        """Test SymmetryInfo default values."""
        from crystalmath.integrations.pymatgen_bridge import (
            SymmetryInfo,
            CrystalSystem,
        )

        info = SymmetryInfo(
            space_group_number=1,
            space_group_symbol="P1",
            point_group="1",
            crystal_system=CrystalSystem.TRICLINIC,
        )

        assert info.hall_symbol == ""
        assert info.is_centrosymmetric is False
        assert info.wyckoff_symbols == []
        assert info.symmetry_operations == 0
        assert info.tolerance == 0.01

    def test_symmetry_info_to_dict(self) -> None:
        """Test SymmetryInfo to_dict method."""
        from crystalmath.integrations.pymatgen_bridge import (
            SymmetryInfo,
            CrystalSystem,
        )

        info = SymmetryInfo(
            space_group_number=225,
            space_group_symbol="Fm-3m",
            point_group="m-3m",
            crystal_system=CrystalSystem.CUBIC,
            is_centrosymmetric=True,
        )

        d = info.to_dict()
        assert d["space_group_number"] == 225
        assert d["space_group_symbol"] == "Fm-3m"
        assert d["crystal_system"] == "cubic"
        assert d["is_centrosymmetric"] is True

    def test_structure_metadata_creation(self) -> None:
        """Test StructureMetadata dataclass creation."""
        from crystalmath.integrations.pymatgen_bridge import StructureMetadata

        meta = StructureMetadata(
            source="cif",
            source_id="test.cif",
            formula="Na1 Cl1",
            reduced_formula="NaCl",
            num_sites=2,
            volume=45.0,
            density=2.16,
        )

        assert meta.source == "cif"
        assert meta.formula == "Na1 Cl1"
        assert meta.num_sites == 2

    def test_structure_metadata_defaults(self) -> None:
        """Test StructureMetadata default values."""
        from crystalmath.integrations.pymatgen_bridge import StructureMetadata

        meta = StructureMetadata(source="unknown")

        assert meta.source_id is None
        assert meta.formula == ""
        assert meta.num_sites == 0
        assert meta.is_ordered is True


# =============================================================================
# Fixtures
# =============================================================================


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
# Test Structure Loading - structure_from_cif
# =============================================================================


class TestStructureFromCIF:
    """Tests for loading structures from CIF files."""

    @pytest.mark.skipif(not HAS_PYMATGEN, reason="pymatgen not installed")
    def test_structure_from_cif_file_not_found(self, tmp_path: Path) -> None:
        """Test error handling for missing CIF file."""
        from crystalmath.integrations.pymatgen_bridge import (
            structure_from_cif,
            StructureLoadError,
        )

        nonexistent = tmp_path / "nonexistent.cif"
        with pytest.raises(StructureLoadError):
            structure_from_cif(str(nonexistent))

    @pytest.mark.skipif(not HAS_PYMATGEN, reason="pymatgen not installed")
    def test_structure_from_cif_real_file(self, cif_file: Path) -> None:
        """Test loading structure from real CIF file."""
        from crystalmath.integrations.pymatgen_bridge import structure_from_cif

        structure = structure_from_cif(cif_file)
        assert structure is not None
        assert structure.num_sites == 2

    def test_structure_from_cif_raises_without_pymatgen(self, tmp_path: Path) -> None:
        """Test that function raises DependencyError when pymatgen not installed."""
        if HAS_PYMATGEN:
            pytest.skip("pymatgen is installed, cannot test missing dependency")

        from crystalmath.integrations.pymatgen_bridge import (
            structure_from_cif,
            DependencyError,
        )

        cif_path = tmp_path / "test.cif"
        cif_path.write_text("dummy content")
        with pytest.raises(DependencyError):
            structure_from_cif(str(cif_path))


# =============================================================================
# Test Structure Loading - structure_from_poscar
# =============================================================================


class TestStructureFromPOSCAR:
    """Tests for loading structures from POSCAR files."""

    @pytest.mark.skipif(not HAS_PYMATGEN, reason="pymatgen not installed")
    def test_structure_from_poscar_file_not_found(self, tmp_path: Path) -> None:
        """Test error handling for missing POSCAR file."""
        from crystalmath.integrations.pymatgen_bridge import (
            structure_from_poscar,
            StructureLoadError,
        )

        nonexistent = tmp_path / "POSCAR_MISSING"
        with pytest.raises(StructureLoadError):
            structure_from_poscar(str(nonexistent))

    @pytest.mark.skipif(not HAS_PYMATGEN, reason="pymatgen not installed")
    def test_structure_from_poscar_real_file(self, poscar_file: Path) -> None:
        """Test loading structure from real POSCAR file."""
        from crystalmath.integrations.pymatgen_bridge import structure_from_poscar

        structure = structure_from_poscar(poscar_file)
        assert structure is not None
        assert structure.num_sites == 2

    def test_structure_from_poscar_raises_without_pymatgen(self, tmp_path: Path) -> None:
        """Test that function raises DependencyError when pymatgen not installed."""
        if HAS_PYMATGEN:
            pytest.skip("pymatgen is installed, cannot test missing dependency")

        from crystalmath.integrations.pymatgen_bridge import (
            structure_from_poscar,
            DependencyError,
        )

        poscar_path = tmp_path / "POSCAR"
        poscar_path.write_text("dummy content")
        with pytest.raises(DependencyError):
            structure_from_poscar(str(poscar_path))


# =============================================================================
# Test Structure Loading - structure_from_file
# =============================================================================


class TestStructureFromFile:
    """Tests for loading structures from generic files."""

    @pytest.mark.skipif(not HAS_PYMATGEN, reason="pymatgen not installed")
    def test_structure_from_file_not_found(self, tmp_path: Path) -> None:
        """Test error handling for missing file."""
        from crystalmath.integrations.pymatgen_bridge import (
            structure_from_file,
            StructureLoadError,
        )

        nonexistent = tmp_path / "missing.xyz"
        with pytest.raises(StructureLoadError):
            structure_from_file(str(nonexistent))

    @pytest.mark.skipif(not HAS_PYMATGEN, reason="pymatgen not installed")
    def test_structure_from_file_cif(self, cif_file: Path) -> None:
        """Test loading CIF via generic loader."""
        from crystalmath.integrations.pymatgen_bridge import structure_from_file

        structure = structure_from_file(cif_file)
        assert structure is not None

    def test_structure_from_file_raises_without_pymatgen(self, tmp_path: Path) -> None:
        """Test that function raises DependencyError when pymatgen not installed."""
        if HAS_PYMATGEN:
            pytest.skip("pymatgen is installed, cannot test missing dependency")

        from crystalmath.integrations.pymatgen_bridge import (
            structure_from_file,
            DependencyError,
        )

        file_path = tmp_path / "test.xyz"
        file_path.write_text("dummy content")
        with pytest.raises(DependencyError):
            structure_from_file(str(file_path))


# =============================================================================
# Test Structure Loading - structure_from_mp (Materials Project)
# =============================================================================


class TestStructureFromMP:
    """Tests for loading structures from Materials Project."""

    @pytest.mark.skip(reason="Requires Materials Project API key and network")
    def test_structure_from_mp_real(self) -> None:
        """Test fetching from Materials Project (requires API key)."""
        from crystalmath.integrations.pymatgen_bridge import structure_from_mp

        structure = structure_from_mp("mp-149")  # Silicon
        assert structure is not None

    @pytest.mark.skip(reason="Requires mp_api package to be installed")
    def test_structure_from_mp_normalizes_id(self) -> None:
        """Test that MP ID is normalized."""
        # This test would require mp_api to be installed
        pass


# =============================================================================
# Test Structure Loading - structure_from_cod (COD)
# =============================================================================


class TestStructureFromCOD:
    """Tests for loading structures from COD."""

    @pytest.mark.skip(reason="Requires network access to COD")
    def test_structure_from_cod_real(self) -> None:
        """Test fetching from COD (requires network)."""
        from crystalmath.integrations.pymatgen_bridge import structure_from_cod

        structure = structure_from_cod(1000041)  # NaCl
        assert structure is not None


# =============================================================================
# Test AiiDA Conversion
# =============================================================================


class TestAiiDAConversion:
    """Tests for AiiDA StructureData conversion."""

    @pytest.mark.skip(reason="Requires AiiDA installation")
    def test_to_aiida_structure_real(self) -> None:
        """Test conversion to AiiDA with real dependencies."""
        pass

    def test_to_aiida_structure_raises_on_missing_dep(self) -> None:
        """Test that to_aiida_structure raises DependencyError if AiiDA missing."""
        mock_structure = Mock()

        with patch.object(
            pymatgen_bridge,
            "_check_pymatgen",
            return_value=None,
        ), patch.object(
            pymatgen_bridge,
            "_check_aiida",
            side_effect=pymatgen_bridge.DependencyError("aiida not installed"),
        ):
            with pytest.raises(pymatgen_bridge.DependencyError):
                pymatgen_bridge.to_aiida_structure(mock_structure)

    def test_from_aiida_structure_raises_on_missing_dep(self) -> None:
        """Test that from_aiida_structure raises DependencyError if AiiDA missing."""
        mock_node = Mock()

        with patch.object(
            pymatgen_bridge,
            "_check_pymatgen",
            return_value=None,
        ), patch.object(
            pymatgen_bridge,
            "_check_aiida",
            side_effect=pymatgen_bridge.DependencyError("aiida not installed"),
        ):
            with pytest.raises(pymatgen_bridge.DependencyError):
                pymatgen_bridge.from_aiida_structure(mock_node)


# =============================================================================
# Test ASE Conversion
# =============================================================================


class TestASEConversion:
    """Tests for ASE Atoms conversion."""

    @pytest.mark.skip(reason="Requires ASE installation")
    def test_to_ase_atoms_real(self) -> None:
        """Test conversion to ASE with real dependencies."""
        pass

    def test_to_ase_atoms_raises_on_missing_dep(self) -> None:
        """Test that to_ase_atoms raises DependencyError if ASE missing."""
        mock_structure = Mock()

        with patch.object(
            pymatgen_bridge,
            "_check_pymatgen",
            return_value=None,
        ), patch.object(
            pymatgen_bridge,
            "_check_ase",
            side_effect=pymatgen_bridge.DependencyError("ASE not installed"),
        ):
            with pytest.raises(pymatgen_bridge.DependencyError):
                pymatgen_bridge.to_ase_atoms(mock_structure)

    def test_from_ase_atoms_raises_on_missing_dep(self) -> None:
        """Test that from_ase_atoms raises DependencyError if ASE missing."""
        mock_atoms = Mock()

        with patch.object(
            pymatgen_bridge,
            "_check_pymatgen",
            return_value=None,
        ), patch.object(
            pymatgen_bridge,
            "_check_ase",
            side_effect=pymatgen_bridge.DependencyError("ASE not installed"),
        ):
            with pytest.raises(pymatgen_bridge.DependencyError):
                pymatgen_bridge.from_ase_atoms(mock_atoms)


# =============================================================================
# Test convert_structure
# =============================================================================


class TestConvertStructure:
    """Tests for the generic convert_structure function."""

    @pytest.mark.skipif(not HAS_PYMATGEN, reason="pymatgen not installed")
    def test_convert_structure_invalid_target(self) -> None:
        """Test error for invalid target format."""
        # Create a real structure to test with
        lattice = Lattice.cubic(5.64)
        structure = Structure(
            lattice,
            ["Na", "Cl"],
            [[0, 0, 0], [0.5, 0.5, 0.5]],
        )

        with pytest.raises(ValueError):
            pymatgen_bridge.convert_structure(structure, "invalid")

    @pytest.mark.skipif(not HAS_PYMATGEN, reason="pymatgen not installed")
    def test_convert_structure_to_pymatgen(self) -> None:
        """Test conversion to pymatgen (identity)."""
        lattice = Lattice.cubic(5.64)
        structure = Structure(
            lattice,
            ["Na", "Cl"],
            [[0, 0, 0], [0.5, 0.5, 0.5]],
        )

        result = pymatgen_bridge.convert_structure(structure, "pymatgen")
        assert result is structure


# =============================================================================
# Test Symmetry Analysis
# =============================================================================


class TestSymmetryAnalysis:
    """Tests for symmetry analysis functions."""

    @pytest.mark.skipif(not HAS_PYMATGEN, reason="pymatgen not installed")
    def test_get_symmetry_info_returns_dataclass(self) -> None:
        """Test that get_symmetry_info returns SymmetryInfo dataclass."""
        from crystalmath.integrations.pymatgen_bridge import (
            get_symmetry_info,
            SymmetryInfo,
        )

        # Create a simple cubic structure
        lattice = Lattice.cubic(5.64)
        structure = Structure(
            lattice,
            ["Na", "Cl"],
            [[0, 0, 0], [0.5, 0.5, 0.5]],
        )

        info = get_symmetry_info(structure)
        assert isinstance(info, SymmetryInfo)
        assert info.space_group_number == 225
        assert info.crystal_system.value == "cubic"

    @pytest.mark.skipif(not HAS_PYMATGEN, reason="pymatgen not installed")
    def test_get_symmetry_info_with_tolerance(self) -> None:
        """Test symmetry analysis with custom tolerance."""
        from crystalmath.integrations.pymatgen_bridge import get_symmetry_info

        lattice = Lattice.cubic(5.64)
        structure = Structure(
            lattice,
            ["Na", "Cl"],
            [[0, 0, 0], [0.5, 0.5, 0.5]],
        )

        info = get_symmetry_info(structure, symprec=0.1)
        assert info.tolerance == 0.1


# =============================================================================
# Test Dimensionality Detection
# =============================================================================


class TestDimensionalityDetection:
    """Tests for dimensionality detection."""

    @pytest.mark.skipif(not HAS_PYMATGEN, reason="pymatgen not installed")
    def test_get_dimensionality_bulk(self) -> None:
        """Test dimensionality detection for bulk structure."""
        from crystalmath.integrations.pymatgen_bridge import get_dimensionality

        lattice = Lattice.cubic(5.64)
        structure = Structure(
            lattice,
            ["Na", "Cl"],
            [[0, 0, 0], [0.5, 0.5, 0.5]],
        )

        dim = get_dimensionality(structure)
        assert dim == 3  # Bulk 3D structure


# =============================================================================
# Test DFT Validation
# =============================================================================


class TestDFTValidation:
    """Tests for DFT validation checks."""

    @pytest.mark.skipif(not HAS_PYMATGEN, reason="pymatgen not installed")
    def test_validate_for_dft_valid_structure(self) -> None:
        """Test validation of a valid structure."""
        from crystalmath.integrations.pymatgen_bridge import validate_for_dft

        lattice = Lattice.cubic(5.64)
        structure = Structure(
            lattice,
            ["Na", "Cl"],
            [[0, 0, 0], [0.5, 0.5, 0.5]],
        )

        is_valid, issues = validate_for_dft(structure)
        assert is_valid is True
        assert isinstance(issues, list)

    @pytest.mark.skipif(not HAS_PYMATGEN, reason="pymatgen not installed")
    def test_validate_for_dft_returns_tuple(self) -> None:
        """Test that validate_for_dft returns (bool, list) tuple."""
        from crystalmath.integrations.pymatgen_bridge import validate_for_dft

        lattice = Lattice.cubic(5.64)
        structure = Structure(
            lattice,
            ["Na", "Cl"],
            [[0, 0, 0], [0.5, 0.5, 0.5]],
        )

        result = validate_for_dft(structure)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], list)

    @pytest.mark.skipif(not HAS_PYMATGEN, reason="pymatgen not installed")
    def test_validate_for_dft_custom_max_atoms(self) -> None:
        """Test validation with custom max_atoms parameter."""
        from crystalmath.integrations.pymatgen_bridge import validate_for_dft

        # Create a 2x2x2 supercell (16 atoms)
        lattice = Lattice.cubic(5.64)
        structure = Structure(
            lattice,
            ["Na", "Cl"],
            [[0, 0, 0], [0.5, 0.5, 0.5]],
        )
        supercell = structure * [2, 2, 2]

        # Should pass with default max (500)
        is_valid_default, _ = validate_for_dft(supercell)
        assert is_valid_default is True

        # Should trigger warning with strict limit
        _, issues = validate_for_dft(supercell, max_atoms=10)
        assert any("atoms" in issue.lower() for issue in issues)


# =============================================================================
# Test Structure Metadata
# =============================================================================


class TestStructureMetadata:
    """Tests for structure metadata extraction."""

    @pytest.mark.skipif(not HAS_PYMATGEN, reason="pymatgen not installed")
    def test_get_structure_metadata(self) -> None:
        """Test metadata extraction from structure."""
        from crystalmath.integrations.pymatgen_bridge import (
            get_structure_metadata,
            StructureMetadata,
        )

        lattice = Lattice.cubic(5.64)
        structure = Structure(
            lattice,
            ["Na", "Cl"],
            [[0, 0, 0], [0.5, 0.5, 0.5]],
        )

        meta = get_structure_metadata(structure)
        assert isinstance(meta, StructureMetadata)
        assert meta.num_sites == 2
        assert meta.volume > 0
        assert "Na" in meta.formula
        assert "Cl" in meta.formula


# =============================================================================
# Test Module Exports
# =============================================================================


class TestModuleExports:
    """Tests for module __all__ exports."""

    def test_exceptions_exported(self) -> None:
        """Test that all exceptions are exported."""
        from crystalmath.integrations.pymatgen_bridge import __all__

        assert "PymatgenBridgeError" in __all__
        assert "StructureLoadError" in __all__
        assert "StructureConversionError" in __all__
        assert "ValidationError" in __all__
        assert "DependencyError" in __all__

    def test_enums_exported(self) -> None:
        """Test that enums are exported."""
        from crystalmath.integrations.pymatgen_bridge import __all__

        assert "CrystalSystem" in __all__
        assert "Dimensionality" in __all__

    def test_dataclasses_exported(self) -> None:
        """Test that dataclasses are exported."""
        from crystalmath.integrations.pymatgen_bridge import __all__

        assert "SymmetryInfo" in __all__
        assert "StructureMetadata" in __all__

    def test_loading_functions_exported(self) -> None:
        """Test that loading functions are exported."""
        from crystalmath.integrations.pymatgen_bridge import __all__

        assert "structure_from_cif" in __all__
        assert "structure_from_poscar" in __all__
        assert "structure_from_mp" in __all__
        assert "structure_from_cod" in __all__
        assert "structure_from_file" in __all__

    def test_conversion_functions_exported(self) -> None:
        """Test that conversion functions are exported."""
        from crystalmath.integrations.pymatgen_bridge import __all__

        assert "to_aiida_structure" in __all__
        assert "from_aiida_structure" in __all__
        assert "to_ase_atoms" in __all__
        assert "from_ase_atoms" in __all__
        assert "convert_structure" in __all__

    def test_analysis_functions_exported(self) -> None:
        """Test that analysis functions are exported."""
        from crystalmath.integrations.pymatgen_bridge import __all__

        assert "get_symmetry_info" in __all__
        assert "get_dimensionality" in __all__
        assert "validate_for_dft" in __all__
        assert "get_structure_metadata" in __all__


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
        assert "Na" in structure.formula
        assert "Cl" in structure.formula

    def test_real_symmetry_analysis(self) -> None:
        """Test symmetry analysis with real structure."""
        from crystalmath.integrations.pymatgen_bridge import get_symmetry_info

        lattice = Lattice.cubic(5.64)
        structure = Structure(
            lattice,
            ["Na", "Cl"],
            [[0, 0, 0], [0.5, 0.5, 0.5]],
        )

        info = get_symmetry_info(structure)
        assert info.crystal_system.value == "cubic"
        assert info.space_group_number == 225

    def test_full_workflow_cif_to_validation(self, cif_file: Path) -> None:
        """Test full workflow from CIF file to validation."""
        from crystalmath.integrations.pymatgen_bridge import (
            structure_from_cif,
            get_symmetry_info,
            validate_for_dft,
            get_structure_metadata,
        )

        # Load structure
        structure = structure_from_cif(cif_file)
        assert structure is not None

        # Analyze symmetry
        sym_info = get_symmetry_info(structure)
        assert sym_info.space_group_number > 0

        # Validate for DFT
        is_valid, issues = validate_for_dft(structure)
        assert is_valid is True

        # Get metadata
        meta = get_structure_metadata(structure)
        assert meta.num_sites == structure.num_sites
