from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.identification import IdentificationSource
from silo.models.metadata_source import MetadataSource
from silo.models.platform import Platform, PlatformFamily
from silo.models.user import User

_METADATA_SOURCES = [
    {"slug": "gog", "name": "GOG", "priority": 10, "request_interval_ms": 250},
    # gog_gamesdb/gog_store ride the shared GOG client; its throttle uses the gog row.
    {"slug": "gog_gamesdb", "name": "GOG GamesDB", "priority": 12},
    {"slug": "gog_store", "name": "GOG Store", "priority": 14},
    {"slug": "igdb", "name": "IGDB", "priority": 20, "request_interval_ms": 250},
    {"slug": "steam", "name": "Steam", "priority": 30, "request_interval_ms": 1500},
]

_PLATFORM_FAMILIES = [
    {"slug": "pc", "name": "PC", "manufacturer": "", "is_pc": True, "icon": "desktop"},
]

_PLATFORMS = [
    {"slug": "windows", "name": "Windows", "family": "pc"},
    {"slug": "macos", "name": "macOS", "family": "pc"},
    {"slug": "linux", "name": "Linux", "family": "pc"},
]

_IDENTIFICATION_SOURCES = [
    {"slug": "redump", "name": "Redump"},
]


async def seed_implicit_user(session: AsyncSession) -> User:
    """Get or create the implicit user."""
    user = (await session.execute(select(User))).scalars().first()
    if user is None:
        user = User(name="owner")
        session.add(user)
        await session.flush()
    return user


async def seed_metadata_sources(session: AsyncSession) -> None:
    """Insert missing metadata_source rows; never update existing ones."""
    existing = set((await session.execute(select(MetadataSource.slug))).scalars())
    for row in _METADATA_SOURCES:
        if row["slug"] not in existing:
            session.add(MetadataSource(**row))
    await session.flush()


async def seed_identification_sources(session: AsyncSession) -> None:
    """Insert missing identification_source rows; never update existing ones."""
    existing = set((await session.execute(select(IdentificationSource.slug))).scalars())
    for row in _IDENTIFICATION_SOURCES:
        if row["slug"] not in existing:
            session.add(IdentificationSource(**row))
    await session.flush()


async def seed_platforms(session: AsyncSession) -> None:
    """Insert missing platform_family/platform rows; never update existing ones."""
    families = {
        family.slug: family.id
        for family in (await session.execute(select(PlatformFamily))).scalars()
    }
    for row in _PLATFORM_FAMILIES:
        if row["slug"] not in families:
            family = PlatformFamily(**row)
            session.add(family)
            await session.flush()
            families[family.slug] = family.id
    existing = set((await session.execute(select(Platform.slug))).scalars())
    for row in _PLATFORMS:
        if row["slug"] not in existing:
            session.add(
                Platform(slug=row["slug"], name=row["name"], family_id=families[row["family"]])
            )
    await session.flush()
