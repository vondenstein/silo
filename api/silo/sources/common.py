import nh3
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from silo.models.metadata_source import MetadataSource

# Matches what the frontend Description component styles.
ALLOWED_TAGS = {"p", "br", "a", "ul", "ol", "li", "h3", "h4", "strong", "em", "b", "i"}
ALLOWED_ATTRIBUTES = {"a": {"href"}}


async def request_interval(session: AsyncSession, slug: str, default_ms: int) -> int:
    """The registry row's request_interval_ms, or the adapter's default when null."""
    interval = await session.scalar(
        select(MetadataSource.request_interval_ms).where(MetadataSource.slug == slug)
    )
    return default_ms if interval is None else interval


def clean_description(html: str) -> str:
    """Sanitize a source description to the frontend-styled allowlist."""
    return nh3.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)


def entity_ref(name: str, uid: object | None = None) -> dict[str, str]:
    """{name, uid?} — uid is the source's stable entity id."""
    return {"name": name, "uid": str(uid)} if uid is not None else {"name": name}


def dedup_assets(assets: list[dict[str, str]]) -> list[dict[str, str]]:
    """Drop duplicate (kind, url) pairs, preserving order."""
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for asset in assets:
        key = (asset["kind"], asset["url"])
        if key not in seen:
            seen.add(key)
            unique.append(asset)
    return unique
