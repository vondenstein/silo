from datetime import date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.asset import AssetBlob, AssetKind, SourceAsset
from silo.models.company import Company, CompanyExternalIdentity
from silo.models.field_lock import FieldKey, FieldLock
from silo.models.game import (
    CompanyRole,
    Game,
    GameAltName,
    GameAsset,
    GameCompany,
    GameExternalIdentity,
    GameMetadata,
    GameOrigin,
    GamePlatform,
    GameRating,
    GameReleaseDate,
    GameSeries,
    GameTag,
    GameType,
    GameVideo,
    RatingAuthority,
    WrapperKind,
)
from silo.models.library import Library
from silo.models.metadata_record import MetadataRecord
from silo.models.metadata_source import MetadataSource
from silo.models.platform import Platform
from silo.models.tag import Tag, TagKind
from silo.schemas.normalized_metadata import EntityRef
from silo.seed import seed_platforms
from silo.services.entities import resolve_tag_refs
from silo.services.game_collections import TAG_FIELDS
from silo.services.resolution import resolve_game_metadata
from tests.seed import seed_in_order


def _library() -> Library:
    now = datetime(2025, 1, 1)
    return Library(id=uuid4(), slug="main", name="Main", created_at=now, updated_at=now)


def _source(slug: str, priority: int) -> MetadataSource:
    return MetadataSource(id=uuid4(), slug=slug, name=slug.upper(), priority=priority)


def _game(library_id, *, origin=None, preferred_source_id=None, **metadata) -> Game:
    gid = uuid4()
    now = datetime(2025, 1, 1)
    game = Game(
        id=gid,
        library_id=library_id,
        slug="doom",
        origin=origin,
        preferred_source_id=preferred_source_id,
        created_at=now,
        updated_at=now,
    )
    game.game_metadata = GameMetadata(game_id=gid, **metadata)
    return game


def _link(game: Game, source: MetadataSource, normalized: dict, external_id: str = "ext") -> list:
    return [
        GameExternalIdentity(game_id=game.id, source_id=source.id, external_id=external_id),
        MetadataRecord(
            source_id=source.id,
            external_id=external_id,
            api_version="1",
            raw_payload={},
            normalized=normalized,
        ),
    ]


async def test_no_records_keeps_current_and_stamps(db_session: AsyncSession):
    lib = _library()
    game = _game(lib.id, title="current", description_full="keep")
    await seed_in_order(db_session, lib, game)

    await resolve_game_metadata(db_session, game)

    assert game.game_metadata.title == "current"
    assert game.game_metadata.description_full == "keep"
    assert game.game_metadata.resolved_at is not None


async def test_single_source_fills_fields(db_session: AsyncSession):
    lib = _library()
    src = _source("gog", priority=1)
    game = _game(lib.id, title="old")
    await seed_in_order(
        db_session, lib, src, game, *_link(game, src, {"title": "DOOM", "description_short": "fps"})
    )

    await resolve_game_metadata(db_session, game)

    assert game.game_metadata.title == "DOOM"
    assert game.game_metadata.description_short == "fps"


async def test_empty_value_does_not_overwrite(db_session: AsyncSession):
    lib = _library()
    src = _source("gog", priority=1)
    game = _game(lib.id, title="keep", description_full="keep full")
    await seed_in_order(
        db_session, lib, src, game, *_link(game, src, {"title": "", "description_short": "new"})
    )

    await resolve_game_metadata(db_session, game)

    assert game.game_metadata.title == "keep"
    assert game.game_metadata.description_full == "keep full"
    assert game.game_metadata.description_short == "new"


async def test_preferred_source_wins_over_priority(db_session: AsyncSession):
    lib = _library()
    gog = _source("gog", priority=5)
    igdb = _source("igdb", priority=1)
    game = _game(lib.id, origin=GameOrigin.GOG_IMPORT, title="x")
    await seed_in_order(
        db_session,
        lib,
        gog,
        igdb,
        game,
        *_link(game, gog, {"title": "GOG"}),
        *_link(game, igdb, {"title": "IGDB"}),
    )

    await resolve_game_metadata(db_session, game)

    assert game.game_metadata.title == "GOG"


async def test_priority_fallback_when_preferred_lacks_field(db_session: AsyncSession):
    lib = _library()
    gog = _source("gog", priority=5)
    igdb = _source("igdb", priority=1)
    game = _game(lib.id, origin=GameOrigin.GOG_IMPORT, title="x")
    await seed_in_order(
        db_session,
        lib,
        gog,
        igdb,
        game,
        *_link(game, gog, {"title": "GOG"}),
        *_link(game, igdb, {"title": "IGDB", "description_short": "from igdb"}),
    )

    await resolve_game_metadata(db_session, game)

    assert game.game_metadata.title == "GOG"
    assert game.game_metadata.description_short == "from igdb"


async def test_priority_order_without_preferred(db_session: AsyncSession):
    lib = _library()
    a = _source("a", priority=1)
    b = _source("b", priority=2)
    game = _game(lib.id, title="x")
    await seed_in_order(
        db_session,
        lib,
        a,
        b,
        game,
        *_link(game, a, {"title": "A"}),
        *_link(game, b, {"title": "B"}),
    )

    await resolve_game_metadata(db_session, game)

    assert game.game_metadata.title == "A"


async def test_per_game_override_beats_origin_default(db_session: AsyncSession):
    lib = _library()
    gog = _source("gog", priority=1)
    steam = _source("steam", priority=5)
    game = _game(lib.id, origin=GameOrigin.GOG_IMPORT, preferred_source_id=steam.id, title="x")
    await seed_in_order(
        db_session,
        lib,
        gog,
        steam,
        game,
        *_link(game, gog, {"title": "GOG"}),
        *_link(game, steam, {"title": "Steam"}),
    )

    await resolve_game_metadata(db_session, game)

    assert game.game_metadata.title == "Steam"


async def test_lock_skips_field(db_session: AsyncSession):
    lib = _library()
    src = _source("gog", priority=1)
    game = _game(lib.id, title="locked")
    await seed_in_order(
        db_session,
        lib,
        src,
        game,
        FieldLock(game_id=game.id, field_key=FieldKey.TITLE),
        *_link(game, src, {"title": "new", "description_short": "fresh"}),
    )

    await resolve_game_metadata(db_session, game)

    assert game.game_metadata.title == "locked"
    assert game.game_metadata.description_short == "fresh"


async def test_coerces_date_and_enums(db_session: AsyncSession):
    lib = _library()
    src = _source("gog", priority=1)
    game = _game(lib.id, title="x")
    await seed_in_order(
        db_session,
        lib,
        src,
        game,
        *_link(
            game,
            src,
            {"first_release_date": "1993-12-10", "wrapper": "dosbox", "game_type": "main"},
        ),
    )

    await resolve_game_metadata(db_session, game)

    assert game.game_metadata.first_release_date == date(1993, 12, 10)
    assert game.game_metadata.wrapper == WrapperKind.DOSBOX
    assert game.game_metadata.game_type == GameType.MAIN


def _identified_record(
    game: Game, source: MetadataSource, external_id: str = "ext"
) -> tuple[GameExternalIdentity, MetadataRecord]:
    return (
        GameExternalIdentity(game_id=game.id, source_id=source.id, external_id=external_id),
        MetadataRecord(
            id=uuid4(),
            source_id=source.id,
            external_id=external_id,
            api_version="1",
            raw_payload={},
            normalized={},
        ),
    )


def _asset(record: MetadataRecord, kind: AssetKind, digest: str, ordinal: int = 0) -> list:
    return [
        AssetBlob(blake3=digest, mime="image/jpeg", size=1),
        SourceAsset(metadata_record_id=record.id, kind=kind, blob_blake3=digest, ordinal=ordinal),
    ]


async def _game_assets(session: AsyncSession, game: Game) -> list[GameAsset]:
    rows = (await session.execute(select(GameAsset).where(GameAsset.game_id == game.id))).scalars()
    return sorted(rows, key=lambda a: (list(AssetKind).index(a.kind), a.ordinal))


async def test_assets_preferred_source_wins(db_session: AsyncSession):
    lib = _library()
    gog = _source("gog", priority=5)
    alpha = _source("alpha", priority=1)
    game = _game(lib.id, origin=GameOrigin.GOG_IMPORT, title="x")
    gog_identity, gog_record = _identified_record(game, gog)
    alpha_identity, alpha_record = _identified_record(game, alpha)
    await seed_in_order(
        db_session,
        lib,
        gog,
        alpha,
        game,
        gog_identity,
        gog_record,
        alpha_identity,
        alpha_record,
        *_asset(gog_record, AssetKind.COVER, "cover-gog"),
        *_asset(alpha_record, AssetKind.COVER, "cover-alpha"),
    )

    await resolve_game_metadata(db_session, game)

    assets = await _game_assets(db_session, game)
    assert [(a.kind, a.blob_blake3, a.visible) for a in assets] == [
        (AssetKind.COVER, "cover-gog", True)
    ]


async def test_assets_fall_back_by_priority(db_session: AsyncSession):
    lib = _library()
    gog = _source("gog", priority=5)
    alpha = _source("alpha", priority=2)
    beta = _source("beta", priority=1)
    game = _game(lib.id, origin=GameOrigin.GOG_IMPORT, title="x")
    gog_identity, gog_record = _identified_record(game, gog)
    alpha_identity, alpha_record = _identified_record(game, alpha)
    beta_identity, beta_record = _identified_record(game, beta)
    await seed_in_order(
        db_session,
        lib,
        gog,
        alpha,
        beta,
        game,
        gog_identity,
        gog_record,
        alpha_identity,
        alpha_record,
        beta_identity,
        beta_record,
        *_asset(gog_record, AssetKind.COVER, "cover-gog"),
        *_asset(alpha_record, AssetKind.SCREENSHOT, "shot-alpha"),
        *_asset(beta_record, AssetKind.SCREENSHOT, "shot-beta"),
    )

    await resolve_game_metadata(db_session, game)

    assets = await _game_assets(db_session, game)
    # The preferred source keeps the kinds it has; missing kinds fall back by priority.
    assert [(a.kind, a.blob_blake3) for a in assets] == [
        (AssetKind.COVER, "cover-gog"),
        (AssetKind.SCREENSHOT, "shot-beta"),
    ]


async def test_assets_keep_order_and_never_delete(db_session: AsyncSession):
    lib = _library()
    gog = _source("gog", priority=1)
    game = _game(lib.id, origin=GameOrigin.GOG_IMPORT, title="x")
    gog_identity, gog_record = _identified_record(game, gog)
    await seed_in_order(
        db_session,
        lib,
        gog,
        game,
        gog_identity,
        gog_record,
        *_asset(gog_record, AssetKind.SCREENSHOT, "shot-1", ordinal=0),
        *_asset(gog_record, AssetKind.SCREENSHOT, "shot-2", ordinal=1),
        # A pre-existing pick (e.g. user-chosen) survives re-resolution untouched.
        AssetBlob(blake3="user-cover", mime="image/png", size=1),
        GameAsset(game_id=game.id, kind=AssetKind.COVER, blob_blake3="user-cover", visible=False),
    )

    await resolve_game_metadata(db_session, game)
    await resolve_game_metadata(db_session, game)

    assets = await _game_assets(db_session, game)
    assert [(a.kind, a.blob_blake3, a.ordinal, a.visible) for a in assets] == [
        (AssetKind.COVER, "user-cover", 0, False),
        (AssetKind.SCREENSHOT, "shot-1", 0, True),
        (AssetKind.SCREENSHOT, "shot-2", 1, True),
    ]


async def test_assets_winner_switch_demotes_old_picks(db_session: AsyncSession):
    lib = _library()
    gog = _source("gog", priority=5)
    alpha = _source("alpha", priority=1)
    game = _game(lib.id, origin=GameOrigin.GOG_IMPORT, title="x")
    gog_identity, gog_record = _identified_record(game, gog)
    alpha_identity, alpha_record = _identified_record(game, alpha)
    await seed_in_order(
        db_session,
        lib,
        gog,
        alpha,
        game,
        gog_identity,
        gog_record,
        alpha_identity,
        alpha_record,
        *_asset(gog_record, AssetKind.LANDSCAPE, "land-gog"),
        *_asset(alpha_record, AssetKind.LANDSCAPE, "land-alpha"),
        # A previous resolve materialized the non-preferred source's pick.
        GameAsset(game_id=game.id, kind=AssetKind.LANDSCAPE, blob_blake3="land-alpha"),
    )

    await resolve_game_metadata(db_session, game)

    assets = await _game_assets(db_session, game)
    assert {(a.kind, a.blob_blake3, a.visible) for a in assets} == {
        (AssetKind.LANDSCAPE, "land-gog", True),
        (AssetKind.LANDSCAPE, "land-alpha", False),
    }


async def test_assets_locked_kind_untouched(db_session: AsyncSession):
    lib = _library()
    gog = _source("gog", priority=5)
    alpha = _source("alpha", priority=1)
    game = _game(lib.id, origin=GameOrigin.GOG_IMPORT, title="x")
    gog_identity, gog_record = _identified_record(game, gog)
    alpha_identity, alpha_record = _identified_record(game, alpha)
    await seed_in_order(
        db_session,
        lib,
        gog,
        alpha,
        game,
        gog_identity,
        gog_record,
        alpha_identity,
        alpha_record,
        *_asset(gog_record, AssetKind.COVER, "cover-gog"),
        *_asset(alpha_record, AssetKind.COVER, "cover-alpha"),
        *_asset(gog_record, AssetKind.SCREENSHOT, "shot-gog"),
        FieldLock(game_id=game.id, field_key=FieldKey.COVER),
        # The user's pick: the non-preferred source's cover, kept visible.
        GameAsset(game_id=game.id, kind=AssetKind.COVER, blob_blake3="cover-alpha"),
    )

    await resolve_game_metadata(db_session, game)

    assets = await _game_assets(db_session, game)
    # Locked kind: no winner materialized, the pick stays; unlocked kinds proceed.
    assert [(a.kind, a.blob_blake3, a.visible) for a in assets] == [
        (AssetKind.COVER, "cover-alpha", True),
        (AssetKind.SCREENSHOT, "shot-gog", True),
    ]


async def test_assets_singleton_kind_ranks_by_resolution(db_session: AsyncSession):
    lib = _library()
    gog = _source("gog", priority=1)
    game = _game(lib.id, origin=GameOrigin.GOG_IMPORT, title="x")
    gog_identity, gog_record = _identified_record(game, gog)
    await seed_in_order(
        db_session,
        lib,
        gog,
        game,
        gog_identity,
        gog_record,
        # Source order says small first — resolution should rank the large one to 0.
        AssetBlob(blake3="cover-small", mime="image/jpeg", size=1, width=100, height=100),
        AssetBlob(blake3="cover-large", mime="image/png", size=1, width=800, height=600),
        SourceAsset(
            metadata_record_id=gog_record.id,
            kind=AssetKind.COVER,
            blob_blake3="cover-small",
            ordinal=0,
        ),
        SourceAsset(
            metadata_record_id=gog_record.id,
            kind=AssetKind.COVER,
            blob_blake3="cover-large",
            ordinal=1,
        ),
        # Screenshots keep the source's narrative order regardless of size.
        AssetBlob(blake3="shot-a", mime="image/jpeg", size=1, width=100, height=100),
        AssetBlob(blake3="shot-b", mime="image/jpeg", size=1, width=1920, height=1080),
        SourceAsset(
            metadata_record_id=gog_record.id,
            kind=AssetKind.SCREENSHOT,
            blob_blake3="shot-a",
            ordinal=0,
        ),
        SourceAsset(
            metadata_record_id=gog_record.id,
            kind=AssetKind.SCREENSHOT,
            blob_blake3="shot-b",
            ordinal=1,
        ),
    )

    await resolve_game_metadata(db_session, game)

    assets = await _game_assets(db_session, game)
    assert [(a.kind, a.blob_blake3, a.ordinal) for a in assets] == [
        (AssetKind.COVER, "cover-large", 0),
        (AssetKind.COVER, "cover-small", 1),
        (AssetKind.SCREENSHOT, "shot-a", 0),
        (AssetKind.SCREENSHOT, "shot-b", 1),
    ]


async def _tag_names(session: AsyncSession, game: Game, kind: TagKind) -> list[str]:
    return list(
        await session.scalars(
            select(Tag.name)
            .join(GameTag, GameTag.tag_id == Tag.id)
            .where(GameTag.game_id == game.id, Tag.kind == kind)
            .order_by(Tag.name)
        )
    )


async def test_collections_winner_set_and_union(db_session: AsyncSession):
    lib = _library()
    gog = _source("gog", priority=5)
    alpha = _source("alpha", priority=1)
    game = _game(lib.id, origin=GameOrigin.GOG_IMPORT, title="x")
    await seed_platforms(db_session)
    await seed_in_order(
        db_session,
        lib,
        gog,
        alpha,
        game,
        *_link(
            game,
            gog,
            {
                "developers": [{"name": "Triumph Studios", "uid": "g-dev"}],
                "genres": [{"name": "Strategy"}],
                "platforms": ["windows"],
                "alt_names": [{"name": "AoW", "comment": "Acronym"}],
                "videos": [{"provider": "youtube", "url": "https://youtu.be/x", "name": "Trailer"}],
                "ratings": [{"authority": "pegi", "value": "12"}],
                "release_dates": [{"platform": "windows", "date": "1999-11-11"}],
            },
        ),
        *_link(
            game,
            alpha,
            {
                "developers": [{"name": "Someone Else"}],
                "genres": [{"name": "Role-playing (RPG)"}],
                "themes": [{"name": "Fantasy"}],
                "platforms": ["linux"],
                "ratings": [
                    {"authority": "pegi", "value": "16"},
                    {"authority": "esrb", "value": "E", "descriptors": ["Mild Violence"]},
                ],
                "release_dates": [
                    {"platform": "windows", "date": "2000-01-01"},
                    {"platform": "linux", "date": "2010-12-31"},
                ],
            },
        ),
    )

    await resolve_game_metadata(db_session, game)
    # Idempotent on re-run.
    await resolve_game_metadata(db_session, game)

    # Set-collections: the preferred source's set wins wholesale...
    developers = list(
        await db_session.scalars(
            select(Company.name)
            .join(GameCompany, GameCompany.company_id == Company.id)
            .where(GameCompany.game_id == game.id, GameCompany.role == CompanyRole.DEVELOPER)
        )
    )
    assert developers == ["Triumph Studios"]
    assert await _tag_names(db_session, game, TagKind.GENRE) == ["Strategy"]
    # ...and priority fallback fills fields the preferred source lacks.
    assert await _tag_names(db_session, game, TagKind.THEME) == ["Fantasy"]
    platforms = list(
        await db_session.scalars(
            select(Platform.slug)
            .join(GamePlatform, GamePlatform.platform_id == Platform.id)
            .where(GamePlatform.game_id == game.id)
        )
    )
    # Winner set, not a union — alpha's linux view loses to the preferred source.
    assert platforms == ["windows"]
    # The uid rode along as an entity identity (D14).
    identity = (await db_session.scalars(select(CompanyExternalIdentity))).one()
    assert (identity.source_id, identity.external_id) == (gog.id, "g-dev")

    # Keyed collections union by key; the preferred source breaks same-key conflicts.
    ratings = {
        (row.authority, row.value)
        for row in await db_session.scalars(select(GameRating).where(GameRating.game_id == game.id))
    }
    assert ratings == {(RatingAuthority.PEGI, "12"), (RatingAuthority.ESRB, "E")}
    dates = {
        (row.platform_id, row.date)
        for row in await db_session.scalars(
            select(GameReleaseDate).where(GameReleaseDate.game_id == game.id)
        )
    }
    by_slug = {
        platform.slug: platform.id for platform in await db_session.scalars(select(Platform))
    }
    assert dates == {
        (by_slug["windows"], date(1999, 11, 11)),
        (by_slug["linux"], date(2010, 12, 31)),
    }

    alt = (
        await db_session.scalars(select(GameAltName).where(GameAltName.game_id == game.id))
    ).one()
    assert (alt.name, alt.comment) == ("AoW", "Acronym")
    video = (await db_session.scalars(select(GameVideo).where(GameVideo.game_id == game.id))).one()
    assert (video.provider, video.url, video.name) == ("youtube", "https://youtu.be/x", "Trailer")


async def test_platform_corners_dedupe_and_keep_current(db_session: AsyncSession):
    lib = _library()
    src = _source("gog", priority=1)
    game = _game(lib.id, origin=GameOrigin.GOG_IMPORT, title="x")
    await seed_platforms(db_session)
    await seed_in_order(
        db_session,
        lib,
        src,
        game,
        *_link(
            game,
            src,
            {
                "platforms": ["windows", "windows"],
                "release_dates": [{"platform": "windows", "date": "1999-11-11"}],
            },
        ),
    )
    await resolve_game_metadata(db_session, game)
    await db_session.commit()

    # Duplicate slugs dedupe to one row.
    platforms = list(
        await db_session.scalars(select(GamePlatform).where(GamePlatform.game_id == game.id))
    )
    assert len(platforms) == 1

    # A record whose slugs are all unseeded must not read as "clear" (R6).
    record = (await db_session.scalars(select(MetadataRecord))).one()
    record.normalized = {
        "platforms": ["amiga"],
        "release_dates": [{"platform": "amiga", "date": "2001-01-01"}],
    }
    await db_session.commit()
    await resolve_game_metadata(db_session, game)

    platforms = list(
        await db_session.scalars(select(GamePlatform).where(GamePlatform.game_id == game.id))
    )
    assert len(platforms) == 1
    dates = list(
        await db_session.scalars(select(GameReleaseDate).where(GameReleaseDate.game_id == game.id))
    )
    assert len(dates) == 1


async def test_collections_replace_and_lock(db_session: AsyncSession):
    lib = _library()
    src = _source("gog", priority=1)
    game = _game(lib.id, origin=GameOrigin.GOG_IMPORT, title="x")
    await seed_in_order(
        db_session,
        lib,
        src,
        game,
        *_link(game, src, {"genres": [{"name": "Strategy"}], "tags": [{"name": "Isometric"}]}),
    )
    await resolve_game_metadata(db_session, game)

    # An unlocked user addition is steamrolled by the next resolve.
    [user_tag] = await resolve_tag_refs(
        db_session, [EntityRef(name="Boomer Shooter")], src.id, TagKind.GENRE
    )
    # Flush the ladder's new tag before referencing it (prod gets this
    # ordering from autoflush on the setters' queries).
    await db_session.flush()
    db_session.add(GameTag(game_id=game.id, tag_id=user_tag))
    await db_session.commit()
    await resolve_game_metadata(db_session, game)
    assert await _tag_names(db_session, game, TagKind.GENRE) == ["Strategy"]

    # Locked, the user's set survives; other kinds still resolve.
    db_session.add(GameTag(game_id=game.id, tag_id=user_tag))
    db_session.add(FieldLock(game_id=game.id, field_key=FieldKey.GENRES))
    await db_session.commit()
    await resolve_game_metadata(db_session, game)
    assert await _tag_names(db_session, game, TagKind.GENRE) == ["Boomer Shooter", "Strategy"]
    assert await _tag_names(db_session, game, TagKind.TAG) == ["Isometric"]


async def test_collections_keep_current_when_sources_lack_field(db_session: AsyncSession):
    lib = _library()
    src = _source("gog", priority=1)
    game = _game(lib.id, origin=GameOrigin.GOG_IMPORT, title="x")
    await seed_in_order(db_session, lib, src, game, *_link(game, src, {"title": "T"}))
    [user_tag] = await resolve_tag_refs(
        db_session, [EntityRef(name="Boomer Shooter")], src.id, TagKind.GENRE
    )
    # Flush the ladder's new tag before referencing it (prod gets this
    # ordering from autoflush on the setters' queries).
    await db_session.flush()
    db_session.add(GameTag(game_id=game.id, tag_id=user_tag))
    await db_session.commit()

    await resolve_game_metadata(db_session, game)

    # R6: no source competes for genres — manual data survives without a lock.
    assert await _tag_names(db_session, game, TagKind.GENRE) == ["Boomer Shooter"]


async def test_videos_unusable_winner_falls_through(db_session: AsyncSession):
    lib = _library()
    gog = _source("gog", priority=5)
    alpha = _source("alpha", priority=1)
    game = _game(lib.id, origin=GameOrigin.GOG_IMPORT, title="x")
    await seed_in_order(
        db_session,
        lib,
        gog,
        alpha,
        game,
        # The preferred source's videos are all url-less — unusable, so the
        # lower-priority url-ful set must win.
        *_link(game, gog, {"videos": [{"provider": "gog", "video_id": "123"}]}),
        *_link(game, alpha, {"videos": [{"provider": "youtube", "url": "https://youtu.be/x"}]}),
    )

    await resolve_game_metadata(db_session, game)

    urls = list(await db_session.scalars(select(GameVideo.url).where(GameVideo.game_id == game.id)))
    assert urls == ["https://youtu.be/x"]


async def test_videos_all_unusable_keeps_current(db_session: AsyncSession):
    lib = _library()
    src = _source("gog", priority=1)
    game = _game(lib.id, origin=GameOrigin.GOG_IMPORT, title="x")
    await seed_in_order(
        db_session,
        lib,
        src,
        game,
        GameVideo(game_id=game.id, url="https://youtu.be/keep", provider="youtube"),
        *_link(game, src, {"videos": [{"provider": "gog", "video_id": "123"}]}),
    )

    await resolve_game_metadata(db_session, game)

    # R6: no source has a usable set — current rows survive.
    urls = list(await db_session.scalars(select(GameVideo.url).where(GameVideo.game_id == game.id)))
    assert urls == ["https://youtu.be/keep"]


_COLLECTION_PAYLOAD = {
    "developers": [{"name": "Dev Co"}],
    "publishers": [{"name": "Pub Co"}],
    "series": [{"name": "Saga"}],
    "genres": [{"name": "RPG"}],
    "themes": [{"name": "Fantasy"}],
    "tags": [{"name": "Isometric"}],
    "engines": [{"name": "Unity"}],
    "modes": [{"name": "Single player"}],
    "platforms": ["windows"],
    "alt_names": [{"name": "Alt Name"}],
    "videos": [{"provider": "youtube", "url": "https://youtu.be/x"}],
    "ratings": [{"authority": "pegi", "value": "18"}],
    "release_dates": [{"platform": "windows", "date": "2020-01-01"}],
}


async def _collection_rows(session: AsyncSession, game_id, field: str) -> int:
    if field in ("developers", "publishers"):
        role = CompanyRole.DEVELOPER if field == "developers" else CompanyRole.PUBLISHER
        stmt = select(GameCompany).where(GameCompany.game_id == game_id, GameCompany.role == role)
    elif field == "series":
        stmt = select(GameSeries).where(GameSeries.game_id == game_id)
    elif field in TAG_FIELDS:
        stmt = (
            select(GameTag)
            .join(Tag, Tag.id == GameTag.tag_id)
            .where(GameTag.game_id == game_id, Tag.kind == TAG_FIELDS[field])
        )
    elif field == "platforms":
        stmt = select(GamePlatform).where(GamePlatform.game_id == game_id)
    elif field == "alt_names":
        stmt = select(GameAltName).where(GameAltName.game_id == game_id)
    elif field == "videos":
        stmt = select(GameVideo).where(GameVideo.game_id == game_id)
    elif field == "ratings":
        stmt = select(GameRating).where(GameRating.game_id == game_id)
    else:
        stmt = select(GameReleaseDate).where(GameReleaseDate.game_id == game_id)
    return len(list(await session.scalars(stmt)))


# One lock per collection field: a transposed FieldKey in any guard would
# write the locked field anyway (only GENRES was pinned before).
@pytest.mark.parametrize("field", sorted(_COLLECTION_PAYLOAD))
async def test_each_collection_lock_blocks_only_its_field(db_session: AsyncSession, field: str):
    lib = _library()
    source = _source("gog", 10)
    game = _game(lib.id, title="current")
    await seed_platforms(db_session)
    await seed_in_order(
        db_session,
        lib,
        source,
        game,
        *_link(game, source, _COLLECTION_PAYLOAD),
        FieldLock(game_id=game.id, field_key=FieldKey(field)),
    )

    await resolve_game_metadata(db_session, game)
    await db_session.commit()

    assert await _collection_rows(db_session, game.id, field) == 0
    # Sanity: an unlocked sibling landed in the same resolve.
    sibling = "themes" if field == "genres" else "genres"
    assert await _collection_rows(db_session, game.id, sibling) > 0
