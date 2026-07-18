import re
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from silo.sources import common
from silo.sources.client import ThrottledClient
from silo.sources.common import clean_description, dedup_assets, entity_ref

STORE_URL = "https://store.steampowered.com"

# The storefront rate-limits aggressively; used when the registry row's interval is null.
DEFAULT_REQUEST_INTERVAL_MS = 1500

_GAME_TYPES = {"game": "main", "dlc": "dlc"}

_OS_SLUGS = {"windows": "windows", "mac": "macos", "linux": "linux"}

# S1: the mode-shaped categories, named to converge with IGDB's mode entities.
_MODE_CATEGORIES = {1: "Multiplayer", 2: "Single player", 9: "Co-operative"}

# ratings block keys → canonical authority; first hit per authority wins.
_RATING_KEYS = (
    ("esrb", "esrb"),
    ("pegi", "pegi"),
    ("usk", "usk"),
    ("steam_germany", "usk"),
    ("dejus", "classind"),
    ("csrr", "csrr"),
    ("igrs", "igrs"),
    ("steam_australia", "acb"),
)

# cc/l pin the release_date format; both orderings still appear. Months are
# matched explicitly — strptime's %b reads the HOST locale, not the payload's.
_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_DATE_PATTERNS = (
    re.compile(r"^(?P<day>\d{1,2}) (?P<month>[A-Za-z]{3,9}),? (?P<year>\d{4})$"),
    re.compile(r"^(?P<month>[A-Za-z]{3,9}) (?P<day>\d{1,2}),? (?P<year>\d{4})$"),
)


async def request_interval(session: AsyncSession) -> int:
    """The steam registry row's request_interval_ms (polite default when null)."""
    return await common.request_interval(session, "steam", DEFAULT_REQUEST_INTERVAL_MS)


class SteamClient(ThrottledClient):
    """Steam storefront client (keyless)."""

    async def appdetails(self, app_id: int) -> dict[str, Any] | None:
        """Raw appdetails data (the steam metadata_record raw_payload)."""
        resp = await self._get(
            f"{STORE_URL}/api/appdetails", params={"appids": app_id, "cc": "us", "l": "en"}
        )
        entry = resp.json().get(str(app_id)) or {}
        return entry.get("data") if entry.get("success") else None


def _parse_release_date(value: dict[str, Any] | None) -> str | None:
    if not value or value.get("coming_soon"):
        return None
    text = (value.get("date") or "").strip()
    for pattern in _DATE_PATTERNS:
        if match := pattern.match(text):
            month = _MONTHS.get(match["month"][:3].lower())
            if month is None:
                return None
            try:
                return date(int(match["year"]), month, int(match["day"])).isoformat()
            except ValueError:
                return None
    return None


def normalize(payload: dict[str, Any]) -> dict[str, Any]:
    """Steam appdetails data → canonical-keyed fields (source-fields.md S-decisions)."""
    normalized: dict[str, Any] = {}
    if name := payload.get("name"):
        normalized["title"] = name
    if short_description := payload.get("short_description"):
        normalized["description_short"] = clean_description(short_description)
    if released := _parse_release_date(payload.get("release_date")):
        normalized["first_release_date"] = released
    if game_type := _GAME_TYPES.get(payload.get("type", "")):
        normalized["game_type"] = game_type

    if developers := [entity_ref(name) for name in payload.get("developers") or [] if name]:
        normalized["developers"] = developers
    if publishers := [entity_ref(name) for name in payload.get("publishers") or [] if name]:
        normalized["publishers"] = publishers
    if genres := [
        entity_ref(g["description"]) for g in payload.get("genres") or [] if g.get("description")
    ]:
        normalized["genres"] = genres
    modes: list[dict[str, str]] = []
    for category in payload.get("categories") or []:
        name = _MODE_CATEGORIES.get(category.get("id"))
        if name is not None and entity_ref(name) not in modes:
            modes.append(entity_ref(name))
    if modes:
        normalized["modes"] = modes
    os_flags = payload.get("platforms") or {}
    if platforms := [slug for key, slug in _OS_SLUGS.items() if os_flags.get(key)]:
        normalized["platforms"] = platforms
    ratings = []
    taken: set[str] = set()
    for key, authority in _RATING_KEYS:
        block = (payload.get("ratings") or {}).get(key)
        if not block or not block.get("rating") or authority in taken:
            continue
        taken.add(authority)
        ratings.append(
            {
                "authority": authority,
                "value": block["rating"],
                "descriptors": [
                    line for line in (block.get("descriptors") or "").splitlines() if line
                ],
            }
        )
    if ratings:
        normalized["ratings"] = ratings
    if videos := [
        {
            "provider": "steam",
            "url": movie["hls_h264"],
            "name": movie.get("name") or None,
        }
        for movie in payload.get("movies") or []
        if movie.get("hls_h264")
    ]:
        normalized["videos"] = videos

    assets: list[dict[str, str]] = []
    if header := payload.get("header_image"):
        assets.append({"kind": "landscape", "url": header})
    if background := payload.get("background_raw"):
        assets.append({"kind": "background", "url": background})
    for screenshot in payload.get("screenshots") or []:
        if url := screenshot.get("path_full"):
            assets.append({"kind": "screenshot", "url": url})
    for movie in payload.get("movies") or []:
        if url := movie.get("thumbnail"):
            assets.append({"kind": "video_thumbnail", "url": url})
    if assets:
        normalized["assets"] = dedup_assets(assets)
    return normalized
