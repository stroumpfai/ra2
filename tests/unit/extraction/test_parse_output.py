"""`ra2.domain.extraction.parse_output` (mvp-spec.md §10.3, §10.4).

**Never raises, never repairs.** A response that is unreadable at all
(truncated JSON, prose instead of JSON, an envelope of the wrong shape)
returns `ParseFailure`. A response that reads but has per-feature problems
returns `ParsedExtraction` **with issues** — the run continues either way,
and every issue is asserted on its `ParseIssueCode`, never on message text
(CLAUDE.md, "Findings, not prose").
"""

import json

import pytest
from tests.unit.extraction.conftest import FeatureFactory

from ra2.domain.extraction import (
    ParsedExtraction,
    ParsedValue,
    ParseFailure,
    ParseIssueCode,
    parse_output,
)
from ra2.domain.feature import ValueType

pytestmark = pytest.mark.unit


def _issues_by_key(result: ParsedExtraction) -> dict[str, list[ParseIssueCode]]:
    by_key: dict[str, list[ParseIssueCode]] = {}
    for issue in result.issues:
        by_key.setdefault(issue.feature_key or "", []).append(issue.code)
    return by_key


def _value(result: ParsedExtraction, key: str) -> ParsedValue:
    (match,) = [v for v in result.values if v.feature_key == key]
    return match


# ===========================================================================
# Valid output
# ===========================================================================


def test_valid_output_parses_with_no_issues(feature_factory: FeatureFactory) -> None:
    features = [
        feature_factory("UnfallartCode", value_type=ValueType.ENUM),
        feature_factory("AnzObjFeld", value_type=ValueType.INTEGER),
    ]
    raw = json.dumps(
        {
            "features": {
                "UnfallartCode": {
                    "value": "01",
                    "present": True,
                    "evidence": "Frontalzusammenstoss",
                },
                "AnzObjFeld": {"value": 2, "present": True, "evidence": "zwei Fahrzeuge"},
            },
            "entities": [
                {"kind": "vehicle", "ref": "G1", "attributes": {"colour": "red"}},
            ],
        }
    )

    result = parse_output(raw, features, enum_codelists={"UnfallartCode": frozenset({"01", "02"})})

    assert isinstance(result, ParsedExtraction)
    assert result.issues == ()
    assert len(result.values) == 2

    code_answer = _value(result, "UnfallartCode")
    assert code_answer.value_raw == "01"
    assert code_answer.value_normalised == "01"
    assert code_answer.present_flag is True
    assert code_answer.evidence_span == "Frontalzusammenstoss"

    count_answer = _value(result, "AnzObjFeld")
    assert count_answer.value_raw == "2"
    assert count_answer.value_normalised == "2"

    assert len(result.entities) == 1
    assert result.entities[0].kind == "vehicle"
    assert result.entities[0].ref == "G1"
    assert result.entities[0].attributes == {"colour": "red"}


def test_a_trimmed_value_normalises_to_its_trimmed_form(feature_factory: FeatureFactory) -> None:
    """ "exact-and-trimmed only" (D6): trimming happens, nothing fancier does."""
    features = [feature_factory("Hergang", value_type=ValueType.FREE_TEXT)]
    raw = json.dumps(
        {
            "features": {
                "Hergang": {"value": "  hit the curb  ", "present": True, "evidence": "curb"}
            },
            "entities": [],
        }
    )

    result = parse_output(raw, features)

    assert isinstance(result, ParsedExtraction)
    answer = _value(result, "Hergang")
    assert answer.value_raw == "  hit the curb  "
    assert answer.value_normalised == "hit the curb"


# ===========================================================================
# Unreadable envelopes -> ParseFailure
# ===========================================================================


def test_truncated_json_returns_parse_failure(feature_factory: FeatureFactory) -> None:
    features = [feature_factory("UnfallartCode")]
    raw = '{"features": {"UnfallartCode": {"value": "01", "present": tr'

    result = parse_output(raw, features)

    assert isinstance(result, ParseFailure)


def test_json_with_prose_around_it_returns_parse_failure(feature_factory: FeatureFactory) -> None:
    features = [feature_factory("UnfallartCode")]
    inner = json.dumps(
        {
            "features": {"UnfallartCode": {"value": "01", "present": True, "evidence": "e"}},
            "entities": [],
        }
    )
    raw = f"Sure, here is the extraction:\n{inner}\nLet me know if you need anything else!"

    result = parse_output(raw, features)

    assert isinstance(result, ParseFailure)


def test_prose_only_response_returns_parse_failure(feature_factory: FeatureFactory) -> None:
    features = [feature_factory("UnfallartCode")]
    raw = "I'm sorry, I cannot process this request."

    result = parse_output(raw, features)

    assert isinstance(result, ParseFailure)


def test_top_level_json_array_returns_parse_failure(feature_factory: FeatureFactory) -> None:
    features = [feature_factory("UnfallartCode")]
    raw = json.dumps(["not", "an", "object"])

    result = parse_output(raw, features)

    assert isinstance(result, ParseFailure)


def test_missing_features_key_returns_parse_failure(feature_factory: FeatureFactory) -> None:
    features = [feature_factory("UnfallartCode")]
    raw = json.dumps({"entities": []})

    result = parse_output(raw, features)

    assert isinstance(result, ParseFailure)


def test_features_key_of_the_wrong_type_returns_parse_failure(
    feature_factory: FeatureFactory,
) -> None:
    features = [feature_factory("UnfallartCode")]
    raw = json.dumps({"features": ["not", "an", "object"], "entities": []})

    result = parse_output(raw, features)

    assert isinstance(result, ParseFailure)


# ===========================================================================
# Per-feature problems -> ParsedExtraction, with issues (Do-NOT #6)
# ===========================================================================


def test_a_missing_feature_key_is_recorded_and_the_run_continues(
    feature_factory: FeatureFactory,
) -> None:
    features = [
        feature_factory("UnfallartCode", value_type=ValueType.ENUM),
        feature_factory("AnzObjFeld", value_type=ValueType.INTEGER),
    ]
    raw = json.dumps(
        {
            "features": {
                "AnzObjFeld": {"value": 1, "present": True, "evidence": "one car"},
            },
            "entities": [],
        }
    )

    result = parse_output(raw, features)

    assert isinstance(result, ParsedExtraction)
    assert _issues_by_key(result)["UnfallartCode"] == [ParseIssueCode.MISSING_FEATURE]
    # Do-NOT #6: never silently drop a row — the missing feature still gets
    # a `ParsedValue` row, carrying nothing rather than not existing at all.
    missing = _value(result, "UnfallartCode")
    assert missing.value_raw is None
    assert missing.value_normalised is None
    assert missing.present_flag is False
    assert missing.evidence_span is None
    # The other feature is unaffected.
    assert _value(result, "AnzObjFeld").value_raw == "1"


def test_an_extra_key_is_recorded_as_unknown_feature(feature_factory: FeatureFactory) -> None:
    features = [feature_factory("UnfallartCode")]
    raw = json.dumps(
        {
            "features": {
                "UnfallartCode": {"value": "01", "present": True, "evidence": "e"},
                "SomeUnconfiguredKey": {"value": "x", "present": True, "evidence": "e"},
            },
            "entities": [],
        }
    )

    result = parse_output(raw, features)

    assert isinstance(result, ParsedExtraction)
    assert _issues_by_key(result)["SomeUnconfiguredKey"] == [ParseIssueCode.UNKNOWN_FEATURE]
    # The configured feature still parses cleanly.
    assert _value(result, "UnfallartCode").value_raw == "01"


def test_non_null_value_with_null_evidence_is_recorded_as_missing_evidence(
    feature_factory: FeatureFactory,
) -> None:
    features = [feature_factory("UnfallartCode", value_type=ValueType.ENUM)]
    raw = json.dumps(
        {
            "features": {"UnfallartCode": {"value": "01", "present": True, "evidence": None}},
            "entities": [],
        }
    )

    result = parse_output(raw, features)

    assert isinstance(result, ParsedExtraction)
    assert _issues_by_key(result)["UnfallartCode"] == [ParseIssueCode.MISSING_EVIDENCE]
    # Still stored, verbatim — a recorded outcome, not a dropped row.
    assert _value(result, "UnfallartCode").value_raw == "01"


def test_null_value_with_non_null_evidence_is_accepted_without_an_issue(
    feature_factory: FeatureFactory,
) -> None:
    """The mirror case of `MISSING_EVIDENCE`, and a deliberately different
    outcome: `MISSING_EVIDENCE` is defined as *a non-null value with no
    evidence* (mvp-spec.md §10.2's instruction is the other way round — an
    evidence span is required "for every non-null value"). A `null` value
    that nonetheless carries an evidence span is not that problem — there is
    no configured `ParseIssueCode` for it, and it must not be raised as one
    by an implementation that checks `(value is None) != (evidence is None)`
    instead of the asymmetric rule the spec actually states."""
    features = [feature_factory("UnfallartCode", value_type=ValueType.ENUM)]
    raw = json.dumps(
        {
            "features": {
                "UnfallartCode": {"value": None, "present": False, "evidence": "no clear code"}
            },
            "entities": [],
        }
    )

    result = parse_output(raw, features)

    assert isinstance(result, ParsedExtraction)
    assert _issues_by_key(result).get("UnfallartCode", []) == []
    answer = _value(result, "UnfallartCode")
    assert answer.value_raw is None
    assert answer.evidence_span == "no clear code"


def test_enum_code_not_in_codelist_is_recorded_and_the_value_kept(
    feature_factory: FeatureFactory,
) -> None:
    features = [feature_factory("UnfallartCode", value_type=ValueType.ENUM)]
    raw = json.dumps(
        {
            "features": {"UnfallartCode": {"value": "99", "present": True, "evidence": "e"}},
            "entities": [],
        }
    )

    result = parse_output(raw, features, enum_codelists={"UnfallartCode": frozenset({"01", "02"})})

    assert isinstance(result, ParsedExtraction)
    assert _issues_by_key(result)["UnfallartCode"] == [ParseIssueCode.ENUM_CODE_NOT_IN_CODELIST]
    # Do-NOT #6: never silently repaired to a valid code, never dropped.
    assert _value(result, "UnfallartCode").value_raw == "99"


def test_enum_code_in_codelist_is_not_flagged(feature_factory: FeatureFactory) -> None:
    features = [feature_factory("UnfallartCode", value_type=ValueType.ENUM)]
    raw = json.dumps(
        {
            "features": {"UnfallartCode": {"value": "01", "present": True, "evidence": "e"}},
            "entities": [],
        }
    )

    result = parse_output(raw, features, enum_codelists={"UnfallartCode": frozenset({"01", "02"})})

    assert isinstance(result, ParsedExtraction)
    assert _issues_by_key(result).get("UnfallartCode", []) == []


def test_no_codelist_snapshot_skips_the_enum_check(feature_factory: FeatureFactory) -> None:
    """`enum_codelists=None` (the default) — a preview call with no
    evaluation snapshot yet must not manufacture a spurious issue."""
    features = [feature_factory("UnfallartCode", value_type=ValueType.ENUM)]
    raw = json.dumps(
        {
            "features": {"UnfallartCode": {"value": "99", "present": True, "evidence": "e"}},
            "entities": [],
        }
    )

    result = parse_output(raw, features)

    assert isinstance(result, ParsedExtraction)
    assert _issues_by_key(result).get("UnfallartCode", []) == []


def test_boolean_feature_answered_with_a_string_is_a_value_type_mismatch(
    feature_factory: FeatureFactory,
) -> None:
    features = [feature_factory("IstVerletzt", value_type=ValueType.BOOLEAN)]
    raw = json.dumps(
        {
            "features": {"IstVerletzt": {"value": "yes", "present": True, "evidence": "e"}},
            "entities": [],
        }
    )

    result = parse_output(raw, features)

    assert isinstance(result, ParsedExtraction)
    assert _issues_by_key(result)["IstVerletzt"] == [ParseIssueCode.VALUE_TYPE_MISMATCH]
    # Kept, not dropped.
    assert _value(result, "IstVerletzt").value_raw == "yes"


def test_feature_answer_of_the_wrong_shape_is_a_value_type_mismatch(
    feature_factory: FeatureFactory,
) -> None:
    """The model answered with a bare string instead of `{value, present,
    evidence}` — unreadable as *this feature's* answer, but not fatal to the
    whole response."""
    features = [
        feature_factory("UnfallartCode", value_type=ValueType.ENUM),
        feature_factory("AnzObjFeld", value_type=ValueType.INTEGER),
    ]
    raw = json.dumps(
        {
            "features": {
                "UnfallartCode": "01",
                "AnzObjFeld": {"value": 2, "present": True, "evidence": "e"},
            },
            "entities": [],
        }
    )

    result = parse_output(raw, features)

    assert isinstance(result, ParsedExtraction)
    assert _issues_by_key(result)["UnfallartCode"] == [ParseIssueCode.VALUE_TYPE_MISMATCH]
    assert _value(result, "AnzObjFeld").value_raw == "2"


# ===========================================================================
# Entities — captured, never scored (mvp-spec.md §10.3)
# ===========================================================================


def test_missing_entities_key_defaults_to_no_entities(feature_factory: FeatureFactory) -> None:
    features = [feature_factory("UnfallartCode")]
    raw = json.dumps(
        {"features": {"UnfallartCode": {"value": "01", "present": True, "evidence": "e"}}}
    )

    result = parse_output(raw, features)

    assert isinstance(result, ParsedExtraction)
    assert result.entities == ()


def test_a_malformed_entity_is_dropped_without_failing_the_response(
    feature_factory: FeatureFactory,
) -> None:
    """Entities are captured, never scored, and there is no `ParseIssueCode`
    for a per-entity problem — the feature answers are the extraction, and a
    malformed capture-only item does not cost the record its answers."""
    features = [feature_factory("UnfallartCode")]
    raw = json.dumps(
        {
            "features": {"UnfallartCode": {"value": "01", "present": True, "evidence": "e"}},
            "entities": [
                {"kind": "vehicle", "ref": "G1", "attributes": {}},
                {"kind": "person"},  # missing required "ref"
            ],
        }
    )

    result = parse_output(raw, features)

    assert isinstance(result, ParsedExtraction)
    assert len(result.entities) == 1
    assert result.entities[0].ref == "G1"


def test_entities_of_the_wrong_type_do_not_fail_the_response(
    feature_factory: FeatureFactory,
) -> None:
    features = [feature_factory("UnfallartCode")]
    raw = json.dumps(
        {
            "features": {"UnfallartCode": {"value": "01", "present": True, "evidence": "e"}},
            "entities": "not-a-list",
        }
    )

    result = parse_output(raw, features)

    assert isinstance(result, ParsedExtraction)
    assert result.entities == ()


# ===========================================================================
# Never raises
# ===========================================================================


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "null",
        "true",
        "42",
        '"just a string"',
        "{}",
        "{",
        "not json at all",
        "\x00\x01\x02",
        "{'single': 'quotes'}",
    ],
)
def test_never_raises_on_hostile_but_plausible_input(
    raw: str, feature_factory: FeatureFactory
) -> None:
    features = [feature_factory("UnfallartCode")]
    result = parse_output(raw, features)
    assert isinstance(result, (ParsedExtraction, ParseFailure))


def test_never_raises_with_no_configured_features(feature_factory: FeatureFactory) -> None:
    raw = json.dumps({"features": {}, "entities": []})
    result = parse_output(raw, [])
    assert isinstance(result, ParsedExtraction)
    assert result.values == ()
