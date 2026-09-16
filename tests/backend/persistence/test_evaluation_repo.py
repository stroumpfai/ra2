"""Round-trip tests for `EvaluationRepository` against a real temp-file
SQLite database (mvp-spec.md §9, sw-design.md §15.2).

An evaluation is mutable while `launched_at IS NULL` — `get()` returns the
ORM row and a draft's columns are edited on it directly, the same convention
`FeatureRepository.get_config()` follows. `launch()` is the one method
covered here that writes more than one table in a single flush: the
`evaluation_feature` snapshot and the runs it creates must all land together,
because that atomicity is what makes "an evaluation pins; a launch snapshots"
(sw-design.md §15.2) a property of the database and not just of the caller's
discipline.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import (
    CorpusId,
    EvaluationId,
    FeatureConfigId,
    FeatureId,
    PromptTemplateId,
    RunId,
)
from ra2.persistence.models import (
    Corpus,
    Evaluation,
    EvaluationFeature,
    Feature,
    FeatureConfig,
    PromptTemplate,
    Run,
)
from ra2.persistence.repositories.evaluation_repo import EvaluationRepository

pytestmark = pytest.mark.backend

NOW = datetime(2026, 9, 13, 9, 0, tzinfo=UTC)


def _make_corpus(corpus_id: str) -> Corpus:
    return Corpus(
        id=CorpusId(corpus_id),
        name="Test corpus",
        imported_at=NOW,
        source_file_manifest_json="[]",
        import_report_json="[]",
        record_count=10,
    )


def _make_feature_config(config_id: str, *, frozen: bool = True) -> FeatureConfig:
    return FeatureConfig(
        id=FeatureConfigId(config_id),
        name="Weather & conditions",
        created_at=NOW,
        frozen_at=NOW if frozen else None,
    )


def _make_evaluation(
    evaluation_id: str, *, corpus_id: str, feature_config_id: str, name: str = "Weather eval"
) -> Evaluation:
    return Evaluation(
        id=EvaluationId(evaluation_id),
        name=name,
        corpus_id=corpus_id,
        feature_config_id=feature_config_id,
        created_at=NOW,
    )


async def _seed_corpus_and_config(session: AsyncSession, *, corpus_id: str, config_id: str) -> None:
    session.add(_make_corpus(corpus_id))
    session.add(_make_feature_config(config_id))
    await session.flush()


async def test_add_draft_and_get_round_trips(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_corpus_and_config(session, corpus_id="corpus-1", config_id="fc-1")
        repo = EvaluationRepository(session)
        await repo.add_draft(
            _make_evaluation("eval-1", corpus_id="corpus-1", feature_config_id="fc-1")
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = EvaluationRepository(session)
        fetched = await repo.get(EvaluationId("eval-1"))

    assert fetched is not None
    assert fetched.name == "Weather eval"
    assert fetched.launched_at is None
    # The design's defaults (sw-design.md §15.2).
    assert fetched.prompt_language == "de"
    assert fetched.temperature == 0.0
    assert fetched.seed == 42
    assert fetched.features == []
    assert fetched.runs == []


async def test_get_returns_none_for_an_unknown_id(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = EvaluationRepository(session)
        assert await repo.get(EvaluationId("does-not-exist")) is None


async def test_draft_columns_are_edited_in_place_not_appended(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A draft is mutable — unlike `corpus` or `extraction`, editing it is an
    `UPDATE` on the existing row, never a new one."""
    async with db_session_factory() as session:
        await _seed_corpus_and_config(session, corpus_id="corpus-1", config_id="fc-1")
        repo = EvaluationRepository(session)
        await repo.add_draft(
            _make_evaluation("eval-1", corpus_id="corpus-1", feature_config_id="fc-1")
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = EvaluationRepository(session)
        evaluation = await repo.get(EvaluationId("eval-1"))
        assert evaluation is not None
        evaluation.temperature = 0.7
        evaluation.seed = 7
        await session.flush()
        await session.commit()

    async with db_session_factory() as session:
        repo = EvaluationRepository(session)
        fetched = await repo.get(EvaluationId("eval-1"))
        assert fetched is not None
        assert fetched.temperature == 0.7
        assert fetched.seed == 7
        # Still exactly one row: an edit is an update, not an append.
        assert len(await repo.list_all()) == 1


async def test_list_all_orders_newest_first(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_corpus_and_config(session, corpus_id="corpus-1", config_id="fc-1")
        repo = EvaluationRepository(session)
        first = _make_evaluation("eval-1", corpus_id="corpus-1", feature_config_id="fc-1")
        first.created_at = datetime(2026, 9, 1, tzinfo=UTC)
        second = _make_evaluation("eval-2", corpus_id="corpus-1", feature_config_id="fc-1")
        second.created_at = datetime(2026, 9, 2, tzinfo=UTC)
        await repo.add_draft(first)
        await repo.add_draft(second)
        await session.commit()

    async with db_session_factory() as session:
        repo = EvaluationRepository(session)
        ids = [e.id for e in await repo.list_all()]

    assert ids == ["eval-2", "eval-1"]


async def test_launch_writes_the_feature_snapshot_and_runs_and_stamps_launched_at(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_corpus_and_config(session, corpus_id="corpus-1", config_id="fc-1")
        session.add(
            Feature(
                id=FeatureId("feat-1"),
                feature_config_id=FeatureConfigId("fc-1"),
                ordinal=1,
                key="road_type",
                kind="labelled",
                description="The road surface type",
                grain="accident",
                source_column="UnfTypAusw",
                value_type="free_text",
                matching_rule='{"kind": "exact"}',
            )
        )
        session.add(
            PromptTemplate(
                id=PromptTemplateId("pt-1"),
                version=1,
                source="{{feature_block}} {{narrative}}",
                created_at=NOW,
                fingerprint="fp-v1",
            )
        )
        await session.flush()
        repo = EvaluationRepository(session)
        evaluation = _make_evaluation("eval-1", corpus_id="corpus-1", feature_config_id="fc-1")
        evaluation.prompt_template_id = PromptTemplateId("pt-1")
        evaluation.selected_models_json = '["llama3.1:8b-instruct-q8_0"]'
        await repo.add_draft(evaluation)
        await session.commit()

    launched_at = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    async with db_session_factory() as session:
        repo = EvaluationRepository(session)
        fetched_evaluation = await repo.get(EvaluationId("eval-1"))
        assert fetched_evaluation is not None
        feature = EvaluationFeature(
            evaluation_id=EvaluationId("eval-1"),
            feature_id=FeatureId("feat-1"),
            fingerprint="feature-fp-1",
        )
        run = Run(
            id=RunId("run-1"),
            evaluation_id="eval-1",
            model_name="llama3.1:8b-instruct-q8_0",
            model_digest="sha256:abc",
            prompt_template_version=1,
            prompt_template_id="pt-1",
            prompt_template_fingerprint="fp-v1",
            temperature=0.0,
            seed=42,
            host_platform="linux-x64",
        )
        await repo.launch(
            fetched_evaluation,
            features=[feature],
            runs=[run],
            is_dev=False,
            launched_at=launched_at,
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = EvaluationRepository(session)
        fetched = await repo.get(EvaluationId("eval-1"))
        assert fetched is not None
        assert fetched.launched_at == launched_at
        assert fetched.is_dev is False
        assert [f.feature_id for f in fetched.features] == ["feat-1"]
        assert fetched.features[0].fingerprint == "feature-fp-1"
        assert [r.id for r in fetched.runs] == ["run-1"]
