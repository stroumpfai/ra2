"""Drafts: the six setup steps while `launched_at IS NULL` (sw-design.md
§15.2).

**A draft is a saved setup; an evaluation is a pinned one.** Everything here
is about the editable half; `test_launch.py` owns the moment it stops being
editable.
"""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.extraction import EvaluationSize
from ra2.domain.ids import CorpusId, EvaluationId, FeatureConfigId, PromptTemplateId
from ra2.infra.clock import FrozenClock
from ra2.persistence.models import Evaluation
from ra2.services.errors import EvaluationLockedError, NotFoundError
from ra2.services.evaluation_service import EvaluationService
from ra2.services.readmodels import FeatureConfigView

pytestmark = pytest.mark.backend


async def test_save_draft_takes_the_designs_defaults(
    evaluation_service: EvaluationService,
    seed_corpus: Callable[..., Awaitable[CorpusId]],
    seed_template: Callable[..., Awaitable[PromptTemplateId]],
    frozen_config: Callable[..., Awaitable[FeatureConfigView]],
) -> None:
    """Temperature 0.0, seed 42, size `full`, and the **active** template."""
    corpus_id = await seed_corpus()
    template_id = await seed_template()
    config = await frozen_config()

    draft = await evaluation_service.save_draft(
        name="Weather eval", corpus_id=corpus_id, feature_config_id=config.feature_config_id
    )

    assert draft.temperature == 0.0
    assert draft.seed == 42
    assert draft.size is EvaluationSize.FULL
    assert draft.prompt_language == "de"
    assert draft.prompt_template_id == template_id
    assert draft.selected_models == ()
    assert draft.launched_at is None
    assert draft.is_launched is False


async def test_save_draft_survives_having_no_template_yet(
    evaluation_service: EvaluationService,
    seed_corpus: Callable[..., Awaitable[CorpusId]],
    frozen_config: Callable[..., Awaitable[FeatureConfigView]],
) -> None:
    """§15.2: `prompt_template_id` is nullable **on purpose** — a draft can be
    saved before any template exists, and only the launch requires one."""
    corpus_id = await seed_corpus()
    config = await frozen_config()

    draft = await evaluation_service.save_draft(
        name="Weather eval", corpus_id=corpus_id, feature_config_id=config.feature_config_id
    )

    assert draft.prompt_template_id is None


async def test_save_draft_refuses_an_unknown_corpus_or_config(
    evaluation_service: EvaluationService,
    seed_corpus: Callable[..., Awaitable[CorpusId]],
    frozen_config: Callable[..., Awaitable[FeatureConfigView]],
) -> None:
    corpus_id = await seed_corpus()
    config = await frozen_config()

    with pytest.raises(NotFoundError):
        await evaluation_service.save_draft(
            name="x", corpus_id=CorpusId("nope"), feature_config_id=config.feature_config_id
        )
    with pytest.raises(NotFoundError):
        await evaluation_service.save_draft(
            name="x", corpus_id=corpus_id, feature_config_id=FeatureConfigId("nope")
        )


async def test_update_draft_edits_every_step(
    evaluation_service: EvaluationService,
    seed_corpus: Callable[..., Awaitable[CorpusId]],
    seed_template: Callable[..., Awaitable[PromptTemplateId]],
    frozen_config: Callable[..., Awaitable[FeatureConfigView]],
) -> None:
    corpus_id = await seed_corpus()
    template_id = await seed_template()
    config = await frozen_config()
    draft = await evaluation_service.save_draft(
        name="Weather eval", corpus_id=corpus_id, feature_config_id=config.feature_config_id
    )

    updated = await evaluation_service.update_draft(
        draft.evaluation_id,
        name="Weather eval v2",
        prompt_template_id=template_id,
        prompt_language="fr",
        temperature=0.2,
        seed=7,
        size=EvaluationSize.DEV,
        selected_models=("llama3.1:8b-instruct-q8_0",),
    )

    assert updated.name == "Weather eval v2"
    assert updated.prompt_language == "fr"
    assert updated.temperature == 0.2
    assert updated.seed == 7
    assert updated.size is EvaluationSize.DEV
    assert updated.selected_models == ("llama3.1:8b-instruct-q8_0",)
    assert updated.launch_label_count == 1
    # Round-tripped, not just returned: the view is built from the row.
    assert (await evaluation_service.get(draft.evaluation_id)).draft == updated


async def test_update_draft_leaves_untouched_steps_alone(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
) -> None:
    """Every parameter defaults to `None` = "leave it"; a rename must not
    silently clear the model selection."""
    _, _, evaluation_id = await launchable()

    updated = await evaluation_service.update_draft(EvaluationId(evaluation_id), name="Renamed")

    assert updated.name == "Renamed"
    assert updated.selected_models != ()


async def test_update_draft_is_refused_after_launch(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """After the launch commit **every edit path raises** (§15.2), and the
    refusal changes nothing."""
    _, _, evaluation_id = await launchable()
    await evaluation_service.launch(EvaluationId(evaluation_id))

    with pytest.raises(EvaluationLockedError):
        await evaluation_service.update_draft(EvaluationId(evaluation_id), name="Renamed")

    async with db_session_factory() as session:
        name = await session.scalar(select(Evaluation.name).where(Evaluation.id == evaluation_id))
    assert name == "Weather eval"


async def test_update_draft_reports_an_unknown_evaluation(
    evaluation_service: EvaluationService,
) -> None:
    with pytest.raises(NotFoundError):
        await evaluation_service.update_draft(EvaluationId("nope"), name="x")


async def test_get_reports_an_unknown_evaluation(
    evaluation_service: EvaluationService,
) -> None:
    with pytest.raises(NotFoundError):
        await evaluation_service.get(EvaluationId("nope"))


async def test_list_evaluations_is_newest_first_and_includes_drafts(
    evaluation_service: EvaluationService,
    seed_corpus: Callable[..., Awaitable[CorpusId]],
    frozen_config: Callable[..., Awaitable[FeatureConfigView]],
    clock: FrozenClock,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    corpus_id = await seed_corpus()
    config = await frozen_config()
    first = await evaluation_service.save_draft(
        name="First", corpus_id=corpus_id, feature_config_id=config.feature_config_id
    )
    # The clock is frozen, so `created_at` would tie; move it so "newest
    # first" is an ordering and not an accident of insertion.
    clock.advance(seconds=60)
    second = await evaluation_service.save_draft(
        name="Second", corpus_id=corpus_id, feature_config_id=config.feature_config_id
    )

    listed = await evaluation_service.list_evaluations()

    assert [view.evaluation_id for view in listed] == [second.evaluation_id, first.evaluation_id]
    assert all(view.launched_at is None for view in listed)
    async with db_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Evaluation)) == 2
