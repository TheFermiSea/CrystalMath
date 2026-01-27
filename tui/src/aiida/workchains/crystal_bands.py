"""
Band Structure WorkChain for CRYSTAL23.

Calculates electronic band structure along a k-path through the Brillouin zone.
This workflow can either:
    - Accept a pre-converged wavefunction
    - Run SCF calculation first (via CrystalBaseWorkChain)

The workflow produces:
    - BandsData with band energies along k-path
    - Band gap analysis (direct/indirect, value)
    - Fermi energy

K-path Generation:
    Uses seekpath (if available) for standardized high-symmetry paths based on
    crystal symmetry. Falls back to simplified detection for common systems
    (cubic, hexagonal, tetragonal) if seekpath is not installed.

Example:
    >>> from aiida import engine, orm
    >>> from src.aiida.workchains import CrystalBandStructureWorkChain
    >>>
    >>> builder = CrystalBandStructureWorkChain.get_builder()
    >>> builder.structure = structure_data
    >>> builder.code = orm.load_code("crystalOMP@localhost")
    >>> # Use auto-generated k-path
    >>> builder.kpoints_distance = orm.Float(0.05)  # k-spacing in 1/Angstrom
    >>> result = engine.run(builder)
    >>> bands = result["bands"]
"""

from __future__ import annotations

from typing import Any

from aiida import orm
from aiida.engine import ToContext, WorkChain, calcfunction

from .crystal_base import CrystalBaseWorkChain

# Check for seekpath availability
try:
    import seekpath

    SEEKPATH_AVAILABLE = True
except ImportError:
    SEEKPATH_AVAILABLE = False


# Standard high-symmetry points for common crystal systems
HIGH_SYMMETRY_POINTS = {
    "cubic": {
        "Gamma": [0.0, 0.0, 0.0],
        "X": [0.5, 0.0, 0.0],
        "M": [0.5, 0.5, 0.0],
        "R": [0.5, 0.5, 0.5],
    },
    "fcc": {
        "Gamma": [0.0, 0.0, 0.0],
        "X": [0.5, 0.0, 0.5],
        "W": [0.5, 0.25, 0.75],
        "K": [0.375, 0.375, 0.75],
        "L": [0.5, 0.5, 0.5],
        "U": [0.625, 0.25, 0.625],
    },
    "bcc": {
        "Gamma": [0.0, 0.0, 0.0],
        "H": [0.5, -0.5, 0.5],
        "N": [0.0, 0.0, 0.5],
        "P": [0.25, 0.25, 0.25],
    },
    "hexagonal": {
        "Gamma": [0.0, 0.0, 0.0],
        "M": [0.5, 0.0, 0.0],
        "K": [1.0 / 3.0, 1.0 / 3.0, 0.0],
        "A": [0.0, 0.0, 0.5],
        "L": [0.5, 0.0, 0.5],
        "H": [1.0 / 3.0, 1.0 / 3.0, 0.5],
    },
    "tetragonal": {
        "Gamma": [0.0, 0.0, 0.0],
        "X": [0.5, 0.0, 0.0],
        "M": [0.5, 0.5, 0.0],
        "Z": [0.0, 0.0, 0.5],
        "R": [0.5, 0.0, 0.5],
        "A": [0.5, 0.5, 0.5],
    },
}

# Standard k-paths for common crystal systems
STANDARD_PATHS = {
    "cubic": ["Gamma", "X", "M", "Gamma", "R", "X"],
    "fcc": ["Gamma", "X", "W", "K", "Gamma", "L", "U", "W", "L", "K"],
    "bcc": ["Gamma", "H", "N", "Gamma", "P", "H"],
    "hexagonal": ["Gamma", "M", "K", "Gamma", "A", "L", "H", "A"],
    "tetragonal": ["Gamma", "X", "M", "Gamma", "Z", "R", "A", "Z"],
}


@calcfunction
def generate_kpath(
    structure: orm.StructureData,
    kpoints_distance: orm.Float,
    crystal_system: orm.Str | None = None,
) -> orm.KpointsData:
    """
    Generate k-point path for band structure calculation.

    Uses seekpath (if available) for standardized high-symmetry paths that
    work with all crystal systems. Falls back to simple detection for
    cubic, hexagonal, and tetragonal systems if seekpath is not installed.

    Args:
        structure: Crystal structure.
        kpoints_distance: Desired spacing between k-points (1/Angstrom).
        crystal_system: Optional crystal system override (only used in fallback).

    Returns:
        KpointsData with band structure k-path.
    """

    # Try seekpath first (handles all crystal systems correctly)
    if SEEKPATH_AVAILABLE:
        return _generate_kpath_seekpath(structure, kpoints_distance)

    # Fallback to simple detection for common systems
    return _generate_kpath_fallback(structure, kpoints_distance, crystal_system)


def _generate_kpath_seekpath(
    structure: orm.StructureData,
    kpoints_distance: orm.Float,
) -> orm.KpointsData:
    """
    Generate k-path using seekpath library.

    Seekpath automatically determines the crystal system, space group,
    and standardized high-symmetry path for any structure.

    Args:
        structure: Crystal structure.
        kpoints_distance: Desired spacing between k-points (1/Angstrom).

    Returns:
        KpointsData with standardized k-path.
    """
    import numpy as np

    # Convert AiiDA structure to seekpath format
    cell = np.array(structure.cell)
    positions = []
    numbers = []

    for site in structure.sites:
        positions.append(site.position)
        # Get atomic number from kind
        kind = structure.get_kind(site.kind_name)
        # Use first symbol's atomic number
        symbol = kind.symbols[0]
        from src.aiida.converters.structure import SYMBOL_TO_Z

        numbers.append(SYMBOL_TO_Z.get(symbol, 6))  # Default to Carbon

    positions = np.array(positions)
    # Convert Cartesian to fractional
    inv_cell = np.linalg.inv(cell)
    frac_positions = np.dot(positions, inv_cell.T)

    # Get explicit k-path from seekpath
    structure_tuple = (cell, frac_positions, numbers)
    path_data = seekpath.get_explicit_k_path(
        structure_tuple,
        reference_distance=kpoints_distance.value,
    )

    # Extract k-points and labels
    kpoints_list = path_data["explicit_kpoints_rel"]
    explicit_labels = path_data["explicit_kpoints_labels"]

    # Build labels list (only non-empty labels)
    labels = []
    label_indices = []
    for i, label in enumerate(explicit_labels):
        if label:
            # Replace GAMMA with more readable name
            display_label = "Gamma" if label == "GAMMA" else label
            labels.append(display_label)
            label_indices.append(i)

    # Create KpointsData
    kpoints = orm.KpointsData()
    kpoints.set_cell_from_structure(structure)
    kpoints.set_kpoints(kpoints_list.tolist(), cartesian=False)

    # Store metadata
    kpoints.base.extras.set("labels", labels)
    kpoints.base.extras.set("label_indices", label_indices)
    kpoints.base.extras.set("crystal_system", path_data.get("bravais_lattice", "unknown"))
    kpoints.base.extras.set(
        "spacegroup_international", path_data.get("spacegroup_international", "")
    )
    kpoints.base.extras.set(
        "seekpath_version", seekpath.__version__ if hasattr(seekpath, "__version__") else "unknown"
    )

    return kpoints


def _generate_kpath_fallback(
    structure: orm.StructureData,
    kpoints_distance: orm.Float,
    crystal_system: orm.Str | None = None,
) -> orm.KpointsData:
    """
    Fallback k-path generation using simple crystal system detection.

    Only supports cubic, hexagonal, and tetragonal systems.
    Other systems default to cubic path (which may be incorrect).

    Args:
        structure: Crystal structure.
        kpoints_distance: Desired spacing between k-points.
        crystal_system: Optional override.

    Returns:
        KpointsData with k-path.
    """
    import numpy as np

    # Detect or use provided crystal system
    if crystal_system:
        system = crystal_system.value
    else:
        system = _detect_crystal_system(structure)

    # Get high-symmetry points and path
    hs_points = HIGH_SYMMETRY_POINTS.get(system, HIGH_SYMMETRY_POINTS["cubic"])
    path = STANDARD_PATHS.get(system, STANDARD_PATHS["cubic"])

    # Calculate number of points between each pair based on distance
    cell = np.array(structure.cell)
    reciprocal = 2 * np.pi * np.linalg.inv(cell).T

    kpoints_list = []
    labels = []
    label_indices = []

    for i in range(len(path) - 1):
        start_label = path[i]
        end_label = path[i + 1]

        start = np.array(hs_points[start_label])
        end = np.array(hs_points[end_label])

        # Convert to Cartesian for distance calculation
        start_cart = np.dot(start, reciprocal)
        end_cart = np.dot(end, reciprocal)
        distance = np.linalg.norm(end_cart - start_cart)

        # Number of points on this segment
        n_points = max(2, int(distance / kpoints_distance.value) + 1)

        # Generate k-points on segment
        for j in range(n_points):
            if j == 0 and i > 0:
                # Skip first point except for first segment (avoid duplicates)
                continue

            t = j / (n_points - 1) if n_points > 1 else 0
            kpoint = start + t * (end - start)
            kpoints_list.append(kpoint.tolist())

            # Record labels
            if j == 0:
                labels.append(start_label)
                label_indices.append(len(kpoints_list) - 1)
            elif j == n_points - 1:
                labels.append(end_label)
                label_indices.append(len(kpoints_list) - 1)

    # Create KpointsData
    kpoints = orm.KpointsData()
    kpoints.set_cell_from_structure(structure)
    kpoints.set_kpoints(kpoints_list, cartesian=False)

    # Store labels as extra attribute
    kpoints.base.extras.set("labels", labels)
    kpoints.base.extras.set("label_indices", label_indices)
    kpoints.base.extras.set("crystal_system", system)
    kpoints.base.extras.set("seekpath_version", "fallback")

    return kpoints


def _detect_crystal_system(structure: orm.StructureData) -> str:
    """Detect crystal system from structure cell parameters."""
    import numpy as np

    cell = np.array(structure.cell)

    # Calculate cell parameters
    a = np.linalg.norm(cell[0])
    b = np.linalg.norm(cell[1])
    c = np.linalg.norm(cell[2])

    # Calculate angles
    alpha = np.degrees(np.arccos(np.dot(cell[1], cell[2]) / (b * c)))
    beta = np.degrees(np.arccos(np.dot(cell[0], cell[2]) / (a * c)))
    gamma = np.degrees(np.arccos(np.dot(cell[0], cell[1]) / (a * b)))

    # Simple classification (can be improved with symmetry analysis)
    tol = 0.1  # degree tolerance

    if abs(a - b) < 0.01 * a and abs(b - c) < 0.01 * a:
        # All lengths equal
        if all(abs(angle - 90) < tol for angle in [alpha, beta, gamma]):
            return "cubic"
        # Could be rhombohedral - treat as cubic for now
        return "cubic"

    if abs(a - b) < 0.01 * a and abs(gamma - 120) < tol:
        # a == b and gamma == 120
        return "hexagonal"

    if abs(a - b) < 0.01 * a:
        # a == b, tetragonal
        if all(abs(angle - 90) < tol for angle in [alpha, beta, gamma]):
            return "tetragonal"

    # Default to cubic path
    return "cubic"


@calcfunction
def parse_band_structure(
    output_parameters: orm.Dict,
    kpoints: orm.KpointsData,
    structure: orm.StructureData,
) -> orm.Dict:
    """
    Parse band structure results from CRYSTAL23 output.

    Extracts:
        - Band energies along k-path
        - Fermi energy
        - Band gap (direct/indirect)
        - VBM/CBM locations

    Args:
        output_parameters: Parsed CRYSTAL23 output.
        kpoints: K-points used for band calculation.
        structure: Crystal structure.

    Returns:
        Dict with band structure data.
    """
    params = output_parameters.get_dict()

    result = {
        "fermi_energy_ev": params.get("fermi_energy_ev", 0.0),
        "n_bands": params.get("n_bands", 0),
        "n_kpoints": len(kpoints.get_kpoints()),
    }

    # Extract band gap information
    if "band_gap_ev" in params:
        result["band_gap_ev"] = params["band_gap_ev"]
        result["band_gap_type"] = params.get("band_gap_type", "unknown")
        result["is_metal"] = params["band_gap_ev"] < 0.01

    # Extract VBM/CBM if available
    if "vbm_ev" in params:
        result["vbm_ev"] = params["vbm_ev"]
        result["cbm_ev"] = params.get("cbm_ev", params["vbm_ev"])

    # K-path metadata
    labels = kpoints.base.extras.get("labels", [])
    label_indices = kpoints.base.extras.get("label_indices", [])
    result["kpath_labels"] = labels
    result["kpath_label_indices"] = label_indices
    result["crystal_system"] = kpoints.base.extras.get("crystal_system", "unknown")

    return orm.Dict(dict=result)


class CrystalBandStructureWorkChain(WorkChain):
    """
    Band Structure WorkChain for CRYSTAL23.

    Calculates electronic band structure along high-symmetry k-path.
    Can optionally run SCF calculation first if no wavefunction provided.

    Workflow:
        1. Run SCF (optional, if no wavefunction)
        2. Generate k-path (if not provided)
        3. Run properties calculation with BAND keyword
        4. Parse and expose band structure results

    Outputs:
        - bands: BandsData with band energies
        - band_parameters: Dict with gap, Fermi energy, etc.
        - output_parameters: Full parsed output
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
            help="Custom k-point path (auto-generated if not provided)",
        )
        spec.input(
            "kpoints_distance",
            valid_type=orm.Float,
            required=False,
            default=lambda: orm.Float(0.05),
            help="K-point spacing for auto-generated path (1/Angstrom)",
        )
        spec.input(
            "crystal_system",
            valid_type=orm.Str,
            required=False,
            help="Crystal system for k-path (auto-detected if not provided)",
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
            "bands",
            valid_type=orm.BandsData,
            help="Band structure data",
        )
        spec.output(
            "band_parameters",
            valid_type=orm.Dict,
            help="Band structure analysis (gap, Fermi energy, etc.)",
        )
        spec.output(
            "output_parameters",
            valid_type=orm.Dict,
            help="Full parsed output",
        )
        spec.output(
            "kpoints",
            valid_type=orm.KpointsData,
            help="K-point path used",
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
            cls.generate_kpath,
            cls.run_band_calculation,
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
            "ERROR_BAND_CALCULATION_FAILED",
            message="Band structure calculation failed",
        )
        spec.exit_code(
            302,
            "ERROR_NO_BANDS_PARSED",
            message="Failed to parse band structure from output",
        )

    def setup(self):
        """Initialize workflow context."""
        self.ctx.run_scf = "wavefunction" not in self.inputs
        self.ctx.wavefunction = self.inputs.get("wavefunction")

        self.report(f"Band structure workflow initialized. SCF required: {self.ctx.run_scf}")

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

        # Build inputs for base workchain
        inputs = {
            "structure": self.inputs.structure,
            "parameters": parameters,
            "code": self.inputs.code,
            "options": self.inputs.options,
        }

        future = self.submit(CrystalBaseWorkChain, **inputs)
        self.report(f"Submitted CrystalBaseWorkChain <{future.pk}>")

        return ToContext(scf_workchain=future)

    def generate_kpath(self):
        """Generate k-point path for band structure."""
        # Check SCF result if we ran it
        if self.ctx.run_scf:
            scf = self.ctx.scf_workchain
            if not scf.is_finished_ok:
                return self.exit_codes.ERROR_SCF_FAILED.format(
                    message=f"Exit code {scf.exit_status}"
                )
            self.ctx.wavefunction = scf.outputs.wavefunction

        # Use provided kpoints or generate
        if "kpoints" in self.inputs:
            self.ctx.kpoints = self.inputs.kpoints
            self.report("Using provided k-point path")
        else:
            self.report("Generating k-point path automatically")
            self.ctx.kpoints = generate_kpath(
                self.inputs.structure,
                self.inputs.kpoints_distance,
                self.inputs.get("crystal_system"),
            )
            labels = self.ctx.kpoints.base.extras.get("labels", [])
            self.report(f"Generated path: {' -> '.join(labels)}")

    def run_band_calculation(self):
        """Run band structure calculation with properties code."""
        self.report("Running band structure calculation")

        # Import properties CalcJob
        from src.aiida.calcjobs.crystal23 import Crystal23PropertiesCalculation

        # Build band-specific parameters
        band_params = {
            "band": {
                "enabled": True,
                "first_band": 1,
                "last_band": -1,  # All bands
                "print_eigenvalues": True,
            }
        }

        # Select properties code
        properties_code = self.inputs.get("properties_code", self.inputs.code)

        inputs = {
            "code": properties_code,
            "wavefunction": self.ctx.wavefunction,
            "parameters": orm.Dict(dict=band_params),
            "kpoints": self.ctx.kpoints,
            "metadata": {
                "options": self._get_calculation_options(),
                "label": "Band structure calculation",
            },
        }

        future = self.submit(Crystal23PropertiesCalculation, **inputs)
        self.report(f"Submitted Crystal23PropertiesCalculation <{future.pk}>")

        return ToContext(band_calc=future)

    def results(self):
        """Process and expose results."""
        calc = self.ctx.band_calc

        if not calc.is_finished_ok:
            return self.exit_codes.ERROR_BAND_CALCULATION_FAILED

        # Get output parameters
        if not hasattr(calc.outputs, "output_parameters"):
            return self.exit_codes.ERROR_NO_BANDS_PARSED

        output_params = calc.outputs.output_parameters

        # Parse band structure
        band_params = parse_band_structure(
            output_params,
            self.ctx.kpoints,
            self.inputs.structure,
        )

        # Create BandsData
        bands = self._create_bands_data(output_params, self.ctx.kpoints)

        # Expose outputs
        self.out("bands", bands)
        self.out("band_parameters", band_params)
        self.out("output_parameters", output_params)
        self.out("kpoints", self.ctx.kpoints)

        if self.ctx.wavefunction:
            self.out("wavefunction", self.ctx.wavefunction)

        gap = band_params["band_gap_ev"] if "band_gap_ev" in band_params.get_dict() else "N/A"
        self.report(f"Band structure completed. Band gap: {gap} eV")

    def _get_default_scf_parameters(self) -> dict[str, Any]:
        """Get default SCF parameters based on protocol."""
        protocol = self.inputs.protocol.value

        protocols = {
            "fast": {
                "scf": {"maxcycle": 50, "toldee": 6, "fmixing": 50},
                "kpoints": {"mesh": [4, 4, 4]},
            },
            "moderate": {
                "scf": {"maxcycle": 100, "toldee": 7, "fmixing": 40},
                "kpoints": {"mesh": [6, 6, 6]},
            },
            "precise": {
                "scf": {"maxcycle": 200, "toldee": 8, "fmixing": 30},
                "kpoints": {"mesh": [8, 8, 8]},
            },
        }

        return protocols.get(protocol, protocols["moderate"])

    def _get_calculation_options(self) -> dict:
        """Get calculation options."""
        options = self.inputs.options.get_dict().copy()
        options.setdefault("resources", {"num_machines": 1, "num_mpiprocs_per_machine": 1})
        options.setdefault("max_wallclock_seconds", 3600)
        return options

    def _create_bands_data(
        self,
        output_params: orm.Dict,
        kpoints: orm.KpointsData,
    ) -> orm.BandsData:
        """Create BandsData from calculation output."""
        import numpy as np

        params = output_params.get_dict()

        # Create BandsData
        bands = orm.BandsData()
        bands.set_kpointsdata(kpoints)

        # Extract eigenvalues from output
        eigenvalues = params.get("eigenvalues", [])
        if eigenvalues:
            bands.set_bands(np.array(eigenvalues))

        # Set occupations if available
        occupations = params.get("occupations", [])
        if occupations:
            bands.set_bands(np.array(eigenvalues), occupations=np.array(occupations))

        # Store metadata
        bands.base.extras.set("fermi_energy_ev", params.get("fermi_energy_ev", 0.0))
        bands.base.extras.set("n_electrons", params.get("n_electrons", 0))

        # Store labels
        labels = kpoints.base.extras.get("labels", [])
        label_indices = kpoints.base.extras.get("label_indices", [])
        if labels:
            bands.set_labels(list(zip(label_indices, labels, strict=False)))

        return bands
