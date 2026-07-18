import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from silo.models.job import Job, JobKind
from silo.settings import Settings


@dataclass
class JobContext:
    """Handler-facing job utilities."""

    job_id: uuid.UUID
    sessionmaker: async_sessionmaker[AsyncSession]
    settings: Settings

    async def report_progress(self, progress: BaseModel) -> None:
        """Write the job's progress in its own transaction so readers see it mid-run.
        Callers must not hold an open write transaction across a report (SQLite lock)."""
        async with self.sessionmaker() as session:
            job = await session.get(Job, self.job_id)
            if job is None:
                return
            job.progress = progress.model_dump(mode="json")
            await session.commit()


@dataclass(frozen=True)
class JobHandler:
    """Typed contract + runner for one job kind."""

    payload_model: type[BaseModel]
    progress_model: type[BaseModel]
    result_model: type[BaseModel]
    run: Callable[[JobContext, Any], Awaitable[BaseModel]]


REGISTRY: dict[JobKind, JobHandler] = {}


def register(kind: JobKind, handler: JobHandler) -> None:
    """Register the handler for a job kind."""
    REGISTRY[kind] = handler
