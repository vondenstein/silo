from datetime import datetime
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.job import Job, JobKind, JobStatus


def _job(status: JobStatus, created_at: datetime, kind: JobKind = JobKind.GOG_IMPORT) -> Job:
    return Job(
        id=uuid4(),
        kind=kind,
        status=status,
        payload={"gog_id": 1},
        created_at=created_at,
        updated_at=created_at,
    )


async def _seed(session: AsyncSession, *jobs: Job) -> None:
    session.add_all(jobs)
    await session.commit()


async def test_list_jobs_empty(client: AsyncClient):
    resp = await client.get("/api/v1/jobs")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "next_cursor": None}


async def test_list_jobs_orders_newest_first(db_session: AsyncSession, client: AsyncClient):
    t = datetime(2025, 1, 1)
    await _seed(
        db_session,
        _job(JobStatus.COMPLETED, t.replace(day=1)),
        _job(JobStatus.RUNNING, t.replace(day=2)),
        _job(JobStatus.PENDING, t.replace(day=3)),
    )

    resp = await client.get("/api/v1/jobs")
    body = resp.json()
    assert [item["status"] for item in body["items"]] == ["pending", "running", "completed"]


async def test_list_jobs_filters_by_status(db_session: AsyncSession, client: AsyncClient):
    t = datetime(2025, 1, 1)
    await _seed(
        db_session,
        _job(JobStatus.COMPLETED, t.replace(day=1)),
        _job(JobStatus.RUNNING, t.replace(day=2)),
        _job(JobStatus.PENDING, t.replace(day=3)),
    )

    resp = await client.get("/api/v1/jobs?status=pending&status=running")
    body = resp.json()
    assert [item["status"] for item in body["items"]] == ["pending", "running"]


async def test_list_jobs_filters_by_kind(db_session: AsyncSession, client: AsyncClient):
    t = datetime(2025, 1, 1)
    await _seed(
        db_session,
        _job(JobStatus.PENDING, t.replace(day=1), kind=JobKind.RENORMALIZE_METADATA),
        _job(JobStatus.PENDING, t.replace(day=2), kind=JobKind.GOG_IMPORT),
    )

    resp = await client.get("/api/v1/jobs?kind=gog_import")
    body = resp.json()
    assert [item["kind"] for item in body["items"]] == ["gog_import"]


async def test_list_jobs_pagination(db_session: AsyncSession, client: AsyncClient):
    t = datetime(2025, 1, 1)
    await _seed(db_session, *[_job(JobStatus.PENDING, t.replace(day=i + 1)) for i in range(3)])

    resp = await client.get("/api/v1/jobs?limit=2")
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"] is not None

    resp = await client.get(f"/api/v1/jobs?limit=2&cursor={body['next_cursor']}")
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["next_cursor"] is None


async def test_get_job(db_session: AsyncSession, client: AsyncClient):
    job = _job(JobStatus.COMPLETED, datetime(2025, 1, 1))
    job.result = {"game_id": "x"}
    await _seed(db_session, job)

    resp = await client.get(f"/api/v1/jobs/{job.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "gog_import"
    assert body["payload"] == {"gog_id": 1}
    assert body["result"] == {"game_id": "x"}


async def test_get_job_not_found(client: AsyncClient):
    resp = await client.get(f"/api/v1/jobs/{uuid4()}")
    assert resp.status_code == 404
