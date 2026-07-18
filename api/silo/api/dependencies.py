from typing import Annotated, Any, TypeVar

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from silo.db import get_session
from silo.models.user import User as DbUser
from silo.schemas.user import User

SessionDep = Annotated[AsyncSession, Depends(get_session)]

ModelT = TypeVar("ModelT")


async def get_or_404(session: AsyncSession, model: type[ModelT], key: Any, what: str) -> ModelT:
    """The row for the primary key, or a 404 naming what's missing."""
    instance = await session.get(model, key)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"{what} {key} not found")
    return instance


async def get_current_user(
    session: SessionDep,
) -> User:
    """Resolve the current user."""
    db_user = (await session.execute(select(DbUser))).scalars().first()
    if db_user is None:
        raise RuntimeError("implicit user not seeded")
    return User.model_validate(db_user)
