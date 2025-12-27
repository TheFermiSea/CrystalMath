"""
Tests for Pydantic models ensuring Rust serde compatibility.

These tests verify:
1. JSON serialization matches Rust struct expectations
2. Field validation rules work correctly
3. State mapping from AiiDA/database states
4. Round-trip serialization (Python -> JSON -> Python)
"""

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from crystalmath.models import (
    ClusterConfig,
    DftCode,
    JobDetails,
    JobState,
    JobStatus,
    JobSubmission,
    RunnerType,
    StructureData,
)


class TestJobState:
    """Tests for JobState enum."""

    def test_all_states_defined(self):
        """Verify all expected states exist."""
        expected = {"CREATED", "SUBMITTED", "QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"}
        actual = {s.value for s in JobState}
        assert actual == expected

    def test_string_serialization(self):
        """States serialize as uppercase strings for Rust serde."""
        assert JobState.RUNNING.value == "RUNNING"
        assert json.dumps(JobState.COMPLETED.value) == '"COMPLETED"'


class TestDftCode:
    """Tests for DftCode enum."""

    def test_all_codes_defined(self):
        """Verify all supported DFT codes exist."""
        expected = {"crystal", "vasp", "quantum_espresso"}
        actual = {c.value for c in DftCode}
        assert actual == expected

    def test_lowercase_values(self):
        """DFT codes use lowercase for file type matching."""
        assert DftCode.CRYSTAL.value == "crystal"
        assert DftCode.VASP.value == "vasp"


class TestJobSubmission:
    """Tests for JobSubmission model."""

    def test_minimal_valid_submission(self):
        """Minimal valid job submission."""
        job = JobSubmission(
            name="test-job",
            input_content="CRYSTAL\n0 0 0\n225\n5.43",
        )
        assert job.name == "test-job"
        assert job.dft_code == DftCode.CRYSTAL
        assert job.runner_type == RunnerType.LOCAL

    def test_full_submission(self):
        """Full job submission with all fields."""
        job = JobSubmission(
            name="mgo-relaxation",
            dft_code=DftCode.CRYSTAL,
            cluster_id=1,
            runner_type=RunnerType.SLURM,
            parameters={"OPTGEOM": {}, "SHRINK": [8, 8]},
            structure_path="/path/to/mgo.cif",
        )
        assert job.cluster_id == 1
        assert job.runner_type == RunnerType.SLURM
        assert "OPTGEOM" in job.parameters

    def test_name_validation_min_length(self):
        """Name must be at least 3 characters."""
        with pytest.raises(ValidationError) as exc_info:
            JobSubmission(name="ab", input_content="test")
        assert "string_too_short" in str(exc_info.value) or "at least 3 characters" in str(exc_info.value)

    def test_name_validation_forbidden_chars(self):
        """Name cannot contain filesystem-unsafe characters."""
        with pytest.raises(ValidationError) as exc_info:
            JobSubmission(name="test/job", input_content="test")
        assert "forbidden" in str(exc_info.value).lower()

    def test_requires_input_source(self):
        """Either parameters or input_content must be provided."""
        with pytest.raises(ValidationError) as exc_info:
            JobSubmission(name="empty-job")
        assert "parameters or input_content" in str(exc_info.value).lower()

    def test_json_serialization(self):
        """JSON output matches Rust serde expectations."""
        job = JobSubmission(
            name="test-job",
            dft_code=DftCode.CRYSTAL,
            parameters={"SHRINK": [8, 8]},
        )
        data = job.model_dump()

        # Verify field names are snake_case (Rust convention)
        assert "dft_code" in data
        assert "cluster_id" in data
        assert "runner_type" in data

        # Verify enum serialization
        assert data["dft_code"] == "crystal"
        assert data["runner_type"] == "local"

    def test_json_roundtrip(self):
        """Data survives Python -> JSON -> Python conversion."""
        original = JobSubmission(
            name="roundtrip-test",
            dft_code=DftCode.VASP,
            parameters={"ENCUT": 400, "SIGMA": 0.05},
        )
        json_str = original.model_dump_json()
        restored = JobSubmission.model_validate_json(json_str)

        assert restored.name == original.name
        assert restored.dft_code == original.dft_code
        assert restored.parameters == original.parameters


class TestJobStatus:
    """Tests for JobStatus model (sidebar list item)."""

    def test_minimal_status(self):
        """Minimal valid job status."""
        status = JobStatus(
            pk=1,
            uuid="abc-123",
            name="test-job",
            state=JobState.RUNNING,
        )
        assert status.pk == 1
        assert status.progress_percent == 0.0
        assert status.wall_time_seconds is None

    def test_full_status(self):
        """Full job status with all fields."""
        now = datetime.now()
        status = JobStatus(
            pk=42,
            uuid="def-456",
            name="mgo-calc",
            state=JobState.COMPLETED,
            dft_code=DftCode.CRYSTAL,
            runner_type=RunnerType.SSH,
            progress_percent=100.0,
            wall_time_seconds=3600.5,
            created_at=now,
        )
        assert status.pk == 42
        assert status.progress_percent == 100.0
        assert status.wall_time_seconds == 3600.5

    def test_aiida_state_mapping(self):
        """AiiDA process states map to UI states."""
        # AiiDA finished -> COMPLETED
        status = JobStatus(pk=1, uuid="x", name="test", state="finished")
        assert status.state == JobState.COMPLETED

        # AiiDA waiting -> QUEUED
        status = JobStatus(pk=2, uuid="y", name="test", state="waiting")
        assert status.state == JobState.QUEUED

        # AiiDA excepted -> FAILED
        status = JobStatus(pk=3, uuid="z", name="test", state="excepted")
        assert status.state == JobState.FAILED

        # AiiDA killed -> CANCELLED
        status = JobStatus(pk=4, uuid="w", name="test", state="killed")
        assert status.state == JobState.CANCELLED

    def test_database_state_mapping(self):
        """Legacy database states map correctly."""
        status = JobStatus(pk=1, uuid="x", name="test", state="PENDING")
        assert status.state == JobState.CREATED

        status = JobStatus(pk=2, uuid="y", name="test", state="QUEUED")
        assert status.state == JobState.QUEUED

    def test_progress_bounds(self):
        """Progress must be between 0 and 100."""
        with pytest.raises(ValidationError):
            JobStatus(pk=1, uuid="x", name="test", state=JobState.RUNNING, progress_percent=150.0)

        with pytest.raises(ValidationError):
            JobStatus(pk=1, uuid="x", name="test", state=JobState.RUNNING, progress_percent=-10.0)

    def test_json_serialization_for_rust(self):
        """JSON matches Rust serde struct exactly."""
        status = JobStatus(
            pk=1,
            uuid="abc-123",
            name="test",
            state=JobState.RUNNING,
            progress_percent=50.5,
        )
        data = json.loads(status.model_dump_json())

        # Verify exact field names for Rust
        assert "pk" in data
        assert "uuid" in data
        assert "state" in data
        assert "progress_percent" in data
        assert "wall_time_seconds" in data

        # Verify state serializes as string
        assert data["state"] == "RUNNING"

    def test_list_serialization(self):
        """List of JobStatus serializes correctly for Vec<JobStatus> in Rust."""
        statuses = [
            JobStatus(pk=1, uuid="a", name="job1", state=JobState.RUNNING),
            JobStatus(pk=2, uuid="b", name="job2", state=JobState.COMPLETED),
        ]
        json_str = json.dumps([s.model_dump() for s in statuses])
        parsed = json.loads(json_str)

        assert len(parsed) == 2
        assert parsed[0]["pk"] == 1
        assert parsed[1]["state"] == "COMPLETED"


class TestJobDetails:
    """Tests for JobDetails model (results view)."""

    def test_minimal_details(self):
        """Minimal valid job details."""
        details = JobDetails(
            pk=1,
            name="test",
            state=JobState.COMPLETED,
        )
        assert details.final_energy is None
        assert details.convergence_met is False
        assert details.warnings == []

    def test_full_details(self):
        """Full job details with computed results."""
        details = JobDetails(
            pk=42,
            uuid="abc-123",
            name="mgo-scf",
            state=JobState.COMPLETED,
            dft_code=DftCode.CRYSTAL,
            final_energy=-275.123456,
            bandgap_ev=7.8,
            convergence_met=True,
            scf_cycles=15,
            cpu_time_seconds=120.5,
            wall_time_seconds=60.2,
            warnings=["Basis set might be too small"],
            stdout_tail=["TOTAL ENERGY -275.123456 AU", "SCF CONVERGED"],
            key_results={"energy": -275.123456, "converged": True},
            work_dir="/tmp/crystal_123",
        )
        assert details.final_energy == -275.123456
        assert details.convergence_met is True
        assert len(details.warnings) == 1
        assert len(details.stdout_tail) == 2

    def test_scf_cycles_validation(self):
        """SCF cycles must be non-negative."""
        with pytest.raises(ValidationError):
            JobDetails(pk=1, name="test", state=JobState.FAILED, scf_cycles=-5)

    def test_bandgap_validation(self):
        """Bandgap must be non-negative."""
        with pytest.raises(ValidationError):
            JobDetails(pk=1, name="test", state=JobState.COMPLETED, bandgap_ev=-1.0)

    def test_json_serialization(self):
        """JSON output for Rust consumption."""
        details = JobDetails(
            pk=1,
            name="test",
            state=JobState.COMPLETED,
            final_energy=-100.0,
            convergence_met=True,
            warnings=["warning1"],
            stdout_tail=["line1", "line2"],
        )
        data = json.loads(details.model_dump_json())

        assert data["pk"] == 1
        assert data["final_energy"] == -100.0
        assert data["convergence_met"] is True
        assert data["warnings"] == ["warning1"]
        assert data["stdout_tail"] == ["line1", "line2"]


class TestClusterConfig:
    """Tests for ClusterConfig model."""

    def test_minimal_cluster(self):
        """Minimal valid cluster config."""
        cluster = ClusterConfig(
            name="hpc",
            cluster_type="ssh",
            hostname="hpc.example.com",
            username="user",
        )
        assert cluster.port == 22
        assert cluster.status == "active"
        assert cluster.max_concurrent == 4

    def test_slurm_cluster(self):
        """SLURM cluster with queue."""
        cluster = ClusterConfig(
            name="slurm-hpc",
            cluster_type="slurm",
            hostname="slurm.example.com",
            username="hpcuser",
            queue_name="gpu",
            max_concurrent=8,
        )
        assert cluster.cluster_type == "slurm"
        assert cluster.queue_name == "gpu"

    def test_hostname_validation(self):
        """Hostname format validation."""
        # Valid hostnames
        ClusterConfig(name="t", cluster_type="ssh", hostname="localhost", username="u")
        ClusterConfig(name="t", cluster_type="ssh", hostname="hpc.example.com", username="u")
        ClusterConfig(name="t", cluster_type="ssh", hostname="192.168.1.1", username="u")

        # Invalid hostname
        with pytest.raises(ValidationError):
            ClusterConfig(name="t", cluster_type="ssh", hostname="hpc@example", username="u")

    def test_port_validation(self):
        """Port must be in valid range."""
        with pytest.raises(ValidationError):
            ClusterConfig(name="t", cluster_type="ssh", hostname="h", username="u", port=0)

        with pytest.raises(ValidationError):
            ClusterConfig(name="t", cluster_type="ssh", hostname="h", username="u", port=70000)


class TestStructureData:
    """Tests for StructureData model."""

    def test_cubic_structure(self):
        """Cubic crystal structure (e.g., MgO)."""
        struct = StructureData(
            formula="MgO",
            lattice_a=4.21,
            lattice_b=4.21,
            lattice_c=4.21,
            space_group=225,
        )
        assert struct.alpha == 90.0
        assert struct.beta == 90.0
        assert struct.gamma == 90.0
        assert struct.space_group == 225

    def test_hexagonal_structure(self):
        """Hexagonal crystal structure."""
        struct = StructureData(
            formula="MoS2",
            lattice_a=3.16,
            lattice_b=3.16,
            lattice_c=12.29,
            alpha=90.0,
            beta=90.0,
            gamma=120.0,
            layer_group=73,
        )
        assert struct.gamma == 120.0
        assert struct.layer_group == 73

    def test_space_group_validation(self):
        """Space group must be 1-230."""
        with pytest.raises(ValidationError):
            StructureData(
                formula="X",
                lattice_a=1,
                lattice_b=1,
                lattice_c=1,
                space_group=300,
            )

    def test_lattice_positive(self):
        """Lattice parameters must be positive."""
        with pytest.raises(ValidationError):
            StructureData(
                formula="X",
                lattice_a=-1,
                lattice_b=1,
                lattice_c=1,
            )


class TestSerdeCompatibility:
    """
    Tests verifying Rust serde compatibility.

    These tests ensure the JSON output can be deserialized by Rust's serde.
    """

    def test_optional_fields_serialize_as_null(self):
        """Optional fields must serialize as null, not be omitted."""
        status = JobStatus(pk=1, uuid="x", name="test", state=JobState.RUNNING)
        data = json.loads(status.model_dump_json())

        # Optional fields should be present with null value
        assert "wall_time_seconds" in data
        assert data["wall_time_seconds"] is None

    def test_enum_values_are_strings(self):
        """Enums serialize as strings for Rust serde derive."""
        status = JobStatus(pk=1, uuid="x", name="test", state=JobState.RUNNING)
        data = json.loads(status.model_dump_json())

        assert isinstance(data["state"], str)
        assert isinstance(data["dft_code"], str)
        assert isinstance(data["runner_type"], str)

    def test_nested_dict_serialization(self):
        """Nested dicts serialize for serde_json::Value."""
        job = JobSubmission(
            name="test",
            parameters={
                "OPTGEOM": {},
                "SHRINK": [8, 8],
                "nested": {"a": 1, "b": [2, 3]},
            },
        )
        json_str = job.model_dump_json()
        data = json.loads(json_str)

        assert data["parameters"]["OPTGEOM"] == {}
        assert data["parameters"]["SHRINK"] == [8, 8]
        assert data["parameters"]["nested"]["a"] == 1

    def test_datetime_iso_format(self):
        """Datetimes serialize as ISO 8601 strings."""
        now = datetime(2024, 1, 15, 10, 30, 0)
        status = JobStatus(
            pk=1,
            uuid="x",
            name="test",
            state=JobState.RUNNING,
            created_at=now,
        )
        data = status.model_dump(mode="json")

        # datetime should be ISO format string
        assert data["created_at"] == "2024-01-15T10:30:00"
