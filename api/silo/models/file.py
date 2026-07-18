import uuid

from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from silo.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class File(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """File."""

    __tablename__ = "file"

    artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artifact.id", ondelete="CASCADE"))
    source_file_id: Mapped[str | None]
    download_url: Mapped[str | None]
    relative_path: Mapped[str | None]
    size: Mapped[int | None] = mapped_column(BigInteger)
    blake3: Mapped[str | None]
    md5: Mapped[str | None]
    sha1: Mapped[str | None]
    sha256: Mapped[str | None]
    crc32: Mapped[str | None]
