import asyncio
import logging
import uuid
from contextlib import suppress
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from silo.jobs.registry import REGISTRY, JobContext
from silo.models.base import utcnow
from silo.models.job import Job, JobKind, JobStatus
from silo.settings import Settings

POLL_INTERVAL_SECONDS = 1.0

SessionFactory = async_sessionmaker[AsyncSession]

logger = logging.getLogger(__name__)


async def enqueue(session: AsyncSession, kind: JobKind, payload: BaseModel) -> Job:
    """Queue a job."""
    job = Job(kind=kind, payload=payload.model_dump(mode="json"))
    session.add(job)
    await session.flush()
    return job


async def job_active(
    session: AsyncSession, kind: JobKind, match: dict[str, Any] | None = None
) -> bool:
    """Whether a pending/running job of the kind exists (payload-matched, if given)."""
    stmt = select(Job.payload).where(
        Job.kind == kind, Job.status.in_((JobStatus.PENDING, JobStatus.RUNNING))
    )
    if match is None:
        return await session.scalar(stmt.limit(1)) is not None
    payloads = await session.scalars(stmt)
    return any(
        all(payload.get(key) == value for key, value in match.items()) for payload in payloads
    )


async def _claim_next(sessionmaker: SessionFactory) -> Job | None:
    """Atomically claim the oldest pending job."""
    stmt = (
        update(Job)
        .where(
            Job.id.in_(
                select(Job.id)
                .where(Job.status == JobStatus.PENDING)
                .order_by(Job.created_at)
                .limit(1)
            ),
            # Not redundant: the atomic-claim double-check — a second worker
            # racing this UPDATE must find zero rows, not re-claim the job.
            Job.status == JobStatus.PENDING,
        )
        .values(status=JobStatus.RUNNING, claimed_at=utcnow())
        .returning(Job)
    )
    async with sessionmaker() as session:
        job = (await session.scalars(stmt)).first()
        await session.commit()
        return job


async def _finish(
    sessionmaker: SessionFactory,
    job_id: uuid.UUID,
    status: JobStatus,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    async with sessionmaker() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        job.status = status
        job.result = result
        job.error = error
        if status == JobStatus.FAILED and isinstance(job.progress, dict):
            # The UI must never show a running stage under a failed job.
            stages = job.progress.get("stages")
            if isinstance(stages, list):
                job.progress = {
                    **job.progress,
                    "stages": [
                        {**stage, "status": "failed"}
                        if isinstance(stage, dict) and stage.get("status") == "running"
                        else stage
                        for stage in stages
                    ],
                }
        await session.commit()


async def run_next_job(sessionmaker: SessionFactory, settings: Settings) -> bool:
    """Claim and run the oldest pending job; True if one ran."""
    job = await _claim_next(sessionmaker)
    if job is None:
        return False

    handler = REGISTRY.get(job.kind)
    if handler is None:
        await _finish(
            sessionmaker,
            job.id,
            JobStatus.FAILED,
            error=f"no handler registered for kind {job.kind}",
        )
        return True

    try:
        payload = handler.payload_model.model_validate(job.payload)
        result = await handler.run(
            JobContext(job_id=job.id, sessionmaker=sessionmaker, settings=settings), payload
        )
        await _finish(
            sessionmaker,
            job.id,
            JobStatus.COMPLETED,
            result=result.model_dump(mode="json"),
        )
    except Exception as exc:
        # A handler error must never kill the worker.
        logger.exception("job %s (%s) failed", job.id, job.kind)
        await _finish(sessionmaker, job.id, JobStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
    return True


async def reconcile_interrupted(sessionmaker: SessionFactory) -> None:
    """Mark orphaned running jobs interrupted (a previous process died mid-run)."""
    async with sessionmaker() as session:
        await session.execute(
            update(Job).where(Job.status == JobStatus.RUNNING).values(status=JobStatus.INTERRUPTED)
        )
        await session.commit()


async def _worker_loop(sessionmaker: SessionFactory, settings: Settings) -> None:
    while True:
        try:
            ran = await run_next_job(sessionmaker, settings)
        except Exception:
            # An infra error (claim, finish) must never kill the worker either.
            logger.exception("worker iteration failed")
            ran = False
        if not ran:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


def start_worker(app: FastAPI) -> None:
    """Start the background worker task."""
    app.state.job_worker = asyncio.create_task(
        _worker_loop(app.state.sessionmaker, app.state.settings)
    )


async def stop_worker(app: FastAPI) -> None:
    """Cancel the worker task and wait for it to exit."""
    task: asyncio.Task[None] = app.state.job_worker
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
