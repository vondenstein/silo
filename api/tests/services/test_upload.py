import hashlib
import zlib
from io import BytesIO
from pathlib import Path

import pytest
from blake3 import blake3
from fastapi import HTTPException, UploadFile

from silo.schemas.upload import FileHashes, StageManifest
from silo.services.upload import promote_stage, stage_dir, write_hashed, write_stage


async def _chunks(parts: list[bytes]):
    for part in parts:
        yield part


def _manifest(filename: str = "game.bin") -> StageManifest:
    hashes = FileHashes(
        blake3="0" * 64, md5="0" * 32, sha1="0" * 40, sha256="0" * 64, crc32="0" * 8
    )
    return StageManifest(filename=filename, size=3, hashes=hashes)


async def test_write_hashed_chains_digests_across_chunks(tmp_path: Path):
    # Multi-chunk input pins the incremental hashing (crc32 chaining, size
    # accumulation) that single-chunk content can't distinguish from a reset.
    parts = [b"chunk-one|", b"two|", b"and the third part"]
    whole = b"".join(parts)

    hashes, size = await write_hashed(_chunks(parts), tmp_path / "out.bin")

    assert size == len(whole)
    assert (tmp_path / "out.bin").read_bytes() == whole
    assert hashes.blake3 == blake3(whole).hexdigest()
    assert hashes.md5 == hashlib.md5(whole).hexdigest()
    assert hashes.sha1 == hashlib.sha1(whole).hexdigest()
    assert hashes.sha256 == hashlib.sha256(whole).hexdigest()
    assert hashes.crc32 == f"{zlib.crc32(whole) & 0xFFFFFFFF:08x}"


async def test_write_stage_strips_client_path_components(tmp_path: Path):
    upload = UploadFile(BytesIO(b"payload"), filename="../../outside.bin")

    stage_id, manifest = await write_stage(tmp_path, upload)

    assert manifest.filename == "outside.bin"
    directory = stage_dir(tmp_path, stage_id)
    assert (directory / "outside.bin").read_bytes() == b"payload"
    # Nothing escaped the staging area.
    written = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert all(directory in path.parents for path in written)


def test_promote_stage_missing_staged_file_404(tmp_path: Path):
    stage_dir(tmp_path, "a" * 32).mkdir(parents=True)

    with pytest.raises(HTTPException) as exc:
        promote_stage(tmp_path, "a" * 32, _manifest(), "main", "doom")

    assert exc.value.status_code == 404


def test_promote_stage_dest_exists_409(tmp_path: Path):
    # Reachable via delete-keep-files then re-uploading the same slug+filename.
    stage = stage_dir(tmp_path, "b" * 32)
    stage.mkdir(parents=True)
    (stage / "game.bin").write_bytes(b"new")
    dest = tmp_path / "main" / "doom" / "game.bin"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"old")

    with pytest.raises(HTTPException) as exc:
        promote_stage(tmp_path, "b" * 32, _manifest(), "main", "doom")

    assert exc.value.status_code == 409
    # The existing file is untouched and the stage survives for a retry.
    assert dest.read_bytes() == b"old"
    assert (stage / "game.bin").read_bytes() == b"new"
