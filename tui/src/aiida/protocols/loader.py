"""
Protocol loader and builder generator for CRYSTAL23 workflows.

Handles loading protocols from YAML files and converting them
to AiiDA WorkChain builders with appropriate inputs.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from .schemas import (
    BUILTIN_PROTOCOLS,
    BandStructureProtocol,
    BaseProtocol,
    DOSProtocol,
    RelaxationProtocol,
    SCFProtocol,
)

if TYPE_CHECKING:
    from aiida import orm
    from aiida.engine import ProcessBuilder, WorkChain


class ProtocolError(Exception):
    """Error loading or validating a protocol."""

    pass


# Directory containing protocol YAML files
PROTOCOLS_DIR = Path(__file__).parent / "definitions"


def load_protocol(
    name: str,
    workflow_type: str = "scf",
    custom_path: Path | None = None,
) -> BaseProtocol:
    """
    Load a protocol by name.

    First checks built-in protocols, then looks for YAML files
    in the protocols directory.

    Args:
        name: Protocol name (e.g., "fast", "moderate", "precise").
        workflow_type: Type of workflow (scf, relax, bands, dos).
        custom_path: Optional path to custom protocol YAML file.

    Returns:
        Protocol dataclass instance.

    Raises:
        ProtocolError: If protocol not found or invalid.
    """
    # Check built-in protocols first
    if name in BUILTIN_PROTOCOLS:
        return BUILTIN_PROTOCOLS[name]

    # Check custom path
    if custom_path and custom_path.exists():
        return _load_protocol_from_yaml(custom_path, workflow_type)

    # Look in protocols directory
    yaml_path = PROTOCOLS_DIR / f"{name}.yaml"
    if yaml_path.exists():
        return _load_protocol_from_yaml(yaml_path, workflow_type)

    # Try workflow-specific file
    yaml_path = PROTOCOLS_DIR / f"{workflow_type}_{name}.yaml"
    if yaml_path.exists():
        return _load_protocol_from_yaml(yaml_path, workflow_type)

    raise ProtocolError(f"Protocol '{name}' not found. Available: {get_available_protocols()}")


def _load_protocol_from_yaml(path: Path, workflow_type: str) -> BaseProtocol:
    """Load protocol from YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ProtocolError(f"Invalid protocol file: {path}")

    # Ensure required fields
    data.setdefault("name", path.stem)
    data.setdefault("description", f"Protocol from {path.name}")

    # Select appropriate protocol class
    protocol_classes = {
        "scf": SCFProtocol,
        "relax": RelaxationProtocol,
        "bands": BandStructureProtocol,
        "dos": DOSProtocol,
    }

    cls = protocol_classes.get(workflow_type, BaseProtocol)

    try:
        return cls.from_dict(data)
    except (TypeError, ValueError) as e:
        raise ProtocolError(f"Invalid protocol data in {path}: {e}") from e


def get_available_protocols() -> list[str]:
    """Get list of available protocol names."""
    protocols = list(BUILTIN_PROTOCOLS.keys())

    # Add protocols from YAML files
    if PROTOCOLS_DIR.exists():
        for yaml_file in PROTOCOLS_DIR.glob("*.yaml"):
            name = yaml_file.stem
            if name not in protocols:
                protocols.append(name)

    return sorted(protocols)


def get_protocol_description(name: str) -> str:
    """Get description for a protocol."""
    try:
        protocol = load_protocol(name)
        return protocol.description
    except ProtocolError:
        return f"Unknown protocol: {name}"


def validate_protocol(data: dict[str, Any]) -> list[str]:
    """
    Validate protocol data structure.

    Args:
        data: Protocol dictionary to validate.

    Returns:
        List of validation errors (empty if valid).
    """
    errors = []

    # Required fields
    if "name" not in data:
        errors.append("Missing required field: name")

    # SCF settings validation
    if "scf" in data:
        scf = data["scf"]
        if "maxcycle" in scf and scf["maxcycle"] < 1:
            errors.append("scf.maxcycle must be >= 1")
        if "toldee" in scf and not (4 <= scf["toldee"] <= 12):
            errors.append("scf.toldee should be between 4 and 12")
        if "fmixing" in scf and not (0 < scf["fmixing"] <= 100):
            errors.append("scf.fmixing should be between 1 and 100")

    # K-points validation
    if "kpoints" in data:
        kp = data["kpoints"]
        if "mesh" in kp:
            if len(kp["mesh"]) != 3:
                errors.append("kpoints.mesh must have 3 elements")
            if any(k < 1 for k in kp["mesh"]):
                errors.append("kpoints.mesh values must be >= 1")

    # Resources validation
    if "resources" in data:
        res = data["resources"]
        if "num_machines" in res and res["num_machines"] < 1:
            errors.append("resources.num_machines must be >= 1")
        if "max_wallclock_seconds" in res and res["max_wallclock_seconds"] < 60:
            errors.append("resources.max_wallclock_seconds should be >= 60")

    return errors


def get_builder_from_protocol(
    workchain_cls: type[WorkChain],
    structure: orm.StructureData,
    code: orm.AbstractCode,
    protocol: str | BaseProtocol = "moderate",
    **overrides,
) -> ProcessBuilder:
    """
    Generate a WorkChain builder from a protocol.

    Converts protocol settings to AiiDA-compatible inputs
    and creates a ProcessBuilder ready for submission.

    Args:
        workchain_cls: WorkChain class to get builder for.
        structure: Input crystal structure.
        code: CRYSTAL23 code node.
        protocol: Protocol name or instance.
        **overrides: Additional parameters to override.

    Returns:
        ProcessBuilder with protocol-based inputs.

    Example:
        >>> builder = get_builder_from_protocol(
        ...     CrystalBaseWorkChain,
        ...     structure=my_structure,
        ...     code=my_code,
        ...     protocol="moderate",
        ...     scf={"maxcycle": 200},  # Override
        ... )
        >>> result = engine.run(builder)
    """
    from aiida import orm

    # Load protocol if string
    if isinstance(protocol, str):
        protocol = load_protocol(protocol)

    # Get builder
    builder = workchain_cls.get_builder()

    # Set structure and code
    builder.structure = structure
    builder.code = code

    # Build parameters dict
    params = _protocol_to_parameters(protocol, overrides)

    # Set parameters
    builder.parameters = orm.Dict(dict=params)

    # Set options
    builder.options = orm.Dict(
        dict={
            "resources": {
                "num_machines": protocol.resources.num_machines,
                "num_mpiprocs_per_machine": protocol.resources.num_mpiprocs_per_machine,
            },
            "max_wallclock_seconds": protocol.resources.max_wallclock_seconds,
        }
    )

    # Set protocol-specific inputs
    if hasattr(builder, "protocol"):
        builder.protocol = orm.Str(protocol.name)

    if hasattr(builder, "clean_workdir"):
        builder.clean_workdir = orm.Bool(protocol.clean_workdir)

    return builder


def _protocol_to_parameters(
    protocol: BaseProtocol,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """Convert protocol to CRYSTAL23 parameters dict."""
    params: dict[str, Any] = {
        "scf": {
            "maxcycle": protocol.scf.maxcycle,
            "toldee": protocol.scf.toldee,
            "fmixing": protocol.scf.fmixing,
        },
        "kpoints": {
            "mesh": protocol.kpoints.mesh,
            "offset": protocol.kpoints.offset,
        },
    }

    # Add optional SCF settings
    if protocol.scf.anderson:
        params["scf"]["anderson"] = True
    if not protocol.scf.diis:
        params["scf"]["nodiis"] = True
    if protocol.scf.smearing:
        params["scf"]["smearing"] = True
        params["scf"]["smearing_width"] = protocol.scf.smearing_width
    if protocol.scf.spinpol:
        params["scf"]["spinpol"] = True
    if protocol.scf.level_shift is not None:
        params["scf"]["level_shift"] = protocol.scf.level_shift

    # K-points density alternative
    if protocol.kpoints.density is not None:
        params["kpoints"]["density"] = protocol.kpoints.density

    # Basis set
    params["basis_set"] = protocol.basis_set

    # Add relaxation settings if applicable
    if isinstance(protocol, RelaxationProtocol):
        params["optimization"] = {
            "type": protocol.optimization.type,
            "maxcycle": protocol.optimization.maxcycle,
            "toldeg": protocol.optimization.toldeg,
            "toldex": protocol.optimization.toldex,
        }
        if protocol.optimization.fix_volume:
            params["optimization"]["fix_volume"] = True
        if protocol.optimization.fix_shape:
            params["optimization"]["fix_shape"] = True

    # Add band structure settings if applicable
    if isinstance(protocol, BandStructureProtocol):
        params["band"] = {
            "enabled": True,
            "first_band": protocol.first_band,
            "last_band": protocol.last_band,
        }
        params["kpoints_distance"] = protocol.kpoints_distance

    # Add DOS settings if applicable
    if isinstance(protocol, DOSProtocol):
        params["doss"] = {
            "enabled": True,
            "energy_min": protocol.energy_min,
            "energy_max": protocol.energy_max,
            "n_points": protocol.n_energy_points,
            "smearing": protocol.smearing_width,
        }
        if protocol.compute_pdos:
            params["doss"]["projected"] = True
            if protocol.pdos_atoms:
                params["doss"]["atoms"] = protocol.pdos_atoms

    # Apply overrides (deep merge)
    _deep_merge(params, overrides)

    return params


def _deep_merge(base: dict, overrides: dict) -> None:
    """Deep merge overrides into base dict."""
    for key, value in overrides.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
