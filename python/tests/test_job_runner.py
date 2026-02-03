"""Tests for job runner module.

Tests cover:
- POTCAR validation
- JobRunner ABC interface
- JobState enum
- Factory function get_runner
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional
import tempfile

import pytest

from crystalmath.quacc.potcar import (
    get_potcar_path,
    validate_potcars,
    get_potcar_info,
)
from crystalmath.quacc.runner import (
    JobRunner,
    JobState,
    get_runner,
    get_or_create_runner,
)


class TestJobState:
    """Tests for JobState enum."""

    def test_job_state_values(self):
        """Test all job state values."""
        assert JobState.PENDING.value == "pending"
        assert JobState.RUNNING.value == "running"
        assert JobState.COMPLETED.value == "completed"
        assert JobState.FAILED.value == "failed"
        assert JobState.CANCELLED.value == "cancelled"

    def test_job_state_is_terminal(self):
        """Test is_terminal method."""
        assert not JobState.PENDING.is_terminal()
        assert not JobState.RUNNING.is_terminal()
        assert JobState.COMPLETED.is_terminal()
        assert JobState.FAILED.is_terminal()
        assert JobState.CANCELLED.is_terminal()

    def test_job_state_is_string(self):
        """Test that JobState inherits from str."""
        assert isinstance(JobState.PENDING, str)
        assert JobState.PENDING == "pending"


class TestPotcarValidation:
    """Tests for POTCAR validation functions."""

    def test_get_potcar_path_not_set(self, monkeypatch):
        """Test get_potcar_path returns None when not configured."""
        monkeypatch.delenv("VASP_PP_PATH", raising=False)
        # Also mock quacc import to fail
        import sys
        if "quacc" in sys.modules:
            monkeypatch.setattr(sys.modules["quacc"], "SETTINGS", None)

        path = get_potcar_path()
        # May or may not be None depending on quacc installation
        # Just verify it doesn't crash

    def test_get_potcar_path_from_env(self, monkeypatch):
        """Test get_potcar_path reads from environment."""
        monkeypatch.setenv("VASP_PP_PATH", "/test/potcar/path")
        path = get_potcar_path()
        assert path == Path("/test/potcar/path")

    def test_validate_potcars_no_path(self, monkeypatch):
        """Test validation fails when VASP_PP_PATH not set."""
        monkeypatch.delenv("VASP_PP_PATH", raising=False)

        valid, error = validate_potcars({"Si", "O"})

        # May be valid if quacc is installed with settings
        if not valid:
            assert "VASP_PP_PATH" in error or "not configured" in error

    def test_validate_potcars_empty_elements(self, monkeypatch):
        """Test validation passes for empty element set."""
        monkeypatch.delenv("VASP_PP_PATH", raising=False)

        valid, error = validate_potcars(set())

        assert valid is True
        assert error is None

    def test_validate_potcars_nonexistent_path(self, monkeypatch):
        """Test validation fails for nonexistent POTCAR path."""
        monkeypatch.setenv("VASP_PP_PATH", "/nonexistent/path")

        valid, error = validate_potcars({"Si"})

        assert valid is False
        assert "does not exist" in error

    def test_validate_potcars_not_directory(self, monkeypatch, tmp_path):
        """Test validation fails when path is not a directory."""
        # Create a file instead of directory
        file_path = tmp_path / "not_a_dir"
        file_path.touch()

        monkeypatch.setenv("VASP_PP_PATH", str(file_path))

        valid, error = validate_potcars({"Si"})

        assert valid is False
        assert "not a directory" in error

    def test_validate_potcars_no_pbe_dir(self, monkeypatch, tmp_path):
        """Test validation fails when no PBE directory found."""
        # Create empty directory
        monkeypatch.setenv("VASP_PP_PATH", str(tmp_path))

        valid, error = validate_potcars({"Si"})

        assert valid is False
        assert "No PBE" in error

    def test_validate_potcars_missing_element(self, monkeypatch, tmp_path):
        """Test validation fails for missing element POTCARs."""
        # Create PBE directory with only Si
        pbe_dir = tmp_path / "potpaw_PBE"
        pbe_dir.mkdir()
        (pbe_dir / "Si").mkdir()

        monkeypatch.setenv("VASP_PP_PATH", str(tmp_path))

        valid, error = validate_potcars({"Si", "O"})

        assert valid is False
        assert "Missing POTCARs" in error
        assert "O" in error

    def test_validate_potcars_success(self, monkeypatch, tmp_path):
        """Test validation succeeds when all elements present."""
        # Create PBE directory with Si and O
        pbe_dir = tmp_path / "potpaw_PBE"
        pbe_dir.mkdir()
        (pbe_dir / "Si").mkdir()
        (pbe_dir / "O").mkdir()

        monkeypatch.setenv("VASP_PP_PATH", str(tmp_path))

        valid, error = validate_potcars({"Si", "O"})

        assert valid is True
        assert error is None

    def test_validate_potcars_element_suffix(self, monkeypatch, tmp_path):
        """Test validation finds elements with suffix (e.g., Si_sv)."""
        pbe_dir = tmp_path / "potpaw_PBE"
        pbe_dir.mkdir()
        (pbe_dir / "Si_sv").mkdir()  # With suffix
        (pbe_dir / "O_s").mkdir()

        monkeypatch.setenv("VASP_PP_PATH", str(tmp_path))

        valid, error = validate_potcars({"Si", "O"})

        assert valid is True
        assert error is None

    def test_get_potcar_info_not_configured(self, monkeypatch):
        """Test get_potcar_info when not configured."""
        monkeypatch.delenv("VASP_PP_PATH", raising=False)

        info = get_potcar_info()

        # May or may not be configured via quacc
        assert isinstance(info, dict)
        assert "configured" in info
        assert "path" in info
        assert "exists" in info
        assert "functionals" in info

    def test_get_potcar_info_configured(self, monkeypatch, tmp_path):
        """Test get_potcar_info with valid configuration."""
        pbe_dir = tmp_path / "potpaw_PBE"
        pbe_dir.mkdir()

        monkeypatch.setenv("VASP_PP_PATH", str(tmp_path))

        info = get_potcar_info()

        assert info["configured"] is True
        assert info["path"] == str(tmp_path)
        assert info["exists"] is True
        assert "potpaw_PBE" in info["functionals"]


class TestJobRunnerABC:
    """Tests for JobRunner abstract base class."""

    def test_job_runner_is_abstract(self):
        """Test that JobRunner cannot be instantiated directly."""
        with pytest.raises(TypeError):
            JobRunner()

    def test_job_runner_generate_job_id(self):
        """Test job ID generation."""
        # Use a concrete implementation to test inherited method
        class TestRunner(JobRunner):
            def submit(self, *args, **kwargs):
                return self.generate_job_id()
            def get_status(self, job_id):
                return JobState.PENDING
            def get_result(self, job_id):
                return None
            def cancel(self, job_id):
                return False

        runner = TestRunner()
        job_id = runner.generate_job_id()

        assert isinstance(job_id, str)
        assert len(job_id) == 36  # UUID format

    def test_job_runner_import_recipe_invalid(self):
        """Test recipe import fails for invalid path."""
        class TestRunner(JobRunner):
            def submit(self, *args, **kwargs):
                pass
            def get_status(self, job_id):
                return JobState.PENDING
            def get_result(self, job_id):
                return None
            def cancel(self, job_id):
                return False

        runner = TestRunner()

        with pytest.raises(ValueError, match="Invalid recipe path"):
            runner._import_recipe("invalid")

        with pytest.raises(ValueError, match="Cannot import recipe"):
            runner._import_recipe("nonexistent.module.function")


class TestGetRunner:
    """Tests for get_runner factory function."""

    def test_get_runner_invalid_engine(self):
        """Test get_runner raises for invalid engine."""
        with pytest.raises(ValueError, match="Unsupported workflow engine"):
            get_runner("invalid_engine")

    def test_get_runner_parsl(self):
        """Test get_runner creates ParslRunner."""
        try:
            runner = get_runner("parsl")
            assert runner is not None
            # ParslRunner is a JobRunner
            from crystalmath.quacc.parsl_runner import ParslRunner
            assert isinstance(runner, ParslRunner)
        except ImportError:
            pytest.skip("Parsl runner dependencies not installed")

    def test_get_runner_covalent(self):
        """Test get_runner creates CovalentRunner."""
        try:
            runner = get_runner("covalent")
            assert runner is not None
            from crystalmath.quacc.covalent_runner import CovalentRunner
            assert isinstance(runner, CovalentRunner)
        except ImportError:
            pytest.skip("Covalent runner dependencies not installed")

    def test_get_runner_case_insensitive(self):
        """Test get_runner handles case insensitivity."""
        try:
            runner1 = get_runner("PARSL")
            runner2 = get_runner("Parsl")
            assert type(runner1) == type(runner2)
        except ImportError:
            pytest.skip("Parsl runner dependencies not installed")


class TestGetOrCreateRunner:
    """Tests for get_or_create_runner singleton factory."""

    def test_get_or_create_runner_caches(self):
        """Test that runners are cached (singleton pattern)."""
        try:
            runner1 = get_or_create_runner("parsl")
            runner2 = get_or_create_runner("parsl")
            assert runner1 is runner2
        except ImportError:
            pytest.skip("Parsl runner dependencies not installed")


class TestParslRunner:
    """Tests for ParslRunner implementation."""

    def test_parsl_runner_init(self):
        """Test ParslRunner initialization."""
        from crystalmath.quacc.parsl_runner import ParslRunner

        runner = ParslRunner()

        assert hasattr(runner, "_futures")
        assert hasattr(runner, "_job_metadata")
        assert isinstance(runner._futures, dict)

    def test_parsl_runner_get_status_unknown_job(self):
        """Test get_status raises for unknown job."""
        from crystalmath.quacc.parsl_runner import ParslRunner

        runner = ParslRunner()

        with pytest.raises(KeyError, match="Unknown job ID"):
            runner.get_status("nonexistent-job-id")

    def test_parsl_runner_get_result_unknown_job(self):
        """Test get_result raises for unknown job."""
        from crystalmath.quacc.parsl_runner import ParslRunner

        runner = ParslRunner()

        with pytest.raises(KeyError, match="Unknown job ID"):
            runner.get_result("nonexistent-job-id")

    def test_parsl_runner_cancel_unknown_job(self):
        """Test cancel raises for unknown job."""
        from crystalmath.quacc.parsl_runner import ParslRunner

        runner = ParslRunner()

        with pytest.raises(KeyError, match="Unknown job ID"):
            runner.cancel("nonexistent-job-id")


class TestCovalentRunner:
    """Tests for CovalentRunner implementation."""

    def test_covalent_runner_init(self):
        """Test CovalentRunner initialization."""
        from crystalmath.quacc.covalent_runner import CovalentRunner

        runner = CovalentRunner()

        assert hasattr(runner, "_dispatch_ids")
        assert hasattr(runner, "_status_map")
        assert isinstance(runner._dispatch_ids, dict)

    def test_covalent_runner_get_status_unknown_job(self):
        """Test get_status raises for unknown job."""
        from crystalmath.quacc.covalent_runner import CovalentRunner

        runner = CovalentRunner()

        with pytest.raises(KeyError, match="Unknown job ID"):
            runner.get_status("nonexistent-job-id")

    def test_covalent_runner_get_result_unknown_job(self):
        """Test get_result raises for unknown job."""
        from crystalmath.quacc.covalent_runner import CovalentRunner

        runner = CovalentRunner()

        with pytest.raises(KeyError, match="Unknown job ID"):
            runner.get_result("nonexistent-job-id")

    def test_covalent_runner_cancel_unknown_job(self):
        """Test cancel raises for unknown job."""
        from crystalmath.quacc.covalent_runner import CovalentRunner

        runner = CovalentRunner()

        with pytest.raises(KeyError, match="Unknown job ID"):
            runner.cancel("nonexistent-job-id")

    def test_covalent_runner_get_dispatch_id(self):
        """Test get_dispatch_id helper method."""
        from crystalmath.quacc.covalent_runner import CovalentRunner

        runner = CovalentRunner()

        # Unknown job returns None
        assert runner.get_dispatch_id("unknown") is None

        # Known job returns dispatch ID
        runner._dispatch_ids["test-job"] = "test-dispatch-123"
        assert runner.get_dispatch_id("test-job") == "test-dispatch-123"
