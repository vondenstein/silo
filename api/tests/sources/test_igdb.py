import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from silo.schemas.normalized_metadata import NormalizedMetadata
from silo.sources.igdb import (
    EXTERNAL_SOURCE_GOG,
    IgdbClient,
    IgdbNotConfiguredError,
    clear_credentials,
    credentials,
    is_configured,
    normalize,
    search_candidates,
    store_credentials,
    uids,
)

SessionFactory = async_sessionmaker[AsyncSession]

FIXTURE = json.loads((Path(__file__).parent.parent / "fixtures" / "igdb_game.json").read_text())[0]


def test_normalize_maps_igdb_fields():
    normalized = normalize(FIXTURE)

    assert normalized["title"] == "Baldur's Gate III"
    assert normalized["description_short"].startswith("An ancient evil has returned")
    # F1: storyline feeds the long-form description.
    assert normalized["description_full"].startswith("The land of Faerûn is in turmoil")
    assert normalized["first_release_date"] == "2023-08-03"
    assert normalized["game_type"] == "main"
    NormalizedMetadata.model_validate(normalized)


def test_normalize_extracts_assets():
    by_kind: dict[str, list[str]] = {}
    for asset in normalize(FIXTURE)["assets"]:
        by_kind.setdefault(asset["kind"], []).append(asset["url"])

    assert by_kind["cover"] == ["https://images.igdb.com/igdb/image/upload/t_original/co670h.png"]
    assert len(by_kind["landscape"]) == 4
    assert len(by_kind["screenshot"]) == 16
    assert by_kind["screenshot"][0] == (
        "https://images.igdb.com/igdb/image/upload/t_original/sc81fj.jpg"
    )


def test_normalize_extracts_collections():
    normalized = normalize(FIXTURE)

    assert [g["name"] for g in normalized["genres"]] == [
        "Role-playing (RPG)",
        "Strategy",
        "Turn-based strategy (TBS)",
    ]
    assert normalized["genres"][0]["uid"] == "genre:12"
    assert [t["name"] for t in normalized["themes"]] == ["Action", "Fantasy"]
    # keywords (51) + player_perspectives (1) → tags.
    assert len(normalized["tags"]) == 52
    assert {m["name"] for m in normalized["modes"]} == {
        "Single player",
        "Multiplayer",
        "Co-operative",
        "Split screen",
    }
    assert [e["name"] for e in normalized["engines"]] == ["Divinity Engine"]
    # franchises + collections both feed series.
    assert [s["name"] for s in normalized["series"]] == [
        "Dungeons & Dragons",
        "Forgotten Realms",
        "Baldur's Gate",
    ]
    developers = [d["name"] for d in normalized["developers"]]
    assert "Larian Studios" in developers
    # supporting/porting-only companies are skipped.
    assert "Wushu Studios" not in developers
    assert "Larian Studios" in [p["name"] for p in normalized["publishers"]]
    assert normalized["platforms"] == ["linux", "windows", "macos"]
    # Earliest date per mapped platform; console entries drop with their platforms.
    assert {(r["platform"], r["date"]) for r in normalized["release_dates"]} == {
        ("windows", "2020-10-06"),
        ("macos", "2020-10-06"),
        ("linux", "2025-09-23"),
    }
    ratings = {r["authority"]: r["value"] for r in normalized["ratings"]}
    assert ratings == {
        "cero": "Z",
        "pegi": "18",
        "classind": "16",
        "esrb": "M",
        "grac": "19+",
        "usk": "18",
        "acb": "MA 15+",
    }
    pegi = next(r for r in normalized["ratings"] if r["authority"] == "pegi")
    assert pegi["descriptors"] == ["Bad Language", "Sex", "Violence"]
    assert {"name": "BG3", "comment": "Acronym"} in normalized["alt_names"]
    assert normalized["videos"][0] == {
        "provider": "youtube",
        "video_id": "jNY7AEQ59-8",
        "url": "https://www.youtube.com/watch?v=jNY7AEQ59-8",
        "name": "Cinematic Trailer",
    }
    NormalizedMetadata.model_validate(normalized)


def test_uids_maps_known_sources():
    payload = {
        "external_games": [
            {"external_game_source": 1, "uid": "1086940"},
            {"external_game_source": 5, "uid": "1456460669"},
            {"external_game_source": 1, "uid": "999"},
            {"external_game_source": 3, "uid": "ignored"},
            {"external_game_source": 1},
        ]
    }
    # First uid per source wins; unknown sources and uid-less entries are skipped.
    assert uids(payload) == {"steam": "1086940", "gog": "1456460669"}
    # The stored fixture predates the uid field — nothing harvestable.
    assert uids(FIXTURE) == {}


async def test_client_queries_games_and_external_games():
    bodies: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Client-ID"] == "cid"
        assert request.headers["Authorization"] == "Bearer tok"
        bodies.append((request.url.path, request.content.decode()))
        if request.url.path == "/v4/games":
            return httpx.Response(200, json=[{"id": 119171, "name": "BG3"}])
        return httpx.Response(200, json=[{"id": 1, "game": 119171}])

    async with IgdbClient("cid", "tok", transport=httpx.MockTransport(handler)) as client:
        game = await client.game(119171)
        discovered = await client.discover(EXTERNAL_SOURCE_GOG, "1456460669")

    assert game == {"id": 119171, "name": "BG3"}
    assert discovered == 119171
    assert bodies[0][0] == "/v4/games"
    assert "where id = 119171;" in bodies[0][1]
    assert "external_games.uid" in bodies[0][1]
    assert bodies[1][0] == "/v4/external_games"
    assert 'uid = "1456460669" & external_game_source = 5' in bodies[1][1]


async def test_search_candidates_queries_and_shapes():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v4/games"
        body = request.content.decode()
        # Quotes are stripped from the term; relevance search with a small limit.
        assert 'search "doom";' in body
        assert "limit 10;" in body
        return httpx.Response(
            200,
            json=[
                {"id": 77, "name": "Doom", "first_release_date": 755481600},
                {"id": 88, "name": "Doom II"},
            ],
        )

    async with IgdbClient("cid", "tok", transport=httpx.MockTransport(handler)) as client:
        candidates = await search_candidates(client, 'do"om')

    assert candidates == [
        {"external_id": "77", "name": "Doom", "year": 1993},
        {"external_id": "88", "name": "Doom II", "year": None},
    ]


async def test_client_handles_empty_results():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    async with IgdbClient("cid", "tok", transport=httpx.MockTransport(handler)) as client:
        assert await client.game(1) is None
        assert await client.discover(EXTERNAL_SOURCE_GOG, "x") is None


async def test_credentials_roundtrip(session_factory: SessionFactory):
    async with session_factory() as session:
        assert await is_configured(session) is False
        with pytest.raises(IgdbNotConfiguredError):
            await credentials(session)
        await store_credentials(session, "cid", "csecret")
        await session.commit()

    async with session_factory() as session:
        assert await is_configured(session) is True
        assert await credentials(session) == ("cid", "csecret")
        # Upsert overwrites on re-entry.
        await store_credentials(session, "cid2", "csecret2")
        await session.commit()

    async with session_factory() as session:
        assert await credentials(session) == ("cid2", "csecret2")
        await clear_credentials(session)
        await session.commit()

    async with session_factory() as session:
        assert await is_configured(session) is False


AOW_FIXTURE = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "igdb_game_aow.json").read_text()
)


def test_normalize_namespaces_uids_per_family():
    # Each IGDB endpoint is an independent numeric id namespace; flattening any
    # single family reintroduces the post-6d game_tag PK crash (mode 1 vs
    # keyword 1 landed the same tag in two kind lists).
    normalized = normalize(FIXTURE)

    assert normalized["themes"][0]["uid"] == "theme:1"
    tag_uids = {t["uid"] for t in normalized["tags"] if t.get("uid")}
    assert "keyword:72" in tag_uids
    assert "perspective:3" in tag_uids
    assert normalized["modes"][0]["uid"] == "mode:1"
    assert normalized["engines"][0]["uid"] == "engine:255"
    assert [s["uid"] for s in normalized["series"]] == [
        "franchise:43",
        "franchise:6951",
        "collection:7",
    ]
    # Companies join across sources by shared external ids — uids stay raw.
    developer = next(d for d in normalized["developers"] if d["name"] == "Larian Studios")
    assert developer["uid"] == "510"


def test_uids_harvests_real_payload():
    # Real stored payload (dev-DB capture, Age of Wonders): uid is a STRING on
    # the wire; unmapped sources (giantbomb & co) are skipped.
    assert uids(AOW_FIXTURE) == {"steam": "61500", "gog": "1207658883"}


def test_normalize_empty_payload():
    # renormalize replays normalizers over heterogeneous historical payloads.
    assert normalize({}) == {}


def test_normalize_asset_kind_set():
    # 7a: the emitted kind SET is the contract, not per-kind counts.
    assert {asset["kind"] for asset in normalize(FIXTURE)["assets"]} == {
        "cover",
        "landscape",
        "screenshot",
    }
