import pytest

from silo.api.dependencies import get_current_user
from silo.seed import seed_implicit_user


async def test_get_current_user_returns_seeded_user(db_session):
    await seed_implicit_user(db_session)
    user = await get_current_user(db_session)
    assert user.name == "owner"


async def test_get_current_user_raises_when_not_seeded(db_session):
    with pytest.raises(RuntimeError, match="implicit user not seeded"):
        await get_current_user(db_session)
