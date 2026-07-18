import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from silo.models.base import Base, ExternalIdentityMixin, UUIDPrimaryKeyMixin


class Series(UUIDPrimaryKeyMixin, Base):
    """Series."""

    __tablename__ = "series"

    slug: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]


class SeriesAlias(Base):
    """Series alias."""

    __tablename__ = "series_alias"

    series_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("series.id", ondelete="CASCADE"), primary_key=True
    )
    alias: Mapped[str] = mapped_column(primary_key=True)


class SeriesExternalIdentity(ExternalIdentityMixin, Base):
    """Series external identity."""

    __tablename__ = "series_external_identity"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)

    series_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("series.id", ondelete="CASCADE"), primary_key=True
    )
