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
from tests.fixtures.fake_llm import StaticEndpointProber, StaticModelCatalog

from ra2.domain.extraction import EvaluationSize
from ra2.domain.ids import CorpusId, EvaluationId, FeatureConfigId, PromptTemplateId
from ra2.infra.clock import FrozenClock
from ra2.infra.config import Settings
from ra2.infra.gpu import StaticGpuProbe
from ra2.infra.idgen import SeededFactory
from ra2.persistence.models import Evaluation
from ra2.services.errors import (
    EvaluationLockedError,
    FeatureValidationError,
    NotFoundError,
)
from ra2.services.evaluation_service import (
    EVAL_ERROR_MIN_CELL_COUNT_BELOW_ONE,
    EvaluationService,
)
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
    # One of the two defaults read from `Settings` rather than named in the
    # service: an analyst who set `RA2_LLM_REASONING_EFFORT` has already said
    # what a new evaluation should ask. The other, the floor, is below.
    assert draft.reasoning_effort == "none"
    assert draft.size is EvaluationSize.FULL
    assert draft.prompt_language == "de"
    assert draft.prompt_template_id == template_id
    assert draft.selected_models == ()
    assert draft.launched_at is None
    assert draft.is_launched is False


def _service_with(
    settings: Settings,
    db_session_factory: async_sessionmaker[AsyncSession],
    model_catalog: StaticModelCatalog,
    endpoint_prober: StaticEndpointProber,
    gpu_probe: StaticGpuProbe,
    clock: FrozenClock,
    ids: SeededFactory,
) -> EvaluationService:
    """The conftest's `evaluation_service`, on a `Settings` of the test's own."""
    return EvaluationService(
        session_factory=db_session_factory,
        model_catalog=model_catalog,
        endpoint_prober=endpoint_prober,
        gpu_probe=gpu_probe,
        clock=clock,
        ids=ids,
        settings=settings,
    )


async def _stored_floor(
    db_session_factory: async_sessionmaker[AsyncSession], evaluation_id: EvaluationId
) -> int:
    async with db_session_factory() as session:
        row = await session.get(Evaluation, evaluation_id)
    assert row is not None
    return row.min_cell_count


async def test_the_draft_floor_comes_from_the_settings(
    eval_settings: Settings,
    db_session_factory: async_sessionmaker[AsyncSession],
    model_catalog: StaticModelCatalog,
    endpoint_prober: StaticEndpointProber,
    gpu_probe: StaticGpuProbe,
    clock: FrozenClock,
    ids: SeededFactory,
    seed_corpus: Callable[..., Awaitable[CorpusId]],
    frozen_config: Callable[..., Awaitable[FeatureConfigView]],
) -> None:
    """`SD42`: `RA2_MIN_CELL_COUNT` seeds the draft's floor, as `models.py`
    said it did from phase 4 while nothing read it.

    The value is deliberately **not** the column's own `20`: a test at the
    default cannot tell a seed from a fallback, which is exactly how the
    missing reader went unnoticed.
    """
    settings = eval_settings.model_copy(update={"min_cell_count": 30})
    assert settings.min_cell_count != Evaluation.__table__.c.min_cell_count.default.arg
    service = _service_with(
        settings, db_session_factory, model_catalog, endpoint_prober, gpu_probe, clock, ids
    )
    corpus_id = await seed_corpus()
    config = await frozen_config()

    draft = await service.save_draft(
        name="Floor", corpus_id=corpus_id, feature_config_id=config.feature_config_id
    )

    assert await _stored_floor(db_session_factory, draft.evaluation_id) == settings.min_cell_count


async def test_a_later_settings_change_does_not_move_an_existing_draft(
    eval_settings: Settings,
    db_session_factory: async_sessionmaker[AsyncSession],
    model_catalog: StaticModelCatalog,
    endpoint_prober: StaticEndpointProber,
    gpu_probe: StaticGpuProbe,
    clock: FrozenClock,
    ids: SeededFactory,
    seed_corpus: Callable[..., Awaitable[CorpusId]],
    frozen_config: Callable[..., Awaitable[FeatureConfigView]],
) -> None:
    """The floor is read **once**, when the draft is saved. A host whose
    environment changes afterwards moves its next draft, never this one — the
    floor is an input to the evaluation, not a view onto the process."""
    before = eval_settings.model_copy(update={"min_cell_count": 30})
    after = eval_settings.model_copy(update={"min_cell_count": 5})
    wiring = (db_session_factory, model_catalog, endpoint_prober, gpu_probe, clock, ids)
    corpus_id = await seed_corpus()
    config = await frozen_config()

    first = await _service_with(before, *wiring).save_draft(
        name="Before", corpus_id=corpus_id, feature_config_id=config.feature_config_id
    )
    second = await _service_with(after, *wiring).save_draft(
        name="After", corpus_id=corpus_id, feature_config_id=config.feature_config_id
    )

    assert await _stored_floor(db_session_factory, first.evaluation_id) == before.min_cell_count
    assert await _stored_floor(db_session_factory, second.evaluation_id) == after.min_cell_count


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
        reasoning_effort="medium",
        size=EvaluationSize.DEV,
        selected_models=("llama3.1:8b-instruct-q8_0",),
        min_cell_count=5,
    )

    assert updated.name == "Weather eval v2"
    assert updated.prompt_language == "fr"
    assert updated.temperature == 0.2
    assert updated.seed == 7
    assert updated.reasoning_effort == "medium"
    assert updated.size is EvaluationSize.DEV
    assert updated.selected_models == ("llama3.1:8b-instruct-q8_0",)
    assert updated.launch_label_count == 1
    assert updated.min_cell_count == 5
    # Round-tripped, not just returned: the view is built from the row.
    assert (await evaluation_service.get(draft.evaluation_id)).draft == updated


async def test_an_effort_the_endpoint_cannot_map_is_refused_and_changes_nothing(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
) -> None:
    """Ollama maps `none|low|medium|high` and nothing else, and an unmappable
    value costs one `RA2_LLM_TIMEOUT_S` **per record** to discover — after the
    analyst has launched and walked away. Refused here, where the repair is
    still one click, and refused in the service rather than in `ui/` so a
    request that never went through the view is refused too.

    The `Settings` validator draws the same line for the process default; this
    is the same rule at the other end of the same vocabulary.
    """
    _, _, evaluation_id = await launchable()
    before = await evaluation_service.get(EvaluationId(evaluation_id))

    with pytest.raises(FeatureValidationError) as excinfo:
        await evaluation_service.update_draft(EvaluationId(evaluation_id), reasoning_effort="xhigh")

    # The sentence names what it could have been — a refusal that only says
    # "no" has done half the job (the `PROBE_WORDS` discipline).
    (message,) = excinfo.value.validation_errors
    assert "xhigh" in message
    assert "none, low, medium, high" in message
    # Nothing changed: the whole update is one transaction.
    assert (await evaluation_service.get(EvaluationId(evaluation_id))).draft == before.draft


async def test_a_floor_below_one_is_refused_and_changes_nothing(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
) -> None:
    """Below 1 there is no cell the floor could suppress. Refused in the
    service, for the reasoning effort's reason: the same rule holds for a
    request that never went through the view."""
    _, _, evaluation_id = await launchable()
    before = await evaluation_service.get(EvaluationId(evaluation_id))

    with pytest.raises(FeatureValidationError) as excinfo:
        await evaluation_service.update_draft(
            EvaluationId(evaluation_id), name="renamed", min_cell_count=0
        )

    assert excinfo.value.validation_errors == (EVAL_ERROR_MIN_CELL_COUNT_BELOW_ONE.format(floor=0),)
    # Nothing changed — not the floor, and not the name set in the same call.
    assert (await evaluation_service.get(EvaluationId(evaluation_id))).draft == before.draft


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
