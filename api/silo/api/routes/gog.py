import uuid

import httpx
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from silo.api.dependencies import SessionDep
from silo.jobs import enqueue, job_active
from silo.jobs.handlers.gog_import import GogImportPayload
from silo.models.artifact import Artifact, ArtifactStatus
from silo.models.game import GameExternalIdentity
from silo.models.job import JobKind
from silo.models.library import Library
from silo.models.metadata_source import MetadataSource
from silo.schemas.gog import (
    GogAuthRequest,
    GogAuthUrlOut,
    GogImportRequest,
    GogStatusOut,
    OwnedGameOut,
)
from silo.schemas.job import JobEnqueuedOut
from silo.sources.gog import (
    GogClient,
    GogNotConnectedError,
    auth_url,
    clear_tokens,
    exchange_code,
    fresh_access_token,
    is_connected,
    request_interval,
    store_tokens,
)

router = APIRouter(prefix="/gog", tags=["gog"])


@router.get("/auth-url", operation_id="get_gog_auth_url")
async def get_gog_auth_url() -> GogAuthUrlOut:
    return GogAuthUrlOut(url=auth_url())


@router.post("/auth", operation_id="connect_gog")
async def connect_gog(session: SessionDep, body: GogAuthRequest) -> GogStatusOut:
    try:
        tokens = await exchange_code(body.code)
    except httpx.HTTPError:
        raise HTTPException(
            status_code=422, detail="authorization code was rejected by GOG"
        ) from None
    await store_tokens(session, tokens)
    return GogStatusOut(connected=True)


@router.delete("/auth", operation_id="disconnect_gog", status_code=204)
async def disconnect_gog(session: SessionDep) -> None:
    await clear_tokens(session)


@router.get("/status", operation_id="get_gog_status")
async def get_gog_status(session: SessionDep) -> GogStatusOut:
    return GogStatusOut(connected=await is_connected(session))


@router.get("/library", operation_id="get_gog_library")
async def get_gog_library(session: SessionDep) -> list[OwnedGameOut]:
    try:
        token = await fresh_access_token(session)
    except GogNotConnectedError:
        raise HTTPException(status_code=409, detail="GOG is not connected") from None
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="GOG token refresh failed") from None

    interval = await request_interval(session)
    # Persist the token rotation and release the write lock before the
    # multi-page upstream fetch (the CLAUDE.md write-lock gotcha).
    await session.commit()
    try:
        async with GogClient(token, request_interval_ms=interval) as client:
            owned = await client.owned_games()
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="GOG library fetch failed") from None

    gog_source_id = await session.scalar(
        select(MetadataSource.id).where(MetadataSource.slug == "gog")
    )
    identity_rows = (
        await session.execute(
            select(GameExternalIdentity.external_id, GameExternalIdentity.game_id).where(
                GameExternalIdentity.source_id == gog_source_id
            )
        )
    ).all()
    identified: dict[str, uuid.UUID] = {
        external_id: game_id for external_id, game_id in identity_rows
    }

    statuses: dict[uuid.UUID, list[ArtifactStatus]] = {}
    if identified:
        artifact_rows = (
            await session.execute(
                select(Artifact.game_id, Artifact.status).where(
                    Artifact.game_id.in_(identified.values())
                )
            )
        ).all()
        for game_id, status in artifact_rows:
            statuses.setdefault(game_id, []).append(status)

    def flags(gog_id: int) -> tuple[bool, bool]:
        game_id = identified.get(str(gog_id))
        if game_id is None:
            return False, False
        game_statuses = statuses.get(game_id, [])
        complete = bool(game_statuses) and all(
            status == ArtifactStatus.STORED for status in game_statuses
        )
        return True, complete

    library: list[OwnedGameOut] = []
    for game in owned:
        imported, complete = flags(game.id)
        library.append(
            OwnedGameOut(
                gog_id=game.id,
                title=game.title,
                slug=game.slug,
                image_url=game.image_url,
                imported=imported,
                complete=complete,
            )
        )
    return library


@router.post("/import", operation_id="import_gog_game", status_code=202)
async def import_gog_game(session: SessionDep, body: GogImportRequest) -> JobEnqueuedOut:
    if await session.get(Library, body.library_id) is None:
        raise HTTPException(status_code=422, detail=f"library {body.library_id} not found")
    if await job_active(session, JobKind.GOG_IMPORT, {"gog_id": body.gog_id}):
        raise HTTPException(
            status_code=409, detail=f"an import for GOG game {body.gog_id} is already queued"
        )
    job = await enqueue(
        session,
        JobKind.GOG_IMPORT,
        GogImportPayload(gog_id=body.gog_id, library_id=body.library_id),
    )
    return JobEnqueuedOut(job_id=job.id)
