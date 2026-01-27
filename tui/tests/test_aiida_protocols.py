"""
Tests for CRYSTAL23 protocol-based configuration.

Tests:
    - Protocol schema validation
    - YAML loading
    - Builder generation
    - Protocol merging and overrides
"""

from pathlib import Path

import pytest

from src.aiida.protocols.loader import (
    ProtocolError,
    _deep_merge,
    _protocol_to_parameters,
    get_available_protocols,
    get_protocol_description,
    load_protocol,
    validate_protocol,
)
from src.aiida.protocols.schemas import (
    BUILTIN_PROTOCOLS,
    BandStructureProtocol,
    BaseProtocol,
    DOSProtocol,
    KPointsSettings,
    OptimizationSettings,
    ProtocolLevel,
    RelaxationProtocol,
    SCFProtocol,
    SCFSettings,
)


class TestSCFSettings:
    """Test SCF settings dataclass."""

    def test_default_values(self):
        """Test default SCF settings."""
        scf = SCFSettings()

        assert scf.maxcycle == 100
        assert scf.toldee == 7
        assert scf.fmixing == 40
        assert scf.diis is True
        assert scf.smearing is False

    def test_custom_values(self):
        """Test custom SCF settings."""
        scf = SCFSettings(maxcycle=200, toldee=8, spinpol=True)

        assert scf.maxcycle == 200
        assert scf.toldee == 8
        assert scf.spinpol is True


class TestKPointsSettings:
    """Test k-points settings."""

    def test_default_mesh(self):
        """Test default k-mesh."""
        kp = KPointsSettings()

        assert kp.mesh == [6, 6, 6]
        assert kp.offset == [0, 0, 0]
        assert kp.density is None

    def test_custom_mesh(self):
        """Test custom k-mesh."""
        kp = KPointsSettings(mesh=[8, 8, 8], density=0.1)

        assert kp.mesh == [8, 8, 8]
        assert kp.density == 0.1


class TestProtocolLevel:
    """Test protocol level enum."""

    def test_level_values(self):
        """Test protocol level values."""
        assert ProtocolLevel.FAST.value == "fast"
        assert ProtocolLevel.MODERATE.value == "moderate"
        assert ProtocolLevel.PRECISE.value == "precise"

    def test_level_from_string(self):
        """Test creating level from string."""
        level = ProtocolLevel("moderate")
        assert level == ProtocolLevel.MODERATE


class TestBaseProtocol:
    """Test base protocol class."""

    def test_from_dict(self):
        """Test creating protocol from dictionary."""
        data = {
            "name": "test",
            "description": "Test protocol",
            "level": "fast",
            "scf": {"maxcycle": 50, "toldee": 6},
            "kpoints": {"mesh": [4, 4, 4]},
        }

        protocol = BaseProtocol.from_dict(data)

        assert protocol.name == "test"
        assert protocol.description == "Test protocol"
        assert protocol.level == ProtocolLevel.FAST
        assert protocol.scf.maxcycle == 50
        assert protocol.scf.toldee == 6
        assert protocol.kpoints.mesh == [4, 4, 4]

    def test_to_dict(self):
        """Test converting protocol to dictionary."""
        protocol = BaseProtocol(
            name="test",
            description="Test",
            level=ProtocolLevel.MODERATE,
        )

        data = protocol.to_dict()

        assert data["name"] == "test"
        assert data["level"] == "moderate"
        assert "scf" in data
        assert "kpoints" in data


class TestSCFProtocol:
    """Test SCF-specific protocol."""

    def test_scf_protocol_defaults(self):
        """Test SCF protocol default values."""
        protocol = SCFProtocol(name="test", description="Test")

        assert protocol.calculate_forces is False
        assert protocol.calculate_stress is False
        assert protocol.store_wavefunction is True


class TestRelaxationProtocol:
    """Test relaxation protocol."""

    def test_relaxation_defaults(self):
        """Test relaxation protocol defaults."""
        protocol = RelaxationProtocol(name="test", description="Test")

        assert protocol.relax_type == "positions_cell"
        assert protocol.spin_type == "none"
        assert protocol.optimization.type == "FULLOPTG"
        assert protocol.optimization.maxcycle == 100

    def test_relaxation_from_dict(self):
        """Test relaxation protocol from dictionary."""
        data = {
            "name": "relax_test",
            "description": "Test relaxation",
            "optimization": {
                "type": "ATOMONLY",
                "maxcycle": 50,
                "toldeg": 0.001,
            },
            "relax_type": "positions",
        }

        protocol = RelaxationProtocol.from_dict(data)

        assert protocol.optimization.type == "ATOMONLY"
        assert protocol.optimization.maxcycle == 50
        assert protocol.relax_type == "positions"


class TestBandStructureProtocol:
    """Test band structure protocol."""

    def test_band_defaults(self):
        """Test band structure protocol defaults."""
        protocol = BandStructureProtocol(name="test", description="Test")

        assert protocol.kpoints_distance == 0.05
        assert protocol.first_band == 1
        assert protocol.last_band == -1
        assert protocol.run_scf is True

    def test_band_from_dict(self):
        """Test band structure from dictionary."""
        data = {
            "name": "bands_test",
            "description": "Test bands",
            "kpoints_distance": 0.03,
            "crystal_system": "hexagonal",
        }

        protocol = BandStructureProtocol.from_dict(data)

        assert protocol.kpoints_distance == 0.03
        assert protocol.crystal_system == "hexagonal"


class TestDOSProtocol:
    """Test DOS protocol."""

    def test_dos_defaults(self):
        """Test DOS protocol defaults."""
        protocol = DOSProtocol(name="test", description="Test")

        assert protocol.energy_min == -10.0
        assert protocol.energy_max == 5.0
        assert protocol.n_energy_points == 1001
        assert protocol.compute_pdos is False

    def test_dos_with_pdos(self):
        """Test DOS protocol with PDOS enabled."""
        protocol = DOSProtocol(
            name="test",
            description="Test",
            compute_pdos=True,
            pdos_atoms=[0, 1, 2],
        )

        assert protocol.compute_pdos is True
        assert protocol.pdos_atoms == [0, 1, 2]


class TestBuiltinProtocols:
    """Test built-in protocol registry."""

    def test_builtin_protocols_exist(self):
        """Test that built-in protocols are registered."""
        assert "fast" in BUILTIN_PROTOCOLS
        assert "moderate" in BUILTIN_PROTOCOLS
        assert "precise" in BUILTIN_PROTOCOLS

    def test_fast_protocol_values(self):
        """Test fast protocol has relaxed settings."""
        fast = BUILTIN_PROTOCOLS["fast"]

        assert fast.scf.maxcycle == 50
        assert fast.scf.toldee == 6
        assert fast.kpoints.mesh == [4, 4, 4]

    def test_precise_protocol_values(self):
        """Test precise protocol has tight settings."""
        precise = BUILTIN_PROTOCOLS["precise"]

        assert precise.scf.maxcycle == 200
        assert precise.scf.toldee == 8
        assert precise.kpoints.mesh == [8, 8, 8]
        assert precise.basis_set == "pob-qzvp"


class TestProtocolLoading:
    """Test protocol loading functions."""

    def test_load_builtin_protocol(self):
        """Test loading built-in protocol."""
        protocol = load_protocol("moderate")

        assert protocol.name == "moderate"
        assert protocol.level == ProtocolLevel.MODERATE

    def test_load_unknown_protocol_raises(self):
        """Test loading unknown protocol raises error."""
        with pytest.raises(ProtocolError, match="not found"):
            load_protocol("nonexistent_protocol")

    def test_get_available_protocols(self):
        """Test getting available protocols."""
        protocols = get_available_protocols()

        assert "fast" in protocols
        assert "moderate" in protocols
        assert "precise" in protocols
        assert len(protocols) >= 3

    def test_get_protocol_description(self):
        """Test getting protocol description."""
        desc = get_protocol_description("moderate")

        assert "default" in desc.lower() or "balanced" in desc.lower()


class TestProtocolValidation:
    """Test protocol validation."""

    def test_valid_protocol(self):
        """Test validating a valid protocol."""
        data = {
            "name": "test",
            "scf": {"maxcycle": 100, "toldee": 7},
            "kpoints": {"mesh": [6, 6, 6]},
        }

        errors = validate_protocol(data)

        assert len(errors) == 0

    def test_invalid_maxcycle(self):
        """Test validation catches invalid maxcycle."""
        data = {
            "name": "test",
            "scf": {"maxcycle": 0},
        }

        errors = validate_protocol(data)

        assert any("maxcycle" in e for e in errors)

    def test_invalid_toldee(self):
        """Test validation catches invalid toldee."""
        data = {
            "name": "test",
            "scf": {"toldee": 20},  # Too high
        }

        errors = validate_protocol(data)

        assert any("toldee" in e for e in errors)

    def test_invalid_kmesh(self):
        """Test validation catches invalid k-mesh."""
        data = {
            "name": "test",
            "kpoints": {"mesh": [4, 4]},  # Only 2 elements
        }

        errors = validate_protocol(data)

        assert any("mesh" in e for e in errors)

    def test_missing_name(self):
        """Test validation catches missing name."""
        data = {
            "scf": {"maxcycle": 100},
        }

        errors = validate_protocol(data)

        assert any("name" in e for e in errors)


class TestDeepMerge:
    """Test deep merge utility."""

    def test_simple_merge(self):
        """Test simple dictionary merge."""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}

        _deep_merge(base, override)

        assert base["a"] == 1
        assert base["b"] == 3
        assert base["c"] == 4

    def test_nested_merge(self):
        """Test nested dictionary merge."""
        base = {"scf": {"maxcycle": 100, "toldee": 7}}
        override = {"scf": {"maxcycle": 200}}

        _deep_merge(base, override)

        assert base["scf"]["maxcycle"] == 200
        assert base["scf"]["toldee"] == 7  # Preserved


class TestProtocolToParameters:
    """Test protocol to parameters conversion."""

    def test_basic_conversion(self):
        """Test basic protocol to parameters conversion."""
        protocol = BUILTIN_PROTOCOLS["moderate"]

        params = _protocol_to_parameters(protocol, {})

        assert "scf" in params
        assert params["scf"]["maxcycle"] == 100
        assert params["scf"]["toldee"] == 7
        assert params["kpoints"]["mesh"] == [6, 6, 6]

    def test_with_overrides(self):
        """Test conversion with overrides."""
        protocol = BUILTIN_PROTOCOLS["moderate"]
        overrides = {"scf": {"maxcycle": 200}}

        params = _protocol_to_parameters(protocol, overrides)

        assert params["scf"]["maxcycle"] == 200  # Overridden
        assert params["scf"]["toldee"] == 7  # Preserved

    def test_relaxation_protocol_conversion(self):
        """Test relaxation protocol adds optimization settings."""
        protocol = RelaxationProtocol(
            name="test",
            description="Test",
            optimization=OptimizationSettings(type="ATOMONLY"),
        )

        params = _protocol_to_parameters(protocol, {})

        assert "optimization" in params
        assert params["optimization"]["type"] == "ATOMONLY"

    def test_bands_protocol_conversion(self):
        """Test band structure protocol adds band settings."""
        protocol = BandStructureProtocol(
            name="test",
            description="Test",
            kpoints_distance=0.03,
        )

        params = _protocol_to_parameters(protocol, {})

        assert "band" in params
        assert params["band"]["enabled"] is True
        assert params["kpoints_distance"] == 0.03

    def test_dos_protocol_conversion(self):
        """Test DOS protocol adds doss settings."""
        protocol = DOSProtocol(
            name="test",
            description="Test",
            compute_pdos=True,
            pdos_atoms=[0, 1],
        )

        params = _protocol_to_parameters(protocol, {})

        assert "doss" in params
        assert params["doss"]["enabled"] is True
        assert params["doss"]["projected"] is True
        assert params["doss"]["atoms"] == [0, 1]


class TestYAMLProtocolFiles:
    """Test loading YAML protocol files."""

    def test_yaml_files_exist(self):
        """Test that YAML protocol files exist."""
        definitions_dir = Path(__file__).parent.parent / "src/aiida/protocols/definitions"

        assert definitions_dir.exists()
        yaml_files = list(definitions_dir.glob("*.yaml"))
        assert len(yaml_files) >= 1

    def test_load_yaml_protocol(self):
        """Test loading a YAML protocol file."""
        # This will look for metal.yaml in definitions/
        try:
            protocol = load_protocol("metal")
            assert protocol.scf.smearing is True
            assert protocol.scf.anderson is True
        except ProtocolError:
            pytest.skip("metal.yaml not found")

    def test_load_magnetic_protocol(self):
        """Test loading magnetic protocol."""
        try:
            protocol = load_protocol("magnetic")
            assert protocol.scf.spinpol is True
        except ProtocolError:
            pytest.skip("magnetic.yaml not found")
