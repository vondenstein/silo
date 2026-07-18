import os
from io import BytesIO
from pathlib import Path

from blake3 import blake3
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.asset import AssetBlob


def asset_url(blob_blake3: str) -> str:
    """Public URL serving a stored blob."""
    return f"/api/v1/assets/{blob_blake3}"


def image_dimensions(content: bytes) -> tuple[int, int] | None:
    """(width, height) when the bytes decode as an image."""
    try:
        with Image.open(BytesIO(content)) as image:
            return image.size
    except Exception:
        return None


async def store_asset_blob(
    session: AsyncSession, asset_dir: Path, content: bytes, mime: str
) -> str:
    """Content-address the bytes into the asset store; insert-if-absent asset_blob row."""
    digest = blake3(content).hexdigest()
    asset_dir.mkdir(parents=True, exist_ok=True)
    path = asset_dir / digest
    if not path.exists():
        # Write-then-rename: existence must always mean a complete blob
        # (the store is permanent — a truncated write would never heal).
        temp = asset_dir / f"{digest}.tmp"
        temp.write_bytes(content)
        os.replace(temp, path)
    if await session.get(AssetBlob, digest) is None:
        dimensions = image_dimensions(content)
        session.add(
            AssetBlob(
                blake3=digest,
                mime=mime,
                size=len(content),
                width=dimensions[0] if dimensions else None,
                height=dimensions[1] if dimensions else None,
            )
        )
    return digest
