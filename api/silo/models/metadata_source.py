from sqlalchemy.orm import Mapped, mapped_column

from silo.models.base import Base, UUIDPrimaryKeyMixin


class MetadataSource(UUIDPrimaryKeyMixin, Base):
    """Metadata source registry."""

    __tablename__ = "metadata_source"

    slug: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    enabled: Mapped[bool] = mapped_column(default=True)
    required: Mapped[bool] = mapped_column(default=False)
    priority: Mapped[int]
    request_interval_ms: Mapped[int | None] = mapped_column(default=None)
