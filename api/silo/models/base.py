import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, MetaData, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Stable, explicit constraint names: https://alembic.sqlalchemy.org/en/latest/naming.html
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base DB model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    """Naive UTC helper."""
    return datetime.now(UTC).replace(tzinfo=None)


def string_enum(enum_cls: type[enum.Enum]) -> SAEnum:
    """SQLAlchemy Enum stored as VARCHAR without a DB CHECK constraint."""
    return SAEnum(enum_cls, native_enum=False, create_constraint=False, length=64)


class TimestampMixin:
    """Created and updated timestamps."""

    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class CreatedAtMixin:
    """Created timestamp."""

    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class UUIDPrimaryKeyMixin:
    """UUIDv4 primary key."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class ExternalIdentityMixin:
    """External identity columns."""

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("metadata_source.id", ondelete="CASCADE"), primary_key=True
    )
    external_id: Mapped[str]
