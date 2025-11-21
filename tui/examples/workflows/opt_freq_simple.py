"""
Simple workflow: Geometry optimization followed by frequency calculation.

This demonstrates:
- Sequential dependency (freq depends on opt)
- Parameter propagation (freq uses .f9 from opt)
- Basic two-node workflow
"""

import asyncio
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.workflow import Workflow, NodeType


async def main():
    """Run simple optimization → frequency workflow."""

    # Create workflow
    wf = Workflow(
        workflow_id="opt_freq_simple",
        name="Optimization → Frequency",
        description="Simple two-step workflow: optimize geometry then calculate frequencies"
    )

    # Add optimization node
    opt = wf.add_node(
        template="optimization",
        params={
            "basis": "sto-3g",
            "functional": "PBE",
            "conv_tol": 1e-6
        },
        node_id="opt",
        max_retries=1
    )

    # Add frequency calculation node (uses .f9 from optimization)
    freq = wf.add_node(
        template="frequency",
        params={
            "basis": "sto-3g",
            "functional": "PBE",
            "guess_file": "{{ opt.f9 }}",  # Parameter propagation
            "temperature": 298.15
        },
        node_id="freq"
    )

    # Add dependency: freq depends on opt
    wf.add_dependency("opt", "freq")

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

    # Show GraphViz representation
    print("GraphViz DOT format:")
    print(wf.to_graphviz())
    print()

    # Execute workflow
    print("Executing workflow...")
    await wf.execute()

    # Show results
    print("\nWorkflow execution complete!")
    print(f"Status: {wf.get_status().value}")

    progress = wf.get_progress()
    print(f"Progress: {progress['completed']}/{progress['total_nodes']} nodes completed")
    print(f"  Completed: {progress['completed']}")
    print(f"  Failed: {progress['failed']}")
    print(f"  Skipped: {progress['skipped']}")

    # Show node results
    print("\nNode results:")
    for node_id, node in wf.nodes.items():
        print(f"  {node_id}:")
        print(f"    Status: {node.status.value}")
        if node.result_data:
            print(f"    Results: {node.result_data}")

    # Save workflow to file
    output_path = Path("opt_freq_simple.json")
    wf.to_json(output_path)
    print(f"\n✓ Workflow saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
