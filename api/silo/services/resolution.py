import uuid
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.asset import AssetBlob, AssetKind, SourceAsset
from silo.models.base import utcnow
from silo.models.field_lock import FieldKey, FieldLock
from silo.models.game import (
    CompanyRole,
    Game,
    GameAsset,
    GameExternalIdentity,
    GameMetadata,
    GameOrigin,
)
from silo.models.metadata_record import MetadataRecord
from silo.models.metadata_source import MetadataSource
from silo.schemas.normalized_metadata import NormalizedMetadata
from silo.services.entities import resolve_company_refs, resolve_series_refs, resolve_tag_refs
from silo.services.game_collections import (
    TAG_FIELDS,
    platform_ids_by_slug,
    set_game_alt_names,
    set_game_companies,
    set_game_platforms,
    set_game_ratings,
    set_game_release_dates,
    set_game_series,
    set_game_tags,
    set_game_videos,
)

_ORIGIN_PREFERRED_SOURCE: dict[GameOrigin, str] = {
    GameOrigin.GOG_IMPORT: "gog",
}

# game_metadata columns only — collection fields resolve via their association tables.
_SCALAR_FIELDS = [
    field for field in NormalizedMetadata.model_fields if field in GameMetadata.__table__.columns
]

_Pairs = list[tuple[MetadataRecord, NormalizedMetadata]]


def _preferred_source_id(game: Game, sources: dict[uuid.UUID, MetadataSource]) -> uuid.UUID | None:
    if game.preferred_source_id is not None:
        return game.preferred_source_id
    slug = _ORIGIN_PREFERRED_SOURCE.get(game.origin) if game.origin is not None else None
    return next((source.id for source in sources.values() if source.slug == slug), None)


def _order_records(
    records: list[MetadataRecord],
    preferred_id: uuid.UUID | None,
    sources: dict[uuid.UUID, MetadataSource],
) -> list[MetadataRecord]:
    return sorted(
        records,
        key=lambda record: (record.source_id != preferred_id, sources[record.source_id].priority),
    )


def _winner(pairs: _Pairs, field: str) -> tuple[MetadataRecord | None, Any]:
    """First record (preference order) with a non-empty value for the field."""
    for record, normalized in pairs:
        value = getattr(normalized, field)
        if value:
            return record, value
    return None, None


async def _materialize_collections(
    session: AsyncSession, game: Game, pairs: _Pairs, locks: set[FieldKey]
) -> None:
    """§7: set-collections = winner-set replace; keyed = union-by-key (empty → keep, R6)."""
    for field, role in (
        ("developers", CompanyRole.DEVELOPER),
        ("publishers", CompanyRole.PUBLISHER),
    ):
        if FieldKey(field) in locks:
            continue
        record, refs = _winner(pairs, field)
        if record is None:
            continue
        ids = await resolve_company_refs(session, refs, record.source_id)
        await set_game_companies(session, game.id, role, ids)

    if FieldKey.SERIES not in locks:
        record, refs = _winner(pairs, "series")
        if record is not None:
            ids = await resolve_series_refs(session, refs, record.source_id)
            await set_game_series(session, game.id, ids)

    for field, kind in TAG_FIELDS.items():
        if FieldKey(field) in locks:
            continue
        record, refs = _winner(pairs, field)
        if record is None:
            continue
        ids = await resolve_tag_refs(session, refs, record.source_id, kind)
        await set_game_tags(session, game.id, kind, ids)

    if FieldKey.PLATFORMS not in locks:
        record, slugs = _winner(pairs, "platforms")
        if record is not None:
            by_slug = await platform_ids_by_slug(session, slugs)
            ids = list(dict.fromkeys(by_slug[slug] for slug in slugs if slug in by_slug))
            # All-unknown slugs must not read as "clear" (R6).
            if ids:
                await set_game_platforms(session, game.id, ids)

    if FieldKey.ALT_NAMES not in locks:
        record, entries = _winner(pairs, "alt_names")
        if record is not None:
            await set_game_alt_names(session, game.id, entries)

    if FieldKey.VIDEOS not in locks:
        # Usability joins the winner test: url-less entries can't render, so an
        # all-url-less source falls through to the next; no usable winner keeps
        # current rows (R6).
        for _, normalized in pairs:
            usable = [entry for entry in normalized.videos or [] if entry.url]
            if usable:
                await set_game_videos(session, game.id, usable)
                break

    # Keyed collections: concatenation in preference order + first-wins-per-key in the
    # setters = union-by-key with the preferred source breaking same-key conflicts.
    if FieldKey.RATINGS not in locks:
        ratings = [entry for _, normalized in pairs for entry in normalized.ratings or []]
        if ratings:
            await set_game_ratings(session, game.id, ratings)

    if FieldKey.RELEASE_DATES not in locks:
        dates = [entry for _, normalized in pairs for entry in normalized.release_dates or []]
        if dates:
            await set_game_release_dates(session, game.id, dates)


# Kinds displayed one-at-a-time: the winner's picks rank by resolution (highest first).
# Screenshots/video thumbnails keep the source's narrative order.
_SINGLETON_KINDS = {
    AssetKind.COVER,
    AssetKind.BACKGROUND,
    AssetKind.LANDSCAPE,
    AssetKind.LOGO,
    AssetKind.ICON,
}


def _area(blob: AssetBlob | None) -> int:
    if blob is None or blob.width is None or blob.height is None:
        return 0
    return blob.width * blob.height


async def _materialize_assets(
    session: AsyncSession, game: Game, ordered: list[MetadataRecord], locks: set[FieldKey]
) -> None:
    """Materialize the winning source's picks per kind (insert-if-absent, never delete)."""
    if not ordered:
        return
    source_assets = await session.scalars(
        select(SourceAsset).where(
            SourceAsset.metadata_record_id.in_([record.id for record in ordered])
        )
    )
    by_record_kind: dict[tuple[uuid.UUID, AssetKind], list[SourceAsset]] = {}
    for row in source_assets:
        by_record_kind.setdefault((row.metadata_record_id, row.kind), []).append(row)
    if not by_record_kind:
        return

    blob_ids = {row.blob_blake3 for rows in by_record_kind.values() for row in rows}
    blobs = {
        blob.blake3: blob
        for blob in await session.scalars(select(AssetBlob).where(AssetBlob.blake3.in_(blob_ids)))
    }
    existing = {
        (row.kind, row.blob_blake3): row
        for row in await session.scalars(select(GameAsset).where(GameAsset.game_id == game.id))
    }
    for kind in AssetKind:
        if FieldKey(kind) in locks:
            continue
        winner = next(
            (
                by_record_kind[(record.id, kind)]
                for record in ordered
                if (record.id, kind) in by_record_kind
            ),
            None,
        )
        if winner is None:
            continue
        winner_blobs = {row.blob_blake3 for row in winner}
        # Singletons re-rank by resolution (the rank becomes the ordinal);
        # narrative kinds keep the source's own order and ordinals.
        if kind in _SINGLETON_KINDS:
            ranked = sorted(winner, key=lambda row: -_area(blobs.get(row.blob_blake3)))
            placements = list(enumerate(ranked))
        else:
            placements = [(row.ordinal, row) for row in sorted(winner, key=lambda row: row.ordinal)]
        for ordinal, row in placements:
            current = existing.get((kind, row.blob_blake3))
            if current is None:
                current = GameAsset(
                    game_id=game.id, kind=kind, blob_blake3=row.blob_blake3, ordinal=ordinal
                )
                session.add(current)
                existing[(kind, row.blob_blake3)] = current
            else:
                current.ordinal = ordinal
                current.visible = True
        # Losing sources' picks are demoted, never deleted.
        for (existing_kind, blob), current in existing.items():
            if existing_kind == kind and blob not in winner_blobs:
                current.visible = False


async def resolve_game_metadata(session: AsyncSession, game: Game) -> None:
    """§7 resolution: preferred source first, priority fallback, locks respected,
    empty never overwrites (R6)."""
    metadata = game.game_metadata

    locks = set(
        await session.scalars(select(FieldLock.field_key).where(FieldLock.game_id == game.id))
    )
    records = list(
        await session.scalars(
            select(MetadataRecord)
            .join(
                GameExternalIdentity,
                and_(
                    GameExternalIdentity.source_id == MetadataRecord.source_id,
                    GameExternalIdentity.external_id == MetadataRecord.external_id,
                ),
            )
            .where(GameExternalIdentity.game_id == game.id)
        )
    )
    sources = {source.id: source for source in await session.scalars(select(MetadataSource))}

    ordered = _order_records(records, _preferred_source_id(game, sources), sources)
    parsed = [NormalizedMetadata.model_validate(record.normalized) for record in ordered]

    # Scalars: first non-empty value in preference order wins (R6 — empty never clears).
    for field in _SCALAR_FIELDS:
        if FieldKey(field) in locks:
            continue
        for normalized in parsed:
            value = getattr(normalized, field)
            if value is not None and value != "":
                setattr(metadata, field, value)
                break

    await _materialize_collections(session, game, list(zip(ordered, parsed, strict=True)), locks)
    await _materialize_assets(session, game, ordered, locks)
    metadata.resolved_at = utcnow()
    await session.flush()
