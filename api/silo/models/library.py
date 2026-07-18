from sqlalchemy.orm import Mapped, mapped_column

from silo.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Library(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Game library."""

    __tablename__ = "library"

    slug: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
