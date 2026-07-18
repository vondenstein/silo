import uuid

from pydantic import BaseModel, ConfigDict, Field

from silo.schemas.common import Slug, UTCDateTime


class Library(BaseModel):
    """Game library."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    created_at: UTCDateTime
    updated_at: UTCDateTime


class LibraryCreate(BaseModel):
    """Library create request."""

    model_config = ConfigDict(extra="forbid")

    slug: Slug
    name: str = Field(min_length=1, max_length=255)


class LibraryPatch(BaseModel):
    """Library patch request."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
