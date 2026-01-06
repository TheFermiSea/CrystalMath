"""
Pydantic models for CrystalMath core data exchange.

These models define the contract between Python components (TUI/CLI) and any
optional Rust/IPC adapters. The core API returns native models; serialization
is handled at the boundary when needed.

Schema Compatibility:
- JSON output matches Rust serde structs where applicable
- Field names use snake_case (Rust convention)
- Optional fields serialize as null (not omitted)
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ========== State Mapping Helper ==========

# Mapping from AiiDA/legacy states to UI states (centralized)
_AIIDA_STATE_MAP: Dict[str, "JobState"] = {
    # AiiDA process states
    "created": None,  # Will be set to JobState.CREATED after class definition
    "waiting": None,  # JobState.QUEUED
    "running": None,  # JobState.RUNNING
    "finished": None,  # JobState.COMPLETED
    "excepted": None,  # JobState.FAILED
    "killed": None,  # JobState.CANCELLED
    # Legacy database states
    "pending": None,  # JobState.CREATED
    "queued": None,  # JobState.QUEUED
    "completed": None,  # JobState.COMPLETED
    "failed": None,  # JobState.FAILED
    "cancelled": None,  # JobState.CANCELLED
}


def _init_state_map() -> None:
    """Initialize state map after JobState is defined."""
    _AIIDA_STATE_MAP.update(
        {
            "created": JobState.CREATED,
            "waiting": JobState.QUEUED,
            "running": JobState.RUNNING,
            "finished": JobState.COMPLETED,
            "excepted": JobState.FAILED,
            "killed": JobState.CANCELLED,
            "pending": JobState.CREATED,
            "queued": JobState.QUEUED,
            "completed": JobState.COMPLETED,
            "failed": JobState.FAILED,
            "cancelled": JobState.CANCELLED,
        }
    )


def map_to_job_state(value: Any) -> "JobState":
    """
    Map various state representations to JobState enum.

    Handles:
    - JobState instances (passthrough)
    - Standard JobState string values (case-insensitive)
    - AiiDA process states (created, waiting, running, finished, excepted, killed)
    - Legacy database states (pending, queued, completed, failed, cancelled)

    Args:
        value: State value to convert

    Returns:
        Corresponding JobState enum value, defaults to CREATED for unknown
    """
    if isinstance(value, JobState):
        return value

    if isinstance(value, str):
        # Try direct mapping (case-insensitive for standard states)
        try:
            return JobState(value.upper())
        except ValueError:
            pass

        # Try AiiDA/legacy state mapping
        return _AIIDA_STATE_MAP.get(value.lower(), JobState.CREATED)

    return JobState.CREATED


class JobState(str, Enum):
    """
    Job execution state enum.

    Maps to Rust's JobState enum via serde string serialization.
    Also maps from AiiDA process states via map_to_job_state().
    """

    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# Initialize state map now that JobState is defined
_init_state_map()


class DftCode(str, Enum):
    """
    Supported DFT calculation codes.

    Determines input file format and validation rules.
    """

    CRYSTAL = "crystal"
    VASP = "vasp"
    QUANTUM_ESPRESSO = "quantum_espresso"


class RunnerType(str, Enum):
    """
    Job execution backend types.

    Determines how jobs are submitted and monitored.
    """

    LOCAL = "local"
    SSH = "ssh"
    SLURM = "slurm"
    AIIDA = "aiida"


class SchedulerOptions(BaseModel):
    """
    SLURM scheduler resource configuration.

    Used when runner_type is SLURM.
    """

    model_config = ConfigDict(extra="forbid")

    walltime: str = Field(default="24:00:00", description="Walltime limit (HH:MM:SS)")
    memory_gb: str = Field(default="32", description="Memory per node in GB")
    cpus_per_task: int = Field(default=4, gt=0, description="CPUs per task")
    nodes: int = Field(default=1, gt=0, description="Number of nodes")
    partition: Optional[str] = Field(default=None, description="SLURM partition/queue")


class JobSubmission(BaseModel):
    """
    Data required to submit a new calculation job.

    Sent from Rust to Python when creating a new job.
    Validated with Pydantic before AiiDA submission.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(..., min_length=3, max_length=100, description="Job display name")
    dft_code: DftCode = Field(default=DftCode.CRYSTAL, description="DFT code to use")
    cluster_id: Optional[int] = Field(
        default=None, description="Target cluster ID (None for local)"
    )
    runner_type: RunnerType = Field(default=RunnerType.LOCAL, description="Execution backend")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="DFT input parameters")
    structure_path: Optional[str] = Field(
        default=None, description="Path to structure file (.cif, .xyz)"
    )
    input_content: Optional[str] = Field(
        default=None, description="Raw input file content (.d12, INCAR)"
    )

    # Extended configuration
    auxiliary_files: Optional[Dict[str, str]] = Field(
        default=None, description="Auxiliary files map (type -> source_path)"
    )
    scheduler_options: Optional[SchedulerOptions] = Field(
        default=None, description="SLURM resource settings"
    )
    mpi_ranks: Optional[int] = Field(default=None, gt=0, description="Number of MPI ranks")
    parallel_mode: Optional[str] = Field(
        default=None, description="Parallel mode ('serial' or 'parallel')"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure name is filesystem-safe."""
        forbidden = set('/\\:*?"<>|')
        if any(c in v for c in forbidden):
            raise ValueError(f"Name contains forbidden characters: {forbidden}")
        return v.strip()

    @model_validator(mode="after")
    def check_input_source(self) -> "JobSubmission":
        """Ensure either parameters or input_content is provided."""
        if not self.parameters and not self.input_content:
            raise ValueError("Either parameters or input_content must be provided")
        return self


class JobStatus(BaseModel):
    """
    Lightweight job status for the sidebar list.

    Optimized for frequent polling - contains only essential fields.
    Returned from the core API; JSON adapters may serialize as needed.
    """

    model_config = ConfigDict(extra="forbid")

    pk: int = Field(..., description="Primary key (database ID)")
    uuid: str = Field(..., description="Unique identifier")
    name: str = Field(..., description="Job display name")
    state: JobState = Field(..., description="Current execution state")
    dft_code: DftCode = Field(default=DftCode.CRYSTAL, description="DFT code type")
    runner_type: RunnerType = Field(default=RunnerType.LOCAL, description="Execution backend")
    progress_percent: float = Field(
        default=0.0, ge=0.0, le=100.0, description="Completion progress"
    )
    wall_time_seconds: Optional[float] = Field(
        default=None, ge=0.0, description="Elapsed wall time"
    )
    created_at: Optional[datetime] = Field(default=None, description="Job creation timestamp")

    @field_validator("state", mode="before")
    @classmethod
    def map_aiida_state(cls, v: Any) -> JobState:
        """Map AiiDA process states to simplified UI states using centralized helper."""
        return map_to_job_state(v)


class JobDetails(BaseModel):
    """
    Full job details for the Results view.

    Contains computed results and output logs.
    Returned from the core API; JSON adapters may serialize as needed.
    """

    model_config = ConfigDict(extra="forbid")

    pk: int = Field(..., description="Primary key (database ID)")
    uuid: Optional[str] = Field(default=None, description="Unique identifier")
    name: str = Field(..., description="Job display name")
    state: JobState = Field(..., description="Current execution state")
    dft_code: DftCode = Field(default=DftCode.CRYSTAL, description="DFT code type")

    # Computed results
    final_energy: Optional[float] = Field(default=None, description="Final total energy (Hartree)")
    bandgap_ev: Optional[float] = Field(default=None, ge=0.0, description="Band gap (eV)")
    convergence_met: bool = Field(default=False, description="SCF convergence achieved")
    scf_cycles: Optional[int] = Field(default=None, ge=0, description="Number of SCF cycles")

    # Timing
    cpu_time_seconds: Optional[float] = Field(default=None, ge=0.0, description="CPU time")
    wall_time_seconds: Optional[float] = Field(default=None, ge=0.0, description="Wall clock time")

    # Diagnostics
    warnings: List[str] = Field(default_factory=list, description="Warning messages")
    errors: List[str] = Field(default_factory=list, description="Error messages")
    stdout_tail: List[str] = Field(default_factory=list, description="Last N lines of stdout")

    # Full results dict (for JSON export)
    key_results: Optional[Dict[str, Any]] = Field(
        default=None, description="Full results dictionary"
    )

    # Input/output paths
    work_dir: Optional[str] = Field(default=None, description="Working directory path")
    input_file: Optional[str] = Field(default=None, description="Input file content")

    @field_validator("state", mode="before")
    @classmethod
    def map_state(cls, v: Any) -> JobState:
        """Map states using centralized helper (same logic as JobStatus)."""
        return map_to_job_state(v)


class ClusterConfig(BaseModel):
    """
    Remote cluster configuration.

    Used for SSH and SLURM job submission.
    """

    model_config = ConfigDict(extra="forbid")

    id: Optional[int] = Field(default=None, description="Database ID")
    name: str = Field(..., min_length=1, max_length=50, description="Cluster display name")
    cluster_type: Literal["ssh", "slurm"] = Field(..., description="Cluster type")
    hostname: str = Field(..., min_length=1, description="Hostname or IP address")
    port: int = Field(default=22, ge=1, le=65535, description="SSH port")
    username: str = Field(..., min_length=1, description="SSH username")

    # Optional configuration
    key_file: Optional[str] = Field(default=None, description="Path to SSH private key")
    remote_workdir: Optional[str] = Field(default=None, description="Remote working directory")
    queue_name: Optional[str] = Field(default=None, description="SLURM queue/partition name")
    max_concurrent: int = Field(default=4, ge=1, description="Max concurrent jobs")

    # Status
    status: Literal["active", "inactive", "error"] = Field(default="active")

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, v: str) -> str:
        """Basic hostname validation."""
        # Allow hostnames, IPs, and FQDN
        import re

        pattern = r"^[a-zA-Z0-9]([a-zA-Z0-9\-\.]*[a-zA-Z0-9])?$"
        if not re.match(pattern, v):
            raise ValueError(f"Invalid hostname format: {v}")
        return v


class StructureData(BaseModel):
    """
    Crystal structure data for input generation.

    Can be populated from Materials Project, CIF, or manual input.
    """

    model_config = ConfigDict(extra="forbid")

    formula: str = Field(..., description="Chemical formula")
    lattice_a: float = Field(..., gt=0, description="Lattice parameter a (Angstrom)")
    lattice_b: float = Field(..., gt=0, description="Lattice parameter b (Angstrom)")
    lattice_c: float = Field(..., gt=0, description="Lattice parameter c (Angstrom)")
    alpha: float = Field(default=90.0, ge=0, le=180, description="Angle alpha (degrees)")
    beta: float = Field(default=90.0, ge=0, le=180, description="Angle beta (degrees)")
    gamma: float = Field(default=90.0, ge=0, le=180, description="Angle gamma (degrees)")

    space_group: Optional[int] = Field(default=None, ge=1, le=230, description="Space group number")
    layer_group: Optional[int] = Field(
        default=None, ge=1, le=80, description="Layer group (for SLAB)"
    )

    # Atomic positions
    atoms: List[Dict[str, Any]] = Field(default_factory=list, description="Atomic positions")

    # Source information
    source: Optional[str] = Field(default=None, description="Data source (mp, cif, manual)")
    material_id: Optional[str] = Field(default=None, description="Materials Project ID")


# Type aliases for Rust compatibility
JobStatusList = List[JobStatus]
