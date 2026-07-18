from typing import Any

from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from silo.models.base import Base


class Setting(Base):
    """Setting."""

    __tablename__ = "setting"

    namespace: Mapped[str] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
