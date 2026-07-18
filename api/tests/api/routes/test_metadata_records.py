from uuid import UUID

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.job import Job, JobKind


async def test_renormalize_enqueues_and_guards_duplicates(
    db_session: AsyncSession, client: AsyncClient
):
    resp = await client.post("/api/v1/metadata-records/renormalize")
    assert resp.status_code == 202
    job = await db_session.get(Job, UUID(resp.json()["job_id"]))
    assert job is not None
    assert job.kind == JobKind.RENORMALIZE_METADATA

    # While that job is pending, a second enqueue is rejected.
    resp = await client.post("/api/v1/metadata-records/renormalize")
    assert resp.status_code == 409
