import re

from silo.schemas.metadata_source import SearchCandidateOut
from silo.services.entities import slugify

_PARENS = re.compile(r"\s*\([^)]*\)")
_YEAR = re.compile(r"\((19\d{2}|20\d{2})\)")


def clean_dat_name(game_name: str) -> str:
    """The search term: a DAT title with its parenthesized qualifiers stripped."""
    return _PARENS.sub("", game_name).strip()


def dat_year(game_name: str) -> int | None:
    """A year carried in the DAT title's qualifiers, when present."""
    match = _YEAR.search(game_name)
    return int(match.group(1)) if match else None


def pick_match(candidates: list[SearchCandidateOut], game_name: str) -> SearchCandidateOut | None:
    """Auto-accept rule: unique exact normalized-title match, year tiebreak on ties."""
    target = slugify(clean_dat_name(game_name))
    if not target:
        return None
    exact = [candidate for candidate in candidates if slugify(candidate.name) == target]
    if len(exact) > 1:
        year = dat_year(game_name)
        if year is not None:
            exact = [candidate for candidate in exact if candidate.year == year]
    return exact[0] if len(exact) == 1 else None
