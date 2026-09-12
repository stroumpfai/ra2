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
    standalone `json.dumps(..., sort_keys=False, separators=(",", ":"),
    ensure_ascii=False)` + `hashlib.sha256` script, never by calling
    `compute_fingerprint` itself) for this exact input:

        {"kind":"labelled","grain":"accident","source_column":"UnfallartCode",
         "derivation_json":null,"value_type":"integer",
         "matching_rule_json":"{\\"kind\\":\\"exact\\",\\"tolerance_minutes\\":
         null,\\"decimal_precision\\":null}","enum_codelist_json":null,
         "description":"Number of injured persons"}

    Key order matters here and is asserted by it: mvp-spec.md §8.5 names an
    exact field order (kind, grain, source_column, derivation_json,
    value_type, matching_rule_json, enum_codelist_json, description), so this
    fixture is built with keys **in that literal order**, not alphabetical —
    a code review found an earlier version of `compute_fingerprint` used
    `sort_keys=True`, which is stable and sensitive (still true either way,
    and the two properties the other tests in this file pin) but hashes the
    fields alphabetically instead of in the order the spec actually states.
    This is the one test that would catch that regressing, or any other
    subtly different but internally-consistent canonicalisation choice
    (`ensure_ascii=True`, non-compact separators, ...).
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
    expected = "4790871a61f1c98f3afb366ca3895405c1e219bbf89f52af35e64bb2daced4bc"
    assert compute_fingerprint(input_) == expected
