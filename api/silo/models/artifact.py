import enum
import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from silo.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, string_enum


class ArtifactKind(enum.StrEnum):
    INSTALLER = "installer"
    PATCH = "patch"
    LANGUAGE_PACK = "language_pack"
    DISC = "disc"
    ROM = "rom"
    EXTRA = "extra"
    SAVE = "save"
    MANUAL = "manual"
    OTHER = "other"


class ArtifactStatus(enum.StrEnum):
    MISSING = "missing"
    PARTIAL = "partial"
    STORED = "stored"


class Artifact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Artifact."""

    __tablename__ = "artifact"

    game_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("game.id", ondelete="CASCADE"))
    kind: Mapped[ArtifactKind] = mapped_column(string_enum(ArtifactKind))
    platform_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platform.id"))
    language: Mapped[str | None]
    version: Mapped[str | None]
    total_size: Mapped[int | None]
    status: Mapped[ArtifactStatus] = mapped_column(string_enum(ArtifactStatus))
    name: Mapped[str | None]
