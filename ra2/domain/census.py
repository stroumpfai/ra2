# FROZEN (types and signatures) — see CONTRACTS.md
"""Census types and the pure compute signature (mvp-spec.md §6, sw-design.md §7).

**M0 freezes the types and the two function signatures. A2 writes the bodies.**

The census is the input to feature selection: the vision's sparsity finding
means features are chosen by populated rate, not by what sounds interesting.
It runs over a corpus, needs no model and no GPU, and is materialised once at
freeze because a corpus is immutable (SD2).
"""

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
    raise NotImplementedError


def compute_buckets(columns: Iterable[ColumnCensus]) -> list[CensusBucket]:
    """Bucket columns by populated rate, over all tables at once.

    Boundaries are 100-80 / 80-60 / 60-40 / 40-20 / 20-0 / empty. `EMPTY` is
    `populated_count == 0` exactly, so it is separate from the 20-0 bucket
    rather than its bottom edge.

    :returns: one bucket per `BUCKET_ORDER` entry, in that order, including
        buckets whose count is zero.
    """
    raise NotImplementedError
