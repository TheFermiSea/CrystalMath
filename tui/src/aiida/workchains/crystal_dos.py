"""
Density of States (DOS) WorkChain for CRYSTAL23.

Calculates electronic density of states, including:
    - Total DOS
    - Projected DOS (atom-resolved, orbital-resolved)
    - Spin-polarized DOS (for magnetic systems)

This workflow can either:
    - Accept a pre-converged wavefunction
    - Run SCF calculation first (via CrystalBaseWorkChain)

Example:
    >>> from aiida import engine, orm
    >>> from src.aiida.workchains import CrystalDOSWorkChain
    >>>
    >>> builder = CrystalDOSWorkChain.get_builder()
    >>> builder.structure = structure_data
    >>> builder.code = orm.load_code("crystalOMP@localhost")
    >>> builder.energy_range = orm.List(list=[-10.0, 5.0])  # eV relative to Fermi
    >>> builder.smearing = orm.Float(0.1)  # eV
    >>> result = engine.run(builder)
    >>> dos = result["dos"]
"""

from __future__ import annotations

from typing import Any

from aiida import orm
from aiida.engine import ToContext, WorkChain, calcfunction

from .crystal_base import CrystalBaseWorkChain


@calcfunction
def compute_dos_kpoints(
    structure: orm.StructureData,
    kpoints_density: orm.Float,
) -> orm.KpointsData:
    """
    Compute dense k-point mesh for DOS calculation.

    DOS requires dense k-point sampling for accurate integration.
    This function generates a Monkhorst-Pack mesh based on
    the specified density.

    Args:
        structure: Crystal structure.
        kpoints_density: Target k-point density (points per Å⁻¹).

    Returns:
        KpointsData with dense mesh for DOS.
    """
    import numpy as np

    cell = np.array(structure.cell)

    # Calculate reciprocal lattice vectors
    reciprocal = 2 * np.pi * np.linalg.inv(cell).T

    # Calculate mesh based on density
    mesh = []
    for i in range(3):
        length = np.linalg.norm(reciprocal[i])
        nk = max(1, int(np.ceil(length / kpoints_density.value)))
        # Ensure odd number for better symmetry
        if nk % 2 == 0:
            nk += 1
        mesh.append(nk)

    kpoints = orm.KpointsData()
    kpoints.set_cell_from_structure(structure)
    kpoints.set_kpoints_mesh(mesh, offset=[0, 0, 0])

    return kpoints


@calcfunction
def parse_dos_output(
    output_parameters: orm.Dict,
    structure: orm.StructureData,
) -> orm.Dict:
    """
    Parse DOS results from CRYSTAL23 output.

    Extracts:
        - Energy grid
        - Total DOS
        - Projected DOS per atom
        - Fermi energy
        - Band gap

    Args:
        output_parameters: Parsed CRYSTAL23 output.
        structure: Crystal structure.

    Returns:
        Dict with DOS data.
    """
    params = output_parameters.get_dict()

    result = {
        "fermi_energy_ev": params.get("fermi_energy_ev", 0.0),
        "n_electrons": params.get("n_electrons", 0),
        "n_atoms": len(structure.sites),
    }

    # Energy grid
    result["energy_min_ev"] = params.get("dos_energy_min", -10.0)
    result["energy_max_ev"] = params.get("dos_energy_max", 5.0)
    result["energy_step_ev"] = params.get("dos_energy_step", 0.01)
    result["n_energy_points"] = params.get("dos_n_points", 0)

    # Band gap information
    if "band_gap_ev" in params:
        result["band_gap_ev"] = params["band_gap_ev"]
        result["is_metal"] = params["band_gap_ev"] < 0.01
    else:
        # Try to detect from DOS
        result["is_metal"] = params.get("dos_at_fermi", 0.0) > 0.01

    # DOS at Fermi level
    result["dos_at_fermi"] = params.get("dos_at_fermi", 0.0)

    # Spin polarization
    result["spin_polarized"] = params.get("spin_polarized", False)
    if result["spin_polarized"]:
        result["n_up_electrons"] = params.get("n_up_electrons", 0)
        result["n_down_electrons"] = params.get("n_down_electrons", 0)
        result["magnetic_moment"] = params.get("magnetic_moment", 0.0)

    # Projected DOS metadata
    result["has_pdos"] = params.get("has_pdos", False)
    if result["has_pdos"]:
        result["pdos_atoms"] = params.get("pdos_atoms", [])
        result["pdos_orbitals"] = params.get("pdos_orbitals", [])

    return orm.Dict(dict=result)


@calcfunction
def create_dos_xy_data(
    output_parameters: orm.Dict,
    dos_parameters: orm.Dict,
) -> orm.XyData:
    """
    Create XyData from DOS calculation results.

    Stores energy as X and DOS as Y data.
    For spin-polarized, stores up-spin and down-spin separately.

    Args:
        output_parameters: Full calculation output.
        dos_parameters: Parsed DOS parameters.

    Returns:
        XyData with DOS curves.
    """
    import numpy as np

    params = output_parameters.get_dict()
    dos_params = dos_parameters.get_dict()

    # Create XyData
    xy = orm.XyData()

    # Get energy grid
    e_min = dos_params["energy_min_ev"]
    e_max = dos_params["energy_max_ev"]
    e_step = dos_params["energy_step_ev"]
    n_points = dos_params.get("n_energy_points", 0)

    if n_points > 0:
        energies = np.linspace(e_min, e_max, n_points)
    else:
        energies = np.arange(e_min, e_max + e_step, e_step)

    # Get DOS data
    total_dos = params.get("total_dos", np.zeros_like(energies))

    # Store as XyData
    xy.set_x(energies, "Energy", "eV")

    if dos_params.get("spin_polarized", False):
        dos_up = params.get("dos_up", total_dos)
        dos_down = params.get("dos_down", np.zeros_like(energies))
        xy.set_y(
            [np.array(dos_up), np.array(dos_down)],
            ["DOS_up", "DOS_down"],
            ["states/eV", "states/eV"],
        )
    else:
        xy.set_y([np.array(total_dos)], ["DOS"], ["states/eV"])

    return xy


class CrystalDOSWorkChain(WorkChain):
    """
    Density of States WorkChain for CRYSTAL23.

    Calculates total and projected DOS.
    Can optionally run SCF calculation first if no wavefunction provided.

    Workflow:
        1. Run SCF (optional, if no wavefunction)
        2. Generate dense k-mesh (if not provided)
        3. Run properties calculation with DOSS keyword
        4. Parse and expose DOS results

    Outputs:
        - dos: XyData with DOS curves
        - dos_parameters: Dict with analysis (Fermi energy, gap, etc.)
        - output_parameters: Full parsed output
        - pdos: Dict with projected DOS per atom (if requested)
    """

    @classmethod
    def define(cls, spec):
        """Define WorkChain specification."""
        super().define(spec)

        # Inputs
        spec.input(
            "structure",
            valid_type=orm.StructureData,
            help="Crystal structure",
        )
        spec.input(
            "code",
            valid_type=orm.AbstractCode,
            help="CRYSTAL23 code",
        )
        spec.input(
            "properties_code",
            valid_type=orm.AbstractCode,
            required=False,
            help="CRYSTAL23 properties code (if different from main code)",
        )
        spec.input(
            "scf_parameters",
            valid_type=orm.Dict,
            required=False,
            help="Parameters for SCF calculation",
        )
        spec.input(
            "wavefunction",
            valid_type=orm.SinglefileData,
            required=False,
            help="Pre-converged wavefunction (skip SCF if provided)",
        )
        spec.input(
            "kpoints",
            valid_type=orm.KpointsData,
            required=False,
            help="Custom k-point mesh (auto-generated if not provided)",
        )
        spec.input(
            "kpoints_density",
            valid_type=orm.Float,
            required=False,
            default=lambda: orm.Float(0.1),
            help="K-point density for auto-generated mesh (1/Angstrom)",
        )
        spec.input(
            "energy_range",
            valid_type=orm.List,
            required=False,
            default=lambda: orm.List(list=[-10.0, 5.0]),
            help="Energy range [min, max] relative to Fermi (eV)",
        )
        spec.input(
            "smearing",
            valid_type=orm.Float,
            required=False,
            default=lambda: orm.Float(0.1),
            help="Gaussian smearing width (eV)",
        )
        spec.input(
            "n_energy_points",
            valid_type=orm.Int,
            required=False,
            default=lambda: orm.Int(1001),
            help="Number of energy points in DOS grid",
        )
        spec.input(
            "compute_pdos",
            valid_type=orm.Bool,
            required=False,
            default=lambda: orm.Bool(False),
            help="Compute projected DOS per atom",
        )
        spec.input(
            "pdos_atoms",
            valid_type=orm.List,
            required=False,
            help="List of atom indices for PDOS (all if not specified)",
        )
        spec.input(
            "options",
            valid_type=orm.Dict,
            required=False,
            default=lambda: orm.Dict(dict={}),
            help="Calculation options",
        )
        spec.input(
            "protocol",
            valid_type=orm.Str,
            required=False,
            default=lambda: orm.Str("moderate"),
            help="Protocol for SCF calculation (fast/moderate/precise)",
        )

        # Outputs
        spec.output(
            "dos",
            valid_type=orm.XyData,
            help="DOS data (energy vs density)",
        )
        spec.output(
            "dos_parameters",
            valid_type=orm.Dict,
            help="DOS analysis (Fermi energy, gap, etc.)",
        )
        spec.output(
            "output_parameters",
            valid_type=orm.Dict,
            help="Full parsed output",
        )
        spec.output(
            "pdos",
            valid_type=orm.Dict,
            required=False,
            help="Projected DOS per atom (if requested)",
        )
        spec.output(
            "kpoints",
            valid_type=orm.KpointsData,
            help="K-point mesh used",
        )
        spec.output(
            "wavefunction",
            valid_type=orm.SinglefileData,
            required=False,
            help="Converged wavefunction",
        )

        # Workflow
        spec.outline(
            cls.setup,
            cls.run_scf_if_needed,
            cls.prepare_kpoints,
            cls.run_dos_calculation,
            cls.results,
        )

        # Exit codes
        spec.exit_code(
            300,
            "ERROR_SCF_FAILED",
            message="SCF calculation failed: {message}",
        )
        spec.exit_code(
            301,
            "ERROR_DOS_CALCULATION_FAILED",
            message="DOS calculation failed",
        )
        spec.exit_code(
            302,
            "ERROR_NO_DOS_PARSED",
            message="Failed to parse DOS from output",
        )

    def setup(self):
        """Initialize workflow context."""
        self.ctx.run_scf = "wavefunction" not in self.inputs
        self.ctx.wavefunction = self.inputs.get("wavefunction")

        self.report(
            f"DOS workflow initialized. "
            f"SCF required: {self.ctx.run_scf}, "
            f"PDOS: {self.inputs.compute_pdos.value}"
        )

    def run_scf_if_needed(self):
        """Run SCF calculation if no wavefunction provided."""
        if not self.ctx.run_scf:
            self.report("Using provided wavefunction, skipping SCF")
            return

        self.report("Running SCF calculation via CrystalBaseWorkChain")

        # Get SCF parameters
        if "scf_parameters" in self.inputs:
            parameters = self.inputs.scf_parameters
        else:
            parameters = orm.Dict(dict=self._get_default_scf_parameters())

        # Build inputs
        inputs = {
            "structure": self.inputs.structure,
            "parameters": parameters,
            "code": self.inputs.code,
            "options": self.inputs.options,
        }

        future = self.submit(CrystalBaseWorkChain, **inputs)
        self.report(f"Submitted CrystalBaseWorkChain <{future.pk}>")

        return ToContext(scf_workchain=future)

    def prepare_kpoints(self):
        """Prepare k-point mesh for DOS calculation."""
        # Check SCF result if we ran it
        if self.ctx.run_scf:
            scf = self.ctx.scf_workchain
            if not scf.is_finished_ok:
                return self.exit_codes.ERROR_SCF_FAILED.format(
                    message=f"Exit code {scf.exit_status}"
                )
            self.ctx.wavefunction = scf.outputs.wavefunction

        # Use provided kpoints or generate dense mesh
        if "kpoints" in self.inputs:
            self.ctx.kpoints = self.inputs.kpoints
            mesh = self.ctx.kpoints.get_kpoints_mesh()[0]
            self.report(f"Using provided k-mesh: {mesh}")
        else:
            self.report("Generating dense k-mesh for DOS")
            self.ctx.kpoints = compute_dos_kpoints(
                self.inputs.structure,
                self.inputs.kpoints_density,
            )
            mesh = self.ctx.kpoints.get_kpoints_mesh()[0]
            self.report(f"Generated k-mesh: {mesh}")

    def run_dos_calculation(self):
        """Run DOS calculation with properties code."""
        self.report("Running DOS calculation")

        # Import properties CalcJob
        from src.aiida.calcjobs.crystal23 import Crystal23PropertiesCalculation

        # Build DOS-specific parameters
        energy_range = self.inputs.energy_range.get_list()
        dos_params = {
            "doss": {
                "enabled": True,
                "energy_min": energy_range[0],
                "energy_max": energy_range[1],
                "n_points": self.inputs.n_energy_points.value,
                "smearing": self.inputs.smearing.value,
            }
        }

        # Add PDOS settings if requested
        if self.inputs.compute_pdos.value:
            dos_params["doss"]["projected"] = True
            if "pdos_atoms" in self.inputs:
                dos_params["doss"]["atoms"] = self.inputs.pdos_atoms.get_list()

        # Select properties code
        properties_code = self.inputs.get("properties_code", self.inputs.code)

        inputs = {
            "code": properties_code,
            "wavefunction": self.ctx.wavefunction,
            "parameters": orm.Dict(dict=dos_params),
            "kpoints": self.ctx.kpoints,
            "metadata": {
                "options": self._get_calculation_options(),
                "label": "DOS calculation",
            },
        }

        future = self.submit(Crystal23PropertiesCalculation, **inputs)
        self.report(f"Submitted Crystal23PropertiesCalculation <{future.pk}>")

        return ToContext(dos_calc=future)

    def results(self):
        """Process and expose results."""
        calc = self.ctx.dos_calc

        if not calc.is_finished_ok:
            return self.exit_codes.ERROR_DOS_CALCULATION_FAILED

        # Get output parameters
        if not hasattr(calc.outputs, "output_parameters"):
            return self.exit_codes.ERROR_NO_DOS_PARSED

        output_params = calc.outputs.output_parameters

        # Parse DOS parameters
        dos_params = parse_dos_output(
            output_params,
            self.inputs.structure,
        )

        # Create XyData for DOS
        dos_xy = create_dos_xy_data(output_params, dos_params)

        # Expose outputs
        self.out("dos", dos_xy)
        self.out("dos_parameters", dos_params)
        self.out("output_parameters", output_params)
        self.out("kpoints", self.ctx.kpoints)

        if self.ctx.wavefunction:
            self.out("wavefunction", self.ctx.wavefunction)

        # PDOS output if computed
        if self.inputs.compute_pdos.value and hasattr(calc.outputs, "pdos"):
            self.out("pdos", calc.outputs.pdos)

        # Report summary
        params = dos_params.get_dict()
        is_metal = params.get("is_metal", False)
        if is_metal:
            self.report(
                f"DOS completed. System is metallic. DOS(E_F) = {params.get('dos_at_fermi', 0):.3f} states/eV"
            )
        else:
            gap = params.get("band_gap_ev", "N/A")
            self.report(f"DOS completed. Band gap: {gap} eV")

    def _get_default_scf_parameters(self) -> dict[str, Any]:
        """Get default SCF parameters based on protocol."""
        protocol = self.inputs.protocol.value

        # DOS requires denser k-mesh than bands
        protocols = {
            "fast": {
                "scf": {"maxcycle": 50, "toldee": 6, "fmixing": 50},
                "kpoints": {"mesh": [6, 6, 6]},
            },
            "moderate": {
                "scf": {"maxcycle": 100, "toldee": 7, "fmixing": 40},
                "kpoints": {"mesh": [8, 8, 8]},
            },
            "precise": {
                "scf": {"maxcycle": 200, "toldee": 8, "fmixing": 30},
                "kpoints": {"mesh": [12, 12, 12]},
            },
        }

        return protocols.get(protocol, protocols["moderate"])

    def _get_calculation_options(self) -> dict:
        """Get calculation options."""
        options = self.inputs.options.get_dict().copy()
        options.setdefault("resources", {"num_machines": 1, "num_mpiprocs_per_machine": 1})
        options.setdefault("max_wallclock_seconds", 3600)
        return options
