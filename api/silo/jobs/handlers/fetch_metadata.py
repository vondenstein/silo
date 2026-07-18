import uuid

from pydantic import BaseModel

from silo.jobs.registry import JobContext, JobHandler, register
from silo.models.game import Game
from silo.models.job import JobKind
from silo.schemas.job import JobStage, JobStageStatus
from silo.services.metadata_fetch import METADATA_GROUP, fetch_game_metadata


class FetchMetadataPayload(BaseModel):
    game_id: uuid.UUID


class FetchMetadataProgress(BaseModel):
    stages: list[JobStage]


class FetchMetadataResult(BaseModel):
    game_id: uuid.UUID


async def run_fetch_metadata(ctx: JobContext, payload: FetchMetadataPayload) -> FetchMetadataResult:
    async with ctx.sessionmaker() as session:
        game = await session.get(Game, payload.game_id)
        if game is None:
            raise RuntimeError(f"game {payload.game_id} not found")

        async def progress(stages: list[JobStage]) -> None:
            await ctx.report_progress(FetchMetadataProgress(stages=stages))

        stages = await fetch_game_metadata(session, game, ctx.settings.asset_dir, progress=progress)

    sources = [stage for stage in stages if stage.group == METADATA_GROUP]
    if not sources:
        raise RuntimeError("no sources available to fetch")
    if all(stage.status == JobStageStatus.FAILED for stage in sources):
        raise RuntimeError("every source fetch failed")
    return FetchMetadataResult(game_id=payload.game_id)


register(
    JobKind.FETCH_METADATA,
    JobHandler(
        FetchMetadataPayload, FetchMetadataProgress, FetchMetadataResult, run_fetch_metadata
    ),
)
