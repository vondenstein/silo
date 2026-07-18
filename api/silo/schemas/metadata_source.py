import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.json_schema import SkipJsonSchema


class MetadataSource(BaseModel):
    """Metadata source registry entry."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    enabled: bool
    required: bool
    priority: int
    request_interval_ms: int | None
    # Whether the source offers a catalog title search (the identify flow).
    searchable: bool = False


class SearchCandidateOut(BaseModel):
    """One catalog-search candidate."""

    model_config = ConfigDict(from_attributes=True)

    external_id: str
    name: str
    year: int | None


class MetadataSourcePatch(BaseModel):
    """Metadata source patch request."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | SkipJsonSchema[None] = None
    priority: int | SkipJsonSchema[None] = Field(default=None, ge=0)
    # Nullable by design: explicit null clears back to the adapter's polite default.
    request_interval_ms: int | None = Field(default=None, ge=0)

    @field_validator("enabled", "priority", mode="before")
    @classmethod
    def prevent_none(cls, v: object) -> object:
        if v is None:
            raise ValueError("cannot be null")
        return v
