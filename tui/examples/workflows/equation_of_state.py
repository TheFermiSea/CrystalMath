"""
Advanced workflow: Equation of State (EOS) calculation.

This demonstrates:
- Multiple parallel calculations at different volumes
- Aggregation of energy-volume data
- Data fitting and analysis
"""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.workflow import Workflow, NodeType


async def main():
    """Run Equation of State workflow."""

    # Create workflow
    wf = Workflow(
        workflow_id="eos_calculation",
        name="Equation of State",
        description="Calculate E(V) curve by running calculations at multiple volumes"
    )

    # Reference equilibrium volume
    v0 = 100.0  # Å³

    # Define volume scaling factors
    volumes = [
        (0.94, v0 * 0.94),
        (0.96, v0 * 0.96),
        (0.98, v0 * 0.98),
        (1.00, v0 * 1.00),
        (1.02, v0 * 1.02),
        (1.04, v0 * 1.04),
        (1.06, v0 * 1.06)
    ]

    # Create calculation node for each volume
    calc_nodes = []
    for scale, volume in volumes:
        node_id = f"calc_v{scale:.2f}".replace(".", "_")

        node = wf.add_node(
            template="single_point",
            params={
                "basis": "6-31g",
                "functional": "PBE",
                "volume": volume,
                "scale_factor": scale,
                "conv_tol": 1e-8
            },
            node_id=node_id
        )
        calc_nodes.append(node_id)

    # Add aggregation node to collect E(V) data
    collect = wf.add_aggregation_node(
        node_id="collect_ev_data",
        aggregation_func="collect",
        dependencies=calc_nodes
    )

    # Add edges from each calculation to the aggregation node
    for calc_id in calc_nodes:
        wf.add_dependency(calc_id, "collect_ev_data")

    # Add EOS fitting node
    fit = wf.add_node(
        template="eos_fit",
        params={
            "energies": "{{ collect_ev_data.aggregated_value }}",
            "equation": "birch_murnaghan",  # Birch-Murnaghan EOS
            "order": 3
        },
        node_id="eos_fit"
    )
    wf.add_dependency("collect_ev_data", "eos_fit")

    # Add analysis node to extract properties
    analysis = wf.add_node(
        template="eos_analysis",
        params={
            "fit_results": "{{ eos_fit.parameters }}",
            "extract": ["v0", "e0", "b0", "bp"]  # V₀, E₀, B₀, B'
        },
        node_id="extract_properties"
    )
    wf.add_dependency("eos_fit", "extract_properties")

    # Validate workflow
    print("Validating workflow...")
    errors = wf.validate()

    if errors:
        print("❌ Validation failed:")
        for err in errors:
            print(f"  - {err}")
        return

    print("✓ Workflow is valid\n")

    # Display workflow info
    print(f"Equation of State Workflow")
    print("=" * 60)
    print(f"Reference volume: {v0:.2f} Å³")
    print(f"Number of volume points: {len(volumes)}")
    print(f"Volume range: {volumes[0][1]:.2f} - {volumes[-1][1]:.2f} Å³")
    print()

    # Show execution plan
    print("Execution plan:")
    print(f"1. Run {len(calc_nodes)} calculations in parallel (volumes)")
    print("2. Collect E(V) data")
    print("3. Fit Birch-Murnaghan equation of state")
    print("4. Extract equilibrium properties (V₀, E₀, B₀, B')")
    print()

    # Show ASCII representation
    print("Workflow structure:")
    print(wf.to_ascii())
    print()

    # Execute workflow with high parallelism
    print("Executing workflow (up to 7 parallel calculations)...")
    await wf.execute(max_parallel=7)

    # Show results
    print("\nWorkflow execution complete!")
    print(f"Status: {wf.get_status().value}")

    progress = wf.get_progress()
    print(f"\nProgress:")
    print(f"  Total nodes: {progress['total_nodes']}")
    print(f"  Completed: {progress['completed']} ({progress['percent_complete']:.1f}%)")
    print(f"  Failed: {progress['failed']}")

    # Show collected data
    print("\nE(V) Data collected:")
    collect_node = wf.nodes["collect_ev_data"]
    if collect_node.result_data:
        print(f"  Number of points: {collect_node.result_data['count']}")
        energies = collect_node.result_data['aggregated_value']
        for i, (scale, _) in enumerate(volumes):
            if i < len(energies):
                print(f"    V = {scale:.2f}V₀: E = {energies[i]:.6f} Hartree")

    # Show fit results
    print("\nEOS Fit Results:")
    fit_node = wf.nodes["eos_fit"]
    if fit_node.result_data:
        print(f"  {fit_node.result_data}")

    # Save workflow
    output_path = Path("equation_of_state.json")
    wf.to_json(output_path)
    print(f"\n✓ Workflow saved to {output_path}")

    # Generate visualization
    dot_path = Path("equation_of_state.dot")
    with open(dot_path, 'w') as f:
        f.write(wf.to_graphviz())
    print(f"✓ GraphViz diagram saved to {dot_path}")
    print("  Render with: dot -Tpng equation_of_state.dot -o equation_of_state.png")


if __name__ == "__main__":
    asyncio.run(main())
