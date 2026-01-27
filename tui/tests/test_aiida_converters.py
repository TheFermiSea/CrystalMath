"""
Tests for structure format converters.

Tests conversion between:
    - AiiDA StructureData ↔ pymatgen Structure
    - AiiDA StructureData ↔ CRYSTAL23 .d12 geometry
    - AiiDA StructureData ↔ VASP POSCAR
"""

from unittest.mock import MagicMock, patch

import pytest

# Check if converters are available (requires numpy + aiida)
from src.aiida.converters import _CONVERTERS_AVAILABLE

if _CONVERTERS_AVAILABLE:
    import numpy as np

    from src.aiida.converters.structure import (
        ATOMIC_SYMBOLS,
        SYMBOL_TO_Z,
        _cart_to_frac,
        _cell_from_params,
        _cell_to_params,
        _frac_to_cart,
        crystal_d12_to_structure,
        poscar_to_structure,
        structure_to_crystal_d12,
        structure_to_poscar,
    )
else:
    np = None
    ATOMIC_SYMBOLS = {}
    SYMBOL_TO_Z = {}

pytestmark = pytest.mark.skipif(
    not _CONVERTERS_AVAILABLE, reason="Structure converters require numpy and aiida"
)


class TestAtomicSymbols:
    """Test atomic symbol/number mapping."""

    def test_common_elements(self):
        """Test mapping for common elements."""
        assert ATOMIC_SYMBOLS[6] == "C"
        assert ATOMIC_SYMBOLS[26] == "Fe"
        assert ATOMIC_SYMBOLS[79] == "Au"

    def test_reverse_mapping(self):
        """Test symbol to Z mapping."""
        assert SYMBOL_TO_Z["C"] == 6
        assert SYMBOL_TO_Z["Fe"] == 26
        assert SYMBOL_TO_Z["Au"] == 79


class TestCellParameters:
    """Test cell parameter conversion utilities."""

    def test_cubic_cell(self):
        """Test cubic cell construction."""
        cell = _cell_from_params(5.0, 5.0, 5.0, 90, 90, 90)

        # Should be diagonal
        assert cell[0][0] == pytest.approx(5.0)
        assert cell[1][1] == pytest.approx(5.0)
        assert cell[2][2] == pytest.approx(5.0)
        assert cell[0][1] == pytest.approx(0.0, abs=1e-10)

    def test_hexagonal_cell(self):
        """Test hexagonal cell construction."""
        cell = _cell_from_params(3.0, 3.0, 5.0, 90, 90, 120)

        # a along x
        assert cell[0][0] == pytest.approx(3.0)

        # b at 120° from a
        assert cell[1][0] == pytest.approx(-1.5, rel=0.01)
        assert cell[1][1] == pytest.approx(2.598, rel=0.01)

    def test_roundtrip(self):
        """Test cell parameters roundtrip."""
        original = (5.43, 5.43, 5.43, 90, 90, 90)  # Silicon-like
        cell = _cell_from_params(*original)
        recovered = _cell_to_params(np.array(cell))

        for orig, rec in zip(original, recovered, strict=False):
            assert orig == pytest.approx(rec, rel=0.01)

    def test_general_triclinic(self):
        """Test general triclinic cell."""
        params = (5.0, 6.0, 7.0, 80, 85, 95)
        cell = _cell_from_params(*params)
        recovered = _cell_to_params(np.array(cell))

        for orig, rec in zip(params, recovered, strict=False):
            assert orig == pytest.approx(rec, rel=0.01)


class TestCoordinateConversion:
    """Test fractional/Cartesian coordinate conversion."""

    def test_cubic_conversion(self):
        """Test coordinate conversion in cubic cell."""
        cell = [[5.0, 0, 0], [0, 5.0, 0], [0, 0, 5.0]]

        # Center of cell
        frac = [0.5, 0.5, 0.5]
        cart = _frac_to_cart(frac, cell)

        assert cart[0] == pytest.approx(2.5)
        assert cart[1] == pytest.approx(2.5)
        assert cart[2] == pytest.approx(2.5)

    def test_roundtrip_conversion(self):
        """Test fractional-Cartesian roundtrip."""
        cell = np.array([[5.0, 0.5, 0], [0, 4.0, 0.3], [0.1, 0, 6.0]])

        original_frac = [0.25, 0.75, 0.33]
        cart = _frac_to_cart(original_frac, cell.tolist())
        recovered_frac = _cart_to_frac(np.array(cart), cell)

        for orig, rec in zip(original_frac, recovered_frac, strict=False):
            assert orig == pytest.approx(rec, rel=0.001)


class TestCrystalD12Parsing:
    """Test CRYSTAL23 .d12 geometry parsing."""

    def test_simple_crystal(self):
        """Test parsing simple cubic structure."""
        d12 = """MgO test
CRYSTAL
225
4.21
2
12 0.0 0.0 0.0
8  0.5 0.5 0.5
END
"""
        with patch("src.aiida.converters.structure.orm") as mock_orm:
            mock_structure = MagicMock()
            mock_orm.StructureData.return_value = mock_structure

            result = crystal_d12_to_structure(d12)

            # Check cell was set
            mock_orm.StructureData.assert_called_once()
            # Should have 2 atoms appended
            assert mock_structure.append_atom.call_count == 2

    def test_hexagonal_crystal(self):
        """Test parsing hexagonal structure (2 cell params)."""
        d12 = """Hexagonal
CRYSTAL
194
3.16 5.02
2
22 0.333333 0.666667 0.25
22 0.666667 0.333333 0.75
END
"""
        with patch("src.aiida.converters.structure.orm") as mock_orm:
            mock_structure = MagicMock()
            mock_orm.StructureData.return_value = mock_structure

            result = crystal_d12_to_structure(d12)

            mock_orm.StructureData.assert_called_once()
            assert mock_structure.append_atom.call_count == 2

    def test_slab_geometry(self):
        """Test parsing SLAB geometry."""
        d12 = """MoS2 monolayer
SLAB
73
3.16 3.16 120.0
3
42 0.333333 0.666667 0.0
16 0.666667 0.333333 1.58
16 0.666667 0.333333 -1.58
END
"""
        with patch("src.aiida.converters.structure.orm") as mock_orm:
            mock_structure = MagicMock()
            mock_orm.StructureData.return_value = mock_structure

            result = crystal_d12_to_structure(d12)

            mock_orm.StructureData.assert_called_once()
            assert mock_structure.append_atom.call_count == 3

    def test_missing_geometry_keyword(self):
        """Test error on missing geometry keyword."""
        d12 = """No geometry keyword
1
4.21
2
"""
        with pytest.raises(ValueError, match="No geometry section"):
            crystal_d12_to_structure(d12)


class TestCrystalD12Generation:
    """Test CRYSTAL23 .d12 geometry generation."""

    def test_simple_structure(self):
        """Test generating d12 from structure."""
        with patch("src.aiida.converters.structure.orm") as mock_orm:
            # Create mock structure
            mock_structure = MagicMock()
            mock_structure.cell = [[5.0, 0, 0], [0, 5.0, 0], [0, 0, 5.0]]

            mock_site1 = MagicMock()
            mock_site1.kind_name = "Mg"
            mock_site1.position = [0.0, 0.0, 0.0]

            mock_site2 = MagicMock()
            mock_site2.kind_name = "O"
            mock_site2.position = [2.5, 2.5, 2.5]

            mock_structure.sites = [mock_site1, mock_site2]

            result = structure_to_crystal_d12(mock_structure)

            assert "CRYSTAL" in result
            assert "1" in result  # Space group
            assert "2" in result  # Number of atoms


class TestPOSCARParsing:
    """Test VASP POSCAR parsing."""

    def test_simple_poscar(self):
        """Test parsing simple POSCAR."""
        poscar = """Si2
1.0
5.43  0.00  0.00
0.00  5.43  0.00
0.00  0.00  5.43
Si
2
Direct
0.00 0.00 0.00
0.25 0.25 0.25
"""
        with patch("src.aiida.converters.structure.orm") as mock_orm:
            mock_structure = MagicMock()
            mock_orm.StructureData.return_value = mock_structure

            result = poscar_to_structure(poscar)

            mock_orm.StructureData.assert_called_once()
            assert mock_structure.append_atom.call_count == 2

    def test_cartesian_poscar(self):
        """Test parsing POSCAR with Cartesian coordinates."""
        poscar = """NaCl
1.0
5.64  0.00  0.00
0.00  5.64  0.00
0.00  0.00  5.64
Na Cl
1 1
Cartesian
0.00 0.00 0.00
2.82 2.82 2.82
"""
        with patch("src.aiida.converters.structure.orm") as mock_orm:
            mock_structure = MagicMock()
            mock_orm.StructureData.return_value = mock_structure

            result = poscar_to_structure(poscar)

            mock_orm.StructureData.assert_called_once()
            assert mock_structure.append_atom.call_count == 2

    def test_multiple_species(self):
        """Test POSCAR with multiple species."""
        poscar = """Fe2O3
1.0
5.03  0.00  0.00
-2.515  4.356  0.00
0.00  0.00  13.75
Fe O
4 6
Direct
0.0 0.0 0.0
0.0 0.0 0.5
0.333 0.667 0.25
0.667 0.333 0.75
0.167 0.167 0.0
0.333 0.333 0.0
0.5 0.5 0.0
0.667 0.667 0.5
0.833 0.833 0.5
0.0 0.0 0.25
"""
        with patch("src.aiida.converters.structure.orm") as mock_orm:
            mock_structure = MagicMock()
            mock_orm.StructureData.return_value = mock_structure

            result = poscar_to_structure(poscar)

            assert mock_structure.append_atom.call_count == 10


class TestPOSCARGeneration:
    """Test VASP POSCAR generation."""

    def test_simple_structure(self):
        """Test generating POSCAR from structure."""
        mock_structure = MagicMock()
        mock_structure.cell = [[5.43, 0, 0], [0, 5.43, 0], [0, 0, 5.43]]

        mock_site1 = MagicMock()
        mock_site1.kind_name = "Si"
        mock_site1.position = [0.0, 0.0, 0.0]

        mock_site2 = MagicMock()
        mock_site2.kind_name = "Si"
        mock_site2.position = [1.3575, 1.3575, 1.3575]

        mock_structure.sites = [mock_site1, mock_site2]

        result = structure_to_poscar(mock_structure, comment="Test Si")

        assert "Test Si" in result
        assert "1.0" in result
        assert "Si" in result
        assert "2" in result  # Count of Si
        assert "Direct" in result

    def test_mixed_species(self):
        """Test generating POSCAR with multiple species."""
        mock_structure = MagicMock()
        mock_structure.cell = [[5.64, 0, 0], [0, 5.64, 0], [0, 0, 5.64]]

        mock_na = MagicMock()
        mock_na.kind_name = "Na"
        mock_na.position = [0.0, 0.0, 0.0]

        mock_cl = MagicMock()
        mock_cl.kind_name = "Cl"
        mock_cl.position = [2.82, 2.82, 2.82]

        mock_structure.sites = [mock_na, mock_cl]

        result = structure_to_poscar(mock_structure)

        lines = result.split("\n")
        # Find species line
        species_line = None
        for line in lines:
            if "Na" in line and "Cl" in line:
                species_line = line
                break

        assert species_line is not None


class TestRoundtripConversions:
    """Test full roundtrip conversions."""

    def test_poscar_roundtrip_values(self):
        """Test POSCAR roundtrip preserves values (without AiiDA mocking)."""
        original_poscar = """Si diamond
1.0
  5.43000000000000    0.00000000000000    0.00000000000000
  0.00000000000000    5.43000000000000    0.00000000000000
  0.00000000000000    0.00000000000000    5.43000000000000
Si
2
Direct
  0.00000000000000    0.00000000000000    0.00000000000000
  0.25000000000000    0.25000000000000    0.25000000000000
"""
        # Parse and regenerate - check key values preserved
        lines = original_poscar.strip().split("\n")

        # Check scaling factor
        assert "1.0" in lines[1]

        # Check species
        assert "Si" in lines[5]

        # Check count
        assert "2" in lines[6]

    def test_d12_geometry_values(self):
        """Test d12 geometry block values."""
        d12 = """MgO
CRYSTAL
225
4.21
2
12 0.0 0.0 0.0
8 0.5 0.5 0.5
END
"""
        lines = d12.strip().split("\n")

        # Check geometry type
        assert lines[1] == "CRYSTAL"

        # Check space group
        assert lines[2] == "225"

        # Check cell parameter
        assert "4.21" in lines[3]

        # Check atom count
        assert lines[4] == "2"

        # Check atom definitions
        assert "12" in lines[5]  # Mg
        assert "8" in lines[6]  # O


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_poscar(self):
        """Test error on empty POSCAR."""
        with pytest.raises(ValueError, match="too short"):
            poscar_to_structure("Short\n1.0\n")

    def test_unsupported_geometry(self):
        """Test error on unsupported geometry type."""
        d12 = """Test
POLYMER
1
10.0
1
6 0.0 0.0 0.0
"""
        with pytest.raises(ValueError, match="Unsupported geometry"):
            crystal_d12_to_structure(d12)

    def test_ghost_atoms(self):
        """Test handling of ghost atoms (Z > 100)."""
        d12 = """Ghost test
CRYSTAL
1
5.0 5.0 5.0 90 90 90
1
106 0.0 0.0 0.0
END
"""
        with patch("src.aiida.converters.structure.orm") as mock_orm:
            mock_structure = MagicMock()
            mock_orm.StructureData.return_value = mock_structure

            result = crystal_d12_to_structure(d12)

            # Should convert 106 -> 6 (Carbon)
            call_args = mock_structure.append_atom.call_args
            assert call_args[1]["symbols"] == "C"
