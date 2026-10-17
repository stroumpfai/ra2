"""Properties of the scrubber over generated narratives (sw-design.md §19.2).

Text is built from a vocabulary of ordinary narrative words, with fixture
names and Swiss-shaped numbers planted at random. Whatever the arrangement:
no planted name survives as a token, every untouched token keeps its order,
placeholders are well formed, and scrubbing twice changes nothing.
"""

import pytest
import regex
from hypothesis import given, settings
from hypothesis import strategies as st

from ra2.domain.scrub import Scrubber, ScrubRules, entry_key
from ra2.domain.scrub_mandatory import MANDATORY_RULES

pytestmark = pytest.mark.unit

FIRSTNAMES = ("Hans", "Anna", "Jörg", "Céline", "Luca")
LASTNAMES = ("Müller", "Meier", "Brunner", "Dupont", "Rossi", "von Allmen")
#: Ordinary words that must survive wherever they land. No canton code: `ZH`
#: followed by a planted `80` *is* a plate, so it would not survive, and
#: rightly. `Kanton` stays, so `Kanton ZH 1234` is generated and tested.
WORDS = (
    "Der",
    "Lenker",
    "fuhr",
    "auf",
    "der",
    "Hauptstrasse",
    "B1",
    "G1",
    "bremste",
    "um",
    "14.30",
    "Uhr",
    "mit",
    "80",
    "km/h",
    "Fahrzeug",
    "le",
    "conducteur",
    "a",
    "freiné",
    "Kanton",
    "rot",
)
NUMBERS = ("079 123 45 67", "+41 44 123 45 67", "BE 123456", "ZH 1234", "h@example.ch")

_PLACEHOLDER = regex.compile(r"<[A-Z][A-Za-z]{1,31}_[1-9]\d*>")
_SCRUBBER = Scrubber(ScrubRules(MANDATORY_RULES, firstnames=FIRSTNAMES, lastnames=LASTNAMES))
_NAME_KEYS = {entry_key(n) for n in (*FIRSTNAMES, *LASTNAMES)}

_pieces = st.lists(
    st.one_of(
        st.sampled_from(WORDS).map(lambda w: ("word", w)),
        st.sampled_from((*FIRSTNAMES, *LASTNAMES)).map(lambda n: ("name", n)),
        st.sampled_from(NUMBERS).map(lambda n: ("number", n)),
    ),
    min_size=1,
    max_size=30,
)
_separators = st.sampled_from([" ", "  ", ", ", ". ", "\n", " (", ") "])


@st.composite
def narratives(draw: st.DrawFn) -> tuple[str, list[tuple[str, str]]]:
    pieces = draw(_pieces)
    parts: list[str] = []
    for index, (_, value) in enumerate(pieces):
        if index:
            parts.append(draw(_separators))
        parts.append(value)
    return "".join(parts), pieces


def _tokens(text: str) -> list[str]:
    return regex.findall(r"\p{L}[\p{L}\p{M}]*", _PLACEHOLDER.sub(" ", text))


@settings(max_examples=300, deadline=None)
@given(narratives())
def test_no_planted_name_survives_as_a_token(case: tuple[str, list[tuple[str, str]]]) -> None:
    text, _ = case
    scrubbed = _SCRUBBER.scrub(text).text
    surviving = {entry_key(t) for t in _tokens(scrubbed)}
    assert not surviving & _NAME_KEYS


@settings(max_examples=300, deadline=None)
@given(narratives())
def test_the_untouched_words_keep_their_order(case: tuple[str, list[tuple[str, str]]]) -> None:
    text, pieces = case
    scrubbed = _SCRUBBER.scrub(text).text
    words = [value for kind, value in pieces if kind == "word" and value.isalpha()]
    remaining = iter(_tokens(scrubbed))
    assert all(any(word == token for token in remaining) for word in words)


@settings(max_examples=300, deadline=None)
@given(narratives())
def test_every_placeholder_is_well_formed_and_matches_a_hit(
    case: tuple[str, list[tuple[str, str]]],
) -> None:
    text, _ = case
    result = _SCRUBBER.scrub(text)
    assert sorted(_PLACEHOLDER.findall(result.text)) == sorted(h.placeholder for h in result.hits)


@settings(max_examples=300, deadline=None)
@given(narratives())
def test_numbers_start_at_one_and_have_no_gaps(case: tuple[str, list[tuple[str, str]]]) -> None:
    text, _ = case
    by_tag: dict[str, set[int]] = {}
    for hit in _SCRUBBER.scrub(text).hits:
        by_tag.setdefault(hit.tag, set()).add(hit.number)
    for numbers in by_tag.values():
        assert numbers == set(range(1, len(numbers) + 1))


@settings(max_examples=300, deadline=None)
@given(narratives())
def test_scrubbing_twice_is_scrubbing_once(case: tuple[str, list[tuple[str, str]]]) -> None:
    text, _ = case
    once = _SCRUBBER.scrub(text).text
    assert _SCRUBBER.scrub(once).text == once


@settings(max_examples=200, deadline=None)
@given(st.text(max_size=200))
def test_arbitrary_text_never_raises_and_hits_lie_inside_it(text: str) -> None:
    result = _SCRUBBER.scrub(text)
    for hit in result.hits:
        assert 0 <= hit.start < hit.end <= len(text)
    starts = [h.start for h in result.hits]
    assert starts == sorted(starts)
    assert all(a.end <= b.start for a, b in zip(result.hits, result.hits[1:], strict=False))
