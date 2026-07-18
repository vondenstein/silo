from datetime import date, datetime
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.artifact import Artifact, ArtifactKind, ArtifactStatus
from silo.models.asset import AssetBlob, AssetKind
from silo.models.company import Company
from silo.models.field_lock import FieldKey, FieldLock
from silo.models.file import File
from silo.models.game import (
    CompanyRole,
    Game,
    GameAltName,
    GameAsset,
    GameCompany,
    GameExternalIdentity,
    GameMetadata,
    GamePlatform,
    GameRating,
    GameReleaseDate,
    GameSerial,
    GameSeries,
    GameTag,
    GameVideo,
    RatingAuthority,
    WrapperKind,
)
from silo.models.job import Job, JobKind
from silo.models.library import Library
from silo.models.metadata_record import MetadataRecord
from silo.models.metadata_source import MetadataSource
from silo.models.platform import Platform
from silo.models.series import Series
from silo.models.tag import Tag, TagKind


# TODO: promote these + the helpers in other test_*.py files to tests/factories.py.
def _library(slug: str = "main") -> Library:
    return Library(
        id=uuid4(),
        slug=slug,
        name=slug.capitalize(),
        created_at=datetime(2025, 1, 1),
        updated_at=datetime(2025, 1, 1),
    )


def _game(
    library_id,
    slug: str,
    title: str = "T",
    created_at: datetime | None = None,
) -> tuple[Game, GameMetadata]:
    game_id = uuid4()
    now = created_at or datetime(2025, 1, 1)
    return (
        Game(id=game_id, library_id=library_id, slug=slug, created_at=now, updated_at=now),
        GameMetadata(game_id=game_id, title=title),
    )


def _source(slug: str, priority: int) -> MetadataSource:
    return MetadataSource(id=uuid4(), slug=slug, name=slug.upper(), priority=priority)


def _link(game_id, source: MetadataSource, normalized: dict) -> list:
    return [
        GameExternalIdentity(game_id=game_id, source_id=source.id, external_id="ext"),
        MetadataRecord(
            source_id=source.id,
            external_id="ext",
            api_version="1",
            raw_payload={},
            normalized=normalized,
        ),
    ]


def _record(
    game_id, source: MetadataSource, external_id: str = "ext"
) -> tuple[GameExternalIdentity, MetadataRecord]:
    return (
        GameExternalIdentity(game_id=game_id, source_id=source.id, external_id=external_id),
        MetadataRecord(
            id=uuid4(),
            source_id=source.id,
            external_id=external_id,
            api_version="1",
            raw_payload={},
            normalized={},
        ),
    )


async def _seed(session: AsyncSession, *rows) -> None:
    # Flush per row: the unit of work does not order inserts across
    # mappers without relationship() directives.
    for row in rows:
        for item in row if isinstance(row, tuple) else (row,):
            session.add(item)
            await session.flush()
    await session.commit()


async def test_list_games_empty(client: AsyncClient):
    resp = await client.get("/api/v1/games")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "next_cursor": None}


async def test_list_games_orders_created_at_desc(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    t = datetime(2025, 1, 1)
    await _seed(
        db_session,
        lib,
        _game(lib.id, "alpha", "Alpha", created_at=t.replace(day=1)),
        _game(lib.id, "beta", "Beta", created_at=t.replace(day=2)),
        _game(lib.id, "gamma", "Gamma", created_at=t.replace(day=3)),
    )

    resp = await client.get("/api/v1/games")
    body = resp.json()
    assert resp.status_code == 200
    assert [item["slug"] for item in body["items"]] == ["gamma", "beta", "alpha"]


async def test_list_games_filter_by_library(db_session: AsyncSession, client: AsyncClient):
    lib1 = _library("lib1")
    lib2 = _library("lib2")
    await _seed(
        db_session,
        lib1,
        lib2,
        _game(lib1.id, "g1"),
        _game(lib2.id, "g2"),
    )

    resp = await client.get(f"/api/v1/games?library_id={lib1.id}")
    body = resp.json()
    assert [item["slug"] for item in body["items"]] == ["g1"]


async def test_list_games_pagination(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    t = datetime(2025, 1, 1)
    await _seed(
        db_session,
        lib,
        *[_game(lib.id, f"g{i}", created_at=t.replace(day=i + 1)) for i in range(3)],
    )

    resp = await client.get("/api/v1/games?limit=2")
    body = resp.json()
    assert [item["slug"] for item in body["items"]] == ["g2", "g1"]
    assert body["next_cursor"] is not None

    resp = await client.get(f"/api/v1/games?limit=2&cursor={body['next_cursor']}")
    body = resp.json()
    assert [item["slug"] for item in body["items"]] == ["g0"]
    assert body["next_cursor"] is None


async def test_create_game(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    await _seed(db_session, lib)

    resp = await client.post(
        "/api/v1/games",
        json={
            "library_id": str(lib.id),
            "slug": "doom",
            "title": "DOOM",
            "first_release_date": "1993-12-10",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["slug"] == "doom"
    assert body["title"] == "DOOM"
    assert body["first_release_date"] == "1993-12-10"
    assert body["library_id"] == str(lib.id)


async def test_create_game_slug_uniqueness_per_library(
    db_session: AsyncSession, client: AsyncClient
):
    lib1 = _library("lib1")
    lib2 = _library("lib2")
    await _seed(db_session, lib1, lib2)

    payload1 = {"library_id": str(lib1.id), "slug": "doom", "title": "DOOM"}
    assert (await client.post("/api/v1/games", json=payload1)).status_code == 201

    r2 = await client.post("/api/v1/games", json=payload1)
    assert r2.status_code == 409

    r3 = await client.post(
        "/api/v1/games",
        json={"library_id": str(lib2.id), "slug": "doom", "title": "DOOM"},
    )
    assert r3.status_code == 201


async def test_create_game_rejects_unknown_library(client: AsyncClient):
    resp = await client.post(
        "/api/v1/games",
        json={"library_id": str(uuid4()), "slug": "doom", "title": "DOOM"},
    )
    assert resp.status_code == 422


async def test_create_game_requires_title(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    await _seed(db_session, lib)

    resp = await client.post(
        "/api/v1/games",
        json={"library_id": str(lib.id), "slug": "doom"},
    )
    assert resp.status_code == 422


async def test_create_game_rejects_invalid_slug(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    await _seed(db_session, lib)

    resp = await client.post(
        "/api/v1/games",
        json={"library_id": str(lib.id), "slug": "Invalid Slug!", "title": "X"},
    )
    assert resp.status_code == 422


async def test_get_game(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom", "DOOM")
    await _seed(db_session, lib, (g, m))

    resp = await client.get(f"/api/v1/games/{g.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "doom"
    assert body["title"] == "DOOM"


async def test_get_game_not_found(client: AsyncClient):
    resp = await client.get(f"/api/v1/games/{uuid4()}")
    assert resp.status_code == 404


async def test_update_game(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom", "DOOM")
    await _seed(db_session, lib, (g, m))

    resp = await client.patch(
        f"/api/v1/games/{g.id}",
        json={"title": "DOOM (1993)", "description_short": "FPS classic"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "DOOM (1993)"
    assert body["description_short"] == "FPS classic"
    assert body["slug"] == "doom"  # immutable


async def test_update_game_null_clears_and_omission_keeps(
    db_session: AsyncSession, client: AsyncClient
):
    lib = _library()
    g, m = _game(lib.id, "doom", "DOOM")
    m.sort_title = "Doom, The"
    m.wrapper = WrapperKind.DOSBOX
    await _seed(db_session, lib, (g, m))

    # Omitted nullable scalars stay untouched...
    resp = await client.patch(f"/api/v1/games/{g.id}", json={"title": "DOOM II"})
    assert resp.status_code == 200
    assert resp.json()["sort_title"] == "Doom, The"
    assert resp.json()["wrapper"] == "dosbox"

    # ...while explicit null clears them (PATCH tri-state).
    resp = await client.patch(f"/api/v1/games/{g.id}", json={"sort_title": None, "wrapper": None})
    assert resp.status_code == 200
    assert resp.json()["sort_title"] is None
    assert resp.json()["wrapper"] is None


async def test_update_game_preferred_source(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom", "DOOM")
    source = MetadataSource(id=uuid4(), slug="acme", name="Acme", priority=1)
    await _seed(db_session, lib, source, (g, m))

    resp = await client.patch(
        f"/api/v1/games/{g.id}",
        json={"preferred_source_id": str(source.id)},
    )
    assert resp.status_code == 200
    assert resp.json()["preferred_source_id"] == str(source.id)


async def test_update_game_rejects_unknown_preferred_source(
    db_session: AsyncSession, client: AsyncClient
):
    lib = _library()
    g, m = _game(lib.id, "doom", "DOOM")
    await _seed(db_session, lib, (g, m))

    resp = await client.patch(
        f"/api/v1/games/{g.id}",
        json={"preferred_source_id": str(uuid4())},
    )
    assert resp.status_code == 422

    # Explicit null still clears.
    resp = await client.patch(f"/api/v1/games/{g.id}", json={"preferred_source_id": None})
    assert resp.status_code == 200
    assert resp.json()["preferred_source_id"] is None


async def test_update_game_rejects_slug_edit(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom", "DOOM")
    await _seed(db_session, lib, (g, m))

    resp = await client.patch(
        f"/api/v1/games/{g.id}",
        json={"title": "X", "slug": "new"},
    )
    assert resp.status_code == 422


async def test_update_game_rejects_null_title(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom", "DOOM")
    await _seed(db_session, lib, (g, m))

    resp = await client.patch(f"/api/v1/games/{g.id}", json={"title": None})
    assert resp.status_code == 422


async def test_update_game_not_found(client: AsyncClient):
    resp = await client.patch(f"/api/v1/games/{uuid4()}", json={"title": "X"})
    assert resp.status_code == 404


async def test_delete_game(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom", "DOOM")
    await _seed(db_session, lib, (g, m))

    resp = await client.delete(f"/api/v1/games/{g.id}")
    assert resp.status_code == 204

    follow = await client.get(f"/api/v1/games/{g.id}")
    assert follow.status_code == 404

    result = await db_session.execute(select(GameMetadata).where(GameMetadata.game_id == g.id))
    assert result.scalar_one_or_none() is None


async def test_delete_game_not_found(client: AsyncClient):
    resp = await client.delete(f"/api/v1/games/{uuid4()}")
    assert resp.status_code == 404


async def test_delete_game_files_options(db_session: AsyncSession, client: AsyncClient, settings):
    lib = _library()
    kept, kept_m = _game(lib.id, "doom", "DOOM")
    purged, purged_m = _game(lib.id, "quake", "QUAKE")
    erased, erased_m = _game(lib.id, "hexen", "HEXEN")
    await _seed(db_session, lib, (kept, kept_m), (purged, purged_m), (erased, erased_m))
    for game, filename in ((kept, "doom.iso"), (purged, "quake.iso"), (erased, "hexen.iso")):
        artifact = Artifact(
            game_id=game.id,
            kind=ArtifactKind.DISC,
            status=ArtifactStatus.STORED,
            total_size=4,
            name=filename,
        )
        db_session.add(artifact)
        await db_session.flush()
        db_session.add(
            File(
                artifact_id=artifact.id, relative_path=f"{lib.slug}/{game.slug}/{filename}", size=4
            )
        )
        directory = settings.library_dir / lib.slug / game.slug
        directory.mkdir(parents=True)
        (directory / filename).write_bytes(b"data")
    await db_session.commit()
    (settings.library_dir / lib.slug / "quake" / "notes.txt").write_text("untracked")

    # Default: the DB row goes, the files stay.
    assert (await client.delete(f"/api/v1/games/{kept.id}")).status_code == 204
    assert (settings.library_dir / lib.slug / "doom" / "doom.iso").read_bytes() == b"data"

    # delete_files removes tracked files only; untracked leftovers keep the directory.
    assert (await client.delete(f"/api/v1/games/{purged.id}?delete_files=true")).status_code == 204
    assert not (settings.library_dir / lib.slug / "quake" / "quake.iso").exists()
    assert (settings.library_dir / lib.slug / "quake" / "notes.txt").exists()

    # A fully-tracked directory is removed once emptied.
    assert (await client.delete(f"/api/v1/games/{erased.id}?delete_files=true")).status_code == 204
    assert not (settings.library_dir / lib.slug / "hexen").exists()


async def test_resolve_metadata(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom", "old title")
    src = _source("acme", priority=1)
    await _seed(
        db_session,
        lib,
        src,
        (g, m),
        *_link(g.id, src, {"title": "DOOM", "description_short": "fps"}),
    )

    resp = await client.post(f"/api/v1/games/{g.id}/resolve-metadata")
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "DOOM"
    assert body["description_short"] == "fps"
    assert body["resolved_at"] is not None


async def test_fetch_metadata_enqueues_and_guards_duplicates(
    db_session: AsyncSession, client: AsyncClient
):
    lib = _library()
    g, m = _game(lib.id, "doom", "DOOM")
    src = _source("acme", priority=1)
    await _seed(db_session, lib, src, (g, m), *_link(g.id, src, {"title": "DOOM"}))

    resp = await client.post(f"/api/v1/games/{g.id}/fetch-metadata")
    assert resp.status_code == 202
    job = await db_session.get(Job, UUID(resp.json()["job_id"]))
    assert job is not None
    assert job.kind == JobKind.FETCH_METADATA
    assert job.payload == {"game_id": str(g.id)}

    # While that job is pending, a second enqueue is rejected.
    resp = await client.post(f"/api/v1/games/{g.id}/fetch-metadata")
    assert resp.status_code == 409


async def test_fetch_metadata_requires_identity(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom", "DOOM")
    await _seed(db_session, lib, (g, m))

    resp = await client.post(f"/api/v1/games/{g.id}/fetch-metadata")
    assert resp.status_code == 409


async def test_fetch_metadata_game_not_found(client: AsyncClient):
    resp = await client.post(f"/api/v1/games/{uuid4()}/fetch-metadata")
    assert resp.status_code == 404


async def test_list_games_includes_cover_url(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom", "DOOM")
    g2, m2 = _game(lib.id, "quake", "Quake")
    await _seed(
        db_session,
        lib,
        (g, m),
        (g2, m2),
        AssetBlob(blake3="c" * 64, mime="image/png", size=1),
        AssetBlob(blake3="e" * 64, mime="image/png", size=1),
        GameAsset(game_id=g.id, kind=AssetKind.COVER, blob_blake3="c" * 64),
        GameAsset(game_id=g.id, kind=AssetKind.LANDSCAPE, blob_blake3="e" * 64),
    )

    resp = await client.get("/api/v1/games")
    by_slug = {item["slug"]: item for item in resp.json()["items"]}
    assert by_slug["doom"]["cover_url"] == f"/api/v1/assets/{'c' * 64}"
    assert by_slug["doom"]["landscape_url"] == f"/api/v1/assets/{'e' * 64}"
    assert by_slug["quake"]["cover_url"] is None
    assert by_slug["quake"]["landscape_url"] is None


async def test_get_game_assets(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom", "DOOM")
    blobs = [AssetBlob(blake3=digest * 64, mime="image/png", size=1) for digest in "abcd"]
    await _seed(
        db_session,
        lib,
        (g, m),
        *blobs,
        GameAsset(game_id=g.id, kind=AssetKind.COVER, blob_blake3="a" * 64),
        GameAsset(game_id=g.id, kind=AssetKind.SCREENSHOT, blob_blake3="b" * 64, ordinal=1),
        GameAsset(game_id=g.id, kind=AssetKind.SCREENSHOT, blob_blake3="c" * 64, ordinal=0),
        GameAsset(
            game_id=g.id, kind=AssetKind.SCREENSHOT, blob_blake3="d" * 64, ordinal=2, visible=False
        ),
    )

    resp = await client.get(f"/api/v1/games/{g.id}")
    body = resp.json()
    assert body["cover_url"] == f"/api/v1/assets/{'a' * 64}"
    # Visible screenshots in ordinal order; the hidden one is excluded.
    assert body["assets"]["screenshots"] == [
        f"/api/v1/assets/{'c' * 64}",
        f"/api/v1/assets/{'b' * 64}",
    ]


async def test_resolve_metadata_no_records(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom", "manual title")
    await _seed(db_session, lib, (g, m))

    resp = await client.post(f"/api/v1/games/{g.id}/resolve-metadata")
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "manual title"
    assert body["resolved_at"] is not None


async def test_resolve_metadata_not_found(client: AsyncClient):
    resp = await client.post(f"/api/v1/games/{uuid4()}/resolve-metadata")
    assert resp.status_code == 404


async def test_lock_field(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    await _seed(db_session, lib, (g, m))

    resp = await client.put(f"/api/v1/games/{g.id}/locks/title")
    assert resp.status_code == 204

    lock = await db_session.get(FieldLock, (g.id, FieldKey.TITLE))
    assert lock is not None


async def test_lock_field_idempotent(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    await _seed(db_session, lib, (g, m))

    assert (await client.put(f"/api/v1/games/{g.id}/locks/title")).status_code == 204
    assert (await client.put(f"/api/v1/games/{g.id}/locks/title")).status_code == 204

    result = await db_session.execute(
        select(FieldLock).where(FieldLock.game_id == g.id, FieldLock.field_key == FieldKey.TITLE)
    )
    assert len(result.scalars().all()) == 1


async def test_unlock_field(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    await _seed(db_session, lib, (g, m), FieldLock(game_id=g.id, field_key=FieldKey.TITLE))

    resp = await client.delete(f"/api/v1/games/{g.id}/locks/title")
    assert resp.status_code == 204

    assert await db_session.get(FieldLock, (g.id, FieldKey.TITLE)) is None


async def test_delete_game_cascades_owned_rows(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    await _seed(db_session, lib, (g, m), FieldLock(game_id=g.id, field_key=FieldKey.TITLE))

    resp = await client.delete(f"/api/v1/games/{g.id}")
    assert resp.status_code == 204

    assert (await client.get(f"/api/v1/games/{g.id}")).status_code == 404
    assert await db_session.get(FieldLock, (g.id, FieldKey.TITLE)) is None


async def test_get_game_includes_locks(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    await _seed(db_session, lib, (g, m))

    resp = await client.get(f"/api/v1/games/{g.id}")
    assert resp.json()["locks"] == []

    await client.put(f"/api/v1/games/{g.id}/locks/title")

    resp = await client.get(f"/api/v1/games/{g.id}")
    assert resp.json()["locks"] == ["title"]


async def test_unlock_field_idempotent_when_absent(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    await _seed(db_session, lib, (g, m))

    resp = await client.delete(f"/api/v1/games/{g.id}/locks/title")
    assert resp.status_code == 204


async def test_lock_field_rejects_invalid_key(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    await _seed(db_session, lib, (g, m))

    resp = await client.put(f"/api/v1/games/{g.id}/locks/not_a_field")
    assert resp.status_code == 422


async def test_lock_field_game_not_found(client: AsyncClient):
    resp = await client.put(f"/api/v1/games/{uuid4()}/locks/title")
    assert resp.status_code == 404


async def test_unlock_field_game_not_found(client: AsyncClient):
    resp = await client.delete(f"/api/v1/games/{uuid4()}/locks/title")
    assert resp.status_code == 404


async def test_get_game_detail_collections(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    src = _source("acme", priority=1)
    dev = Company(id=uuid4(), slug="id-software", name="id Software")
    pub = Company(id=uuid4(), slug="gt-interactive", name="GT Interactive")
    series = Series(id=uuid4(), slug="doom", name="Doom")
    genre = Tag(id=uuid4(), kind=TagKind.GENRE, slug="shooter", name="Shooter")
    mode = Tag(id=uuid4(), kind=TagKind.MODE, slug="single-player", name="Single player")
    # The lifespan seeded the PC platforms.
    windows = (
        await db_session.execute(select(Platform).where(Platform.slug == "windows"))
    ).scalar_one()
    await _seed(
        db_session,
        lib,
        src,
        (g, m),
        dev,
        pub,
        series,
        genre,
        mode,
        GameCompany(game_id=g.id, company_id=dev.id, role=CompanyRole.DEVELOPER),
        GameCompany(game_id=g.id, company_id=pub.id, role=CompanyRole.PUBLISHER),
        GameSeries(game_id=g.id, series_id=series.id),
        GameTag(game_id=g.id, tag_id=genre.id),
        GameTag(game_id=g.id, tag_id=mode.id),
        GamePlatform(game_id=g.id, platform_id=windows.id),
        GameReleaseDate(game_id=g.id, platform_id=windows.id, date=date(1993, 12, 10)),
        GameRating(
            game_id=g.id, authority=RatingAuthority.PEGI, value="16", descriptors=["Violence"]
        ),
        GameAltName(game_id=g.id, name="DOOM", comment=None),
        GameVideo(
            game_id=g.id, url="https://youtu.be/x", provider="youtube", video_id="x", name="T"
        ),
        GameSerial(game_id=g.id, value="DOOM-001", comment="big box"),
        GameExternalIdentity(game_id=g.id, source_id=src.id, external_id="42"),
    )

    body = (await client.get(f"/api/v1/games/{g.id}")).json()

    assert body["developers"] == [{"slug": "id-software", "name": "id Software"}]
    assert body["publishers"] == [{"slug": "gt-interactive", "name": "GT Interactive"}]
    assert body["series"] == [{"slug": "doom", "name": "Doom"}]
    assert body["genres"] == [{"slug": "shooter", "name": "Shooter"}]
    assert body["modes"] == [{"slug": "single-player", "name": "Single player"}]
    assert body["themes"] == [] and body["tags"] == [] and body["engines"] == []
    assert body["platforms"] == [{"slug": "windows", "name": "Windows", "family_slug": "pc"}]
    assert body["release_dates"] == [{"platform": "windows", "date": "1993-12-10"}]
    assert body["ratings"] == [{"authority": "pegi", "value": "16", "descriptors": ["Violence"]}]
    assert body["alt_names"] == [{"name": "DOOM", "comment": None}]
    assert body["videos"] == [
        {"provider": "youtube", "url": "https://youtu.be/x", "video_id": "x", "name": "T"}
    ]
    assert body["serials"] == [{"value": "DOOM-001", "comment": "big box"}]
    assert body["external_identities"] == [{"source_slug": "acme", "external_id": "42"}]


async def test_update_game_collections(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    await _seed(db_session, lib, (g, m))

    patch = {
        "developers": ["id Software"],
        "genres": ["Shooter", "FPS"],
        "platforms": ["windows", "linux"],
        "ratings": [{"authority": "esrb", "value": "M", "descriptors": ["Blood"]}],
        "release_dates": [{"platform": "windows", "date": "1993-12-10"}],
        "alt_names": [{"name": "DOOM"}],
        "videos": [{"provider": "youtube", "url": "https://youtu.be/x", "name": "Trailer"}],
        "serials": [{"value": "DOOM-001", "comment": "big box"}],
    }
    assert (await client.patch(f"/api/v1/games/{g.id}", json=patch)).status_code == 200

    body = (await client.get(f"/api/v1/games/{g.id}")).json()
    assert [d["name"] for d in body["developers"]] == ["id Software"]
    # Entity lists come back name-ordered; platforms slug-ordered.
    assert [x["name"] for x in body["genres"]] == ["FPS", "Shooter"]
    assert [p["slug"] for p in body["platforms"]] == ["linux", "windows"]
    assert body["ratings"] == [{"authority": "esrb", "value": "M", "descriptors": ["Blood"]}]
    assert body["release_dates"] == [{"platform": "windows", "date": "1993-12-10"}]
    assert body["alt_names"] == [{"name": "DOOM", "comment": None}]
    assert body["videos"][0]["url"] == "https://youtu.be/x"
    assert body["serials"] == [{"value": "DOOM-001", "comment": "big box"}]

    # Replace-array semantics: a shrunk list replaces, [] clears, omitted stays.
    resp = await client.patch(f"/api/v1/games/{g.id}", json={"genres": ["Shooter"], "serials": []})
    assert resp.status_code == 200
    body = (await client.get(f"/api/v1/games/{g.id}")).json()
    assert [x["name"] for x in body["genres"]] == ["Shooter"]
    assert body["serials"] == []
    assert [d["name"] for d in body["developers"]] == ["id Software"]


async def test_update_game_collections_validation(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    await _seed(db_session, lib, (g, m))

    cases = [
        {"genres": None},
        {"genres": ["!!!"]},
        {"platforms": ["amiga"]},
        {"platforms": ["windows", "windows"]},
        {"ratings": [{"authority": "pegi", "value": "12"}, {"authority": "pegi", "value": "16"}]},
        {"release_dates": [{"platform": "amiga", "date": "1990-01-01"}]},
        {"videos": [{"provider": "youtube"}]},
        {"serials": [{"value": "A"}, {"value": "A"}]},
    ]
    for case in cases:
        resp = await client.patch(f"/api/v1/games/{g.id}", json=case)
        assert resp.status_code == 422, case


async def test_set_and_remove_game_identity(db_session: AsyncSession, client: AsyncClient):
    lib = _library()
    g, m = _game(lib.id, "doom")
    await _seed(db_session, lib, (g, m))

    resp = await client.put(f"/api/v1/games/{g.id}/identities/igdb", json={"external_id": "77"})
    assert resp.status_code == 204
    detail = (await client.get(f"/api/v1/games/{g.id}")).json()
    assert detail["external_identities"] == [{"source_slug": "igdb", "external_id": "77"}]

    # An explicit user PUT replaces the mapping.
    resp = await client.put(f"/api/v1/games/{g.id}/identities/igdb", json={"external_id": "88"})
    assert resp.status_code == 204
    detail = (await client.get(f"/api/v1/games/{g.id}")).json()
    assert detail["external_identities"] == [{"source_slug": "igdb", "external_id": "88"}]

    assert (await client.delete(f"/api/v1/games/{g.id}/identities/igdb")).status_code == 204
    detail = (await client.get(f"/api/v1/games/{g.id}")).json()
    assert detail["external_identities"] == []
    # Idempotent delete.
    assert (await client.delete(f"/api/v1/games/{g.id}/identities/igdb")).status_code == 204

    put = client.put
    assert (
        await put(f"/api/v1/games/{uuid4()}/identities/igdb", json={"external_id": "1"})
    ).status_code == 404
    assert (
        await put(f"/api/v1/games/{g.id}/identities/nope", json={"external_id": "1"})
    ).status_code == 404
    assert (
        await put(f"/api/v1/games/{g.id}/identities/igdb", json={"external_id": ""})
    ).status_code == 422


async def test_update_game_moves_library(db_session: AsyncSession, client: AsyncClient):
    lib_a, lib_b = _library("alpha"), _library("beta")
    g, m = _game(lib_a.id, "doom")
    await _seed(db_session, lib_a, lib_b, (g, m))

    resp = await client.patch(f"/api/v1/games/{g.id}", json={"library_id": str(lib_b.id)})
    assert resp.status_code == 200
    assert resp.json()["library_id"] == str(lib_b.id)
    in_b = (await client.get(f"/api/v1/games?library_id={lib_b.id}")).json()["items"]
    assert [row["id"] for row in in_b] == [str(g.id)]


async def test_update_game_library_validation(db_session: AsyncSession, client: AsyncClient):
    lib_a, lib_b = _library("alpha"), _library("beta")
    g, m = _game(lib_a.id, "doom")
    taken, taken_m = _game(lib_b.id, "doom")
    await _seed(db_session, lib_a, lib_b, (g, m), (taken, taken_m))

    # Slug collision in the target library.
    resp = await client.patch(f"/api/v1/games/{g.id}", json={"library_id": str(lib_b.id)})
    assert resp.status_code == 409
    # Unknown library; explicit null.
    resp = await client.patch(f"/api/v1/games/{g.id}", json={"library_id": str(uuid4())})
    assert resp.status_code == 422
    resp = await client.patch(f"/api/v1/games/{g.id}", json={"library_id": None})
    assert resp.status_code == 422


async def test_get_game_file_signatures(db_session: AsyncSession, client: AsyncClient):
    from silo.models.artifact import Artifact, ArtifactKind, ArtifactStatus
    from silo.models.file import File
    from silo.models.identification import (
        IdentificationDataset,
        IdentificationSignature,
        IdentificationSource,
    )

    lib = _library()
    g, m = _game(lib.id, "doom")
    artifact = Artifact(
        id=uuid4(), game_id=g.id, kind=ArtifactKind.DISC, status=ArtifactStatus.STORED
    )
    file = File(id=uuid4(), artifact_id=artifact.id, md5="feedface")
    source_id = (
        await db_session.execute(
            select(IdentificationSource.id).where(IdentificationSource.slug == "redump")
        )
    ).scalar_one()
    dataset = IdentificationDataset(
        id=uuid4(), source_id=source_id, slug="redump-psx", name="PlayStation"
    )
    signature = IdentificationSignature(
        id=uuid4(),
        dataset_id=dataset.id,
        game_name="Doom (USA)",
        file_name="Doom (USA).bin",
        md5="feedface",
    )
    await _seed(db_session, lib, (g, m), artifact, file, dataset, signature)

    body = (await client.get(f"/api/v1/games/{g.id}")).json()

    [file_out] = body["artifacts"][0]["files"]
    assert file_out["matches"] == [
        {
            "signature_id": str(signature.id),
            "game_name": "Doom (USA)",
            "file_name": "Doom (USA).bin",
            "category": None,
            "dataset_name": "PlayStation",
            "source_slug": "redump",
        }
    ]
