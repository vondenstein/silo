import uuid
from datetime import date

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.artifact import Artifact
from silo.models.asset import AssetKind
from silo.models.company import Company
from silo.models.field_lock import FieldLock
from silo.models.file import File
from silo.models.game import (
    CompanyRole,
    Game,
    GameAltName,
    GameAsset,
    GameCompany,
    GameExternalIdentity,
    GameMetadata,
    GamePlatform,
    GameRating,
    GameReleaseDate,
    GameSerial,
    GameSeries,
    GameTag,
    GameType,
    GameVideo,
    WrapperKind,
)
from silo.models.library import Library
from silo.models.metadata_source import MetadataSource
from silo.models.platform import Platform, PlatformFamily
from silo.models.series import Series
from silo.models.tag import Tag, TagKind
from silo.schemas.game import (
    ArtifactOut,
    EntityOut,
    ExternalIdentityOut,
    FileOut,
    GameAssetsOut,
    GameDetail,
    PlatformOut,
    SerialEntry,
    VideoOut,
)
from silo.schemas.game import Game as GameSchema
from silo.schemas.normalized_metadata import AltNameEntry, RatingEntry, ReleaseDateEntry
from silo.services.assets import asset_url
from silo.services.identification import matches_for_files


class UnknownLibraryError(Exception):
    """The target library does not exist."""

    def __init__(self, library_id: uuid.UUID) -> None:
        super().__init__(f"library {library_id} not found")


class DuplicateSlugError(Exception):
    """The slug is already taken within the library."""

    def __init__(self, slug: str, library_id: uuid.UUID) -> None:
        super().__init__(f"game with slug '{slug}' already exists in library {library_id}")


def build_game_schema(
    game: Game,
    metadata: GameMetadata,
    cover_url: str | None = None,
    landscape_url: str | None = None,
) -> GameSchema:
    """Assemble the Game response from its two rows."""
    return GameSchema(
        cover_url=cover_url,
        landscape_url=landscape_url,
        id=game.id,
        library_id=game.library_id,
        slug=game.slug,
        origin=game.origin,
        preferred_source_id=game.preferred_source_id,
        created_at=game.created_at,
        updated_at=game.updated_at,
        title=metadata.title,
        sort_title=metadata.sort_title,
        description_short=metadata.description_short,
        description_full=metadata.description_full,
        first_release_date=metadata.first_release_date,
        wrapper=metadata.wrapper,
        game_type=metadata.game_type,
        resolved_at=metadata.resolved_at,
    )


async def create_game_with_metadata(
    session: AsyncSession,
    *,
    library_id: uuid.UUID,
    slug: str,
    title: str,
    sort_title: str | None = None,
    description_short: str | None = None,
    description_full: str | None = None,
    first_release_date: date | None = None,
    wrapper: WrapperKind | None = None,
    game_type: GameType | None = None,
) -> tuple[Library, Game, GameMetadata]:
    """Create a game + metadata row; raises UnknownLibraryError / DuplicateSlugError."""
    library = await session.get(Library, library_id)
    if library is None:
        raise UnknownLibraryError(library_id)
    game = Game(library_id=library_id, slug=slug)
    session.add(game)
    try:
        await session.flush()
    except IntegrityError as exc:
        # A racing library deletion surfaces as an FK failure, not a slug clash.
        if "FOREIGN KEY constraint failed" in str(exc.orig):
            raise UnknownLibraryError(library_id) from None
        raise DuplicateSlugError(slug, library_id) from None
    metadata = GameMetadata(
        game_id=game.id,
        title=title,
        sort_title=sort_title,
        description_short=description_short,
        description_full=description_full,
        first_release_date=first_release_date,
        wrapper=wrapper,
        game_type=game_type,
    )
    session.add(metadata)
    await session.flush()
    return library, game, metadata


async def art_urls(
    session: AsyncSession, game_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[AssetKind, str]]:
    """First visible cover/landscape per game, as content-addressed URLs."""
    if not game_ids:
        return {}
    rows = (
        await session.execute(
            select(GameAsset.game_id, GameAsset.kind, GameAsset.blob_blake3)
            .where(
                GameAsset.game_id.in_(game_ids),
                GameAsset.kind.in_((AssetKind.COVER, AssetKind.LANDSCAPE)),
                GameAsset.visible.is_(True),
            )
            .order_by(GameAsset.ordinal)
        )
    ).all()
    urls: dict[uuid.UUID, dict[AssetKind, str]] = {}
    for game_id, kind, blob in rows:
        urls.setdefault(game_id, {}).setdefault(kind, asset_url(blob))
    return urls


async def load_artifacts(session: AsyncSession, game_id: uuid.UUID) -> list[ArtifactOut]:
    """The game's artifacts with files and derived signature matches."""
    artifacts = (
        await session.scalars(
            select(Artifact)
            .where(Artifact.game_id == game_id)
            .order_by(Artifact.created_at, Artifact.id)
        )
    ).all()
    if not artifacts:
        return []
    files = (
        await session.scalars(
            select(File)
            .where(File.artifact_id.in_([artifact.id for artifact in artifacts]))
            .order_by(File.created_at, File.id)
        )
    ).all()
    matches = await matches_for_files(session, list(files))
    platform_slugs = {row.id: row.slug for row in await session.scalars(select(Platform))}
    return [
        ArtifactOut(
            id=artifact.id,
            kind=artifact.kind,
            platform_slug=(
                platform_slugs[artifact.platform_id] if artifact.platform_id is not None else None
            ),
            language=artifact.language,
            version=artifact.version,
            status=artifact.status,
            total_size=artifact.total_size,
            name=artifact.name,
            files=[
                FileOut(
                    id=file.id,
                    relative_path=file.relative_path,
                    size=file.size,
                    blake3=file.blake3,
                    matches=matches.get(file.id, []),
                )
                for file in files
                if file.artifact_id == artifact.id
            ],
        )
        for artifact in artifacts
    ]


class GameDetailCollections(BaseModel):
    """The collection half of GameDetail (typed loader output)."""

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


async def load_detail_collections(
    session: AsyncSession, game_id: uuid.UUID
) -> GameDetailCollections:
    """The game's resolved collections, vocabulary entities, and identities."""
    by_role: dict[CompanyRole, list[EntityOut]] = {role: [] for role in CompanyRole}
    for role, company in (
        await session.execute(
            select(GameCompany.role, Company)
            .join(Company, Company.id == GameCompany.company_id)
            .where(GameCompany.game_id == game_id)
            .order_by(Company.name)
        )
    ).all():
        by_role[role].append(EntityOut(slug=company.slug, name=company.name))
    series = [
        EntityOut(slug=row.slug, name=row.name)
        for row in await session.scalars(
            select(Series)
            .join(GameSeries, GameSeries.series_id == Series.id)
            .where(GameSeries.game_id == game_id)
            .order_by(Series.name)
        )
    ]
    tags_by_kind: dict[TagKind, list[EntityOut]] = {kind: [] for kind in TagKind}
    for tag in await session.scalars(
        select(Tag)
        .join(GameTag, GameTag.tag_id == Tag.id)
        .where(GameTag.game_id == game_id)
        .order_by(Tag.name)
    ):
        tags_by_kind[tag.kind].append(EntityOut(slug=tag.slug, name=tag.name))
    platforms = [
        PlatformOut(slug=platform.slug, name=platform.name, family_slug=family_slug)
        for platform, family_slug in (
            await session.execute(
                select(Platform, PlatformFamily.slug)
                .join(PlatformFamily, PlatformFamily.id == Platform.family_id)
                .join(GamePlatform, GamePlatform.platform_id == Platform.id)
                .where(GamePlatform.game_id == game_id)
                .order_by(Platform.slug)
            )
        ).all()
    ]
    release_dates = [
        ReleaseDateEntry(platform=slug, date=released)
        for slug, released in (
            await session.execute(
                select(Platform.slug, GameReleaseDate.date)
                .join(GameReleaseDate, GameReleaseDate.platform_id == Platform.id)
                .where(GameReleaseDate.game_id == game_id)
                .order_by(Platform.slug)
            )
        ).all()
    ]
    ratings = [
        RatingEntry(authority=row.authority, value=row.value, descriptors=row.descriptors)
        for row in await session.scalars(
            select(GameRating).where(GameRating.game_id == game_id).order_by(GameRating.authority)
        )
    ]
    alt_names = [
        AltNameEntry(name=row.name, comment=row.comment)
        for row in await session.scalars(
            select(GameAltName).where(GameAltName.game_id == game_id).order_by(GameAltName.name)
        )
    ]
    videos = [
        VideoOut(provider=row.provider, url=row.url, video_id=row.video_id, name=row.name)
        for row in await session.scalars(
            select(GameVideo).where(GameVideo.game_id == game_id).order_by(GameVideo.url)
        )
    ]
    serials = [
        SerialEntry(value=row.value, comment=row.comment)
        for row in await session.scalars(
            select(GameSerial).where(GameSerial.game_id == game_id).order_by(GameSerial.value)
        )
    ]
    external_identities = [
        ExternalIdentityOut(source_slug=slug, external_id=external_id)
        for slug, external_id in (
            await session.execute(
                select(MetadataSource.slug, GameExternalIdentity.external_id)
                .join(GameExternalIdentity, GameExternalIdentity.source_id == MetadataSource.id)
                .where(GameExternalIdentity.game_id == game_id)
                .order_by(MetadataSource.slug)
            )
        ).all()
    ]
    return GameDetailCollections(
        developers=by_role[CompanyRole.DEVELOPER],
        publishers=by_role[CompanyRole.PUBLISHER],
        series=series,
        genres=tags_by_kind[TagKind.GENRE],
        themes=tags_by_kind[TagKind.THEME],
        tags=tags_by_kind[TagKind.TAG],
        engines=tags_by_kind[TagKind.ENGINE],
        modes=tags_by_kind[TagKind.MODE],
        platforms=platforms,
        release_dates=release_dates,
        ratings=ratings,
        alt_names=alt_names,
        videos=videos,
        serials=serials,
        external_identities=external_identities,
    )


async def load_game_detail(session: AsyncSession, game: Game, metadata: GameMetadata) -> GameDetail:
    """Assemble the full GameDetail response."""
    locks = list(
        await session.scalars(select(FieldLock.field_key).where(FieldLock.game_id == game.id))
    )
    asset_rows = await session.scalars(
        select(GameAsset)
        .where(GameAsset.game_id == game.id, GameAsset.visible.is_(True))
        .order_by(GameAsset.ordinal)
    )
    urls_by_kind: dict[AssetKind, list[str]] = {}
    for row in asset_rows:
        urls_by_kind.setdefault(row.kind, []).append(asset_url(row.blob_blake3))

    def first_url(kind: AssetKind) -> str | None:
        urls = urls_by_kind.get(kind)
        return urls[0] if urls else None

    base = build_game_schema(
        game,
        metadata,
        cover_url=first_url(AssetKind.COVER),
        landscape_url=first_url(AssetKind.LANDSCAPE),
    )
    collections = await load_detail_collections(session, game.id)
    # The base spread is parent→subclass of the same schema family (drift-proof);
    # the collection half maps explicitly so a field mismatch is a type error.
    return GameDetail(
        **base.model_dump(),
        locks=locks,
        artifacts=await load_artifacts(session, game.id),
        assets=GameAssetsOut(screenshots=urls_by_kind.get(AssetKind.SCREENSHOT) or []),
        developers=collections.developers,
        publishers=collections.publishers,
        series=collections.series,
        genres=collections.genres,
        themes=collections.themes,
        tags=collections.tags,
        engines=collections.engines,
        modes=collections.modes,
        platforms=collections.platforms,
        release_dates=collections.release_dates,
        ratings=collections.ratings,
        alt_names=collections.alt_names,
        videos=collections.videos,
        serials=collections.serials,
        external_identities=collections.external_identities,
    )
