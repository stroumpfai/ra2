"""`ra2.domain.census.compute_buckets` (mvp-spec.md §6, sw-design.md §7).

Six population-profile buckets over all tables at once: 100-80 / 80-60 /
60-40 / 40-20 / 20-0 / empty. `EMPTY` is `populated_count == 0` exactly — a
column that is empty in every row lands there, never in `20-0` (h08).
"""

import pytest

from ra2.domain.census import (
    BUCKET_ORDER,
    CensusBucketLabel,
    ColumnCensus,
    TypeHint,
    compute_buckets,
)

pytestmark = pytest.mark.unit


def _column(*, populated_count: int, record_count: int = 100) -> ColumnCensus:
    return ColumnCensus(
        table_name="unfall",
        column_name="col",
        type_hint=TypeHint.TEXT,
        record_count=record_count,
        populated_count=populated_count,
        populated_rate=populated_count / record_count if record_count else 0.0,
        distinct_count=min(populated_count, 1),
        top_values=(),
        top_value_share=0.0,
        long_tail=False,
    )


def test_buckets_are_returned_in_display_order_including_zero_counts():
    result = compute_buckets([])
    assert [b.label for b in result] == list(BUCKET_ORDER)
    assert all(b.column_count == 0 for b in result)


def test_an_all_empty_column_lands_in_the_empty_bucket_not_20_0():
    """h08: `populated_count == 0` is `EMPTY`, never the bottom edge of `20-0`."""
    columns = [_column(populated_count=0)]
    result = {b.label: b.column_count for b in compute_buckets(columns)}
    assert result[CensusBucketLabel.EMPTY] == 1
    assert result[CensusBucketLabel.P20_0] == 0


@pytest.mark.parametrize(
    ("populated_count", "expected_label"),
    [
        (100, CensusBucketLabel.P100_80),  # 100 %
        (81, CensusBucketLabel.P100_80),  # just above 80 %
        (80, CensusBucketLabel.P80_60),  # boundary belongs to the bucket above it
        (61, CensusBucketLabel.P80_60),
        (60, CensusBucketLabel.P60_40),
        (41, CensusBucketLabel.P60_40),
        (40, CensusBucketLabel.P40_20),
        (21, CensusBucketLabel.P40_20),
        (20, CensusBucketLabel.P20_0),
        (1, CensusBucketLabel.P20_0),  # just above 0 %, not empty
        (0, CensusBucketLabel.EMPTY),
    ],
)
def test_boundary_values_land_in_the_expected_bucket(populated_count, expected_label):
    columns = [_column(populated_count=populated_count)]
    result = {b.label: b.column_count for b in compute_buckets(columns)}
    assert result[expected_label] == 1
    assert sum(result.values()) == 1


def test_buckets_column_counts_across_multiple_tables():
    columns = [
        _column(populated_count=100),  # 100-80
        _column(populated_count=90),  # 100-80
        _column(populated_count=70),  # 80-60
        _column(populated_count=0),  # empty
        _column(populated_count=0),  # empty
    ]
    result = {b.label: b.column_count for b in compute_buckets(columns)}
    assert result[CensusBucketLabel.P100_80] == 2
    assert result[CensusBucketLabel.P80_60] == 1
    assert result[CensusBucketLabel.P60_40] == 0
    assert result[CensusBucketLabel.P40_20] == 0
    assert result[CensusBucketLabel.P20_0] == 0
    assert result[CensusBucketLabel.EMPTY] == 2
