from fastapi import APIRouter, HTTPException

from silo.api.dependencies import SessionDep
from silo.jobs import enqueue, job_active
from silo.jobs.handlers.renormalize_metadata import RenormalizeMetadataPayload
from silo.models.job import JobKind
from silo.schemas.job import JobEnqueuedOut

router = APIRouter(prefix="/metadata-records", tags=["metadata-records"])


@router.post("/renormalize", operation_id="renormalize_metadata", status_code=202)
async def renormalize_metadata(session: SessionDep) -> JobEnqueuedOut:
    if await job_active(session, JobKind.RENORMALIZE_METADATA):
        raise HTTPException(status_code=409, detail="a re-normalize job is already queued")
    job = await enqueue(session, JobKind.RENORMALIZE_METADATA, RenormalizeMetadataPayload())
    return JobEnqueuedOut(job_id=job.id)
