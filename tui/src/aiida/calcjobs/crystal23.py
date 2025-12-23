"""
AiiDA CalcJob for CRYSTAL23 calculations.

This module provides the Crystal23Calculation CalcJob class for running
CRYSTAL23 crystalOMP/PcrystalOMP calculations through AiiDA.

The CalcJob handles:
    - Input file generation (d12 format)
    - Job submission and resource management
    - Output file retrieval
    - Result parsing via Crystal23Parser

Example:
    >>> from aiida import engine, orm
    >>> from src.aiida.calcjobs.crystal23 import Crystal23Calculation
    >>>
    >>> builder = Crystal23Calculation.get_builder()
    >>> builder.code = orm.load_code("crystalOMP@localhost")
    >>> builder.structure = structure_data
    >>> builder.parameters = orm.Dict(dict={...})
    >>> result = engine.run(builder)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from aiida import orm
from aiida.common import datastructures
from aiida.engine import CalcJob

if TYPE_CHECKING:
    from aiida.engine import CalcInfo


class Crystal23Calculation(CalcJob):
    """
    AiiDA CalcJob for CRYSTAL23 calculations.

    Replaces the custom runners (local.py, ssh_runner.py, slurm_runner.py)
    with AiiDA's unified job submission framework.
    """

    # Input/output file names
    _INPUT_FILE = "INPUT"
    _OUTPUT_FILE = "OUTPUT"

    @classmethod
    def define(cls, spec: datastructures.CalcJobProcessSpec) -> None:
        """Define CalcJob inputs, outputs, and exit codes."""
        super().define(spec)

        # Input namespace
        spec.input_namespace("crystal", help="CRYSTAL23 specific inputs")

        # Required inputs
        spec.input(
            "crystal.input_file",
            valid_type=orm.SinglefileData,
            required=False,
            help="Pre-built d12 input file (alternative to structure+parameters)",
        )
        spec.input(
            "crystal.structure",
            valid_type=orm.StructureData,
            required=False,
            help="Crystal structure (alternative to input_file)",
        )
        spec.input(
            "crystal.parameters",
            valid_type=orm.Dict,
            required=False,
            help="CRYSTAL23 input parameters (used with structure)",
        )
        spec.input(
            "crystal.basis_set",
            valid_type=orm.Dict,
            required=False,
            help="Basis set definitions (atomic species -> basis)",
        )
        spec.input(
            "crystal.wavefunction",
            valid_type=orm.SinglefileData,
            required=False,
            help="Restart wavefunction (fort.9 from previous calculation)",
        )
        spec.input(
            "crystal.gui_file",
            valid_type=orm.SinglefileData,
            required=False,
            help="External geometry file (.gui format)",
        )

        # Computational settings
        spec.input(
            "metadata.options.input_filename",
            valid_type=str,
            default=cls._INPUT_FILE,
            help="Name of the input file",
        )
        spec.input(
            "metadata.options.output_filename",
            valid_type=str,
            default=cls._OUTPUT_FILE,
            help="Name of the output file",
        )
        spec.input(
            "metadata.options.resources",
            valid_type=dict,
            default={"num_machines": 1, "num_mpiprocs_per_machine": 1},
            help="Computational resources",
        )
        spec.input(
            "metadata.options.max_wallclock_seconds",
            valid_type=int,
            default=3600,
            help="Maximum wall clock time (seconds)",
        )
        spec.input(
            "metadata.options.withmpi",
            valid_type=bool,
            default=False,
            help="Run with MPI (for PcrystalOMP)",
        )

        # Outputs
        spec.output(
            "output_parameters",
            valid_type=orm.Dict,
            help="Parsed calculation results (energy, convergence, etc.)",
        )
        spec.output(
            "output_structure",
            valid_type=orm.StructureData,
            required=False,
            help="Optimized structure (if geometry optimization)",
        )
        spec.output(
            "wavefunction",
            valid_type=orm.SinglefileData,
            required=False,
            help="Converged wavefunction (fort.9)",
        )
        spec.output(
            "remote_folder",
            valid_type=orm.RemoteData,
            help="Remote work directory",
        )
        spec.output(
            "retrieved",
            valid_type=orm.FolderData,
            help="Retrieved output files",
        )

        # Exit codes
        spec.exit_code(
            300,
            "ERROR_NO_INPUT",
            message="Neither input_file nor structure+parameters provided",
        )
        spec.exit_code(
            301,
            "ERROR_MISSING_OUTPUT",
            message="Output file not found in retrieved files",
        )
        spec.exit_code(
            302,
            "ERROR_SCF_NOT_CONVERGED",
            message="SCF calculation did not converge",
        )
        spec.exit_code(
            303,
            "ERROR_GEOMETRY_NOT_CONVERGED",
            message="Geometry optimization did not converge",
        )
        spec.exit_code(
            304,
            "ERROR_INSUFFICIENT_MEMORY",
            message="Calculation failed due to insufficient memory",
        )
        spec.exit_code(
            305,
            "ERROR_TIMEOUT",
            message="Calculation exceeded wall time limit",
        )
        spec.exit_code(
            400,
            "ERROR_OUTPUT_PARSING",
            message="Failed to parse output file",
        )

        # Set parser
        spec.inputs["metadata"]["options"]["parser_name"].default = "crystal23.crystal"

    def validate_inputs(self) -> str | None:
        """Validate that required inputs are provided."""
        crystal = self.inputs.get("crystal", {})

        has_input_file = "input_file" in crystal
        has_structure = "structure" in crystal and "parameters" in crystal

        if not has_input_file and not has_structure:
            return "Must provide either 'crystal.input_file' or 'crystal.structure' + 'crystal.parameters'"

        return None

    def prepare_for_submission(self, folder: datastructures.Folder) -> "CalcInfo":
        """
        Prepare calculation for submission.

        Creates input files in the temporary folder and configures
        the calculation job.

        Args:
            folder: AiiDA Folder for staging input files.

        Returns:
            CalcInfo with job configuration.
        """
        crystal = self.inputs.crystal

        # Determine input source
        if "input_file" in crystal:
            # Use pre-built input file
            input_content = crystal.input_file.get_content()
        else:
            # Generate input from structure and parameters
            input_content = self._generate_d12_input(
                structure=crystal.structure,
                parameters=crystal.parameters.get_dict(),
                basis_set=crystal.get("basis_set", orm.Dict(dict={})).get_dict(),
            )

        # Write main input file
        input_filename = self.options.input_filename
        with folder.open(input_filename, "w", encoding="utf-8") as f:
            f.write(input_content)

        # Handle optional files
        local_copy_list = []
        remote_copy_list = []

        # Restart wavefunction
        if "wavefunction" in crystal:
            local_copy_list.append(
                (crystal.wavefunction.uuid, crystal.wavefunction.filename, "fort.20")
            )

        # External geometry file
        if "gui_file" in crystal:
            local_copy_list.append(
                (crystal.gui_file.uuid, crystal.gui_file.filename, "fort.34")
            )

        # Setup code execution
        codeinfo = datastructures.CodeInfo()
        codeinfo.code_uuid = self.inputs.code.uuid

        # CRYSTAL uses stdin for input
        codeinfo.stdin_name = input_filename
        codeinfo.stdout_name = self.options.output_filename

        # Calculation info
        calcinfo = datastructures.CalcInfo()
        calcinfo.uuid = str(self.uuid)
        calcinfo.codes_info = [codeinfo]
        calcinfo.local_copy_list = local_copy_list
        calcinfo.remote_copy_list = remote_copy_list

        # Files to retrieve after calculation
        calcinfo.retrieve_list = [
            self.options.output_filename,  # Main output
            "fort.9",     # Binary wavefunction
            "fort.98",    # Formatted wavefunction
            "fort.34",    # Final geometry (if optimization)
            "OPTINFO.DAT",  # Optimization status
            "HESSOPT.DAT",  # Hessian (if computed)
            "FREQINFO.DAT",  # Frequency restart
            "*.xyz",      # XYZ coordinates
        ]

        return calcinfo

    def _generate_d12_input(
        self,
        structure: orm.StructureData,
        parameters: dict,
        basis_set: dict,
    ) -> str:
        """
        Generate CRYSTAL23 d12 input file from structured data.

        Args:
            structure: AiiDA StructureData with crystal geometry.
            parameters: Calculation parameters (keywords, convergence, etc.).
            basis_set: Basis set definitions per element.

        Returns:
            Complete d12 input file content.
        """
        lines = []

        # Title
        title = parameters.get("title", "CRYSTAL23 calculation via AiiDA")
        lines.append(title)

        # Crystal type and symmetry
        crystal_type = parameters.get("crystal_type", "CRYSTAL")
        lines.append(crystal_type)

        # Space group (if using CRYSTAL type)
        if crystal_type == "CRYSTAL":
            space_group = parameters.get("space_group", 1)
            lines.append(str(space_group))

            # Lattice parameters
            cell = structure.cell
            a, b, c = [sum(v ** 2 for v in row) ** 0.5 for row in cell]
            # For simplicity, assume orthorhombic - full implementation would
            # compute angles and use appropriate format
            lines.append(f"{a:.10f} {b:.10f} {c:.10f}")
            lines.append("90.0 90.0 90.0")  # Simplified

            # Number of atoms in asymmetric unit
            sites = structure.sites
            lines.append(str(len(sites)))

            # Atomic positions
            for site in sites:
                symbol = site.kind_name
                # Get atomic number
                from aiida.common.constants import elements
                atomic_num = next(
                    (n for n, s in elements.items() if s == symbol),
                    0
                )
                pos = site.position
                lines.append(f"{atomic_num} {pos[0]:.10f} {pos[1]:.10f} {pos[2]:.10f}")

        elif crystal_type == "EXTERNAL":
            lines.append("EXTERNAL")

        # End geometry
        lines.append("END")

        # Basis set block
        lines.append("# BASIS SET")
        if basis_set:
            for element, basis in basis_set.items():
                lines.append(basis)
        else:
            # Default: use internal basis set library reference
            lines.append("# (basis sets should be provided)")

        lines.append("99 0")  # End of basis sets
        lines.append("END")

        # Hamiltonian block
        lines.append("# HAMILTONIAN")
        hamiltonian = parameters.get("hamiltonian", {})

        # DFT settings
        if hamiltonian.get("dft", True):
            lines.append("DFT")
            functional = hamiltonian.get("functional", "B3LYP")
            lines.append(functional)
            lines.append("END")

        # SCF settings
        scf = parameters.get("scf", {})
        if scf.get("maxcycle"):
            lines.append(f"MAXCYCLE\n{scf['maxcycle']}")
        if scf.get("toldee"):
            lines.append(f"TOLDEE\n{scf['toldee']}")

        # Shrinking factors (k-point mesh)
        shrink = parameters.get("shrink", [8, 8])
        lines.append(f"SHRINK\n{shrink[0]} {shrink[1]}")

        # Geometry optimization
        if parameters.get("optgeom"):
            lines.append("OPTGEOM")
            optgeom = parameters["optgeom"]
            if optgeom.get("fulloptg"):
                lines.append("FULLOPTG")
            elif optgeom.get("atomonly"):
                lines.append("ATOMONLY")
            if optgeom.get("maxcycle"):
                lines.append(f"MAXCYCLE\n{optgeom['maxcycle']}")
            lines.append("ENDOPT")

        lines.append("END")

        return "\n".join(lines)
