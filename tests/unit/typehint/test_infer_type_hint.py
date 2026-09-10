"""`ra2.domain.typehint.infer_type_hint` (mvp-spec.md §6, sw-design.md §7).

The suffix rule runs first and always wins over value-shape inspection when
they would disagree; value-shape inspection only decides what the suffix
leaves open.
"""

import pytest

from ra2.domain.census import TypeHint
from ra2.domain.typehint import infer_type_hint

pytestmark = pytest.mark.unit


# --- the suffix rule ---------------------------------------------------


def test_ausw_suffix_is_always_enum():
    assert infer_type_hint("UnfallartAusw", ["01", "02", "03"]) == TypeHint.ENUM


def test_ausw_suffix_beats_value_shape_even_when_values_look_integral():
    """The load-bearing case: an `Ausw`-suffixed column whose values happen to
    look like integers must still resolve to `enum`, never `integer`."""
    assert infer_type_hint("LichtVerhAusw", ["1", "2", "3"]) == TypeHint.ENUM


def test_ausw_suffix_beats_value_shape_even_when_values_look_like_dates():
    assert infer_type_hint("SomeAusw", ["20230101", "20230102"]) == TypeHint.ENUM


def test_feld_suffix_falls_through_to_value_shape():
    """`Feld` carries no special meaning of its own — it is just a column
    whose name does not end in `Ausw`, so it falls through to shape
    inspection like any other non-enum column."""
    assert infer_type_hint("AnzObjFeld", ["1", "2", "3"]) == TypeHint.INTEGER


# --- value-shape inspection, in priority order --------------------------


def test_all_values_yyyymmdd_in_plausible_range_is_date():
    assert infer_type_hint("UnfallDatum", ["20230115", "19991231"]) == TypeHint.DATE


@pytest.mark.parametrize(
    "value",
    [
        "20231301",  # month 13
        "20230100",  # day 0
        "18500101",  # year before the plausible range
        "21500101",  # year after the plausible range
        "2023011",  # too short
        "2023-01-01",  # not digits-only
    ],
)
def test_implausible_yyyymmdd_is_not_a_date(value):
    assert infer_type_hint("SomeFeld", [value]) != TypeHint.DATE


def test_all_values_hh_mm_is_time():
    assert infer_type_hint("UnfallZeit", ["08:15", "23:59", "00:00"]) == TypeHint.TIME


@pytest.mark.parametrize("value", ["24:00", "12:60", "8:15", "12:5"])
def test_malformed_hh_mm_is_not_time(value):
    assert infer_type_hint("SomeFeld", [value]) != TypeHint.TIME


def test_all_values_integral_is_integer():
    assert infer_type_hint("AnzObjFeld", ["0", "1", "42", "-3"]) == TypeHint.INTEGER


def test_a_value_with_a_decimal_point_is_not_integer_even_if_whole():
    assert infer_type_hint("SomeFeld", ["1", "2.0"]) == TypeHint.DECIMAL


def test_all_values_decimal_parseable_is_decimal():
    assert infer_type_hint("SomeFeld", ["1.5", "2.75", "3"]) == TypeHint.DECIMAL


def test_non_numeric_values_are_text():
    assert infer_type_hint("SomeFeld", ["Kollision", "Sturz"]) == TypeHint.TEXT


def test_mixed_shapes_fall_back_to_text():
    """One value that breaks the pattern for every stricter type demotes the
    whole column to `text` rather than picking a partial match."""
    assert infer_type_hint("SomeFeld", ["1", "abc"]) == TypeHint.TEXT


# --- Swiss/German grouped numbers and dotted dates -----------------------


def test_apostrophe_grouped_integers_are_integer():
    assert infer_type_hint("SomeFeld", ["40'367", "1'127'946"]) == TypeHint.INTEGER


def test_mixed_grouped_and_plain_integers_are_integer():
    """Swiss formatting only groups once a number reaches 1000+, so a column
    is realistically a mix of grouped and ungrouped values."""
    assert infer_type_hint("SomeFeld", ["367", "1'127'946"]) == TypeHint.INTEGER


def test_negative_apostrophe_grouped_is_integer():
    assert infer_type_hint("SomeFeld", ["-40'367"]) == TypeHint.INTEGER


def test_apostrophe_grouped_decimals_are_decimal():
    assert infer_type_hint("SomeFeld", ["602'378.61", "1'127'946.61"]) == TypeHint.DECIMAL


def test_apostrophe_grouped_decimal_point_still_beats_integer():
    """The existing "any `.` demotes from integer" rule still applies after
    grouping normalisation."""
    assert infer_type_hint("SomeFeld", ["1'000", "2.5"]) == TypeHint.DECIMAL


@pytest.mark.parametrize(
    "value",
    [
        "40'36",  # short group
        "'367",  # leading apostrophe
        "40''367",  # doubled apostrophe
        "1'2345",  # 4-digit group
    ],
)
def test_malformed_grouping_is_not_a_number(value):
    assert infer_type_hint("SomeFeld", [value]) == TypeHint.TEXT


def test_dotted_ddmmyy_date_is_date():
    """Covers both sides of the century pivot: `23` -> 2023, `99` -> 1999."""
    assert infer_type_hint("UnfallDatum", ["20.01.23", "15.06.99"]) == TypeHint.DATE


@pytest.mark.parametrize(
    "value",
    [
        "32.01.23",  # day 32
        "20.13.23",  # month 13
        "20.01.2",  # short year
        "20-01-23",  # wrong separator
    ],
)
def test_implausible_dotted_date_is_not_a_date(value):
    assert infer_type_hint("SomeFeld", [value]) != TypeHint.DATE


def test_ausw_suffix_beats_value_shape_even_when_values_look_like_apostrophe_grouped_numbers():
    assert infer_type_hint("SomeAusw", ["40'367", "1'127'946"]) == TypeHint.ENUM


def test_ausw_suffix_beats_value_shape_even_when_values_look_like_dotted_dates():
    assert infer_type_hint("SomeAusw", ["20.01.23"]) == TypeHint.ENUM


# --- empties -------------------------------------------------------------


def test_a_column_with_no_populated_values_is_text():
    assert infer_type_hint("SomeFeld", ["", "", ""]) == TypeHint.TEXT


def test_empty_values_are_ignored_when_shape_is_inspected():
    """Empty means *no value provided* (§8.6): it neither counts as evidence
    for a shape nor breaks one."""
    assert infer_type_hint("SomeFeld", ["1", "", "2"]) == TypeHint.INTEGER


def test_no_values_at_all_is_text():
    assert infer_type_hint("SomeFeld", []) == TypeHint.TEXT
