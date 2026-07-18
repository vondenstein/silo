import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from silo.jobs.handlers.renormalize_metadata import RenormalizeMetadataPayload
from silo.jobs.worker import enqueue, run_next_job
from silo.models.company import Company
from silo.models.game import (
    CompanyRole,
    GameCompany,
    GameExternalIdentity,
    GamePlatform,
    GameRating,
    GameTag,
    RatingAuthority,
)
from silo.models.job import Job, JobKind, JobStatus
from silo.models.metadata_record import MetadataRecord
from silo.models.metadata_source import MetadataSource
from silo.models.platform import Platform
from silo.models.tag import Tag, TagKind

SessionFactory = async_sessionmaker[AsyncSession]

STEAM_RAW: dict[str, Any] = {
    "name": "Test Game",
    "type": "game",
    "developers": ["id Software"],
    "publishers": ["GT Interactive"],
    "genres": [{"id": "1", "description": "Shooter"}],
    "categories": [{"id": 2, "description": "Single-player"}],
    "platforms": {"windows": True, "mac": False, "linux": True},
    "ratings": {"esrb": {"rating": "m", "descriptors": "Violence\r\nBlood"}},
}


async def test_renormalize_full_cycle(
    client: AsyncClient, session_factory: SessionFactory, settings
):
    lib = await client.post("/api/v1/libraries", json={"slug": "main", "name": "Main"})
    game = await client.post(
        "/api/v1/games",
        json={"library_id": lib.json()["id"], "slug": "test-game", "title": "Test Game"},
    )
    game_id = uuid.UUID(game.json()["id"])
    async with session_factory() as session:
        steam_id = await session.scalar(
            select(MetadataSource.id).where(MetadataSource.slug == "steam")
        )
        assert steam_id is not None
        session.add(GameExternalIdentity(game_id=game_id, source_id=steam_id, external_id="42"))
        # A stale pre-collections normalized blob — re-derived from raw by the job.
        session.add(
            MetadataRecord(
                source_id=steam_id,
                external_id="42",
                api_version="storefront-appdetails",
                raw_payload=STEAM_RAW,
                normalized={"title": "Stale"},
            )
        )
        await session.commit()

    async with session_factory() as session:
        job = await enqueue(session, JobKind.RENORMALIZE_METADATA, RenormalizeMetadataPayload())
        await session.commit()
        job_id = job.id

    assert await run_next_job(session_factory, settings) is True

    async with session_factory() as session:
        finished = await session.get(Job, job_id)
        assert finished is not None
        assert finished.error is None
        assert finished.status == JobStatus.COMPLETED
        assert finished.result == {"records": 1, "games": 1}
        stages = {s["key"]: s["status"] for s in finished.progress["stages"]}
        assert stages == {
            "gog": "completed",
            "gog_gamesdb": "completed",
            "gog_store": "completed",
            "igdb": "completed",
            "steam": "completed",
            "resolve": "completed",
        }
        record = (await session.scalars(select(MetadataRecord))).one()
        assert record.normalized["title"] == "Test Game"
        assert record.normalized["developers"] == [{"name": "id Software"}]

        developers = list(
            await session.scalars(
                select(Company.name)
                .join(GameCompany, GameCompany.company_id == Company.id)
                .where(GameCompany.game_id == game_id, GameCompany.role == CompanyRole.DEVELOPER)
            )
        )
        assert developers == ["id Software"]
        tags = {
            (tag.kind, tag.name)
            for tag in await session.scalars(
                select(Tag)
                .join(GameTag, GameTag.tag_id == Tag.id)
                .where(GameTag.game_id == game_id)
            )
        }
        assert tags == {(TagKind.GENRE, "Shooter"), (TagKind.MODE, "Single player")}
        platforms = set(
            await session.scalars(
                select(Platform.slug)
                .join(GamePlatform, GamePlatform.platform_id == Platform.id)
                .where(GamePlatform.game_id == game_id)
            )
        )
        assert platforms == {"windows", "linux"}
        rating = (
            await session.scalars(select(GameRating).where(GameRating.game_id == game_id))
        ).one()
        assert (rating.authority, rating.value, rating.descriptors) == (
            RatingAuthority.ESRB,
            "m",
            ["Violence", "Blood"],
        )
