from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from silo.models.asset import AssetKind
from silo.models.game import GameType, RatingAuthority, WrapperKind


class EntityRef(BaseModel):
    """One source's reference to a vocabulary entity (uid = its stable id there)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    uid: str | None = None


class ReleaseDateEntry(BaseModel):
    """Per-platform release date."""

    model_config = ConfigDict(extra="forbid")

    platform: str = Field(min_length=1, max_length=255)
    date: date


class RatingEntry(BaseModel):
    """One authority's age rating."""

    model_config = ConfigDict(extra="forbid")

    authority: RatingAuthority
    value: str = Field(min_length=1, max_length=255)
    descriptors: list[str] = []


class AltNameEntry(BaseModel):
    """Alternative display name."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    comment: str | None = Field(default=None, max_length=255)


class VideoEntry(BaseModel):
    """External video reference."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    url: str | None = None
    video_id: str | None = None
    name: str | None = None


class AssetEntry(BaseModel):
    """One downloadable asset URL."""

    model_config = ConfigDict(extra="forbid")

    kind: AssetKind
    url: str


class NormalizedMetadata(BaseModel):
    """One source's canonical-shaped contribution (metadata_record.normalized).
    Strict — normalizer key changes ride a renormalize (CR-178)."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    sort_title: str | None = None
    description_short: str | None = None
    description_full: str | None = None
    first_release_date: date | None = None
    wrapper: WrapperKind | None = None
    game_type: GameType | None = None

    developers: list[EntityRef] | None = None
    publishers: list[EntityRef] | None = None
    series: list[EntityRef] | None = None
    genres: list[EntityRef] | None = None
    themes: list[EntityRef] | None = None
    tags: list[EntityRef] | None = None
    engines: list[EntityRef] | None = None
    modes: list[EntityRef] | None = None
    platforms: list[str] | None = None
    release_dates: list[ReleaseDateEntry] | None = None
    ratings: list[RatingEntry] | None = None
    alt_names: list[AltNameEntry] | None = None
    videos: list[VideoEntry] | None = None
    assets: list[AssetEntry] | None = None
