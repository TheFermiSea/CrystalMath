# Workflow Examples

This directory contains example workflows demonstrating the Workflow DAG system for CRYSTAL calculations.

## Running Examples

All examples can be run directly with Python:

```bash
# From the tui/ directory
python examples/workflows/opt_freq_simple.py
python examples/workflows/convergence_scan.py
python examples/workflows/conditional_branch.py
python examples/workflows/equation_of_state.py
```

## Examples

### 1. opt_freq_simple.py

**Description:** Simple two-step workflow: geometry optimization followed by frequency calculation.

**Demonstrates:**
- Sequential dependencies (freq depends on opt)
- Parameter propagation using Jinja2 templates (`{{ opt.f9 }}`)
- Basic workflow construction and validation
- ASCII and GraphViz visualization

**Workflow:**
```
opt [optimization] → freq [frequency]
```

**Key Concepts:**
- Wave function file (.f9) from optimization is passed to frequency calculation
- Sequential execution - frequency waits for optimization to complete

---

### 2. convergence_scan.py

**Description:** Basis set convergence scan with parallel calculations and result aggregation.

**Demonstrates:**
- Parallel node execution (5 calculations run concurrently)
- Aggregation node to collect results
- Analysis of aggregated data
- High parallelism (max_parallel=5)

**Workflow:**
```
calc_sto-3g ────┐
calc_6-31g ─────┤
calc_6-31gd ────┼─→ collect_energies [aggregation] → analysis
calc_6-311gd ───┤
calc_6-311gdp ──┘
```

**Key Concepts:**
- All basis set calculations run independently in parallel
- Aggregation node waits for all calculations to complete
- Analysis node processes the aggregated E(basis) data
- Useful for determining basis set convergence

---

### 3. conditional_branch.py

**Description:** Conditional workflow that branches based on convergence results.

**Demonstrates:**
- Condition nodes for branching logic
- Different execution paths based on calculation results
- Conditional edges
- Retry mechanism with different parameters

**Workflow:**
```
opt_initial → check_convergence
               ├─ if converged ──────→ freq_calc
               └─ if not converged ──→ opt_retry → freq_after_retry
```

**Key Concepts:**
- Python expression evaluation in condition nodes
- Separate branches activate based on convergence status
- Failed optimization triggers retry with tighter tolerance
- Demonstrates adaptive workflow behavior

---

### 4. equation_of_state.py

**Description:** Complete E(V) equation of state calculation at multiple volumes.

**Demonstrates:**
- Large parallel execution (7 volume points)
- Aggregation of energy-volume data
- EOS fitting (Birch-Murnaghan equation)
- Property extraction (V₀, E₀, B₀, B')
- Complex multi-step workflow

**Workflow:**
```
calc_v0.94 ─┐
calc_v0.96 ─┤
calc_v0.98 ─┤
calc_v1.00 ─┼─→ collect_ev_data → eos_fit → extract_properties
calc_v1.02 ─┤
calc_v1.04 ─┤
calc_v1.06 ─┘
```

**Key Concepts:**
- Systematic parameter variation (volume scaling)
- High parallelism for independent calculations
- Data fitting and analysis pipeline
- Extract physical properties from fitted equation of state

---

## Output Files

Each example generates:

1. **JSON workflow file** - Complete workflow definition and results
   - `opt_freq_simple.json`
   - `convergence_scan.json`
   - `conditional_branch.json`
   - `equation_of_state.json`

2. **GraphViz DOT file** (where applicable)
   - `convergence_scan.dot`
   - `conditional_branch.dot`
   - `equation_of_state.dot`

### Rendering Diagrams

Convert DOT files to PNG images:

```bash
dot -Tpng convergence_scan.dot -o convergence_scan.png
dot -Tpng equation_of_state.dot -o equation_of_state.png
```

## Common Patterns

### Pattern 1: Sequential Pipeline

```python
wf = Workflow("sequential", "Linear Pipeline")
opt = wf.add_node("optimization", {...}, node_id="opt")
freq = wf.add_node("frequency", {...}, node_id="freq")
wf.add_dependency("opt", "freq")
```

### Pattern 2: Parallel Fan-Out

```python
wf = Workflow("parallel", "Multiple Analyses")
opt = wf.add_node("optimization", {...}, node_id="opt")
dos = wf.add_node("dos", {...}, node_id="dos")
band = wf.add_node("band_structure", {...}, node_id="band")
wf.add_dependency("opt", "dos")
wf.add_dependency("opt", "band")
```

### Pattern 3: Aggregation

```python
# Create parallel calculations
calcs = [wf.add_node("calc", {"param": val}, node_id=f"calc_{val}")
         for val in values]

# Aggregate results
agg = wf.add_aggregation_node("collect", "collect",
                              dependencies=[c.node_id for c in calcs])

# Add edges
for calc in calcs:
    wf.add_dependency(calc.node_id, "collect")
```

### Pattern 4: Conditional Branching

```python
opt = wf.add_node("optimization", {...}, node_id="opt")
check = wf.add_condition_node(
    "check_result",
    condition_expr="opt['converged'] == True",
    true_branch=["continue"],
    false_branch=["retry"],
    dependencies=["opt"]
)
wf.add_dependency("opt", "check_result")
```

## Customization

Modify these examples for your own calculations:

1. **Change parameters:**
   - Basis sets
   - DFT functionals
   - Convergence thresholds
   - Temperature/pressure conditions

2. **Add more steps:**
   - Add DOS calculation after frequency
   - Add band structure after optimization
   - Add elastic constants calculation

3. **Adjust parallelism:**
   - Change `max_parallel` in `execute()` call
   - Balance with available CPU cores

4. **Add error handling:**
   - Set `max_retries` on critical nodes
   - Add condition nodes to check results
   - Implement fallback paths

## Troubleshooting

**Problem:** "Orphaned nodes detected"

**Solution:** Ensure all nodes are connected with edges. For aggregation nodes, add edges from source nodes to aggregation:

```python
agg = wf.add_aggregation_node("agg", "collect", dependencies=calc_nodes)
for calc_id in calc_nodes:
    wf.add_dependency(calc_id, "agg")  # Add edge
```

**Problem:** "Workflow contains a cycle"

**Solution:** Check dependencies with `wf.to_ascii()` or `wf.to_graphviz()`. Remove circular dependencies.

**Problem:** Execution hangs

**Solution:** Check that all dependencies are satisfied. Use `wf.get_ready_nodes()` to see which nodes are waiting.

## Learn More

- **Workflow DAG Documentation:** `docs/WORKFLOW_DAG.md`
- **API Reference:** See docstrings in `src/core/workflow.py`
- **Test Suite:** `tests/test_workflow.py` for more usage examples

## Contributing

Have a useful workflow pattern? Submit it as an example:

1. Create a new Python file in this directory
2. Follow the existing example structure
3. Add comprehensive comments
4. Test that it runs successfully
5. Update this README with your example
