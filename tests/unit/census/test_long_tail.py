"""The SD8 long-tail rule: `distinct_count > 20 and top_value_share < 0.01`.

Both sides of both thresholds are asserted directly against the private
`_is_long_tail` predicate `compute_census` calls internally. This is
deliberate rather than routing every case through `compute_census`'s cell
counting: with only `N` distinct values the most frequent one holds at least
`1/N` of the total (pigeonhole), so `top_value_share < 0.01` cannot be
realised below roughly 100 distinct values — a real column with exactly 21
distinct values can never have a top share under 1 %. Testing the boolean
directly lets each threshold's boundary be asserted on its own terms; a
second block below confirms the same rule end-to-end through `compute_census`
using distinct counts large enough for both conditions to be jointly
realisable.
"""

import pytest

from ra2.domain.census import (
    LONG_TAIL_MAX_TOP_SHARE,
    LONG_TAIL_MIN_DISTINCT,
    _is_long_tail,
    compute_census,
)

pytestmark = pytest.mark.unit


def test_thresholds_match_sd8():
    assert LONG_TAIL_MIN_DISTINCT == 20
    assert LONG_TAIL_MAX_TOP_SHARE == 0.01


# --- the distinct-count threshold, share held deep in "long tail" territory --


def test_distinct_count_exactly_at_threshold_is_not_long_tail():
    assert _is_long_tail(distinct_count=20, top_value_share=0.001) is False


def test_distinct_count_one_above_threshold_is_long_tail():
    assert _is_long_tail(distinct_count=21, top_value_share=0.001) is True


# --- the top-value-share threshold, distinct held deep in "long tail" territory --


def test_top_value_share_at_0_011_is_not_long_tail():
    assert _is_long_tail(distinct_count=200, top_value_share=0.011) is False


def test_top_value_share_at_0_009_is_long_tail():
    assert _is_long_tail(distinct_count=200, top_value_share=0.009) is True


# --- exactly-on-the-boundary is the non-long-tail side (strict inequalities) --


def test_share_exactly_at_the_max_is_not_long_tail():
    assert _is_long_tail(distinct_count=200, top_value_share=0.01) is False


def test_distinct_exactly_at_the_min_is_not_long_tail_regardless_of_share():
    assert _is_long_tail(distinct_count=20, top_value_share=0.0001) is False


# --- end to end through compute_census, with jointly realisable numbers ------


def test_compute_census_flags_long_tail_on_a_flat_wide_distribution():
    """101 distinct values, each equally frequent: top share is `1/101`,
    just under 1 %, and distinct count is well past 20."""
    cells = [("Code", str(i)) for i in range(101) for _ in range(10)]
    result = compute_census("unfall", cells, columns=("Code",), record_count=1010)
    c = result[0]
    assert c.distinct_count == 101
    assert c.top_value_share < 0.01
    assert c.long_tail is True


def test_compute_census_does_not_flag_a_skewed_column_despite_many_distinct_values():
    """25 distinct values, but one dominates at ~88 % — not a long tail."""
    cells = [("Code", "DOMINANT")] * 900
    for i in range(24):
        cells += [("Code", f"v{i}")] * 5
    result = compute_census("unfall", cells, columns=("Code",), record_count=len(cells))
    c = result[0]
    assert c.distinct_count == 25
    assert c.top_value_share > 0.5
    assert c.long_tail is False


def test_compute_census_does_not_flag_a_column_with_few_distinct_values():
    """Only 3 distinct values: `distinct_count > 20` fails outright, however
    evenly the values are spread."""
    cells = [("Code", "a")] * 34 + [("Code", "b")] * 33 + [("Code", "c")] * 33
    result = compute_census("unfall", cells, columns=("Code",), record_count=100)
    c = result[0]
    assert c.distinct_count == 3
    assert c.long_tail is False
