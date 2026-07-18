import asyncio
import uuid
from datetime import datetime

import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from silo.jobs.registry import REGISTRY, JobContext, JobHandler
from silo.jobs.worker import enqueue, reconcile_interrupted, run_next_job
from silo.models.job import Job, JobKind, JobStatus
from silo.schemas.job import JobStage, JobStageStatus

SessionFactory = async_sessionmaker[AsyncSession]


class Payload(BaseModel):
    value: int = 0


class Progress(BaseModel):
    step: int


class Result(BaseModel):
    doubled: int


async def _noop(ctx: JobContext, payload: Payload) -> Result:
    await ctx.report_progress(Progress(step=1))
    return Result(doubled=payload.value * 2)


SCRATCH_KIND = JobKind.RENORMALIZE_METADATA


@pytest.fixture
def noop_registered():
    # Swap the real handler for a scratch one; the enum carries no test kind.
    saved = REGISTRY.get(SCRATCH_KIND)
    REGISTRY[SCRATCH_KIND] = JobHandler(Payload, Progress, Result, _noop)
    yield
    if saved is None:
        del REGISTRY[SCRATCH_KIND]
    else:
        REGISTRY[SCRATCH_KIND] = saved


async def _get_job(session_factory: SessionFactory, job_id: uuid.UUID) -> Job:
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        assert job is not None
        return job


async def test_enqueue_creates_pending_job(session_factory: SessionFactory):
    async with session_factory() as session:
        job = await enqueue(session, SCRATCH_KIND, Payload(value=3))
        await session.commit()

    fresh = await _get_job(session_factory, job.id)
    assert fresh.status == JobStatus.PENDING
    assert fresh.payload == {"value": 3}


async def test_run_next_job_completes(session_factory: SessionFactory, noop_registered, settings):
    async with session_factory() as session:
        job = await enqueue(session, SCRATCH_KIND, Payload(value=3))
        await session.commit()

    assert await run_next_job(session_factory, settings) is True

    fresh = await _get_job(session_factory, job.id)
    assert fresh.status == JobStatus.COMPLETED
    assert fresh.result == {"doubled": 6}
    assert fresh.progress == {"step": 1}
    assert fresh.claimed_at is not None


async def test_run_next_job_empty_queue(session_factory: SessionFactory, settings):
    assert await run_next_job(session_factory, settings) is False


async def test_run_next_job_claims_oldest_first(
    session_factory: SessionFactory, noop_registered, settings
):
    async with session_factory() as session:
        first = await enqueue(session, SCRATCH_KIND, Payload(value=1))
        second = await enqueue(session, SCRATCH_KIND, Payload(value=2))
        first.created_at = datetime(2025, 1, 1)
        second.created_at = datetime(2025, 1, 2)
        await session.commit()

    assert await run_next_job(session_factory, settings) is True
    assert (await _get_job(session_factory, first.id)).status == JobStatus.COMPLETED
    assert (await _get_job(session_factory, second.id)).status == JobStatus.PENDING


async def test_handler_error_fails_job_and_worker_survives(
    session_factory: SessionFactory, settings
):
    async def boom(ctx: JobContext, payload: Payload) -> Result:
        raise RuntimeError("boom")

    saved = REGISTRY.get(SCRATCH_KIND)
    REGISTRY[SCRATCH_KIND] = JobHandler(Payload, Progress, Result, boom)
    try:
        async with session_factory() as session:
            job = await enqueue(session, SCRATCH_KIND, Payload())
            await session.commit()

        assert await run_next_job(session_factory, settings) is True
        fresh = await _get_job(session_factory, job.id)
        assert fresh.status == JobStatus.FAILED
        assert fresh.error == "RuntimeError: boom"
        assert await run_next_job(session_factory, settings) is False
    finally:
        if saved is None:
            del REGISTRY[SCRATCH_KIND]
        else:
            REGISTRY[SCRATCH_KIND] = saved


async def test_unregistered_kind_fails(session_factory: SessionFactory, settings):
    saved = REGISTRY.pop(SCRATCH_KIND, None)
    async with session_factory() as session:
        job = await enqueue(session, SCRATCH_KIND, Payload())
        await session.commit()

    try:
        assert await run_next_job(session_factory, settings) is True
    finally:
        if saved is not None:
            REGISTRY[SCRATCH_KIND] = saved
    fresh = await _get_job(session_factory, job.id)
    assert fresh.status == JobStatus.FAILED
    assert fresh.error is not None and "no handler registered" in fresh.error


async def test_reconcile_marks_running_interrupted(session_factory: SessionFactory):
    async with session_factory() as session:
        job = await enqueue(session, SCRATCH_KIND, Payload())
        job.status = JobStatus.RUNNING
        await session.commit()

    await reconcile_interrupted(session_factory)
    fresh = await _get_job(session_factory, job.id)
    assert fresh.status == JobStatus.INTERRUPTED


async def test_failed_job_flips_running_stages(session_factory: SessionFactory, settings):
    class StagesProgress(BaseModel):
        stages: list[JobStage]

    async def dies_mid_stage(ctx: JobContext, payload: Payload) -> Result:
        await ctx.report_progress(
            StagesProgress(
                stages=[
                    JobStage(key="a", label="A", group="T", status=JobStageStatus.COMPLETED),
                    JobStage(key="b", label="B", group="T", status=JobStageStatus.RUNNING),
                ]
            )
        )
        raise RuntimeError("mid-stage death")

    saved = REGISTRY.get(SCRATCH_KIND)
    REGISTRY[SCRATCH_KIND] = JobHandler(Payload, StagesProgress, Result, dies_mid_stage)
    try:
        async with session_factory() as session:
            job = await enqueue(session, SCRATCH_KIND, Payload())
            await session.commit()

        assert await run_next_job(session_factory, settings) is True
        fresh = await _get_job(session_factory, job.id)
        assert fresh.status == JobStatus.FAILED
        assert fresh.progress is not None
        assert [s["status"] for s in fresh.progress["stages"]] == ["completed", "failed"]
    finally:
        if saved is None:
            del REGISTRY[SCRATCH_KIND]
        else:
            REGISTRY[SCRATCH_KIND] = saved


async def test_lifespan_worker_processes_pending_job(
    app, session_factory: SessionFactory, noop_registered
):
    async with session_factory() as session:
        job = await enqueue(session, SCRATCH_KIND, Payload(value=4))
        await session.commit()
        job_id = job.id

    async with app.router.lifespan_context(app):
        for _ in range(100):
            fresh = await _get_job(session_factory, job_id)
            if fresh.status not in (JobStatus.PENDING, JobStatus.RUNNING):
                break
            await asyncio.sleep(0.05)

    assert fresh.status == JobStatus.COMPLETED
    assert fresh.result == {"doubled": 8}
