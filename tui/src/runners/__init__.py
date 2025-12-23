"""Job execution backends."""

from .base import (
    BaseRunner,
    RemoteBaseRunner,
    RunnerConfig,
    JobHandle,
    JobStatus,
    JobInfo,
)
from .exceptions import (
    # Base exception
    RunnerError,
    # Common exceptions
    ConnectionError,
    ExecutionError,
    TimeoutError,
    ConfigurationError,
    ResourceError,
    CancellationError,
    JobSubmissionError,
    JobNotFoundError,
    # Runner-specific exceptions
    LocalRunnerError,
    SSHRunnerError,
    SLURMRunnerError,
)
from .local import (
    LocalRunner,
    JobResult,
    ExecutableNotFoundError,
    InputFileError,
    run_crystal_job,
    run_dft_job,
)
from .slurm_runner import (
    SLURMRunner,
    SLURMJobConfig,
    SLURMJobState,
    SLURMSubmissionError,
    SLURMStatusError,
)

__all__ = [
    # Base classes and types
    "BaseRunner",
    "RemoteBaseRunner",
    "RunnerConfig",
    "JobHandle",
    "JobStatus",
    "JobInfo",
    # Base exception
    "RunnerError",
    # Common exceptions
    "ConnectionError",
    "ExecutionError",
    "TimeoutError",
    "ConfigurationError",
    "ResourceError",
    "CancellationError",
    "JobSubmissionError",
    "JobNotFoundError",
    # Runner-specific exceptions
    "LocalRunnerError",
    "SSHRunnerError",
    "SLURMRunnerError",
    # Local Runner
    "LocalRunner",
    "JobResult",
    "ExecutableNotFoundError",
    "InputFileError",
    "run_crystal_job",
    "run_dft_job",
    # SLURM Runner
    "SLURMRunner",
    "SLURMJobConfig",
    "SLURMJobState",
    "SLURMSubmissionError",
    "SLURMStatusError",
]
