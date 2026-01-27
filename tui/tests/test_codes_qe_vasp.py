"""Tests for Quantum Espresso and VASP output parsers and input handling."""

import pytest
from pathlib import Path
import tempfile

from src.core.codes import DFTCode, get_code_config, list_available_codes
from src.core.codes.parsers.base import get_parser, PARSER_REGISTRY
from src.core.codes.quantum_espresso import QE_CONFIG
from src.core.codes.vasp import (
    VASP_CONFIG,
    VASPInputFiles,
    VASP_REQUIRED_FILES,
    VASP_OPTIONAL_INPUTS,
    VASP_OUTPUT_FILES,
    get_vasp_files_to_stage,
    get_vasp_output_patterns,
)


# Sample QE output for testing
QE_SUCCESS_OUTPUT = """
     Program PWSCF v.7.2 starts on 15Dec2024 at 10:30:15

     This program is part of the open-source Quantum ESPRESSO suite

     bravais-lattice index     =            2
     lattice parameter (alat)  =       7.2558  a.u.

     Self-consistent Calculation

     iteration #  1     ecut=    60.00 Ry     beta= 0.70
     Davidson diagonalization with overlap
     ethr =  1.00E-02,  avg # of iterations =  3.0

     iteration #  2     ecut=    60.00 Ry     beta= 0.70
     Davidson diagonalization with overlap
     ethr =  5.23E-04,  avg # of iterations =  2.0

     iteration #  3     ecut=    60.00 Ry     beta= 0.70
     Davidson diagonalization with overlap
     ethr =  1.45E-05,  avg # of iterations =  3.0

     convergence has been achieved in   3 iterations

!    total energy              =     -65.45703298 Ry

     JOB DONE.
"""

QE_RELAX_SUCCESS_OUTPUT = """
     Program PWSCF v.7.2 starts on 15Dec2024 at 10:30:15

     BFGS Geometry Optimization

     iteration #  1     ecut=    60.00 Ry
!    total energy              =     -65.45000000 Ry

     Total force =     0.105234

     iteration #  2     ecut=    60.00 Ry
!    total energy              =     -65.45500000 Ry

     Total force =     0.025000

     BFGS converged in   2 scf cycles and   2 bfgs steps

     bfgs converged

     convergence has been achieved in   3 iterations

!    total energy              =     -65.45703298 Ry

     JOB DONE.
"""

QE_FAILED_OUTPUT = """
     Program PWSCF v.7.2 starts on 15Dec2024 at 10:30:15

     iteration #  1     ecut=    60.00 Ry
     iteration #  2     ecut=    60.00 Ry
     iteration #  3     ecut=    60.00 Ry
     iteration # 100     ecut=    60.00 Ry

     convergence NOT achieved after 100 iterations: stopping

     Error in routine electrons (1):
     convergence NOT achieved

"""

QE_WITH_WARNINGS = """
     Program PWSCF v.7.2 starts on 15Dec2024 at 10:30:15

     Warning: some deprecated feature was used

     iteration #  1     ecut=    60.00 Ry

     convergence has been achieved in   1 iterations

!    total energy              =     -10.12345678 Ry

     JOB DONE.
"""

# Sample VASP output for testing
VASP_SUCCESS_OUTPUT = """
 running on    4 total cores
 vasp.5.4.4.18Apr17-6-g9f103f2a35 (build Dec 15 2023 14:50:32)

 POTCAR:    PAW_PBE Si 05Jan2001

 POSCAR:  Si2
  positions in direct lattice

   FREE ENERGIE OF THE ION-ELECTRON SYSTEM (eV)
   ---------------------------------------------------

       1       -10.12345       0.12E-02
       2       -10.45678       0.45E-03
       3       -10.78910       0.12E-05

------------------------ aborting loop because EDIFF is reached --------------------

  free  energy   TOTEN  =       -85.54234987 eV

  energy  without entropy =       -85.53789012

                   LOOP+:  cpu time   12.34

 General timing and accounting informance:

  Total CPU time used (sec):       45.678
"""

VASP_RELAX_SUCCESS_OUTPUT = """
 running on    4 total cores
 IBRION = 2
 NSW = 100

   FREE ENERGIE OF THE ION-ELECTRON SYSTEM (eV)
   ---------------------------------------------------

       1       -10.12345       0.12E-02

------------------------ aborting loop because EDIFF is reached --------------------

   FREE ENERGIE OF THE ION-ELECTRON SYSTEM (eV)
   ---------------------------------------------------

       1       -10.45678       0.45E-03

------------------------ aborting loop because EDIFF is reached --------------------

 reached required accuracy - stopping structural energy minimisation

  free  energy   TOTEN  =       -85.54234987 eV

 General timing and accounting informance:

  Total CPU time used (sec):       120.456
"""

VASP_FAILED_OUTPUT = """
 running on    4 total cores

 VERY BAD NEWS! internal error in subroutine SGRCON:
 Found wrong high symmetry kpoint.

 Error EDDDAV: Call to ZHEGV failed.

"""

VASP_WITH_WARNINGS = """
 running on    4 total cores

 WARNING: aliasing errors present

  free  energy   TOTEN  =       -50.12345678 eV

 General timing and accounting informance:

  Total CPU time used (sec):       30.123
"""

# Comprehensive VASP output with full timing information for benchmark testing
VASP_BENCHMARK_OUTPUT = """
 running on   16 total cores
 distrk:  each k-point on   16 cores,    1 groups
 distr:  one band on NCORES_PER_BAND=   4 cores,    4 groups


--------------------------------------------------------------------------------------------------------


 vasp.5.4.4.18Apr17-6-g9f103f2a35 (build Dec 15 2023 14:50:32) complex

 executed on             LinuxIFC date 2024.12.15  10:30:00
 running on   16 total cores
 distrk:  each k-point on   16 cores,    1 groups
 distr:  one band on NCORES_PER_BAND=   4 cores,    4 groups

 POTCAR:    PAW_PBE Si 05Jan2001

   NPAR =       4
   NCORE=       4
   KPAR =       2

 total amount of memory used by VASP MPI-rank0   524288. kBytes

   FREE ENERGIE OF THE ION-ELECTRON SYSTEM (eV)
   ---------------------------------------------------

       1       -10.12345       0.12E-02
       2       -10.45678       0.45E-03
       3       -10.78910       0.12E-05

------------------------ aborting loop because EDIFF is reached --------------------

   POTLOK:  cpu time    1.23: real time    1.45
   SETDIJ:  cpu time    0.56: real time    0.78
   EDDIAG:  cpu time    2.34: real time    2.89
   RMM-DIIS: cpu time    3.45: real time    4.12
   ORTHCH:  cpu time    0.12: real time    0.15
   DOS:     cpu time    0.02: real time    0.03
   CHARGE:  cpu time    1.23: real time    1.56
   MIXING:  cpu time    0.34: real time    0.45
   LOOP:    cpu time   12.34: real time   15.67

   FREE ENERGIE OF THE ION-ELECTRON SYSTEM (eV)
   ---------------------------------------------------

       1       -10.98765       0.12E-03
       2       -11.23456       0.45E-05

------------------------ aborting loop because EDIFF is reached --------------------

   POTLOK:  cpu time    1.12: real time    1.34
   SETDIJ:  cpu time    0.45: real time    0.67
   EDDIAG:  cpu time    2.12: real time    2.67
   RMM-DIIS: cpu time    3.23: real time    3.89
   ORTHCH:  cpu time    0.11: real time    0.14
   DOS:     cpu time    0.02: real time    0.02
   CHARGE:  cpu time    1.12: real time    1.45
   MIXING:  cpu time    0.32: real time    0.42
   FORCES:  cpu time    0.89: real time    1.12
   STRESS:  cpu time    1.23: real time    1.56
   LOOP:    cpu time   11.23: real time   14.34

                   LOOP+:  cpu time   24.56: real time   31.45

 reached required accuracy - stopping structural energy minimisation

  free  energy   TOTEN  =       -85.54234987 eV

  energy  without entropy =       -85.53789012

 General timing and accounting informations for this job:

  Total CPU time used (sec):      125.678
  Elapsed time (sec):              45.234

  Maximum memory used (kb):      654321.

--------------------------------------------------------------------------------------------------------

"""

# VASP output with minimal timing (single-point calculation)
VASP_SINGLE_POINT_OUTPUT = """
 running on    8 total cores

   NPAR =       2
   NCORE=       4

 POTCAR:    PAW_PBE Fe 06Sep2000

 total amount of memory used by VASP MPI-rank0   262144. kBytes

   FREE ENERGIE OF THE ION-ELECTRON SYSTEM (eV)
   ---------------------------------------------------

       1       -25.12345       0.12E-01
       2       -26.45678       0.45E-02
       3       -27.78910       0.12E-03
       4       -27.89012       0.45E-05

------------------------ aborting loop because EDIFF is reached --------------------

   POTLOK:  cpu time    0.98: real time    1.12
   SETDIJ:  cpu time    0.34: real time    0.45
   EDDIAG:  cpu time    1.56: real time    1.89
   RMM-DIIS: cpu time    2.34: real time    2.78
   ORTHCH:  cpu time    0.08: real time    0.10
   CHARGE:  cpu time    0.89: real time    1.12
   MIXING:  cpu time    0.23: real time    0.31
   LOOP:    cpu time    8.45: real time   10.23

  free  energy   TOTEN  =       -27.89012345 eV

 General timing and accounting informations for this job:

  Total CPU time used (sec):       32.456
  Elapsed time (sec):              12.345

--------------------------------------------------------------------------------------------------------

"""


class TestQuantumEspressoConfig:
    """Tests for Quantum Espresso code configuration."""

    def test_qe_registered(self):
        """Test that QE is registered as an available code."""
        assert DFTCode.QUANTUM_ESPRESSO in list_available_codes()

    def test_get_qe_config(self):
        """Test retrieving QE configuration."""
        config = get_code_config(DFTCode.QUANTUM_ESPRESSO)
        assert config.name == "quantum_espresso"
        assert config.display_name == "Quantum Espresso"

    def test_qe_input_extensions(self):
        """Test QE input file extensions."""
        assert ".in" in QE_CONFIG.input_extensions
        assert ".pwi" in QE_CONFIG.input_extensions

    def test_qe_executables(self):
        """Test QE executable configuration."""
        assert QE_CONFIG.serial_executable == "pw.x"
        assert "pw.x" in QE_CONFIG.parallel_executable

    def test_qe_energy_unit(self):
        """Test QE energy unit."""
        assert QE_CONFIG.energy_unit == "Ry"

    def test_qe_convergence_patterns(self):
        """Test QE convergence patterns."""
        assert "convergence has been achieved" in QE_CONFIG.convergence_patterns
        assert "JOB DONE" in QE_CONFIG.convergence_patterns


class TestVASPConfig:
    """Tests for VASP code configuration."""

    def test_vasp_registered(self):
        """Test that VASP is registered as an available code."""
        assert DFTCode.VASP in list_available_codes()

    def test_get_vasp_config(self):
        """Test retrieving VASP configuration."""
        config = get_code_config(DFTCode.VASP)
        assert config.name == "vasp"
        assert config.display_name == "VASP"

    def test_vasp_executables(self):
        """Test VASP executable configuration."""
        assert VASP_CONFIG.serial_executable == "vasp_std"
        assert "vasp_std" in VASP_CONFIG.parallel_executable

    def test_vasp_energy_unit(self):
        """Test VASP energy unit."""
        assert VASP_CONFIG.energy_unit == "eV"

    def test_vasp_convergence_patterns(self):
        """Test VASP convergence patterns."""
        assert "reached required accuracy" in VASP_CONFIG.convergence_patterns


class TestQuantumEspressoParser:
    """Tests for Quantum Espresso output parser."""

    @pytest.fixture
    def parser(self):
        """Get the QE parser instance."""
        return get_parser(DFTCode.QUANTUM_ESPRESSO)

    @pytest.mark.asyncio
    async def test_parse_successful_scf(self, parser):
        """Test parsing successful QE SCF output."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".out", delete=False) as f:
            f.write(QE_SUCCESS_OUTPUT)
            f.flush()
            result = await parser.parse(Path(f.name))

        assert result.success is True
        assert result.final_energy == pytest.approx(-65.45703298, rel=1e-6)
        assert result.energy_unit == "Ry"
        assert result.convergence_status == "CONVERGED"
        assert result.scf_cycles == 3
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_parse_successful_relax(self, parser):
        """Test parsing successful QE geometry optimization output."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".out", delete=False) as f:
            f.write(QE_RELAX_SUCCESS_OUTPUT)
            f.flush()
            result = await parser.parse(Path(f.name))

        assert result.success is True
        assert result.final_energy == pytest.approx(-65.45703298, rel=1e-6)
        assert result.convergence_status == "CONVERGED"
        assert result.geometry_converged is True
        assert "total_force" in result.metadata

    @pytest.mark.asyncio
    async def test_parse_failed_convergence(self, parser):
        """Test parsing QE output with failed convergence."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".out", delete=False) as f:
            f.write(QE_FAILED_OUTPUT)
            f.flush()
            result = await parser.parse(Path(f.name))

        assert result.success is False
        assert result.convergence_status == "NOT_CONVERGED"
        assert len(result.errors) > 0
        assert any("convergence" in e.lower() for e in result.errors)

    @pytest.mark.asyncio
    async def test_parse_with_warnings(self, parser):
        """Test parsing QE output with warnings."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".out", delete=False) as f:
            f.write(QE_WITH_WARNINGS)
            f.flush()
            result = await parser.parse(Path(f.name))

        assert result.success is True
        assert len(result.warnings) > 0
        assert any("deprecated" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_parse_nonexistent_file(self, parser):
        """Test parsing nonexistent file returns error result."""
        result = await parser.parse(Path("/nonexistent/file.out"))

        assert result.success is False
        assert result.convergence_status == "UNKNOWN"
        assert len(result.errors) > 0
        assert "not found" in result.errors[0].lower()

    def test_energy_unit(self, parser):
        """Test energy unit is Rydberg."""
        assert parser.get_energy_unit() == "Ry"


class TestVASPParser:
    """Tests for VASP output parser."""

    @pytest.fixture
    def parser(self):
        """Get the VASP parser instance."""
        return get_parser(DFTCode.VASP)

    @pytest.mark.asyncio
    async def test_parse_successful_scf(self, parser):
        """Test parsing successful VASP SCF output."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".out", delete=False) as f:
            f.write(VASP_SUCCESS_OUTPUT)
            f.flush()
            result = await parser.parse(Path(f.name))

        assert result.success is True
        assert result.final_energy == pytest.approx(-85.54234987, rel=1e-6)
        assert result.energy_unit == "eV"
        assert result.convergence_status == "COMPLETED"
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_parse_successful_relax(self, parser):
        """Test parsing successful VASP geometry optimization output."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".out", delete=False) as f:
            f.write(VASP_RELAX_SUCCESS_OUTPUT)
            f.flush()
            result = await parser.parse(Path(f.name))

        assert result.success is True
        assert result.final_energy == pytest.approx(-85.54234987, rel=1e-6)
        assert result.convergence_status == "CONVERGED"
        assert result.geometry_converged is True

    @pytest.mark.asyncio
    async def test_parse_failed_calculation(self, parser):
        """Test parsing VASP output with errors."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".out", delete=False) as f:
            f.write(VASP_FAILED_OUTPUT)
            f.flush()
            result = await parser.parse(Path(f.name))

        assert result.success is False
        assert result.convergence_status == "FAILED"
        assert len(result.errors) > 0
        assert any("very bad news" in e.lower() for e in result.errors)

    @pytest.mark.asyncio
    async def test_parse_with_warnings(self, parser):
        """Test parsing VASP output with warnings."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".out", delete=False) as f:
            f.write(VASP_WITH_WARNINGS)
            f.flush()
            result = await parser.parse(Path(f.name))

        assert result.success is True
        assert len(result.warnings) > 0
        assert any("warning" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_parse_directory_with_outcar(self, parser):
        """Test parsing VASP output when given directory path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            outcar_path = Path(tmpdir) / "OUTCAR"
            outcar_path.write_text(VASP_SUCCESS_OUTPUT)

            result = await parser.parse(Path(tmpdir))

        assert result.success is True
        assert result.final_energy == pytest.approx(-85.54234987, rel=1e-6)

    @pytest.mark.asyncio
    async def test_parse_nonexistent_file(self, parser):
        """Test parsing nonexistent file returns error result."""
        result = await parser.parse(Path("/nonexistent/OUTCAR"))

        assert result.success is False
        assert result.convergence_status == "UNKNOWN"
        assert len(result.errors) > 0
        assert "not found" in result.errors[0].lower()

    def test_energy_unit(self, parser):
        """Test energy unit is eV."""
        assert parser.get_energy_unit() == "eV"


class TestParserRegistry:
    """Tests for the parser registry."""

    def test_qe_parser_registered(self):
        """Test QE parser is in registry."""
        assert DFTCode.QUANTUM_ESPRESSO in PARSER_REGISTRY

    def test_vasp_parser_registered(self):
        """Test VASP parser is in registry."""
        assert DFTCode.VASP in PARSER_REGISTRY

    def test_crystal_parser_registered(self):
        """Test CRYSTAL parser is in registry."""
        assert DFTCode.CRYSTAL in PARSER_REGISTRY

    def test_get_parser_qe(self):
        """Test getting QE parser."""
        parser = get_parser(DFTCode.QUANTUM_ESPRESSO)
        assert parser.get_energy_unit() == "Ry"

    def test_get_parser_vasp(self):
        """Test getting VASP parser."""
        parser = get_parser(DFTCode.VASP)
        assert parser.get_energy_unit() == "eV"

    def test_get_parser_unknown_raises(self):
        """Test getting unknown parser raises KeyError."""
        # Create a mock enum value that doesn't exist
        with pytest.raises(KeyError):
            # This will fail because the code doesn't exist
            get_parser("nonexistent")


class TestCodeBuildCommand:
    """Tests for build_command method across codes."""

    def test_qe_build_command(self):
        """Test QE command building with -in flag."""
        cmd = QE_CONFIG.build_command(
            Path("input.in"), Path("output.out"), parallel=False
        )
        assert "pw.x" in cmd[-1]
        assert "-in input.in" in cmd[-1]
        assert "> output.out" in cmd[-1]

    def test_vasp_build_command(self):
        """Test VASP command building (CWD style)."""
        cmd = VASP_CONFIG.build_command(
            Path("POSCAR"), Path("output.out"), parallel=False
        )
        assert "vasp_std" in cmd[-1]
        assert "> output.out" in cmd[-1]
        # VASP CWD style shouldn't have input file in command
        assert "POSCAR" not in cmd[-1] or "-in" not in cmd[-1]


# Sample VASP input files for testing
SAMPLE_POSCAR = """Si
1.0
5.43 0.00 0.00
0.00 5.43 0.00
0.00 0.00 5.43
Si
2
Direct
0.0 0.0 0.0
0.25 0.25 0.25
"""

SAMPLE_INCAR = """SYSTEM = Silicon
ENCUT = 400
PREC = Accurate
IBRION = 2
NSW = 50
EDIFF = 1E-6
"""

SAMPLE_KPOINTS = """Automatic mesh
0
Gamma
4 4 4
0 0 0
"""

SAMPLE_POTCAR = """PAW_PBE Si 05Jan2001
parameters from POTCAR
END PAW_PBE Si
"""


class TestVASPInputFiles:
    """Tests for VASP multi-file input handling."""

    def test_create_vasp_input_files(self):
        """Test creating VASPInputFiles instance."""
        inputs = VASPInputFiles(
            poscar=SAMPLE_POSCAR,
            incar=SAMPLE_INCAR,
            kpoints=SAMPLE_KPOINTS,
            potcar=SAMPLE_POTCAR,
        )
        assert inputs.poscar == SAMPLE_POSCAR
        assert inputs.incar == SAMPLE_INCAR
        assert inputs.kpoints == SAMPLE_KPOINTS
        assert inputs.potcar == SAMPLE_POTCAR
        assert inputs.wavecar is None
        assert inputs.chgcar is None
        assert inputs.contcar is None

    def test_validate_valid_inputs(self):
        """Test validation passes for valid inputs."""
        inputs = VASPInputFiles(
            poscar=SAMPLE_POSCAR,
            incar=SAMPLE_INCAR,
            kpoints=SAMPLE_KPOINTS,
            potcar=SAMPLE_POTCAR,
        )
        issues = inputs.validate()
        assert len(issues) == 0

    def test_validate_empty_poscar(self):
        """Test validation catches empty POSCAR."""
        inputs = VASPInputFiles(
            poscar="",
            incar=SAMPLE_INCAR,
            kpoints=SAMPLE_KPOINTS,
            potcar=SAMPLE_POTCAR,
        )
        issues = inputs.validate()
        assert any("POSCAR" in issue for issue in issues)

    def test_validate_empty_incar(self):
        """Test validation catches empty INCAR."""
        inputs = VASPInputFiles(
            poscar=SAMPLE_POSCAR,
            incar="",
            kpoints=SAMPLE_KPOINTS,
            potcar=SAMPLE_POTCAR,
        )
        issues = inputs.validate()
        assert any("INCAR" in issue for issue in issues)

    def test_validate_incomplete_poscar(self):
        """Test validation catches incomplete POSCAR."""
        inputs = VASPInputFiles(
            poscar="Si\n1.0\n",  # Only 2 lines
            incar=SAMPLE_INCAR,
            kpoints=SAMPLE_KPOINTS,
            potcar=SAMPLE_POTCAR,
        )
        issues = inputs.validate()
        assert any("incomplete" in issue.lower() for issue in issues)

    def test_validate_missing_encut(self):
        """Test validation warns about missing ENCUT."""
        inputs = VASPInputFiles(
            poscar=SAMPLE_POSCAR,
            incar="SYSTEM = Test\nISMEAR = 0\n",  # No ENCUT or PREC
            kpoints=SAMPLE_KPOINTS,
            potcar=SAMPLE_POTCAR,
        )
        issues = inputs.validate()
        assert any("ENCUT" in issue for issue in issues)

    def test_write_to_directory(self):
        """Test writing VASP files to directory."""
        inputs = VASPInputFiles(
            poscar=SAMPLE_POSCAR,
            incar=SAMPLE_INCAR,
            kpoints=SAMPLE_KPOINTS,
            potcar=SAMPLE_POTCAR,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            written = inputs.write_to_directory(work_dir)

            # Check all required files were written
            assert "POSCAR" in written
            assert "INCAR" in written
            assert "KPOINTS" in written
            assert "POTCAR" in written

            # Check file contents
            assert (work_dir / "POSCAR").read_text() == SAMPLE_POSCAR
            assert (work_dir / "INCAR").read_text() == SAMPLE_INCAR
            assert (work_dir / "KPOINTS").read_text() == SAMPLE_KPOINTS
            assert (work_dir / "POTCAR").read_text() == SAMPLE_POTCAR

    def test_write_with_contcar(self):
        """Test writing VASP files including CONTCAR."""
        inputs = VASPInputFiles(
            poscar=SAMPLE_POSCAR,
            incar=SAMPLE_INCAR,
            kpoints=SAMPLE_KPOINTS,
            potcar=SAMPLE_POTCAR,
            contcar="CONTCAR content here",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)
            written = inputs.write_to_directory(work_dir)

            assert "CONTCAR" in written
            assert (work_dir / "CONTCAR").read_text() == "CONTCAR content here"

    def test_from_directory(self):
        """Test reading VASP files from directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)

            # Write files
            (work_dir / "POSCAR").write_text(SAMPLE_POSCAR)
            (work_dir / "INCAR").write_text(SAMPLE_INCAR)
            (work_dir / "KPOINTS").write_text(SAMPLE_KPOINTS)
            (work_dir / "POTCAR").write_text(SAMPLE_POTCAR)

            # Read back
            inputs = VASPInputFiles.from_directory(work_dir)

            assert inputs.poscar == SAMPLE_POSCAR
            assert inputs.incar == SAMPLE_INCAR
            assert inputs.kpoints == SAMPLE_KPOINTS
            assert inputs.potcar == SAMPLE_POTCAR

    def test_from_directory_with_optional(self):
        """Test reading VASP files including optional files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)

            # Write required files
            (work_dir / "POSCAR").write_text(SAMPLE_POSCAR)
            (work_dir / "INCAR").write_text(SAMPLE_INCAR)
            (work_dir / "KPOINTS").write_text(SAMPLE_KPOINTS)
            (work_dir / "POTCAR").write_text(SAMPLE_POTCAR)
            (work_dir / "CONTCAR").write_text("CONTCAR content")

            # Read back
            inputs = VASPInputFiles.from_directory(work_dir)

            assert inputs.contcar == "CONTCAR content"

    def test_from_directory_missing_poscar(self):
        """Test error when POSCAR is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)

            # Write only some files
            (work_dir / "INCAR").write_text(SAMPLE_INCAR)
            (work_dir / "KPOINTS").write_text(SAMPLE_KPOINTS)
            (work_dir / "POTCAR").write_text(SAMPLE_POTCAR)

            with pytest.raises(FileNotFoundError) as exc_info:
                VASPInputFiles.from_directory(work_dir)

            assert "POSCAR" in str(exc_info.value)


class TestVASPFileStagingHelpers:
    """Tests for VASP file staging helper functions."""

    def test_get_vasp_files_to_stage(self):
        """Test getting list of files to stage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)

            # Write required files
            (work_dir / "POSCAR").write_text(SAMPLE_POSCAR)
            (work_dir / "INCAR").write_text(SAMPLE_INCAR)
            (work_dir / "KPOINTS").write_text(SAMPLE_KPOINTS)
            (work_dir / "POTCAR").write_text(SAMPLE_POTCAR)

            files = get_vasp_files_to_stage(work_dir)

            assert len(files) == 4
            filenames = [f.name for f in files]
            assert "POSCAR" in filenames
            assert "INCAR" in filenames
            assert "KPOINTS" in filenames
            assert "POTCAR" in filenames

    def test_get_vasp_files_with_optional(self):
        """Test staging includes optional restart files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir)

            # Write all files
            (work_dir / "POSCAR").write_text(SAMPLE_POSCAR)
            (work_dir / "INCAR").write_text(SAMPLE_INCAR)
            (work_dir / "KPOINTS").write_text(SAMPLE_KPOINTS)
            (work_dir / "POTCAR").write_text(SAMPLE_POTCAR)
            (work_dir / "WAVECAR").write_bytes(b"binary data")
            (work_dir / "CHGCAR").write_text("charge density")

            files = get_vasp_files_to_stage(work_dir)

            assert len(files) == 6
            filenames = [f.name for f in files]
            assert "WAVECAR" in filenames
            assert "CHGCAR" in filenames

    def test_get_vasp_output_patterns(self):
        """Test getting list of output patterns."""
        patterns = get_vasp_output_patterns()

        assert "OUTCAR" in patterns
        assert "CONTCAR" in patterns
        assert "vasprun.xml" in patterns
        assert "DOSCAR" in patterns

    def test_vasp_required_files_constant(self):
        """Test VASP required files constant."""
        assert "POSCAR" in VASP_REQUIRED_FILES
        assert "INCAR" in VASP_REQUIRED_FILES
        assert "KPOINTS" in VASP_REQUIRED_FILES
        assert "POTCAR" in VASP_REQUIRED_FILES

    def test_vasp_optional_inputs_constant(self):
        """Test VASP optional inputs constant."""
        assert "WAVECAR" in VASP_OPTIONAL_INPUTS
        assert "CHGCAR" in VASP_OPTIONAL_INPUTS
        assert "CONTCAR" in VASP_OPTIONAL_INPUTS

    def test_vasp_output_files_constant(self):
        """Test VASP output files constant."""
        assert "OUTCAR" in VASP_OUTPUT_FILES
        assert "vasprun.xml" in VASP_OUTPUT_FILES
        assert "EIGENVAL" in VASP_OUTPUT_FILES


class TestVASPConfigAuxiliaryMappings:
    """Tests for VASP auxiliary file mappings in config."""

    def test_auxiliary_inputs_includes_required(self):
        """Test auxiliary inputs includes all required files."""
        for filename in VASP_REQUIRED_FILES:
            assert filename in VASP_CONFIG.auxiliary_inputs

    def test_auxiliary_inputs_includes_optional(self):
        """Test auxiliary inputs includes optional restart files."""
        for filename in VASP_OPTIONAL_INPUTS:
            assert filename in VASP_CONFIG.auxiliary_inputs

    def test_auxiliary_outputs_includes_key_files(self):
        """Test auxiliary outputs includes key output files."""
        assert "OUTCAR" in VASP_CONFIG.auxiliary_outputs
        assert "CONTCAR" in VASP_CONFIG.auxiliary_outputs
        assert "vasprun.xml" in VASP_CONFIG.auxiliary_outputs

    def test_vasp_invocation_is_cwd(self):
        """Test VASP uses CWD invocation style."""
        from src.core.codes.base import InvocationStyle
        assert VASP_CONFIG.invocation_style == InvocationStyle.CWD


class TestVASPBenchmarkExtraction:
    """Tests for VASP benchmark timing extraction (task ct3.6)."""

    @pytest.fixture
    def parser(self):
        """Get the VASP parser instance."""
        return get_parser(DFTCode.VASP)

    def test_extract_total_timing(self, parser):
        """Test extraction of total CPU and elapsed time."""
        timing = parser.extract_timing_data(VASP_BENCHMARK_OUTPUT)

        assert "total_cpu_time_sec" in timing
        assert timing["total_cpu_time_sec"] == pytest.approx(125.678, rel=1e-3)

        assert "elapsed_time_sec" in timing
        assert timing["elapsed_time_sec"] == pytest.approx(45.234, rel=1e-3)

    def test_extract_loop_timing(self, parser):
        """Test extraction of LOOP (SCF) timing - summed across iterations."""
        timing = parser.extract_timing_data(VASP_BENCHMARK_OUTPUT)

        # Should sum both LOOP entries: 12.34 + 11.23 = 23.57
        assert "loop_cpu_time_sec" in timing
        assert timing["loop_cpu_time_sec"] == pytest.approx(23.57, rel=1e-2)

        # Real time: 15.67 + 14.34 = 30.01
        assert "loop_real_time_sec" in timing
        assert timing["loop_real_time_sec"] == pytest.approx(30.01, rel=1e-2)

        # Two ionic steps = two LOOP entries
        assert "loop_count" in timing
        assert timing["loop_count"] == 2

    def test_extract_loop_plus_timing(self, parser):
        """Test extraction of LOOP+ (ionic step) timing."""
        timing = parser.extract_timing_data(VASP_BENCHMARK_OUTPUT)

        assert "loop_plus_cpu_time_sec" in timing
        assert timing["loop_plus_cpu_time_sec"] == pytest.approx(24.56, rel=1e-2)

        assert "loop_plus_real_time_sec" in timing
        assert timing["loop_plus_real_time_sec"] == pytest.approx(31.45, rel=1e-2)

        assert "loop_plus_count" in timing
        assert timing["loop_plus_count"] == 1

    def test_extract_routine_timings(self, parser):
        """Test extraction of per-routine timing breakdown."""
        timing = parser.extract_timing_data(VASP_BENCHMARK_OUTPUT)

        assert "routine_timings" in timing
        routines = timing["routine_timings"]

        # Check POTLOK timing (summed across 2 ionic steps)
        assert "POTLOK" in routines
        assert routines["POTLOK"]["cpu_sec"] == pytest.approx(1.23 + 1.12, rel=1e-2)
        assert routines["POTLOK"]["real_sec"] == pytest.approx(1.45 + 1.34, rel=1e-2)
        assert routines["POTLOK"]["count"] == 2

        # Check SETDIJ timing
        assert "SETDIJ" in routines
        assert routines["SETDIJ"]["cpu_sec"] == pytest.approx(0.56 + 0.45, rel=1e-2)

        # Check EDDIAG timing
        assert "EDDIAG" in routines
        assert routines["EDDIAG"]["cpu_sec"] == pytest.approx(2.34 + 2.12, rel=1e-2)

        # Check CHARGE timing
        assert "CHARGE" in routines
        assert routines["CHARGE"]["cpu_sec"] == pytest.approx(1.23 + 1.12, rel=1e-2)

        # Check FORCES (only in second ionic step)
        assert "FORCES" in routines
        assert routines["FORCES"]["count"] == 1

        # Check STRESS (only in second ionic step)
        assert "STRESS" in routines
        assert routines["STRESS"]["count"] == 1

    def test_extract_memory_usage(self, parser):
        """Test extraction of memory usage per core."""
        timing = parser.extract_timing_data(VASP_BENCHMARK_OUTPUT)

        # 524288 kBytes = 512 MB
        assert "memory_per_core_mb" in timing
        assert timing["memory_per_core_mb"] == pytest.approx(512.0, rel=1e-2)

        # Maximum memory: 654321 kb = ~639 MB
        assert "maximum_memory_used_mb" in timing
        assert timing["maximum_memory_used_mb"] == pytest.approx(639.18, rel=1e-2)

    def test_extract_parallelization_settings(self, parser):
        """Test extraction of NPAR, NCORE, KPAR."""
        timing = parser.extract_timing_data(VASP_BENCHMARK_OUTPUT)

        assert "npar" in timing
        assert timing["npar"] == 4

        assert "ncore" in timing
        assert timing["ncore"] == 4

        assert "kpar" in timing
        assert timing["kpar"] == 2

    def test_extract_num_cores(self, parser):
        """Test extraction of number of cores."""
        timing = parser.extract_timing_data(VASP_BENCHMARK_OUTPUT)

        assert "num_cores" in timing
        assert timing["num_cores"] == 16

    def test_calculate_efficiency_metrics(self, parser):
        """Test calculation of efficiency metrics."""
        timing = parser.extract_timing_data(VASP_BENCHMARK_OUTPUT)

        # CPU to wall ratio
        assert "cpu_to_wall_ratio" in timing
        expected_ratio = 125.678 / 45.234
        assert timing["cpu_to_wall_ratio"] == pytest.approx(expected_ratio, rel=1e-3)

        # Parallel efficiency: CPU time / (wall time * num_cores)
        assert "parallel_efficiency" in timing
        expected_efficiency = 125.678 / (45.234 * 16)
        assert timing["parallel_efficiency"] == pytest.approx(expected_efficiency, rel=1e-3)

    def test_single_point_calculation(self, parser):
        """Test timing extraction for single-point (no ionic steps) calculation."""
        timing = parser.extract_timing_data(VASP_SINGLE_POINT_OUTPUT)

        # Should have total timing
        assert "total_cpu_time_sec" in timing
        assert timing["total_cpu_time_sec"] == pytest.approx(32.456, rel=1e-3)

        assert "elapsed_time_sec" in timing
        assert timing["elapsed_time_sec"] == pytest.approx(12.345, rel=1e-3)

        # Single LOOP entry
        assert "loop_count" in timing
        assert timing["loop_count"] == 1
        assert timing["loop_cpu_time_sec"] == pytest.approx(8.45, rel=1e-2)

        # No LOOP+ for single-point calculation
        assert "loop_plus_count" not in timing or timing.get("loop_plus_count", 0) == 0

        # Should have routine timings
        assert "routine_timings" in timing
        assert "POTLOK" in timing["routine_timings"]

        # Parallelization settings
        assert timing["npar"] == 2
        assert timing["ncore"] == 4
        assert timing["num_cores"] == 8

    @pytest.mark.asyncio
    async def test_benchmark_in_parsing_result(self, parser):
        """Test that benchmark data appears in ParsingResult metadata."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".out", delete=False) as f:
            f.write(VASP_BENCHMARK_OUTPUT)
            f.flush()
            result = await parser.parse(Path(f.name))

        assert result.success is True
        assert "benchmark" in result.metadata

        benchmark = result.metadata["benchmark"]
        assert "total_cpu_time_sec" in benchmark
        assert "elapsed_time_sec" in benchmark
        assert "routine_timings" in benchmark

    def test_empty_content(self, parser):
        """Test timing extraction with empty content."""
        timing = parser.extract_timing_data("")

        # Should return empty or minimal dict, not crash
        assert isinstance(timing, dict)
        assert "total_cpu_time_sec" not in timing

    def test_partial_content(self, parser):
        """Test timing extraction with partial/incomplete OUTCAR."""
        partial_content = """
 running on    4 total cores

   NPAR =       2

   POTLOK:  cpu time    1.23: real time    1.45
   LOOP:    cpu time   12.34: real time   15.67

  free  energy   TOTEN  =       -50.12345678 eV
"""
        timing = parser.extract_timing_data(partial_content)

        # Should extract what's available
        assert timing.get("num_cores") == 4
        assert timing.get("npar") == 2
        assert timing.get("loop_count") == 1
        assert "POTLOK" in timing.get("routine_timings", {})

        # These shouldn't be present (no timing section at end)
        assert "total_cpu_time_sec" not in timing


class TestVASPBenchmarkMetricsDataclass:
    """Tests for VASPBenchmarkMetrics dataclass."""

    def test_to_dict_complete(self):
        """Test to_dict with all fields populated."""
        from src.core.codes.parsers.vasp import VASPBenchmarkMetrics

        metrics = VASPBenchmarkMetrics(
            total_cpu_time_sec=100.0,
            elapsed_time_sec=50.0,
            loop_cpu_time_sec=80.0,
            loop_real_time_sec=40.0,
            loop_count=5,
            loop_plus_cpu_time_sec=95.0,
            loop_plus_real_time_sec=48.0,
            loop_plus_count=2,
            routine_timings={"POTLOK": {"cpu_sec": 10.0, "real_sec": 8.0, "count": 5}},
            memory_per_core_mb=512.0,
            maximum_memory_used_mb=1024.0,
            npar=4,
            ncore=4,
            kpar=2,
            num_cores=16,
            cpu_to_wall_ratio=2.0,
            parallel_efficiency=0.125,
        )

        d = metrics.to_dict()

        assert d["total_cpu_time_sec"] == 100.0
        assert d["elapsed_time_sec"] == 50.0
        assert d["loop_count"] == 5
        assert d["loop_plus_count"] == 2
        assert d["memory_per_core_mb"] == 512.0
        assert d["npar"] == 4
        assert d["num_cores"] == 16
        assert "POTLOK" in d["routine_timings"]

    def test_to_dict_minimal(self):
        """Test to_dict with minimal fields (default values)."""
        from src.core.codes.parsers.vasp import VASPBenchmarkMetrics

        metrics = VASPBenchmarkMetrics()
        d = metrics.to_dict()

        # Empty dict when nothing is set
        assert isinstance(d, dict)
        # Default loop_count is 0, which should not be included
        assert "loop_count" not in d
        assert "total_cpu_time_sec" not in d

    def test_to_dict_partial(self):
        """Test to_dict with some fields populated."""
        from src.core.codes.parsers.vasp import VASPBenchmarkMetrics

        metrics = VASPBenchmarkMetrics(
            total_cpu_time_sec=50.0,
            elapsed_time_sec=25.0,
            num_cores=8,
        )
        d = metrics.to_dict()

        assert d["total_cpu_time_sec"] == 50.0
        assert d["elapsed_time_sec"] == 25.0
        assert d["num_cores"] == 8
        assert "npar" not in d  # Not set
        assert "routine_timings" not in d  # Empty dict excluded
