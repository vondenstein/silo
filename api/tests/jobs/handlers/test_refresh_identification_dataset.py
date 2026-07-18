import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from silo.jobs.handlers.refresh_identification_dataset import (
    RefreshIdentificationDatasetPayload,
)
from silo.jobs.worker import enqueue, run_next_job
from silo.models.identification import (
    IdentificationDataset,
    IdentificationSignature,
    IdentificationSource,
)
from silo.models.job import Job, JobKind, JobStatus

SessionFactory = async_sessionmaker[AsyncSession]

DAT_V1 = b"""<?xml version="1.0"?>
<datafile>
  <header><version>v1</version></header>
  <game name="Doom (USA)">
    <rom name="Doom (USA).bin" size="1000" crc="aabbccdd" md5="a1" sha1="b2"/>
    <rom name="Doom (USA).cue" size="100" crc="11223344" md5="c3" sha1="d4"/>
  </game>
  <game name="Quake (Europe)">
    <rom name="Quake (Europe).bin" size="2000" crc="55667788" md5="e5" sha1="f6"/>
  </game>
</datafile>
"""

# v2: Quake is gone, Doom's .bin hash changed, Hexen is new.
DAT_V2 = b"""<?xml version="1.0"?>
<datafile>
  <header><version>v2</version></header>
  <game name="Doom (USA)">
    <rom name="Doom (USA).bin" size="1000" crc="ffffffff" md5="a1-new" sha1="b2-new"/>
    <rom name="Doom (USA).cue" size="100" crc="11223344" md5="c3" sha1="d4"/>
  </game>
  <game name="Hexen (USA)">
    <rom name="Hexen (USA).bin" size="3000" crc="99999999" md5="99" sha1="98"/>
  </game>
</datafile>
"""


async def _seed_dataset(session_factory: SessionFactory) -> uuid.UUID:
    async with session_factory() as session:
        source_id = await session.scalar(
            select(IdentificationSource.id).where(IdentificationSource.slug == "redump")
        )
        assert source_id is not None
        dataset = IdentificationDataset(
            id=uuid.uuid4(),
            source_id=source_id,
            slug="redump-psx",
            name="PlayStation",
            dataset_url="http://redump.org/datfile/psx/",
        )
        session.add(dataset)
        await session.commit()
        return dataset.id


async def _run_refresh(session_factory: SessionFactory, settings, dataset_id: uuid.UUID) -> Job:
    async with session_factory() as session:
        job = await enqueue(
            session,
            JobKind.REFRESH_IDENTIFICATION_DATASET,
            RefreshIdentificationDatasetPayload(dataset_id=dataset_id),
        )
        await session.commit()
        job_id = job.id
    assert await run_next_job(session_factory, settings) is True
    async with session_factory() as session:
        finished = await session.get(Job, job_id)
        assert finished is not None
        return finished


async def test_refresh_imports_then_reconciles(
    client: AsyncClient,
    session_factory: SessionFactory,
    settings,
    monkeypatch: pytest.MonkeyPatch,
):
    dataset_id = await _seed_dataset(session_factory)
    payloads = iter([DAT_V1, DAT_V2])

    async def fake_download(url: str) -> bytes:
        assert url == "http://redump.org/datfile/psx/"
        return next(payloads)

    monkeypatch.setattr("silo.sources.redump.download_dat", fake_download)

    first = await _run_refresh(session_factory, settings, dataset_id)
    assert first.status == JobStatus.COMPLETED
    assert first.result == {"signatures": 3}
    assert [(s["key"], s["status"]) for s in first.progress["stages"]] == [
        ("download", "completed"),
        ("import", "completed"),
    ]
    async with session_factory() as session:
        rows = {
            (row.game_name, row.file_name): row
            for row in await session.scalars(select(IdentificationSignature))
        }
        assert len(rows) == 3
        dataset = await session.get(IdentificationDataset, dataset_id)
        assert dataset is not None
        assert dataset.dataset_version == "v1"
        assert dataset.refreshed_at is not None

    second = await _run_refresh(session_factory, settings, dataset_id)
    assert second.result == {"signatures": 3}
    async with session_factory() as session:
        rows = {
            (row.game_name, row.file_name): row
            for row in await session.scalars(select(IdentificationSignature))
        }
        # Wholesale replace: Quake gone, Hexen added, changed hashes current.
        # (Signature ids are transient across refreshes — nothing stores them.)
        assert set(rows) == {
            ("Doom (USA)", "Doom (USA).bin"),
            ("Doom (USA)", "Doom (USA).cue"),
            ("Hexen (USA)", "Hexen (USA).bin"),
        }
        assert rows[("Doom (USA)", "Doom (USA).bin")].md5 == "a1-new"
        dataset = await session.get(IdentificationDataset, dataset_id)
        assert dataset is not None
        assert dataset.dataset_version == "v2"


async def test_refresh_missing_dataset_fails(
    client: AsyncClient, session_factory: SessionFactory, settings
):
    async with session_factory() as session:
        job = await enqueue(
            session,
            JobKind.REFRESH_IDENTIFICATION_DATASET,
            RefreshIdentificationDatasetPayload(dataset_id=uuid.uuid4()),
        )
        await session.commit()
        job_id = job.id

    assert await run_next_job(session_factory, settings) is True

    async with session_factory() as session:
        finished = await session.get(Job, job_id)
        assert finished is not None
        assert finished.status == JobStatus.FAILED
        assert finished.error is not None and "not found" in finished.error
