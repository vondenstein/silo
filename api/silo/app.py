from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.types import Scope

from silo.api.routes.assets import router as assets_router
from silo.api.routes.files import router as files_router
from silo.api.routes.game_assets import router as game_assets_router
from silo.api.routes.games import router as games_router
from silo.api.routes.gog import router as gog_router
from silo.api.routes.health import router as health_router
from silo.api.routes.identification import (
    datasets_router as identification_datasets_router,
)
from silo.api.routes.identification import (
    sources_router as identification_sources_router,
)
from silo.api.routes.igdb import router as igdb_router
from silo.api.routes.jobs import router as jobs_router
from silo.api.routes.libraries import router as libraries_router
from silo.api.routes.metadata_records import router as metadata_records_router
from silo.api.routes.metadata_sources import router as metadata_sources_router
from silo.api.routes.secrets import router as secrets_router
from silo.api.routes.upload import router as upload_router
from silo.db import close_db, open_db, run_migrations
from silo.jobs import reconcile_interrupted, start_worker, stop_worker
from silo.seed import (
    seed_identification_sources,
    seed_implicit_user,
    seed_metadata_sources,
    seed_platforms,
)
from silo.settings import Settings

API_V1 = "/api/v1"


class SpaStaticFiles(StaticFiles):
    """Serves the built web app; non-API misses fall back to index.html."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """App lifespan."""
    settings = app.state.settings
    run_migrations(settings)
    open_db(app, settings.db_url_async)
    async with app.state.sessionmaker() as session:
        await seed_implicit_user(session)
        await seed_metadata_sources(session)
        await seed_platforms(session)
        await seed_identification_sources(session)
        await session.commit()
    await reconcile_interrupted(app.state.sessionmaker)
    start_worker(app)
    yield
    await stop_worker(app)
    await close_db(app)


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = Settings()

    app = FastAPI(title="Silo", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    for router in (
        health_router,
        libraries_router,
        games_router,
        game_assets_router,
        metadata_sources_router,
        metadata_records_router,
        secrets_router,
        assets_router,
        upload_router,
        files_router,
        gog_router,
        igdb_router,
        jobs_router,
        identification_sources_router,
        identification_datasets_router,
    ):
        app.include_router(router, prefix=API_V1)
    if settings.web_dist_dir is not None:
        app.mount("/", SpaStaticFiles(directory=settings.web_dist_dir, html=True))
    return app
