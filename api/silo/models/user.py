from sqlalchemy.orm import Mapped

from silo.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Silo user."""

    __tablename__ = "user"

    name: Mapped[str]
