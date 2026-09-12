"""Adding, editing and deleting features inside a draft."""

import pytest

from ra2.domain.feature import (
    AnyObjectMatches,
    AnyPersonMatches,
    CountObjects,
    CountPersons,
    DistinctCount,
    Filter,
    Grain,
    Kind,
    MatchingRule,
    MatchingRuleKind,
    MaxOrdinal,
    MinOrdinal,
    Operator,
    ValueType,
    derivation_from_json,
    derivation_to_json,
)
from ra2.domain.ids import FeatureId
from ra2.services.errors import FeatureConfigFrozenError, NotFoundError

pytestmark = pytest.mark.backend

#: One of each of mvp-spec.md §8.3's seven derivation shapes, each with the
#: parameter that makes it non-trivial to serialise: a tuple-valued `in`
#: filter, a `None` filter, an ordered code list, an empty-value operator.
EVERY_DERIVATION = (
    CountObjects(filter=None),
    CountObjects(filter=Filter(column="FahrzeugartAusw", operator=Operator.EQ, value="M12")),
    CountPersons(filter=Filter(column="VerletzungsgradAusw", operator=Operator.IS_NOT_EMPTY)),
    AnyObjectMatches(
        filter=Filter(column="FahrzeugartAusw", operator=Operator.IN, value=("M12", "M13"))
    ),
    AnyPersonMatches(
        filter=Filter(column="GeschlechtAusw", operator=Operator.NOT_IN, value=("1", "2"))
    ),
    MaxOrdinal(table="person", column="VerletzungsgradAusw", ordered_codes=("1", "2", "3", "4")),
    MinOrdinal(table="objekt", column="SchadenAusw", ordered_codes=("A", "B")),
    DistinctCount(table="objekt", column="FahrzeugartAusw"),
)


async def test_add_feature_returns_the_whole_updated_set(feature_service, feature_kwargs):
    draft = await feature_service.create_draft(name="Weather & conditions")

    view = await feature_service.add_feature(
        draft.feature_config_id, **feature_kwargs(key="weather")
    )

    assert [f.key for f in view.features] == ["weather"]
    only = view.features[0]
    assert only.feature_config_id == draft.feature_config_id
    assert only.ordinal == 0
    assert only.kind is Kind.LABELLED
    assert only.grain is Grain.ACCIDENT
    assert only.value_type is ValueType.ENUM
    assert only.source_column == "WitterungAusw"
    assert only.derivation is None
    assert only.matching_rule == MatchingRule(kind=MatchingRuleKind.EXACT)
    # §8.5's snapshot is taken at evaluation creation; phase 2 has none.
    assert only.enum_codelist is None
    assert only.fingerprint is None
    assert len(only.fingerprint_preview) == 64


async def test_ordinals_are_dense_and_ordered(feature_service, draft_with):
    view = await draft_with({"key": "a"}, {"key": "b"}, {"key": "c"})

    assert [(f.key, f.ordinal) for f in view.features] == [("a", 0), ("b", 1), ("c", 2)]


async def test_delete_feature_compacts_the_remaining_ordinals(feature_service, draft_with):
    """`add_feature` takes the next ordinal from the feature count, so a gap
    left by a delete would make two rows collide on the same display slot."""
    view = await draft_with({"key": "a"}, {"key": "b"}, {"key": "c"})
    middle = view.features[1].feature_id

    await feature_service.delete_feature(view.feature_config_id, middle)
    after = await feature_service.get(view.feature_config_id)

    assert [(f.key, f.ordinal) for f in after.features] == [("a", 0), ("c", 1)]


async def test_a_feature_added_after_a_delete_lands_last(
    feature_service, draft_with, feature_kwargs
):
    view = await draft_with({"key": "a"}, {"key": "b"})
    await feature_service.delete_feature(view.feature_config_id, view.features[0].feature_id)

    after = await feature_service.add_feature(view.feature_config_id, **feature_kwargs(key="c"))

    assert [(f.key, f.ordinal) for f in after.features] == [("b", 0), ("c", 1)]


async def test_edit_feature_replaces_every_field(feature_service, draft_with, feature_kwargs):
    view = await draft_with({"key": "weather"})
    feature_id = view.features[0].feature_id

    edited = await feature_service.edit_feature(
        view.feature_config_id,
        feature_id,
        **feature_kwargs(
            key="accident_time",
            description="The time on the clock when it happened.",
            source_column="UnfallZeitFeld",
            value_type=ValueType.TIME,
            matching_rule=MatchingRule(
                kind=MatchingRuleKind.WITHIN_TOLERANCE, tolerance_minutes=15
            ),
        ),
    )

    only = edited.features[0]
    assert only.feature_id == feature_id
    assert only.key == "accident_time"
    assert only.source_column == "UnfallZeitFeld"
    assert only.value_type is ValueType.TIME
    assert only.matching_rule == MatchingRule(
        kind=MatchingRuleKind.WITHIN_TOLERANCE, tolerance_minutes=15
    )


async def test_editing_the_tolerance_moves_the_preview_fingerprint(
    feature_service, draft_with, feature_kwargs
):
    """The design's "changing it changes the fingerprint" — the parameter
    travels in the hash, not just the rule name (mvp-spec.md §8.5)."""
    view = await draft_with(
        {
            "value_type": ValueType.TIME,
            "matching_rule": MatchingRule(
                kind=MatchingRuleKind.WITHIN_TOLERANCE, tolerance_minutes=15
            ),
        }
    )
    before = view.features[0].fingerprint_preview

    edited = await feature_service.edit_feature(
        view.feature_config_id,
        view.features[0].feature_id,
        **feature_kwargs(
            value_type=ValueType.TIME,
            matching_rule=MatchingRule(kind=MatchingRuleKind.WITHIN_TOLERANCE, tolerance_minutes=5),
        ),
    )

    assert edited.features[0].fingerprint_preview != before


@pytest.mark.parametrize("derivation", EVERY_DERIVATION, ids=lambda d: type(d).__name__)
async def test_every_derivation_round_trips_through_a_feature(
    feature_service, draft_with, derivation
):
    """Stored as `derivation_json` and read back by D2's codec — this asserts
    the service hands the codec the right thing, not the codec itself."""
    view = await draft_with(
        {"grain": Grain.DERIVED, "source_column": None, "derivation": derivation}
    )

    stored = view.features[0].derivation

    assert stored == derivation
    assert derivation_from_json(derivation_to_json(derivation)) == stored


async def test_edit_of_an_unknown_feature_is_not_found(feature_service, draft_with, feature_kwargs):
    view = await draft_with({})

    with pytest.raises(NotFoundError) as missing:
        await feature_service.edit_feature(
            view.feature_config_id, FeatureId("no-such-feature"), **feature_kwargs()
        )

    assert missing.value.kind == "feature"


async def test_a_feature_of_another_set_is_not_found(feature_service, draft_with, feature_kwargs):
    """A valid id belonging to a different set must not be editable through
    this one — otherwise a stale UI selection edits someone else's row."""
    mine = await draft_with({"key": "weather"}, name="Weather & conditions")
    theirs = await draft_with({"key": "surface"}, name="Road surface")

    with pytest.raises(NotFoundError):
        await feature_service.edit_feature(
            mine.feature_config_id, theirs.features[0].feature_id, **feature_kwargs()
        )
    with pytest.raises(NotFoundError):
        await feature_service.delete_feature(mine.feature_config_id, theirs.features[0].feature_id)


async def test_every_write_path_refuses_a_frozen_set(feature_service, draft_with, feature_kwargs):
    draft = await draft_with({"key": "weather"})
    frozen = await feature_service.freeze(draft.feature_config_id)
    feature_id = frozen.features[0].feature_id

    with pytest.raises(FeatureConfigFrozenError):
        await feature_service.add_feature(frozen.feature_config_id, **feature_kwargs(key="light"))
    with pytest.raises(FeatureConfigFrozenError):
        await feature_service.edit_feature(
            frozen.feature_config_id, feature_id, **feature_kwargs(description="reworded")
        )
    with pytest.raises(FeatureConfigFrozenError):
        await feature_service.delete_feature(frozen.feature_config_id, feature_id)
    with pytest.raises(FeatureConfigFrozenError):
        await feature_service.freeze(frozen.feature_config_id)

    after = await feature_service.get(frozen.feature_config_id)
    assert [f.key for f in after.features] == ["weather"]
    assert after.features[0].description == frozen.features[0].description
