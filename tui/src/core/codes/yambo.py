"""YAMBO code configuration and input/output handling.

YAMBO is a many-body perturbation theory code for optical and electronic
properties calculations including:
- GW quasiparticle corrections
- Bethe-Salpeter Equation (BSE) for optical absorption
- Non-linear optics (shift current, bulk photovoltaic effect)

YAMBO requires a pre-existing QE calculation and uses the p2y converter
to create its SAVE database.

Workflow:
1. QE SCF calculation (pw.x)
2. QE NSCF calculation (pw.x with wf_collect=.true.)
3. p2y conversion (creates SAVE directory)
4. yambo initialization (creates ns.db1)
5. yambo calculation (GW, BSE, or non-linear)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .base import DFTCode, DFTCodeConfig, InvocationStyle
from .registry import register_code


class YAMBOCalculationType(Enum):
    """Types of YAMBO calculations."""

    SETUP = "setup"  # Initial database creation (p2y + yambo)
    GW = "gw"  # GW quasiparticle corrections
    BSE = "bse"  # Bethe-Salpeter equation (optical absorption)
    SHIFT_CURRENT = "shift_current"  # Non-linear optics (bulk photovoltaic)
    OPTICS_IP = "optics_ip"  # Independent particle optical absorption


# YAMBO SAVE database files
YAMBO_SAVE_FILES = [
    "ns.db1",  # Core database (structure, k-points)
    "ns.wf",  # Wavefunction coefficients
    "ns.kb_pp",  # Pseudopotential data (if stored)
]

# YAMBO calculation output patterns
YAMBO_OUTPUT_PATTERNS = {
    YAMBOCalculationType.GW: [
        "o-*.qp",  # Quasiparticle corrections
        "r-*.qp",  # Report file
        "l-*.qp",  # Log file
    ],
    YAMBOCalculationType.BSE: [
        "o-*.eps*",  # Dielectric function
        "o-*.alpha*",  # Absorption coefficient
        "r-*.bse",  # Report file
        "l-*.bse",  # Log file
    ],
    YAMBOCalculationType.SHIFT_CURRENT: [
        "o-*.YPP-SC*",  # Shift current tensor
        "o-*.j_",  # Current components
        "r-*.nloptics",  # Report file
        "l-*.nloptics",  # Log file
    ],
    YAMBOCalculationType.OPTICS_IP: [
        "o-*.eps_q1*",  # IP dielectric function
        "o-*.alpha*",  # Absorption
        "r-*.optics",  # Report file
    ],
}


@dataclass
class GWParameters:
    """Parameters for GW quasiparticle calculations.

    Default values chosen for reasonable accuracy/cost tradeoff.
    """

    # Band ranges
    bands_screening: tuple[int, int] = (1, 200)  # Bands for screening (BndsRnXp)
    bands_self_energy: tuple[int, int] = (1, 200)  # Bands for self-energy (GbndRnge)

    # Cutoffs
    screening_cutoff: float = 5.0  # Ry, NGsBlkXp
    exchange_cutoff: float = 30.0  # Ry, EXXRLvcs
    correlation_cutoff: float = 30.0  # Ry, VXCRLvcs

    # QPk range: which k-points and bands to compute QP corrections for
    qp_kpoints: tuple[int, int] = (1, 10)  # k-point range
    qp_bands: tuple[int, int] = (1, 50)  # band range within those k-points

    # Plasmon-pole model
    ppmodel: str = "HL"  # Hybertsen-Louie plasmon pole

    # Convergence
    gw_iterations: int = 0  # 0 = one-shot G0W0

    def to_yambo_input(self) -> str:
        """Generate YAMBO input text for GW calculation."""
        return f"""# GW Quasiparticle Calculation
gwcalc                     # Enable GW calculation
GWoIter = {self.gw_iterations}             # Number of GW iterations (0 = G0W0)

# Screening calculation
BndsRnXp= {self.bands_screening[0]} | {self.bands_screening[1]}    # Bands for polarization
NGsBlkXp= {self.screening_cutoff} Ry         # G-vectors for screening

# Self-energy calculation
GbndRnge= {self.bands_self_energy[0]} | {self.bands_self_energy[1]}    # Bands for self-energy

# Plasmon-pole model
ppmodel = "{self.ppmodel}"         # Hybertsen-Louie

# Exchange-correlation cutoffs
EXXRLvcs= {self.exchange_cutoff} Ry          # Exchange cutoff
VXCRLvcs= {self.correlation_cutoff} Ry          # Correlation cutoff

# QP corrections k-points and bands
%QPkrange
 {self.qp_kpoints[0]}| {self.qp_kpoints[1]}|  {self.qp_bands[0]}| {self.qp_bands[1]}
%
"""


@dataclass
class BSEParameters:
    """Parameters for BSE optical absorption calculations."""

    # Band ranges (valence and conduction for excitons)
    bse_bands: tuple[int, int] = (20, 80)  # BSEBands

    # Cutoffs
    exchange_cutoff: float = 30.0  # Ry, BSENGexx
    correlation_cutoff: float = 2.0  # Ry, BSENGBlk

    # Energy range for spectra
    energy_range: tuple[float, float] = (0.0, 6.0)  # eV
    energy_steps: int = 500
    broadening: float = 0.05  # eV, BDmRange

    # Solver
    solver: str = "h"  # Haydock iterative solver
    solver_iterations: int = 500  # BSSNIter

    # BSE mode
    bse_mode: str = "resonant"  # BSEmod: resonant or coupling
    kernel_mode: str = "SEX"  # BSKmod: SEX (screened exchange)

    # Light polarization direction
    polarization: tuple[float, float, float] = (1.0, 0.0, 0.0)  # BLongDir

    # Property to compute
    property: str = "abs"  # BSSProp: abs, kerr, magn

    def to_yambo_input(self) -> str:
        """Generate YAMBO input text for BSE calculation."""
        return f"""# BSE Optical Absorption Calculation
bse                        # Enable BSE
optics                     # Compute optical properties

# BSE configuration
BSEmod = "{self.bse_mode}"      # Resonant or coupling
BSKmod = "{self.kernel_mode}"          # Screened exchange kernel

# Cutoffs
BSENGBlk= {self.correlation_cutoff} Ry         # Correlation (W) cutoff
BSENGexx= {self.exchange_cutoff} Ry         # Exchange cutoff

# Band range for excitons
%BSEBands
  {self.bse_bands[0]} | {self.bse_bands[1]}
%

# Solver configuration
BSSmod = "{self.solver}"              # Haydock iterative solver
BSSNIter = {self.solver_iterations}          # Max iterations

# Energy range for spectrum
%BEnRange
 {self.energy_range[0]} | {self.energy_range[1]} | eV
%
BEnSteps= {self.energy_steps}           # Energy resolution

# Broadening
BDmRange= {self.broadening} | {self.broadening} eV

# Light polarization direction
%BLongDir
 {self.polarization[0]} | {self.polarization[1]} | {self.polarization[2]}
%

# Output property
BSSProp = "{self.property}"          # Absorption spectrum
"""


@dataclass
class ShiftCurrentParameters:
    """Parameters for shift current (bulk photovoltaic) calculations.

    The shift current is a non-linear optical response that generates
    DC current from light absorption in non-centrosymmetric materials.
    """

    # Band range for optical transitions
    nl_bands: tuple[int, int] = (1, 200)  # NLBands

    # Energy range for photon energies
    energy_range: tuple[float, float] = (0.5, 4.0)  # eV
    energy_steps: int = 200

    # Broadening (lifetime)
    damping: float = 0.05  # eV, NLDamping

    # Electric field direction and intensity
    field_direction: tuple[float, float, float] = (1.0, 0.0, 0.0)
    field_intensity: float = 1000.0  # kW/m^2

    # Time propagation parameters
    total_time: float = 50.0  # fs, NLTime
    integration_time: float = 10.0  # fs, NLIntTime
    time_step: float = 0.002  # fs, NLstep

    # Correlation level
    correlation: str = "IPA"  # Independent particle approx, or "HARTREE", "LRC"

    # Output type
    output: str = "current"  # NLoutput

    def to_yambo_input(self) -> str:
        """Generate YAMBO input text for shift current calculation."""
        return f"""# Shift Current (Bulk Photovoltaic Effect) Calculation
nl                         # Non-linear optics
shiftc                     # Shift current calculation

# Band range
%NLBands
 {self.nl_bands[0]} | {self.nl_bands[1]}
%

# Photon energy range
%NLEnRange
 {self.energy_range[0]} | {self.energy_range[1]} | eV
%
NLEnSteps= {self.energy_steps}          # Energy points

# Lifetime broadening
NLDamping= {self.damping} eV

# Electric field configuration
%Field1_Dir
 {self.field_direction[0]} | {self.field_direction[1]} | {self.field_direction[2]}
%
Field1_Int= {self.field_intensity} kWLm2

# Time propagation parameters
NLTime= {self.total_time} fs             # Total propagation time
NLIntTime= {self.integration_time} fs          # Integration time for current
NLstep= {self.time_step} fs             # Time step

# Correlation level
NLCorrelation= "{self.correlation}"   # IPA, HARTREE, or LRC

# Output
NLoutput= "{self.output}"        # Current output
"""


@dataclass
class YAMBOInputConfig:
    """Complete YAMBO calculation configuration.

    Combines calculation type with specific parameters and
    optional reference to QE calculation directory.
    """

    calculation_type: YAMBOCalculationType
    job_name: str = "yambo"

    # Calculation-specific parameters
    gw_params: GWParameters | None = None
    bse_params: BSEParameters | None = None
    shift_params: ShiftCurrentParameters | None = None

    # Reference to QE SAVE database
    save_path: Path | None = None

    # Parallelization
    mpi_processes: int = 1
    omp_threads: int = 1

    # Container settings (for Apptainer execution)
    use_container: bool = False
    container_path: str | None = None

    def validate(self) -> list[str]:
        """Validate configuration and return list of issues."""
        issues = []

        # Check calculation type has matching parameters
        if self.calculation_type == YAMBOCalculationType.GW and not self.gw_params:
            issues.append("GW calculation requires gw_params")
        if self.calculation_type == YAMBOCalculationType.BSE and not self.bse_params:
            issues.append("BSE calculation requires bse_params")
        if self.calculation_type == YAMBOCalculationType.SHIFT_CURRENT and not self.shift_params:
            issues.append("Shift current calculation requires shift_params")

        # Check SAVE database exists if specified
        if self.save_path:
            save_dir = Path(self.save_path)
            if not save_dir.exists():
                issues.append(f"SAVE directory not found: {save_dir}")
            elif not (save_dir / "ns.db1").exists():
                issues.append(f"ns.db1 not found in SAVE directory: {save_dir}")

        return issues

    def generate_input(self) -> str:
        """Generate YAMBO input file content based on calculation type."""
        if self.calculation_type == YAMBOCalculationType.SETUP:
            return "# YAMBO setup - run p2y first, then yambo for initialization\n"

        if self.calculation_type == YAMBOCalculationType.GW:
            if self.gw_params:
                return self.gw_params.to_yambo_input()
            return GWParameters().to_yambo_input()

        if self.calculation_type == YAMBOCalculationType.BSE:
            if self.bse_params:
                return self.bse_params.to_yambo_input()
            return BSEParameters().to_yambo_input()

        if self.calculation_type == YAMBOCalculationType.SHIFT_CURRENT:
            if self.shift_params:
                return self.shift_params.to_yambo_input()
            return ShiftCurrentParameters().to_yambo_input()

        if self.calculation_type == YAMBOCalculationType.OPTICS_IP:
            return """# Independent Particle Optical Absorption
optics                     # Enable optics
chi                        # Compute polarizability

# Energy range
%EnRange
 0.0 | 10.0 | eV
%
ETStps= 500               # Energy steps

# Broadening
DmRnge= 0.05 | 0.05 | eV

# Directions
%LongDrXd
 1.0 | 0.0 | 0.0
%
"""

        raise ValueError(f"Unknown calculation type: {self.calculation_type}")


@dataclass
class YAMBOOutput:
    """Parsed YAMBO calculation output."""

    calculation_type: YAMBOCalculationType
    converged: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # GW results
    qp_corrections: dict[str, Any] | None = None
    band_gap_gw: float | None = None  # eV

    # BSE results
    optical_gap: float | None = None  # eV (first bright exciton)
    exciton_binding: float | None = None  # eV
    absorption_spectrum: dict[str, list[float]] | None = None

    # Shift current results
    shift_current_tensor: dict[str, Any] | None = None

    # Timing
    wall_time_seconds: float | None = None

    @classmethod
    def parse_report(cls, report_content: str, calc_type: YAMBOCalculationType) -> YAMBOOutput:
        """Parse YAMBO report file (r-*) to extract results.

        Args:
            report_content: Content of the report file.
            calc_type: Type of calculation to guide parsing.

        Returns:
            YAMBOOutput with extracted data.
        """
        output = cls(calculation_type=calc_type)

        # Check for completion
        if "[TIMING]" in report_content or "Total time" in report_content:
            output.converged = True

        # Check for errors
        if "ERROR" in report_content or "STOP" in report_content:
            output.converged = False
            # Extract error messages
            for line in report_content.split("\n"):
                if "ERROR" in line or "STOP" in line:
                    output.errors.append(line.strip())

        # Check for warnings
        for line in report_content.split("\n"):
            if "WARNING" in line.upper():
                output.warnings.append(line.strip())

        # Parse timing
        for line in report_content.split("\n"):
            if "Total time" in line:
                try:
                    # Format: "Total time : XX.XX s"
                    parts = line.split(":")
                    if len(parts) >= 2:
                        time_str = parts[-1].strip().replace("s", "").strip()
                        output.wall_time_seconds = float(time_str)
                except (ValueError, IndexError):
                    pass

        return output

    @classmethod
    def parse_qp_file(cls, qp_content: str) -> dict[str, Any]:
        """Parse quasiparticle corrections file (o-*.qp).

        Returns dictionary with:
        - k_points: list of k-point indices
        - bands: list of band indices
        - e_dft: DFT eigenvalues (eV)
        - e_qp: QP eigenvalues (eV)
        - delta_e: QP corrections (eV)
        """
        result = {
            "k_points": [],
            "bands": [],
            "e_dft": [],
            "e_qp": [],
            "delta_e": [],
        }

        for line in qp_content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split()
            if len(parts) >= 5:
                try:
                    result["k_points"].append(int(parts[0]))
                    result["bands"].append(int(parts[1]))
                    result["e_dft"].append(float(parts[2]))
                    result["e_qp"].append(float(parts[3]))
                    result["delta_e"].append(float(parts[4]))
                except (ValueError, IndexError):
                    continue

        return result

    @classmethod
    def parse_eps_file(cls, eps_content: str) -> dict[str, list[float]]:
        """Parse dielectric function file (o-*.eps*).

        Returns dictionary with:
        - energy: photon energies (eV)
        - eps_real: real part of dielectric function
        - eps_imag: imaginary part of dielectric function
        """
        result: dict[str, list[float]] = {
            "energy": [],
            "eps_real": [],
            "eps_imag": [],
        }

        for line in eps_content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = line.split()
            if len(parts) >= 3:
                try:
                    result["energy"].append(float(parts[0]))
                    result["eps_real"].append(float(parts[1]))
                    result["eps_imag"].append(float(parts[2]))
                except (ValueError, IndexError):
                    continue

        return result


def get_yambo_executables() -> dict[str, str]:
    """Return dictionary of YAMBO executables and their purposes."""
    return {
        "p2y": "QE to YAMBO converter",
        "yambo": "Main YAMBO executable",
        "ypp": "YAMBO post-processing",
        "yambo_nl": "Non-linear optics (shift current)",
        "ypp_nl": "Non-linear post-processing (symmetry reduction)",
    }


def get_required_files_for_calculation(calc_type: YAMBOCalculationType) -> list[str]:
    """Get list of required files for a YAMBO calculation type."""
    base_files = ["SAVE"]  # All calculations need SAVE database

    if calc_type == YAMBOCalculationType.SETUP:
        # For setup, need QE output
        return ["prefix.save"]  # QE save directory

    if calc_type == YAMBOCalculationType.GW:
        return base_files

    if calc_type == YAMBOCalculationType.BSE:
        # BSE typically needs GW corrections
        return base_files + ["ndb.QP"]

    if calc_type == YAMBOCalculationType.SHIFT_CURRENT:
        return base_files

    return base_files


def generate_p2y_command(qe_save_dir: Path) -> list[str]:
    """Generate command to convert QE output to YAMBO format."""
    return ["p2y", "-O", str(qe_save_dir)]


def generate_yambo_setup_command() -> list[str]:
    """Generate command to initialize YAMBO database."""
    return ["yambo"]


def generate_yambo_gw_command(input_file: str, job_name: str) -> list[str]:
    """Generate command for GW calculation."""
    return ["yambo", "-F", input_file, "-J", job_name, "-o", "g"]


def generate_yambo_bse_command(input_file: str, job_name: str) -> list[str]:
    """Generate command for BSE calculation."""
    return ["yambo", "-F", input_file, "-J", job_name, "-o", "b"]


def generate_yambo_shift_command(input_file: str, job_name: str) -> list[str]:
    """Generate command for shift current calculation using yambo_nl."""
    return ["yambo_nl", "-F", input_file, "-J", job_name]


def generate_ypp_symmetry_command() -> list[str]:
    """Generate command to reduce symmetries for non-linear optics."""
    return ["ypp_nl", "-y"]


# YAMBO DFTCodeConfig
YAMBO_CONFIG = DFTCodeConfig(
    name="yambo",
    display_name="YAMBO",
    # YAMBO uses various input extensions
    input_extensions=[".in"],
    output_extension=".out",
    # YAMBO has many auxiliary files
    auxiliary_inputs={
        "SAVE": "SAVE",  # Core database directory
        "ndb.QP": "ndb.QP",  # GW corrections (for BSE)
    },
    auxiliary_outputs={
        "o-*.qp": "o-*.qp",  # QP corrections
        "o-*.eps*": "o-*.eps*",  # Dielectric function
        "o-*.alpha*": "o-*.alpha*",  # Absorption
        "r-*": "r-*",  # Report files
        "l-*": "l-*",  # Log files
        "ndb.*": "ndb.*",  # Database files
    },
    # Executables
    serial_executable="yambo",
    parallel_executable="mpirun yambo",
    invocation_style=InvocationStyle.FLAG,  # yambo -F input.in
    # Environment
    root_env_var="YAMBO_ROOT",
    bashrc_pattern="yambo.bashrc",
    # Parsing
    energy_unit="eV",
    convergence_patterns=[
        "[TIMING]",
        "Total time",
        "Game Over",
    ],
    error_patterns=[
        "ERROR",
        "STOP",
        "Aborted",
        "segmentation fault",
        "core dumped",
    ],
)


# Auto-register when module is imported
register_code(DFTCode.YAMBO, YAMBO_CONFIG)


__all__ = [
    # Configuration
    "YAMBO_CONFIG",
    "YAMBOCalculationType",
    "YAMBOInputConfig",
    "YAMBOOutput",
    # Parameter classes
    "GWParameters",
    "BSEParameters",
    "ShiftCurrentParameters",
    # File lists
    "YAMBO_SAVE_FILES",
    "YAMBO_OUTPUT_PATTERNS",
    # Command generators
    "get_yambo_executables",
    "get_required_files_for_calculation",
    "generate_p2y_command",
    "generate_yambo_setup_command",
    "generate_yambo_gw_command",
    "generate_yambo_bse_command",
    "generate_yambo_shift_command",
    "generate_ypp_symmetry_command",
]
