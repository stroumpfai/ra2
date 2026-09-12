# FROZEN (types and signatures) — see CONTRACTS.md
"""Feature configuration shapes (mvp-spec.md §8).

**Shape only, no evaluator** (plan-phase-2.md Q1). Derived-aggregate features
store `derivation_json` and nothing executes it in phase 2 — the Case C edit
zone shows a placeholder where the design shows a live number, and scoring
(phase 3) is what finally runs one of these.

`Kind`, `Grain`, `ValueType`, `MatchingRule` and the closed derivation
catalogue are declared here. `is_scalar_grain` / `requires_codelist` and the
rest of D2's validation helpers are Wave 1 additions to this same file —
Wave 0 declares only what `feature_service`'s and the API's typed signatures
need to exist today.
"""

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

__all__ = [
    "EXPLORATORY_FEATURE_CAP",
    "AnyObjectMatches",
    "AnyPersonMatches",
    "CountObjects",
    "CountPersons",
    "DerivationSpec",
    "DerivationType",
    "DistinctCount",
    "Filter",
    "Grain",
    "Kind",
    "MatchingRule",
    "MatchingRuleKind",
    "MaxOrdinal",
    "MinOrdinal",
    "Operator",
    "ValueType",
    "derivation_from_json",
    "derivation_to_json",
    "is_scalar_grain",
    "requires_codelist",
]

#: mvp-spec.md §8.1 — exploratory features are capped, never mixed into
#: Goal 1/2 aggregates.
EXPLORATORY_FEATURE_CAP: Final = 20


class Kind(StrEnum):
    """mvp-spec.md §8.1."""

    LABELLED = "labelled"
    EXPLORATORY = "exploratory"


class Grain(StrEnum):
    """mvp-spec.md §8.2. MVP admits scalars only for scoring; `OBJECT` and
    `PERSON` are captured, never scored."""

    ACCIDENT = "accident"
    DERIVED = "derived"
    OBJECT = "object"
    PERSON = "person"


class ValueType(StrEnum):
    """mvp-spec.md §8.4."""

    ENUM = "enum"
    INTEGER = "integer"
    DECIMAL = "decimal"
    DATE = "date"
    TIME = "time"
    BOOLEAN = "boolean"
    FREE_TEXT = "free_text"


class MatchingRuleKind(StrEnum):
    """The three shapes a matching rule takes (mvp-spec.md §8.4)."""

    EXACT = "exact"
    #: `time` only, mvp-spec.md §8.4's "exact, optional ± tolerance".
    WITHIN_TOLERANCE = "within_tolerance"
    #: Exploratory features: "n/a — no ground truth" (design, Case D).
    NONE = "none"


@dataclass(frozen=True, slots=True)
class MatchingRule:
    """A matching rule and its parameters, together — both travel in the
    fingerprint (mvp-spec.md §8.5: "matching_rule (incl. parameters...)")."""

    kind: MatchingRuleKind
    #: Minutes either side of the ground truth. Only meaningful for
    #: `WITHIN_TOLERANCE` on a `TIME` value type.
    tolerance_minutes: int | None = None
    #: Rounding precision before comparison. Only meaningful for `DECIMAL`.
    decimal_precision: int | None = None


class Operator(StrEnum):
    """mvp-spec.md §8.3's six operators, shared by every filterable derivation."""

    EQ = "eq"
    NE = "ne"
    IN = "in"
    NOT_IN = "not_in"
    IS_EMPTY = "is_empty"
    IS_NOT_EMPTY = "is_not_empty"


@dataclass(frozen=True, slots=True)
class Filter:
    """`(column, op, value)` — one derivation's optional or required filter.

    `value` is `None` for `IS_EMPTY` / `IS_NOT_EMPTY`, a single string for
    `EQ` / `NE`, and a tuple for `IN` / `NOT_IN`.
    """

    column: str
    operator: Operator
    value: str | tuple[str, ...] | None = None


class DerivationType(StrEnum):
    """mvp-spec.md §8.3's closed catalogue — the discriminator stored in
    `derivation_json` and shown in the design's mono expression."""

    COUNT_OBJECTS = "count_objects"
    COUNT_PERSONS = "count_persons"
    ANY_OBJECT_MATCHES = "any_object_matches"
    ANY_PERSON_MATCHES = "any_person_matches"
    MAX_ORDINAL = "max_ordinal"
    MIN_ORDINAL = "min_ordinal"
    DISTINCT_COUNT = "distinct_count"


@dataclass(frozen=True, slots=True)
class CountObjects:
    """Result: integer. `filter=None` counts every `objekt` row."""

    filter: Filter | None = None


@dataclass(frozen=True, slots=True)
class CountPersons:
    """Result: integer. `filter=None` counts every `person` row."""

    filter: Filter | None = None


@dataclass(frozen=True, slots=True)
class AnyObjectMatches:
    """Result: boolean."""

    filter: Filter


@dataclass(frozen=True, slots=True)
class AnyPersonMatches:
    """Result: boolean."""

    filter: Filter


@dataclass(frozen=True, slots=True)
class MaxOrdinal:
    """Result: code. `table` is `objekt` or `person`."""

    table: str
    column: str
    ordered_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MinOrdinal:
    """Result: code. `table` is `objekt` or `person`."""

    table: str
    column: str
    ordered_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DistinctCount:
    """Result: integer. `table` is `objekt` or `person`."""

    table: str
    column: str


#: What `derivation_json` deserialises to. `DerivationType` is the wire/storage
#: discriminator between these seven shapes.
DerivationSpec = (
    CountObjects
    | CountPersons
    | AnyObjectMatches
    | AnyPersonMatches
    | MaxOrdinal
    | MinOrdinal
    | DistinctCount
)


# ---------------------------------------------------------------------------
# Wave 1 additions (D2) — validation helpers and the derivation_json codec.
# ---------------------------------------------------------------------------


def is_scalar_grain(grain: Grain) -> bool:
    """mvp-spec.md §8.2: `ACCIDENT` and `DERIVED` are scalar and scored;
    `OBJECT` and `PERSON` are captured only. A `Kind.LABELLED` feature at a
    non-scalar grain is a validation error (design's "Damage per vehicle ·
    non-scalar ERROR" row)."""
    return grain in (Grain.ACCIDENT, Grain.DERIVED)


def requires_codelist(value_type: ValueType) -> bool:
    """mvp-spec.md §8.4: only an `enum` feature needs a code table, and that
    table always comes from Codelists — never an inline list typed into the
    feature config."""
    return value_type is ValueType.ENUM


#: Canonical, lossless JSON — matches the `*_json` column convention (M0-D8):
#: the application controls key order and separators, `ensure_ascii=False` so
#: label text round-trips as text, not `\uXXXX` escapes.
_JSON_KWARGS: Final = {"sort_keys": True, "separators": (",", ":"), "ensure_ascii": False}


def _filter_to_dict(filter_: Filter) -> dict[str, object]:
    """`Filter.value` is `None`, a `str`, or a `tuple[str, ...]` — JSON tells
    those three apart natively (`null`, a string, a list), so no extra tagging
    is needed to make the round trip lossless."""
    value: object
    if isinstance(filter_.value, tuple):
        value = list(filter_.value)
    else:
        value = filter_.value
    return {"column": filter_.column, "operator": filter_.operator.value, "value": value}


def _filter_from_dict(payload: object) -> Filter:
    if not isinstance(payload, dict):
        raise ValueError(f"Filter payload must be a JSON object: {payload!r}")
    raw_value = payload["value"]
    value: str | tuple[str, ...] | None
    if isinstance(raw_value, list):
        value = tuple(str(item) for item in raw_value)
    elif raw_value is None:
        value = None
    else:
        value = str(raw_value)
    return Filter(
        column=str(payload["column"]),
        operator=Operator(str(payload["operator"])),
        value=value,
    )


def _str_tuple_from(payload: object) -> tuple[str, ...]:
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON array of codes: {payload!r}")
    return tuple(str(item) for item in payload)


def derivation_to_json(derivation: DerivationSpec) -> str:
    """Serialise one of the seven derivation shapes to the canonical JSON
    string stored in `feature.derivation_json`.

    Carries a `type` discriminator (the matching `DerivationType.value`) plus
    that shape's own fields. `derivation_from_json` is the exact inverse.
    """
    payload: dict[str, object]
    if isinstance(derivation, CountObjects):
        payload = {
            "type": DerivationType.COUNT_OBJECTS.value,
            "filter": _filter_to_dict(derivation.filter) if derivation.filter is not None else None,
        }
    elif isinstance(derivation, CountPersons):
        payload = {
            "type": DerivationType.COUNT_PERSONS.value,
            "filter": _filter_to_dict(derivation.filter) if derivation.filter is not None else None,
        }
    elif isinstance(derivation, AnyObjectMatches):
        payload = {
            "type": DerivationType.ANY_OBJECT_MATCHES.value,
            "filter": _filter_to_dict(derivation.filter),
        }
    elif isinstance(derivation, AnyPersonMatches):
        payload = {
            "type": DerivationType.ANY_PERSON_MATCHES.value,
            "filter": _filter_to_dict(derivation.filter),
        }
    elif isinstance(derivation, MaxOrdinal):
        payload = {
            "type": DerivationType.MAX_ORDINAL.value,
            "table": derivation.table,
            "column": derivation.column,
            "ordered_codes": list(derivation.ordered_codes),
        }
    elif isinstance(derivation, MinOrdinal):
        payload = {
            "type": DerivationType.MIN_ORDINAL.value,
            "table": derivation.table,
            "column": derivation.column,
            "ordered_codes": list(derivation.ordered_codes),
        }
    elif isinstance(derivation, DistinctCount):
        payload = {
            "type": DerivationType.DISTINCT_COUNT.value,
            "table": derivation.table,
            "column": derivation.column,
        }
    else:
        raise TypeError(f"Not a DerivationSpec: {derivation!r}")
    return json.dumps(payload, **_JSON_KWARGS)  # type: ignore[arg-type]


def derivation_from_json(payload: str) -> DerivationSpec:
    """The exact inverse of `derivation_to_json`."""
    data: dict[str, object] = json.loads(payload)
    derivation_type = DerivationType(str(data["type"]))
    if derivation_type is DerivationType.COUNT_OBJECTS:
        raw_filter = data["filter"]
        return CountObjects(
            filter=_filter_from_dict(raw_filter) if raw_filter is not None else None
        )
    if derivation_type is DerivationType.COUNT_PERSONS:
        raw_filter = data["filter"]
        return CountPersons(
            filter=_filter_from_dict(raw_filter) if raw_filter is not None else None
        )
    if derivation_type is DerivationType.ANY_OBJECT_MATCHES:
        return AnyObjectMatches(filter=_filter_from_dict(data["filter"]))
    if derivation_type is DerivationType.ANY_PERSON_MATCHES:
        return AnyPersonMatches(filter=_filter_from_dict(data["filter"]))
    if derivation_type is DerivationType.MAX_ORDINAL:
        return MaxOrdinal(
            table=str(data["table"]),
            column=str(data["column"]),
            ordered_codes=_str_tuple_from(data["ordered_codes"]),
        )
    if derivation_type is DerivationType.MIN_ORDINAL:
        return MinOrdinal(
            table=str(data["table"]),
            column=str(data["column"]),
            ordered_codes=_str_tuple_from(data["ordered_codes"]),
        )
    if derivation_type is DerivationType.DISTINCT_COUNT:
        return DistinctCount(table=str(data["table"]), column=str(data["column"]))
    raise ValueError(
        f"Unknown derivation type: {derivation_type!r}"
    )  # pragma: no cover - closed enum
