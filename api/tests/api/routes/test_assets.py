from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.asset import AssetBlob
from silo.settings import Settings


# Promote to tests/factories.py when a second resource's tests need seeded blobs.
def _blob(blake3: str, mime: str = "image/png", size: int = 0) -> AssetBlob:
    return AssetBlob(blake3=blake3, mime=mime, size=size)


async def _seed(session: AsyncSession, *blobs: AssetBlob) -> None:
    session.add_all(blobs)
    await session.commit()


async def test_get_asset(settings: Settings, db_session: AsyncSession, client: AsyncClient):
    blake3 = "a" * 64
    payload = b"hello bytes"

    asset_dir = settings.data_dir / "metadata" / "assets"
    asset_dir.mkdir(parents=True)
    (asset_dir / blake3).write_bytes(payload)

    await _seed(db_session, _blob(blake3, mime="image/png", size=len(payload)))

    resp = await client.get(f"/api/v1/assets/{blake3}")
    assert resp.status_code == 200
    assert resp.content == payload
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"


async def test_get_asset_db_row_missing(client: AsyncClient):
    resp = await client.get("/api/v1/assets/" + "b" * 64)
    assert resp.status_code == 404


async def test_get_asset_file_missing(db_session: AsyncSession, client: AsyncClient):
    blake3 = "c" * 64
    await _seed(db_session, _blob(blake3, mime="image/png", size=10))

    resp = await client.get(f"/api/v1/assets/{blake3}")
    assert resp.status_code == 404


async def test_get_asset_rejects_invalid_hash(client: AsyncClient):
    resp = await client.get("/api/v1/assets/not-a-blake3-hash")
    assert resp.status_code == 422
