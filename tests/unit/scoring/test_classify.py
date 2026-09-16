"""`domain.scoring.classify` — mvp-spec.md §11.1 and §8.6.

The §8.6 rule has three plausible wrong readings and **all three produce
numbers** (sw-design.md §16.2). This file pins the right one at the layer where
the distinction is first made.
"""

import pytest

from ra2.domain.feature import MatchingRule, MatchingRuleKind, ValueType
from ra2.domain.scoring import Outcome, classify

EXACT = MatchingRule(kind=MatchingRuleKind.EXACT)


def call(record: str | None, model: str | None) -> Outcome | None:
    return classify(record, model, value_type=ValueType.ENUM, rule=EXACT)


def test_a_matching_value_is_a_hit():
    assert call("3", "3") is Outcome.HIT


def test_a_non_matching_value_is_wrong():
    assert call("3", "4") is Outcome.WRONG


def test_a_null_model_value_is_missing():
    assert call("3", None) is Outcome.MISSING
    assert call("3", "") is Outcome.MISSING


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_an_empty_record_value_is_not_a_labelled_case(empty):
    """**`None`, not `MISSING`.**

    §8.6: "a record whose column is empty is excluded from that feature's
    denominator **entirely**". The model was never asked a question that had an
    answer. Returning `MISSING` is the wrong reading that still produces
    numbers: it would inflate the denominator and depress recall for every
    feature the delivery populates sparsely — which is most of them.
    """
    assert call(empty, "3") is None


def test_an_empty_record_value_is_not_a_labelled_case_even_when_the_model_is_silent_too():
    """Both sides empty is still not a case. There is nothing to score."""
    assert call("", None) is None


def test_a_zero_record_value_is_a_labelled_case():
    """`"0"` is a measurement, not an absence — and a derived `count_objects`
    over a record with no objects produces exactly this."""
    assert call("0", "0") is Outcome.HIT
    assert call("0", "1") is Outcome.WRONG


def test_the_outcome_vocabulary_has_exactly_three_members():
    """The vision names a fourth, `hallucinated`. **The MVP cannot compute it**
    (`D1`): distinguishing a hallucination from a misread means adjudicating
    whether an evidence span supports a value. It is a review tag on the
    mismatch list, never an `Outcome`, and a report must not present a
    hallucination rate as if it were measured."""
    assert {o.value for o in Outcome} == {"hit", "wrong", "missing"}


def test_classification_respects_the_value_types_normalisation():
    """`classify` does not compare strings itself — it asks `matching`, so a
    `1'250` in the record and a `1250` from the model is a hit."""
    assert classify("1'250", "1250", value_type=ValueType.INTEGER, rule=EXACT) is Outcome.HIT


def test_the_record_is_authoritative_and_there_is_no_adjudication():
    """mvp-spec.md §12: "The structured record is fully authoritative in every
    case. No adjudication step exists anywhere in the pipeline."

    A disagreement is a `WRONG`, whatever the model's reasoning. Whether the
    record or the model was right is a question for the mismatch list.
    """
    assert call("3", "4") is Outcome.WRONG
    assert call("4", "3") is Outcome.WRONG
