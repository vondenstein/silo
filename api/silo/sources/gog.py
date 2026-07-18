import re
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.secret import Secret
from silo.sources import common
from silo.sources.client import ThrottledClient
from silo.sources.common import clean_description, dedup_assets, entity_ref

AUTH_BASE_URL = "https://auth.gog.com/auth"
TOKEN_URL = "https://auth.gog.com/token"
EMBED_URL = "https://embed.gog.com"
API_URL = "https://api.gog.com"
GAMESDB_URL = "https://gamesdb.gog.com"

# The whole family rides one client; applied when the gog row's interval is null.
DEFAULT_REQUEST_INTERVAL_MS = 250

# Well-known Galaxy client credentials (used by all community GOG tools).
CLIENT_ID = "46899977096215655"
CLIENT_SECRET = "9d85c43b1482497dbbce61f6e4aa173a433796eeae2ca8c5f6129f2dc4de46d9"
REDIRECT_URI = "https://embed.gog.com/on_login_success?origin=client"

PRODUCT_EXPAND = "downloads,expanded_dlcs,description,screenshots,videos,related_products"

ACCESS_TOKEN_SECRET = "gog_access_token"
REFRESH_TOKEN_SECRET = "gog_refresh_token"


class GogNotConnectedError(Exception):
    def __init__(self) -> None:
        super().__init__("GOG is not connected")


class GogTokens(BaseModel):
    access_token: str
    refresh_token: str


class OwnedGame(BaseModel):
    id: int
    title: str
    slug: str
    image_url: str | None = None


def auth_url() -> str:
    """URL the user visits to authorize Silo with GOG."""
    return (
        f"{AUTH_BASE_URL}?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
        f"&response_type=code&layout=client2"
    )


async def exchange_code(code: str) -> GogTokens:
    """Exchange an authorization code for tokens."""
    return await _token_request(
        {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI}
    )


async def refresh_tokens(refresh_token: str) -> GogTokens:
    """Refresh an expired access token."""
    return await _token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})


async def _token_request(params: dict[str, str]) -> GogTokens:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            TOKEN_URL,
            params={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, **params},
        )
        resp.raise_for_status()
        return GogTokens.model_validate(resp.json())


async def store_tokens(session: AsyncSession, tokens: GogTokens) -> None:
    """Upsert both token secrets."""
    for name, value in (
        (ACCESS_TOKEN_SECRET, tokens.access_token),
        (REFRESH_TOKEN_SECRET, tokens.refresh_token),
    ):
        secret = await session.get(Secret, name)
        if secret is None:
            session.add(Secret(name=name, value=value))
        else:
            secret.value = value
    await session.flush()


async def clear_tokens(session: AsyncSession) -> None:
    for name in (ACCESS_TOKEN_SECRET, REFRESH_TOKEN_SECRET):
        secret = await session.get(Secret, name)
        if secret is not None:
            await session.delete(secret)
    await session.flush()


async def is_connected(session: AsyncSession) -> bool:
    return await session.get(Secret, REFRESH_TOKEN_SECRET) is not None


async def request_interval(session: AsyncSession) -> int:
    """The gog registry row's request_interval_ms (family default when null)."""
    return await common.request_interval(session, "gog", DEFAULT_REQUEST_INTERVAL_MS)


async def fresh_access_token(session: AsyncSession) -> str:
    """Refresh via the stored refresh token, persist the rotation, return the access token."""
    secret = await session.get(Secret, REFRESH_TOKEN_SECRET)
    if secret is None:
        raise GogNotConnectedError
    tokens = await refresh_tokens(secret.value)
    await store_tokens(session, tokens)
    return tokens.access_token


class GogClient(ThrottledClient):
    """Authenticated GOG API client with per-request throttling."""

    def __init__(
        self,
        access_token: str,
        request_interval_ms: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            headers={"Authorization": f"Bearer {access_token}"},
            request_interval_ms=request_interval_ms,
            transport=transport,
        )

    async def owned_games(self) -> list[OwnedGame]:
        """The account's owned games (paginated)."""
        games: list[OwnedGame] = []
        page = 1
        while True:
            resp = await self._get(
                f"{EMBED_URL}/account/getFilteredProducts",
                params={"mediaType": 1, "page": page},
            )
            data = resp.json()
            games.extend(
                OwnedGame(
                    id=product["id"],
                    title=product["title"],
                    slug=product["slug"],
                    image_url=product.get("image"),
                )
                for product in data.get("products", [])
            )
            if page >= data.get("totalPages", 1):
                break
            page += 1
        return games

    async def product(self, gog_id: int) -> dict[str, Any]:
        """Raw Galaxy product payload (the gog metadata_record raw_payload)."""
        resp = await self._get(f"{API_URL}/products/{gog_id}", params={"expand": PRODUCT_EXPAND})
        return resp.json()

    async def product_v2(self, gog_id: int) -> dict[str, Any]:
        """Raw Store-v2 payload (the gog_store metadata_record raw_payload)."""
        resp = await self._get(f"{API_URL}/v2/games/{gog_id}")
        return resp.json()

    async def gamesdb_release(self, gog_id: int) -> dict[str, Any]:
        """Raw GamesDB release payload (the gog_gamesdb metadata_record raw_payload)."""
        resp = await self._get(f"{GAMESDB_URL}/platforms/gog/external_releases/{gog_id}")
        return resp.json()

    async def download_url(self, downlink: str) -> str:
        """Resolve a GOG downlink to a direct download URL."""
        await self._throttle()
        resp = await self._client.get(downlink, follow_redirects=False)
        if resp.status_code in (301, 302):
            return resp.headers["location"]
        resp.raise_for_status()
        return resp.json()["downlink"]


_GAME_TYPES = {"game": "main", "dlc": "dlc"}

_OS_SLUGS = {"windows": "windows", "osx": "macos", "linux": "linux"}

# GOG rating blocks ({ageRating, contentDescriptors}) → canonical authority.
_RATING_KEYS = (("pegiRating", "pegi"), ("uskRating", "usk"), ("brRating", "classind"))

ASSET_HOST = "https://images.gog-statics.com"


def _asset_url(url: str) -> str:
    """Normalize a GOG art URL: https, un-sharded host, size/chrome suffix stripped."""
    if url.startswith("//"):
        url = f"https:{url}"
    if "gog-statics.com" in url:
        url = re.sub(r"^https://images-\d+\.gog-statics\.com", ASSET_HOST, url)
        url = re.sub(r"_[a-z0-9_]+(\.(?:jpg|png))$", r"\1", url)
    return url


def _gamesdb_image(value: dict[str, Any] | None, ext: str) -> str | None:
    """Fill a GamesDB url_format template (empty formatter = the full image)."""
    url_format = (value or {}).get("url_format")
    if not url_format:
        return None
    return url_format.replace("{formatter}", "").replace("{ext}", ext)


def uids(payload: dict[str, Any]) -> dict[str, str]:
    """SourceSpec.uids: cross-catalog ids from GamesDB releases[] (D13), slug → uid."""
    found: dict[str, str] = {}
    for release in (payload.get("game") or {}).get("releases") or []:
        slug = release.get("platform_id")
        uid = release.get("external_id")
        if slug and uid:
            found.setdefault(slug, str(uid))
    return found


def normalize_galaxy(payload: dict[str, Any]) -> dict[str, Any]:
    """Galaxy payload → canonical-keyed fields (source-fields.md GOG D-decisions)."""
    normalized: dict[str, Any] = {}
    if title := payload.get("title"):
        normalized["title"] = title
    if description := (payload.get("description") or {}).get("full"):
        normalized["description_full"] = clean_description(description)
    if game_type := _GAME_TYPES.get(payload.get("game_type", "")):
        normalized["game_type"] = game_type
    # D2: Galaxy release_date is store-specific, not true first release — ignored.
    # D3-refinement: Galaxy's flat languages superseded by Store-v2 localizations —
    # not emitted (raw payloads keep the data for a future localization epic).
    compat = payload.get("content_system_compatibility") or {}
    if platforms := [slug for key, slug in _OS_SLUGS.items() if compat.get(key)]:
        normalized["platforms"] = platforms
    if videos := [
        {"provider": v["provider"], "url": v["video_url"]}
        for v in payload.get("videos") or []
        if v.get("provider") and v.get("video_url")
    ]:
        normalized["videos"] = videos
    assets: list[dict[str, str]] = []
    images = payload.get("images") or {}
    # Galaxy's "logo" is the 1600×740 grid-tile artwork, not a wordmark → landscape.
    for field, kind in (("background", "background"), ("logo", "landscape"), ("icon", "icon")):
        if url := images.get(field):
            assets.append({"kind": kind, "url": _asset_url(url)})
    for screenshot in payload.get("screenshots") or []:
        if image_id := screenshot.get("image_id"):
            assets.append({"kind": "screenshot", "url": f"{ASSET_HOST}/{image_id}.jpg"})
    for video in payload.get("videos") or []:
        if thumbnail := video.get("thumbnail_url"):
            assets.append({"kind": "video_thumbnail", "url": _asset_url(thumbnail)})
    if assets:
        normalized["assets"] = dedup_assets(assets)
    return normalized


def _localized(value: dict[str, Any] | None) -> str | None:
    """The "*" default of a {locale: str} mapping (cross-cutting locale rule)."""
    return (value or {}).get("*")


def normalize_store(payload: dict[str, Any]) -> dict[str, Any]:
    """Store-v2 payload → canonical-keyed fields (source-fields.md GOG D-decisions)."""
    normalized: dict[str, Any] = {}
    embedded = payload.get("_embedded") or {}
    product = embedded.get("product") or {}
    if title := product.get("title"):
        normalized["title"] = title
    if description := payload.get("description"):
        normalized["description_full"] = clean_description(description)
    if release := product.get("globalReleaseDate"):
        normalized["first_release_date"] = datetime.fromisoformat(release).date().isoformat()
    if payload.get("isUsingDosBox"):
        normalized["wrapper"] = "dosbox"
    if game_type := _GAME_TYPES.get(str(embedded.get("productType") or "").lower()):
        normalized["game_type"] = game_type
    if developers := [
        entity_ref(d["name"]) for d in embedded.get("developers") or [] if d.get("name")
    ]:
        normalized["developers"] = developers
    publishers = embedded.get("publishers") or (
        [embedded["publisher"]] if embedded.get("publisher") else []
    )
    if publisher_refs := [entity_ref(p["name"]) for p in publishers if p.get("name")]:
        normalized["publishers"] = publisher_refs
    if (series := embedded.get("series")) and series.get("name"):
        normalized["series"] = [entity_ref(series["name"], series.get("id"))]
    # D10: GOG tags → genre, properties → tag.
    if genres := [
        entity_ref(t["name"], t.get("id")) for t in embedded.get("tags") or [] if t.get("name")
    ]:
        normalized["genres"] = genres
    if tags := [entity_ref(p["name"]) for p in embedded.get("properties") or [] if p.get("name")]:
        normalized["tags"] = tags
    if platforms := [
        slug
        for system in embedded.get("supportedOperatingSystems") or []
        if (slug := _OS_SLUGS.get((system.get("operatingSystem") or {}).get("name", "")))
    ]:
        normalized["platforms"] = platforms
    ratings = []
    for key, authority in _RATING_KEYS:
        block = embedded.get(key)
        if block and block.get("ageRating") is not None:
            ratings.append(
                {
                    "authority": authority,
                    "value": str(block["ageRating"]),
                    # brRating descriptors arrive with trailing \r on the live API.
                    "descriptors": [
                        stripped
                        for d in block.get("contentDescriptors") or []
                        if (stripped := (d.get("descriptor") or "").strip())
                    ],
                }
            )
    if ratings:
        normalized["ratings"] = ratings
    videos = []
    for video in embedded.get("videos") or []:
        if not video.get("provider"):
            continue
        self_link = (video.get("_links") or {}).get("self") or {}
        videos.append(
            {
                "provider": video["provider"],
                "video_id": video.get("videoId"),
                "url": self_link.get("href"),
            }
        )
    if videos:
        normalized["videos"] = videos
    links = payload.get("_links") or {}
    # Store screenshots are Galaxy's set resized — deliberately not extracted.
    assets = [
        {"kind": kind, "url": _asset_url(href)}
        for field, kind in (
            ("boxArtImage", "cover"),
            ("backgroundImage", "background"),
            ("galaxyBackgroundImage", "background"),
            ("logo", "logo"),
            ("icon", "icon"),
        )
        if (href := (links.get(field) or {}).get("href"))
    ]
    if assets:
        normalized["assets"] = dedup_assets(assets)
    return normalized


def _gamesdb_refs(items: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Entity refs from GamesDB objects (names are plain or localized)."""
    refs = []
    for item in items or []:
        name = item.get("name")
        if not isinstance(name, str):
            name = _localized(name)
        if name:
            refs.append(entity_ref(name, item.get("id")))
    return refs


def normalize_gamesdb(payload: dict[str, Any]) -> dict[str, Any]:
    """GamesDB release payload → canonical-keyed fields (source-fields.md GOG D-decisions)."""
    normalized: dict[str, Any] = {}
    game = payload.get("game") or {}
    if title := _localized(game.get("title")):
        normalized["title"] = title
    if sort_title := _localized(game.get("sorting_title")):
        normalized["sort_title"] = sort_title
    if summary := _localized(game.get("summary")):
        normalized["description_short"] = clean_description(summary)
    if release := game.get("first_release_date"):
        normalized["first_release_date"] = datetime.fromisoformat(release).date().isoformat()
    if game_type := _GAME_TYPES.get(str(game.get("type") or "").lower()):
        normalized["game_type"] = game_type
    if developers := _gamesdb_refs(game.get("developers")):
        normalized["developers"] = developers
    if publishers := _gamesdb_refs(game.get("publishers")):
        normalized["publishers"] = publishers
    if genres := _gamesdb_refs(game.get("genres")):
        normalized["genres"] = genres
    if themes := _gamesdb_refs(game.get("themes")):
        normalized["themes"] = themes
    if modes := _gamesdb_refs(game.get("game_modes")):
        normalized["modes"] = modes
    if series := _gamesdb_refs([game["series"]] if game.get("series") else None):
        normalized["series"] = series
    if platforms := [
        slug
        for system in payload.get("supported_operating_systems") or []
        if (slug := _OS_SLUGS.get(system.get("slug", "")))
    ]:
        normalized["platforms"] = platforms
    # CR-199 (D4): the family's richest video source — youtube only (url-less
    # entries are unusable), URL synthesized like the IGDB adapter's.
    if videos := [
        {
            "provider": "youtube",
            "video_id": video["video_id"],
            "url": f"https://www.youtube.com/watch?v={video['video_id']}",
            "name": video.get("name") or None,
        }
        for video in game.get("videos") or []
        if video.get("video_id") and video.get("provider") == "youtube"
    ]:
        normalized["videos"] = videos
    assets: list[dict[str, str]] = []
    # Field→kind audit (2026-07-12, source-fields.md): horizontal_artwork duplicates
    # background; logo carries grid-tile art, not a wordmark; square_icon is
    # inconsistent art — all three deliberately unmapped.
    # 5c fidelity policy: art at full-res png, screenshots at jpg (the future
    # asset-fidelity setting turns on these arguments).
    for field, kind in (
        ("cover", "cover"),
        ("vertical_cover", "cover"),
        ("background", "background"),
    ):
        if url := _gamesdb_image(game.get(field), "png"):
            assets.append({"kind": kind, "url": url})
    for artwork in game.get("artworks") or []:
        if url := _gamesdb_image(artwork, "png"):
            assets.append({"kind": "landscape", "url": url})
    for screenshot in game.get("screenshots") or []:
        if url := _gamesdb_image(screenshot, "jpg"):
            assets.append({"kind": "screenshot", "url": url})
    if assets:
        normalized["assets"] = dedup_assets(assets)
    return normalized
