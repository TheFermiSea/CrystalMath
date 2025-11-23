"""
Comprehensive test suite for dependency validation utilities.

Tests the consolidated dependency validation logic used by both
WorkflowOrchestrator and QueueManager.
"""

import pytest
from src.core.dependency_utils import assert_acyclic, CircularDependencyError
from src.core.orchestrator import WorkflowOrchestrator, WorkflowDefinition, WorkflowNode
from src.core.queue_manager import QueueManager
from src.core.database import Database
from pathlib import Path
import tempfile


class TestAssertAcyclic:
    """Tests for the core assert_acyclic function."""

    def test_empty_graph(self):
        """Empty graph should be valid (no cycles)."""
        graph = {}
        # Should not raise
        assert_acyclic(graph)

    def test_single_node_no_dependencies(self):
        """Single node with no dependencies should be valid."""
        graph = {"A": []}
        # Should not raise
        assert_acyclic(graph)

    def test_linear_chain(self):
        """Linear dependency chain A → B → C should be valid."""
        graph = {
            "A": ["B"],
            "B": ["C"],
            "C": []
        }
        # Should not raise
        assert_acyclic(graph)

    def test_valid_dag_with_multiple_paths(self):
        """Valid DAG with multiple paths should be accepted.
        
        Structure:
            A → B → D
            A → C → D
        """
        graph = {
            "A": ["B", "C"],
            "B": ["D"],
            "C": ["D"],
            "D": []
        }
        # Should not raise
        assert_acyclic(graph)

    def test_simple_cycle_two_nodes(self):
        """Simple cycle A → B → A should be detected."""
        graph = {
            "A": ["B"],
            "B": ["A"]
        }
        with pytest.raises(CircularDependencyError) as exc_info:
            assert_acyclic(graph)
        
        # Error message should mention the cycle
        assert "Circular dependency detected" in str(exc_info.value)

    def test_self_cycle(self):
        """Self-cycle A → A should be detected."""
        graph = {
            "A": ["A"]
        }
        with pytest.raises(CircularDependencyError) as exc_info:
            assert_acyclic(graph)
        
        assert "Circular dependency detected" in str(exc_info.value)
        assert "A" in str(exc_info.value)

    def test_complex_cycle_three_nodes(self):
        """Complex cycle A → B → C → A should be detected."""
        graph = {
            "A": ["B"],
            "B": ["C"],
            "C": ["A"]
        }
        with pytest.raises(CircularDependencyError) as exc_info:
            assert_acyclic(graph)
        
        assert "Circular dependency detected" in str(exc_info.value)

    def test_disconnected_components(self):
        """Graph with disconnected components should be valid if no cycles.
        
        Structure:
            A → B
            C → D
        (A-B and C-D are separate components)
        """
        graph = {
            "A": ["B"],
            "B": [],
            "C": ["D"],
            "D": []
        }
        # Should not raise
        assert_acyclic(graph)

    def test_disconnected_components_with_cycle(self):
        """Cycle in one component should be detected even with other valid components.
        
        Structure:
            A → B (valid)
            C → D → C (cycle)
        """
        graph = {
            "A": ["B"],
            "B": [],
            "C": ["D"],
            "D": ["C"]
        }
        with pytest.raises(CircularDependencyError):
            assert_acyclic(graph)

    def test_integer_node_ids(self):
        """Graph with integer node IDs should work correctly."""
        graph = {
            1: [2],
            2: [3],
            3: []
        }
        # Should not raise
        assert_acyclic(graph)

    def test_integer_node_ids_with_cycle(self):
        """Cycle detection should work with integer node IDs."""
        graph = {
            1: [2],
            2: [3],
            3: [1]
        }
        with pytest.raises(CircularDependencyError) as exc_info:
            assert_acyclic(graph)
        
        assert "Circular dependency detected" in str(exc_info.value)

    def test_mixed_string_and_integer_ids(self):
        """Graph with mixed string and integer IDs should work."""
        graph = {
            "A": [1],
            1: [2],
            2: ["B"],
            "B": []
        }
        # Should not raise
        assert_acyclic(graph)


class TestOrchestratorIntegration:
    """Tests for WorkflowOrchestrator integration with dependency validation."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        db = Database(db_path)
        yield db
        
        # Cleanup
        db.close()
        if db_path.exists():
            db_path.unlink()

    @pytest.fixture
    def mock_queue_manager(self):
        """Mock queue manager for testing."""
        class MockQueueManager:
            async def enqueue(self, **kwargs):
                pass
            
            def register_callback(self, job_id, callback):
                pass
        
        return MockQueueManager()

    def test_workflow_with_valid_dag_accepted(self, temp_db, mock_queue_manager):
        """Workflow with valid DAG should be accepted by orchestrator."""
        orchestrator = WorkflowOrchestrator(temp_db, mock_queue_manager)
        
        workflow = WorkflowDefinition(
            workflow_id=1,
            name="Valid Workflow",
            description="Test workflow with valid DAG",
            nodes=[
                WorkflowNode(
                    node_id="node1",
                    job_name="job1",
                    template="test template 1",
                    parameters={},
                    dependencies=[]
                ),
                WorkflowNode(
                    node_id="node2",
                    job_name="job2",
                    template="test template 2",
                    parameters={},
                    dependencies=["node1"]
                ),
                WorkflowNode(
                    node_id="node3",
                    job_name="job3",
                    template="test template 3",
                    parameters={},
                    dependencies=["node2"]
                )
            ]
        )
        
        # Should not raise
        orchestrator.register_workflow(workflow)

    def test_workflow_with_cycle_rejected(self, temp_db, mock_queue_manager):
        """Workflow with circular dependencies should be rejected."""
        from src.core.orchestrator import CircularDependencyError as OrchestratorCircularDependencyError

        orchestrator = WorkflowOrchestrator(temp_db, mock_queue_manager)

        workflow = WorkflowDefinition(
            workflow_id=2,
            name="Invalid Workflow",
            description="Test workflow with cycle",
            nodes=[
                WorkflowNode(
                    node_id="node1",
                    job_name="job1",
                    template="test template 1",
                    parameters={},
                    dependencies=["node2"]
                ),
                WorkflowNode(
                    node_id="node2",
                    job_name="job2",
                    template="test template 2",
                    parameters={},
                    dependencies=["node1"]
                )
            ]
        )

        # Should raise CircularDependencyError
        with pytest.raises(OrchestratorCircularDependencyError) as exc_info:
            orchestrator.register_workflow(workflow)

        # Check error message contains workflow name and cycle info
        error_msg = str(exc_info.value)
        assert "Invalid Workflow" in error_msg or "Circular" in error_msg


class TestQueueManagerIntegration:
    """Tests for QueueManager integration with dependency validation."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        
        db = Database(db_path)
        yield db
        
        # Cleanup
        db.close()
        if db_path.exists():
            db_path.unlink()

    @pytest.fixture
    def queue_manager(self, temp_db):
        """Create a QueueManager instance for testing."""
        qm = QueueManager(temp_db)
        return qm

    @pytest.mark.asyncio
    async def test_valid_dependencies_accepted(self, queue_manager, temp_db):
        """Jobs with valid dependencies should be accepted."""
        # Create jobs
        job1_id = temp_db.create_job("job1", "/tmp/job1", "test input 1")
        job2_id = temp_db.create_job("job2", "/tmp/job2", "test input 2")
        
        # Job2 depends on Job1 (valid)
        await queue_manager.enqueue(job_id=job1_id, priority=2)
        await queue_manager.enqueue(job_id=job2_id, priority=2, dependencies=[job1_id])
        
        # Both jobs should be in queue
        assert job1_id in queue_manager._jobs
        assert job2_id in queue_manager._jobs

    @pytest.mark.asyncio
    async def test_self_dependency_rejected(self, queue_manager, temp_db):
        """Job depending on itself should be rejected."""
        job_id = temp_db.create_job("job1", "/tmp/job1", "test input")
        
        # Try to make job depend on itself
        from src.core.queue_manager import CircularDependencyError as QMCircularDependencyError
        
        with pytest.raises(QMCircularDependencyError) as exc_info:
            await queue_manager.enqueue(job_id=job_id, priority=2, dependencies=[job_id])
        
        assert "cannot depend on itself" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_circular_dependency_rejected(self, queue_manager, temp_db):
        """Circular dependencies should be rejected."""
        # Create jobs
        job1_id = temp_db.create_job("job1", "/tmp/job1", "test input 1")
        job2_id = temp_db.create_job("job2", "/tmp/job2", "test input 2")
        
        # Enqueue job1
        await queue_manager.enqueue(job_id=job1_id, priority=2, dependencies=[job2_id])
        
        # Try to make job2 depend on job1 (creates cycle)
        from src.core.queue_manager import CircularDependencyError as QMCircularDependencyError
        
        with pytest.raises(QMCircularDependencyError) as exc_info:
            await queue_manager.enqueue(job_id=job2_id, priority=2, dependencies=[job1_id])
        
        assert "circular" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_non_existent_dependency_rejected(self, queue_manager, temp_db):
        """Job depending on non-existent job should be rejected."""
        job_id = temp_db.create_job("job1", "/tmp/job1", "test input")
        
        from src.core.queue_manager import InvalidJobError
        
        # Try to depend on job ID 9999 which doesn't exist
        with pytest.raises(InvalidJobError) as exc_info:
            await queue_manager.enqueue(job_id=job_id, priority=2, dependencies=[9999])
        
        assert "9999" in str(exc_info.value)
        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_complex_dependency_chain_validated(self, queue_manager, temp_db):
        """Complex dependency chains should be validated correctly.

        Structure:
            job1 (no deps)
            job2 → job1
            job3 → job2
            job4 → job3
        """
        # Create jobs
        job1_id = temp_db.create_job("job1", "/tmp/job1", "test input 1")
        job2_id = temp_db.create_job("job2", "/tmp/job2", "test input 2")
        job3_id = temp_db.create_job("job3", "/tmp/job3", "test input 3")
        job4_id = temp_db.create_job("job4", "/tmp/job4", "test input 4")
        
        # Enqueue in dependency order
        await queue_manager.enqueue(job_id=job1_id, priority=2)
        await queue_manager.enqueue(job_id=job2_id, priority=2, dependencies=[job1_id])
        await queue_manager.enqueue(job_id=job3_id, priority=2, dependencies=[job2_id])
        await queue_manager.enqueue(job_id=job4_id, priority=2, dependencies=[job3_id])
        
        # All jobs should be in queue
        assert len(queue_manager._jobs) == 4

    @pytest.mark.asyncio
    async def test_complex_cycle_detection(self, queue_manager, temp_db):
        """Complex cycles in dependency chains should be detected.

        Attempt to create:
            job1 → job2 → job3 → job1 (cycle)
        """
        # Create jobs
        job1_id = temp_db.create_job("job1", "/tmp/job1", "test input 1")
        job2_id = temp_db.create_job("job2", "/tmp/job2", "test input 2")
        job3_id = temp_db.create_job("job3", "/tmp/job3", "test input 3")
        
        # Build chain
        await queue_manager.enqueue(job_id=job1_id, priority=2, dependencies=[job3_id])
        await queue_manager.enqueue(job_id=job2_id, priority=2, dependencies=[job1_id])
        
        # Try to close the cycle
        from src.core.queue_manager import CircularDependencyError as QMCircularDependencyError
        
        with pytest.raises(QMCircularDependencyError):
            await queue_manager.enqueue(job_id=job3_id, priority=2, dependencies=[job2_id])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
