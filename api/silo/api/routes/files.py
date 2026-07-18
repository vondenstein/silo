import mimetypes
import uuid
import zipfile
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from silo.api.dependencies import SessionDep
from silo.models.file import File
from silo.schemas.file import ZipMemberOut

router = APIRouter(prefix="/files", tags=["files"])


async def _stored_path(request: Request, session: AsyncSession, file_id: uuid.UUID) -> Path:
    file = await session.get(File, file_id)
    if file is None or file.relative_path is None:
        raise HTTPException(status_code=404, detail=f"file {file_id} not found")
    path = request.app.state.settings.library_dir / file.relative_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"file {file_id} is not on disk")
    return path


def _disposition(inline: bool) -> str:
    return "inline" if inline else "attachment"


def _content_disposition(inline: bool, filename: str) -> str:
    """RFC 6266 header value (what FileResponse does): ASCII quoted, else filename*."""
    quoted = quote(filename)
    if quoted == filename:
        return f'{_disposition(inline)}; filename="{filename}"'
    return f"{_disposition(inline)}; filename*=utf-8''{quoted}"


@router.get("/{file_id}", operation_id="download_file")
async def download_file(
    request: Request,
    session: SessionDep,
    file_id: uuid.UUID,
    inline: bool = False,
) -> FileResponse:
    path = await _stored_path(request, session, file_id)
    return FileResponse(path, filename=path.name, content_disposition_type=_disposition(inline))


@router.get("/{file_id}/contents", operation_id="list_file_contents")
async def list_file_contents(
    request: Request,
    session: SessionDep,
    file_id: uuid.UUID,
) -> list[ZipMemberOut]:
    path = await _stored_path(request, session, file_id)
    members = await run_in_threadpool(_zip_members, path)
    if members is None:
        raise HTTPException(status_code=422, detail=f"file {file_id} is not a zip archive")
    return members


def _zip_members(path: Path) -> list[ZipMemberOut] | None:
    """Member listing, or None for a non-zip (runs in the threadpool — NAS reads)."""
    if not zipfile.is_zipfile(path):
        return None
    with zipfile.ZipFile(path) as archive:
        return [
            ZipMemberOut(path=info.filename, size=info.file_size)
            for info in archive.infolist()
            if not info.is_dir()
        ]


def _zip_member_info(path: Path, member: str) -> zipfile.ZipInfo | None:
    """Single member lookup, or None when absent; ValueError for a non-zip
    (runs in the threadpool — NAS reads)."""
    if not zipfile.is_zipfile(path):
        raise ValueError("not a zip archive")
    with zipfile.ZipFile(path) as archive:
        try:
            return archive.getinfo(member)
        except KeyError:
            return None


def _iter_member(path: Path, member: str) -> Iterator[bytes]:
    with zipfile.ZipFile(path) as archive, archive.open(member) as handle:
        while chunk := handle.read(256 * 1024):
            yield chunk


@router.get("/{file_id}/contents/{member_path:path}", operation_id="download_file_member")
async def download_file_member(
    request: Request,
    session: SessionDep,
    file_id: uuid.UUID,
    member_path: str,
    inline: bool = False,
) -> StreamingResponse:
    path = await _stored_path(request, session, file_id)
    try:
        info = await run_in_threadpool(_zip_member_info, path, member_path)
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"file {file_id} is not a zip archive"
        ) from None
    if info is None:
        raise HTTPException(status_code=404, detail=f"no member {member_path!r} in file {file_id}")
    filename = member_path.rsplit("/", 1)[-1]
    media_type = mimetypes.guess_type(member_path)[0] or "application/octet-stream"
    return StreamingResponse(
        _iter_member(path, member_path),
        media_type=media_type,
        headers={
            "Content-Length": str(info.file_size),
            "Content-Disposition": _content_disposition(inline, filename),
        },
    )
