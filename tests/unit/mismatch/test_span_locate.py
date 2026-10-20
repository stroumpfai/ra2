"""`domain.span_locate.locate` — where the evidence span sits in the narrative
(`SD71`, `plan-mismatch-context.md` §4.1). It locates and never judges."""

import pytest

from ra2.domain.span_locate import locate

pytestmark = pytest.mark.unit

#: `s05`'s lossy French, byte-exact.
FRENCH_LOSSY = "Le v hicule a d rap  sur la chauss e mouill e."


def _spans(text: str, span: str) -> list[str]:
    return [text[start:end] for start, end in locate(text, span)]


def test_every_exact_occurrence_left_to_right() -> None:
    text = "Regen. Dann wieder Regen, später Regen."
    assert locate(text, "Regen") == ((0, 5), (19, 24), (33, 38))


def test_occurrences_do_not_overlap() -> None:
    assert locate("aaaa", "aa") == ((0, 2), (2, 4))


def test_a_span_across_an_embedded_newline_is_found_in_the_original() -> None:
    """The hazard: the narrative breaks the line where the quote has a space."""
    text = "Der Lenker fuhr bei\nstarkem Regen auf die A1."
    assert _spans(text, "bei starkem Regen") == ["bei\nstarkem Regen"]


def test_a_crlf_and_a_run_of_spaces_fold_too() -> None:
    text = "auf der\r\nNassen   Fahrbahn"
    assert _spans(text, "der Nassen Fahrbahn") == ["der\r\nNassen   Fahrbahn"]
    assert _spans("a  b", "a\nb") == ["a  b"]


def test_the_tolerant_pass_runs_only_when_exact_finds_nothing() -> None:
    """One exact hit is the answer; a folded second one is not added."""
    text = "nass rutschig. nass\nrutschig."
    assert locate(text, "nass rutschig") == ((0, 13),)


def test_case_matters() -> None:
    assert locate("Regen", "regen") == ()


def test_a_lossy_character_matches_only_itself() -> None:
    """No normalisation: a span that restored the accent is not in this text."""
    assert _spans(FRENCH_LOSSY, "chauss e mouill e") == ["chauss e mouill e"]
    assert locate(FRENCH_LOSSY, "chaussée mouillée") == ()


def test_a_span_that_is_not_there_gives_nothing_and_says_nothing() -> None:
    assert locate("Schneefall, Strasse nass.", "Nebel") == ()


@pytest.mark.parametrize(
    ("text", "span"),
    [(None, "x"), ("", "x"), ("text", None), ("text", ""), ("text", "  \n ")],
)
def test_nothing_to_look_for_or_in_gives_nothing(text: str | None, span: str | None) -> None:
    assert locate(text, span) == ()


def test_leading_and_trailing_whitespace_in_a_span_does_not_stop_a_fold() -> None:
    assert _spans("bei\nRegen", " bei Regen ") == ["bei\nRegen"]
