"""Tests for job submission handlers.

Tests cover:
- jobs.submit handler with success and error paths
- jobs.status handler with polling
- jobs.cancel handler with state validation
- MockRunner integration

Uses MockRunner to test without requiring Parsl/Covalent dependencies.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from crystalmath.quacc.mock_runner import MockRunner, MockJobState
from crystalmath.quacc.runner import JobState
from crystalmath.quacc.store import JobMetadata, JobStatus


# =============================================================================
# MockRunner Tests
# =============================================================================


class TestMockRunner:
    """Tests for MockRunner implementation."""

    def test_mock_runner_submit(self):
        """MockRunner.submit returns job ID."""
        runner = MockRunner()
        mock_atoms = MagicMock()
        mock_atoms.get_chemical_formula.return_value = "Si8"

        job_id = runner.submit(
            recipe_fullname="quacc.recipes.vasp.core.relax_job",
            atoms=mock_atoms,
            cluster_name="local",
        )

        assert job_id is not None
        assert len(job_id) == 36  # UUID format
        assert runner._jobs[job_id] == MockJobState.SUBMITTED

    def test_mock_runner_status_lifecycle(self):
        """MockRunner advances state each status call."""
        runner = MockRunner()
        mock_atoms = MagicMock()

        job_id = runner.submit("relax_job", mock_atoms, "local")

        # First call: SUBMITTED -> RUNNING
        status1 = runner.get_status(job_id)
        assert status1 == JobState.RUNNING

        # Second call: RUNNING -> COMPLETED
        status2 = runner.get_status(job_id)
        assert status2 == JobState.COMPLETED

        # Subsequent calls stay COMPLETED
        status3 = runner.get_status(job_id)
        assert status3 == JobState.COMPLETED

    def test_mock_runner_status_failure(self):
        """MockRunner fails job when set_fail called."""
        runner = MockRunner()
        mock_atoms = MagicMock()

        job_id = runner.submit("relax_job", mock_atoms, "local")
        runner.set_fail(job_id)

        # First call: SUBMITTED -> RUNNING
        status1 = runner.get_status(job_id)
        assert status1 == JobState.RUNNING

        # Second call: RUNNING -> FAILED
        status2 = runner.get_status(job_id)
        assert status2 == JobState.FAILED

    def test_mock_runner_result(self):
        """MockRunner returns result when completed."""
        runner = MockRunner()
        mock_atoms = MagicMock()
        mock_atoms.get_chemical_formula.return_value = "Si8"

        job_id = runner.submit("relax_job", mock_atoms, "local")

        # No result before completion
        assert runner.get_result(job_id) is None

        # Advance to completed
        runner.get_status(job_id)  # RUNNING
        runner.get_status(job_id)  # COMPLETED

        result = runner.get_result(job_id)
        assert result is not None
        assert "results" in result
        assert result["formula_pretty"] == "Si8"

    def test_mock_runner_custom_result(self):
        """MockRunner uses custom result when set."""
        runner = MockRunner()
        mock_atoms = MagicMock()

        job_id = runner.submit("relax_job", mock_atoms, "local")
        custom_result = {"energy": -999.0, "custom_key": "test"}
        runner.set_custom_result(job_id, custom_result)

        # Advance to completed
        runner.get_status(job_id)
        runner.get_status(job_id)

        result = runner.get_result(job_id)
        assert result == custom_result

    def test_mock_runner_cancel(self):
        """MockRunner cancel works for active jobs."""
        runner = MockRunner()
        mock_atoms = MagicMock()

        job_id = runner.submit("relax_job", mock_atoms, "local")

        # Can cancel submitted job
        assert runner.cancel(job_id) is True
        assert runner._jobs[job_id] == MockJobState.CANCELLED

    def test_mock_runner_cancel_completed(self):
        """MockRunner cancel fails for completed jobs."""
        runner = MockRunner()
        mock_atoms = MagicMock()

        job_id = runner.submit("relax_job", mock_atoms, "local")
        runner.get_status(job_id)
        runner.get_status(job_id)  # COMPLETED

        assert runner.cancel(job_id) is False

    def test_mock_runner_unknown_job(self):
        """MockRunner raises for unknown job ID."""
        runner = MockRunner()

        with pytest.raises(ValueError, match="Unknown job"):
            runner.get_status("nonexistent-job")

    def test_mock_runner_clear(self):
        """MockRunner.clear resets all state."""
        runner = MockRunner()
        mock_atoms = MagicMock()

        job_id = runner.submit("relax_job", mock_atoms, "local")
        runner.clear()

        assert len(runner._jobs) == 0
        with pytest.raises(ValueError):
            runner.get_status(job_id)


# =============================================================================
# jobs.submit Handler Tests
# =============================================================================


class TestJobsSubmitHandler:
    """Tests for jobs.submit handler."""

    @pytest.fixture
    def mock_atoms(self):
        """Create mock ASE Atoms object."""
        atoms = MagicMock()
        atoms.get_chemical_formula.return_value = "Si8"
        atoms.get_chemical_symbols.return_value = ["Si"] * 8
        return atoms

    @pytest.mark.asyncio
    async def test_submit_returns_job_id(self, mock_atoms):
        """Successful submission returns job_id."""
        from crystalmath.server.handlers.jobs import handle_jobs_submit

        mock_runner = MockRunner()

        with (
            patch(
                "crystalmath.quacc.runner.get_or_create_runner",
                return_value=mock_runner,
            ),
            patch(
                "crystalmath.quacc.engines.get_workflow_engine",
                return_value="parsl",
            ),
            patch(
                "crystalmath.quacc.potcar.validate_potcars",
                return_value=(True, None),
            ),
            patch("ase.io.read", return_value=mock_atoms),
            patch("crystalmath.quacc.store.JobStore") as MockStore,
        ):
            MockStore.return_value.save_job = MagicMock()

            result = await handle_jobs_submit(
                None,
                {
                    "recipe": "quacc.recipes.vasp.core.relax_job",
                    "structure": "Si\n1.0\n5.43 0.0 0.0\n0.0 5.43 0.0\n0.0 0.0 5.43\nSi\n8\nDirect\n0.0 0.0 0.0\n",
                    "cluster": "local",
                },
            )

        assert result["job_id"] is not None
        assert result["status"] == "pending"
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_submit_no_workflow_engine(self):
        """Submission fails without workflow engine."""
        from crystalmath.server.handlers.jobs import handle_jobs_submit

        with patch(
            "crystalmath.quacc.engines.get_workflow_engine",
            return_value=None,
        ):
            result = await handle_jobs_submit(
                None,
                {
                    "recipe": "quacc.recipes.vasp.core.relax_job",
                    "structure": "Si\n1.0\n...",
                },
            )

        assert result["job_id"] is None
        assert result["status"] == "error"
        assert "workflow engine" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_submit_potcar_validation_fails(self, mock_atoms):
        """Submission fails if POTCARs missing."""
        from crystalmath.server.handlers.jobs import handle_jobs_submit

        with (
            patch(
                "crystalmath.quacc.engines.get_workflow_engine",
                return_value="parsl",
            ),
            patch(
                "crystalmath.quacc.potcar.validate_potcars",
                return_value=(False, "Missing POTCARs for: Si"),
            ),
            patch("ase.io.read", return_value=mock_atoms),
        ):
            result = await handle_jobs_submit(
                None,
                {
                    "recipe": "quacc.recipes.vasp.core.relax_job",
                    "structure": "Si\n1.0\n5.43 0.0 0.0\n0.0 5.43 0.0\n0.0 0.0 5.43\nSi\n8\nDirect\n0.0 0.0 0.0\n",
                },
            )

        assert result["job_id"] is None
        assert result["status"] == "error"
        assert "POTCAR" in result["error"]

    @pytest.mark.asyncio
    async def test_submit_missing_recipe(self):
        """Submission fails without recipe parameter."""
        from crystalmath.server.handlers.jobs import handle_jobs_submit

        with patch(
            "crystalmath.quacc.engines.get_workflow_engine",
            return_value="parsl",
        ):
            result = await handle_jobs_submit(
                None,
                {"structure": "Si\n1.0\n..."},
            )

        assert result["job_id"] is None
        assert result["status"] == "error"
        assert "recipe" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_submit_missing_structure(self):
        """Submission fails without structure parameter."""
        from crystalmath.server.handlers.jobs import handle_jobs_submit

        with patch(
            "crystalmath.quacc.engines.get_workflow_engine",
            return_value="parsl",
        ):
            result = await handle_jobs_submit(
                None,
                {"recipe": "quacc.recipes.vasp.core.relax_job"},
            )

        assert result["job_id"] is None
        assert result["status"] == "error"
        assert "structure" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_submit_invalid_structure(self):
        """Submission fails with invalid structure format."""
        from crystalmath.server.handlers.jobs import handle_jobs_submit

        with (
            patch(
                "crystalmath.quacc.engines.get_workflow_engine",
                return_value="parsl",
            ),
            patch("ase.io.read", side_effect=ValueError("Invalid POSCAR format")),
        ):
            result = await handle_jobs_submit(
                None,
                {
                    "recipe": "quacc.recipes.vasp.core.relax_job",
                    "structure": "invalid data",
                },
            )

        assert result["job_id"] is None
        assert result["status"] == "error"
        assert "parse structure" in result["error"].lower()


# =============================================================================
# jobs.status Handler Tests
# =============================================================================


class TestJobsStatusHandler:
    """Tests for jobs.status handler."""

    @pytest.mark.asyncio
    async def test_status_missing_job_id(self):
        """Status fails without job_id parameter."""
        from crystalmath.server.handlers.jobs import handle_jobs_status

        result = await handle_jobs_status(None, {})

        assert "error" in result
        assert "job_id" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_status_job_not_found(self):
        """Status fails for unknown job."""
        from crystalmath.server.handlers.jobs import handle_jobs_status

        with patch("crystalmath.quacc.store.JobStore") as MockStore:
            MockStore.return_value.get_job.return_value = None
            result = await handle_jobs_status(None, {"job_id": "nonexistent"})

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_status_returns_cached_for_terminal(self):
        """Status returns cached status for terminal jobs."""
        from crystalmath.server.handlers.jobs import handle_jobs_status

        now = datetime.now(timezone.utc)
        mock_job = JobMetadata(
            id="completed-job",
            recipe="relax_job",
            status=JobStatus.completed,
            created_at=now,
            updated_at=now,
            results_summary={"energy_ev": -123.456},
        )

        with patch("crystalmath.quacc.store.JobStore") as MockStore:
            MockStore.return_value.get_job.return_value = mock_job
            result = await handle_jobs_status(None, {"job_id": "completed-job"})

        assert result["job_id"] == "completed-job"
        assert result["status"] == "completed"
        assert result["result"]["energy_ev"] == -123.456

    @pytest.mark.asyncio
    async def test_status_polls_active_job(self):
        """Status polls runner for active job."""
        from crystalmath.server.handlers.jobs import handle_jobs_status

        now = datetime.now(timezone.utc)
        mock_job = JobMetadata(
            id="running-job",
            recipe="relax_job",
            status=JobStatus.pending,
            created_at=now,
            updated_at=now,
        )

        mock_runner = MockRunner()
        # Pre-populate the runner with the job
        mock_runner._jobs["running-job"] = MockJobState.SUBMITTED
        mock_runner._status_calls["running-job"] = 0

        with (
            patch("crystalmath.quacc.store.JobStore") as MockStore,
            patch(
                "crystalmath.quacc.engines.get_workflow_engine",
                return_value="parsl",
            ),
            patch(
                "crystalmath.quacc.runner.get_or_create_runner",
                return_value=mock_runner,
            ),
        ):
            MockStore.return_value.get_job.return_value = mock_job
            MockStore.return_value.save_job = MagicMock()

            result = await handle_jobs_status(None, {"job_id": "running-job"})

        assert result["job_id"] == "running-job"
        # First poll advances SUBMITTED -> RUNNING
        assert result["status"] == "running"

    @pytest.mark.asyncio
    async def test_status_no_engine_returns_cached(self):
        """Status returns cached when no engine configured."""
        from crystalmath.server.handlers.jobs import handle_jobs_status

        now = datetime.now(timezone.utc)
        mock_job = JobMetadata(
            id="pending-job",
            recipe="relax_job",
            status=JobStatus.pending,
            created_at=now,
            updated_at=now,
        )

        with (
            patch("crystalmath.quacc.store.JobStore") as MockStore,
            patch(
                "crystalmath.quacc.engines.get_workflow_engine",
                return_value=None,
            ),
        ):
            MockStore.return_value.get_job.return_value = mock_job
            result = await handle_jobs_status(None, {"job_id": "pending-job"})

        assert result["job_id"] == "pending-job"
        assert result["status"] == "pending"


# =============================================================================
# jobs.cancel Handler Tests
# =============================================================================


class TestJobsCancelHandler:
    """Tests for jobs.cancel handler."""

    @pytest.mark.asyncio
    async def test_cancel_missing_job_id(self):
        """Cancel fails without job_id parameter."""
        from crystalmath.server.handlers.jobs import handle_jobs_cancel

        result = await handle_jobs_cancel(None, {})

        assert "error" in result
        assert "job_id" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_cancel_job_not_found(self):
        """Cancel fails for unknown job."""
        from crystalmath.server.handlers.jobs import handle_jobs_cancel

        with patch("crystalmath.quacc.store.JobStore") as MockStore:
            MockStore.return_value.get_job.return_value = None
            result = await handle_jobs_cancel(None, {"job_id": "nonexistent"})

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_cancel_terminal_job_fails(self):
        """Cancel fails for already completed job."""
        from crystalmath.server.handlers.jobs import handle_jobs_cancel

        now = datetime.now(timezone.utc)
        mock_job = JobMetadata(
            id="completed-job",
            recipe="relax_job",
            status=JobStatus.completed,
            created_at=now,
            updated_at=now,
        )

        with patch("crystalmath.quacc.store.JobStore") as MockStore:
            MockStore.return_value.get_job.return_value = mock_job
            result = await handle_jobs_cancel(None, {"job_id": "completed-job"})

        assert result["cancelled"] is False
        assert "terminal state" in result["error"]

    @pytest.mark.asyncio
    async def test_cancel_running_job(self):
        """Cancel succeeds for running job."""
        from crystalmath.server.handlers.jobs import handle_jobs_cancel

        now = datetime.now(timezone.utc)
        mock_job = JobMetadata(
            id="running-job",
            recipe="relax_job",
            status=JobStatus.running,
            created_at=now,
            updated_at=now,
        )

        mock_runner = MockRunner()
        mock_runner._jobs["running-job"] = MockJobState.RUNNING

        with (
            patch("crystalmath.quacc.store.JobStore") as MockStore,
            patch(
                "crystalmath.quacc.engines.get_workflow_engine",
                return_value="parsl",
            ),
            patch(
                "crystalmath.quacc.runner.get_or_create_runner",
                return_value=mock_runner,
            ),
        ):
            MockStore.return_value.get_job.return_value = mock_job
            MockStore.return_value.save_job = MagicMock()

            result = await handle_jobs_cancel(None, {"job_id": "running-job"})

        assert result["job_id"] == "running-job"
        assert result["cancelled"] is True
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_cancel_no_engine(self):
        """Cancel fails when no engine configured."""
        from crystalmath.server.handlers.jobs import handle_jobs_cancel

        now = datetime.now(timezone.utc)
        mock_job = JobMetadata(
            id="pending-job",
            recipe="relax_job",
            status=JobStatus.pending,
            created_at=now,
            updated_at=now,
        )

        with (
            patch("crystalmath.quacc.store.JobStore") as MockStore,
            patch(
                "crystalmath.quacc.engines.get_workflow_engine",
                return_value=None,
            ),
        ):
            MockStore.return_value.get_job.return_value = mock_job
            result = await handle_jobs_cancel(None, {"job_id": "pending-job"})

        assert result["cancelled"] is False
        assert "engine" in result["error"].lower()


# =============================================================================
# Integration Tests
# =============================================================================


class TestJobSubmissionIntegration:
    """Integration tests using MockRunner end-to-end."""

    @pytest.mark.asyncio
    async def test_full_job_lifecycle_with_mock_runner(self):
        """Test complete job lifecycle: submit -> poll -> complete."""
        from crystalmath.server.handlers.jobs import (
            handle_jobs_submit,
            handle_jobs_status,
        )

        mock_runner = MockRunner()
        mock_atoms = MagicMock()
        mock_atoms.get_chemical_formula.return_value = "Si8"
        mock_atoms.get_chemical_symbols.return_value = ["Si"] * 8

        # Store for tracking job metadata
        job_store = {}

        def mock_save_job(job):
            job_store[job.id] = job

        def mock_get_job(job_id):
            return job_store.get(job_id)

        with (
            patch(
                "crystalmath.quacc.runner.get_or_create_runner",
                return_value=mock_runner,
            ),
            patch(
                "crystalmath.quacc.engines.get_workflow_engine",
                return_value="parsl",
            ),
            patch(
                "crystalmath.quacc.potcar.validate_potcars",
                return_value=(True, None),
            ),
            patch("ase.io.read", return_value=mock_atoms),
            patch("crystalmath.quacc.store.JobStore") as MockStore,
        ):
            MockStore.return_value.save_job = mock_save_job
            MockStore.return_value.get_job = mock_get_job

            # 1. Submit job
            submit_result = await handle_jobs_submit(
                None,
                {
                    "recipe": "quacc.recipes.vasp.core.relax_job",
                    "structure": "Si\n1.0\n...",
                    "cluster": "local",
                },
            )

            assert submit_result["job_id"] is not None
            job_id = submit_result["job_id"]
            assert submit_result["status"] == "pending"

            # Pre-populate runner with job ID for status polling
            # (In real flow, submit() does this, but our mock uses different ID)
            mock_runner._jobs[job_id] = MockJobState.SUBMITTED
            mock_runner._status_calls[job_id] = 0

            # 2. First status poll -> RUNNING
            status1 = await handle_jobs_status(None, {"job_id": job_id})
            assert status1["status"] == "running"

            # 3. Second status poll -> COMPLETED
            status2 = await handle_jobs_status(None, {"job_id": job_id})
            assert status2["status"] == "completed"
            # Result should be populated
            assert status2["result"] is not None

    @pytest.mark.asyncio
    async def test_job_failure_lifecycle(self):
        """Test job failure flow: submit -> poll -> fail."""
        from crystalmath.server.handlers.jobs import (
            handle_jobs_submit,
            handle_jobs_status,
        )

        mock_runner = MockRunner()
        mock_atoms = MagicMock()
        mock_atoms.get_chemical_formula.return_value = "Si8"
        mock_atoms.get_chemical_symbols.return_value = ["Si"] * 8

        job_store = {}

        def mock_save_job(job):
            job_store[job.id] = job

        def mock_get_job(job_id):
            return job_store.get(job_id)

        with (
            patch(
                "crystalmath.quacc.runner.get_or_create_runner",
                return_value=mock_runner,
            ),
            patch(
                "crystalmath.quacc.engines.get_workflow_engine",
                return_value="parsl",
            ),
            patch(
                "crystalmath.quacc.potcar.validate_potcars",
                return_value=(True, None),
            ),
            patch("ase.io.read", return_value=mock_atoms),
            patch("crystalmath.quacc.store.JobStore") as MockStore,
        ):
            MockStore.return_value.save_job = mock_save_job
            MockStore.return_value.get_job = mock_get_job

            # Submit job
            submit_result = await handle_jobs_submit(
                None,
                {
                    "recipe": "quacc.recipes.vasp.core.relax_job",
                    "structure": "Si\n1.0\n...",
                },
            )

            job_id = submit_result["job_id"]

            # Set up runner state and mark for failure
            mock_runner._jobs[job_id] = MockJobState.SUBMITTED
            mock_runner._status_calls[job_id] = 0
            mock_runner.set_fail(job_id)

            # First poll -> RUNNING
            status1 = await handle_jobs_status(None, {"job_id": job_id})
            assert status1["status"] == "running"

            # Second poll -> FAILED
            status2 = await handle_jobs_status(None, {"job_id": job_id})
            assert status2["status"] == "failed"
