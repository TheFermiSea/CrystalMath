"""
Complex workflow: Basis set convergence scan with aggregation.

This demonstrates:
- Parallel node execution (multiple basis sets)
- Aggregation node (collect and analyze energies)
- Parameter variation across multiple calculations
"""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.workflow import Workflow, NodeType


async def main():
    """Run basis set convergence scan workflow."""

    # Create workflow
    wf = Workflow(
        workflow_id="convergence_scan",
        name="Basis Set Convergence Scan",
        description="Run calculations with increasing basis set quality and aggregate results"
    )

    # Define basis sets to test
    basis_sets = [
        ("sto-3g", "STO-3G"),
        ("6-31g", "6-31G"),
        ("6-31gd", "6-31G(d)"),
        ("6-311gd", "6-311G(d)"),
        ("6-311gdp", "6-311G(d,p)")
    ]

    # Create calculation node for each basis set
    calc_nodes = []
    for basis_id, basis_name in basis_sets:
        node = wf.add_node(
            template="single_point",
            params={
                "basis": basis_name,
                "functional": "PBE",
                "conv_tol": 1e-8
            },
            node_id=f"calc_{basis_id}"
        )
        calc_nodes.append(node.node_id)

    # Add aggregation node to collect energies
    agg = wf.add_aggregation_node(
        node_id="collect_energies",
        aggregation_func="collect",
        dependencies=calc_nodes
    )

    # Add edges from each calculation to the aggregation node
    for calc_id in calc_nodes:
        wf.add_dependency(calc_id, "collect_energies")

    # Add analysis node that depends on aggregation
    analysis = wf.add_node(
        template="convergence_analysis",
        params={
            "energies": "{{ collect_energies.aggregated_value }}",
            "threshold": 1e-5  # mHartree convergence threshold
        },
        node_id="analysis"
    )

    # Connect aggregation to analysis
    wf.add_dependency("collect_energies", "analysis")

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
    print("Workflow structure:")
    print(wf.to_ascii())
    print()

    # Show execution plan
    print("Execution plan:")
    order = wf._topological_sort()
    for i, node_id in enumerate(order, 1):
        node = wf.nodes[node_id]
        print(f"{i}. {node_id} [{node.node_type.value}]")
        if node.dependencies:
            print(f"   Depends on: {', '.join(node.dependencies)}")
    print()

    # Execute workflow with high parallelism
    print("Executing workflow (up to 5 parallel calculations)...")
    await wf.execute(max_parallel=5)

    # Show results
    print("\nWorkflow execution complete!")
    print(f"Status: {wf.get_status().value}")

    progress = wf.get_progress()
    print(f"Progress: {progress['completed']}/{progress['total_nodes']} nodes completed")
    print(f"  Percent complete: {progress['percent_complete']:.1f}%")

    # Show aggregated results
    print("\nAggregation results:")
    agg_node = wf.nodes["collect_energies"]
    if agg_node.result_data:
        print(f"  Total calculations: {agg_node.result_data['count']}")
        print(f"  Energy values: {agg_node.result_data['aggregated_value']}")

    # Save workflow
    output_path = Path("convergence_scan.json")
    wf.to_json(output_path)
    print(f"\n✓ Workflow saved to {output_path}")

    # Generate visualization
    dot_path = Path("convergence_scan.dot")
    with open(dot_path, 'w') as f:
        f.write(wf.to_graphviz())
    print(f"✓ GraphViz diagram saved to {dot_path}")
    print("  Render with: dot -Tpng convergence_scan.dot -o convergence_scan.png")


if __name__ == "__main__":
    asyncio.run(main())
