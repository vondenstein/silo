import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.game import (
    CompanyRole,
    GameAltName,
    GameCompany,
    GamePlatform,
    GameRating,
    GameReleaseDate,
    GameSerial,
    GameSeries,
    GameTag,
    GameVideo,
    RatingAuthority,
)
from silo.models.platform import Platform
from silo.models.tag import Tag, TagKind
from silo.schemas.game import SerialEntry
from silo.schemas.normalized_metadata import (
    AltNameEntry,
    RatingEntry,
    ReleaseDateEntry,
    VideoEntry,
)

TAG_FIELDS: dict[str, TagKind] = {
    "genres": TagKind.GENRE,
    "themes": TagKind.THEME,
    "tags": TagKind.TAG,
    "engines": TagKind.ENGINE,
    "modes": TagKind.MODE,
}


async def _replace_links(
    session: AsyncSession,
    existing: dict[uuid.UUID, Any],
    desired_ids: list[uuid.UUID],
    make_row: Callable[[uuid.UUID], Any],
) -> None:
    for entity_id in desired_ids:
        if entity_id not in existing:
            session.add(make_row(entity_id))
    keep = set(desired_ids)
    for entity_id, row in existing.items():
        if entity_id not in keep:
            await session.delete(row)


async def _replace_keyed(
    session: AsyncSession,
    existing: dict[Any, Any],
    desired: dict[Any, Any],
    make_row: Callable[[Any, Any], Any],
    update_row: Callable[[Any, Any], None],
) -> None:
    """Insert/update rows to match desired by key; delete rows for absent keys."""
    for key, value in desired.items():
        row = existing.get(key)
        if row is None:
            session.add(make_row(key, value))
        else:
            update_row(row, value)
    for key, row in existing.items():
        if key not in desired:
            await session.delete(row)


async def platform_ids_by_slug(session: AsyncSession, slugs: list[str]) -> dict[str, uuid.UUID]:
    """Seeded platform ids for the slugs (unknown slugs simply absent)."""
    return {
        platform.slug: platform.id
        for platform in await session.scalars(select(Platform).where(Platform.slug.in_(slugs)))
    }


async def set_game_companies(
    session: AsyncSession, game_id: uuid.UUID, role: CompanyRole, company_ids: list[uuid.UUID]
) -> None:
    """Replace the game's company rows for one role."""
    existing = {
        row.company_id: row
        for row in await session.scalars(
            select(GameCompany).where(GameCompany.game_id == game_id, GameCompany.role == role)
        )
    }
    await _replace_links(
        session,
        existing,
        company_ids,
        lambda company_id: GameCompany(game_id=game_id, company_id=company_id, role=role),
    )


async def set_game_series(
    session: AsyncSession, game_id: uuid.UUID, series_ids: list[uuid.UUID]
) -> None:
    """Replace the game's series rows."""
    existing = {
        row.series_id: row
        for row in await session.scalars(select(GameSeries).where(GameSeries.game_id == game_id))
    }
    await _replace_links(
        session,
        existing,
        series_ids,
        lambda series_id: GameSeries(game_id=game_id, series_id=series_id),
    )


async def set_game_tags(
    session: AsyncSession, game_id: uuid.UUID, kind: TagKind, tag_ids: list[uuid.UUID]
) -> None:
    """Replace the game's tag rows for one kind."""
    existing = {
        row.tag_id: row
        for row in await session.scalars(
            select(GameTag)
            .join(Tag, Tag.id == GameTag.tag_id)
            .where(GameTag.game_id == game_id, Tag.kind == kind)
        )
    }
    await _replace_links(
        session, existing, tag_ids, lambda tag_id: GameTag(game_id=game_id, tag_id=tag_id)
    )


async def set_game_platforms(
    session: AsyncSession, game_id: uuid.UUID, platform_ids: list[uuid.UUID]
) -> None:
    """Replace the game's platform rows."""
    existing = {
        row.platform_id: row
        for row in await session.scalars(
            select(GamePlatform).where(GamePlatform.game_id == game_id)
        )
    }
    await _replace_links(
        session,
        existing,
        platform_ids,
        lambda platform_id: GamePlatform(game_id=game_id, platform_id=platform_id),
    )


async def set_game_alt_names(
    session: AsyncSession, game_id: uuid.UUID, entries: list[AltNameEntry]
) -> None:
    """Replace the game's alt-name rows (keyed by name, first entry wins)."""
    desired: dict[str, str | None] = {}
    for entry in entries:
        desired.setdefault(entry.name, entry.comment)
    existing = {
        row.name: row
        for row in await session.scalars(select(GameAltName).where(GameAltName.game_id == game_id))
    }

    def update(row: GameAltName, comment: str | None) -> None:
        row.comment = comment

    await _replace_keyed(
        session,
        existing,
        desired,
        lambda name, comment: GameAltName(game_id=game_id, name=name, comment=comment),
        update,
    )


async def set_game_videos(
    session: AsyncSession, game_id: uuid.UUID, entries: list[VideoEntry]
) -> None:
    """Replace the game's video rows (keyed by url; url-less entries are skipped)."""
    desired: dict[str, VideoEntry] = {}
    for entry in entries:
        if entry.url:
            desired.setdefault(entry.url, entry)
    existing = {
        row.url: row
        for row in await session.scalars(select(GameVideo).where(GameVideo.game_id == game_id))
    }

    def update(row: GameVideo, entry: VideoEntry) -> None:
        row.provider = entry.provider
        row.video_id = entry.video_id
        row.name = entry.name

    await _replace_keyed(
        session,
        existing,
        desired,
        lambda url, entry: GameVideo(
            game_id=game_id,
            url=url,
            provider=entry.provider,
            video_id=entry.video_id,
            name=entry.name,
        ),
        update,
    )


async def set_game_ratings(
    session: AsyncSession, game_id: uuid.UUID, entries: list[RatingEntry]
) -> None:
    """Replace the game's rating rows (keyed by authority, first entry wins)."""
    desired: dict[RatingAuthority, RatingEntry] = {}
    for entry in entries:
        desired.setdefault(entry.authority, entry)
    existing = {
        row.authority: row
        for row in await session.scalars(select(GameRating).where(GameRating.game_id == game_id))
    }

    def update(row: GameRating, entry: RatingEntry) -> None:
        row.value = entry.value
        row.descriptors = entry.descriptors

    await _replace_keyed(
        session,
        existing,
        desired,
        lambda authority, entry: GameRating(
            game_id=game_id, authority=authority, value=entry.value, descriptors=entry.descriptors
        ),
        update,
    )


async def set_game_release_dates(
    session: AsyncSession, game_id: uuid.UUID, entries: list[ReleaseDateEntry]
) -> None:
    """Replace the game's release-date rows (keyed by platform slug, first entry wins;
    unknown slugs are skipped)."""
    by_slug: dict[str, ReleaseDateEntry] = {}
    for entry in entries:
        by_slug.setdefault(entry.platform, entry)
    ids = await platform_ids_by_slug(session, list(by_slug))
    desired = {ids[slug]: entry.date for slug, entry in by_slug.items() if slug in ids}
    if entries and not desired:
        # All-unknown slugs must not read as "clear" (R6); an empty input still clears.
        return
    existing = {
        row.platform_id: row
        for row in await session.scalars(
            select(GameReleaseDate).where(GameReleaseDate.game_id == game_id)
        )
    }

    def update(row: GameReleaseDate, when: Any) -> None:
        row.date = when

    await _replace_keyed(
        session,
        existing,
        desired,
        lambda platform_id, when: GameReleaseDate(
            game_id=game_id, platform_id=platform_id, date=when
        ),
        update,
    )


async def set_game_serials(
    session: AsyncSession, game_id: uuid.UUID, entries: list[SerialEntry]
) -> None:
    """Replace the game's serial rows (keyed by value, first entry wins)."""
    desired: dict[str, str | None] = {}
    for entry in entries:
        desired.setdefault(entry.value, entry.comment)
    existing = {
        row.value: row
        for row in await session.scalars(select(GameSerial).where(GameSerial.game_id == game_id))
    }

    def update(row: GameSerial, comment: str | None) -> None:
        row.comment = comment

    await _replace_keyed(
        session,
        existing,
        desired,
        lambda value, comment: GameSerial(game_id=game_id, value=value, comment=comment),
        update,
    )
