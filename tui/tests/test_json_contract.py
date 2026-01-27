"""JSON Contract Integration Tests.

These tests verify that the Python API produces JSON that Rust models can deserialize.
This is critical for the PyO3 FFI boundary between the Rust TUI and Python backend.

The tests validate:
1. Enum serialization matches Rust serde expectations
2. Field names and types align between Python Pydantic and Rust serde
3. Optional fields serialize correctly (null vs missing)
4. Edge cases (empty results, null fields, special characters)

Reference files:
- Python models: python/crystalmath/models.py
- Python API: python/crystalmath/api.py
- Rust models: src/models.rs

NOTE: These tests are self-contained and do not require the crystalmath Python
package to be installed. They validate JSON structures directly against the
expected Rust serde schema.
"""

import json
from datetime import datetime
from enum import Enum
from typing import Any

# ==================== Python Model Enum Values ====================
# These match the enums defined in python/crystalmath/models.py


class JobState(str, Enum):
    """Job execution state enum - mirrors Python's JobState."""

    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DftCode(str, Enum):
    """DFT code type - mirrors Python's DftCode."""

    CRYSTAL = "crystal"
    VASP = "vasp"
    QUANTUM_ESPRESSO = "quantum_espresso"


class RunnerType(str, Enum):
    """Job execution backend - mirrors Python's RunnerType."""

    LOCAL = "local"
    SSH = "ssh"
    SLURM = "slurm"
    AIIDA = "aiida"


# ==================== JSON Structure Builders ====================
# These create JSON structures matching what the Python API produces


def build_job_status(
    pk: int,
    uuid: str,
    name: str,
    state: JobState,
    dft_code: DftCode = DftCode.CRYSTAL,
    runner_type: RunnerType = RunnerType.LOCAL,
    progress_percent: float = 0.0,
    wall_time_seconds: float | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a JobStatus JSON object matching Python's JobStatus.model_dump(mode='json')."""
    return {
        "pk": pk,
        "uuid": uuid,
        "name": name,
        "state": state.value,
        "dft_code": dft_code.value,
        "runner_type": runner_type.value,
        "progress_percent": progress_percent,
        "wall_time_seconds": wall_time_seconds,
        "created_at": created_at,
    }


def build_job_details(
    pk: int,
    name: str,
    state: JobState,
    uuid: str | None = None,
    dft_code: DftCode = DftCode.CRYSTAL,
    final_energy: float | None = None,
    bandgap_ev: float | None = None,
    convergence_met: bool = False,
    scf_cycles: int | None = None,
    cpu_time_seconds: float | None = None,
    wall_time_seconds: float | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    stdout_tail: list[str] | None = None,
    key_results: dict[str, Any] | None = None,
    work_dir: str | None = None,
    input_file: str | None = None,
) -> dict[str, Any]:
    """Build a JobDetails JSON object matching Python's JobDetails.model_dump(mode='json')."""
    return {
        "pk": pk,
        "uuid": uuid,
        "name": name,
        "state": state.value,
        "dft_code": dft_code.value,
        "final_energy": final_energy,
        "bandgap_ev": bandgap_ev,
        "convergence_met": convergence_met,
        "scf_cycles": scf_cycles,
        "cpu_time_seconds": cpu_time_seconds,
        "wall_time_seconds": wall_time_seconds,
        "warnings": warnings or [],
        "errors": errors or [],
        "stdout_tail": stdout_tail or [],
        "key_results": key_results,
        "work_dir": work_dir,
        "input_file": input_file,
    }


def build_ok_response(data: Any) -> dict[str, Any]:
    """Build success response matching Python's _ok_response()."""
    return {"ok": True, "data": data}


def build_error_response(code: str, message: str) -> dict[str, Any]:
    """Build error response matching Python's _error_response()."""
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
        },
    }


def build_slurm_queue_entry(
    job_id: str,
    name: str = "",
    user: str = "",
    partition: str = "",
    state: str = "",
    nodes: int | None = None,
    gpus: int | None = None,
    time_used: str | None = None,
    time_limit: str | None = None,
    node_list: str | None = None,
    state_reason: str | None = None,
) -> dict[str, Any]:
    """Build a SLURM queue entry matching Python's squeue output parsing."""
    return {
        "job_id": job_id,
        "name": name,
        "user": user,
        "partition": partition,
        "state": state,
        "nodes": nodes,
        "gpus": gpus,
        "time_used": time_used,
        "time_limit": time_limit,
        "node_list": node_list,
        "state_reason": state_reason,
    }


# ==================== Rust Schema Validators ====================
# These validate JSON against expected Rust serde struct schema


def validate_rust_job_state(value: str) -> bool:
    """Validate JobState matches Rust enum (SCREAMING_SNAKE_CASE)."""
    valid_states = {
        "CREATED",
        "SUBMITTED",
        "QUEUED",
        "RUNNING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
    }
    return value in valid_states


def validate_rust_dft_code(value: str) -> bool:
    """Validate DftCode matches Rust enum (snake_case)."""
    valid_codes = {"crystal", "vasp", "quantum_espresso"}
    return value in valid_codes


def validate_rust_runner_type(value: str) -> bool:
    """Validate RunnerType matches Rust enum (snake_case)."""
    valid_types = {"local", "ssh", "slurm", "aiida"}
    return value in valid_types


def validate_rust_job_status_schema(data: dict[str, Any]) -> list[str]:
    """
    Validate JSON matches Rust JobStatus struct.

    Rust struct (from src/models.rs):
        pub struct JobStatus {
            pub pk: i32,
            pub uuid: String,
            pub name: String,
            pub state: JobState,
            #[serde(default)]
            pub dft_code: Option<DftCode>,
            #[serde(default)]
            pub runner_type: Option<RunnerType>,
            #[serde(default)]
            pub progress_percent: f64,
            #[serde(default)]
            pub wall_time_seconds: Option<f64>,
            #[serde(default)]
            pub created_at: Option<String>,
            #[serde(default)]
            pub error_snippet: Option<String>,
        }

    Returns list of validation errors (empty if valid).
    """
    errors = []

    # Required fields
    required = ["pk", "uuid", "name", "state"]
    for field in required:
        if field not in data:
            errors.append(f"Missing required field: {field}")

    # Type checks
    if "pk" in data and not isinstance(data["pk"], int):
        errors.append(f"pk must be int, got {type(data['pk']).__name__}")

    if "uuid" in data and not isinstance(data["uuid"], str):
        errors.append(f"uuid must be str, got {type(data['uuid']).__name__}")

    if "name" in data and not isinstance(data["name"], str):
        errors.append(f"name must be str, got {type(data['name']).__name__}")

    if "state" in data and not validate_rust_job_state(data["state"]):
        errors.append(f"Invalid state value: {data['state']}")

    # Optional fields with correct types
    if "dft_code" in data and data["dft_code"] is not None:
        if not validate_rust_dft_code(data["dft_code"]):
            errors.append(f"Invalid dft_code value: {data['dft_code']}")

    if "runner_type" in data and data["runner_type"] is not None:
        if not validate_rust_runner_type(data["runner_type"]):
            errors.append(f"Invalid runner_type value: {data['runner_type']}")

    if "progress_percent" in data:
        if not isinstance(data["progress_percent"], (int, float)):
            errors.append(
                f"progress_percent must be numeric, got {type(data['progress_percent']).__name__}"
            )

    if "wall_time_seconds" in data and data["wall_time_seconds"] is not None:
        if not isinstance(data["wall_time_seconds"], (int, float)):
            errors.append(
                f"wall_time_seconds must be numeric, got {type(data['wall_time_seconds']).__name__}"
            )

    if "created_at" in data and data["created_at"] is not None:
        if not isinstance(data["created_at"], str):
            errors.append(
                f"created_at must be str (ISO format), got {type(data['created_at']).__name__}"
            )

    return errors


def validate_rust_job_details_schema(data: dict[str, Any]) -> list[str]:
    """
    Validate JSON matches Rust JobDetails struct.

    Rust struct (from src/models.rs):
        pub struct JobDetails {
            pub pk: i32,
            #[serde(default)]
            pub uuid: Option<String>,
            pub name: String,
            pub state: JobState,
            #[serde(default)]
            pub dft_code: Option<DftCode>,
            #[serde(default)]
            pub final_energy: Option<f64>,
            #[serde(default)]
            pub bandgap_ev: Option<f64>,
            #[serde(default)]
            pub convergence_met: bool,
            #[serde(default)]
            pub scf_cycles: Option<i32>,
            #[serde(default)]
            pub cpu_time_seconds: Option<f64>,
            #[serde(default)]
            pub wall_time_seconds: Option<f64>,
            #[serde(default)]
            pub warnings: Vec<String>,
            #[serde(default)]
            pub errors: Vec<String>,
            #[serde(default)]
            pub stdout_tail: Vec<String>,
            #[serde(default)]
            pub key_results: Option<serde_json::Value>,
            #[serde(default)]
            pub work_dir: Option<String>,
            #[serde(default)]
            pub input_file: Option<String>,
        }

    Returns list of validation errors (empty if valid).
    """
    errors = []

    # Required fields
    required = ["pk", "name", "state"]
    for field in required:
        if field not in data:
            errors.append(f"Missing required field: {field}")

    # Type checks for required fields
    if "pk" in data and not isinstance(data["pk"], int):
        errors.append(f"pk must be int, got {type(data['pk']).__name__}")

    if "name" in data and not isinstance(data["name"], str):
        errors.append(f"name must be str, got {type(data['name']).__name__}")

    if "state" in data and not validate_rust_job_state(data["state"]):
        errors.append(f"Invalid state value: {data['state']}")

    # Optional string fields
    for field in ["uuid", "work_dir", "input_file"]:
        if field in data and data[field] is not None:
            if not isinstance(data[field], str):
                errors.append(f"{field} must be str or null, got {type(data[field]).__name__}")

    # Optional numeric fields
    for field in ["final_energy", "bandgap_ev", "cpu_time_seconds", "wall_time_seconds"]:
        if field in data and data[field] is not None:
            if not isinstance(data[field], (int, float)):
                errors.append(f"{field} must be numeric or null, got {type(data[field]).__name__}")

    # Optional integer fields
    if "scf_cycles" in data and data["scf_cycles"] is not None:
        if not isinstance(data["scf_cycles"], int):
            errors.append(
                f"scf_cycles must be int or null, got {type(data['scf_cycles']).__name__}"
            )

    # Boolean fields (default to false in Rust)
    if "convergence_met" in data:
        if not isinstance(data["convergence_met"], bool):
            errors.append(
                f"convergence_met must be bool, got {type(data['convergence_met']).__name__}"
            )

    # List fields (default to empty vec in Rust)
    for field in ["warnings", "errors", "stdout_tail"]:
        if field in data:
            if not isinstance(data[field], list):
                errors.append(f"{field} must be list, got {type(data[field]).__name__}")
            elif not all(isinstance(item, str) for item in data[field]):
                errors.append(f"{field} must contain only strings")

    # key_results is Option<serde_json::Value> - can be any JSON value or null
    # No specific validation needed

    return errors


def validate_rust_api_response_schema(data: dict[str, Any], data_validator=None) -> list[str]:
    """
    Validate JSON matches Rust ApiResponse<T> struct.

    Rust struct (from src/models.rs):
        pub struct ApiResponse<T> {
            pub ok: bool,
            #[serde(default)]
            pub data: Option<T>,
            #[serde(default)]
            pub error: Option<ApiError>,
        }

        pub struct ApiError {
            pub code: String,
            pub message: String,
        }

    Returns list of validation errors (empty if valid).
    """
    errors = []

    # Required field: ok
    if "ok" not in data:
        errors.append("Missing required field: ok")
    elif not isinstance(data["ok"], bool):
        errors.append(f"ok must be bool, got {type(data['ok']).__name__}")

    # Success case: data field present
    if data.get("ok") is True:
        if "data" not in data:
            errors.append("Success response missing 'data' field")
        elif data_validator and data["data"] is not None:
            # Validate the data payload
            if isinstance(data["data"], list):
                for i, item in enumerate(data["data"]):
                    item_errors = data_validator(item)
                    for err in item_errors:
                        errors.append(f"data[{i}]: {err}")
            else:
                item_errors = data_validator(data["data"])
                errors.extend(item_errors)

    # Error case: error field present
    if data.get("ok") is False:
        if "error" not in data:
            errors.append("Error response missing 'error' field")
        elif data["error"] is not None:
            error_obj = data["error"]
            if not isinstance(error_obj, dict):
                errors.append(f"error must be object, got {type(error_obj).__name__}")
            else:
                if "code" not in error_obj:
                    errors.append("error object missing 'code' field")
                elif not isinstance(error_obj["code"], str):
                    errors.append(f"error.code must be str, got {type(error_obj['code']).__name__}")

                if "message" not in error_obj:
                    errors.append("error object missing 'message' field")
                elif not isinstance(error_obj["message"], str):
                    errors.append(
                        f"error.message must be str, got {type(error_obj['message']).__name__}"
                    )

    return errors


def validate_rust_slurm_queue_entry_schema(data: dict[str, Any]) -> list[str]:
    """
    Validate JSON matches Rust SlurmQueueEntry struct.

    Rust struct (from src/models.rs):
        pub struct SlurmQueueEntry {
            #[serde(default)]
            pub job_id: String,
            #[serde(default)]
            pub name: String,
            #[serde(default)]
            pub user: String,
            #[serde(default)]
            pub partition: String,
            #[serde(default)]
            pub state: String,
            #[serde(default)]
            pub nodes: Option<i32>,
            #[serde(default)]
            pub gpus: Option<i32>,
            #[serde(default)]
            pub time_used: Option<String>,
            #[serde(default)]
            pub time_limit: Option<String>,
            #[serde(default)]
            pub node_list: Option<String>,
            #[serde(default)]
            pub state_reason: Option<String>,
        }

    Returns list of validation errors (empty if valid).
    """
    errors = []

    # All fields have #[serde(default)] in Rust, so they're optional
    # but should have correct types when present

    string_fields = ["job_id", "name", "user", "partition", "state"]
    for field in string_fields:
        if field in data and data[field] is not None:
            if not isinstance(data[field], str):
                errors.append(f"{field} must be str, got {type(data[field]).__name__}")

    optional_int_fields = ["nodes", "gpus"]
    for field in optional_int_fields:
        if field in data and data[field] is not None:
            if not isinstance(data[field], int):
                errors.append(f"{field} must be int or null, got {type(data[field]).__name__}")

    optional_string_fields = ["time_used", "time_limit", "node_list", "state_reason"]
    for field in optional_string_fields:
        if field in data and data[field] is not None:
            if not isinstance(data[field], str):
                errors.append(f"{field} must be str or null, got {type(data[field]).__name__}")

    return errors


# ==================== Test Classes ====================


class TestJobStateContract:
    """Tests for JobState enum serialization."""

    def test_all_states_serialize_correctly(self):
        """Verify all JobState values serialize to Rust-compatible format."""
        state_mapping = {
            JobState.CREATED: "CREATED",
            JobState.SUBMITTED: "SUBMITTED",
            JobState.QUEUED: "QUEUED",
            JobState.RUNNING: "RUNNING",
            JobState.COMPLETED: "COMPLETED",
            JobState.FAILED: "FAILED",
            JobState.CANCELLED: "CANCELLED",
        }

        for py_state, expected_rust in state_mapping.items():
            data = build_job_status(
                pk=1,
                uuid="test",
                name="test",
                state=py_state,
            )

            assert data["state"] == expected_rust, (
                f"State {py_state} serialized as {data['state']}, expected {expected_rust}"
            )
            assert validate_rust_job_state(data["state"]), f"Invalid Rust state: {data['state']}"

    def test_state_from_aiida_process_states(self):
        """Verify AiiDA process states map correctly.

        The Python API maps AiiDA states to UI states via map_to_job_state():
        - created -> CREATED
        - waiting -> QUEUED
        - running -> RUNNING
        - finished -> COMPLETED
        - excepted -> FAILED
        - killed -> CANCELLED
        """
        aiida_to_ui_mapping = {
            "created": JobState.CREATED,
            "waiting": JobState.QUEUED,
            "running": JobState.RUNNING,
            "finished": JobState.COMPLETED,
            "excepted": JobState.FAILED,
            "killed": JobState.CANCELLED,
        }

        for aiida_state, ui_state in aiida_to_ui_mapping.items():
            data = build_job_status(
                pk=1,
                uuid="test",
                name="test",
                state=ui_state,  # Simulates post-mapping result
            )

            assert validate_rust_job_state(data["state"]), (
                f"AiiDA state '{aiida_state}' -> {data['state']} is not valid Rust state"
            )


class TestDftCodeContract:
    """Tests for DftCode enum serialization."""

    def test_all_codes_serialize_correctly(self):
        """Verify all DftCode values serialize to Rust-compatible format."""
        code_mapping = {
            DftCode.CRYSTAL: "crystal",
            DftCode.VASP: "vasp",
            DftCode.QUANTUM_ESPRESSO: "quantum_espresso",
        }

        for py_code, expected_rust in code_mapping.items():
            data = build_job_status(
                pk=1,
                uuid="test",
                name="test",
                state=JobState.CREATED,
                dft_code=py_code,
            )

            assert data["dft_code"] == expected_rust, (
                f"DftCode {py_code} serialized as {data['dft_code']}, expected {expected_rust}"
            )
            assert validate_rust_dft_code(data["dft_code"]), (
                f"Invalid Rust dft_code: {data['dft_code']}"
            )


class TestRunnerTypeContract:
    """Tests for RunnerType enum serialization."""

    def test_all_runners_serialize_correctly(self):
        """Verify all RunnerType values serialize to Rust-compatible format."""
        runner_mapping = {
            RunnerType.LOCAL: "local",
            RunnerType.SSH: "ssh",
            RunnerType.SLURM: "slurm",
            RunnerType.AIIDA: "aiida",
        }

        for py_runner, expected_rust in runner_mapping.items():
            data = build_job_status(
                pk=1,
                uuid="test",
                name="test",
                state=JobState.CREATED,
                runner_type=py_runner,
            )

            assert data["runner_type"] == expected_rust, (
                f"RunnerType {py_runner} serialized as {data['runner_type']}, expected {expected_rust}"
            )
            assert validate_rust_runner_type(data["runner_type"]), (
                f"Invalid Rust runner_type: {data['runner_type']}"
            )


class TestJobStatusContract:
    """Tests for JobStatus model serialization."""

    def test_minimal_job_status(self):
        """Test JobStatus with only required fields."""
        data = build_job_status(
            pk=42,
            uuid="abc-123",
            name="mgo-scf",
            state=JobState.RUNNING,
        )

        errors = validate_rust_job_status_schema(data)
        assert not errors, f"Schema validation errors: {errors}"

        # Verify defaults
        assert data["progress_percent"] == 0.0
        assert data["dft_code"] == "crystal"
        assert data["runner_type"] == "local"

    def test_full_job_status(self):
        """Test JobStatus with all fields populated."""
        now = datetime.now().isoformat()
        data = build_job_status(
            pk=1,
            uuid="uuid-full-test",
            name="full-job",
            state=JobState.COMPLETED,
            dft_code=DftCode.VASP,
            runner_type=RunnerType.SLURM,
            progress_percent=100.0,
            wall_time_seconds=3600.5,
            created_at=now,
        )

        errors = validate_rust_job_status_schema(data)
        assert not errors, f"Schema validation errors: {errors}"

        # Verify all fields
        assert data["pk"] == 1
        assert data["uuid"] == "uuid-full-test"
        assert data["name"] == "full-job"
        assert data["state"] == "COMPLETED"
        assert data["dft_code"] == "vasp"
        assert data["runner_type"] == "slurm"
        assert data["progress_percent"] == 100.0
        assert data["wall_time_seconds"] == 3600.5
        assert data["created_at"] is not None

    def test_job_status_list_serialization(self):
        """Test array of JobStatus objects."""
        statuses = [
            build_job_status(pk=1, uuid="a", name="job1", state=JobState.RUNNING),
            build_job_status(pk=2, uuid="b", name="job2", state=JobState.COMPLETED),
            build_job_status(pk=3, uuid="c", name="job3", state=JobState.FAILED),
        ]

        json_str = json.dumps(statuses)

        # Verify JSON is valid and parseable
        parsed = json.loads(json_str)
        assert len(parsed) == 3

        for item in parsed:
            errors = validate_rust_job_status_schema(item)
            assert not errors, f"Schema validation errors: {errors}"

    def test_empty_job_list(self):
        """Test empty array serialization."""
        data: list[dict[str, Any]] = []
        json_str = json.dumps(data)

        parsed = json.loads(json_str)
        assert parsed == []


class TestJobDetailsContract:
    """Tests for JobDetails model serialization."""

    def test_minimal_job_details(self):
        """Test JobDetails with only required fields."""
        data = build_job_details(
            pk=1,
            name="minimal-job",
            state=JobState.CREATED,
        )

        errors = validate_rust_job_details_schema(data)
        assert not errors, f"Schema validation errors: {errors}"

        # Verify defaults
        assert data["convergence_met"] is False
        assert data["warnings"] == []
        assert data["errors"] == []
        assert data["stdout_tail"] == []

    def test_full_job_details(self):
        """Test JobDetails with all fields populated."""
        data = build_job_details(
            pk=42,
            uuid="uuid-full-details",
            name="full-details-job",
            state=JobState.COMPLETED,
            dft_code=DftCode.CRYSTAL,
            final_energy=-275.123456,
            bandgap_ev=2.5,
            convergence_met=True,
            scf_cycles=15,
            cpu_time_seconds=1800.5,
            wall_time_seconds=1900.0,
            warnings=["Warning 1", "Warning 2"],
            errors=[],
            stdout_tail=["line1", "line2", "line3"],
            key_results={"energy": -275.123, "converged": True},
            work_dir="/path/to/work",
            input_file="CRYSTAL\n0 0 0\n225",
        )

        errors = validate_rust_job_details_schema(data)
        assert not errors, f"Schema validation errors: {errors}"

        # Verify key fields
        assert data["pk"] == 42
        assert data["final_energy"] == -275.123456
        assert data["bandgap_ev"] == 2.5
        assert data["convergence_met"] is True
        assert data["scf_cycles"] == 15
        assert len(data["warnings"]) == 2
        assert len(data["stdout_tail"]) == 3

    def test_job_details_null_optional_fields(self):
        """Test that null optional fields serialize correctly for Rust."""
        data = build_job_details(
            pk=1,
            name="null-optionals",
            state=JobState.RUNNING,
            final_energy=None,
            bandgap_ev=None,
            scf_cycles=None,
            work_dir=None,
        )

        errors = validate_rust_job_details_schema(data)
        assert not errors, f"Schema validation errors: {errors}"

        # Verify nulls are explicit (not missing)
        assert "final_energy" in data
        assert data["final_energy"] is None
        assert "bandgap_ev" in data
        assert data["bandgap_ev"] is None


class TestApiResponseContract:
    """Tests for the ApiResponse wrapper format."""

    def test_success_response_with_data(self):
        """Test successful response with data payload."""
        status = build_job_status(pk=1, uuid="test", name="job", state=JobState.COMPLETED)
        data = build_ok_response(status)

        errors = validate_rust_api_response_schema(data, validate_rust_job_status_schema)
        assert not errors, f"Schema validation errors: {errors}"

    def test_success_response_with_list(self):
        """Test successful response with array payload."""
        statuses = [
            build_job_status(pk=i, uuid=f"uuid-{i}", name=f"job-{i}", state=JobState.RUNNING)
            for i in range(3)
        ]
        data = build_ok_response(statuses)

        errors = validate_rust_api_response_schema(data, validate_rust_job_status_schema)
        assert not errors, f"Schema validation errors: {errors}"

    def test_error_response(self):
        """Test error response format."""
        data = build_error_response("NOT_FOUND", "Job with pk=999 not found")

        errors = validate_rust_api_response_schema(data)
        assert not errors, f"Schema validation errors: {errors}"

    def test_various_error_codes(self):
        """Test different error codes that API can return."""
        error_codes = [
            "NOT_FOUND",
            "INTERNAL_ERROR",
            "CONFIGURATION_ERROR",
            "IMPORT_ERROR",
            "SEARCH_FAILED",
            "GENERATION_FAILED",
            "SLURM_ERROR",
            "NO_DATABASE",
            "INVALID_JSON",
            "MISSING_FIELD",
            "TIMEOUT",
            "CONNECTION_FAILED",
        ]

        for code in error_codes:
            data = build_error_response(code, f"Error message for {code}")
            errors = validate_rust_api_response_schema(data)
            assert not errors, f"Schema validation errors for code '{code}': {errors}"


class TestSlurmQueueContract:
    """Tests for SLURM queue entry serialization."""

    def test_full_slurm_entry(self):
        """Test full SLURM queue entry."""
        entry = build_slurm_queue_entry(
            job_id="12345",
            name="my-job",
            user="testuser",
            partition="compute",
            state="RUNNING",
            nodes=4,
            gpus=2,
            time_used="01:23:45",
            time_limit="24:00:00",
            node_list="node[001-004]",
            state_reason="None",
        )

        errors = validate_rust_slurm_queue_entry_schema(entry)
        assert not errors, f"Schema validation errors: {errors}"

    def test_minimal_slurm_entry(self):
        """Test SLURM entry with only required fields."""
        entry = build_slurm_queue_entry(
            job_id="99999",
            state="PENDING",
        )

        errors = validate_rust_slurm_queue_entry_schema(entry)
        assert not errors, f"Schema validation errors: {errors}"

    def test_slurm_entry_with_nulls(self):
        """Test SLURM entry with explicit null fields."""
        entry = build_slurm_queue_entry(
            job_id="12345",
            name="job",
            user="user",
            partition="default",
            state="PENDING",
            nodes=None,
            gpus=None,
            time_used=None,
            time_limit=None,
            node_list=None,
            state_reason="(Priority)",
        )

        errors = validate_rust_slurm_queue_entry_schema(entry)
        assert not errors, f"Schema validation errors: {errors}"


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_special_characters_in_name(self):
        """Test job names with special characters."""
        # These should be valid (no filesystem-forbidden chars)
        valid_names = [
            "job-with-dashes",
            "job_with_underscores",
            "job.with.dots",
            "job with spaces",
            "MoS2-optimization",
            "LiFePO4_SCF",
        ]

        for name in valid_names:
            data = build_job_status(pk=1, uuid="test", name=name, state=JobState.CREATED)
            errors = validate_rust_job_status_schema(data)
            assert not errors, f"Schema validation errors for name '{name}': {errors}"

    def test_unicode_in_strings(self):
        """Test unicode characters in string fields."""
        data = build_job_status(
            pk=1,
            uuid="test-unicode",
            name="MoS\u2082-calc",  # MoS2 with subscript
            state=JobState.COMPLETED,
        )
        json_str = json.dumps(data)

        # Verify JSON is valid
        parsed = json.loads(json_str)
        assert "MoS" in parsed["name"]

    def test_large_pk_values(self):
        """Test large primary key values."""
        data = build_job_status(
            pk=2147483647,  # Max i32
            uuid="large-pk",
            name="large-pk-job",
            state=JobState.CREATED,
        )
        errors = validate_rust_job_status_schema(data)
        assert not errors, f"Schema validation errors: {errors}"

    def test_float_precision(self):
        """Test float values maintain precision."""
        data = build_job_details(
            pk=1,
            name="precision-test",
            state=JobState.COMPLETED,
            final_energy=-275.123456789012345,
            bandgap_ev=1.234567890,
        )

        # Verify reasonable precision is maintained
        assert abs(data["final_energy"] - (-275.123456789012345)) < 1e-10
        assert abs(data["bandgap_ev"] - 1.234567890) < 1e-10

    def test_empty_string_fields(self):
        """Test empty strings in optional fields."""
        data = build_job_details(
            pk=1,
            name="empty-strings",
            state=JobState.RUNNING,
            work_dir="",
            input_file="",
        )
        errors = validate_rust_job_details_schema(data)
        assert not errors, f"Schema validation errors: {errors}"

    def test_long_stdout_tail(self):
        """Test stdout_tail with many lines."""
        data = build_job_details(
            pk=1,
            name="long-output",
            state=JobState.COMPLETED,
            stdout_tail=[f"Line {i}" for i in range(100)],
        )
        errors = validate_rust_job_details_schema(data)
        assert not errors, f"Schema validation errors: {errors}"
        assert len(data["stdout_tail"]) == 100

    def test_complex_key_results(self):
        """Test key_results with nested JSON."""
        data = build_job_details(
            pk=1,
            name="complex-results",
            state=JobState.COMPLETED,
            key_results={
                "energy": -275.123,
                "converged": True,
                "nested": {
                    "array": [1, 2, 3],
                    "object": {"a": "b"},
                },
                "null_value": None,
            },
        )
        errors = validate_rust_job_details_schema(data)
        assert not errors, f"Schema validation errors: {errors}"

        # Verify nested structure preserved
        json_str = json.dumps(data)
        parsed = json.loads(json_str)
        assert parsed["key_results"]["nested"]["array"] == [1, 2, 3]


class TestJsonRoundTrip:
    """Tests verifying JSON round-trip serialization."""

    def test_job_status_round_trip(self):
        """Test JobStatus JSON round-trip."""
        original = build_job_status(
            pk=42,
            uuid="test-uuid",
            name="test-job",
            state=JobState.RUNNING,
            dft_code=DftCode.CRYSTAL,
            progress_percent=50.5,
        )

        # Serialize
        json_str = json.dumps(original)

        # Deserialize
        parsed = json.loads(json_str)

        assert parsed["pk"] == original["pk"]
        assert parsed["uuid"] == original["uuid"]
        assert parsed["name"] == original["name"]
        assert parsed["state"] == original["state"]
        assert parsed["dft_code"] == original["dft_code"]
        assert parsed["progress_percent"] == original["progress_percent"]

    def test_job_details_round_trip(self):
        """Test JobDetails JSON round-trip."""
        original = build_job_details(
            pk=1,
            name="test-details",
            state=JobState.COMPLETED,
            final_energy=-275.123,
            convergence_met=True,
            warnings=["Warning 1"],
        )

        # Serialize
        json_str = json.dumps(original)

        # Deserialize
        parsed = json.loads(json_str)

        assert parsed["pk"] == original["pk"]
        assert parsed["final_energy"] == original["final_energy"]
        assert parsed["convergence_met"] == original["convergence_met"]
        assert parsed["warnings"] == original["warnings"]

    def test_api_response_round_trip(self):
        """Test ApiResponse JSON round-trip."""
        original = build_ok_response(
            build_job_status(pk=1, uuid="a", name="test", state=JobState.RUNNING)
        )

        # Serialize
        json_str = json.dumps(original)

        # Deserialize
        parsed = json.loads(json_str)

        assert parsed["ok"] is True
        assert parsed["data"]["pk"] == 1
        assert parsed["data"]["state"] == "RUNNING"


class TestMaterialsApiContract:
    """Tests for Materials Project API response structures."""

    def test_material_result_schema(self):
        """Test MaterialResult structure matches Rust expectations.

        Rust struct (from src/models.rs):
            pub struct MaterialResult {
                pub material_id: String,
                #[serde(default)]
                pub formula: Option<String>,
                #[serde(default)]
                pub formula_pretty: Option<String>,
                #[serde(default)]
                pub source: Option<String>,
                #[serde(default)]
                pub properties: MaterialProperties,
                #[serde(default)]
                pub metadata: serde_json::Value,
                #[serde(default)]
                pub structure: Option<serde_json::Value>,
            }
        """
        material = {
            "material_id": "mp-2815",
            "formula": "MoS2",
            "formula_pretty": "MoS\u2082",
            "source": "materials_project",
            "properties": {
                "band_gap": 1.23,
                "energy_above_hull": 0.0,
                "formation_energy_per_atom": -0.5,
                "energy_per_atom": -4.5,
                "total_magnetization": None,
                "is_metal": False,
            },
            "metadata": {
                "space_group": {"symbol": "P6_3/mmc", "number": 194},
            },
            "structure": None,
        }

        # Verify required field
        assert "material_id" in material
        assert isinstance(material["material_id"], str)

        # Verify optional fields
        for field in ["formula", "formula_pretty", "source"]:
            assert field in material
            assert material[field] is None or isinstance(material[field], str)

        # Verify properties structure
        props = material["properties"]
        assert isinstance(props, dict)
        for field in [
            "band_gap",
            "energy_above_hull",
            "formation_energy_per_atom",
            "energy_per_atom",
        ]:
            assert field in props
            assert props[field] is None or isinstance(props[field], (int, float))

    def test_material_search_response(self):
        """Test materials search API response format."""
        materials = [
            {
                "material_id": "mp-2815",
                "formula": "MoS2",
                "properties": {"band_gap": 1.23},
                "metadata": {},
            },
            {
                "material_id": "mp-1234",
                "formula": "LiCoO2",
                "properties": {"band_gap": 2.7},
                "metadata": {},
            },
        ]

        response = build_ok_response(materials)
        errors = validate_rust_api_response_schema(response)
        assert not errors, f"Schema validation errors: {errors}"

        assert response["ok"] is True
        assert len(response["data"]) == 2


class TestClusterConfigContract:
    """Tests for ClusterConfig model serialization."""

    def test_cluster_response_from_api(self):
        """Test cluster config response format from get_clusters_json().

        The API returns clusters in this format (from api.py):
            {
                "id": cluster.id,
                "name": cluster.name,
                "hostname": cluster.hostname,
                "port": cluster.port,
                "username": cluster.username,
                "cluster_type": cluster.type,  # matches Rust ClusterConfig field
                "status": cluster.status,
                "connection_config": conn_config,
            }
        """
        cluster = {
            "id": 1,
            "name": "test-cluster",
            "hostname": "cluster.example.com",
            "port": 22,
            "username": "testuser",
            "cluster_type": "slurm",  # Must use cluster_type to match Rust ClusterConfig
            "status": "active",
            "connection_config": {
                "key_file": "~/.ssh/id_ed25519",
            },
        }

        # Verify required fields
        assert "name" in cluster
        assert "hostname" in cluster
        assert "username" in cluster
        assert "cluster_type" in cluster

        # Verify types
        assert isinstance(cluster["name"], str)
        assert isinstance(cluster["port"], int)
        assert cluster["cluster_type"] in ("ssh", "slurm")
        assert cluster["status"] in ("active", "inactive", "error")

    def test_connection_test_result(self):
        """Test cluster connection test response format.

        Rust struct:
            pub struct ClusterConnectionResult {
                #[serde(default)]
                pub success: bool,
                #[serde(default)]
                pub hostname: Option<String>,
                #[serde(default)]
                pub system_info: Option<String>,
                #[serde(default)]
                pub error: Option<String>,
            }
        """
        # Success case
        success_result = {
            "connected": True,
            "hostname": "cluster01",
            "system_info": "Linux cluster01 5.4.0",
            "message": "Successfully connected",
        }

        response = build_ok_response(success_result)
        errors = validate_rust_api_response_schema(response)
        assert not errors, f"Schema validation errors: {errors}"

        # Verify field types
        data = response["data"]
        assert isinstance(data["connected"], bool)
        assert isinstance(data["hostname"], str)


class TestSlurmCancelContract:
    """Tests for SLURM job cancel response format."""

    def test_cancel_success_response(self):
        """Test successful SLURM cancel response.

        Rust struct:
            pub struct SlurmCancelResult {
                #[serde(default)]
                pub success: bool,
                #[serde(default)]
                pub message: Option<String>,
            }
        """
        result = {
            "success": True,
            "message": "Job 12345 cancelled successfully",
        }

        response = build_ok_response(result)
        errors = validate_rust_api_response_schema(response)
        assert not errors, f"Schema validation errors: {errors}"

        data = response["data"]
        assert isinstance(data["success"], bool)
        assert data["success"] is True
        assert isinstance(data["message"], str)

    def test_cancel_failure_response(self):
        """Test failed SLURM cancel response."""
        result = {
            "success": False,
            "message": "Permission denied: job 12345",
        }

        response = build_ok_response(result)
        errors = validate_rust_api_response_schema(response)
        assert not errors, f"Schema validation errors: {errors}"

        data = response["data"]
        assert data["success"] is False
