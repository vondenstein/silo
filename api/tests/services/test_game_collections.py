from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.game import (
    Game,
    GameAltName,
    GameMetadata,
    GameRating,
    GameReleaseDate,
    GameSerial,
    GameVideo,
    RatingAuthority,
)
from silo.models.library import Library
from silo.schemas.game import SerialEntry
from silo.schemas.normalized_metadata import (
    AltNameEntry,
    RatingEntry,
    ReleaseDateEntry,
    VideoEntry,
)
from silo.seed import seed_platforms
from silo.services.game_collections import (
    set_game_alt_names,
    set_game_ratings,
    set_game_release_dates,
    set_game_serials,
    set_game_videos,
)
from tests.seed import seed_in_order


async def _seed_game(session: AsyncSession) -> Game:
    now = datetime(2025, 1, 1)
    library = Library(id=uuid4(), slug="main", name="Main", created_at=now, updated_at=now)
    game = Game(id=uuid4(), library_id=library.id, slug="doom", created_at=now, updated_at=now)
    metadata = GameMetadata(game_id=game.id, title="DOOM")
    await seed_in_order(session, library, game, metadata)
    return game


# Each keyed setter: same-key rows update in place, absent keys delete.


async def test_alt_names_update_and_delete_stale(db_session: AsyncSession):
    game = await _seed_game(db_session)
    await set_game_alt_names(
        db_session, game.id, [AltNameEntry(name="Doom", comment="old"), AltNameEntry(name="Stale")]
    )
    await db_session.commit()

    await set_game_alt_names(
        db_session, game.id, [AltNameEntry(name="Doom", comment="new"), AltNameEntry(name="Fresh")]
    )
    await db_session.commit()

    rows = await db_session.scalars(select(GameAltName).where(GameAltName.game_id == game.id))
    assert {row.name: row.comment for row in rows} == {"Doom": "new", "Fresh": None}


async def test_videos_update_and_delete_stale(db_session: AsyncSession):
    game = await _seed_game(db_session)
    await set_game_videos(
        db_session,
        game.id,
        [
            VideoEntry(provider="youtube", url="https://y.t/keep", video_id="a", name="Old"),
            VideoEntry(provider="youtube", url="https://y.t/stale"),
        ],
    )
    await db_session.commit()

    await set_game_videos(
        db_session,
        game.id,
        [VideoEntry(provider="youtube", url="https://y.t/keep", video_id="b", name="New")],
    )
    await db_session.commit()

    (row,) = list(await db_session.scalars(select(GameVideo).where(GameVideo.game_id == game.id)))
    assert (row.url, row.video_id, row.name) == ("https://y.t/keep", "b", "New")


async def test_ratings_update_and_delete_stale(db_session: AsyncSession):
    game = await _seed_game(db_session)
    await set_game_ratings(
        db_session,
        game.id,
        [
            RatingEntry(authority=RatingAuthority.PEGI, value="16"),
            RatingEntry(authority=RatingAuthority.USK, value="12"),
        ],
    )
    await db_session.commit()

    await set_game_ratings(
        db_session,
        game.id,
        [RatingEntry(authority=RatingAuthority.PEGI, value="18", descriptors=["Violence"])],
    )
    await db_session.commit()

    (row,) = list(await db_session.scalars(select(GameRating).where(GameRating.game_id == game.id)))
    assert (row.authority.value, row.value, row.descriptors) == ("pegi", "18", ["Violence"])


async def test_release_dates_update_and_delete_stale(db_session: AsyncSession):
    game = await _seed_game(db_session)
    await seed_platforms(db_session)
    await set_game_release_dates(
        db_session,
        game.id,
        [
            ReleaseDateEntry(platform="windows", date=date(2020, 1, 1)),
            ReleaseDateEntry(platform="linux", date=date(2021, 1, 1)),
        ],
    )
    await db_session.commit()

    await set_game_release_dates(
        db_session, game.id, [ReleaseDateEntry(platform="windows", date=date(2022, 2, 2))]
    )
    await db_session.commit()

    (row,) = list(
        await db_session.scalars(select(GameReleaseDate).where(GameReleaseDate.game_id == game.id))
    )
    assert row.date == date(2022, 2, 2)


async def test_serials_update_and_delete_stale(db_session: AsyncSession):
    game = await _seed_game(db_session)
    await set_game_serials(
        db_session,
        game.id,
        [SerialEntry(value="ABC-123", comment="old"), SerialEntry(value="STALE-1")],
    )
    await db_session.commit()

    await set_game_serials(db_session, game.id, [SerialEntry(value="ABC-123", comment="new")])
    await db_session.commit()

    (row,) = list(await db_session.scalars(select(GameSerial).where(GameSerial.game_id == game.id)))
    assert (row.value, row.comment) == ("ABC-123", "new")
