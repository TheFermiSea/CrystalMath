"""Tests for quacc-related RPC handlers.

Tests the recipes.list, clusters.list, and jobs.list JSON-RPC handlers.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from crystalmath.quacc.store import JobMetadata, JobStatus


# =============================================================================
# Handler Registration Tests
# =============================================================================


class TestHandlerRegistration:
    """Tests for handler registration in HANDLER_REGISTRY."""

    def test_all_handlers_registered(self) -> None:
        """All required handlers are registered."""
        from crystalmath.server.handlers import HANDLER_REGISTRY

        required = [
            "system.ping",
            "system.shutdown",
            "system.version",
            "recipes.list",
            "clusters.list",
            "jobs.list",
        ]
        for handler_name in required:
            assert handler_name in HANDLER_REGISTRY, f"{handler_name} not registered"

    def test_server_import_registers_handlers(self) -> None:
        """Importing from server module registers all handlers."""
        # Fresh import
        from crystalmath.server import HANDLER_REGISTRY

        assert "recipes.list" in HANDLER_REGISTRY
        assert "clusters.list" in HANDLER_REGISTRY
        assert "jobs.list" in HANDLER_REGISTRY


# =============================================================================
# recipes.list Handler Tests
# =============================================================================


class TestRecipesListHandler:
    """Tests for recipes.list handler."""

    @pytest.mark.asyncio
    async def test_recipes_list_quacc_not_installed(self) -> None:
        """recipes.list returns empty list when quacc not installed."""
        from crystalmath.server.handlers import HANDLER_REGISTRY

        handler = HANDLER_REGISTRY["recipes.list"]

        # Patch at the source module where discover_vasp_recipes is defined
        with patch(
            "crystalmath.quacc.discovery.discover_vasp_recipes",
            side_effect=ImportError("No module named 'quacc'"),
        ):
            result = await handler(None, {})

        assert result["recipes"] == []
        assert result["quacc_version"] is None
        assert "not available" in result["error"]

    @pytest.mark.asyncio
    async def test_recipes_list_with_recipes(self) -> None:
        """recipes.list returns recipes when quacc is installed."""
        from crystalmath.server.handlers import HANDLER_REGISTRY

        mock_recipes = [
            {
                "name": "relax_job",
                "module": "quacc.recipes.vasp.core",
                "fullname": "quacc.recipes.vasp.core.relax_job",
                "docstring": "Relax a structure",
                "signature": "(atoms, **kwargs)",
                "type": "job",
            },
            {
                "name": "static_job",
                "module": "quacc.recipes.vasp.core",
                "fullname": "quacc.recipes.vasp.core.static_job",
                "docstring": "Single-point calculation",
                "signature": "(atoms, **kwargs)",
                "type": "job",
            },
        ]

        handler = HANDLER_REGISTRY["recipes.list"]

        with patch(
            "crystalmath.quacc.discovery.discover_vasp_recipes",
            return_value=mock_recipes,
        ):
            result = await handler(None, {})

        assert len(result["recipes"]) == 2
        assert result["recipes"][0]["name"] == "relax_job"
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_recipes_list_response_structure(self) -> None:
        """recipes.list response has correct structure."""
        from crystalmath.server.handlers import HANDLER_REGISTRY

        handler = HANDLER_REGISTRY["recipes.list"]
        result = await handler(None, {})

        # Response should have all required keys
        assert "recipes" in result
        assert "quacc_version" in result
        assert "error" in result
        assert isinstance(result["recipes"], list)


# =============================================================================
# clusters.list Handler Tests
# =============================================================================


class TestClustersListHandler:
    """Tests for clusters.list handler."""

    @pytest.mark.asyncio
    async def test_clusters_list_empty(self) -> None:
        """clusters.list returns empty list when no clusters configured."""
        from crystalmath.server.handlers import HANDLER_REGISTRY

        handler = HANDLER_REGISTRY["clusters.list"]

        # Patch at the source modules
        with patch("crystalmath.quacc.config.ClusterConfigStore") as MockStore:
            MockStore.return_value.list_clusters.return_value = []
            with patch(
                "crystalmath.quacc.engines.get_engine_status",
                return_value={
                    "configured": None,
                    "installed": [],
                    "quacc_installed": False,
                },
            ):
                result = await handler(None, {})

        assert result["clusters"] == []
        assert result["workflow_engine"]["quacc_installed"] is False

    @pytest.mark.asyncio
    async def test_clusters_list_with_clusters(self) -> None:
        """clusters.list returns configured clusters."""
        from crystalmath.server.handlers import HANDLER_REGISTRY

        mock_clusters = [
            {"name": "nersc-perlmutter", "partition": "regular", "account": "m1234"},
            {"name": "local-slurm", "partition": "debug"},
        ]
        mock_status = {
            "configured": "parsl",
            "installed": ["parsl", "dask"],
            "quacc_installed": True,
        }

        handler = HANDLER_REGISTRY["clusters.list"]

        with patch("crystalmath.quacc.config.ClusterConfigStore") as MockStore:
            MockStore.return_value.list_clusters.return_value = mock_clusters
            with patch(
                "crystalmath.quacc.engines.get_engine_status",
                return_value=mock_status,
            ):
                result = await handler(None, {})

        assert len(result["clusters"]) == 2
        assert result["clusters"][0]["name"] == "nersc-perlmutter"
        assert result["workflow_engine"]["configured"] == "parsl"
        assert "parsl" in result["workflow_engine"]["installed"]

    @pytest.mark.asyncio
    async def test_clusters_list_response_structure(self) -> None:
        """clusters.list response has correct structure."""
        from crystalmath.server.handlers import HANDLER_REGISTRY

        handler = HANDLER_REGISTRY["clusters.list"]

        with patch("crystalmath.quacc.config.ClusterConfigStore") as MockStore:
            MockStore.return_value.list_clusters.return_value = []
            with patch(
                "crystalmath.quacc.engines.get_engine_status",
                return_value={
                    "configured": None,
                    "installed": [],
                    "quacc_installed": False,
                },
            ):
                result = await handler(None, {})

        # Response should have all required keys
        assert "clusters" in result
        assert "workflow_engine" in result
        assert isinstance(result["clusters"], list)
        assert isinstance(result["workflow_engine"], dict)
        assert "configured" in result["workflow_engine"]
        assert "installed" in result["workflow_engine"]
        assert "quacc_installed" in result["workflow_engine"]


# =============================================================================
# jobs.list Handler Tests
# =============================================================================


class TestJobsListHandler:
    """Tests for jobs.list handler."""

    @pytest.mark.asyncio
    async def test_jobs_list_empty(self) -> None:
        """jobs.list returns empty list when no jobs."""
        from crystalmath.server.handlers import HANDLER_REGISTRY

        handler = HANDLER_REGISTRY["jobs.list"]

        with patch("crystalmath.quacc.store.JobStore") as MockStore:
            MockStore.return_value.list_jobs.return_value = []
            result = await handler(None, {})

        assert result["jobs"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_jobs_list_with_jobs(self) -> None:
        """jobs.list returns job metadata."""
        from crystalmath.server.handlers import HANDLER_REGISTRY

        now = datetime.now()
        mock_jobs = [
            JobMetadata(
                id="job-1",
                recipe="quacc.recipes.vasp.core.relax_job",
                status=JobStatus.running,
                created_at=now,
                updated_at=now,
                cluster="nersc-perlmutter",
            ),
            JobMetadata(
                id="job-2",
                recipe="quacc.recipes.vasp.core.static_job",
                status=JobStatus.completed,
                created_at=now,
                updated_at=now,
            ),
        ]

        handler = HANDLER_REGISTRY["jobs.list"]

        with patch("crystalmath.quacc.store.JobStore") as MockStore:
            MockStore.return_value.list_jobs.return_value = mock_jobs
            result = await handler(None, {})

        assert len(result["jobs"]) == 2
        assert result["total"] == 2
        assert result["jobs"][0]["id"] == "job-1"
        assert result["jobs"][0]["status"] == "running"
        assert result["jobs"][1]["id"] == "job-2"

    @pytest.mark.asyncio
    async def test_jobs_list_with_status_filter(self) -> None:
        """jobs.list filters by status when provided."""
        from crystalmath.server.handlers import HANDLER_REGISTRY

        now = datetime.now()
        mock_pending_jobs = [
            JobMetadata(
                id="pending-job",
                recipe="quacc.recipes.vasp.core.relax_job",
                status=JobStatus.pending,
                created_at=now,
                updated_at=now,
            ),
        ]

        handler = HANDLER_REGISTRY["jobs.list"]

        with patch("crystalmath.quacc.store.JobStore") as MockStore:
            MockStore.return_value.list_jobs.return_value = mock_pending_jobs
            result = await handler(None, {"status": "pending"})

            # Verify list_jobs was called with status filter
            MockStore.return_value.list_jobs.assert_called_once()
            call_kwargs = MockStore.return_value.list_jobs.call_args
            assert call_kwargs.kwargs.get("status") == JobStatus.pending

        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_jobs_list_with_limit(self) -> None:
        """jobs.list respects limit parameter."""
        from crystalmath.server.handlers import HANDLER_REGISTRY

        handler = HANDLER_REGISTRY["jobs.list"]

        with patch("crystalmath.quacc.store.JobStore") as MockStore:
            MockStore.return_value.list_jobs.return_value = []
            await handler(None, {"limit": 50})

            # Verify list_jobs was called with correct limit
            MockStore.return_value.list_jobs.assert_called_once()
            call_kwargs = MockStore.return_value.list_jobs.call_args
            assert call_kwargs.kwargs.get("limit") == 50

    @pytest.mark.asyncio
    async def test_jobs_list_default_limit(self) -> None:
        """jobs.list uses default limit of 100."""
        from crystalmath.server.handlers import HANDLER_REGISTRY

        handler = HANDLER_REGISTRY["jobs.list"]

        with patch("crystalmath.quacc.store.JobStore") as MockStore:
            MockStore.return_value.list_jobs.return_value = []
            await handler(None, {})

            # Verify default limit is 100
            call_kwargs = MockStore.return_value.list_jobs.call_args
            assert call_kwargs.kwargs.get("limit") == 100

    @pytest.mark.asyncio
    async def test_jobs_list_response_structure(self) -> None:
        """jobs.list response has correct structure."""
        from crystalmath.server.handlers import HANDLER_REGISTRY

        handler = HANDLER_REGISTRY["jobs.list"]

        with patch("crystalmath.quacc.store.JobStore") as MockStore:
            MockStore.return_value.list_jobs.return_value = []
            result = await handler(None, {})

        # Response should have all required keys
        assert "jobs" in result
        assert "total" in result
        assert isinstance(result["jobs"], list)
        assert isinstance(result["total"], int)


# =============================================================================
# Integration Tests
# =============================================================================


class TestHandlerIntegration:
    """Integration tests for RPC handlers with actual quacc module."""

    @pytest.mark.asyncio
    async def test_recipes_list_real_discovery(self) -> None:
        """recipes.list works with real discovery (quacc not installed)."""
        from crystalmath.server.handlers import HANDLER_REGISTRY

        handler = HANDLER_REGISTRY["recipes.list"]
        result = await handler(None, {})

        # Should succeed even without quacc - returns empty list
        assert isinstance(result["recipes"], list)
        # quacc_version is None when quacc not installed
        # error might be None (if discovery returns empty) or a message

    @pytest.mark.asyncio
    async def test_clusters_list_real_store(self, tmp_path: Path) -> None:
        """clusters.list works with real store (empty config)."""
        from crystalmath.quacc.config import ClusterConfigStore
        from crystalmath.server.handlers import HANDLER_REGISTRY

        handler = HANDLER_REGISTRY["clusters.list"]

        # Use empty temp directory so no config exists
        with patch(
            "crystalmath.quacc.config.ClusterConfigStore",
            return_value=ClusterConfigStore(config_path=tmp_path / "clusters.json"),
        ):
            result = await handler(None, {})

        assert result["clusters"] == []
        assert "workflow_engine" in result

    @pytest.mark.asyncio
    async def test_jobs_list_real_store(self, tmp_path: Path) -> None:
        """jobs.list works with real store (empty)."""
        from crystalmath.quacc.store import JobStore
        from crystalmath.server.handlers import HANDLER_REGISTRY

        handler = HANDLER_REGISTRY["jobs.list"]

        # Use empty temp directory so no jobs exist
        with patch(
            "crystalmath.quacc.store.JobStore",
            return_value=JobStore(store_path=tmp_path / "jobs.json"),
        ):
            result = await handler(None, {})

        assert result["jobs"] == []
        assert result["total"] == 0
