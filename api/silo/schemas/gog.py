import uuid

from pydantic import BaseModel, ConfigDict, Field


class GogAuthUrlOut(BaseModel):
    """GOG authorization URL."""

    url: str


class GogAuthRequest(BaseModel):
    """Auth-code exchange request."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)


class GogStatusOut(BaseModel):
    """GOG connection status."""

    connected: bool


class OwnedGameOut(BaseModel):
    """An owned GOG game, flagged when it's already in the library."""

    gog_id: int
    title: str
    slug: str
    image_url: str | None
    imported: bool
    complete: bool


class GogImportRequest(BaseModel):
    """Import request for one owned GOG game."""

    model_config = ConfigDict(extra="forbid")

    gog_id: int
    library_id: uuid.UUID
