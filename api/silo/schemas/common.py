from datetime import UTC, datetime
from typing import Annotated

from pydantic import Field, PlainSerializer

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"

Slug = Annotated[str, Field(min_length=1, max_length=64, pattern=SLUG_PATTERN)]

EntityName = Annotated[str, Field(min_length=1, max_length=255)]


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC)


# Storage is naive UTC; the wire declares the offset (RFC 3339).
UTCDateTime = Annotated[datetime, PlainSerializer(_as_utc, return_type=datetime, when_used="json")]
