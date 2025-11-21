"""
Tests for environment configuration module.
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.core.environment import (
    CrystalConfig,
    EnvironmentError,
    load_crystal_environment,
    get_crystal_config,
    reset_config_cache,
    _source_bashrc,
    _validate_environment,
)


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset config cache before each test."""
    reset_config_cache()
    yield
    reset_config_cache()


class TestCrystalConfig:
    """Tests for CrystalConfig dataclass."""

    def test_config_creation(self):
        """Test creating a CrystalConfig object."""
        config = CrystalConfig(
            executable_dir=Path("/path/to/bin"),
            scratch_dir=Path("/tmp/crystal"),
            version="v1.0.1",
            executable_path=Path("/path/to/bin/crystalOMP")
        )

        assert config.executable_dir == Path("/path/to/bin")
        assert config.scratch_dir == Path("/tmp/crystal")
        assert config.version == "v1.0.1"
        assert config.executable_path == Path("/path/to/bin/crystalOMP")

    def test_config_path_conversion(self):
        """Test that strings are converted to Path objects."""
        config = CrystalConfig(
            executable_dir="/path/to/bin",
            scratch_dir="/tmp/crystal",
            version="v1.0.1",
            executable_path="/path/to/bin/crystalOMP"
        )

        assert isinstance(config.executable_dir, Path)
        assert isinstance(config.scratch_dir, Path)
        assert isinstance(config.executable_path, Path)


class TestSourceBashrc:
    """Tests for _source_bashrc function."""

    @patch('subprocess.run')
    def test_source_bashrc_success(self, mock_run):
        """Test successful bashrc sourcing."""
        mock_run.return_value = MagicMock(
            stdout="CRY23_EXEDIR=/path/to/bin\nCRY23_SCRDIR=/tmp\nVERSION=v1.0.1\n",
            returncode=0
        )

        result = _source_bashrc(Path("/path/to/cry23.bashrc"))

        assert result == {
            'CRY23_EXEDIR': '/path/to/bin',
            'CRY23_SCRDIR': '/tmp',
            'VERSION': 'v1.0.1'
        }

    @patch('subprocess.run')
    def test_source_bashrc_with_echo_output(self, mock_run):
        """Test bashrc sourcing ignores echo messages."""
        mock_run.return_value = MagicMock(
            stdout=(
                "CRY23_SCRDIR - scratch folder: /tmp\n"
                "CRY23_EXEDIR=/path/to/bin\n"
                "CRY23_SCRDIR=/tmp\n"
                "VERSION=v1.0.1\n"
            ),
            returncode=0
        )

        result = _source_bashrc(Path("/path/to/cry23.bashrc"))

        assert result == {
            'CRY23_EXEDIR': '/path/to/bin',
            'CRY23_SCRDIR': '/tmp',
            'VERSION': 'v1.0.1'
        }

    @patch('subprocess.run')
    def test_source_bashrc_missing_variables(self, mock_run):
        """Test error when required variables are missing."""
        mock_run.return_value = MagicMock(
            stdout="CRY23_EXEDIR=/path/to/bin\n",
            returncode=0
        )

        with pytest.raises(EnvironmentError, match="Failed to extract required environment variables"):
            _source_bashrc(Path("/path/to/cry23.bashrc"))


class TestValidateEnvironment:
    """Tests for _validate_environment function."""

    def test_validate_nonexistent_executable_dir(self, tmp_path):
        """Test error when executable directory doesn't exist."""
        exe_dir = tmp_path / "nonexistent"
        exe_path = exe_dir / "crystalOMP"
        scratch_dir = tmp_path / "scratch"

        with pytest.raises(EnvironmentError, match="Executable directory does not exist"):
            _validate_environment(exe_dir, exe_path, scratch_dir)

    def test_validate_executable_dir_is_file(self, tmp_path):
        """Test error when executable dir path is a file."""
        exe_dir = tmp_path / "file.txt"
        exe_dir.touch()
        exe_path = exe_dir / "crystalOMP"
        scratch_dir = tmp_path / "scratch"

        with pytest.raises(EnvironmentError, match="not a directory"):
            _validate_environment(exe_dir, exe_path, scratch_dir)

    def test_validate_missing_executable(self, tmp_path):
        """Test error when crystalOMP doesn't exist."""
        exe_dir = tmp_path / "bin"
        exe_dir.mkdir()
        exe_path = exe_dir / "crystalOMP"
        scratch_dir = tmp_path / "scratch"

        with pytest.raises(EnvironmentError, match="crystalOMP executable not found"):
            _validate_environment(exe_dir, exe_path, scratch_dir)

    def test_validate_non_executable(self, tmp_path):
        """Test error when crystalOMP is not executable."""
        exe_dir = tmp_path / "bin"
        exe_dir.mkdir()
        exe_path = exe_dir / "crystalOMP"
        exe_path.touch()
        scratch_dir = tmp_path / "scratch"

        with pytest.raises(EnvironmentError, match="not executable"):
            _validate_environment(exe_dir, exe_path, scratch_dir)

    def test_validate_creates_scratch_dir(self, tmp_path):
        """Test that scratch directory is created if it doesn't exist."""
        exe_dir = tmp_path / "bin"
        exe_dir.mkdir()
        exe_path = exe_dir / "crystalOMP"
        exe_path.touch()
        exe_path.chmod(0o755)
        scratch_dir = tmp_path / "scratch"

        assert not scratch_dir.exists()
        _validate_environment(exe_dir, exe_path, scratch_dir)
        assert scratch_dir.exists()
        assert scratch_dir.is_dir()

    def test_validate_success(self, tmp_path):
        """Test successful validation."""
        exe_dir = tmp_path / "bin"
        exe_dir.mkdir()
        exe_path = exe_dir / "crystalOMP"
        exe_path.touch()
        exe_path.chmod(0o755)
        scratch_dir = tmp_path / "scratch"
        scratch_dir.mkdir()

        # Should not raise
        _validate_environment(exe_dir, exe_path, scratch_dir)


class TestLoadCrystalEnvironment:
    """Tests for load_crystal_environment function."""

    def test_load_missing_bashrc(self, tmp_path):
        """Test error when bashrc doesn't exist."""
        bashrc_path = tmp_path / "nonexistent.bashrc"

        with pytest.raises(EnvironmentError, match="cry23.bashrc not found"):
            load_crystal_environment(bashrc_path=bashrc_path)

    @patch('src.core.environment._source_bashrc')
    @patch('src.core.environment._validate_environment')
    def test_load_success(self, mock_validate, mock_source, tmp_path):
        """Test successful environment loading."""
        bashrc_path = tmp_path / "cry23.bashrc"
        bashrc_path.touch()

        mock_source.return_value = {
            'CRY23_EXEDIR': str(tmp_path / "bin"),
            'CRY23_SCRDIR': str(tmp_path / "scratch"),
            'VERSION': 'v1.0.1'
        }

        config = load_crystal_environment(bashrc_path=bashrc_path)

        assert isinstance(config, CrystalConfig)
        assert config.executable_dir == tmp_path / "bin"
        assert config.scratch_dir == tmp_path / "scratch"
        assert config.version == "v1.0.1"
        assert config.executable_path == tmp_path / "bin" / "crystalOMP"

    @patch('src.core.environment._source_bashrc')
    @patch('src.core.environment._validate_environment')
    def test_load_caching(self, mock_validate, mock_source, tmp_path):
        """Test that config is cached after first load."""
        bashrc_path = tmp_path / "cry23.bashrc"
        bashrc_path.touch()

        mock_source.return_value = {
            'CRY23_EXEDIR': str(tmp_path / "bin"),
            'CRY23_SCRDIR': str(tmp_path / "scratch"),
            'VERSION': 'v1.0.1'
        }

        # First call
        config1 = load_crystal_environment(bashrc_path=bashrc_path)
        assert mock_source.call_count == 1

        # Second call should use cache
        config2 = load_crystal_environment(bashrc_path=bashrc_path)
        assert mock_source.call_count == 1  # Not called again
        assert config1 is config2  # Same object

    @patch('src.core.environment._source_bashrc')
    @patch('src.core.environment._validate_environment')
    def test_load_force_reload(self, mock_validate, mock_source, tmp_path):
        """Test force reload bypasses cache."""
        bashrc_path = tmp_path / "cry23.bashrc"
        bashrc_path.touch()

        mock_source.return_value = {
            'CRY23_EXEDIR': str(tmp_path / "bin"),
            'CRY23_SCRDIR': str(tmp_path / "scratch"),
            'VERSION': 'v1.0.1'
        }

        # First call
        config1 = load_crystal_environment(bashrc_path=bashrc_path)
        assert mock_source.call_count == 1

        # Second call with force_reload
        config2 = load_crystal_environment(bashrc_path=bashrc_path, force_reload=True)
        assert mock_source.call_count == 2  # Called again
        assert config1 is not config2  # Different objects


class TestGetCrystalConfig:
    """Tests for get_crystal_config function."""

    @patch('src.core.environment.load_crystal_environment')
    def test_get_config(self, mock_load):
        """Test get_crystal_config calls load_crystal_environment."""
        mock_config = MagicMock(spec=CrystalConfig)
        mock_load.return_value = mock_config

        config = get_crystal_config()

        assert config is mock_config
        mock_load.assert_called_once()


class TestIntegration:
    """Integration tests with real CRYSTAL23 installation."""

    def test_load_real_environment(self):
        """Test loading actual CRYSTAL23 environment (if available)."""
        # This test will only work if CRYSTAL23 is properly installed
        try:
            config = load_crystal_environment()

            # Basic validation
            assert config.version == "v1.0.1"
            assert config.executable_dir.exists()
            assert config.executable_path.exists()
            assert config.scratch_dir.exists()
            assert os.access(config.executable_path, os.X_OK)

            print(f"Successfully loaded CRYSTAL23 environment:")
            print(f"  Version: {config.version}")
            print(f"  Executable: {config.executable_path}")
            print(f"  Scratch dir: {config.scratch_dir}")

        except EnvironmentError as e:
            pytest.skip(f"CRYSTAL23 not properly installed: {e}")
