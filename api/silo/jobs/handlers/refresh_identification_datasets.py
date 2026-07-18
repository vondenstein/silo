import asyncio

from pydantic import BaseModel
from sqlalchemy import select

from silo.jobs.registry import JobContext, JobHandler, register
from silo.models.identification import IdentificationDataset, IdentificationSource
from silo.models.job import JobKind
from silo.schemas.job import JobStage, JobStageStatus
from silo.services.identification import import_signatures
from silo.sources import redump


class RefreshIdentificationDatasetsPayload(BaseModel):
    pass


class RefreshIdentificationDatasetsProgress(BaseModel):
    stages: list[JobStage]


class RefreshIdentificationDatasetsResult(BaseModel):
    refreshed: int
    failed: list[str]


async def run_refresh_identification_datasets(
    ctx: JobContext, payload: RefreshIdentificationDatasetsPayload
) -> RefreshIdentificationDatasetsResult:
    async with ctx.sessionmaker() as session:
        targets = (
            await session.execute(
                select(
                    IdentificationDataset.id,
                    IdentificationDataset.slug,
                    IdentificationDataset.name,
                    IdentificationDataset.dataset_url,
                    IdentificationSource.name.label("source_name"),
                )
                .join(
                    IdentificationSource,
                    IdentificationSource.id == IdentificationDataset.source_id,
                )
                .where(
                    IdentificationDataset.enabled.is_(True),
                    IdentificationDataset.dataset_url.is_not(None),
                )
                .order_by(IdentificationDataset.name)
            )
        ).all()
    if not targets:
        raise RuntimeError("no enabled datasets to refresh")

    stages = [
        JobStage(key=target.slug, label=target.name, group=target.source_name) for target in targets
    ]

    async def report() -> None:
        await ctx.report_progress(RefreshIdentificationDatasetsProgress(stages=stages))

    refreshed = 0
    failed: list[str] = []
    for target, stage in zip(targets, stages, strict=True):
        stage.status = JobStageStatus.RUNNING
        await report()
        try:
            parsed = await asyncio.to_thread(
                redump.parse_dat, await redump.download_dat(target.dataset_url)
            )
            async with ctx.sessionmaker() as session:
                await import_signatures(session, target.id, parsed)
                await session.commit()
        except Exception as exc:
            stage.status = JobStageStatus.FAILED
            stage.error = f"{type(exc).__name__}: {exc}"
            failed.append(target.slug)
        else:
            stage.status = JobStageStatus.COMPLETED
            refreshed += 1
        await report()
    if not refreshed:
        raise RuntimeError("every dataset refresh failed")
    return RefreshIdentificationDatasetsResult(refreshed=refreshed, failed=failed)


register(
    JobKind.REFRESH_IDENTIFICATION_DATASETS,
    JobHandler(
        RefreshIdentificationDatasetsPayload,
        RefreshIdentificationDatasetsProgress,
        RefreshIdentificationDatasetsResult,
        run_refresh_identification_datasets,
    ),
)
