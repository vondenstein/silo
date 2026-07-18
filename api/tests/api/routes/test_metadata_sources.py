from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.metadata_source import MetadataSource
from silo.schemas.metadata_source import SearchCandidateOut
from silo.seed import _METADATA_SOURCES


# Promote to tests/factories.py when a second resource's tests need seeded sources.
def _source(slug: str, name: str, priority: int) -> MetadataSource:
    return MetadataSource(
        id=uuid4(),
        slug=slug,
        name=name,
        enabled=True,
        required=False,
        priority=priority,
        request_interval_ms=None,
    )


async def _seed(session: AsyncSession, *sources: MetadataSource) -> None:
    session.add_all(sources)
    await session.commit()


async def test_list_metadata_sources_seeded(client: AsyncClient):
    resp = await client.get("/api/v1/metadata-sources")
    assert resp.status_code == 200
    assert {item["slug"] for item in resp.json()} == {row["slug"] for row in _METADATA_SOURCES}


async def test_list_metadata_sources_orders_by_priority(
    db_session: AsyncSession, client: AsyncClient
):
    await _seed(
        db_session,
        _source("alpha", "Alpha", priority=1),
        _source("beta", "Beta", priority=25),
        _source("gamma", "Gamma", priority=99),
    )

    resp = await client.get("/api/v1/metadata-sources")
    assert resp.status_code == 200
    body = resp.json()
    # The lifespan-seeded rows sort among the hand-seeded ones.
    assert [item["slug"] for item in body] == [
        "alpha",
        "gog",
        "gog_gamesdb",
        "gog_store",
        "igdb",
        "beta",
        "steam",
        "gamma",
    ]


async def test_update_metadata_source(db_session: AsyncSession, client: AsyncClient):
    source = _source("acme", "Acme", priority=5)
    await _seed(db_session, source)

    resp = await client.patch(
        f"/api/v1/metadata-sources/{source.id}",
        json={"enabled": False, "priority": 10},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["priority"] == 10
    assert body["slug"] == "acme"  # immutable


async def test_update_metadata_source_interval(db_session: AsyncSession, client: AsyncClient):
    source = _source("acme", "Acme", priority=5)
    await _seed(db_session, source)

    resp = await client.patch(
        f"/api/v1/metadata-sources/{source.id}", json={"request_interval_ms": 500}
    )
    assert resp.status_code == 200
    assert resp.json()["request_interval_ms"] == 500

    # Explicit null clears back to the adapter's default pacing.
    resp = await client.patch(
        f"/api/v1/metadata-sources/{source.id}", json={"request_interval_ms": None}
    )
    assert resp.status_code == 200
    assert resp.json()["request_interval_ms"] is None


async def test_update_metadata_source_not_found(client: AsyncClient):
    resp = await client.patch(
        f"/api/v1/metadata-sources/{uuid4()}",
        json={"enabled": False},
    )
    assert resp.status_code == 404


async def test_update_metadata_source_rejects_null(db_session: AsyncSession, client: AsyncClient):
    source = _source("acme", "Acme", priority=5)
    await _seed(db_session, source)

    resp = await client.patch(
        f"/api/v1/metadata-sources/{source.id}",
        json={"enabled": None},
    )
    assert resp.status_code == 422


async def test_update_metadata_source_rejects_extra_field(
    db_session: AsyncSession, client: AsyncClient
):
    source = _source("acme", "Acme", priority=5)
    await _seed(db_session, source)

    resp = await client.patch(
        f"/api/v1/metadata-sources/{source.id}",
        json={"name": "Renamed"},
    )
    assert resp.status_code == 422


async def test_update_metadata_source_rejects_negative_priority(
    db_session: AsyncSession, client: AsyncClient
):
    source = _source("acme", "Acme", priority=5)
    await _seed(db_session, source)

    resp = await client.patch(
        f"/api/v1/metadata-sources/{source.id}",
        json={"priority": -1},
    )
    assert resp.status_code == 422


def _stub_search(monkeypatch, result):
    async def fake(session, slug: str, term: str):
        assert slug == "igdb"
        assert term == "doom"
        if result is None:
            return None
        return [SearchCandidateOut.model_validate(candidate) for candidate in result]

    monkeypatch.setattr("silo.api.routes.metadata_sources.search_source", fake)


async def test_search_returns_candidates(client: AsyncClient, monkeypatch):
    _stub_search(
        monkeypatch,
        [
            {"external_id": "77", "name": "Doom", "year": 1993},
            {"external_id": "88", "name": "Doom II", "year": None},
        ],
    )

    resp = await client.get("/api/v1/metadata-sources/igdb/search?q=doom")

    assert resp.status_code == 200
    assert resp.json() == [
        {"external_id": "77", "name": "Doom", "year": 1993},
        {"external_id": "88", "name": "Doom II", "year": None},
    ]


async def test_search_unconfigured_source(client: AsyncClient, monkeypatch):
    _stub_search(monkeypatch, None)

    resp = await client.get("/api/v1/metadata-sources/igdb/search?q=doom")

    assert resp.status_code == 409


async def test_search_upstream_failure(client: AsyncClient, monkeypatch):
    async def broken(session, slug, term):
        raise RuntimeError("boom")

    monkeypatch.setattr("silo.api.routes.metadata_sources.search_source", broken)

    resp = await client.get("/api/v1/metadata-sources/igdb/search?q=doom")

    assert resp.status_code == 502


async def test_search_capability_and_existence(client: AsyncClient):
    # steam is seeded but has no catalog search.
    assert (await client.get("/api/v1/metadata-sources/steam/search?q=doom")).status_code == 422
    assert (await client.get("/api/v1/metadata-sources/nope/search?q=doom")).status_code == 404
    # An empty query is rejected by validation.
    assert (await client.get("/api/v1/metadata-sources/igdb/search?q=")).status_code == 422


async def test_sources_expose_searchable(client: AsyncClient):
    rows = (await client.get("/api/v1/metadata-sources")).json()
    by_slug = {row["slug"]: row["searchable"] for row in rows}
    assert by_slug["igdb"] is True
    assert by_slug["steam"] is False
