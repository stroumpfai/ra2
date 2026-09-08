# FROZEN (types and signatures) — see CONTRACTS.md
"""Census types and the pure compute signature (mvp-spec.md §6, sw-design.md §7).

**M0 freezes the types and the two function signatures. A2 writes the bodies.**

The census is the input to feature selection: the vision's sparsity finding
means features are chosen by populated rate, not by what sounds interesting.
It runs over a corpus, needs no model and no GPU, and is materialised once at
freeze because a corpus is immutable (SD2).
"""

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

__all__ = [
    "BUCKET_ORDER",
    "LONG_TAIL_MAX_TOP_SHARE",
    "LONG_TAIL_MIN_DISTINCT",
    "TOP_VALUES_STORED",
    "CensusBucket",
    "CensusBucketLabel",
    "ColumnCensus",
    "TypeHint",
    "ValueCount",
    "compute_buckets",
    "compute_census",
]

#: mvp-spec.md §6: "top 20 values with frequencies". 20 are stored; the Census
#: view shows the top 4 as bar segments and the top 3 in the legend
#: (sw-design.md §7).
TOP_VALUES_STORED: Final = 20

#: SD8. The design states the rendering ("long tail · 1 461 distinct, no value
#: over 1 %"); these are the thresholds behind it.
LONG_TAIL_MIN_DISTINCT: Final = 20
LONG_TAIL_MAX_TOP_SHARE: Final = 0.01


class TypeHint(StrEnum):
    """Inferred column type (sw-design.md §7).

    The `Ausw`/`Feld` suffix rule runs **first**; value-shape inspection only
    decides what the suffix leaves open. An `Ausw` column is `ENUM` even when
    every value happens to look like an integer.
    """

    ENUM = "enum"
    DATE = "date"
    TIME = "time"
    INTEGER = "integer"
    DECIMAL = "decimal"
    TEXT = "text"


class CensusBucketLabel(StrEnum):
    """The six population-profile buckets, over all tables (sw-design.md §7).

    Values are stable identifiers; the "100–80 %" rendering lives in `ra2/ui/`.
    """

    P100_80 = "100-80"
    P80_60 = "80-60"
    P60_40 = "60-40"
    P40_20 = "40-20"
    P20_0 = "20-0"
    EMPTY = "empty"


#: Display order of the profile card, left to right.
BUCKET_ORDER: Final = (
    CensusBucketLabel.P100_80,
    CensusBucketLabel.P80_60,
    CensusBucketLabel.P60_40,
    CensusBucketLabel.P40_20,
    CensusBucketLabel.P20_0,
    CensusBucketLabel.EMPTY,
)


@dataclass(frozen=True, slots=True)
class ValueCount:
    """One of a column's top values."""

    value_raw: str
    count: int
    #: `count / populated_count`, in [0, 1].
    share: float


@dataclass(frozen=True, slots=True)
class ColumnCensus:
    """One source column profiled over one corpus."""

    table_name: str
    column_name: str
    type_hint: TypeHint
    #: Corpus record count — the denominator. Every column of a table shares it,
    #: including a column that is empty in every row (h08).
    record_count: int
    #: Populated = **non-empty string**. Empty means *no value provided*, never
    #: "not applicable" (mvp-spec.md §6, §8.6).
    populated_count: int
    populated_rate: float
    distinct_count: int
    #: Top 20, most frequent first.
    top_values: tuple[ValueCount, ...]
    #: `top_values[0].share` if any, else 0.0. Stored so the UI never recomputes.
    top_value_share: float
    #: SD8: `distinct_count > 20 and top_value_share < 0.01`. Stored, not derived
    #: at render time.
    long_tail: bool


@dataclass(frozen=True, slots=True)
class CensusBucket:
    """One bar of the "Population profile · all tables" card."""

    label: CensusBucketLabel
    column_count: int


def _is_long_tail(distinct_count: int, top_value_share: float) -> bool:
    """SD8: `distinct_count > 20 and top_value_share < 0.01`.

    Pulled out of `compute_census` so the boundary itself — not just an
    end-to-end census over synthesised cells — has a direct test. The two
    thresholds are not independent in real data (with only `N` distinct
    values, the most frequent one holds at least `1/N` of the total, so
    `top_value_share < 0.01` is unreachable below roughly 100 distinct
    values); testing this predicate directly lets each threshold's boundary
    be asserted on its own terms regardless of that coupling.
    """
    return distinct_count > LONG_TAIL_MIN_DISTINCT and top_value_share < LONG_TAIL_MAX_TOP_SHARE


def compute_census(
    table_name: str,
    cells: Iterable[tuple[str, str]],
    *,
    columns: Sequence[str],
    record_count: int,
    top_n: int = TOP_VALUES_STORED,
) -> list[ColumnCensus]:
    """Profile every column of one table. Pure: no DB, no I/O, no files.

    :param table_name: `unfall`, `objekt` or `person`.
    :param cells: every stored cell of the table as `(column_name, value_raw)`.
        Streamed, so this may be a generator over EAV rows.
    :param columns: the table's canonical header, in header order. Passed
        explicitly so a column that is empty in **every** row still appears at
        0 % rather than vanishing from an EAV scan (h08).
    :param record_count: the corpus record count — the denominator for
        `populated_rate`. For `objekt`/`person` this is still the *record*
        count, so a rate is comparable across tables.
    :param top_n: how many top values to keep.
    :returns: one `ColumnCensus` per entry in `columns`, in `columns` order.
    """
    counters: dict[str, Counter[str]] = {column: Counter() for column in columns}
    for column_name, value_raw in cells:
        counter = counters.get(column_name)
        if counter is None:
            # A cell for a column outside the canonical header. `columns` is
            # the header of record (M0-D9); a cell that disagrees with it is
            # not this function's data-quality problem to raise on, so it is
            # excluded from every denominator rather than crashing the census.
            continue
        if value_raw == "":
            # Populated = non-empty string (mvp-spec.md §8.6). An empty cell
            # still exists as a row, but never counts towards population,
            # distinctness or the top values.
            continue
        counter[value_raw] += 1

    results: list[ColumnCensus] = []
    for column_name in columns:
        counter = counters[column_name]
        populated_count = sum(counter.values())
        distinct_count = len(counter)
        populated_rate = populated_count / record_count if record_count else 0.0
        top_values = tuple(
            ValueCount(value_raw=value, count=count, share=count / populated_count)
            for value, count in counter.most_common(top_n)
        )
        top_value_share = top_values[0].share if top_values else 0.0
        long_tail = _is_long_tail(distinct_count, top_value_share)
        results.append(
            ColumnCensus(
                table_name=table_name,
                column_name=column_name,
                type_hint=_infer_type_hint(column_name, counter.keys()),
                record_count=record_count,
                populated_count=populated_count,
                populated_rate=populated_rate,
                distinct_count=distinct_count,
                top_values=top_values,
                top_value_share=top_value_share,
                long_tail=long_tail,
            )
        )
    return results


def compute_buckets(columns: Iterable[ColumnCensus]) -> list[CensusBucket]:
    """Bucket columns by populated rate, over all tables at once.

    Boundaries are 100-80 / 80-60 / 60-40 / 40-20 / 20-0 / empty. `EMPTY` is
    `populated_count == 0` exactly, so it is separate from the 20-0 bucket
    rather than its bottom edge.

    :returns: one bucket per `BUCKET_ORDER` entry, in that order, including
        buckets whose count is zero.
    """
    counts: dict[CensusBucketLabel, int] = dict.fromkeys(BUCKET_ORDER, 0)
    for column in columns:
        counts[_bucket_label_for(column)] += 1
    return [CensusBucket(label=label, column_count=counts[label]) for label in BUCKET_ORDER]


def _bucket_label_for(column: ColumnCensus) -> CensusBucketLabel:
    """Each non-empty bucket is `(lower, upper]` of `populated_rate`, so a
    column sitting exactly on a boundary (80 %, 60 %, ...) belongs to the
    bucket above it. `populated_count == 0` is `EMPTY` regardless of the rate
    (h08: an all-empty column is 0.0, not "20-0")."""
    if column.populated_count == 0:
        return CensusBucketLabel.EMPTY
    rate = column.populated_rate
    if rate <= 0.20:
        return CensusBucketLabel.P20_0
    if rate <= 0.40:
        return CensusBucketLabel.P40_20
    if rate <= 0.60:
        return CensusBucketLabel.P60_40
    if rate <= 0.80:
        return CensusBucketLabel.P80_60
    return CensusBucketLabel.P100_80


# --- type-hint inference ----------------------------------------------------
#
# Lives here, not in typehint.py: `typehint.infer_type_hint` already imports
# `TypeHint` from this module, and `compute_census` above needs the same
# inference to fill in `ColumnCensus.type_hint`. Making this module import
# from `typehint` too would be a cycle, so the one shared implementation sits
# on the side of the dependency that has nothing importing it back, and
# `typehint.infer_type_hint` is a thin public wrapper over it (sw-design.md
# §7, mvp-spec.md §6).

#: `unfall`/`objekt`/`person` columns ending in `Ausw` are enum-coded. This
#: check runs before any value-shape inspection and always wins when they
#: would disagree.
_ENUM_SUFFIX = "Ausw"

#: `YYYYMMDD`, digits only. Calendar-range plausibility is checked separately
#: so `00000000` or `99999999` do not pass as dates.
_DATE_PATTERN = re.compile(r"^\d{8}$")

#: `HH:MM`, zero-padded 24-hour clock plus minutes.
_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

#: Plausible calendar range for the delivered data. Generous on purpose: this
#: is a type-hint heuristic, not a validation rule.
_MIN_YEAR = 1900
_MAX_YEAR = 2100


def _is_plausible_date(value: str) -> bool:
    if not _DATE_PATTERN.match(value):
        return False
    year, month, day = int(value[0:4]), int(value[4:6]), int(value[6:8])
    if not (_MIN_YEAR <= year <= _MAX_YEAR):
        return False
    if not (1 <= month <= 12):
        return False
    return 1 <= day <= 31


def _is_time(value: str) -> bool:
    return bool(_TIME_PATTERN.match(value))


def _is_integer(value: str) -> bool:
    if "." in value:
        return False
    try:
        int(value)
    except ValueError:
        return False
    return True


def _is_decimal(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _infer_type_hint(column_name: str, values: Iterable[str]) -> TypeHint:
    """The suffix rule, then value-shape inspection. See `typehint.py`."""
    if column_name.endswith(_ENUM_SUFFIX):
        return TypeHint.ENUM

    populated = [value for value in values if value != ""]
    if not populated:
        return TypeHint.TEXT

    if all(_is_plausible_date(value) for value in populated):
        return TypeHint.DATE
    if all(_is_time(value) for value in populated):
        return TypeHint.TIME
    if all(_is_integer(value) for value in populated):
        return TypeHint.INTEGER
    if all(_is_decimal(value) for value in populated):
        return TypeHint.DECIMAL
    return TypeHint.TEXT
