import base64
import json
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, and_, or_


class PaginationData(BaseModel):
    cursor: str | None = Field(default=None, description="Opaque cursor from next_cursor.")
    limit: int = Field(default=50, ge=1, le=200, description="Page size.")


def encode_cursor(created_at: datetime, id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(
        json.dumps({"created_at": created_at.isoformat(), "id": str(id)}).encode()
    ).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(data["created_at"]), uuid.UUID(data["id"])
    except (ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(status_code=400, detail="invalid cursor") from None


def keyset_clause(model: Any, cursor: str) -> ColumnElement[bool]:
    """WHERE continuation for a (created_at desc, id desc) keyset page."""
    after_created, after_id = decode_cursor(cursor)
    return or_(
        model.created_at < after_created,
        and_(model.created_at == after_created, model.id < after_id),
    )


def slice_page(
    rows: Sequence[Any], limit: int, keyed_by: Callable[[Any], Any] = lambda row: row
) -> tuple[list[Any], str | None]:
    """The page's items + next cursor (None on the last page). Expects limit+1 rows."""
    items = list(rows[:limit])
    if len(rows) <= limit:
        return items, None
    last = keyed_by(items[-1])
    return items, encode_cursor(last.created_at, last.id)
