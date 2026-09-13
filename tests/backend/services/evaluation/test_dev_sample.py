"""The dev sample is deterministic (§15 F9, sw-design.md §15.2).

> "A re-run is a check, not a new sample" is false the moment the record
> selection is random: the seed fixes what the model does with what it sees,
> and determinism has to cover what it is *shown* too.

The corpus fixture inserts its records **last id first**, so "the first N
records by id" is a claim that insertion order cannot satisfy by accident.
"""

from collections.abc import Awaitable, Callable

import pytest

from ra2.domain.extraction import EvaluationSize
from ra2.domain.ids import CorpusId, EvaluationId
from ra2.infra.config import Settings
from ra2.services.evaluation_service import EvaluationService
from ra2.services.readmodels import FeatureConfigView

pytestmark = pytest.mark.backend


async def test_a_dev_sized_launch_takes_the_first_n_records_by_id(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    eval_settings: Settings,
) -> None:
    """The cap comes from `RA2_DEV_RECORD_MAX`, never from a literal — the
    design's "Dev · 40 records" reads its number from config."""
    corpus_id, _, evaluation_id = await launchable(record_count=10)
    await evaluation_service.update_draft(EvaluationId(evaluation_id), size=EvaluationSize.DEV)

    scope = await evaluation_service.record_scope(EvaluationId(evaluation_id))

    assert len(scope) == eval_settings.dev_record_max
    assert list(scope) == [f"{corpus_id}-rec-{n:03d}" for n in range(eval_settings.dev_record_max)]
    assert list(scope) == sorted(scope)


async def test_the_dev_sample_is_the_same_ids_twice(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
) -> None:
    """Asked twice, answered identically — the property a re-run depends on."""
    _, _, evaluation_id = await launchable(record_count=10)
    await evaluation_service.update_draft(EvaluationId(evaluation_id), size=EvaluationSize.DEV)

    first = await evaluation_service.record_scope(EvaluationId(evaluation_id))
    second = await evaluation_service.record_scope(EvaluationId(evaluation_id))

    assert first == second


async def test_the_dev_sample_survives_the_launch_commit(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
) -> None:
    """The scope is derived from pinned inputs, so launching cannot move it —
    which is what lets `run_service` resume against the same records after a
    restart."""
    _, _, evaluation_id = await launchable(record_count=10)
    await evaluation_service.update_draft(EvaluationId(evaluation_id), size=EvaluationSize.DEV)
    before = await evaluation_service.record_scope(EvaluationId(evaluation_id))

    await evaluation_service.launch(EvaluationId(evaluation_id))

    assert await evaluation_service.record_scope(EvaluationId(evaluation_id)) == before


async def test_a_full_launch_scopes_the_whole_corpus(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
) -> None:
    _, _, evaluation_id = await launchable(record_count=10)

    scope = await evaluation_service.record_scope(EvaluationId(evaluation_id))

    assert len(scope) == 10
    assert list(scope) == sorted(scope)


async def test_the_progress_total_follows_the_scope_not_the_corpus(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    eval_settings: Settings,
) -> None:
    """A dev run's progress bar counts against the sample it will actually
    visit; showing the whole corpus as the denominator would make a finished
    smoke test look stalled."""
    _, _, evaluation_id = await launchable(record_count=10)
    await evaluation_service.update_draft(EvaluationId(evaluation_id), size=EvaluationSize.DEV)

    view = await evaluation_service.launch(EvaluationId(evaluation_id))

    assert view.corpus_record_count == 10
    assert [card.total for card in view.progress] == [eval_settings.dev_record_max]
    assert [card.done for card in view.progress] == [0]
    # A `queued` card has no metrics line — there is nothing honest to put
    # in it yet.
    assert all(card.has_metrics is False for card in view.progress)
    assert [card.percent for card in view.progress] == [0.0]
