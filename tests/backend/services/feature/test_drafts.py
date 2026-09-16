"""Draft lifecycle: create, read, list, rename, delete."""

import pytest

from ra2.domain.ids import FeatureConfigId
from ra2.services.errors import FeatureConfigFrozenError, NotFoundError

pytestmark = pytest.mark.backend


async def test_create_draft_is_version_one_and_not_frozen(feature_service, clock):
    view = await feature_service.create_draft(name="Weather & conditions", description="v1 draft")

    assert view.name == "Weather & conditions"
    assert view.version == 1
    assert view.description == "v1 draft"
    # Aware, because `models.UtcDateTime` re-attaches UTC on load (P3-D15).
    assert view.created_at == clock.now()
    assert view.frozen_at is None
    assert view.is_frozen is False
    assert view.features == ()


async def test_next_version_is_monotonic_per_name(feature_service):
    first = await feature_service.create_draft(name="Weather & conditions")
    second = await feature_service.create_draft(name="Weather & conditions")
    other = await feature_service.create_draft(name="Road surface")

    assert (first.version, second.version, other.version) == (1, 2, 1)


async def test_get_raises_not_found_for_an_unknown_set(feature_service):
    with pytest.raises(NotFoundError) as missing:
        await feature_service.get(FeatureConfigId("no-such-config"))

    assert missing.value.kind == "feature config"


async def test_list_configs_counts_features_and_citing_evaluations(
    feature_service, draft_with, seed_evaluation
):
    cited = await draft_with({"key": "weather"}, {"key": "light"})
    await feature_service.create_draft(name="Road surface")
    await seed_evaluation(cited.feature_config_id)

    summaries = {s.feature_config_id: s for s in await feature_service.list_configs()}

    assert len(summaries) == 2
    assert summaries[cited.feature_config_id].feature_count == 2
    assert summaries[cited.feature_config_id].locked_by_evaluations == 1
    assert summaries[cited.feature_config_id].is_frozen is False
    other = next(s for s in summaries.values() if s.feature_config_id != cited.feature_config_id)
    assert (other.feature_count, other.locked_by_evaluations) == (0, 0)


async def test_get_reports_citing_evaluations(feature_service, draft_with, seed_evaluation):
    draft = await draft_with({})
    await seed_evaluation(draft.feature_config_id, name="eval-a")
    await seed_evaluation(draft.feature_config_id, name="eval-b")

    assert (await feature_service.get(draft.feature_config_id)).locked_by_evaluations == 2


async def test_rename_keeps_the_id_and_the_features(feature_service, draft_with):
    draft = await draft_with({"key": "weather"})

    renamed = await feature_service.rename(draft.feature_config_id, name="Wetter")

    assert renamed.feature_config_id == draft.feature_config_id
    assert renamed.name == "Wetter"
    assert [f.key for f in renamed.features] == ["weather"]


async def test_rename_into_an_occupied_name_takes_the_next_version(feature_service):
    """`uq_feature_config_name_version` would otherwise surface an
    `IntegrityError` from the flush. The rename re-derives the version for
    its new name, the way `create_draft` does."""
    await feature_service.create_draft(name="Wetter")
    draft = await feature_service.create_draft(name="Weather & conditions")

    renamed = await feature_service.rename(draft.feature_config_id, name="Wetter")

    assert (renamed.name, renamed.version) == ("Wetter", 2)


async def test_rename_to_the_same_name_does_not_bump_the_version(feature_service):
    draft = await feature_service.create_draft(name="Wetter")

    renamed = await feature_service.rename(draft.feature_config_id, name="Wetter")

    assert renamed.version == 1


async def test_delete_removes_a_draft_and_its_features(feature_service, draft_with):
    draft = await draft_with({})

    await feature_service.delete(draft.feature_config_id)

    assert await feature_service.list_configs() == []
    with pytest.raises(NotFoundError):
        await feature_service.get(draft.feature_config_id)


async def test_delete_of_an_unknown_set_is_not_found(feature_service):
    with pytest.raises(NotFoundError):
        await feature_service.delete(FeatureConfigId("no-such-config"))


async def test_rename_and_delete_refuse_a_frozen_set(feature_service, draft_with):
    draft = await draft_with({})
    frozen = await feature_service.freeze(draft.feature_config_id)

    with pytest.raises(FeatureConfigFrozenError) as refused:
        await feature_service.rename(frozen.feature_config_id, name="Wetter")
    with pytest.raises(FeatureConfigFrozenError):
        await feature_service.delete(frozen.feature_config_id)

    assert refused.value.feature_config_id == frozen.feature_config_id
    assert (await feature_service.get(frozen.feature_config_id)).name == "Weather & conditions"
