import uuid
from typing import Annotated, Any, get_args, get_origin

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from silo.api.dependencies import SessionDep, get_or_404
from silo.api.pagination import PaginationData, keyset_clause, slice_page
from silo.jobs import enqueue, job_active
from silo.jobs.handlers.fetch_metadata import FetchMetadataPayload
from silo.models.artifact import Artifact
from silo.models.asset import AssetKind
from silo.models.field_lock import FieldKey, FieldLock
from silo.models.file import File
from silo.models.game import CompanyRole, GameExternalIdentity, GameMetadata
from silo.models.game import Game as GameModel
from silo.models.job import JobKind
from silo.models.library import Library
from silo.models.metadata_source import MetadataSource
from silo.models.tag import TagKind
from silo.schemas.game import Game as GameSchema
from silo.schemas.game import GameCreate, GameDetail, GamePatch, IdentityPut
from silo.schemas.job import JobEnqueuedOut
from silo.schemas.normalized_metadata import EntityRef, VideoEntry
from silo.schemas.pagination import Page
from silo.services.entities import (
    resolve_company_refs,
    resolve_series_refs,
    resolve_tag_refs,
    slugify,
)
from silo.services.game_collections import (
    TAG_FIELDS,
    platform_ids_by_slug,
    set_game_alt_names,
    set_game_companies,
    set_game_platforms,
    set_game_ratings,
    set_game_release_dates,
    set_game_serials,
    set_game_series,
    set_game_tags,
    set_game_videos,
)
from silo.services.games import (
    DuplicateSlugError,
    UnknownLibraryError,
    art_urls,
    build_game_schema,
    create_game_with_metadata,
    load_game_detail,
)
from silo.services.resolution import resolve_game_metadata

router = APIRouter(prefix="/games", tags=["games"])


class GameListParams(PaginationData):
    """Query params for `GET /games`: pagination + library filter."""

    library_id: uuid.UUID | None = None


@router.get("", operation_id="list_games")
async def list_games(
    session: SessionDep,
    params: Annotated[GameListParams, Query()],
) -> Page[GameSchema]:
    stmt = (
        select(GameModel, GameMetadata)
        .join(GameMetadata, GameMetadata.game_id == GameModel.id)
        .order_by(GameModel.created_at.desc(), GameModel.id.desc())
        .limit(params.limit + 1)
    )
    if params.library_id is not None:
        stmt = stmt.where(GameModel.library_id == params.library_id)
    if params.cursor:
        stmt = stmt.where(keyset_clause(GameModel, params.cursor))
    rows = (await session.execute(stmt)).all()
    items, next_cursor = slice_page(rows, params.limit, keyed_by=lambda row: row[0])
    art = await art_urls(session, [game.id for game, _ in items])
    return Page[GameSchema](
        items=[
            build_game_schema(
                game,
                metadata,
                cover_url=art.get(game.id, {}).get(AssetKind.COVER),
                landscape_url=art.get(game.id, {}).get(AssetKind.LANDSCAPE),
            )
            for game, metadata in items
        ],
        next_cursor=next_cursor,
    )


@router.post("", operation_id="create_game", status_code=201)
async def create_game(
    session: SessionDep,
    body: GameCreate,
) -> GameSchema:
    try:
        _, game, metadata = await create_game_with_metadata(
            session,
            library_id=body.library_id,
            slug=body.slug,
            title=body.title,
            sort_title=body.sort_title,
            description_short=body.description_short,
            description_full=body.description_full,
            first_release_date=body.first_release_date,
            wrapper=body.wrapper,
            game_type=body.game_type,
        )
    except UnknownLibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except DuplicateSlugError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return build_game_schema(game, metadata)


@router.get("/{game_id}", operation_id="get_game")
async def get_game(
    session: SessionDep,
    game_id: uuid.UUID,
) -> GameDetail:
    game = await get_or_404(session, GameModel, game_id, "game")
    metadata = await get_or_404(session, GameMetadata, game_id, "game")
    return await load_game_detail(session, game, metadata)


def _is_list_field(annotation: Any) -> bool:
    unioned = get_args(annotation) or (annotation,)
    return any(get_origin(arg) is list for arg in unioned)


# Derived, not hand-synced: every list-annotated GamePatch field routes to its
# association-table setter, never to setattr on GameMetadata.
_COLLECTION_PATCH_FIELDS = tuple(
    name for name, field in GamePatch.model_fields.items() if _is_list_field(field.annotation)
)


def _require_unique(values: list[Any], what: str) -> None:
    if len(set(values)) != len(values):
        raise HTTPException(status_code=422, detail=f"duplicate {what}")


async def _resolve_patch_names(
    session: SessionDep, resolver: Any, names: list[str], kind: TagKind | None = None
) -> list[uuid.UUID]:
    unresolvable = [name for name in names if not slugify(name)]
    if unresolvable:
        raise HTTPException(
            status_code=422, detail=f"cannot derive a slug for: {', '.join(unresolvable)}"
        )
    refs = [EntityRef(name=name) for name in names]
    if kind is not None:
        return await resolver(session, refs, None, kind)
    return await resolver(session, refs, None)


async def _apply_collection_patch(session: SessionDep, game_id: uuid.UUID, body: GamePatch) -> None:
    fields = body.model_fields_set
    if "developers" in fields and body.developers is not None:
        ids = await _resolve_patch_names(session, resolve_company_refs, body.developers)
        await set_game_companies(session, game_id, CompanyRole.DEVELOPER, ids)
    if "publishers" in fields and body.publishers is not None:
        ids = await _resolve_patch_names(session, resolve_company_refs, body.publishers)
        await set_game_companies(session, game_id, CompanyRole.PUBLISHER, ids)
    if "series" in fields and body.series is not None:
        ids = await _resolve_patch_names(session, resolve_series_refs, body.series)
        await set_game_series(session, game_id, ids)
    for field, kind in TAG_FIELDS.items():
        names = getattr(body, field)
        if field in fields and names is not None:
            ids = await _resolve_patch_names(session, resolve_tag_refs, names, kind)
            await set_game_tags(session, game_id, kind, ids)
    if "platforms" in fields and body.platforms is not None:
        _require_unique(body.platforms, "platforms")
        by_slug = await platform_ids_by_slug(session, body.platforms)
        if unknown := [slug for slug in body.platforms if slug not in by_slug]:
            raise HTTPException(status_code=422, detail=f"unknown platforms: {', '.join(unknown)}")
        await set_game_platforms(session, game_id, [by_slug[slug] for slug in body.platforms])
    if "release_dates" in fields and body.release_dates is not None:
        slugs = [entry.platform for entry in body.release_dates]
        _require_unique(slugs, "release date platforms")
        by_slug = await platform_ids_by_slug(session, slugs)
        if unknown := [slug for slug in slugs if slug not in by_slug]:
            raise HTTPException(status_code=422, detail=f"unknown platforms: {', '.join(unknown)}")
        await set_game_release_dates(session, game_id, body.release_dates)
    if "ratings" in fields and body.ratings is not None:
        _require_unique([entry.authority for entry in body.ratings], "rating authorities")
        await set_game_ratings(session, game_id, body.ratings)
    if "alt_names" in fields and body.alt_names is not None:
        _require_unique([entry.name for entry in body.alt_names], "alt names")
        await set_game_alt_names(session, game_id, body.alt_names)
    if "videos" in fields and body.videos is not None:
        _require_unique([entry.url for entry in body.videos], "video urls")
        await set_game_videos(
            session, game_id, [VideoEntry(**entry.model_dump()) for entry in body.videos]
        )
    if "serials" in fields and body.serials is not None:
        _require_unique([entry.value for entry in body.serials], "serials")
        await set_game_serials(session, game_id, body.serials)


@router.patch("/{game_id}", operation_id="update_game")
async def update_game(
    session: SessionDep,
    game_id: uuid.UUID,
    body: GamePatch,
) -> GameSchema:
    game = await get_or_404(session, GameModel, game_id, "game")
    metadata = await get_or_404(session, GameMetadata, game_id, "game")
    update_data = body.model_dump(exclude_unset=True)
    if "preferred_source_id" in update_data:
        preferred_source_id = update_data.pop("preferred_source_id")
        if (
            preferred_source_id is not None
            and await session.get(MetadataSource, preferred_source_id) is None
        ):
            raise HTTPException(
                status_code=422, detail=f"metadata source {preferred_source_id} not found"
            )
        game.preferred_source_id = preferred_source_id
    if "library_id" in update_data:
        library_id = update_data.pop("library_id")
        if library_id != game.library_id:
            if await session.get(Library, library_id) is None:
                raise HTTPException(status_code=422, detail=f"library {library_id} not found")
            collision = await session.scalar(
                select(GameModel.id).where(
                    GameModel.library_id == library_id, GameModel.slug == game.slug
                )
            )
            if collision is not None:
                raise HTTPException(
                    status_code=409,
                    detail=f"slug {game.slug!r} already exists in the target library",
                )
            # Files stay put on disk — relative_path is stored data, not a derivation
            # (physical relocation is Epic C file management).
            game.library_id = library_id
    for field in _COLLECTION_PATCH_FIELDS:
        update_data.pop(field, None)
    for field, value in update_data.items():
        setattr(metadata, field, value)
    await _apply_collection_patch(session, game_id, body)
    await session.flush()
    return build_game_schema(game, metadata)


@router.delete("/{game_id}", operation_id="delete_game", status_code=204)
async def delete_game(
    request: Request,
    session: SessionDep,
    game_id: uuid.UUID,
    delete_files: bool = False,
) -> None:
    game = await get_or_404(session, GameModel, game_id, "game")
    paths: list[str] = []
    if delete_files:
        paths = [
            relative
            for relative in await session.scalars(
                select(File.relative_path)
                .join(Artifact, Artifact.id == File.artifact_id)
                .where(Artifact.game_id == game_id, File.relative_path.is_not(None))
            )
            if relative is not None
        ]
    # DB delete flushes first: a constraint failure must not have already
    # destroyed files (unlinks can't roll back).
    await session.delete(game)
    await session.flush()
    if delete_files:
        # Precise, not rmtree: only tracked files go; untracked leftovers keep the dir.
        library_dir = request.app.state.settings.library_dir
        parents = set()
        for relative in paths:
            path = library_dir / relative
            path.unlink(missing_ok=True)
            parents.add(path.parent)
        for parent in parents:
            if parent != library_dir and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()


@router.post("/{game_id}/resolve-metadata", operation_id="resolve_game_metadata")
async def resolve_metadata(
    session: SessionDep,
    game_id: uuid.UUID,
) -> GameSchema:
    game = await get_or_404(session, GameModel, game_id, "game")
    await resolve_game_metadata(session, game)
    return build_game_schema(game, game.game_metadata)


@router.post("/{game_id}/fetch-metadata", operation_id="fetch_game_metadata", status_code=202)
async def fetch_metadata(
    session: SessionDep,
    game_id: uuid.UUID,
) -> JobEnqueuedOut:
    await get_or_404(session, GameModel, game_id, "game")
    identified = await session.scalar(
        select(GameExternalIdentity.game_id).where(GameExternalIdentity.game_id == game_id).limit(1)
    )
    if identified is None:
        raise HTTPException(status_code=409, detail="game has no external identities")
    if await job_active(session, JobKind.FETCH_METADATA, {"game_id": str(game_id)}):
        raise HTTPException(
            status_code=409, detail="a metadata fetch for this game is already queued"
        )
    job = await enqueue(session, JobKind.FETCH_METADATA, FetchMetadataPayload(game_id=game_id))
    return JobEnqueuedOut(job_id=job.id)


@router.put("/{game_id}/locks/{field_key}", operation_id="lock_field", status_code=204)
async def lock_field(
    session: SessionDep,
    game_id: uuid.UUID,
    field_key: FieldKey,
) -> None:
    await get_or_404(session, GameModel, game_id, "game")
    if await session.get(FieldLock, (game_id, field_key)) is None:
        session.add(FieldLock(game_id=game_id, field_key=field_key))
        await session.flush()


@router.delete("/{game_id}/locks/{field_key}", operation_id="unlock_field", status_code=204)
async def unlock_field(
    session: SessionDep,
    game_id: uuid.UUID,
    field_key: FieldKey,
) -> None:
    await get_or_404(session, GameModel, game_id, "game")
    lock = await session.get(FieldLock, (game_id, field_key))
    if lock is not None:
        await session.delete(lock)
        await session.flush()


async def _identity_context(
    session: SessionDep, game_id: uuid.UUID, source_slug: str
) -> tuple[MetadataSource, GameExternalIdentity | None]:
    """The (source, existing identity) pair behind both identity endpoints; 404s."""
    await get_or_404(session, GameModel, game_id, "game")
    source = await session.scalar(select(MetadataSource).where(MetadataSource.slug == source_slug))
    if source is None:
        raise HTTPException(status_code=404, detail=f"metadata source {source_slug!r} not found")
    identity = await session.scalar(
        select(GameExternalIdentity).where(
            GameExternalIdentity.game_id == game_id,
            GameExternalIdentity.source_id == source.id,
        )
    )
    return source, identity


@router.put(
    "/{game_id}/identities/{source_slug}", operation_id="set_game_identity", status_code=204
)
async def set_game_identity(
    session: SessionDep,
    game_id: uuid.UUID,
    source_slug: str,
    body: IdentityPut,
) -> None:
    source, identity = await _identity_context(session, game_id, source_slug)
    if identity is None:
        session.add(
            GameExternalIdentity(game_id=game_id, source_id=source.id, external_id=body.external_id)
        )
    else:
        # An explicit user PUT may replace; never-overwrite guards automated writes only.
        identity.external_id = body.external_id
    await session.flush()


@router.delete(
    "/{game_id}/identities/{source_slug}", operation_id="delete_game_identity", status_code=204
)
async def delete_game_identity(
    session: SessionDep,
    game_id: uuid.UUID,
    source_slug: str,
) -> None:
    _, identity = await _identity_context(session, game_id, source_slug)
    if identity is not None:
        await session.delete(identity)
        await session.flush()
