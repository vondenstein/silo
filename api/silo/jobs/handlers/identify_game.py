import uuid

from pydantic import BaseModel
from sqlalchemy import select

from silo.jobs.handlers.fetch_metadata import FetchMetadataPayload
from silo.jobs.registry import JobContext, JobHandler, register
from silo.jobs.worker import enqueue
from silo.models.game import Game, GameExternalIdentity
from silo.models.job import JobKind
from silo.models.metadata_source import MetadataSource
from silo.schemas.job import JobStage, JobStageStatus
from silo.services.identity_bridge import clean_dat_name, pick_match
from silo.services.metadata_fetch import search_source


class IdentifyGamePayload(BaseModel):
    game_id: uuid.UUID
    game_name: str


class IdentifyGameProgress(BaseModel):
    stages: list[JobStage]


class IdentifyGameResult(BaseModel):
    matched: bool
    external_id: str | None = None
    name: str | None = None


async def run_identify_game(ctx: JobContext, payload: IdentifyGamePayload) -> IdentifyGameResult:
    stages = [JobStage(key="igdb", label="Match against IGDB", group="Identify")]
    stage = stages[0]

    async def report() -> None:
        await ctx.report_progress(IdentifyGameProgress(stages=stages))

    stage.status = JobStageStatus.RUNNING
    await report()

    async with ctx.sessionmaker() as session:
        game = await session.get(Game, payload.game_id)
        if game is None:
            raise RuntimeError(f"game {payload.game_id} not found")
        source = await session.scalar(select(MetadataSource).where(MetadataSource.slug == "igdb"))
        if source is None:
            raise RuntimeError("igdb metadata source is not seeded")
        existing = await session.scalar(
            select(GameExternalIdentity).where(
                GameExternalIdentity.game_id == payload.game_id,
                GameExternalIdentity.source_id == source.id,
            )
        )
        if existing is not None:
            # Already identified — just kick the fetch.
            await enqueue(session, JobKind.FETCH_METADATA, FetchMetadataPayload(game_id=game.id))
            await session.commit()
            stage.status = JobStageStatus.COMPLETED
            await report()
            return IdentifyGameResult(matched=True, external_id=existing.external_id)

        candidates = await search_source(session, "igdb", clean_dat_name(payload.game_name))
        if candidates is None:
            raise RuntimeError("IGDB is not configured")
        match = pick_match(candidates, payload.game_name)
        if match is None:
            stage.status = JobStageStatus.COMPLETED
            await report()
            return IdentifyGameResult(matched=False)

        session.add(
            GameExternalIdentity(
                game_id=game.id, source_id=source.id, external_id=match.external_id
            )
        )
        await enqueue(session, JobKind.FETCH_METADATA, FetchMetadataPayload(game_id=game.id))
        await session.commit()

    stage.status = JobStageStatus.COMPLETED
    await report()
    return IdentifyGameResult(matched=True, external_id=match.external_id, name=match.name)


register(
    JobKind.IDENTIFY_GAME,
    JobHandler(IdentifyGamePayload, IdentifyGameProgress, IdentifyGameResult, run_identify_game),
)
