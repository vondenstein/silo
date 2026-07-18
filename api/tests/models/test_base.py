from datetime import datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.field_lock import FieldKey, FieldLock
from silo.models.game import Game
from silo.models.library import Library
from tests.seed import seed_in_order


async def test_string_enum_stores_member_names(db_session: AsyncSession):
    now = datetime(2025, 1, 1)
    library = Library(id=uuid4(), slug="main", name="Main", created_at=now, updated_at=now)
    game = Game(id=uuid4(), library_id=library.id, slug="doom", created_at=now, updated_at=now)
    await seed_in_order(
        db_session, library, game, FieldLock(game_id=game.id, field_key=FieldKey.TITLE)
    )

    # Deployed DBs store enum member NAMES; switching string_enum to values
    # would pass on fresh DBs while making every existing row unreadable
    # (LookupError on load). Covers the shared helper for all 13 enums.
    stored = await db_session.scalar(text("SELECT field_key FROM field_lock"))
    assert stored == "TITLE"
