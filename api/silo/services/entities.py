import re
import uuid
from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.company import Company, CompanyAlias, CompanyExternalIdentity
from silo.models.series import Series, SeriesAlias, SeriesExternalIdentity
from silo.models.tag import Tag, TagAlias, TagExternalIdentity, TagKind
from silo.schemas.normalized_metadata import EntityRef

SLUG_MAX_LENGTH = 64


def slugify(name: str) -> str:
    """lib/slug.ts twin: lowercase, delete punctuation (ASCII), collapse separators."""
    slug = re.sub(r"[^\w\s-]", "", name.lower().strip(), flags=re.ASCII)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug.strip("-")[:SLUG_MAX_LENGTH].strip("-")


class _EntityFamily(NamedTuple):
    entity: Any
    alias: Any
    identity: Any
    fk: str


_COMPANY = _EntityFamily(Company, CompanyAlias, CompanyExternalIdentity, "company_id")
_SERIES = _EntityFamily(Series, SeriesAlias, SeriesExternalIdentity, "series_id")
_TAG = _EntityFamily(Tag, TagAlias, TagExternalIdentity, "tag_id")


async def resolve_company_refs(
    session: AsyncSession, refs: list[EntityRef], source_id: uuid.UUID | None
) -> list[uuid.UUID]:
    """Company ids for the refs, creating/aliasing per the reconciliation ladder."""
    return await _resolve_refs(session, _COMPANY, refs, source_id)


async def resolve_series_refs(
    session: AsyncSession, refs: list[EntityRef], source_id: uuid.UUID | None
) -> list[uuid.UUID]:
    """Series ids for the refs, creating/aliasing per the reconciliation ladder."""
    return await _resolve_refs(session, _SERIES, refs, source_id)


async def resolve_tag_refs(
    session: AsyncSession, refs: list[EntityRef], source_id: uuid.UUID | None, kind: TagKind
) -> list[uuid.UUID]:
    """Tag ids (kind-scoped) for the refs, creating/aliasing per the reconciliation ladder."""
    return await _resolve_refs(session, _TAG, refs, source_id, kind)


async def _resolve_refs(
    session: AsyncSession,
    family: _EntityFamily,
    refs: list[EntityRef],
    source_id: uuid.UUID | None,
    kind: TagKind | None = None,
) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for ref in refs:
        entity_id = await _resolve_ref(session, family, ref, source_id, kind)
        if entity_id is not None and entity_id not in ids:
            ids.append(entity_id)
    return ids


async def _resolve_ref(
    session: AsyncSession,
    family: _EntityFamily,
    ref: EntityRef,
    source_id: uuid.UUID | None,
    kind: TagKind | None,
) -> uuid.UUID | None:
    """The ladder: identity (source, uid) → alias exact → slug → create."""
    entity = None
    uid_mapped = False
    if ref.uid is not None and source_id is not None:
        entity_id = await session.scalar(
            select(getattr(family.identity, family.fk)).where(
                family.identity.source_id == source_id,
                family.identity.external_id == ref.uid,
            )
        )
        uid_mapped = entity_id is not None
        if entity_id is not None:
            candidate = await session.get(family.entity, entity_id)
            # A wrong-kind identity hit falls through to the name rungs — a
            # kind-blind match here is the post-6d game_tag crash class.
            if candidate is not None and (kind is None or candidate.kind == kind):
                entity = candidate
    if entity is None:
        stmt = (
            select(family.entity)
            .join(family.alias, getattr(family.alias, family.fk) == family.entity.id)
            .where(family.alias.alias == ref.name)
        )
        if kind is not None:
            stmt = stmt.where(family.entity.kind == kind)
        entity = await session.scalar(stmt)
    if entity is None:
        slug = slugify(ref.name)
        if not slug:
            return None
        stmt = select(family.entity).where(family.entity.slug == slug)
        if kind is not None:
            stmt = stmt.where(family.entity.kind == kind)
        entity = await session.scalar(stmt)
        if entity is None:
            extra = {"kind": kind} if kind is not None else {}
            entity = family.entity(id=uuid.uuid4(), slug=slug, name=ref.name, **extra)
            session.add(entity)
    # A divergent incoming name becomes an alias (covers slug-collision match-and-alias).
    if entity.name != ref.name:
        known = await session.scalar(
            select(family.alias.alias).where(
                getattr(family.alias, family.fk) == entity.id,
                family.alias.alias == ref.name,
            )
        )
        if known is None:
            session.add(family.alias(**{family.fk: entity.id, "alias": ref.name}))
    # uid → identity row: only when the uid is globally unmapped (never
    # overwrite, never conflict — a wrong-kind mapping stays put and the name
    # rungs carry the match) AND this entity has no mapping for the source yet.
    if ref.uid is not None and source_id is not None and not uid_mapped:
        mapped = await session.scalar(
            select(family.identity.external_id).where(
                getattr(family.identity, family.fk) == entity.id,
                family.identity.source_id == source_id,
            )
        )
        if mapped is None:
            session.add(
                family.identity(**{family.fk: entity.id}, source_id=source_id, external_id=ref.uid)
            )
    return entity.id
