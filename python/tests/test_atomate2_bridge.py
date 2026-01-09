"""Tests for atomate2_bridge module.

This module tests atomate2 integration including:
- FlowMakerRegistry workflow lookup
- Atomate2FlowAdapter flow wrapping
- Atomate2Bridge submission interface
- MultiCodeFlowBuilder for complex workflows

Tests are designed to work without atomate2/jobflow installed by using mocks.
Many methods are stubs for Phase 3 implementation.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from dataclasses import dataclass

# Check if optional dependencies are available
try:
    import atomate2

    HAS_ATOMATE2 = True
except ImportError:
    HAS_ATOMATE2 = False

try:
    import jobflow

    HAS_JOBFLOW = True
except ImportError:
    HAS_JOBFLOW = False


# =============================================================================
# Mock Classes for Testing
# =============================================================================


@dataclass
class MockJob:
    """Mock jobflow Job for testing."""

    name: str
    uuid: str = "test-uuid-1234"
    output: Any = None
    state: str = "READY"


@dataclass
class MockFlow:
    """Mock jobflow Flow for testing."""

    name: str
    jobs: List[MockJob]
    uuid: str = "flow-uuid-1234"
    state: str = "READY"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_structure() -> Mock:
    """Create a mock pymatgen Structure."""
    mock = Mock()
    mock.formula = "Si2"
    mock.composition.reduced_formula = "Si"
    mock.num_sites = 2
    mock.volume = 40.0
    mock.lattice.abc = (5.43, 5.43, 5.43)
    mock.lattice.angles = (90.0, 90.0, 90.0)
    return mock


@pytest.fixture
def mock_vasp_job() -> MockJob:
    """Create a mock VASP job."""
    return MockJob(name="relax", uuid="vasp-job-1234")


@pytest.fixture
def mock_vasp_flow(mock_vasp_job: MockJob) -> MockFlow:
    """Create a mock VASP flow."""
    return MockFlow(name="vasp_relax_flow", jobs=[mock_vasp_job])


# =============================================================================
# Test FlowMakerRegistry
# =============================================================================


class TestFlowMakerRegistry:
    """Tests for FlowMakerRegistry workflow lookup."""

    def test_registry_creation(self) -> None:
        """Test creating registry instance."""
        from crystalmath.integrations.atomate2_bridge import FlowMakerRegistry

        registry = FlowMakerRegistry()
        assert registry is not None

    def test_registry_list_available(self) -> None:
        """Test listing available workflow/code combinations."""
        from crystalmath.integrations.atomate2_bridge import FlowMakerRegistry

        registry = FlowMakerRegistry()
        available = registry.list_available()

        assert isinstance(available, dict)
        assert "relax" in available
        assert "vasp" in available["relax"]

    def test_registry_register_maker(self) -> None:
        """Test registering a custom maker."""
        from crystalmath.integrations.atomate2_bridge import (
            FlowMakerRegistry,
            MakerConfig,
        )

        registry = FlowMakerRegistry()

        mock_maker_class = Mock()
        config = MakerConfig(
            maker_class=mock_maker_class,
            default_kwargs={"option": "value"},
        )

        registry.register("custom_workflow", "custom_code", config)

        # Verify registration
        available = registry.list_available()
        assert "custom_workflow" in available
        assert "custom_code" in available["custom_workflow"]

    @pytest.mark.skip(reason="Requires atomate2 to be installed")
    def test_registry_get_maker(self) -> None:
        """Test getting a maker for workflow/code combination."""
        from crystalmath.integrations.atomate2_bridge import FlowMakerRegistry

        registry = FlowMakerRegistry()
        maker = registry.get_maker("relax", code="vasp")
        assert maker is not None

    def test_registry_get_maker_not_found(self) -> None:
        """Test error for unknown workflow type."""
        from crystalmath.integrations.atomate2_bridge import (
            FlowMakerRegistry,
            MakerNotFoundError,
        )

        registry = FlowMakerRegistry()

        with pytest.raises(MakerNotFoundError):
            registry.get_maker("unknown_workflow", code="vasp")

    def test_registry_get_maker_unknown_code(self) -> None:
        """Test error for unknown code."""
        from crystalmath.integrations.atomate2_bridge import (
            FlowMakerRegistry,
            MakerNotFoundError,
        )

        registry = FlowMakerRegistry()

        with pytest.raises(MakerNotFoundError):
            registry.get_maker("relax", code="unknown_code")


# =============================================================================
# Test Protocol Level
# =============================================================================


class TestProtocolLevel:
    """Tests for ProtocolLevel enum."""

    def test_protocol_levels(self) -> None:
        """Test all protocol levels exist."""
        from crystalmath.integrations.atomate2_bridge import ProtocolLevel

        assert ProtocolLevel.FAST.value == "fast"
        assert ProtocolLevel.MODERATE.value == "moderate"
        assert ProtocolLevel.PRECISE.value == "precise"

    def test_protocol_level_extended(self) -> None:
        """Test extended protocol levels."""
        from crystalmath.integrations.atomate2_bridge import ProtocolLevel

        assert ProtocolLevel.DEBUG.value == "debug"
        assert ProtocolLevel.PRODUCTION.value == "production"


# =============================================================================
# Test Execution Mode
# =============================================================================


class TestExecutionMode:
    """Tests for ExecutionMode enum."""

    def test_execution_modes(self) -> None:
        """Test all execution modes exist."""
        from crystalmath.integrations.atomate2_bridge import ExecutionMode

        assert ExecutionMode.LOCAL.value == "local"
        assert ExecutionMode.REMOTE.value == "remote"
        assert ExecutionMode.FIREWORKS.value == "fireworks"


# =============================================================================
# Test MakerConfig
# =============================================================================


class TestMakerConfig:
    """Tests for MakerConfig dataclass."""

    def test_create_maker_config(self) -> None:
        """Test creating a MakerConfig."""
        from crystalmath.integrations.atomate2_bridge import MakerConfig, ProtocolLevel

        mock_maker_class = Mock()
        config = MakerConfig(
            maker_class=mock_maker_class,
            default_kwargs={"option": "value"},
            protocol_mapping={
                ProtocolLevel.FAST: {"fast_option": True},
                ProtocolLevel.PRECISE: {"precise_option": True},
            },
            requires_gpu=True,
            supported_codes=["vasp", "qe"],
        )

        assert config.maker_class == mock_maker_class
        assert config.default_kwargs == {"option": "value"}
        assert config.requires_gpu is True
        assert "vasp" in config.supported_codes


# =============================================================================
# Test FlowResult
# =============================================================================


class TestFlowResult:
    """Tests for FlowResult dataclass."""

    def test_create_flow_result(self) -> None:
        """Test creating a FlowResult."""
        from crystalmath.integrations.atomate2_bridge import FlowResult

        result = FlowResult(
            flow_uuid="test-uuid-1234",
            job_uuids=["job-1", "job-2"],
            outputs={"energy": -10.5},
            state="completed",
        )

        assert result.flow_uuid == "test-uuid-1234"
        assert len(result.job_uuids) == 2
        assert result.state == "completed"

    def test_flow_result_to_workflow_result(self) -> None:
        """Test converting FlowResult to WorkflowResult."""
        from crystalmath.integrations.atomate2_bridge import FlowResult

        result = FlowResult(
            flow_uuid="test-uuid-1234",
            job_uuids=["job-1"],
            outputs={"energy": -10.5},
            state="completed",
        )

        workflow_result = result.to_workflow_result()

        assert workflow_result.success is True
        assert workflow_result.workflow_id == "test-uuid-1234"
        assert "energy" in workflow_result.outputs


# =============================================================================
# Test CodeHandoff
# =============================================================================


class TestCodeHandoff:
    """Tests for CodeHandoff dataclass."""

    def test_create_code_handoff(self) -> None:
        """Test creating a CodeHandoff."""
        from crystalmath.integrations.atomate2_bridge import CodeHandoff

        handoff = CodeHandoff(
            source_code="vasp",
            target_code="yambo",
            output_key="structure",
            input_key="structure",
        )

        assert handoff.source_code == "vasp"
        assert handoff.target_code == "yambo"

    def test_code_handoff_transfer(self) -> None:
        """Test data transfer in CodeHandoff."""
        from crystalmath.integrations.atomate2_bridge import CodeHandoff

        handoff = CodeHandoff(
            source_code="vasp",
            target_code="yambo",
            output_key="structure",
            input_key="input_structure",
        )

        source_outputs = {"structure": "mock_structure"}
        result = handoff.transfer(source_outputs)

        assert "input_structure" in result
        assert result["input_structure"] == "mock_structure"

    def test_code_handoff_with_converter(self) -> None:
        """Test data transfer with converter function."""
        from crystalmath.integrations.atomate2_bridge import CodeHandoff

        def converter(value):
            return f"converted_{value}"

        handoff = CodeHandoff(
            source_code="vasp",
            target_code="yambo",
            output_key="energy",
            input_key="input_energy",
            converter=converter,
        )

        source_outputs = {"energy": -10.5}
        result = handoff.transfer(source_outputs)

        assert result["input_energy"] == "converted_-10.5"

    def test_code_handoff_missing_key(self) -> None:
        """Test error when output key is missing."""
        from crystalmath.integrations.atomate2_bridge import (
            CodeHandoff,
            CodeHandoffError,
        )

        handoff = CodeHandoff(
            source_code="vasp",
            target_code="yambo",
            output_key="missing_key",
            input_key="input",
        )

        with pytest.raises(CodeHandoffError):
            handoff.transfer({"other_key": "value"})


# =============================================================================
# Test Atomate2FlowAdapter
# =============================================================================


class TestAtomate2FlowAdapter:
    """Tests for Atomate2FlowAdapter flow wrapping."""

    def test_adapter_creation(self, mock_vasp_flow: MockFlow) -> None:
        """Test adapter instance creation."""
        from crystalmath.integrations.atomate2_bridge import Atomate2FlowAdapter

        adapter = Atomate2FlowAdapter(flow=mock_vasp_flow)
        assert adapter is not None
        assert adapter.flow == mock_vasp_flow

    def test_adapter_flow_uuid(self, mock_vasp_flow: MockFlow) -> None:
        """Test getting flow UUID."""
        from crystalmath.integrations.atomate2_bridge import Atomate2FlowAdapter

        adapter = Atomate2FlowAdapter(flow=mock_vasp_flow)
        assert adapter.flow_uuid == mock_vasp_flow.uuid

    @pytest.mark.skip(reason="run_and_collect is stub - Phase 3 implementation")
    def test_adapter_run_and_collect(self, mock_vasp_flow: MockFlow) -> None:
        """Test running flow and collecting results."""
        from crystalmath.integrations.atomate2_bridge import Atomate2FlowAdapter

        adapter = Atomate2FlowAdapter(flow=mock_vasp_flow)
        result = adapter.run_and_collect()
        assert result is not None


# =============================================================================
# Test Atomate2Bridge
# =============================================================================


class TestAtomate2Bridge:
    """Tests for Atomate2Bridge main integration point."""

    def test_bridge_creation(self) -> None:
        """Test bridge instance creation."""
        from crystalmath.integrations.atomate2_bridge import Atomate2Bridge

        bridge = Atomate2Bridge()
        assert bridge is not None
        assert bridge.name == "atomate2"

    def test_bridge_is_available(self) -> None:
        """Test checking atomate2 availability."""
        from crystalmath.integrations.atomate2_bridge import Atomate2Bridge

        bridge = Atomate2Bridge()
        available = bridge.is_available

        # Returns True only if atomate2 and jobflow are installed
        assert isinstance(available, bool)

    def test_bridge_execution_modes(self) -> None:
        """Test bridge with different execution modes."""
        from crystalmath.integrations.atomate2_bridge import (
            Atomate2Bridge,
            ExecutionMode,
        )

        bridge = Atomate2Bridge(execution_mode=ExecutionMode.LOCAL)
        assert bridge is not None

        bridge = Atomate2Bridge(execution_mode=ExecutionMode.REMOTE)
        assert bridge is not None

    @pytest.mark.skip(reason="submit requires atomate2 Maker - Phase 3 implementation")
    def test_bridge_submit(self, mock_structure: Mock) -> None:
        """Test submitting a workflow."""
        from crystalmath.integrations.atomate2_bridge import Atomate2Bridge
        from crystalmath.protocols import WorkflowType

        bridge = Atomate2Bridge()
        result = bridge.submit(
            workflow_type=WorkflowType.RELAX,
            structure=mock_structure,
            code="vasp",
        )
        assert result is not None

    def test_bridge_get_status_unknown_workflow(self) -> None:
        """Test getting status of unknown workflow."""
        from crystalmath.integrations.atomate2_bridge import Atomate2Bridge

        bridge = Atomate2Bridge()
        status = bridge.get_status("unknown-uuid")

        assert status == "failed"

    def test_bridge_get_result_unknown_workflow(self) -> None:
        """Test getting result of unknown workflow."""
        from crystalmath.integrations.atomate2_bridge import Atomate2Bridge

        bridge = Atomate2Bridge()
        result = bridge.get_result("unknown-uuid")

        assert result.success is False
        assert len(result.errors) > 0

    def test_bridge_cancel_unknown_workflow(self) -> None:
        """Test canceling unknown workflow."""
        from crystalmath.integrations.atomate2_bridge import Atomate2Bridge

        bridge = Atomate2Bridge()
        cancelled = bridge.cancel("unknown-uuid")

        assert cancelled is False


# =============================================================================
# Test MultiCodeFlowBuilder
# =============================================================================


class TestMultiCodeFlowBuilder:
    """Tests for MultiCodeFlowBuilder complex workflows."""

    def test_builder_creation(self) -> None:
        """Test builder instance creation."""
        from crystalmath.integrations.atomate2_bridge import MultiCodeFlowBuilder

        builder = MultiCodeFlowBuilder()
        assert builder is not None

    def test_builder_add_step(self) -> None:
        """Test adding workflow steps."""
        from crystalmath.integrations.atomate2_bridge import MultiCodeFlowBuilder
        from crystalmath.protocols import WorkflowType

        builder = MultiCodeFlowBuilder()
        result = builder.add_step(
            name="relax",
            code="vasp",
            workflow_type=WorkflowType.RELAX,
        )

        # Should return self for chaining
        assert result is builder

    def test_builder_add_handoff(self) -> None:
        """Test adding data handoffs."""
        from crystalmath.integrations.atomate2_bridge import MultiCodeFlowBuilder
        from crystalmath.protocols import WorkflowType

        builder = MultiCodeFlowBuilder()
        builder.add_step("scf", "vasp", WorkflowType.SCF)
        builder.add_step("gw", "yambo", WorkflowType.GW)

        result = builder.add_handoff(
            source_step="scf",
            target_step="gw",
            output_key="structure",
            input_key="structure",
        )

        # Should return self for chaining
        assert result is builder

    def test_builder_method_chaining(self) -> None:
        """Test builder method chaining."""
        from crystalmath.integrations.atomate2_bridge import MultiCodeFlowBuilder
        from crystalmath.protocols import WorkflowType

        builder = (
            MultiCodeFlowBuilder()
            .add_step("relax", "vasp", WorkflowType.RELAX)
            .add_step("scf", "vasp", WorkflowType.SCF, depends_on=["relax"])
            .add_step("gw", "yambo", WorkflowType.GW, depends_on=["scf"])
            .add_handoff("scf", "gw")
        )

        assert builder is not None

    def test_builder_validate_empty(self) -> None:
        """Test validation of empty workflow."""
        from crystalmath.integrations.atomate2_bridge import MultiCodeFlowBuilder

        builder = MultiCodeFlowBuilder()
        is_valid, issues = builder.validate()

        assert isinstance(is_valid, bool)
        assert isinstance(issues, list)

    def test_builder_validate_missing_dependency(self) -> None:
        """Test validation catches missing dependencies."""
        from crystalmath.integrations.atomate2_bridge import MultiCodeFlowBuilder
        from crystalmath.protocols import WorkflowType

        builder = MultiCodeFlowBuilder()
        builder.add_step(
            "gw",
            "yambo",
            WorkflowType.GW,
            depends_on=["nonexistent_step"],
        )

        is_valid, issues = builder.validate()

        assert is_valid is False
        assert len(issues) > 0

    def test_builder_validate_circular_dependency(self) -> None:
        """Test validation catches circular dependencies."""
        from crystalmath.integrations.atomate2_bridge import MultiCodeFlowBuilder
        from crystalmath.protocols import WorkflowType

        builder = MultiCodeFlowBuilder()
        builder.add_step(
            "step1",
            "vasp",
            WorkflowType.SCF,
            depends_on=["step1"],  # Self-dependency
        )

        is_valid, issues = builder.validate()

        assert is_valid is False
        assert len(issues) > 0

    @pytest.mark.skip(reason="build is stub - Phase 3 implementation")
    def test_builder_build(self, mock_structure: Mock) -> None:
        """Test building the composite flow."""
        from crystalmath.integrations.atomate2_bridge import MultiCodeFlowBuilder
        from crystalmath.protocols import WorkflowType

        builder = (
            MultiCodeFlowBuilder()
            .add_step("relax", "vasp", WorkflowType.RELAX)
            .add_step("scf", "vasp", WorkflowType.SCF, depends_on=["relax"])
        )

        flow = builder.build(mock_structure)
        assert flow is not None


# =============================================================================
# Test Factory Functions
# =============================================================================


class TestFactoryFunctions:
    """Tests for convenience factory functions."""

    def test_get_atomate2_bridge(self) -> None:
        """Test get_atomate2_bridge factory function."""
        from crystalmath.integrations.atomate2_bridge import get_atomate2_bridge

        bridge = get_atomate2_bridge()
        assert bridge is not None
        assert bridge.name == "atomate2"

    def test_get_atomate2_bridge_with_execution_mode(self) -> None:
        """Test get_atomate2_bridge with execution mode."""
        from crystalmath.integrations.atomate2_bridge import (
            get_atomate2_bridge,
            ExecutionMode,
        )

        bridge = get_atomate2_bridge(execution_mode=ExecutionMode.REMOTE)
        assert bridge is not None

    @pytest.mark.skip(reason="create_vasp_to_yambo_flow is stub - Phase 3 implementation")
    def test_create_vasp_to_yambo_flow(self, mock_structure: Mock) -> None:
        """Test VASP to YAMBO flow creation."""
        from crystalmath.integrations.atomate2_bridge import create_vasp_to_yambo_flow

        flow = create_vasp_to_yambo_flow(mock_structure)
        assert flow is not None


# =============================================================================
# Test Exceptions
# =============================================================================


class TestExceptions:
    """Tests for custom exceptions."""

    def test_atomate2_integration_error(self) -> None:
        """Test base integration error."""
        from crystalmath.integrations.atomate2_bridge import Atomate2IntegrationError

        error = Atomate2IntegrationError("Test error")
        assert str(error) == "Test error"

    def test_maker_not_found_error(self) -> None:
        """Test MakerNotFoundError."""
        from crystalmath.integrations.atomate2_bridge import MakerNotFoundError

        error = MakerNotFoundError("Maker not found")
        assert isinstance(error, Exception)

    def test_flow_execution_error(self) -> None:
        """Test FlowExecutionError."""
        from crystalmath.integrations.atomate2_bridge import FlowExecutionError

        error = FlowExecutionError("Execution failed")
        assert isinstance(error, Exception)

    def test_code_handoff_error(self) -> None:
        """Test CodeHandoffError."""
        from crystalmath.integrations.atomate2_bridge import CodeHandoffError

        error = CodeHandoffError("Handoff failed")
        assert isinstance(error, Exception)


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.skipif(not HAS_ATOMATE2, reason="atomate2 not installed")
class TestAtomate2Integration:
    """Integration tests using real atomate2."""

    def test_real_vasp_maker_import(self) -> None:
        """Test importing real VASP makers."""
        from atomate2.vasp.flows.core import DoubleRelaxMaker

        assert DoubleRelaxMaker is not None

    def test_real_flow_creation(self, mock_structure: Mock) -> None:
        """Test creating real flow (mocked execution)."""
        pass  # Requires actual atomate2


@pytest.mark.skipif(not HAS_JOBFLOW, reason="jobflow not installed")
class TestJobflowIntegration:
    """Integration tests using real jobflow."""

    def test_real_job_creation(self) -> None:
        """Test creating real jobflow Job."""
        from jobflow import job

        @job
        def test_job():
            return 42

        job_instance = test_job()
        assert job_instance is not None

    def test_real_flow_creation(self) -> None:
        """Test creating real jobflow Flow."""
        from jobflow import Flow, job

        @job
        def job1():
            return 1

        @job
        def job2():
            return 2

        flow = Flow([job1(), job2()])
        assert len(flow.jobs) == 2
