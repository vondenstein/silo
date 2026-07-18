import uuid

from fastapi import APIRouter, HTTPException, Request, UploadFile
from sqlalchemy import and_, func, select

from silo.api.dependencies import SessionDep, get_or_404
from silo.models.asset import AssetBlob, AssetKind, SourceAsset
from silo.models.game import Game as GameModel
from silo.models.game import GameAsset, GameExternalIdentity
from silo.models.metadata_record import MetadataRecord
from silo.models.metadata_source import MetadataSource
from silo.schemas.game import AssetCandidateOut, AssetKindPut, GameAssetCandidates
from silo.services.assets import asset_url, image_dimensions, store_asset_blob

router = APIRouter(prefix="/games", tags=["games"])

MAX_ASSET_UPLOAD_BYTES = 32 * 1024 * 1024


@router.get("/{game_id}/assets", operation_id="get_game_assets")
async def get_game_assets(
    session: SessionDep,
    game_id: uuid.UUID,
) -> GameAssetCandidates:
    await get_or_404(session, GameModel, game_id, "game")
    candidate_rows = (
        await session.execute(
            select(SourceAsset.kind, SourceAsset.blob_blake3, MetadataSource.slug)
            .join(MetadataRecord, MetadataRecord.id == SourceAsset.metadata_record_id)
            .join(MetadataSource, MetadataSource.id == MetadataRecord.source_id)
            .join(
                GameExternalIdentity,
                and_(
                    GameExternalIdentity.source_id == MetadataRecord.source_id,
                    GameExternalIdentity.external_id == MetadataRecord.external_id,
                ),
            )
            .where(GameExternalIdentity.game_id == game_id)
            .order_by(MetadataSource.priority, SourceAsset.ordinal)
        )
    ).all()
    picks = {
        (row.kind, row.blob_blake3): row
        for row in await session.scalars(
            select(GameAsset).where(GameAsset.game_id == game_id).order_by(GameAsset.ordinal)
        )
    }
    # Pool in (source priority, ordinal) order; picks with no live candidate append after.
    pool: dict[tuple[AssetKind, str], list[str]] = {}
    for kind, blob, slug in candidate_rows:
        pool.setdefault((kind, blob), []).append(slug)
    for key in picks:
        pool.setdefault(key, [])
    blob_ids = [blob for _, blob in pool]
    blobs = {
        blob.blake3: blob
        for blob in await session.scalars(select(AssetBlob).where(AssetBlob.blake3.in_(blob_ids)))
    }
    per_kind: dict[AssetKind, list[AssetCandidateOut]] = {kind: [] for kind in AssetKind}
    for (kind, blob_id), slugs in pool.items():
        pick = picks.get((kind, blob_id))
        per_kind[kind].append(
            AssetCandidateOut(
                blake3=blob_id,
                url=asset_url(blob_id),
                mime=blobs[blob_id].mime,
                size=blobs[blob_id].size,
                width=blobs[blob_id].width,
                height=blobs[blob_id].height,
                source_slugs=slugs,
                visible=pick.visible if pick is not None else None,
                ordinal=pick.ordinal if pick is not None else None,
            )
        )
    return GameAssetCandidates(
        cover=per_kind[AssetKind.COVER],
        background=per_kind[AssetKind.BACKGROUND],
        landscape=per_kind[AssetKind.LANDSCAPE],
        logo=per_kind[AssetKind.LOGO],
        icon=per_kind[AssetKind.ICON],
        screenshot=per_kind[AssetKind.SCREENSHOT],
        video_thumbnail=per_kind[AssetKind.VIDEO_THUMBNAIL],
    )


@router.post("/{game_id}/assets/{kind}", operation_id="upload_game_asset", status_code=201)
async def upload_game_asset(
    request: Request,
    session: SessionDep,
    game_id: uuid.UUID,
    kind: AssetKind,
    file: UploadFile,
) -> AssetCandidateOut:
    await get_or_404(session, GameModel, game_id, "game")
    mime = file.content_type or ""
    if not mime.startswith("image/"):
        raise HTTPException(status_code=422, detail="expected an image upload")
    content = await file.read(MAX_ASSET_UPLOAD_BYTES + 1)
    if len(content) > MAX_ASSET_UPLOAD_BYTES:
        raise HTTPException(status_code=422, detail="asset exceeds the 32 MiB upload limit")
    if image_dimensions(content) is None:
        raise HTTPException(status_code=422, detail="file is not a decodable image")
    digest = await store_asset_blob(session, request.app.state.settings.asset_dir, content, mime)
    row = await session.get(GameAsset, (game_id, kind, digest))
    if row is None:
        last = await session.scalar(
            select(func.max(GameAsset.ordinal)).where(
                GameAsset.game_id == game_id, GameAsset.kind == kind
            )
        )
        row = GameAsset(
            game_id=game_id,
            kind=kind,
            blob_blake3=digest,
            ordinal=0 if last is None else last + 1,
            # Uploads stage un-curated; the curation PUT publishes them.
            visible=False,
        )
        session.add(row)
    await session.flush()
    blob = await session.get(AssetBlob, digest)
    assert blob is not None
    return AssetCandidateOut(
        blake3=digest,
        url=asset_url(digest),
        mime=blob.mime,
        size=blob.size,
        width=blob.width,
        height=blob.height,
        source_slugs=[],
        visible=row.visible,
        ordinal=row.ordinal,
    )


@router.put("/{game_id}/assets/{kind}", operation_id="set_game_assets", status_code=204)
async def set_game_assets(
    session: SessionDep,
    game_id: uuid.UUID,
    kind: AssetKind,
    body: AssetKindPut,
) -> None:
    await get_or_404(session, GameModel, game_id, "game")
    if len(set(body.blobs)) != len(body.blobs):
        raise HTTPException(status_code=422, detail="duplicate blobs")
    existing = {
        row.blob_blake3: row
        for row in await session.scalars(
            select(GameAsset).where(GameAsset.game_id == game_id, GameAsset.kind == kind)
        )
    }
    candidates = set(
        (
            await session.scalars(
                select(SourceAsset.blob_blake3)
                .join(MetadataRecord, MetadataRecord.id == SourceAsset.metadata_record_id)
                .join(
                    GameExternalIdentity,
                    and_(
                        GameExternalIdentity.source_id == MetadataRecord.source_id,
                        GameExternalIdentity.external_id == MetadataRecord.external_id,
                    ),
                )
                .where(GameExternalIdentity.game_id == game_id, SourceAsset.kind == kind)
            )
        ).all()
    )
    unknown = [blob for blob in body.blobs if blob not in candidates and blob not in existing]
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"unknown blobs for {kind}: {', '.join(unknown)}"
        )
    for ordinal, blob in enumerate(body.blobs):
        row = existing.get(blob)
        if row is None:
            session.add(GameAsset(game_id=game_id, kind=kind, blob_blake3=blob, ordinal=ordinal))
        else:
            row.ordinal = ordinal
            row.visible = True
    listed = set(body.blobs)
    for blob, row in existing.items():
        if blob not in listed:
            row.visible = False
    await session.flush()
