# CrystalController API Reference

The `CrystalController` class is the primary Python API facade for TUIs and CLI tools. It manages backend selection (AiiDA, SQLite, or demo) and provides a unified interface for job management, cluster configuration, and workflow operations.

## Import

```python
from crystalmath.api import CrystalController
```

## Constructor

```python
CrystalController(
    profile_name: str = "default",
    use_aiida: bool = True,
    db_path: Optional[str] = None,
)
```

**Parameters:**
- `profile_name` - AiiDA profile name (default: "default")
- `use_aiida` - Whether to try AiiDA backend (default: True)
- `db_path` - Path to SQLite database file (bypasses AiiDA)

**Backend Selection:**
The controller automatically selects the best available backend:
1. AiiDA if `use_aiida=True` and AiiDA is installed
2. SQLite if `db_path` is provided
3. Demo backend as fallback

## Job Management

### get_jobs

```python
get_jobs(limit: int = 100) -> List[JobStatus]
```

Get list of jobs with lightweight status information.

**Returns:** List of `JobStatus` objects (see [models reference](models.md))

**Example:**
```python
ctrl = CrystalController(db_path="jobs.db")
jobs = ctrl.get_jobs(limit=20)
for job in jobs:
    print(f"{job.pk}: {job.name} - {job.state}")
```

### get_job_details

```python
get_job_details(pk: int) -> Optional[JobDetails]
```

Get detailed job information including computed results and logs.

**Parameters:**
- `pk` - Job primary key (database ID)

**Returns:** `JobDetails` object or None if not found

**Example:**
```python
details = ctrl.get_job_details(pk=42)
if details:
    print(f"Energy: {details.final_energy} Ha")
    print(f"Bandgap: {details.bandgap_ev} eV")
    print(f"Converged: {details.convergence_met}")
```

### submit_job

```python
submit_job(submission: JobSubmission) -> int
```

Submit a new calculation job.

**Parameters:**
- `submission` - `JobSubmission` object with job configuration

**Returns:** Job primary key (pk) of the submitted job

**Example:**
```python
from crystalmath.models import JobSubmission, DftCode, RunnerType

submission = JobSubmission(
    name="mgo_scf",
    dft_code=DftCode.CRYSTAL,
    runner_type=RunnerType.LOCAL,
    input_content="...",  # d12 file content
    mpi_ranks=4,
)
pk = ctrl.submit_job(submission)
print(f"Job submitted with ID: {pk}")
```

### cancel_job

```python
cancel_job(pk: int) -> bool
```

Cancel a running or queued job.

**Parameters:**
- `pk` - Job primary key

**Returns:** True if successfully cancelled, False otherwise

### get_job_log

```python
get_job_log(pk: int, tail_lines: int = 100) -> Dict[str, List[str]]
```

Get job output logs (stdout/stderr).

**Parameters:**
- `pk` - Job primary key
- `tail_lines` - Number of lines to retrieve from end of log (default: 100)

**Returns:** Dictionary with keys "stdout" and "stderr", each containing list of strings

**Example:**
```python
logs = ctrl.get_job_log(pk=42, tail_lines=50)
print("=== STDOUT ===")
print("\n".join(logs["stdout"]))
print("\n=== STDERR ===")
print("\n".join(logs["stderr"]))
```

## Cluster Management (JSON API)

These methods accept and return JSON strings for Rust bridge compatibility.

### get_clusters_json

```python
get_clusters_json() -> str
```

Get all configured clusters as JSON array.

**Returns:** JSON string with array of cluster configurations

### create_cluster_json

```python
create_cluster_json(json_payload: str) -> str
```

Create a new cluster configuration from JSON payload.

**Parameters:**
- `json_payload` - JSON string with cluster configuration

**Returns:** JSON response with created cluster ID

### test_cluster_connection_json

```python
test_cluster_connection_json(cluster_id: int) -> str
```

Test SSH connection to a cluster.

**Parameters:**
- `cluster_id` - Cluster database ID

**Returns:** JSON response with connection status

## Materials Integration (JSON API)

### search_materials_json

```python
search_materials_json(formula: str, limit: int = 20) -> str
```

Search Materials Project database by chemical formula.

**Parameters:**
- `formula` - Chemical formula (e.g., "MgO", "Li2O3")
- `limit` - Maximum number of results (default: 20)

**Returns:** JSON string with search results

### get_material_details_json

```python
get_material_details_json(mp_id: str) -> str
```

Get detailed information about a material from Materials Project.

**Parameters:**
- `mp_id` - Materials Project ID (e.g., "mp-149")

**Returns:** JSON string with material details (structure, properties)

## Template System (JSON API)

### list_templates_json

```python
list_templates_json() -> str
```

List all available input templates.

**Returns:** JSON array of template metadata (name, category, description, dft_code)

### render_template_json

```python
render_template_json(template_name: str, params_json: str) -> str
```

Render a template with provided parameters.

**Parameters:**
- `template_name` - Template identifier (e.g., "basic/single_point")
- `params_json` - JSON string with template parameters

**Returns:** JSON response with rendered input file content

## Workflow Management (JSON API)

### create_convergence_study_json

```python
create_convergence_study_json(config_json: str) -> str
```

Create a convergence study workflow (k-points, basis set, etc.).

**Parameters:**
- `config_json` - JSON string with workflow configuration

**Returns:** JSON response with workflow ID and job IDs

### create_band_structure_workflow_json

```python
create_band_structure_workflow_json(config_json: str) -> str
```

Create a band structure calculation workflow (SCF + bands).

### create_phonon_workflow_json

```python
create_phonon_workflow_json(config_json: str) -> str
```

Create a phonon calculation workflow.

### create_eos_workflow_json

```python
create_eos_workflow_json(config_json: str) -> str
```

Create an equation of state workflow with volume scaling.

## VASP Input Generation (JSON API)

### generate_vasp_inputs_json

```python
generate_vasp_inputs_json(config_json: str) -> str
```

Generate VASP input files (POSCAR, INCAR, KPOINTS) from configuration.

**Parameters:**
- `config_json` - JSON with structure and VASP parameters

**Returns:** JSON response with generated input file contents

### generate_vasp_from_mp_json

```python
generate_vasp_from_mp_json(mp_id: str, config_json: str) -> str
```

Generate VASP inputs directly from Materials Project ID.

**Parameters:**
- `mp_id` - Materials Project ID (e.g., "mp-149")
- `config_json` - JSON with VASP calculation parameters

**Returns:** JSON response with generated VASP inputs

## JSON-RPC Dispatch

### dispatch

```python
dispatch(request_json: str) -> str
```

Dispatch a JSON-RPC 2.0 request to the appropriate handler.

This is the single entry point for the thin IPC bridge pattern used by the Rust TUI.

**Protocol:** JSON-RPC 2.0

**Request Format:**
```json
{
  "jsonrpc": "2.0",
  "method": "fetch_jobs",
  "params": {"limit": 50},
  "id": 1
}
```

**Response Format:**
```json
{
  "jsonrpc": "2.0",
  "result": [...],
  "id": 1
}
```

**Security:** Only methods registered in the internal `_rpc_registry` can be called.

## Complete Example

```python
from crystalmath.api import CrystalController
from crystalmath.models import JobSubmission, DftCode, RunnerType
from pathlib import Path

# Initialize controller with SQLite backend
ctrl = CrystalController(use_aiida=False, db_path="jobs.db")

# Read input file
input_content = Path("mgo.d12").read_text()

# Submit job
submission = JobSubmission(
    name="mgo_test",
    dft_code=DftCode.CRYSTAL,
    runner_type=RunnerType.LOCAL,
    input_content=input_content,
    mpi_ranks=4,
)
pk = ctrl.submit_job(submission)
print(f"Submitted job {pk}")

# Check status
jobs = ctrl.get_jobs(limit=10)
for job in jobs:
    if job.pk == pk:
        print(f"Status: {job.state}")
        print(f"Progress: {job.progress_percent}%")

# Get detailed results when complete
details = ctrl.get_job_details(pk)
if details and details.state.value == "COMPLETED":
    print(f"Final energy: {details.final_energy} Ha")
    print(f"Bandgap: {details.bandgap_ev} eV")
    print(f"SCF cycles: {details.scf_cycles}")
```

## See Also

- [Data Models Reference](models.md) - Pydantic models for all API objects
- [CLI Reference](cli.md) - Command-line interface
- [Template System](templates.md) - Input file templates
