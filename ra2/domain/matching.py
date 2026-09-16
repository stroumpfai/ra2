# FROZEN (types and signatures) — see CONTRACTS.md
"""Normalisation and matching (mvp-spec.md §8.4, §8.6).

Phase 2 stored the `MatchingRule` shape and never compared two values with it.
This is where the comparison lives: one normalisation per value type, then
equality, and **nothing else**.

**Free-text matching is deliberately strict** (`D6`). Fuzzy thresholds and
LLM-as-judge are deferred (§16) because both need a threshold that can be
defended, and defending one wants the real numbers this phase is the first to
produce. **Accent folding is off** for the same reason and one more: §8.4 flags
it as "worth evaluating, because it interacts with §4.4 damage", and turning it
on before the evaluation would decide the question by assuming the answer.

`is_empty` is the smallest and most consequential function in the phase. It is
`mvp-spec.md` §8.6 — *"a record whose column is empty is excluded from that
feature's denominator **entirely**"* — and §16.2 tabulates its three plausible
wrong readings, all of which produce numbers.

Pure — no SQLAlchemy, no session (sw-design.md §16.8).

**M27 freezes the signatures. S2 writes the bodies.**
"""

from ra2.domain.feature import MatchingRule, ValueType

__all__ = ["is_empty", "matches", "normalise"]


def is_empty(value: str | None) -> bool:
    """`mvp-spec.md` §8.6's predicate: no value was provided.

    `None`, the empty string, or whitespace only. Note what it is **not**: it
    is not "zero", not "false", and not "a value that failed to parse". §8.6 is
    explicit that the data cannot distinguish "empty" from "not applicable",
    which is why an empty cell leaves the denominator rather than counting as a
    `MISSING` the model failed to find.

    The distinction that catches people is the derived one: `count_objects`
    over a record with **zero objects** is `"0"`, and `is_empty("0")` is
    `False`. "No objects" is a fact the data states; "no value" is a fact the
    data is missing.
    """
    raise NotImplementedError


def normalise(value: str | None, *, value_type: ValueType, rule: MatchingRule) -> str | None:
    """One value in its canonical comparable form — `mvp-spec.md` §8.4's table.

    | Type | Normalisation |
    |---|---|
    | `ENUM` | none — codes are compared as they stand |
    | `INTEGER` | strip thousands separators and surrounding whitespace |
    | `DECIMAL` | parse, round to `rule`'s precision, render canonically |
    | `DATE` | `YYYYMMDD` -> ISO `YYYY-MM-DD` |
    | `TIME` | `HH:MM` -> minutes since midnight |
    | `BOOLEAN` | truthy mapping |
    | `FREE_TEXT` | NFKC -> casefold -> collapse whitespace -> strip edge punctuation |

    Returns `None` **only** for an input `is_empty` accepts — never for one
    that failed to parse. That asymmetry is deliberate and it is a §8.6
    consequence: a `None` here means "not a labelled case", so mapping an
    unparseable `"abc"` in an integer column to `None` would quietly delete a
    record from the denominator instead of scoring it. An unparseable value
    normalises to its whitespace-trimmed self, which simply does not compare
    equal to a parsed one — unless the other side says `"abc"` too, in which
    case the model read the record correctly and a hit is the right answer.

    `rule` carries the parameters §8.4 leaves open: decimal precision and the
    optional `TIME` tolerance.
    """
    raise NotImplementedError


def matches(
    record_value: str | None,
    model_value: str | None,
    *,
    value_type: ValueType,
    rule: MatchingRule,
) -> bool:
    """Do these two values agree, under `rule`?

    Both sides go through `normalise` and are compared for **equality**. The
    only exception the spec allows is `TIME`'s optional tolerance, which is a
    property of the rule rather than a second matching mode.

    **The structured record is fully authoritative** (mvp-spec.md §12): this
    function never adjudicates, never prefers the model's reading, and has no
    notion of a value being "close enough". A disagreement is a `WRONG`, and
    whether the record or the model was right is a question for the mismatch
    list, not for this function.
    """
    raise NotImplementedError
