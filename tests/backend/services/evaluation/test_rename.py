"""Naming an evaluation: `EvaluationService.rename` (`SD58`).

A new evaluation is named after its feature set, which tells evaluations
apart only until a set has several. The name is usually worth choosing once
the results are in, and by then the evaluation is launched. So `rename` is the
one edit the launch does not lock: the name pins nothing a run depends on.

Every other edit path still raises after the launch
(`test_evaluation_drafts.test_update_draft_is_refused_after_launch`), and
`update_draft(name=...)` among them.
"""

import dataclasses
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import CorpusId, EvaluationId
from ra2.persistence.models import Evaluation, Run
from ra2.services.errors import EvaluationLockedError, FeatureValidationError, NotFoundError
from ra2.services.evaluation_service import (
    EVAL_ERROR_NAME_BLANK,
    EVAL_ERROR_NAME_TOO_LONG,
    EvaluationService,
)
from ra2.services.readmodels import FeatureConfigView

pytestmark = pytest.mark.backend

Launchable = Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]]


async def _stored_name(factory: async_sessionmaker[AsyncSession], evaluation_id: str) -> str | None:
    async with factory() as session:
        name: str | None = await session.scalar(
            select(Evaluation.name).where(Evaluation.id == evaluation_id)
        )
        return name


async def _runs(
    factory: async_sessionmaker[AsyncSession], evaluation_id: str
) -> list[tuple[object, ...]]:
    """Every pinned column of every run, so a rename can be shown to touch
    none of them."""
    async with factory() as session:
        rows = (await session.scalars(select(Run).where(Run.evaluation_id == evaluation_id))).all()
        return sorted(
            (
                run.id,
                run.model_name,
                run.model_digest,
                run.prompt_template_id,
                run.prompt_template_fingerprint,
                run.temperature,
                run.seed,
                run.status,
            )
            for run in rows
        )


async def test_a_draft_is_renamed(
    evaluation_service: EvaluationService, launchable: Launchable
) -> None:
    _, _, evaluation_id = await launchable()

    renamed = await evaluation_service.rename(EvaluationId(evaluation_id), name="Baseline")

    assert renamed.name == "Baseline"
    assert not renamed.is_launched
    # Every other step is left as it was: a rename is not a re-save.
    assert renamed.selected_models != ()


async def test_a_launched_evaluation_is_renamed_and_nothing_it_pinned_moves(
    evaluation_service: EvaluationService,
    launchable: Launchable,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The point of `SD58`: the lock that refuses every other edit does not
    reach the name, and the rename reaches nothing the lock protects."""
    _, _, evaluation_id = await launchable()
    await evaluation_service.launch(EvaluationId(evaluation_id))
    before = (await evaluation_service.get(EvaluationId(evaluation_id), probe=False)).draft
    runs_before = await _runs(db_session_factory, evaluation_id)
    assert runs_before, "the launch queues one run per selected model"

    renamed = await evaluation_service.rename(
        EvaluationId(evaluation_id), name="Prompt v5 · after the fix"
    )

    assert renamed.name == "Prompt v5 · after the fix"
    assert renamed.launched_at == before.launched_at
    # The whole draft view, less the name, is what it was.
    assert dataclasses.replace(renamed, name=before.name) == before
    assert await _runs(db_session_factory, evaluation_id) == runs_before
    # And the lock still holds for every other path, `update_draft`'s name too.
    with pytest.raises(EvaluationLockedError):
        await evaluation_service.update_draft(EvaluationId(evaluation_id), name="Other")
    assert await _stored_name(db_session_factory, evaluation_id) == "Prompt v5 · after the fix"


async def test_the_name_is_stored_stripped(
    evaluation_service: EvaluationService, launchable: Launchable
) -> None:
    _, _, evaluation_id = await launchable()

    renamed = await evaluation_service.rename(EvaluationId(evaluation_id), name="  Baseline \n")

    assert renamed.name == "Baseline"


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
async def test_a_blank_name_is_refused_and_changes_nothing(
    evaluation_service: EvaluationService,
    launchable: Launchable,
    db_session_factory: async_sessionmaker[AsyncSession],
    blank: str,
) -> None:
    """A blank name leaves a picker row with nothing to click."""
    _, _, evaluation_id = await launchable()

    with pytest.raises(FeatureValidationError) as excinfo:
        await evaluation_service.rename(EvaluationId(evaluation_id), name=blank)

    assert excinfo.value.validation_errors == (EVAL_ERROR_NAME_BLANK,)
    assert await _stored_name(db_session_factory, evaluation_id) == "Weather eval"


async def test_a_name_longer_than_the_column_is_refused(
    evaluation_service: EvaluationService,
    launchable: Launchable,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`String(200)`: SQLite would store more, and the next database might
    not. Exactly 200 is accepted, so the bound is the column's, not one off."""
    _, _, evaluation_id = await launchable()

    accepted = await evaluation_service.rename(EvaluationId(evaluation_id), name="x" * 200)
    assert accepted.name == "x" * 200

    with pytest.raises(FeatureValidationError) as excinfo:
        await evaluation_service.rename(EvaluationId(evaluation_id), name="y" * 201)

    assert excinfo.value.validation_errors == (
        EVAL_ERROR_NAME_TOO_LONG.format(length=201, limit=200),
    )
    assert await _stored_name(db_session_factory, evaluation_id) == "x" * 200


async def test_update_draft_and_save_draft_follow_the_same_rule(
    evaluation_service: EvaluationService,
    launchable: Launchable,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Every path that writes the name checks it the same way, so a draft
    cannot hold a name a rename would refuse."""
    corpus_id, config, evaluation_id = await launchable()

    with pytest.raises(FeatureValidationError) as excinfo:
        await evaluation_service.update_draft(EvaluationId(evaluation_id), name="  ")
    assert excinfo.value.validation_errors == (EVAL_ERROR_NAME_BLANK,)
    assert await _stored_name(db_session_factory, evaluation_id) == "Weather eval"

    with pytest.raises(FeatureValidationError):
        await evaluation_service.save_draft(
            name="", corpus_id=corpus_id, feature_config_id=config.feature_config_id
        )

    updated = await evaluation_service.update_draft(EvaluationId(evaluation_id), name=" Spaced ")
    assert updated.name == "Spaced"


async def test_rename_reports_an_unknown_evaluation(
    evaluation_service: EvaluationService,
) -> None:
    with pytest.raises(NotFoundError):
        await evaluation_service.rename(EvaluationId("nope"), name="x")
