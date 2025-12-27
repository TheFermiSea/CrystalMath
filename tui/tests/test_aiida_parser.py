"""Unit tests for AiiDA CRYSTAL23 Parser."""

from unittest.mock import MagicMock, Mock, patch

import pytest


class TestCrystal23Parser:
    """Test suite for Crystal23Parser class."""

    @pytest.fixture
    def mock_parser(self):
        """Create mock parser instance."""
        from src.aiida.calcjobs.parser import Crystal23Parser

        parser = Crystal23Parser(MagicMock())
        parser.node = MagicMock()
        parser.retrieved = MagicMock()
        parser.logger = MagicMock()
        parser.exit_codes = MagicMock()
        parser.out = MagicMock()

        return parser

    @pytest.fixture
    def sample_output_completed(self):
        """Sample CRYSTAL23 output for completed calculation."""
        return """
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

    @pytest.fixture
    def sample_output_geometry_opt(self):
        """Sample output for geometry optimization."""
        return """
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

    def test_parse_manual_completed(self, mock_parser, sample_output_completed):
        """Test manual parsing of completed calculation."""
        mock_parser.node.get_option.return_value = "OUTPUT"
        mock_parser.retrieved.get_object_content.return_value = sample_output_completed

        results = mock_parser._parse_manual(sample_output_completed)

        assert results["parser"] == "manual"
        assert results["completed"] is True
        assert results["scf_converged"] is True
        assert results["final_energy_hartree"] == -100.345678
        assert "band_gap_ev" in results
        assert results["band_gap_ev"] == 5.43
        assert results["band_gap_type"] == "direct"

    def test_parse_manual_scf_iterations(self, mock_parser, sample_output_completed):
        """Test counting SCF iterations."""
        results = mock_parser._parse_manual(sample_output_completed)

        assert "scf_iterations" in results
        assert results["scf_iterations"] == 3

    def test_parse_manual_geometry_opt(self, mock_parser, sample_output_geometry_opt):
        """Test parsing geometry optimization."""
        results = mock_parser._parse_manual(sample_output_geometry_opt)

        assert results["completed"] is True
        assert results["is_geometry_optimization"] is True
        assert results["geom_converged"] is True
        assert results["optimization_steps"] == 1

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

    @patch("src.aiida.calcjobs.parser.Crystal_output")
    def test_parse_with_crystalpytools_success(self, mock_crystal_output, mock_parser):
        """Test parsing with CRYSTALpytools."""
        # Mock CRYSTALpytools parser
        mock_cry_out = MagicMock()
        mock_cry_out.is_terminated_normally.return_value = True
        mock_cry_out.is_converged.return_value = True
        mock_cry_out.get_final_energy.return_value = -100.5
        mock_cry_out.get_scf_iterations.return_value = 5
        mock_cry_out.is_geometry_optimization.return_value = False
        mock_cry_out.get_band_gap.return_value = 4.2

        mock_crystal_output.return_value = mock_cry_out

        output_content = "dummy output"
        results = mock_parser._parse_with_crystalpytools(output_content)

        assert results["parser"] == "CRYSTALpytools"
        assert results["completed"] is True
        assert results["scf_converged"] is True
        assert results["final_energy_hartree"] == -100.5
        assert results["scf_iterations"] == 5
        assert results["band_gap_ev"] == 4.2

    @patch("src.aiida.calcjobs.parser.Crystal_output")
    def test_parse_with_crystalpytools_geometry_opt(
        self, mock_crystal_output, mock_parser
    ):
        """Test parsing geometry optimization with CRYSTALpytools."""
        mock_cry_out = MagicMock()
        mock_cry_out.is_terminated_normally.return_value = True
        mock_cry_out.is_converged.return_value = True
        mock_cry_out.is_geometry_optimization.return_value = True
        mock_cry_out.is_opt_converged.return_value = True
        mock_cry_out.get_opt_steps.return_value = 10
        mock_cry_out.get_final_energy.return_value = -100.0

        mock_crystal_output.return_value = mock_cry_out

        results = mock_parser._parse_with_crystalpytools("output")

        assert results["is_geometry_optimization"] is True
        assert results["geom_converged"] is True
        assert results["optimization_steps"] == 10

    @patch("src.aiida.calcjobs.parser.Crystal_output")
    def test_parse_with_crystalpytools_handles_exceptions(
        self, mock_crystal_output, mock_parser
    ):
        """Test that CRYSTALpytools exceptions are handled gracefully."""
        mock_cry_out = MagicMock()
        mock_cry_out.is_terminated_normally.return_value = True
        mock_cry_out.is_converged.return_value = True
        mock_cry_out.get_final_energy.side_effect = Exception("Energy error")
        mock_cry_out.get_scf_iterations.side_effect = Exception("SCF error")

        mock_crystal_output.return_value = mock_cry_out

        results = mock_parser._parse_with_crystalpytools("output")

        # Should still return basic results even if some calls fail
        assert results["completed"] is True
        assert results["scf_converged"] is True
        assert "final_energy_hartree" not in results

    def test_parse_missing_output(self, mock_parser):
        """Test handling missing output file."""
        mock_parser.node.get_option.return_value = "OUTPUT"
        mock_parser.retrieved.get_object_content.side_effect = FileNotFoundError()
        mock_parser.exit_codes.ERROR_MISSING_OUTPUT = "ERROR_MISSING_OUTPUT"

        result = mock_parser.parse()

        assert result == "ERROR_MISSING_OUTPUT"

    def test_parse_success_manual(self, mock_parser, sample_output_completed):
        """Test complete parse workflow with manual parser."""
        mock_parser.node.get_option.return_value = "OUTPUT"
        mock_parser.retrieved.get_object_content.return_value = sample_output_completed

        # Mock CRYSTALpytools import error (force fallback to manual)
        with patch(
            "src.aiida.calcjobs.parser.Crystal_output", side_effect=ImportError()
        ):
            result = mock_parser.parse()

        assert result is None  # None = success
        mock_parser.out.assert_called()

    @patch("src.aiida.calcjobs.parser.orm")
    def test_parse_stores_output_parameters(
        self, mock_orm, mock_parser, sample_output_completed
    ):
        """Test that output parameters are stored."""
        mock_parser.node.get_option.return_value = "OUTPUT"
        mock_parser.retrieved.get_object_content.return_value = sample_output_completed

        with patch(
            "src.aiida.calcjobs.parser.Crystal_output", side_effect=ImportError()
        ):
            mock_parser.parse()

        # Check that output_parameters was stored
        calls = mock_parser.out.call_args_list
        assert any("output_parameters" in str(call) for call in calls)

    def test_parse_error_output_parsing(self, mock_parser):
        """Test handling of parsing failure."""
        mock_parser.node.get_option.return_value = "OUTPUT"
        mock_parser.retrieved.get_object_content.return_value = "invalid output"
        mock_parser.exit_codes.ERROR_OUTPUT_PARSING = "ERROR_OUTPUT_PARSING"

        # Mock parse methods to return None
        with patch.object(mock_parser, "_parse_manual", return_value=None):
            result = mock_parser.parse()

        assert result == "ERROR_OUTPUT_PARSING"

    def test_parse_error_scf_not_converged(self, mock_parser):
        """Test handling of SCF not converged."""
        mock_parser.node.get_option.return_value = "OUTPUT"
        mock_parser.retrieved.get_object_content.return_value = "output"
        mock_parser.exit_codes.ERROR_SCF_NOT_CONVERGED = "ERROR_SCF_NOT_CONVERGED"

        with patch.object(
            mock_parser,
            "_parse_manual",
            return_value={"completed": True, "scf_converged": False},
        ):
            result = mock_parser.parse()

        assert result == "ERROR_SCF_NOT_CONVERGED"

    def test_parse_error_geometry_not_converged(self, mock_parser):
        """Test handling of geometry not converged."""
        mock_parser.node.get_option.return_value = "OUTPUT"
        mock_parser.retrieved.get_object_content.return_value = "output"
        mock_parser.exit_codes.ERROR_GEOMETRY_NOT_CONVERGED = (
            "ERROR_GEOMETRY_NOT_CONVERGED"
        )

        with patch.object(
            mock_parser,
            "_parse_manual",
            return_value={"completed": True, "geom_converged": False},
        ):
            result = mock_parser.parse()

        assert result == "ERROR_GEOMETRY_NOT_CONVERGED"

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

    @patch("src.aiida.calcjobs.parser.orm")
    def test_store_output_structure(self, mock_orm, mock_parser):
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

    @patch("src.aiida.calcjobs.parser.orm")
    def test_parse_fort34_valid(self, mock_orm, mock_parser):
        """Test parsing valid fort.34 file."""
        fort34_content = """
0
10.0 0.0 0.0
0.0 10.0 0.0
0.0 0.0 10.0
6 0.0 0.0 0.0
8 5.0 5.0 5.0
        """

        mock_structure = MagicMock()
        mock_orm.StructureData.return_value = mock_structure

        # Mock elements dictionary
        with patch("src.aiida.calcjobs.parser.elements", {6: "C", 8: "O"}):
            structure = mock_parser._parse_fort34(fort34_content)

        # Verify StructureData created with cell
        mock_orm.StructureData.assert_called_once()
        assert structure is not None

    def test_parse_fort34_invalid(self, mock_parser):
        """Test handling invalid fort.34 content."""
        invalid_content = "invalid data"

        structure = mock_parser._parse_fort34(invalid_content)

        assert structure is None

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


class TestParserIntegration:
    """Integration tests for parser workflow."""

    @pytest.fixture
    def full_output_success(self):
        """Complete successful CRYSTAL23 output."""
        return """
CRYSTAL23 VERSION 1.0.1

GEOMETRY INPUT FROM EXTERNAL FILE (FORTRAN UNIT 34)

 CRYSTAL - SCF CALCULATION

TTTTTTTTTTTTTTTTTTTTTTTTTTTTTT EIGENVECTORS     TELAPSE        1.50 TCPU        1.50

 CYC   ETOT(AU)      DETOT        CONV
   1  -100.123456   1.0E+00      N
   2  -100.234567   1.1E-01      N
   3  -100.345678   1.1E-02      Y

 == SCF ENDED - CONVERGENCE ON ENERGY      E(AU)  -100.345678   CYCLES   3

TOTAL ENERGY(DFT)(AU) (  3) -100.345678

 BAND GAP ANALYSIS
 DIRECT BAND GAP:   5.43 EV
 INDIRECT BAND GAP: 4.21 EV

EEEEEEEE TERMINATION  DATE 01 01 2024 TIME 12:00:00.0
        """

    @pytest.fixture
    def full_output_geom_opt(self):
        """Complete geometry optimization output."""
        return """
OPTOPTOPTOPTOPTOPTOPTOPTOPTOPTOPTOPTOPTOPTOPTOPTOPTOPTOPTOPT
COORDINATE OPTIMIZATION - POINT    1

OPTIMIZATION - PAIR DISTANCE EVALUATION  1

 CYC   ETOT(AU)      DETOT        CONV
   1  -100.123456   1.0E+00      N
   2  -100.234567   1.1E-01      Y

 == SCF ENDED - CONVERGENCE ON ENERGY

OPTIMIZATION - PAIR DISTANCE EVALUATION  2

 CYC   ETOT(AU)      DETOT
   1  -100.345678   1.1E-02      Y

 == SCF ENDED - CONVERGENCE ON ENERGY

CONVERGENCE TESTS SATISFIED  OPTIMIZER ENDS

EEEEEEEE TERMINATION
        """

    def test_full_parse_success(self, full_output_success):
        """Test complete parsing of successful calculation."""
        from src.aiida.calcjobs.parser import Crystal23Parser

        parser = Crystal23Parser(MagicMock())
        parser.node = MagicMock()
        parser.node.get_option.return_value = "OUTPUT"
        parser.retrieved = MagicMock()
        parser.retrieved.get_object_content.return_value = full_output_success
        parser.logger = MagicMock()
        parser.exit_codes = MagicMock()
        parser.out = MagicMock()

        with patch(
            "src.aiida.calcjobs.parser.Crystal_output", side_effect=ImportError()
        ):
            result = parser.parse()

        # Should succeed
        assert result is None

        # Check that output was stored
        parser.out.assert_called()

    def test_full_parse_geometry_opt(self, full_output_geom_opt):
        """Test complete parsing of geometry optimization."""
        from src.aiida.calcjobs.parser import Crystal23Parser

        parser = Crystal23Parser(MagicMock())
        parser.node = MagicMock()
        parser.node.get_option.return_value = "OUTPUT"
        parser.retrieved = MagicMock()
        parser.retrieved.get_object_content.return_value = full_output_geom_opt
        parser.logger = MagicMock()
        parser.exit_codes = MagicMock()
        parser.out = MagicMock()

        with patch(
            "src.aiida.calcjobs.parser.Crystal_output", side_effect=ImportError()
        ):
            results = parser._parse_manual(full_output_geom_opt)

        assert results["is_geometry_optimization"] is True
        assert results["geom_converged"] is True
        assert results["optimization_steps"] == 2
