"""
Protocol-based configuration for CRYSTAL23 workflows.

This module provides a user-friendly YAML-based configuration system
that maps to AiiDA WorkChain inputs. Users can specify calculations
using simple protocol names (fast/moderate/precise) rather than
understanding all the underlying parameters.

Usage:
    >>> from src.aiida.protocols import load_protocol, get_builder_from_protocol
    >>>
    >>> # Load a protocol
    >>> protocol = load_protocol("moderate")
    >>>
    >>> # Generate WorkChain builder from protocol
    >>> builder = get_builder_from_protocol(
    ...     CrystalBaseWorkChain,
    ...     structure=my_structure,
    ...     protocol="moderate",
    ... )

Protocol files are stored in the protocols/ directory as YAML files.
Custom protocols can be added by creating new YAML files following
the schema defined in protocols/schema.yaml.
"""

from .loader import (
    ProtocolError,
    get_available_protocols,
    get_builder_from_protocol,
    get_protocol_description,
    load_protocol,
    validate_protocol,
)
from .schemas import (
    BandStructureProtocol,
    BaseProtocol,
    DOSProtocol,
    RelaxationProtocol,
    SCFProtocol,
)

__all__ = [
    # Loading functions
    "load_protocol",
    "get_available_protocols",
    "get_protocol_description",
    "validate_protocol",
    "get_builder_from_protocol",
    "ProtocolError",
    # Schema classes
    "BaseProtocol",
    "SCFProtocol",
    "RelaxationProtocol",
    "BandStructureProtocol",
    "DOSProtocol",
]
