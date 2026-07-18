import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel
from sqlalchemy import select

from silo.jobs.registry import JobContext, JobHandler, register
from silo.models.artifact import Artifact, ArtifactKind, ArtifactStatus
from silo.models.file import File
from silo.models.game import Game, GameExternalIdentity, GameMetadata, GameOrigin
from silo.models.job import JobKind
from silo.models.library import Library
from silo.models.metadata_source import MetadataSource
from silo.models.platform import Platform
from silo.schemas.job import JobStage, JobStageStatus
from silo.schemas.upload import FileHashes
from silo.services.games import DuplicateSlugError, create_game_with_metadata
from silo.services.metadata_fetch import fetch_game_metadata
from silo.services.upload import suggest_slug, write_hashed
from silo.sources.client import USER_AGENT
from silo.sources.gog import GogClient, fresh_access_token, request_interval

_DOWNLOAD_KINDS = {
    "installers": ArtifactKind.INSTALLER,
    "patches": ArtifactKind.PATCH,
    "language_packs": ArtifactKind.LANGUAGE_PACK,
}
_BONUS_KINDS = {"manuals": ArtifactKind.MANUAL}

# GOG download-entry os → seeded platform slug.
_OS_PLATFORM_SLUGS = {"windows": "windows", "mac": "macos", "linux": "linux"}


class DownloadPolicy(BaseModel):
    """Which GOG download groups to fetch; the future download-policy setting fills this."""

    installers: bool = True
    patches: bool = True
    language_packs: bool = True
    bonus_content: bool = True


class GogImportPayload(BaseModel):
    gog_id: int
    library_id: uuid.UUID
    policy: DownloadPolicy = DownloadPolicy()


class GogImportProgress(BaseModel):
    stages: list[JobStage]


class GogImportResult(BaseModel):
    game_id: uuid.UUID


async def _counted(
    chunks: AsyncIterator[bytes], on_bytes: Callable[[int], Awaitable[None]]
) -> AsyncIterator[bytes]:
    done = 0
    async for chunk in chunks:
        done += len(chunk)
        await on_bytes(done)
        yield chunk


async def fetch_hashed(
    url: str, dest: Path, on_bytes: Callable[[int], Awaitable[None]] | None = None
) -> tuple[FileHashes, int]:
    """Stream a download to dest, hashing in one pass; on_bytes gets cumulative bytes."""
    # read is per-chunk: it only fires when NO bytes arrive — a stalled
    # connection must not hang the sequential worker forever.
    timeout = httpx.Timeout(30.0, read=300.0)
    async with (
        httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        ) as client,
        client.stream("GET", url) as resp,
    ):
        resp.raise_for_status()
        chunks = resp.aiter_bytes()
        if on_bytes is not None:
            chunks = _counted(chunks, on_bytes)
        return await write_hashed(chunks, dest)


def _plan_downloads(
    raw: dict[str, Any], policy: DownloadPolicy
) -> list[tuple[dict[str, Any], str | None, list[tuple[str, str, int | None]]]]:
    """(artifact columns, entry os, [(source_file_id, downlink, size)]) per selected entry."""
    downloads = raw.get("downloads") or {}
    plan: list[tuple[dict[str, Any], str | None, list[tuple[str, str, int | None]]]] = []

    def entry_files(entry: dict[str, Any]) -> list[tuple[str, str, int | None]]:
        return [
            (str(f.get("id")), f["downlink"], f.get("size"))
            for f in entry.get("files") or []
            if f.get("downlink")
        ]

    for group, kind in _DOWNLOAD_KINDS.items():
        if not getattr(policy, group):
            continue
        for entry in downloads.get(group) or []:
            files = entry_files(entry)
            if not files:
                continue
            plan.append(
                (
                    {
                        "kind": kind,
                        "language": entry.get("language"),
                        "version": entry.get("version"),
                        "total_size": entry.get("total_size"),
                        "name": str(entry.get("name") or entry.get("id") or kind),
                    },
                    entry.get("os"),
                    files,
                )
            )
    if policy.bonus_content:
        for entry in downloads.get("bonus_content") or []:
            files = entry_files(entry)
            if not files:
                continue
            plan.append(
                (
                    {
                        "kind": _BONUS_KINDS.get(entry.get("type", ""), ArtifactKind.EXTRA),
                        "language": None,
                        "version": None,
                        "total_size": entry.get("total_size"),
                        "name": str(entry.get("name") or entry.get("id") or "extra"),
                    },
                    None,
                    files,
                )
            )
    return plan


async def _reconcile_manifest(
    ctx: JobContext, game_id: uuid.UUID, raw: dict[str, Any], policy: DownloadPolicy
) -> None:
    """Create missing artifact + placeholder file rows for the planned downloads."""
    async with ctx.sessionmaker() as session:
        platform_id_by_slug = {
            row.slug: row.id for row in (await session.execute(select(Platform))).scalars()
        }
        artifacts = list(
            (await session.execute(select(Artifact).where(Artifact.game_id == game_id))).scalars()
        )
        by_key = {(a.kind, a.name, a.language, a.version, a.platform_id): a for a in artifacts}
        artifact_ids = [a.id for a in artifacts]
        known_source_ids = set(
            (
                await session.execute(
                    select(File.source_file_id).where(File.artifact_id.in_(artifact_ids))
                )
            ).scalars()
            if artifact_ids
            else []
        )

        for artifact_columns, operating_system, files in _plan_downloads(raw, policy):
            platform_id = platform_id_by_slug.get(
                _OS_PLATFORM_SLUGS.get(operating_system or "", "")
            )
            key = (
                artifact_columns["kind"],
                artifact_columns["name"],
                artifact_columns["language"],
                artifact_columns["version"],
                platform_id,
            )
            artifact = by_key.get(key)
            if artifact is None:
                artifact = Artifact(
                    game_id=game_id,
                    status=ArtifactStatus.MISSING,
                    platform_id=platform_id,
                    **artifact_columns,
                )
                session.add(artifact)
                await session.flush()
                by_key[key] = artifact
            for source_file_id, downlink, size in files:
                if source_file_id in known_source_ids:
                    continue
                session.add(
                    File(
                        artifact_id=artifact.id,
                        source_file_id=source_file_id,
                        download_url=downlink,
                        size=size,
                    )
                )
                known_source_ids.add(source_file_id)
        await session.commit()


async def _find_or_create_game(
    ctx: JobContext, payload: GogImportPayload, raw: dict[str, Any]
) -> tuple[uuid.UUID, str, str]:
    """Find the game by gog identity or create it; returns (id, library slug, game slug)."""
    async with ctx.sessionmaker() as session:
        gog_source_id = await session.scalar(
            select(MetadataSource.id).where(MetadataSource.slug == "gog")
        )
        if gog_source_id is None:
            raise RuntimeError("gog metadata_source row is missing")
        external_id = str(payload.gog_id)
        row = (
            await session.execute(
                select(Game, Library.slug)
                .join(Library, Library.id == Game.library_id)
                .join(GameExternalIdentity, GameExternalIdentity.game_id == Game.id)
                .where(
                    GameExternalIdentity.source_id == gog_source_id,
                    GameExternalIdentity.external_id == external_id,
                )
            )
        ).first()
        if row is not None:
            # An existing game wins over payload.library_id — resume, not move.
            existing, library_slug = row
            return existing.id, library_slug, existing.slug

        title = str(raw.get("title") or f"GOG {payload.gog_id}")
        base = (suggest_slug(str(raw.get("slug") or title)) or f"gog-{payload.gog_id}")[:48]
        game: Game | None = None
        library: Library | None = None
        metadata: GameMetadata | None = None
        for slug in (base, f"{base}-gog", f"{base}-gog-{payload.gog_id}"):
            try:
                library, game, metadata = await create_game_with_metadata(
                    session, library_id=payload.library_id, slug=slug, title=title
                )
                break
            except DuplicateSlugError:
                # Failed flush pending — clear it before the next candidate.
                await session.rollback()
        if game is None or library is None or metadata is None:
            raise RuntimeError("could not allocate a slug for the imported game")

        game.origin = GameOrigin.GOG_IMPORT
        session.add(
            GameExternalIdentity(game_id=game.id, source_id=gog_source_id, external_id=external_id)
        )
        await session.commit()
        return game.id, library.slug, game.slug


async def run_gog_import(ctx: JobContext, payload: GogImportPayload) -> GogImportResult:
    stages = [
        JobStage(key="game", label="Create game", group="Setup", status=JobStageStatus.RUNNING)
    ]

    async def report() -> None:
        await ctx.report_progress(GogImportProgress(stages=stages))

    await report()
    async with ctx.sessionmaker() as session:
        token = await fresh_access_token(session)
        interval = await request_interval(session)
        await session.commit()

    async with GogClient(token, request_interval_ms=interval) as client:
        raw = await client.product(payload.gog_id)
        game_id, library_slug, game_slug = await _find_or_create_game(ctx, payload, raw)
        stages[0].status = JobStageStatus.COMPLETED
        await report()

        service_len = 0

        async def on_service(service_stages: list[JobStage]) -> None:
            nonlocal service_len
            stages[1 : 1 + service_len] = service_stages
            service_len = len(service_stages)
            await report()

        async with ctx.sessionmaker() as session:
            game = await session.get(Game, game_id)
            if game is not None:
                await fetch_game_metadata(
                    session,
                    game,
                    ctx.settings.asset_dir,
                    gog_client=client,
                    galaxy_raw=raw,
                    progress=on_service,
                )

        await _reconcile_manifest(ctx, game_id, raw, payload.policy)

        async with ctx.sessionmaker() as session:
            manifest = (
                await session.execute(
                    select(File, Artifact)
                    .join(Artifact, Artifact.id == File.artifact_id)
                    .where(Artifact.game_id == game_id)
                    .order_by(File.created_at)
                )
            ).all()
            platform_names = {
                row.id: row.name for row in (await session.execute(select(Platform))).scalars()
            }

        part_counts = Counter(artifact.id for _, artifact in manifest)
        parts_seen: Counter[uuid.UUID] = Counter()
        file_stages: dict[uuid.UUID, JobStage] = {}
        for file, artifact in manifest:
            parts_seen[artifact.id] += 1
            label = artifact.name or str(artifact.kind)
            if artifact.platform_id is not None:
                platform_name = platform_names[artifact.platform_id]
                # GOG entry names often carry the OS already — don't repeat it.
                if platform_name.lower() not in label.lower():
                    label = f"{label} ({platform_name})"
            if part_counts[artifact.id] > 1:
                label = f"{label} ({parts_seen[artifact.id]}/{part_counts[artifact.id]})"
            file_stages[file.id] = JobStage(
                key=file.source_file_id or str(file.id),
                label=label,
                group="Files",
                status=JobStageStatus.COMPLETED if file.blake3 else JobStageStatus.PENDING,
                bytes_total=file.size,
            )
        stages.extend(file_stages.values())
        await report()

        pending = [file for file, _ in manifest if file.blake3 is None]
        failures: list[str] = []
        dest_dir = ctx.settings.library_dir / library_slug / game_slug
        dest_dir.mkdir(parents=True, exist_ok=True)
        last_report = time.monotonic()

        for file in pending:
            stage = file_stages[file.id]
            label = file.source_file_id or str(file.id)
            try:
                if file.download_url is None:
                    raise RuntimeError("file has no download URL")
                url = await client.download_url(file.download_url)
                filename = Path(urlparse(url).path).name or f"{label}.bin"
                stage.status = JobStageStatus.RUNNING
                await report()
                async with ctx.sessionmaker() as session:
                    artifact = await session.get(Artifact, file.artifact_id)
                    if artifact is not None and artifact.status == ArtifactStatus.MISSING:
                        artifact.status = ArtifactStatus.PARTIAL
                        await session.commit()

                async def on_bytes(done: int, stage: JobStage = stage) -> None:
                    nonlocal last_report
                    stage.bytes_done = done
                    if time.monotonic() - last_report >= 1.0:
                        last_report = time.monotonic()
                        await report()

                # Disk leftovers under this name are untrusted; write_hashed truncates them.
                dest = dest_dir / filename
                hashes, size = await fetch_hashed(url, dest, on_bytes)
                async with ctx.sessionmaker() as session:
                    stored = await session.get(File, file.id)
                    if stored is not None:
                        stored.relative_path = str(dest.relative_to(ctx.settings.library_dir))
                        stored.size = size
                        stored.blake3 = hashes.blake3
                        stored.md5 = hashes.md5
                        stored.sha1 = hashes.sha1
                        stored.sha256 = hashes.sha256
                        stored.crc32 = hashes.crc32
                    remaining = await session.scalar(
                        select(File.id)
                        .where(File.artifact_id == file.artifact_id, File.blake3.is_(None))
                        .limit(1)
                    )
                    if remaining is None:
                        artifact = await session.get(Artifact, file.artifact_id)
                        if artifact is not None:
                            artifact.status = ArtifactStatus.STORED
                    await session.commit()
                stage.bytes_done = size
                stage.status = JobStageStatus.COMPLETED
            except Exception as exc:
                stage.status = JobStageStatus.FAILED
                stage.error = f"{type(exc).__name__}: {exc}"
                failures.append(f"{label}: {type(exc).__name__}: {exc}")
            await report()

    if failures:
        summary = "; ".join(failures[:3]) + ("; …" if len(failures) > 3 else "")
        raise RuntimeError(f"{len(failures)} of {len(pending)} files failed: {summary}")
    return GogImportResult(game_id=game_id)


register(
    JobKind.GOG_IMPORT,
    JobHandler(GogImportPayload, GogImportProgress, GogImportResult, run_gog_import),
)
