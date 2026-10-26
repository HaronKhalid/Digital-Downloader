"""Job model and state machine. Re-exported from core.models.job for backward compatibility."""

from __future__ import annotations

from core.models.job import InvalidTransition, Job, JobStatus, TERMINAL

__all__ = ["Job", "JobStatus", "TERMINAL", "InvalidTransition"]
