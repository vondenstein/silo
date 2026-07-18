from io import BytesIO
from pathlib import Path

from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.asset import AssetBlob
from silo.services.assets import image_dimensions, store_asset_blob


def png_bytes(width: int = 4, height: int = 3) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_image_dimensions():
    assert image_dimensions(png_bytes(7, 5)) == (7, 5)
    assert image_dimensions(b"not an image") is None


async def test_store_asset_blob_writes_file_row_and_dimensions(
    db_session: AsyncSession, tmp_path: Path
):
    asset_dir = tmp_path / "assets"
    content = png_bytes(8, 6)

    digest = await store_asset_blob(db_session, asset_dir, content, "image/png")

    assert (asset_dir / digest).read_bytes() == content
    blob = await db_session.get(AssetBlob, digest)
    assert blob is not None
    assert (blob.mime, blob.size, blob.width, blob.height) == ("image/png", len(content), 8, 6)


async def test_store_asset_blob_is_idempotent(db_session: AsyncSession, tmp_path: Path):
    asset_dir = tmp_path / "assets"
    content = png_bytes()

    first = await store_asset_blob(db_session, asset_dir, content, "image/png")
    second = await store_asset_blob(db_session, asset_dir, content, "image/png")

    assert first == second


async def test_store_asset_blob_non_image_has_no_dimensions(
    db_session: AsyncSession, tmp_path: Path
):
    digest = await store_asset_blob(db_session, tmp_path, b"plain bytes", "text/plain")

    blob = await db_session.get(AssetBlob, digest)
    assert blob is not None
    assert (blob.width, blob.height) == (None, None)
