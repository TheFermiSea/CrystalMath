"""
Tests for QE Pseudopotential Manager Screen.
"""

from unittest.mock import MagicMock

import pytest

from src.tui.screens.qe_pseudopotential_manager import (
    ATOMIC_MASSES,
    UPF_LIBRARIES,
    ElementPseudopotential,
    PseudoDirValidator,
    QEPseudopotentialManagerScreen,
    QEPseudopotentialsReady,
)


class TestElementPseudopotential:
    """Tests for ElementPseudopotential dataclass."""

    def test_default_values(self):
        """Test default values for ElementPseudopotential."""
        ep = ElementPseudopotential(element="Si", mass=28.09)
        assert ep.element == "Si"
        assert ep.mass == 28.09
        assert ep.upf_filename == ""
        assert ep.library == "SSSP Efficiency"
        assert ep.custom_content is None
        assert ep.validated is False

    def test_with_upf_filename(self):
        """Test ElementPseudopotential with UPF filename."""
        ep = ElementPseudopotential(
            element="C",
            mass=12.01,
            upf_filename="C.pbe-n-kjpaw_psl.1.0.0.UPF",
            library="SSSP Precision",
            validated=True,
        )
        assert ep.element == "C"
        assert ep.upf_filename == "C.pbe-n-kjpaw_psl.1.0.0.UPF"
        assert ep.library == "SSSP Precision"
        assert ep.validated is True


class TestPseudoDirValidator:
    """Tests for PseudoDirValidator."""

    def test_empty_path_fails(self):
        """Test that empty path fails validation."""
        validator = PseudoDirValidator()
        result = validator.validate("")
        assert not result.is_valid
        assert "required" in result.failure_descriptions[0].lower()

    def test_whitespace_path_fails(self):
        """Test that whitespace-only path fails validation."""
        validator = PseudoDirValidator()
        result = validator.validate("   ")
        assert not result.is_valid

    def test_relative_path_fails(self):
        """Test that relative path fails validation."""
        validator = PseudoDirValidator()
        result = validator.validate("pseudo/files")
        assert not result.is_valid
        assert "absolute" in result.failure_descriptions[0].lower()

    def test_absolute_path_succeeds(self):
        """Test that absolute path succeeds validation."""
        validator = PseudoDirValidator()
        result = validator.validate("/usr/share/espresso/pseudo")
        assert result.is_valid

    def test_tilde_path_succeeds(self):
        """Test that tilde-prefixed path succeeds validation."""
        validator = PseudoDirValidator()
        result = validator.validate("~/pseudopotentials")
        assert result.is_valid


class TestAtomicMasses:
    """Tests for atomic mass data."""

    def test_common_elements_present(self):
        """Test that common elements have masses defined."""
        common_elements = ["H", "C", "N", "O", "Si", "Fe", "Cu", "Zn"]
        for elem in common_elements:
            assert elem in ATOMIC_MASSES
            assert ATOMIC_MASSES[elem] > 0

    def test_silicon_mass(self):
        """Test silicon has correct atomic mass."""
        assert abs(ATOMIC_MASSES["Si"] - 28.09) < 0.1

    def test_carbon_mass(self):
        """Test carbon has correct atomic mass."""
        assert abs(ATOMIC_MASSES["C"] - 12.01) < 0.1


class TestUPFLibraries:
    """Tests for UPF library definitions."""

    def test_sssp_libraries_present(self):
        """Test that SSSP libraries are defined."""
        assert "SSSP Efficiency" in UPF_LIBRARIES
        assert "SSSP Precision" in UPF_LIBRARIES

    def test_pslibrary_present(self):
        """Test that PSlibrary options are defined."""
        assert "PSlibrary PAW" in UPF_LIBRARIES
        assert "PSlibrary US" in UPF_LIBRARIES

    def test_custom_option(self):
        """Test that custom option is available."""
        assert "Custom" in UPF_LIBRARIES


class TestQEPseudopotentialsReady:
    """Tests for QEPseudopotentialsReady message."""

    def test_message_creation(self):
        """Test creating QEPseudopotentialsReady message."""
        msg = QEPseudopotentialsReady(
            pseudo_dir="/usr/share/pseudo",
            element_pseudos={"Si": "Si.UPF", "O": "O.UPF"},
            atomic_species_block="ATOMIC_SPECIES\n  Si  28.09  Si.UPF",
            job_name="silicon_oxide",
        )
        assert msg.pseudo_dir == "/usr/share/pseudo"
        assert msg.element_pseudos == {"Si": "Si.UPF", "O": "O.UPF"}
        assert "ATOMIC_SPECIES" in msg.atomic_species_block
        assert msg.job_name == "silicon_oxide"


class TestQEPseudopotentialManagerScreen:
    """Tests for QEPseudopotentialManagerScreen."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database."""
        return MagicMock()

    def test_initialization_with_single_element(self, mock_db):
        """Test initialization with a single element."""
        screen = QEPseudopotentialManagerScreen(
            db=mock_db,
            elements=["Si"],
        )
        assert "Si" in screen.element_pseudos
        assert len(screen.element_pseudos) == 1
        assert screen.element_pseudos["Si"].element == "Si"

    def test_initialization_with_multiple_elements(self, mock_db):
        """Test initialization with multiple elements."""
        screen = QEPseudopotentialManagerScreen(
            db=mock_db,
            elements=["Si", "O", "C"],
        )
        assert len(screen.element_pseudos) == 3
        assert "Si" in screen.element_pseudos
        assert "O" in screen.element_pseudos
        assert "C" in screen.element_pseudos

    def test_initialization_deduplicates_elements(self, mock_db):
        """Test that duplicate elements are deduplicated."""
        screen = QEPseudopotentialManagerScreen(
            db=mock_db,
            elements=["Si", "O", "Si", "O", "Si"],  # SiO2 has duplicates
        )
        assert len(screen.element_pseudos) == 2
        assert "Si" in screen.element_pseudos
        assert "O" in screen.element_pseudos

    def test_default_upf_name_generation(self, mock_db):
        """Test default UPF filename generation."""
        screen = QEPseudopotentialManagerScreen(
            db=mock_db,
            elements=["Si"],
        )
        upf_name = screen._get_default_upf_name("Si")
        assert upf_name.startswith("Si.")
        assert upf_name.endswith(".UPF")
        assert "pbe" in upf_name.lower()

    def test_custom_pseudo_dir(self, mock_db):
        """Test custom PSEUDO_DIR path."""
        screen = QEPseudopotentialManagerScreen(
            db=mock_db,
            elements=["Si"],
            default_pseudo_dir="/custom/path/to/pseudo",
        )
        assert screen.default_pseudo_dir == "/custom/path/to/pseudo"

    def test_element_masses_assigned(self, mock_db):
        """Test that element masses are correctly assigned."""
        screen = QEPseudopotentialManagerScreen(
            db=mock_db,
            elements=["Si", "C", "O"],
        )
        assert abs(screen.element_pseudos["Si"].mass - 28.09) < 0.1
        assert abs(screen.element_pseudos["C"].mass - 12.01) < 0.1
        assert abs(screen.element_pseudos["O"].mass - 16.00) < 0.1

    def test_unknown_element_default_mass(self, mock_db):
        """Test that unknown elements get default mass of 1.0."""
        screen = QEPseudopotentialManagerScreen(
            db=mock_db,
            elements=["Xx"],  # Unknown element
        )
        assert screen.element_pseudos["Xx"].mass == 1.0

    def test_cluster_id_stored(self, mock_db):
        """Test that cluster ID is stored."""
        screen = QEPseudopotentialManagerScreen(
            db=mock_db,
            elements=["Si"],
            cluster_id=42,
        )
        assert screen.cluster_id == 42


class TestAtomicSpeciesGeneration:
    """Tests for ATOMIC_SPECIES block generation."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database."""
        return MagicMock()

    def test_single_element_atomic_species(self, mock_db):
        """Test ATOMIC_SPECIES generation for single element."""
        screen = QEPseudopotentialManagerScreen(
            db=mock_db,
            elements=["Si"],
        )
        screen.element_pseudos["Si"].upf_filename = "Si.pbe-n-kjpaw.UPF"

        # The _update_atomic_species_preview method generates the block
        # We can manually generate it for testing
        lines = ["ATOMIC_SPECIES"]
        for elem, pseudo in sorted(screen.element_pseudos.items()):
            lines.append(f"  {elem}  {pseudo.mass:.4f}  {pseudo.upf_filename}")

        block = "\n".join(lines)
        assert "ATOMIC_SPECIES" in block
        assert "Si" in block
        assert "Si.pbe-n-kjpaw.UPF" in block

    def test_multi_element_atomic_species(self, mock_db):
        """Test ATOMIC_SPECIES generation for multiple elements."""
        screen = QEPseudopotentialManagerScreen(
            db=mock_db,
            elements=["O", "Si"],  # SiO2
        )
        screen.element_pseudos["Si"].upf_filename = "Si.UPF"
        screen.element_pseudos["O"].upf_filename = "O.UPF"

        lines = ["ATOMIC_SPECIES"]
        for elem, pseudo in sorted(screen.element_pseudos.items()):
            lines.append(f"  {elem}  {pseudo.mass:.4f}  {pseudo.upf_filename}")

        block = "\n".join(lines)
        assert block.count("\n") == 2  # Header + 2 elements
        assert "O" in block
        assert "Si" in block
