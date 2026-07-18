import zipfile
from datetime import datetime
from io import BytesIO
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.artifact import Artifact, ArtifactKind, ArtifactStatus
from silo.models.file import File
from silo.models.game import Game, GameMetadata
from silo.models.library import Library
from tests.seed import seed_in_order

PDF_BYTES = b"%PDF-1.4 test"


def zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in members.items():
            archive.writestr(path, content)
    return buffer.getvalue()


async def _seed_file(db_session: AsyncSession, settings, name: str, content: bytes) -> File:
    now = datetime(2025, 1, 1)
    library = Library(id=uuid4(), slug="main", name="Main", created_at=now, updated_at=now)
    game = Game(id=uuid4(), library_id=library.id, slug="doom", created_at=now, updated_at=now)
    metadata = GameMetadata(game_id=game.id, title="DOOM")
    artifact = Artifact(
        id=uuid4(), game_id=game.id, kind=ArtifactKind.MANUAL, status=ArtifactStatus.STORED
    )
    relative_path = f"main/doom/{name}"
    on_disk = settings.library_dir / relative_path
    on_disk.parent.mkdir(parents=True, exist_ok=True)
    on_disk.write_bytes(content)
    file = File(id=uuid4(), artifact_id=artifact.id, relative_path=relative_path, size=len(content))
    await seed_in_order(db_session, library, game, metadata, artifact, file)
    return file


async def test_download_file_disposition(db_session: AsyncSession, client: AsyncClient, settings):
    file = await _seed_file(db_session, settings, "manual.pdf", PDF_BYTES)

    resp = await client.get(f"/api/v1/files/{file.id}")
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("attachment")

    resp = await client.get(f"/api/v1/files/{file.id}?inline=true")
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("inline")
    assert resp.headers["content-type"] == "application/pdf"


async def test_download_file_not_found(client: AsyncClient):
    assert (await client.get(f"/api/v1/files/{uuid4()}")).status_code == 404


async def test_download_file_missing_on_disk(
    db_session: AsyncSession, client: AsyncClient, settings
):
    file = await _seed_file(db_session, settings, "manual.pdf", PDF_BYTES)
    (settings.library_dir / "main" / "doom" / "manual.pdf").unlink()

    assert (await client.get(f"/api/v1/files/{file.id}")).status_code == 404


async def test_download_file_member_rejects_non_zip(
    db_session: AsyncSession, client: AsyncClient, settings
):
    file = await _seed_file(db_session, settings, "manual.pdf", PDF_BYTES)

    resp = await client.get(f"/api/v1/files/{file.id}/contents/anything.pdf")
    assert resp.status_code == 422


async def test_list_file_contents(db_session: AsyncSession, client: AsyncClient, settings):
    file = await _seed_file(
        db_session,
        settings,
        "manual.zip",
        zip_bytes({"docs/manual.pdf": PDF_BYTES, "readme.txt": b"hi", "docs/": b""}),
    )

    resp = await client.get(f"/api/v1/files/{file.id}/contents")
    assert resp.status_code == 200
    # Directory entries are skipped.
    assert resp.json() == [
        {"path": "docs/manual.pdf", "size": len(PDF_BYTES)},
        {"path": "readme.txt", "size": 2},
    ]


async def test_list_file_contents_rejects_non_zip(
    db_session: AsyncSession, client: AsyncClient, settings
):
    file = await _seed_file(db_session, settings, "manual.pdf", PDF_BYTES)

    assert (await client.get(f"/api/v1/files/{file.id}/contents")).status_code == 422


async def test_download_file_member(db_session: AsyncSession, client: AsyncClient, settings):
    file = await _seed_file(
        db_session, settings, "manual.zip", zip_bytes({"docs/manual.pdf": PDF_BYTES})
    )

    resp = await client.get(f"/api/v1/files/{file.id}/contents/docs/manual.pdf?inline=true")
    assert resp.status_code == 200
    assert resp.content == PDF_BYTES
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"] == 'inline; filename="manual.pdf"'
    assert resp.headers["content-length"] == str(len(PDF_BYTES))

    # Default disposition stays attachment.
    resp = await client.get(f"/api/v1/files/{file.id}/contents/docs/manual.pdf")
    assert resp.headers["content-disposition"].startswith("attachment")

    assert (await client.get(f"/api/v1/files/{file.id}/contents/missing.pdf")).status_code == 404


async def test_download_file_member_non_latin1_name(
    db_session: AsyncSession, client: AsyncClient, settings
):
    file = await _seed_file(
        db_session, settings, "manual.zip", zip_bytes({"docs/说明书.pdf": PDF_BYTES})
    )

    resp = await client.get(f"/api/v1/files/{file.id}/contents/docs/说明书.pdf")
    assert resp.status_code == 200
    assert resp.content == PDF_BYTES
    assert resp.headers["content-disposition"].startswith("attachment; filename*=utf-8''")
