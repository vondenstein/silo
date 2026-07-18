from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.identification import (
    IdentificationDataset,
    IdentificationSignature,
    IdentificationSource,
)
from silo.models.job import Job, JobKind
from silo.sources.redump import RedumpSystem


async def _redump_source_id(db_session: AsyncSession) -> UUID:
    source_id = await db_session.scalar(
        select(IdentificationSource.id).where(IdentificationSource.slug == "redump")
    )
    assert source_id is not None
    return source_id


async def test_discover_datasets_creates_and_updates(
    db_session: AsyncSession, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    systems = [
        RedumpSystem(slug="psx", name="PlayStation", dat_url="http://redump.org/datfile/psx/"),
        RedumpSystem(slug="dc", name="Dreamcast", dat_url="http://redump.org/datfile/dc/"),
    ]

    async def fake_fetch() -> list[RedumpSystem]:
        return systems

    monkeypatch.setattr("silo.sources.redump.fetch_systems", fake_fetch)

    resp = await client.post("/api/v1/identification-sources/redump/discover-datasets")
    assert resp.status_code == 200
    assert resp.json() == {"dataset_count": 2}

    rows = (await client.get("/api/v1/identification-datasets")).json()
    assert [(d["slug"], d["name"], d["enabled"], d["signature_count"]) for d in rows] == [
        ("redump-dc", "Dreamcast", False, 0),
        ("redump-psx", "PlayStation", False, 0),
    ]
    assert all(d["source_slug"] == "redump" for d in rows)

    # Re-discovery updates names/urls but never flips enabled.
    dataset_id = UUID(rows[1]["id"])
    await client.patch(f"/api/v1/identification-datasets/{dataset_id}", json={"enabled": True})
    systems[0] = RedumpSystem(
        slug="psx", name="Sony PlayStation", dat_url="http://redump.org/datfile/psx/"
    )
    assert (
        await client.post("/api/v1/identification-sources/redump/discover-datasets")
    ).status_code == 200
    rows = (await client.get("/api/v1/identification-datasets")).json()
    by_slug = {d["slug"]: d for d in rows}
    assert by_slug["redump-psx"]["name"] == "Sony PlayStation"
    assert by_slug["redump-psx"]["enabled"] is True


async def test_discover_datasets_unknown_source(client: AsyncClient):
    resp = await client.post("/api/v1/identification-sources/nope/discover-datasets")
    assert resp.status_code == 404


async def test_discover_datasets_upstream_failure(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def broken() -> list[RedumpSystem]:
        raise RuntimeError("boom")

    monkeypatch.setattr("silo.sources.redump.fetch_systems", broken)

    resp = await client.post("/api/v1/identification-sources/redump/discover-datasets")
    assert resp.status_code == 502


async def test_update_dataset_and_counts(db_session: AsyncSession, client: AsyncClient):
    source_id = await _redump_source_id(db_session)
    dataset = IdentificationDataset(
        id=uuid4(), source_id=source_id, slug="redump-psx", name="PlayStation"
    )
    db_session.add(dataset)
    db_session.add(
        IdentificationSignature(
            id=uuid4(), dataset_id=dataset.id, game_name="Doom (USA)", file_name="Doom (USA).bin"
        )
    )
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/identification-datasets/{dataset.id}", json={"enabled": False}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["signature_count"] == 1
    assert body["source_slug"] == "redump"

    resp = await client.patch(f"/api/v1/identification-datasets/{uuid4()}", json={"enabled": True})
    assert resp.status_code == 404


async def test_refresh_dataset_enqueues_and_guards(db_session: AsyncSession, client: AsyncClient):
    source_id = await _redump_source_id(db_session)
    with_url = IdentificationDataset(
        id=uuid4(),
        source_id=source_id,
        slug="redump-psx",
        name="PlayStation",
        dataset_url="http://redump.org/datfile/psx/",
    )
    without_url = IdentificationDataset(
        id=uuid4(), source_id=source_id, slug="local-dat", name="Local"
    )
    db_session.add_all([with_url, without_url])
    await db_session.commit()

    resp = await client.post(f"/api/v1/identification-datasets/{with_url.id}/refresh")
    assert resp.status_code == 202
    job = await db_session.get(Job, UUID(resp.json()["job_id"]))
    assert job is not None
    assert job.kind == JobKind.REFRESH_IDENTIFICATION_DATASET

    # While that job is pending, a second enqueue is rejected.
    resp = await client.post(f"/api/v1/identification-datasets/{with_url.id}/refresh")
    assert resp.status_code == 409

    assert (
        await client.post(f"/api/v1/identification-datasets/{without_url.id}/refresh")
    ).status_code == 409
    assert (
        await client.post(f"/api/v1/identification-datasets/{uuid4()}/refresh")
    ).status_code == 404


async def test_refresh_all_enqueues_and_guards(db_session: AsyncSession, client: AsyncClient):
    source_id = await _redump_source_id(db_session)
    no_url = IdentificationDataset(
        id=uuid4(), source_id=source_id, slug="local-dat", name="Local", enabled=True
    )
    disabled = IdentificationDataset(
        id=uuid4(),
        source_id=source_id,
        slug="redump-dc",
        name="Dreamcast",
        dataset_url="http://redump.org/datfile/dc/",
        enabled=False,
    )
    db_session.add_all([no_url, disabled])
    await db_session.commit()

    # Nothing enabled with a dataset_url yet.
    assert (await client.post("/api/v1/identification-datasets/refresh")).status_code == 409

    await client.patch(f"/api/v1/identification-datasets/{disabled.id}", json={"enabled": True})
    resp = await client.post("/api/v1/identification-datasets/refresh")
    assert resp.status_code == 202
    job = await db_session.get(Job, UUID(resp.json()["job_id"]))
    assert job is not None
    assert job.kind == JobKind.REFRESH_IDENTIFICATION_DATASETS
    assert job.payload == {}

    # While that job is pending, a second sweep is rejected.
    assert (await client.post("/api/v1/identification-datasets/refresh")).status_code == 409
