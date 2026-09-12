"""`ra2.domain.fingerprint.compute_fingerprint` (mvp-spec.md §8.5).

`sha256` over a canonical JSON serialisation of `FingerprintInput`'s eight
fields. Must be **stable** (same input, same hash, every time) and
**sensitive** (changing any single one of the eight fields changes the hash —
the property "two runs asked the model different questions" in §8.5 depends
on).
"""

import dataclasses

import pytest

from ra2.domain.feature import Grain, Kind, ValueType
from ra2.domain.fingerprint import FingerprintInput, compute_fingerprint

pytestmark = pytest.mark.unit


def _base() -> FingerprintInput:
    return FingerprintInput(
        kind=Kind.LABELLED,
        grain=Grain.ACCIDENT,
        source_column="UnfallartCode",
        derivation_json='{"type":"count_objects","filter":null}',
        value_type=ValueType.INTEGER,
        matching_rule_json='{"kind":"exact","tolerance_minutes":null,"decimal_precision":null}',
        enum_codelist_json='{"01":"A"}',
        description="Base description",
    )


# --- stability -------------------------------------------------------------


def test_stability_same_input_hashes_the_same_way_twice() -> None:
    assert compute_fingerprint(_base()) == compute_fingerprint(_base())


def test_stability_across_repeated_calls_on_the_same_instance() -> None:
    input_ = _base()
    first = compute_fingerprint(input_)
    second = compute_fingerprint(input_)
    third = compute_fingerprint(input_)
    assert first == second == third


# --- sensitivity: one test per field, all eight ------------------------


def test_sensitivity_kind() -> None:
    base = _base()
    changed = dataclasses.replace(base, kind=Kind.EXPLORATORY)
    assert compute_fingerprint(base) != compute_fingerprint(changed)


def test_sensitivity_grain() -> None:
    base = _base()
    changed = dataclasses.replace(base, grain=Grain.DERIVED)
    assert compute_fingerprint(base) != compute_fingerprint(changed)


def test_sensitivity_source_column() -> None:
    base = _base()
    changed = dataclasses.replace(base, source_column="SomeOtherColumn")
    assert compute_fingerprint(base) != compute_fingerprint(changed)


def test_sensitivity_derivation_json() -> None:
    base = _base()
    changed = dataclasses.replace(base, derivation_json='{"type":"count_persons","filter":null}')
    assert compute_fingerprint(base) != compute_fingerprint(changed)


def test_sensitivity_value_type() -> None:
    base = _base()
    changed = dataclasses.replace(base, value_type=ValueType.DECIMAL)
    assert compute_fingerprint(base) != compute_fingerprint(changed)


def test_sensitivity_matching_rule_json() -> None:
    base = _base()
    changed = dataclasses.replace(
        base,
        matching_rule_json='{"kind":"exact","tolerance_minutes":5,"decimal_precision":null}',
    )
    assert compute_fingerprint(base) != compute_fingerprint(changed)


def test_sensitivity_enum_codelist_json() -> None:
    base = _base()
    changed = dataclasses.replace(base, enum_codelist_json='{"01":"B"}')
    assert compute_fingerprint(base) != compute_fingerprint(changed)


def test_sensitivity_description() -> None:
    base = _base()
    changed = dataclasses.replace(base, description="A different description")
    assert compute_fingerprint(base) != compute_fingerprint(changed)


# --- hand-computed fixture --------------------------------------------------


def test_matches_an_independently_computed_hash() -> None:
    """The canonical JSON and its sha256 were worked out independently (a
    standalone `json.dumps(..., sort_keys=True, separators=(",", ":"),
    ensure_ascii=False)` + `hashlib.sha256` script, never by calling
    `compute_fingerprint` itself) for this exact input:

        {"derivation_json":null,"description":"Number of injured persons",
         "enum_codelist_json":null,"grain":"accident","kind":"labelled",
         "matching_rule_json":"{\\"kind\\":\\"exact\\",\\"tolerance_minutes\\":
         null,\\"decimal_precision\\":null}","source_column":"UnfallartCode",
         "value_type":"integer"}

    This is the one test that would catch a subtly different but
    internally-consistent canonicalisation choice (e.g. `sort_keys=False`,
    `ensure_ascii=True`, or non-compact separators).
    """
    input_ = FingerprintInput(
        kind=Kind.LABELLED,
        grain=Grain.ACCIDENT,
        source_column="UnfallartCode",
        derivation_json=None,
        value_type=ValueType.INTEGER,
        matching_rule_json=('{"kind":"exact","tolerance_minutes":null,"decimal_precision":null}'),
        enum_codelist_json=None,
        description="Number of injured persons",
    )
    expected = "417d35b54e4efba71ec2345efb8cd694db35a63a0774af226b87022e23ca2c42"
    assert compute_fingerprint(input_) == expected
