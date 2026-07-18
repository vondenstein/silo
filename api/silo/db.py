from collections.abc import AsyncIterator
from pathlib import Path

from alembic.config import Config
from fastapi import FastAPI, Request
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from silo.settings import Settings


def install_sqlite_pragmas(engine: AsyncEngine) -> None:
    """Attach the per-connection SQLite pragmas (FK enforcement, WAL, busy timeout)."""

    @event.listens_for(engine.sync_engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


def open_db(app: FastAPI, db_url: str) -> None:
    """Create engine and session factory on app.state."""
    engine = create_async_engine(db_url)
    install_sqlite_pragmas(engine)
    app.state.db_engine = engine
    app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)


async def close_db(app: FastAPI) -> None:
    """Dispose the engine."""
    await app.state.db_engine.dispose()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Request-scoped DB session."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def run_migrations(settings: Settings) -> None:
    """Run Alembic upgrade head."""
    ini_path = Path(__file__).parent.parent / "alembic.ini"
    config = Config(str(ini_path))
    config.set_main_option("sqlalchemy.url", settings.db_url_sync)
    command.upgrade(config, "head")
