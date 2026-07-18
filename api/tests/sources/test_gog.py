import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from silo.models.metadata_source import MetadataSource
from silo.models.secret import Secret
from silo.schemas.normalized_metadata import NormalizedMetadata
from silo.sources.gog import (
    API_URL,
    DEFAULT_REQUEST_INTERVAL_MS,
    EMBED_URL,
    GogClient,
    GogNotConnectedError,
    GogTokens,
    clear_tokens,
    fresh_access_token,
    is_connected,
    normalize_galaxy,
    normalize_gamesdb,
    normalize_store,
    request_interval,
    store_tokens,
    uids,
)

SessionFactory = async_sessionmaker[AsyncSession]


def _fixture(name: str) -> dict:
    return json.loads((Path(__file__).parent.parent / "fixtures" / name).read_text())


GALAXY_FIXTURE = _fixture("gog_galaxy_product.json")
STORE_FIXTURE = _fixture("gog_store_game.json")
GAMESDB_FIXTURE = _fixture("gog_gamesdb_release.json")


STATICS = "https://images.gog-statics.com"


def test_normalize_maps_galaxy_fields():
    normalized = normalize_galaxy(GALAXY_FIXTURE)

    assert normalized["title"] == "Baldur's Gate: Enhanced Edition"
    assert normalized["game_type"] == "main"
    assert "<script" not in normalized["description_full"]
    assert normalized["videos"][0]["provider"] == "wistia"
    # D3-refinement: Galaxy languages superseded by Store-v2 localizations.
    assert "languages" not in normalized
    # D2: Galaxy release_date is store-specific — never mapped.
    assert "first_release_date" not in normalized
    assert "release_date" not in normalized
    # The raw images/screenshots stashes died with asset extraction (5c).
    assert "images" not in normalized
    assert "screenshots" not in normalized


def _assets_by_kind(normalized: dict) -> dict[str, list[str]]:
    by_kind: dict[str, list[str]] = {}
    for asset in normalized["assets"]:
        by_kind.setdefault(asset["kind"], []).append(asset["url"])
    return by_kind


def test_normalize_galaxy_extracts_assets():
    by_kind = _assets_by_kind(normalize_galaxy(GALAXY_FIXTURE))

    assert by_kind["background"] == [
        f"{STATICS}/1ca0d935dc9e2902b9a998957e0157928564989ac1b675ad29f626fa3170ea6e.jpg"
    ]
    # Galaxy's "logo" is 1600×740 grid-tile artwork → landscape; suffix strips to the master.
    assert by_kind["landscape"] == [
        f"{STATICS}/90ba7463dae94110fd495957a6311648a6e1999bab1a0fcc2d5176b3f46141e8.jpg"
    ]
    assert "logo" not in by_kind
    assert by_kind["icon"] == [
        f"{STATICS}/d66732900379ee90b812111ac0934c571ef5edbf038cb3e9fcd3b4bed12cd35c.png"
    ]
    assert len(by_kind["screenshot"]) == 12
    assert by_kind["screenshot"][0] == (
        f"{STATICS}/77a3d5151b16385f85204560ef27af4843fca43a6c7643b58f5e4e352dc06527.jpg"
    )
    assert len(by_kind["video_thumbnail"]) == len(GALAXY_FIXTURE["videos"])


def test_normalize_galaxy_extracts_collections():
    normalized = normalize_galaxy(GALAXY_FIXTURE)

    assert normalized["platforms"] == ["windows", "macos", "linux"]
    assert [v["provider"] for v in normalized["videos"]] == ["wistia", "youtube"]
    assert normalized["videos"][0]["url"].startswith("https://fast.wistia.net/")
    # Thumbnails ride assets, not the videos list.
    assert "thumbnail_url" not in normalized["videos"][0]
    NormalizedMetadata.model_validate(normalized)


def test_normalize_store_extracts_assets():
    assets = normalize_store(STORE_FIXTURE)["assets"]

    assert [asset["kind"] for asset in assets] == [
        "cover",
        "background",
        "background",
        "logo",
        "icon",
    ]
    assert assets[0]["url"] == (
        f"{STATICS}/855573122ad636464037105f92145e943e43704875076c7f3648116fda5f18f3.jpg"
    )
    assert all(asset["url"].startswith(f"{STATICS}/") for asset in assets)


def test_normalize_store_extracts_collections():
    normalized = normalize_store(STORE_FIXTURE)

    assert normalized["developers"] == [{"name": "Beamdog"}]
    # The fixture's plural publishers[] is null — the singular publisher{} fills in.
    assert normalized["publishers"] == [{"name": "Beamdog"}]
    assert normalized["series"] == [{"name": "Baldur's Gate Enhanced", "uid": "933"}]
    # D10: tags → genre, properties → tag.
    assert normalized["genres"] == [
        {"name": "Role-playing", "uid": "57"},
        {"name": "Real-time", "uid": "62"},
        {"name": "Fantasy", "uid": "71"},
    ]
    assert {t["name"] for t in normalized["tags"]} >= {"Story Rich", "CRPG", "Isometric"}
    assert normalized["platforms"] == ["windows", "linux", "macos"]
    assert {(r["authority"], r["value"]) for r in normalized["ratings"]} == {
        ("pegi", "12"),
        ("usk", "12"),
    }
    assert normalized["videos"][0] == {
        "provider": "youtube",
        "video_id": "dG-4Gp3XNiw",
        "url": "https://www.youtube.com/embed/dG-4Gp3XNiw?wmode=opaque&rel=0",
    }
    NormalizedMetadata.model_validate(normalized)


def test_normalize_gamesdb_extracts_assets():
    by_kind = _assets_by_kind(normalize_gamesdb(GAMESDB_FIXTURE))

    # cover and vertical_cover share a hash — the (kind, url) dedup collapses them.
    assert by_kind["cover"] == [
        "https://images.gog.com/"
        "58f8d797948813511a6b58fe6cdb7f96d7074a764c3596d4284e52ecdb2442e7.png?namespace=gamesdb"
    ]
    assert len(by_kind["screenshot"]) == 17
    assert all(url.endswith(".jpg?namespace=gamesdb") for url in by_kind["screenshot"])
    # artworks[] only — horizontal_artwork/logo/square_icon dropped at the field→kind audit.
    assert len(by_kind["landscape"]) == 1
    assert len(by_kind["background"]) == 1
    assert "logo" not in by_kind
    assert "icon" not in by_kind


def test_normalize_gamesdb_extracts_collections():
    normalized = normalize_gamesdb(GAMESDB_FIXTURE)

    # GamesDB ids ride as uids — the D14 reconciliation anchors.
    assert normalized["developers"] == [{"name": "Overhaul Games", "uid": "51141465308637629"}]
    assert [p["name"] for p in normalized["publishers"]] == ["Atari, Inc.", "Beamdog"]
    # Localized {*} names unwrap.
    assert normalized["genres"][0] == {"name": "Role-playing (RPG)", "uid": "51071842242881003"}
    assert [t["name"] for t in normalized["themes"]] == ["Fantasy"]
    assert [m["name"] for m in normalized["modes"]] == [
        "Single player",
        "Co-operative",
        "Multiplayer",
    ]
    assert normalized["series"] == [{"name": "Baldur's Gate", "uid": "53028463452469271"}]
    assert normalized["platforms"] == ["linux", "macos", "windows"]
    # CR-199: gamesdb videos extracted (youtube only, synthesized URL).
    assert [v["video_id"] for v in normalized["videos"]] == [
        "kiAsHuRO_Ao",
        "-yiaRoz-fjk",
        "86NLGVQ6Iaw",
    ]
    assert normalized["videos"][0]["url"] == "https://www.youtube.com/watch?v=kiAsHuRO_Ao"
    NormalizedMetadata.model_validate(normalized)


def test_uids_maps_catalogs():
    found = uids(GAMESDB_FIXTURE)

    assert found["steam"] == "228280"
    assert found["gog"] == "1207666353"
    # Unfiltered adapter-side; the service intersects with the registry.
    assert "epic" in found


def test_normalize_sanitizes_description():
    payload = {"description": {"full": '<p onclick="x()">ok</p><script>evil()</script><img src=x>'}}
    normalized = normalize_galaxy(payload)
    assert normalized["description_full"] == "<p>ok</p>"


def test_normalize_store_maps_scalars():
    normalized = normalize_store(STORE_FIXTURE)

    assert normalized["title"] == "Baldur's Gate: Enhanced Edition"
    assert normalized["game_type"] == "main"
    assert normalized["first_release_date"] == "2013-01-16"
    assert normalized["description_full"].startswith("<b>Baldur")
    # BG:EE is not a DOSBox title; the flag maps only when true.
    assert "wrapper" not in normalized


def test_normalize_store_maps_dosbox_wrapper():
    assert normalize_store({"isUsingDosBox": True}) == {"wrapper": "dosbox"}


def test_normalize_gamesdb_maps_scalars():
    normalized = normalize_gamesdb(GAMESDB_FIXTURE)

    assert normalized["title"] == "Baldur's Gate: Enhanced Edition"
    assert normalized["sort_title"] == "Baldurs Gate 1"
    assert normalized["game_type"] == "main"
    # The true first release — earlier than Store-v2's globalReleaseDate.
    assert normalized["first_release_date"] == "2012-11-27"
    assert normalized["description_short"].startswith("Running on an upgraded")


def test_normalize_output_fits_normalized_metadata():
    for normalized in (
        normalize_galaxy(GALAXY_FIXTURE),
        normalize_store(STORE_FIXTURE),
        normalize_gamesdb(GAMESDB_FIXTURE),
    ):
        NormalizedMetadata.model_validate(normalized)


async def test_owned_games_paginates():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/account/getFilteredProducts"
        page = int(request.url.params["page"])
        products = {
            1: [{"id": 1, "title": "A", "slug": "a", "image": "//img/a"}],
            2: [{"id": 2, "title": "B", "slug": "b"}],
        }[page]
        return httpx.Response(200, json={"products": products, "totalPages": 2})

    async with GogClient("token", transport=httpx.MockTransport(handler)) as client:
        games = await client.owned_games()

    assert [(g.id, g.title, g.image_url) for g in games] == [(1, "A", "//img/a"), (2, "B", None)]


async def test_product_fetches_expanded_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/products/123"
        assert "downloads" in request.url.params["expand"]
        assert request.headers["Authorization"] == "Bearer token"
        return httpx.Response(200, json={"id": 123, "title": "T"})

    async with GogClient("token", transport=httpx.MockTransport(handler)) as client:
        payload = await client.product(123)

    assert payload == {"id": 123, "title": "T"}


async def test_product_v2_and_gamesdb_fetch_paths():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer token"
        return httpx.Response(200, json={"path": request.url.path, "host": request.url.host})

    async with GogClient("token", transport=httpx.MockTransport(handler)) as client:
        store = await client.product_v2(123)
        gamesdb = await client.gamesdb_release(123)

    assert store == {"path": "/v2/games/123", "host": "api.gog.com"}
    assert gamesdb == {"path": "/platforms/gog/external_releases/123", "host": "gamesdb.gog.com"}


async def test_download_url_follows_redirect_and_json():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"location": "https://cdn.gog.com/file.exe"})
        return httpx.Response(200, json={"downlink": "https://cdn.gog.com/json.exe"})

    async with GogClient("token", transport=httpx.MockTransport(handler)) as client:
        assert await client.download_url(f"{API_URL}/redirect") == "https://cdn.gog.com/file.exe"
        assert await client.download_url(f"{EMBED_URL}/json") == "https://cdn.gog.com/json.exe"


async def test_token_secrets_roundtrip(session_factory: SessionFactory):
    async with session_factory() as session:
        assert await is_connected(session) is False
        await store_tokens(session, GogTokens(access_token="a1", refresh_token="r1"))
        await session.commit()

    async with session_factory() as session:
        assert await is_connected(session) is True
        secret = await session.get(Secret, "gog_refresh_token")
        assert secret is not None and secret.value == "r1"
        # Upsert overwrites on rotation.
        await store_tokens(session, GogTokens(access_token="a2", refresh_token="r2"))
        await session.commit()

    async with session_factory() as session:
        secret = await session.get(Secret, "gog_access_token")
        assert secret is not None and secret.value == "a2"
        await clear_tokens(session)
        await session.commit()

    async with session_factory() as session:
        assert await is_connected(session) is False


async def test_fresh_access_token_requires_connection(session_factory: SessionFactory):
    async with session_factory() as session:
        with pytest.raises(GogNotConnectedError):
            await fresh_access_token(session)


async def test_request_interval_defaults_when_null(session_factory: SessionFactory):
    async with session_factory() as session:
        session.add(MetadataSource(id=uuid4(), slug="gog", name="GOG", priority=10))
        await session.commit()
        assert await request_interval(session) == DEFAULT_REQUEST_INTERVAL_MS

        gog_row = (
            await session.scalars(select(MetadataSource).where(MetadataSource.slug == "gog"))
        ).one()
        gog_row.request_interval_ms = 100
        await session.commit()
        assert await request_interval(session) == 100


CYBERPUNK_STORE_FIXTURE = _fixture("gog_store_cyberpunk.json")


# 7a's field→kind audit: the emitted kind SET per normalizer is the contract —
# a silently re-added skip (gamesdb logo/icon, store screenshots) must fail here.
def test_normalize_galaxy_asset_kind_set():
    by_kind = _assets_by_kind(normalize_galaxy(GALAXY_FIXTURE))
    assert set(by_kind) == {"background", "icon", "landscape", "screenshot", "video_thumbnail"}


def test_normalize_store_asset_kind_set():
    by_kind = _assets_by_kind(normalize_store(STORE_FIXTURE))
    assert set(by_kind) == {"background", "cover", "icon", "logo"}


def test_normalize_gamesdb_asset_kind_set():
    by_kind = _assets_by_kind(normalize_gamesdb(GAMESDB_FIXTURE))
    assert set(by_kind) == {"background", "cover", "landscape", "screenshot"}


def test_normalize_store_ratings_from_real_payload():
    # Live Cyberpunk 2077 capture: the `descriptor` key is real, and brRating
    # descriptors arrive with trailing \r — stripped at the normalizer.
    normalized = normalize_store(CYBERPUNK_STORE_FIXTURE)

    ratings = {r["authority"]: r for r in normalized["ratings"]}
    assert ratings["pegi"]["value"] == "18"
    assert ratings["pegi"]["descriptors"] == ["Bad Language", "Sex", "Violence"]
    assert ratings["classind"]["descriptors"] == [
        "Conteúdo Sexual",
        "Drogas",
        "Violência Extrema",
    ]
    assert ratings["usk"]["descriptors"] == []
    NormalizedMetadata.model_validate(normalized)


# renormalize replays normalizers over heterogeneous historical payloads.
@pytest.mark.parametrize("normalizer", [normalize_galaxy, normalize_store, normalize_gamesdb])
def test_normalize_empty_payload(normalizer):
    assert normalizer({}) == {}
