import enum
import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from silo.models.base import Base, string_enum


class FieldKey(enum.StrEnum):
    # scalars
    TITLE = "title"
    SORT_TITLE = "sort_title"
    DESCRIPTION_SHORT = "description_short"
    DESCRIPTION_FULL = "description_full"
    FIRST_RELEASE_DATE = "first_release_date"
    WRAPPER = "wrapper"
    GAME_TYPE = "game_type"
    # collection fields
    DEVELOPERS = "developers"
    PUBLISHERS = "publishers"
    SERIES = "series"
    GENRES = "genres"
    THEMES = "themes"
    TAGS = "tags"
    ENGINES = "engines"
    MODES = "modes"
    PLATFORMS = "platforms"
    RELEASE_DATES = "release_dates"
    RATINGS = "ratings"
    SYS_REQUIREMENTS = "sys_requirements"
    ALT_NAMES = "alt_names"
    VIDEOS = "videos"
    # asset kinds (values match AssetKind)
    COVER = "cover"
    BACKGROUND = "background"
    LANDSCAPE = "landscape"
    LOGO = "logo"
    ICON = "icon"
    SCREENSHOT = "screenshot"
    VIDEO_THUMBNAIL = "video_thumbnail"


class FieldLock(Base):
    """Field lock."""

    __tablename__ = "field_lock"

    game_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), primary_key=True
    )
    field_key: Mapped[FieldKey] = mapped_column(string_enum(FieldKey), primary_key=True)
