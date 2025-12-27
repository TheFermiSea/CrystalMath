"""
Configuration file loader for crystalmath TUI.

Loads cluster configurations from YAML files and imports them into the database.
Supports cluster definitions, SLURM settings, and environment configurations.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

import yaml

from .database import Database, Cluster

logger = logging.getLogger(__name__)


class ClusterConfig:
    """Parsed cluster configuration from YAML."""

    def __init__(self, config_path: Path):
        """
        Load and parse a cluster configuration file.

        Args:
            config_path: Path to the YAML configuration file.
        """
        self.config_path = config_path
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load and validate the configuration file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(self.config_path) as f:
            self._data = yaml.safe_load(f)

        self._validate()

    def _validate(self) -> None:
        """Validate required configuration fields."""
        required = ["name", "type", "connection"]
        for field in required:
            if field not in self._data:
                raise ValueError(f"Missing required field '{field}' in {self.config_path}")

        # Validate connection settings
        conn = self._data.get("connection", {})
        if "hostname" not in conn:
            raise ValueError(f"Missing 'connection.hostname' in {self.config_path}")
        if "username" not in conn:
            raise ValueError(f"Missing 'connection.username' in {self.config_path}")

    @property
    def name(self) -> str:
        """Cluster name."""
        return self._data["name"]

    @property
    def description(self) -> str:
        """Cluster description."""
        return self._data.get("description", "")

    @property
    def cluster_type(self) -> str:
        """Cluster type (ssh or slurm)."""
        return self._data["type"]

    @property
    def dft_code(self) -> str:
        """DFT code this cluster is configured for."""
        return self._data.get("dft_code", "crystal")

    @property
    def hostname(self) -> str:
        """SSH hostname."""
        return self._data["connection"]["hostname"]

    @property
    def port(self) -> int:
        """SSH port."""
        return self._data["connection"].get("port", 22)

    @property
    def username(self) -> str:
        """SSH username."""
        return self._data["connection"]["username"]

    @property
    def key_file(self) -> Optional[str]:
        """SSH key file path."""
        return self._data["connection"].get("key_file")

    @property
    def password(self) -> Optional[str]:
        """SSH password (not recommended)."""
        return self._data["connection"].get("password")

    @property
    def nodes(self) -> List[Dict[str, Any]]:
        """List of compute nodes."""
        return self._data.get("nodes", [])

    @property
    def hardware(self) -> Dict[str, Any]:
        """Hardware specifications."""
        return self._data.get("hardware", {})

    @property
    def slurm_settings(self) -> Dict[str, Any]:
        """SLURM scheduler settings."""
        return self._data.get("slurm", {})

    @property
    def software(self) -> Dict[str, Any]:
        """Software environment configuration."""
        return self._data.get("software", {})

    @property
    def defaults(self) -> Dict[str, Any]:
        """Default job settings."""
        return self._data.get("defaults", {})

    @property
    def directories(self) -> Dict[str, str]:
        """Directory paths."""
        return self._data.get("directories", {})

    @property
    def gres(self) -> Dict[str, str]:
        """SLURM GRES configuration."""
        return self._data.get("gres", {})

    def to_connection_config(self) -> Dict[str, Any]:
        """
        Build the connection_config JSON for database storage.

        Returns:
            Dictionary suitable for storing in clusters.connection_config.
        """
        config: Dict[str, Any] = {
            "dft_code": self.dft_code,
        }

        # SSH authentication
        if self.key_file:
            config["key_file"] = self.key_file
        if self.password:
            config["password"] = self.password

        # SLURM settings
        if self.slurm_settings:
            config["slurm"] = self.slurm_settings

        # Hardware specs
        if self.hardware:
            config["hardware"] = self.hardware

        # Software environment
        if self.software:
            config["software"] = self.software

        # Node list
        if self.nodes:
            config["nodes"] = self.nodes

        # GRES (Generic Resources)
        if self.gres:
            config["gres"] = self.gres

        # Default job settings
        if self.defaults:
            config["defaults"] = self.defaults

        # Directories
        if self.directories:
            config["directories"] = self.directories

        return config

    def to_dict(self) -> Dict[str, Any]:
        """Return raw configuration dictionary."""
        return self._data.copy()


class ConfigLoader:
    """Loads and manages cluster configurations."""

    def __init__(self, db: Database, config_dir: Optional[Path] = None):
        """
        Initialize the config loader.

        Args:
            db: Database instance.
            config_dir: Directory containing cluster config files.
                       Defaults to config/clusters/ relative to package.
        """
        self.db = db
        if config_dir is None:
            # Default to config/clusters/ in the tui directory
            config_dir = Path(__file__).parent.parent.parent / "config" / "clusters"
        self.config_dir = config_dir

    def discover_configs(self) -> List[Path]:
        """
        Discover all cluster configuration files.

        Returns:
            List of paths to YAML config files.
        """
        if not self.config_dir.exists():
            logger.warning(f"Config directory not found: {self.config_dir}")
            return []

        configs = list(self.config_dir.glob("*.yaml"))
        configs.extend(self.config_dir.glob("*.yml"))
        return sorted(configs)

    def load_config(self, config_path: Path) -> ClusterConfig:
        """
        Load a single cluster configuration.

        Args:
            config_path: Path to the configuration file.

        Returns:
            Parsed ClusterConfig object.
        """
        return ClusterConfig(config_path)

    def import_cluster(
        self,
        config: ClusterConfig,
        update_existing: bool = True
    ) -> int:
        """
        Import a cluster configuration into the database.

        Args:
            config: Parsed cluster configuration.
            update_existing: If True, update existing cluster with same name.

        Returns:
            Cluster ID in the database.
        """
        existing = self.db.get_cluster_by_name(config.name)

        if existing:
            if update_existing:
                logger.info(f"Updating existing cluster: {config.name}")
                self.db.update_cluster(
                    cluster_id=existing.id,
                    hostname=config.hostname,
                    port=config.port,
                    username=config.username,
                    connection_config=config.to_connection_config(),
                    status="active"
                )
                return existing.id
            else:
                logger.warning(f"Cluster '{config.name}' already exists, skipping")
                return existing.id

        logger.info(f"Creating new cluster: {config.name}")
        cluster_id = self.db.create_cluster(
            name=config.name,
            type=config.cluster_type,
            hostname=config.hostname,
            username=config.username,
            port=config.port,
            connection_config=config.to_connection_config()
        )
        return cluster_id

    def import_all(self, update_existing: bool = True) -> Dict[str, int]:
        """
        Import all discovered cluster configurations.

        Args:
            update_existing: If True, update existing clusters.

        Returns:
            Dictionary mapping cluster name to database ID.
        """
        results = {}
        for config_path in self.discover_configs():
            try:
                config = self.load_config(config_path)
                cluster_id = self.import_cluster(config, update_existing)
                results[config.name] = cluster_id
                logger.info(f"Imported cluster '{config.name}' (id={cluster_id})")
            except Exception as e:
                logger.error(f"Failed to import {config_path}: {e}")
        return results


def load_cluster_config(config_path: Path) -> ClusterConfig:
    """
    Convenience function to load a cluster configuration.

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        Parsed ClusterConfig object.
    """
    return ClusterConfig(config_path)


def import_cluster_configs(db: Database, config_dir: Optional[Path] = None) -> Dict[str, int]:
    """
    Convenience function to import all cluster configs from a directory.

    Args:
        db: Database instance.
        config_dir: Optional directory path. Defaults to config/clusters/.

    Returns:
        Dictionary mapping cluster name to database ID.
    """
    loader = ConfigLoader(db, config_dir)
    return loader.import_all()


__all__ = [
    "ClusterConfig",
    "ConfigLoader",
    "load_cluster_config",
    "import_cluster_configs",
]
