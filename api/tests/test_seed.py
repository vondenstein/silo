from sqlalchemy import func, select

from silo.models.identification import IdentificationSource
from silo.models.metadata_source import MetadataSource
from silo.models.platform import Platform, PlatformFamily
from silo.models.user import User
from silo.seed import (
    _IDENTIFICATION_SOURCES,
    _METADATA_SOURCES,
    _PLATFORMS,
    seed_identification_sources,
    seed_implicit_user,
    seed_metadata_sources,
    seed_platforms,
)


async def test_seed_is_idempotent(db_session):
    first = await seed_implicit_user(db_session)
    second = await seed_implicit_user(db_session)
    assert first.id == second.id
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1


async def test_seed_metadata_sources_is_idempotent(db_session):
    await seed_metadata_sources(db_session)
    await seed_metadata_sources(db_session)
    count = await db_session.scalar(select(func.count()).select_from(MetadataSource))
    assert count == len(_METADATA_SOURCES)


async def test_seed_platforms_is_idempotent(db_session):
    await seed_platforms(db_session)
    await seed_platforms(db_session)

    assert await db_session.scalar(select(func.count()).select_from(Platform)) == len(_PLATFORMS)
    assert await db_session.scalar(select(func.count()).select_from(PlatformFamily)) == 1
    linux = (
        await db_session.execute(select(Platform).where(Platform.slug == "linux"))
    ).scalar_one()
    family = await db_session.get(PlatformFamily, linux.family_id)
    assert family is not None
    assert family.slug == "pc"
    assert family.is_pc is True


async def test_seed_identification_sources_is_idempotent(db_session):
    await seed_identification_sources(db_session)
    await seed_identification_sources(db_session)

    count = await db_session.scalar(select(func.count()).select_from(IdentificationSource))
    assert count == len(_IDENTIFICATION_SOURCES)


async def test_seed_preserves_operator_edits(db_session):
    await seed_metadata_sources(db_session)
    gog_query = select(MetadataSource).where(MetadataSource.slug == "gog")
    gog = (await db_session.execute(gog_query)).scalar_one()
    gog.enabled = False
    gog.priority = 99
    await db_session.flush()

    await seed_metadata_sources(db_session)
    gog = (await db_session.execute(gog_query)).scalar_one()
    assert (gog.enabled, gog.priority) == (False, 99)
