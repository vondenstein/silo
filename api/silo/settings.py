from pathlib import Path

from pydantic import DirectoryPath
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Silo environment settings."""

    model_config = SettingsConfigDict(env_prefix="SILO_", validate_default=True)

    data_dir: DirectoryPath = Path("/data")
    library_dir: DirectoryPath = Path("/games")
    web_dist_dir: DirectoryPath | None = None

    @property
    def db_url_async(self) -> str:
        return f"sqlite+aiosqlite:///{self.data_dir / 'silo.db'}"

    @property
    def db_url_sync(self) -> str:
        return f"sqlite:///{self.data_dir / 'silo.db'}"

    @property
    def metadata_dir(self) -> Path:
        return self.data_dir / "metadata"

    @property
    def asset_dir(self) -> Path:
        return self.metadata_dir / "assets"
