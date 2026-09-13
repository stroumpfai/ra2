"""`ra2.domain.extraction.build_output_schema` (mvp-spec.md §10.3).

The schema this function returns becomes the constrained-decoding format sent
to the endpoint, so two properties matter more than the shape itself:

- **it matches a committed golden JSON Schema**, one per feature-kind
  combination, so a change is a diff a reviewer reads rather than a silent
  regeneration (plan-phase-3.md §7, H2's exit criteria);
- **its key order is stable** across repeated calls for the same feature
  sequence — two runs of the same evaluation must ask the same question
  (sw-design.md §15.3).
"""

import json

import pytest
from tests.unit.extraction.conftest import FeatureFactory, SchemaGolden

from ra2.domain.codes import CodeValue
from ra2.domain.extraction import build_output_schema
from ra2.domain.feature import Kind, ValueType

pytestmark = pytest.mark.unit


# ===========================================================================
# Golden snapshots — one per feature-kind combination
# ===========================================================================


def test_single_labelled_enum_feature_matches_golden_schema(
    feature_factory: FeatureFactory, golden: SchemaGolden
) -> None:
    features = [
        feature_factory(
            "UnfallartCode",
            kind=Kind.LABELLED,
            value_type=ValueType.ENUM,
            description="The kind of accident.",
            enum_codelist=(
                CodeValue(attribute_key="accident_type", code="01", label={"de": "Auffahrunfall"}),
                CodeValue(attribute_key="accident_type", code="02", label={"de": "Frontalunfall"}),
            ),
        )
    ]
    golden.assert_matches(build_output_schema(features), "single_labelled_enum")


def test_labelled_features_across_all_value_types_matches_golden_schema(
    feature_factory: FeatureFactory, golden: SchemaGolden
) -> None:
    features = [
        feature_factory(
            "UnfallartCode",
            value_type=ValueType.ENUM,
            description="The kind of accident.",
            enum_codelist=(CodeValue(attribute_key="accident_type", code="01", label={"de": "A"}),),
        ),
        feature_factory("AnzObjFeld", value_type=ValueType.INTEGER, description="Object count."),
        feature_factory(
            "SchadenBetrag", value_type=ValueType.DECIMAL, description="Damage amount, CHF."
        ),
        feature_factory("UnfallDatum", value_type=ValueType.DATE, description="Accident date."),
        feature_factory("UnfallZeit", value_type=ValueType.TIME, description="Accident time."),
        feature_factory(
            "IstVerletzt", value_type=ValueType.BOOLEAN, description="Was anyone injured?"
        ),
        feature_factory(
            "Hergang", value_type=ValueType.FREE_TEXT, description="Narrative summary."
        ),
    ]
    golden.assert_matches(build_output_schema(features), "labelled_all_value_types")


def test_exploratory_features_matches_golden_schema(
    feature_factory: FeatureFactory, golden: SchemaGolden
) -> None:
    features = [
        feature_factory(
            "weather_mentioned",
            kind=Kind.EXPLORATORY,
            value_type=ValueType.FREE_TEXT,
            description="Verbatim: does the narrative mention weather conditions?",
        ),
        feature_factory(
            "alcohol_suspected",
            kind=Kind.EXPLORATORY,
            value_type=ValueType.FREE_TEXT,
            description="Verbatim: is alcohol involvement suspected?",
        ),
    ]
    golden.assert_matches(build_output_schema(features), "exploratory_only")


def test_mixed_labelled_and_exploratory_matches_golden_schema(
    feature_factory: FeatureFactory, golden: SchemaGolden
) -> None:
    features = [
        feature_factory(
            "UnfallartCode",
            kind=Kind.LABELLED,
            value_type=ValueType.ENUM,
            description="The kind of accident.",
            enum_codelist=(CodeValue(attribute_key="accident_type", code="01", label={"de": "A"}),),
        ),
        feature_factory(
            "AnzObjFeld", kind=Kind.LABELLED, value_type=ValueType.INTEGER, description="Objects."
        ),
        feature_factory(
            "weather_mentioned",
            kind=Kind.EXPLORATORY,
            value_type=ValueType.FREE_TEXT,
            description="Verbatim: does the narrative mention weather conditions?",
        ),
    ]
    golden.assert_matches(build_output_schema(features), "mixed_labelled_and_exploratory")


# ===========================================================================
# Key order stability (sw-design.md §15.3)
# ===========================================================================


def test_key_order_is_stable_across_repeated_calls(feature_factory: FeatureFactory) -> None:
    features = [
        feature_factory("zeta", value_type=ValueType.FREE_TEXT),
        feature_factory("alpha", value_type=ValueType.INTEGER),
        feature_factory("mu", value_type=ValueType.BOOLEAN),
    ]

    schemas = [build_output_schema(features).model_json_schema() for _ in range(5)]

    top_level_orders = [list(schema["properties"].keys()) for schema in schemas]
    feature_key_orders = [
        list(schema["$defs"]["ExtractionFeatures"]["properties"].keys()) for schema in schemas
    ]

    assert all(order == top_level_orders[0] for order in top_level_orders)
    assert all(order == feature_key_orders[0] for order in feature_key_orders)
    # And it is *this* order, not an alphabetised one — "zeta" sorts last but
    # is listed first, exactly as the caller supplied it.
    assert feature_key_orders[0] == ["zeta", "alpha", "mu"]


def test_key_order_follows_the_feature_sequence_not_the_key_text(
    feature_factory: FeatureFactory,
) -> None:
    """A second, differently-ordered feature sequence proves the schema's
    property order tracks the *sequence* given, not some independent
    canonicalisation (alphabetical, insertion-into-a-set, ...) that would
    happen to agree with the first test's order by coincidence."""
    reordered = [
        feature_factory("mu", value_type=ValueType.BOOLEAN),
        feature_factory("zeta", value_type=ValueType.FREE_TEXT),
        feature_factory("alpha", value_type=ValueType.INTEGER),
    ]

    schema = build_output_schema(reordered).model_json_schema()
    assert list(schema["$defs"]["ExtractionFeatures"]["properties"].keys()) == [
        "mu",
        "zeta",
        "alpha",
    ]


# ===========================================================================
# Shape
# ===========================================================================


def test_schema_forbids_extra_top_level_keys(feature_factory: FeatureFactory) -> None:
    """Constrained decoding is only worth it when the endpoint cannot invent
    a key the schema never named."""
    schema = build_output_schema([feature_factory("only_key")]).model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["ExtractionFeatures"]["additionalProperties"] is False


def test_schema_declares_every_configured_feature_key_as_required(
    feature_factory: FeatureFactory,
) -> None:
    features = [feature_factory("a"), feature_factory("b"), feature_factory("c")]
    schema = build_output_schema(features).model_json_schema()
    assert schema["$defs"]["ExtractionFeatures"]["required"] == ["a", "b", "c"]
    assert schema["required"] == ["features", "entities"]


def test_empty_feature_sequence_still_declares_entities(feature_factory: FeatureFactory) -> None:
    schema = build_output_schema([]).model_json_schema()
    assert schema["$defs"]["ExtractionFeatures"]["properties"] == {}
    assert "entities" in schema["properties"]


def test_the_returned_model_round_trips_a_valid_answer(feature_factory: FeatureFactory) -> None:
    """The narrow schema is still an ordinary Pydantic model: valid input
    validates, and reports back exactly the values given."""
    model = build_output_schema([feature_factory("only_key", value_type=ValueType.FREE_TEXT)])
    instance = model.model_validate(
        {
            "features": {"only_key": {"value": "hello", "present": True, "evidence": "hello"}},
            "entities": [],
        }
    )
    dumped = instance.model_dump()
    assert dumped["features"]["only_key"] == {
        "value": "hello",
        "present": True,
        "evidence": "hello",
    }
    assert dumped["entities"] == []


def test_the_returned_model_rejects_an_undeclared_feature_key(
    feature_factory: FeatureFactory,
) -> None:
    """`extra="forbid"` at the `features` level: this is the schema the
    endpoint is constrained against, so an answer with a key the schema never
    declared is invalid input to the model itself, not something
    `parse_output` has to notice later."""
    from pydantic import ValidationError

    model = build_output_schema([feature_factory("only_key")])
    with pytest.raises(ValidationError):
        model.model_validate(
            {
                "features": {
                    "only_key": {"value": None, "present": False, "evidence": None},
                    "unexpected": {"value": None, "present": False, "evidence": None},
                },
                "entities": [],
            }
        )


def test_schema_is_json_serialisable(feature_factory: FeatureFactory) -> None:
    """Sanity: this is what actually gets sent to the endpoint."""
    schema = build_output_schema([feature_factory("k")]).model_json_schema()
    json.dumps(schema)  # must not raise
