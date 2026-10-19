"""Layer 1 — `domain.codelist_suggest` (plan-codelists-usability.md §4.1).

Pure: plain `(value, count)` cells and code sets in, suggestions out. The
hazards are the ones a real code table carries — leading zeros (`01` vs `1`),
small integer codes that sit inside many attributes at once, an all-empty
column, and a copied key the current import no longer has.
"""

from ra2.domain.codelist_suggest import (
    MIN_OVERLAP_DISTINCT,
    MappingSuggestion,
    SuggestionSource,
    rank_attributes,
    suggest_mappings,
)

#: Two attributes over the same small integers, one padded — the shape that
#: makes overlap alone untrustworthy, and the leading-zero hazard.
PADDED = frozenset({"01", "02", "03", "04"})
BARE = frozenset({"1", "2", "3", "4"})
WIDE = frozenset({str(n) for n in range(1, 10)})


def _only(suggestions: tuple[MappingSuggestion, ...]) -> MappingSuggestion:
    (suggestion,) = suggestions
    return suggestion


def test_a_copied_key_wins_over_a_better_overlap() -> None:
    """The analyst's earlier decision is the suggestion, even where another
    attribute covers the column more tightly — with its overlap attached, so
    a bad copy shows as one."""
    suggestion = _only(
        suggest_mappings(
            {"WitterungAusw": [("1", 5), ("2", 1)]},
            {"weather": WIDE, "light": BARE},
            {"WitterungAusw": "weather"},
        )
    )
    assert suggestion.source is SuggestionSource.COPIED
    assert suggestion.attribute_key == "weather"
    assert (suggestion.overlap.contained, suggestion.overlap.distinct) == (2, 2)


def test_a_copy_that_does_not_cover_the_column_still_says_so() -> None:
    suggestion = _only(suggest_mappings({"A": [("1", 3), ("7", 1)]}, {"k": BARE}, {"A": "k"}))
    assert (suggestion.overlap.contained, suggestion.overlap.distinct) == (1, 2)
    assert suggestion.overlap.records_contained == 0.75


def test_a_copied_key_missing_from_the_import_gives_no_suggestion() -> None:
    """Never a silent fall-back to overlap: the caller reports the column as
    unresolved, and the analyst decides."""
    assert suggest_mappings({"A": [("1", 3)]}, {"k": BARE}, {"A": "gone"}) == ()


def test_overlap_suggests_the_one_attribute_that_is_just_big_enough() -> None:
    """`BARE` and `WIDE` both contain {1, 2, 3}; `BARE` is the tighter fit."""
    suggestion = _only(
        suggest_mappings({"A": [("1", 4), ("2", 2), ("3", 1)]}, {"wide": WIDE, "bare": BARE}, {})
    )
    assert suggestion.source is SuggestionSource.OVERLAP
    assert suggestion.attribute_key == "bare"


def test_overlap_needs_every_value_covered() -> None:
    """`9` is in no attribute but `WIDE`, so only `WIDE` qualifies."""
    suggestion = _only(
        suggest_mappings({"A": [("1", 40), ("9", 1)]}, {"bare": BARE, "wide": WIDE}, {})
    )
    assert suggestion.attribute_key == "wide"
    assert suggest_mappings({"A": [("1", 40), ("99", 1)]}, {"bare": BARE, "wide": WIDE}, {}) == ()


def test_a_tie_on_overlap_gives_no_suggestion() -> None:
    """Two attributes with identical codes: a coin flip is not a proposal."""
    cells = [("1", 2), ("2", 1)]
    assert suggest_mappings({"A": cells}, {"x": BARE, "y": frozenset(BARE)}, {}) == ()


def test_codes_match_exactly_so_a_lost_leading_zero_is_no_overlap() -> None:
    """`1` is not `01`. The padded attribute is not offered for a bare column,
    and the bare one is for the bare column alone."""
    attributes = {"padded": PADDED, "bare": BARE}
    suggestions = suggest_mappings(
        {"Bare": [("1", 3), ("2", 1)], "Padded": [("01", 3), ("02", 1)]}, attributes, {}
    )
    assert [(s.column_name, s.attribute_key) for s in suggestions] == [
        ("Bare", "bare"),
        ("Padded", "padded"),
    ]
    (padded,) = [o for o in rank_attributes([("1", 3)], attributes) if o.attribute_key == "padded"]
    assert padded.contained == 0


def test_one_distinct_value_is_no_evidence_for_overlap() -> None:
    """`1` sits inside every attribute that has it, so the "tightest fit" would
    only be the smallest attribute. A copy has no such floor: it rests on a
    decision, not on the data."""
    assert MIN_OVERLAP_DISTINCT == 2
    assert suggest_mappings({"A": [("1", 40)]}, {"bare": BARE, "wide": WIDE}, {}) == ()
    copied = _only(suggest_mappings({"A": [("1", 40)]}, {"wide": WIDE}, {"A": "wide"}))
    assert copied.source is SuggestionSource.COPIED


def test_an_all_empty_column_gives_no_suggestion() -> None:
    assert suggest_mappings({"A": []}, {"k": BARE}, {"A": "k"}) == ()


def test_no_attributes_gives_no_suggestion() -> None:
    assert suggest_mappings({"A": [("1", 1), ("2", 1)]}, {}, {}) == ()


def test_suggestions_keep_the_callers_column_order() -> None:
    columns = {
        "Z": [("1", 1), ("2", 1)],
        "A": [("01", 1), ("02", 1)],
        "M": [("1", 1), ("3", 1)],
    }
    suggestions = suggest_mappings(columns, {"bare": BARE, "padded": PADDED}, {})
    assert [s.column_name for s in suggestions] == ["Z", "A", "M"]


def test_the_ranking_is_total_and_deterministic() -> None:
    """Same score, different keys: ordered by key, whatever order the
    attributes arrived in."""
    ranked = rank_attributes([("1", 1)], {"b": BARE, "a": frozenset(BARE), "w": WIDE})
    assert [o.attribute_key for o in ranked] == ["a", "b", "w"]


def test_records_weigh_more_than_distinct_values() -> None:
    """A stray value on one record barely dents the share of records covered,
    which is what ranks first."""
    (best, *_) = rank_attributes([("1", 99), ("7", 1)], {"bare": BARE, "other": frozenset({"7"})})
    assert best.attribute_key == "bare"
    assert best.records_contained == 0.99
