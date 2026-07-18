import asyncio
import uuid

from pydantic import BaseModel

from silo.jobs.registry import JobContext, JobHandler, register
from silo.models.identification import IdentificationDataset
from silo.models.job import JobKind
from silo.schemas.job import JobStage, JobStageStatus
from silo.services.identification import import_signatures
from silo.sources import redump


class RefreshIdentificationDatasetPayload(BaseModel):
    dataset_id: uuid.UUID


class RefreshIdentificationDatasetProgress(BaseModel):
    stages: list[JobStage]


class RefreshIdentificationDatasetResult(BaseModel):
    signatures: int


async def run_refresh_identification_dataset(
    ctx: JobContext, payload: RefreshIdentificationDatasetPayload
) -> RefreshIdentificationDatasetResult:
    stages = [
        JobStage(key="download", label="Download DAT", group="Refresh"),
        JobStage(key="import", label="Import signatures", group="Refresh"),
    ]
    by_key = {stage.key: stage for stage in stages}

    async def report() -> None:
        await ctx.report_progress(RefreshIdentificationDatasetProgress(stages=stages))

    async with ctx.sessionmaker() as session:
        dataset = await session.get(IdentificationDataset, payload.dataset_id)
        if dataset is None:
            raise RuntimeError(f"dataset {payload.dataset_id} not found")
        if dataset.dataset_url is None:
            raise RuntimeError(f"dataset {dataset.slug!r} has no dataset_url")
        url = dataset.dataset_url

    by_key["download"].status = JobStageStatus.RUNNING
    await report()
    # Tens of MB of unzip + XML parse — keep it off the event loop.
    parsed = await asyncio.to_thread(redump.parse_dat, await redump.download_dat(url))
    by_key["download"].status = JobStageStatus.COMPLETED
    by_key["import"].status = JobStageStatus.RUNNING
    await report()

    async with ctx.sessionmaker() as session:
        signatures = await import_signatures(session, payload.dataset_id, parsed)
        await session.commit()

    by_key["import"].status = JobStageStatus.COMPLETED
    await report()
    return RefreshIdentificationDatasetResult(signatures=signatures)


register(
    JobKind.REFRESH_IDENTIFICATION_DATASET,
    JobHandler(
        RefreshIdentificationDatasetPayload,
        RefreshIdentificationDatasetProgress,
        RefreshIdentificationDatasetResult,
        run_refresh_identification_dataset,
    ),
)
