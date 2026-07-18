import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.json_schema import SkipJsonSchema

from silo.models.artifact import ArtifactKind, ArtifactStatus
from silo.models.field_lock import FieldKey
from silo.models.game import GameOrigin, GameType, WrapperKind
from silo.schemas.common import EntityName, Slug, UTCDateTime
from silo.schemas.identification import SignatureMatchOut
from silo.schemas.normalized_metadata import AltNameEntry, RatingEntry, ReleaseDateEntry


class Game(BaseModel):
    """Game (list shape)."""

    model_config = ConfigDict(from_attributes=True)

    # identity
    id: uuid.UUID
    library_id: uuid.UUID
    slug: str
    origin: GameOrigin | None
    preferred_source_id: uuid.UUID | None
    created_at: UTCDateTime
    updated_at: UTCDateTime

    # canonical scalars
    title: str
    sort_title: str | None
    description_short: str | None
    description_full: str | None
    first_release_date: date | None
    wrapper: WrapperKind | None
    game_type: GameType | None
    resolved_at: UTCDateTime | None

    # resolved display assets (content-addressed URLs)
    cover_url: str | None
    landscape_url: str | None


class FileOut(BaseModel):
    """Stored file (matches = its derived identification matches)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    relative_path: str | None
    size: int | None
    blake3: str | None
    matches: list[SignatureMatchOut] = []


class ArtifactOut(BaseModel):
    """Artifact with its files."""

    id: uuid.UUID
    kind: ArtifactKind
    platform_slug: str | None
    language: str | None
    version: str | None
    status: ArtifactStatus
    total_size: int | None
    name: str | None
    files: list[FileOut]


class GameAssetsOut(BaseModel):
    """Resolved display assets beyond the flat cover/landscape pair."""

    screenshots: list[str]


class EntityOut(BaseModel):
    """Vocabulary entity reference."""

    slug: str
    name: str


class PlatformOut(BaseModel):
    """Platform with its family."""

    slug: str
    name: str
    family_slug: str


class VideoOut(BaseModel):
    """External video."""

    provider: str
    url: str
    video_id: str | None
    name: str | None


class VideoPut(BaseModel):
    """Video entry as writable via PATCH (a URL is required)."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=2048)
    video_id: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, max_length=255)


class SerialEntry(BaseModel):
    """Serial number row."""

    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, max_length=255)
    comment: str | None = Field(default=None, max_length=255)


class ExternalIdentityOut(BaseModel):
    """External catalog identity."""

    source_slug: str
    external_id: str


class IdentityPut(BaseModel):
    """Set a game's identity in one external catalog."""

    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=255)


class GameDetail(Game):
    """Full game detail."""

    locks: list[FieldKey]
    artifacts: list[ArtifactOut]
    assets: GameAssetsOut
    developers: list[EntityOut]
    publishers: list[EntityOut]
    series: list[EntityOut]
    genres: list[EntityOut]
    themes: list[EntityOut]
    tags: list[EntityOut]
    engines: list[EntityOut]
    modes: list[EntityOut]
    platforms: list[PlatformOut]
    release_dates: list[ReleaseDateEntry]
    ratings: list[RatingEntry]
    alt_names: list[AltNameEntry]
    videos: list[VideoOut]
    serials: list[SerialEntry]
    external_identities: list[ExternalIdentityOut]


class AssetCandidateOut(BaseModel):
    """One candidate image (visible/ordinal null until it is a game_asset row)."""

    blake3: str
    url: str
    mime: str
    size: int
    width: int | None
    height: int | None
    source_slugs: list[str]
    visible: bool | None
    ordinal: int | None


class GameAssetCandidates(BaseModel):
    """Candidate pool per asset kind, with current selection state."""

    cover: list[AssetCandidateOut]
    background: list[AssetCandidateOut]
    landscape: list[AssetCandidateOut]
    logo: list[AssetCandidateOut]
    icon: list[AssetCandidateOut]
    screenshot: list[AssetCandidateOut]
    video_thumbnail: list[AssetCandidateOut]


class AssetKindPut(BaseModel):
    """Ordered visible set for one asset kind."""

    model_config = ConfigDict(extra="forbid")

    blobs: list[str]


class GameCreate(BaseModel):
    """Game create request."""

    model_config = ConfigDict(extra="forbid")

    library_id: uuid.UUID
    slug: Slug
    title: str = Field(min_length=1, max_length=255)
    sort_title: str | None = Field(default=None, max_length=255)
    description_short: str | None = Field(default=None, max_length=1_000)
    description_full: str | None = Field(default=None, max_length=50_000)
    first_release_date: date | None = None
    wrapper: WrapperKind | None = None
    game_type: GameType | None = None


class GamePatch(BaseModel):
    """Game patch request. Collections are replace-arrays: omit = untouched,
    [] = clear; the fields typed without null reject explicit null."""

    model_config = ConfigDict(extra="forbid")

    title: str | SkipJsonSchema[None] = Field(default=None, min_length=1, max_length=255)
    sort_title: str | None = Field(default=None, max_length=255)
    description_short: str | None = Field(default=None, max_length=1_000)
    description_full: str | None = Field(default=None, max_length=50_000)
    first_release_date: date | None = None
    wrapper: WrapperKind | None = None
    game_type: GameType | None = None
    preferred_source_id: uuid.UUID | None = None
    library_id: uuid.UUID | SkipJsonSchema[None] = None
    developers: list[EntityName] | SkipJsonSchema[None] = None
    publishers: list[EntityName] | SkipJsonSchema[None] = None
    series: list[EntityName] | SkipJsonSchema[None] = None
    genres: list[EntityName] | SkipJsonSchema[None] = None
    themes: list[EntityName] | SkipJsonSchema[None] = None
    tags: list[EntityName] | SkipJsonSchema[None] = None
    engines: list[EntityName] | SkipJsonSchema[None] = None
    modes: list[EntityName] | SkipJsonSchema[None] = None
    platforms: list[EntityName] | SkipJsonSchema[None] = None
    release_dates: list[ReleaseDateEntry] | SkipJsonSchema[None] = None
    ratings: list[RatingEntry] | SkipJsonSchema[None] = None
    alt_names: list[AltNameEntry] | SkipJsonSchema[None] = None
    videos: list[VideoPut] | SkipJsonSchema[None] = None
    serials: list[SerialEntry] | SkipJsonSchema[None] = None

    @field_validator(
        "title",
        "library_id",
        "developers",
        "publishers",
        "series",
        "genres",
        "themes",
        "tags",
        "engines",
        "modes",
        "platforms",
        "release_dates",
        "ratings",
        "alt_names",
        "videos",
        "serials",
        mode="before",
    )
    @classmethod
    def prevent_none(cls, v: object) -> object:
        if v is None:
            raise ValueError("cannot be null")
        return v
