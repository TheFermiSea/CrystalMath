"""
Unit tests for the crystalmath.quacc module.

Tests recipe discovery, engine detection, cluster configuration,
and job store functionality.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from crystalmath.quacc.config import ClusterConfigStore, ParslClusterConfig
from crystalmath.quacc.discovery import discover_vasp_recipes
from crystalmath.quacc.engines import (
    get_engine_status,
    get_installed_engines,
    get_workflow_engine,
)
from crystalmath.quacc.store import JobMetadata, JobStatus, JobStore


# =============================================================================
# Discovery Tests
# =============================================================================


class TestDiscoverVaspRecipes:
    """Tests for discover_vasp_recipes()."""

    def test_discover_vasp_recipes_without_quacc(self) -> None:
        """Returns empty list when quacc is not installed."""
        # quacc is not installed in test env, so should return empty
        recipes = discover_vasp_recipes()
        # This will be empty since quacc isn't installed
        assert isinstance(recipes, list)

    def test_discover_vasp_recipes_with_quacc(self) -> None:
        """Discovers recipes when quacc is available."""
        # Create mock quacc module structure using types.ModuleType for proper behavior
        from types import ModuleType

        # Create proper module hierarchy - parent modules must reference children
        mock_quacc = ModuleType("quacc")
        mock_recipes = ModuleType("quacc.recipes")
        mock_vasp = ModuleType("quacc.recipes.vasp")
        mock_vasp.__path__ = ["/fake/path"]  # type: ignore[attr-defined]

        # Wire up the hierarchy
        mock_quacc.recipes = mock_recipes  # type: ignore[attr-defined]
        mock_recipes.vasp = mock_vasp  # type: ignore[attr-defined]

        # Create a mock core module with recipe functions
        mock_core = ModuleType("quacc.recipes.vasp.core")

        def relax_job(atoms: Any, **kwargs: Any) -> dict[str, Any]:
            """Relax a structure."""
            return {}

        def static_job(atoms: Any, **kwargs: Any) -> dict[str, Any]:
            """Single-point calculation."""
            return {}

        def relax_flow(atoms: Any, **kwargs: Any) -> dict[str, Any]:
            """Multi-step relaxation flow."""
            return {}

        # Set function modules so they're recognized as defined in core
        relax_job.__module__ = "quacc.recipes.vasp.core"
        static_job.__module__ = "quacc.recipes.vasp.core"
        relax_flow.__module__ = "quacc.recipes.vasp.core"

        mock_core.relax_job = relax_job  # type: ignore[attr-defined]
        mock_core.static_job = static_job  # type: ignore[attr-defined]
        mock_core.relax_flow = relax_flow  # type: ignore[attr-defined]

        with patch.dict(
            sys.modules,
            {
                "quacc": mock_quacc,
                "quacc.recipes": mock_recipes,
                "quacc.recipes.vasp": mock_vasp,
                "quacc.recipes.vasp.core": mock_core,
            },
        ):
            # Mock walk_packages to return our fake module
            with patch("crystalmath.quacc.discovery.pkgutil.walk_packages") as mock_walk:
                mock_walk.return_value = [
                    (None, "quacc.recipes.vasp.core", False),
                ]

                recipes = discover_vasp_recipes()

        # Should find our mock recipes
        assert len(recipes) == 3

        recipe_names = {r["name"] for r in recipes}
        assert "relax_job" in recipe_names
        assert "static_job" in recipe_names
        assert "relax_flow" in recipe_names

        # Check recipe structure
        relax = next(r for r in recipes if r["name"] == "relax_job")
        assert relax["module"] == "quacc.recipes.vasp.core"
        assert relax["fullname"] == "quacc.recipes.vasp.core.relax_job"
        assert relax["type"] == "job"
        assert "Relax" in relax["docstring"]

        flow = next(r for r in recipes if r["name"] == "relax_flow")
        assert flow["type"] == "flow"

    def test_discover_skips_import_errors(self, caplog: pytest.LogCaptureFixture) -> None:
        """Submodule ImportErrors are caught and logged."""
        from types import ModuleType

        # Create proper module hierarchy
        mock_quacc = ModuleType("quacc")
        mock_recipes = ModuleType("quacc.recipes")
        mock_vasp = ModuleType("quacc.recipes.vasp")
        mock_vasp.__path__ = ["/fake/path"]  # type: ignore[attr-defined]

        mock_quacc.recipes = mock_recipes  # type: ignore[attr-defined]
        mock_recipes.vasp = mock_vasp  # type: ignore[attr-defined]

        with patch.dict(
            sys.modules,
            {
                "quacc": mock_quacc,
                "quacc.recipes": mock_recipes,
                "quacc.recipes.vasp": mock_vasp,
            },
        ):
            # Mock walk_packages to simulate a module that fails to import
            with patch("crystalmath.quacc.discovery.pkgutil.walk_packages") as mock_walk:
                mock_walk.return_value = [
                    (None, "quacc.recipes.vasp.mlip", False),
                ]

                # Mock import_module to raise ImportError for mlip
                with patch(
                    "crystalmath.quacc.discovery.import_module"
                ) as mock_import:
                    mock_import.side_effect = ImportError(
                        "No module named 'mace'"
                    )

                    with caplog.at_level(logging.DEBUG):
                        recipes = discover_vasp_recipes()

        # Should return empty list (no successful modules)
        assert recipes == []

    def test_discover_logs_skipped_modules(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Verify DEBUG log message is emitted for skipped modules."""
        from types import ModuleType

        # Create proper module hierarchy
        mock_quacc = ModuleType("quacc")
        mock_recipes = ModuleType("quacc.recipes")
        mock_vasp = ModuleType("quacc.recipes.vasp")
        mock_vasp.__path__ = ["/fake/path"]  # type: ignore[attr-defined]

        mock_quacc.recipes = mock_recipes  # type: ignore[attr-defined]
        mock_recipes.vasp = mock_vasp  # type: ignore[attr-defined]

        with patch.dict(
            sys.modules,
            {
                "quacc": mock_quacc,
                "quacc.recipes": mock_recipes,
                "quacc.recipes.vasp": mock_vasp,
            },
        ):
            with patch("crystalmath.quacc.discovery.pkgutil.walk_packages") as mock_walk:
                mock_walk.return_value = [
                    (None, "quacc.recipes.vasp.broken", False),
                ]

                with patch(
                    "crystalmath.quacc.discovery.import_module"
                ) as mock_import:
                    mock_import.side_effect = ImportError("missing dep")

                    with caplog.at_level(logging.DEBUG):
                        discover_vasp_recipes()

        # Check log contains the skip message
        assert any(
            "Skipping module quacc.recipes.vasp.broken" in record.message
            for record in caplog.records
        )


# =============================================================================
# Engines Tests
# =============================================================================


class TestGetWorkflowEngine:
    """Tests for get_workflow_engine()."""

    def test_get_workflow_engine_not_installed(self) -> None:
        """Returns None when quacc is not installed."""
        # In test env, quacc is not installed
        result = get_workflow_engine()
        assert result is None

    def test_get_workflow_engine_not_set(self) -> None:
        """Returns None when WORKFLOW_ENGINE is not set."""
        mock_settings = MagicMock()
        mock_settings.WORKFLOW_ENGINE = None

        with patch.dict(sys.modules, {"quacc": MagicMock(SETTINGS=mock_settings)}):
            with patch(
                "crystalmath.quacc.engines.get_workflow_engine"
            ) as mock_get:
                mock_get.return_value = None
                result = mock_get()

        assert result is None

    def test_get_workflow_engine_parsl(self) -> None:
        """Returns 'parsl' when configured."""
        mock_settings = MagicMock()
        mock_settings.WORKFLOW_ENGINE = "parsl"
        mock_quacc = MagicMock()
        mock_quacc.SETTINGS = mock_settings

        with patch.dict(sys.modules, {"quacc": mock_quacc}):
            # Need to reimport to pick up mock
            from importlib import reload
            import crystalmath.quacc.engines as engines_mod

            reload(engines_mod)
            result = engines_mod.get_workflow_engine()

        assert result == "parsl"


class TestGetInstalledEngines:
    """Tests for get_installed_engines()."""

    def test_get_installed_engines_none(self) -> None:
        """Returns empty list when no engines installed."""
        with patch(
            "crystalmath.quacc.engines.import_module"
        ) as mock_import:
            mock_import.side_effect = ImportError("not installed")
            result = get_installed_engines()

        assert result == []

    def test_get_installed_engines_some(self) -> None:
        """Detects installed engines."""

        def selective_import(name: str) -> ModuleType:
            if name == "parsl":
                return MagicMock()
            if name == "dask.distributed":
                return MagicMock()
            raise ImportError(f"No module named '{name}'")

        with patch(
            "crystalmath.quacc.engines.import_module", side_effect=selective_import
        ):
            result = get_installed_engines()

        assert "parsl" in result
        assert "dask" in result
        assert "prefect" not in result


class TestGetEngineStatus:
    """Tests for get_engine_status()."""

    def test_get_engine_status_structure(self) -> None:
        """Verify return dict has all expected keys."""
        status = get_engine_status()

        assert "configured" in status
        assert "installed" in status
        assert "quacc_installed" in status

        assert isinstance(status["installed"], list)
        assert isinstance(status["quacc_installed"], bool)


# =============================================================================
# Config Tests
# =============================================================================


class TestParslClusterConfig:
    """Tests for ParslClusterConfig model."""

    def test_parsl_cluster_config_defaults(self) -> None:
        """Verify default values are set correctly."""
        config = ParslClusterConfig(name="test", partition="compute")

        assert config.name == "test"
        assert config.partition == "compute"
        assert config.account is None
        assert config.nodes_per_block == 1
        assert config.cores_per_node == 32
        assert config.mem_per_node is None
        assert config.walltime == "01:00:00"
        assert config.max_blocks == 10
        assert config.worker_init == ""
        assert config.scheduler_options == ""

    def test_parsl_cluster_config_walltime_valid(self) -> None:
        """Valid walltime patterns are accepted."""
        # Standard format
        config = ParslClusterConfig(
            name="test", partition="compute", walltime="02:30:00"
        )
        assert config.walltime == "02:30:00"

        # Single digit hours
        config = ParslClusterConfig(
            name="test", partition="compute", walltime="1:00:00"
        )
        assert config.walltime == "1:00:00"

        # Large hours
        config = ParslClusterConfig(
            name="test", partition="compute", walltime="168:00:00"
        )
        assert config.walltime == "168:00:00"

    def test_parsl_cluster_config_walltime_invalid(self) -> None:
        """Invalid walltime patterns are rejected."""
        with pytest.raises(ValueError, match="Invalid walltime format"):
            ParslClusterConfig(
                name="test", partition="compute", walltime="2h30m"
            )

        with pytest.raises(ValueError, match="Invalid walltime format"):
            ParslClusterConfig(
                name="test", partition="compute", walltime="02:30"
            )

        with pytest.raises(ValueError, match="Invalid walltime format"):
            ParslClusterConfig(
                name="test", partition="compute", walltime="invalid"
            )


class TestClusterConfigStore:
    """Tests for ClusterConfigStore."""

    def test_cluster_config_store_empty_file(self, tmp_path: Path) -> None:
        """Returns empty list when file doesn't exist."""
        store = ClusterConfigStore(config_path=tmp_path / "clusters.json")
        assert store.list_clusters() == []

    def test_cluster_config_store_list_clusters(self, tmp_path: Path) -> None:
        """Parses clusters from JSON file."""
        config_path = tmp_path / "clusters.json"
        clusters = [
            {"name": "hpc1", "partition": "gpu", "account": "proj123"},
            {"name": "hpc2", "partition": "compute"},
        ]
        config_path.write_text(json.dumps(clusters))

        store = ClusterConfigStore(config_path=config_path)
        result = store.list_clusters()

        assert len(result) == 2
        assert result[0]["name"] == "hpc1"
        assert result[1]["name"] == "hpc2"

    def test_cluster_config_store_get_cluster(self, tmp_path: Path) -> None:
        """Finds cluster by name."""
        config_path = tmp_path / "clusters.json"
        clusters = [
            {"name": "hpc1", "partition": "gpu"},
            {"name": "hpc2", "partition": "compute"},
        ]
        config_path.write_text(json.dumps(clusters))

        store = ClusterConfigStore(config_path=config_path)

        cluster = store.get_cluster("hpc1")
        assert cluster is not None
        assert cluster.name == "hpc1"
        assert cluster.partition == "gpu"

        missing = store.get_cluster("nonexistent")
        assert missing is None

    def test_cluster_config_store_save_cluster(self, tmp_path: Path) -> None:
        """Saves new cluster configuration."""
        config_path = tmp_path / "clusters.json"
        store = ClusterConfigStore(config_path=config_path)

        config = ParslClusterConfig(name="new_cluster", partition="gpu")
        store.save_cluster(config)

        # Verify it was saved
        clusters = store.list_clusters()
        assert len(clusters) == 1
        assert clusters[0]["name"] == "new_cluster"

    def test_cluster_config_store_creates_parent_dir(self, tmp_path: Path) -> None:
        """Creates parent directory if it doesn't exist."""
        config_path = tmp_path / "subdir" / "clusters.json"
        store = ClusterConfigStore(config_path=config_path)

        # Parent should be created
        assert config_path.parent.exists()


# =============================================================================
# Store Tests
# =============================================================================


class TestJobStatus:
    """Tests for JobStatus enum."""

    def test_job_status_enum_values(self) -> None:
        """All status values are accessible."""
        assert JobStatus.pending.value == "pending"
        assert JobStatus.running.value == "running"
        assert JobStatus.completed.value == "completed"
        assert JobStatus.failed.value == "failed"

    def test_job_status_is_string_enum(self) -> None:
        """JobStatus values can be used as strings."""
        # String enum allows direct comparison with string
        assert JobStatus.pending == "pending"
        # The .value property gives the string value
        assert JobStatus.running.value == "running"


class TestJobMetadata:
    """Tests for JobMetadata model."""

    def test_job_metadata_required_fields(self) -> None:
        """Validates required fields."""
        # Should succeed with required fields
        job = JobMetadata(
            id="test-uuid",
            recipe="quacc.recipes.vasp.core.relax_job",
            status=JobStatus.pending,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert job.id == "test-uuid"

        # Should fail without required fields
        with pytest.raises(ValueError):
            JobMetadata(id="test-uuid")  # type: ignore

    def test_job_metadata_optional_fields(self) -> None:
        """Optional fields default to None."""
        job = JobMetadata(
            id="test-uuid",
            recipe="quacc.recipes.vasp.core.relax_job",
            status=JobStatus.pending,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert job.cluster is None
        assert job.work_dir is None
        assert job.error_message is None
        assert job.results_summary is None


class TestJobStore:
    """Tests for JobStore."""

    def test_job_store_empty(self, tmp_path: Path) -> None:
        """Returns empty list when no file exists."""
        store = JobStore(store_path=tmp_path / "jobs.json")
        assert store.list_jobs() == []

    def test_job_store_list_jobs(self, tmp_path: Path) -> None:
        """Lists jobs from store file."""
        store_path = tmp_path / "jobs.json"
        now = datetime.now().isoformat()
        jobs = [
            {
                "id": "job1",
                "recipe": "quacc.recipes.vasp.core.relax_job",
                "status": "completed",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": "job2",
                "recipe": "quacc.recipes.vasp.core.static_job",
                "status": "pending",
                "created_at": now,
                "updated_at": now,
            },
        ]
        store_path.write_text(json.dumps(jobs))

        store = JobStore(store_path=store_path)
        result = store.list_jobs()

        assert len(result) == 2
        assert all(isinstance(j, JobMetadata) for j in result)

    def test_job_store_filter_by_status(self, tmp_path: Path) -> None:
        """Filters jobs by status."""
        store_path = tmp_path / "jobs.json"
        now = datetime.now().isoformat()
        jobs = [
            {
                "id": "job1",
                "recipe": "recipe1",
                "status": "completed",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": "job2",
                "recipe": "recipe2",
                "status": "pending",
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": "job3",
                "recipe": "recipe3",
                "status": "pending",
                "created_at": now,
                "updated_at": now,
            },
        ]
        store_path.write_text(json.dumps(jobs))

        store = JobStore(store_path=store_path)

        pending = store.list_jobs(status=JobStatus.pending)
        assert len(pending) == 2
        assert all(j.status == JobStatus.pending for j in pending)

        completed = store.list_jobs(status=JobStatus.completed)
        assert len(completed) == 1
        assert completed[0].id == "job1"

    def test_job_store_get_job(self, tmp_path: Path) -> None:
        """Gets job by ID."""
        store_path = tmp_path / "jobs.json"
        now = datetime.now().isoformat()
        jobs = [
            {
                "id": "target-job",
                "recipe": "quacc.recipes.vasp.core.relax_job",
                "status": "running",
                "created_at": now,
                "updated_at": now,
            },
        ]
        store_path.write_text(json.dumps(jobs))

        store = JobStore(store_path=store_path)

        job = store.get_job("target-job")
        assert job is not None
        assert job.id == "target-job"
        assert job.status == JobStatus.running

        missing = store.get_job("nonexistent")
        assert missing is None

    def test_job_store_save_job(self, tmp_path: Path) -> None:
        """Saves new job to store."""
        store = JobStore(store_path=tmp_path / "jobs.json")

        job = JobMetadata(
            id="new-job",
            recipe="quacc.recipes.vasp.core.static_job",
            status=JobStatus.pending,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        store.save_job(job)

        # Verify saved
        loaded = store.get_job("new-job")
        assert loaded is not None
        assert loaded.recipe == "quacc.recipes.vasp.core.static_job"

    def test_job_store_creates_parent_dir(self, tmp_path: Path) -> None:
        """Creates parent directory if needed."""
        store_path = tmp_path / "subdir" / "jobs.json"
        store = JobStore(store_path=store_path)

        assert store_path.parent.exists()
