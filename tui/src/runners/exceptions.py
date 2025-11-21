"""
Runner-specific exceptions for CRYSTAL job execution.

This module defines a hierarchy of exceptions for handling errors
during job execution across different runner backends (local, SSH, SLURM).
"""


class RunnerError(Exception):
    """
    Base exception for all runner errors.

    All runner-specific exceptions inherit from this class to allow
    generic error handling at the application level.
    """
    pass


class ConnectionError(RunnerError):
    """
    Raised when connection to a remote execution environment fails.

    This applies to:
    - SSH connection failures
    - SLURM scheduler connection issues
    - Network timeouts or authentication failures

    Attributes:
        host: The remote host or cluster that failed to connect
        details: Additional error details from underlying connection attempt
    """

    def __init__(self, message: str, host: str = "", details: str = ""):
        super().__init__(message)
        self.host = host
        self.details = details


class ExecutionError(RunnerError):
    """
    Raised when job execution fails after successful submission.

    This indicates the job was successfully started but encountered
    an error during execution (e.g., invalid input, resource limits,
    CRYSTAL internal errors).

    Attributes:
        job_handle: The job identifier that failed
        exit_code: Process exit code if available
        stderr_output: Standard error output from the failed job
    """

    def __init__(
        self,
        message: str,
        job_handle: str = "",
        exit_code: int | None = None,
        stderr_output: str = ""
    ):
        super().__init__(message)
        self.job_handle = job_handle
        self.exit_code = exit_code
        self.stderr_output = stderr_output


class TimeoutError(RunnerError):
    """
    Raised when a job or operation exceeds its timeout limit.

    This can occur during:
    - Job submission (queue timeout)
    - Job execution (wall time exceeded)
    - Result retrieval (network timeout)
    - Status polling (connection timeout)

    Attributes:
        timeout_seconds: The timeout limit that was exceeded
        operation: Description of the operation that timed out
    """

    def __init__(self, message: str, timeout_seconds: float = 0.0, operation: str = ""):
        super().__init__(message)
        self.timeout_seconds = timeout_seconds
        self.operation = operation


class ConfigurationError(RunnerError):
    """
    Raised when runner configuration is invalid or incomplete.

    This includes:
    - Missing required configuration parameters
    - Invalid executable paths
    - Malformed runner-specific settings
    - Incompatible configuration combinations

    Attributes:
        config_key: The configuration parameter that is invalid
        expected_format: Description of the expected format
    """

    def __init__(self, message: str, config_key: str = "", expected_format: str = ""):
        super().__init__(message)
        self.config_key = config_key
        self.expected_format = expected_format


class ResourceError(RunnerError):
    """
    Raised when required resources are unavailable or exhausted.

    This includes:
    - Insufficient disk space in scratch directory
    - Memory allocation failures
    - CPU/GPU availability issues
    - Queue or slot limits exceeded

    Attributes:
        resource_type: The type of resource that is unavailable
        required: Amount of resource required
        available: Amount of resource available (if known)
    """

    def __init__(
        self,
        message: str,
        resource_type: str = "",
        required: str = "",
        available: str = ""
    ):
        super().__init__(message)
        self.resource_type = resource_type
        self.required = required
        self.available = available


class CancellationError(RunnerError):
    """
    Raised when job cancellation fails.

    This can occur when:
    - Job no longer exists in the scheduler
    - Insufficient permissions to cancel the job
    - Job is in a non-cancellable state
    - Communication with scheduler fails during cancellation

    Attributes:
        job_handle: The job identifier that could not be cancelled
        reason: Specific reason for cancellation failure
    """

    def __init__(self, message: str, job_handle: str = "", reason: str = ""):
        super().__init__(message)
        self.job_handle = job_handle
        self.reason = reason
