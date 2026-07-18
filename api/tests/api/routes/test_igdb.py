import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.secret import Secret


async def test_status_disconnected(client: AsyncClient):
    resp = await client.get("/api/v1/igdb/status")
    assert resp.json() == {"connected": False}


async def test_connect_stores_credentials(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    async def fake_token(client_id: str, client_secret: str) -> str:
        assert (client_id, client_secret) == ("cid", "csecret")
        return "tok"

    monkeypatch.setattr("silo.api.routes.igdb.app_token", fake_token)

    resp = await client.put(
        "/api/v1/igdb/credentials", json={"client_id": "cid", "client_secret": "csecret"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"connected": True}

    assert (await client.get("/api/v1/igdb/status")).json() == {"connected": True}
    secret = await db_session.get(Secret, "igdb_client_secret")
    assert secret is not None and secret.value == "csecret"


async def test_connect_rejected_credentials(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    async def fake_token(client_id: str, client_secret: str) -> str:
        raise httpx.HTTPStatusError(
            "bad", request=httpx.Request("POST", "x://x"), response=httpx.Response(403)
        )

    monkeypatch.setattr("silo.api.routes.igdb.app_token", fake_token)

    resp = await client.put(
        "/api/v1/igdb/credentials", json={"client_id": "bad", "client_secret": "bad"}
    )
    assert resp.status_code == 422


async def test_disconnect(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    async def fake_token(client_id: str, client_secret: str) -> str:
        return "tok"

    monkeypatch.setattr("silo.api.routes.igdb.app_token", fake_token)
    await client.put(
        "/api/v1/igdb/credentials", json={"client_id": "cid", "client_secret": "csecret"}
    )

    resp = await client.delete("/api/v1/igdb/credentials")
    assert resp.status_code == 204
    assert (await client.get("/api/v1/igdb/status")).json() == {"connected": False}
