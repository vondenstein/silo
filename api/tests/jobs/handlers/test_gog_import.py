import copy
import hashlib
import uuid
import zlib
from pathlib import Path
from typing import Any

import pytest
from blake3 import blake3
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from silo.jobs.handlers.gog_import import (
    DownloadPolicy,
    GogImportPayload,
    _counted,
    _find_or_create_game,
)
from silo.jobs.registry import JobContext
from silo.jobs.worker import enqueue, run_next_job
from silo.models.job import Job, JobKind, JobStatus
from silo.schemas.upload import FileHashes
from silo.sources.gog import GogClient
from silo.sources.steam import SteamClient

SessionFactory = async_sessionmaker[AsyncSession]

CONTENT = b"gog installer bytes"

PRODUCT: dict[str, Any] = {
    "id": 42,
    "title": "Test Game",
    "slug": "test_game",
    "game_type": "game",
    "description": {"full": "<p>An import.</p>"},
    "downloads": {
        "installers": [
            {
                "id": "installer_windows_en",
                "os": "windows",
                "language": "en",
                "version": "1.0",
                "total_size": 38,
                "name": "Test Game (Windows)",
                "files": [
                    {"id": "en1", "size": 19, "downlink": "https://api.gog.com/dl/en1"},
                    {"id": "en2", "size": 19, "downlink": "https://api.gog.com/dl/en2"},
                ],
            }
        ],
        "patches": [],
        "language_packs": [],
        "bonus_content": [
            {
                "id": 9,
                "name": "manual",
                "type": "manuals",
                "count": 1,
                "total_size": 19,
                "files": [{"id": 9, "size": 19, "downlink": "https://api.gog.com/dl/9"}],
            }
        ],
    },
}

STORE: dict[str, Any] = {
    "description": "<p>Store full.</p>",
    "_embedded": {
        "product": {"title": "Test Game", "globalReleaseDate": "2013-01-16T00:00:00+02:00"},
        "productType": "GAME",
    },
}
GAMESDB: dict[str, Any] = {
    "game": {
        "title": {"*": "Test Game"},
        "sorting_title": {"*": "Game 1"},
        "summary": {"*": "Short."},
        "first_release_date": "2012-11-27T00:00:00+0000",
        "type": "game",
    }
}


def _content_hashes() -> tuple[FileHashes, int]:
    return (
        FileHashes(
            blake3=blake3(CONTENT).hexdigest(),
            md5=hashlib.md5(CONTENT).hexdigest(),
            sha1=hashlib.sha1(CONTENT).hexdigest(),
            sha256=hashlib.sha256(CONTENT).hexdigest(),
            crc32=f"{zlib.crc32(CONTENT):08x}",
        ),
        len(CONTENT),
    )


@pytest.fixture
def gog_stubbed(monkeypatch: pytest.MonkeyPatch):
    async def fake_fresh(session) -> str:
        return "tok"

    async def fake_product(self: GogClient, gog_id: int) -> dict[str, Any]:
        assert gog_id == 42
        return PRODUCT

    async def fake_product_v2(self: GogClient, gog_id: int) -> dict[str, Any]:
        return STORE

    async def fake_gamesdb(self: GogClient, gog_id: int) -> dict[str, Any]:
        return GAMESDB

    async def fake_appdetails(self: SteamClient, app_id: int) -> dict[str, Any] | None:
        return {"name": "Steam Stub", "type": "game"}

    async def fake_download_url(self: GogClient, downlink: str) -> str:
        return f"https://cdn.gog.com/{downlink.rsplit('/', 1)[-1]}.bin"

    async def fake_fetch(url: str, dest: Path, on_bytes=None) -> tuple[FileHashes, int]:
        dest.write_bytes(CONTENT)
        return _content_hashes()

    monkeypatch.setattr("silo.jobs.handlers.gog_import.fresh_access_token", fake_fresh)
    monkeypatch.setattr(GogClient, "product", fake_product)
    monkeypatch.setattr(GogClient, "product_v2", fake_product_v2)
    monkeypatch.setattr(GogClient, "gamesdb_release", fake_gamesdb)
    monkeypatch.setattr(SteamClient, "appdetails", fake_appdetails)
    monkeypatch.setattr(GogClient, "download_url", fake_download_url)
    monkeypatch.setattr("silo.jobs.handlers.gog_import.fetch_hashed", fake_fetch)


async def _create_library(client: AsyncClient, slug: str = "main") -> str:
    resp = await client.post("/api/v1/libraries", json={"slug": slug, "name": slug.capitalize()})
    assert resp.status_code == 201
    return resp.json()["id"]


async def _job(session_factory: SessionFactory, job_id: uuid.UUID | str) -> Job:
    async with session_factory() as session:
        job = await session.get(Job, uuid.UUID(str(job_id)))
        assert job is not None
        return job


async def test_import_full_cycle(
    client: AsyncClient, session_factory: SessionFactory, settings, gog_stubbed
):
    library_id = await _create_library(client)

    resp = await client.post("/api/v1/gog/import", json={"gog_id": 42, "library_id": library_id})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    assert await run_next_job(session_factory, settings) is True

    job = await _job(session_factory, job_id)
    assert job.error is None
    assert job.status == JobStatus.COMPLETED
    assert job.result is not None
    stages = job.progress["stages"]
    assert [(s["key"], s["status"]) for s in stages] == [
        ("game", "completed"),
        ("gog", "completed"),
        ("gog_store", "completed"),
        ("gog_gamesdb", "completed"),
        ("resolve", "completed"),
        ("en1", "completed"),
        ("en2", "completed"),
        ("9", "completed"),
    ]
    assert [s["label"] for s in stages[5:]] == [
        "Test Game (Windows) (1/2)",
        "Test Game (Windows) (2/2)",
        "manual",
    ]
    assert stages[0]["label"] == "Create game"
    assert [s["group"] for s in stages] == [
        "Setup",
        "Metadata",
        "Metadata",
        "Metadata",
        "Resolve",
    ] + ["Files"] * 3
    assert stages[5]["bytes_done"] == len(CONTENT)
    assert stages[5]["bytes_total"] == 19
    game_id = job.result["game_id"]

    detail = (await client.get(f"/api/v1/games/{game_id}")).json()
    assert detail["slug"] == "test-game"
    assert detail["title"] == "Test Game"
    assert detail["origin"] == "gog_import"
    # Resolution spans galaxy + the inline family fetch (store/gamesdb).
    assert detail["description_full"] == "<p>An import.</p>"
    assert detail["game_type"] == "main"
    assert detail["sort_title"] == "Game 1"
    assert detail["description_short"] == "Short."
    assert detail["first_release_date"] == "2012-11-27"
    assert detail["resolved_at"] is not None

    kinds = {a["kind"]: a for a in detail["artifacts"]}
    assert set(kinds) == {"installer", "manual"}
    assert kinds["installer"]["language"] == "en"
    assert kinds["installer"]["version"] == "1.0"
    assert kinds["installer"]["status"] == "stored"
    assert len(kinds["installer"]["files"]) == 2
    assert len(kinds["manual"]["files"]) == 1

    on_disk = sorted(p.name for p in (settings.library_dir / "main" / "test-game").iterdir())
    assert on_disk == ["9.bin", "en1.bin", "en2.bin"]

    # Re-import is accepted now (the resume path); duplicates are blocked only while active.
    resp = await client.post("/api/v1/gog/import", json={"gog_id": 42, "library_id": library_id})
    assert resp.status_code == 202


async def test_import_slug_fallback(
    client: AsyncClient, session_factory: SessionFactory, settings, gog_stubbed
):
    library_id = await _create_library(client)
    taken = await client.post(
        "/api/v1/games",
        json={"library_id": library_id, "slug": "test-game", "title": "Occupies the slug"},
    )
    assert taken.status_code == 201

    resp = await client.post("/api/v1/gog/import", json={"gog_id": 42, "library_id": library_id})
    assert resp.status_code == 202
    assert await run_next_job(session_factory, settings) is True

    job = await _job(session_factory, resp.json()["job_id"])
    assert job.status == JobStatus.COMPLETED
    assert job.result is not None
    detail = (await client.get(f"/api/v1/games/{job.result['game_id']}")).json()
    assert detail["slug"] == "test-game-gog"


async def test_import_splits_artifacts_per_os(
    client: AsyncClient,
    session_factory: SessionFactory,
    settings,
    gog_stubbed,
    monkeypatch: pytest.MonkeyPatch,
):
    product = copy.deepcopy(PRODUCT)
    product["downloads"]["installers"] = [
        {**product["downloads"]["installers"][0], "name": "Test Game"},
        {
            "id": "installer_mac_en",
            "os": "mac",
            "language": "en",
            "version": "1.0",
            "total_size": 19,
            "name": "Test Game",
            "files": [{"id": "mac1", "size": 19, "downlink": "https://api.gog.com/dl/mac1"}],
        },
    ]

    async def fake_product(self: GogClient, gog_id: int) -> dict[str, Any]:
        return product

    monkeypatch.setattr(GogClient, "product", fake_product)
    library_id = await _create_library(client)

    resp = await client.post("/api/v1/gog/import", json={"gog_id": 42, "library_id": library_id})
    assert await run_next_job(session_factory, settings) is True
    job = await _job(session_factory, resp.json()["job_id"])
    assert job.status == JobStatus.COMPLETED
    assert job.result is not None

    detail = (await client.get(f"/api/v1/games/{job.result['game_id']}")).json()
    installers = {a["platform_slug"]: a for a in detail["artifacts"] if a["kind"] == "installer"}
    assert set(installers) == {"windows", "macos"}
    assert len(installers["windows"]["files"]) == 2
    assert len(installers["macos"]["files"]) == 1
    assert installers["windows"]["total_size"] == 38
    assert installers["macos"]["total_size"] == 19

    labels = [s["label"] for s in job.progress["stages"] if s["group"] == "Files"]
    assert labels == [
        "Test Game (Windows) (1/2)",
        "Test Game (Windows) (2/2)",
        "Test Game (macOS)",
        "manual",
    ]


async def test_import_policy_narrows_downloads(
    client: AsyncClient, session_factory: SessionFactory, settings, gog_stubbed
):
    library_id = await _create_library(client)
    async with session_factory() as session:
        job = await enqueue(
            session,
            JobKind.GOG_IMPORT,
            GogImportPayload(
                gog_id=42,
                library_id=uuid.UUID(library_id),
                policy=DownloadPolicy(bonus_content=False),
            ),
        )
        await session.commit()

    assert await run_next_job(session_factory, settings) is True
    job = await _job(session_factory, job.id)
    assert job.status == JobStatus.COMPLETED
    assert job.result is not None

    detail = (await client.get(f"/api/v1/games/{job.result['game_id']}")).json()
    assert [a["kind"] for a in detail["artifacts"]] == ["installer"]


async def test_import_unknown_library(client: AsyncClient):
    resp = await client.post(
        "/api/v1/gog/import",
        json={"gog_id": 42, "library_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 422


async def test_import_duplicate_active_job_rejected(client: AsyncClient):
    library_id = await _create_library(client)

    first = await client.post("/api/v1/gog/import", json={"gog_id": 42, "library_id": library_id})
    assert first.status_code == 202
    dup = await client.post("/api/v1/gog/import", json={"gog_id": 42, "library_id": library_id})
    assert dup.status_code == 409
    other = await client.post("/api/v1/gog/import", json={"gog_id": 7, "library_id": library_id})
    assert other.status_code == 202


async def test_find_or_create_game_is_idempotent(
    client: AsyncClient, session_factory: SessionFactory, settings
):
    library_id = await _create_library(client)
    ctx = JobContext(job_id=uuid.uuid4(), sessionmaker=session_factory, settings=settings)
    payload = GogImportPayload(gog_id=42, library_id=uuid.UUID(library_id))

    first = await _find_or_create_game(ctx, payload, PRODUCT)
    second = await _find_or_create_game(ctx, payload, PRODUCT)

    assert first == second


async def test_import_resume_completes_partial(
    client: AsyncClient,
    session_factory: SessionFactory,
    settings,
    gog_stubbed,
    monkeypatch: pytest.MonkeyPatch,
):
    library_id = await _create_library(client)
    attempts: list[str] = []

    async def flaky_fetch(url: str, dest: Path, on_bytes=None) -> tuple[FileHashes, int]:
        attempts.append(url)
        if "en2" in url and sum("en2" in u for u in attempts) == 1:
            raise RuntimeError("network died")
        dest.write_bytes(CONTENT)
        return _content_hashes()

    monkeypatch.setattr("silo.jobs.handlers.gog_import.fetch_hashed", flaky_fetch)

    resp = await client.post("/api/v1/gog/import", json={"gog_id": 42, "library_id": library_id})
    assert await run_next_job(session_factory, settings) is True
    job = await _job(session_factory, resp.json()["job_id"])
    assert job.status == JobStatus.FAILED
    assert job.error is not None
    assert "1 of 3 files failed" in job.error
    assert "en2" in job.error
    failed_stages = {s["key"]: s for s in job.progress["stages"]}
    assert failed_stages["en2"]["status"] == "failed"
    assert "network died" in failed_stages["en2"]["error"]

    game_id = (await client.get("/api/v1/games")).json()["items"][0]["id"]
    detail = (await client.get(f"/api/v1/games/{game_id}")).json()
    kinds = {a["kind"]: a for a in detail["artifacts"]}
    # Continue-on-error: the manual landed despite the installer failure.
    assert kinds["manual"]["status"] == "stored"
    assert kinds["installer"]["status"] == "partial"
    assert sorted(f["blake3"] is not None for f in kinds["installer"]["files"]) == [False, True]

    resume = await client.post("/api/v1/gog/import", json={"gog_id": 42, "library_id": library_id})
    assert resume.status_code == 202
    assert await run_next_job(session_factory, settings) is True
    job = await _job(session_factory, resume.json()["job_id"])
    assert job.status == JobStatus.COMPLETED
    # The resume job's manifest view shows previously-stored files as done.
    assert all(s["status"] == "completed" for s in job.progress["stages"])

    detail = (await client.get(f"/api/v1/games/{game_id}")).json()
    assert all(a["status"] == "stored" for a in detail["artifacts"])
    on_disk = sorted(p.name for p in (settings.library_dir / "main" / "test-game").iterdir())
    assert on_disk == ["9.bin", "en1.bin", "en2.bin"]
    # Stored files are never re-downloaded: en1 + en2(failed) + 9, then en2 alone.
    assert len(attempts) == 4


async def test_import_ignores_disk_leftovers(
    client: AsyncClient, session_factory: SessionFactory, settings, gog_stubbed
):
    library_id = await _create_library(client)
    leftover_dir = settings.library_dir / "main" / "test-game"
    leftover_dir.mkdir(parents=True)
    (leftover_dir / "en1.bin").write_bytes(b"stale partial bytes")

    resp = await client.post("/api/v1/gog/import", json={"gog_id": 42, "library_id": library_id})
    assert await run_next_job(session_factory, settings) is True
    job = await _job(session_factory, resp.json()["job_id"])
    assert job.status == JobStatus.COMPLETED
    assert (leftover_dir / "en1.bin").read_bytes() == CONTENT


async def test_counted_reports_cumulative_bytes():
    async def chunks():
        yield b"ab"
        yield b"cde"

    seen: list[int] = []

    async def on_bytes(done: int) -> None:
        seen.append(done)

    out = [chunk async for chunk in _counted(chunks(), on_bytes)]
    assert out == [b"ab", b"cde"]
    assert seen == [2, 5]
