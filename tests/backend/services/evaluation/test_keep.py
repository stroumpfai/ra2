"""Marking an evaluation to keep: `EvaluationService.set_kept` (`SD61`).

The mark is what G3 reads (`LifecycleService`, §18.2): a kept evaluation and
every run of it are refused by discard until released. Like the name, it pins
nothing, so the launch lock does not reach it; a baseline is only worth
keeping once its results are in.
"""

import dataclasses
from collections.abc import Awaitable, Callable

import pytest

from ra2.domain.ids import CorpusId, EvaluationId
from ra2.infra.clock import FrozenClock
from ra2.services.errors import EvaluationLockedError, NotFoundError
from ra2.services.evaluation_service import EvaluationService
from ra2.services.readmodels import FeatureConfigView

pytestmark = pytest.mark.backend

Launchable = Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]]


async def test_a_draft_is_kept_and_released(
    evaluation_service: EvaluationService, launchable: Launchable, clock: FrozenClock
) -> None:
    _, _, evaluation_id = await launchable()
    key = EvaluationId(evaluation_id)

    kept = await evaluation_service.set_kept(key, kept=True)
    assert kept.is_kept
    assert kept.kept_at == clock.now()

    released = await evaluation_service.set_kept(key, kept=False)
    assert not released.is_kept
    assert released.kept_at is None
    assert not (await evaluation_service.get(key, probe=False)).draft.is_kept


async def test_a_launched_evaluation_is_kept_and_nothing_it_pinned_moves(
    evaluation_service: EvaluationService, launchable: Launchable
) -> None:
    """The point of the exemption: the lock that refuses every other edit does
    not reach the mark, and the mark reaches nothing the lock protects."""
    _, _, evaluation_id = await launchable()
    key = EvaluationId(evaluation_id)
    await evaluation_service.launch(key)
    before = (await evaluation_service.get(key, probe=False)).draft

    kept = await evaluation_service.set_kept(key, kept=True)

    assert kept.is_kept
    assert dataclasses.replace(kept, kept_at=None) == before
    with pytest.raises(EvaluationLockedError):
        await evaluation_service.update_draft(key, seed=7)


async def test_keeping_a_kept_evaluation_keeps_the_first_time(
    evaluation_service: EvaluationService, launchable: Launchable, clock: FrozenClock
) -> None:
    """When the decision was made is what `kept_at` records; a second press
    is not a second decision."""
    _, _, evaluation_id = await launchable()
    key = EvaluationId(evaluation_id)
    first = (await evaluation_service.set_kept(key, kept=True)).kept_at

    clock.advance(seconds=3600)
    again = await evaluation_service.set_kept(key, kept=True)

    assert again.kept_at == first
    assert (await evaluation_service.get(key, probe=False)).draft.kept_at == first


async def test_releasing_an_evaluation_that_is_not_kept_changes_nothing(
    evaluation_service: EvaluationService, launchable: Launchable
) -> None:
    _, _, evaluation_id = await launchable()
    key = EvaluationId(evaluation_id)
    before = (await evaluation_service.get(key, probe=False)).draft

    released = await evaluation_service.set_kept(key, kept=False)

    assert released == before


async def test_a_new_evaluation_is_not_kept(
    evaluation_service: EvaluationService, launchable: Launchable
) -> None:
    _, _, evaluation_id = await launchable()

    draft = (await evaluation_service.get(EvaluationId(evaluation_id), probe=False)).draft

    assert draft.kept_at is None


async def test_an_unknown_evaluation_is_not_found(evaluation_service: EvaluationService) -> None:
    with pytest.raises(NotFoundError):
        await evaluation_service.set_kept(EvaluationId("no-such-evaluation"), kept=True)
