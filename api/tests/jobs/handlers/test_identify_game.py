import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from silo.jobs.handlers.identify_game import IdentifyGamePayload
from silo.jobs.worker import enqueue, run_next_job
from silo.models.game import GameExternalIdentity
from silo.models.job import Job, JobKind, JobStatus
from silo.models.metadata_source import MetadataSource
from silo.schemas.metadata_source import SearchCandidateOut

SessionFactory = async_sessionmaker[AsyncSession]


async def _game(client: AsyncClient) -> uuid.UUID:
    lib = await client.post("/api/v1/libraries", json={"slug": "main", "name": "Main"})
    game = await client.post(
        "/api/v1/games",
        json={"library_id": lib.json()["id"], "slug": "doom", "title": "Doom"},
    )
    return uuid.UUID(game.json()["id"])


async def _run(session_factory: SessionFactory, settings, payload: IdentifyGamePayload) -> Job:
    async with session_factory() as session:
        job = await enqueue(session, JobKind.IDENTIFY_GAME, payload)
        await session.commit()
        job_id = job.id
    assert await run_next_job(session_factory, settings) is True
    async with session_factory() as session:
        finished = await session.get(Job, job_id)
        assert finished is not None
        return finished


def _stub_search(monkeypatch: pytest.MonkeyPatch, candidates: list[dict[str, Any]] | None):
    async def fake(session, slug: str, term: str) -> list[SearchCandidateOut] | None:
        assert slug == "igdb"
        if candidates is None:
            return None
        return [SearchCandidateOut.model_validate(candidate) for candidate in candidates]

    monkeypatch.setattr("silo.jobs.handlers.identify_game.search_source", fake)


async def test_identify_matches_writes_identity_and_chains_fetch(
    client: AsyncClient,
    session_factory: SessionFactory,
    settings,
    monkeypatch: pytest.MonkeyPatch,
):
    game_id = await _game(client)
    _stub_search(monkeypatch, [{"external_id": "77", "name": "Doom", "year": 1993}])

    job = await _run(
        session_factory, settings, IdentifyGamePayload(game_id=game_id, game_name="Doom (USA)")
    )

    assert job.status == JobStatus.COMPLETED
    assert job.result == {"matched": True, "external_id": "77", "name": "Doom"}
    async with session_factory() as session:
        igdb_id = await session.scalar(
            select(MetadataSource.id).where(MetadataSource.slug == "igdb")
        )
        identity = (
            await session.scalars(
                select(GameExternalIdentity).where(
                    GameExternalIdentity.game_id == game_id,
                    GameExternalIdentity.source_id == igdb_id,
                )
            )
        ).one()
        assert identity.external_id == "77"
        fetch_jobs = (
            await session.scalars(select(Job).where(Job.kind == JobKind.FETCH_METADATA))
        ).all()
        assert [job.payload for job in fetch_jobs] == [{"game_id": str(game_id)}]


async def test_identify_below_threshold_writes_nothing(
    client: AsyncClient,
    session_factory: SessionFactory,
    settings,
    monkeypatch: pytest.MonkeyPatch,
):
    game_id = await _game(client)
    _stub_search(monkeypatch, [{"external_id": "77", "name": "Doom 3", "year": 2004}])

    job = await _run(
        session_factory, settings, IdentifyGamePayload(game_id=game_id, game_name="Doom (USA)")
    )

    assert job.status == JobStatus.COMPLETED
    assert job.result == {"matched": False, "external_id": None, "name": None}
    async with session_factory() as session:
        identities = (
            await session.scalars(
                select(GameExternalIdentity).where(GameExternalIdentity.game_id == game_id)
            )
        ).all()
        assert identities == []
        assert (
            await session.scalars(select(Job).where(Job.kind == JobKind.FETCH_METADATA))
        ).all() == []


async def test_identify_already_identified_skips_search(
    client: AsyncClient,
    session_factory: SessionFactory,
    settings,
    monkeypatch: pytest.MonkeyPatch,
):
    game_id = await _game(client)
    async with session_factory() as session:
        igdb_id = await session.scalar(
            select(MetadataSource.id).where(MetadataSource.slug == "igdb")
        )
        assert igdb_id is not None
        session.add(GameExternalIdentity(game_id=game_id, source_id=igdb_id, external_id="55"))
        await session.commit()

    async def exploding(session, slug, term):
        raise AssertionError("search must not run for identified games")

    monkeypatch.setattr("silo.jobs.handlers.identify_game.search_source", exploding)

    job = await _run(
        session_factory, settings, IdentifyGamePayload(game_id=game_id, game_name="Doom (USA)")
    )

    assert job.status == JobStatus.COMPLETED
    assert job.result == {"matched": True, "external_id": "55", "name": None}
    async with session_factory() as session:
        fetch_jobs = (
            await session.scalars(select(Job).where(Job.kind == JobKind.FETCH_METADATA))
        ).all()
        assert len(fetch_jobs) == 1


async def test_identify_unconfigured_igdb_fails(
    client: AsyncClient,
    session_factory: SessionFactory,
    settings,
    monkeypatch: pytest.MonkeyPatch,
):
    game_id = await _game(client)
    _stub_search(monkeypatch, None)

    job = await _run(
        session_factory, settings, IdentifyGamePayload(game_id=game_id, game_name="Doom (USA)")
    )

    assert job.status == JobStatus.FAILED
    assert job.error is not None and "IGDB is not configured" in job.error
