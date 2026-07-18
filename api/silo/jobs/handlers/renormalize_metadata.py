from pydantic import BaseModel
from sqlalchemy import select

from silo.jobs.registry import JobContext, JobHandler, register
from silo.models.game import Game, GameExternalIdentity
from silo.models.job import JobKind
from silo.models.metadata_record import MetadataRecord
from silo.models.metadata_source import MetadataSource
from silo.schemas.job import JobStage, JobStageStatus
from silo.services.metadata_fetch import source_normalizers
from silo.services.resolution import resolve_game_metadata


class RenormalizeMetadataPayload(BaseModel):
    pass


class RenormalizeMetadataProgress(BaseModel):
    stages: list[JobStage]


class RenormalizeMetadataResult(BaseModel):
    records: int
    games: int


async def run_renormalize_metadata(
    ctx: JobContext, payload: RenormalizeMetadataPayload
) -> RenormalizeMetadataResult:
    normalizers = source_normalizers()
    async with ctx.sessionmaker() as session:
        sources = [
            source
            for source in await session.scalars(
                select(MetadataSource).order_by(MetadataSource.priority)
            )
            if source.slug in normalizers
        ]

    stages = [JobStage(key=source.slug, label=source.name, group="Records") for source in sources]
    stages.append(JobStage(key="resolve", label="Resolve games", group="Resolve"))
    by_key = {stage.key: stage for stage in stages}

    async def report() -> None:
        await ctx.report_progress(RenormalizeMetadataProgress(stages=stages))

    await report()
    records = 0
    for source in sources:
        stage = by_key[source.slug]
        stage.status = JobStageStatus.RUNNING
        await report()
        async with ctx.sessionmaker() as session:
            rows = (
                await session.scalars(
                    select(MetadataRecord).where(MetadataRecord.source_id == source.id)
                )
            ).all()
            for record in rows:
                record.normalized = normalizers[source.slug](record.raw_payload)
            await session.commit()
        records += len(rows)
        stage.status = JobStageStatus.COMPLETED
        await report()

    stage = by_key["resolve"]
    stage.status = JobStageStatus.RUNNING
    await report()
    async with ctx.sessionmaker() as session:
        game_ids = (await session.scalars(select(GameExternalIdentity.game_id).distinct())).all()
    games = 0
    for index, game_id in enumerate(game_ids):
        async with ctx.sessionmaker() as session:
            game = await session.get(Game, game_id)
            if game is None:
                continue
            await resolve_game_metadata(session, game)
            await session.commit()
        games += 1
        if (index + 1) % 10 == 0:
            stage.label = f"Resolve games ({index + 1}/{len(game_ids)})"
            await report()
    stage.label = f"Resolve games ({games}/{len(game_ids)})"
    stage.status = JobStageStatus.COMPLETED
    await report()
    return RenormalizeMetadataResult(records=records, games=games)


register(
    JobKind.RENORMALIZE_METADATA,
    JobHandler(
        RenormalizeMetadataPayload,
        RenormalizeMetadataProgress,
        RenormalizeMetadataResult,
        run_renormalize_metadata,
    ),
)
