from datetime import datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.library import Library


# Promote to tests/factories.py when a second resource's tests need seeded libraries.
def _library(slug: str, name: str, created_at: datetime) -> Library:
    return Library(
        id=uuid4(),
        slug=slug,
        name=name,
        created_at=created_at,
        updated_at=created_at,
    )


async def _seed(session: AsyncSession, *libraries: Library) -> None:
    session.add_all(libraries)
    await session.commit()


async def test_list_libraries_empty(client: AsyncClient):
    resp = await client.get("/api/v1/libraries")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "next_cursor": None}


async def test_list_libraries_orders_created_at_desc(db_session: AsyncSession, client: AsyncClient):
    t = datetime(2025, 1, 1)
    await _seed(
        db_session,
        _library("alpha", "Alpha", t.replace(day=1)),
        _library("beta", "Beta", t.replace(day=2)),
        _library("gamma", "Gamma", t.replace(day=3)),
    )

    resp = await client.get("/api/v1/libraries")
    body = resp.json()
    assert resp.status_code == 200
    assert [item["slug"] for item in body["items"]] == ["gamma", "beta", "alpha"]
    assert body["next_cursor"] is None


async def test_list_libraries_pagination(db_session: AsyncSession, client: AsyncClient):
    t = datetime(2025, 1, 1)
    await _seed(
        db_session,
        *[_library(f"lib{i}", f"Lib {i}", t.replace(day=i + 1)) for i in range(5)],
    )

    # first page
    resp = await client.get("/api/v1/libraries?limit=2")
    body = resp.json()
    assert [item["slug"] for item in body["items"]] == ["lib4", "lib3"]
    assert body["next_cursor"] is not None

    # next page via cursor
    resp = await client.get(f"/api/v1/libraries?limit=2&cursor={body['next_cursor']}")
    body = resp.json()
    assert [item["slug"] for item in body["items"]] == ["lib2", "lib1"]
    assert body["next_cursor"] is not None

    # last page; next_cursor is null
    resp = await client.get(f"/api/v1/libraries?limit=2&cursor={body['next_cursor']}")
    body = resp.json()
    assert [item["slug"] for item in body["items"]] == ["lib0"]
    assert body["next_cursor"] is None


@pytest.mark.parametrize(
    "cursor",
    [
        "not-a-real-cursor",
        "Mw==",  # base64 of 3 — valid base64, non-object JSON
        "bnVsbA==",  # base64 of null
        "eyJpZCI6IDN9",  # base64 of {"id": 3} — non-string id
    ],
)
async def test_list_libraries_rejects_invalid_cursor(client: AsyncClient, cursor: str):
    resp = await client.get(f"/api/v1/libraries?cursor={cursor}")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid cursor"


async def test_create_library(client: AsyncClient):
    resp = await client.post("/api/v1/libraries", json={"slug": "main", "name": "Main"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["slug"] == "main"
    assert body["name"] == "Main"
    assert set(body.keys()) == {"id", "slug", "name", "created_at", "updated_at"}


async def test_create_library_slug_conflict(client: AsyncClient):
    payload = {"slug": "main", "name": "Main"}
    assert (await client.post("/api/v1/libraries", json=payload)).status_code == 201

    resp = await client.post("/api/v1/libraries", json={**payload, "name": "Other"})
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


async def test_create_library_rejects_invalid_slug(client: AsyncClient):
    resp = await client.post("/api/v1/libraries", json={"slug": "Invalid Slug!", "name": "Main"})
    assert resp.status_code == 422


# The unified slug rule's boundaries (shared Slug type — pins the pattern
# for every slugged resource, not just libraries).
@pytest.mark.parametrize("slug", ["UPPER", "-a", "a-", "a--b", "a" * 65])
async def test_create_library_rejects_boundary_slugs(client: AsyncClient, slug: str):
    resp = await client.post("/api/v1/libraries", json={"slug": slug, "name": "Main"})
    assert resp.status_code == 422


@pytest.mark.parametrize("slug", ["a", "a-1"])
async def test_create_library_accepts_minimal_slugs(client: AsyncClient, slug: str):
    resp = await client.post("/api/v1/libraries", json={"slug": slug, "name": "Main"})
    assert resp.status_code == 201


async def test_create_library_requires_name(client: AsyncClient):
    resp = await client.post("/api/v1/libraries", json={"slug": "main"})
    assert resp.status_code == 422


async def test_created_library_appears_in_list(client: AsyncClient):
    await client.post("/api/v1/libraries", json={"slug": "main", "name": "Main"})

    resp = await client.get("/api/v1/libraries")
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["slug"] == "main"


async def test_get_library(db_session: AsyncSession, client: AsyncClient):
    library = _library("main", "Main", datetime(2025, 1, 1))
    await _seed(db_session, library)

    resp = await client.get(f"/api/v1/libraries/{library.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(library.id)
    assert body["slug"] == "main"
    assert body["name"] == "Main"


async def test_get_library_not_found(client: AsyncClient):
    resp = await client.get(f"/api/v1/libraries/{uuid4()}")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


async def test_get_library_rejects_invalid_uuid(client: AsyncClient):
    resp = await client.get("/api/v1/libraries/not-a-uuid")
    assert resp.status_code == 422


async def test_update_library(db_session: AsyncSession, client: AsyncClient):
    library = _library("main", "Main", datetime(2025, 1, 1))
    await _seed(db_session, library)

    resp = await client.patch(f"/api/v1/libraries/{library.id}", json={"name": "Renamed"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["slug"] == "main"  # immutable
    assert body["id"] == str(library.id)


async def test_update_library_not_found(client: AsyncClient):
    resp = await client.patch(f"/api/v1/libraries/{uuid4()}", json={"name": "X"})
    assert resp.status_code == 404


async def test_update_library_rejects_slug_edit(db_session: AsyncSession, client: AsyncClient):
    library = _library("main", "Main", datetime(2025, 1, 1))
    await _seed(db_session, library)

    resp = await client.patch(
        f"/api/v1/libraries/{library.id}",
        json={"name": "Renamed", "slug": "new-slug"},
    )
    assert resp.status_code == 422


async def test_update_library_requires_name(db_session: AsyncSession, client: AsyncClient):
    library = _library("main", "Main", datetime(2025, 1, 1))
    await _seed(db_session, library)

    resp = await client.patch(f"/api/v1/libraries/{library.id}", json={})
    assert resp.status_code == 422


async def test_delete_library(db_session: AsyncSession, client: AsyncClient):
    library = _library("main", "Main", datetime(2025, 1, 1))
    await _seed(db_session, library)

    resp = await client.delete(f"/api/v1/libraries/{library.id}")
    assert resp.status_code == 204

    follow = await client.get(f"/api/v1/libraries/{library.id}")
    assert follow.status_code == 404


async def test_delete_library_with_games_conflicts(db_session: AsyncSession, client: AsyncClient):
    library = _library("main", "Main", datetime(2025, 1, 1))
    await _seed(db_session, library)
    created = await client.post(
        "/api/v1/games", json={"library_id": str(library.id), "slug": "doom", "title": "Doom"}
    )
    assert created.status_code == 201

    resp = await client.delete(f"/api/v1/libraries/{library.id}")
    assert resp.status_code == 409

    await client.delete(f"/api/v1/games/{created.json()['id']}")
    assert (await client.delete(f"/api/v1/libraries/{library.id}")).status_code == 204


async def test_delete_library_not_found(client: AsyncClient):
    resp = await client.delete(f"/api/v1/libraries/{uuid4()}")
    assert resp.status_code == 404
