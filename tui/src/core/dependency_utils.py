"""
Shared dependency validation utilities.

This module provides consolidated dependency graph validation
used by both WorkflowOrchestrator and QueueManager to ensure
consistent validation logic across the codebase.
"""

from typing import Dict, List, Set, Union


class CircularDependencyError(Exception):
    """Raised when circular dependencies are detected in a dependency graph."""
    pass


def assert_acyclic(
    graph: Dict[Union[str, int], List[Union[str, int]]],
    error_context: str = ""
) -> None:
    """
    Validate that a dependency graph contains no cycles.

    Uses depth-first search (DFS) with recursion stack tracking to detect cycles.
    This algorithm efficiently detects cycles in O(V + E) time complexity.

    Args:
        graph: Adjacency list representing dependencies.
               Keys are node IDs, values are lists of dependency IDs.
               Example: {"A": ["B", "C"], "B": ["C"], "C": []}
               means A depends on B and C, B depends on C, C has no dependencies.
        error_context: Optional context string to include in error message.
                      Example: "workflow 'MyWorkflow'" or "job queue"

    Raises:
        CircularDependencyError: If a cycle is detected in the graph.

    Examples:
        >>> # Valid DAG (no cycle)
        >>> graph = {"A": ["B"], "B": ["C"], "C": []}
        >>> assert_acyclic(graph)  # No exception

        >>> # Cycle detection
        >>> graph = {"A": ["B"], "B": ["A"]}
        >>> assert_acyclic(graph)  # Raises CircularDependencyError

        >>> # With context
        >>> assert_acyclic(graph, error_context="workflow 'Test'")
        >>> # Raises: "Circular dependency detected in workflow 'Test' involving node 'A'"
    """
    visited: Set[Union[str, int]] = set()
    rec_stack: Set[Union[str, int]] = set()

    def has_cycle(node_id: Union[str, int]) -> bool:
        """
        DFS helper to detect cycles.

        Args:
            node_id: Current node being visited

        Returns:
            True if a cycle is detected, False otherwise
        """
        visited.add(node_id)
        rec_stack.add(node_id)

        # Check all dependencies
        for dep_id in graph.get(node_id, []):
            if dep_id not in visited:
                if has_cycle(dep_id):
                    return True
            elif dep_id in rec_stack:
                # Found a back edge (cycle)
                return True

        rec_stack.remove(node_id)
        return False

    # Check all nodes in the graph
    for node_id in graph:
        if node_id not in visited:
            if has_cycle(node_id):
                context_str = f" in {error_context}" if error_context else ""
                raise CircularDependencyError(
                    f"Circular dependency detected{context_str} involving node '{node_id}'"
                )
