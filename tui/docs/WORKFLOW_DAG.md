# Workflow DAG System Documentation

## Overview

The Workflow DAG (Directed Acyclic Graph) system provides a powerful framework for defining, validating, and executing multi-step CRYSTAL calculation workflows with complex dependencies.

## Key Concepts

### Workflow

A **Workflow** represents a complete calculation pipeline consisting of multiple interconnected nodes. Each workflow has:

- **Unique ID**: Identifier for the workflow
- **Name**: Human-readable name
- **Description**: Detailed explanation of workflow purpose
- **Nodes**: Individual calculation or processing steps
- **Edges**: Dependencies between nodes
- **Status**: Current execution state

### Nodes

**WorkflowNode** represents a single step in the workflow. There are four types of nodes:

#### 1. Calculation Nodes (CALCULATION)

Execute CRYSTAL calculations (optimization, frequency, band structure, etc.).

```python
node = workflow.add_node(
    template="optimization",
    params={"basis": "sto-3g", "functional": "PBE"},
    node_id="opt"
)
```

#### 2. Data Transfer Nodes (DATA_TRANSFER)

Copy files between calculation nodes (e.g., .f9 wave function files).

```python
transfer = workflow.add_data_transfer_node(
    node_id="copy_wavefunction",
    source_node="opt",
    source_files=["*.f9", "*.f98"],
    target_node="freq"
)
```

#### 3. Condition Nodes (CONDITION)

Branch execution based on calculation results.

```python
condition = workflow.add_condition_node(
    node_id="check_convergence",
    condition_expr="opt['converged'] == True",
    true_branch=["freq"],
    false_branch=["restart_opt"],
    dependencies=["opt"]
)
```

#### 4. Aggregation Nodes (AGGREGATION)

Combine results from multiple calculations.

```python
agg = workflow.add_aggregation_node(
    node_id="average_energy",
    aggregation_func="mean",  # or "min", "max", "collect"
    dependencies=["calc1", "calc2", "calc3"]
)
```

### Dependencies

Dependencies define the execution order. A node cannot start until all its dependencies are completed.

```python
workflow.add_dependency("opt", "freq")  # freq waits for opt
```

### Parameter Propagation

Use Jinja2 templates to pass data between nodes:

```python
# Optimization node produces: result_data = {"f9": "/path/to/opt.f9", "energy": -123.456}

# Frequency node uses optimization output:
freq = workflow.add_node(
    "frequency",
    params={
        "guess_file": "{{ opt.f9 }}",      # Resolves to "/path/to/opt.f9"
        "ref_energy": "{{ opt.energy }}"   # Resolves to "-123.456"
    },
    node_id="freq"
)
```

## Workflow Lifecycle

### 1. Construction

Build the workflow by adding nodes and dependencies:

```python
from src.core.workflow import Workflow

# Create workflow
wf = Workflow(
    workflow_id="my_workflow",
    name="My Calculation Pipeline",
    description="Detailed description"
)

# Add nodes
opt = wf.add_node("optimization", {"basis": "sto-3g"}, node_id="opt")
freq = wf.add_node("frequency", {"basis": "sto-3g"}, node_id="freq")

# Add dependencies
wf.add_dependency("opt", "freq")
```

### 2. Validation

Validate the workflow before execution:

```python
errors = wf.validate()

if errors:
    print("Validation errors:")
    for err in errors:
        print(f"  - {err}")
else:
    print("✓ Workflow is valid")
```

Validation checks:
- ✅ No cycles in the DAG
- ✅ All dependencies exist
- ✅ Parameter templates reference valid nodes
- ✅ Condition nodes have expressions
- ✅ Data transfer nodes have valid sources
- ✅ No orphaned nodes (disconnected components)

### 3. Execution

Execute the workflow asynchronously:

```python
import asyncio

# Execute with parallel execution
await wf.execute(max_parallel=4)

# Check status
print(f"Status: {wf.get_status().value}")
```

Execution features:
- **Topological ordering**: Ensures dependencies are respected
- **Parallel execution**: Independent nodes run concurrently
- **Retry mechanism**: Configurable per-node retries on failure
- **Failure handling**: Failed nodes skip dependent nodes
- **Progress tracking**: Real-time execution progress

### 4. Monitoring

Track workflow progress during execution:

```python
progress = wf.get_progress()
print(f"Completed: {progress['completed']}/{progress['total_nodes']}")
print(f"Progress: {progress['percent_complete']:.1f}%")
print(f"Running: {progress['running']}")
print(f"Failed: {progress['failed']}")
```

### 5. Results

Access node results after execution:

```python
opt_node = wf.nodes["opt"]
print(f"Status: {opt_node.status.value}")
print(f"Results: {opt_node.result_data}")

if opt_node.status == NodeStatus.COMPLETED:
    energy = opt_node.result_data["energy"]
    print(f"Optimized energy: {energy} Hartree")
```

### 6. Persistence

Save and load workflows:

```python
from pathlib import Path

# Save to JSON
wf.to_json(Path("my_workflow.json"))

# Load from JSON
loaded = Workflow.from_json(Path("my_workflow.json"))

# Or use dictionaries
data = wf.to_dict()
restored = Workflow.from_dict(data)
```

## Visualization

### ASCII Art

Simple text-based workflow representation:

```python
print(wf.to_ascii())
```

Output:
```
Workflow: Optimization → Frequency (RUNNING)
============================================================
1. ✓ opt [CALCULATION]
2. ● freq [CALCULATION] (depends on: opt)
```

Symbols:
- `○` PENDING
- `◐` READY
- `●` RUNNING
- `✓` COMPLETED
- `✗` FAILED
- `⊘` SKIPPED

### GraphViz DOT Format

Generate publication-quality diagrams:

```python
# Generate DOT format
dot_content = wf.to_graphviz()

# Save to file
with open("workflow.dot", 'w') as f:
    f.write(dot_content)

# Render to PNG
# $ dot -Tpng workflow.dot -o workflow.png
```

Features:
- Colored nodes by status
- Directional edges showing dependencies
- Conditional edges labeled
- Node types indicated

## Common Workflow Patterns

### Pattern 1: Sequential Pipeline

Linear chain of calculations:

```python
wf = Workflow("sequential", "Linear Pipeline")

opt = wf.add_node("optimization", {...}, node_id="opt")
freq = wf.add_node("frequency", {...}, node_id="freq")
dos = wf.add_node("dos", {...}, node_id="dos")

wf.add_dependency("opt", "freq")
wf.add_dependency("freq", "dos")
```

```
opt → freq → dos
```

### Pattern 2: Parallel Fan-Out

One calculation feeds multiple independent analyses:

```python
wf = Workflow("fanout", "Parallel Analysis")

opt = wf.add_node("optimization", {...}, node_id="opt")
dos = wf.add_node("dos", {...}, node_id="dos")
band = wf.add_node("band_structure", {...}, node_id="band")
charge = wf.add_node("charge_density", {...}, node_id="charge")

wf.add_dependency("opt", "dos")
wf.add_dependency("opt", "band")
wf.add_dependency("opt", "charge")
```

```
       ┌─→ dos
opt ───┼─→ band
       └─→ charge
```

### Pattern 3: Diamond Convergence

Multiple paths reconverge at a single node:

```python
wf = Workflow("diamond", "Diamond Pattern")

init = wf.add_node("initial_guess", {...}, node_id="init")
path1 = wf.add_node("method_a", {...}, node_id="path1")
path2 = wf.add_node("method_b", {...}, node_id="path2")
final = wf.add_node("compare_results", {...}, node_id="final")

wf.add_dependency("init", "path1")
wf.add_dependency("init", "path2")
wf.add_dependency("path1", "final")
wf.add_dependency("path2", "final")
```

```
      ┌─→ path1 ─┐
init ─┤           ├─→ final
      └─→ path2 ─┘
```

### Pattern 4: Convergence Scan

Parallel calculations with aggregation:

```python
wf = Workflow("scan", "Convergence Scan")

# Multiple calculations at different parameters
calcs = []
for basis in ["sto-3g", "6-31g", "6-311g"]:
    node = wf.add_node("single_point", {"basis": basis}, node_id=f"calc_{basis}")
    calcs.append(node.node_id)

# Aggregate results
agg = wf.add_aggregation_node("collect", "collect", dependencies=calcs)

# Analyze convergence
analysis = wf.add_node("convergence_analysis", {...}, node_id="analysis")
wf.add_dependency("collect", "analysis")
```

```
calc_1 ─┐
calc_2 ─┼─→ collect → analysis
calc_3 ─┘
```

### Pattern 5: Conditional Branching

Different paths based on results:

```python
wf = Workflow("conditional", "Conditional Workflow")

opt = wf.add_node("optimization", {...}, node_id="opt")

check = wf.add_condition_node(
    "check_convergence",
    condition_expr="opt['converged'] == True",
    true_branch=["freq"],
    false_branch=["restart"],
    dependencies=["opt"]
)

freq = wf.add_node("frequency", {...}, node_id="freq")
restart = wf.add_node("restart_opt", {...}, node_id="restart")

wf.add_dependency("opt", "check_convergence")
wf.add_dependency("check_convergence", "freq", condition="converged")
wf.add_dependency("check_convergence", "restart", condition="not converged")
```

```
       ┌─ if converged ──→ freq
opt → check
       └─ if not converged ──→ restart
```

## Advanced Features

### Retry Mechanism

Configure automatic retries for failed nodes:

```python
node = wf.add_node(
    "optimization",
    params={...},
    node_id="opt",
    max_retries=3  # Retry up to 3 times on failure
)
```

### Failure Propagation

When a node fails, all dependent nodes are automatically skipped:

```python
# If 'opt' fails:
opt → freq → dos
#     ↓      ↓
#   FAILED  SKIPPED
```

### Metadata

Store custom metadata with workflows:

```python
wf = Workflow(
    workflow_id="my_workflow",
    name="My Workflow",
    metadata={
        "project": "Material X",
        "author": "Research Team",
        "version": "1.0",
        "tags": ["optimization", "frequency"]
    }
)
```

### Checkpointing

Workflows are automatically checkpointed during execution. Resume from failure:

```python
# Save current state
wf.to_json(Path("checkpoint.json"))

# Later, resume from checkpoint
wf = Workflow.from_json(Path("checkpoint.json"))
await wf.execute()  # Continues from where it left off
```

## API Reference

### Workflow Class

#### Constructor

```python
Workflow(
    workflow_id: str,
    name: str,
    description: str = "",
    metadata: Optional[Dict[str, Any]] = None
)
```

#### Methods

**add_node(template, params, node_id, node_type, max_retries, \*\*kwargs) → WorkflowNode**

Add a calculation node to the workflow.

**add_data_transfer_node(node_id, source_node, source_files, target_node) → WorkflowNode**

Add a data transfer node.

**add_condition_node(node_id, condition_expr, true_branch, false_branch, dependencies) → WorkflowNode**

Add a conditional branching node.

**add_aggregation_node(node_id, aggregation_func, dependencies) → WorkflowNode**

Add an aggregation node.

**add_dependency(from_node, to_node, condition) → None**

Add a dependency edge.

**validate() → List[str]**

Validate the workflow DAG. Returns list of error messages.

**async execute(max_parallel=4) → None**

Execute the workflow asynchronously.

**get_ready_nodes() → List[WorkflowNode]**

Get nodes ready to execute.

**get_status() → WorkflowStatus**

Get overall workflow status.

**get_progress() → Dict[str, Any]**

Get execution progress metrics.

**to_dict() → Dict[str, Any]**

Convert to dictionary for serialization.

**to_json(filepath) → None**

Save to JSON file.

**from_dict(data) → Workflow** (classmethod)

Create from dictionary.

**from_json(filepath) → Workflow** (classmethod)

Load from JSON file.

**to_graphviz() → str**

Generate GraphViz DOT format.

**to_ascii() → str**

Generate ASCII art representation.

### WorkflowNode Class

#### Attributes

- `node_id`: Unique identifier
- `node_type`: NodeType enum (CALCULATION, DATA_TRANSFER, CONDITION, AGGREGATION)
- `job_template`: Template name (for CALCULATION nodes)
- `parameters`: Node parameters (dict)
- `dependencies`: List of node IDs this node depends on
- `status`: NodeStatus enum (PENDING, READY, RUNNING, COMPLETED, FAILED, SKIPPED)
- `result_data`: Results from node execution
- `error_message`: Error message if failed
- `started_at`: Timestamp when node started
- `completed_at`: Timestamp when node completed
- `retry_count`: Current retry attempt
- `max_retries`: Maximum retry attempts

### Enums

**NodeType**
- `CALCULATION`: CRYSTAL calculation
- `DATA_TRANSFER`: File copying
- `CONDITION`: Conditional branching
- `AGGREGATION`: Result aggregation

**NodeStatus**
- `PENDING`: Not yet started
- `READY`: Dependencies met, ready to run
- `RUNNING`: Currently executing
- `COMPLETED`: Finished successfully
- `FAILED`: Execution failed
- `SKIPPED`: Skipped due to upstream failure

**WorkflowStatus**
- `CREATED`: Just created
- `VALIDATING`: Being validated
- `VALID`: Validation passed
- `INVALID`: Validation failed
- `RUNNING`: Currently executing
- `COMPLETED`: All nodes completed successfully
- `FAILED`: Workflow failed
- `PARTIAL`: Some nodes completed, some failed

## Example Workflows

See the `examples/workflows/` directory for complete examples:

1. **opt_freq_simple.py**: Simple optimization → frequency workflow
2. **convergence_scan.py**: Basis set convergence scan with aggregation
3. **conditional_branch.py**: Conditional branching based on convergence
4. **equation_of_state.py**: E(V) curve with parallel calculations

## Best Practices

### 1. Unique Node IDs

Always use descriptive, unique node IDs:

```python
# ✅ GOOD
wf.add_node("optimization", {...}, node_id="opt_bulk_silicon")
wf.add_node("frequency", {...}, node_id="freq_bulk_silicon")

# ❌ BAD
wf.add_node("optimization", {...}, node_id="node1")
wf.add_node("frequency", {...}, node_id="node2")
```

### 2. Validate Before Execute

Always validate before executing:

```python
# ✅ GOOD
errors = wf.validate()
if not errors:
    await wf.execute()
else:
    handle_errors(errors)

# ❌ BAD
await wf.execute()  # May fail with unclear error
```

### 3. Use Parameter Propagation

Use templates instead of hardcoding paths:

```python
# ✅ GOOD
freq = wf.add_node("frequency", {"guess": "{{ opt.f9 }}"}, node_id="freq")

# ❌ BAD
freq = wf.add_node("frequency", {"guess": "/hardcoded/path/opt.f9"}, node_id="freq")
```

### 4. Set Appropriate Parallelism

Balance parallelism with system resources:

```python
# For CPU-bound calculations with 8 cores
await wf.execute(max_parallel=2)  # 4 cores per job

# For I/O-bound tasks
await wf.execute(max_parallel=8)  # Higher parallelism OK
```

### 5. Use Metadata

Document workflows with metadata:

```python
wf = Workflow(
    "study_x",
    "Material X Study",
    metadata={
        "material": "Silicon",
        "crystal_system": "cubic",
        "space_group": 227,
        "date": "2024-01-15",
        "purpose": "Band gap calculation"
    }
)
```

### 6. Save Workflows

Save workflows for reproducibility:

```python
# Save after construction
wf.to_json(Path("workflow_definition.json"))

# Save after execution (includes results)
wf.to_json(Path("workflow_results.json"))
```

### 7. Handle Failures Gracefully

Check node status and handle errors:

```python
if wf.status == WorkflowStatus.FAILED:
    for node_id, node in wf.nodes.items():
        if node.status == NodeStatus.FAILED:
            print(f"Node {node_id} failed: {node.error_message}")
            if node.retry_count < node.max_retries:
                # Can retry...
```

## Troubleshooting

### Validation Error: "Workflow contains a cycle"

**Cause**: Circular dependencies detected.

**Solution**: Check dependencies with `wf.to_ascii()` or `wf.to_graphviz()`. Remove circular edges.

### Validation Error: "Orphaned nodes detected"

**Cause**: Nodes with no connections to other nodes.

**Solution**: Either remove orphaned nodes or add dependencies to connect them.

### Validation Error: "Parameter references non-existent node"

**Cause**: Template `{{ node.field }}` references a node that doesn't exist.

**Solution**: Ensure the referenced node is added to the workflow and has the correct node_id.

### Execution Hangs

**Cause**: Deadlock or all nodes waiting on dependencies.

**Solution**: Check with `wf.get_ready_nodes()` during execution. Ensure dependencies are correct.

### Node Keeps Failing

**Cause**: Calculation error or incorrect parameters.

**Solution**: Check `node.error_message`. Increase `max_retries` or fix parameters.

## Future Enhancements

Planned features for future versions:

- [ ] Interactive workflow editor (TUI)
- [ ] Workflow templates library
- [ ] Real-time visualization during execution
- [ ] Distributed execution across multiple machines
- [ ] Integration with job schedulers (SLURM, PBS)
- [ ] Automatic parameter optimization
- [ ] Machine learning-based workflow suggestions
- [ ] Provenance tracking and reproducibility

## Contributing

Contributions are welcome! See `docs/CONTRIBUTING.md` for guidelines.

## License

This workflow system is part of the CRYSTAL-TOOLS monorepo. See `LICENSE` for details.
