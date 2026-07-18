from pydantic import BaseModel, ConfigDict, Field


class IgdbCredentialsPut(BaseModel):
    """Twitch developer-app credentials for IGDB."""

    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(min_length=1)
    client_secret: str = Field(min_length=1)


class IgdbStatusOut(BaseModel):
    """IGDB connection status."""

    connected: bool
