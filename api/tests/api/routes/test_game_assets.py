from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.asset import AssetBlob, AssetKind, SourceAsset
from silo.models.game import GameAsset
from tests.api.routes.test_games import _game, _library, _record, _seed, _source
from tests.services.test_assets import png_bytes


async def test_asset_candidates(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    alpha = _source("alpha", priority=1)
    beta = _source("beta", priority=2)
    a_identity, a_record = _record(g.id, alpha)
    b_identity, b_record = _record(g.id, beta)
    cover_a, cover_b, shot = "a" * 64, "b" * 64, "c" * 64
    await _seed(
        db_session,
        lib,
        alpha,
        beta,
        (g, m),
        a_identity,
        a_record,
        b_identity,
        b_record,
        AssetBlob(blake3=cover_a, mime="image/png", size=10),
        AssetBlob(blake3=cover_b, mime="image/jpeg", size=20),
        AssetBlob(blake3=shot, mime="image/jpeg", size=30),
        SourceAsset(metadata_record_id=a_record.id, kind=AssetKind.COVER, blob_blake3=cover_a),
        # beta carries the same cover blob (family overlap) plus its own.
        SourceAsset(metadata_record_id=b_record.id, kind=AssetKind.COVER, blob_blake3=cover_a),
        SourceAsset(metadata_record_id=b_record.id, kind=AssetKind.COVER, blob_blake3=cover_b),
        SourceAsset(metadata_record_id=a_record.id, kind=AssetKind.SCREENSHOT, blob_blake3=shot),
        # The materialized pick.
        GameAsset(game_id=g.id, kind=AssetKind.COVER, blob_blake3=cover_a),
    )

    resp = await client.get(f"/api/v1/games/{g.id}/assets")
    assert resp.status_code == 200
    body = resp.json()
    covers = body["cover"]
    assert [c["blake3"] for c in covers] == [cover_a, cover_b]
    assert covers[0]["source_slugs"] == ["alpha", "beta"]
    assert covers[0]["visible"] is True
    assert covers[0]["ordinal"] == 0
    assert covers[0]["url"] == f"/api/v1/assets/{cover_a}"
    assert covers[0]["mime"] == "image/png"
    assert covers[0]["size"] == 10
    assert covers[1]["source_slugs"] == ["beta"]
    assert covers[1]["visible"] is None
    assert covers[1]["ordinal"] is None
    assert [s["blake3"] for s in body["screenshot"]] == [shot]
    assert body["background"] == []


async def test_asset_candidates_include_stale_picks(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    user_cover = "d" * 64
    await _seed(
        db_session,
        lib,
        (g, m),
        AssetBlob(blake3=user_cover, mime="image/png", size=5),
        # A pick with no live candidate (e.g. its record was re-fetched away).
        GameAsset(game_id=g.id, kind=AssetKind.COVER, blob_blake3=user_cover),
    )

    resp = await client.get(f"/api/v1/games/{g.id}/assets")
    covers = resp.json()["cover"]
    assert [(c["blake3"], c["source_slugs"], c["visible"]) for c in covers] == [
        (user_cover, [], True)
    ]


async def test_asset_candidates_game_not_found(client: AsyncClient):
    resp = await client.get(f"/api/v1/games/{uuid4()}/assets")
    assert resp.status_code == 404


async def test_set_game_assets_reorders_and_hides(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    src = _source("alpha", priority=1)
    identity, record = _record(g.id, src)
    s1, s2, s3 = "a" * 64, "b" * 64, "c" * 64
    await _seed(
        db_session,
        lib,
        src,
        (g, m),
        identity,
        record,
        *(AssetBlob(blake3=b, mime="image/jpeg", size=1) for b in (s1, s2, s3)),
        *(
            SourceAsset(
                metadata_record_id=record.id, kind=AssetKind.SCREENSHOT, blob_blake3=b, ordinal=i
            )
            for i, b in enumerate((s1, s2, s3))
        ),
        GameAsset(game_id=g.id, kind=AssetKind.SCREENSHOT, blob_blake3=s1, ordinal=0),
        GameAsset(game_id=g.id, kind=AssetKind.SCREENSHOT, blob_blake3=s2, ordinal=1),
    )

    resp = await client.put(f"/api/v1/games/{g.id}/assets/screenshot", json={"blobs": [s3, s1]})
    assert resp.status_code == 204

    # s3 materialized at ordinal 0, s1 follows, s2 hidden (never deleted).
    detail = (await client.get(f"/api/v1/games/{g.id}")).json()
    assert detail["assets"]["screenshots"] == [f"/api/v1/assets/{s3}", f"/api/v1/assets/{s1}"]
    hidden = (await client.get(f"/api/v1/games/{g.id}/assets")).json()["screenshot"]
    assert {(c["blake3"], c["visible"]) for c in hidden} == {(s1, True), (s2, False), (s3, True)}


async def test_set_game_assets_pick_survives_locked_resolve(
    db_session: AsyncSession, client: AsyncClient
):
    lib = _library()
    g, m = _game(lib.id, "doom")
    src = _source("alpha", priority=1)
    identity, record = _record(g.id, src)
    win, pick = "a" * 64, "b" * 64
    await _seed(
        db_session,
        lib,
        src,
        (g, m),
        identity,
        record,
        AssetBlob(blake3=win, mime="image/png", size=1),
        AssetBlob(blake3=pick, mime="image/png", size=1),
        SourceAsset(metadata_record_id=record.id, kind=AssetKind.COVER, blob_blake3=win, ordinal=0),
        SourceAsset(
            metadata_record_id=record.id, kind=AssetKind.COVER, blob_blake3=pick, ordinal=1
        ),
        GameAsset(game_id=g.id, kind=AssetKind.COVER, blob_blake3=win),
    )

    put = await client.put(f"/api/v1/games/{g.id}/assets/cover", json={"blobs": [pick]})
    assert put.status_code == 204
    assert (await client.put(f"/api/v1/games/{g.id}/locks/cover")).status_code == 204

    assert (await client.post(f"/api/v1/games/{g.id}/resolve-metadata")).status_code == 200

    detail = (await client.get(f"/api/v1/games/{g.id}")).json()
    assert detail["cover_url"] == f"/api/v1/assets/{pick}"
    assert "cover" in detail["locks"]


async def test_set_game_assets_rejects_unknown_blob(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    src = _source("alpha", priority=1)
    identity, record = _record(g.id, src)
    shot = "a" * 64
    await _seed(
        db_session,
        lib,
        src,
        (g, m),
        identity,
        record,
        AssetBlob(blake3=shot, mime="image/jpeg", size=1),
        SourceAsset(metadata_record_id=record.id, kind=AssetKind.SCREENSHOT, blob_blake3=shot),
    )

    # Not a blob at all.
    resp = await client.put(f"/api/v1/games/{g.id}/assets/cover", json={"blobs": ["f" * 64]})
    assert resp.status_code == 422
    # A real blob, but a screenshot candidate — kinds don't cross.
    resp = await client.put(f"/api/v1/games/{g.id}/assets/cover", json={"blobs": [shot]})
    assert resp.status_code == 422


async def test_set_game_assets_rejects_duplicates(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    src = _source("alpha", priority=1)
    identity, record = _record(g.id, src)
    cover = "a" * 64
    await _seed(
        db_session,
        lib,
        src,
        (g, m),
        identity,
        record,
        AssetBlob(blake3=cover, mime="image/png", size=1),
        SourceAsset(metadata_record_id=record.id, kind=AssetKind.COVER, blob_blake3=cover),
    )

    resp = await client.put(f"/api/v1/games/{g.id}/assets/cover", json={"blobs": [cover, cover]})
    assert resp.status_code == 422


async def test_set_game_assets_empty_hides_all(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    cover = "a" * 64
    await _seed(
        db_session,
        lib,
        (g, m),
        AssetBlob(blake3=cover, mime="image/png", size=1),
        GameAsset(game_id=g.id, kind=AssetKind.COVER, blob_blake3=cover),
    )

    resp = await client.put(f"/api/v1/games/{g.id}/assets/cover", json={"blobs": []})
    assert resp.status_code == 204

    assert (await client.get(f"/api/v1/games/{g.id}")).json()["cover_url"] is None


async def test_set_game_assets_rejects_unknown_kind(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    await _seed(db_session, lib, (g, m))

    resp = await client.put(f"/api/v1/games/{g.id}/assets/poster", json={"blobs": []})
    assert resp.status_code == 422


async def test_set_game_assets_game_not_found(client: AsyncClient):
    resp = await client.put(f"/api/v1/games/{uuid4()}/assets/cover", json={"blobs": []})
    assert resp.status_code == 404


async def test_upload_game_asset(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    await _seed(db_session, lib, (g, m))
    png = png_bytes(10, 20)

    resp = await client.post(
        f"/api/v1/games/{g.id}/assets/cover", files={"file": ("cover.png", png, "image/png")}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["source_slugs"] == []
    assert body["visible"] is False
    assert body["ordinal"] == 0
    assert (body["width"], body["height"]) == (10, 20)

    # Same bytes again → same blob, same row (idempotent).
    again = await client.post(
        f"/api/v1/games/{g.id}/assets/cover", files={"file": ("cover.png", png, "image/png")}
    )
    assert again.status_code == 201
    assert again.json()["blake3"] == body["blake3"]
    assert again.json()["ordinal"] == 0

    # A different image appends after the existing pick.
    second = await client.post(
        f"/api/v1/games/{g.id}/assets/cover",
        files={"file": ("alt.png", png_bytes(5, 5), "image/png")},
    )
    assert second.json()["ordinal"] == 1

    candidates = (await client.get(f"/api/v1/games/{g.id}/assets")).json()["cover"]
    assert [c["blake3"] for c in candidates] == [body["blake3"], second.json()["blake3"]]
    # Staged: uploads never become the cover until curated in.
    detail = (await client.get(f"/api/v1/games/{g.id}")).json()
    assert detail["cover_url"] is None


async def test_upload_game_asset_publishes_via_put(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    await _seed(db_session, lib, (g, m))

    body = (
        await client.post(
            f"/api/v1/games/{g.id}/assets/cover",
            files={"file": ("cover.png", png_bytes(10, 20), "image/png")},
        )
    ).json()
    assert body["visible"] is False

    resp = await client.put(f"/api/v1/games/{g.id}/assets/cover", json={"blobs": [body["blake3"]]})
    assert resp.status_code == 204

    [candidate] = (await client.get(f"/api/v1/games/{g.id}/assets")).json()["cover"]
    assert candidate["visible"] is True
    detail = (await client.get(f"/api/v1/games/{g.id}")).json()
    assert detail["cover_url"] == body["url"]


async def test_upload_game_asset_validation(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    await _seed(db_session, lib, (g, m))

    resp = await client.post(
        f"/api/v1/games/{g.id}/assets/cover", files={"file": ("x.txt", b"hello", "text/plain")}
    )
    assert resp.status_code == 422
    resp = await client.post(
        f"/api/v1/games/{g.id}/assets/cover", files={"file": ("x.png", b"junk", "image/png")}
    )
    assert resp.status_code == 422
    resp = await client.post(
        f"/api/v1/games/{uuid4()}/assets/cover",
        files={"file": ("x.png", png_bytes(), "image/png")},
    )
    assert resp.status_code == 404
