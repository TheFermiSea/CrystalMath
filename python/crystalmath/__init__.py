"""
CrystalMath Python Core.

This package provides the shared scientific backend for CrystalMath. The core
API returns native Pydantic models for Python consumers, with optional JSON
adapters for Rust/IPC boundaries.
"""

from crystalmath.models import (
    JobState,
    DftCode,
    JobSubmission,
    JobStatus,
    JobDetails,
    ClusterConfig,
    StructureData,
    RunnerType,
    map_to_job_state,
)

__version__ = "0.2.0"
__all__ = [
    "JobState",
    "DftCode",
    "JobSubmission",
    "JobStatus",
    "JobDetails",
    "ClusterConfig",
    "StructureData",
    "RunnerType",
    "map_to_job_state",
]
