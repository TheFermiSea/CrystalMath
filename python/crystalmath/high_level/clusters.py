"""Cluster profile configuration for CrystalMath.

This module defines pre-configured cluster profiles with hardware specs,
available codes, and resource presets for common HPC environments.

The module provides:
1. ClusterProfile - High-level cluster configuration
2. NodeConfig - Per-node hardware and software configuration
3. CodeConfig - DFT code installation details with AiiDA integration
4. Resource presets - Pre-configured resource allocations
5. Auto-setup utilities - Functions to configure AiiDA profiles

Example:
    from crystalmath.high_level.clusters import (
        get_cluster_profile,
        get_node_config,
        get_optimal_resources,
        setup_aiida_beefcake2,
    )

    # Get cluster profile
    profile = get_cluster_profile("beefcake2")
    print(f"Available codes: {profile.available_codes}")

    # Get resource preset
    resources = profile.presets["gpu-single"]
    print(f"GPUs: {resources.gpus}")

    # Get node-specific configuration
    node = get_node_config("vasp-01")
    print(f"Node IP: {node.ip_address}, Cores: {node.cores}")

    # Get optimal resources for a calculation
    resources = get_optimal_resources(
        code="vasp",
        system_size=128,  # atoms
        calculation_type="relax",
    )

    # Auto-setup AiiDA profile (creates computers and codes)
    result = setup_aiida_beefcake2(profile_name="beefcake2")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from crystalmath.protocols import DFTCode, ResourceRequirements

logger = logging.getLogger(__name__)


# =============================================================================
# Enums for Node and Code Classification
# =============================================================================


class NodeType(str, Enum):
    """Classification of compute node types."""

    VASP = "vasp"  # Nodes optimized for VASP
    QE = "qe"  # Nodes optimized for Quantum ESPRESSO
    GPU = "gpu"  # GPU-accelerated nodes
    GENERAL = "general"  # General purpose nodes


class CalculationType(str, Enum):
    """Types of DFT calculations for resource estimation."""

    SCF = "scf"
    RELAX = "relax"
    BANDS = "bands"
    DOS = "dos"
    PHONON = "phonon"
    GW = "gw"
    BSE = "bse"
    HYBRID = "hybrid"
    MD = "md"
    NEB = "neb"


class MPIDistribution(str, Enum):
    """MPI distribution strategies."""

    FLAT = "flat"  # One MPI rank per core
    HYBRID = "hybrid"  # MPI + OpenMP threading
    GPU = "gpu"  # GPU-aware MPI


# =============================================================================
# Node Configuration
# =============================================================================


@dataclass
class NodeConfig:
    """Configuration for a single compute node.

    Represents the hardware and software configuration of a compute node
    in the beefcake2 cluster. Each node has specific capabilities and
    available DFT codes.

    Attributes:
        name: Node hostname (e.g., "vasp-01", "qe-node1")
        hostname: Full hostname or DNS name
        ip_address: IP address for SSH access (10.0.0.x network)
        cores: Number of CPU cores (40 for Xeon Gold 6248)
        memory_gb: Total memory in GB
        has_gpu: Whether node has GPU passthrough
        gpu_type: GPU model (Tesla V100S)
        gpu_memory_gb: GPU memory in GB
        infiniband_ip: InfiniBand IP address (10.100.0.x network)
        node_type: Classification of node type
        available_codes: List of DFT codes installed on this node
        numa_nodes: Number of NUMA domains (4 with SubNumaCluster)
        ssh_user: SSH username for this node
        ssh_password: SSH password (for VASP nodes)
        work_directory: Default working directory for calculations
        scratch_directory: High-performance scratch space
    """

    name: str
    hostname: str
    ip_address: str
    cores: int = 40
    memory_gb: float = 376.0
    has_gpu: bool = True
    gpu_type: str = "Tesla V100S"
    gpu_memory_gb: float = 32.0
    infiniband_ip: Optional[str] = None
    node_type: NodeType = NodeType.GENERAL
    available_codes: List[DFTCode] = field(default_factory=list)
    numa_nodes: int = 4
    ssh_user: str = "root"
    ssh_password: Optional[str] = None
    work_directory: str = "/home/calculations"
    scratch_directory: str = "/scratch"

    def get_cores_per_numa(self) -> int:
        """Get number of cores per NUMA domain."""
        return self.cores // self.numa_nodes

    def supports_code(self, code: DFTCode) -> bool:
        """Check if this node supports a specific DFT code."""
        return code in self.available_codes

    def get_ssh_connection_string(self) -> str:
        """Get SSH connection string for this node."""
        if self.ssh_password:
            return f"sshpass -p '{self.ssh_password}' ssh {self.ssh_user}@{self.ip_address}"
        return f"ssh {self.ssh_user}@{self.ip_address}"


# =============================================================================
# Code Configuration
# =============================================================================


@dataclass
class CodeConfig:
    """Configuration for a DFT code installation.

    Defines the installation details and runtime configuration for a
    specific DFT code version. Includes AiiDA plugin integration details.

    Attributes:
        name: DFT code identifier (e.g., "vasp", "quantum_espresso")
        version: Version string (e.g., "6.4.3", "7.3.1")
        label: Human-readable label (e.g., "VASP 6.4.3")
        executable: Path to main executable
        executables: Dict of variant executables (std, gam, ncl for VASP)
        mpi_command: MPI launcher command
        mpi_args: Default MPI arguments
        prepend_text: Text to prepend to run script (module loads, etc.)
        append_text: Text to append to run script
        input_plugin: AiiDA input plugin name
        parser_plugin: AiiDA parser plugin name
        default_resources: Default resource requirements
        environment_variables: Environment variables to set
        ucx_settings: UCX configuration for InfiniBand
        gpu_enabled: Whether this code supports GPU acceleration
        openmp_enabled: Whether this code supports OpenMP threading
    """

    name: DFTCode
    version: str
    label: str
    executable: str
    executables: Dict[str, str] = field(default_factory=dict)
    mpi_command: str = "mpirun"
    mpi_args: List[str] = field(default_factory=list)
    prepend_text: str = ""
    append_text: str = ""
    input_plugin: Optional[str] = None
    parser_plugin: Optional[str] = None
    default_resources: Optional[ResourceRequirements] = None
    environment_variables: Dict[str, str] = field(default_factory=dict)
    ucx_settings: Dict[str, str] = field(default_factory=dict)
    gpu_enabled: bool = False
    openmp_enabled: bool = True

    def get_executable(self, variant: str = "std") -> str:
        """Get executable path for a specific variant.

        Args:
            variant: Executable variant (e.g., "std", "gam", "ncl" for VASP)

        Returns:
            Path to the executable
        """
        if variant in self.executables:
            return self.executables[variant]
        return self.executable

    def get_full_prepend_text(self) -> str:
        """Get complete prepend text including environment setup."""
        lines = []

        # Add environment variables
        for key, value in self.environment_variables.items():
            lines.append(f"export {key}={value}")

        # Add UCX settings for InfiniBand
        for key, value in self.ucx_settings.items():
            lines.append(f"export {key}={value}")

        # Add custom prepend text
        if self.prepend_text:
            lines.append(self.prepend_text)

        return "\n".join(lines)


# =============================================================================
# Beefcake2 Node Definitions
# =============================================================================

# VASP nodes (10.0.0.20-22)
BEEFCAKE2_NODES: Dict[str, NodeConfig] = {
    "vasp-01": NodeConfig(
        name="vasp-01",
        hostname="vasp-01",
        ip_address="10.0.0.20",
        cores=40,
        memory_gb=376.0,
        has_gpu=True,
        gpu_type="Tesla V100S",
        gpu_memory_gb=32.0,
        infiniband_ip="10.100.0.20",
        node_type=NodeType.VASP,
        available_codes=["vasp", "crystal23"],
        numa_nodes=4,
        ssh_user="root",
        ssh_password="adminadmin",
        work_directory="/home/calculations",
        scratch_directory="/scratch",
    ),
    "vasp-02": NodeConfig(
        name="vasp-02",
        hostname="vasp-02",
        ip_address="10.0.0.21",
        cores=40,
        memory_gb=376.0,
        has_gpu=True,
        gpu_type="Tesla V100S",
        gpu_memory_gb=32.0,
        infiniband_ip="10.100.0.21",
        node_type=NodeType.VASP,
        available_codes=["vasp", "crystal23"],
        numa_nodes=4,
        ssh_user="root",
        ssh_password="adminadmin",
        work_directory="/home/calculations",
        scratch_directory="/scratch",
    ),
    "vasp-03": NodeConfig(
        name="vasp-03",
        hostname="vasp-03",
        ip_address="10.0.0.22",
        cores=40,
        memory_gb=376.0,
        has_gpu=True,
        gpu_type="Tesla V100S",
        gpu_memory_gb=32.0,
        infiniband_ip="10.100.0.22",
        node_type=NodeType.VASP,
        available_codes=["vasp", "crystal23"],
        numa_nodes=4,
        ssh_user="root",
        ssh_password="adminadmin",
        work_directory="/home/calculations",
        scratch_directory="/scratch",
    ),
    # QE nodes (10.0.0.10-12)
    "qe-node1": NodeConfig(
        name="qe-node1",
        hostname="qe-node1",
        ip_address="10.0.0.10",
        cores=40,
        memory_gb=376.0,
        has_gpu=True,
        gpu_type="Tesla V100S",
        gpu_memory_gb=32.0,
        infiniband_ip="10.100.0.10",
        node_type=NodeType.QE,
        available_codes=["quantum_espresso", "yambo", "crystal23", "wannier90"],
        numa_nodes=4,
        ssh_user="ubuntu",
        ssh_password=None,  # SSH key auth
        work_directory="/home/ubuntu/calculations",
        scratch_directory="/scratch",
    ),
    "qe-node2": NodeConfig(
        name="qe-node2",
        hostname="qe-node2",
        ip_address="10.0.0.11",
        cores=40,
        memory_gb=376.0,
        has_gpu=True,
        gpu_type="Tesla V100S",
        gpu_memory_gb=32.0,
        infiniband_ip="10.100.0.11",
        node_type=NodeType.QE,
        available_codes=["quantum_espresso", "crystal23", "wannier90"],
        numa_nodes=4,
        ssh_user="ubuntu",
        ssh_password=None,
        work_directory="/home/ubuntu/calculations",
        scratch_directory="/scratch",
    ),
    "qe-node3": NodeConfig(
        name="qe-node3",
        hostname="qe-node3",
        ip_address="10.0.0.12",
        cores=40,
        memory_gb=376.0,
        has_gpu=True,
        gpu_type="Tesla V100S",
        gpu_memory_gb=32.0,
        infiniband_ip="10.100.0.12",
        node_type=NodeType.QE,
        available_codes=["quantum_espresso", "crystal23", "wannier90"],
        numa_nodes=4,
        ssh_user="ubuntu",
        ssh_password=None,
        work_directory="/home/ubuntu/calculations",
        scratch_directory="/scratch",
    ),
}


# =============================================================================
# Beefcake2 Code Configurations
# =============================================================================

# Common UCX settings for InfiniBand (ConnectX-6 HDR100)
_UCX_SETTINGS = {
    "UCX_TLS": "rc,cuda_copy,cuda_ipc",
    "UCX_NET_DEVICES": "mlx5_0:1",
    "UCX_IB_GPU_DIRECT_RDMA": "yes",
    "UCX_RNDV_SCHEME": "get_zcopy",
    "UCX_MAX_RNDV_RAILS": "1",
}

# Common OpenMPI settings
_OPENMPI_ARGS = [
    "--mca", "btl", "^openib",
    "--mca", "pml", "ucx",
    "-x", "UCX_TLS",
    "-x", "UCX_NET_DEVICES",
]

# VASP prepend text (module loads and environment)
_VASP_PREPEND = """# VASP Environment Setup
source /opt/intel/oneapi/setvars.sh
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-1}
export OMP_STACKSIZE=512m
export MKL_NUM_THREADS=1
export I_MPI_PIN_DOMAIN=omp
export VASP_PP_PATH=/opt/vasp/potcars
ulimit -s unlimited
"""

# QE prepend text
_QE_PREPEND = """# Quantum ESPRESSO Environment Setup
source /opt/intel/oneapi/setvars.sh
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-1}
export OMP_STACKSIZE=512m
export ESPRESSO_PSEUDO=/opt/qe/pseudopotentials
ulimit -s unlimited
"""

# YAMBO prepend text (GPU-enabled)
_YAMBO_PREPEND = """# YAMBO 5.3.0 GPU Environment Setup
export PATH=/opt/yambo/5.3.0/bin:$PATH
export LD_LIBRARY_PATH=/opt/nvidia/hpc_sdk/Linux_x86_64/24.7/cuda/lib64:$LD_LIBRARY_PATH
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-4}
export OMP_STACKSIZE=512m
# GPU settings
export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0}
export YAMBO_GPU_MEMORY=28000
ulimit -s unlimited
"""

# CRYSTAL23 prepend text
_CRYSTAL23_PREPEND = """# CRYSTAL23 Environment Setup
source /opt/intel/oneapi/setvars.sh
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-1}
export OMP_STACKSIZE=512m
export CRYSTAL_SCRDIR=/scratch
export CRYSTAL_TMPDIR=/tmp
ulimit -s unlimited
"""

BEEFCAKE2_CODES: Dict[str, CodeConfig] = {
    # VASP 6.4.3
    "vasp-6.4.3": CodeConfig(
        name="vasp",
        version="6.4.3",
        label="VASP 6.4.3",
        executable="/opt/vasp/6.4.3/bin/vasp_std",
        executables={
            "std": "/opt/vasp/6.4.3/bin/vasp_std",
            "gam": "/opt/vasp/6.4.3/bin/vasp_gam",
            "ncl": "/opt/vasp/6.4.3/bin/vasp_ncl",
        },
        mpi_command="mpirun",
        mpi_args=_OPENMPI_ARGS.copy(),
        prepend_text=_VASP_PREPEND,
        input_plugin="vasp.vasp",
        parser_plugin="vasp.vasp",
        default_resources=ResourceRequirements(
            num_nodes=1,
            num_mpi_ranks=40,
            num_threads_per_rank=1,
            memory_gb=256,
            walltime_hours=24,
            gpus=0,
            partition="compute",
        ),
        environment_variables={
            "VASP_PP_PATH": "/opt/vasp/potcars",
        },
        ucx_settings=_UCX_SETTINGS.copy(),
        gpu_enabled=True,
        openmp_enabled=True,
    ),
    # Quantum ESPRESSO 7.3.1
    "qe-7.3.1": CodeConfig(
        name="quantum_espresso",
        version="7.3.1",
        label="Quantum ESPRESSO 7.3.1",
        executable="/opt/qe/7.3.1/bin/pw.x",
        executables={
            "pw": "/opt/qe/7.3.1/bin/pw.x",
            "ph": "/opt/qe/7.3.1/bin/ph.x",
            "pp": "/opt/qe/7.3.1/bin/pp.x",
            "bands": "/opt/qe/7.3.1/bin/bands.x",
            "dos": "/opt/qe/7.3.1/bin/dos.x",
            "projwfc": "/opt/qe/7.3.1/bin/projwfc.x",
            "epsilon": "/opt/qe/7.3.1/bin/epsilon.x",
            "turbo_lanczos": "/opt/qe/7.3.1/bin/turbo_lanczos.x",
            "turbo_davidson": "/opt/qe/7.3.1/bin/turbo_davidson.x",
        },
        mpi_command="mpirun",
        mpi_args=_OPENMPI_ARGS.copy(),
        prepend_text=_QE_PREPEND,
        input_plugin="quantumespresso.pw",
        parser_plugin="quantumespresso.pw",
        default_resources=ResourceRequirements(
            num_nodes=1,
            num_mpi_ranks=40,
            num_threads_per_rank=1,
            memory_gb=256,
            walltime_hours=24,
            gpus=0,
            partition="compute",
        ),
        environment_variables={
            "ESPRESSO_PSEUDO": "/opt/qe/pseudopotentials",
        },
        ucx_settings=_UCX_SETTINGS.copy(),
        gpu_enabled=False,  # CPU-only build
        openmp_enabled=True,
    ),
    # CRYSTAL23
    "crystal23": CodeConfig(
        name="crystal23",
        version="1.0.1",
        label="CRYSTAL23 1.0.1",
        executable="/opt/crystal23/bin/crystal",
        executables={
            "crystal": "/opt/crystal23/bin/crystal",
            "properties": "/opt/crystal23/bin/properties",
            "pcrystal": "/opt/crystal23/bin/Pcrystal",
            "pproperties": "/opt/crystal23/bin/Pproperties",
            "mppcrystal": "/opt/crystal23/bin/MPPcrystal",
        },
        mpi_command="mpirun",
        mpi_args=_OPENMPI_ARGS.copy(),
        prepend_text=_CRYSTAL23_PREPEND,
        input_plugin="crystal23.crystal",
        parser_plugin="crystal23.crystal",
        default_resources=ResourceRequirements(
            num_nodes=1,
            num_mpi_ranks=40,
            num_threads_per_rank=1,
            memory_gb=256,
            walltime_hours=24,
            gpus=0,
            partition="compute",
        ),
        environment_variables={
            "CRYSTAL_SCRDIR": "/scratch",
            "CRYSTAL_TMPDIR": "/tmp",
        },
        ucx_settings=_UCX_SETTINGS.copy(),
        gpu_enabled=False,
        openmp_enabled=True,
    ),
    # YAMBO 5.3.0 (GPU-enabled, qe-node1 only)
    "yambo-5.3.0": CodeConfig(
        name="yambo",
        version="5.3.0",
        label="YAMBO 5.3.0 GPU",
        executable="/opt/yambo/5.3.0/bin/yambo",
        executables={
            "yambo": "/opt/yambo/5.3.0/bin/yambo",
            "yambo_gpu": "/opt/yambo/5.3.0/bin/yambo",
            "ypp": "/opt/yambo/5.3.0/bin/ypp",
            "p2y": "/opt/yambo/5.3.0/bin/p2y",
            "a2y": "/opt/yambo/5.3.0/bin/a2y",
            "yambo_rt": "/opt/yambo/5.3.0/bin/yambo_rt",
            "ypp_rt": "/opt/yambo/5.3.0/bin/ypp_rt",
            "yambo_nl": "/opt/yambo/5.3.0/bin/yambo_nl",
            "ypp_nl": "/opt/yambo/5.3.0/bin/ypp_nl",
            "yambo_sc": "/opt/yambo/5.3.0/bin/yambo_sc",
            "ypp_sc": "/opt/yambo/5.3.0/bin/ypp_sc",
        },
        mpi_command="mpirun",
        mpi_args=["-np", "1"],  # GPU mode typically uses single MPI rank
        prepend_text=_YAMBO_PREPEND,
        input_plugin="yambo.yambo",
        parser_plugin="yambo.yambo",
        default_resources=ResourceRequirements(
            num_nodes=1,
            num_mpi_ranks=1,
            num_threads_per_rank=4,
            memory_gb=64,
            walltime_hours=24,
            gpus=1,
            partition="gpu",
        ),
        environment_variables={
            "YAMBO_GPU_MEMORY": "28000",
        },
        ucx_settings={
            "UCX_TLS": "rc,cuda_copy,cuda_ipc",
        },
        gpu_enabled=True,
        openmp_enabled=True,
    ),
    # Wannier90
    "wannier90-3.1.0": CodeConfig(
        name="wannier90",
        version="3.1.0",
        label="Wannier90 3.1.0",
        executable="/opt/wannier90/3.1.0/bin/wannier90.x",
        executables={
            "wannier90": "/opt/wannier90/3.1.0/bin/wannier90.x",
            "postw90": "/opt/wannier90/3.1.0/bin/postw90.x",
        },
        mpi_command="mpirun",
        mpi_args=_OPENMPI_ARGS.copy(),
        prepend_text=_QE_PREPEND,  # Same environment as QE
        input_plugin="wannier90.wannier90",
        parser_plugin="wannier90.wannier90",
        default_resources=ResourceRequirements(
            num_nodes=1,
            num_mpi_ranks=4,
            num_threads_per_rank=1,
            memory_gb=32,
            walltime_hours=4,
            gpus=0,
            partition="compute",
        ),
        environment_variables={},
        ucx_settings=_UCX_SETTINGS.copy(),
        gpu_enabled=False,
        openmp_enabled=True,
    ),
}


# =============================================================================
# Resource Presets for Beefcake2
# =============================================================================

BEEFCAKE2_RESOURCE_PRESETS: Dict[str, ResourceRequirements] = {
    # Small jobs: 8 cores, 32GB, 4 hours
    # Good for: small molecules, testing, quick SCF
    "small": ResourceRequirements(
        num_nodes=1,
        num_mpi_ranks=8,
        num_threads_per_rank=1,
        memory_gb=32,
        walltime_hours=4,
        gpus=0,
        partition="compute",
    ),
    # Medium jobs: 20 cores, 128GB, 12 hours
    # Good for: moderate systems (50-100 atoms), relaxations
    "medium": ResourceRequirements(
        num_nodes=1,
        num_mpi_ranks=20,
        num_threads_per_rank=2,
        memory_gb=128,
        walltime_hours=12,
        gpus=0,
        partition="compute",
    ),
    # Large jobs: 2 nodes, 80 cores, 256GB, 24 hours
    # Good for: large systems (100+ atoms), phonons
    "large": ResourceRequirements(
        num_nodes=2,
        num_mpi_ranks=80,
        num_threads_per_rank=1,
        memory_gb=256,
        walltime_hours=24,
        gpus=0,
        partition="compute",
    ),
    # GPU single: 1 GPU, 4 threads, 64GB, 12 hours
    # Good for: YAMBO GW/BSE, GPU-accelerated calculations
    "gpu-single": ResourceRequirements(
        num_nodes=1,
        num_mpi_ranks=1,
        num_threads_per_rank=4,
        memory_gb=64,
        walltime_hours=12,
        gpus=1,
        partition="gpu",
    ),
    # GPU multi: 3 GPUs across nodes, 192GB, 24 hours
    # Good for: large GW/BSE calculations
    "gpu-multi": ResourceRequirements(
        num_nodes=3,
        num_mpi_ranks=3,
        num_threads_per_rank=4,
        memory_gb=192,
        walltime_hours=24,
        gpus=3,
        partition="gpu",
    ),
    # Full node: all 40 cores, 350GB, 24 hours
    # Good for: memory-intensive calculations
    "full-node": ResourceRequirements(
        num_nodes=1,
        num_mpi_ranks=40,
        num_threads_per_rank=1,
        memory_gb=350,
        walltime_hours=24,
        gpus=0,
        partition="compute",
    ),
    # Hybrid MPI+OpenMP: 10 MPI ranks, 4 threads each
    # Good for: VASP with hybrid parallelization
    "hybrid": ResourceRequirements(
        num_nodes=1,
        num_mpi_ranks=10,
        num_threads_per_rank=4,
        memory_gb=256,
        walltime_hours=24,
        gpus=0,
        partition="compute",
    ),
    # Multi-node large: 4 nodes, 160 cores
    # Good for: very large systems, MD simulations
    "multi-node-large": ResourceRequirements(
        num_nodes=4,
        num_mpi_ranks=160,
        num_threads_per_rank=1,
        memory_gb=512,
        walltime_hours=48,
        gpus=0,
        partition="compute",
    ),
    # Quick test: minimal resources
    # Good for: input validation, testing
    "test": ResourceRequirements(
        num_nodes=1,
        num_mpi_ranks=4,
        num_threads_per_rank=1,
        memory_gb=8,
        walltime_hours=0.5,
        gpus=0,
        partition="compute",
    ),
}


@dataclass
class ClusterProfile:
    """Configuration profile for a compute cluster.

    Contains hardware specifications, available DFT codes, default resources,
    and resource presets for common job sizes.

    Attributes:
        name: Cluster identifier (e.g., "beefcake2", "local")
        description: Human-readable description
        nodes: Total number of compute nodes
        cores_per_node: CPU cores per node
        memory_gb_per_node: Memory per node in GB
        gpus_per_node: GPUs per node (0 if none)
        gpu_type: GPU model (e.g., "Tesla V100S")
        available_codes: DFT codes available on this cluster
        code_paths: Full paths to code executables
        default_partition: Default SLURM partition
        default_walltime_hours: Default walltime limit
        presets: Named resource presets (small, medium, large, gpu-single, etc.)
        ssh_host: SSH hostname for remote access
        ssh_user: SSH username
        scheduler: Job scheduler type (slurm, pbs, local)
    """

    name: str
    description: str
    nodes: int
    cores_per_node: int
    memory_gb_per_node: float
    gpus_per_node: int = 0
    gpu_type: Optional[str] = None
    available_codes: List[DFTCode] = field(default_factory=list)
    code_paths: Dict[DFTCode, str] = field(default_factory=dict)
    default_partition: str = "default"
    default_walltime_hours: float = 24.0
    presets: Dict[str, ResourceRequirements] = field(default_factory=dict)
    ssh_host: Optional[str] = None
    ssh_user: Optional[str] = None
    scheduler: str = "slurm"

    def get_preset(self, preset_name: str) -> ResourceRequirements:
        """Get a resource preset by name.

        Args:
            preset_name: Preset name (small, medium, large, gpu-single, etc.)

        Returns:
            ResourceRequirements for the preset

        Raises:
            KeyError: If preset not found
        """
        if preset_name not in self.presets:
            raise KeyError(
                f"Unknown preset '{preset_name}' for cluster '{self.name}'. "
                f"Available: {list(self.presets.keys())}"
            )
        return self.presets[preset_name]

    def has_code(self, code: DFTCode) -> bool:
        """Check if a DFT code is available on this cluster.

        Args:
            code: DFT code to check

        Returns:
            True if code is available
        """
        return code in self.available_codes

    def get_code_path(self, code: DFTCode) -> Optional[str]:
        """Get the executable path for a DFT code.

        Args:
            code: DFT code

        Returns:
            Path to executable, or None if not configured
        """
        return self.code_paths.get(code)


# =============================================================================
# Pre-configured Cluster Profiles
# =============================================================================

CLUSTER_PROFILES: Dict[str, ClusterProfile] = {
    "beefcake2": ClusterProfile(
        name="beefcake2",
        description="Beefcake2 HPC cluster (6 nodes, V100S GPUs, InfiniBand)",
        nodes=6,
        cores_per_node=40,  # 2x Xeon Gold 6248, HT disabled
        memory_gb_per_node=376,
        gpus_per_node=1,
        gpu_type="Tesla V100S",
        available_codes=["vasp", "quantum_espresso", "yambo", "crystal23", "wannier90"],
        code_paths={
            "vasp": "/opt/vasp/6.4.3/bin/vasp_std",
            "quantum_espresso": "/opt/qe/7.3.1/bin/pw.x",
            "yambo": "/opt/yambo/5.3.0/bin/yambo",
            "crystal23": "/opt/crystal23/bin/crystal",
            "wannier90": "/opt/wannier90/3.1.0/bin/wannier90.x",
        },
        default_partition="compute",
        default_walltime_hours=24.0,
        presets=BEEFCAKE2_RESOURCE_PRESETS,
        ssh_host="10.0.0.20",  # vasp-01
        ssh_user="root",
        scheduler="slurm",
    ),
    "local": ClusterProfile(
        name="local",
        description="Local execution (development/testing)",
        nodes=1,
        cores_per_node=4,
        memory_gb_per_node=16,
        gpus_per_node=0,
        available_codes=["crystal23"],
        code_paths={
            "crystal23": "crystal",  # Assumes in PATH
        },
        default_partition="local",
        default_walltime_hours=1.0,
        presets={
            "default": ResourceRequirements(
                num_nodes=1,
                num_mpi_ranks=4,
                num_threads_per_rank=1,
                memory_gb=8,
                walltime_hours=1,
                gpus=0,
            ),
            "serial": ResourceRequirements(
                num_nodes=1,
                num_mpi_ranks=1,
                num_threads_per_rank=1,
                memory_gb=4,
                walltime_hours=1,
                gpus=0,
            ),
        },
        scheduler="local",
    ),
}


def get_cluster_profile(name: str) -> ClusterProfile:
    """Get cluster profile by name.

    Args:
        name: Profile name (e.g., "beefcake2", "local")

    Returns:
        ClusterProfile configuration

    Raises:
        KeyError: If profile not found

    Example:
        profile = get_cluster_profile("beefcake2")
        print(f"Nodes: {profile.nodes}")
        print(f"Codes: {profile.available_codes}")
    """
    if name not in CLUSTER_PROFILES:
        raise KeyError(
            f"Unknown cluster profile: '{name}'. "
            f"Available: {list(CLUSTER_PROFILES.keys())}"
        )
    return CLUSTER_PROFILES[name]


def list_cluster_profiles() -> List[str]:
    """List available cluster profile names.

    Returns:
        List of profile names
    """
    return list(CLUSTER_PROFILES.keys())


def add_cluster_profile(profile: ClusterProfile) -> None:
    """Register a custom cluster profile.

    Args:
        profile: ClusterProfile to register

    Example:
        my_cluster = ClusterProfile(
            name="my_cluster",
            description="My custom cluster",
            nodes=10,
            cores_per_node=64,
            memory_gb_per_node=256,
            available_codes=["vasp"],
        )
        add_cluster_profile(my_cluster)
    """
    CLUSTER_PROFILES[profile.name] = profile


# =============================================================================
# Beefcake2 Node and Code Access Functions
# =============================================================================


def get_node_config(node_name: str) -> NodeConfig:
    """Get configuration for a specific beefcake2 node.

    Args:
        node_name: Node name (e.g., "vasp-01", "qe-node1")

    Returns:
        NodeConfig for the specified node

    Raises:
        KeyError: If node not found

    Example:
        node = get_node_config("vasp-01")
        print(f"IP: {node.ip_address}")
        print(f"Cores: {node.cores}")
        print(f"Available codes: {node.available_codes}")
    """
    if node_name not in BEEFCAKE2_NODES:
        raise KeyError(
            f"Unknown node: '{node_name}'. "
            f"Available nodes: {list(BEEFCAKE2_NODES.keys())}"
        )
    return BEEFCAKE2_NODES[node_name]


def get_code_config(code_key: str) -> CodeConfig:
    """Get configuration for a specific DFT code installation.

    Args:
        code_key: Code key (e.g., "vasp-6.4.3", "qe-7.3.1", "yambo-5.3.0")

    Returns:
        CodeConfig for the specified code

    Raises:
        KeyError: If code not found

    Example:
        code = get_code_config("vasp-6.4.3")
        print(f"Executable: {code.executable}")
        print(f"Plugin: {code.input_plugin}")
    """
    if code_key not in BEEFCAKE2_CODES:
        raise KeyError(
            f"Unknown code: '{code_key}'. "
            f"Available codes: {list(BEEFCAKE2_CODES.keys())}"
        )
    return BEEFCAKE2_CODES[code_key]


def list_beefcake2_nodes() -> List[str]:
    """List all beefcake2 node names.

    Returns:
        List of node names
    """
    return list(BEEFCAKE2_NODES.keys())


def list_beefcake2_codes() -> List[str]:
    """List all beefcake2 code keys.

    Returns:
        List of code keys (e.g., ["vasp-6.4.3", "qe-7.3.1", ...])
    """
    return list(BEEFCAKE2_CODES.keys())


def get_node_for_code(code: DFTCode) -> Optional[str]:
    """Get recommended node for running a specific DFT code.

    Returns the primary node where the specified code is installed
    and optimized for. YAMBO specifically runs on qe-node1 with GPU.

    Args:
        code: DFT code (e.g., "vasp", "quantum_espresso", "yambo")

    Returns:
        Node name, or None if code not available on any node

    Example:
        node = get_node_for_code("yambo")
        # Returns "qe-node1" (only node with YAMBO GPU build)
    """
    # Special cases with specific node requirements
    code_node_mapping: Dict[DFTCode, str] = {
        "yambo": "qe-node1",  # GPU-enabled YAMBO only on qe-node1
        "vasp": "vasp-01",  # Primary VASP node
        "quantum_espresso": "qe-node1",  # Primary QE node
        "crystal23": "vasp-01",  # Available on all nodes
        "wannier90": "qe-node1",  # Typically used with QE
        # "berkeleygw": Not installed on beefcake2
    }

    if code in code_node_mapping:
        return code_node_mapping[code]

    # Fallback: find any node that supports the code
    for node_name, node_config in BEEFCAKE2_NODES.items():
        if node_config.supports_code(code):
            return node_name

    return None


def get_nodes_for_code(code: DFTCode) -> List[str]:
    """Get all nodes that support a specific DFT code.

    Args:
        code: DFT code (e.g., "vasp", "quantum_espresso")

    Returns:
        List of node names supporting the code

    Example:
        nodes = get_nodes_for_code("crystal23")
        # Returns all 6 nodes since CRYSTAL23 is installed everywhere
    """
    return [
        node_name
        for node_name, node_config in BEEFCAKE2_NODES.items()
        if node_config.supports_code(code)
    ]


def get_nodes_by_type(node_type: NodeType) -> List[str]:
    """Get all nodes of a specific type.

    Args:
        node_type: Node type (VASP, QE, GPU, GENERAL)

    Returns:
        List of node names matching the type

    Example:
        vasp_nodes = get_nodes_by_type(NodeType.VASP)
        # Returns ["vasp-01", "vasp-02", "vasp-03"]
    """
    return [
        node_name
        for node_name, node_config in BEEFCAKE2_NODES.items()
        if node_config.node_type == node_type
    ]


# =============================================================================
# Resource Optimization Functions
# =============================================================================


def get_optimal_resources(
    code: DFTCode,
    system_size: int,
    calculation_type: Union[str, CalculationType] = "scf",
    use_gpu: bool = False,
    max_nodes: int = 6,
    max_walltime_hours: float = 48.0,
) -> ResourceRequirements:
    """Get optimal resources based on code, system size, and calculation type.

    Uses heuristics based on beefcake2 hardware characteristics to estimate
    optimal resource allocation. Considers:
    - System size scaling (memory and cores)
    - Calculation type complexity
    - GPU availability and suitability
    - NUMA topology (4 domains per node)

    Args:
        code: DFT code to use
        system_size: Number of atoms in the system
        calculation_type: Type of calculation (scf, relax, bands, etc.)
        use_gpu: Force GPU usage if available
        max_nodes: Maximum number of nodes to use
        max_walltime_hours: Maximum walltime in hours

    Returns:
        Optimized ResourceRequirements

    Example:
        # Small molecule SCF
        resources = get_optimal_resources("vasp", 10, "scf")

        # Large system GW calculation
        resources = get_optimal_resources("yambo", 100, "gw", use_gpu=True)

        # Phonon calculation (memory intensive)
        resources = get_optimal_resources("quantum_espresso", 50, "phonon")
    """
    # Normalize calculation type
    if isinstance(calculation_type, str):
        try:
            calc_type = CalculationType(calculation_type.lower())
        except ValueError:
            calc_type = CalculationType.SCF
    else:
        calc_type = calculation_type

    # Base memory estimation (GB per atom, varies by calculation type)
    memory_per_atom = {
        CalculationType.SCF: 0.5,
        CalculationType.RELAX: 0.6,
        CalculationType.BANDS: 0.8,
        CalculationType.DOS: 0.8,
        CalculationType.PHONON: 2.0,  # Very memory intensive
        CalculationType.GW: 4.0,  # Extremely memory intensive
        CalculationType.BSE: 5.0,  # Most memory intensive
        CalculationType.HYBRID: 1.5,
        CalculationType.MD: 0.4,
        CalculationType.NEB: 1.0,
    }

    # Core scaling factors (cores per atom baseline)
    cores_per_atom = {
        CalculationType.SCF: 0.5,
        CalculationType.RELAX: 0.6,
        CalculationType.BANDS: 0.8,
        CalculationType.DOS: 0.4,
        CalculationType.PHONON: 1.5,
        CalculationType.GW: 2.0,
        CalculationType.BSE: 2.5,
        CalculationType.HYBRID: 1.2,
        CalculationType.MD: 0.3,
        CalculationType.NEB: 1.0,
    }

    # Walltime multipliers (base hours per 100 atoms)
    walltime_per_100_atoms = {
        CalculationType.SCF: 1.0,
        CalculationType.RELAX: 4.0,
        CalculationType.BANDS: 2.0,
        CalculationType.DOS: 1.0,
        CalculationType.PHONON: 12.0,
        CalculationType.GW: 24.0,
        CalculationType.BSE: 36.0,
        CalculationType.HYBRID: 6.0,
        CalculationType.MD: 8.0,
        CalculationType.NEB: 16.0,
    }

    # Calculate base requirements
    base_memory = system_size * memory_per_atom.get(calc_type, 1.0)
    base_cores = max(4, int(system_size * cores_per_atom.get(calc_type, 0.5)))
    base_walltime = (system_size / 100) * walltime_per_100_atoms.get(calc_type, 4.0)

    # Minimum values
    base_memory = max(16, base_memory)
    base_cores = max(4, base_cores)
    base_walltime = max(1.0, min(base_walltime, max_walltime_hours))

    # GPU handling
    gpus = 0
    partition = "compute"

    # GPU-accelerated calculations
    gpu_codes = ["yambo"]
    gpu_calc_types = [CalculationType.GW, CalculationType.BSE]

    if use_gpu or (code in gpu_codes and calc_type in gpu_calc_types):
        gpus = 1
        partition = "gpu"
        # GPU calculations use fewer MPI ranks but more memory
        base_cores = min(base_cores, 8)
        base_memory = max(base_memory, 64)

    # Calculate number of nodes needed
    cores_per_node = 40
    memory_per_node = 350  # Leave some headroom from 376

    nodes_by_cores = max(1, (base_cores + cores_per_node - 1) // cores_per_node)
    nodes_by_memory = max(1, (int(base_memory) + memory_per_node - 1) // memory_per_node)
    num_nodes = min(max(nodes_by_cores, nodes_by_memory), max_nodes)

    # Calculate MPI ranks and threads
    total_cores = num_nodes * cores_per_node

    # Determine parallelization strategy
    if code == "vasp" and system_size > 50:
        # VASP benefits from hybrid parallelization for larger systems
        num_threads = 4
        num_mpi_ranks = total_cores // num_threads
    elif code == "crystal23":
        # CRYSTAL23 prefers flat MPI
        num_threads = 1
        num_mpi_ranks = min(base_cores, total_cores)
    elif gpus > 0:
        # GPU calculations: few MPI ranks, more threads
        num_threads = 4
        num_mpi_ranks = gpus
    else:
        # Default: flat MPI
        num_threads = 1
        num_mpi_ranks = min(base_cores, total_cores)

    # Calculate final memory (per node accounting)
    total_memory = min(int(base_memory), num_nodes * memory_per_node)

    return ResourceRequirements(
        num_nodes=num_nodes,
        num_mpi_ranks=num_mpi_ranks,
        num_threads_per_rank=num_threads,
        memory_gb=total_memory,
        walltime_hours=base_walltime,
        gpus=gpus,
        partition=partition,
    )


def estimate_job_time(
    code: DFTCode,
    system_size: int,
    calculation_type: Union[str, CalculationType] = "scf",
    num_kpoints: int = 1,
) -> float:
    """Estimate job walltime in hours.

    Provides a rough estimate based on system size, calculation type,
    and k-point sampling density.

    Args:
        code: DFT code
        system_size: Number of atoms
        calculation_type: Type of calculation
        num_kpoints: Number of k-points (affects scaling)

    Returns:
        Estimated walltime in hours

    Example:
        time = estimate_job_time("vasp", 64, "relax", num_kpoints=16)
        print(f"Estimated time: {time:.1f} hours")
    """
    # Normalize calculation type
    if isinstance(calculation_type, str):
        try:
            calc_type = CalculationType(calculation_type.lower())
        except ValueError:
            calc_type = CalculationType.SCF
    else:
        calc_type = calculation_type

    # Base time per atom (hours/atom) - calibrated for beefcake2
    base_times = {
        CalculationType.SCF: 0.01,
        CalculationType.RELAX: 0.05,
        CalculationType.BANDS: 0.02,
        CalculationType.DOS: 0.01,
        CalculationType.PHONON: 0.2,
        CalculationType.GW: 0.5,
        CalculationType.BSE: 1.0,
        CalculationType.HYBRID: 0.1,
        CalculationType.MD: 0.1,
        CalculationType.NEB: 0.3,
    }

    # Code-specific multipliers
    code_multipliers = {
        "vasp": 1.0,
        "quantum_espresso": 1.2,
        "crystal23": 0.8,
        "yambo": 0.5,  # GPU-accelerated
        "wannier90": 0.1,
    }

    base_time = base_times.get(calc_type, 0.05)
    code_mult = code_multipliers.get(code, 1.0)

    # K-point scaling (sublinear for parallel execution)
    kpoint_factor = num_kpoints ** 0.7

    # Calculate estimate with safety margin (1.5x)
    estimate = system_size * base_time * code_mult * kpoint_factor * 1.5

    # Minimum 30 minutes, maximum 48 hours
    return max(0.5, min(estimate, 48.0))


def recommend_preset(
    code: DFTCode,
    system_size: int,
    calculation_type: Union[str, CalculationType] = "scf",
) -> str:
    """Recommend a resource preset based on job characteristics.

    Maps job requirements to the most appropriate preset from
    BEEFCAKE2_RESOURCE_PRESETS.

    Args:
        code: DFT code
        system_size: Number of atoms
        calculation_type: Type of calculation

    Returns:
        Preset name (e.g., "small", "medium", "large", "gpu-single")

    Example:
        preset = recommend_preset("yambo", 64, "gw")
        # Returns "gpu-single" for GPU-accelerated GW
    """
    # Normalize calculation type
    if isinstance(calculation_type, str):
        try:
            calc_type = CalculationType(calculation_type.lower())
        except ValueError:
            calc_type = CalculationType.SCF
    else:
        calc_type = calculation_type

    # GPU calculations
    if calc_type in [CalculationType.GW, CalculationType.BSE]:
        if system_size > 100:
            return "gpu-multi"
        return "gpu-single"

    # Memory-intensive calculations
    if calc_type == CalculationType.PHONON:
        if system_size > 50:
            return "large"
        return "medium"

    # Size-based selection
    if system_size <= 20:
        return "small"
    elif system_size <= 80:
        return "medium"
    elif system_size <= 200:
        return "large"
    else:
        return "multi-node-large"


# =============================================================================
# AiiDA Integration Functions
# =============================================================================


def setup_aiida_beefcake2(
    profile_name: str = "beefcake2",
    ssh_key_path: Optional[Path] = None,
    create_codes: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Auto-setup AiiDA profile with beefcake2 computers and codes.

    Creates a complete AiiDA configuration including:
    - Computer entries for each beefcake2 node
    - Code entries for each DFT code on appropriate nodes
    - SSH transport configuration
    - Default metadata options

    Note: This function requires AiiDA to be installed and configured.
    It will NOT overwrite existing computers or codes.

    Args:
        profile_name: AiiDA profile name to use (default: "beefcake2")
        ssh_key_path: Path to SSH private key (optional, uses default if not provided)
        create_codes: Whether to create code entries (default: True)
        dry_run: If True, only validate and return planned actions without executing

    Returns:
        Dict containing:
            - computers: Dict of created computer labels to UUIDs
            - codes: Dict of created code labels to UUIDs
            - errors: List of any errors encountered
            - warnings: List of warnings

    Raises:
        ImportError: If AiiDA is not installed
        RuntimeError: If AiiDA profile cannot be loaded

    Example:
        # Full setup
        result = setup_aiida_beefcake2()
        print(f"Created computers: {list(result['computers'].keys())}")
        print(f"Created codes: {list(result['codes'].keys())}")

        # Dry run to see what would be created
        result = setup_aiida_beefcake2(dry_run=True)
    """
    result: Dict[str, Any] = {
        "computers": {},
        "codes": {},
        "errors": [],
        "warnings": [],
        "dry_run": dry_run,
    }

    # Try to import AiiDA
    try:
        from aiida import load_profile, orm
        from aiida.common.exceptions import NotExistent
    except ImportError as e:
        result["errors"].append(f"AiiDA not installed: {e}")
        logger.error("AiiDA is required for setup_aiida_beefcake2()")
        return result

    # Load or create profile
    try:
        load_profile(profile_name)
        logger.info(f"Loaded AiiDA profile: {profile_name}")
    except Exception as e:
        result["errors"].append(f"Failed to load profile '{profile_name}': {e}")
        logger.error(f"Cannot load AiiDA profile: {e}")
        return result

    # Determine SSH key path
    if ssh_key_path is None:
        ssh_key_path = Path.home() / ".ssh" / "id_rsa"
        if not ssh_key_path.exists():
            ssh_key_path = Path.home() / ".ssh" / "id_ed25519"

    # Create computers for each node
    for node_name, node_config in BEEFCAKE2_NODES.items():
        computer_label = f"beefcake2-{node_name}"

        if dry_run:
            result["computers"][computer_label] = "DRY_RUN"
            logger.info(f"[DRY RUN] Would create computer: {computer_label}")
            continue

        try:
            # Check if computer already exists
            existing = orm.Computer.collection.get(label=computer_label)
            result["warnings"].append(f"Computer '{computer_label}' already exists")
            result["computers"][computer_label] = str(existing.uuid)
            continue
        except NotExistent:
            pass

        try:
            # Create new computer
            computer = orm.Computer(
                label=computer_label,
                description=f"Beefcake2 {node_name} ({node_config.node_type.value} node)",
                hostname=node_config.ip_address,
                transport_type="core.ssh",
                scheduler_type="core.slurm",
                workdir=node_config.work_directory + "/{username}/aiida_run/",
            ).store()

            # Configure computer
            computer.set_minimum_job_poll_interval(30)
            computer.set_default_mpiprocs_per_machine(node_config.cores)

            # Configure SSH transport
            auth_params = {
                "username": node_config.ssh_user,
                "port": 22,
                "look_for_keys": True,
                "key_filename": str(ssh_key_path),
                "timeout": 60,
                "allow_agent": True,
                "compress": True,
            }

            # Use password for VASP nodes if needed
            if node_config.ssh_password:
                auth_params["password"] = node_config.ssh_password
                auth_params["look_for_keys"] = False

            computer.configure(safe_interval=30, **auth_params)

            result["computers"][computer_label] = str(computer.uuid)
            logger.info(f"Created computer: {computer_label}")

        except Exception as e:
            error_msg = f"Failed to create computer '{computer_label}': {e}"
            result["errors"].append(error_msg)
            logger.error(error_msg)

    # Create codes if requested
    if create_codes:
        # Map codes to appropriate nodes
        code_node_assignments = [
            ("vasp-6.4.3", ["vasp-01", "vasp-02", "vasp-03"]),
            ("qe-7.3.1", ["qe-node1", "qe-node2", "qe-node3"]),
            ("crystal23", list(BEEFCAKE2_NODES.keys())),  # All nodes
            ("yambo-5.3.0", ["qe-node1"]),  # GPU-enabled only on qe-node1
            ("wannier90-3.1.0", ["qe-node1", "qe-node2", "qe-node3"]),
        ]

        for code_key, node_names in code_node_assignments:
            if code_key not in BEEFCAKE2_CODES:
                continue

            code_config = BEEFCAKE2_CODES[code_key]

            for node_name in node_names:
                code_label = f"{code_key}@beefcake2-{node_name}"
                computer_label = f"beefcake2-{node_name}"

                if dry_run:
                    result["codes"][code_label] = "DRY_RUN"
                    logger.info(f"[DRY RUN] Would create code: {code_label}")
                    continue

                try:
                    # Check if code already exists
                    existing = orm.Code.collection.get(label=code_label)
                    result["warnings"].append(f"Code '{code_label}' already exists")
                    result["codes"][code_label] = str(existing.uuid)
                    continue
                except NotExistent:
                    pass

                try:
                    # Get computer
                    computer = orm.Computer.collection.get(label=computer_label)

                    # Create code
                    code = orm.InstalledCode(
                        label=code_label,
                        description=f"{code_config.label} on {node_name}",
                        default_calc_job_plugin=code_config.input_plugin,
                        computer=computer,
                        filepath_executable=code_config.executable,
                    ).store()

                    # Set prepend text for environment setup
                    code.prepend_text = code_config.get_full_prepend_text()

                    result["codes"][code_label] = str(code.uuid)
                    logger.info(f"Created code: {code_label}")

                except Exception as e:
                    error_msg = f"Failed to create code '{code_label}': {e}"
                    result["errors"].append(error_msg)
                    logger.error(error_msg)

    # Summary
    num_computers = len([v for v in result["computers"].values() if v != "DRY_RUN"])
    num_codes = len([v for v in result["codes"].values() if v != "DRY_RUN"])

    if dry_run:
        logger.info(
            f"[DRY RUN] Would create {len(result['computers'])} computers "
            f"and {len(result['codes'])} codes"
        )
    else:
        logger.info(f"Created {num_computers} computers and {num_codes} codes")

    if result["errors"]:
        logger.warning(f"Encountered {len(result['errors'])} errors during setup")

    return result


def get_aiida_computer_config(node_name: str) -> Dict[str, Any]:
    """Get AiiDA computer configuration dict for a beefcake2 node.

    Returns a configuration dict suitable for programmatic computer setup
    or YAML export.

    Args:
        node_name: Node name (e.g., "vasp-01", "qe-node1")

    Returns:
        Dict with computer configuration

    Example:
        config = get_aiida_computer_config("vasp-01")
        # Can be used with `verdi computer setup` or AiiDA API
    """
    node = get_node_config(node_name)

    return {
        "label": f"beefcake2-{node_name}",
        "hostname": node.ip_address,
        "description": f"Beefcake2 {node_name} ({node.node_type.value} node)",
        "transport": "core.ssh",
        "scheduler": "core.slurm",
        "work_dir": f"{node.work_directory}/{{username}}/aiida_run/",
        "mpirun_command": "mpirun",
        "mpiprocs_per_machine": node.cores,
        "default_memory_per_machine_kb": int(node.memory_gb * 1024 * 1024),
        "use_double_quotes": False,
        "prepend_text": "",
        "append_text": "",
    }


def get_aiida_code_config(code_key: str, node_name: str) -> Dict[str, Any]:
    """Get AiiDA code configuration dict.

    Returns a configuration dict suitable for programmatic code setup
    or YAML export.

    Args:
        code_key: Code key (e.g., "vasp-6.4.3", "qe-7.3.1")
        node_name: Node name where code is installed

    Returns:
        Dict with code configuration

    Example:
        config = get_aiida_code_config("vasp-6.4.3", "vasp-01")
    """
    code = get_code_config(code_key)

    return {
        "label": f"{code_key}@beefcake2-{node_name}",
        "description": f"{code.label} on {node_name}",
        "computer": f"beefcake2-{node_name}",
        "remote_abs_path": code.executable,
        "input_plugin": code.input_plugin,
        "prepend_text": code.get_full_prepend_text(),
        "append_text": code.append_text,
    }


# =============================================================================
# Validation Functions
# =============================================================================


def validate_cluster_config() -> Tuple[bool, List[str]]:
    """Validate beefcake2 cluster configuration consistency.

    Checks:
    - All nodes have required fields
    - All codes reference valid nodes
    - Resource presets are within hardware limits
    - Code configurations are complete

    Returns:
        Tuple of (is_valid, list_of_issues)

    Example:
        valid, issues = validate_cluster_config()
        if not valid:
            for issue in issues:
                print(f"  - {issue}")
    """
    issues: List[str] = []

    # Validate nodes
    for node_name, node in BEEFCAKE2_NODES.items():
        if node.cores <= 0:
            issues.append(f"Node {node_name}: invalid core count ({node.cores})")
        if node.memory_gb <= 0:
            issues.append(f"Node {node_name}: invalid memory ({node.memory_gb}GB)")
        if not node.ip_address:
            issues.append(f"Node {node_name}: missing IP address")
        if not node.available_codes:
            issues.append(f"Node {node_name}: no codes available")

    # Validate codes
    for code_key, code in BEEFCAKE2_CODES.items():
        if not code.executable:
            issues.append(f"Code {code_key}: missing executable path")
        if not code.input_plugin:
            issues.append(f"Code {code_key}: missing AiiDA input plugin")

        # Check if code is available on at least one node
        code_available = False
        for node in BEEFCAKE2_NODES.values():
            if code.name in node.available_codes:
                code_available = True
                break
        if not code_available:
            issues.append(f"Code {code_key}: not available on any node")

    # Validate resource presets
    max_cores = 40  # per node
    max_memory = 376  # GB per node

    for preset_name, preset in BEEFCAKE2_RESOURCE_PRESETS.items():
        cores_per_node = preset.num_mpi_ranks // preset.num_nodes
        if cores_per_node * preset.num_threads_per_rank > max_cores:
            issues.append(
                f"Preset {preset_name}: exceeds {max_cores} cores/node "
                f"({cores_per_node * preset.num_threads_per_rank})"
            )

        memory_per_node = preset.memory_gb / preset.num_nodes
        if memory_per_node > max_memory:
            issues.append(
                f"Preset {preset_name}: exceeds {max_memory}GB/node "
                f"({memory_per_node:.0f}GB)"
            )

    return len(issues) == 0, issues


def get_cluster_status_summary() -> Dict[str, Any]:
    """Get summary of cluster configuration.

    Returns:
        Dict with cluster summary information

    Example:
        summary = get_cluster_status_summary()
        print(f"Total nodes: {summary['total_nodes']}")
        print(f"Total cores: {summary['total_cores']}")
    """
    total_nodes = len(BEEFCAKE2_NODES)
    total_cores = sum(n.cores for n in BEEFCAKE2_NODES.values())
    total_memory = sum(n.memory_gb for n in BEEFCAKE2_NODES.values())
    total_gpus = sum(1 for n in BEEFCAKE2_NODES.values() if n.has_gpu)

    vasp_nodes = len([n for n in BEEFCAKE2_NODES.values() if n.node_type == NodeType.VASP])
    qe_nodes = len([n for n in BEEFCAKE2_NODES.values() if n.node_type == NodeType.QE])

    return {
        "cluster_name": "beefcake2",
        "total_nodes": total_nodes,
        "total_cores": total_cores,
        "total_memory_gb": total_memory,
        "total_gpus": total_gpus,
        "vasp_nodes": vasp_nodes,
        "qe_nodes": qe_nodes,
        "available_codes": list(BEEFCAKE2_CODES.keys()),
        "resource_presets": list(BEEFCAKE2_RESOURCE_PRESETS.keys()),
        "hardware": {
            "cpu": "2x Intel Xeon Gold 6248 (40 cores, HT disabled)",
            "memory": "376GB DDR4",
            "gpu": "NVIDIA Tesla V100S 32GB",
            "network": "ConnectX-6 HDR100 InfiniBand",
        },
    }


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Enums
    "NodeType",
    "CalculationType",
    "MPIDistribution",
    # Data classes
    "NodeConfig",
    "CodeConfig",
    "ClusterProfile",
    # Node/Code dictionaries
    "BEEFCAKE2_NODES",
    "BEEFCAKE2_CODES",
    "BEEFCAKE2_RESOURCE_PRESETS",
    "CLUSTER_PROFILES",
    # Profile functions
    "get_cluster_profile",
    "list_cluster_profiles",
    "add_cluster_profile",
    # Node/Code access
    "get_node_config",
    "get_code_config",
    "list_beefcake2_nodes",
    "list_beefcake2_codes",
    "get_node_for_code",
    "get_nodes_for_code",
    "get_nodes_by_type",
    # Resource optimization
    "get_optimal_resources",
    "estimate_job_time",
    "recommend_preset",
    # AiiDA integration
    "setup_aiida_beefcake2",
    "get_aiida_computer_config",
    "get_aiida_code_config",
    # Validation
    "validate_cluster_config",
    "get_cluster_status_summary",
]
