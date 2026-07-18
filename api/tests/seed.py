from sqlalchemy.ext.asyncio import AsyncSession


# The unit of work does not order inserts across mappers without
# relationship() directives — rows must arrive parent-first.
async def seed_in_order(session: AsyncSession, *rows) -> None:
    """Add and flush each row in argument order, then commit."""
    for row in rows:
        session.add(row)
        await session.flush()
    await session.commit()
