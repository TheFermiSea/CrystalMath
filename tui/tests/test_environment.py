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
    _find_bashrc_path,
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
            root_dir=Path("/path/to/CRYSTAL23"),
            executable_dir=Path("/path/to/bin"),
            scratch_dir=Path("/tmp/crystal"),
            utils_dir=Path("/path/to/utils23"),
            architecture="MacOsx_ARM-gfortran_omp",
            version="v1.0.1",
            executable_path=Path("/path/to/bin/crystalOMP")
        )

        assert config.root_dir == Path("/path/to/CRYSTAL23")
        assert config.executable_dir == Path("/path/to/bin")
        assert config.scratch_dir == Path("/tmp/crystal")
        assert config.utils_dir == Path("/path/to/utils23")
        assert config.architecture == "MacOsx_ARM-gfortran_omp"
        assert config.version == "v1.0.1"
        assert config.executable_path == Path("/path/to/bin/crystalOMP")

    def test_config_path_conversion(self):
        """Test that strings are converted to Path objects."""
        config = CrystalConfig(
            root_dir="/path/to/CRYSTAL23",
            executable_dir="/path/to/bin",
            scratch_dir="/tmp/crystal",
            utils_dir="/path/to/utils23",
            architecture="MacOsx_ARM-gfortran_omp",
            version="v1.0.1",
            executable_path="/path/to/bin/crystalOMP"
        )

        assert isinstance(config.root_dir, Path)
        assert isinstance(config.executable_dir, Path)
        assert isinstance(config.scratch_dir, Path)
        assert isinstance(config.utils_dir, Path)
        assert isinstance(config.executable_path, Path)


class TestFindBashrcPath:
    """Tests for _find_bashrc_path function (precedence chain)."""

    def test_explicit_path_highest_priority(self, tmp_path):
        """Test that explicit path has highest priority."""
        explicit_bashrc = tmp_path / "explicit" / "cry23.bashrc"
        explicit_bashrc.parent.mkdir(parents=True)
        explicit_bashrc.touch()

        result = _find_bashrc_path(explicit_path=explicit_bashrc)
        assert result == explicit_bashrc.resolve()

    def test_explicit_path_even_if_invalid(self, tmp_path):
        """Test explicit path is returned even if it doesn't exist."""
        explicit_bashrc = tmp_path / "nonexistent" / "cry23.bashrc"

        result = _find_bashrc_path(explicit_path=explicit_bashrc)
        assert result == explicit_bashrc.resolve()

    def test_cry23_root_env_var_second_priority(self, tmp_path):
        """Test CRY23_ROOT environment variable is checked second."""
        cry23_root = tmp_path / "crystal23"
        bashrc = cry23_root / "utils23" / "cry23.bashrc"
        bashrc.parent.mkdir(parents=True)
        bashrc.touch()

        with patch.dict(os.environ, {'CRY23_ROOT': str(cry23_root)}):
            # Clear explicit path
            result = _find_bashrc_path(explicit_path=None)
            assert result == bashrc.resolve()

    def test_cry23_root_env_var_ignored_if_not_exists(self, tmp_path):
        """Test CRY23_ROOT is skipped if bashrc doesn't exist there."""
        cry23_root = tmp_path / "crystal23"
        # Don't create bashrc

        with patch.dict(os.environ, {'CRY23_ROOT': str(cry23_root)}):
            result = _find_bashrc_path(explicit_path=None)
            # Should fall back to development layout
            # The key is that it doesn't use the non-existent CRY23_ROOT path
            assert str(cry23_root) not in str(result)

    def test_development_layout_last_resort(self, tmp_path):
        """Test development layout is checked as last resort."""
        with patch.dict(os.environ, {}, clear=True):  # Clear CRY23_ROOT
            result = _find_bashrc_path(explicit_path=None)
            # Should compute dev_bashrc path (will include utils23/cry23.bashrc)
            assert 'utils23' in str(result)
            assert 'cry23.bashrc' in str(result)

    def test_precedence_explicit_over_env_var(self, tmp_path):
        """Test explicit path takes precedence over CRY23_ROOT."""
        explicit_bashrc = tmp_path / "explicit" / "cry23.bashrc"
        explicit_bashrc.parent.mkdir(parents=True)
        explicit_bashrc.touch()

        cry23_root = tmp_path / "crystal23"
        env_bashrc = cry23_root / "utils23" / "cry23.bashrc"
        env_bashrc.parent.mkdir(parents=True)
        env_bashrc.touch()

        with patch.dict(os.environ, {'CRY23_ROOT': str(cry23_root)}):
            result = _find_bashrc_path(explicit_path=explicit_bashrc)
            assert result == explicit_bashrc.resolve()
            assert result != env_bashrc.resolve()

    def test_returns_path_object(self, tmp_path):
        """Test that function returns resolved Path object."""
        bashrc = tmp_path / "cry23.bashrc"
        bashrc.touch()

        result = _find_bashrc_path(explicit_path=bashrc)
        assert isinstance(result, Path)
        assert result.is_absolute()


class TestSourceBashrc:
    """Tests for _source_bashrc function."""

    @patch('subprocess.run')
    def test_source_bashrc_success(self, mock_run):
        """Test successful bashrc sourcing."""
        mock_run.return_value = MagicMock(
            stdout=(
                "CRY23_ROOT=/path/to/CRYSTAL23\n"
                "CRY23_EXEDIR=/path/to/bin\n"
                "CRY23_SCRDIR=/tmp\n"
                "CRY23_UTILS=/path/to/utils23\n"
                "CRY23_ARCH=MacOsx_ARM-gfortran_omp\n"
                "VERSION=v1.0.1\n"
            ),
            returncode=0
        )

        result = _source_bashrc(Path("/path/to/cry23.bashrc"))

        assert result == {
            'CRY23_ROOT': '/path/to/CRYSTAL23',
            'CRY23_EXEDIR': '/path/to/bin',
            'CRY23_SCRDIR': '/tmp',
            'CRY23_UTILS': '/path/to/utils23',
            'CRY23_ARCH': 'MacOsx_ARM-gfortran_omp',
            'VERSION': 'v1.0.1'
        }

    @patch('subprocess.run')
    def test_source_bashrc_with_empty_lines(self, mock_run):
        """Test bashrc sourcing handles empty lines."""
        mock_run.return_value = MagicMock(
            stdout=(
                "CRY23_ROOT=/path/to/CRYSTAL23\n"
                "\n"
                "CRY23_EXEDIR=/path/to/bin\n"
                "CRY23_SCRDIR=/tmp\n"
                "CRY23_UTILS=/path/to/utils23\n"
                "CRY23_ARCH=MacOsx_ARM-gfortran_omp\n"
                "VERSION=v1.0.1\n"
            ),
            returncode=0
        )

        result = _source_bashrc(Path("/path/to/cry23.bashrc"))

        assert result == {
            'CRY23_ROOT': '/path/to/CRYSTAL23',
            'CRY23_EXEDIR': '/path/to/bin',
            'CRY23_SCRDIR': '/tmp',
            'CRY23_UTILS': '/path/to/utils23',
            'CRY23_ARCH': 'MacOsx_ARM-gfortran_omp',
            'VERSION': 'v1.0.1'
        }

    @patch('subprocess.run')
    def test_source_bashrc_missing_variables(self, mock_run):
        """Test error when required variables are missing."""
        mock_run.return_value = MagicMock(
            stdout="CRY23_EXEDIR=/path/to/bin\nCRY23_SCRDIR=/tmp\n",
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

    def test_error_message_has_setup_instructions(self, tmp_path):
        """Test that error message includes setup instructions."""
        bashrc_path = tmp_path / "nonexistent.bashrc"

        try:
            load_crystal_environment(bashrc_path=bashrc_path)
            pytest.fail("Expected EnvironmentError")
        except EnvironmentError as e:
            error_msg = str(e)
            # Should include setup instructions
            assert "Setup instructions" in error_msg
            assert "CRY23_ROOT" in error_msg
            assert "export CRY23_ROOT" in error_msg
            assert "utils23/cry23.bashrc" in error_msg

    @patch('src.core.environment._source_bashrc')
    @patch('src.core.environment._validate_environment')
    def test_load_success(self, mock_validate, mock_source, tmp_path):
        """Test successful environment loading."""
        bashrc_path = tmp_path / "cry23.bashrc"
        bashrc_path.touch()

        mock_source.return_value = {
            'CRY23_ROOT': str(tmp_path),
            'CRY23_EXEDIR': str(tmp_path / "bin"),
            'CRY23_SCRDIR': str(tmp_path / "scratch"),
            'CRY23_UTILS': str(tmp_path / "utils23"),
            'CRY23_ARCH': 'MacOsx_ARM-gfortran_omp',
            'VERSION': 'v1.0.1'
        }

        config = load_crystal_environment(bashrc_path=bashrc_path)

        assert isinstance(config, CrystalConfig)
        assert config.root_dir == tmp_path
        assert config.executable_dir == tmp_path / "bin"
        assert config.scratch_dir == tmp_path / "scratch"
        assert config.utils_dir == tmp_path / "utils23"
        assert config.architecture == "MacOsx_ARM-gfortran_omp"
        assert config.version == "v1.0.1"
        assert config.executable_path == tmp_path / "bin" / "crystalOMP"

    @patch('src.core.environment._source_bashrc')
    @patch('src.core.environment._validate_environment')
    def test_load_caching(self, mock_validate, mock_source, tmp_path):
        """Test that config is cached after first load."""
        bashrc_path = tmp_path / "cry23.bashrc"
        bashrc_path.touch()

        mock_source.return_value = {
            'CRY23_ROOT': str(tmp_path),
            'CRY23_EXEDIR': str(tmp_path / "bin"),
            'CRY23_SCRDIR': str(tmp_path / "scratch"),
            'CRY23_UTILS': str(tmp_path / "utils23"),
            'CRY23_ARCH': 'MacOsx_ARM-gfortran_omp',
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
            'CRY23_ROOT': str(tmp_path),
            'CRY23_EXEDIR': str(tmp_path / "bin"),
            'CRY23_SCRDIR': str(tmp_path / "scratch"),
            'CRY23_UTILS': str(tmp_path / "utils23"),
            'CRY23_ARCH': 'MacOsx_ARM-gfortran_omp',
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


class TestCrossPlatform:
    """Tests for cross-platform compatibility."""

    @patch('subprocess.run')
    def test_linux_environment(self, mock_run, tmp_path):
        """Test loading environment with Linux-style paths."""
        bashrc_path = tmp_path / "cry23.bashrc"
        bashrc_path.touch()

        mock_run.return_value = MagicMock(
            stdout=(
                "CRY23_ROOT=/home/user/CRYSTAL23\n"
                "CRY23_EXEDIR=/home/user/CRYSTAL23/bin/Linux-ifort_i64_omp/v1.0.1\n"
                "CRY23_SCRDIR=/tmp/crystal\n"
                "CRY23_UTILS=/home/user/CRYSTAL23/utils23\n"
                "CRY23_ARCH=Linux-ifort_i64_omp\n"
                "VERSION=v1.0.1\n"
            ),
            returncode=0
        )

        with patch('src.core.environment._validate_environment'):
            config = load_crystal_environment(bashrc_path=bashrc_path)
            assert config.architecture == "Linux-ifort_i64_omp"
            assert str(config.root_dir) == "/home/user/CRYSTAL23"

    @patch('subprocess.run')
    def test_macos_environment(self, mock_run, tmp_path):
        """Test loading environment with macOS-style paths."""
        bashrc_path = tmp_path / "cry23.bashrc"
        bashrc_path.touch()

        mock_run.return_value = MagicMock(
            stdout=(
                "CRY23_ROOT=/Users/user/CRYSTAL23\n"
                "CRY23_EXEDIR=/Users/user/CRYSTAL23/bin/MacOsx_ARM-gfortran_omp/v1.0.1\n"
                "CRY23_SCRDIR=/Users/user/tmp\n"
                "CRY23_UTILS=/Users/user/CRYSTAL23/utils23\n"
                "CRY23_ARCH=MacOsx_ARM-gfortran_omp\n"
                "VERSION=v1.0.1\n"
            ),
            returncode=0
        )

        with patch('src.core.environment._validate_environment'):
            config = load_crystal_environment(bashrc_path=bashrc_path)
            assert config.architecture == "MacOsx_ARM-gfortran_omp"
            assert str(config.root_dir) == "/Users/user/CRYSTAL23"


class TestIntegration:
    """Integration tests with real CRYSTAL23 installation."""

    def test_load_real_environment(self):
        """Test loading actual CRYSTAL23 environment (if available)."""
        # This test will only work if CRYSTAL23 is properly installed
        try:
            config = load_crystal_environment()

            # Basic validation
            assert config.version == "v1.0.1"
            assert config.root_dir.exists()
            assert config.executable_dir.exists()
            assert config.executable_path.exists()
            assert config.scratch_dir.exists()
            assert config.utils_dir.exists()
            assert os.access(config.executable_path, os.X_OK)

            print(f"\nSuccessfully loaded CRYSTAL23 environment:")
            print(f"  Root: {config.root_dir}")
            print(f"  Architecture: {config.architecture}")
            print(f"  Version: {config.version}")
            print(f"  Executable: {config.executable_path}")
            print(f"  Utils: {config.utils_dir}")
            print(f"  Scratch dir: {config.scratch_dir}")

        except EnvironmentError as e:
            pytest.skip(f"CRYSTAL23 not properly installed: {e}")
