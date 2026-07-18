import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from silo.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, string_enum


class JobKind(enum.StrEnum):
    GOG_IMPORT = "gog_import"
    FETCH_METADATA = "fetch_metadata"
    RENORMALIZE_METADATA = "renormalize_metadata"
    REFRESH_IDENTIFICATION_DATASET = "refresh_identification_dataset"
    REFRESH_IDENTIFICATION_DATASETS = "refresh_identification_datasets"
    IDENTIFY_GAME = "identify_game"


class JobStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Job."""

    __tablename__ = "job"

    kind: Mapped[JobKind] = mapped_column(string_enum(JobKind))
    status: Mapped[JobStatus] = mapped_column(string_enum(JobStatus), default=JobStatus.PENDING)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    error: Mapped[str | None]
    claimed_at: Mapped[datetime | None]


class Schedule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Schedule."""

    __tablename__ = "schedule"

    kind: Mapped[JobKind] = mapped_column(string_enum(JobKind))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    hour: Mapped[int]
    next_run: Mapped[datetime]
    last_run: Mapped[datetime | None]
    enabled: Mapped[bool] = mapped_column(default=True)
