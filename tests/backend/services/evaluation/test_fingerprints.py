"""Phase 2 Q3's promise, now testable (mvp-spec.md §8.5, sw-design.md §15.2).

> `feature.fingerprint` remains the draft-time **preview**: the same function
> over the same inputs minus the snapshot, which is exactly why a preview badge
> and a run's fingerprint can legitimately differ.

The claim under test is the "exactly when": an `evaluation_feature`
fingerprint differs from its draft preview **precisely** when the codelist
snapshot differs, and agrees otherwise. Both directions are asserted in one
launch, over one feature set holding one enum feature and one free-text one,
so a bug that moved every fingerprint would fail just as loudly as one that
moved none.
"""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.fingerprint import FingerprintInput, compute_fingerprint
from ra2.domain.ids import CorpusId, EvaluationId
from ra2.persistence.models import EvaluationFeature
from ra2.services.evaluation_service import EvaluationService
from ra2.services.feature_service import FeatureService, matching_rule_json
from ra2.services.readmodels import FeatureConfigView

pytestmark = pytest.mark.backend


async def _stored(
    session_factory: async_sessionmaker[AsyncSession], evaluation_id: str
) -> dict[str, EvaluationFeature]:
    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(EvaluationFeature).where(EvaluationFeature.evaluation_id == evaluation_id)
            )
        ).all()
    return {row.feature_id: row for row in rows}


async def test_the_fingerprint_differs_from_the_preview_exactly_when_the_snapshot_does(
    evaluation_service: EvaluationService,
    feature_service: FeatureService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    db_session_factory: async_sessionmaker[AsyncSession],
    make_enum_feature: Callable[..., dict[str, object]],
    make_text_feature: Callable[..., dict[str, object]],
) -> None:
    _, config, evaluation_id = await launchable(make_enum_feature(), make_text_feature())
    await evaluation_service.launch(EvaluationId(evaluation_id))

    # The preview is read back through `feature_service`, not recomputed here:
    # the claim is about what the two services produce, not about what this
    # test thinks they should.
    preview = {
        feature.feature_id: feature.fingerprint_preview
        for feature in (await feature_service.get(config.feature_config_id)).features
    }
    by_key = {feature.key: feature.feature_id for feature in config.features}
    stored = await _stored(db_session_factory, evaluation_id)

    enum_id = by_key["weather"]
    text_id = by_key["injury_note"]

    # An enum feature: the snapshot resolved, so the fingerprint moved.
    assert stored[enum_id].enum_codelist_json is not None
    assert stored[enum_id].fingerprint != preview[enum_id]

    # Everything else: no snapshot, so the same eight inputs and the same hash.
    assert stored[text_id].enum_codelist_json is None
    assert stored[text_id].fingerprint == preview[text_id]


async def test_the_stored_fingerprint_is_the_hash_of_the_stored_snapshot(
    evaluation_service: EvaluationService,
    feature_service: FeatureService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`compute_fingerprint` is phase 2's and is unchanged; the launch is its
    **second caller**, differing only in the snapshot it passes. Recomputing
    from the row's own eight §8.5 inputs must land on the stored value —
    otherwise the row is not self-describing and §19.8 is not satisfied."""
    _, config, evaluation_id = await launchable()
    await evaluation_service.launch(EvaluationId(evaluation_id))
    feature = (await feature_service.get(config.feature_config_id)).features[0]
    stored = (await _stored(db_session_factory, evaluation_id))[feature.feature_id]

    recomputed = compute_fingerprint(
        FingerprintInput(
            kind=feature.kind,
            grain=feature.grain,
            source_column=feature.source_column,
            derivation_json=None,
            value_type=feature.value_type,
            matching_rule_json=matching_rule_json(feature.matching_rule),
            enum_codelist_json=stored.enum_codelist_json,
            description=feature.description,
        )
    )

    assert stored.fingerprint == recomputed


async def test_two_launches_of_the_same_inputs_fingerprint_identically(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    db_session_factory: async_sessionmaker[AsyncSession],
    fitting_model: str,
) -> None:
    """Stability, the other half of what a fingerprint is for: the same corpus,
    the same frozen config and the same mapping generation must hash the same
    way twice, or "a re-run is a check" means nothing."""
    corpus_id, config, first_id = await launchable()
    await evaluation_service.launch(EvaluationId(first_id))

    second = await evaluation_service.save_draft(
        name="Same inputs again",
        corpus_id=corpus_id,
        feature_config_id=config.feature_config_id,
    )
    await evaluation_service.update_draft(second.evaluation_id, selected_models=(fitting_model,))
    await evaluation_service.launch(second.evaluation_id)

    first = await _stored(db_session_factory, first_id)
    again = await _stored(db_session_factory, second.evaluation_id)

    assert {row.fingerprint for row in first.values()} == {
        row.fingerprint for row in again.values()
    }
