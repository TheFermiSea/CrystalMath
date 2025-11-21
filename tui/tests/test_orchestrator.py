"""
Tests for workflow orchestrator.
"""

import pytest
import asyncio
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch
from typing import List

from src.core.orchestrator import (
    WorkflowOrchestrator,
    WorkflowDefinition,
    WorkflowNode,
    WorkflowState,
    WorkflowStatus,
    NodeStatus,
    FailurePolicy,
    WorkflowEvent,
    WorkflowStarted,
    NodeStarted,
    NodeCompleted,
    NodeFailed,
    WorkflowCompleted,
    WorkflowFailed,
    WorkflowCancelled,
    WorkflowNotFoundError,
    CircularDependencyError,
    ParameterResolutionError,
)
from src.core.database import Database, Job


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for testing."""
    db_path = tmp_path / "test_orchestrator.db"
    db = Database(db_path)
    yield db
    db.close()


@pytest.fixture
def mock_queue_manager():
    """Create a mock queue manager."""
    queue_manager = Mock()
    queue_manager.enqueue = AsyncMock()
    queue_manager.stop_job = AsyncMock()
    return queue_manager


@pytest.fixture
def event_collector():
    """Create an event collector for testing."""
    events: List[WorkflowEvent] = []

    def collect(event: WorkflowEvent):
        events.append(event)

    collect.events = events
    return collect


@pytest.fixture
def orchestrator(temp_db, mock_queue_manager, event_collector):
    """Create an orchestrator instance for testing."""
    return WorkflowOrchestrator(
        database=temp_db,
        queue_manager=mock_queue_manager,
        event_callback=event_collector
    )


class TestWorkflowValidation:
    """Tests for workflow validation."""

    def test_simple_linear_workflow(self, orchestrator):
        """Test validating a simple linear workflow."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Linear Test",
            description="A -> B -> C",
            nodes=[
                WorkflowNode(node_id="A", job_name="job_a", template="input A", parameters={}),
                WorkflowNode(
                    node_id="B",
                    job_name="job_b",
                    template="input B",
                    parameters={},
                    dependencies=["A"]
                ),
                WorkflowNode(
                    node_id="C",
                    job_name="job_c",
                    template="input C",
                    parameters={},
                    dependencies=["B"]
                ),
            ]
        )

        # Should not raise
        orchestrator.register_workflow(workflow)
        assert 1 in orchestrator._workflows

    def test_parallel_workflow(self, orchestrator):
        """Test validating a workflow with parallel branches."""
        workflow = WorkflowDefinition(
            workflow_id=2,
            name="Parallel Test",
            description="A -> [B, C] -> D",
            nodes=[
                WorkflowNode(node_id="A", job_name="job_a", template="input A", parameters={}),
                WorkflowNode(
                    node_id="B",
                    job_name="job_b",
                    template="input B",
                    parameters={},
                    dependencies=["A"]
                ),
                WorkflowNode(
                    node_id="C",
                    job_name="job_c",
                    template="input C",
                    parameters={},
                    dependencies=["A"]
                ),
                WorkflowNode(
                    node_id="D",
                    job_name="job_d",
                    template="input D",
                    parameters={},
                    dependencies=["B", "C"]
                ),
            ]
        )

        # Should not raise
        orchestrator.register_workflow(workflow)
        assert 2 in orchestrator._workflows

    def test_circular_dependency_detected(self, orchestrator):
        """Test that circular dependencies are detected."""
        workflow = WorkflowDefinition(
            workflow_id=3,
            name="Circular Test",
            description="A -> B -> C -> A (circular!)",
            nodes=[
                WorkflowNode(
                    node_id="A",
                    job_name="job_a",
                    template="input A",
                    parameters={},
                    dependencies=["C"]
                ),
                WorkflowNode(
                    node_id="B",
                    job_name="job_b",
                    template="input B",
                    parameters={},
                    dependencies=["A"]
                ),
                WorkflowNode(
                    node_id="C",
                    job_name="job_c",
                    template="input C",
                    parameters={},
                    dependencies=["B"]
                ),
            ]
        )

        with pytest.raises(CircularDependencyError):
            orchestrator.register_workflow(workflow)

    def test_self_dependency_detected(self, orchestrator):
        """Test that self-dependencies are detected."""
        workflow = WorkflowDefinition(
            workflow_id=4,
            name="Self Dependency Test",
            description="A depends on itself",
            nodes=[
                WorkflowNode(
                    node_id="A",
                    job_name="job_a",
                    template="input A",
                    parameters={},
                    dependencies=["A"]
                ),
            ]
        )

        with pytest.raises(CircularDependencyError):
            orchestrator.register_workflow(workflow)


class TestWorkflowExecution:
    """Tests for workflow execution."""

    @pytest.mark.asyncio
    async def test_start_workflow(self, orchestrator, event_collector):
        """Test starting a workflow."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Start Test",
            description="Simple workflow",
            nodes=[
                WorkflowNode(node_id="A", job_name="job_a", template="CRYSTAL\nEND", parameters={}),
            ]
        )

        orchestrator.register_workflow(workflow)
        await orchestrator.start_workflow(1)

        # Check state
        state = await orchestrator.get_workflow_status(1)
        assert state.status == WorkflowStatus.RUNNING
        assert state.started_at is not None

        # Check events
        assert len(event_collector.events) >= 1
        assert isinstance(event_collector.events[0], WorkflowStarted)

        # Cleanup
        await orchestrator.stop()

    @pytest.mark.asyncio
    async def test_workflow_not_found(self, orchestrator):
        """Test error when workflow not found."""
        with pytest.raises(WorkflowNotFoundError):
            await orchestrator.start_workflow(999)

    @pytest.mark.asyncio
    async def test_pause_resume_workflow(self, orchestrator):
        """Test pausing and resuming a workflow."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Pause Test",
            description="Test pause/resume",
            nodes=[
                WorkflowNode(node_id="A", job_name="job_a", template="CRYSTAL\nEND", parameters={}),
            ]
        )

        orchestrator.register_workflow(workflow)
        await orchestrator.start_workflow(1)

        # Pause
        await orchestrator.pause_workflow(1)
        state = await orchestrator.get_workflow_status(1)
        assert state.status == WorkflowStatus.PAUSED
        assert state.paused_at is not None

        # Resume
        await orchestrator.resume_workflow(1)
        state = await orchestrator.get_workflow_status(1)
        assert state.status == WorkflowStatus.RUNNING
        assert state.paused_at is None

        # Cleanup
        await orchestrator.stop()

    @pytest.mark.asyncio
    async def test_cancel_workflow(self, orchestrator, event_collector):
        """Test cancelling a workflow."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Cancel Test",
            description="Test cancellation",
            nodes=[
                WorkflowNode(node_id="A", job_name="job_a", template="CRYSTAL\nEND", parameters={}),
            ]
        )

        orchestrator.register_workflow(workflow)
        await orchestrator.start_workflow(1)

        # Cancel
        await orchestrator.cancel_workflow(1, reason="Testing cancel")
        state = await orchestrator.get_workflow_status(1)
        assert state.status == WorkflowStatus.CANCELLED
        assert state.completed_at is not None

        # Check for cancel event
        cancel_events = [e for e in event_collector.events if isinstance(e, WorkflowCancelled)]
        assert len(cancel_events) == 1
        assert cancel_events[0].reason == "Testing cancel"

        # Cleanup
        await orchestrator.stop()


class TestParameterResolution:
    """Tests for parameter resolution."""

    @pytest.mark.asyncio
    async def test_simple_parameter_substitution(self, orchestrator):
        """Test simple parameter substitution."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Param Test",
            description="Test parameter resolution",
            nodes=[
                WorkflowNode(
                    node_id="A",
                    job_name="job_a",
                    template="ENERGY {{ energy }}",
                    parameters={"energy": -100.5}
                ),
            ],
            global_parameters={}
        )

        orchestrator.register_workflow(workflow)
        node = workflow.nodes[0]

        # Resolve parameters
        resolved = await orchestrator._resolve_parameters(1, node)
        assert resolved["energy"] == -100.5

        # Render template
        rendered = orchestrator._render_template(node.template, resolved)
        assert "ENERGY -100.5" in rendered

    @pytest.mark.asyncio
    async def test_global_parameters(self, orchestrator):
        """Test global parameters are available to all nodes."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Global Param Test",
            description="Test global parameters",
            nodes=[
                WorkflowNode(
                    node_id="A",
                    job_name="job_a",
                    template="BASIS {{ basis_set }}",
                    parameters={}
                ),
            ],
            global_parameters={"basis_set": "6-31G"}
        )

        orchestrator.register_workflow(workflow)
        node = workflow.nodes[0]

        resolved = await orchestrator._resolve_parameters(1, node)
        assert resolved["basis_set"] == "6-31G"

    @pytest.mark.asyncio
    async def test_dependency_results_propagation(self, orchestrator):
        """Test that results from dependencies are available."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Dependency Test",
            description="A -> B",
            nodes=[
                WorkflowNode(
                    node_id="A",
                    job_name="job_a",
                    template="SCF",
                    parameters={}
                ),
                WorkflowNode(
                    node_id="B",
                    job_name="job_b",
                    template="Energy from A: {{ A.final_energy }}",
                    parameters={},
                    dependencies=["A"]
                ),
            ]
        )

        orchestrator.register_workflow(workflow)

        # Simulate A completing with results
        node_a = orchestrator._node_lookup[1]["A"]
        node_a.status = NodeStatus.COMPLETED
        node_a.results = {"final_energy": -123.456}

        # Mark A as completed in state
        state = orchestrator._workflow_states[1]
        state.completed_nodes.add("A")

        # Now resolve B's parameters
        node_b = orchestrator._node_lookup[1]["B"]
        resolved = await orchestrator._resolve_parameters(1, node_b)

        # Check that A's results are available as nested dict
        assert "A" in resolved
        assert resolved["A"]["final_energy"] == -123.456

        # Render template
        rendered = orchestrator._render_template(node_b.template, resolved)
        assert "Energy from A: -123.456" in rendered

    @pytest.mark.asyncio
    async def test_template_error_handling(self, orchestrator):
        """Test handling of template syntax errors."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Template Error Test",
            description="Invalid template",
            nodes=[
                WorkflowNode(
                    node_id="A",
                    job_name="job_a",
                    template="Bad {{ syntax }}",
                    parameters={"unclosed": "{{ value"}  # Invalid Jinja2
                ),
            ]
        )

        orchestrator.register_workflow(workflow)
        node = workflow.nodes[0]

        # Should raise ParameterResolutionError
        with pytest.raises(ParameterResolutionError):
            await orchestrator._resolve_parameters(1, node)


class TestFailureHandling:
    """Tests for failure handling policies."""

    @pytest.mark.asyncio
    async def test_abort_policy(self, orchestrator, temp_db, event_collector):
        """Test ABORT policy stops entire workflow."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Abort Test",
            description="A -> B (A fails, workflow aborts)",
            nodes=[
                WorkflowNode(
                    node_id="A",
                    job_name="job_a",
                    template="CRYSTAL\nEND",
                    parameters={},
                    failure_policy=FailurePolicy.ABORT
                ),
                WorkflowNode(
                    node_id="B",
                    job_name="job_b",
                    template="CRYSTAL\nEND",
                    parameters={},
                    dependencies=["A"]
                ),
            ]
        )

        orchestrator.register_workflow(workflow)

        # Create a job for node A
        job_id = temp_db.create_job("job_a", "/tmp/test", "CRYSTAL\nEND")

        # Simulate A failing
        node_a = orchestrator._node_lookup[1]["A"]
        node_a.job_id = job_id
        state = orchestrator._workflow_states[1]
        state.status = WorkflowStatus.RUNNING
        state.running_nodes.add("A")

        # Handle failure
        await orchestrator._handle_node_failure(1, "A", job_id, "Test failure")

        # Check workflow state
        state = await orchestrator.get_workflow_status(1)
        assert state.status == WorkflowStatus.FAILED
        assert "A" in state.failed_nodes

        # Check for failure events
        fail_events = [e for e in event_collector.events if isinstance(e, WorkflowFailed)]
        assert len(fail_events) == 1

    @pytest.mark.asyncio
    async def test_skip_dependents_policy(self, orchestrator, temp_db):
        """Test SKIP_DEPENDENTS policy skips dependent nodes."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Skip Test",
            description="A -> B -> C (A fails, B and C skipped)",
            nodes=[
                WorkflowNode(
                    node_id="A",
                    job_name="job_a",
                    template="CRYSTAL\nEND",
                    parameters={},
                    failure_policy=FailurePolicy.SKIP_DEPENDENTS
                ),
                WorkflowNode(
                    node_id="B",
                    job_name="job_b",
                    template="CRYSTAL\nEND",
                    parameters={},
                    dependencies=["A"]
                ),
                WorkflowNode(
                    node_id="C",
                    job_name="job_c",
                    template="CRYSTAL\nEND",
                    parameters={},
                    dependencies=["B"]
                ),
            ]
        )

        orchestrator.register_workflow(workflow)

        # Create a job for node A
        job_id = temp_db.create_job("job_a", "/tmp/test", "CRYSTAL\nEND")

        # Simulate A failing
        node_a = orchestrator._node_lookup[1]["A"]
        node_a.job_id = job_id
        state = orchestrator._workflow_states[1]
        state.status = WorkflowStatus.RUNNING
        state.running_nodes.add("A")

        # Handle failure
        await orchestrator._handle_node_failure(1, "A", job_id, "Test failure")

        # Check that B and C are skipped
        node_b = orchestrator._node_lookup[1]["B"]
        node_c = orchestrator._node_lookup[1]["C"]

        await orchestrator._skip_dependent_nodes(1, "A")

        assert node_b.status == NodeStatus.SKIPPED
        assert node_c.status == NodeStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_retry_policy(self, orchestrator, temp_db, event_collector):
        """Test RETRY policy retries failed nodes."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Retry Test",
            description="A with retry",
            nodes=[
                WorkflowNode(
                    node_id="A",
                    job_name="job_a",
                    template="CRYSTAL\nEND",
                    parameters={},
                    failure_policy=FailurePolicy.RETRY,
                    max_retries=2
                ),
            ]
        )

        orchestrator.register_workflow(workflow)

        # Create a job for node A
        job_id = temp_db.create_job("job_a", "/tmp/test", "CRYSTAL\nEND")

        # Simulate A failing
        node_a = orchestrator._node_lookup[1]["A"]
        node_a.job_id = job_id
        state = orchestrator._workflow_states[1]
        state.status = WorkflowStatus.RUNNING
        state.running_nodes.add("A")

        # Handle failure (should retry)
        await orchestrator._handle_node_failure(1, "A", job_id, "First failure")

        # Check retry count increased
        assert node_a.retry_count == 1
        # After retry, node is re-submitted so status is QUEUED
        assert node_a.status == NodeStatus.QUEUED

        # Check for retry event
        fail_events = [e for e in event_collector.events if isinstance(e, NodeFailed)]
        assert len(fail_events) == 1
        assert fail_events[0].retry_count == 1

    @pytest.mark.asyncio
    async def test_continue_policy(self, orchestrator, temp_db):
        """Test CONTINUE policy continues with independent nodes."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Continue Test",
            description="A and B independent (A fails, B continues)",
            nodes=[
                WorkflowNode(
                    node_id="A",
                    job_name="job_a",
                    template="CRYSTAL\nEND",
                    parameters={},
                    failure_policy=FailurePolicy.CONTINUE
                ),
                WorkflowNode(
                    node_id="B",
                    job_name="job_b",
                    template="CRYSTAL\nEND",
                    parameters={}  # No dependencies
                ),
            ]
        )

        orchestrator.register_workflow(workflow)

        # Create a job for node A
        job_id = temp_db.create_job("job_a", "/tmp/test", "CRYSTAL\nEND")

        # Simulate A failing
        node_a = orchestrator._node_lookup[1]["A"]
        node_a.job_id = job_id
        state = orchestrator._workflow_states[1]
        state.status = WorkflowStatus.RUNNING
        state.running_nodes.add("A")

        # Handle failure (should continue)
        await orchestrator._handle_node_failure(1, "A", job_id, "Test failure")

        # Check state
        assert state.status == WorkflowStatus.RUNNING  # Should still be running
        assert "A" in state.failed_nodes

        # Node B should be queued (submitted by _submit_ready_nodes in CONTINUE policy)
        node_b = orchestrator._node_lookup[1]["B"]
        assert node_b.status == NodeStatus.QUEUED


class TestWorkflowCompletion:
    """Tests for workflow completion detection."""

    @pytest.mark.asyncio
    async def test_successful_completion(self, orchestrator, event_collector):
        """Test detecting successful workflow completion."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Completion Test",
            description="A -> B",
            nodes=[
                WorkflowNode(node_id="A", job_name="job_a", template="CRYSTAL\nEND", parameters={}),
                WorkflowNode(
                    node_id="B",
                    job_name="job_b",
                    template="CRYSTAL\nEND",
                    parameters={},
                    dependencies=["A"]
                ),
            ]
        )

        orchestrator.register_workflow(workflow)

        # Mark both nodes as completed
        node_a = orchestrator._node_lookup[1]["A"]
        node_a.status = NodeStatus.COMPLETED
        node_b = orchestrator._node_lookup[1]["B"]
        node_b.status = NodeStatus.COMPLETED

        state = orchestrator._workflow_states[1]
        state.status = WorkflowStatus.RUNNING
        state.completed_nodes.add("A")
        state.completed_nodes.add("B")

        # Check completion
        await orchestrator._check_workflow_completion(1)

        # Should be completed
        state = await orchestrator.get_workflow_status(1)
        assert state.status == WorkflowStatus.COMPLETED
        assert state.progress == 100.0

        # Check for completion event
        complete_events = [e for e in event_collector.events if isinstance(e, WorkflowCompleted)]
        assert len(complete_events) == 1
        assert complete_events[0].successful_nodes == 2
        assert complete_events[0].failed_nodes == 0

    @pytest.mark.asyncio
    async def test_failed_completion(self, orchestrator, event_collector):
        """Test detecting workflow completion with failures."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Failed Completion Test",
            description="A -> B (A fails with SKIP_DEPENDENTS)",
            nodes=[
                WorkflowNode(
                    node_id="A",
                    job_name="job_a",
                    template="CRYSTAL\nEND",
                    parameters={},
                    failure_policy=FailurePolicy.SKIP_DEPENDENTS
                ),
                WorkflowNode(
                    node_id="B",
                    job_name="job_b",
                    template="CRYSTAL\nEND",
                    parameters={},
                    dependencies=["A"]
                ),
            ]
        )

        orchestrator.register_workflow(workflow)

        # Mark A as failed, B as skipped
        node_a = orchestrator._node_lookup[1]["A"]
        node_a.status = NodeStatus.FAILED
        node_b = orchestrator._node_lookup[1]["B"]
        node_b.status = NodeStatus.SKIPPED

        state = orchestrator._workflow_states[1]
        state.status = WorkflowStatus.RUNNING
        state.failed_nodes.add("A")

        # Check completion
        await orchestrator._check_workflow_completion(1)

        # Should be failed
        state = await orchestrator.get_workflow_status(1)
        assert state.status == WorkflowStatus.FAILED

        # Check for failure event
        fail_events = [e for e in event_collector.events if isinstance(e, WorkflowFailed)]
        assert len(fail_events) == 1

    @pytest.mark.asyncio
    async def test_progress_tracking(self, orchestrator):
        """Test workflow progress calculation."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Progress Test",
            description="Three nodes",
            nodes=[
                WorkflowNode(node_id="A", job_name="job_a", template="CRYSTAL\nEND", parameters={}),
                WorkflowNode(node_id="B", job_name="job_b", template="CRYSTAL\nEND", parameters={}),
                WorkflowNode(node_id="C", job_name="job_c", template="CRYSTAL\nEND", parameters={}),
            ]
        )

        orchestrator.register_workflow(workflow)

        state = orchestrator._workflow_states[1]
        state.status = WorkflowStatus.RUNNING

        # Complete first node
        node_a = orchestrator._node_lookup[1]["A"]
        node_a.status = NodeStatus.COMPLETED
        state.completed_nodes.add("A")

        await orchestrator._check_workflow_completion(1)
        state = await orchestrator.get_workflow_status(1)
        assert state.progress == pytest.approx(33.33, rel=0.1)

        # Complete second node
        node_b = orchestrator._node_lookup[1]["B"]
        node_b.status = NodeStatus.COMPLETED
        state.completed_nodes.add("B")

        await orchestrator._check_workflow_completion(1)
        state = await orchestrator.get_workflow_status(1)
        assert state.progress == pytest.approx(66.66, rel=0.1)

        # Complete third node
        node_c = orchestrator._node_lookup[1]["C"]
        node_c.status = NodeStatus.COMPLETED
        state.completed_nodes.add("C")

        await orchestrator._check_workflow_completion(1)
        state = await orchestrator.get_workflow_status(1)
        assert state.progress == 100.0


class TestDependencyResolution:
    """Tests for dependency resolution."""

    def test_no_dependencies(self, orchestrator):
        """Test node with no dependencies is ready."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="No Deps Test",
            description="Single node",
            nodes=[
                WorkflowNode(node_id="A", job_name="job_a", template="CRYSTAL\nEND", parameters={}),
            ]
        )

        orchestrator.register_workflow(workflow)
        node = workflow.nodes[0]

        assert orchestrator._dependencies_met(1, node)

    def test_dependencies_not_met(self, orchestrator):
        """Test node with unmet dependencies is not ready."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Deps Not Met Test",
            description="A -> B",
            nodes=[
                WorkflowNode(node_id="A", job_name="job_a", template="CRYSTAL\nEND", parameters={}),
                WorkflowNode(
                    node_id="B",
                    job_name="job_b",
                    template="CRYSTAL\nEND",
                    parameters={},
                    dependencies=["A"]
                ),
            ]
        )

        orchestrator.register_workflow(workflow)
        node_b = workflow.nodes[1]

        # A not completed yet
        assert not orchestrator._dependencies_met(1, node_b)

    def test_dependencies_met(self, orchestrator):
        """Test node with met dependencies is ready."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Deps Met Test",
            description="A -> B",
            nodes=[
                WorkflowNode(node_id="A", job_name="job_a", template="CRYSTAL\nEND", parameters={}),
                WorkflowNode(
                    node_id="B",
                    job_name="job_b",
                    template="CRYSTAL\nEND",
                    parameters={},
                    dependencies=["A"]
                ),
            ]
        )

        orchestrator.register_workflow(workflow)

        # Mark A as completed
        state = orchestrator._workflow_states[1]
        state.completed_nodes.add("A")

        node_b = workflow.nodes[1]
        assert orchestrator._dependencies_met(1, node_b)

    def test_multiple_dependencies(self, orchestrator):
        """Test node with multiple dependencies."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Multiple Deps Test",
            description="[A, B] -> C",
            nodes=[
                WorkflowNode(node_id="A", job_name="job_a", template="CRYSTAL\nEND", parameters={}),
                WorkflowNode(node_id="B", job_name="job_b", template="CRYSTAL\nEND", parameters={}),
                WorkflowNode(
                    node_id="C",
                    job_name="job_c",
                    template="CRYSTAL\nEND",
                    parameters={},
                    dependencies=["A", "B"]
                ),
            ]
        )

        orchestrator.register_workflow(workflow)
        state = orchestrator._workflow_states[1]
        node_c = workflow.nodes[2]

        # Both dependencies not met
        assert not orchestrator._dependencies_met(1, node_c)

        # Only A completed
        state.completed_nodes.add("A")
        assert not orchestrator._dependencies_met(1, node_c)

        # Both completed
        state.completed_nodes.add("B")
        assert orchestrator._dependencies_met(1, node_c)


class TestEventSystem:
    """Tests for event system."""

    @pytest.mark.asyncio
    async def test_event_callback_receives_events(self, orchestrator, event_collector):
        """Test that event callback receives events."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Event Test",
            description="Test events",
            nodes=[
                WorkflowNode(node_id="A", job_name="job_a", template="CRYSTAL\nEND", parameters={}),
            ]
        )

        orchestrator.register_workflow(workflow)
        await orchestrator.start_workflow(1)

        # Should have received WorkflowStarted event
        assert len(event_collector.events) > 0
        assert any(isinstance(e, WorkflowStarted) for e in event_collector.events)

        await orchestrator.stop()

    def test_event_callback_error_handling(self, orchestrator):
        """Test that errors in event callback don't break orchestration."""

        def bad_callback(event: WorkflowEvent):
            raise RuntimeError("Callback error")

        orchestrator.event_callback = bad_callback

        # Should not raise even though callback raises
        orchestrator._emit_event(WorkflowStarted(workflow_id=1))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
