from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request, UploadFile

from silo.api.dependencies import SessionDep
from silo.jobs import enqueue
from silo.jobs.handlers.identify_game import IdentifyGamePayload
from silo.models.artifact import Artifact, ArtifactStatus
from silo.models.file import File
from silo.models.identification import IdentificationSignature
from silo.models.job import JobKind
from silo.schemas.upload import FinalizeOut, FinalizeRequest, StageOut
from silo.services.games import (
    DuplicateSlugError,
    UnknownLibraryError,
    build_game_schema,
    create_game_with_metadata,
)
from silo.services.identification import match_hashes
from silo.services.upload import (
    promote_stage,
    read_stage,
    remove_stage,
    stage_dir,
    suggest_kind,
    suggest_slug,
    write_stage,
)

router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("/stage", operation_id="stage_upload", status_code=201)
async def stage_upload(request: Request, session: SessionDep, file: UploadFile) -> StageOut:
    library_dir = request.app.state.settings.library_dir
    stage_id, manifest = await write_stage(library_dir, file)
    return StageOut(
        stage_id=stage_id,
        filename=manifest.filename,
        size=manifest.size,
        hashes=manifest.hashes,
        suggested_slug=suggest_slug(manifest.filename),
        suggested_kind=suggest_kind(manifest.filename),
        matches=await match_hashes(
            session,
            md5=manifest.hashes.md5,
            sha1=manifest.hashes.sha1,
            sha256=manifest.hashes.sha256,
            crc32=manifest.hashes.crc32,
        ),
    )


@router.post("/finalize", operation_id="finalize_upload", status_code=201)
async def finalize_upload(
    request: Request,
    session: SessionDep,
    body: FinalizeRequest,
) -> FinalizeOut:
    library_dir = request.app.state.settings.library_dir
    manifest = read_stage(library_dir, body.stage_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"stage {body.stage_id!r} not found")
    signature = None
    if body.chosen_signature_id is not None:
        signature = await session.get(IdentificationSignature, body.chosen_signature_id)
        if signature is None:
            raise HTTPException(
                status_code=422, detail=f"signature {body.chosen_signature_id} not found"
            )

    try:
        library, game, metadata = await create_game_with_metadata(
            session, library_id=body.library_id, slug=body.slug, title=body.title
        )
    except UnknownLibraryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except DuplicateSlugError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    artifact = Artifact(
        game_id=game.id,
        kind=body.kind,
        status=ArtifactStatus.STORED,
        total_size=manifest.size,
        name=manifest.filename,
    )
    session.add(artifact)
    await session.flush()

    session.add(
        File(
            artifact_id=artifact.id,
            relative_path=f"{library.slug}/{body.slug}/{manifest.filename}",
            size=manifest.size,
            blake3=manifest.hashes.blake3,
            md5=manifest.hashes.md5,
            sha1=manifest.hashes.sha1,
            sha256=manifest.hashes.sha256,
            crc32=manifest.hashes.crc32,
        )
    )
    identify_job = None
    if signature is not None:
        # The chosen signature is transient: it only seeds the identity bridge.
        identify_job = await enqueue(
            session,
            JobKind.IDENTIFY_GAME,
            IdentifyGamePayload(game_id=game.id, game_name=signature.game_name),
        )
    await session.flush()
    # Promote last: the rename destroys resume state, so every DB write must
    # have flushed first — a failure here rolls the rows back with the stage
    # intact.
    promote_stage(library_dir, body.stage_id, manifest, library.slug, body.slug)
    return FinalizeOut(
        game=build_game_schema(game, metadata),
        identify_job_id=identify_job.id if identify_job else None,
    )


@router.delete("/stage/{stage_id}", operation_id="cancel_upload", status_code=204)
async def cancel_upload(
    request: Request,
    stage_id: Annotated[str, Path(pattern=r"^[a-f0-9]{32}$")],
) -> None:
    library_dir = request.app.state.settings.library_dir
    if not stage_dir(library_dir, stage_id).is_dir():
        raise HTTPException(status_code=404, detail=f"stage {stage_id!r} not found")
    remove_stage(library_dir, stage_id)
