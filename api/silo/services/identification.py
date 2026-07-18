import uuid

from sqlalchemy import Select, delete, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.base import utcnow
from silo.models.file import File
from silo.models.identification import (
    IdentificationDataset,
    IdentificationSignature,
    IdentificationSource,
)
from silo.schemas.identification import SignatureMatchOut
from silo.sources.redump import ParsedDat


def _match_stmt() -> Select:
    return (
        select(IdentificationSignature, IdentificationDataset.name, IdentificationSource.slug)
        .join(
            IdentificationDataset,
            IdentificationDataset.id == IdentificationSignature.dataset_id,
        )
        .join(IdentificationSource, IdentificationSource.id == IdentificationDataset.source_id)
        .where(
            IdentificationDataset.enabled.is_(True),
            IdentificationSource.enabled.is_(True),
        )
    )


def _to_match(
    signature: IdentificationSignature, dataset_name: str, source_slug: str
) -> SignatureMatchOut:
    return SignatureMatchOut(
        signature_id=signature.id,
        game_name=signature.game_name,
        file_name=signature.file_name,
        category=signature.category,
        dataset_name=dataset_name,
        source_slug=source_slug,
    )


async def match_hashes(
    session: AsyncSession,
    *,
    md5: str | None = None,
    sha1: str | None = None,
    sha256: str | None = None,
    crc32: str | None = None,
) -> list[SignatureMatchOut]:
    """Derived identification: signatures whose hash columns equal the file's."""
    clauses = []
    if md5:
        clauses.append(IdentificationSignature.md5 == md5.lower())
    if sha1:
        clauses.append(IdentificationSignature.sha1 == sha1.lower())
    if sha256:
        clauses.append(IdentificationSignature.sha256 == sha256.lower())
    if crc32:
        clauses.append(IdentificationSignature.crc32 == crc32.lower())
    if not clauses:
        return []
    rows = (await session.execute(_match_stmt().where(or_(*clauses)))).all()
    return [_to_match(signature, name, slug) for signature, name, slug in rows]


async def matches_for_files(
    session: AsyncSession, files: list[File]
) -> dict[uuid.UUID, list[SignatureMatchOut]]:
    """Per-file derived matches, one batched query."""
    hashed = [file for file in files if file.md5 or file.sha1 or file.sha256 or file.crc32]
    if not hashed:
        return {}
    clauses = []
    for attr, column in (
        ("md5", IdentificationSignature.md5),
        ("sha1", IdentificationSignature.sha1),
        ("sha256", IdentificationSignature.sha256),
        ("crc32", IdentificationSignature.crc32),
    ):
        values = {getattr(file, attr) for file in hashed if getattr(file, attr)}
        if values:
            clauses.append(column.in_(values))
    rows = (await session.execute(_match_stmt().where(or_(*clauses)))).all()
    matches: dict[uuid.UUID, list[SignatureMatchOut]] = {}
    for signature, dataset_name, source_slug in rows:
        for file in hashed:
            if (
                (file.md5 and file.md5 == signature.md5)
                or (file.sha1 and file.sha1 == signature.sha1)
                or (file.sha256 and file.sha256 == signature.sha256)
                or (file.crc32 and file.crc32 == signature.crc32)
            ):
                matches.setdefault(file.id, []).append(
                    _to_match(signature, dataset_name, source_slug)
                )
    return matches


async def import_signatures(session: AsyncSession, dataset_id: uuid.UUID, parsed: ParsedDat) -> int:
    """Replace a dataset's signatures from a parsed DAT; stamps version and refreshed_at."""
    # Signature ids are transient — nothing stores them across refreshes, so a
    # wholesale replace beats row-by-row reconciliation.
    await session.execute(
        delete(IdentificationSignature).where(IdentificationSignature.dataset_id == dataset_id)
    )
    seen: set[tuple[str, str]] = set()
    rows: list[dict[str, object]] = []
    for entry in parsed.entries:
        key = (entry.game_name, entry.file_name)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "id": uuid.uuid4(),
                "dataset_id": dataset_id,
                "game_name": entry.game_name,
                "file_name": entry.file_name,
                "category": entry.category,
                "md5": entry.md5,
                "sha1": entry.sha1,
                "sha256": None,
                "crc32": entry.crc32,
                "size": entry.size,
            }
        )
    if rows:
        await session.execute(insert(IdentificationSignature), rows)
    dataset = await session.get(IdentificationDataset, dataset_id)
    assert dataset is not None
    dataset.dataset_version = parsed.version
    dataset.refreshed_at = utcnow()
    return len(seen)
