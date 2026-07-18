import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from silo.models.base import Base, UUIDPrimaryKeyMixin


class IdentificationSource(UUIDPrimaryKeyMixin, Base):
    """Identification source."""

    __tablename__ = "identification_source"

    slug: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    enabled: Mapped[bool] = mapped_column(default=True)


class IdentificationDataset(UUIDPrimaryKeyMixin, Base):
    """Identification dataset."""

    __tablename__ = "identification_dataset"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("identification_source.id", ondelete="CASCADE")
    )
    slug: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    platform_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platform.id"))
    dataset_url: Mapped[str | None]
    dataset_version: Mapped[str | None]
    refreshed_at: Mapped[datetime | None]
    enabled: Mapped[bool] = mapped_column(default=True)


class IdentificationSignature(UUIDPrimaryKeyMixin, Base):
    """Identification signature."""

    __tablename__ = "identification_signature"
    __table_args__ = (
        UniqueConstraint("dataset_id", "game_name", "file_name"),
        # Derived matching (stage + detail) queries these at Redump scale.
        Index("ix_identification_signature_md5", "md5"),
        Index("ix_identification_signature_sha1", "sha1"),
        Index("ix_identification_signature_sha256", "sha256"),
        Index("ix_identification_signature_crc32", "crc32"),
    )

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("identification_dataset.id", ondelete="CASCADE")
    )
    game_name: Mapped[str]
    file_name: Mapped[str]
    category: Mapped[str | None]
    md5: Mapped[str | None]
    sha1: Mapped[str | None]
    sha256: Mapped[str | None]
    crc32: Mapped[str | None]
    size: Mapped[int | None] = mapped_column(BigInteger)
