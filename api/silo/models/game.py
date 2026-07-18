import enum
import uuid
from datetime import date, datetime

from sqlalchemy import JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from silo.models.asset import AssetKind
from silo.models.base import (
    Base,
    ExternalIdentityMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    string_enum,
)


class SysRequirementKind(enum.StrEnum):
    MINIMUM = "minimum"
    RECOMMENDED = "recommended"


class SysRequirementKey(enum.StrEnum):
    OS = "os"
    OS_VERSION = "os_version"
    CPU = "cpu"
    MEMORY = "memory"
    GPU = "gpu"
    STORAGE = "storage"
    DIRECTX = "directx"
    SOUND = "sound"
    NOTES = "notes"


class RatingAuthority(enum.StrEnum):
    ESRB = "esrb"
    PEGI = "pegi"
    USK = "usk"
    CERO = "cero"
    ACB = "acb"
    CLASSIND = "classind"
    GRAC = "grac"
    CSRR = "csrr"
    IGRS = "igrs"


class CompanyRole(enum.StrEnum):
    DEVELOPER = "developer"
    PUBLISHER = "publisher"


class GameOrigin(enum.StrEnum):
    GOG_IMPORT = "gog_import"


class WrapperKind(enum.StrEnum):
    DOSBOX = "dosbox"
    SCUMMVM = "scummvm"


class GameType(enum.StrEnum):
    MAIN = "main"
    DLC = "dlc"
    EXPANSION = "expansion"


class Game(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Game."""

    __tablename__ = "game"
    __table_args__ = (UniqueConstraint("library_id", "slug"),)

    library_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("library.id"))
    slug: Mapped[str]
    origin: Mapped[GameOrigin | None] = mapped_column(string_enum(GameOrigin))
    preferred_source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("metadata_source.id"))
    game_metadata: Mapped["GameMetadata"] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True
    )


class GameAltName(Base):
    """Game alt name."""

    __tablename__ = "game_alt_name"

    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(primary_key=True)
    comment: Mapped[str | None]


class GameSerial(Base):
    """Game serial."""

    __tablename__ = "game_serial"

    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), primary_key=True
    )
    value: Mapped[str] = mapped_column(primary_key=True)
    comment: Mapped[str | None]


class GameExternalIdentity(ExternalIdentityMixin, Base):
    """Game external identity."""

    __tablename__ = "game_external_identity"

    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), primary_key=True
    )


class GameMetadata(Base):
    """Game metadata."""

    __tablename__ = "game_metadata"

    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), primary_key=True
    )
    title: Mapped[str]
    sort_title: Mapped[str | None]
    description_short: Mapped[str | None]
    description_full: Mapped[str | None]
    first_release_date: Mapped[date | None]
    wrapper: Mapped[WrapperKind | None] = mapped_column(string_enum(WrapperKind))
    game_type: Mapped[GameType | None] = mapped_column(string_enum(GameType))
    resolved_at: Mapped[datetime | None]


class GameSeries(Base):
    """Game series."""

    __tablename__ = "game_series"

    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), primary_key=True
    )
    series_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("series.id", ondelete="CASCADE"), primary_key=True
    )


class GameCompany(Base):
    """Game company."""

    __tablename__ = "game_company"

    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), primary_key=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("company.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[CompanyRole] = mapped_column(string_enum(CompanyRole), primary_key=True)


class GamePlatform(Base):
    """Game platform."""

    __tablename__ = "game_platform"

    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), primary_key=True
    )
    platform_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform.id", ondelete="CASCADE"), primary_key=True
    )


class GameRating(Base):
    """Game rating."""

    __tablename__ = "game_rating"

    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), primary_key=True
    )
    authority: Mapped[RatingAuthority] = mapped_column(
        string_enum(RatingAuthority), primary_key=True
    )
    value: Mapped[str]
    descriptors: Mapped[list[str]] = mapped_column(JSON)


class GameReleaseDate(Base):
    """Game release date."""

    __tablename__ = "game_release_date"

    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), primary_key=True
    )
    platform_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform.id", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[date]


class GameSysRequirement(Base):
    """Game sys requirement."""

    __tablename__ = "game_sys_requirement"

    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), primary_key=True
    )
    os_platform_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[SysRequirementKind] = mapped_column(
        string_enum(SysRequirementKind), primary_key=True
    )
    key: Mapped[SysRequirementKey] = mapped_column(string_enum(SysRequirementKey), primary_key=True)
    value: Mapped[str]


class GameTag(Base):
    """Game tag."""

    __tablename__ = "game_tag"

    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True
    )


class GameVideo(Base):
    """Game video."""

    __tablename__ = "game_video"

    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), primary_key=True
    )
    url: Mapped[str] = mapped_column(primary_key=True)
    provider: Mapped[str]
    video_id: Mapped[str | None]
    name: Mapped[str | None]


class GameAsset(Base):
    """Game asset."""

    __tablename__ = "game_asset"

    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[AssetKind] = mapped_column(string_enum(AssetKind), primary_key=True)
    blob_blake3: Mapped[str] = mapped_column(ForeignKey("asset_blob.blake3"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(default=0)
    visible: Mapped[bool] = mapped_column(default=True)
