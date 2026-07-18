from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.secret import Secret
from silo.sources import common
from silo.sources.client import ThrottledClient
from silo.sources.common import clean_description, dedup_assets, entity_ref

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
API_URL = "https://api.igdb.com/v4"

CLIENT_ID_SECRET = "igdb_client_id"
CLIENT_SECRET_SECRET = "igdb_client_secret"

# IGDB allows 4 requests/second; used when the registry row's interval is null.
DEFAULT_REQUEST_INTERVAL_MS = 250

EXTERNAL_SOURCE_STEAM = 1
EXTERNAL_SOURCE_GOG = 5

# external_games.external_game_source → registry slug (F2).
_IDENTITY_SOURCES = {EXTERNAL_SOURCE_STEAM: "steam", EXTERNAL_SOURCE_GOG: "gog"}

# IGDB platform names → seeded platform slugs; release_dates carry names only,
# so keying on names keeps stored payloads re-normalizable offline.
_PLATFORMS = {"PC (Microsoft Windows)": "windows", "Mac": "macos", "Linux": "linux"}

_RATING_ORGS = {
    "ESRB": "esrb",
    "PEGI": "pegi",
    "USK": "usk",
    "CERO": "cero",
    "ACB": "acb",
    "CLASS_IND": "classind",
    "GRAC": "grac",
}

_GAME_TYPES = {0: "main", 1: "dlc", 2: "expansion"}

_IMAGE_URL_TEMPLATE = "https://images.igdb.com/igdb/image/upload/t_original/{image_id}.{ext}"

# The census's corrected query (design/source-fields.md) + external_games.uid.
GAME_FIELDS = (
    "fields name,slug,summary,storyline,url,first_release_date,"
    "aggregated_rating,aggregated_rating_count,rating,rating_count,"
    "total_rating,total_rating_count,hypes,"
    "game_type.type,cover.image_id,cover.width,cover.height,"
    "artworks.image_id,artworks.width,artworks.height,"
    "screenshots.image_id,screenshots.width,screenshots.height,"
    "videos.video_id,videos.name,genres.name,genres.slug,themes.name,themes.slug,"
    "keywords.name,keywords.slug,game_modes.name,game_modes.slug,"
    "player_perspectives.name,player_perspectives.slug,game_engines.name,game_engines.slug,"
    "platforms.name,platforms.slug,platforms.abbreviation,"
    "platforms.platform_family.name,platforms.platform_type,"
    "involved_companies.developer,involved_companies.publisher,involved_companies.porting,"
    "involved_companies.supporting,involved_companies.company.name,"
    "involved_companies.company.slug,franchises.name,franchises.slug,"
    "collections.name,collections.slug,multiplayer_modes.*,"
    "alternative_names.name,alternative_names.comment,"
    "language_supports.language.name,language_supports.language.locale,"
    "language_supports.language_support_type.name,"
    "game_localizations.name,game_localizations.region,"
    "release_dates.human,release_dates.y,release_dates.m,release_dates.date,"
    "release_dates.date_format,release_dates.platform.name,release_dates.release_region,"
    "release_dates.status,age_ratings.organization.name,age_ratings.rating_category.rating,"
    "age_ratings.rating_content_descriptions.description,"
    "external_games.name,external_games.url,external_games.external_game_source,"
    "external_games.uid,"
    "dlcs.name,dlcs.slug,expansions.name,expansions.slug,ports.name,remakes.name,"
    "remasters.name,parent_game.name,websites.url,websites.type"
)


class IgdbNotConfiguredError(Exception):
    def __init__(self) -> None:
        super().__init__("IGDB credentials are not configured")


async def store_credentials(session: AsyncSession, client_id: str, client_secret: str) -> None:
    """Upsert both credential secrets."""
    for name, value in ((CLIENT_ID_SECRET, client_id), (CLIENT_SECRET_SECRET, client_secret)):
        secret = await session.get(Secret, name)
        if secret is None:
            session.add(Secret(name=name, value=value))
        else:
            secret.value = value
    await session.flush()


async def clear_credentials(session: AsyncSession) -> None:
    for name in (CLIENT_ID_SECRET, CLIENT_SECRET_SECRET):
        secret = await session.get(Secret, name)
        if secret is not None:
            await session.delete(secret)
    await session.flush()


async def credentials(session: AsyncSession) -> tuple[str, str]:
    """The stored (client_id, client_secret); raises when unconfigured."""
    client_id = await session.get(Secret, CLIENT_ID_SECRET)
    client_secret = await session.get(Secret, CLIENT_SECRET_SECRET)
    if client_id is None or client_secret is None:
        raise IgdbNotConfiguredError
    return client_id.value, client_secret.value


async def is_configured(session: AsyncSession) -> bool:
    return (
        await session.get(Secret, CLIENT_ID_SECRET) is not None
        and await session.get(Secret, CLIENT_SECRET_SECRET) is not None
    )


async def app_token(client_id: str, client_secret: str) -> str:
    """Twitch client-credentials app token (fetched per run, never stored)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            TOKEN_URL,
            params={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


async def request_interval(session: AsyncSession) -> int:
    """The igdb registry row's request_interval_ms (polite default when null)."""
    return await common.request_interval(session, "igdb", DEFAULT_REQUEST_INTERVAL_MS)


class IgdbClient(ThrottledClient):
    """Authenticated IGDB v4 client (APIcalypse queries)."""

    def __init__(
        self,
        client_id: str,
        access_token: str,
        request_interval_ms: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            headers={"Client-ID": client_id, "Authorization": f"Bearer {access_token}"},
            request_interval_ms=request_interval_ms,
            transport=transport,
        )

    async def _query(self, endpoint: str, body: str) -> list[dict[str, Any]]:
        resp = await self._post(f"{API_URL}/{endpoint}", content=body)
        return resp.json()

    async def game(self, igdb_id: int) -> dict[str, Any] | None:
        """Raw game payload (the igdb metadata_record raw_payload)."""
        rows = await self._query("games", f"{GAME_FIELDS}; where id = {igdb_id};")
        return rows[0] if rows else None

    async def discover(self, external_source: int, uid: str) -> int | None:
        """IGDB game id from the external_games cross-reference."""
        rows = await self._query(
            "external_games",
            f'fields game; where uid = "{uid}" & external_game_source = {external_source};',
        )
        return rows[0].get("game") if rows else None

    async def search(self, term: str) -> list[dict[str, Any]]:
        """Relevance-ordered title-search candidates."""
        escaped = term.replace('"', "")
        return await self._query(
            "games", f'search "{escaped}"; fields name,slug,first_release_date; limit 10;'
        )


def _image_url(value: dict[str, Any] | None, ext: str) -> str | None:
    """Full-res image URL from an IGDB image object."""
    image_id = (value or {}).get("image_id")
    return _IMAGE_URL_TEMPLATE.format(image_id=image_id, ext=ext) if image_id else None


async def search_candidates(client: IgdbClient, term: str) -> list[dict[str, Any]]:
    """Normalized search candidates: {external_id, name, year}."""
    candidates = []
    for row in await client.search(term):
        epoch = row.get("first_release_date")
        year = datetime.fromtimestamp(epoch, tz=timezone.utc).year if epoch else None
        candidates.append(
            {"external_id": str(row["id"]), "name": row.get("name", ""), "year": year}
        )
    return candidates


def uids(payload: dict[str, Any]) -> dict[str, str]:
    """SourceSpec.uids: cross-catalog ids from external_games (F2), slug → uid."""
    found: dict[str, str] = {}
    for entry in payload.get("external_games") or []:
        slug = _IDENTITY_SOURCES.get(entry.get("external_game_source"))
        uid = entry.get("uid")
        if slug is not None and uid:
            found.setdefault(slug, str(uid))
    return found


def _refs(items: list[dict[str, Any]] | None, namespace: str) -> list[dict[str, str]]:
    """Entity refs from IGDB {id, name} objects, uids namespaced per endpoint
    (the post-6d game_tag fix — IGDB ids are only unique per endpoint)."""
    return [
        entity_ref(
            item["name"], f"{namespace}:{item['id']}" if item.get("id") is not None else None
        )
        for item in items or []
        if item.get("name")
    ]


def _release_dates(entries: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Earliest date per mapped platform (ISO strings compare correctly)."""
    earliest: dict[str, str] = {}
    for entry in entries or []:
        slug = _PLATFORMS.get((entry.get("platform") or {}).get("name", ""))
        epoch = entry.get("date")
        if slug is None or epoch is None:
            continue
        released = datetime.fromtimestamp(epoch, tz=timezone.utc).date().isoformat()
        if slug not in earliest or released < earliest[slug]:
            earliest[slug] = released
    return [{"platform": slug, "date": released} for slug, released in earliest.items()]


def _ratings(entries: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Canonical rating entries from age_ratings (unmapped authorities skipped)."""
    ratings: list[dict[str, Any]] = []
    for entry in entries or []:
        authority = _RATING_ORGS.get((entry.get("organization") or {}).get("name", ""))
        value = (entry.get("rating_category") or {}).get("rating")
        if authority is None or not value:
            continue
        ratings.append(
            {
                "authority": authority,
                "value": value,
                "descriptors": [
                    d["description"]
                    for d in entry.get("rating_content_descriptions") or []
                    if d.get("description")
                ],
            }
        )
    return ratings


def normalize(payload: dict[str, Any]) -> dict[str, Any]:
    """IGDB game payload → canonical-keyed fields (source-fields.md F-decisions)."""
    normalized: dict[str, Any] = {}
    if name := payload.get("name"):
        normalized["title"] = name
    if summary := payload.get("summary"):
        normalized["description_short"] = clean_description(summary)
    if storyline := payload.get("storyline"):
        normalized["description_full"] = clean_description(storyline)
    if (epoch := payload.get("first_release_date")) is not None:
        released = datetime.fromtimestamp(epoch, tz=timezone.utc).date()
        normalized["first_release_date"] = released.isoformat()
    type_id = (payload.get("game_type") or {}).get("id")
    if type_id is not None and (mapped := _GAME_TYPES.get(type_id)) is not None:
        normalized["game_type"] = mapped

    if genres := _refs(payload.get("genres"), "genre"):
        normalized["genres"] = genres
    if themes := _refs(payload.get("themes"), "theme"):
        normalized["themes"] = themes
    if tags := _refs(payload.get("keywords"), "keyword") + _refs(
        payload.get("player_perspectives"), "perspective"
    ):
        normalized["tags"] = tags
    if modes := _refs(payload.get("game_modes"), "mode"):
        normalized["modes"] = modes
    if engines := _refs(payload.get("game_engines"), "engine"):
        normalized["engines"] = engines
    if series := _refs(payload.get("franchises"), "franchise") + _refs(
        payload.get("collections"), "collection"
    ):
        normalized["series"] = series
    developers: list[dict[str, str]] = []
    publishers: list[dict[str, str]] = []
    for involved in payload.get("involved_companies") or []:
        company = involved.get("company") or {}
        if not company.get("name"):
            continue
        company_ref = entity_ref(company["name"], company.get("id"))
        if involved.get("developer"):
            developers.append(company_ref)
        if involved.get("publisher"):
            publishers.append(company_ref)
    if developers:
        normalized["developers"] = developers
    if publishers:
        normalized["publishers"] = publishers
    if platforms := [
        slug
        for platform in payload.get("platforms") or []
        if (slug := _PLATFORMS.get(platform.get("name", "")))
    ]:
        normalized["platforms"] = platforms
    if release_dates := _release_dates(payload.get("release_dates")):
        normalized["release_dates"] = release_dates
    if ratings := _ratings(payload.get("age_ratings")):
        normalized["ratings"] = ratings
    if alt_names := [
        {"name": alt["name"], "comment": alt.get("comment") or None}
        for alt in payload.get("alternative_names") or []
        if alt.get("name")
    ]:
        normalized["alt_names"] = alt_names
    if videos := [
        {
            "provider": "youtube",
            "video_id": video["video_id"],
            "url": f"https://www.youtube.com/watch?v={video['video_id']}",
            "name": video.get("name") or None,
        }
        for video in payload.get("videos") or []
        if video.get("video_id")
    ]:
        normalized["videos"] = videos

    assets: list[dict[str, str]] = []
    # 5c fidelity policy: cover at full-res png, art/screenshots at jpg (the
    # future asset-fidelity setting turns on these arguments).
    if url := _image_url(payload.get("cover"), "png"):
        assets.append({"kind": "cover", "url": url})
    for artwork in payload.get("artworks") or []:
        if url := _image_url(artwork, "jpg"):
            assets.append({"kind": "landscape", "url": url})
    for screenshot in payload.get("screenshots") or []:
        if url := _image_url(screenshot, "jpg"):
            assets.append({"kind": "screenshot", "url": url})
    if assets:
        normalized["assets"] = dedup_assets(assets)
    return normalized
