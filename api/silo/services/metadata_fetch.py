import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, NamedTuple

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.asset import AssetKind, SourceAsset
from silo.models.base import utcnow
from silo.models.game import Game, GameExternalIdentity
from silo.models.metadata_record import MetadataRecord
from silo.models.metadata_source import MetadataSource
from silo.schemas.job import JobStage, JobStageStatus
from silo.schemas.metadata_source import SearchCandidateOut
from silo.schemas.normalized_metadata import AssetEntry, NormalizedMetadata
from silo.services.assets import store_asset_blob
from silo.services.resolution import resolve_game_metadata
from silo.sources import gog, igdb, steam
from silo.sources.client import USER_AGENT

ProgressHook = Callable[[list[JobStage]], Awaitable[None]]

# Stage group for per-source fetches — the fetch_metadata handler keys success
# logic off it, so it is contract, not just display.
METADATA_GROUP = "Metadata"

_ASSET_LABELS = {
    AssetKind.COVER: "Cover",
    AssetKind.BACKGROUND: "Background",
    AssetKind.LANDSCAPE: "Landscape",
    AssetKind.LOGO: "Logo",
    AssetKind.ICON: "Icon",
    AssetKind.SCREENSHOT: "Screenshots",
    AssetKind.VIDEO_THUMBNAIL: "Video thumbnails",
}


async def _download_asset(client: httpx.AsyncClient, url: str) -> tuple[bytes, str]:
    """Download an asset; returns (bytes, mime)."""
    resp = await client.get(url)
    resp.raise_for_status()
    mime = resp.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
    return resp.content, mime


class SourceSpec(NamedTuple):
    family: str
    fetch: Callable[[Any, str], Awaitable[dict[str, Any] | None]]
    normalize: Callable[[dict[str, Any]], dict[str, Any]]
    api_version: str
    uids: Callable[[dict[str, Any]], dict[str, str]] | None = None
    discover: Callable[[Any, dict[str, GameExternalIdentity]], Awaitable[str | None]] | None = None
    search: Callable[[Any, str], Awaitable[list[dict[str, Any]]]] | None = None


async def _discover_igdb(client: Any, by_slug: dict[str, GameExternalIdentity]) -> str | None:
    """IGDB id via the external_games reverse lookup (gog uid first, then steam)."""
    for slug, external_source in (
        ("gog", igdb.EXTERNAL_SOURCE_GOG),
        ("steam", igdb.EXTERNAL_SOURCE_STEAM),
    ):
        identity = by_slug.get(slug)
        if identity is not None:
            found = await client.discover(external_source, identity.external_id)
            if found is not None:
                return str(found)
    return None


# Late-bound: client methods resolve at call time so class-level patches apply.
_SOURCES: dict[str, SourceSpec] = {
    "gog": SourceSpec(
        family="gog",
        fetch=lambda client, eid: client.product(int(eid)),
        normalize=gog.normalize_galaxy,
        api_version="galaxy-products",
    ),
    "gog_store": SourceSpec(
        family="gog",
        fetch=lambda client, eid: client.product_v2(int(eid)),
        normalize=gog.normalize_store,
        api_version="store-v2-games",
    ),
    "gog_gamesdb": SourceSpec(
        family="gog",
        fetch=lambda client, eid: client.gamesdb_release(int(eid)),
        normalize=gog.normalize_gamesdb,
        api_version="gamesdb-external-releases",
        uids=gog.uids,
    ),
    "igdb": SourceSpec(
        family="igdb",
        fetch=lambda client, eid: client.game(int(eid)),
        normalize=igdb.normalize,
        api_version="v4-games",
        uids=igdb.uids,
        discover=_discover_igdb,
        search=lambda client, term: igdb.search_candidates(client, term),
    ),
    "steam": SourceSpec(
        family="steam",
        fetch=lambda client, eid: client.appdetails(int(eid)),
        normalize=steam.normalize,
        api_version="storefront-appdetails",
    ),
}


def source_normalizers() -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
    """Registry slug → normalize (offline re-normalization from stored raw payloads)."""
    return {slug: spec.normalize for slug, spec in _SOURCES.items()}


def source_search_available(slug: str) -> bool:
    """Whether the source implements a catalog search."""
    spec = _SOURCES.get(slug)
    return spec is not None and spec.search is not None


async def search_source(
    session: AsyncSession, slug: str, term: str
) -> list[SearchCandidateOut] | None:
    """Search a source's catalog; None when the family client is unconfigured."""
    spec = _SOURCES[slug]
    assert spec.search is not None
    client = await _FAMILY_CLIENTS[spec.family](session)
    if client is None:
        return None
    async with client:
        # The one validation at the adapter edge — everything downstream is typed.
        return [
            SearchCandidateOut.model_validate(candidate)
            for candidate in await spec.search(client, term)
        ]


async def _gog_family_client(session: AsyncSession) -> gog.GogClient | None:
    try:
        token = await gog.fresh_access_token(session)
    except gog.GogNotConnectedError:
        return None
    interval = await gog.request_interval(session)
    # Persists a rotated refresh token AND releases the write txn before any
    # network I/O (report_progress writes from a second connection).
    await session.commit()
    return gog.GogClient(token, request_interval_ms=interval)


async def _igdb_family_client(session: AsyncSession) -> igdb.IgdbClient | None:
    try:
        client_id, client_secret = await igdb.credentials(session)
    except igdb.IgdbNotConfiguredError:
        return None
    token = await igdb.app_token(client_id, client_secret)
    interval = await igdb.request_interval(session)
    return igdb.IgdbClient(client_id, token, request_interval_ms=interval)


async def _steam_family_client(session: AsyncSession) -> steam.SteamClient:
    return steam.SteamClient(request_interval_ms=await steam.request_interval(session))


_FAMILY_CLIENTS = {
    "gog": _gog_family_client,
    "igdb": _igdb_family_client,
    "steam": _steam_family_client,
}


async def upsert_metadata_record(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    external_id: str,
    api_version: str,
    raw_payload: dict[str, Any],
    normalized: dict[str, Any],
) -> MetadataRecord:
    """Insert or refresh the (source, external_id) record; returns it."""
    record = await session.scalar(
        select(MetadataRecord).where(
            MetadataRecord.source_id == source_id,
            MetadataRecord.external_id == external_id,
        )
    )
    if record is None:
        record = MetadataRecord(
            source_id=source_id,
            external_id=external_id,
            api_version=api_version,
            raw_payload=raw_payload,
            normalized=normalized,
        )
        session.add(record)
    else:
        record.api_version = api_version
        record.raw_payload = raw_payload
        record.normalized = normalized
        record.fetched_at = utcnow()
    return record


def _add_identity(
    session: AsyncSession, game: Game, source: MetadataSource, external_id: str
) -> GameExternalIdentity:
    identity = GameExternalIdentity(game_id=game.id, source_id=source.id, external_id=external_id)
    session.add(identity)
    return identity


def _add_uid_identities(
    session: AsyncSession,
    game: Game,
    uids: dict[str, str],
    sources: dict[str, MetadataSource],
    by_slug: dict[str, GameExternalIdentity],
) -> None:
    """Cross-catalog uids (D13/F2) → identities for registry sources; never overwrites."""
    for slug, uid in uids.items():
        source = sources.get(slug)
        if source is None or slug in by_slug:
            continue
        by_slug[slug] = _add_identity(session, game, source, uid)


async def _download_assets(
    session: AsyncSession,
    asset_dir: Path,
    wanted: dict[str, list[tuple[MetadataRecord, AssetKind, int]]],
    asset_stages: dict[AssetKind, JobStage],
    report: Callable[[], Awaitable[None]],
) -> None:
    """Download each unique URL once; write blob files + asset_blob/source_asset rows."""
    record_ids = {record.id for consumers in wanted.values() for record, _, _ in consumers}
    existing = {
        (row.metadata_record_id, row.kind, row.blob_blake3): row
        for row in await session.scalars(
            select(SourceAsset).where(SourceAsset.metadata_record_id.in_(record_ids))
        )
    }
    # First URL occurrence owns a row's ordinal (duplicate content dedupes).
    placed: set[tuple[uuid.UUID, AssetKind, str]] = set()
    blob_by_url: dict[str, str] = {}

    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as client:
        for kind, stage in asset_stages.items():
            stage.status = JobStageStatus.RUNNING
            await report()
            error: str | None = None
            for url, consumers in wanted.items():
                entries = [
                    (record, index)
                    for record, wanted_kind, index in consumers
                    if wanted_kind == kind
                ]
                if not entries:
                    continue
                try:
                    digest = blob_by_url.get(url)
                    if digest is None:
                        content, mime = await _download_asset(client, url)
                        try:
                            digest = await store_asset_blob(session, asset_dir, content, mime)
                        except Exception:
                            # A DB failure poisons the session: roll back so later
                            # writes and the stage commit stay usable, and drop
                            # cached digests whose blob rows just rolled back.
                            await session.rollback()
                            blob_by_url.clear()
                            raise
                        blob_by_url[url] = digest
                    for record, index in entries:
                        key = (record.id, kind, digest)
                        if key in placed:
                            continue
                        placed.add(key)
                        row = existing.get(key)
                        if row is None:
                            row = SourceAsset(
                                metadata_record_id=record.id,
                                kind=kind,
                                blob_blake3=digest,
                                ordinal=index,
                            )
                            session.add(row)
                            existing[key] = row
                        elif row.ordinal != index:
                            # Ordinals mirror the current normalized list — resumes
                            # and upstream reorders heal in place.
                            row.ordinal = index
                except Exception as exc:
                    error = error or f"{type(exc).__name__}: {exc}"
            stage.error = error
            try:
                await session.commit()
            except Exception as exc:
                await session.rollback()
                stage.error = error or f"{type(exc).__name__}: {exc}"
            stage.status = JobStageStatus.FAILED if stage.error else JobStageStatus.COMPLETED
            await report()


async def fetch_game_metadata(
    session: AsyncSession,
    game: Game,
    asset_dir: Path,
    *,
    gog_client: gog.GogClient | None = None,
    galaxy_raw: dict[str, Any] | None = None,
    progress: ProgressHook | None = None,
) -> list[JobStage]:
    """Fetch each reachable source's record (committing per source), then re-resolve."""
    sources = {source.slug: source for source in await session.scalars(select(MetadataSource))}
    identities = await session.scalars(
        select(GameExternalIdentity).where(GameExternalIdentity.game_id == game.id)
    )
    ids_by_source = {identity.source_id: identity for identity in identities}
    by_slug = {
        slug: ids_by_source[source.id]
        for slug, source in sources.items()
        if source.id in ids_by_source
    }

    # A gog identity implies the same id on the other family rows (the shared fetch key).
    if (gog_identity := by_slug.get("gog")) is not None:
        for slug in ("gog_store", "gog_gamesdb"):
            if slug in sources and slug not in by_slug:
                by_slug[slug] = _add_identity(
                    session, game, sources[slug], gog_identity.external_id
                )
    # Interleaved commits: report_progress writes from a second connection (SQLite lock).
    await session.commit()

    candidates = [
        slug
        for slug, spec in _SOURCES.items()
        if slug in sources and sources[slug].enabled and (slug in by_slug or spec.discover)
    ]

    stages: list[JobStage] = []
    harvested: list[tuple[MetadataRecord, list[AssetEntry]]] = []

    async def report() -> None:
        if progress is not None:
            await progress(stages)

    async with AsyncExitStack() as stack:
        # Family clients built once, lazily per plan; unconfigured families drop out.
        clients: dict[str, Any] = {}
        for family in {_SOURCES[slug].family for slug in candidates}:
            if family == "gog" and gog_client is not None:
                clients["gog"] = gog_client
                continue
            client = await _FAMILY_CLIENTS[family](session)
            if client is not None:
                clients[family] = await stack.enter_async_context(client)

        for slug in candidates:
            spec = _SOURCES[slug]
            client = clients.get(spec.family)
            if client is None or slug in by_slug or spec.discover is None:
                continue
            discovered = await spec.discover(client, by_slug)
            if discovered is not None:
                by_slug[slug] = _add_identity(session, game, sources[slug], discovered)
        await session.commit()

        stages.extend(
            JobStage(key=slug, label=sources[slug].name, group=METADATA_GROUP)
            for slug in candidates
            if slug in by_slug and _SOURCES[slug].family in clients
        )
        await report()
        for stage in stages:
            stage.status = JobStageStatus.RUNNING
            await report()
            spec = _SOURCES[stage.key]
            client = clients[spec.family]
            external_id = by_slug[stage.key].external_id
            try:
                if stage.key == "gog" and galaxy_raw is not None:
                    raw = galaxy_raw
                else:
                    raw = await spec.fetch(client, external_id)
                if raw is None:
                    raise RuntimeError("record not found")
                normalized = spec.normalize(raw)
                # Drifted normalizer output fails this source's stage here —
                # it must never enter storage (strict schema, CR-178).
                validated = NormalizedMetadata.model_validate(normalized)
                record = await upsert_metadata_record(
                    session,
                    source_id=sources[stage.key].id,
                    external_id=external_id,
                    api_version=spec.api_version,
                    raw_payload=raw,
                    normalized=normalized,
                )
                if spec.uids is not None:
                    _add_uid_identities(session, game, spec.uids(raw), sources, by_slug)
                # Commit before planning downloads: a failed commit must not
                # leave a rolled-back record queued for asset writes.
                await session.commit()
                harvested.append((record, validated.assets or []))
                stage.status = JobStageStatus.COMPLETED
            except Exception as exc:
                await session.rollback()
                stage.status = JobStageStatus.FAILED
                stage.error = f"{type(exc).__name__}: {exc}"
            await report()

    wanted: dict[str, list[tuple[MetadataRecord, AssetKind, int]]] = {}
    indexes: Counter[tuple[uuid.UUID, AssetKind]] = Counter()
    for record, assets in harvested:
        for asset in assets:
            key = (record.id, asset.kind)
            wanted.setdefault(asset.url, []).append((record, asset.kind, indexes[key]))
            indexes[key] += 1
    if wanted:
        present = {kind for consumers in wanted.values() for _, kind, _ in consumers}
        asset_stages = {
            kind: JobStage(key=str(kind), label=_ASSET_LABELS[kind], group="Assets")
            for kind in AssetKind
            if kind in present
        }
        stages.extend(asset_stages.values())
        await report()
        await _download_assets(session, asset_dir, wanted, asset_stages, report)

    resolve_stage = JobStage(key="resolve", label="Resolve", group="Resolve")
    stages.append(resolve_stage)
    resolve_stage.status = JobStageStatus.RUNNING
    await report()
    try:
        await resolve_game_metadata(session, game)
        await session.commit()
    except Exception as exc:
        # Roll back before reporting: report_progress writes from a second connection.
        await session.rollback()
        resolve_stage.status = JobStageStatus.FAILED
        resolve_stage.error = f"{type(exc).__name__}: {exc}"
        await report()
        raise
    resolve_stage.status = JobStageStatus.COMPLETED
    await report()
    return stages
