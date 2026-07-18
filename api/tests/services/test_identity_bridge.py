from silo.schemas.metadata_source import SearchCandidateOut
from silo.services.identity_bridge import clean_dat_name, dat_year, pick_match


def _candidate(external_id: str, name: str, year: int | None) -> SearchCandidateOut:
    return SearchCandidateOut(external_id=external_id, name=name, year=year)


def test_clean_dat_name_strips_qualifiers():
    assert clean_dat_name("Doom (USA) (Rev 1)") == "Doom"
    assert clean_dat_name("Baldur's Gate (Europe) (Disc 2)") == "Baldur's Gate"
    assert clean_dat_name("Quake") == "Quake"


def test_dat_year():
    assert dat_year("Doom (USA) (1993)") == 1993
    assert dat_year("Doom (USA)") is None


def test_pick_match_unique_exact():
    candidates = [_candidate("1", "Doom", 1993), _candidate("2", "Doom II", 1994)]
    match = pick_match(candidates, "Doom (USA)")
    assert match is not None and match.external_id == "1"


def test_pick_match_normalizes_punctuation():
    match = pick_match([_candidate("9", "Baldur's Gate", 1998)], "Baldurs Gate (Europe)")
    assert match is not None and match.external_id == "9"


def test_pick_match_rejects_fuzzy_and_ambiguous():
    # No exact normalized match → prompt, never guess.
    assert pick_match([_candidate("1", "Doom 3", 2004)], "Doom (USA)") is None
    # Two exacts without a year to break the tie → prompt.
    twins = [_candidate("1", "Doom", 1993), _candidate("2", "Doom", 2016)]
    assert pick_match(twins, "Doom (USA)") is None


def test_pick_match_year_tiebreak():
    twins = [_candidate("1", "Doom", 1993), _candidate("2", "Doom", 2016)]
    match = pick_match(twins, "Doom (USA) (2016)")
    assert match is not None and match.external_id == "2"


def test_pick_match_unslugifiable_name():
    assert pick_match([_candidate("1", "!!!", None)], "(!!!)") is None
