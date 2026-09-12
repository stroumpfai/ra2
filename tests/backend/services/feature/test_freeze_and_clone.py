"""`freeze()` — the one hard gate — and `clone()`."""

import pytest

from ra2.domain.codelist_coverage import CoverageStatus
from ra2.domain.feature import (
    EXPLORATORY_FEATURE_CAP,
    AnyObjectMatches,
    Filter,
    Grain,
    Kind,
    MatchingRule,
    MatchingRuleKind,
    Operator,
    ValueType,
)
from ra2.domain.fingerprint import FingerprintInput, compute_fingerprint
from ra2.domain.ids import FeatureConfigId
from ra2.services.errors import FeatureValidationError, NotFoundError
from ra2.services.feature_service import (
    FEATURE_ERROR_CLONE_OF_DRAFT,
    FEATURE_ERROR_EXPLORATORY_CAP,
    FEATURE_ERROR_NO_CODELIST,
    FEATURE_ERROR_NON_SCALAR_GRAIN,
    matching_rule_json,
)

pytestmark = pytest.mark.backend

EXPLORATORY = {
    "kind": Kind.EXPLORATORY,
    "grain": Grain.ACCIDENT,
    "source_column": None,
    "value_type": ValueType.FREE_TEXT,
    "matching_rule": MatchingRule(kind=MatchingRuleKind.NONE),
}


async def test_freeze_stamps_frozen_at_and_stores_every_fingerprint(
    feature_service, draft_with, clock
):
    view = await draft_with(
        {"key": "weather", "value_type": ValueType.INTEGER},
        {**EXPLORATORY, "key": "phone_use"},
    )

    frozen = await feature_service.freeze(view.feature_config_id)

    assert frozen.is_frozen is True
    assert frozen.frozen_at == clock.now().replace(tzinfo=None)
    assert all(f.fingerprint is not None for f in frozen.features)
    # Q3: the preview and the real value differ only in the §8.5 snapshot,
    # which is still `None` in phase 2 — so here they must agree exactly.
    assert [f.fingerprint for f in frozen.features] == [
        f.fingerprint_preview for f in frozen.features
    ]


async def test_the_stored_fingerprint_is_mvp_spec_8_5s_hash(feature_service, draft_with):
    """Recomputed here from the eight fields, so a change of what the service
    feeds `compute_fingerprint` fails rather than silently re-baselining."""
    derivation = AnyObjectMatches(
        filter=Filter(column="FahrzeugartAusw", operator=Operator.IN, value=("M12", "M13"))
    )
    view = await draft_with(
        {
            "key": "bicycle_involved",
            "description": "Was a bicycle involved?",
            "grain": Grain.DERIVED,
            "source_column": None,
            "derivation": derivation,
            "value_type": ValueType.BOOLEAN,
        }
    )

    frozen = await feature_service.freeze(view.feature_config_id)

    only = frozen.features[0]
    assert only.fingerprint == compute_fingerprint(
        FingerprintInput(
            kind=Kind.LABELLED,
            grain=Grain.DERIVED,
            source_column=None,
            derivation_json='{"filter":{"column":"FahrzeugartAusw","operator":"in",'
            '"value":["M12","M13"]},"type":"any_object_matches"}',
            value_type=ValueType.BOOLEAN,
            matching_rule_json=matching_rule_json(MatchingRule(kind=MatchingRuleKind.EXACT)),
            enum_codelist_json=None,
            description="Was a bicycle involved?",
        )
    )


async def test_matching_rule_json_is_canonical_and_carries_its_parameters():
    """mvp-spec.md §8.5: the rule travels "incl. parameters". Keys are sorted
    and always present, so the same rule hashes the same way twice."""
    assert matching_rule_json(MatchingRule(kind=MatchingRuleKind.EXACT)) == (
        '{"decimal_precision":null,"kind":"exact","tolerance_minutes":null}'
    )
    assert matching_rule_json(
        MatchingRule(kind=MatchingRuleKind.WITHIN_TOLERANCE, tolerance_minutes=15)
    ) == ('{"decimal_precision":null,"kind":"within_tolerance","tolerance_minutes":15}')


async def test_freeze_writes_nothing_when_a_grain_blocks(feature_service, draft_with):
    view = await draft_with(
        {"key": "weather", "value_type": ValueType.INTEGER},
        {"key": "damage_per_vehicle", "grain": Grain.OBJECT, "source_column": "SchadenAusw"},
    )

    with pytest.raises(FeatureValidationError) as blocked:
        await feature_service.freeze(view.feature_config_id)

    assert blocked.value.validation_errors == (
        FEATURE_ERROR_NON_SCALAR_GRAIN.format(key="damage_per_vehicle", grain="object"),
    )
    after = await feature_service.get(view.feature_config_id)
    assert after.frozen_at is None
    assert all(f.fingerprint is None for f in after.features)


async def test_freeze_is_blocked_by_the_exploratory_cap(feature_service, draft_with):
    view = await draft_with(
        *[{**EXPLORATORY, "key": f"probe_{n:02d}"} for n in range(EXPLORATORY_FEATURE_CAP + 2)]
    )

    with pytest.raises(FeatureValidationError) as blocked:
        await feature_service.freeze(view.feature_config_id)

    assert blocked.value.validation_errors == (
        FEATURE_ERROR_EXPLORATORY_CAP.format(key="probe_20", cap=EXPLORATORY_FEATURE_CAP),
        FEATURE_ERROR_EXPLORATORY_CAP.format(key="probe_21", cap=EXPLORATORY_FEATURE_CAP),
    )
    assert (await feature_service.get(view.feature_config_id)).frozen_at is None


async def test_freeze_carries_every_blocking_message_from_both_tiers(
    feature_service, draft_with, validation_corpus
):
    """The design's "2 errors block set creation" counts across the whole
    set, not the selected row."""
    view = await draft_with(
        {"key": "right_of_way", "source_column": "VortrittAusw"},
        {"key": "damage_per_vehicle", "grain": Grain.OBJECT, "source_column": "SchadenAusw"},
    )

    with pytest.raises(FeatureValidationError) as blocked:
        await feature_service.freeze(view.feature_config_id, validate_against=validation_corpus)

    assert set(blocked.value.validation_errors) == {
        FEATURE_ERROR_NO_CODELIST.format(key="right_of_way", column="VortrittAusw"),
        FEATURE_ERROR_NON_SCALAR_GRAIN.format(key="damage_per_vehicle", grain="object"),
        FEATURE_ERROR_NO_CODELIST.format(key="damage_per_vehicle", column="SchadenAusw"),
    }


async def test_a_codeless_enum_freezes_when_no_corpus_is_named(
    feature_service, draft_with, codelist_provider, validation_corpus
):
    """C3: a feature set is corpus-independent. Without `validate_against`
    the codelist tier is not run, so the set is freezable — and the *same*
    set is refused the moment a corpus is named."""
    view = await draft_with({"key": "right_of_way", "source_column": "VortrittAusw"})

    with pytest.raises(FeatureValidationError):
        await feature_service.freeze(view.feature_config_id, validate_against=validation_corpus)
    frozen = await feature_service.freeze(view.feature_config_id)

    assert frozen.is_frozen is True
    assert codelist_provider.columns_asked == ["VortrittAusw"]


async def test_freeze_passes_once_the_column_has_codes(
    feature_service, draft_with, codelist_provider, column_coverage, validation_corpus
):
    codelist_provider.answers["WitterungAusw"] = column_coverage(CoverageStatus.PARTIAL)
    view = await draft_with({"key": "weather"})

    frozen = await feature_service.freeze(
        view.feature_config_id, validate_against=validation_corpus
    )

    assert frozen.is_frozen is True
    assert frozen.features[0].validation_errors == ()


async def test_freeze_of_an_unknown_set_is_not_found(feature_service):
    with pytest.raises(NotFoundError):
        await feature_service.freeze(FeatureConfigId("no-such-config"))


# --- clone -----------------------------------------------------------------


async def test_clone_of_a_frozen_set_is_a_fresh_draft(feature_service, draft_with):
    source = await draft_with({"key": "weather", "value_type": ValueType.INTEGER})
    frozen = await feature_service.freeze(source.feature_config_id)

    clone = await feature_service.clone(frozen.feature_config_id, name="Weather & conditions")

    assert clone.feature_config_id != frozen.feature_config_id
    assert clone.version == 2
    assert clone.frozen_at is None
    assert [f.key for f in clone.features] == ["weather"]
    only = clone.features[0]
    assert only.feature_id != frozen.features[0].feature_id
    # A clone is a new draft, not a copy of history.
    assert only.fingerprint is None
    assert only.enum_codelist is None
    # The definition is identical, so the preview hash is too.
    assert only.fingerprint_preview == frozen.features[0].fingerprint_preview


async def test_a_clone_shares_no_mutable_state_with_its_source(
    feature_service, draft_with, feature_kwargs
):
    source = await draft_with(
        {"key": "weather", "value_type": ValueType.INTEGER},
        {"key": "light", "value_type": ValueType.INTEGER},
    )
    frozen = await feature_service.freeze(source.feature_config_id)
    clone = await feature_service.clone(frozen.feature_config_id, name="Wetter")

    await feature_service.edit_feature(
        clone.feature_config_id,
        clone.features[0].feature_id,
        **feature_kwargs(
            key="wetter",
            description="Das Wetter zum Unfallzeitpunkt.",
            value_type=ValueType.INTEGER,
        ),
    )
    await feature_service.delete_feature(clone.feature_config_id, clone.features[1].feature_id)

    original = await feature_service.get(frozen.feature_config_id)
    assert [f.key for f in original.features] == ["weather", "light"]
    assert original.features[0].description == frozen.features[0].description
    assert original.features[0].fingerprint == frozen.features[0].fingerprint
    edited = await feature_service.get(clone.feature_config_id)
    assert [f.key for f in edited.features] == ["wetter"]


async def test_clone_refuses_a_draft(feature_service, draft_with):
    """A draft is editable already; cloning one would only duplicate it."""
    draft = await draft_with({})

    with pytest.raises(FeatureValidationError) as refused:
        await feature_service.clone(draft.feature_config_id, name="Copy")

    assert refused.value.validation_errors == (
        FEATURE_ERROR_CLONE_OF_DRAFT.format(name="Weather & conditions"),
    )
    assert len(await feature_service.list_configs()) == 1


async def test_clone_of_an_unknown_set_is_not_found(feature_service):
    with pytest.raises(NotFoundError):
        await feature_service.clone(FeatureConfigId("no-such-config"), name="Copy")
