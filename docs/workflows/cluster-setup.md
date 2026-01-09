# Cluster Setup Guide

This guide covers configuring the beefcake2 cluster for CrystalMath, including node definitions, code configurations, resource presets, and AiiDA auto-setup.

## Beefcake2 Cluster Overview

The beefcake2 cluster consists of 6 compute nodes optimized for DFT calculations:

| Node | IP Address | Type | GPU | Available Codes |
|------|------------|------|-----|-----------------|
| vasp-01 | 10.0.0.20 | VASP | V100S | VASP, CRYSTAL23 |
| vasp-02 | 10.0.0.21 | VASP | V100S | VASP, CRYSTAL23 |
| vasp-03 | 10.0.0.22 | VASP | V100S | VASP, CRYSTAL23 |
| qe-node1 | 10.0.0.10 | QE | V100S | QE, YAMBO, CRYSTAL23, Wannier90 |
| qe-node2 | 10.0.0.11 | QE | V100S | QE, CRYSTAL23, Wannier90 |
| qe-node3 | 10.0.0.12 | QE | V100S | QE, CRYSTAL23, Wannier90 |

### Hardware Specifications (Per Node)

- **CPU:** 40 cores (2x Intel Xeon Gold 6248), HyperThreading disabled
- **RAM:** 376 GB DDR4
- **GPU:** NVIDIA Tesla V100S (32GB)
- **Network:** ConnectX-6 HDR100 InfiniBand (10.100.0.x)
- **NUMA:** 4 domains (SubNumaCluster enabled)

## Getting Cluster Information

### Cluster Profile

```python
from crystalmath.high_level.clusters import get_cluster_profile

profile = get_cluster_profile("beefcake2")

print(f"Name: {profile.name}")
print(f"Nodes: {profile.nodes}")
print(f"Cores/node: {profile.cores_per_node}")
print(f"Memory/node: {profile.memory_gb_per_node} GB")
print(f"GPUs/node: {profile.gpus_per_node}")
print(f"Available codes: {profile.available_codes}")
```

### Cluster Summary

```python
from crystalmath.high_level.clusters import get_cluster_status_summary

summary = get_cluster_status_summary()
print(f"Total cores: {summary['total_cores']}")
print(f"Total memory: {summary['total_memory_gb']} GB")
print(f"Total GPUs: {summary['total_gpus']}")
print(f"Hardware: {summary['hardware']}")
```

### Available Profiles

```python
from crystalmath.high_level.clusters import list_cluster_profiles

profiles = list_cluster_profiles()
print(profiles)
# ['beefcake2', 'local']
```

## Node Configuration

### Getting Node Details

```python
from crystalmath.high_level.clusters import get_node_config

node = get_node_config("vasp-01")

print(f"Name: {node.name}")
print(f"IP: {node.ip_address}")
print(f"Cores: {node.cores}")
print(f"Memory: {node.memory_gb} GB")
print(f"GPU: {node.gpu_type} ({node.gpu_memory_gb} GB)")
print(f"InfiniBand IP: {node.infiniband_ip}")
print(f"Available codes: {node.available_codes}")
print(f"SSH command: {node.get_ssh_connection_string()}")
```

### Listing Nodes

```python
from crystalmath.high_level.clusters import (
    list_beefcake2_nodes,
    get_nodes_for_code,
    get_nodes_by_type,
    get_node_for_code,
    NodeType,
)

# All nodes
nodes = list_beefcake2_nodes()
print(nodes)
# ['vasp-01', 'vasp-02', 'vasp-03', 'qe-node1', 'qe-node2', 'qe-node3']

# Nodes supporting a specific code
yambo_nodes = get_nodes_for_code("yambo")
print(yambo_nodes)
# ['qe-node1']

# Nodes by type
vasp_nodes = get_nodes_by_type(NodeType.VASP)
print(vasp_nodes)
# ['vasp-01', 'vasp-02', 'vasp-03']

# Recommended node for a code
node = get_node_for_code("yambo")
print(node)
# 'qe-node1'
```

## Code Configuration

### Getting Code Details

```python
from crystalmath.high_level.clusters import get_code_config

code = get_code_config("vasp-6.4.3")

print(f"Name: {code.name}")
print(f"Version: {code.version}")
print(f"Executable: {code.executable}")
print(f"GPU enabled: {code.gpu_enabled}")
print(f"OpenMP enabled: {code.openmp_enabled}")
print(f"AiiDA plugin: {code.input_plugin}")
```

### Available Executables

```python
# VASP executables
code = get_code_config("vasp-6.4.3")
print(code.executables)
# {
#     'std': '/opt/vasp/6.4.3/bin/vasp_std',
#     'gam': '/opt/vasp/6.4.3/bin/vasp_gam',
#     'ncl': '/opt/vasp/6.4.3/bin/vasp_ncl',
# }

# Get specific executable
vasp_ncl = code.get_executable("ncl")

# Quantum ESPRESSO executables
qe = get_code_config("qe-7.3.1")
print(qe.executables)
# {
#     'pw': '/opt/qe/7.3.1/bin/pw.x',
#     'ph': '/opt/qe/7.3.1/bin/ph.x',
#     'pp': '/opt/qe/7.3.1/bin/pp.x',
#     'bands': '/opt/qe/7.3.1/bin/bands.x',
#     'dos': '/opt/qe/7.3.1/bin/dos.x',
#     ...
# }

# YAMBO executables (GPU-enabled)
yambo = get_code_config("yambo-5.3.0")
print(yambo.executables)
# {
#     'yambo': '/opt/yambo/5.3.0/bin/yambo',
#     'ypp': '/opt/yambo/5.3.0/bin/ypp',
#     'p2y': '/opt/yambo/5.3.0/bin/p2y',
#     'a2y': '/opt/yambo/5.3.0/bin/a2y',
#     ...
# }
```

### Listing Codes

```python
from crystalmath.high_level.clusters import list_beefcake2_codes

codes = list_beefcake2_codes()
print(codes)
# ['vasp-6.4.3', 'qe-7.3.1', 'crystal23', 'yambo-5.3.0', 'wannier90-3.1.0']
```

## Resource Presets

CrystalMath includes pre-configured resource allocations for common job sizes.

### Available Presets

| Preset | Nodes | MPI Ranks | Threads | Memory | Walltime | GPUs |
|--------|-------|-----------|---------|--------|----------|------|
| `test` | 1 | 4 | 1 | 8 GB | 0.5 hr | 0 |
| `small` | 1 | 8 | 1 | 32 GB | 4 hr | 0 |
| `medium` | 1 | 20 | 2 | 128 GB | 12 hr | 0 |
| `large` | 2 | 80 | 1 | 256 GB | 24 hr | 0 |
| `full-node` | 1 | 40 | 1 | 350 GB | 24 hr | 0 |
| `hybrid` | 1 | 10 | 4 | 256 GB | 24 hr | 0 |
| `gpu-single` | 1 | 1 | 4 | 64 GB | 12 hr | 1 |
| `gpu-multi` | 3 | 3 | 4 | 192 GB | 24 hr | 3 |
| `multi-node-large` | 4 | 160 | 1 | 512 GB | 48 hr | 0 |

### Using Presets

```python
from crystalmath.high_level.clusters import get_cluster_profile

profile = get_cluster_profile("beefcake2")

# Get a preset
resources = profile.get_preset("medium")
print(f"Nodes: {resources.num_nodes}")
print(f"MPI ranks: {resources.num_mpi_ranks}")
print(f"Memory: {resources.memory_gb} GB")
print(f"Walltime: {resources.walltime_hours} hr")

# In workflow builder
from crystalmath.high_level import WorkflowBuilder

workflow = (
    WorkflowBuilder()
    .from_file("struct.cif")
    .relax()
    .on_cluster("beefcake2", resources=profile.get_preset("large"))
    .build()
)
```

### Preset Selection by Calculation Type

```python
from crystalmath.high_level.clusters import recommend_preset

# Get recommended preset
preset = recommend_preset("vasp", system_size=64, calculation_type="relax")
print(preset)
# 'medium'

preset = recommend_preset("yambo", system_size=100, calculation_type="gw")
print(preset)
# 'gpu-single'
```

### Optimal Resource Estimation

```python
from crystalmath.high_level.clusters import get_optimal_resources

# Automatic resource estimation
resources = get_optimal_resources(
    code="vasp",
    system_size=128,          # atoms
    calculation_type="phonon",
    use_gpu=False,
    max_nodes=4
)

print(f"Nodes: {resources.num_nodes}")
print(f"MPI ranks: {resources.num_mpi_ranks}")
print(f"Threads: {resources.num_threads_per_rank}")
print(f"Memory: {resources.memory_gb} GB")
print(f"Walltime: {resources.walltime_hours} hr")
```

### Job Time Estimation

```python
from crystalmath.high_level.clusters import estimate_job_time

# Estimate walltime
hours = estimate_job_time(
    code="vasp",
    system_size=64,
    calculation_type="relax",
    num_kpoints=16
)
print(f"Estimated time: {hours:.1f} hours")
```

## AiiDA Auto-Setup

The `setup_aiida_beefcake2()` function automatically creates AiiDA computers and codes for the entire cluster.

### Basic Setup

```python
from crystalmath.high_level.clusters import setup_aiida_beefcake2

# Full setup
result = setup_aiida_beefcake2(profile_name="beefcake2")

print(f"Created computers: {list(result['computers'].keys())}")
print(f"Created codes: {list(result['codes'].keys())}")

if result['errors']:
    print(f"Errors: {result['errors']}")
if result['warnings']:
    print(f"Warnings: {result['warnings']}")
```

### Dry Run Mode

Preview what would be created without making changes:

```python
result = setup_aiida_beefcake2(dry_run=True)

print("Would create:")
for computer in result['computers']:
    print(f"  Computer: {computer}")
for code in result['codes']:
    print(f"  Code: {code}")
```

### Custom SSH Key

```python
from pathlib import Path

result = setup_aiida_beefcake2(
    profile_name="beefcake2",
    ssh_key_path=Path.home() / ".ssh" / "my_key",
    create_codes=True
)
```

### What Gets Created

**Computers (one per node):**
- `beefcake2-vasp-01`
- `beefcake2-vasp-02`
- `beefcake2-vasp-03`
- `beefcake2-qe-node1`
- `beefcake2-qe-node2`
- `beefcake2-qe-node3`

**Codes (for each code/node combination):**
- `vasp-6.4.3@beefcake2-vasp-01`
- `vasp-6.4.3@beefcake2-vasp-02`
- `qe-7.3.1@beefcake2-qe-node1`
- `yambo-5.3.0@beefcake2-qe-node1`
- ...and more

### Manual Configuration Export

Get configuration dictionaries for manual setup:

```python
from crystalmath.high_level.clusters import (
    get_aiida_computer_config,
    get_aiida_code_config,
)

# Computer configuration
computer_config = get_aiida_computer_config("vasp-01")
print(computer_config)
# {
#     'label': 'beefcake2-vasp-01',
#     'hostname': '10.0.0.20',
#     'transport': 'core.ssh',
#     'scheduler': 'core.slurm',
#     'work_dir': '/home/calculations/{username}/aiida_run/',
#     ...
# }

# Code configuration
code_config = get_aiida_code_config("vasp-6.4.3", "vasp-01")
print(code_config)
# {
#     'label': 'vasp-6.4.3@beefcake2-vasp-01',
#     'computer': 'beefcake2-vasp-01',
#     'remote_abs_path': '/opt/vasp/6.4.3/bin/vasp_std',
#     'input_plugin': 'vasp.vasp',
#     ...
# }
```

## SSH Configuration

### VASP Nodes (password auth)

```python
node = get_node_config("vasp-01")
print(f"User: {node.ssh_user}")           # root
print(f"Password: {node.ssh_password}")   # adminadmin
print(f"Command: {node.get_ssh_connection_string()}")
# sshpass -p 'adminadmin' ssh root@10.0.0.20
```

### QE Nodes (key auth)

```python
node = get_node_config("qe-node1")
print(f"User: {node.ssh_user}")           # ubuntu
print(f"Password: {node.ssh_password}")   # None (key auth)
print(f"Command: {node.get_ssh_connection_string()}")
# ssh ubuntu@10.0.0.10
```

### Testing Connectivity

```bash
# VASP nodes
sshpass -p 'adminadmin' ssh root@10.0.0.20 "hostname && nproc"

# QE nodes
ssh ubuntu@10.0.0.10 "hostname && nproc"
```

## SLURM Configuration

All nodes use SLURM for job scheduling. Key parameters:

- **Default partition:** `compute`
- **GPU partition:** `gpu`
- **Default walltime:** 24 hours
- **MPI launcher:** `mpirun` with UCX transport

### UCX Settings (InfiniBand)

```bash
export UCX_TLS=rc,cuda_copy,cuda_ipc
export UCX_NET_DEVICES=mlx5_0:1
export UCX_IB_GPU_DIRECT_RDMA=yes
export UCX_RNDV_SCHEME=get_zcopy
```

## Validation

### Validate Configuration

```python
from crystalmath.high_level.clusters import validate_cluster_config

is_valid, issues = validate_cluster_config()

if is_valid:
    print("Configuration is valid")
else:
    print("Issues found:")
    for issue in issues:
        print(f"  - {issue}")
```

## Custom Cluster Profiles

### Adding a Custom Profile

```python
from crystalmath.high_level.clusters import (
    ClusterProfile,
    add_cluster_profile,
    ResourceRequirements,
)

my_cluster = ClusterProfile(
    name="my_cluster",
    description="My custom HPC cluster",
    nodes=10,
    cores_per_node=64,
    memory_gb_per_node=256,
    gpus_per_node=2,
    gpu_type="A100",
    available_codes=["vasp", "quantum_espresso"],
    code_paths={
        "vasp": "/opt/vasp/6.4.3/bin/vasp_std",
        "quantum_espresso": "/opt/qe/bin/pw.x",
    },
    default_partition="batch",
    presets={
        "small": ResourceRequirements(
            num_nodes=1,
            num_mpi_ranks=32,
            walltime_hours=4
        ),
        "large": ResourceRequirements(
            num_nodes=4,
            num_mpi_ranks=256,
            walltime_hours=24
        ),
    },
    scheduler="slurm",
)

add_cluster_profile(my_cluster)
```

### Using the Custom Profile

```python
from crystalmath.high_level import WorkflowBuilder

workflow = (
    WorkflowBuilder()
    .from_file("struct.cif")
    .relax()
    .on_cluster("my_cluster")
    .build()
)
```

## Complete Setup Example

```python
from crystalmath.high_level.clusters import (
    get_cluster_profile,
    get_cluster_status_summary,
    setup_aiida_beefcake2,
    validate_cluster_config,
)

# 1. Validate configuration
is_valid, issues = validate_cluster_config()
if not is_valid:
    raise ValueError(f"Invalid config: {issues}")

# 2. Get cluster summary
summary = get_cluster_status_summary()
print(f"Cluster: {summary['cluster_name']}")
print(f"Nodes: {summary['total_nodes']}")
print(f"Total cores: {summary['total_cores']}")
print(f"Total GPUs: {summary['total_gpus']}")

# 3. Set up AiiDA (dry run first)
result = setup_aiida_beefcake2(dry_run=True)
print(f"Would create {len(result['computers'])} computers")
print(f"Would create {len(result['codes'])} codes")

# 4. Actual setup
result = setup_aiida_beefcake2()
if result['errors']:
    print(f"Errors: {result['errors']}")
else:
    print("AiiDA setup complete!")

# 5. Use in workflow
from crystalmath.high_level import HighThroughput

results = HighThroughput.run_standard_analysis(
    structure="Si.cif",
    properties=["relax", "bands"],
    cluster="beefcake2"
)
```

## SLURM Integration

CrystalMath automatically submits all computational jobs through SLURM when using
a cluster with `scheduler="slurm"`. This is **mandatory** for the beefcake2 cluster
to ensure proper resource management and cgroup pinning.

### Automatic SLURM Runner Selection

When you create a high-level runner with a SLURM-enabled cluster, the
`SLURMWorkflowRunner` is automatically selected:

```python
from crystalmath.high_level.runners import StandardAnalysis
from crystalmath.high_level.clusters import get_cluster_profile

profile = get_cluster_profile("beefcake2")

# SLURM runner is automatically selected because profile.scheduler == "slurm"
analysis = StandardAnalysis(cluster=profile, protocol="moderate")

# Verify SLURM runner is active
print(f"Runner: {analysis._runner.name}")  # Output: "slurm"
```

### How SLURM Submission Works

When you run a workflow:

1. **Input Generation**: CrystalMath generates the appropriate input files
   (INCAR/POSCAR/KPOINTS for VASP, pw.in for QE, INPUT for CRYSTAL23)

2. **SLURM Script Creation**: A batch script is created with:
   - Resource specifications (nodes, tasks, memory, GPUs, walltime)
   - Module loading for the DFT code
   - Execution command (`srun vasp_std`, `srun pw.x`, etc.)

3. **File Transfer**: Input files are transferred to the cluster via SSH/SFTP

4. **Job Submission**: The job is submitted via `sbatch` over SSH

5. **Monitoring**: Job status is polled via `squeue`/`sacct`

6. **Result Retrieval**: Output files are downloaded when the job completes

### Manual SLURM Runner Configuration

You can also create the SLURM runner explicitly:

```python
from crystalmath.integrations import SLURMWorkflowRunner, create_slurm_runner

# Option 1: Factory function
runner = create_slurm_runner(cluster_name="beefcake2", default_code="vasp")

# Option 2: From cluster profile
runner = SLURMWorkflowRunner.from_cluster_profile(
    profile=get_cluster_profile("beefcake2"),
    default_code="vasp"
)

# Option 3: Full configuration
from crystalmath.integrations import SLURMConfig

config = SLURMConfig(
    cluster_host="10.0.0.20",
    cluster_port=22,
    username="root",
    default_partition="compute",
)
runner = SLURMWorkflowRunner(config=config, default_code="vasp")

# Use with high-level API
analysis = StandardAnalysis(
    cluster=get_cluster_profile("beefcake2"),
    runner=runner,  # Explicit runner
)
```

### SLURM Job Tracking

Track your submitted jobs:

```python
# List all workflows
workflows = runner.list_workflows()
for wf in workflows:
    print(f"{wf['workflow_id']}: {wf['state']} (SLURM ID: {wf['slurm_job_id']})")

# Get status of specific workflow
status = runner.get_status(workflow_id)
print(f"Status: {status}")  # submitted, running, completed, failed

# Get results when complete
result = runner.get_result(workflow_id)
print(f"Energy: {result.outputs.get('energy')} eV")

# Cancel a running job
success = runner.cancel(workflow_id)
```

### Important Notes

⚠️ **CRITICAL**: ALL computational tasks on beefcake2 MUST go through SLURM.
Never run DFT codes directly on compute nodes via SSH, as this bypasses
resource management and cgroup pinning.

The `SLURMWorkflowRunner` ensures this by:
- Generating SLURM batch scripts for all jobs
- Submitting via `sbatch` only
- Never executing DFT codes directly
