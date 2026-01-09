"""Cluster profile configuration for CrystalMath.

This module defines pre-configured cluster profiles with hardware specs,
available codes, and resource presets for common HPC environments.

Example:
    from crystalmath.high_level.clusters import get_cluster_profile

    profile = get_cluster_profile("beefcake2")
    print(f"Available codes: {profile.available_codes}")

    # Get resource preset
    resources = profile.presets["gpu-single"]
    print(f"GPUs: {resources.gpus}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from crystalmath.protocols import DFTCode, ResourceRequirements


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
        available_codes=["vasp", "quantum_espresso", "yambo", "crystal23"],
        code_paths={
            "vasp": "/opt/vasp/6.5.1/bin/vasp_std",
            "quantum_espresso": "/opt/qe/7.3.1/bin/pw.x",
            "yambo": "/opt/yambo/5.3.0/bin/yambo",
            "crystal23": "/opt/crystal23/bin/crystal",
        },
        default_partition="compute",
        default_walltime_hours=24.0,
        presets={
            "small": ResourceRequirements(
                num_nodes=1,
                num_mpi_ranks=8,
                num_threads_per_rank=1,
                memory_gb=32,
                walltime_hours=4,
                gpus=0,
            ),
            "medium": ResourceRequirements(
                num_nodes=1,
                num_mpi_ranks=20,
                num_threads_per_rank=2,
                memory_gb=128,
                walltime_hours=12,
                gpus=0,
            ),
            "large": ResourceRequirements(
                num_nodes=2,
                num_mpi_ranks=80,
                num_threads_per_rank=1,
                memory_gb=256,
                walltime_hours=24,
                gpus=0,
            ),
            "gpu-single": ResourceRequirements(
                num_nodes=1,
                num_mpi_ranks=1,
                num_threads_per_rank=4,
                memory_gb=64,
                walltime_hours=12,
                gpus=1,
                partition="gpu",
            ),
            "gpu-multi": ResourceRequirements(
                num_nodes=3,
                num_mpi_ranks=3,
                num_threads_per_rank=4,
                memory_gb=192,
                walltime_hours=24,
                gpus=3,
                partition="gpu",
            ),
        },
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
