import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from silo.sources.redump import parse_dat, parse_systems

HOMEPAGE = """
<html><body>
  <a href="/discs/system/psx/">• PlayStation</a>
  <a href="/discs/system/psx/">PlayStation (duplicate)</a>
  <a href="/discs/system/dc/">• Sega Dreamcast</a>
  <a href="/downloads/">Downloads</a>
</body></html>
"""

DAT = b"""<?xml version="1.0"?>
<datafile>
  <header><name>Test</name><version>2026-07-11 00-00-00</version></header>
  <game name="Doom (USA)">
    <category>Games</category>
    <rom name="Doom (USA).bin" size="1000" crc="AABBCCDD" md5="A1" sha1="B2"/>
    <rom name="Doom (USA).cue" size="100" crc="11223344" md5="c3" sha1="d4"/>
  </game>
  <game name="Quake (Europe)">
    <rom name="Quake (Europe).bin" size="0" crc="" md5="e5" sha1="f6"/>
  </game>
</datafile>
"""


def test_parse_systems_dedups_and_builds_dat_urls():
    systems = parse_systems(HOMEPAGE)

    assert [(s.slug, s.name) for s in systems] == [
        ("psx", "PlayStation"),
        ("dc", "Sega Dreamcast"),
    ]
    assert systems[0].dat_url == "http://redump.org/datfile/psx/"


def test_parse_dat_entries_and_header():
    parsed = parse_dat(DAT)

    assert parsed.version == "2026-07-11 00-00-00"
    assert len(parsed.entries) == 3
    first = parsed.entries[0]
    assert (first.game_name, first.file_name, first.category) == (
        "Doom (USA)",
        "Doom (USA).bin",
        "Games",
    )
    # Hashes lowercase; empty/zero values become None.
    assert (first.md5, first.sha1, first.crc32, first.size) == ("a1", "b2", "aabbccdd", 1000)
    last = parsed.entries[2]
    assert (last.size, last.crc32) == (None, None)


def test_parse_dat_unwraps_zip():
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("test.dat", DAT)

    parsed = parse_dat(buffer.getvalue())

    assert len(parsed.entries) == 3


FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_parse_systems_real_homepage():
    # Real captured homepage (2026-07-16) — the scrape is the most drift-prone
    # parser in the slice; hand-built HTML can't pin its real structure.
    systems = parse_systems((FIXTURES / "redump_homepage.html").read_text())

    assert len(systems) == 60
    by_slug = {system.slug: system for system in systems}
    assert by_slug["psx"].name == "Sony PlayStation"
    assert by_slug["gamewave"].dat_url == "http://redump.org/datfile/gamewave/"


def test_parse_dat_real_zip_wrapped_dat():
    # Real captured DAT (Game Wave, the smallest system) — zip-wrapped Logiqx
    # exactly as redump serves it.
    parsed = parse_dat((FIXTURES / "redump_gamewave_dat.zip").read_bytes())

    assert parsed.version == "2025-12-08 00-53-19"
    assert len(parsed.entries) == 16
    entry = parsed.entries[0]
    assert entry.game_name == "4 Degrees - The Arc of Trivia - Bible Edition (USA)"
    assert entry.file_name == "4 Degrees - The Arc of Trivia - Bible Edition (USA).iso"
    assert (entry.category, entry.size) == ("Games", 4430123008)
    assert (entry.md5, entry.sha1, entry.crc32) == (
        "14e207e841a0c7129bbfb72a12b89cbc",
        "21001ee96dea1fd92ce2756e684ff9087cbff47f",
        "10e6f6a6",
    )


# The refresh job relies on these propagating (its stage fails with the error).
def test_parse_dat_zip_without_dat_raises():
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", b"not a dat")

    with pytest.raises(ValueError, match="no .dat file"):
        parse_dat(buffer.getvalue())


def test_parse_dat_malformed_xml_raises():
    with pytest.raises(ET.ParseError):
        parse_dat(b"<datafile><game")


def test_parse_dat_non_numeric_size_raises():
    with pytest.raises(ValueError):
        parse_dat(b'<datafile><game name="X"><rom name="x.bin" size="huge"/></game></datafile>')
