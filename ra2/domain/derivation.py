# FROZEN (types and signatures) — see CONTRACTS.md
"""The derived-aggregate evaluator (mvp-spec.md §8.3).

**This module is `plan-phase-2.md` Q1's deferral coming due.** Phase 2 stored
`derivation_json` and declined to execute it, on the explicit reasoning that
"scoring (phase 3) needs to build one anyway — building it twice is waste".
Phase 3 did not need it: a derivation reaches a prompt as a *description*.
Scoring needs it, because a derived feature's **ground truth does not exist
anywhere** until something computes it (sw-design.md §16.2).

It is pure, and it takes a `RecordProjection` rather than a session: the closed
catalogue is testable without a database, and the EAV read stays in
`persistence/` where §1.1 requires it.

Pure — no SQLAlchemy, no session (sw-design.md §16.8).

**M27 freezes the types and the signature. S3 writes the bodies.**
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from ra2.domain.feature import (
    AnyObjectMatches,
    AnyPersonMatches,
    CountObjects,
    CountPersons,
    DerivationSpec,
    DistinctCount,
    Filter,
    MaxOrdinal,
    MinOrdinal,
    Operator,
)

__all__ = ["DerivationError", "RecordProjection", "evaluate"]


@dataclass(frozen=True, slots=True)
class RecordProjection:
    """One record's `objekt` and `person` cells, as plain data.

    One mapping per row, `column_name -> value_raw`. A column absent from a
    mapping and a column present with an empty value are treated **alike** —
    `IS_EMPTY` is true for both and every comparison is false for both —
    because the delivery cannot distinguish them either (mvp-spec.md §8.6:
    empty means "no value was provided", and the data cannot tell that from
    "not applicable"). What matters is the other half: **nothing invents a
    value for a missing column**, so a filter on a column this delivery does
    not carry matches no rows rather than matching all of them.

    *(M27 wrote this paragraph claiming the two were treated differently and
    then described identical treatment for both. Corrected by S3 in the same
    commit, per CLAUDE.md.)*

    `person_rows` are flattened across their parent `objekt` rows. `person`
    hangs off `objekt`, never off `unfall` (mvp-spec.md §4.1), but no
    derivation in the catalogue reaches across that edge: `count_persons` and
    `any_person_matches` are record-wide, so carrying the tree here would be
    structure nothing reads.
    """

    objekt_rows: Sequence[Mapping[str, str]]
    person_rows: Sequence[Mapping[str, str]]


class DerivationError(Exception):
    """A derivation that cannot be evaluated against this projection.

    The one case that reaches it in practice is an ordinal whose observed code
    is absent from `ordered_codes` — the feature config declared an ordering
    and the data contains something outside it. That is a **configuration**
    fault, not a record fault, so it raises rather than resolving to `None`:
    silently skipping the row would drop a record from the denominator and make
    a feature look better measured than it is (Do-NOT #6's reasoning, applied
    to ground truth).
    """


def evaluate(derivation: DerivationSpec, projection: RecordProjection) -> str | None:
    """This record's ground-truth value for one derived feature.

    Returns a **string**, because that is what it is compared against:
    `extraction_value.value_normalised` is a string, and `domain/matching.py`
    normalises both sides the same way. Counts render as decimal integers,
    booleans as `"true"` / `"false"`, ordinals as the code itself.

    Returns `None` only when the derivation genuinely has no value for this
    record — `MAX_ORDINAL` over a record with no rows in the named table. That
    `None` means "not a labelled case" and the record leaves the denominator,
    exactly as an empty source column does (§8.6).

    **A count over zero rows is `"0"`, not `None`.** It is the single most
    consequential line in this module: "no objects" is a fact the data states
    and belongs in the denominator, while "no value" is a fact the data is
    missing and does not. Getting it backwards changes every derived feature's
    `n` (sw-design.md §16.2).

    Raises `DerivationError` for a configuration fault; never for a data one.
    """
    match derivation:
        case CountObjects(filter=row_filter):
            return str(_count(projection.objekt_rows, row_filter))
        case CountPersons(filter=row_filter):
            return str(_count(projection.person_rows, row_filter))
        case AnyObjectMatches(filter=row_filter):
            return _BOOLEAN[_count(projection.objekt_rows, row_filter) > 0]
        case AnyPersonMatches(filter=row_filter):
            return _BOOLEAN[_count(projection.person_rows, row_filter) > 0]
        case MaxOrdinal(table=table, column=column, ordered_codes=codes):
            return _extreme(projection, table, column, codes, pick=max)
        case MinOrdinal(table=table, column=column, ordered_codes=codes):
            return _extreme(projection, table, column, codes, pick=min)
        case DistinctCount(table=table, column=column):
            rows = _rows_for(projection, table)
            present = {value for row in rows if not _is_blank(value := row.get(column))}
            return str(len(present))
    # `DerivationSpec` is a closed union of exactly seven shapes, so this is
    # unreachable through the type system. It is here because `derivation_json`
    # is data on disk: a row written by a future catalogue entry must fail
    # loudly rather than score as zero.
    raise DerivationError(f"unknown derivation shape: {type(derivation).__name__}")


#: Booleans render as the strings `matching.normalise` compares, so a derived
#: boolean and a model's `true` meet on the same ground.
_BOOLEAN: Final = {True: "true", False: "false"}

_TABLES: Final = ("objekt", "person")


def _is_blank(value: str | None) -> bool:
    """A missing column and a blank cell are alike here — see
    `RecordProjection`. Kept separate from `matching.is_empty` deliberately:
    that one answers a question about a *record's* ground truth, this one about
    a *cell* inside a derivation, and collapsing them would couple the
    catalogue to the matching rules."""
    return value is None or not value.strip()


def _rows_for(projection: RecordProjection, table: str) -> Sequence[Mapping[str, str]]:
    if table == "objekt":
        return projection.objekt_rows
    if table == "person":
        return projection.person_rows
    raise DerivationError(f"derivation names table {table!r}; expected one of {_TABLES}")


def _matches(row: Mapping[str, str], row_filter: Filter) -> bool:
    """One row against one `(column, operator, value)` — mvp-spec.md §8.3's
    six operators and nothing else."""
    value = row.get(row_filter.column)
    match row_filter.operator:
        case Operator.IS_EMPTY:
            return _is_blank(value)
        case Operator.IS_NOT_EMPTY:
            return not _is_blank(value)
        case Operator.EQ:
            return value is not None and value == row_filter.value
        case Operator.NE:
            # A missing column is not a value that differs — it is no value at
            # all, and `NE` must not quietly count every row that lacks the
            # column as a match.
            return value is not None and value != row_filter.value
        case Operator.IN:
            return value is not None and value in _as_tuple(row_filter.value)
        case Operator.NOT_IN:
            return value is not None and value not in _as_tuple(row_filter.value)
    raise DerivationError(f"unknown operator: {row_filter.operator!r}")


def _as_tuple(value: str | tuple[str, ...] | None) -> tuple[str, ...]:
    if isinstance(value, tuple):
        return value
    if value is None:
        return ()
    return (value,)


def _count(rows: Sequence[Mapping[str, str]], row_filter: Filter | None) -> int:
    """`filter=None` counts every row — mvp-spec.md §8.3."""
    if row_filter is None:
        return len(rows)
    return sum(1 for row in rows if _matches(row, row_filter))


def _extreme(
    projection: RecordProjection,
    table: str,
    column: str,
    ordered_codes: tuple[str, ...],
    *,
    pick: Callable[[Iterable[int]], int],
) -> str | None:
    """The highest or lowest observed code, by the config's declared order.

    A code the config did not order **raises**: the feature config declared an
    ordering and the data contains something outside it, which is a
    configuration fault rather than a record fault. Skipping the row silently
    would drop a record from the denominator and make the feature look better
    measured than it is (Do-NOT #6's reasoning, applied to ground truth).
    """
    rows = _rows_for(projection, table)
    positions: list[int] = []
    for row in rows:
        value = row.get(column)
        if _is_blank(value):
            continue
        assert value is not None
        try:
            positions.append(ordered_codes.index(value))
        except ValueError:
            raise DerivationError(
                f"code {value!r} in {table}.{column} is absent from the "
                f"configured ordering {ordered_codes!r}"
            ) from None
    if not positions:
        # No rows, or none carrying this column: the derivation genuinely has
        # no value here, and the record leaves the denominator (§8.6). Note
        # this is NOT what a count does — `_count` over zero rows is 0, which
        # is a value the data states.
        return None
    return ordered_codes[pick(positions)]
