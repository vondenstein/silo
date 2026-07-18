from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from silo.app import create_app
from silo.db import install_sqlite_pragmas, run_migrations
from silo.settings import Settings


@pytest.fixture
def settings(tmp_path: Path):
    data = tmp_path / "data"
    games = tmp_path / "games"
    data.mkdir()
    games.mkdir()
    return Settings(data_dir=data, library_dir=games)


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
async def client(app, monkeypatch):
    # The app worker would race tests that claim or inspect jobs themselves;
    # tests/jobs/test_worker.py covers the real loop end-to-end.
    monkeypatch.setattr("silo.app.start_worker", lambda _app: None)

    async def _stop_worker_noop(_app) -> None:
        return None

    monkeypatch.setattr("silo.app.stop_worker", _stop_worker_noop)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
async def session_factory(settings):
    run_migrations(settings)
    engine = create_async_engine(settings.db_url_async)
    install_sqlite_pragmas(engine)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def db_session(session_factory):
    async with session_factory() as session:
        yield session
