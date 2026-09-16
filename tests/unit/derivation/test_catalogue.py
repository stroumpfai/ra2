"""`domain.derivation` — mvp-spec.md §8.3's closed catalogue, executed.

`plan-phase-2.md` Q1 deferred this evaluator with the words "scoring (phase 3)
needs to build one anyway — building it twice is waste". Phase 3 did not need
it; a derivation reaches a prompt as a *description*. Scoring does, because a
derived feature's ground truth does not exist anywhere until something computes
it (sw-design.md §16.2).

One test per catalogue type, filtered and unfiltered, plus the two distinctions
that decide what a feature's `n` is.
"""

import pytest

from ra2.domain.derivation import DerivationError, RecordProjection, evaluate
from ra2.domain.feature import (
    AnyObjectMatches,
    AnyPersonMatches,
    CountObjects,
    CountPersons,
    DistinctCount,
    Filter,
    MaxOrdinal,
    MinOrdinal,
    Operator,
)

#: Two vehicles and three people. `ObjArtAusw` is the vehicle kind, `VerlAusw`
#: the injury severity — real column names, the shapes the delivery carries.
PROJECTION = RecordProjection(
    objekt_rows=[
        {"ObjArtAusw": "01", "Marke": "VW", "SchadenAusw": "2"},
        {"ObjArtAusw": "03", "Marke": "", "SchadenAusw": "1"},
    ],
    person_rows=[
        {"VerlAusw": "2", "GeschlAusw": "1"},
        {"VerlAusw": "3", "GeschlAusw": "2"},
        {"VerlAusw": "", "GeschlAusw": "1"},
    ],
)

EMPTY = RecordProjection(objekt_rows=[], person_rows=[])


# --- counts ----------------------------------------------------------------


def test_count_objects_without_a_filter_counts_every_row():
    assert evaluate(CountObjects(), PROJECTION) == "2"


def test_count_objects_with_a_filter_counts_matching_rows():
    matcher = Filter("ObjArtAusw", Operator.EQ, "01")
    assert evaluate(CountObjects(matcher), PROJECTION) == "1"


def test_count_persons_without_a_filter():
    assert evaluate(CountPersons(), PROJECTION) == "3"


def test_count_persons_with_a_filter():
    matcher = Filter("GeschlAusw", Operator.EQ, "1")
    assert evaluate(CountPersons(matcher), PROJECTION) == "2"


def test_a_count_over_zero_rows_is_the_string_zero_not_none():
    """**The single most consequential line in this module** (§16.2).

    "No objects" is a fact the data states and belongs in the denominator;
    "no value" is a fact the data is missing and does not. Returning `None`
    here would delete every objectless record from every derived feature's `n`,
    silently, and every derived rate would be computed over the wrong base.
    """
    assert evaluate(CountObjects(), EMPTY) == "0"
    assert evaluate(CountPersons(), EMPTY) == "0"


# --- booleans --------------------------------------------------------------


def test_any_object_matches_is_true_when_one_does():
    matcher = Filter("ObjArtAusw", Operator.IN, ("03", "04"))
    assert evaluate(AnyObjectMatches(matcher), PROJECTION) == "true"


def test_any_object_matches_is_false_when_none_does():
    matcher = Filter("ObjArtAusw", Operator.EQ, "99")
    assert evaluate(AnyObjectMatches(matcher), PROJECTION) == "false"


def test_any_person_matches():
    assert evaluate(AnyPersonMatches(Filter("VerlAusw", Operator.EQ, "3")), PROJECTION) == "true"
    assert evaluate(AnyPersonMatches(Filter("VerlAusw", Operator.EQ, "9")), PROJECTION) == "false"


def test_a_boolean_over_zero_rows_is_false_not_none():
    """Same rule as a count: "this record has no bicycle" is a fact."""
    assert evaluate(AnyObjectMatches(Filter("ObjArtAusw", Operator.EQ, "01")), EMPTY) == "false"


def test_booleans_render_as_the_strings_matching_compares():
    """A derived boolean and a model's `true` have to meet on the same ground
    — `matching.normalise` sees both as strings."""
    assert evaluate(AnyObjectMatches(Filter("Marke", Operator.IS_NOT_EMPTY)), PROJECTION) in {
        "true",
        "false",
    }


# --- ordinals --------------------------------------------------------------


def test_max_ordinal_returns_the_highest_configured_code():
    spec = MaxOrdinal("objekt", "ObjArtAusw", ("01", "02", "03"))
    assert evaluate(spec, PROJECTION) == "03"


def test_min_ordinal_returns_the_lowest_configured_code():
    spec = MinOrdinal("objekt", "ObjArtAusw", ("01", "02", "03"))
    assert evaluate(spec, PROJECTION) == "01"


def test_ordinal_order_is_the_configured_one_not_lexical():
    """The whole reason the catalogue takes an `ordered_code_list`: codes are
    labels, and `"10"` sorts before `"9"` as a string."""
    projection = RecordProjection(
        objekt_rows=[{"Severity": "9"}, {"Severity": "10"}], person_rows=[]
    )
    spec = MaxOrdinal("objekt", "Severity", ("9", "10"))
    assert evaluate(spec, projection) == "10"


def test_an_ordinal_over_no_rows_is_none_not_a_code():
    """Here `None` **is** right: the derivation genuinely has no value, so the
    record leaves the denominator (§8.6). Contrast the count above."""
    assert evaluate(MaxOrdinal("objekt", "ObjArtAusw", ("01",)), EMPTY) is None


def test_an_ordinal_skips_blank_cells_but_still_answers():
    projection = RecordProjection(
        objekt_rows=[{"Severity": ""}, {"Severity": "02"}], person_rows=[]
    )
    assert evaluate(MaxOrdinal("objekt", "Severity", ("01", "02")), projection) == "02"


def test_an_ordinal_with_only_blank_cells_is_none():
    projection = RecordProjection(objekt_rows=[{"Severity": ""}], person_rows=[])
    assert evaluate(MaxOrdinal("objekt", "Severity", ("01", "02")), projection) is None


def test_a_code_outside_the_configured_ordering_raises():
    """**A typed error, not a silent skip.** The config declared an ordering
    and the data contains something outside it — a configuration fault, not a
    record fault. Skipping the row would drop a record from the denominator and
    make the feature look better measured than it is.
    """
    spec = MaxOrdinal("objekt", "ObjArtAusw", ("01", "02"))
    with pytest.raises(DerivationError, match="absent from the configured ordering"):
        evaluate(spec, PROJECTION)


# --- distinct count --------------------------------------------------------


def test_distinct_count_ignores_blanks():
    assert evaluate(DistinctCount("objekt", "Marke"), PROJECTION) == "1"


def test_distinct_count_counts_distinct_values_not_rows():
    projection = RecordProjection(
        objekt_rows=[{"Marke": "VW"}, {"Marke": "VW"}, {"Marke": "Audi"}], person_rows=[]
    )
    assert evaluate(DistinctCount("objekt", "Marke"), projection) == "2"


def test_distinct_count_over_zero_rows_is_zero():
    assert evaluate(DistinctCount("objekt", "Marke"), EMPTY) == "0"


# --- operators -------------------------------------------------------------


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [
        (Operator.EQ, "01", "1"),
        (Operator.NE, "01", "1"),
        (Operator.IN, ("01", "03"), "2"),
        (Operator.NOT_IN, ("01", "03"), "0"),
        (Operator.IS_EMPTY, None, "0"),
        (Operator.IS_NOT_EMPTY, None, "2"),
    ],
)
def test_every_operator_in_the_closed_set(operator, value, expected):
    """mvp-spec.md §8.3's six. Anything beyond them is out of scope, and the
    `Operator` enum is what makes "anything beyond" unrepresentable."""
    matcher = Filter("ObjArtAusw", operator, value)
    assert evaluate(CountObjects(matcher), PROJECTION) == expected


def test_a_missing_column_matches_nothing_rather_than_everything():
    """Nothing invents a value for a column this delivery does not carry.

    `NE` is where the naive implementation goes wrong: `row.get(col) != value`
    is `True` for every row lacking the column, so a filter on a mistyped
    column name would count the whole table and look like a working feature.
    """
    matcher = Filter("NoSuchColumn", Operator.NE, "01")
    assert evaluate(CountObjects(matcher), PROJECTION) == "0"


def test_a_missing_column_is_empty():
    matcher = Filter("NoSuchColumn", Operator.IS_EMPTY, None)
    assert evaluate(CountObjects(matcher), PROJECTION) == "2"


def test_a_blank_cell_and_a_missing_column_are_alike():
    """The delivery cannot distinguish them either (§8.6)."""
    blank = RecordProjection(objekt_rows=[{"Marke": ""}], person_rows=[])
    missing = RecordProjection(objekt_rows=[{"Other": "x"}], person_rows=[])
    matcher = Filter("Marke", Operator.IS_EMPTY, None)
    assert evaluate(CountObjects(matcher), blank) == evaluate(CountObjects(matcher), missing) == "1"


# --- misuse ----------------------------------------------------------------


def test_an_unknown_table_raises():
    with pytest.raises(DerivationError, match="expected one of"):
        evaluate(DistinctCount("vehicle", "Marke"), PROJECTION)


def test_person_rows_are_flat_not_nested_under_objekt():
    """`person` hangs off `objekt` in the delivery (mvp-spec.md §4.1), but no
    derivation in the catalogue reaches across that edge — `count_persons` is
    record-wide, so the projection carries a flat list."""
    assert evaluate(CountPersons(), PROJECTION) == "3"
    assert len(PROJECTION.person_rows) == 3
