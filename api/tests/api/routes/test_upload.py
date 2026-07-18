import hashlib
import zlib
from uuid import uuid4

import pytest
from blake3 import blake3
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.identification import (
    IdentificationDataset,
    IdentificationSignature,
    IdentificationSource,
)
from silo.services.upload import MANIFEST_NAME

CONTENT = b"doom wad bytes"


async def _create_library(client: AsyncClient, slug: str = "main") -> str:
    resp = await client.post("/api/v1/libraries", json={"slug": slug, "name": slug.capitalize()})
    assert resp.status_code == 201
    return resp.json()["id"]


async def _stage(client: AsyncClient, filename: str = "Doom II.iso") -> dict:
    resp = await client.post("/api/v1/upload/stage", files={"file": (filename, CONTENT)})
    assert resp.status_code == 201
    return resp.json()


async def test_stage_hashes_and_suggestions(client: AsyncClient, settings):
    body = await _stage(client)

    assert body["filename"] == "Doom II.iso"
    assert body["size"] == len(CONTENT)
    assert body["hashes"]["blake3"] == blake3(CONTENT).hexdigest()
    assert body["hashes"]["md5"] == hashlib.md5(CONTENT).hexdigest()
    assert body["hashes"]["sha1"] == hashlib.sha1(CONTENT).hexdigest()
    assert body["hashes"]["sha256"] == hashlib.sha256(CONTENT).hexdigest()
    assert body["hashes"]["crc32"] == f"{zlib.crc32(CONTENT):08x}"
    assert body["suggested_slug"] == "doom-ii"
    assert body["suggested_kind"] == "disc"
    assert body["matches"] == []

    stage_path = settings.library_dir / "uploads" / body["stage_id"]
    assert (stage_path / "Doom II.iso").read_bytes() == CONTENT
    assert (stage_path / MANIFEST_NAME).is_file()


async def test_stage_sanitizes_client_filenames(client: AsyncClient, settings):
    # Path components strip to the basename.
    body = await _stage(client, filename="../evil.bin")
    stage_path = settings.library_dir / "uploads" / body["stage_id"]
    assert body["filename"] == "evil.bin"
    assert (stage_path / "evil.bin").read_bytes() == CONTENT

    # The manifest name and bare '..' fall back instead of colliding/escaping.
    for hostile in (MANIFEST_NAME, ".."):
        body = await _stage(client, filename=hostile)
        stage_path = settings.library_dir / "uploads" / body["stage_id"]
        assert body["filename"] == "upload.bin"
        assert (stage_path / "upload.bin").read_bytes() == CONTENT
        assert (stage_path / MANIFEST_NAME).stat().st_size < len(CONTENT) + 512


async def test_finalize_corrupt_manifest_reads_as_missing(client: AsyncClient, settings):
    library_id = await _create_library(client)
    body = await _stage(client)
    manifest = settings.library_dir / "uploads" / body["stage_id"] / MANIFEST_NAME
    manifest.write_text("{not json")

    resp = await client.post(
        "/api/v1/upload/finalize",
        json={
            "stage_id": body["stage_id"],
            "library_id": library_id,
            "slug": "doom-ii",
            "title": "Doom II",
            "kind": "disc",
        },
    )
    assert resp.status_code == 404


async def test_stage_reports_signature_matches(db_session: AsyncSession, client: AsyncClient):
    source_id = await db_session.scalar(
        select(IdentificationSource.id).where(IdentificationSource.slug == "redump")
    )
    assert source_id is not None
    dataset = IdentificationDataset(
        id=uuid4(), source_id=source_id, slug="redump-pc", name="IBM PC compatible"
    )
    db_session.add(dataset)
    db_session.add(
        IdentificationSignature(
            id=uuid4(),
            dataset_id=dataset.id,
            game_name="Doom II (USA)",
            file_name="Doom II (USA).iso",
            category="Games",
            md5=hashlib.md5(CONTENT).hexdigest(),
        )
    )
    await db_session.commit()

    body = await _stage(client)

    assert [(m["game_name"], m["dataset_name"], m["source_slug"]) for m in body["matches"]] == [
        ("Doom II (USA)", "IBM PC compatible", "redump")
    ]


async def test_finalize_creates_game_artifact_file(client: AsyncClient, settings):
    library_id = await _create_library(client)
    stage = await _stage(client)

    resp = await client.post(
        "/api/v1/upload/finalize",
        json={
            "stage_id": stage["stage_id"],
            "library_id": library_id,
            "slug": "doom-ii",
            "title": "Doom II",
            "kind": "disc",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["identify_job_id"] is None
    game = body["game"]
    assert game["title"] == "Doom II"

    stored = settings.library_dir / "main" / "doom-ii" / "Doom II.iso"
    assert stored.read_bytes() == CONTENT
    assert not (settings.library_dir / "uploads" / stage["stage_id"]).exists()

    detail = (await client.get(f"/api/v1/games/{game['id']}")).json()
    assert len(detail["artifacts"]) == 1
    artifact = detail["artifacts"][0]
    assert artifact["kind"] == "disc"
    assert artifact["status"] == "stored"
    assert artifact["name"] == "Doom II.iso"
    assert len(artifact["files"]) == 1
    assert artifact["files"][0]["relative_path"] == "main/doom-ii/Doom II.iso"
    assert artifact["files"][0]["blake3"] == stage["hashes"]["blake3"]


async def test_finalize_unknown_stage(client: AsyncClient):
    library_id = await _create_library(client)
    resp = await client.post(
        "/api/v1/upload/finalize",
        json={
            "stage_id": "0" * 32,
            "library_id": library_id,
            "slug": "doom",
            "title": "Doom",
            "kind": "disc",
        },
    )
    assert resp.status_code == 404


# The stage_id pattern is the anti-traversal guard before any filesystem join.
@pytest.mark.parametrize(
    "override",
    [
        {"stage_id": "../evil"},
        {"stage_id": "Z" * 32},
        {"slug": "Bad Slug"},
    ],
)
async def test_finalize_rejects_malformed_input(client: AsyncClient, override: dict):
    library_id = await _create_library(client)
    resp = await client.post(
        "/api/v1/upload/finalize",
        json={
            "stage_id": "a" * 32,
            "library_id": library_id,
            "slug": "doom",
            "title": "DOOM",
            "kind": "disc",
            **override,
        },
    )
    assert resp.status_code == 422


# A slash-bearing traversal can't even route here (the router 404s it);
# dot-bearing single segments must die on the pattern.
@pytest.mark.parametrize("stage_id", ["..evil", "Z" * 32, "deadbeef"])
async def test_cancel_rejects_malformed_stage_id(client: AsyncClient, stage_id: str):
    resp = await client.delete(f"/api/v1/upload/stage/{stage_id}")
    assert resp.status_code == 422


async def test_finalize_promote_conflict_rolls_back_game(client: AsyncClient, settings):
    library_id = await _create_library(client)
    first = await _stage(client)
    resp = await client.post(
        "/api/v1/upload/finalize",
        json={
            "stage_id": first["stage_id"],
            "library_id": library_id,
            "slug": "doom",
            "title": "DOOM",
            "kind": "disc",
        },
    )
    assert resp.status_code == 201
    game_id = resp.json()["game"]["id"]

    # Delete keeping files: the slug frees up but the file stays on disk.
    assert (await client.delete(f"/api/v1/games/{game_id}")).status_code == 204
    assert (settings.library_dir / "main" / "doom" / "Doom II.iso").is_file()

    second = await _stage(client)
    resp = await client.post(
        "/api/v1/upload/finalize",
        json={
            "stage_id": second["stage_id"],
            "library_id": library_id,
            "slug": "doom",
            "title": "DOOM",
            "kind": "disc",
        },
    )
    assert resp.status_code == 409

    # The game row rolled back with the failed promote; the stage survives a retry.
    assert (await client.get("/api/v1/games")).json()["items"] == []
    assert (settings.library_dir / "uploads" / second["stage_id"] / "Doom II.iso").is_file()


async def test_finalize_duplicate_slug_keeps_stage(client: AsyncClient, settings):
    library_id = await _create_library(client)
    first = await _stage(client)
    await client.post(
        "/api/v1/upload/finalize",
        json={
            "stage_id": first["stage_id"],
            "library_id": library_id,
            "slug": "doom-ii",
            "title": "Doom II",
            "kind": "disc",
        },
    )

    second = await _stage(client)
    resp = await client.post(
        "/api/v1/upload/finalize",
        json={
            "stage_id": second["stage_id"],
            "library_id": library_id,
            "slug": "doom-ii",
            "title": "Doom II again",
            "kind": "disc",
        },
    )
    assert resp.status_code == 409
    # The staged file survives a failed finalize (rescuable).
    stage_path = settings.library_dir / "uploads" / second["stage_id"]
    assert (stage_path / "Doom II.iso").read_bytes() == CONTENT


async def test_finalize_with_signature_enqueues_identify(
    db_session: AsyncSession, client: AsyncClient
):
    from silo.models.job import Job, JobKind

    source_id = await db_session.scalar(
        select(IdentificationSource.id).where(IdentificationSource.slug == "redump")
    )
    dataset = IdentificationDataset(
        id=uuid4(), source_id=source_id, slug="redump-pc", name="IBM PC compatible"
    )
    signature = IdentificationSignature(
        id=uuid4(),
        dataset_id=dataset.id,
        game_name="Doom II (USA)",
        file_name="Doom II (USA).iso",
        md5=hashlib.md5(CONTENT).hexdigest(),
    )
    db_session.add_all([dataset, signature])
    await db_session.commit()

    library_id = await _create_library(client)
    stage = await _stage(client)
    resp = await client.post(
        "/api/v1/upload/finalize",
        json={
            "stage_id": stage["stage_id"],
            "library_id": library_id,
            "slug": "doom-ii",
            "title": "Doom II",
            "kind": "disc",
            "chosen_signature_id": str(signature.id),
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    game_id = body["game"]["id"]

    jobs = (await db_session.scalars(select(Job).where(Job.kind == JobKind.IDENTIFY_GAME))).all()
    assert [job.payload for job in jobs] == [{"game_id": game_id, "game_name": "Doom II (USA)"}]
    assert body["identify_job_id"] == str(jobs[0].id)


async def test_finalize_unknown_signature(client: AsyncClient):
    library_id = await _create_library(client)
    stage = await _stage(client)
    resp = await client.post(
        "/api/v1/upload/finalize",
        json={
            "stage_id": stage["stage_id"],
            "library_id": library_id,
            "slug": "doom-ii",
            "title": "Doom II",
            "kind": "disc",
            "chosen_signature_id": str(uuid4()),
        },
    )
    assert resp.status_code == 422


async def test_cancel_upload(client: AsyncClient, settings):
    stage = await _stage(client)

    resp = await client.delete(f"/api/v1/upload/stage/{stage['stage_id']}")
    assert resp.status_code == 204
    assert not (settings.library_dir / "uploads" / stage["stage_id"]).exists()

    resp = await client.delete(f"/api/v1/upload/stage/{stage['stage_id']}")
    assert resp.status_code == 404


async def test_download_file(client: AsyncClient):
    library_id = await _create_library(client)
    stage = await _stage(client)
    game = (
        await client.post(
            "/api/v1/upload/finalize",
            json={
                "stage_id": stage["stage_id"],
                "library_id": library_id,
                "slug": "doom-ii",
                "title": "Doom II",
                "kind": "disc",
            },
        )
    ).json()["game"]

    detail = (await client.get(f"/api/v1/games/{game['id']}")).json()
    file_id = detail["artifacts"][0]["files"][0]["id"]

    resp = await client.get(f"/api/v1/files/{file_id}")
    assert resp.status_code == 200
    assert resp.content == CONTENT

    resp = await client.get(f"/api/v1/files/{uuid4()}")
    assert resp.status_code == 404


async def test_reserved_library_slug(client: AsyncClient):
    resp = await client.post("/api/v1/libraries", json={"slug": "uploads", "name": "Uploads"})
    assert resp.status_code == 422
