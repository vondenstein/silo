import json
from pathlib import Path

import httpx

from silo.schemas.normalized_metadata import NormalizedMetadata
from silo.sources.steam import SteamClient, _parse_release_date, normalize

FIXTURE = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "steam_appdetails.json").read_text()
)
DATA = next(iter(FIXTURE.values()))["data"]


def test_normalize_maps_steam_fields():
    normalized = normalize(DATA)

    assert normalized["title"] == "Baldur's Gate 3"
    assert normalized["description_short"]
    assert normalized["first_release_date"] == "2023-08-03"
    assert normalized["game_type"] == "main"
    # Steam's marketing HTML never feeds description_full (census S-decisions).
    assert "description_full" not in normalized
    NormalizedMetadata.model_validate(normalized)


def test_normalize_extracts_assets():
    by_kind: dict[str, list[str]] = {}
    for asset in normalize(DATA)["assets"]:
        by_kind.setdefault(asset["kind"], []).append(asset["url"])

    assert len(by_kind["landscape"]) == 1
    assert "header.jpg" in by_kind["landscape"][0]
    assert len(by_kind["background"]) == 1
    assert "page_bg_raw" in by_kind["background"][0]
    assert len(by_kind["screenshot"]) == 19
    assert ".1920x1080.jpg" in by_kind["screenshot"][0]
    assert len(by_kind["video_thumbnail"]) == 6


def test_normalize_extracts_collections():
    normalized = normalize(DATA)

    assert normalized["developers"] == [{"name": "Larian Studios"}]
    assert normalized["publishers"] == [{"name": "Larian Studios"}]
    assert [g["name"] for g in normalized["genres"]] == ["Adventure", "RPG", "Strategy"]
    # S1: only the mode-shaped categories map; Steam-proprietary ones drop.
    assert [m["name"] for m in normalized["modes"]] == [
        "Single player",
        "Multiplayer",
        "Co-operative",
    ]
    assert normalized["platforms"] == ["windows", "macos"]
    ratings = {r["authority"]: r["value"] for r in normalized["ratings"]}
    assert set(ratings) == {"esrb", "pegi", "classind", "csrr", "usk", "igrs", "acb"}
    assert ratings["esrb"] == "m"
    # The usk block wins over steam_germany (first mapped key per authority).
    assert ratings["usk"] == "18"
    esrb = next(r for r in normalized["ratings"] if r["authority"] == "esrb")
    assert "Intense Violence" in esrb["descriptors"]
    assert len(esrb["descriptors"]) == 5
    assert normalized["videos"][0]["provider"] == "steam"
    assert normalized["videos"][0]["name"] == "Baldur's Gate 3 - Accolades Trailer"
    assert normalized["videos"][0]["url"].startswith("https://video.akamai.steamstatic.com/")
    NormalizedMetadata.model_validate(normalized)


def test_parse_release_date_variants():
    assert _parse_release_date({"coming_soon": False, "date": "3 Aug, 2023"}) == "2023-08-03"
    assert _parse_release_date({"coming_soon": False, "date": "Aug 3, 2023"}) == "2023-08-03"
    assert _parse_release_date({"coming_soon": True, "date": "3 Aug, 2023"}) is None
    assert _parse_release_date({"coming_soon": False, "date": "Coming soon"}) is None
    assert _parse_release_date(None) is None


async def test_appdetails_unwraps_envelope():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/appdetails"
        assert request.url.params["appids"] == "1086940"
        assert request.url.params["cc"] == "us"
        return httpx.Response(200, json={"1086940": {"success": True, "data": {"name": "BG3"}}})

    async with SteamClient(transport=httpx.MockTransport(handler)) as client:
        assert await client.appdetails(1086940) == {"name": "BG3"}


async def test_appdetails_failure_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"999": {"success": False}})

    async with SteamClient(transport=httpx.MockTransport(handler)) as client:
        assert await client.appdetails(999) is None


def test_normalize_asset_kind_set():
    # 7a: capsules stay out — the kind SET is the contract, not per-kind counts.
    by_kind: dict[str, list[str]] = {}
    for asset in normalize(DATA)["assets"]:
        by_kind.setdefault(asset["kind"], []).append(asset["url"])

    assert set(by_kind) == {"background", "landscape", "screenshot", "video_thumbnail"}


def test_normalize_empty_payload():
    # renormalize replays normalizers over heterogeneous historical payloads.
    assert normalize({}) == {}
