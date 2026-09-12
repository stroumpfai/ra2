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
