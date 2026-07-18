import uuid

from pydantic import BaseModel, ConfigDict, Field

from silo.models.artifact import ArtifactKind
from silo.schemas.common import Slug
from silo.schemas.game import Game
from silo.schemas.identification import SignatureMatchOut


class FileHashes(BaseModel):
    """Digests computed while the upload streamed to staging."""

    blake3: str
    md5: str
    sha1: str
    sha256: str
    crc32: str


class StageManifest(BaseModel):
    """Sidecar persisted next to the staged file."""

    filename: str
    size: int
    hashes: FileHashes


class StageOut(BaseModel):
    """Staged upload."""

    stage_id: str
    filename: str
    size: int
    hashes: FileHashes
    suggested_slug: str
    suggested_kind: ArtifactKind
    matches: list[SignatureMatchOut]


class FinalizeRequest(BaseModel):
    """Finalize request: create the game + artifact from a staged file."""

    model_config = ConfigDict(extra="forbid")

    stage_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    library_id: uuid.UUID
    slug: Slug
    title: str = Field(min_length=1, max_length=255)
    kind: ArtifactKind
    chosen_signature_id: uuid.UUID | None = None


class FinalizeOut(BaseModel):
    """Finalize result: the created game, plus the identify job when a signature seeded it."""

    game: Game
    identify_job_id: uuid.UUID | None
