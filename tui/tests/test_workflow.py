"""
Unit tests for Workflow DAG system.

Tests cover:
- DAG construction and validation
- Cycle detection
- Topological sort
- Parameter propagation
- Execution order and parallelism
- Node types and branching
- Serialization/deserialization
"""

import pytest
import asyncio
from pathlib import Path
import json
import tempfile

from src.core.workflow import (
    Workflow,
    WorkflowNode,
    NodeType,
    NodeStatus,
    WorkflowStatus,
    WorkflowEdge
)


class TestWorkflowConstruction:
    """Test basic workflow construction."""

    def test_create_empty_workflow(self):
        """Test creating an empty workflow."""
        wf = Workflow("test_wf", "Test Workflow", "A test workflow")

        assert wf.workflow_id == "test_wf"
        assert wf.name == "Test Workflow"
        assert wf.description == "A test workflow"
        assert wf.status == WorkflowStatus.CREATED
        assert len(wf.nodes) == 0
        assert len(wf.edges) == 0

    def test_add_calculation_node(self):
        """Test adding a calculation node."""
        wf = Workflow("test", "Test")

        node = wf.add_node("optimization", {"basis": "sto-3g"}, node_id="opt")

        assert node.node_id == "opt"
        assert node.node_type == NodeType.CALCULATION
        assert node.job_template == "optimization"
        assert node.parameters == {"basis": "sto-3g"}
        assert node.status == NodeStatus.PENDING
        assert "opt" in wf.nodes

    def test_add_node_auto_id(self):
        """Test automatic node ID generation."""
        wf = Workflow("test", "Test")

        node1 = wf.add_node("opt", {})
        node2 = wf.add_node("opt", {})

        assert node1.node_id == "opt_0"
        assert node2.node_id == "opt_1"

    def test_add_duplicate_node_id_fails(self):
        """Test that duplicate node IDs raise an error."""
        wf = Workflow("test", "Test")

        wf.add_node("opt", {}, node_id="node1")

        with pytest.raises(ValueError, match="already exists"):
            wf.add_node("freq", {}, node_id="node1")

    def test_add_data_transfer_node(self):
        """Test adding a data transfer node."""
        wf = Workflow("test", "Test")
        wf.add_node("opt", {}, node_id="opt")

        transfer = wf.add_data_transfer_node(
            "transfer_f9",
            source_node="opt",
            source_files=["*.f9"],
            target_node="freq"
        )

        assert transfer.node_type == NodeType.DATA_TRANSFER
        assert transfer.source_node == "opt"
        assert transfer.source_files == ["*.f9"]
        assert "opt" in transfer.dependencies

    def test_add_condition_node(self):
        """Test adding a conditional branching node."""
        wf = Workflow("test", "Test")
        wf.add_node("opt", {}, node_id="opt")

        condition = wf.add_condition_node(
            "check_converged",
            condition_expr="opt['converged'] == True",
            true_branch=["freq"],
            false_branch=["restart_opt"],
            dependencies=["opt"]
        )

        assert condition.node_type == NodeType.CONDITION
        assert condition.condition_expr == "opt['converged'] == True"
        assert condition.true_branch == ["freq"]
        assert condition.false_branch == ["restart_opt"]

    def test_add_aggregation_node(self):
        """Test adding an aggregation node."""
        wf = Workflow("test", "Test")
        wf.add_node("calc1", {}, node_id="calc1")
        wf.add_node("calc2", {}, node_id="calc2")

        agg = wf.add_aggregation_node(
            "average_energy",
            aggregation_func="mean",
            dependencies=["calc1", "calc2"]
        )

        assert agg.node_type == NodeType.AGGREGATION
        assert agg.aggregation_func == "mean"
        assert agg.dependencies == ["calc1", "calc2"]

    def test_add_aggregation_invalid_func_fails(self):
        """Test that invalid aggregation function raises error."""
        wf = Workflow("test", "Test")

        with pytest.raises(ValueError, match="Invalid aggregation function"):
            wf.add_aggregation_node("agg", "invalid_func", ["node1"])


class TestWorkflowDependencies:
    """Test dependency management."""

    def test_add_simple_dependency(self):
        """Test adding a simple dependency."""
        wf = Workflow("test", "Test")
        wf.add_node("opt", {}, node_id="opt")
        wf.add_node("freq", {}, node_id="freq")

        wf.add_dependency("opt", "freq")

        assert len(wf.edges) == 1
        assert wf.edges[0].from_node == "opt"
        assert wf.edges[0].to_node == "freq"
        assert "opt" in wf.nodes["freq"].dependencies

    def test_add_dependency_nonexistent_source_fails(self):
        """Test that dependency with nonexistent source fails."""
        wf = Workflow("test", "Test")
        wf.add_node("freq", {}, node_id="freq")

        with pytest.raises(ValueError, match="does not exist"):
            wf.add_dependency("nonexistent", "freq")

    def test_add_dependency_nonexistent_target_fails(self):
        """Test that dependency with nonexistent target fails."""
        wf = Workflow("test", "Test")
        wf.add_node("opt", {}, node_id="opt")

        with pytest.raises(ValueError, match="does not exist"):
            wf.add_dependency("opt", "nonexistent")

    def test_add_conditional_dependency(self):
        """Test adding a conditional dependency."""
        wf = Workflow("test", "Test")
        wf.add_node("opt", {}, node_id="opt")
        wf.add_node("freq", {}, node_id="freq")

        wf.add_dependency("opt", "freq", condition="converged == True")

        assert wf.edges[0].condition == "converged == True"

    def test_multiple_dependencies(self):
        """Test node with multiple dependencies."""
        wf = Workflow("test", "Test")
        wf.add_node("opt", {}, node_id="opt")
        wf.add_node("dos", {}, node_id="dos")
        wf.add_node("band", {}, node_id="band")

        wf.add_dependency("opt", "dos")
        wf.add_dependency("opt", "band")

        assert len(wf.nodes["dos"].dependencies) == 1
        assert len(wf.nodes["band"].dependencies) == 1
        assert "opt" in wf.nodes["dos"].dependencies
        assert "opt" in wf.nodes["band"].dependencies


class TestWorkflowValidation:
    """Test workflow validation."""

    def test_validate_simple_workflow(self):
        """Test validation of a simple valid workflow."""
        wf = Workflow("test", "Test")
        wf.add_node("opt", {}, node_id="opt")
        wf.add_node("freq", {}, node_id="freq")
        wf.add_dependency("opt", "freq")

        errors = wf.validate()

        assert len(errors) == 0
        assert wf.status == WorkflowStatus.VALID

    def test_detect_simple_cycle(self):
        """Test detection of a simple cycle."""
        wf = Workflow("test", "Test")
        wf.add_node("a", {}, node_id="a")
        wf.add_node("b", {}, node_id="b")
        wf.add_dependency("a", "b")
        wf.add_dependency("b", "a")

        errors = wf.validate()

        assert len(errors) > 0
        assert any("cycle" in err.lower() for err in errors)
        assert wf.status == WorkflowStatus.INVALID

    def test_detect_complex_cycle(self):
        """Test detection of a complex cycle."""
        wf = Workflow("test", "Test")
        wf.add_node("a", {}, node_id="a")
        wf.add_node("b", {}, node_id="b")
        wf.add_node("c", {}, node_id="c")
        wf.add_dependency("a", "b")
        wf.add_dependency("b", "c")
        wf.add_dependency("c", "a")

        errors = wf.validate()

        assert len(errors) > 0
        assert any("cycle" in err.lower() for err in errors)

    def test_detect_missing_dependency(self):
        """Test detection of missing dependency reference."""
        wf = Workflow("test", "Test")
        node = wf.add_node("freq", {}, node_id="freq")
        node.dependencies.append("nonexistent")

        errors = wf.validate()

        assert len(errors) > 0
        assert any("missing dependency" in err.lower() for err in errors)

    def test_detect_orphaned_nodes(self):
        """Test detection of orphaned nodes."""
        wf = Workflow("test", "Test")
        wf.add_node("a", {}, node_id="a")
        wf.add_node("b", {}, node_id="b")
        wf.add_node("orphan", {}, node_id="orphan")
        wf.add_dependency("a", "b")

        errors = wf.validate()

        assert len(errors) > 0
        assert any("orphaned" in err.lower() for err in errors)
        assert "orphan" in errors[0]

    def test_single_node_no_orphan_error(self):
        """Test that single node workflow doesn't report orphan."""
        wf = Workflow("test", "Test")
        wf.add_node("single", {}, node_id="single")

        errors = wf.validate()

        assert len(errors) == 0

    def test_validate_parameter_template_reference(self):
        """Test validation of parameter template references."""
        wf = Workflow("test", "Test")
        wf.add_node("opt", {}, node_id="opt")
        wf.add_node("freq", {"guess": "{{ opt.f9 }}"}, node_id="freq")
        wf.add_dependency("opt", "freq")

        errors = wf.validate()

        assert len(errors) == 0

    def test_validate_invalid_parameter_template_node(self):
        """Test validation catches invalid node reference in template."""
        wf = Workflow("test", "Test")
        wf.add_node("freq", {"guess": "{{ nonexistent.f9 }}"}, node_id="freq")

        errors = wf.validate()

        assert len(errors) > 0
        assert any("non-existent node" in err for err in errors)

    def test_validate_parameter_template_no_dependency(self):
        """Test validation catches template reference without dependency."""
        wf = Workflow("test", "Test")
        wf.add_node("opt", {}, node_id="opt")
        wf.add_node("freq", {"guess": "{{ opt.f9 }}"}, node_id="freq")
        # Missing: wf.add_dependency("opt", "freq")

        errors = wf.validate()

        assert len(errors) > 0
        assert any("no dependency" in err for err in errors)

    def test_validate_condition_node(self):
        """Test validation of condition nodes."""
        wf = Workflow("test", "Test")
        wf.add_node("opt", {}, node_id="opt")
        wf.add_node("freq", {}, node_id="freq")
        wf.add_condition_node(
            "check",
            condition_expr="opt['converged']",
            true_branch=["freq"],
            false_branch=[],
            dependencies=["opt"]
        )
        wf.add_dependency("opt", "check")
        wf.add_dependency("check", "freq")

        errors = wf.validate()

        assert len(errors) == 0

    def test_validate_condition_node_no_expression(self):
        """Test validation catches condition node without expression."""
        wf = Workflow("test", "Test")
        node = wf.add_condition_node(
            "check",
            condition_expr="",
            true_branch=["freq"],
            false_branch=[],
            dependencies=[]
        )
        node.condition_expr = None  # Force invalid state

        errors = wf.validate()

        assert len(errors) > 0
        assert any("no condition expression" in err for err in errors)

    def test_validate_condition_node_no_branches(self):
        """Test validation catches condition node without branches."""
        wf = Workflow("test", "Test")
        wf.add_condition_node(
            "check",
            condition_expr="True",
            true_branch=[],
            false_branch=[],
            dependencies=[]
        )

        errors = wf.validate()

        assert len(errors) > 0
        assert any("no branches" in err for err in errors)

    def test_validate_data_transfer_node(self):
        """Test validation of data transfer nodes."""
        wf = Workflow("test", "Test")
        wf.add_node("opt", {}, node_id="opt")
        wf.add_node("freq", {}, node_id="freq")
        # Create data transfer node (adds opt to dependencies internally)
        transfer = wf.add_data_transfer_node(
            "transfer",
            source_node="opt",
            source_files=["*.f9"],
            target_node="freq"
        )
        # Must manually add edges for the dependency relationships
        wf.add_dependency("opt", "transfer")  # opt->transfer edge
        wf.add_dependency("transfer", "freq")  # transfer->freq edge

        errors = wf.validate()

        # Should pass - opt->transfer->freq is a complete path
        assert len(errors) == 0

    def test_validate_data_transfer_invalid_source(self):
        """Test validation catches invalid source in data transfer."""
        wf = Workflow("test", "Test")
        node = wf.add_data_transfer_node(
            "transfer",
            source_node="nonexistent",
            source_files=["*.f9"],
            target_node="freq"
        )

        errors = wf.validate()

        assert len(errors) > 0
        assert any("invalid source" in err for err in errors)

    def test_validate_data_transfer_no_files(self):
        """Test validation catches data transfer with no files."""
        wf = Workflow("test", "Test")
        wf.add_node("opt", {}, node_id="opt")
        node = wf.add_data_transfer_node(
            "transfer",
            source_node="opt",
            source_files=[],
            target_node="freq"
        )

        errors = wf.validate()

        assert len(errors) > 0
        assert any("no source files" in err for err in errors)


class TestTopologicalSort:
    """Test topological sorting."""

    def test_topological_sort_linear(self):
        """Test topological sort on linear workflow."""
        wf = Workflow("test", "Test")
        wf.add_node("a", {}, node_id="a")
        wf.add_node("b", {}, node_id="b")
        wf.add_node("c", {}, node_id="c")
        wf.add_dependency("a", "b")
        wf.add_dependency("b", "c")

        order = wf._topological_sort()

        assert order == ["a", "b", "c"]

    def test_topological_sort_parallel_branches(self):
        """Test topological sort with parallel branches."""
        wf = Workflow("test", "Test")
        wf.add_node("opt", {}, node_id="opt")
        wf.add_node("dos", {}, node_id="dos")
        wf.add_node("band", {}, node_id="band")
        wf.add_dependency("opt", "dos")
        wf.add_dependency("opt", "band")

        order = wf._topological_sort()

        assert order[0] == "opt"
        assert set(order[1:]) == {"dos", "band"}

    def test_topological_sort_diamond(self):
        """Test topological sort on diamond-shaped DAG."""
        wf = Workflow("test", "Test")
        wf.add_node("a", {}, node_id="a")
        wf.add_node("b", {}, node_id="b")
        wf.add_node("c", {}, node_id="c")
        wf.add_node("d", {}, node_id="d")
        wf.add_dependency("a", "b")
        wf.add_dependency("a", "c")
        wf.add_dependency("b", "d")
        wf.add_dependency("c", "d")

        order = wf._topological_sort()

        assert order[0] == "a"
        assert order[-1] == "d"
        assert set(order[1:3]) == {"b", "c"}

    def test_topological_sort_with_cycle_raises(self):
        """Test topological sort raises error on cycle."""
        wf = Workflow("test", "Test")
        wf.add_node("a", {}, node_id="a")
        wf.add_node("b", {}, node_id="b")
        wf.add_dependency("a", "b")
        wf.add_dependency("b", "a")

        with pytest.raises(ValueError, match="cycle"):
            wf._topological_sort()


class TestReadyNodes:
    """Test getting ready nodes."""

    def test_get_ready_nodes_initial(self):
        """Test getting ready nodes at start."""
        wf = Workflow("test", "Test")
        wf.add_node("a", {}, node_id="a")
        wf.add_node("b", {}, node_id="b")
        wf.add_dependency("a", "b")

        ready = wf.get_ready_nodes()

        assert len(ready) == 1
        assert ready[0].node_id == "a"

    def test_get_ready_nodes_after_completion(self):
        """Test getting ready nodes after completing a node."""
        wf = Workflow("test", "Test")
        wf.add_node("a", {}, node_id="a")
        wf.add_node("b", {}, node_id="b")
        wf.add_dependency("a", "b")

        # Mark 'a' as completed
        wf.nodes["a"].status = NodeStatus.COMPLETED
        wf._completed_nodes.add("a")

        ready = wf.get_ready_nodes()

        assert len(ready) == 1
        assert ready[0].node_id == "b"

    def test_get_ready_nodes_parallel(self):
        """Test getting multiple ready nodes in parallel."""
        wf = Workflow("test", "Test")
        wf.add_node("opt", {}, node_id="opt")
        wf.add_node("dos", {}, node_id="dos")
        wf.add_node("band", {}, node_id="band")
        wf.add_dependency("opt", "dos")
        wf.add_dependency("opt", "band")

        # Mark 'opt' as completed
        wf.nodes["opt"].status = NodeStatus.COMPLETED
        wf._completed_nodes.add("opt")

        ready = wf.get_ready_nodes()

        assert len(ready) == 2
        assert {n.node_id for n in ready} == {"dos", "band"}

    def test_get_ready_nodes_excludes_running(self):
        """Test that running nodes are not marked as ready."""
        wf = Workflow("test", "Test")
        wf.add_node("a", {}, node_id="a")

        wf._running_nodes.add("a")

        ready = wf.get_ready_nodes()

        assert len(ready) == 0


class TestParameterPropagation:
    """Test parameter propagation and template resolution."""

    def test_resolve_simple_parameter(self):
        """Test resolving a simple parameter template."""
        wf = Workflow("test", "Test")
        opt = wf.add_node("opt", {}, node_id="opt")
        freq = wf.add_node("freq", {"guess": "{{ opt.f9 }}"}, node_id="freq")
        wf.add_dependency("opt", "freq")

        # Set result data
        opt.result_data = {"f9": "/path/to/opt.f9"}

        resolved = wf._resolve_parameters(freq)

        assert resolved["guess"] == "/path/to/opt.f9"

    def test_resolve_multiple_parameters(self):
        """Test resolving multiple parameter templates."""
        wf = Workflow("test", "Test")
        opt = wf.add_node("opt", {}, node_id="opt")
        freq = wf.add_node(
            "freq",
            {
                "guess": "{{ opt.f9 }}",
                "energy": "{{ opt.energy }}"
            },
            node_id="freq"
        )
        wf.add_dependency("opt", "freq")

        opt.result_data = {"f9": "/path/to/opt.f9", "energy": "-123.456"}

        resolved = wf._resolve_parameters(freq)

        assert resolved["guess"] == "/path/to/opt.f9"
        assert resolved["energy"] == "-123.456"

    def test_resolve_mixed_parameters(self):
        """Test resolving mix of template and literal parameters."""
        wf = Workflow("test", "Test")
        opt = wf.add_node("opt", {}, node_id="opt")
        freq = wf.add_node(
            "freq",
            {
                "guess": "{{ opt.f9 }}",
                "basis": "sto-3g",
                "nprocs": 8
            },
            node_id="freq"
        )
        wf.add_dependency("opt", "freq")

        opt.result_data = {"f9": "/path/to/opt.f9"}

        resolved = wf._resolve_parameters(freq)

        assert resolved["guess"] == "/path/to/opt.f9"
        assert resolved["basis"] == "sto-3g"
        assert resolved["nprocs"] == 8

    def test_resolve_missing_field(self):
        """Test that missing fields remain as templates."""
        wf = Workflow("test", "Test")
        opt = wf.add_node("opt", {}, node_id="opt")
        freq = wf.add_node("freq", {"guess": "{{ opt.missing }}"}, node_id="freq")
        wf.add_dependency("opt", "freq")

        opt.result_data = {"f9": "/path/to/opt.f9"}

        resolved = wf._resolve_parameters(freq)

        # Should remain as template
        assert resolved["guess"] == "{{ opt.missing }}"


class TestWorkflowExecution:
    """Test workflow execution."""

    @pytest.mark.asyncio
    async def test_execute_simple_workflow(self):
        """Test executing a simple two-node workflow."""
        wf = Workflow("test", "Test")
        wf.add_node("opt", {}, node_id="opt")
        wf.add_node("freq", {}, node_id="freq")
        wf.add_dependency("opt", "freq")

        await wf.execute()

        assert wf.status == WorkflowStatus.COMPLETED
        assert wf.nodes["opt"].status == NodeStatus.COMPLETED
        assert wf.nodes["freq"].status == NodeStatus.COMPLETED
        assert len(wf.execution_order) == 2

    @pytest.mark.asyncio
    async def test_execute_validates_first(self):
        """Test that execution validates workflow first."""
        wf = Workflow("test", "Test")
        wf.add_node("a", {}, node_id="a")
        wf.add_node("b", {}, node_id="b")
        wf.add_dependency("a", "b")
        wf.add_dependency("b", "a")  # Cycle

        with pytest.raises(ValueError, match="validation failed"):
            await wf.execute()

    @pytest.mark.asyncio
    async def test_execute_parallel_nodes(self):
        """Test executing parallel nodes."""
        wf = Workflow("test", "Test")
        wf.add_node("opt", {}, node_id="opt")
        wf.add_node("dos", {}, node_id="dos")
        wf.add_node("band", {}, node_id="band")
        wf.add_dependency("opt", "dos")
        wf.add_dependency("opt", "band")

        await wf.execute()

        assert wf.status == WorkflowStatus.COMPLETED
        assert wf.nodes["opt"].status == NodeStatus.COMPLETED
        assert wf.nodes["dos"].status == NodeStatus.COMPLETED
        assert wf.nodes["band"].status == NodeStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_execute_respects_dependencies(self):
        """Test that execution respects dependencies."""
        wf = Workflow("test", "Test")
        wf.add_node("a", {}, node_id="a")
        wf.add_node("b", {}, node_id="b")
        wf.add_node("c", {}, node_id="c")
        wf.add_dependency("a", "b")
        wf.add_dependency("b", "c")

        await wf.execute()

        # Check execution order
        assert wf.execution_order == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_execute_aggregation_node(self):
        """Test executing an aggregation node."""
        wf = Workflow("test", "Test")
        wf.add_node("calc1", {}, node_id="calc1")
        wf.add_node("calc2", {}, node_id="calc2")
        agg = wf.add_aggregation_node(
            "avg",
            aggregation_func="mean",
            dependencies=["calc1", "calc2"]
        )
        wf.add_dependency("calc1", "avg")
        wf.add_dependency("calc2", "avg")

        await wf.execute()

        assert wf.status == WorkflowStatus.COMPLETED
        assert agg.result_data is not None
        assert "aggregated_value" in agg.result_data
        assert agg.result_data["count"] == 2


class TestWorkflowSerialization:
    """Test workflow serialization and deserialization."""

    def test_workflow_to_dict(self):
        """Test converting workflow to dictionary."""
        wf = Workflow("test_wf", "Test Workflow", "Description")
        wf.add_node("opt", {"basis": "sto-3g"}, node_id="opt")
        wf.add_node("freq", {}, node_id="freq")
        wf.add_dependency("opt", "freq")

        data = wf.to_dict()

        assert data["workflow_id"] == "test_wf"
        assert data["name"] == "Test Workflow"
        assert data["description"] == "Description"
        assert "opt" in data["nodes"]
        assert "freq" in data["nodes"]
        assert len(data["edges"]) == 1

    def test_workflow_from_dict(self):
        """Test creating workflow from dictionary."""
        wf = Workflow("test_wf", "Test Workflow")
        wf.add_node("opt", {"basis": "sto-3g"}, node_id="opt")
        wf.add_node("freq", {}, node_id="freq")
        wf.add_dependency("opt", "freq")

        data = wf.to_dict()
        restored = Workflow.from_dict(data)

        assert restored.workflow_id == wf.workflow_id
        assert restored.name == wf.name
        assert len(restored.nodes) == len(wf.nodes)
        assert len(restored.edges) == len(wf.edges)

    def test_workflow_json_roundtrip(self):
        """Test JSON serialization round-trip."""
        wf = Workflow("test_wf", "Test Workflow")
        wf.add_node("opt", {"basis": "sto-3g"}, node_id="opt")
        wf.add_node("freq", {}, node_id="freq")
        wf.add_dependency("opt", "freq")

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            filepath = Path(f.name)

        try:
            wf.to_json(filepath)
            restored = Workflow.from_json(filepath)

            assert restored.workflow_id == wf.workflow_id
            assert restored.name == wf.name
            assert len(restored.nodes) == len(wf.nodes)
            assert len(restored.edges) == len(wf.edges)

        finally:
            filepath.unlink()


class TestWorkflowVisualization:
    """Test workflow visualization methods."""

    def test_to_graphviz(self):
        """Test GraphViz DOT format generation."""
        wf = Workflow("test", "Test")
        wf.add_node("opt", {}, node_id="opt")
        wf.add_node("freq", {}, node_id="freq")
        wf.add_dependency("opt", "freq")

        dot = wf.to_graphviz()

        assert "digraph Workflow" in dot
        assert '"opt"' in dot
        assert '"freq"' in dot
        assert '"opt" -> "freq"' in dot

    def test_to_ascii(self):
        """Test ASCII art generation."""
        wf = Workflow("test", "Test Workflow")
        wf.add_node("opt", {}, node_id="opt")
        wf.add_node("freq", {}, node_id="freq")
        wf.add_dependency("opt", "freq")

        ascii_art = wf.to_ascii()

        assert "Test Workflow" in ascii_art
        assert "opt" in ascii_art
        assert "freq" in ascii_art

    def test_get_progress(self):
        """Test progress tracking."""
        wf = Workflow("test", "Test")
        wf.add_node("opt", {}, node_id="opt")
        wf.add_node("freq", {}, node_id="freq")
        wf.add_node("dos", {}, node_id="dos")

        wf.nodes["opt"].status = NodeStatus.COMPLETED
        wf.nodes["freq"].status = NodeStatus.RUNNING
        wf.nodes["dos"].status = NodeStatus.PENDING

        progress = wf.get_progress()

        assert progress["total_nodes"] == 3
        assert progress["completed"] == 1
        assert progress["running"] == 1
        assert progress["pending"] == 1
        assert progress["percent_complete"] == pytest.approx(33.33, rel=0.1)


class TestFailureHandling:
    """Test workflow failure handling."""

    @pytest.mark.asyncio
    async def test_node_failure_skips_dependents(self):
        """Test that node failure causes dependent nodes to be skipped."""
        wf = Workflow("test", "Test")
        wf.add_node("a", {}, node_id="a")
        wf.add_node("b", {}, node_id="b")
        wf.add_node("c", {}, node_id="c")
        wf.add_dependency("a", "b")
        wf.add_dependency("b", "c")

        # Mark 'b' as failed
        wf.nodes["a"].status = NodeStatus.COMPLETED
        wf._completed_nodes.add("a")
        wf.nodes["b"].status = NodeStatus.FAILED
        wf._failed_nodes.add("b")

        wf._skip_dependent_nodes("b")

        assert wf.nodes["c"].status == NodeStatus.SKIPPED

    def test_skip_transitive_dependents(self):
        """Test skipping transitively dependent nodes."""
        wf = Workflow("test", "Test")
        wf.add_node("a", {}, node_id="a")
        wf.add_node("b", {}, node_id="b")
        wf.add_node("c", {}, node_id="c")
        wf.add_node("d", {}, node_id="d")
        wf.add_dependency("a", "b")
        wf.add_dependency("b", "c")
        wf.add_dependency("c", "d")

        wf._skip_dependent_nodes("b")

        assert wf.nodes["c"].status == NodeStatus.SKIPPED
        assert wf.nodes["d"].status == NodeStatus.SKIPPED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
