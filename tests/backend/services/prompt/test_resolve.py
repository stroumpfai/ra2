"""`resolve()` — the `PromptResolver` seam I3's worker calls (sw-design.md
§15.1, §15.3).

Exit criterion: resolving against a dev-sized evaluation and against a full
evaluation, for the same record and the same underlying feature set, produces
the **same text**. Also covers: the caller's session is used directly and
`resolve()` never commits (the worker owns the transaction boundary).
"""

from collections.abc import Awaitable, Callable

import pytest
from tests.fixtures.factories import seed_corpus

from ra2.domain.ids import CorpusId, EvaluationId, FeatureConfigId, PromptTemplateId, RecordId
from ra2.persistence.models import Evaluation
from ra2.persistence.repositories.prompt_repo import PromptRepository
from ra2.services.errors import NotFoundError

pytestmark = pytest.mark.backend

TEMPLATE_SOURCE = "Language: {{language}}\nNarrative: {{narrative}}\nFeatures:\n{{feature_block}}"


async def _seed_common(
    seed_template: Callable[..., Awaitable[PromptTemplateId]],
    seed_minimal_feature_config: Callable[..., Awaitable[FeatureConfigId]],
    seed_record: Callable[..., Awaitable[RecordId]],
    *,
    record_id: str = "rec-1",
) -> tuple[PromptTemplateId, FeatureConfigId, RecordId]:
    template_id = await seed_template("pt-1", source=TEMPLATE_SOURCE)
    config_id = await seed_minimal_feature_config("fc-1", source_column="WitterungAusw")
    rec_id = await seed_record(
        record_id,
        corpus_id="corpus-1",
        unfall_uid="uid-0001",
        text_raw="Es regnete stark.",
    )
    return template_id, config_id, rec_id


async def test_resolve_expands_the_pinned_template_against_the_snapshot(
    prompt_service,
    db_session_factory,
    seed_template,
    seed_minimal_feature_config,
    seed_record,
    seed_evaluation_with_snapshot,
):
    template_id, config_id, record_id = await _seed_common(
        seed_template, seed_minimal_feature_config, seed_record
    )
    evaluation_id = await seed_evaluation_with_snapshot(
        "eval-1",
        corpus_id="corpus-1",
        feature_config_id=config_id,
        prompt_template_id=template_id,
        weather_feature_id="fc-1-weather",
        injured_feature_id="fc-1-injured",
        notes_feature_id="fc-1-notes",
        prompt_language="fr",
    )

    async with db_session_factory() as session:
        resolved = await prompt_service.resolve(session, evaluation_id, record_id)

    assert "Es regnete stark." in resolved.text
    assert "Language: fr" in resolved.text
    # The evaluation_feature snapshot's labels, in the evaluation's own
    # pinned language — not whatever `preview()`'s caller happens to pass.
    assert "01 — Clair" in resolved.text
    assert "02 — Pluie" in resolved.text
    assert "notes: Anything else worth flagging." in resolved.text
    assert resolved.token_estimate > 0


async def test_resolve_produces_the_same_text_for_a_dev_and_a_full_evaluation(
    prompt_service,
    db_session_factory,
    seed_template,
    seed_minimal_feature_config,
    seed_record,
    seed_evaluation_with_snapshot,
):
    """Two separate evaluations, same template/feature-set/record — one
    `is_dev=True`, one not. `resolve()` must not read `is_dev` at all, so the
    two must render byte-identical text for the same record."""
    template_id, config_id, record_id = await _seed_common(
        seed_template, seed_minimal_feature_config, seed_record
    )
    dev_evaluation_id = await seed_evaluation_with_snapshot(
        "eval-dev",
        corpus_id="corpus-1",
        feature_config_id=config_id,
        prompt_template_id=template_id,
        weather_feature_id="fc-1-weather",
        injured_feature_id="fc-1-injured",
        notes_feature_id="fc-1-notes",
        is_dev=True,
    )
    full_evaluation_id = await seed_evaluation_with_snapshot(
        "eval-full",
        corpus_id="corpus-1",
        feature_config_id=config_id,
        prompt_template_id=template_id,
        weather_feature_id="fc-1-weather",
        injured_feature_id="fc-1-injured",
        notes_feature_id="fc-1-notes",
        is_dev=False,
    )

    async with db_session_factory() as session:
        dev_resolved = await prompt_service.resolve(session, dev_evaluation_id, record_id)
    async with db_session_factory() as session:
        full_resolved = await prompt_service.resolve(session, full_evaluation_id, record_id)

    assert dev_resolved.text == full_resolved.text
    assert dev_resolved.token_estimate == full_resolved.token_estimate
    assert dev_resolved.slots_used == full_resolved.slots_used


async def test_resolve_uses_the_callers_session_and_never_commits(
    prompt_service,
    db_session_factory,
    seed_template,
    seed_minimal_feature_config,
    seed_record,
    seed_evaluation_with_snapshot,
):
    """`resolve()` only reads. Rolling back the caller's session afterwards
    must leave nothing behind — proof it never opened or committed a
    transaction of its own (sw-design.md §15.3: the worker owns the
    boundary)."""
    template_id, config_id, record_id = await _seed_common(
        seed_template, seed_minimal_feature_config, seed_record
    )
    evaluation_id = await seed_evaluation_with_snapshot(
        "eval-1",
        corpus_id="corpus-1",
        feature_config_id=config_id,
        prompt_template_id=template_id,
        weather_feature_id="fc-1-weather",
        injured_feature_id="fc-1-injured",
        notes_feature_id="fc-1-notes",
    )

    async with db_session_factory() as session:
        resolved = await prompt_service.resolve(session, evaluation_id, record_id)
        assert resolved.text  # the call itself worked inside this open session
        await session.rollback()

    # A fresh session still sees exactly what was seeded — resolve() added no
    # row and left no pending write for the rollback to have been hiding.
    async with db_session_factory() as session:
        repo = PromptRepository(session)
        assert (await repo.get(template_id)) is not None
        assert len(await repo.list_all()) == 1


async def test_resolve_raises_not_found_for_an_unknown_evaluation(
    prompt_service, db_session_factory
):
    async with db_session_factory() as session:
        with pytest.raises(NotFoundError):
            await prompt_service.resolve(session, EvaluationId("does-not-exist"), RecordId("rec-1"))


async def test_resolve_raises_not_found_for_an_unknown_record(
    prompt_service,
    db_session_factory,
    seed_template,
    seed_minimal_feature_config,
    seed_record,
    seed_evaluation_with_snapshot,
):
    template_id, config_id, _record_id = await _seed_common(
        seed_template, seed_minimal_feature_config, seed_record
    )
    evaluation_id = await seed_evaluation_with_snapshot(
        "eval-1",
        corpus_id="corpus-1",
        feature_config_id=config_id,
        prompt_template_id=template_id,
        weather_feature_id="fc-1-weather",
        injured_feature_id="fc-1-injured",
        notes_feature_id="fc-1-notes",
    )

    async with db_session_factory() as session:
        with pytest.raises(NotFoundError):
            await prompt_service.resolve(session, evaluation_id, RecordId("does-not-exist"))


async def test_resolve_raises_not_found_when_the_evaluation_has_no_template_pinned(
    prompt_service, db_session_factory, seed_minimal_feature_config, seed_record
):
    """A draft evaluation (`prompt_template_id IS NULL`, sw-design.md §15.2)
    should never reach the worker, but `resolve()` guards it anyway rather
    than raising an unrelated `AttributeError`."""
    config_id = await seed_minimal_feature_config("fc-1")
    record_id = await seed_record("rec-1", corpus_id="corpus-1")

    async with db_session_factory() as session:
        await seed_corpus(session, "corpus-draft")
        session.add(
            Evaluation(
                id=EvaluationId("eval-draft"),
                name="draft",
                corpus_id=CorpusId("corpus-draft"),
                feature_config_id=FeatureConfigId(config_id),
            )
        )
        await session.commit()

    async with db_session_factory() as session:
        with pytest.raises(NotFoundError):
            await prompt_service.resolve(session, EvaluationId("eval-draft"), record_id)
