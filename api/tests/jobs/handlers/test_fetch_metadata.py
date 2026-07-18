import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from silo.jobs.handlers.fetch_metadata import FetchMetadataPayload
from silo.jobs.worker import enqueue, run_next_job
from silo.models.game import GameExternalIdentity
from silo.models.job import Job, JobKind, JobStatus
from silo.models.metadata_source import MetadataSource
from silo.sources.gog import GogClient

SessionFactory = async_sessionmaker[AsyncSession]

GALAXY: dict[str, Any] = {
    "title": "Test Game",
    "game_type": "game",
    "description": {"full": "<p>Full.</p>"},
}
STORE: dict[str, Any] = {
    "description": "<p>Store full.</p>",
    "_embedded": {
        "product": {"title": "Test Game", "globalReleaseDate": "2013-01-16T00:00:00+02:00"},
        "productType": "GAME",
    },
}
GAMESDB: dict[str, Any] = {
    "game": {
        "title": {"*": "Test Game"},
        "sorting_title": {"*": "Game 1"},
        "summary": {"*": "Short."},
        "first_release_date": "2012-11-27T00:00:00+0000",
        "type": "game",
        "releases": [{"platform_id": "steam", "external_id": "111"}],
    }
}


@pytest.fixture
def gog_stubbed(monkeypatch: pytest.MonkeyPatch):
    async def fake_fresh(session) -> str:
        return "tok"

    async def fake_product(self: GogClient, gog_id: int) -> dict[str, Any]:
        return GALAXY

    async def fake_product_v2(self: GogClient, gog_id: int) -> dict[str, Any]:
        return STORE

    async def fake_gamesdb(self: GogClient, gog_id: int) -> dict[str, Any]:
        return GAMESDB

    monkeypatch.setattr("silo.sources.gog.fresh_access_token", fake_fresh)
    monkeypatch.setattr(GogClient, "product", fake_product)
    monkeypatch.setattr(GogClient, "product_v2", fake_product_v2)
    monkeypatch.setattr(GogClient, "gamesdb_release", fake_gamesdb)


async def _game_with_identity(client: AsyncClient, session_factory: SessionFactory) -> str:
    lib = await client.post("/api/v1/libraries", json={"slug": "main", "name": "Main"})
    assert lib.status_code == 201
    game = await client.post(
        "/api/v1/games",
        json={"library_id": lib.json()["id"], "slug": "test-game", "title": "Placeholder"},
    )
    assert game.status_code == 201
    game_id = game.json()["id"]
    async with session_factory() as session:
        gog_id = await session.scalar(select(MetadataSource.id).where(MetadataSource.slug == "gog"))
        assert gog_id is not None
        session.add(
            GameExternalIdentity(game_id=uuid.UUID(game_id), source_id=gog_id, external_id="42")
        )
        await session.commit()
    return game_id


async def _enqueue(session_factory: SessionFactory, game_id: str) -> uuid.UUID:
    async with session_factory() as session:
        job = await enqueue(
            session, JobKind.FETCH_METADATA, FetchMetadataPayload(game_id=uuid.UUID(game_id))
        )
        await session.commit()
        return job.id


async def _job(session_factory: SessionFactory, job_id: uuid.UUID) -> Job:
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        assert job is not None
        return job


async def test_fetch_metadata_full_cycle(
    client: AsyncClient, session_factory: SessionFactory, settings, gog_stubbed
):
    game_id = await _game_with_identity(client, session_factory)
    job_id = await _enqueue(session_factory, game_id)

    assert await run_next_job(session_factory, settings) is True

    job = await _job(session_factory, job_id)
    assert job.error is None
    assert job.status == JobStatus.COMPLETED
    assert job.result == {"game_id": game_id}
    assert [(s["key"], s["label"], s["status"]) for s in job.progress["stages"]] == [
        ("gog", "GOG", "completed"),
        ("gog_store", "GOG Store", "completed"),
        ("gog_gamesdb", "GOG GamesDB", "completed"),
        ("resolve", "Resolve", "completed"),
    ]

    detail = (await client.get(f"/api/v1/games/{game_id}")).json()
    assert detail["title"] == "Test Game"
    assert detail["sort_title"] == "Game 1"
    assert detail["description_short"] == "Short."
    # Galaxy (priority 10) beats Store-v2 (14); GamesDB (12) supplies the true release date.
    assert detail["description_full"] == "<p>Full.</p>"
    assert detail["first_release_date"] == "2012-11-27"

    async with session_factory() as session:
        slugs = set(
            (
                await session.execute(
                    select(MetadataSource.slug)
                    .join(GameExternalIdentity, GameExternalIdentity.source_id == MetadataSource.id)
                    .where(GameExternalIdentity.game_id == uuid.UUID(game_id))
                )
            ).scalars()
        )
    assert slugs == {"gog", "gog_store", "gog_gamesdb", "steam"}


async def test_fetch_metadata_partial_failure_completes(
    client: AsyncClient,
    session_factory: SessionFactory,
    settings,
    gog_stubbed,
    monkeypatch: pytest.MonkeyPatch,
):
    async def broken(self: GogClient, gog_id: int) -> dict[str, Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(GogClient, "product_v2", broken)
    game_id = await _game_with_identity(client, session_factory)
    job_id = await _enqueue(session_factory, game_id)

    assert await run_next_job(session_factory, settings) is True

    job = await _job(session_factory, job_id)
    assert job.status == JobStatus.COMPLETED
    stages = {s["key"]: s for s in job.progress["stages"]}
    assert stages["gog_store"]["status"] == "failed"
    assert "RuntimeError: boom" in stages["gog_store"]["error"]
    assert stages["gog"]["status"] == "completed"
    assert stages["gog_gamesdb"]["status"] == "completed"


async def test_fetch_metadata_all_failed_fails_job(
    client: AsyncClient,
    session_factory: SessionFactory,
    settings,
    gog_stubbed,
    monkeypatch: pytest.MonkeyPatch,
):
    async def broken(self: GogClient, gog_id: int) -> dict[str, Any]:
        raise RuntimeError("boom")

    for method in ("product", "product_v2", "gamesdb_release"):
        monkeypatch.setattr(GogClient, method, broken)
    game_id = await _game_with_identity(client, session_factory)
    job_id = await _enqueue(session_factory, game_id)

    assert await run_next_job(session_factory, settings) is True

    job = await _job(session_factory, job_id)
    assert job.status == JobStatus.FAILED
    assert job.error is not None and "every source fetch failed" in job.error
    # The final stage list survives on the failed job — the post-mortem view.
    # Resolve still runs (and succeeds, as a no-op) even when every fetch failed.
    assert [s["status"] for s in job.progress["stages"]] == [
        "failed",
        "failed",
        "failed",
        "completed",
    ]


async def test_fetch_metadata_resolve_failure_fails_job_with_stage(
    client: AsyncClient,
    session_factory: SessionFactory,
    settings,
    gog_stubbed,
    monkeypatch: pytest.MonkeyPatch,
):
    async def broken_resolve(session: Any, game: Any) -> None:
        raise RuntimeError("resolve boom")

    monkeypatch.setattr("silo.services.metadata_fetch.resolve_game_metadata", broken_resolve)
    game_id = await _game_with_identity(client, session_factory)
    job_id = await _enqueue(session_factory, game_id)

    assert await run_next_job(session_factory, settings) is True

    job = await _job(session_factory, job_id)
    assert job.status == JobStatus.FAILED
    assert job.error is not None and "resolve boom" in job.error
    stages = {s["key"]: s for s in job.progress["stages"]}
    assert stages["gog"]["status"] == "completed"
    assert stages["resolve"]["status"] == "failed"
    assert "RuntimeError: resolve boom" in stages["resolve"]["error"]


async def test_fetch_metadata_missing_game_fails(
    client: AsyncClient, session_factory: SessionFactory, settings, gog_stubbed
):
    job_id = await _enqueue(session_factory, str(uuid.uuid4()))

    assert await run_next_job(session_factory, settings) is True

    job = await _job(session_factory, job_id)
    assert job.status == JobStatus.FAILED
    assert job.error is not None and "not found" in job.error
