"""`ra2.domain.census.compute_census` (mvp-spec.md §6, sw-design.md §7).

Pure, in-memory: cells are constructed by hand and every number below is
hand-computed, not derived from the function under test.
"""

import pytest

from ra2.domain.census import TOP_VALUES_STORED, ColumnCensus, TypeHint, compute_census

pytestmark = pytest.mark.unit

COLUMNS = ("UnfallUid", "WetterAusw", "AnzObjFeld", "StrasseName")

# Five records. `StrasseName` is empty in every one of them (h08): the column
# name still appears in `COLUMNS`, so it must be reported at 0 %, never
# dropped from the result.
CELLS = [
    ("UnfallUid", "u1"),
    ("WetterAusw", "01"),
    ("AnzObjFeld", "1"),
    ("StrasseName", ""),
    ("UnfallUid", "u2"),
    ("WetterAusw", "01"),
    ("AnzObjFeld", "2"),
    ("StrasseName", ""),
    ("UnfallUid", "u3"),
    ("WetterAusw", "02"),
    ("AnzObjFeld", "1"),
    ("StrasseName", ""),
    ("UnfallUid", "u4"),
    ("WetterAusw", ""),
    ("AnzObjFeld", "3"),
    ("StrasseName", ""),
    ("UnfallUid", "u5"),
    ("WetterAusw", "01"),
    ("AnzObjFeld", "2"),
    ("StrasseName", ""),
]


def _census() -> dict[str, ColumnCensus]:
    result = compute_census("unfall", CELLS, columns=COLUMNS, record_count=5)
    return {c.column_name: c for c in result}


def test_returns_one_column_census_per_input_column_in_order():
    result = compute_census("unfall", CELLS, columns=COLUMNS, record_count=5)
    assert [c.column_name for c in result] == list(COLUMNS)
    assert all(c.table_name == "unfall" for c in result)
    assert all(c.record_count == 5 for c in result)


def test_a_fully_populated_distinct_column():
    """`UnfallUid`: 5 records, 5 distinct values, each once."""
    c = _census()["UnfallUid"]
    assert c.populated_count == 5
    assert c.populated_rate == pytest.approx(1.0)
    assert c.distinct_count == 5
    assert [(v.value_raw, v.count) for v in c.top_values] == [
        ("u1", 1),
        ("u2", 1),
        ("u3", 1),
        ("u4", 1),
        ("u5", 1),
    ]
    assert all(v.share == pytest.approx(0.2) for v in c.top_values)
    assert c.top_value_share == pytest.approx(0.2)
    assert c.long_tail is False
    assert c.type_hint == TypeHint.TEXT


def test_an_ausw_column_with_one_empty_row():
    """`WetterAusw`: populated in 4 of 5 records, `01` three times, `02` once."""
    c = _census()["WetterAusw"]
    assert c.populated_count == 4
    assert c.populated_rate == pytest.approx(0.8)
    assert c.distinct_count == 2
    assert [(v.value_raw, v.count) for v in c.top_values] == [("01", 3), ("02", 1)]
    assert [v.share for v in c.top_values] == [pytest.approx(0.75), pytest.approx(0.25)]
    assert c.top_value_share == pytest.approx(0.75)
    assert c.long_tail is False
    assert c.type_hint == TypeHint.ENUM, "Ausw suffix wins regardless of value shape"


def test_a_fully_populated_integer_column_with_a_tie():
    """`AnzObjFeld`: `1` and `2` both occur twice; `1` was seen first."""
    c = _census()["AnzObjFeld"]
    assert c.populated_count == 5
    assert c.populated_rate == pytest.approx(1.0)
    assert c.distinct_count == 3
    assert [(v.value_raw, v.count) for v in c.top_values] == [
        ("1", 2),
        ("2", 2),
        ("3", 1),
    ]
    assert c.top_value_share == pytest.approx(0.4)
    assert c.type_hint == TypeHint.INTEGER


def test_an_all_empty_column_is_zero_percent_and_not_dropped():
    """h08: `StrasseName` is empty in every row but must still appear."""
    c = _census()["StrasseName"]
    assert c.populated_count == 0
    assert c.populated_rate == 0.0
    assert c.distinct_count == 0
    assert c.top_values == ()
    assert c.top_value_share == 0.0
    assert c.long_tail is False
    assert c.type_hint == TypeHint.TEXT


def test_a_column_absent_from_the_cells_stream_entirely_is_still_reported():
    """h08's sharper form (M0-D9): in EAV storage a column with no populated
    row may never appear in the cell stream at all — not even as an empty
    string. `columns` is the header of record, so it must still surface at
    0 % rather than vanish."""
    cells = [("UnfallUid", "u1"), ("UnfallUid", "u2")]
    result = compute_census(
        "unfall", cells, columns=("UnfallUid", "NieGesetztFeld"), record_count=2
    )
    by_name = {c.column_name: c for c in result}
    ghost = by_name["NieGesetztFeld"]
    assert ghost.populated_count == 0
    assert ghost.populated_rate == 0.0
    assert ghost.distinct_count == 0
    assert ghost.top_values == ()
    assert ghost.long_tail is False


def test_populated_rate_uses_record_count_not_populated_count_as_denominator():
    """`objekt`/`person` rows can outnumber records; the denominator is
    always the corpus record count so rates stay comparable across tables."""
    cells = [("ObjektUid", "o1"), ("ObjektUid", "o2"), ("ObjektUid", "o3")]
    result = compute_census("objekt", cells, columns=("ObjektUid",), record_count=10)
    assert result[0].populated_rate == pytest.approx(0.3)
    assert result[0].record_count == 10


def test_record_count_zero_never_divides_by_zero():
    result = compute_census("unfall", [], columns=("UnfallUid",), record_count=0)
    assert result[0].populated_rate == 0.0


def test_top_n_limits_stored_values_but_not_distinct_count():
    cells = [("Code", str(i)) for i in range(30)]
    result = compute_census("unfall", cells, columns=("Code",), record_count=30, top_n=5)
    c = result[0]
    assert c.distinct_count == 30
    assert len(c.top_values) == 5


def test_default_top_n_matches_the_stored_constant():
    cells = [("Code", str(i)) for i in range(TOP_VALUES_STORED + 5)]
    result = compute_census("unfall", cells, columns=("Code",), record_count=TOP_VALUES_STORED + 5)
    assert len(result[0].top_values) == TOP_VALUES_STORED


def test_a_cell_for_a_column_outside_the_canonical_header_is_ignored():
    """Defensive: `columns` is the source of truth for what gets reported;
    a stray cell for an unlisted column must not crash the census or leak
    into another column's counts."""
    cells = [("UnfallUid", "u1"), ("SomeOtherTable_Column", "x")]
    result = compute_census("unfall", cells, columns=("UnfallUid",), record_count=1)
    assert len(result) == 1
    assert result[0].populated_count == 1
