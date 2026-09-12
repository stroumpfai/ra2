"""`ra2.domain.codes.validate_import` (mvp-spec.md §7, sw-design.md §14.1).

Pure, no I/O: `validate_import` takes a JSON string and returns either a
`CodeTableImportResult` or a `list[CodeImportError]` — never a partial result
(Do-NOT list #6). Each hazard's fixture is loaded from the committed,
synthetic files under `tests/fixtures/codelists/hazards/` (c01-c05); the real
`codes-2018.json` never appears here (CLAUDE.md Do-NOT #11).
"""

import pytest

from ra2.domain.codes import (
    CodeImportError,
    CodeTableImportResult,
    validate_import,
)

pytestmark = pytest.mark.unit


def test_c01_minimal_valid_import_succeeds_with_the_right_counts(cl):
    result = validate_import(cl.raw_json("c01_minimal_valid"))

    assert isinstance(result, CodeTableImportResult)
    assert {a.key for a in result.attributes} == {"accident_type", "road_type"}
    assert len(result.attributes) == 2
    # Two codes per attribute, four values in total.
    assert len(result.values) == 4
    assert {v.code for v in result.values if v.attribute_key == "accident_type"} == {"01", "02"}


def test_c01_every_code_carries_all_three_languages(cl):
    result = validate_import(cl.raw_json("c01_minimal_valid"))
    assert isinstance(result, CodeTableImportResult)
    for value in result.values:
        assert set(value.label) == {"de", "fr", "it"}
    for attribute in result.attributes:
        assert set(attribute.name) == {"de", "fr", "it"}


def test_c01_value_attribute_key_joins_back_to_its_attribute(cl):
    """`CodeValue.attribute_key` is the join key before either has a db id."""
    result = validate_import(cl.raw_json("c01_minimal_valid"))
    assert isinstance(result, CodeTableImportResult)
    attribute_keys = {a.key for a in result.attributes}
    assert all(v.attribute_key in attribute_keys for v in result.values)


def test_c02_a_code_missing_one_language_parses_with_a_partial_label_map(cl):
    """Import validity does not require every language — c02 succeeds; the
    missing `it` label only matters once `compute_coverage` looks at it."""
    result = validate_import(cl.raw_json("c02_missing_language_label"))
    assert isinstance(result, CodeTableImportResult)
    values_by_code = {v.code: v for v in result.values}
    assert set(values_by_code["01"].label) == {"de", "fr", "it"}
    assert set(values_by_code["02"].label) == {"de", "fr"}
    assert "it" not in values_by_code["02"].label


def test_c03_an_attribute_with_zero_codes_is_a_valid_import(cl):
    """`codes: {}` is structurally valid — zero `CodeValue` rows, not an error.
    (`MISSING` coverage is a `compute_coverage` concern, tested separately.)"""
    result = validate_import(cl.raw_json("c03_attribute_with_zero_codes"))
    assert isinstance(result, CodeTableImportResult)
    assert [a.key for a in result.attributes] == ["light_condition"]
    assert result.values == ()


def test_c04_one_attribute_missing_codes_fails_the_whole_import(cl):
    """The whole import fails — `road_type` is well-formed but is not returned
    as a partial success alongside `weather`'s error (Do-NOT list #6)."""
    result = validate_import(cl.raw_json("c04_missing_codes_key"))

    # `list[CodeImportError]`, not a `CodeTableImportResult` with holes: the
    # two types are disjoint, so this isinstance check alone is the assertion
    # that nothing partial was returned.
    assert isinstance(result, list)
    assert all(isinstance(e, CodeImportError) for e in result)


def test_c04_the_error_names_the_offending_attribute_and_field(cl):
    result = validate_import(cl.raw_json("c04_missing_codes_key"))
    assert isinstance(result, list)
    assert len(result) == 1
    error = result[0]
    assert error.attribute_key == "weather"
    assert "codes" in error.path


def test_malformed_json_is_reported_with_no_attribute_key():
    result = validate_import("not json at all")
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].attribute_key is None


def test_a_json_array_at_the_top_level_is_reported_not_crashed():
    """The document must be an object of attributes, not a list."""
    result = validate_import("[1, 2, 3]")
    assert isinstance(result, list)
    assert result[0].attribute_key is None


def test_an_unknown_field_on_an_attribute_fails_the_import():
    raw = '{"weather": {"name": {"de": "Wetter"}, "codes": {}, "unexpected_field": 1}}'
    result = validate_import(raw)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].attribute_key == "weather"


def test_every_error_is_collected_not_just_the_first():
    """Two independently-broken attributes both surface, in one call."""
    raw = '{"a": {"codes": {}}, "b": {"name": {"de": "B"}, "codes": {}, "extra": 1}}'
    result = validate_import(raw)
    assert isinstance(result, list)
    attribute_keys = {e.attribute_key for e in result}
    assert attribute_keys == {"a", "b"}


def test_empty_object_is_a_valid_import_with_nothing_in_it():
    result = validate_import("{}")
    assert isinstance(result, CodeTableImportResult)
    assert result.attributes == ()
    assert result.values == ()
