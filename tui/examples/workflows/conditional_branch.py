"""
Advanced workflow: Conditional branching based on calculation results.

This demonstrates:
- Condition nodes for branching logic
- Different execution paths based on convergence
- Retry mechanism with different parameters
"""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.workflow import Workflow, NodeType


async def main():
    """Run workflow with conditional branching."""

    # Create workflow
    wf = Workflow(
        workflow_id="conditional_opt",
        name="Optimization with Conditional Restart",
        description="Optimize geometry, check convergence, and restart with tighter parameters if needed"
    )

    # Initial optimization attempt
    opt1 = wf.add_node(
        template="optimization",
        params={
            "basis": "sto-3g",
            "functional": "PBE",
            "conv_tol": 1e-5,
            "max_cycles": 50
        },
        node_id="opt_initial"
    )

    # Condition node: Check if optimization converged
    check = wf.add_condition_node(
        node_id="check_convergence",
        condition_expr="opt_initial['converged'] == True",
        true_branch=["freq_calc"],
        false_branch=["opt_retry"],
        dependencies=["opt_initial"]
    )
    wf.add_dependency("opt_initial", "check_convergence")

    # Branch 1 (True): Run frequency calculation on converged geometry
    freq = wf.add_node(
        template="frequency",
        params={
            "basis": "sto-3g",
            "functional": "PBE",
            "guess_file": "{{ opt_initial.f9 }}"
        },
        node_id="freq_calc"
    )
    wf.add_dependency("check_convergence", "freq_calc", condition="converged")

    # Branch 2 (False): Retry optimization with tighter convergence
    opt2 = wf.add_node(
        template="optimization",
        params={
            "basis": "sto-3g",
            "functional": "PBE",
            "conv_tol": 1e-6,  # Tighter tolerance
            "max_cycles": 100,  # More cycles
            "guess_file": "{{ opt_initial.f9 }}"  # Start from previous geometry
        },
        node_id="opt_retry"
    )
    wf.add_dependency("check_convergence", "opt_retry", condition="not converged")

    # After retry, always run frequency
    freq2 = wf.add_node(
        template="frequency",
        params={
            "basis": "sto-3g",
            "functional": "PBE",
            "guess_file": "{{ opt_retry.f9 }}"
        },
        node_id="freq_after_retry"
    )
    wf.add_dependency("opt_retry", "freq_after_retry")

    # Validate workflow
    print("Validating workflow...")
    errors = wf.validate()

    if errors:
        print("❌ Validation failed:")
        for err in errors:
            print(f"  - {err}")
        return

    print("✓ Workflow is valid\n")

    # Display workflow structure
    print("Workflow structure (with conditional branches):")
    print(wf.to_ascii())
    print()

    # Show GraphViz representation
    print("GraphViz DOT format:")
    dot_content = wf.to_graphviz()
    print(dot_content)
    print()

    # Execute workflow
    print("Executing workflow...")
    print("Note: Execution will follow one branch based on convergence check")
    print()

    await wf.execute()

    # Show results
    print("\nWorkflow execution complete!")
    print(f"Status: {wf.get_status().value}")

    progress = wf.get_progress()
    print(f"\nProgress:")
    print(f"  Total nodes: {progress['total_nodes']}")
    print(f"  Completed: {progress['completed']}")
    print(f"  Failed: {progress['failed']}")
    print(f"  Skipped: {progress['skipped']}")

    # Show which branch was taken
    print("\nExecution path:")
    for node_id in wf.execution_order:
        node = wf.nodes[node_id]
        symbol = {
            "COMPLETED": "✓",
            "FAILED": "✗",
            "SKIPPED": "○"
        }.get(node.status.value, "?")
        print(f"  {symbol} {node_id} [{node.status.value}]")

    # Save workflow
    output_path = Path("conditional_branch.json")
    wf.to_json(output_path)
    print(f"\n✓ Workflow saved to {output_path}")

    # Save diagram
    dot_path = Path("conditional_branch.dot")
    with open(dot_path, 'w') as f:
        f.write(dot_content)
    print(f"✓ Workflow diagram saved to {dot_path}")


if __name__ == "__main__":
    asyncio.run(main())
