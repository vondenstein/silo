from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import FileResponse

from silo.api.dependencies import SessionDep
from silo.models.asset import AssetBlob

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("/{blake3}", operation_id="get_asset")
async def get_asset(
    request: Request,
    session: SessionDep,
    blake3: Annotated[str, Path(pattern=r"^[a-f0-9]{64}$")],
) -> FileResponse:
    blob = await session.get(AssetBlob, blake3)
    if blob is None:
        raise HTTPException(status_code=404, detail=f"asset {blake3!r} not found")
    file_path = request.app.state.settings.asset_dir / blake3
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"asset {blake3!r} not found")
    return FileResponse(
        file_path,
        media_type=blob.mime,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
