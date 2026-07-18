from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.secret import Secret


# Promote to tests/factories.py when a second resource's tests need seeded secrets.
def _secret(name: str, value: str = "x") -> Secret:
    return Secret(name=name, value=value)


async def _seed(session: AsyncSession, *secrets: Secret) -> None:
    session.add_all(secrets)
    await session.commit()


async def test_list_secrets_empty(client: AsyncClient):
    resp = await client.get("/api/v1/secrets")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_secrets_sorted(db_session: AsyncSession, client: AsyncClient):
    await _seed(db_session, _secret("zeta"), _secret("alpha"), _secret("middle"))

    resp = await client.get("/api/v1/secrets")
    assert resp.json() == ["alpha", "middle", "zeta"]


async def test_set_secret_creates_then_overwrites(db_session: AsyncSession, client: AsyncClient):
    resp = await client.put("/api/v1/secrets/token", json={"value": "first"})
    assert resp.status_code == 204
    result = await db_session.execute(select(Secret.value).where(Secret.name == "token"))
    assert result.scalar_one() == "first"

    resp = await client.put("/api/v1/secrets/token", json={"value": "second"})
    assert resp.status_code == 204
    result = await db_session.execute(select(Secret.value).where(Secret.name == "token"))
    assert result.scalar_one() == "second"


async def test_set_secret_rejects_empty_value(client: AsyncClient):
    resp = await client.put("/api/v1/secrets/token", json={"value": ""})
    assert resp.status_code == 422


async def test_set_secret_rejects_extra_field(client: AsyncClient):
    resp = await client.put("/api/v1/secrets/token", json={"value": "x", "extra": "y"})
    assert resp.status_code == 422


async def test_delete_secret(db_session: AsyncSession, client: AsyncClient):
    await _seed(db_session, _secret("token"))

    resp = await client.delete("/api/v1/secrets/token")
    assert resp.status_code == 204

    list_resp = await client.get("/api/v1/secrets")
    assert list_resp.json() == []


async def test_delete_secret_is_idempotent(client: AsyncClient):
    resp = await client.delete("/api/v1/secrets/nonexistent")
    assert resp.status_code == 204
