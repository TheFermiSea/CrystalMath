"""
CRYSTAL23 environment configuration module.

This module handles loading and validating the CRYSTAL23 environment
by sourcing cry23.bashrc and extracting required configuration.
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class CrystalConfig:
    """Configuration for CRYSTAL23 environment."""

    executable_dir: Path
    scratch_dir: Path
    version: str
    executable_path: Path

    def __post_init__(self):
        """Validate configuration after initialization."""
        # Convert to Path objects if strings were provided
        if not isinstance(self.executable_dir, Path):
            self.executable_dir = Path(self.executable_dir)
        if not isinstance(self.scratch_dir, Path):
            self.scratch_dir = Path(self.scratch_dir)
        if not isinstance(self.executable_path, Path):
            self.executable_path = Path(self.executable_path)


class EnvironmentError(Exception):
    """Custom exception for environment configuration errors."""
    pass


# Singleton config cache
_cached_config: Optional[CrystalConfig] = None


def load_crystal_environment(
    bashrc_path: Optional[Path] = None,
    force_reload: bool = False
) -> CrystalConfig:
    """
    Load CRYSTAL23 environment configuration.

    Sources cry23.bashrc and extracts environment variables to create
    a validated CrystalConfig object.

    Args:
        bashrc_path: Path to cry23.bashrc (default: auto-detect from CRYSTAL23 structure)
        force_reload: If True, bypass cached config and reload from bashrc

    Returns:
        CrystalConfig: Validated configuration object

    Raises:
        EnvironmentError: If configuration is invalid or files are missing
    """
    global _cached_config

    # Return cached config if available and not forcing reload
    if _cached_config is not None and not force_reload:
        return _cached_config

    # Determine bashrc path
    if bashrc_path is None:
        # Try to auto-detect from current file location
        # This file is in: CRYSTAL23/bin/crystal-tui/src/core/
        # bashrc is in: CRYSTAL23/utils23/
        project_root = Path(__file__).parent.parent.parent.parent.parent
        bashrc_path = project_root / "utils23" / "cry23.bashrc"

    if not bashrc_path.exists():
        raise EnvironmentError(
            f"cry23.bashrc not found at: {bashrc_path}\n"
            f"Please ensure CRYSTAL23 is properly installed."
        )

    # Source bashrc and extract environment variables
    try:
        config_data = _source_bashrc(bashrc_path)
    except subprocess.CalledProcessError as e:
        raise EnvironmentError(
            f"Failed to source cry23.bashrc: {e}\n"
            f"Return code: {e.returncode}\n"
            f"Output: {e.output}"
        )
    except Exception as e:
        raise EnvironmentError(f"Error loading environment: {e}")

    # Create config object
    executable_dir = Path(config_data['CRY23_EXEDIR'])
    scratch_dir = Path(config_data['CRY23_SCRDIR'])
    version = config_data['VERSION']

    # Construct full path to crystalOMP
    executable_path = executable_dir / 'crystalOMP'

    # Validate configuration
    _validate_environment(executable_dir, executable_path, scratch_dir)

    # Create config object
    config = CrystalConfig(
        executable_dir=executable_dir,
        scratch_dir=scratch_dir,
        version=version,
        executable_path=executable_path
    )

    # Cache and return
    _cached_config = config
    return config


def _source_bashrc(bashrc_path: Path) -> dict[str, str]:
    """
    Source bashrc and extract environment variables.

    Args:
        bashrc_path: Path to cry23.bashrc

    Returns:
        Dictionary of environment variable names to values

    Raises:
        subprocess.CalledProcessError: If bash command fails
    """
    # Create bash command that sources the file and prints variables
    bash_cmd = f"""
    source "{bashrc_path}"
    echo "CRY23_EXEDIR=$CRY23_EXEDIR"
    echo "CRY23_SCRDIR=$CRY23_SCRDIR"
    echo "VERSION=$VERSION"
    """

    # Execute command
    result = subprocess.run(
        ['bash', '-c', bash_cmd],
        capture_output=True,
        text=True,
        check=True
    )

    # Parse output
    config_data = {}
    for line in result.stdout.strip().split('\n'):
        # Skip echo messages from cry23.bashrc
        if '=' not in line:
            continue

        # Parse KEY=VALUE lines
        key, value = line.split('=', 1)
        if key in ['CRY23_EXEDIR', 'CRY23_SCRDIR', 'VERSION']:
            config_data[key] = value

    # Validate we got all required variables
    required = ['CRY23_EXEDIR', 'CRY23_SCRDIR', 'VERSION']
    missing = [var for var in required if var not in config_data]
    if missing:
        raise EnvironmentError(
            f"Failed to extract required environment variables from cry23.bashrc: {', '.join(missing)}\n"
            f"Output was:\n{result.stdout}"
        )

    return config_data


def _validate_environment(
    executable_dir: Path,
    executable_path: Path,
    scratch_dir: Path
) -> None:
    """
    Validate that the environment is properly configured.

    Args:
        executable_dir: Directory containing executables
        executable_path: Full path to crystalOMP executable
        scratch_dir: Scratch directory for temporary files

    Raises:
        EnvironmentError: If validation fails
    """
    # Check executable directory exists
    if not executable_dir.exists():
        raise EnvironmentError(
            f"Executable directory does not exist: {executable_dir}\n"
            f"Please ensure CRYSTAL23 binaries are properly installed."
        )

    if not executable_dir.is_dir():
        raise EnvironmentError(
            f"Executable path is not a directory: {executable_dir}"
        )

    # Check crystalOMP exists
    if not executable_path.exists():
        raise EnvironmentError(
            f"crystalOMP executable not found: {executable_path}\n"
            f"Expected location: {executable_dir}/crystalOMP\n"
            f"Please ensure CRYSTAL23 binaries are properly compiled."
        )

    # Check crystalOMP is executable
    if not os.access(executable_path, os.X_OK):
        raise EnvironmentError(
            f"crystalOMP is not executable: {executable_path}\n"
            f"Try running: chmod +x {executable_path}"
        )

    # Create scratch directory if it doesn't exist
    try:
        scratch_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise EnvironmentError(
            f"Failed to create scratch directory: {scratch_dir}\n"
            f"Error: {e}"
        )

    # Verify scratch directory is writable
    if not os.access(scratch_dir, os.W_OK):
        raise EnvironmentError(
            f"Scratch directory is not writable: {scratch_dir}\n"
            f"Please check permissions."
        )


def get_crystal_config() -> CrystalConfig:
    """
    Get the cached CRYSTAL23 configuration.

    This is a convenience function that returns the cached config
    without forcing a reload. If config hasn't been loaded yet,
    it will load it automatically.

    Returns:
        CrystalConfig: The current configuration

    Raises:
        EnvironmentError: If configuration cannot be loaded
    """
    return load_crystal_environment()


def reset_config_cache() -> None:
    """Reset the cached configuration (useful for testing)."""
    global _cached_config
    _cached_config = None
