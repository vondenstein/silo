from datetime import datetime
from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.artifact import Artifact, ArtifactKind, ArtifactStatus
from silo.models.game import Game, GameExternalIdentity, GameMetadata
from silo.models.library import Library
from silo.models.metadata_source import MetadataSource
from silo.models.secret import Secret
from silo.sources.gog import GogClient, GogTokens, OwnedGame
from tests.seed import seed_in_order


async def test_auth_url(client: AsyncClient):
    resp = await client.get("/api/v1/gog/auth-url")
    assert resp.status_code == 200
    assert resp.json()["url"].startswith("https://auth.gog.com/auth?client_id=")


async def test_status_disconnected(client: AsyncClient):
    resp = await client.get("/api/v1/gog/status")
    assert resp.json() == {"connected": False}


async def test_connect_stores_tokens(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    async def fake_exchange(code: str) -> GogTokens:
        assert code == "authcode"
        return GogTokens(access_token="a1", refresh_token="r1")

    monkeypatch.setattr("silo.api.routes.gog.exchange_code", fake_exchange)

    resp = await client.post("/api/v1/gog/auth", json={"code": "authcode"})
    assert resp.status_code == 200
    assert resp.json() == {"connected": True}

    assert (await client.get("/api/v1/gog/status")).json() == {"connected": True}
    secret = await db_session.get(Secret, "gog_refresh_token")
    assert secret is not None and secret.value == "r1"


async def test_connect_rejected_code(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    async def fake_exchange(code: str) -> GogTokens:
        raise httpx.HTTPStatusError(
            "bad", request=httpx.Request("GET", "x://x"), response=httpx.Response(400)
        )

    monkeypatch.setattr("silo.api.routes.gog.exchange_code", fake_exchange)

    resp = await client.post("/api/v1/gog/auth", json={"code": "bad"})
    assert resp.status_code == 422


async def test_disconnect(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    async def fake_exchange(code: str) -> GogTokens:
        return GogTokens(access_token="a1", refresh_token="r1")

    monkeypatch.setattr("silo.api.routes.gog.exchange_code", fake_exchange)
    await client.post("/api/v1/gog/auth", json={"code": "c"})

    resp = await client.delete("/api/v1/gog/auth")
    assert resp.status_code == 204
    assert (await client.get("/api/v1/gog/status")).json() == {"connected": False}


async def test_library_requires_connection(client: AsyncClient):
    resp = await client.get("/api/v1/gog/library")
    assert resp.status_code == 409


async def test_library_502_on_token_refresh_failure(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def fake_exchange(code: str) -> GogTokens:
        return GogTokens(access_token="a1", refresh_token="r1")

    async def failing_fresh(session) -> str:
        raise httpx.ConnectError("boom")

    monkeypatch.setattr("silo.api.routes.gog.exchange_code", fake_exchange)
    monkeypatch.setattr("silo.api.routes.gog.fresh_access_token", failing_fresh)
    await client.post("/api/v1/gog/auth", json={"code": "c"})

    resp = await client.get("/api/v1/gog/library")
    assert resp.status_code == 502
    assert "token refresh" in resp.json()["detail"]


async def test_library_502_on_owned_games_failure(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    async def fake_exchange(code: str) -> GogTokens:
        return GogTokens(access_token="a1", refresh_token="r1")

    async def fake_fresh(session) -> str:
        return "a1"

    async def failing_owned(self: GogClient) -> list[OwnedGame]:
        raise httpx.ReadTimeout("slow upstream")

    monkeypatch.setattr("silo.api.routes.gog.exchange_code", fake_exchange)
    monkeypatch.setattr("silo.api.routes.gog.fresh_access_token", fake_fresh)
    monkeypatch.setattr(GogClient, "owned_games", failing_owned)
    await client.post("/api/v1/gog/auth", json={"code": "c"})

    resp = await client.get("/api/v1/gog/library")
    assert resp.status_code == 502
    assert "library fetch" in resp.json()["detail"]


async def test_library_lists_owned_games(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    async def fake_exchange(code: str) -> GogTokens:
        return GogTokens(access_token="a1", refresh_token="r1")

    async def fake_fresh(session) -> str:
        return "a1"

    async def fake_owned(self: GogClient) -> list[OwnedGame]:
        return [OwnedGame(id=1, title="Doom", slug="doom", image_url="//img/doom")]

    monkeypatch.setattr("silo.api.routes.gog.exchange_code", fake_exchange)
    monkeypatch.setattr("silo.api.routes.gog.fresh_access_token", fake_fresh)
    monkeypatch.setattr(GogClient, "owned_games", fake_owned)
    await client.post("/api/v1/gog/auth", json={"code": "c"})

    resp = await client.get("/api/v1/gog/library")
    assert resp.status_code == 200
    assert resp.json() == [
        {
            "gog_id": 1,
            "title": "Doom",
            "slug": "doom",
            "image_url": "//img/doom",
            "imported": False,
            "complete": False,
        }
    ]


def _imported_game(lib_id, slug: str, gog_source_id, gog_id: int, statuses) -> list:
    game_id = uuid4()
    now = datetime(2025, 1, 1)
    return [
        Game(id=game_id, library_id=lib_id, slug=slug, created_at=now, updated_at=now),
        GameMetadata(game_id=game_id, title=slug),
        GameExternalIdentity(game_id=game_id, source_id=gog_source_id, external_id=str(gog_id)),
        *(
            Artifact(game_id=game_id, kind=ArtifactKind.INSTALLER, status=status)
            for status in statuses
        ),
    ]


async def test_library_flags_imported_and_complete(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    async def fake_exchange(code: str) -> GogTokens:
        return GogTokens(access_token="a1", refresh_token="r1")

    async def fake_fresh(session) -> str:
        return "a1"

    async def fake_owned(self: GogClient) -> list[OwnedGame]:
        return [
            OwnedGame(id=1, title="Stored", slug="stored"),
            OwnedGame(id=2, title="Partial", slug="partial"),
            OwnedGame(id=3, title="No files", slug="no-files"),
            OwnedGame(id=4, title="New", slug="new"),
        ]

    monkeypatch.setattr("silo.api.routes.gog.exchange_code", fake_exchange)
    monkeypatch.setattr("silo.api.routes.gog.fresh_access_token", fake_fresh)
    monkeypatch.setattr(GogClient, "owned_games", fake_owned)
    await client.post("/api/v1/gog/auth", json={"code": "c"})

    gog_source_id = await db_session.scalar(
        select(MetadataSource.id).where(MetadataSource.slug == "gog")
    )
    lib = Library(
        id=uuid4(),
        slug="main",
        name="Main",
        created_at=datetime(2025, 1, 1),
        updated_at=datetime(2025, 1, 1),
    )
    await seed_in_order(
        db_session,
        lib,
        *_imported_game(lib.id, "stored", gog_source_id, 1, [ArtifactStatus.STORED]),
        *_imported_game(
            lib.id, "partial", gog_source_id, 2, [ArtifactStatus.STORED, ArtifactStatus.PARTIAL]
        ),
        *_imported_game(lib.id, "no-files", gog_source_id, 3, []),
    )

    resp = await client.get("/api/v1/gog/library")
    assert resp.status_code == 200
    flags = {game["gog_id"]: (game["imported"], game["complete"]) for game in resp.json()}
    assert flags == {
        1: (True, True),
        2: (True, False),
        3: (True, False),
        4: (False, False),
    }
