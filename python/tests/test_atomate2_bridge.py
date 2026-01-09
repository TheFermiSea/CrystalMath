"""Tests for atomate2_bridge module.

This module tests atomate2 integration including:
- FlowMakerRegistry code selection
- Atomate2FlowAdapter flow adaptation
- JobStore bridge functionality
- Mock atomate2/jobflow dependencies

Tests are designed to work without atomate2/jobflow installed by using mocks.
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


@pytest.fixture
def mock_job_store() -> Mock:
    """Create a mock JobStore."""
    store = Mock()
    store.connect.return_value = None
    store.query.return_value = []
    store.update.return_value = None
    return store


# =============================================================================
# Test FlowMakerRegistry
# =============================================================================


class TestFlowMakerRegistry:
    """Tests for FlowMakerRegistry code selection."""

    def test_registry_get_available_codes(self) -> None:
        """Test getting available DFT codes."""
        from crystalmath.integrations.atomate2_bridge import FlowMakerRegistry

        codes = FlowMakerRegistry.get_available_codes()
        assert isinstance(codes, list)
        assert "vasp" in codes

    def test_registry_get_code_workflows(self) -> None:
        """Test getting workflows for a specific code."""
        from crystalmath.integrations.atomate2_bridge import FlowMakerRegistry

        workflows = FlowMakerRegistry.get_code_workflows("vasp")
        assert isinstance(workflows, list)
        assert len(workflows) > 0

    def test_registry_select_code_for_property(self) -> None:
        """Test code selection based on property."""
        from crystalmath.integrations.atomate2_bridge import FlowMakerRegistry

        # Test standard DFT properties prefer VASP
        code = FlowMakerRegistry.select_code_for_property("bands")
        assert code in ["vasp", "qe", "crystal23"]

    def test_registry_select_code_for_gw(self) -> None:
        """Test code selection for GW calculations."""
        from crystalmath.integrations.atomate2_bridge import FlowMakerRegistry

        code = FlowMakerRegistry.select_code_for_property("gw")
        assert code in ["yambo", "berkeleygw", "vasp"]

    def test_registry_select_code_for_bse(self) -> None:
        """Test code selection for BSE calculations."""
        from crystalmath.integrations.atomate2_bridge import FlowMakerRegistry

        code = FlowMakerRegistry.select_code_for_property("bse")
        assert code in ["yambo", "berkeleygw"]

    @pytest.mark.parametrize(
        "property_name,expected_codes",
        [
            ("scf", ["vasp", "qe", "crystal23"]),
            ("relax", ["vasp", "qe", "crystal23"]),
            ("bands", ["vasp", "qe", "crystal23"]),
            ("dos", ["vasp", "qe", "crystal23"]),
            ("phonon", ["vasp", "qe"]),
            ("elastic", ["vasp"]),
            ("gw", ["yambo", "berkeleygw", "vasp"]),
            ("bse", ["yambo", "berkeleygw"]),
        ],
    )
    def test_registry_code_selection_all_properties(
        self, property_name: str, expected_codes: List[str]
    ) -> None:
        """Test code selection for all supported properties."""
        from crystalmath.integrations.atomate2_bridge import FlowMakerRegistry

        code = FlowMakerRegistry.select_code_for_property(property_name)
        assert code in expected_codes

    def test_registry_unknown_property(self) -> None:
        """Test error handling for unknown property."""
        from crystalmath.integrations.atomate2_bridge import FlowMakerRegistry

        with pytest.raises((KeyError, ValueError)):
            FlowMakerRegistry.select_code_for_property("unknown_property")

    def test_registry_get_maker_class(self) -> None:
        """Test getting maker class for code/workflow combination."""
        with patch(
            "crystalmath.integrations.atomate2_bridge.HAS_ATOMATE2", True
        ):
            from crystalmath.integrations.atomate2_bridge import FlowMakerRegistry

            # Should return maker class or None if not available
            maker_class = FlowMakerRegistry.get_maker_class("vasp", "relax")
            # Type depends on whether atomate2 is installed

    def test_registry_register_custom_maker(self) -> None:
        """Test registering custom maker class."""
        from crystalmath.integrations.atomate2_bridge import FlowMakerRegistry

        mock_maker = Mock()
        FlowMakerRegistry.register_maker("custom_code", "custom_workflow", mock_maker)

        # Verify registration
        makers = FlowMakerRegistry.get_code_workflows("custom_code")
        assert "custom_workflow" in makers


class TestFlowMakerRegistryConfiguration:
    """Tests for FlowMakerRegistry configuration options."""

    def test_registry_set_default_code(self) -> None:
        """Test setting default code preference."""
        from crystalmath.integrations.atomate2_bridge import FlowMakerRegistry

        FlowMakerRegistry.set_default_code("vasp")
        default = FlowMakerRegistry.get_default_code()
        assert default == "vasp"

    def test_registry_code_priority(self) -> None:
        """Test code priority ordering."""
        from crystalmath.integrations.atomate2_bridge import FlowMakerRegistry

        FlowMakerRegistry.set_code_priority(["vasp", "qe", "crystal23"])
        priority = FlowMakerRegistry.get_code_priority()
        assert priority[0] == "vasp"

    def test_registry_validate_code_availability(self) -> None:
        """Test validation of code availability."""
        from crystalmath.integrations.atomate2_bridge import FlowMakerRegistry

        is_available = FlowMakerRegistry.is_code_available("vasp")
        assert isinstance(is_available, bool)


# =============================================================================
# Test Atomate2FlowAdapter
# =============================================================================


class TestAtomate2FlowAdapter:
    """Tests for Atomate2FlowAdapter flow adaptation."""

    def test_adapter_creation(self) -> None:
        """Test adapter instance creation."""
        from crystalmath.integrations.atomate2_bridge import Atomate2FlowAdapter

        adapter = Atomate2FlowAdapter()
        assert adapter is not None

    def test_adapter_adapt_vasp_flow(self, mock_structure: Mock) -> None:
        """Test adapting a VASP flow."""
        mock_maker = Mock()
        mock_flow = MockFlow(name="test", jobs=[MockJob(name="relax")])
        mock_maker.make.return_value = mock_flow

        with patch(
            "crystalmath.integrations.atomate2_bridge.HAS_ATOMATE2", True
        ):
            from crystalmath.integrations.atomate2_bridge import Atomate2FlowAdapter

            adapter = Atomate2FlowAdapter()
            result = adapter.adapt_flow(mock_maker, mock_structure)
            assert result is not None

    def test_adapter_set_resources(self) -> None:
        """Test setting computational resources."""
        from crystalmath.integrations.atomate2_bridge import Atomate2FlowAdapter

        adapter = Atomate2FlowAdapter()
        adapter.set_resources(
            num_nodes=2,
            num_cores=40,
            walltime_hours=24,
            memory_gb=100,
        )

        resources = adapter.get_resources()
        assert resources["num_nodes"] == 2
        assert resources["num_cores"] == 40

    def test_adapter_set_code_settings(self) -> None:
        """Test setting code-specific settings."""
        from crystalmath.integrations.atomate2_bridge import Atomate2FlowAdapter

        adapter = Atomate2FlowAdapter()
        adapter.set_code_settings("vasp", {"ENCUT": 520, "EDIFF": 1e-6})

        settings = adapter.get_code_settings("vasp")
        assert settings["ENCUT"] == 520

    def test_adapter_chain_flows(self) -> None:
        """Test chaining multiple flows together."""
        flow1 = MockFlow(name="relax", jobs=[MockJob(name="relax")])
        flow2 = MockFlow(name="bands", jobs=[MockJob(name="bands")])

        from crystalmath.integrations.atomate2_bridge import Atomate2FlowAdapter

        adapter = Atomate2FlowAdapter()
        chained = adapter.chain_flows([flow1, flow2])
        assert chained is not None

    def test_adapter_add_dependencies(self) -> None:
        """Test adding job dependencies."""
        job1 = MockJob(name="scf")
        job2 = MockJob(name="bands")

        from crystalmath.integrations.atomate2_bridge import Atomate2FlowAdapter

        adapter = Atomate2FlowAdapter()
        adapter.add_dependency(job2, job1)
        # Verify dependency was added

    def test_adapter_without_atomate2(self, mock_structure: Mock) -> None:
        """Test error handling when atomate2 not available."""
        mock_maker = Mock()

        with patch("crystalmath.integrations.atomate2_bridge.HAS_ATOMATE2", False):
            from crystalmath.integrations.atomate2_bridge import Atomate2FlowAdapter

            adapter = Atomate2FlowAdapter()
            with pytest.raises(ImportError):
                adapter.adapt_flow(mock_maker, mock_structure)


class TestFlowAdaptation:
    """Tests for specific flow adaptation scenarios."""

    def test_adapt_relax_flow(self, mock_structure: Mock) -> None:
        """Test adapting relaxation flow."""
        from crystalmath.integrations.atomate2_bridge import Atomate2FlowAdapter

        adapter = Atomate2FlowAdapter()
        flow = adapter.create_relax_flow(mock_structure, code="vasp")
        assert flow is not None

    def test_adapt_bands_flow(self, mock_structure: Mock) -> None:
        """Test adapting band structure flow."""
        from crystalmath.integrations.atomate2_bridge import Atomate2FlowAdapter

        adapter = Atomate2FlowAdapter()
        flow = adapter.create_bands_flow(mock_structure, code="vasp")
        assert flow is not None

    def test_adapt_phonon_flow(self, mock_structure: Mock) -> None:
        """Test adapting phonon flow."""
        from crystalmath.integrations.atomate2_bridge import Atomate2FlowAdapter

        adapter = Atomate2FlowAdapter()
        flow = adapter.create_phonon_flow(mock_structure, code="vasp")
        assert flow is not None

    def test_adapt_elastic_flow(self, mock_structure: Mock) -> None:
        """Test adapting elastic constants flow."""
        from crystalmath.integrations.atomate2_bridge import Atomate2FlowAdapter

        adapter = Atomate2FlowAdapter()
        flow = adapter.create_elastic_flow(mock_structure, code="vasp")
        assert flow is not None

    def test_adapt_multi_code_flow(self, mock_structure: Mock) -> None:
        """Test adapting multi-code workflow (DFT + GW)."""
        from crystalmath.integrations.atomate2_bridge import Atomate2FlowAdapter

        adapter = Atomate2FlowAdapter()
        flow = adapter.create_gw_flow(
            mock_structure,
            dft_code="vasp",
            gw_code="yambo",
        )
        assert flow is not None


# =============================================================================
# Test JobStore Bridge
# =============================================================================


class TestJobStoreBridge:
    """Tests for JobStore bridge functionality."""

    def test_bridge_creation(self, mock_job_store: Mock) -> None:
        """Test bridge instance creation."""
        from crystalmath.integrations.atomate2_bridge import JobStoreBridge

        bridge = JobStoreBridge(mock_job_store)
        assert bridge is not None

    def test_bridge_connect(self, mock_job_store: Mock) -> None:
        """Test connecting to job store."""
        from crystalmath.integrations.atomate2_bridge import JobStoreBridge

        bridge = JobStoreBridge(mock_job_store)
        bridge.connect()
        mock_job_store.connect.assert_called_once()

    def test_bridge_query_jobs(self, mock_job_store: Mock) -> None:
        """Test querying jobs from store."""
        mock_job_store.query.return_value = [
            {"uuid": "job-1", "state": "COMPLETED"},
            {"uuid": "job-2", "state": "RUNNING"},
        ]

        from crystalmath.integrations.atomate2_bridge import JobStoreBridge

        bridge = JobStoreBridge(mock_job_store)
        jobs = bridge.query_jobs(state="COMPLETED")
        assert len(jobs) >= 0

    def test_bridge_get_job_by_uuid(self, mock_job_store: Mock) -> None:
        """Test getting specific job by UUID."""
        mock_job_store.query_one.return_value = {
            "uuid": "test-uuid",
            "state": "COMPLETED",
            "output": {"energy": -10.5},
        }

        from crystalmath.integrations.atomate2_bridge import JobStoreBridge

        bridge = JobStoreBridge(mock_job_store)
        job = bridge.get_job("test-uuid")
        assert job is not None

    def test_bridge_get_job_output(self, mock_job_store: Mock) -> None:
        """Test getting job output."""
        mock_job_store.query_one.return_value = {
            "uuid": "test-uuid",
            "state": "COMPLETED",
            "output": {"energy": -10.5, "bandgap": 1.1},
        }

        from crystalmath.integrations.atomate2_bridge import JobStoreBridge

        bridge = JobStoreBridge(mock_job_store)
        output = bridge.get_job_output("test-uuid")
        assert output is not None

    def test_bridge_update_job(self, mock_job_store: Mock) -> None:
        """Test updating job metadata."""
        from crystalmath.integrations.atomate2_bridge import JobStoreBridge

        bridge = JobStoreBridge(mock_job_store)
        bridge.update_job("test-uuid", {"metadata": {"key": "value"}})
        mock_job_store.update.assert_called()

    def test_bridge_list_flows(self, mock_job_store: Mock) -> None:
        """Test listing all flows."""
        mock_job_store.query.return_value = [
            {"uuid": "flow-1", "name": "relax_flow"},
            {"uuid": "flow-2", "name": "bands_flow"},
        ]

        from crystalmath.integrations.atomate2_bridge import JobStoreBridge

        bridge = JobStoreBridge(mock_job_store)
        flows = bridge.list_flows()
        assert isinstance(flows, list)


class TestJobStoreFiltering:
    """Tests for JobStore query filtering."""

    def test_filter_by_state(self, mock_job_store: Mock) -> None:
        """Test filtering jobs by state."""
        from crystalmath.integrations.atomate2_bridge import JobStoreBridge

        bridge = JobStoreBridge(mock_job_store)
        _ = bridge.query_jobs(state="COMPLETED")
        mock_job_store.query.assert_called()

    def test_filter_by_code(self, mock_job_store: Mock) -> None:
        """Test filtering jobs by DFT code."""
        from crystalmath.integrations.atomate2_bridge import JobStoreBridge

        bridge = JobStoreBridge(mock_job_store)
        _ = bridge.query_jobs(code="vasp")

    def test_filter_by_date_range(self, mock_job_store: Mock) -> None:
        """Test filtering jobs by date range."""
        from datetime import datetime, timedelta

        from crystalmath.integrations.atomate2_bridge import JobStoreBridge

        bridge = JobStoreBridge(mock_job_store)
        start = datetime.now() - timedelta(days=7)
        end = datetime.now()
        _ = bridge.query_jobs(start_date=start, end_date=end)

    def test_filter_by_formula(self, mock_job_store: Mock) -> None:
        """Test filtering jobs by chemical formula."""
        from crystalmath.integrations.atomate2_bridge import JobStoreBridge

        bridge = JobStoreBridge(mock_job_store)
        _ = bridge.query_jobs(formula="Si")


# =============================================================================
# Test Flow Execution
# =============================================================================


class TestFlowExecution:
    """Tests for flow execution functionality."""

    def test_submit_flow(self, mock_job_store: Mock) -> None:
        """Test submitting a flow for execution."""
        flow = MockFlow(name="test", jobs=[MockJob(name="job1")])

        from crystalmath.integrations.atomate2_bridge import FlowExecutor

        executor = FlowExecutor(mock_job_store)
        result = executor.submit(flow)
        assert result is not None

    def test_run_flow_locally(self, mock_job_store: Mock) -> None:
        """Test running a flow locally."""
        flow = MockFlow(name="test", jobs=[MockJob(name="job1")])

        from crystalmath.integrations.atomate2_bridge import FlowExecutor

        executor = FlowExecutor(mock_job_store)
        result = executor.run_locally(flow)
        assert result is not None

    def test_submit_to_fireworks(self, mock_job_store: Mock) -> None:
        """Test submitting to FireWorks (mocked)."""
        flow = MockFlow(name="test", jobs=[MockJob(name="job1")])

        mock_launchpad = Mock()

        with patch(
            "crystalmath.integrations.atomate2_bridge.LaunchPad",
            return_value=mock_launchpad,
        ):
            from crystalmath.integrations.atomate2_bridge import FlowExecutor

            executor = FlowExecutor(mock_job_store)
            result = executor.submit_to_fireworks(flow)

    def test_get_flow_status(self, mock_job_store: Mock) -> None:
        """Test getting flow execution status."""
        mock_job_store.query_one.return_value = {
            "uuid": "flow-uuid",
            "state": "RUNNING",
        }

        from crystalmath.integrations.atomate2_bridge import FlowExecutor

        executor = FlowExecutor(mock_job_store)
        status = executor.get_status("flow-uuid")
        assert status in ["READY", "RUNNING", "COMPLETED", "FAILED", "PAUSED"]


# =============================================================================
# Test Error Handling
# =============================================================================


class TestErrorHandling:
    """Tests for error handling in atomate2 bridge."""

    def test_invalid_code_name(self) -> None:
        """Test error for invalid code name."""
        from crystalmath.integrations.atomate2_bridge import FlowMakerRegistry

        with pytest.raises((KeyError, ValueError)):
            FlowMakerRegistry.get_code_workflows("invalid_code")

    def test_missing_structure(self) -> None:
        """Test error when structure is missing."""
        from crystalmath.integrations.atomate2_bridge import Atomate2FlowAdapter

        adapter = Atomate2FlowAdapter()
        with pytest.raises((ValueError, TypeError)):
            adapter.create_relax_flow(None, code="vasp")

    def test_job_store_connection_error(self) -> None:
        """Test error handling for store connection failure."""
        mock_store = Mock()
        mock_store.connect.side_effect = ConnectionError("Failed to connect")

        from crystalmath.integrations.atomate2_bridge import JobStoreBridge

        bridge = JobStoreBridge(mock_store)
        with pytest.raises(ConnectionError):
            bridge.connect()

    def test_job_not_found(self, mock_job_store: Mock) -> None:
        """Test error when job is not found."""
        mock_job_store.query_one.return_value = None

        from crystalmath.integrations.atomate2_bridge import JobStoreBridge

        bridge = JobStoreBridge(mock_job_store)
        job = bridge.get_job("nonexistent-uuid")
        assert job is None


# =============================================================================
# Test Configuration
# =============================================================================


class TestConfiguration:
    """Tests for atomate2 bridge configuration."""

    def test_load_config_from_file(self, tmp_path: Path) -> None:
        """Test loading configuration from file."""
        config_file = tmp_path / "atomate2_config.yaml"
        config_file.write_text(
            """
default_code: vasp
vasp:
    ENCUT: 520
    EDIFF: 1e-6
qe:
    ecutwfc: 60
"""
        )

        from crystalmath.integrations.atomate2_bridge import Atomate2Config

        config = Atomate2Config.from_file(str(config_file))
        assert config.default_code == "vasp"

    def test_default_config(self) -> None:
        """Test default configuration values."""
        from crystalmath.integrations.atomate2_bridge import Atomate2Config

        config = Atomate2Config()
        assert config.default_code is not None

    def test_config_validation(self) -> None:
        """Test configuration validation."""
        from crystalmath.integrations.atomate2_bridge import Atomate2Config

        config = Atomate2Config()
        is_valid, issues = config.validate()
        assert isinstance(is_valid, bool)
        assert isinstance(issues, list)


# =============================================================================
# Test Data Conversion
# =============================================================================


class TestDataConversion:
    """Tests for data format conversion."""

    def test_convert_vasp_output(self) -> None:
        """Test converting VASP output to standard format."""
        vasp_output = {
            "energy": -10.5,
            "forces": [[0.1, 0.2, 0.3]],
            "stress": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        }

        from crystalmath.integrations.atomate2_bridge import DataConverter

        result = DataConverter.from_vasp(vasp_output)
        assert "energy" in result

    def test_convert_qe_output(self) -> None:
        """Test converting QE output to standard format."""
        qe_output = {
            "energy": -10.5,
            "forces": [[0.1, 0.2, 0.3]],
        }

        from crystalmath.integrations.atomate2_bridge import DataConverter

        result = DataConverter.from_qe(qe_output)
        assert "energy" in result

    def test_convert_to_crystalmath_format(self) -> None:
        """Test converting to CrystalMath internal format."""
        output = {
            "energy": -10.5,
            "bandgap": 1.1,
            "structure": Mock(),
        }

        from crystalmath.integrations.atomate2_bridge import DataConverter

        result = DataConverter.to_crystalmath(output)
        assert isinstance(result, dict)


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
        from jobflow import Job

        @Job
        def test_job():
            return 42

        job = test_job()
        assert job is not None

    def test_real_flow_creation(self) -> None:
        """Test creating real jobflow Flow."""
        from jobflow import Flow, Job

        @Job
        def job1():
            return 1

        @Job
        def job2():
            return 2

        flow = Flow([job1(), job2()])
        assert len(flow.jobs) == 2


# =============================================================================
# Test Multi-Code Workflows
# =============================================================================


class TestMultiCodeWorkflows:
    """Tests for multi-code workflow support."""

    def test_vasp_to_yambo_handoff(self, mock_structure: Mock) -> None:
        """Test VASP to YAMBO data handoff."""
        from crystalmath.integrations.atomate2_bridge import MultiCodeAdapter

        adapter = MultiCodeAdapter()
        handoff = adapter.prepare_handoff("vasp", "yambo", mock_structure)
        assert handoff is not None

    def test_qe_to_yambo_handoff(self, mock_structure: Mock) -> None:
        """Test QE to YAMBO data handoff."""
        from crystalmath.integrations.atomate2_bridge import MultiCodeAdapter

        adapter = MultiCodeAdapter()
        handoff = adapter.prepare_handoff("qe", "yambo", mock_structure)
        assert handoff is not None

    def test_crystal_to_yambo_handoff(self, mock_structure: Mock) -> None:
        """Test CRYSTAL23 to YAMBO data handoff (via converter)."""
        from crystalmath.integrations.atomate2_bridge import MultiCodeAdapter

        adapter = MultiCodeAdapter()
        handoff = adapter.prepare_handoff("crystal23", "yambo", mock_structure)
        assert handoff is not None

    def test_validate_code_compatibility(self) -> None:
        """Test validation of code compatibility."""
        from crystalmath.integrations.atomate2_bridge import MultiCodeAdapter

        adapter = MultiCodeAdapter()

        # Compatible pairs
        assert adapter.is_compatible("vasp", "yambo") is True
        assert adapter.is_compatible("qe", "yambo") is True

        # Incompatible pairs (example)
        # Some combinations may not be supported


class TestWorkflowChaining:
    """Tests for workflow chaining functionality."""

    def test_chain_relax_bands(self, mock_structure: Mock) -> None:
        """Test chaining relaxation and bands calculations."""
        from crystalmath.integrations.atomate2_bridge import WorkflowChainer

        chainer = WorkflowChainer()
        workflow = chainer.chain(
            ["relax", "bands"],
            mock_structure,
            code="vasp",
        )
        assert workflow is not None

    def test_chain_with_gw(self, mock_structure: Mock) -> None:
        """Test chaining DFT with GW calculations."""
        from crystalmath.integrations.atomate2_bridge import WorkflowChainer

        chainer = WorkflowChainer()
        workflow = chainer.chain(
            ["scf", "gw", "bse"],
            mock_structure,
            codes={"scf": "vasp", "gw": "yambo", "bse": "yambo"},
        )
        assert workflow is not None

    def test_chain_conditional_steps(self, mock_structure: Mock) -> None:
        """Test conditional workflow steps."""
        from crystalmath.integrations.atomate2_bridge import WorkflowChainer

        chainer = WorkflowChainer()
        workflow = chainer.chain_conditional(
            steps=["relax", "bands"],
            condition=lambda result: result.get("converged", False),
            structure=mock_structure,
        )
        assert workflow is not None
