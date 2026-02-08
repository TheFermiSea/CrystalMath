# atomate2 Integration Guide

> **Status: Planned Feature**
>
> The atomate2 integration described below is a design document for planned functionality.
> The bridge classes exist as stubs but are not yet production-ready. For current workflow
> capabilities, see the [Workflow Classes Reference](high-level-api.md).

CrystalMath provides seamless integration with atomate2 and jobflow for users who want to leverage atomate2's extensive pre-built workflows while using CrystalMath's unified interface.

## Overview

The integration architecture maps atomate2 Flows and Makers to CrystalMath's protocol interfaces:

```
    CrystalMath Protocols          atomate2/jobflow
    +------------------+           +------------------+
    | WorkflowRunner   |           | Maker            |
    | WorkflowType     |  <--->    | Flow             |
    | WorkflowResult   |           | Job              |
    +------------------+           +------------------+
           |                               |
           v                               v
    +------------------+           +------------------+
    | Atomate2Bridge   |---------->| FlowMakerRegistry|
    | (adapter layer)  |           | (maker lookup)   |
    +------------------+           +------------------+
```

## Prerequisites

Install atomate2 and jobflow:

```bash
pip install atomate2 jobflow

# For VASP workflows
pip install atomate2[vasp]

# For remote execution
pip install jobflow-remote
```

## Setting Up atomate2

### 1. Install Required Packages

```bash
pip install atomate2 jobflow maggma pymatgen
```

### 2. Configure JobStore

atomate2 uses Maggma stores for job results. Configure a store in your environment:

```python
from maggma.stores import MongoStore, MemoryStore

# For development (in-memory)
store = MemoryStore()

# For production (MongoDB)
store = MongoStore(
    database="crystalmath",
    collection_name="jobs",
    host="localhost",
    port=27017,
)
```

Or via environment variables:

```bash
export JOBFLOW_STORE_TYPE=MongoStore
export JOBFLOW_STORE_DATABASE=crystalmath
export JOBFLOW_STORE_COLLECTION=jobs
export JOBFLOW_STORE_HOST=localhost
export JOBFLOW_STORE_PORT=27017
```

## FlowMakerRegistry

The `FlowMakerRegistry` maps CrystalMath's `WorkflowType` to atomate2 Maker classes.

### Basic Usage

```python
from crystalmath.integrations.atomate2_bridge import FlowMakerRegistry
from crystalmath.protocols import WorkflowType

registry = FlowMakerRegistry()

# Get a VASP relaxation maker
maker = registry.get_maker(
    workflow_type=WorkflowType.RELAX,
    code="vasp",
    protocol=ProtocolLevel.MODERATE
)

# Create a flow
flow = maker.make(structure)
```

### Available Makers

| WorkflowType | VASP Maker | QE Maker |
|--------------|------------|----------|
| RELAX | DoubleRelaxMaker | RelaxMaker |
| SCF | StaticMaker | StaticMaker |
| BANDS | BandStructureMaker | - |
| ELASTIC | ElasticMaker | - |
| PHONON | PhononMaker | - |

### Protocol Levels

```python
from crystalmath.integrations.atomate2_bridge import ProtocolLevel

# Quick screening
maker = registry.get_maker(
    WorkflowType.RELAX,
    protocol=ProtocolLevel.FAST
)

# Production quality
maker = registry.get_maker(
    WorkflowType.RELAX,
    protocol=ProtocolLevel.MODERATE
)

# Publication quality
maker = registry.get_maker(
    WorkflowType.RELAX,
    protocol=ProtocolLevel.PRECISE
)
```

### Registering Custom Makers

```python
from crystalmath.integrations.atomate2_bridge import MakerConfig

# Register a custom maker
registry.register(
    workflow_type="custom_workflow",
    code="vasp",
    config=MakerConfig(
        maker_class=MyCustomMaker,
        default_kwargs={"option": "value"},
        protocol_mapping={
            ProtocolLevel.FAST: {"steps": 10},
            ProtocolLevel.PRECISE: {"steps": 100},
        },
        requires_gpu=True,
        supported_codes=["vasp"],
    )
)
```

### Listing Available Combinations

```python
available = registry.list_available()
print(available)
# {
#     'relax': ['vasp', 'qe'],
#     'scf': ['vasp', 'qe'],
#     'bands': ['vasp'],
#     'elastic': ['vasp'],
#     'phonon': ['vasp'],
# }
```

## Atomate2Bridge

The `Atomate2Bridge` is the main integration point for running atomate2 workflows through CrystalMath.

### Basic Usage

```python
from crystalmath.integrations.atomate2_bridge import Atomate2Bridge
from crystalmath.protocols import WorkflowType
from pymatgen.core import Structure

bridge = Atomate2Bridge()

# Check if atomate2 is available
if bridge.is_available:
    print("atomate2 integration ready")

# Run a relaxation
structure = Structure.from_file("POSCAR")
result = bridge.submit(
    workflow_type=WorkflowType.RELAX,
    structure=structure,
    code="vasp",
    protocol=ProtocolLevel.MODERATE
)

print(f"Workflow ID: {result.workflow_id}")
```

### Configuration

```python
from maggma.stores import MongoStore
from crystalmath.integrations.atomate2_bridge import ExecutionMode

# Configure with MongoDB store and remote execution
bridge = Atomate2Bridge(
    store=MongoStore(
        database="crystalmath",
        collection_name="jobs"
    ),
    execution_mode=ExecutionMode.REMOTE
)
```

**Execution Modes:**

| Mode | Description |
|------|-------------|
| `LOCAL` | In-process execution via `run_locally()` |
| `REMOTE` | HPC submission via jobflow-remote |
| `FIREWORKS` | FireWorks backend (legacy) |

### Workflow Submission

```python
# Submit workflow
result = bridge.submit(
    workflow_type=WorkflowType.RELAX,
    structure=structure,
    code="vasp",
    parameters={"force_convergence": 0.01},
    resources=None,  # Use defaults
    protocol=ProtocolLevel.MODERATE
)

# Track status
status = bridge.get_status(result.workflow_id)
print(f"State: {status}")

# Get final result
final_result = bridge.get_result(result.workflow_id)
print(f"Success: {final_result.success}")

# Cancel if needed
bridge.cancel(result.workflow_id)
```

### Structure Conversion

The bridge automatically handles structure conversion:

```python
# From pymatgen Structure
result = bridge.submit(
    workflow_type=WorkflowType.SCF,
    structure=Structure.from_file("POSCAR"),
    code="vasp"
)

# From file path
result = bridge.submit(
    workflow_type=WorkflowType.SCF,
    structure="structure.cif",
    code="vasp"
)

# From AiiDA StructureData
result = bridge.submit(
    workflow_type=WorkflowType.SCF,
    structure=aiida_structure_node,
    code="vasp"
)

# From dictionary
result = bridge.submit(
    workflow_type=WorkflowType.SCF,
    structure=structure_dict,
    code="vasp"
)
```

## Multi-Code Workflows

Use `MultiCodeFlowBuilder` for complex workflows spanning multiple codes.

### VASP -> YAMBO Example

```python
from crystalmath.integrations.atomate2_bridge import MultiCodeFlowBuilder
from crystalmath.protocols import WorkflowType

builder = MultiCodeFlowBuilder()

# Build VASP -> YAMBO GW workflow
flow = (
    builder
    .add_step("relax", "vasp", WorkflowType.RELAX)
    .add_step("scf", "vasp", WorkflowType.SCF, depends_on=["relax"])
    .add_handoff("scf", "gw", output_key="wavefunction", input_key="wavefunction")
    .add_step("gw", "yambo", WorkflowType.GW, depends_on=["scf"])
    .add_step("bse", "yambo", WorkflowType.BSE, depends_on=["gw"])
    .build(structure)
)
```

### Adding Steps

```python
builder.add_step(
    name="step_name",           # Unique step identifier
    code="vasp",                # DFT code
    workflow_type=WorkflowType.SCF,
    depends_on=["other_step"],  # Dependencies
    parameters={"key": "value"} # Step parameters
)
```

### Defining Handoffs

Handoffs specify how data flows between codes:

```python
builder.add_handoff(
    source_step="scf",           # Source step name
    target_step="gw",            # Target step name
    output_key="wavefunction",   # Key in source outputs
    input_key="wavefunction",    # Key in target inputs
    converter=my_converter_func  # Optional format converter
)
```

### Validation

```python
is_valid, issues = builder.validate()
if not is_valid:
    for issue in issues:
        print(f"  - {issue}")
```

## Converting atomate2 Flows to CrystalMath

### Using Atomate2FlowAdapter

```python
from atomate2.vasp.flows.core import DoubleRelaxMaker
from crystalmath.integrations.atomate2_bridge import Atomate2FlowAdapter

# Create atomate2 flow
maker = DoubleRelaxMaker()
flow = maker.make(structure)

# Wrap for CrystalMath
adapter = Atomate2FlowAdapter(
    flow=flow,
    execution_mode=ExecutionMode.LOCAL
)

# Convert to WorkflowSteps
steps = adapter.to_workflow_steps()
for step in steps:
    print(f"{step.name}: {step.workflow_type}")
```

### Flow Result Conversion

```python
# Execute and convert results
flow_result = adapter.run_and_collect()

# Convert to CrystalMath WorkflowResult
workflow_result = flow_result.to_workflow_result()

print(f"Success: {workflow_result.success}")
print(f"Outputs: {workflow_result.outputs}")
```

## Convenience Functions

### get_atomate2_bridge()

```python
from crystalmath.integrations.atomate2_bridge import get_atomate2_bridge

bridge = get_atomate2_bridge(
    store=my_store,
    execution_mode=ExecutionMode.REMOTE
)
```

### create_vasp_to_yambo_flow()

```python
from crystalmath.integrations.atomate2_bridge import create_vasp_to_yambo_flow

flow = create_vasp_to_yambo_flow(
    structure=structure,
    gw_parameters={"n_bands": 100, "protocol": "gw0"}
)
```

## Complete Example

```python
from crystalmath.integrations.atomate2_bridge import (
    Atomate2Bridge,
    FlowMakerRegistry,
    MultiCodeFlowBuilder,
    ExecutionMode,
    ProtocolLevel,
)
from crystalmath.protocols import WorkflowType
from pymatgen.core import Structure
from maggma.stores import MemoryStore

# Initialize bridge
bridge = Atomate2Bridge(
    store=MemoryStore(),
    execution_mode=ExecutionMode.LOCAL
)

# Load structure
structure = Structure.from_file("NbOCl2.cif")

# Option 1: Direct submission through bridge
result = bridge.submit(
    workflow_type=WorkflowType.RELAX,
    structure=structure,
    code="vasp",
    protocol=ProtocolLevel.MODERATE
)

# Option 2: Use FlowMakerRegistry for custom configuration
registry = FlowMakerRegistry()
maker = registry.get_maker(
    WorkflowType.BANDS,
    code="vasp",
    protocol=ProtocolLevel.PRECISE,
    line_density=100  # Custom parameter
)
flow = maker.make(structure)

# Option 3: Multi-code workflow
builder = MultiCodeFlowBuilder()
complex_flow = (
    builder
    .add_step("relax", "vasp", WorkflowType.RELAX)
    .add_step("scf", "vasp", WorkflowType.SCF, depends_on=["relax"])
    .add_step("bands", "vasp", WorkflowType.BANDS, depends_on=["scf"])
    .add_handoff("scf", "gw", output_key="wavefunction", input_key="wavefunction")
    .add_step("gw", "yambo", WorkflowType.GW, depends_on=["scf"])
    .build(structure)
)

# Validate before execution
is_valid, issues = builder.validate()
if is_valid:
    print("Workflow is valid")
else:
    print(f"Issues: {issues}")
```

## Error Handling

```python
from crystalmath.integrations.atomate2_bridge import (
    Atomate2IntegrationError,
    MakerNotFoundError,
    FlowExecutionError,
    CodeHandoffError,
)

try:
    result = bridge.submit(
        workflow_type=WorkflowType.GW,
        structure=structure,
        code="unknown_code"
    )
except MakerNotFoundError as e:
    print(f"No maker found: {e}")
except FlowExecutionError as e:
    print(f"Execution failed: {e}")
except CodeHandoffError as e:
    print(f"Data transfer failed: {e}")
```

## Notes

- The atomate2 integration is implemented as stub code in Phase 2. Full implementation will be completed in Phase 3.
- For production use, configure a persistent store (MongoDB recommended).
- Use `ExecutionMode.REMOTE` with jobflow-remote for HPC submission.
- GW/BSE workflows require additional setup for YAMBO integration.
