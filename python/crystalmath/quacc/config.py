"""
Cluster configuration storage for Parsl workflow execution.

This module provides Pydantic models and storage for SLURM cluster
configurations used by Parsl for distributed job execution.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# Regex pattern for HH:MM:SS walltime format
WALLTIME_PATTERN = re.compile(r"^\d{1,3}:\d{2}:\d{2}$")


class ParslClusterConfig(BaseModel):
    """
    Configuration for a Parsl SLURM cluster.

    This model defines all parameters needed to configure a Parsl
    HighThroughputExecutor with a SlurmProvider.
    """

    name: str = Field(..., description="Unique cluster name")
    partition: str = Field(..., description="SLURM partition name")
    account: str | None = Field(default=None, description="SLURM account")
    nodes_per_block: int = Field(default=1, ge=1, description="Nodes per Parsl block")
    cores_per_node: int = Field(default=32, ge=1, description="CPU cores per node")
    mem_per_node: int | None = Field(
        default=None, ge=1, description="Memory per node in GB"
    )
    walltime: str = Field(
        default="01:00:00", description="Walltime in HH:MM:SS format"
    )
    max_blocks: int = Field(
        default=10, ge=1, description="Maximum Parsl blocks to scale to"
    )
    worker_init: str = Field(
        default="",
        description="Commands to run before worker starts (module loads, conda activate)",
    )
    scheduler_options: str = Field(
        default="",
        description="Additional #SBATCH directives",
    )

    @field_validator("walltime")
    @classmethod
    def validate_walltime(cls, v: str) -> str:
        """Validate walltime is in HH:MM:SS format."""
        if not WALLTIME_PATTERN.match(v):
            raise ValueError(
                f"Invalid walltime format: {v}. Expected HH:MM:SS or H:MM:SS"
            )
        return v

    model_config = {"extra": "forbid"}


class ClusterConfigStore:
    """
    Persistent storage for cluster configurations.

    Stores cluster configurations in a JSON file, defaulting to
    ~/.crystalmath/clusters.json.
    """

    def __init__(self, config_path: Path | None = None) -> None:
        """
        Initialize the cluster config store.

        Args:
            config_path: Path to the JSON config file. Defaults to
                ~/.crystalmath/clusters.json
        """
        if config_path is None:
            config_path = Path.home() / ".crystalmath" / "clusters.json"
        self.config_path = config_path

        # Create parent directory if needed
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

    def list_clusters(self) -> list[dict[str, Any]]:
        """
        List all stored cluster configurations.

        Returns:
            List of cluster config dicts.
        """
        if not self.config_path.exists():
            return []

        try:
            with open(self.config_path) as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and "clusters" in data:
                    return data["clusters"]
                else:
                    logger.warning(f"Unexpected config format in {self.config_path}")
                    return []
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse cluster config: {e}")
            return []
        except OSError as e:
            logger.error(f"Failed to read cluster config: {e}")
            return []

    def get_cluster(self, name: str) -> ParslClusterConfig | None:
        """
        Get a cluster configuration by name.

        Args:
            name: The cluster name to look up.

        Returns:
            ParslClusterConfig if found, None otherwise.
        """
        clusters = self.list_clusters()
        for cluster in clusters:
            if cluster.get("name") == name:
                try:
                    return ParslClusterConfig(**cluster)
                except Exception as e:
                    logger.error(f"Failed to parse cluster {name}: {e}")
                    return None
        return None

    def save_cluster(self, config: ParslClusterConfig) -> None:
        """
        Save or update a cluster configuration.

        If a cluster with the same name exists, it will be updated.
        Otherwise, a new cluster entry will be added.

        Args:
            config: The cluster configuration to save.
        """
        clusters = self.list_clusters()

        # Find and update existing or append new
        found = False
        for i, cluster in enumerate(clusters):
            if cluster.get("name") == config.name:
                clusters[i] = config.model_dump()
                found = True
                break

        if not found:
            clusters.append(config.model_dump())

        # Write back
        try:
            with open(self.config_path, "w") as f:
                json.dump(clusters, f, indent=2)
        except OSError as e:
            logger.error(f"Failed to write cluster config: {e}")
            raise
