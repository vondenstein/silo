import pytest
from sqlalchemy import text

from silo.models.job import Job, JobKind, JobStatus


async def test_lifespan_configures_db(client, app):
    async with app.state.sessionmaker() as session:
        assert (await session.execute(text("SELECT 1"))).scalar_one() == 1


async def test_lifespan_reconciles_interrupted_jobs(
    app, session_factory, monkeypatch: pytest.MonkeyPatch
):
    # A job left RUNNING by a crash must flip to INTERRUPTED on boot — pins
    # the lifespan wiring, not just the reconcile helper.
    async with session_factory() as session:
        job = Job(kind=JobKind.RENORMALIZE_METADATA, status=JobStatus.RUNNING, payload={})
        session.add(job)
        await session.commit()
        job_id = job.id

    monkeypatch.setattr("silo.app.start_worker", lambda _app: None)

    async def _stop_worker_noop(_app) -> None:
        return None

    monkeypatch.setattr("silo.app.stop_worker", _stop_worker_noop)
    async with app.router.lifespan_context(app):
        async with app.state.sessionmaker() as session:
            fresh = await session.get(Job, job_id)
            assert fresh is not None
            assert fresh.status == JobStatus.INTERRUPTED
