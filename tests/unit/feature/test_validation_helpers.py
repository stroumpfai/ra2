"""`ra2.domain.feature.is_scalar_grain` / `requires_codelist`
(mvp-spec.md §8.2, §8.4).
"""

import pytest

from ra2.domain.feature import Grain, ValueType, is_scalar_grain, requires_codelist

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("grain", "expected"),
    [
        (Grain.ACCIDENT, True),
        (Grain.DERIVED, True),
        (Grain.OBJECT, False),
        (Grain.PERSON, False),
    ],
)
def test_is_scalar_grain(grain: Grain, expected: bool) -> None:
    assert is_scalar_grain(grain) is expected


@pytest.mark.parametrize(
    ("value_type", "expected"),
    [
        (ValueType.ENUM, True),
        (ValueType.INTEGER, False),
        (ValueType.DECIMAL, False),
        (ValueType.DATE, False),
        (ValueType.TIME, False),
        (ValueType.BOOLEAN, False),
        (ValueType.FREE_TEXT, False),
    ],
)
def test_requires_codelist(value_type: ValueType, expected: bool) -> None:
    assert requires_codelist(value_type) is expected
