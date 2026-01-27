"""Phonopy integration for phonon calculations via finite displacements.

Phonopy uses the finite displacement method to calculate phonon properties:
1. Generate displaced structures from equilibrium geometry
2. Calculate forces on each displaced structure (using VASP, QE, etc.)
3. Collect forces and compute force constants
4. Calculate phonon band structure, DOS, thermodynamic properties

This module provides a subprocess wrapper for phonopy commands,
enabling integration with the CrystalMath workflow system.

Workflow:
1. phonopy -d --dim="N N N" -c POSCAR  # Generate displacements
2. Run DFT on each POSCAR-XXX          # Calculate forces (parallel)
3. phonopy -f disp-*/vasprun.xml       # Collect forces -> FORCE_SETS
4. phonopy --fc FORCE_SETS             # Compute force constants
5. phonopy -c POSCAR -p band.conf      # Band structure
6. phonopy -c POSCAR -t mesh.conf      # DOS and thermodynamics
"""

from __future__ import annotations

import asyncio
import glob
import re
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class PhonopyDFTInterface(Enum):
    """DFT codes supported by phonopy for force calculations."""

    VASP = "vasp"
    QE = "qe"
    CRYSTAL = "crystal"
    ABINIT = "abinit"
    AIMS = "aims"


class PhonopyCalculationType(Enum):
    """Types of phonopy calculations."""

    DISPLACEMENT = "displacement"  # Generate displaced structures
    FORCE_COLLECTION = "force_collection"  # Collect forces from DFT
    FORCE_CONSTANTS = "force_constants"  # Compute force constants
    BAND_STRUCTURE = "band_structure"  # Phonon band structure
    DOS = "dos"  # Phonon density of states
    THERMAL = "thermal"  # Thermodynamic properties
    IRREPS = "irreps"  # Irreducible representations
    MODULATION = "modulation"  # Atomic modulations


@dataclass
class PhonopyConfig:
    """Configuration for phonopy calculations."""

    # Supercell dimensions
    supercell_dim: tuple[int, int, int] = (2, 2, 2)

    # DFT interface
    dft_code: PhonopyDFTInterface = PhonopyDFTInterface.VASP

    # Structure file
    structure_file: str = "POSCAR"  # Can be POSCAR, CONTCAR, or CIF

    # Displacement settings
    displacement_distance: float = 0.01  # Angstrom
    is_plusminus: bool = True  # Use +/- displacements for symmetry

    # Primitive cell settings
    primitive_axes: str = "AUTO"  # Or explicit matrix

    # Band structure settings
    band_path: str = "AUTO"  # Or explicit path like "G X M G"
    band_points: int = 101  # Points along each segment

    # DOS/mesh settings
    mesh: tuple[int, int, int] = (20, 20, 20)
    gamma_center: bool = True

    # Thermal properties
    tmin: float = 0.0  # K
    tmax: float = 1000.0  # K
    tstep: float = 10.0  # K

    # Output settings
    save_force_constants: bool = True
    write_yaml: bool = True

    def get_dim_string(self) -> str:
        """Return supercell dimension as phonopy command string."""
        return f"{self.supercell_dim[0]} {self.supercell_dim[1]} {self.supercell_dim[2]}"

    def get_mesh_string(self) -> str:
        """Return mesh as phonopy command string."""
        return f"{self.mesh[0]} {self.mesh[1]} {self.mesh[2]}"


@dataclass
class PhonopyOutput:
    """Results from phonopy calculations."""

    success: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Displacement generation results
    num_displacements: int = 0
    displacement_files: list[str] = field(default_factory=list)

    # Force constants
    force_constants_file: str | None = None
    force_sets_file: str | None = None

    # Band structure results
    band_yaml: str | None = None
    frequencies_at_gamma: list[float] = field(default_factory=list)
    has_imaginary: bool = False
    min_frequency: float | None = None

    # DOS results
    dos_yaml: str | None = None
    total_dos: dict[str, list[float]] | None = None

    # Thermal properties
    thermal_yaml: str | None = None
    free_energy: dict[str, list[float]] | None = None  # T, F
    entropy: dict[str, list[float]] | None = None  # T, S
    heat_capacity: dict[str, list[float]] | None = None  # T, Cv

    # Timing
    wall_time_seconds: float | None = None


class PhonopyWrapper:
    """Subprocess wrapper for phonopy commands.

    This class provides an async interface to phonopy for use in
    the CrystalMath workflow system. It handles:
    - Command construction
    - Process execution
    - Output parsing
    - Error handling
    """

    def __init__(
        self,
        work_dir: Path,
        config: PhonopyConfig | None = None,
        phonopy_cmd: str = "phonopy",
    ):
        """Initialize phonopy wrapper.

        Args:
            work_dir: Working directory for calculations.
            config: Phonopy configuration (uses defaults if None).
            phonopy_cmd: Path or name of phonopy executable.
        """
        self.work_dir = Path(work_dir)
        self.config = config or PhonopyConfig()
        self.phonopy_cmd = phonopy_cmd

    async def check_phonopy_available(self) -> bool:
        """Check if phonopy is available in the environment."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self.phonopy_cmd,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            return proc.returncode == 0
        except FileNotFoundError:
            return False

    async def get_phonopy_version(self) -> str | None:
        """Get phonopy version string."""
        try:
            proc = await asyncio.create_subprocess_exec(
                self.phonopy_cmd,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                return stdout.decode().strip()
        except FileNotFoundError:
            pass
        return None

    async def generate_displacements(self) -> PhonopyOutput:
        """Generate displaced structures for force calculations.

        Creates POSCAR-001, POSCAR-002, etc. in the work directory.

        Returns:
            PhonopyOutput with displacement information.
        """
        output = PhonopyOutput()

        # Build command
        cmd = [
            self.phonopy_cmd,
            "-d",
            "--dim",
            self.config.get_dim_string(),
            "-c",
            self.config.structure_file,
        ]

        if self.config.displacement_distance != 0.01:
            cmd.extend(["--amplitude", str(self.config.displacement_distance)])

        if self.config.is_plusminus:
            cmd.append("--pm")

        # Run phonopy
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                output.errors.append(f"phonopy -d failed: {stderr.decode()}")
                return output

            # Count generated displacements
            poscar_files = list(self.work_dir.glob("POSCAR-*"))
            output.num_displacements = len(poscar_files)
            output.displacement_files = [f.name for f in sorted(poscar_files)]
            output.success = output.num_displacements > 0

            if output.num_displacements == 0:
                output.errors.append("No displacement files generated")

        except Exception as e:
            output.errors.append(f"Failed to run phonopy: {e}")

        return output

    async def collect_forces_vasp(self, disp_dirs: list[str] | None = None) -> PhonopyOutput:
        """Collect forces from VASP calculations.

        Expects vasprun.xml files in disp-XXX directories.

        Args:
            disp_dirs: List of displacement directories. If None, auto-detect.

        Returns:
            PhonopyOutput with FORCE_SETS information.
        """
        output = PhonopyOutput()

        # Auto-detect displacement directories
        if disp_dirs is None:
            disp_dirs = sorted(glob.glob(str(self.work_dir / "disp-*")))
            if not disp_dirs:
                # Try alternative naming
                disp_dirs = sorted(glob.glob(str(self.work_dir / "POSCAR-*")))

        if not disp_dirs:
            output.errors.append("No displacement directories found")
            return output

        # Build force collection command
        vasprun_pattern = "disp-*/vasprun.xml"
        cmd = [
            self.phonopy_cmd,
            "-f",
            vasprun_pattern,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Need shell expansion for glob
            )
            stdout, stderr = await proc.communicate()

            # Check for FORCE_SETS file
            force_sets = self.work_dir / "FORCE_SETS"
            if force_sets.exists():
                output.force_sets_file = str(force_sets)
                output.success = True
            else:
                # Try with explicit file list
                vasprun_files = sorted(glob.glob(str(self.work_dir / "disp-*/vasprun.xml")))
                if vasprun_files:
                    cmd = [self.phonopy_cmd, "-f"] + vasprun_files
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        cwd=self.work_dir,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await proc.communicate()

                    if force_sets.exists():
                        output.force_sets_file = str(force_sets)
                        output.success = True
                    else:
                        output.errors.append("FORCE_SETS not created")
                else:
                    output.errors.append("No vasprun.xml files found in disp-* directories")

        except Exception as e:
            output.errors.append(f"Force collection failed: {e}")

        return output

    async def collect_forces_qe(self) -> PhonopyOutput:
        """Collect forces from Quantum ESPRESSO calculations.

        Expects *.out files in displacement directories.

        Returns:
            PhonopyOutput with FORCE_SETS information.
        """
        output = PhonopyOutput()

        # Find QE output files
        qe_outputs = sorted(glob.glob(str(self.work_dir / "disp-*/*.out")))
        if not qe_outputs:
            output.errors.append("No QE output files found")
            return output

        cmd = [
            self.phonopy_cmd,
            "-f",
            "--qe",
        ] + qe_outputs

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            force_sets = self.work_dir / "FORCE_SETS"
            if force_sets.exists():
                output.force_sets_file = str(force_sets)
                output.success = True
            else:
                output.errors.append("FORCE_SETS not created")

        except Exception as e:
            output.errors.append(f"Force collection failed: {e}")

        return output

    async def compute_force_constants(self) -> PhonopyOutput:
        """Compute force constants from FORCE_SETS.

        Creates FORCE_CONSTANTS file.

        Returns:
            PhonopyOutput with force constants information.
        """
        output = PhonopyOutput()

        # Check FORCE_SETS exists
        force_sets = self.work_dir / "FORCE_SETS"
        if not force_sets.exists():
            output.errors.append("FORCE_SETS not found - run force collection first")
            return output

        cmd = [
            self.phonopy_cmd,
            "--fc",
            "FORCE_SETS",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            fc_file = self.work_dir / "FORCE_CONSTANTS"
            if fc_file.exists():
                output.force_constants_file = str(fc_file)
                output.success = True
            else:
                output.errors.append("FORCE_CONSTANTS not created")

        except Exception as e:
            output.errors.append(f"Force constants calculation failed: {e}")

        return output

    async def compute_band_structure(
        self,
        band_conf: str | None = None,
    ) -> PhonopyOutput:
        """Compute phonon band structure.

        Args:
            band_conf: Path to band.conf file. If None, generates one.

        Returns:
            PhonopyOutput with band structure information.
        """
        output = PhonopyOutput()

        # Generate band.conf if not provided
        if band_conf is None:
            band_conf_path = self.work_dir / "band.conf"
            band_conf_content = f"""# Phonon band structure
DIM = {self.config.get_dim_string()}
PRIMITIVE_AXES = {self.config.primitive_axes}
BAND = {self.config.band_path}
BAND_POINTS = {self.config.band_points}
BAND_CONNECTION = .TRUE.
"""
            band_conf_path.write_text(band_conf_content)
            band_conf = str(band_conf_path)

        cmd = [
            self.phonopy_cmd,
            "-c",
            self.config.structure_file,
            "-p",
            band_conf,
            "--gnuplot",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            # Check for band.yaml
            band_yaml = self.work_dir / "band.yaml"
            if band_yaml.exists():
                output.band_yaml = str(band_yaml)
                output.success = True

                # Parse for imaginary frequencies
                content = band_yaml.read_text()
                if "imaginary" in content.lower():
                    output.has_imaginary = True
                    output.warnings.append(
                        "Imaginary frequencies detected - structure may be unstable"
                    )

                # Extract frequencies at Gamma
                output.frequencies_at_gamma = self._parse_gamma_frequencies(content)
                if output.frequencies_at_gamma:
                    output.min_frequency = min(output.frequencies_at_gamma)
            else:
                output.errors.append("band.yaml not created")

        except Exception as e:
            output.errors.append(f"Band structure calculation failed: {e}")

        return output

    async def compute_dos_and_thermal(
        self,
        mesh_conf: str | None = None,
    ) -> PhonopyOutput:
        """Compute phonon DOS and thermodynamic properties.

        Args:
            mesh_conf: Path to mesh.conf file. If None, generates one.

        Returns:
            PhonopyOutput with DOS and thermal information.
        """
        output = PhonopyOutput()

        # Generate mesh.conf if not provided
        if mesh_conf is None:
            mesh_conf_path = self.work_dir / "mesh.conf"
            mesh_conf_content = f"""# Phonon DOS and thermal properties
DIM = {self.config.get_dim_string()}
PRIMITIVE_AXES = {self.config.primitive_axes}
MP = {self.config.get_mesh_string()}
GAMMA_CENTER = .{"TRUE" if self.config.gamma_center else "FALSE"}.
TPROP = .TRUE.
TMIN = {self.config.tmin}
TMAX = {self.config.tmax}
TSTEP = {self.config.tstep}
"""
            mesh_conf_path.write_text(mesh_conf_content)
            mesh_conf = str(mesh_conf_path)

        cmd = [
            self.phonopy_cmd,
            "-c",
            self.config.structure_file,
            "-t",
            mesh_conf,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            # Check for output files
            mesh_yaml = self.work_dir / "mesh.yaml"
            thermal_yaml = self.work_dir / "thermal_properties.yaml"

            if mesh_yaml.exists():
                output.dos_yaml = str(mesh_yaml)

            if thermal_yaml.exists():
                output.thermal_yaml = str(thermal_yaml)
                output.success = True

                # Parse thermal properties
                thermal_data = self._parse_thermal_properties(thermal_yaml.read_text())
                output.free_energy = thermal_data.get("free_energy")
                output.entropy = thermal_data.get("entropy")
                output.heat_capacity = thermal_data.get("heat_capacity")
            else:
                output.errors.append("thermal_properties.yaml not created")

        except Exception as e:
            output.errors.append(f"DOS/thermal calculation failed: {e}")

        return output

    def _parse_gamma_frequencies(self, band_yaml_content: str) -> list[float]:
        """Extract frequencies at Gamma point from band.yaml."""
        frequencies = []
        # Simple regex to find frequency values at q=[0,0,0]
        # This is a simplified parser - full YAML parsing would be more robust
        in_gamma = False
        for line in band_yaml_content.split("\n"):
            if "q-position:" in line and "0.0" in line:
                in_gamma = True
            elif in_gamma and "frequency:" in line:
                match = re.search(r"frequency:\s*([-\d.]+)", line)
                if match:
                    frequencies.append(float(match.group(1)))
            elif in_gamma and "q-position:" in line:
                break  # Past Gamma point
        return frequencies

    def _parse_thermal_properties(
        self, thermal_yaml_content: str
    ) -> dict[str, dict[str, list[float]]]:
        """Parse thermal_properties.yaml for thermodynamic data."""
        result: dict[str, Any] = {
            "free_energy": {"temperature": [], "value": []},
            "entropy": {"temperature": [], "value": []},
            "heat_capacity": {"temperature": [], "value": []},
        }

        # Simple line-by-line parsing
        current_temp = None
        for line in thermal_yaml_content.split("\n"):
            if "temperature:" in line:
                match = re.search(r"temperature:\s*([\d.]+)", line)
                if match:
                    current_temp = float(match.group(1))
            elif current_temp is not None:
                if "free_energy:" in line:
                    match = re.search(r"free_energy:\s*([-\d.]+)", line)
                    if match:
                        result["free_energy"]["temperature"].append(current_temp)
                        result["free_energy"]["value"].append(float(match.group(1)))
                elif "entropy:" in line:
                    match = re.search(r"entropy:\s*([\d.]+)", line)
                    if match:
                        result["entropy"]["temperature"].append(current_temp)
                        result["entropy"]["value"].append(float(match.group(1)))
                elif "heat_capacity:" in line:
                    match = re.search(r"heat_capacity:\s*([\d.]+)", line)
                    if match:
                        result["heat_capacity"]["temperature"].append(current_temp)
                        result["heat_capacity"]["value"].append(float(match.group(1)))

        return result

    def setup_displacement_directories(
        self,
        dft_code: PhonopyDFTInterface = PhonopyDFTInterface.VASP,
        template_dir: Path | None = None,
    ) -> list[Path]:
        """Create directories for each displacement with required input files.

        Args:
            dft_code: DFT code to prepare inputs for.
            template_dir: Directory containing template input files (INCAR, KPOINTS, etc.)

        Returns:
            List of created displacement directories.
        """
        created_dirs = []

        # Find displacement files
        poscar_files = sorted(self.work_dir.glob("POSCAR-*"))
        if not poscar_files:
            return created_dirs

        for poscar in poscar_files:
            # Extract displacement number (POSCAR-001 -> 001)
            num = poscar.name.split("-")[-1]
            disp_dir = self.work_dir / f"disp-{num}"
            disp_dir.mkdir(exist_ok=True)

            # Copy POSCAR
            shutil.copy(poscar, disp_dir / "POSCAR")

            # Copy template files if provided
            if template_dir and template_dir.exists():
                if dft_code == PhonopyDFTInterface.VASP:
                    for fname in ["INCAR", "KPOINTS", "POTCAR"]:
                        src = template_dir / fname
                        if src.exists():
                            shutil.copy(src, disp_dir / fname)

                elif dft_code == PhonopyDFTInterface.QE:
                    # For QE, need to modify input template with new structure
                    pass  # Would require structure-aware template generation

            created_dirs.append(disp_dir)

        return created_dirs


def get_phonopy_force_collection_command(
    dft_code: PhonopyDFTInterface,
    output_pattern: str,
) -> list[str]:
    """Generate phonopy force collection command for a DFT code.

    Args:
        dft_code: DFT code used for force calculations.
        output_pattern: Glob pattern for output files.

    Returns:
        Command list for subprocess execution.
    """
    cmd = ["phonopy", "-f"]

    if dft_code == PhonopyDFTInterface.VASP:
        # VASP uses vasprun.xml
        cmd.append(output_pattern)  # e.g., "disp-*/vasprun.xml"

    elif dft_code == PhonopyDFTInterface.QE:
        cmd.extend(["--qe", output_pattern])

    elif dft_code == PhonopyDFTInterface.CRYSTAL:
        cmd.extend(["--crystal", output_pattern])

    return cmd


def generate_phonopy_workflow_commands(
    config: PhonopyConfig,
    structure_file: str = "POSCAR",
) -> dict[str, list[str]]:
    """Generate all phonopy commands for a complete workflow.

    Returns dictionary of step names to commands.
    """
    dim = config.get_dim_string()

    return {
        "generate_displacements": [
            "phonopy",
            "-d",
            "--dim",
            dim,
            "-c",
            structure_file,
        ],
        "compute_force_constants": [
            "phonopy",
            "--fc",
            "FORCE_SETS",
        ],
        "band_structure": [
            "phonopy",
            "-c",
            structure_file,
            "-p",
            "band.conf",
            "--gnuplot",
        ],
        "dos_thermal": [
            "phonopy",
            "-c",
            structure_file,
            "-t",
            "mesh.conf",
        ],
    }


__all__ = [
    # Configuration
    "PhonopyConfig",
    "PhonopyOutput",
    "PhonopyDFTInterface",
    "PhonopyCalculationType",
    # Main wrapper class
    "PhonopyWrapper",
    # Utility functions
    "get_phonopy_force_collection_command",
    "generate_phonopy_workflow_commands",
]
