import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from silo.api.dependencies import SessionDep, get_or_404
from silo.api.pagination import PaginationData, keyset_clause, slice_page
from silo.models.game import Game as GameModel
from silo.models.library import Library as LibraryModel
from silo.schemas.library import Library as LibrarySchema
from silo.schemas.library import LibraryCreate, LibraryPatch
from silo.schemas.pagination import Page
from silo.services.upload import RESERVED_LIBRARY_SLUGS

router = APIRouter(prefix="/libraries", tags=["libraries"])


@router.get("", operation_id="list_libraries")
async def list_libraries(
    session: SessionDep,
    params: Annotated[PaginationData, Query()],
) -> Page[LibrarySchema]:
    stmt = (
        select(LibraryModel)
        .order_by(LibraryModel.created_at.desc(), LibraryModel.id.desc())
        .limit(params.limit + 1)
    )
    if params.cursor:
        stmt = stmt.where(keyset_clause(LibraryModel, params.cursor))
    rows = (await session.scalars(stmt)).all()
    items, next_cursor = slice_page(rows, params.limit)
    return Page[LibrarySchema](
        items=[LibrarySchema.model_validate(library) for library in items],
        next_cursor=next_cursor,
    )


@router.post("", operation_id="create_library", status_code=201)
async def create_library(
    session: SessionDep,
    body: LibraryCreate,
) -> LibrarySchema:
    if body.slug in RESERVED_LIBRARY_SLUGS:
        raise HTTPException(status_code=422, detail=f"slug {body.slug!r} is reserved")
    library = LibraryModel(slug=body.slug, name=body.name)
    session.add(library)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"library with slug '{body.slug}' already exists",
        ) from None
    return LibrarySchema.model_validate(library)


@router.get("/{library_id}", operation_id="get_library")
async def get_library(
    session: SessionDep,
    library_id: uuid.UUID,
) -> LibrarySchema:
    library = await get_or_404(session, LibraryModel, library_id, "library")
    return LibrarySchema.model_validate(library)


@router.patch("/{library_id}", operation_id="update_library")
async def update_library(
    session: SessionDep,
    library_id: uuid.UUID,
    body: LibraryPatch,
) -> LibrarySchema:
    library = await get_or_404(session, LibraryModel, library_id, "library")
    library.name = body.name
    await session.flush()
    return LibrarySchema.model_validate(library)


@router.delete("/{library_id}", operation_id="delete_library", status_code=204)
async def delete_library(
    session: SessionDep,
    library_id: uuid.UUID,
) -> None:
    library = await get_or_404(session, LibraryModel, library_id, "library")
    has_games = await session.scalar(
        select(GameModel.id).where(GameModel.library_id == library_id).limit(1)
    )
    if has_games is not None:
        raise HTTPException(status_code=409, detail="library still contains games")
    await session.delete(library)
    await session.flush()
