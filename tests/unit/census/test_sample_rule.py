"""Whose census values may be shown at all — the sample rule (risk B1).

The census stores the top 20 raw values of **every** column and the census CSV
is the week-one deliverable, the artefact most meant to be shown to other
people. In the working corpus that combination put verbatim LV95 coordinates
at metre precision and verbatim record UIDs into that file, 16 to 20 of each
column's 20 stored values occurring exactly once. A value that occurs once is
one accident.

The rule is one line — `sample_is_shareable` — and it is tested here rather
than only through the service, for the reason `test_long_tail.py` gives for
`_is_long_tail`: a rule that only has an end-to-end test is one whose boundary
nobody has stated.
"""

import pytest

from ra2.domain.census import (
    SHAREABLE_TYPE_HINTS,
    TypeHint,
    sample_is_shareable,
)

pytestmark = pytest.mark.unit


def test_only_coded_columns_may_show_their_values():
    """The whole of what is permitted, on one line — `LOOPBACK_HOSTS`'s shape.

    Asserted as an equality rather than a membership so widening it is a red
    test and not an unnoticed diff.
    """
    assert frozenset({TypeHint.ENUM}) == SHAREABLE_TYPE_HINTS


def test_an_enum_column_keeps_its_sample():
    assert sample_is_shareable(TypeHint.ENUM) is True


@pytest.mark.parametrize(
    "type_hint",
    [
        pytest.param(TypeHint.DECIMAL, id="decimal — the coordinate columns"),
        pytest.param(TypeHint.TEXT, id="text — the UID columns and free text"),
        pytest.param(TypeHint.DATE, id="date"),
        pytest.param(TypeHint.TIME, id="time"),
        pytest.param(TypeHint.INTEGER, id="integer"),
    ],
)
def test_every_other_column_withholds_its_sample(type_hint: TypeHint) -> None:
    """The four coordinate columns are `DECIMAL` and the three UID columns are
    `TEXT` — the seven the reviewer measured, by the hint each one carries."""
    assert sample_is_shareable(type_hint) is False


def test_the_rule_covers_every_type_hint_that_exists():
    """A hint added later is refused until someone decides otherwise.

    `sample_is_shareable` is a membership test, so a new `TypeHint` is excluded
    by construction — which is the right default for this rule and the wrong
    one to leave implicit.
    """
    assert {hint for hint in TypeHint if sample_is_shareable(hint)} == SHAREABLE_TYPE_HINTS
    assert set(TypeHint) > SHAREABLE_TYPE_HINTS


def test_the_known_cost_is_a_decision_not_an_oversight():
    """A code seen in one record is still exported, because the line is drawn
    at the header rather than at a frequency (`domain.census`'s docstring says
    so). Asserted so that a later reader meets the trade as a stated one."""
    assert sample_is_shareable(TypeHint.ENUM) is True
