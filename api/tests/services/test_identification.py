from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.artifact import Artifact, ArtifactKind, ArtifactStatus
from silo.models.file import File
from silo.models.game import Game, GameMetadata
from silo.models.identification import (
    IdentificationDataset,
    IdentificationSignature,
    IdentificationSource,
)
from silo.models.library import Library
from silo.services.identification import import_signatures, match_hashes, matches_for_files
from silo.sources.redump import DatEntry, ParsedDat
from tests.seed import seed_in_order


async def _dataset(
    session: AsyncSession, *, source_enabled: bool = True, dataset_enabled: bool = True
) -> IdentificationDataset:
    source = IdentificationSource(id=uuid4(), slug=f"src-{uuid4().hex[:8]}", name="Redump")
    source.enabled = source_enabled
    dataset = IdentificationDataset(
        id=uuid4(),
        source_id=source.id,
        slug=f"redump-{uuid4().hex[:8]}",
        name="PlayStation",
        enabled=dataset_enabled,
    )
    session.add(source)
    await session.flush()
    session.add(dataset)
    await session.flush()
    return dataset


def _signature(dataset: IdentificationDataset, **kwargs) -> IdentificationSignature:
    defaults = {
        "id": uuid4(),
        "dataset_id": dataset.id,
        "game_name": "Doom (USA)",
        "file_name": "Doom (USA).bin",
        "category": "Games",
    }
    return IdentificationSignature(**{**defaults, **kwargs})


async def test_match_hashes_or_semantics_and_display_fields(db_session: AsyncSession):
    dataset = await _dataset(db_session)
    db_session.add(_signature(dataset, md5="aa", sha1="bb"))
    await db_session.commit()

    by_md5 = await match_hashes(db_session, md5="AA")
    by_sha1 = await match_hashes(db_session, sha1="bb")
    miss = await match_hashes(db_session, md5="zz", sha1="zz", crc32="zz")

    assert len(by_md5) == 1
    assert by_md5[0].game_name == "Doom (USA)"
    assert by_md5[0].dataset_name == "PlayStation"
    assert by_md5[0].source_slug.startswith("src-")
    assert by_sha1[0].signature_id == by_md5[0].signature_id
    assert miss == []
    assert await match_hashes(db_session) == []


async def test_match_hashes_respects_enabled_flags(db_session: AsyncSession):
    disabled_dataset = await _dataset(db_session, dataset_enabled=False)
    db_session.add(_signature(disabled_dataset, md5="aa"))
    disabled_source = await _dataset(db_session, source_enabled=False)
    db_session.add(_signature(disabled_source, md5="aa"))
    await db_session.commit()

    assert await match_hashes(db_session, md5="aa") == []


async def test_matches_for_files_batches_per_file(db_session: AsyncSession):
    now = datetime(2025, 1, 1)
    library = Library(id=uuid4(), slug="main", name="Main", created_at=now, updated_at=now)
    game = Game(id=uuid4(), library_id=library.id, slug="doom", created_at=now, updated_at=now)
    metadata = GameMetadata(game_id=game.id, title="DOOM")
    artifact = Artifact(
        id=uuid4(), game_id=game.id, kind=ArtifactKind.DISC, status=ArtifactStatus.STORED
    )
    matched = File(id=uuid4(), artifact_id=artifact.id, md5="aa")
    unmatched = File(id=uuid4(), artifact_id=artifact.id, md5="zz")
    bare = File(id=uuid4(), artifact_id=artifact.id)
    dataset = await _dataset(db_session)
    await seed_in_order(
        db_session,
        library,
        game,
        metadata,
        artifact,
        matched,
        unmatched,
        bare,
        _signature(dataset, md5="aa"),
    )

    matches = await matches_for_files(db_session, [matched, unmatched, bare])

    assert set(matches) == {matched.id}
    assert matches[matched.id][0].file_name == "Doom (USA).bin"


async def test_import_signatures_dedupes_within_dat(db_session: AsyncSession):
    # Redump DATs can repeat (game_name, file_name); without the dedupe the
    # bulk insert IntegrityErrors and takes the whole refresh job down.
    dataset = await _dataset(db_session)
    await db_session.commit()
    entry = DatEntry(
        game_name="Doom (USA)",
        file_name="Doom (USA).bin",
        category="Games",
        size=1000,
        md5="a1",
        sha1="b2",
        crc32="c3",
    )
    duplicate = entry._replace(md5="ff")
    other = entry._replace(file_name="Doom (USA).cue")

    count = await import_signatures(
        db_session, dataset.id, ParsedDat(version="v1", entries=[entry, duplicate, other])
    )
    await db_session.commit()

    assert count == 2
    rows = list(
        await db_session.scalars(
            select(IdentificationSignature).where(IdentificationSignature.dataset_id == dataset.id)
        )
    )
    assert len(rows) == 2
    # First entry wins the key.
    kept = next(row for row in rows if row.file_name == "Doom (USA).bin")
    assert kept.md5 == "a1"
