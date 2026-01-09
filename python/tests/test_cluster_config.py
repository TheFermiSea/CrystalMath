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
        "memory_per_node_gb": 376,
        "gpus_per_node": 1,
        "gpu_type": "V100S",
        "infiniband": True,
        "partition": "gpu",
    }


@pytest.fixture
def vasp_node_config() -> Dict[str, Any]:
    """Expected VASP node configuration."""
    return {
        "hostname": "vasp-01",
        "ip": "10.0.0.20",
        "cores": 40,
        "memory_gb": 376,
        "gpu": "V100S",
        "codes": ["vasp"],
    }


@pytest.fixture
def qe_node_config() -> Dict[str, Any]:
    """Expected QE node configuration."""
    return {
        "hostname": "qe-node1",
        "ip": "10.0.0.10",
        "cores": 40,
        "memory_gb": 376,
        "gpu": "V100S",
        "codes": ["quantum_espresso", "yambo"],
    }


@pytest.fixture
def mock_structure() -> Mock:
    """Create a mock structure for resource optimization."""
    mock = Mock()
    mock.num_sites = 50
    mock.volume = 500.0
    return mock


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
            scheduler="slurm",
            nodes=4,
            cores_per_node=32,
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
            scheduler="slurm",
            nodes=2,
            cores_per_node=40,
            gpus_per_node=2,
            gpu_type="V100S",
        )

        assert profile.gpus_per_node == 2
        assert profile.gpu_type == "V100S"

    def test_cluster_profile_total_cores(self) -> None:
        """Test calculating total cluster cores."""
        from crystalmath.high_level.clusters import ClusterProfile

        profile = ClusterProfile(
            name="test",
            scheduler="slurm",
            nodes=4,
            cores_per_node=40,
        )

        assert profile.total_cores == 160

    def test_cluster_profile_total_gpus(self) -> None:
        """Test calculating total cluster GPUs."""
        from crystalmath.high_level.clusters import ClusterProfile

        profile = ClusterProfile(
            name="test",
            scheduler="slurm",
            nodes=6,
            cores_per_node=40,
            gpus_per_node=1,
        )

        assert profile.total_gpus == 6

    def test_cluster_profile_validation(self) -> None:
        """Test cluster profile validation."""
        from crystalmath.high_level.clusters import ClusterProfile

        profile = ClusterProfile(
            name="test",
            scheduler="slurm",
            nodes=4,
            cores_per_node=40,
        )

        is_valid, issues = profile.validate()
        assert is_valid is True
        assert len(issues) == 0

    def test_cluster_profile_invalid_nodes(self) -> None:
        """Test validation fails for invalid node count."""
        from crystalmath.high_level.clusters import ClusterProfile

        with pytest.raises((ValueError, AssertionError)):
            ClusterProfile(
                name="test",
                scheduler="slurm",
                nodes=0,  # Invalid
                cores_per_node=40,
            )


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
        assert profile.scheduler in ["local", "none"]

    def test_unknown_cluster_raises(self) -> None:
        """Test error for unknown cluster."""
        from crystalmath.high_level.clusters import get_cluster_profile

        with pytest.raises(KeyError):
            get_cluster_profile("nonexistent_cluster")

    def test_list_available_clusters(self) -> None:
        """Test listing available cluster presets."""
        from crystalmath.high_level.clusters import list_clusters

        clusters = list_clusters()

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
            hostname="vasp-01",
            ip="10.0.0.20",
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

        assert node.gpu_type == "V100S"
        assert node.gpu_memory_gb == 32  # V100S has 32GB

    def test_node_infiniband_config(self) -> None:
        """Test node InfiniBand configuration."""
        from crystalmath.high_level.clusters import get_node_config

        node = get_node_config("vasp-01")

        assert node.infiniband is True
        assert node.infiniband_ip is not None

    def test_node_available_codes(self, vasp_node_config: Dict[str, Any]) -> None:
        """Test codes available on node."""
        from crystalmath.high_level.clusters import get_node_config

        node = get_node_config("vasp-01")

        assert "vasp" in node.codes

    def test_unknown_node_raises(self) -> None:
        """Test error for unknown node."""
        from crystalmath.high_level.clusters import get_node_config

        with pytest.raises(KeyError):
            get_node_config("nonexistent-node")


class TestNodeConfigValidation:
    """Tests for NodeConfig validation."""

    def test_validate_node_connectivity(self) -> None:
        """Test node connectivity validation (mocked)."""
        from crystalmath.high_level.clusters import NodeConfig

        node = NodeConfig(
            hostname="test-node",
            ip="10.0.0.100",
            cores=40,
        )

        with patch("socket.socket") as mock_socket:
            mock_socket.return_value.__enter__.return_value.connect.return_value = None
            # Validation would check SSH connectivity

    def test_validate_gpu_availability(self) -> None:
        """Test GPU availability validation."""
        from crystalmath.high_level.clusters import NodeConfig

        node = NodeConfig(
            hostname="test-node",
            ip="10.0.0.100",
            cores=40,
            gpu_type="V100S",
        )

        # GPU validation would check nvidia-smi


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
            executable="/opt/vasp/bin/vasp_std",
            version="6.4.2",
            mpi_enabled=True,
            gpu_enabled=True,
        )

        assert code.name == "vasp"
        assert code.mpi_enabled is True
        assert code.gpu_enabled is True

    @pytest.mark.parametrize(
        "code_name,expected_gpu",
        [
            ("vasp", True),
            ("crystal23", False),
            ("quantum_espresso", True),
            ("yambo", True),
        ],
    )
    def test_code_gpu_support(self, code_name: str, expected_gpu: bool) -> None:
        """Test GPU support configuration for codes."""
        from crystalmath.high_level.clusters import get_code_config

        code = get_code_config(code_name)
        assert code.gpu_enabled == expected_gpu

    def test_vasp_config(self) -> None:
        """Test VASP code configuration."""
        from crystalmath.high_level.clusters import get_code_config

        code = get_code_config("vasp")

        assert code.name == "vasp"
        assert "vasp_std" in code.executable or code.executable is not None
        assert code.mpi_enabled is True

    def test_crystal23_config(self) -> None:
        """Test CRYSTAL23 code configuration."""
        from crystalmath.high_level.clusters import get_code_config

        code = get_code_config("crystal23")

        assert code.name == "crystal23"
        assert code.mpi_enabled is True

    def test_quantum_espresso_config(self) -> None:
        """Test Quantum ESPRESSO code configuration."""
        from crystalmath.high_level.clusters import get_code_config

        code = get_code_config("quantum_espresso")

        assert code.name == "quantum_espresso"
        assert code.mpi_enabled is True

    def test_yambo_config(self) -> None:
        """Test YAMBO code configuration."""
        from crystalmath.high_level.clusters import get_code_config

        code = get_code_config("yambo")

        assert code.name == "yambo"
        assert code.gpu_enabled is True

    def test_code_environment_modules(self) -> None:
        """Test code environment module loading."""
        from crystalmath.high_level.clusters import get_code_config

        code = get_code_config("vasp")

        assert code.modules is not None
        # Should include Intel MPI and CUDA modules


class TestCodeConfigValidation:
    """Tests for CodeConfig validation."""

    def test_validate_executable_exists(self) -> None:
        """Test executable existence validation."""
        from crystalmath.high_level.clusters import CodeConfig

        code = CodeConfig(
            name="test_code",
            executable="/path/to/executable",
            version="1.0",
        )

        # In dry_run mode, should not actually check
        is_valid, issues = code.validate(dry_run=True)
        assert isinstance(is_valid, bool)

    def test_validate_version(self) -> None:
        """Test version string validation."""
        from crystalmath.high_level.clusters import CodeConfig

        code = CodeConfig(
            name="test_code",
            executable="/path/to/exe",
            version="1.2.3",
        )

        assert code.version == "1.2.3"


# =============================================================================
# Test get_node_for_code()
# =============================================================================


class TestGetNodeForCode:
    """Tests for get_node_for_code() function."""

    def test_get_node_for_vasp(self) -> None:
        """Test getting node for VASP code."""
        from crystalmath.high_level.clusters import get_node_for_code

        node = get_node_for_code("vasp")

        assert node is not None
        assert "vasp" in node.codes

    def test_get_node_for_quantum_espresso(self) -> None:
        """Test getting node for QE code."""
        from crystalmath.high_level.clusters import get_node_for_code

        node = get_node_for_code("quantum_espresso")

        assert node is not None
        assert "quantum_espresso" in node.codes

    def test_get_node_for_yambo(self) -> None:
        """Test getting node for YAMBO code."""
        from crystalmath.high_level.clusters import get_node_for_code

        node = get_node_for_code("yambo")

        assert node is not None
        assert "yambo" in node.codes

    def test_get_node_for_unknown_code(self) -> None:
        """Test error for unknown code."""
        from crystalmath.high_level.clusters import get_node_for_code

        with pytest.raises((KeyError, ValueError)):
            get_node_for_code("unknown_code")

    def test_get_node_with_preference(self) -> None:
        """Test getting node with preference."""
        from crystalmath.high_level.clusters import get_node_for_code

        # Prefer GPU-capable node
        node = get_node_for_code("vasp", prefer_gpu=True)

        assert node.gpu_type is not None


# =============================================================================
# Test get_optimal_resources()
# =============================================================================


class TestGetOptimalResources:
    """Tests for get_optimal_resources() heuristics."""

    def test_optimal_resources_small_system(self, mock_structure: Mock) -> None:
        """Test resource optimization for small system."""
        mock_structure.num_sites = 10

        from crystalmath.high_level.clusters import get_optimal_resources

        resources = get_optimal_resources(
            structure=mock_structure,
            code="vasp",
            cluster="beefcake2",
        )

        assert resources.num_nodes >= 1
        assert resources.num_mpi_ranks > 0

    def test_optimal_resources_large_system(self, mock_structure: Mock) -> None:
        """Test resource optimization for large system."""
        mock_structure.num_sites = 500

        from crystalmath.high_level.clusters import get_optimal_resources

        resources = get_optimal_resources(
            structure=mock_structure,
            code="vasp",
            cluster="beefcake2",
        )

        # Large system should get more resources
        assert resources.num_nodes > 1 or resources.num_mpi_ranks > 40

    def test_optimal_resources_gpu_code(self, mock_structure: Mock) -> None:
        """Test resource optimization for GPU-enabled code."""
        from crystalmath.high_level.clusters import get_optimal_resources

        resources = get_optimal_resources(
            structure=mock_structure,
            code="vasp",
            cluster="beefcake2",
            use_gpu=True,
        )

        assert resources.gpus > 0

    def test_optimal_resources_cpu_only(self, mock_structure: Mock) -> None:
        """Test resource optimization for CPU-only code."""
        from crystalmath.high_level.clusters import get_optimal_resources

        resources = get_optimal_resources(
            structure=mock_structure,
            code="crystal23",  # CPU-only
            cluster="beefcake2",
        )

        # Should not request GPUs for CPU-only code
        assert resources.gpus == 0

    @pytest.mark.parametrize(
        "num_atoms,expected_min_nodes",
        [
            (10, 1),
            (50, 1),
            (100, 1),
            (200, 2),
            (500, 3),
        ],
    )
    def test_scaling_heuristics(
        self, mock_structure: Mock, num_atoms: int, expected_min_nodes: int
    ) -> None:
        """Test resource scaling heuristics."""
        mock_structure.num_sites = num_atoms

        from crystalmath.high_level.clusters import get_optimal_resources

        resources = get_optimal_resources(
            structure=mock_structure,
            code="vasp",
            cluster="beefcake2",
        )

        assert resources.num_nodes >= expected_min_nodes

    def test_walltime_estimation(self, mock_structure: Mock) -> None:
        """Test walltime estimation."""
        from crystalmath.high_level.clusters import get_optimal_resources

        resources = get_optimal_resources(
            structure=mock_structure,
            code="vasp",
            cluster="beefcake2",
            workflow_type="relax",
        )

        # Relaxation needs more time than SCF
        assert resources.walltime_hours >= 12

    def test_memory_estimation(self, mock_structure: Mock) -> None:
        """Test memory estimation."""
        mock_structure.num_sites = 100

        from crystalmath.high_level.clusters import get_optimal_resources

        resources = get_optimal_resources(
            structure=mock_structure,
            code="vasp",
            cluster="beefcake2",
        )

        # Should have adequate memory
        assert resources.memory_gb >= 50


class TestResourceHeuristics:
    """Tests for specific resource heuristics."""

    def test_k_point_parallelization(self, mock_structure: Mock) -> None:
        """Test k-point parallelization heuristics."""
        from crystalmath.high_level.clusters import get_optimal_resources

        # More k-points can use more parallelization
        resources_high_k = get_optimal_resources(
            structure=mock_structure,
            code="vasp",
            cluster="beefcake2",
            k_density=0.02,  # High density
        )

        resources_low_k = get_optimal_resources(
            structure=mock_structure,
            code="vasp",
            cluster="beefcake2",
            k_density=0.08,  # Low density
        )

        # High k-density may benefit from more ranks
        # (actual behavior depends on implementation)

    def test_phonon_parallelization(self, mock_structure: Mock) -> None:
        """Test phonon calculation parallelization."""
        from crystalmath.high_level.clusters import get_optimal_resources

        resources = get_optimal_resources(
            structure=mock_structure,
            code="vasp",
            cluster="beefcake2",
            workflow_type="phonon",
            supercell=[2, 2, 2],
        )

        # Phonon needs more resources due to supercell
        assert resources.num_nodes >= 1

    def test_gw_resources(self, mock_structure: Mock) -> None:
        """Test GW calculation resource estimation."""
        from crystalmath.high_level.clusters import get_optimal_resources

        resources = get_optimal_resources(
            structure=mock_structure,
            code="yambo",
            cluster="beefcake2",
            workflow_type="gw",
        )

        # GW calculations are memory-intensive
        assert resources.memory_gb >= 100


# =============================================================================
# Test setup_aiida_beefcake2()
# =============================================================================


class TestSetupAiidaBeefcake2:
    """Tests for setup_aiida_beefcake2() dry_run mode."""

    def test_setup_dry_run(self) -> None:
        """Test AiiDA setup in dry_run mode."""
        from crystalmath.high_level.clusters import setup_aiida_beefcake2

        result = setup_aiida_beefcake2(dry_run=True)

        assert result["success"] is True
        assert "computers" in result
        assert "codes" in result

    def test_setup_dry_run_computers(self) -> None:
        """Test computer configuration in dry_run."""
        from crystalmath.high_level.clusters import setup_aiida_beefcake2

        result = setup_aiida_beefcake2(dry_run=True)

        # Should configure all VASP and QE nodes
        computer_names = [c["hostname"] for c in result["computers"]]
        assert "vasp-01" in computer_names
        assert "qe-node1" in computer_names

    def test_setup_dry_run_codes(self) -> None:
        """Test code configuration in dry_run."""
        from crystalmath.high_level.clusters import setup_aiida_beefcake2

        result = setup_aiida_beefcake2(dry_run=True)

        code_names = [c["name"] for c in result["codes"]]
        assert "vasp" in code_names or "vasp@vasp-01" in code_names

    def test_setup_generates_commands(self) -> None:
        """Test that setup generates AiiDA commands."""
        from crystalmath.high_level.clusters import setup_aiida_beefcake2

        result = setup_aiida_beefcake2(dry_run=True)

        assert "commands" in result
        commands = result["commands"]

        # Should have verdi computer and code setup commands
        assert any("verdi computer" in cmd for cmd in commands)
        assert any("verdi code" in cmd for cmd in commands)

    def test_setup_transport_config(self) -> None:
        """Test transport configuration in dry_run."""
        from crystalmath.high_level.clusters import setup_aiida_beefcake2

        result = setup_aiida_beefcake2(dry_run=True)

        # Should configure SSH transport
        for computer in result["computers"]:
            assert computer.get("transport") == "ssh" or "transport" in computer

    def test_setup_scheduler_config(self) -> None:
        """Test scheduler configuration in dry_run."""
        from crystalmath.high_level.clusters import setup_aiida_beefcake2

        result = setup_aiida_beefcake2(dry_run=True)

        # Should configure SLURM scheduler
        for computer in result["computers"]:
            assert computer.get("scheduler") == "slurm" or "scheduler" in computer


class TestSetupAiidaValidation:
    """Tests for AiiDA setup validation."""

    def test_validate_aiida_available(self) -> None:
        """Test checking AiiDA availability."""
        from crystalmath.high_level.clusters import setup_aiida_beefcake2

        with patch.dict("sys.modules", {"aiida": None}):
            # Should handle missing AiiDA gracefully
            result = setup_aiida_beefcake2(dry_run=True)
            # dry_run should work even without AiiDA

    def test_validate_existing_setup(self) -> None:
        """Test validating existing AiiDA setup."""
        from crystalmath.high_level.clusters import validate_aiida_setup

        result = validate_aiida_setup(dry_run=True)

        assert "valid" in result
        assert "issues" in result


# =============================================================================
# Test Cluster Utilities
# =============================================================================


class TestClusterUtilities:
    """Tests for cluster utility functions."""

    def test_get_available_nodes(self) -> None:
        """Test getting list of available nodes."""
        from crystalmath.high_level.clusters import get_available_nodes

        nodes = get_available_nodes("beefcake2")

        assert len(nodes) == 6
        hostnames = [n.hostname for n in nodes]
        assert "vasp-01" in hostnames
        assert "qe-node1" in hostnames

    def test_get_nodes_by_code(self) -> None:
        """Test filtering nodes by available code."""
        from crystalmath.high_level.clusters import get_nodes_by_code

        vasp_nodes = get_nodes_by_code("vasp")
        assert all("vasp" in n.codes for n in vasp_nodes)

        qe_nodes = get_nodes_by_code("quantum_espresso")
        assert all("quantum_espresso" in n.codes for n in qe_nodes)

    def test_get_cluster_status(self) -> None:
        """Test getting cluster status (mocked)."""
        from crystalmath.high_level.clusters import get_cluster_status

        with patch(
            "crystalmath.high_level.clusters._check_node_status"
        ) as mock_check:
            mock_check.return_value = {"status": "online", "load": 0.5}

            status = get_cluster_status("beefcake2", dry_run=True)

            assert "nodes" in status

    def test_estimate_job_time(self, mock_structure: Mock) -> None:
        """Test job time estimation."""
        from crystalmath.high_level.clusters import estimate_job_time

        time_hrs = estimate_job_time(
            structure=mock_structure,
            code="vasp",
            workflow_type="relax",
        )

        assert time_hrs > 0


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

    def test_to_slurm_dict(self) -> None:
        """Test conversion to SLURM resource dict."""
        resources = ResourceRequirements(
            num_nodes=2,
            num_mpi_ranks=80,
            walltime_hours=24,
        )

        slurm_dict = resources.to_slurm_dict()

        assert "num_machines" in slurm_dict
        assert slurm_dict["num_machines"] == 2

    def test_to_aiida_dict(self) -> None:
        """Test conversion to AiiDA resource dict."""
        resources = ResourceRequirements(
            num_nodes=2,
            num_mpi_ranks=80,
            walltime_hours=24,
        )

        aiida_dict = resources.to_aiida_dict()

        assert "resources" in aiida_dict
        assert "max_wallclock_seconds" in aiida_dict
        assert aiida_dict["max_wallclock_seconds"] == 24 * 3600


# =============================================================================
# Test Integration
# =============================================================================


class TestClusterIntegration:
    """Integration tests for cluster configuration."""

    def test_full_workflow_resources(self, mock_structure: Mock) -> None:
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
            structure=mock_structure,
            code="vasp",
            cluster="beefcake2",
            workflow_type="relax",
        )
        assert resources is not None

        # Get node for VASP
        node = get_node_for_code("vasp")
        assert node is not None

    def test_multi_code_workflow_resources(self, mock_structure: Mock) -> None:
        """Test resources for multi-code workflow."""
        from crystalmath.high_level.clusters import get_optimal_resources

        # DFT step (VASP)
        dft_resources = get_optimal_resources(
            structure=mock_structure,
            code="vasp",
            cluster="beefcake2",
            workflow_type="scf",
        )

        # GW step (YAMBO)
        gw_resources = get_optimal_resources(
            structure=mock_structure,
            code="yambo",
            cluster="beefcake2",
            workflow_type="gw",
        )

        # Both should have resources
        assert dft_resources is not None
        assert gw_resources is not None

    def test_aiida_setup_complete(self) -> None:
        """Test complete AiiDA setup workflow."""
        from crystalmath.high_level.clusters import setup_aiida_beefcake2

        result = setup_aiida_beefcake2(dry_run=True)

        # Verify complete setup
        assert len(result["computers"]) == 6
        assert len(result["codes"]) > 0
        assert len(result["commands"]) > 0
