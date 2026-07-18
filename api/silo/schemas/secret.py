from pydantic import BaseModel, ConfigDict, Field


class SecretPut(BaseModel):
    """Secret put request."""

    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, max_length=10_000)
