"""
CrystalMath Python Backend.

This package provides the Python scientific backend for the CrystalMath Rust TUI.
It exposes AiiDA workflow management through a simple JSON-based API for PyO3 consumption.
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
