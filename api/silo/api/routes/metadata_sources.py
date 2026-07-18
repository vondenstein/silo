import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from silo.api.dependencies import SessionDep
from silo.models.metadata_source import MetadataSource as MetadataSourceModel
from silo.schemas.metadata_source import MetadataSource as MetadataSourceSchema
from silo.schemas.metadata_source import MetadataSourcePatch, SearchCandidateOut
from silo.services.metadata_fetch import search_source, source_search_available

router = APIRouter(prefix="/metadata-sources", tags=["metadata-sources"])


def _source_out(source: MetadataSourceModel) -> MetadataSourceSchema:
    out = MetadataSourceSchema.model_validate(source)
    out.searchable = source_search_available(source.slug)
    return out


@router.get("", operation_id="list_metadata_sources")
async def list_metadata_sources(
    session: SessionDep,
) -> list[MetadataSourceSchema]:
    stmt = select(MetadataSourceModel).order_by(
        MetadataSourceModel.priority.asc(), MetadataSourceModel.id.asc()
    )
    rows = (await session.scalars(stmt)).all()
    return [_source_out(source) for source in rows]


@router.get("/{slug}/search", operation_id="search_metadata_source")
async def search_metadata_source(
    session: SessionDep,
    slug: str,
    q: str = Query(min_length=1, max_length=255),
) -> list[SearchCandidateOut]:
    source = await session.scalar(
        select(MetadataSourceModel).where(MetadataSourceModel.slug == slug)
    )
    if source is None:
        raise HTTPException(status_code=404, detail=f"metadata source {slug!r} not found")
    if not source_search_available(slug):
        raise HTTPException(status_code=422, detail=f"{slug!r} has no catalog search")
    try:
        candidates = await search_source(session, slug, q)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"search failed: {type(exc).__name__}: {exc}"
        ) from exc
    if candidates is None:
        raise HTTPException(status_code=409, detail=f"{slug!r} is not configured")
    return candidates


@router.patch("/{source_id}", operation_id="update_metadata_source")
async def update_metadata_source(
    session: SessionDep,
    source_id: uuid.UUID,
    body: MetadataSourcePatch,
) -> MetadataSourceSchema:
    source = await session.get(MetadataSourceModel, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"metadata source {source_id} not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(source, field, value)
    await session.flush()
    return _source_out(source)
