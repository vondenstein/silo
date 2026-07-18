import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from typing import NamedTuple

import httpx
from bs4 import BeautifulSoup

from silo.sources.client import USER_AGENT

REDUMP_URL = "http://redump.org"


class RedumpSystem(NamedTuple):
    slug: str
    name: str
    dat_url: str


def parse_systems(html: str) -> list[RedumpSystem]:
    """Systems from the redump.org homepage menu (/discs/system/{slug}/ links)."""
    soup = BeautifulSoup(html, "html.parser")
    systems: list[RedumpSystem] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not isinstance(href, str) or not href.startswith("/discs/system/"):
            continue
        parts = href.strip("/").split("/")
        if len(parts) < 3:
            continue
        slug = parts[2]
        if slug in seen:
            continue
        seen.add(slug)
        label = link.get_text(strip=True).lstrip("• ")
        name = label or slug
        systems.append(RedumpSystem(slug=slug, name=name, dat_url=f"{REDUMP_URL}/datfile/{slug}/"))
    return systems


async def fetch_systems() -> list[RedumpSystem]:
    """Scrape the homepage (the dedicated downloads page hangs for some clients)."""
    timeout = httpx.Timeout(connect=15.0, read=180.0, write=30.0, pool=15.0)
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"},
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        resp = await client.get(f"{REDUMP_URL}/")
        resp.raise_for_status()
    return parse_systems(resp.text)


async def download_dat(url: str) -> bytes:
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, timeout=120, follow_redirects=True
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


class DatEntry(NamedTuple):
    game_name: str
    file_name: str
    category: str | None
    size: int | None
    md5: str | None
    sha1: str | None
    crc32: str | None


class ParsedDat(NamedTuple):
    version: str | None
    entries: list[DatEntry]


def parse_dat(data: bytes) -> ParsedDat:
    """Logiqx DAT (XML, possibly zip-wrapped) → header version + rom entries."""
    if data[:2] == b"PK":
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".dat")]
            if not names:
                raise ValueError("no .dat file in the zip")
            data = archive.read(names[0])
    root = ET.fromstring(data)
    dat_version = root.findtext("header/version") or None
    entries: list[DatEntry] = []
    for game in root.findall("game"):
        game_name = game.get("name", "")
        category = game.findtext("category") or None
        for rom in game.findall("rom"):
            entries.append(
                DatEntry(
                    game_name=game_name,
                    file_name=rom.get("name", ""),
                    category=category,
                    size=int(rom.get("size", 0)) or None,
                    md5=(rom.get("md5") or "").lower() or None,
                    sha1=(rom.get("sha1") or "").lower() or None,
                    crc32=(rom.get("crc") or "").lower() or None,
                )
            )
    return ParsedDat(version=dat_version, entries=entries)
