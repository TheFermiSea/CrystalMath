"""
Centralized constants for the TUI application.

This module provides a single source of truth for all status constants used
throughout the application, preventing typos and inconsistencies.

Usage:
    from src.core.constants import JobStatus, QueueStatus, RunnerType

    if job.status == JobStatus.RUNNING:
        # Handle running job
        pass
"""


class JobStatus:
    """Job execution status constants.

    Note: Database uses uppercase values for the CHECK constraint.
    All status constants should be uppercase for database compatibility.
    """
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"
    QUEUED = "QUEUED"

    @classmethod
    def all(cls):
        """Return all valid status values."""
        return [
            cls.PENDING,
            cls.RUNNING,
            cls.COMPLETED,
            cls.FAILED,
            cls.CANCELLED,
            cls.UNKNOWN,
            cls.QUEUED,
        ]


class QueueStatus:
    """Queue/workflow status constants."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"

    @classmethod
    def all(cls):
        """Return all valid queue status values."""
        return [
            cls.PENDING,
            cls.IN_PROGRESS,
            cls.COMPLETED,
            cls.FAILED,
            cls.PAUSED,
            cls.CANCELLED,
        ]


class RunnerType:
    """Job runner types."""
    LOCAL = "local"
    SSH = "ssh"
    SLURM = "slurm"

    @classmethod
    def all(cls):
        """Return all valid runner types."""
        return [cls.LOCAL, cls.SSH, cls.SLURM]


class NodeStatus:
    """Workflow node status constants."""
    PENDING = "pending"
    READY = "ready"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

    @classmethod
    def all(cls):
        """Return all valid node status values."""
        return [
            cls.PENDING,
            cls.READY,
            cls.QUEUED,
            cls.RUNNING,
            cls.COMPLETED,
            cls.FAILED,
            cls.SKIPPED,
        ]


class WorkflowStatus:
    """Workflow execution status constants."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @classmethod
    def all(cls):
        """Return all valid workflow status values."""
        return [
            cls.PENDING,
            cls.RUNNING,
            cls.PAUSED,
            cls.COMPLETED,
            cls.FAILED,
            cls.CANCELLED,
        ]
