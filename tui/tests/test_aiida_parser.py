"""Unit tests for AiiDA CRYSTAL23 Parser.

These tests verify the Crystal23Parser class for parsing CRYSTAL23 output files.
The tests are designed to work without AiiDA installed.
"""

from unittest.mock import MagicMock, patch

import pytest

# Sample output fixtures that can be used by many tests
SAMPLE_OUTPUT_COMPLETED = """
CRYSTAL23 - SCF CALCULATION

CYC   ETOT(AU)      DETOT        CONV
  1  -100.123456   1.0E+00      N
  2  -100.234567   1.1E-01      N
  3  -100.345678   1.1E-02      Y

== SCF ENDED - CONVERGENCE ON ENERGY      E(AU)  -100.345678

TOTAL ENERGY(DFT)(AU) (  3) -100.345678

DIRECT BAND GAP:   5.43 EV

EEEEEEEE TERMINATION  DATE 01 01 2024 TIME 12:00:00.0
"""

SAMPLE_OUTPUT_GEOMETRY_OPT = """
OPTOPTOPTOPT
GEOMETRY OPTIMIZATION

OPTIMIZATION - PAIR DISTANCE EVALUATION  1

CYC   ETOT(AU)      DETOT        CONV
  1  -100.123456   1.0E+00      N
  2  -100.234567   1.1E-01      Y

== SCF ENDED - CONVERGENCE ON ENERGY

CONVERGENCE TESTS SATISFIED  OPTIMIZER ENDS

EEEEEEEE TERMINATION  DATE 01 01 2024
"""


@pytest.fixture
def mock_parser():
    """Create mock parser instance."""
    from src.aiida.calcjobs.parser import Crystal23Parser

    # Create parser instance by bypassing __init__
    parser = object.__new__(Crystal23Parser)
    parser.node = MagicMock()
    parser.retrieved = MagicMock()
    parser.logger = MagicMock()
    parser.exit_codes = MagicMock()
    parser.out = MagicMock()

    return parser


class TestCrystal23ParserManualCompleted:
    """Test manual parsing of completed calculations."""

    def test_parse_manual_completed(self, mock_parser):
        """Test manual parsing of completed calculation."""
        results = mock_parser._parse_manual(SAMPLE_OUTPUT_COMPLETED)

        assert results["parser"] == "manual"
        assert results["completed"] is True
        assert results["scf_converged"] is True
        assert results["final_energy_hartree"] == -100.345678
        assert results["band_gap_ev"] == 5.43
        assert results["band_gap_type"] == "direct"

    def test_parse_manual_scf_iterations(self, mock_parser):
        """Test counting SCF iterations."""
        results = mock_parser._parse_manual(SAMPLE_OUTPUT_COMPLETED)

        assert "scf_iterations" in results
        assert results["scf_iterations"] == 3

    def test_parse_manual_energy_conversion(self, mock_parser):
        """Test energy conversion from Hartree to eV."""
        output = """
        TOTAL ENERGY(DFT)(AU) (  1) -100.0

        EEEEEEEE TERMINATION
        """

        results = mock_parser._parse_manual(output)

        assert results["final_energy_hartree"] == -100.0
        # 1 Hartree = 27.2114 eV
        expected_ev = -100.0 * 27.2114
        assert abs(results["final_energy_ev"] - expected_ev) < 0.01


class TestCrystal23ParserManualGeometryOpt:
    """Test manual parsing of geometry optimization."""

    def test_parse_manual_geometry_opt(self, mock_parser):
        """Test parsing geometry optimization."""
        results = mock_parser._parse_manual(SAMPLE_OUTPUT_GEOMETRY_OPT)

        assert results["completed"] is True
        assert results["is_geometry_optimization"] is True
        assert results["geom_converged"] is True
        assert results["optimization_steps"] == 1


class TestCrystal23ParserManualIncomplete:
    """Test manual parsing of incomplete calculations."""

    def test_parse_manual_not_completed(self, mock_parser):
        """Test parsing incomplete calculation."""
        incomplete_output = """
        CRYSTAL23 - SCF CALCULATION

        CYC   ETOT(AU)      DETOT
          1  -100.123456   1.0E+00
        """

        results = mock_parser._parse_manual(incomplete_output)

        assert results["completed"] is False

    def test_parse_manual_not_converged(self, mock_parser):
        """Test parsing non-converged calculation."""
        not_converged = """
        CYC   ETOT(AU)      DETOT        CONV
          1  -100.123456   1.0E+00      N
          2  -100.234567   1.1E-01      N

        SCF DID NOT CONVERGE

        EEEEEEEE TERMINATION
        """

        results = mock_parser._parse_manual(not_converged)

        assert results["completed"] is False
        assert results["scf_converged"] is False
        assert "error_message" in results


class TestCrystal23ParserManualErrors:
    """Test manual parsing of error conditions."""

    def test_parse_manual_insufficient_memory(self, mock_parser):
        """Test detecting insufficient memory error."""
        error_output = """
        ERROR IN CRYSTAL23 INSUFFICIENT MEMORY
        """

        results = mock_parser._parse_manual(error_output)

        assert "error_message" in results
        assert "memory" in results["error_message"].lower()
        assert results["completed"] is False

    def test_parse_manual_timeout(self, mock_parser):
        """Test detecting timeout error."""
        error_output = """
        ERROR CALCULATION TIMEOUT EXCEEDED
        """

        results = mock_parser._parse_manual(error_output)

        assert "error_message" in results
        assert "timeout" in results["error_message"].lower()


class TestCrystal23ParserBandGap:
    """Test band gap parsing."""

    def test_parse_manual_direct_band_gap(self, mock_parser):
        """Test parsing direct band gap."""
        output = """
        DIRECT BAND GAP:   5.43 EV

        EEEEEEEE TERMINATION
        """

        results = mock_parser._parse_manual(output)

        assert results["band_gap_ev"] == 5.43
        assert results["band_gap_type"] == "direct"

    def test_parse_manual_indirect_band_gap(self, mock_parser):
        """Test parsing indirect band gap."""
        output = """
        INDIRECT BAND GAP:   3.21 EV

        EEEEEEEE TERMINATION
        """

        results = mock_parser._parse_manual(output)

        assert results["band_gap_ev"] == 3.21
        assert results["band_gap_type"] == "indirect"


class TestCrystal23ParserParse:
    """Test the main parse() method."""

    def test_parse_missing_output(self, mock_parser):
        """Test handling missing output file."""
        mock_parser.node.get_option.return_value = "OUTPUT"
        mock_parser.retrieved.get_object_content.side_effect = FileNotFoundError()
        mock_parser.exit_codes.ERROR_MISSING_OUTPUT = "ERROR_MISSING_OUTPUT"

        result = mock_parser.parse()

        assert result == "ERROR_MISSING_OUTPUT"

    def test_parse_error_insufficient_memory(self, mock_parser):
        """Test handling of insufficient memory error."""
        mock_parser.node.get_option.return_value = "OUTPUT"
        mock_parser.retrieved.get_object_content.return_value = "output"
        mock_parser.exit_codes.ERROR_INSUFFICIENT_MEMORY = "ERROR_INSUFFICIENT_MEMORY"

        with patch.object(
            mock_parser,
            "_parse_manual",
            return_value={"completed": False, "error_message": "insufficient memory"},
        ):
            result = mock_parser.parse()

        assert result == "ERROR_INSUFFICIENT_MEMORY"

    def test_parse_error_timeout(self, mock_parser):
        """Test handling of timeout error."""
        mock_parser.node.get_option.return_value = "OUTPUT"
        mock_parser.retrieved.get_object_content.return_value = "output"
        mock_parser.exit_codes.ERROR_TIMEOUT = "ERROR_TIMEOUT"

        with patch.object(
            mock_parser,
            "_parse_manual",
            return_value={"completed": False, "error_message": "timeout exceeded"},
        ):
            result = mock_parser.parse()

        assert result == "ERROR_TIMEOUT"


class TestCrystal23ParserStructure:
    """Test structure parsing and storage."""

    def test_store_output_structure(self, mock_parser):
        """Test storing output structure."""
        mock_parser.retrieved.get_object_content.return_value = """
        0
        1.0 0.0 0.0
        0.0 1.0 0.0
        0.0 0.0 1.0
        6 0.0 0.0 0.0
        """

        structure_data = {"cell": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}
        mock_parser._store_output_structure(structure_data)

        # Should attempt to read fort.34
        mock_parser.retrieved.get_object_content.assert_called_with("fort.34")

    def test_store_output_structure_not_found(self, mock_parser):
        """Test handling missing fort.34."""
        mock_parser.retrieved.get_object_content.side_effect = FileNotFoundError()

        # Should not raise exception
        mock_parser._store_output_structure({})

    def test_parse_fort34_invalid(self, mock_parser):
        """Test handling invalid fort.34 content."""
        invalid_content = "invalid data"

        structure = mock_parser._parse_fort34(invalid_content)

        assert structure is None


class TestCrystal23ParserWavefunction:
    """Test wavefunction storage."""

    def test_store_wavefunction(self, mock_parser):
        """Test storing wavefunction file."""
        mock_parser.retrieved.get_object_content.return_value = b"binary data"

        mock_parser._store_wavefunction()

        mock_parser.retrieved.get_object_content.assert_called_with("fort.9", mode="rb")

    def test_store_wavefunction_not_found(self, mock_parser):
        """Test handling missing wavefunction file."""
        mock_parser.retrieved.get_object_content.side_effect = FileNotFoundError()

        # Should not raise exception
        mock_parser._store_wavefunction()
