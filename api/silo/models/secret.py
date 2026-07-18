from sqlalchemy.orm import Mapped, mapped_column

from silo.models.base import Base


class Secret(Base):
    """Secret."""

    __tablename__ = "secret"

    name: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str]
