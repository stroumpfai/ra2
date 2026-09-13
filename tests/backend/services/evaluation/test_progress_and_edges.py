"""The Evaluation screen's progress column, and the edges the other modules
do not reach.

**Progress is derived from committed `extraction` rows, never counted**
(§15 F6). There is no `records_done` column to read, so the numbers below are
seeded as rows and asserted through the read model — which is the only way to
tell a derived count from a cached one.
"""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.fake_llm import StaticModelCatalog

from ra2.domain.extraction import RunStatus
from ra2.domain.feature import Grain, Kind, MatchingRule, MatchingRuleKind, ValueType
from ra2.domain.ids import (
    CodeAttributeId,
    CorpusId,
    EvaluationId,
    ExtractionId,
    FeatureConfigId,
    FeatureId,
    PromptTemplateId,
    RecordId,
    RunId,
)
from ra2.domain.llm import EndpointStatus, ModelInfo
from ra2.infra.clock import FrozenClock
from ra2.persistence.models import Extraction, Feature, FeatureConfig, Record, Run
from ra2.services.errors import FeatureValidationError, NotFoundError
from ra2.services.evaluation_service import (
    EVAL_ERROR_ENUM_NO_CODELIST,
    EVAL_ERROR_MODEL_NOT_AVAILABLE,
    EvaluationService,
    snapshot_from_json,
    snapshot_to_json,
)
from ra2.services.feature_service import matching_rule_json
from ra2.services.readmodels import FeatureConfigView

pytestmark = pytest.mark.backend


async def _seed_extractions(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    corpus_id: str,
    *,
    count: int,
    latencies: list[int],
    parse_failures: int = 0,
    retries: int = 0,
) -> None:
    async with session_factory() as session:
        record_ids = (
            await session.scalars(
                select(Record.id).where(Record.corpus_id == corpus_id).order_by(Record.id)
            )
        ).all()
        for n in range(count):
            session.add(
                Extraction(
                    id=ExtractionId(f"{run_id}-x{n:03d}"),
                    run_id=RunId(run_id),
                    record_id=RecordId(record_ids[n]),
                    raw_output_text="{}",
                    parse_ok=n >= parse_failures,
                    parse_error=None if n >= parse_failures else "not json",
                    latency_ms=latencies[n % len(latencies)],
                    prompt_tokens=100,
                    completion_tokens=10,
                    retry_count=1 if n < retries else 0,
                )
            )
        await session.commit()


async def test_progress_is_derived_from_committed_extraction_rows(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    db_session_factory: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    corpus_id, _, evaluation_id = await launchable(record_count=10)
    view = await evaluation_service.launch(EvaluationId(evaluation_id))
    run_id = view.progress[0].run_id

    async with db_session_factory() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        run.status = RunStatus.RUNNING
        run.started_at = clock.now()
        await session.commit()
    await _seed_extractions(
        db_session_factory,
        run_id,
        corpus_id,
        count=4,
        latencies=[100, 300, 200, 400],
        parse_failures=1,
        retries=2,
    )
    # Ten seconds of wall clock, four records done out of ten.
    clock.advance(seconds=10)

    card = (await evaluation_service.get(EvaluationId(evaluation_id))).progress[0]

    assert card.done == 4
    assert card.total == 10
    assert card.percent == 40.0
    assert card.parse_failures == 1
    assert card.retries == 2
    assert card.median_latency_ms == 250
    assert card.prompt_tokens == 400
    assert card.elapsed_ms == 10_000
    # Six records left at 2.5 s each.
    assert card.eta_ms == 15_000
    assert card.has_metrics is True


async def test_a_finished_run_reports_its_duration_not_the_wall_clock(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    db_session_factory: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    """Once a run is over, its elapsed time stops moving — a `done` card that
    kept counting would be reporting the reader's idle time."""
    corpus_id, _, evaluation_id = await launchable(record_count=10)
    view = await evaluation_service.launch(EvaluationId(evaluation_id))
    run_id = view.progress[0].run_id
    started = clock.now()
    clock.advance(seconds=5)
    async with db_session_factory() as session:
        run = await session.get(Run, run_id)
        assert run is not None
        run.status = RunStatus.DONE
        run.started_at = started
        run.finished_at = clock.now()
        await session.commit()
    await _seed_extractions(db_session_factory, run_id, corpus_id, count=10, latencies=[50])
    clock.advance(seconds=600)

    card = (await evaluation_service.get(EvaluationId(evaluation_id))).progress[0]

    assert card.elapsed_ms == 5_000
    # Nothing left to do, so no ETA to invent.
    assert card.eta_ms is None
    assert card.done == card.total == 10
    assert card.percent == 100.0


async def test_a_queued_run_has_no_elapsed_time_and_no_eta(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
) -> None:
    """An ETA from zero observations is a guess dressed as a number."""
    _, _, evaluation_id = await launchable(record_count=10)

    view = await evaluation_service.launch(EvaluationId(evaluation_id))

    card = view.progress[0]
    assert card.elapsed_ms is None
    assert card.eta_ms is None
    assert card.median_latency_ms is None
    assert card.prompt_tokens == 0


async def test_the_view_labels_the_pinned_inputs(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
) -> None:
    """The toolbar's "only the model varies" line reads from the pinned rows,
    never from whatever the view last had in hand."""
    _, config, evaluation_id = await launchable()

    view = await evaluation_service.get(EvaluationId(evaluation_id))

    assert view.feature_config_label == f"{config.name} · v{config.version}"
    assert view.corpus_label == "Zurich 2024 · v1"


async def test_a_model_the_endpoint_no_longer_offers_is_refused_at_launch(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    model_catalog: StaticModelCatalog,
    fitting_model: str,
    second_fitting_model: str,
) -> None:
    """mvp-spec.md §19.8 wants the **digest**, and a tag the endpoint has
    dropped has none — so the launch refuses rather than pinning a blank."""
    _, _, evaluation_id = await launchable(models=(fitting_model,))
    # Still reachable — only the catalogue changed under the draft.
    model_catalog.set_status(
        EndpointStatus.REACHABLE,
        models=[ModelInfo(tag=second_fitting_model, digest="c17b904e", size_bytes=1)],
    )

    with pytest.raises(FeatureValidationError) as excinfo:
        await evaluation_service.launch(EvaluationId(evaluation_id))

    assert excinfo.value.validation_errors == (
        EVAL_ERROR_MODEL_NOT_AVAILABLE.format(tag=fitting_model),
    )


async def test_an_enum_feature_naming_no_column_at_all_is_refused_at_launch(
    evaluation_service: EvaluationService,
    seed_corpus: Callable[..., Awaitable[CorpusId]],
    seed_codelists: Callable[..., Awaitable[dict[str, CodeAttributeId]]],
    seed_template: Callable[..., Awaitable[PromptTemplateId]],
    db_session_factory: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
    fitting_model: str,
) -> None:
    """mvp-spec.md §7 one step earlier: there is not even a column to look a
    code table up by.

    `feature_service.freeze` blocks this already
    (`FEATURE_ERROR_ENUM_HAS_NO_COLUMN`), which is the design's earlier
    safety net — so the row is seeded **frozen, directly**, to prove the
    launch is the second lock and not a pass-through. A launch that
    snapshotted `None` here would silently ask the model for a code out of a
    code table nobody named.
    """
    corpus_id = await seed_corpus()
    await seed_codelists()
    await seed_template()
    async with db_session_factory() as session:
        session.add(
            FeatureConfig(
                id=FeatureConfigId("fc-no-column"),
                name="No column",
                created_at=clock.now(),
                frozen_at=clock.now(),
            )
        )
        await session.flush()
        session.add(
            Feature(
                id=FeatureId("f-no-column"),
                feature_config_id=FeatureConfigId("fc-no-column"),
                ordinal=0,
                key="weather",
                kind=Kind.LABELLED,
                description="The weather at the time of the accident.",
                grain=Grain.ACCIDENT,
                source_column=None,
                value_type=ValueType.ENUM,
                matching_rule=matching_rule_json(MatchingRule(kind=MatchingRuleKind.EXACT)),
            )
        )
        await session.commit()

    draft = await evaluation_service.save_draft(
        name="No column eval",
        corpus_id=corpus_id,
        feature_config_id=FeatureConfigId("fc-no-column"),
    )
    await evaluation_service.update_draft(draft.evaluation_id, selected_models=(fitting_model,))

    with pytest.raises(FeatureValidationError) as excinfo:
        await evaluation_service.launch(draft.evaluation_id)

    assert excinfo.value.validation_errors == (
        EVAL_ERROR_ENUM_NO_CODELIST.format(key="weather", column="(none)"),
    )


async def test_update_draft_reports_an_unknown_template(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
) -> None:
    _, _, evaluation_id = await launchable()

    with pytest.raises(NotFoundError):
        await evaluation_service.update_draft(
            EvaluationId(evaluation_id), prompt_template_id=PromptTemplateId("nope")
        )


async def test_update_draft_can_repoint_the_corpus_and_the_config(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    seed_corpus: Callable[..., Awaitable[CorpusId]],
    frozen_config: Callable[..., Awaitable[FeatureConfigView]],
) -> None:
    """Steps 1 and 2 are as editable as the rest while the draft is a draft."""
    _, _, evaluation_id = await launchable()
    other_corpus = await seed_corpus(corpus_id="corpus-2", name="Bern 2024")
    other_config = await frozen_config(name="Road surface")

    updated = await evaluation_service.update_draft(
        EvaluationId(evaluation_id),
        corpus_id=other_corpus,
        feature_config_id=other_config.feature_config_id,
    )

    assert updated.corpus_id == other_corpus
    assert updated.feature_config_id == other_config.feature_config_id


def test_the_snapshot_codec_round_trips() -> None:
    """The one encoding of `evaluation_feature.enum_codelist_json`: I1 and I3
    read it back with `snapshot_from_json`, so the pair must be exact — and
    the bytes must be stable, because they are hashed."""
    values = snapshot_from_json(
        '[{"attribute_key":"weather","code":"02","label":{"de":"Regen"}},'
        '{"attribute_key":"weather","code":"01","label":{"de":"Klar","fr":"Clair"}}]'
    )

    encoded = snapshot_to_json(values)

    # Re-encoding orders by code and sorts every object's keys, so two writers
    # of one code table emit one byte sequence.
    assert encoded == (
        '[{"attribute_key":"weather","code":"01","label":{"de":"Klar","fr":"Clair"}},'
        '{"attribute_key":"weather","code":"02","label":{"de":"Regen"}}]'
    )
    assert snapshot_from_json(encoded) == tuple(sorted(values, key=lambda v: v.code))


def test_the_snapshot_codec_keeps_label_text_as_text() -> None:
    """`ensure_ascii=False`, matching `domain.fingerprint`: a label hashes as
    text, not as `\\uXXXX` escapes (mvp-spec.md §8.5)."""
    values = snapshot_from_json('[{"attribute_key":"a","code":"01","label":{"de":"Straße"}}]')

    assert "Straße" in snapshot_to_json(values)


def test_the_enum_no_codelist_message_names_the_column(enum_column: str) -> None:
    """The message templates are the stable identifiers (CLAUDE.md's
    "findings, not prose" applied to a `FeatureValidationError`'s strings)."""
    assert enum_column in EVAL_ERROR_ENUM_NO_CODELIST.format(key="weather", column=enum_column)
