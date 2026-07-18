import uuid

from pydantic import BaseModel, ConfigDict, field_validator

from silo.schemas.common import UTCDateTime


class SignatureMatchOut(BaseModel):
    """A file's identification-signature match (derived)."""

    signature_id: uuid.UUID
    game_name: str
    file_name: str
    category: str | None
    dataset_name: str
    source_slug: str


class Dataset(BaseModel):
    """Identification dataset with its source and signature count."""

    id: uuid.UUID
    source_slug: str
    slug: str
    name: str
    enabled: bool
    dataset_version: str | None
    refreshed_at: UTCDateTime | None
    signature_count: int


class DatasetPatch(BaseModel):
    """Dataset settings patch."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None

    @field_validator("enabled", mode="before")
    @classmethod
    def prevent_none(cls, v: object) -> object:
        if v is None:
            raise ValueError("cannot be null")
        return v


class DiscoverDatasetsOut(BaseModel):
    """Dataset-discovery result."""

    dataset_count: int
