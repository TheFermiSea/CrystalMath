"""End-to-end integration tests for MVP vertical slice.

Tests the complete flow: HighThroughput.from_mp() -> atomate2 -> Results
All tests use mocks -- no real DFT deps needed.
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import Mock, MagicMock, patch


class TestBridgeSubmitAndRetrieve:
    """Test Atomate2Bridge submit -> complete_workflow -> get_result round-trip."""

    def test_submit_mock_path(self):
        """Submit via mock path returns success with workflow_id."""
        from crystalmath.integrations.atomate2_bridge import Atomate2Bridge
        from crystalmath.protocols import WorkflowType

        bridge = Atomate2Bridge()
        result = bridge.submit(WorkflowType.SCF, None, code="vasp")

        assert result.success is True
        assert result.workflow_id is not None
        assert len(result.workflow_id) > 0

    def test_complete_and_retrieve(self):
        """Complete workflow and retrieve results."""
        from crystalmath.integrations.atomate2_bridge import Atomate2Bridge
        from crystalmath.protocols import WorkflowType

        bridge = Atomate2Bridge()
        result = bridge.submit(WorkflowType.SCF, None, code="vasp")
        wf_id = result.workflow_id

        # Complete with outputs
        outputs = {
            "energy": -10.84,
            "band_gap": 1.17,
            "is_direct_gap": True,
            "fermi_energy": 5.23,
            "structure": {"formula": "Si2"},
        }
        assert bridge.complete_workflow(wf_id, outputs) is True

        # Verify status
        assert bridge.get_status(wf_id) == "completed"

        # Retrieve result
        final = bridge.get_result(wf_id)
        assert final.success is True
        assert final.outputs["energy"] == -10.84
        assert final.outputs["band_gap"] == 1.17

    def test_inject_result(self):
        """Inject individual result keys."""
        from crystalmath.integrations.atomate2_bridge import Atomate2Bridge
        from crystalmath.protocols import WorkflowType

        bridge = Atomate2Bridge()
        result = bridge.submit(WorkflowType.BANDS, None, code="vasp")
        wf_id = result.workflow_id

        assert bridge.inject_result(wf_id, "band_gap", 1.17) is True
        assert bridge.inject_result(wf_id, "is_direct_gap", False) is True

        # Complete and check
        bridge.complete_workflow(wf_id, bridge._active_flows[wf_id]["outputs"])
        final = bridge.get_result(wf_id)
        assert final.outputs["band_gap"] == 1.17

    def test_submit_status_tracking(self):
        """Status transitions: submitted -> completed."""
        from crystalmath.integrations.atomate2_bridge import Atomate2Bridge
        from crystalmath.protocols import WorkflowType

        bridge = Atomate2Bridge()
        result = bridge.submit(WorkflowType.SCF, None, code="vasp")
        wf_id = result.workflow_id

        assert bridge.get_status(wf_id) == "submitted"
        bridge.complete_workflow(wf_id, {"energy": -5.0})
        assert bridge.get_status(wf_id) == "completed"

    def test_cancel_workflow(self):
        """Cancel removes workflow from tracking."""
        from crystalmath.integrations.atomate2_bridge import Atomate2Bridge
        from crystalmath.protocols import WorkflowType

        bridge = Atomate2Bridge()
        result = bridge.submit(WorkflowType.SCF, None, code="vasp")
        wf_id = result.workflow_id

        assert bridge.cancel(wf_id) is True
        assert bridge.get_status(wf_id) == "failed"

    def test_unknown_workflow_returns_error(self):
        """Unknown workflow_id returns error result."""
        from crystalmath.integrations.atomate2_bridge import Atomate2Bridge

        bridge = Atomate2Bridge()
        result = bridge.get_result("nonexistent-id")
        assert result.success is False
        assert len(result.errors) > 0


class TestSQLiteJobStore:
    """Test SQLiteJobStore connect -> update -> query round-trip."""

    def test_connect_creates_table(self, tmp_path):
        """Connect creates the jobflow_jobs table."""
        from crystalmath.integrations.jobflow_store import SQLiteJobStore

        db_path = tmp_path / "test.db"
        store = SQLiteJobStore(db_path)
        store.connect()
        assert store._connected is True
        store.close()

    def test_update_and_query(self, tmp_path):
        """Insert docs and query them back."""
        from crystalmath.integrations.jobflow_store import SQLiteJobStore

        db_path = tmp_path / "test.db"
        store = SQLiteJobStore(db_path)
        store.connect()

        store.update([
            {"uuid": "j1", "name": "relax_Si", "state": "completed",
             "output": {"energy": -10.84}},
            {"uuid": "j2", "name": "bands_Si", "state": "running"},
        ])

        # Query all
        docs = list(store.query())
        assert len(docs) == 2

        # Query by state
        completed = list(store.query(criteria={"state": "completed"}))
        assert len(completed) == 1
        assert completed[0]["uuid"] == "j1"
        assert completed[0]["output"]["energy"] == -10.84

        store.close()

    def test_query_with_regex(self, tmp_path):
        """Query with $regex criteria."""
        from crystalmath.integrations.jobflow_store import SQLiteJobStore

        db_path = tmp_path / "test.db"
        store = SQLiteJobStore(db_path)
        store.connect()

        store.update([
            {"uuid": "j1", "name": "relax_Si"},
            {"uuid": "j2", "name": "bands_MoS2"},
            {"uuid": "j3", "name": "relax_MoS2"},
        ])

        results = list(store.query(criteria={"name": {"$regex": "relax"}}))
        assert len(results) == 2

        store.close()

    def test_distinct(self, tmp_path):
        """Test distinct values retrieval."""
        from crystalmath.integrations.jobflow_store import SQLiteJobStore

        db_path = tmp_path / "test.db"
        store = SQLiteJobStore(db_path)
        store.connect()

        store.update([
            {"uuid": "j1", "state": "completed"},
            {"uuid": "j2", "state": "running"},
            {"uuid": "j3", "state": "completed"},
        ])

        states = store.distinct("state")
        assert set(states) == {"completed", "running"}

        store.close()

    def test_count(self, tmp_path):
        """Test document counting."""
        from crystalmath.integrations.jobflow_store import SQLiteJobStore

        db_path = tmp_path / "test.db"
        store = SQLiteJobStore(db_path)
        store.connect()

        store.update([
            {"uuid": "j1", "state": "completed"},
            {"uuid": "j2", "state": "running"},
        ])

        assert store.count() == 2
        assert store.count(criteria={"state": "completed"}) == 1

        store.close()


class TestHighThroughputAPI:
    """Test HighThroughput validate, resolve deps, and from_mp with mocks."""

    def test_validate_valid_properties(self):
        """Validate accepts known properties."""
        from crystalmath.high_level.api import HighThroughput

        is_valid, issues = HighThroughput._validate_properties(["scf", "bands"])
        assert is_valid is True
        assert len(issues) == 0

    def test_validate_invalid_properties(self):
        """Validate rejects unknown properties."""
        from crystalmath.high_level.api import HighThroughput

        is_valid, issues = HighThroughput._validate_properties(["nonexistent"])
        assert is_valid is False

    def test_determine_workflow_steps_basic(self):
        """Resolve basic property to steps."""
        from crystalmath.high_level.api import HighThroughput
        from crystalmath.protocols import WorkflowType

        steps = HighThroughput._determine_workflow_steps(["scf"], None)
        assert len(steps) == 1
        assert steps[0][0] == "scf"
        assert steps[0][1] == WorkflowType.SCF

    def test_determine_workflow_steps_with_deps(self):
        """bands auto-adds scf dependency."""
        from crystalmath.high_level.api import HighThroughput
        from crystalmath.protocols import WorkflowType

        steps = HighThroughput._determine_workflow_steps(["bands"], None)
        step_names = [s[0] for s in steps]
        assert "scf" in step_names
        assert "bands" in step_names
        # scf must come before bands
        assert step_names.index("scf") < step_names.index("bands")

    def test_determine_workflow_steps_with_code_override(self):
        """Code override applies correctly."""
        from crystalmath.high_level.api import HighThroughput

        steps = HighThroughput._determine_workflow_steps(
            ["scf", "gw"], {"dft": "quantum_espresso", "gw": "berkeleygw"}
        )
        step_dict = {s[0]: s[2] for s in steps}
        assert step_dict["scf"] == "quantum_espresso"
        assert step_dict["gw"] == "berkeleygw"

    def test_determine_workflow_steps_deep_deps(self):
        """BSE chain: bse -> gw -> scf."""
        from crystalmath.high_level.api import HighThroughput

        steps = HighThroughput._determine_workflow_steps(["bse"], None)
        step_names = [s[0] for s in steps]
        assert "scf" in step_names
        assert "gw" in step_names
        assert "bse" in step_names
        assert step_names.index("scf") < step_names.index("gw")
        assert step_names.index("gw") < step_names.index("bse")

    def test_run_standard_analysis_with_mock_bridge(self):
        """run_standard_analysis works end-to-end with mock bridge."""
        from crystalmath.high_level.api import HighThroughput

        # Uses mock bridge path (no atomate2)
        results = HighThroughput.run_standard_analysis(
            structure=None,
            properties=["scf"],
        )
        # Should return AnalysisResults (not raise NotImplementedError)
        assert results is not None

    @patch("crystalmath.high_level.api.HighThroughput._load_structure_from_mp")
    def test_from_mp_with_mock(self, mock_load):
        """from_mp delegates to run_standard_analysis."""
        from crystalmath.high_level.api import HighThroughput

        mock_load.return_value = None  # Mock structure

        results = HighThroughput.from_mp("mp-149", properties=["scf"])
        assert results is not None
        mock_load.assert_called_once_with("mp-149")


class TestAnalysisResultsExport:
    """Test AnalysisResults to_dict, to_json, to_json(file)."""

    def test_to_dict(self):
        """to_dict returns nested dict."""
        from crystalmath.high_level.results import AnalysisResults

        results = AnalysisResults(
            formula="Si",
            band_gap_ev=1.17,
            is_direct_gap=False,
            fermi_energy_ev=5.23,
        )
        d = results.to_dict()

        assert d["formula"] == "Si"
        assert d["electronic"]["band_gap_ev"] == 1.17
        assert d["electronic"]["is_direct_gap"] is False

    def test_to_json_string(self):
        """to_json returns valid JSON string."""
        from crystalmath.high_level.results import AnalysisResults

        results = AnalysisResults(formula="Si", band_gap_ev=1.17)
        json_str = results.to_json()

        data = json.loads(json_str)
        assert data["formula"] == "Si"

    def test_to_json_file(self, tmp_path):
        """to_json writes to file when path given."""
        from crystalmath.high_level.results import AnalysisResults

        results = AnalysisResults(formula="Si", band_gap_ev=1.17)
        output_file = tmp_path / "silicon.json"
        results.to_json(str(output_file))

        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert data["formula"] == "Si"
        assert data["electronic"]["band_gap_ev"] == 1.17


class TestWorkflowBuilder:
    """Test WorkflowBuilder validate, build, step dependencies."""

    def test_validate_no_structure(self):
        """Validate catches missing structure."""
        from crystalmath.high_level.builder import WorkflowBuilder

        builder = WorkflowBuilder()
        builder.scf()
        is_valid, issues = builder.validate()
        assert is_valid is False
        assert any("structure" in i.lower() or "No structure" in i for i in issues)

    def test_validate_no_steps(self):
        """Validate catches missing steps."""
        from crystalmath.high_level.builder import WorkflowBuilder

        builder = WorkflowBuilder()
        builder.from_file("test.cif")
        is_valid, issues = builder.validate()
        assert is_valid is False
        assert any("step" in i.lower() for i in issues)

    def test_validate_valid(self):
        """Valid builder passes validation."""
        from crystalmath.high_level.builder import WorkflowBuilder

        builder = WorkflowBuilder().from_file("test.cif").scf()
        is_valid, issues = builder.validate()
        assert is_valid is True

    def test_build_returns_workflow(self):
        """Build returns Workflow instance."""
        from crystalmath.high_level.builder import WorkflowBuilder, Workflow

        builder = WorkflowBuilder().from_file("test.cif").scf()
        workflow = builder.build()
        assert isinstance(workflow, Workflow)
        assert len(workflow.steps) == 1

    def test_build_with_multiple_steps(self):
        """Build with chained steps preserves order."""
        from crystalmath.high_level.builder import WorkflowBuilder, Workflow

        builder = (
            WorkflowBuilder()
            .from_file("test.cif")
            .relax()
            .then_bands()
            .then_dos()
        )
        workflow = builder.build()
        assert len(workflow.steps) == 3
        assert workflow.steps[0].name == "relax"
        assert workflow.steps[1].name == "bands"
        assert workflow.steps[2].name == "dos"

    def test_build_invalid_raises(self):
        """Build with invalid config raises WorkflowValidationError."""
        from crystalmath.high_level.builder import WorkflowBuilder

        builder = WorkflowBuilder()  # No structure, no steps
        with pytest.raises(Exception):  # WorkflowValidationError
            builder.build()


class TestGetRunner:
    """Test get_runner factory wiring."""

    def test_get_runner_jobflow(self):
        """get_runner('jobflow') returns Atomate2Bridge."""
        from crystalmath.protocols import get_runner

        runner = get_runner("jobflow")
        assert runner.name == "atomate2"

    def test_get_runner_unknown_raises(self):
        """get_runner with unknown type raises NotImplementedError."""
        from crystalmath.protocols import get_runner

        with pytest.raises(NotImplementedError):
            get_runner("aiida")
