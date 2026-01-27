"""
Common relaxation workflow interface for CRYSTAL23.

Implements the aiida-common-workflows specification for geometry relaxation,
enabling CRYSTAL23 to be used interchangeably with other DFT codes.

The interface defines:
    - Standard input parameters (protocol, relax_type, spin_type)
    - Standard output nodes (structure, total_energy, forces)
    - Protocol-based parameter selection (fast, moderate, precise)
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from aiida import orm
from aiida.engine import WorkChain, calcfunction

from ..workchains.crystal_base import CrystalBaseWorkChain


class RelaxType(Enum):
    """Type of geometry relaxation."""

    NONE = "none"  # Single-point calculation
    POSITIONS = "positions"  # Atomic positions only (ATOMONLY)
    CELL = "cell"  # Cell parameters only (CELLONLY)
    POSITIONS_CELL = "positions_cell"  # Both (FULLOPTG)
    POSITIONS_SHAPE = "positions_shape"  # Positions + shape, fixed volume
    POSITIONS_VOLUME = "positions_volume"  # Positions + volume, fixed shape


class SpinType(Enum):
    """Spin polarization treatment."""

    NONE = "none"  # Spin-unpolarized (default CRYSTAL23)
    COLLINEAR = "collinear"  # Spin-polarized (UHF/UDFT)
    NON_COLLINEAR = "non_collinear"  # Not supported by CRYSTAL23
    SPIN_ORBIT = "spin_orbit"  # With spin-orbit coupling


class ElectronicType(Enum):
    """Electronic structure type."""

    METAL = "metal"
    INSULATOR = "insulator"
    AUTOMATIC = "automatic"


# Protocol definitions: parameter sets for different accuracy/speed tradeoffs
PROTOCOLS = {
    "fast": {
        "description": "Fast relaxation for initial exploration",
        "scf": {
            "maxcycle": 50,
            "toldee": 6,
            "fmixing": 50,
        },
        "optimization": {
            "maxcycle": 30,
            "toldeg": 0.003,
            "toldex": 0.012,
        },
        "basis": "sto-3g",
        "kpoints_density": 0.3,  # k-points per Å⁻¹
    },
    "moderate": {
        "description": "Balanced accuracy and speed (default)",
        "scf": {
            "maxcycle": 100,
            "toldee": 7,
            "fmixing": 40,
        },
        "optimization": {
            "maxcycle": 100,
            "toldeg": 0.0003,
            "toldex": 0.0012,
        },
        "basis": "pob-tzvp",
        "kpoints_density": 0.2,
    },
    "precise": {
        "description": "High accuracy for publication-quality results",
        "scf": {
            "maxcycle": 200,
            "toldee": 8,
            "fmixing": 30,
        },
        "optimization": {
            "maxcycle": 200,
            "toldeg": 0.00003,
            "toldex": 0.00012,
        },
        "basis": "pob-qzvp",
        "kpoints_density": 0.15,
    },
}


@calcfunction
def extract_total_energy(output_parameters: orm.Dict) -> orm.Float:
    """Extract total energy from calculation output."""
    params = output_parameters.get_dict()
    energy_ev = params.get("final_energy_ev")
    if energy_ev is None:
        energy_hartree = params.get("final_energy_hartree", 0.0)
        energy_ev = energy_hartree * 27.2114
    return orm.Float(energy_ev)


class CrystalCommonRelaxInputGenerator:
    """
    Input generator for CRYSTAL23 relaxation following common-workflows spec.

    Generates standardized inputs based on:
        - Protocol (fast/moderate/precise)
        - Relaxation type (positions/cell/both)
        - Spin type (none/collinear)
        - Electronic type (metal/insulator/auto)

    Example:
        >>> generator = CrystalCommonRelaxInputGenerator(
        ...     code=orm.load_code("crystalOMP@localhost")
        ... )
        >>> inputs = generator.get_builder(
        ...     structure=structure,
        ...     protocol="moderate",
        ...     relax_type=RelaxType.POSITIONS_CELL,
        ... )
    """

    def __init__(self, code: orm.AbstractCode):
        """
        Initialize the input generator.

        Args:
            code: AiiDA Code node for CRYSTAL23.
        """
        self.code = code

    @staticmethod
    def get_protocol_names() -> list[str]:
        """Return available protocol names."""
        return list(PROTOCOLS.keys())

    @staticmethod
    def get_default_protocol_name() -> str:
        """Return the default protocol name."""
        return "moderate"

    @staticmethod
    def get_protocol(protocol_name: str) -> dict[str, Any]:
        """
        Get protocol parameters by name.

        Args:
            protocol_name: One of "fast", "moderate", "precise".

        Returns:
            Protocol parameter dictionary.

        Raises:
            ValueError: If protocol name is unknown.
        """
        if protocol_name not in PROTOCOLS:
            raise ValueError(
                f"Unknown protocol '{protocol_name}'. Available: {list(PROTOCOLS.keys())}"
            )
        return PROTOCOLS[protocol_name]

    def get_builder(
        self,
        structure: orm.StructureData,
        protocol: str | None = None,
        relax_type: RelaxType = RelaxType.POSITIONS_CELL,
        spin_type: SpinType = SpinType.NONE,
        electronic_type: ElectronicType = ElectronicType.AUTOMATIC,
        magnetization_per_site: list[float] | None = None,
        reference_workchain: WorkChain | None = None,
        **kwargs,
    ):
        """
        Generate inputs for CrystalCommonRelaxWorkChain.

        Args:
            structure: Input crystal structure.
            protocol: Protocol name ("fast", "moderate", "precise").
            relax_type: Type of relaxation to perform.
            spin_type: Spin polarization treatment.
            electronic_type: Metal/insulator/auto classification.
            magnetization_per_site: Initial magnetic moments per atom.
            reference_workchain: Previous workchain for restart.
            **kwargs: Additional parameters to override.

        Returns:
            ProcessBuilder for CrystalCommonRelaxWorkChain.
        """
        protocol = protocol or self.get_default_protocol_name()
        protocol_params = self.get_protocol(protocol)

        # Build CRYSTAL23 parameters
        params = self._build_parameters(
            structure=structure,
            protocol_params=protocol_params,
            relax_type=relax_type,
            spin_type=spin_type,
            electronic_type=electronic_type,
            magnetization_per_site=magnetization_per_site,
            **kwargs,
        )

        # Get builder
        builder = CrystalCommonRelaxWorkChain.get_builder()
        builder.structure = structure
        builder.code = self.code
        builder.parameters = orm.Dict(dict=params)
        builder.relax_type = orm.Str(relax_type.value)
        builder.protocol = orm.Str(protocol)

        # Calculate resources based on structure size
        num_atoms = len(structure.sites)
        builder.options = orm.Dict(
            dict={
                "resources": {
                    "num_machines": 1,
                    "num_mpiprocs_per_machine": min(4, max(1, num_atoms // 10)),
                },
                "max_wallclock_seconds": self._estimate_walltime(num_atoms, protocol),
            }
        )

        # Add restart wavefunction if reference provided
        if reference_workchain and hasattr(reference_workchain.outputs, "wavefunction"):
            builder.wavefunction = reference_workchain.outputs.wavefunction

        return builder

    def _build_parameters(
        self,
        structure: orm.StructureData,
        protocol_params: dict[str, Any],
        relax_type: RelaxType,
        spin_type: SpinType,
        electronic_type: ElectronicType,
        magnetization_per_site: list[float] | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        """Build CRYSTAL23 input parameters."""
        params = {
            "scf": dict(protocol_params["scf"]),
            "optimization": {},
        }

        # Set optimization type
        if relax_type == RelaxType.NONE:
            params["optimization"]["enabled"] = False
        elif relax_type == RelaxType.POSITIONS:
            params["optimization"]["type"] = "ATOMONLY"
        elif relax_type == RelaxType.CELL:
            params["optimization"]["type"] = "CELLONLY"
        elif relax_type == RelaxType.POSITIONS_CELL:
            params["optimization"]["type"] = "FULLOPTG"
        elif relax_type == RelaxType.POSITIONS_SHAPE:
            params["optimization"]["type"] = "FULLOPTG"
            params["optimization"]["fix_volume"] = True
        elif relax_type == RelaxType.POSITIONS_VOLUME:
            params["optimization"]["type"] = "FULLOPTG"
            params["optimization"]["fix_shape"] = True

        # Copy optimization parameters from protocol
        if relax_type != RelaxType.NONE:
            params["optimization"].update(protocol_params.get("optimization", {}))

        # Handle spin polarization
        if spin_type == SpinType.COLLINEAR:
            params["scf"]["spinpol"] = True
            if magnetization_per_site:
                params["scf"]["initial_spin"] = magnetization_per_site
        elif spin_type == SpinType.SPIN_ORBIT:
            params["scf"]["spinorbit"] = True

        # Handle electronic type
        if electronic_type == ElectronicType.METAL:
            params["scf"]["smearing"] = True
            params["scf"]["smearing_width"] = 0.01  # eV
        elif electronic_type == ElectronicType.INSULATOR:
            params["scf"]["smearing"] = False

        # Calculate k-points from density
        kpoints_density = protocol_params.get("kpoints_density", 0.2)
        params["kpoints"] = self._calculate_kpoints(structure, kpoints_density)

        # Override with any user-provided kwargs
        for key, value in kwargs.items():
            if key in params:
                if isinstance(params[key], dict) and isinstance(value, dict):
                    params[key].update(value)
                else:
                    params[key] = value

        return params

    def _calculate_kpoints(self, structure: orm.StructureData, density: float) -> dict[str, Any]:
        """Calculate k-point mesh from density."""
        import numpy as np

        cell = np.array(structure.cell)

        # Calculate reciprocal lattice vectors
        reciprocal = 2 * np.pi * np.linalg.inv(cell).T

        # Calculate mesh based on density
        mesh = []
        for i in range(3):
            length = np.linalg.norm(reciprocal[i])
            nk = max(1, int(np.ceil(length / density)))
            mesh.append(nk)

        return {"mesh": mesh, "offset": [0, 0, 0]}

    def _estimate_walltime(self, num_atoms: int, protocol: str) -> int:
        """Estimate walltime based on system size and protocol."""
        base_time = {
            "fast": 1800,  # 30 minutes
            "moderate": 7200,  # 2 hours
            "precise": 28800,  # 8 hours
        }.get(protocol, 7200)

        # Scale with system size (roughly O(N²) for DFT)
        scaling = (num_atoms / 10) ** 1.5
        return int(base_time * max(1, scaling))


class CrystalCommonRelaxWorkChain(WorkChain):
    """
    Common relaxation WorkChain for CRYSTAL23.

    Implements the standard interface from aiida-common-workflows:
        - Standard inputs (structure, protocol, relax_type)
        - Standard outputs (relaxed_structure, total_energy, forces)
        - Protocol-based parameter selection

    This allows CRYSTAL23 to be used in multi-code workflows where
    different codes can be swapped transparently.

    Example:
        >>> builder = CrystalCommonRelaxWorkChain.get_builder()
        >>> builder.structure = structure
        >>> builder.code = orm.load_code("crystalOMP@localhost")
        >>> builder.protocol = orm.Str("moderate")
        >>> builder.relax_type = orm.Str("positions_cell")
        >>> result = engine.run(builder)
        >>> relaxed = result["relaxed_structure"]
    """

    @classmethod
    def define(cls, spec):
        """Define WorkChain specification."""
        super().define(spec)

        # Inputs - following common-workflows spec
        spec.input(
            "structure",
            valid_type=orm.StructureData,
            help="Input crystal structure",
        )
        spec.input(
            "code",
            valid_type=orm.AbstractCode,
            help="CRYSTAL23 code",
        )
        spec.input(
            "parameters",
            valid_type=orm.Dict,
            required=False,
            help="CRYSTAL23 calculation parameters",
        )
        spec.input(
            "protocol",
            valid_type=orm.Str,
            required=False,
            default=lambda: orm.Str("moderate"),
            help="Protocol name (fast/moderate/precise)",
        )
        spec.input(
            "relax_type",
            valid_type=orm.Str,
            required=False,
            default=lambda: orm.Str("positions_cell"),
            help="Relaxation type",
        )
        spec.input(
            "options",
            valid_type=orm.Dict,
            required=False,
            default=lambda: orm.Dict(dict={}),
            help="Calculation options",
        )
        spec.input(
            "wavefunction",
            valid_type=orm.SinglefileData,
            required=False,
            help="Restart wavefunction",
        )

        # Outputs - following common-workflows spec
        spec.output(
            "relaxed_structure",
            valid_type=orm.StructureData,
            required=False,
            help="Relaxed structure (if optimization performed)",
        )
        spec.output(
            "total_energy",
            valid_type=orm.Float,
            help="Total energy in eV",
        )
        spec.output(
            "forces",
            valid_type=orm.ArrayData,
            required=False,
            help="Forces on atoms",
        )
        spec.output(
            "output_parameters",
            valid_type=orm.Dict,
            help="Full output parameters from CRYSTAL23",
        )

        # Workflow
        spec.outline(
            cls.setup,
            cls.run_relaxation,
            cls.results,
        )

        # Exit codes
        spec.exit_code(
            300,
            "ERROR_RELAXATION_FAILED",
            message="Geometry relaxation did not converge",
        )

    def setup(self):
        """Initialize workflow context."""
        self.ctx.inputs_generated = False

        # Get or generate parameters
        if "parameters" in self.inputs:
            self.ctx.parameters = self.inputs.parameters.get_dict()
        else:
            # Generate from protocol
            generator = CrystalCommonRelaxInputGenerator(self.inputs.code)
            relax_type = RelaxType(self.inputs.relax_type.value)
            protocol = self.inputs.protocol.value

            self.ctx.parameters = generator._build_parameters(
                structure=self.inputs.structure,
                protocol_params=generator.get_protocol(protocol),
                relax_type=relax_type,
                spin_type=SpinType.NONE,
                electronic_type=ElectronicType.AUTOMATIC,
            )
            self.ctx.inputs_generated = True

        self.report(
            f"Using protocol '{self.inputs.protocol.value}' with "
            f"relax_type '{self.inputs.relax_type.value}'"
        )

    def run_relaxation(self):
        """Submit relaxation calculation."""
        from aiida.engine import ToContext

        # Build inputs for CrystalBaseWorkChain
        inputs = {
            "structure": self.inputs.structure,
            "code": self.inputs.code,
            "parameters": orm.Dict(dict=self.ctx.parameters),
            "options": self.inputs.options,
        }

        if "wavefunction" in self.inputs:
            inputs["wavefunction"] = self.inputs.wavefunction

        # Submit to self-healing base workchain
        future = self.submit(CrystalBaseWorkChain, **inputs)
        self.report(f"Submitted CrystalBaseWorkChain <{future.pk}>")

        return ToContext(workchain=future)

    def results(self):
        """Process results and expose standard outputs."""
        workchain = self.ctx.workchain

        if not workchain.is_finished_ok:
            return self.exit_codes.ERROR_RELAXATION_FAILED

        # Extract and expose outputs
        if hasattr(workchain.outputs, "output_parameters"):
            self.out("output_parameters", workchain.outputs.output_parameters)

            # Extract total energy
            energy = extract_total_energy(workchain.outputs.output_parameters)
            self.out("total_energy", energy)

        # Expose relaxed structure
        if hasattr(workchain.outputs, "output_structure"):
            self.out("relaxed_structure", workchain.outputs.output_structure)
        else:
            # No optimization, original structure is "relaxed"
            # Only output if relax_type is NONE
            if self.inputs.relax_type.value == "none":
                self.out("relaxed_structure", self.inputs.structure)

        self.report("Common relaxation workflow completed successfully")
