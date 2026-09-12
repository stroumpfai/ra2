"""`ra2.domain.feature.derivation_to_json` / `derivation_from_json`
(mvp-spec.md §8.3) — the codec `feature.derivation_json` actually stores.

The round trip must be exactly lossless, including `Filter.value`'s three
shapes (`None`, a single string, a tuple) and a derivation with no filter at
all.
"""

import pytest

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
    derivation_from_json,
    derivation_to_json,
)

pytestmark = pytest.mark.unit

DERIVATIONS: tuple[DerivationSpec, ...] = (
    CountObjects(),
    CountObjects(filter=Filter(column="Rolle", operator=Operator.EQ, value="01")),
    CountObjects(filter=Filter(column="Rolle", operator=Operator.IS_EMPTY, value=None)),
    CountPersons(),
    CountPersons(filter=Filter(column="Rolle", operator=Operator.NE, value="02")),
    CountPersons(filter=Filter(column="Rolle", operator=Operator.IN, value=("01", "02", "03"))),
    AnyObjectMatches(filter=Filter(column="Fahrzeugart", operator=Operator.EQ, value="10")),
    AnyObjectMatches(
        filter=Filter(column="Fahrzeugart", operator=Operator.IS_NOT_EMPTY, value=None)
    ),
    AnyPersonMatches(
        filter=Filter(column="Verletzungsgrad", operator=Operator.NOT_IN, value=("1", "2"))
    ),
    MaxOrdinal(table="person", column="Verletzungsgrad", ordered_codes=("1", "2", "3")),
    MinOrdinal(table="objekt", column="Beschaedigung", ordered_codes=("0", "1", "2")),
    DistinctCount(table="objekt", column="Fahrzeugart"),
)


@pytest.mark.parametrize("derivation", DERIVATIONS)
def test_round_trip_is_lossless(derivation: DerivationSpec) -> None:
    payload = derivation_to_json(derivation)
    assert derivation_from_json(payload) == derivation


def test_bare_count_objects_round_trips_filter_none_not_a_missing_key() -> None:
    """A derivation with no filter at all round-trips `filter=None`, not an
    empty object or a default that happens to look the same."""
    result = derivation_from_json(derivation_to_json(CountObjects()))
    assert isinstance(result, CountObjects)
    assert result.filter is None


def test_filter_value_none_is_preserved_for_is_empty() -> None:
    derivation = AnyObjectMatches(filter=Filter(column="X", operator=Operator.IS_EMPTY, value=None))
    result = derivation_from_json(derivation_to_json(derivation))
    assert isinstance(result, AnyObjectMatches)
    assert result.filter.value is None


def test_filter_value_none_is_preserved_for_is_not_empty() -> None:
    derivation = AnyPersonMatches(
        filter=Filter(column="X", operator=Operator.IS_NOT_EMPTY, value=None)
    )
    result = derivation_from_json(derivation_to_json(derivation))
    assert isinstance(result, AnyPersonMatches)
    assert result.filter.value is None


def test_filter_value_tuple_is_preserved_not_collapsed_to_a_string() -> None:
    derivation = CountPersons(filter=Filter(column="X", operator=Operator.IN, value=("a", "b")))
    result = derivation_from_json(derivation_to_json(derivation))
    assert isinstance(result, CountPersons)
    assert result.filter is not None
    assert result.filter.value == ("a", "b")
    assert isinstance(result.filter.value, tuple)


def test_filter_value_single_string_is_preserved_not_wrapped_in_a_tuple() -> None:
    derivation = CountObjects(filter=Filter(column="X", operator=Operator.EQ, value="a"))
    result = derivation_from_json(derivation_to_json(derivation))
    assert isinstance(result, CountObjects)
    assert result.filter is not None
    assert result.filter.value == "a"
    assert isinstance(result.filter.value, str)


def test_serialised_json_carries_the_type_discriminator() -> None:
    payload = derivation_to_json(DistinctCount(table="objekt", column="Fahrzeugart"))
    assert '"type":"distinct_count"' in payload


def test_derivation_to_json_is_canonical_across_calls() -> None:
    """Same derivation, hashed or diffed byte-for-byte, must not depend on
    dict-construction order inside the implementation."""
    derivation = MaxOrdinal(table="person", column="Verletzungsgrad", ordered_codes=("1", "2"))
    assert derivation_to_json(derivation) == derivation_to_json(derivation)


def test_unknown_type_discriminator_raises() -> None:
    with pytest.raises(ValueError):
        derivation_from_json('{"type":"not_a_real_derivation_type"}')
