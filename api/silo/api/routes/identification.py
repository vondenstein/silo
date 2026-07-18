import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from silo.api.dependencies import SessionDep, get_or_404
from silo.jobs import enqueue, job_active
from silo.jobs.handlers.refresh_identification_dataset import (
    RefreshIdentificationDatasetPayload,
)
from silo.jobs.handlers.refresh_identification_datasets import (
    RefreshIdentificationDatasetsPayload,
)
from silo.models.identification import (
    IdentificationDataset,
    IdentificationSignature,
    IdentificationSource,
)
from silo.models.job import JobKind
from silo.schemas.identification import Dataset, DatasetPatch, DiscoverDatasetsOut
from silo.schemas.job import JobEnqueuedOut
from silo.sources import redump

sources_router = APIRouter(prefix="/identification-sources", tags=["identification"])
datasets_router = APIRouter(prefix="/identification-datasets", tags=["identification"])


@sources_router.post("/{slug}/discover-datasets", operation_id="discover_identification_datasets")
async def discover_datasets(session: SessionDep, slug: str) -> DiscoverDatasetsOut:
    source = await session.scalar(
        select(IdentificationSource).where(IdentificationSource.slug == slug)
    )
    if source is None:
        raise HTTPException(status_code=404, detail=f"identification source {slug!r} not found")
    if slug != "redump":
        raise HTTPException(status_code=422, detail=f"{slug!r} has no dataset discovery")
    try:
        systems = await redump.fetch_systems()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"failed to fetch redump systems: {type(exc).__name__}: {exc}",
        ) from exc
    existing = {
        dataset.slug: dataset
        for dataset in await session.scalars(
            select(IdentificationDataset).where(IdentificationDataset.source_id == source.id)
        )
    }
    for system in systems:
        dataset_slug = f"redump-{system.slug}"
        dataset = existing.get(dataset_slug)
        if dataset is None:
            session.add(
                IdentificationDataset(
                    id=uuid.uuid4(),
                    source_id=source.id,
                    slug=dataset_slug,
                    name=system.name,
                    dataset_url=system.dat_url,
                    enabled=False,
                )
            )
        else:
            dataset.name = system.name
            dataset.dataset_url = system.dat_url
    await session.flush()
    return DiscoverDatasetsOut(dataset_count=len(systems))


def _dataset_out(dataset: IdentificationDataset, source_slug: str, signature_count: int) -> Dataset:
    """The Dataset response shape (pure builder — both read paths use it)."""
    return Dataset(
        id=dataset.id,
        source_slug=source_slug,
        slug=dataset.slug,
        name=dataset.name,
        enabled=dataset.enabled,
        dataset_version=dataset.dataset_version,
        refreshed_at=dataset.refreshed_at,
        signature_count=signature_count,
    )


@datasets_router.get("", operation_id="list_identification_datasets")
async def list_datasets(session: SessionDep) -> list[Dataset]:
    counts = {
        dataset_id: count
        for dataset_id, count in await session.execute(
            select(IdentificationSignature.dataset_id, func.count()).group_by(
                IdentificationSignature.dataset_id
            )
        )
    }
    rows = (
        await session.execute(
            select(IdentificationDataset, IdentificationSource.slug)
            .join(IdentificationSource, IdentificationSource.id == IdentificationDataset.source_id)
            .order_by(IdentificationDataset.name)
        )
    ).all()
    return [
        _dataset_out(dataset, source_slug, counts.get(dataset.id, 0))
        for dataset, source_slug in rows
    ]


@datasets_router.patch("/{dataset_id}", operation_id="update_identification_dataset")
async def update_dataset(session: SessionDep, dataset_id: uuid.UUID, body: DatasetPatch) -> Dataset:
    dataset = await get_or_404(session, IdentificationDataset, dataset_id, "dataset")
    if body.enabled is not None:
        dataset.enabled = body.enabled
    await session.flush()
    source_slug = await session.scalar(
        select(IdentificationSource.slug).where(IdentificationSource.id == dataset.source_id)
    )
    signature_count = await session.scalar(
        select(func.count())
        .select_from(IdentificationSignature)
        .where(IdentificationSignature.dataset_id == dataset.id)
    )
    return _dataset_out(dataset, source_slug or "", signature_count or 0)


@datasets_router.post("/refresh", operation_id="refresh_identification_datasets", status_code=202)
async def refresh_datasets(session: SessionDep) -> JobEnqueuedOut:
    enabled = await session.scalar(
        select(func.count())
        .select_from(IdentificationDataset)
        .where(
            IdentificationDataset.enabled.is_(True),
            IdentificationDataset.dataset_url.is_not(None),
        )
    )
    if not enabled:
        raise HTTPException(status_code=409, detail="no enabled datasets to refresh")
    if await job_active(session, JobKind.REFRESH_IDENTIFICATION_DATASETS):
        raise HTTPException(status_code=409, detail="a dataset refresh is already queued")
    job = await enqueue(
        session, JobKind.REFRESH_IDENTIFICATION_DATASETS, RefreshIdentificationDatasetsPayload()
    )
    return JobEnqueuedOut(job_id=job.id)


@datasets_router.post(
    "/{dataset_id}/refresh", operation_id="refresh_identification_dataset", status_code=202
)
async def refresh_dataset(session: SessionDep, dataset_id: uuid.UUID) -> JobEnqueuedOut:
    dataset = await get_or_404(session, IdentificationDataset, dataset_id, "dataset")
    if dataset.dataset_url is None:
        raise HTTPException(status_code=409, detail=f"dataset {dataset.slug!r} has no dataset_url")
    if await job_active(
        session, JobKind.REFRESH_IDENTIFICATION_DATASET, {"dataset_id": str(dataset_id)}
    ):
        raise HTTPException(status_code=409, detail="a refresh for this dataset is already queued")
    job = await enqueue(
        session,
        JobKind.REFRESH_IDENTIFICATION_DATASET,
        RefreshIdentificationDatasetPayload(dataset_id=dataset_id),
    )
    return JobEnqueuedOut(job_id=job.id)
