"""Layer 1 — `domain.text_search` (plan-codelists-usability.md §2–§3).

`fold` runs twice: here, on the text the server writes into `data-search`,
and in the browser, on what the analyst types (`_KEY_FILTER_JS`). The cases
below are the ones where Python's and JavaScript's own case-folding disagree,
which is why `fold` sticks to steps both spell the same way.
"""

import pytest

from ra2.domain.text_search import fold, matches


@pytest.mark.parametrize(
    ("text", "folded"),
    [
        ("Strassenart", "strassenart"),
        ("Straße", "strasse"),
        ("STRASSE", "strasse"),
        ("Chaussée", "chaussee"),
        ("Lichtverhältnis", "lichtverhaltnis"),
        ("Gravità", "gravita"),
        ("ﬁn", "fin"),  # a compatibility ligature, NFKD-decomposed
        ("", ""),
    ],
)
def test_fold(text: str, folded: str) -> None:
    assert fold(text) == folded


def test_fold_drops_spacing_marks_as_the_browser_does() -> None:
    """`\\p{M}` in the browser takes spacing marks (`Mc`) too, which
    `unicodedata.combining` would have kept: U+0903 is one."""
    assert fold("aःb") == "ab"


@pytest.mark.parametrize(
    ("query", "expected"),
    [("", True), ("  ", True), ("strasse", True), ("STRAßE", True), ("weather", False)],
)
def test_matches_any_haystack(query: str, expected: bool) -> None:
    assert matches(query, "UnfallartAusw", "Strassenart") is expected


def test_matches_with_no_haystack_is_false_unless_blank() -> None:
    assert matches("x") is False
    assert matches("") is True
