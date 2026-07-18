import shutil
import uuid
import zlib
from collections.abc import AsyncIterator
from hashlib import md5, sha1, sha256
from pathlib import Path

from blake3 import blake3
from fastapi import HTTPException, UploadFile
from pydantic import ValidationError

from silo.models.artifact import ArtifactKind
from silo.schemas.upload import FileHashes, StageManifest
from silo.services.entities import slugify

CHUNK_SIZE = 1024 * 1024
STAGING_DIR_NAME = "uploads"
RESERVED_LIBRARY_SLUGS = {STAGING_DIR_NAME}
MANIFEST_NAME = ".stage.json"

_KIND_BY_EXTENSION = {
    ".exe": ArtifactKind.INSTALLER,
    ".msi": ArtifactKind.INSTALLER,
    ".sh": ArtifactKind.INSTALLER,
    ".pkg": ArtifactKind.INSTALLER,
    ".dmg": ArtifactKind.INSTALLER,
    ".iso": ArtifactKind.DISC,
    ".cue": ArtifactKind.DISC,
    ".bin": ArtifactKind.DISC,
    ".img": ArtifactKind.DISC,
    ".chd": ArtifactKind.DISC,
    ".nes": ArtifactKind.ROM,
    ".sfc": ArtifactKind.ROM,
    ".smc": ArtifactKind.ROM,
    ".gb": ArtifactKind.ROM,
    ".gbc": ArtifactKind.ROM,
    ".gba": ArtifactKind.ROM,
    ".n64": ArtifactKind.ROM,
    ".z64": ArtifactKind.ROM,
    ".pdf": ArtifactKind.MANUAL,
}


def stage_dir(library_dir: Path, stage_id: str) -> Path:
    """The stage's directory under the visible uploads/ staging area."""
    return library_dir / STAGING_DIR_NAME / stage_id


def suggest_slug(filename: str) -> str:
    """Slug prefill derived from the uploaded filename."""
    return slugify(Path(filename).stem)


def suggest_kind(filename: str) -> ArtifactKind:
    """Artifact-kind prefill derived from the file extension."""
    return _KIND_BY_EXTENSION.get(Path(filename).suffix.lower(), ArtifactKind.OTHER)


async def write_hashed(chunks: AsyncIterator[bytes], dest: Path) -> tuple[FileHashes, int]:
    """Stream chunks to dest, computing all digests in one pass."""
    b3, h_md5, h_sha1, h_sha256 = blake3(), md5(), sha1(), sha256()
    crc = 0
    size = 0
    with dest.open("wb") as out:
        async for chunk in chunks:
            out.write(chunk)
            b3.update(chunk)
            h_md5.update(chunk)
            h_sha1.update(chunk)
            h_sha256.update(chunk)
            crc = zlib.crc32(chunk, crc)
            size += len(chunk)
    hashes = FileHashes(
        blake3=b3.hexdigest(),
        md5=h_md5.hexdigest(),
        sha1=h_sha1.hexdigest(),
        sha256=h_sha256.hexdigest(),
        crc32=f"{crc & 0xFFFFFFFF:08x}",
    )
    return hashes, size


async def _upload_chunks(upload: UploadFile) -> AsyncIterator[bytes]:
    """The upload's bytes as CHUNK_SIZE chunks."""
    while chunk := await upload.read(CHUNK_SIZE):
        yield chunk


async def write_stage(library_dir: Path, upload: UploadFile) -> tuple[str, StageManifest]:
    """Stream the upload into a new stage dir, computing all digests in one pass."""
    stage_id = uuid.uuid4().hex
    directory = stage_dir(library_dir, stage_id)
    directory.mkdir(parents=True)
    # .name strips any client-supplied path components; '..' passes it, and
    # the manifest name would overwrite the manifest itself.
    filename = Path(upload.filename or "upload.bin").name or "upload.bin"
    if filename in (MANIFEST_NAME, ".."):
        filename = "upload.bin"

    hashes, size = await write_hashed(_upload_chunks(upload), directory / filename)
    manifest = StageManifest(filename=filename, size=size, hashes=hashes)
    (directory / MANIFEST_NAME).write_text(manifest.model_dump_json())
    return stage_id, manifest


def read_stage(library_dir: Path, stage_id: str) -> StageManifest | None:
    """The stage's manifest; None when absent or unreadable."""
    path = stage_dir(library_dir, stage_id) / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        return StageManifest.model_validate_json(path.read_text())
    except ValidationError:
        # A corrupt manifest is consequence-identical to a missing stage.
        return None


def remove_stage(library_dir: Path, stage_id: str) -> None:
    """Delete the stage directory (best-effort)."""
    shutil.rmtree(stage_dir(library_dir, stage_id), ignore_errors=True)


def promote_stage(
    library_dir: Path,
    stage_id: str,
    manifest: StageManifest,
    library_slug: str,
    game_slug: str,
) -> Path:
    """Move the staged file into the library; returns its path relative to library_dir."""
    src = stage_dir(library_dir, stage_id) / manifest.filename
    if not src.is_file():
        raise HTTPException(status_code=404, detail=f"stage {stage_id!r} has no staged file")
    dest_dir = library_dir / library_slug / game_slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / manifest.filename
    if dest.exists():
        raise HTTPException(
            status_code=409, detail=f"file {manifest.filename!r} already exists for this game"
        )
    src.rename(dest)
    remove_stage(library_dir, stage_id)
    return dest.relative_to(library_dir)
