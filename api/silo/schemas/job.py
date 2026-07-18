import enum
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict

from silo.models.job import JobKind, JobStatus
from silo.schemas.common import UTCDateTime


class JobStageStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStage(BaseModel):
    """One stage of a job's typed progress."""

    key: str
    label: str
    group: str | None = None
    status: JobStageStatus = JobStageStatus.PENDING
    error: str | None = None
    bytes_done: int | None = None
    bytes_total: int | None = None


class JobProgress(BaseModel):
    """Staged job progress."""

    stages: list[JobStage] = []


class Job(BaseModel):
    """Job with kind-typed JSON payload/result (typed per kind client-side)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: JobKind
    status: JobStatus
    payload: dict[str, Any]
    progress: JobProgress
    result: dict[str, Any] | None
    error: str | None
    created_at: UTCDateTime
    updated_at: UTCDateTime


class JobEnqueuedOut(BaseModel):
    """Reference to a queued job."""

    job_id: uuid.UUID
