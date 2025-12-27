"""
Tests for CrystalController API.

These tests verify:
1. Demo mode works without AiiDA/SQLite
2. JSON output matches expected schema
3. Job submission and retrieval works
4. Error handling for invalid inputs
"""

import json
from datetime import datetime

import pytest

from crystalmath.api import CrystalController, create_controller
from crystalmath.models import DftCode, JobState, JobStatus, JobDetails


class TestCrystalControllerDemoMode:
    """Tests for demo mode (no backend)."""

    def test_create_controller_demo_mode(self):
        """Controller initializes in demo mode without backends."""
        controller = CrystalController(use_aiida=False)
        assert not controller._aiida_available

    def test_get_jobs_json_returns_valid_json(self):
        """get_jobs_json returns parseable JSON."""
        controller = CrystalController(use_aiida=False)
        result = controller.get_jobs_json()

        data = json.loads(result)
        assert isinstance(data, list)

    def test_get_jobs_json_schema_matches_rust(self):
        """Job list JSON matches Rust serde expectations."""
        controller = CrystalController(use_aiida=False)
        result = controller.get_jobs_json()

        jobs = json.loads(result)
        assert len(jobs) > 0  # Demo mode has sample jobs

        job = jobs[0]
        # Verify required fields for Rust
        assert "pk" in job
        assert "uuid" in job
        assert "name" in job
        assert "state" in job
        assert "dft_code" in job
        assert "runner_type" in job
        assert "progress_percent" in job

    def test_get_job_details_json(self):
        """get_job_details_json returns valid details in structured response."""
        controller = CrystalController(use_aiida=False)

        # Get jobs first
        jobs = json.loads(controller.get_jobs_json())
        pk = jobs[0]["pk"]

        # Get details - now returns structured {"ok": true, "data": {...}}
        result = controller.get_job_details_json(pk)
        response = json.loads(result)

        assert response["ok"] is True
        details = response["data"]
        assert details["pk"] == pk
        assert "name" in details
        assert "state" in details

    def test_get_job_details_not_found(self):
        """get_job_details_json returns structured error for missing job."""
        controller = CrystalController(use_aiida=False)
        result = controller.get_job_details_json(99999)

        response = json.loads(result)
        assert response["ok"] is False
        assert "error" in response
        assert response["error"]["code"] == "NOT_FOUND"

    def test_submit_job_json(self):
        """submit_job_json creates new job."""
        controller = CrystalController(use_aiida=False)

        payload = json.dumps({
            "name": "test-submission",
            "dft_code": "crystal",
            "parameters": {"SHRINK": [8, 8]},
        })

        pk = controller.submit_job_json(payload)
        assert pk > 0

        # Verify job appears in list
        jobs = json.loads(controller.get_jobs_json())
        job_names = [j["name"] for j in jobs]
        assert "test-submission" in job_names

    def test_submit_job_validation_error(self):
        """submit_job_json raises on invalid payload."""
        controller = CrystalController(use_aiida=False)

        # Missing required fields
        payload = json.dumps({
            "name": "ab",  # Too short
        })

        with pytest.raises(RuntimeError) as exc_info:
            controller.submit_job_json(payload)
        assert "Job submission failed" in str(exc_info.value)

    def test_cancel_job(self):
        """cancel_job updates job state."""
        controller = CrystalController(use_aiida=False)

        # Get a running job
        jobs = json.loads(controller.get_jobs_json())
        running_job = next((j for j in jobs if j["state"] == "RUNNING"), None)

        if running_job:
            result = controller.cancel_job(running_job["pk"])
            assert result is True

            # Verify state changed - response is structured now
            response = json.loads(controller.get_job_details_json(running_job["pk"]))
            assert response["ok"] is True
            assert response["data"]["state"] == "CANCELLED"

    def test_cancel_job_not_found(self):
        """cancel_job returns False for missing job."""
        controller = CrystalController(use_aiida=False)
        result = controller.cancel_job(99999)
        assert result is False


class TestCreateController:
    """Tests for the factory function."""

    def test_create_controller_demo(self):
        """Factory creates demo controller."""
        controller = create_controller(use_aiida=False)
        assert isinstance(controller, CrystalController)
        assert not controller._aiida_available

    def test_create_controller_with_db_path(self):
        """Factory with db_path attempts SQLite."""
        # This may fail gracefully if database doesn't exist
        controller = create_controller(
            use_aiida=False,
            db_path="/nonexistent/path.db",
        )
        assert isinstance(controller, CrystalController)


class TestJobStatusParsing:
    """Test that returned JSON can be parsed into models."""

    def test_parse_job_status_list(self):
        """Job list JSON parses into JobStatus models."""
        controller = CrystalController(use_aiida=False)
        result = controller.get_jobs_json()

        jobs_data = json.loads(result)
        for job_data in jobs_data:
            # Validate by parsing into model
            status = JobStatus.model_validate(job_data)
            assert isinstance(status.state, JobState)
            assert isinstance(status.dft_code, DftCode)

    def test_parse_job_details(self):
        """Job details JSON parses into JobDetails model."""
        controller = CrystalController(use_aiida=False)

        jobs = json.loads(controller.get_jobs_json())
        pk = jobs[0]["pk"]

        result = controller.get_job_details_json(pk)
        response = json.loads(result)

        # Response is now structured: {"ok": true, "data": {...}}
        assert response["ok"] is True
        details_data = response["data"]

        # Validate by parsing into model
        details = JobDetails.model_validate(details_data)
        assert details.pk == pk
        assert isinstance(details.state, JobState)


class TestJobLogRetrieval:
    """Tests for log retrieval."""

    def test_get_job_log_json_returns_structure(self):
        """get_job_log_json returns stdout/stderr structure."""
        controller = CrystalController(use_aiida=False)

        result = controller.get_job_log_json(1)
        data = json.loads(result)

        assert "stdout" in data
        assert "stderr" in data
        assert isinstance(data["stdout"], list)
        assert isinstance(data["stderr"], list)


class TestRustInteroperability:
    """Tests ensuring compatibility with Rust PyO3 calls."""

    def test_all_methods_return_strings(self):
        """All API methods return string type for PyO3."""
        controller = CrystalController(use_aiida=False)

        # These are the methods Rust will call
        jobs = controller.get_jobs_json()
        assert isinstance(jobs, str)

        details = controller.get_job_details_json(1)
        assert isinstance(details, str)

        logs = controller.get_job_log_json(1)
        assert isinstance(logs, str)

    def test_submit_returns_int(self):
        """submit_job_json returns int for PyO3."""
        controller = CrystalController(use_aiida=False)

        payload = json.dumps({
            "name": "rust-test",
            "input_content": "CRYSTAL\n0 0 0\n225\n5.43",
        })

        pk = controller.submit_job_json(payload)
        assert isinstance(pk, int)
        assert pk > 0

    def test_cancel_returns_bool(self):
        """cancel_job returns bool for PyO3."""
        controller = CrystalController(use_aiida=False)

        result = controller.cancel_job(99999)
        assert isinstance(result, bool)
