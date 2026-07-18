import uuid

from pydantic import BaseModel, ConfigDict

from silo.schemas.common import UTCDateTime


class User(BaseModel):
    """Silo user."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: UTCDateTime
