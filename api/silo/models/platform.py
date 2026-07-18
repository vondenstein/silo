import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from silo.models.base import Base, UUIDPrimaryKeyMixin


class PlatformFamily(UUIDPrimaryKeyMixin, Base):
    """Platform family."""

    __tablename__ = "platform_family"

    slug: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    manufacturer: Mapped[str]
    is_pc: Mapped[bool] = mapped_column(default=False)
    icon: Mapped[str]


class Platform(UUIDPrimaryKeyMixin, Base):
    """Platform."""

    __tablename__ = "platform"

    slug: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    icon: Mapped[str | None]
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform_family.id"))
