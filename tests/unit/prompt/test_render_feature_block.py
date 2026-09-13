"""`ra2.domain.prompt.render_feature_block` (mvp-spec.md §10.2, sw-design.md §15.1).

One `name — type` line per labelled feature, the full code -> label list per
enum feature, and each exploratory attribute's description verbatim. Pure
and deterministic. Asserted against golden strings, never a substring match
— a stray extra line or a swapped separator would pass a substring check and
still be a different prompt sent to the model.
"""

import pytest

from ra2.domain.codes import CodeValue
from ra2.domain.feature import Grain, Kind, MatchingRule, MatchingRuleKind, ValueType
from ra2.domain.prompt import FeatureBlockEntry, render_feature_block

pytestmark = pytest.mark.unit


def _rule(kind: MatchingRuleKind = MatchingRuleKind.EXACT) -> MatchingRule:
    return MatchingRule(kind=kind, tolerance_minutes=None, decimal_precision=None)


def test_golden_string_labelled_enum_and_exploratory_together():
    features = (
        FeatureBlockEntry(
            key="road_surface",
            kind=Kind.LABELLED,
            grain=Grain.ACCIDENT,
            value_type=ValueType.ENUM,
            description="Condition of the road surface at the time of the accident",
            matching_rule=_rule(),
            enum_codelist=(
                CodeValue(
                    attribute_key="road_surface", code="01", label={"de": "Trocken", "fr": "Sec"}
                ),
                CodeValue(
                    attribute_key="road_surface", code="02", label={"de": "Nass", "fr": "Mouillé"}
                ),
            ),
        ),
        FeatureBlockEntry(
            key="injury_count",
            kind=Kind.LABELLED,
            grain=Grain.ACCIDENT,
            value_type=ValueType.INTEGER,
            description="Number of injured persons",
            matching_rule=_rule(),
            enum_codelist=None,
        ),
        FeatureBlockEntry(
            key="unusual_circumstances",
            kind=Kind.EXPLORATORY,
            grain=Grain.ACCIDENT,
            value_type=ValueType.FREE_TEXT,
            description="Anything the report calls out as unusual, verbatim from the expert.",
            matching_rule=_rule(MatchingRuleKind.NONE),
            enum_codelist=None,
        ),
    )

    result = render_feature_block(features, language="fr")

    expected = (
        "road_surface — enum\n"
        "  01 — Sec\n"
        "  02 — Mouillé\n"
        "\n"
        "injury_count — integer\n"
        "\n"
        "unusual_circumstances: Anything the report calls out as unusual, "
        "verbatim from the expert."
    )
    assert result == expected


def test_empty_feature_sequence_renders_empty_string():
    assert render_feature_block((), language="de") == ""


def test_p06_a_code_with_no_label_in_the_requested_language_falls_back_visibly(ph):
    """The phase-2 `partial` coverage case, seen from the prompt's side: a
    code missing the requested language's label must render a visible
    marker, never an empty string and never a silently substituted other
    language's text."""
    entries, language = ph.feature_block_entries("p06_enum_missing_label")

    result = render_feature_block(entries, language=language)

    assert language == "fr"
    expected = (
        "weather — enum\n"
        "  01 — Clair\n"
        "  02 — [no fr label]\n"
        "\n"
        "road_notes: Anything unusual about the road surface, verbatim from the expert."
    )
    assert result == expected
    # Never an empty label, and never someone else's language quietly standing in.
    assert "02 — \n" not in result
    assert "02 — Regen" not in result
    assert "02 — Pioggia" not in result
