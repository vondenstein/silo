from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.company import Company, CompanyAlias, CompanyExternalIdentity
from silo.models.metadata_source import MetadataSource
from silo.models.tag import Tag, TagAlias, TagExternalIdentity, TagKind
from silo.schemas.normalized_metadata import EntityRef
from silo.services.entities import (
    resolve_company_refs,
    resolve_series_refs,
    resolve_tag_refs,
    slugify,
)


def _source(slug: str = "acme", priority: int = 1) -> MetadataSource:
    return MetadataSource(id=uuid4(), slug=slug, name=slug.upper(), priority=priority)


def test_slugify_matches_frontend_rule():
    assert slugify("Baldur's Gate: Enhanced Edition") == "baldurs-gate-enhanced-edition"
    assert slugify("Role-playing (RPG)") == "role-playing-rpg"
    assert slugify("  Age  of _ Wonders  ") == "age-of-wonders"
    # ASCII \w, like the JS twin.
    assert slugify("Pokémon") == "pokmon"
    assert slugify("奇迹时代") == ""
    assert len(slugify("x" * 100)) <= 64


async def test_creates_and_reuses_by_slug(db_session: AsyncSession):
    src = _source()
    db_session.add(src)
    await db_session.flush()

    first = await resolve_company_refs(db_session, [EntityRef(name="Valve")], src.id)
    second = await resolve_company_refs(db_session, [EntityRef(name="Valve")], src.id)

    assert first == second
    company = await db_session.get(Company, first[0])
    assert company is not None
    assert (company.slug, company.name) == ("valve", "Valve")
    assert await db_session.scalar(select(func.count()).select_from(Company)) == 1


async def test_slug_collision_matches_and_aliases(db_session: AsyncSession):
    src = _source()
    db_session.add(src)
    await db_session.flush()

    first = await resolve_company_refs(db_session, [EntityRef(name="Atari, Inc.")], src.id)
    second = await resolve_company_refs(db_session, [EntityRef(name="Atari Inc")], src.id)

    assert first == second
    company = await db_session.get(Company, first[0])
    assert company is not None
    # The entity keeps its first-seen name; the variant becomes an alias.
    assert company.name == "Atari, Inc."
    aliases = (await db_session.scalars(select(CompanyAlias.alias))).all()
    assert aliases == ["Atari Inc"]


async def test_alias_exact_match(db_session: AsyncSession):
    src = _source()
    db_session.add(src)
    await db_session.flush()
    [company_id] = await resolve_company_refs(db_session, [EntityRef(name="Beamdog")], src.id)
    db_session.add(CompanyAlias(company_id=company_id, alias="Overhaul Games"))
    await db_session.flush()

    # A different slug entirely — only the alias links it.
    assert await resolve_company_refs(db_session, [EntityRef(name="Overhaul Games")], src.id) == [
        company_id
    ]
    assert await db_session.scalar(select(func.count()).select_from(Company)) == 1


async def test_uid_identity_wins_over_name(db_session: AsyncSession):
    src = _source()
    db_session.add(src)
    await db_session.flush()
    [company_id] = await resolve_company_refs(
        db_session, [EntityRef(name="Triumph Studios", uid="123")], src.id
    )

    # Same uid, renamed upstream → same entity, new alias, identity intact.
    renamed = await resolve_company_refs(
        db_session, [EntityRef(name="Triumph Studios B.V.", uid="123")], src.id
    )

    assert renamed == [company_id]
    company = await db_session.get(Company, company_id)
    assert company is not None
    assert company.name == "Triumph Studios"
    aliases = (
        await db_session.scalars(
            select(CompanyAlias.alias).where(CompanyAlias.company_id == company_id)
        )
    ).all()
    assert aliases == ["Triumph Studios B.V."]


async def test_uid_recorded_on_name_match_never_overwritten(db_session: AsyncSession):
    src = _source()
    db_session.add(src)
    await db_session.flush()
    [company_id] = await resolve_company_refs(
        db_session, [EntityRef(name="Larian Studios")], src.id
    )

    # A name-matched ref carrying a uid records the identity...
    await resolve_company_refs(db_session, [EntityRef(name="Larian Studios", uid="510")], src.id)
    # ...and a later different uid for the same (entity, source) never overwrites it.
    await resolve_company_refs(db_session, [EntityRef(name="Larian Studios", uid="999")], src.id)

    identity = (
        await db_session.scalars(
            select(CompanyExternalIdentity).where(CompanyExternalIdentity.company_id == company_id)
        )
    ).one()
    assert identity.external_id == "510"


async def test_identities_accumulate_across_sources(db_session: AsyncSession):
    alpha, beta = _source("alpha"), _source("beta", priority=2)
    db_session.add_all([alpha, beta])
    await db_session.flush()

    [company_id] = await resolve_company_refs(
        db_session, [EntityRef(name="Larian Studios", uid="510")], alpha.id
    )
    assert await resolve_company_refs(
        db_session, [EntityRef(name="Larian Studios", uid="X9")], beta.id
    ) == [company_id]

    rows = (
        await db_session.scalars(
            select(CompanyExternalIdentity).where(CompanyExternalIdentity.company_id == company_id)
        )
    ).all()
    assert {(row.source_id, row.external_id) for row in rows} == {
        (alpha.id, "510"),
        (beta.id, "X9"),
    }


async def test_tag_kinds_do_not_collide(db_session: AsyncSession):
    src = _source()
    db_session.add(src)
    await db_session.flush()

    [genre_id] = await resolve_tag_refs(
        db_session, [EntityRef(name="Strategy")], src.id, TagKind.GENRE
    )
    [tag_id] = await resolve_tag_refs(db_session, [EntityRef(name="Strategy")], src.id, TagKind.TAG)

    assert genre_id != tag_id
    tags = (await db_session.scalars(select(Tag))).all()
    assert {(tag.kind, tag.slug) for tag in tags} == {
        (TagKind.GENRE, "strategy"),
        (TagKind.TAG, "strategy"),
    }


async def test_dedup_and_unresolvable_refs(db_session: AsyncSession):
    src = _source()
    db_session.add(src)
    await db_session.flush()

    ids = await resolve_series_refs(
        db_session,
        [EntityRef(name="Baldur's Gate"), EntityRef(name="Baldurs Gate"), EntityRef(name="!!!")],
        src.id,
    )

    # The slug collision dedups to one series; the all-punctuation ref is skipped.
    assert len(ids) == 1


async def test_wrong_kind_uid_falls_through_and_never_conflicts(db_session: AsyncSession):
    src = _source()
    db_session.add(src)
    await db_session.flush()

    # A theme owns the uid; a genre ref arriving with the same uid must fall
    # through to the name rungs instead of returning (or crashing on) the theme.
    [theme_id] = await resolve_tag_refs(
        db_session, [EntityRef(name="Fantasy", uid="keyword:1")], src.id, TagKind.THEME
    )
    [genre_id] = await resolve_tag_refs(
        db_session, [EntityRef(name="Fantasy", uid="keyword:1")], src.id, TagKind.GENRE
    )

    assert genre_id != theme_id
    genre = await db_session.get(Tag, genre_id)
    assert genre is not None and genre.kind == TagKind.GENRE
    # The uid mapping stays with the theme — never overwritten, never duplicated
    # (the unique (source_id, external_id) constraint holds by construction).
    await db_session.flush()
    rows = (
        await db_session.execute(
            select(TagExternalIdentity.tag_id).where(
                TagExternalIdentity.source_id == src.id,
                TagExternalIdentity.external_id == "keyword:1",
            )
        )
    ).scalars()
    assert list(rows) == [theme_id]


async def test_alias_rung_is_kind_scoped(db_session: AsyncSession):
    # An alias on a MODE tag must not satisfy a GENRE resolve — a cross-kind
    # alias hit would land the wrong tag id in the genre list.
    mode = Tag(id=uuid4(), kind=TagKind.MODE, slug="single-player", name="Single player")
    db_session.add(mode)
    await db_session.flush()
    db_session.add(TagAlias(tag_id=mode.id, alias="Solo"))
    await db_session.flush()

    ids = await resolve_tag_refs(db_session, [EntityRef(name="Solo")], None, TagKind.GENRE)

    (created,) = ids
    assert created != mode.id
    tag = await db_session.get(Tag, created)
    assert tag is not None
    assert (tag.kind, tag.slug) == (TagKind.GENRE, "solo")
