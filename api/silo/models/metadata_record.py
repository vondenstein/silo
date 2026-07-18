import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from silo.models.base import Base, UUIDPrimaryKeyMixin, utcnow


class MetadataRecord(UUIDPrimaryKeyMixin, Base):
    """External metadata record."""

    __tablename__ = "metadata_record"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("metadata_source.id", ondelete="CASCADE")
    )
    external_id: Mapped[str]
    api_version: Mapped[str]
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    normalized: Mapped[dict[str, Any]] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(default=utcnow)
