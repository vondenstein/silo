import json
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.asset import AssetBlob, AssetKind, SourceAsset
from silo.models.game import Game, GameExternalIdentity, GameMetadata
from silo.models.library import Library
from silo.models.metadata_record import MetadataRecord
from silo.models.metadata_source import MetadataSource
from silo.schemas.job import JobStage
from silo.services.metadata_fetch import (
    _gog_family_client,
    _igdb_family_client,
    _steam_family_client,
    fetch_game_metadata,
)
from silo.sources.gog import GogClient
from silo.sources.igdb import IgdbClient, store_credentials
from silo.sources.steam import SteamClient
from tests.seed import seed_in_order

GOG_ID = "1207666353"

ASSET_KINDS = ["cover", "background", "landscape", "logo", "icon", "screenshot", "video_thumbnail"]


def _fixture(name: str) -> dict:
    return json.loads((Path(__file__).parent.parent / "fixtures" / name).read_text())


GALAXY = _fixture("gog_galaxy_product.json")
STORE = _fixture("gog_store_game.json")
GAMESDB = _fixture("gog_gamesdb_release.json")

_ROUTES = {
    f"/products/{GOG_ID}": GALAXY,
    f"/v2/games/{GOG_ID}": STORE,
    f"/platforms/gog/external_releases/{GOG_ID}": GAMESDB,
}


@pytest.fixture(autouse=True)
def network_stubbed(monkeypatch: pytest.MonkeyPatch):
    async def fake_download_asset(client: httpx.AsyncClient, url: str) -> tuple[bytes, str]:
        return f"bytes:{url}".encode(), "image/jpeg"

    async def fake_appdetails(self: SteamClient, app_id: int) -> dict | None:
        return {"name": "Steam Stub", "type": "game"}

    monkeypatch.setattr("silo.services.metadata_fetch._download_asset", fake_download_asset)
    monkeypatch.setattr(SteamClient, "appdetails", fake_appdetails)


def _client(hits: list[str] | None = None, fail: set[str] | None = None) -> GogClient:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if hits is not None:
            hits.append(path)
        if fail and path in fail:
            return httpx.Response(500)
        return httpx.Response(200, json=_ROUTES[path])

    return GogClient("token", transport=httpx.MockTransport(handler))


def _library() -> Library:
    now = datetime(2025, 1, 1)
    return Library(id=uuid4(), slug="main", name="Main", created_at=now, updated_at=now)


def _sources(**overrides) -> dict[str, MetadataSource]:
    priorities = {"gog": 10, "gog_gamesdb": 12, "gog_store": 14, "igdb": 20, "steam": 30}
    return {
        slug: MetadataSource(
            id=uuid4(), slug=slug, name=slug, priority=priority, **overrides.get(slug, {})
        )
        for slug, priority in priorities.items()
    }


def _game(library_id) -> Game:
    gid = uuid4()
    now = datetime(2025, 1, 1)
    game = Game(id=gid, library_id=library_id, slug="bgee", created_at=now, updated_at=now)
    game.game_metadata = GameMetadata(game_id=gid, title="placeholder")
    return game


async def _seed(session: AsyncSession, sources: dict[str, MetadataSource]) -> Game:
    lib = _library()
    game = _game(lib.id)
    await seed_in_order(
        session,
        lib,
        *sources.values(),
        game,
        GameExternalIdentity(game_id=game.id, source_id=sources["gog"].id, external_id=GOG_ID),
    )
    return game


async def _identity_slugs(session: AsyncSession, game, sources) -> dict[str, str]:
    slug_by_id = {source.id: slug for slug, source in sources.items()}
    identities = (
        await session.execute(
            select(GameExternalIdentity).where(GameExternalIdentity.game_id == game.id)
        )
    ).scalars()
    return {slug_by_id[i.source_id]: i.external_id for i in identities}


async def test_fetches_family_and_resolves(db_session: AsyncSession, tmp_path: Path):
    sources = _sources()
    game = await _seed(db_session, sources)

    async with _client() as client:
        stages = await fetch_game_metadata(db_session, game, tmp_path, gog_client=client)
    await db_session.commit()

    assert [(s.key, s.status) for s in stages if s.group == "Metadata"] == [
        ("gog", "completed"),
        ("gog_store", "completed"),
        ("gog_gamesdb", "completed"),
    ]
    # All seven kinds appear across the family; each downloads to done.
    assert [(s.key, s.status) for s in stages if s.group == "Assets"] == [
        (kind, "completed") for kind in ASSET_KINDS
    ]
    records = (await db_session.execute(select(MetadataRecord))).scalars().all()
    assert len(records) == 3
    assert {r.external_id for r in records} == {GOG_ID}
    # Family identities derived from the gog row; D13 adds steam from releases[].
    assert await _identity_slugs(db_session, game, sources) == {
        "gog": GOG_ID,
        "gog_store": GOG_ID,
        "gog_gamesdb": GOG_ID,
        "steam": "228280",
    }
    # Resolution spans the family: galaxy title, gamesdb sort_title + true release date.
    assert game.game_metadata.title == "Baldur's Gate: Enhanced Edition"
    assert game.game_metadata.sort_title == "Baldurs Gate 1"
    assert game.game_metadata.first_release_date == date(2012, 11, 27)


async def test_galaxy_raw_skips_refetch(db_session: AsyncSession, tmp_path: Path):
    sources = _sources()
    game = await _seed(db_session, sources)

    hits: list[str] = []
    async with _client(hits) as client:
        await fetch_game_metadata(db_session, game, tmp_path, gog_client=client, galaxy_raw=GALAXY)

    assert f"/products/{GOG_ID}" not in hits
    assert len(hits) == 2
    # The galaxy record is still written, from the passed payload.
    records = (await db_session.execute(select(MetadataRecord))).scalars().all()
    assert len(records) == 3


async def test_source_failure_continues_and_resolves(db_session: AsyncSession, tmp_path: Path):
    sources = _sources()
    game = await _seed(db_session, sources)

    async with _client(fail={f"/v2/games/{GOG_ID}"}) as client:
        stages = await fetch_game_metadata(db_session, game, tmp_path, gog_client=client)

    by_key = {s.key: s for s in stages}
    assert by_key["gog_store"].status == "failed"
    assert by_key["gog_store"].error is not None
    assert "HTTPStatusError" in by_key["gog_store"].error
    assert by_key["gog"].status == "completed"
    assert by_key["gog_gamesdb"].status == "completed"
    records = (await db_session.execute(select(MetadataRecord))).scalars().all()
    assert len(records) == 2
    # Whatever landed still resolves.
    assert game.game_metadata.sort_title == "Baldurs Gate 1"


async def test_asset_resume_restores_source_order(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from blake3 import blake3

    from silo.sources.gog import normalize_galaxy

    sources = _sources()
    game = await _seed(db_session, sources)
    urls = [a["url"] for a in normalize_galaxy(GALAXY)["assets"] if a["kind"] == "screenshot"]
    assert len(urls) >= 3
    failing = {urls[1]}

    async def flaky_download_asset(client: httpx.AsyncClient, url: str) -> tuple[bytes, str]:
        if url in failing:
            raise RuntimeError("cdn stall")
        return f"bytes:{url}".encode(), "image/jpeg"

    monkeypatch.setattr("silo.services.metadata_fetch._download_asset", flaky_download_asset)

    async with _client() as client:
        await fetch_game_metadata(db_session, game, tmp_path, gog_client=client)
    failing.clear()
    async with _client() as client:
        await fetch_game_metadata(db_session, game, tmp_path, gog_client=client)

    galaxy_record = (
        await db_session.execute(
            select(MetadataRecord).where(MetadataRecord.source_id == sources["gog"].id)
        )
    ).scalar_one()
    rows = (
        (
            await db_session.execute(
                select(SourceAsset)
                .where(
                    SourceAsset.metadata_record_id == galaxy_record.id,
                    SourceAsset.kind == AssetKind.SCREENSHOT,
                )
                .order_by(SourceAsset.ordinal)
            )
        )
        .scalars()
        .all()
    )
    expected = [blake3(f"bytes:{url}".encode()).hexdigest() for url in urls]
    assert [row.blob_blake3 for row in rows] == expected


async def test_disabled_source_skipped(db_session: AsyncSession, tmp_path: Path):
    sources = _sources(gog_store={"enabled": False})
    game = await _seed(db_session, sources)

    async with _client() as client:
        stages = await fetch_game_metadata(db_session, game, tmp_path, gog_client=client)

    assert [s.key for s in stages if s.group == "Metadata"] == ["gog", "gog_gamesdb"]


async def test_release_identities_never_overwrite(db_session: AsyncSession, tmp_path: Path):
    sources = _sources()
    game = await _seed(db_session, sources)
    db_session.add(
        GameExternalIdentity(game_id=game.id, source_id=sources["steam"].id, external_id="999")
    )
    await db_session.commit()

    async with _client() as client:
        await fetch_game_metadata(db_session, game, tmp_path, gog_client=client)
    await db_session.commit()

    identities = await _identity_slugs(db_session, game, sources)
    assert identities["steam"] == "999"


async def test_refetch_updates_existing_record(db_session: AsyncSession, tmp_path: Path):
    sources = _sources()
    game = await _seed(db_session, sources)
    db_session.add(
        MetadataRecord(
            source_id=sources["gog"].id,
            external_id=GOG_ID,
            api_version="old",
            raw_payload={},
            normalized={"title": "stale"},
        )
    )
    await db_session.commit()

    async with _client() as client:
        await fetch_game_metadata(db_session, game, tmp_path, gog_client=client)
    await db_session.commit()

    record = (
        await db_session.execute(
            select(MetadataRecord).where(MetadataRecord.source_id == sources["gog"].id)
        )
    ).scalar_one()
    assert record.api_version == "galaxy-products"
    assert record.normalized["title"] == "Baldur's Gate: Enhanced Edition"


async def test_assets_stored_and_deduped(db_session: AsyncSession, tmp_path: Path):
    sources = _sources()
    game = await _seed(db_session, sources)
    asset_dir = tmp_path / "assets"

    async with _client() as client:
        await fetch_game_metadata(db_session, game, asset_dir, gog_client=client)
    await db_session.commit()

    blobs = (await db_session.execute(select(AssetBlob))).scalars().all()
    assert {p.name for p in asset_dir.iterdir()} == {b.blake3 for b in blobs}
    rows = (await db_session.execute(select(SourceAsset))).scalars().all()
    # Shared URLs (same bytes serving several kinds/records) produce more rows than blobs.
    assert len(rows) > len(blobs)

    gamesdb_record_id = await db_session.scalar(
        select(MetadataRecord.id).where(MetadataRecord.source_id == sources["gog_gamesdb"].id)
    )
    per_kind: dict[AssetKind, set[str]] = {}
    for row in rows:
        if row.metadata_record_id == gamesdb_record_id:
            per_kind.setdefault(row.kind, set()).add(row.blob_blake3)
    # Post-audit: gamesdb landscape (artworks only) is distinct art — never the background.
    assert per_kind[AssetKind.BACKGROUND].isdisjoint(per_kind[AssetKind.LANDSCAPE])
    ordinals = sorted(
        row.ordinal
        for row in rows
        if row.metadata_record_id == gamesdb_record_id and row.kind == AssetKind.SCREENSHOT
    )
    assert ordinals == list(range(17))

    # A second run downloads nothing new and adds no rows.
    async with _client() as client:
        await fetch_game_metadata(db_session, game, asset_dir, gog_client=client)
    await db_session.commit()
    rows_after = (await db_session.execute(select(SourceAsset))).scalars().all()
    assert len(rows_after) == len(rows)


async def test_asset_failure_fails_kind_stage_only(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    async def flaky(client: httpx.AsyncClient, url: str) -> tuple[bytes, str]:
        if url.endswith(".jpg?namespace=gamesdb"):
            raise RuntimeError("cdn hiccup")
        return f"bytes:{url}".encode(), "image/jpeg"

    monkeypatch.setattr("silo.services.metadata_fetch._download_asset", flaky)
    sources = _sources()
    game = await _seed(db_session, sources)

    async with _client() as client:
        stages = await fetch_game_metadata(db_session, game, tmp_path, gog_client=client)

    by_key = {s.key: s for s in stages}
    assert by_key["screenshot"].status == "failed"
    assert by_key["screenshot"].error is not None
    assert "cdn hiccup" in by_key["screenshot"].error
    assert by_key["cover"].status == "completed"
    # The metadata walk is untouched by asset failures.
    assert by_key["gog_gamesdb"].status == "completed"


async def test_igdb_discovered_and_fetched(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    sources = _sources()
    game = await _seed(db_session, sources)
    await store_credentials(db_session, "cid", "csecret")
    await db_session.commit()

    async def fake_token(client_id: str, client_secret: str) -> str:
        return "tok"

    async def fake_discover(self: IgdbClient, external_source: int, uid: str) -> int | None:
        assert (external_source, uid) == (5, GOG_ID)
        return 119171

    async def fake_game(self: IgdbClient, igdb_id: int) -> dict | None:
        assert igdb_id == 119171
        return {
            "name": "IGDB Name",
            "external_games": [{"external_game_source": 1, "uid": "111"}],
        }

    monkeypatch.setattr("silo.sources.igdb.app_token", fake_token)
    monkeypatch.setattr(IgdbClient, "discover", fake_discover)
    monkeypatch.setattr(IgdbClient, "game", fake_game)

    async with _client() as client:
        stages = await fetch_game_metadata(db_session, game, tmp_path, gog_client=client)
    await db_session.commit()

    by_key = {s.key: s for s in stages}
    assert by_key["igdb"].status == "completed"
    identities = await _identity_slugs(db_session, game, sources)
    assert identities["igdb"] == "119171"
    # F2 never overwrites D13's steam id.
    assert identities["steam"] == "228280"
    record = (
        await db_session.execute(
            select(MetadataRecord).where(MetadataRecord.source_id == sources["igdb"].id)
        )
    ).scalar_one()
    assert record.api_version == "v4-games"
    assert record.normalized["title"] == "IGDB Name"


async def test_steam_fetched_for_identified_game(db_session: AsyncSession, tmp_path: Path):
    sources = _sources()
    game = await _seed(db_session, sources)
    db_session.add(
        GameExternalIdentity(game_id=game.id, source_id=sources["steam"].id, external_id="1086940")
    )
    await db_session.commit()

    async with _client() as client:
        stages = await fetch_game_metadata(db_session, game, tmp_path, gog_client=client)
    await db_session.commit()

    by_key = {s.key: s for s in stages}
    assert by_key["steam"].status == "completed"
    record = (
        await db_session.execute(
            select(MetadataRecord).where(MetadataRecord.source_id == sources["steam"].id)
        )
    ).scalar_one()
    assert record.api_version == "storefront-appdetails"
    assert record.normalized["title"] == "Steam Stub"


async def test_igdb_unconfigured_skipped(db_session: AsyncSession, tmp_path: Path):
    sources = _sources()
    game = await _seed(db_session, sources)

    async with _client() as client:
        stages = await fetch_game_metadata(db_session, game, tmp_path, gog_client=client)

    assert "igdb" not in {s.key for s in stages}


async def test_gog_family_skipped_when_disconnected(db_session: AsyncSession, tmp_path: Path):
    sources = _sources()
    game = await _seed(db_session, sources)

    stages = await fetch_game_metadata(db_session, game, tmp_path)

    # Only the unconditional resolve stage remains — no source was reachable.
    assert [(s.key, s.status) for s in stages] == [("resolve", "completed")]


async def test_progress_reports_transitions(db_session: AsyncSession, tmp_path: Path):
    sources = _sources()
    game = await _seed(db_session, sources)

    snapshots: list[list[tuple[str, str]]] = []

    async def progress(stages: list[JobStage]) -> None:
        snapshots.append([(s.key, str(s.status)) for s in stages])

    async with _client() as client:
        await fetch_game_metadata(db_session, game, tmp_path, gog_client=client, progress=progress)

    assert snapshots[0] == [
        ("gog", "pending"),
        ("gog_store", "pending"),
        ("gog_gamesdb", "pending"),
    ]
    # Structural cadence, not implementation echoes: the stage list only grows
    # (stable prefix), and every stage passes through running before completing.
    keys_per_snapshot = [[key for key, _ in snapshot] for snapshot in snapshots]
    for previous, current in zip(keys_per_snapshot, keys_per_snapshot[1:]):
        assert current[: len(previous)] == previous
    for key in keys_per_snapshot[-1]:
        statuses = [status for snapshot in snapshots for k, status in snapshot if k == key]
        assert "running" in statuses
        assert statuses[-1] == "completed"
        assert statuses.index("running") < statuses.index("completed")
    assert {key for key, _ in snapshots[-1]} == {
        "gog",
        "gog_store",
        "gog_gamesdb",
        "resolve",
        *ASSET_KINDS,
    }


async def test_family_clients_carry_registry_interval(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    # The registry's request_interval_ms must reach the built family clients —
    # a dropped hop silently unthrottles every fetch.
    sources = _sources(
        gog={"request_interval_ms": 111},
        igdb={"request_interval_ms": 222},
        steam={"request_interval_ms": 333},
    )
    await seed_in_order(db_session, *sources.values())

    async def fake_fresh(session) -> str:
        return "token"

    async def fake_app_token(client_id: str, client_secret: str) -> str:
        return "app-token"

    monkeypatch.setattr("silo.sources.gog.fresh_access_token", fake_fresh)
    monkeypatch.setattr("silo.sources.igdb.app_token", fake_app_token)
    await store_credentials(db_session, "cid", "csecret")
    await db_session.commit()

    gog_client = await _gog_family_client(db_session)
    igdb_client = await _igdb_family_client(db_session)
    steam_client = await _steam_family_client(db_session)
    assert gog_client is not None
    assert igdb_client is not None
    for client, expected in ((gog_client, 0.111), (igdb_client, 0.222), (steam_client, 0.333)):
        async with client:
            # ThrottledClient keeps the interval in seconds.
            assert client._interval == pytest.approx(expected)
