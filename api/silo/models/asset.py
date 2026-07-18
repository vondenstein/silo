import enum
import uuid

from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from silo.models.base import Base, string_enum


class AssetKind(enum.StrEnum):
    COVER = "cover"
    BACKGROUND = "background"
    LANDSCAPE = "landscape"
    LOGO = "logo"
    ICON = "icon"
    SCREENSHOT = "screenshot"
    VIDEO_THUMBNAIL = "video_thumbnail"


class AssetBlob(Base):
    """Asset blob."""

    __tablename__ = "asset_blob"

    blake3: Mapped[str] = mapped_column(primary_key=True)
    mime: Mapped[str]
    size: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int | None]
    height: Mapped[int | None]


class SourceAsset(Base):
    """Source asset."""

    __tablename__ = "source_asset"

    metadata_record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("metadata_record.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[AssetKind] = mapped_column(string_enum(AssetKind), primary_key=True)
    blob_blake3: Mapped[str] = mapped_column(ForeignKey("asset_blob.blake3"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(default=0)
