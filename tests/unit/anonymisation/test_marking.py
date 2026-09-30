"""What the anonymisation marking may claim (`SD50`, risk B5).

The data knows one thing: whether a narrative came from the
`UnfHergangTextAnonym` fallback column. Whether a *delivered* narrative is
anonymised is the supplier's to say, and until they have, it is unknown.
"""

import pytest

from ra2.domain.anonymisation import (
    AnonymisationMarking,
    DeliveredTextAnonymised,
    anonymisation_marking,
)


@pytest.mark.parametrize("delivered", list(DeliveredTextAnonymised))
def test_the_fallback_column_is_named_for_its_source_whatever_the_answer(
    delivered: DeliveredTextAnonymised,
) -> None:
    assert anonymisation_marking(True, delivered) is AnonymisationMarking.ANONYMISED_COLUMN


@pytest.mark.parametrize(
    ("delivered", "expected"),
    [
        (DeliveredTextAnonymised.UNKNOWN, AnonymisationMarking.UNKNOWN),
        (DeliveredTextAnonymised.YES, AnonymisationMarking.ANONYMISED),
        (DeliveredTextAnonymised.NO, AnonymisationMarking.NOT_ANONYMISED),
    ],
)
def test_a_delivered_narrative_follows_the_suppliers_answer(
    delivered: DeliveredTextAnonymised, expected: AnonymisationMarking
) -> None:
    assert anonymisation_marking(False, delivered) is expected


def test_the_default_answer_is_unknown() -> None:
    """Never *not anonymised* by silence: that is the claim B5 is about."""
    from ra2.infra.config import Settings

    assert Settings(_env_file=None).delivered_text_anonymised is DeliveredTextAnonymised.UNKNOWN
