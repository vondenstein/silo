import enum
import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from silo.models.base import Base, ExternalIdentityMixin, UUIDPrimaryKeyMixin, string_enum


class TagKind(enum.StrEnum):
    GENRE = "genre"
    THEME = "theme"
    TAG = "tag"
    ENGINE = "engine"
    MODE = "mode"


class Tag(UUIDPrimaryKeyMixin, Base):
    """Tag."""

    __tablename__ = "tag"
    __table_args__ = (UniqueConstraint("kind", "slug"),)

    kind: Mapped[TagKind] = mapped_column(string_enum(TagKind))
    slug: Mapped[str]
    name: Mapped[str]


class TagAlias(Base):
    """Tag alias."""

    __tablename__ = "tag_alias"

    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True
    )
    alias: Mapped[str] = mapped_column(primary_key=True)


class TagExternalIdentity(ExternalIdentityMixin, Base):
    """Tag external identity."""

    __tablename__ = "tag_external_identity"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)

    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True
    )
