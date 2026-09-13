"""The launch transaction (sw-design.md §15.2, plan-phase-3.md §14 R5).

`plan-phase-3.md` R5: *if `evaluation_feature` is wrong, every fingerprint is
wrong.* Every refusal below is therefore asserted twice — that it raised, and
that it left **zero** `evaluation_feature` rows, **zero** `run` rows and a
`launched_at` still `NULL`. "Nothing is created" is a row count, not the
absence of an exception.
"""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.fake_llm import StaticModelCatalog

from ra2.domain.extraction import EvaluationSize, RunStatus
from ra2.domain.ids import CodeAttributeId, CorpusId, EvaluationId, PromptTemplateId
from ra2.domain.llm import EndpointStatus
from ra2.infra.clock import FrozenClock
from ra2.infra.config import Settings
from ra2.infra.gpu import GpuInfo, StaticGpuProbe
from ra2.infra.idgen import SeededFactory
from ra2.persistence.models import Evaluation, EvaluationFeature, Run
from ra2.services.errors import EvaluationLockedError, FeatureValidationError
from ra2.services.evaluation_service import (
    EVAL_ERROR_CONFIG_NOT_FROZEN,
    EVAL_ERROR_ENDPOINT_UNREACHABLE,
    EVAL_ERROR_ENUM_NO_CODELIST,
    EVAL_ERROR_ENUM_NO_LABEL_IN_LANGUAGE,
    EVAL_ERROR_MODEL_EXCEEDS_VRAM,
    EVAL_ERROR_NO_MODELS_SELECTED,
    EVAL_ERROR_NO_TEMPLATE,
    EvaluationService,
    snapshot_from_json,
)
from ra2.services.readmodels import FeatureConfigView

pytestmark = pytest.mark.backend


async def _counts(
    session_factory: async_sessionmaker[AsyncSession], evaluation_id: str
) -> tuple[int, int, object]:
    """`(evaluation_feature rows, run rows, launched_at)` — what "nothing was
    created" is measured with."""
    async with session_factory() as session:
        snapshots = await session.scalar(
            select(func.count())
            .select_from(EvaluationFeature)
            .where(EvaluationFeature.evaluation_id == evaluation_id)
        )
        runs = await session.scalar(
            select(func.count()).select_from(Run).where(Run.evaluation_id == evaluation_id)
        )
        launched_at = await session.scalar(
            select(Evaluation.launched_at).where(Evaluation.id == evaluation_id)
        )
    return int(snapshots or 0), int(runs or 0), launched_at


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


async def test_launch_writes_one_snapshot_per_feature_and_one_run_per_model(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    db_session_factory: async_sessionmaker[AsyncSession],
    make_enum_feature: Callable[..., dict[str, object]],
    make_text_feature: Callable[..., dict[str, object]],
    fitting_model: str,
    second_fitting_model: str,
) -> None:
    _, config, evaluation_id = await launchable(
        make_enum_feature(),
        make_text_feature(),
        models=(fitting_model, second_fitting_model),
    )

    view = await evaluation_service.launch(EvaluationId(evaluation_id))

    snapshots, runs, launched_at = await _counts(db_session_factory, evaluation_id)
    assert snapshots == len(config.features) == 2
    assert runs == 2
    assert launched_at is not None
    assert view.draft.is_launched is True
    assert view.can_launch is False
    assert {progress.model_tag for progress in view.progress} == {
        fitting_model,
        second_fitting_model,
    }
    assert all(progress.status is RunStatus.QUEUED for progress in view.progress)


async def test_every_run_carries_its_full_provenance(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    db_session_factory: async_sessionmaker[AsyncSession],
    fitting_model: str,
    fixture_gpu: GpuInfo,
    eval_settings: Settings,
) -> None:
    """mvp-spec.md §19.8 — "every run's record alone is sufficient to
    reproduce it". Written at launch, not at completion: a run that never
    starts is still a reproducible run (§15.4)."""
    _, config, evaluation_id = await launchable(models=(fitting_model,))

    view = await evaluation_service.launch(EvaluationId(evaluation_id))

    async with db_session_factory() as session:
        run = await session.scalar(select(Run).where(Run.evaluation_id == evaluation_id))
    assert run is not None
    assert run.model_name == fitting_model
    # The digest, not just the tag: a tag is mutable at the endpoint.
    assert run.model_digest == "8fa1c3d0"
    assert run.prompt_template_version == 1
    assert run.prompt_template_fingerprint == "fp-template-1"
    assert run.temperature == 0.0
    assert run.seed == 42
    assert run.host_platform != ""
    assert run.gpu_name == fixture_gpu.name
    assert run.llm_endpoint == eval_settings.llm_base_url
    assert run.status == RunStatus.QUEUED
    assert run.started_at is None

    provenance = view.provenance
    assert provenance is not None
    assert provenance.feature_config_id == config.feature_config_id
    assert provenance.corpus_version == 1
    # The **real** fingerprints, from `evaluation_feature` — never a preview.
    assert set(provenance.feature_fingerprints) == {feature.key for feature in config.features}


async def test_the_snapshot_carries_the_whole_mapped_code_table(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    db_session_factory: async_sessionmaker[AsyncSession],
    make_enum_feature: Callable[..., dict[str, object]],
    make_text_feature: Callable[..., dict[str, object]],
) -> None:
    """mvp-spec.md §8.5: the snapshot **includes label text**, and every
    language the import carried. Only an `enum` feature gets one."""
    _, config, evaluation_id = await launchable(make_enum_feature(), make_text_feature())
    by_key = {feature.key: feature.feature_id for feature in config.features}

    await evaluation_service.launch(EvaluationId(evaluation_id))

    async with db_session_factory() as session:
        rows = (
            await session.scalars(
                select(EvaluationFeature).where(EvaluationFeature.evaluation_id == evaluation_id)
            )
        ).all()
    stored = {row.feature_id: row for row in rows}

    enum_row = stored[by_key["weather"]]
    assert enum_row.enum_codelist_json is not None
    codes = snapshot_from_json(enum_row.enum_codelist_json)
    assert [value.code for value in codes] == ["01", "02"]
    assert codes[0].label == {"de": "Klar", "fr": "Clair", "it": "Chiaro"}
    assert codes[0].attribute_key == "weather"

    # A free-text feature has no code table to snapshot.
    assert stored[by_key["injury_note"]].enum_codelist_json is None


# ---------------------------------------------------------------------------
# Refusals — each one leaves nothing behind
# ---------------------------------------------------------------------------


async def test_an_unfrozen_feature_config_is_refused_and_creates_nothing(
    evaluation_service: EvaluationService,
    seed_corpus: Callable[..., Awaitable[CorpusId]],
    seed_codelists: Callable[..., Awaitable[dict[str, CodeAttributeId]]],
    map_column: Callable[..., Awaitable[None]],
    seed_template: Callable[..., Awaitable[PromptTemplateId]],
    draft_config: Callable[..., Awaitable[FeatureConfigView]],
    db_session_factory: async_sessionmaker[AsyncSession],
    fitting_model: str,
    attribute_keys: dict[str, str],
) -> None:
    """mvp-spec.md §9: "an evaluation only ever cites an already-frozen
    config, it never freezes one itself"."""
    corpus_id = await seed_corpus()
    attributes = await seed_codelists()
    await map_column(corpus_id, attributes[attribute_keys["weather"]])
    await seed_template()
    config = await draft_config()
    draft = await evaluation_service.save_draft(
        name="Weather eval", corpus_id=corpus_id, feature_config_id=config.feature_config_id
    )
    await evaluation_service.update_draft(draft.evaluation_id, selected_models=(fitting_model,))

    with pytest.raises(FeatureValidationError) as excinfo:
        await evaluation_service.launch(draft.evaluation_id)

    assert excinfo.value.validation_errors == (
        EVAL_ERROR_CONFIG_NOT_FROZEN.format(name="Unfrozen set"),
    )
    assert await _counts(db_session_factory, draft.evaluation_id) == (0, 0, None)


async def test_a_launch_without_a_template_is_refused(
    evaluation_service: EvaluationService,
    seed_corpus: Callable[..., Awaitable[CorpusId]],
    seed_codelists: Callable[..., Awaitable[dict[str, CodeAttributeId]]],
    map_column: Callable[..., Awaitable[None]],
    frozen_config: Callable[..., Awaitable[FeatureConfigView]],
    db_session_factory: async_sessionmaker[AsyncSession],
    fitting_model: str,
    attribute_keys: dict[str, str],
) -> None:
    """§15.2: the column is nullable so a draft can exist before a template
    does; the launch transaction requires one."""
    corpus_id = await seed_corpus()
    attributes = await seed_codelists()
    await map_column(corpus_id, attributes[attribute_keys["weather"]])
    config = await frozen_config()
    draft = await evaluation_service.save_draft(
        name="Weather eval", corpus_id=corpus_id, feature_config_id=config.feature_config_id
    )
    await evaluation_service.update_draft(draft.evaluation_id, selected_models=(fitting_model,))

    with pytest.raises(FeatureValidationError) as excinfo:
        await evaluation_service.launch(draft.evaluation_id)

    assert excinfo.value.validation_errors == (EVAL_ERROR_NO_TEMPLATE,)
    assert await _counts(db_session_factory, draft.evaluation_id) == (0, 0, None)


async def test_a_launch_with_no_models_selected_is_refused(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, _, evaluation_id = await launchable(models=())

    with pytest.raises(FeatureValidationError) as excinfo:
        await evaluation_service.launch(EvaluationId(evaluation_id))

    assert excinfo.value.validation_errors == (EVAL_ERROR_NO_MODELS_SELECTED,)
    assert await _counts(db_session_factory, evaluation_id) == (0, 0, None)


async def test_an_unreachable_endpoint_blocks_launch_without_a_traceback(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    model_catalog: StaticModelCatalog,
    db_session_factory: async_sessionmaker[AsyncSession],
    eval_settings: Settings,
) -> None:
    """C3 — an unreachable endpoint **disables Launch**, and a service call
    that gets past a disabled button is a refusal, not a 502. mvp-spec.md
    §19.8 is the reason: with nothing to ask, there is no digest to pin."""
    _, _, evaluation_id = await launchable()
    model_catalog.set_status(EndpointStatus.UNREACHABLE)

    view = await evaluation_service.get(EvaluationId(evaluation_id))
    assert view.can_launch is False
    assert view.connection.reason is not None

    with pytest.raises(FeatureValidationError) as excinfo:
        await evaluation_service.launch(EvaluationId(evaluation_id))

    assert excinfo.value.validation_errors == (
        EVAL_ERROR_ENDPOINT_UNREACHABLE.format(endpoint=eval_settings.llm_base_url),
    )
    assert await _counts(db_session_factory, evaluation_id) == (0, 0, None)


async def test_a_vram_infeasible_model_is_refused_at_launch_too(
    db_session_factory: async_sessionmaker[AsyncSession],
    model_catalog: StaticModelCatalog,
    clock: FrozenClock,
    ids: SeededFactory,
    eval_settings: Settings,
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    oversized_model: str,
    fixture_gpu: GpuInfo,
) -> None:
    """The selection gate is not the only gate: a draft saved on a host with
    no GPU answer must not launch on one that knows the model will not fit."""
    _, _, evaluation_id = await launchable()
    # Saved while the VRAM was unknown — "unknown" is not "does not fit", so
    # this selection is allowed.
    unknown_host = EvaluationService(
        session_factory=db_session_factory,
        model_catalog=model_catalog,
        gpu_probe=StaticGpuProbe(),
        clock=clock,
        ids=ids,
        settings=eval_settings,
    )
    await unknown_host.update_draft(EvaluationId(evaluation_id), selected_models=(oversized_model,))

    with pytest.raises(FeatureValidationError) as excinfo:
        await evaluation_service.launch(EvaluationId(evaluation_id))

    assert excinfo.value.validation_errors == (
        EVAL_ERROR_MODEL_EXCEEDS_VRAM.format(
            tag=oversized_model,
            size_gb=42.5,
            vram_gb=fixture_gpu.total_vram_bytes / 1_000_000_000,
        ),
    )
    assert await _counts(db_session_factory, evaluation_id) == (0, 0, None)


async def test_an_enum_feature_with_no_mapping_cannot_be_launched(
    evaluation_service: EvaluationService,
    seed_corpus: Callable[..., Awaitable[CorpusId]],
    seed_codelists: Callable[..., Awaitable[dict[str, CodeAttributeId]]],
    seed_template: Callable[..., Awaitable[PromptTemplateId]],
    frozen_config: Callable[..., Awaitable[FeatureConfigView]],
    db_session_factory: async_sessionmaker[AsyncSession],
    fitting_model: str,
    enum_column: str,
) -> None:
    """mvp-spec.md §7: "A feature whose column has no mapping ... and whose
    type is `enum` **cannot be run** — hard validation error at evaluation
    setup, not a silent degradation." No mapping is seeded here at all."""
    corpus_id = await seed_corpus()
    await seed_codelists()
    await seed_template()
    config = await frozen_config()
    draft = await evaluation_service.save_draft(
        name="Weather eval", corpus_id=corpus_id, feature_config_id=config.feature_config_id
    )
    await evaluation_service.update_draft(draft.evaluation_id, selected_models=(fitting_model,))

    with pytest.raises(FeatureValidationError) as excinfo:
        await evaluation_service.launch(draft.evaluation_id)

    assert excinfo.value.validation_errors == (
        EVAL_ERROR_ENUM_NO_CODELIST.format(key="weather", column=enum_column),
    )
    assert await _counts(db_session_factory, draft.evaluation_id) == (0, 0, None)


async def test_a_prompt_language_the_code_table_has_no_labels_for_is_refused(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    db_session_factory: async_sessionmaker[AsyncSession],
    attribute_keys: dict[str, str],
    enum_column: str,
) -> None:
    """mvp-spec.md §7's known gap (`main_cause*` has no `it`): "a validation
    error at evaluation setup for a corpus/prompt-language combination that
    needs it — **not a fallback to another language**"."""
    _, _, evaluation_id = await launchable(attribute=attribute_keys["de_only"])
    await evaluation_service.update_draft(EvaluationId(evaluation_id), prompt_language="it")

    with pytest.raises(FeatureValidationError) as excinfo:
        await evaluation_service.launch(EvaluationId(evaluation_id))

    assert excinfo.value.validation_errors == (
        EVAL_ERROR_ENUM_NO_LABEL_IN_LANGUAGE.format(
            key="weather", column=enum_column, language="it"
        ),
    )
    assert await _counts(db_session_factory, evaluation_id) == (0, 0, None)


async def test_one_code_missing_one_label_does_not_block_a_launch(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The weather fixture's code `02` has no `fr` label. mvp-spec.md §7's
    gate is about an **attribute** with no labels in that language, not about
    one hole in one code — and the snapshot keeps the hole verbatim rather
    than filling it from another language."""
    _, _, evaluation_id = await launchable()
    await evaluation_service.update_draft(EvaluationId(evaluation_id), prompt_language="fr")

    await evaluation_service.launch(EvaluationId(evaluation_id))

    async with db_session_factory() as session:
        row = await session.scalar(
            select(EvaluationFeature).where(EvaluationFeature.evaluation_id == evaluation_id)
        )
    assert row is not None
    assert row.enum_codelist_json is not None
    codes = {value.code: value.label for value in snapshot_from_json(row.enum_codelist_json)}
    assert "fr" not in codes["02"]


async def test_launching_twice_is_refused(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`evaluation_feature` is written **once** and never updated (Do-NOT #2
    in spirit): a second launch must not double the snapshot or the runs."""
    _, _, evaluation_id = await launchable()
    await evaluation_service.launch(EvaluationId(evaluation_id))
    before = await _counts(db_session_factory, evaluation_id)

    with pytest.raises(EvaluationLockedError):
        await evaluation_service.launch(EvaluationId(evaluation_id))

    assert await _counts(db_session_factory, evaluation_id) == before


# ---------------------------------------------------------------------------
# `is_dev` — the size choice against the two thresholds
# ---------------------------------------------------------------------------


async def test_a_dev_sized_launch_is_marked_dev(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    db_session_factory: async_sessionmaker[AsyncSession],
    eval_settings: Settings,
) -> None:
    _, _, evaluation_id = await launchable(record_count=eval_settings.eval_record_min + 5)
    await evaluation_service.update_draft(EvaluationId(evaluation_id), size=EvaluationSize.DEV)

    view = await evaluation_service.launch(EvaluationId(evaluation_id))

    async with db_session_factory() as session:
        is_dev = await session.scalar(
            select(Evaluation.is_dev).where(Evaluation.id == evaluation_id)
        )
    assert is_dev is True
    assert view.runs is not None
    assert all(run.is_dev for run in view.runs.items)


async def test_a_full_launch_below_the_evaluation_floor_is_still_dev(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    db_session_factory: async_sessionmaker[AsyncSession],
    eval_settings: Settings,
) -> None:
    """mvp-spec.md §9 — "a run over a corpus below the evaluation floor is
    marked **dev**", whatever the size selector said."""
    _, _, evaluation_id = await launchable(record_count=eval_settings.eval_record_min - 1)

    await evaluation_service.launch(EvaluationId(evaluation_id))

    async with db_session_factory() as session:
        is_dev = await session.scalar(
            select(Evaluation.is_dev).where(Evaluation.id == evaluation_id)
        )
    assert is_dev is True


async def test_a_full_launch_at_or_above_the_floor_is_not_dev(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    db_session_factory: async_sessionmaker[AsyncSession],
    eval_settings: Settings,
) -> None:
    _, _, evaluation_id = await launchable(record_count=eval_settings.eval_record_min)

    view = await evaluation_service.launch(EvaluationId(evaluation_id))

    async with db_session_factory() as session:
        is_dev = await session.scalar(
            select(Evaluation.is_dev).where(Evaluation.id == evaluation_id)
        )
    assert is_dev is False
    assert view.corpus_record_count == eval_settings.eval_record_min
    # The design's "Dev · N records" reads its number from config.
    assert view.dev_record_max == eval_settings.dev_record_max
