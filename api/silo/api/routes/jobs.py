import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from silo.api.dependencies import SessionDep, get_or_404
from silo.api.pagination import PaginationData, keyset_clause, slice_page
from silo.models.job import Job as JobModel
from silo.models.job import JobKind, JobStatus
from silo.schemas.job import Job
from silo.schemas.pagination import Page

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobListParams(PaginationData):
    """Query params for `GET /jobs`: pagination + kind/status filters."""

    kind: JobKind | None = None
    status: list[JobStatus] | None = None


@router.get("", operation_id="list_jobs")
async def list_jobs(
    session: SessionDep,
    params: Annotated[JobListParams, Query()],
) -> Page[Job]:
    stmt = (
        select(JobModel)
        .order_by(JobModel.created_at.desc(), JobModel.id.desc())
        .limit(params.limit + 1)
    )
    if params.kind is not None:
        stmt = stmt.where(JobModel.kind == params.kind)
    if params.status:
        stmt = stmt.where(JobModel.status.in_(params.status))
    if params.cursor:
        stmt = stmt.where(keyset_clause(JobModel, params.cursor))
    rows = (await session.scalars(stmt)).all()
    items, next_cursor = slice_page(rows, params.limit)
    return Page[Job](
        items=[Job.model_validate(job) for job in items],
        next_cursor=next_cursor,
    )


@router.get("/{job_id}", operation_id="get_job")
async def get_job(session: SessionDep, job_id: uuid.UUID) -> Job:
    job = await get_or_404(session, JobModel, job_id, "job")
    return Job.model_validate(job)
