"""Tests for cluster configuration (clusters.py module).

This module tests cluster configuration including:
- ClusterProfile creation and presets
- NodeConfig for all beefcake2 nodes
- CodeConfig for all DFT codes
- get_cluster_profile() and get_node_for_code()
- get_optimal_resources() heuristics
- setup_aiida_beefcake2() dry_run mode

Tests are designed to verify correct cluster configuration without
requiring actual cluster access.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from dataclasses import dataclass

from crystalmath.protocols import ResourceRequirements


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def beefcake2_profile() -> Dict[str, Any]:
    """Expected beefcake2 cluster profile."""
    return {
        "name": "beefcake2",
        "description": "6-node V100S GPU cluster",
        "scheduler": "slurm",
        "nodes": 6,
        "cores_per_node": 40,
        "memory_gb_per_node": 376,
        "gpus_per_node": 1,
        "gpu_type": "Tesla V100S",
    }


@pytest.fixture
def vasp_node_config() -> Dict[str, Any]:
    """Expected VASP node configuration."""
    return {
        "hostname": "vasp-01",
        "ip_address": "10.0.0.20",
        "cores": 40,
        "memory_gb": 376,
        "gpu_type": "Tesla V100S",
        "available_codes": ["vasp", "crystal23"],
    }


@pytest.fixture
def qe_node_config() -> Dict[str, Any]:
    """Expected QE node configuration."""
    return {
        "hostname": "qe-node1",
        "ip_address": "10.0.0.10",
        "cores": 40,
        "memory_gb": 376,
        "gpu_type": "Tesla V100S",
        "available_codes": ["quantum_espresso", "yambo", "crystal23", "wannier90"],
    }


# =============================================================================
# Test ClusterProfile
# =============================================================================


class TestClusterProfile:
    """Tests for ClusterProfile creation and configuration."""

    def test_create_cluster_profile(self) -> None:
        """Test creating a cluster profile."""
        from crystalmath.high_level.clusters import ClusterProfile

        profile = ClusterProfile(
            name="test_cluster",
            description="Test cluster",
            scheduler="slurm",
            nodes=4,
            cores_per_node=32,
            memory_gb_per_node=256,
        )

        assert profile.name == "test_cluster"
        assert profile.scheduler == "slurm"
        assert profile.nodes == 4
        assert profile.cores_per_node == 32

    def test_cluster_profile_with_gpu(self) -> None:
        """Test cluster profile with GPU configuration."""
        from crystalmath.high_level.clusters import ClusterProfile

        profile = ClusterProfile(
            name="gpu_cluster",
            description="GPU cluster",
            scheduler="slurm",
            nodes=2,
            cores_per_node=40,
            memory_gb_per_node=376,
            gpus_per_node=2,
            gpu_type="V100S",
        )

        assert profile.gpus_per_node == 2
        assert profile.gpu_type == "V100S"

    def test_cluster_profile_get_preset(self) -> None:
        """Test getting resource presets."""
        from crystalmath.high_level.clusters import get_cluster_profile

        profile = get_cluster_profile("beefcake2")
        preset = profile.get_preset("small")

        assert preset.num_mpi_ranks > 0

    def test_cluster_profile_unknown_preset_raises(self) -> None:
        """Test error for unknown preset."""
        from crystalmath.high_level.clusters import get_cluster_profile

        profile = get_cluster_profile("beefcake2")

        with pytest.raises(KeyError):
            profile.get_preset("nonexistent_preset")


class TestClusterProfilePresets:
    """Tests for cluster profile presets."""

    def test_beefcake2_preset(self, beefcake2_profile: Dict[str, Any]) -> None:
        """Test beefcake2 cluster preset."""
        from crystalmath.high_level.clusters import get_cluster_profile

        profile = get_cluster_profile("beefcake2")

        assert profile.name == "beefcake2"
        assert profile.nodes == 6
        assert profile.cores_per_node == 40
        assert profile.gpus_per_node == 1

    def test_local_preset(self) -> None:
        """Test local execution preset."""
        from crystalmath.high_level.clusters import get_cluster_profile

        profile = get_cluster_profile("local")

        assert profile.name == "local"
        assert profile.scheduler in ["local", "none", "slurm"]

    def test_unknown_cluster_raises(self) -> None:
        """Test error for unknown cluster."""
        from crystalmath.high_level.clusters import get_cluster_profile

        with pytest.raises(KeyError):
            get_cluster_profile("nonexistent_cluster")

    def test_list_available_clusters(self) -> None:
        """Test listing available cluster presets."""
        from crystalmath.high_level.clusters import list_cluster_profiles

        clusters = list_cluster_profiles()

        assert "beefcake2" in clusters
        assert "local" in clusters


# =============================================================================
# Test NodeConfig
# =============================================================================


class TestNodeConfig:
    """Tests for NodeConfig for all beefcake2 nodes."""

    def test_create_node_config(self) -> None:
        """Test creating a node configuration."""
        from crystalmath.high_level.clusters import NodeConfig

        node = NodeConfig(
            name="vasp-01",
            hostname="vasp-01",
            ip_address="10.0.0.20",
            cores=40,
            memory_gb=376,
        )

        assert node.hostname == "vasp-01"
        assert node.cores == 40

    @pytest.mark.parametrize(
        "hostname,ip,expected_cores",
        [
            ("vasp-01", "10.0.0.20", 40),
            ("vasp-02", "10.0.0.21", 40),
            ("vasp-03", "10.0.0.22", 40),
            ("qe-node1", "10.0.0.10", 40),
            ("qe-node2", "10.0.0.11", 40),
            ("qe-node3", "10.0.0.12", 40),
        ],
    )
    def test_beefcake2_nodes(
        self, hostname: str, ip: str, expected_cores: int
    ) -> None:
        """Test all beefcake2 node configurations."""
        from crystalmath.high_level.clusters import get_node_config

        node = get_node_config(hostname)

        assert node.hostname == hostname
        assert node.cores == expected_cores

    def test_node_gpu_config(self, vasp_node_config: Dict[str, Any]) -> None:
        """Test node GPU configuration."""
        from crystalmath.high_level.clusters import get_node_config

        node = get_node_config("vasp-01")

        assert node.gpu_type == "Tesla V100S"
        assert node.gpu_memory_gb == 32  # V100S has 32GB

    def test_node_infiniband_config(self) -> None:
        """Test node InfiniBand configuration."""
        from crystalmath.high_level.clusters import get_node_config

        node = get_node_config("vasp-01")

        assert node.infiniband_ip is not None

    def test_node_available_codes(self, vasp_node_config: Dict[str, Any]) -> None:
        """Test codes available on node."""
        from crystalmath.high_level.clusters import get_node_config

        node = get_node_config("vasp-01")

        assert "vasp" in node.available_codes

    def test_unknown_node_raises(self) -> None:
        """Test error for unknown node."""
        from crystalmath.high_level.clusters import get_node_config

        with pytest.raises(KeyError):
            get_node_config("nonexistent-node")


class TestNodeConfigValidation:
    """Tests for NodeConfig validation."""

    def test_node_supports_code(self) -> None:
        """Test checking code support on node."""
        from crystalmath.high_level.clusters import get_node_config

        node = get_node_config("vasp-01")
        assert node.supports_code("vasp") is True
        assert node.supports_code("nonexistent_code") is False

    def test_node_ssh_connection_string(self) -> None:
        """Test SSH connection string generation."""
        from crystalmath.high_level.clusters import get_node_config

        node = get_node_config("vasp-01")
        conn_str = node.get_ssh_connection_string()

        assert "10.0.0.20" in conn_str


# =============================================================================
# Test CodeConfig
# =============================================================================


class TestCodeConfig:
    """Tests for CodeConfig for all DFT codes."""

    def test_create_code_config(self) -> None:
        """Test creating a code configuration."""
        from crystalmath.high_level.clusters import CodeConfig

        code = CodeConfig(
            name="vasp",
            version="6.4.3",
            label="VASP 6.4.3",
            executable="/opt/vasp/bin/vasp_std",
            gpu_enabled=True,
        )

        assert code.name == "vasp"
        assert code.gpu_enabled is True

    def test_vasp_config(self) -> None:
        """Test VASP code configuration."""
        from crystalmath.high_level.clusters import get_code_config

        code = get_code_config("vasp-6.4.3")

        assert code.name == "vasp"
        assert "vasp" in code.executable.lower()

    def test_crystal23_config(self) -> None:
        """Test CRYSTAL23 code configuration."""
        from crystalmath.high_level.clusters import get_code_config

        code = get_code_config("crystal23")

        assert code.name == "crystal23"

    def test_quantum_espresso_config(self) -> None:
        """Test Quantum ESPRESSO code configuration."""
        from crystalmath.high_level.clusters import get_code_config

        code = get_code_config("qe-7.3.1")

        assert code.name == "quantum_espresso"

    def test_yambo_config(self) -> None:
        """Test YAMBO code configuration."""
        from crystalmath.high_level.clusters import get_code_config

        code = get_code_config("yambo-5.3.0")

        assert code.name == "yambo"
        assert code.gpu_enabled is True

    def test_code_get_executable_variant(self) -> None:
        """Test getting executable variant."""
        from crystalmath.high_level.clusters import get_code_config

        code = get_code_config("vasp-6.4.3")

        std_exe = code.get_executable("std")
        assert "vasp_std" in std_exe

    def test_unknown_code_raises(self) -> None:
        """Test error for unknown code."""
        from crystalmath.high_level.clusters import get_code_config

        with pytest.raises(KeyError):
            get_code_config("nonexistent_code")


# =============================================================================
# Test get_node_for_code()
# =============================================================================


class TestGetNodeForCode:
    """Tests for get_node_for_code() function."""

    def test_get_node_for_vasp(self) -> None:
        """Test getting node for VASP code."""
        from crystalmath.high_level.clusters import get_node_for_code

        node_name = get_node_for_code("vasp")

        assert node_name is not None
        assert "vasp" in node_name

    def test_get_node_for_quantum_espresso(self) -> None:
        """Test getting node for QE code."""
        from crystalmath.high_level.clusters import get_node_for_code

        node_name = get_node_for_code("quantum_espresso")

        assert node_name is not None
        assert "qe" in node_name

    def test_get_node_for_yambo(self) -> None:
        """Test getting node for YAMBO code."""
        from crystalmath.high_level.clusters import get_node_for_code

        node_name = get_node_for_code("yambo")

        assert node_name is not None
        # YAMBO is only on qe-node1
        assert node_name == "qe-node1"

    def test_get_node_for_unknown_code(self) -> None:
        """Test None returned for unknown code."""
        from crystalmath.high_level.clusters import get_node_for_code

        node_name = get_node_for_code("unknown_code")

        assert node_name is None


class TestGetNodesForCode:
    """Tests for get_nodes_for_code() function."""

    def test_get_nodes_for_vasp(self) -> None:
        """Test getting all nodes for VASP code."""
        from crystalmath.high_level.clusters import get_nodes_for_code

        nodes = get_nodes_for_code("vasp")

        assert len(nodes) >= 3
        assert "vasp-01" in nodes

    def test_get_nodes_for_crystal23(self) -> None:
        """Test getting all nodes for CRYSTAL23."""
        from crystalmath.high_level.clusters import get_nodes_for_code

        nodes = get_nodes_for_code("crystal23")

        # CRYSTAL23 is on all nodes
        assert len(nodes) == 6


# =============================================================================
# Test get_optimal_resources()
# =============================================================================


class TestGetOptimalResources:
    """Tests for get_optimal_resources() heuristics."""

    def test_optimal_resources_small_system(self) -> None:
        """Test resource optimization for small system."""
        from crystalmath.high_level.clusters import get_optimal_resources

        resources = get_optimal_resources(
            code="vasp",
            system_size=10,
            calculation_type="scf",
        )

        assert resources.num_nodes >= 1
        assert resources.num_mpi_ranks > 0

    def test_optimal_resources_large_system(self) -> None:
        """Test resource optimization for large system."""
        from crystalmath.high_level.clusters import get_optimal_resources

        resources = get_optimal_resources(
            code="vasp",
            system_size=500,
            calculation_type="scf",
        )

        # Large system should get more resources
        assert resources.num_nodes >= 1

    def test_optimal_resources_gpu_code(self) -> None:
        """Test resource optimization for GPU-enabled code."""
        from crystalmath.high_level.clusters import get_optimal_resources

        resources = get_optimal_resources(
            code="yambo",
            system_size=50,
            calculation_type="gw",
            use_gpu=True,
        )

        assert resources.gpus > 0

    def test_optimal_resources_cpu_only(self) -> None:
        """Test resource optimization for CPU-only code."""
        from crystalmath.high_level.clusters import get_optimal_resources

        resources = get_optimal_resources(
            code="crystal23",
            system_size=50,
            calculation_type="scf",
        )

        # Should not request GPUs for CPU-only code
        assert resources.gpus == 0

    def test_optimal_resources_relax(self) -> None:
        """Test resource optimization for relaxation."""
        from crystalmath.high_level.clusters import get_optimal_resources

        resources = get_optimal_resources(
            code="vasp",
            system_size=50,
            calculation_type="relax",
        )

        assert resources.walltime_hours > 0


class TestResourceHeuristics:
    """Tests for specific resource heuristics."""

    def test_gw_resources(self) -> None:
        """Test GW calculation resource estimation."""
        from crystalmath.high_level.clusters import get_optimal_resources

        resources = get_optimal_resources(
            code="yambo",
            system_size=50,
            calculation_type="gw",
        )

        # GW calculations are memory-intensive
        assert resources.memory_gb >= 50

    def test_phonon_resources(self) -> None:
        """Test phonon calculation resource estimation."""
        from crystalmath.high_level.clusters import get_optimal_resources

        resources = get_optimal_resources(
            code="quantum_espresso",
            system_size=50,
            calculation_type="phonon",
        )

        # Phonon needs more resources
        assert resources.num_nodes >= 1


# =============================================================================
# Test estimate_job_time()
# =============================================================================


class TestEstimateJobTime:
    """Tests for estimate_job_time() function."""

    def test_estimate_job_time_scf(self) -> None:
        """Test job time estimation for SCF."""
        from crystalmath.high_level.clusters import estimate_job_time

        time_hrs = estimate_job_time(
            code="vasp",
            system_size=50,
            calculation_type="scf",
        )

        assert time_hrs > 0

    def test_estimate_job_time_relax(self) -> None:
        """Test job time estimation for relaxation."""
        from crystalmath.high_level.clusters import estimate_job_time

        time_hrs = estimate_job_time(
            code="vasp",
            system_size=50,
            calculation_type="relax",
        )

        # Relaxation should take longer than SCF
        scf_time = estimate_job_time(
            code="vasp",
            system_size=50,
            calculation_type="scf",
        )
        assert time_hrs >= scf_time


# =============================================================================
# Test recommend_preset()
# =============================================================================


class TestRecommendPreset:
    """Tests for recommend_preset() function."""

    def test_recommend_preset_small(self) -> None:
        """Test preset recommendation for small system."""
        from crystalmath.high_level.clusters import recommend_preset

        preset = recommend_preset(
            code="vasp",
            system_size=10,
            calculation_type="scf",
        )

        assert preset == "small"

    def test_recommend_preset_gw(self) -> None:
        """Test preset recommendation for GW calculation."""
        from crystalmath.high_level.clusters import recommend_preset

        preset = recommend_preset(
            code="yambo",
            system_size=50,
            calculation_type="gw",
        )

        assert "gpu" in preset


# =============================================================================
# Test setup_aiida_beefcake2()
# =============================================================================


class TestSetupAiidaBeefcake2:
    """Tests for setup_aiida_beefcake2() dry_run mode."""

    def test_setup_dry_run(self) -> None:
        """Test AiiDA setup in dry_run mode."""
        from crystalmath.high_level.clusters import setup_aiida_beefcake2

        result = setup_aiida_beefcake2(dry_run=True)

        # dry_run should return a result dict even if AiiDA isn't installed
        assert isinstance(result, dict)
        assert "computers" in result
        assert "codes" in result

    def test_setup_dry_run_returns_dict(self) -> None:
        """Test that dry_run returns proper structure."""
        from crystalmath.high_level.clusters import setup_aiida_beefcake2

        result = setup_aiida_beefcake2(dry_run=True)

        assert "dry_run" in result
        assert result["dry_run"] is True


# =============================================================================
# Test validate_cluster_config()
# =============================================================================


class TestValidateClusterConfig:
    """Tests for validate_cluster_config() function."""

    def test_validate_cluster_config(self) -> None:
        """Test cluster configuration validation."""
        from crystalmath.high_level.clusters import validate_cluster_config

        is_valid, issues = validate_cluster_config()

        assert isinstance(is_valid, bool)
        assert isinstance(issues, list)


# =============================================================================
# Test Cluster Utilities
# =============================================================================


class TestClusterUtilities:
    """Tests for cluster utility functions."""

    def test_list_beefcake2_nodes(self) -> None:
        """Test listing beefcake2 nodes."""
        from crystalmath.high_level.clusters import list_beefcake2_nodes

        nodes = list_beefcake2_nodes()

        assert len(nodes) == 6
        assert "vasp-01" in nodes
        assert "qe-node1" in nodes

    def test_list_beefcake2_codes(self) -> None:
        """Test listing beefcake2 codes."""
        from crystalmath.high_level.clusters import list_beefcake2_codes

        codes = list_beefcake2_codes()

        assert len(codes) > 0
        assert "vasp-6.4.3" in codes

    def test_get_cluster_status_summary(self) -> None:
        """Test getting cluster status summary."""
        from crystalmath.high_level.clusters import get_cluster_status_summary

        status = get_cluster_status_summary()

        assert isinstance(status, dict)
        assert "total_nodes" in status


class TestAiidaConfigHelpers:
    """Tests for AiiDA configuration helper functions."""

    def test_get_aiida_computer_config(self) -> None:
        """Test getting AiiDA computer configuration."""
        from crystalmath.high_level.clusters import get_aiida_computer_config

        config = get_aiida_computer_config("vasp-01")

        assert "label" in config
        assert "hostname" in config
        assert "10.0.0.20" in config["hostname"]

    def test_get_aiida_code_config(self) -> None:
        """Test getting AiiDA code configuration."""
        from crystalmath.high_level.clusters import get_aiida_code_config

        config = get_aiida_code_config("vasp-6.4.3", "vasp-01")

        assert "label" in config
        assert "computer" in config


# =============================================================================
# Test Resource Requirements
# =============================================================================


class TestResourceRequirements:
    """Tests for ResourceRequirements dataclass."""

    def test_create_resource_requirements(self) -> None:
        """Test creating resource requirements."""
        resources = ResourceRequirements(
            num_nodes=2,
            num_mpi_ranks=80,
            num_threads_per_rank=1,
            memory_gb=200,
            walltime_hours=48,
            gpus=2,
        )

        assert resources.num_nodes == 2
        assert resources.num_mpi_ranks == 80
        assert resources.gpus == 2

    def test_resource_requirements_from_preset(self) -> None:
        """Test getting resource requirements from preset."""
        from crystalmath.high_level.clusters import get_cluster_profile

        profile = get_cluster_profile("beefcake2")
        resources = profile.get_preset("medium")

        assert resources.num_nodes >= 1
        assert resources.num_mpi_ranks > 0


# =============================================================================
# Test Integration
# =============================================================================


class TestClusterIntegration:
    """Integration tests for cluster configuration."""

    def test_full_workflow_resources(self) -> None:
        """Test getting resources for full workflow."""
        from crystalmath.high_level.clusters import (
            get_cluster_profile,
            get_optimal_resources,
            get_node_for_code,
        )

        # Get cluster profile
        profile = get_cluster_profile("beefcake2")
        assert profile is not None

        # Get optimal resources for VASP
        resources = get_optimal_resources(
            code="vasp",
            system_size=50,
            calculation_type="relax",
        )
        assert resources is not None

        # Get node for VASP
        node_name = get_node_for_code("vasp")
        assert node_name is not None

    def test_multi_code_workflow_resources(self) -> None:
        """Test resources for multi-code workflow."""
        from crystalmath.high_level.clusters import get_optimal_resources

        # DFT step (VASP)
        dft_resources = get_optimal_resources(
            code="vasp",
            system_size=50,
            calculation_type="scf",
        )

        # GW step (YAMBO)
        gw_resources = get_optimal_resources(
            code="yambo",
            system_size=50,
            calculation_type="gw",
        )

        # Both should have resources
        assert dft_resources is not None
        assert gw_resources is not None
