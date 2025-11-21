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

    root_dir: Path
    executable_dir: Path
    scratch_dir: Path
    utils_dir: Path
    architecture: str
    version: str
    executable_path: Path

    def __post_init__(self):
        """Validate configuration after initialization."""
        # Convert to Path objects if strings were provided
        if not isinstance(self.root_dir, Path):
            self.root_dir = Path(self.root_dir)
        if not isinstance(self.executable_dir, Path):
            self.executable_dir = Path(self.executable_dir)
        if not isinstance(self.scratch_dir, Path):
            self.scratch_dir = Path(self.scratch_dir)
        if not isinstance(self.utils_dir, Path):
            self.utils_dir = Path(self.utils_dir)
        if not isinstance(self.executable_path, Path):
            self.executable_path = Path(self.executable_path)


class EnvironmentError(Exception):
    """Custom exception for environment configuration errors."""
    pass


# Singleton config cache
_cached_config: Optional[CrystalConfig] = None


def _find_bashrc_path(explicit_path: Optional[Path] = None) -> Path:
    """
    Find cry23.bashrc using precedence chain.

    Precedence order:
    1. Explicit path parameter (highest priority)
    2. CRY23_ROOT environment variable
    3. Development layout detection (last resort)

    Args:
        explicit_path: Explicitly specified bashrc path

    Returns:
        Path: Path to cry23.bashrc (may not exist yet)
    """
    # 1. Explicit parameter (highest priority)
    if explicit_path is not None:
        return explicit_path.resolve()

    # 2. CRY23_ROOT environment variable
    cry23_root = os.environ.get('CRY23_ROOT')
    if cry23_root:
        bashrc = Path(cry23_root) / 'utils23' / 'cry23.bashrc'
        if bashrc.exists():
            return bashrc.resolve()

    # 3. Development layout (last resort)
    # This file is in: CRYSTAL23/crystalmath/tui/src/core/environment.py
    # bashrc is in: CRYSTAL23/utils23/cry23.bashrc
    # Path structure: environment.py -> core -> src -> tui -> crystalmath -> CRYSTAL23
    dev_bashrc = Path(__file__).resolve().parents[4] / 'utils23' / 'cry23.bashrc'
    if dev_bashrc.exists():
        return dev_bashrc

    # Return best guess (development layout) even if it doesn't exist
    # Will be caught and reported clearly by load_crystal_environment
    return dev_bashrc


def load_crystal_environment(
    bashrc_path: Optional[Path] = None,
    force_reload: bool = False
) -> CrystalConfig:
    """
    Load CRYSTAL23 environment configuration with proper fallback chain.

    Sources cry23.bashrc and extracts environment variables to create
    a validated CrystalConfig object.

    Precedence for finding cry23.bashrc:
    1. Explicit bashrc_path parameter (highest priority)
    2. CRY23_ROOT environment variable
    3. Development layout detection (__file__.parents[4]) as last resort

    Args:
        bashrc_path: Path to cry23.bashrc (explicit override, highest priority)
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

    # Determine bashrc path using precedence chain
    bashrc_path = _find_bashrc_path(bashrc_path)

    if not bashrc_path.exists():
        raise EnvironmentError(
            f"cry23.bashrc not found at: {bashrc_path}\n"
            f"\nPlease ensure CRYSTAL23 is properly installed and configured.\n"
            f"\nSetup instructions:\n"
            f"1. Set environment variable: export CRY23_ROOT=/path/to/CRYSTAL23\n"
            f"2. Verify bashrc exists: $CRY23_ROOT/utils23/cry23.bashrc\n"
            f"3. Or pass explicit path: load_crystal_environment(bashrc_path=Path('/...'))\n"
            f"\nExpected location: <CRYSTAL23_ROOT>/utils23/cry23.bashrc"
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

    # Extract configuration paths
    root_dir = Path(config_data['CRY23_ROOT'])
    executable_dir = Path(config_data['CRY23_EXEDIR'])
    scratch_dir = Path(config_data['CRY23_SCRDIR'])
    utils_dir = Path(config_data['CRY23_UTILS'])
    architecture = config_data['CRY23_ARCH']
    version = config_data['VERSION']

    # Construct full path to crystalOMP
    executable_path = executable_dir / 'crystalOMP'

    # Validate configuration
    _validate_environment(executable_dir, executable_path, scratch_dir)

    # Create config object
    config = CrystalConfig(
        root_dir=root_dir,
        executable_dir=executable_dir,
        scratch_dir=scratch_dir,
        utils_dir=utils_dir,
        architecture=architecture,
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
    # Redirect echo output from cry23.bashrc to stderr so we only get our output
    bash_cmd = f"""
    source "{bashrc_path}" >/dev/null 2>&1
    echo "CRY23_ROOT=$CRY23_ROOT"
    echo "CRY23_EXEDIR=$CRY23_EXEDIR"
    echo "CRY23_SCRDIR=$CRY23_SCRDIR"
    echo "CRY23_UTILS=$CRY23_UTILS"
    echo "CRY23_ARCH=$CRY23_ARCH"
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
        # Skip empty lines
        if not line or '=' not in line:
            continue

        # Parse KEY=VALUE lines
        key, value = line.split('=', 1)
        if key in ['CRY23_ROOT', 'CRY23_EXEDIR', 'CRY23_SCRDIR', 'CRY23_UTILS', 'CRY23_ARCH', 'VERSION']:
            config_data[key] = value

    # Validate we got all required variables
    required = ['CRY23_ROOT', 'CRY23_EXEDIR', 'CRY23_SCRDIR', 'CRY23_UTILS', 'CRY23_ARCH', 'VERSION']
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
