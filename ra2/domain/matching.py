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

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Final

from ra2.domain.feature import MatchingRule, MatchingRuleKind, ValueType

__all__ = ["is_empty", "matches", "normalise"]

#: mvp-spec.md §8.4's "truthy mapping", spelled out. Codes first, because the
#: delivery is coded data: `1`/`0` is what a boolean column actually holds.
_TRUE: Final = frozenset({"1", "true", "t", "yes", "y", "ja", "oui", "si", "wahr", "vrai"})
_FALSE: Final = frozenset({"0", "false", "f", "no", "n", "nein", "non", "falsch", "faux"})

#: Thousands separators the delivery uses. The apostrophe is the Swiss one
#: (`1'250`), which is exactly the case a naive `int(value)` drops.
_SEPARATORS: Final = str.maketrans("", "", " '\u00a0\u2019_")

_WHITESPACE: Final = re.compile(r"\s+")

#: Stripped from both ends of free text, never from the middle: an inner
#: hyphen or apostrophe is part of the word.
_EDGE_PUNCTUATION: Final = " \t\r\n.,;:!?\"'()[]{}<>«»\u201c\u201d\u2018\u2019-\u2013\u2014/\\"


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
    return value is None or not value.strip()


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
    if is_empty(value):
        return None
    assert value is not None
    text = value.strip()
    match value_type:
        case ValueType.ENUM:
            # None — codes are compared as they stand. A code is an identifier,
            # and case-folding one would merge two codes the codelist separates.
            return text
        case ValueType.INTEGER:
            digits = text.translate(_SEPARATORS)
            try:
                return str(int(digits))
            except ValueError:
                return text
        case ValueType.DECIMAL:
            return _normalise_decimal(text, rule.decimal_precision)
        case ValueType.DATE:
            return _normalise_date(text)
        case ValueType.TIME:
            return _normalise_time(text)
        case ValueType.BOOLEAN:
            folded = text.casefold()
            if folded in _TRUE:
                return "true"
            if folded in _FALSE:
                return "false"
            return text
        case ValueType.FREE_TEXT:
            folded = unicodedata.normalize("NFKC", text).casefold()
            collapsed = _WHITESPACE.sub(" ", folded)
            stripped = collapsed.strip(_EDGE_PUNCTUATION)
            # Stripping edge punctuation can empty a value that was only
            # punctuation. It was not empty on the way in, so it must not
            # become `None` here — that would move the record out of the
            # denominator (§8.6) on a normalisation step.
            return stripped or collapsed.strip()
    raise AssertionError(f"unhandled value type: {value_type!r}")


def _normalise_decimal(text: str, precision: int | None) -> str:
    """Parse, round to the rule's precision, render canonically.

    `1.50` and `1.5` are the same number and must compare equal; `Decimal`
    rather than `float` because rounding 2.675 to two places is a worked
    example of why float rounding is not the rounding anyone means.
    """
    try:
        number = Decimal(text.translate(_SEPARATORS).replace(",", "."))
    except InvalidOperation:
        return text
    if precision is not None:
        number = round(number, precision)
    return f"{number.normalize():f}"


def _normalise_date(text: str) -> str:
    """`YYYYMMDD` -> ISO, per §8.4. An already-ISO value passes through."""
    digits = text.replace("-", "")
    if len(digits) == 8 and digits.isdigit():
        try:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:])).isoformat()
        except ValueError:
            return text
    return text


def _normalise_time(text: str) -> str:
    """`HH:MM` -> minutes since midnight, per §8.4.

    Minutes rather than a formatted string because the tolerance rule has to
    subtract them, and two representations of the same instant would otherwise
    compare unequal before the tolerance was ever applied.
    """
    parts = text.split(":")
    if len(parts) in (2, 3) and all(part.isdigit() for part in parts[:2]):
        hours, minutes = int(parts[0]), int(parts[1])
        if 0 <= hours < 24 and 0 <= minutes < 60:
            return str(hours * 60 + minutes)
    if text.isdigit() and len(text) == 4:
        hours, minutes = int(text[:2]), int(text[2:])
        if 0 <= hours < 24 and 0 <= minutes < 60:
            return str(hours * 60 + minutes)
    return text


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
    if is_empty(record_value) or is_empty(model_value):
        # Not this function's decision to make. `classify` has already sorted
        # empty record values out of the denominator (§8.6) and a null model
        # value into `MISSING`; reaching here with one means the caller asked
        # a question with no answer, and `False` is the only honest reply.
        return False
    left = normalise(record_value, value_type=value_type, rule=rule)
    right = normalise(model_value, value_type=value_type, rule=rule)
    if left is None or right is None:
        return False
    if (
        value_type is ValueType.TIME
        and rule.kind is MatchingRuleKind.WITHIN_TOLERANCE
        and rule.tolerance_minutes is not None
    ):
        # The one place §8.4 allows anything but equality, and it is a property
        # of the rule rather than a second matching mode.
        try:
            return abs(int(left) - int(right)) <= rule.tolerance_minutes
        except ValueError:
            return left == right
    return left == right
