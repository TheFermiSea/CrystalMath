# Workflow Execution Stub - Critical Implementation Gap

**Issue ID:** CRIT-001
**Severity:** CRITICAL
**Date:** December 9, 2025

---

## Problem Statement

The workflow execution system in `tui/src/core/workflow.py` is **completely stubbed out**. Instead of executing real CRYSTAL23 calculations, it:
1. Sleeps for 0.1 seconds
2. Returns hardcoded mock results
3. Pretends to copy files (sleeps for 0.05 seconds)

This means **no actual calculations are performed** through the workflow orchestrator.

---

## Current Implementation

### Location: `tui/src/core/workflow.py` lines 641-680

```python
async def _execute_node(self, node: WorkflowNode) -> None:
    """Execute a single workflow node."""
    try:
        node.status = NodeStatus.RUNNING
        node.started_at = datetime.now()

        # Get the calculation parameters
        calc_params = node.calculation_params or {}

        # TODO: Actually execute the calculation
        # For now, just simulate with a delay
        await asyncio.sleep(0.1)

        # TODO: Actually copy files
        # For now, just simulate
        await asyncio.sleep(0.05)

        # Store mock results
        node.result_data = {
            "energy": -123.456,
            "converged": True,
            "iterations": 10
        }

        node.status = NodeStatus.COMPLETED
        node.completed_at = datetime.now()

    except Exception as e:
        node.status = NodeStatus.FAILED
        node.error_message = str(e)
        node.completed_at = datetime.now()
        raise
```

---

## What Should Happen

A proper implementation should:

1. **Prepare the calculation:**
   - Create working directory
   - Stage input files (.d12, basis sets, etc.)
   - Set up environment variables

2. **Select and configure runner:**
   - LocalRunner for local execution
   - SSHRunner for remote execution
   - SLURMRunner for HPC clusters

3. **Submit the job:**
   - Call `runner.submit_job()`
   - Store job ID for tracking

4. **Monitor execution:**
   - Poll job status
   - Stream output logs
   - Handle timeouts

5. **Collect results:**
   - Parse output files
   - Extract energy, convergence, properties
   - Store in node.result_data

6. **Handle errors:**
   - Detect failed calculations
   - Parse error messages from output
   - Provide meaningful error information

---

## Proposed Implementation

### Step 1: Add Runner Integration

```python
async def _execute_node(self, node: WorkflowNode) -> None:
    """Execute a single workflow node."""
    try:
        node.status = NodeStatus.RUNNING
        node.started_at = datetime.now()

        # Get calculation parameters
        calc_params = node.calculation_params or {}
        runner_type = calc_params.get('runner', 'local')

        # Get appropriate runner
        runner = self._get_runner(runner_type, calc_params)

        # Prepare working directory
        work_dir = await self._prepare_work_dir(node)

        # Stage input files
        await self._stage_input_files(node, work_dir)

        # Submit job
        job_id = await runner.submit_job(
            input_file=work_dir / "INPUT",
            work_dir=work_dir,
            **calc_params
        )

        node.job_id = job_id

        # Wait for completion
        await self._wait_for_job(runner, job_id, node)

        # Collect results
        node.result_data = await self._parse_results(work_dir)

        node.status = NodeStatus.COMPLETED
        node.completed_at = datetime.now()

    except CancellationError:
        node.status = NodeStatus.CANCELLED
        node.completed_at = datetime.now()
        raise
    except Exception as e:
        node.status = NodeStatus.FAILED
        node.error_message = str(e)
        node.completed_at = datetime.now()
        raise
```

### Step 2: Add Helper Methods

```python
def _get_runner(self, runner_type: str, params: Dict) -> BaseRunner:
    """Get configured runner instance."""
    if runner_type == 'local':
        return LocalRunner(
            crystal_executable=params.get('executable', 'crystal'),
            num_threads=params.get('omp_threads', 4)
        )
    elif runner_type == 'ssh':
        return SSHRunner(
            cluster_id=params['cluster_id'],
            connection_manager=self.connection_manager
        )
    elif runner_type == 'slurm':
        return SLURMRunner(
            cluster_id=params['cluster_id'],
            connection_manager=self.connection_manager,
            partition=params.get('partition', 'default')
        )
    else:
        raise ConfigurationError(f"Unknown runner type: {runner_type}")


async def _prepare_work_dir(self, node: WorkflowNode) -> Path:
    """Create and prepare working directory for calculation."""
    work_dir = self.base_work_dir / f"node_{node.id}_{node.name}"
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


async def _stage_input_files(self, node: WorkflowNode, work_dir: Path) -> None:
    """Stage input files to working directory."""
    # Copy main input file
    if node.input_file:
        input_path = Path(node.input_file)
        if input_path.exists():
            shutil.copy(input_path, work_dir / "INPUT")

    # Copy auxiliary files (basis sets, geometry, etc.)
    for aux_file in node.auxiliary_files or []:
        aux_path = Path(aux_file)
        if aux_path.exists():
            shutil.copy(aux_path, work_dir / aux_path.name)


async def _wait_for_job(
    self,
    runner: BaseRunner,
    job_id: str,
    node: WorkflowNode
) -> None:
    """Wait for job completion with progress updates."""
    while True:
        status = await runner.get_job_status(job_id)

        if status == JobStatus.COMPLETED:
            return
        elif status == JobStatus.FAILED:
            raise ExecutionError(f"Job {job_id} failed")
        elif status == JobStatus.CANCELLED:
            raise CancellationError(f"Job {job_id} was cancelled")

        # Check for cancellation request
        if node.cancel_requested:
            await runner.cancel_job(job_id)
            raise CancellationError("Cancellation requested")

        # Wait before polling again
        await asyncio.sleep(self.poll_interval)


async def _parse_results(self, work_dir: Path) -> Dict[str, Any]:
    """Parse CRYSTAL output files and extract results."""
    output_file = work_dir / "OUTPUT"

    if not output_file.exists():
        raise ExecutionError("Output file not found")

    results = {}

    # Parse output file
    content = output_file.read_text()

    # Extract total energy
    energy_match = re.search(
        r'TOTAL ENERGY\(.*?\)\s+([-\d.E+]+)',
        content
    )
    if energy_match:
        results['energy'] = float(energy_match.group(1))

    # Check convergence
    results['converged'] = 'CONVERGENCE' in content or 'TTTTTT END' in content

    # Extract iteration count
    iter_matches = re.findall(r'CYC\s+(\d+)', content)
    if iter_matches:
        results['iterations'] = int(iter_matches[-1])

    # Check for errors
    if 'ERROR' in content or 'ABORT' in content:
        error_lines = [l for l in content.split('\n') if 'ERROR' in l or 'ABORT' in l]
        results['errors'] = error_lines[:5]  # First 5 error lines

    return results
```

---

## Integration with CLI

The TUI can optionally delegate to the CLI for execution:

```python
async def _execute_via_cli(self, node: WorkflowNode, work_dir: Path) -> None:
    """Execute calculation using the CLI tool."""
    input_name = work_dir / "INPUT"

    # Build CLI command
    cmd = [
        str(self.cli_path / "bin" / "runcrystal"),
        str(input_name.stem),  # Without extension
    ]

    # Add parallelism if specified
    if mpi_ranks := node.calculation_params.get('mpi_ranks'):
        cmd.append(str(mpi_ranks))

    # Run CLI
    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=work_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        raise ExecutionError(
            f"CLI execution failed: {stderr.decode()}"
        )
```

---

## Testing Strategy

### Unit Tests

```python
# test_workflow_execution.py

@pytest.mark.asyncio
async def test_node_execution_creates_work_dir(workflow_engine, tmp_path):
    """Test that execution creates working directory."""
    node = WorkflowNode(name="test", calculation_params={})

    await workflow_engine._execute_node(node)

    work_dir = tmp_path / f"node_{node.id}_test"
    assert work_dir.exists()


@pytest.mark.asyncio
async def test_node_execution_stages_input(workflow_engine, tmp_path, sample_input):
    """Test that input files are staged correctly."""
    node = WorkflowNode(
        name="test",
        input_file=str(sample_input),
        calculation_params={}
    )

    await workflow_engine._execute_node(node)

    work_dir = tmp_path / f"node_{node.id}_test"
    assert (work_dir / "INPUT").exists()


@pytest.mark.asyncio
async def test_node_execution_parses_results(workflow_engine, mock_crystal_output):
    """Test that results are parsed from output."""
    node = WorkflowNode(name="test", calculation_params={})

    await workflow_engine._execute_node(node)

    assert 'energy' in node.result_data
    assert 'converged' in node.result_data
```

### Integration Tests

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_crystal_execution(workflow_engine, mgo_input):
    """Test execution with real CRYSTAL23 (requires installation)."""
    pytest.importorskip('crystal23')  # Skip if not installed

    node = WorkflowNode(
        name="mgo_test",
        input_file=str(mgo_input),
        calculation_params={
            'runner': 'local',
            'executable': '/opt/crystal23-omp/bin/crystalOMP',
            'omp_threads': 4
        }
    )

    await workflow_engine._execute_node(node)

    assert node.status == NodeStatus.COMPLETED
    assert node.result_data['converged'] is True
    assert node.result_data['energy'] < 0  # Should be negative
```

---

## Migration Path

1. **Phase 1:** Implement local execution only
   - Works on local machine
   - Uses LocalRunner
   - No network dependencies

2. **Phase 2:** Add SSH execution
   - Remote execution via SSH
   - Uses SSHRunner
   - Connection management

3. **Phase 3:** Add SLURM execution
   - HPC cluster submission
   - Uses SLURMRunner
   - Job scheduling integration

---

## Estimated Effort

| Task | Hours |
|------|-------|
| Core _execute_node implementation | 4 |
| Runner integration | 4 |
| File staging and preparation | 2 |
| Results parsing | 3 |
| Error handling | 2 |
| Unit tests | 3 |
| Integration tests | 4 |
| **Total** | **22** |

---

## Related Issues

- CRIT-003: Orchestrator Job Cancellation (depends on runner.cancel_job)
- HIGH-004: Custom Output Parsers (integrates with _parse_results)
- HIGH-006: BaseRunner get_output() (needed for log streaming)
