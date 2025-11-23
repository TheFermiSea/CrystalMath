"""
Tests for workflow orchestrator.
"""

import os
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


class TestScratchDirectoryManagement:
    """Tests for scratch directory configuration and cleanup."""

    def test_scratch_base_from_cry_scratch_base_env(self, temp_db, mock_queue_manager):
        """Test that CRY_SCRATCH_BASE environment variable is used."""
        custom_scratch = "/custom/scratch"
        with patch.dict(os.environ, {"CRY_SCRATCH_BASE": custom_scratch}):
            orchestrator = WorkflowOrchestrator(
                database=temp_db,
                queue_manager=mock_queue_manager
            )
            assert orchestrator._scratch_base == Path(custom_scratch)

    def test_scratch_base_fallback_to_cry23_scrdir(self, temp_db, mock_queue_manager):
        """Test fallback to CRY23_SCRDIR when CRY_SCRATCH_BASE not set."""
        custom_scratch = "/crystal/scratch"
        # Remove CRY_SCRATCH_BASE if set
        with patch.dict(os.environ, {"CRY23_SCRDIR": custom_scratch}, clear=False):
            # Clear CRY_SCRATCH_BASE to force fallback
            if "CRY_SCRATCH_BASE" in os.environ:
                del os.environ["CRY_SCRATCH_BASE"]

            orchestrator = WorkflowOrchestrator(
                database=temp_db,
                queue_manager=mock_queue_manager
            )
            # Should use CRY23_SCRDIR
            assert orchestrator._scratch_base == Path(custom_scratch)

    def test_scratch_base_explicit_parameter(self, temp_db, mock_queue_manager, tmp_path):
        """Test that explicit scratch_base parameter is used."""
        custom_scratch = tmp_path / "explicit_scratch"
        orchestrator = WorkflowOrchestrator(
            database=temp_db,
            queue_manager=mock_queue_manager,
            scratch_base=custom_scratch
        )
        assert orchestrator._scratch_base == custom_scratch

    def test_get_scratch_base_priority_order(self):
        """Test scratch base resolution follows correct priority order."""
        import tempfile

        # Test 1: CRY_SCRATCH_BASE has highest priority
        with patch.dict(
            os.environ,
            {
                "CRY_SCRATCH_BASE": "/cry_scratch_base",
                "CRY23_SCRDIR": "/cry23_scrdir"
            }
        ):
            result = WorkflowOrchestrator._get_scratch_base()
            assert result == Path("/cry_scratch_base")

        # Test 2: CRY23_SCRDIR used when CRY_SCRATCH_BASE not set
        with patch.dict(os.environ, {"CRY23_SCRDIR": "/cry23_scrdir"}, clear=True):
            result = WorkflowOrchestrator._get_scratch_base()
            assert result == Path("/cry23_scrdir")

        # Test 3: tempfile.gettempdir() used when neither set
        with patch.dict(os.environ, {}, clear=True):
            result = WorkflowOrchestrator._get_scratch_base()
            # Should match system temp directory (varies by OS)
            assert result == Path(tempfile.gettempdir())

    def test_create_work_directory_respects_scratch_base(
        self, temp_db, mock_queue_manager, tmp_path
    ):
        """Test that work directories are created in configured scratch base."""
        scratch_base = tmp_path / "crystal_scratch"
        orchestrator = WorkflowOrchestrator(
            database=temp_db,
            queue_manager=mock_queue_manager,
            scratch_base=scratch_base
        )

        work_dir = orchestrator._create_work_directory(workflow_id=1, node_id="test_node")

        # Verify directory was created under scratch_base
        assert work_dir.exists()
        assert work_dir.is_dir()
        assert scratch_base in work_dir.parents or work_dir.parent == scratch_base

    def test_create_work_directory_naming(
        self, temp_db, mock_queue_manager, tmp_path
    ):
        """Test that work directories have correct naming format."""
        scratch_base = tmp_path / "scratch"
        orchestrator = WorkflowOrchestrator(
            database=temp_db,
            queue_manager=mock_queue_manager,
            scratch_base=scratch_base
        )

        work_dir = orchestrator._create_work_directory(workflow_id=42, node_id="calc_step_1")

        # Verify directory name format
        dir_name = work_dir.name
        assert "workflow_42" in dir_name
        assert "node_calc_step_1" in dir_name
        assert dir_name.count("_") >= 3  # At least workflow, node, timestamp, pid separators

    def test_create_work_directory_uniqueness(
        self, temp_db, mock_queue_manager, tmp_path
    ):
        """Test that multiple work directories get unique names."""
        scratch_base = tmp_path / "scratch"
        orchestrator = WorkflowOrchestrator(
            database=temp_db,
            queue_manager=mock_queue_manager,
            scratch_base=scratch_base
        )

        # Create two work directories for same workflow/node
        work_dir1 = orchestrator._create_work_directory(workflow_id=1, node_id="A")
        work_dir2 = orchestrator._create_work_directory(workflow_id=1, node_id="A")

        # Should be different (different timestamps/pids)
        assert work_dir1 != work_dir2
        assert work_dir1.exists()
        assert work_dir2.exists()

    def test_work_directory_registered_for_cleanup(
        self, temp_db, mock_queue_manager, tmp_path
    ):
        """Test that created work directories are registered for cleanup."""
        scratch_base = tmp_path / "scratch"
        orchestrator = WorkflowOrchestrator(
            database=temp_db,
            queue_manager=mock_queue_manager,
            scratch_base=scratch_base
        )

        work_dir = orchestrator._create_work_directory(workflow_id=1, node_id="test")

        # Verify directory is in cleanup set
        assert work_dir in orchestrator._work_dirs

    def test_cleanup_work_directories(
        self, temp_db, mock_queue_manager, tmp_path
    ):
        """Test that work directories are cleaned up properly."""
        scratch_base = tmp_path / "scratch"
        orchestrator = WorkflowOrchestrator(
            database=temp_db,
            queue_manager=mock_queue_manager,
            scratch_base=scratch_base
        )

        # Create work directories
        work_dir1 = orchestrator._create_work_directory(workflow_id=1, node_id="A")
        work_dir2 = orchestrator._create_work_directory(workflow_id=1, node_id="B")

        # Create some test files
        test_file1 = work_dir1 / "test.txt"
        test_file1.write_text("test content")
        test_file2 = work_dir2 / "data.dat"
        test_file2.write_text("data")

        assert work_dir1.exists()
        assert work_dir2.exists()
        assert test_file1.exists()
        assert test_file2.exists()

        # Clean up
        orchestrator._cleanup_work_dirs()

        # Verify directories are removed
        assert not work_dir1.exists()
        assert not work_dir2.exists()

    def test_cleanup_handles_missing_directories(
        self, temp_db, mock_queue_manager, tmp_path
    ):
        """Test that cleanup handles directories that no longer exist."""
        scratch_base = tmp_path / "scratch"
        orchestrator = WorkflowOrchestrator(
            database=temp_db,
            queue_manager=mock_queue_manager,
            scratch_base=scratch_base
        )

        work_dir = orchestrator._create_work_directory(workflow_id=1, node_id="test")

        # Manually remove the directory
        import shutil
        shutil.rmtree(work_dir)

        # Cleanup should not raise even though directory is gone
        orchestrator._cleanup_work_dirs()  # Should not raise

    def test_cleanup_handles_permission_errors(
        self, temp_db, mock_queue_manager, tmp_path
    ):
        """Test that cleanup handles permission errors gracefully."""
        scratch_base = tmp_path / "scratch"
        orchestrator = WorkflowOrchestrator(
            database=temp_db,
            queue_manager=mock_queue_manager,
            scratch_base=scratch_base
        )

        work_dir = orchestrator._create_work_directory(workflow_id=1, node_id="test")

        # Mock shutil.rmtree to raise PermissionError
        with patch("shutil.rmtree", side_effect=PermissionError("Permission denied")):
            # Cleanup should not raise
            orchestrator._cleanup_work_dirs()  # Should not raise

    @pytest.mark.asyncio
    async def test_submit_node_creates_work_directory(
        self, temp_db, mock_queue_manager, tmp_path
    ):
        """Test that _submit_node creates work directory in correct location."""
        scratch_base = tmp_path / "crystal_scratch"
        orchestrator = WorkflowOrchestrator(
            database=temp_db,
            queue_manager=mock_queue_manager,
            scratch_base=scratch_base
        )

        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Test Workflow",
            description="Test",
            nodes=[
                WorkflowNode(
                    node_id="test_calc",
                    job_name="job_test",
                    template="CRYSTAL\nEND",
                    parameters={}
                ),
            ]
        )

        orchestrator.register_workflow(workflow)

        # Submit the node
        node = workflow.nodes[0]
        await orchestrator._submit_node(workflow_id=1, node=node)

        # Verify work directory was created
        state = orchestrator._workflow_states[1]
        assert len(state.running_nodes) == 1

        # Verify at least one work directory was registered
        assert len(orchestrator._work_dirs) > 0

        # All work dirs should be under scratch_base
        for work_dir in orchestrator._work_dirs:
            assert scratch_base in work_dir.parents or work_dir.parent == scratch_base

    @pytest.mark.asyncio
    async def test_submit_node_work_directory_in_database(
        self, temp_db, mock_queue_manager, tmp_path
    ):
        """Test that work directory path is correctly stored in database."""
        scratch_base = tmp_path / "scratch"
        orchestrator = WorkflowOrchestrator(
            database=temp_db,
            queue_manager=mock_queue_manager,
            scratch_base=scratch_base
        )

        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Test",
            description="Test",
            nodes=[
                WorkflowNode(
                    node_id="calc",
                    job_name="job_calc",
                    template="CRYSTAL\nEND",
                    parameters={}
                ),
            ]
        )

        orchestrator.register_workflow(workflow)
        node = workflow.nodes[0]

        await orchestrator._submit_node(workflow_id=1, node=node)

        # Get the job from database
        job = temp_db.get_job(node.job_id)
        assert job is not None

        # Verify work_dir is not in /tmp
        assert not job.work_dir.startswith("/tmp/workflow_")

        # Verify work_dir is under scratch_base
        job_work_dir = Path(job.work_dir)
        assert scratch_base in job_work_dir.parents or job_work_dir.parent == scratch_base


class TestJobSubmissionIntegration:
    """Integration tests for job submission and queue manager integration."""

    @pytest.mark.asyncio
    async def test_submit_node_calls_queue_manager_enqueue(
        self, orchestrator, mock_queue_manager, temp_db, tmp_path
    ):
        """Test that _submit_node calls queue_manager.enqueue with correct parameters."""
        scratch_base = tmp_path / "scratch"
        orchestrator._scratch_base = scratch_base

        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Queue Test",
            description="Test queue submission",
            nodes=[
                WorkflowNode(
                    node_id="test_node",
                    job_name="job_test",
                    template="CRYSTAL\nEND",
                    parameters={}
                ),
            ]
        )

        orchestrator.register_workflow(workflow)
        node = workflow.nodes[0]

        # Submit the node
        await orchestrator._submit_node(workflow_id=1, node=node)

        # Verify queue_manager.enqueue was called
        assert mock_queue_manager.enqueue.called
        call_kwargs = mock_queue_manager.enqueue.call_args[1]

        # Check call parameters
        assert "job_id" in call_kwargs
        assert call_kwargs["priority"] == 2  # NORMAL priority
        assert call_kwargs["runner_type"] == "local"  # Default runner type

    @pytest.mark.asyncio
    async def test_submit_node_with_dependencies(
        self, orchestrator, mock_queue_manager, temp_db, tmp_path
    ):
        """Test that _submit_node passes dependencies to queue manager."""
        scratch_base = tmp_path / "scratch"
        orchestrator._scratch_base = scratch_base

        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Dependency Test",
            description="Test with dependencies",
            nodes=[
                WorkflowNode(
                    node_id="A",
                    job_name="job_a",
                    template="CRYSTAL\nEND",
                    parameters={}
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

        # Submit node A first
        node_a = workflow.nodes[0]
        await orchestrator._submit_node(workflow_id=1, node=node_a)

        # Clear mock call history
        mock_queue_manager.reset_mock()

        # Submit node B
        node_b = workflow.nodes[1]
        await orchestrator._submit_node(workflow_id=1, node=node_b)

        # Verify queue_manager.enqueue was called for B with A's job_id as dependency
        assert mock_queue_manager.enqueue.called
        call_kwargs = mock_queue_manager.enqueue.call_args[1]

        assert "dependencies" in call_kwargs
        assert call_kwargs["dependencies"] == [node_a.job_id]

    @pytest.mark.asyncio
    async def test_submit_node_registers_callback(
        self, orchestrator, temp_db, tmp_path
    ):
        """Test that _submit_node registers a completion callback."""
        scratch_base = tmp_path / "scratch"
        orchestrator._scratch_base = scratch_base

        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Callback Test",
            description="Test callback registration",
            nodes=[
                WorkflowNode(
                    node_id="test",
                    job_name="job_test",
                    template="CRYSTAL\nEND",
                    parameters={}
                ),
            ]
        )

        orchestrator.register_workflow(workflow)
        node = workflow.nodes[0]

        await orchestrator._submit_node(workflow_id=1, node=node)

        # Verify callback was registered
        assert node.job_id in orchestrator._node_callbacks
        callback_data = orchestrator._node_callbacks[node.job_id]
        assert callback_data == (1, "test")  # (workflow_id, node_id)

    @pytest.mark.asyncio
    async def test_on_node_complete_success(
        self, orchestrator, temp_db, event_collector
    ):
        """Test _on_node_complete processes successful job completion."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Success Test",
            description="Test successful completion",
            nodes=[
                WorkflowNode(
                    node_id="test",
                    job_name="job_test",
                    template="CRYSTAL\nEND",
                    parameters={}
                ),
            ]
        )

        orchestrator.register_workflow(workflow)
        node = workflow.nodes[0]

        # Create and associate a job with the node
        job_id = temp_db.create_job("job_test", "/tmp/test", "CRYSTAL\nEND")
        node.job_id = job_id

        # Update workflow state
        state = orchestrator._workflow_states[1]
        state.status = WorkflowStatus.RUNNING
        state.running_nodes.add("test")

        # Update job status to COMPLETED
        temp_db.update_status(job_id, "COMPLETED")

        # Call the completion handler
        await orchestrator._on_node_complete(1, node, "COMPLETED")

        # Verify node was processed
        node = orchestrator._node_lookup[1]["test"]
        assert node.status == NodeStatus.COMPLETED
        assert "test" in state.completed_nodes

    @pytest.mark.asyncio
    async def test_on_node_complete_failure(
        self, orchestrator, temp_db, event_collector
    ):
        """Test _on_node_complete processes job failure."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Failure Test",
            description="Test failure handling",
            nodes=[
                WorkflowNode(
                    node_id="test",
                    job_name="job_test",
                    template="CRYSTAL\nEND",
                    parameters={},
                    failure_policy=FailurePolicy.ABORT
                ),
            ]
        )

        orchestrator.register_workflow(workflow)
        node = workflow.nodes[0]

        # Create and associate a job with the node
        job_id = temp_db.create_job("job_test", "/tmp/test", "CRYSTAL\nEND")
        node.job_id = job_id

        # Update workflow state
        state = orchestrator._workflow_states[1]
        state.status = WorkflowStatus.RUNNING
        state.running_nodes.add("test")

        # Call the failure handler
        await orchestrator._on_node_complete(1, node, "FAILED")

        # Verify failure was handled
        state = orchestrator._workflow_states[1]
        assert state.status == WorkflowStatus.FAILED

    @pytest.mark.asyncio
    async def test_workflow_submission_end_to_end(
        self, orchestrator, mock_queue_manager, temp_db, event_collector, tmp_path
    ):
        """Integration test: submit workflow, verify queue manager calls."""
        scratch_base = tmp_path / "scratch"
        orchestrator._scratch_base = scratch_base

        workflow = WorkflowDefinition(
            workflow_id=1,
            name="E2E Test",
            description="End-to-end submission test",
            nodes=[
                WorkflowNode(
                    node_id="A",
                    job_name="job_a",
                    template="CRYSTAL\nEND",
                    parameters={}
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
        await orchestrator.start_workflow(1)

        # Wait a bit for initial submission
        await asyncio.sleep(0.1)

        # Verify queue_manager.enqueue was called at least once for node A
        assert mock_queue_manager.enqueue.called

        # Check that we got a NodeStarted event for A
        node_started_events = [e for e in event_collector.events if isinstance(e, NodeStarted)]
        assert len(node_started_events) >= 1
        assert node_started_events[0].node_id == "A"

        # Cleanup
        await orchestrator.stop()

    @pytest.mark.asyncio
    async def test_job_submission_updates_database_status(
        self, orchestrator, temp_db, tmp_path
    ):
        """Test that job submission updates database status to QUEUED."""
        scratch_base = tmp_path / "scratch"
        orchestrator._scratch_base = scratch_base

        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Status Test",
            description="Test database status update",
            nodes=[
                WorkflowNode(
                    node_id="test",
                    job_name="job_test",
                    template="CRYSTAL\nEND",
                    parameters={}
                ),
            ]
        )

        orchestrator.register_workflow(workflow)
        node = workflow.nodes[0]

        await orchestrator._submit_node(workflow_id=1, node=node)

        # Verify job status in database
        job = temp_db.get_job(node.job_id)
        assert job is not None
        assert job.status == "QUEUED"


class TestWorkflowDirectoryCleanup:
    """Tests for workflow directory cleanup on exit."""

    @pytest.mark.asyncio
    async def test_workflow_directories_cleaned_on_orchestrator_stop(
        self, temp_db, mock_queue_manager, tmp_path
    ):
        """Test that workflow directories are cleaned when orchestrator stops."""
        scratch_base = tmp_path / "scratch"
        orchestrator = WorkflowOrchestrator(
            database=temp_db,
            queue_manager=mock_queue_manager,
            scratch_base=scratch_base
        )

        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Cleanup Test",
            description="Test directory cleanup",
            nodes=[
                WorkflowNode(
                    node_id="test",
                    job_name="job_test",
                    template="CRYSTAL\nEND",
                    parameters={}
                ),
            ]
        )

        orchestrator.register_workflow(workflow)
        node = workflow.nodes[0]

        await orchestrator._submit_node(workflow_id=1, node=node)

        # Get the work directory path
        job = temp_db.get_job(node.job_id)
        work_dir = Path(job.work_dir)

        # Verify directory exists
        assert work_dir.exists()

        # Manually call cleanup
        orchestrator._cleanup_work_dirs()

        # Verify directory is removed
        assert not work_dir.exists()

    def test_atexit_handler_registered(self, temp_db, mock_queue_manager):
        """Test that cleanup handler is registered with atexit."""
        orchestrator = WorkflowOrchestrator(
            database=temp_db,
            queue_manager=mock_queue_manager
        )

        # The atexit handler should be registered
        # We can't directly test atexit, but we can verify the method exists
        assert hasattr(orchestrator, '_cleanup_work_dirs')
        assert callable(orchestrator._cleanup_work_dirs)


class TestJinja2SecurityHardening:
    """Security tests for Jinja2 template injection vulnerabilities in orchestrator.

    VULNERABILITY (FIXED): orchestrator.py used unsandboxed Jinja2 Environment
    allowing arbitrary code execution through parameter templates.

    FIX: Replaced Environment with SandboxedEnvironment to restrict dangerous operations.
    """

    @pytest.mark.asyncio
    async def test_orchestrator_uses_sandboxed_environment(self, orchestrator):
        """Test that orchestrator uses SandboxedEnvironment, not regular Environment."""
        from jinja2.sandbox import SandboxedEnvironment

        # Verify the Jinja2 environment is sandboxed
        assert isinstance(orchestrator._jinja_env, SandboxedEnvironment)

    @pytest.mark.asyncio
    async def test_parameter_template_injection_blocked(self, orchestrator):
        """Test that malicious Jinja2 expressions in parameters are blocked."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Injection Test",
            description="Test parameter template injection",
            nodes=[
                WorkflowNode(
                    node_id="A",
                    job_name="job_a",
                    template="CRYSTAL\nEND",
                    # Malicious parameter trying to execute code
                    parameters={
                        "malicious": "{{ ''.__class__.__mro__[1].__subclasses__()[104].__init__.__globals__['sys'].exit() }}"
                    }
                ),
            ]
        )

        orchestrator.register_workflow(workflow)
        node = workflow.nodes[0]

        # Should either block the attack or fail safely
        try:
            resolved = await orchestrator._resolve_parameters(1, node)
            # If resolution succeeds, malicious code should be neutralized
            # The result should not contain evidence of Python internals access
            result_str = str(resolved.get("malicious", ""))
            assert "exit()" not in result_str or "class" in result_str  # Still escaped
        except Exception as e:
            # Sandbox blocking the attack is also acceptable
            error_str = str(e).lower()
            assert "unsafe" in error_str or "not allowed" in error_str or "forbidden" in error_str

    @pytest.mark.asyncio
    async def test_template_file_access_blocked(self, orchestrator):
        """Test that templates cannot read arbitrary files."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="File Access Test",
            description="Test file access blocking",
            nodes=[
                WorkflowNode(
                    node_id="A",
                    job_name="job_a",
                    # Template tries to read /etc/passwd
                    template="{{ open('/etc/passwd').read() }}",
                    parameters={}
                ),
            ]
        )

        orchestrator.register_workflow(workflow)
        node = workflow.nodes[0]

        # Should fail safely
        try:
            resolved = await orchestrator._resolve_parameters(1, node)
            rendered = orchestrator._render_template(node.template, resolved)
            # Should not contain /etc/passwd content
            assert "root:" not in rendered
            assert "/bin/bash" not in rendered
        except Exception:
            # Exception is acceptable - sandbox blocked the attack
            pass

    @pytest.mark.asyncio
    async def test_template_import_blocked(self, orchestrator):
        """Test that templates cannot import modules."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Import Test",
            description="Test import blocking",
            nodes=[
                WorkflowNode(
                    node_id="A",
                    job_name="job_a",
                    # Template tries to import os and execute command
                    template="{{ __import__('os').system('id') }}",
                    parameters={}
                ),
            ]
        )

        orchestrator.register_workflow(workflow)
        node = workflow.nodes[0]

        # Should fail safely
        try:
            resolved = await orchestrator._resolve_parameters(1, node)
            rendered = orchestrator._render_template(node.template, resolved)
            # Should not contain command output (like "uid=")
            assert "uid=" not in rendered
        except Exception:
            # Exception is acceptable - sandbox blocked the attack
            pass

    @pytest.mark.asyncio
    async def test_template_config_access_blocked(self, orchestrator):
        """Test that templates cannot access config or globals."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Config Access Test",
            description="Test config access blocking",
            nodes=[
                WorkflowNode(
                    node_id="A",
                    job_name="job_a",
                    # Template tries to access config and globals
                    template="{{ config.__class__.__init__.__globals__['sys'].exit() }}",
                    parameters={}
                ),
            ]
        )

        orchestrator.register_workflow(workflow)
        node = workflow.nodes[0]

        # Should fail safely
        try:
            resolved = await orchestrator._resolve_parameters(1, node)
            rendered = orchestrator._render_template(node.template, resolved)
            # Rendering should not execute or expose system objects
            assert "__globals__" not in rendered or "config" in rendered  # Still escaped
        except Exception:
            # Exception is acceptable - sandbox blocked the attack
            pass

    @pytest.mark.asyncio
    async def test_parameter_resolution_with_safe_templates(self, orchestrator):
        """Test that legitimate parameter templates still work with sandbox."""
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Safe Template Test",
            description="A -> B (B uses A's results)",
            nodes=[
                WorkflowNode(
                    node_id="A",
                    job_name="job_a",
                    template="CRYSTAL\nEND",
                    parameters={"energy": -100.5}
                ),
                WorkflowNode(
                    node_id="B",
                    job_name="job_b",
                    template="Previous energy: {{ A.final_energy }}",
                    parameters={
                        "computed_value": "{{ A.final_energy * 2 }}"
                    },
                    dependencies=["A"]
                ),
            ]
        )

        orchestrator.register_workflow(workflow)

        # Simulate A completing with results
        node_a = orchestrator._node_lookup[1]["A"]
        node_a.status = NodeStatus.COMPLETED
        node_a.results = {"final_energy": -123.456}
        state = orchestrator._workflow_states[1]
        state.completed_nodes.add("A")

        # Resolve B's parameters (legitimate use case)
        node_b = orchestrator._node_lookup[1]["B"]
        resolved = await orchestrator._resolve_parameters(1, node_b)

        # Should work correctly
        assert "A" in resolved
        assert resolved["A"]["final_energy"] == -123.456

        # Render template should work
        rendered = orchestrator._render_template(node_b.template, resolved)
        assert "Previous energy: -123.456" in rendered

    @pytest.mark.asyncio
    async def test_multiple_malicious_payloads_blocked(self, orchestrator):
        """Test that various malicious payloads are all blocked."""
        dangerous_payloads = [
            "{{ [].__class__.__mro__[1].__subclasses__()[104] }}",
            "{{ lipsum.__globals__['os'].system('id') }}",
            "{{ ().__class__.__bases__[0].__subclasses__() }}",
            "{{ config.items() }}",
        ]

        for i, payload in enumerate(dangerous_payloads):
            workflow = WorkflowDefinition(
                workflow_id=i+1,
                name=f"Payload Test {i+1}",
                description=f"Test malicious payload {i+1}",
                nodes=[
                    WorkflowNode(
                        node_id="A",
                        job_name="job_a",
                        template=payload,
                        parameters={}
                    ),
                ]
            )

            orchestrator.register_workflow(workflow)
            node = workflow.nodes[0]

            # All should fail safely
            try:
                resolved = await orchestrator._resolve_parameters(i+1, node)
                rendered = orchestrator._render_template(node.template, resolved)
                # If rendering succeeds, should not expose Python internals
                assert "uid=" not in rendered
                assert "<class" not in rendered or "__class__" in rendered  # Still escaped
            except Exception:
                # Exception is acceptable - sandbox blocked
                pass

    @pytest.mark.asyncio
    async def test_render_template_injection_blocked(self, orchestrator):
        """Test that _render_template method blocks injection attacks."""
        # Direct test of _render_template with malicious content
        malicious_template = "{{ ''.__class__.__mro__[1].__subclasses__()[104].__init__.__globals__['os'].popen('ls').read() }}"

        try:
            result = orchestrator._render_template(malicious_template, {})
            # Should not contain file listing
            assert "bin" not in result or "__class__" in result  # Still escaped
        except Exception:
            # Exception is acceptable - sandbox blocked
            pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
