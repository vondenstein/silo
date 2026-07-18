import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from silo.jobs.handlers.refresh_identification_datasets import (
    RefreshIdentificationDatasetsPayload,
)
from silo.jobs.worker import enqueue, run_next_job
from silo.models.identification import (
    IdentificationDataset,
    IdentificationSignature,
    IdentificationSource,
)
from silo.models.job import Job, JobKind, JobStatus

SessionFactory = async_sessionmaker[AsyncSession]

DAT = b"""<?xml version="1.0"?>
<datafile>
  <header><version>v1</version></header>
  <game name="Doom (USA)">
    <rom name="Doom (USA).bin" size="1000" crc="aabbccdd" md5="a1" sha1="b2"/>
  </game>
</datafile>
"""


async def _seed_datasets(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        source_id = await session.scalar(
            select(IdentificationSource.id).where(IdentificationSource.slug == "redump")
        )
        assert source_id is not None
        session.add_all(
            [
                IdentificationDataset(
                    id=uuid.uuid4(),
                    source_id=source_id,
                    slug="redump-dc",
                    name="Dreamcast",
                    dataset_url="http://redump.org/datfile/dc/",
                    enabled=True,
                ),
                IdentificationDataset(
                    id=uuid.uuid4(),
                    source_id=source_id,
                    slug="redump-psx",
                    name="PlayStation",
                    dataset_url="http://redump.org/datfile/psx/",
                    enabled=True,
                ),
                IdentificationDataset(
                    id=uuid.uuid4(),
                    source_id=source_id,
                    slug="redump-ss",
                    name="Saturn",
                    dataset_url="http://redump.org/datfile/ss/",
                    enabled=False,
                ),
            ]
        )
        await session.commit()


async def _run_sweep(session_factory: SessionFactory, settings) -> Job:
    async with session_factory() as session:
        job = await enqueue(
            session,
            JobKind.REFRESH_IDENTIFICATION_DATASETS,
            RefreshIdentificationDatasetsPayload(),
        )
        await session.commit()
        job_id = job.id
    assert await run_next_job(session_factory, settings) is True
    async with session_factory() as session:
        finished = await session.get(Job, job_id)
        assert finished is not None
        return finished


async def test_sweep_refreshes_enabled_and_continues_on_error(
    client: AsyncClient,
    session_factory: SessionFactory,
    settings,
    monkeypatch: pytest.MonkeyPatch,
):
    await _seed_datasets(session_factory)

    async def fake_download(url: str) -> bytes:
        if "psx" in url:
            raise RuntimeError("boom")
        return DAT

    monkeypatch.setattr("silo.sources.redump.download_dat", fake_download)

    job = await _run_sweep(session_factory, settings)
    assert job.status == JobStatus.COMPLETED
    assert job.result == {"refreshed": 1, "failed": ["redump-psx"]}
    assert [(s["key"], s["group"], s["status"]) for s in job.progress["stages"]] == [
        ("redump-dc", "Redump", "completed"),
        ("redump-psx", "Redump", "failed"),
    ]
    assert "boom" in job.progress["stages"][1]["error"]
    async with session_factory() as session:
        signatures = (await session.scalars(select(IdentificationSignature))).all()
        assert len(signatures) == 1
        datasets = {d.slug: d for d in await session.scalars(select(IdentificationDataset))}
        assert datasets["redump-dc"].dataset_version == "v1"
        assert datasets["redump-dc"].refreshed_at is not None
        assert datasets["redump-psx"].refreshed_at is None
        assert datasets["redump-ss"].refreshed_at is None


async def test_sweep_fails_when_every_dataset_fails(
    client: AsyncClient,
    session_factory: SessionFactory,
    settings,
    monkeypatch: pytest.MonkeyPatch,
):
    await _seed_datasets(session_factory)

    async def broken(url: str) -> bytes:
        raise RuntimeError("down")

    monkeypatch.setattr("silo.sources.redump.download_dat", broken)

    job = await _run_sweep(session_factory, settings)
    assert job.status == JobStatus.FAILED
    assert job.error is not None and "every dataset refresh failed" in job.error


async def test_sweep_without_enabled_datasets_fails(
    client: AsyncClient, session_factory: SessionFactory, settings
):
    job = await _run_sweep(session_factory, settings)
    assert job.status == JobStatus.FAILED
    assert job.error is not None and "no enabled datasets" in job.error
