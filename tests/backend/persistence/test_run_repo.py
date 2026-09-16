"""Round-trip tests for `RunRepository` against a real temp-file SQLite
database (mvp-spec.md §5/§9, sw-design.md §15.2/§15.4).

**There is deliberately no `records_done` column** (§15 F6): `count_done()`
must be a live `COUNT(extraction WHERE run_id = …)`, so its tests write
`extraction` rows directly and assert the count tracks them rather than
trusting anything cached on `run` itself.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.extraction import RunStatus
from ra2.domain.ids import (
    CorpusId,
    EvaluationId,
    ExtractionId,
    FeatureConfigId,
    PromptTemplateId,
    RecordId,
    RunId,
)
from ra2.persistence.models import (
    Corpus,
    Evaluation,
    Extraction,
    FeatureConfig,
    PromptTemplate,
    Record,
    Run,
)
from ra2.persistence.repositories.run_repo import RunRepository

pytestmark = pytest.mark.backend

NOW = datetime(2026, 9, 13, 9, 0, tzinfo=UTC)


def _make_run(run_id: str, evaluation_id: str, *, prompt_template_id: str = "pt-1") -> Run:
    return Run(
        id=RunId(run_id),
        evaluation_id=evaluation_id,
        model_name="llama3.1:8b-instruct-q8_0",
        model_digest="sha256:abc",
        prompt_template_version=1,
        prompt_template_id=prompt_template_id,
        prompt_template_fingerprint="fp-v1",
        temperature=0.0,
        seed=42,
        host_platform="linux-x64",
    )


def _make_extraction(
    extraction_id: str, run_id: str, record_id: str, *, parse_ok: bool = True
) -> Extraction:
    return Extraction(
        id=ExtractionId(extraction_id),
        run_id=run_id,
        record_id=record_id,
        raw_output_text="{}",
        parse_ok=parse_ok,
        retry_count=0,
    )


async def _seed_evaluation_and_template(session: AsyncSession, *, evaluation_id: str) -> None:
    session.add(
        Corpus(
            id=CorpusId("corpus-1"),
            name="Test corpus",
            imported_at=NOW,
            source_file_manifest_json="[]",
            import_report_json="[]",
            record_count=10,
        )
    )
    session.add(FeatureConfig(id=FeatureConfigId("fc-1"), name="Weather", created_at=NOW))
    session.add(
        PromptTemplate(
            id=PromptTemplateId("pt-1"), version=1, source="x", created_at=NOW, fingerprint="fp"
        )
    )
    await session.flush()
    session.add(
        Evaluation(
            id=EvaluationId(evaluation_id),
            name="Weather eval",
            corpus_id="corpus-1",
            feature_config_id="fc-1",
            created_at=NOW,
        )
    )
    await session.flush()


async def _seed_record(session: AsyncSession, record_id: str) -> None:
    session.add(
        Record(
            id=RecordId(record_id),
            corpus_id=CorpusId("corpus-1"),
            unfall_uid=record_id.rjust(32, "0"),
            language="de",
            language_confidence=1.0,
        )
    )
    await session.flush()


async def test_add_and_get_round_trips(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_evaluation_and_template(session, evaluation_id="eval-1")
        repo = RunRepository(session)
        await repo.add(_make_run("run-1", "eval-1"))
        await session.commit()

    async with db_session_factory() as session:
        repo = RunRepository(session)
        fetched = await repo.get(RunId("run-1"))

    assert fetched is not None
    assert fetched.status == RunStatus.QUEUED
    assert fetched.started_at is None


async def test_get_returns_none_for_an_unknown_id(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = RunRepository(session)
        assert await repo.get(RunId("does-not-exist")) is None


async def test_list_by_evaluation_returns_every_run(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_evaluation_and_template(session, evaluation_id="eval-1")
        repo = RunRepository(session)
        await repo.add(_make_run("run-1", "eval-1"))
        await repo.add(_make_run("run-2", "eval-1"))
        await session.commit()

    async with db_session_factory() as session:
        repo = RunRepository(session)
        runs = await repo.list_by_evaluation(EvaluationId("eval-1"))

    assert {r.id for r in runs} == {"run-1", "run-2"}


async def test_set_status_moves_the_run_through_its_lifecycle(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_evaluation_and_template(session, evaluation_id="eval-1")
        repo = RunRepository(session)
        await repo.add(_make_run("run-1", "eval-1"))
        await session.commit()

    started_at = datetime(2026, 9, 13, 10, 0, tzinfo=UTC)
    async with db_session_factory() as session:
        repo = RunRepository(session)
        await repo.set_status(RunId("run-1"), RunStatus.RUNNING, started_at=started_at)
        await session.commit()

    async with db_session_factory() as session:
        repo = RunRepository(session)
        running = await repo.get(RunId("run-1"))
        assert running is not None
        assert running.status == RunStatus.RUNNING
        assert running.started_at == started_at

    finished_at = datetime(2026, 9, 13, 11, 0, tzinfo=UTC)
    async with db_session_factory() as session:
        repo = RunRepository(session)
        await repo.set_status(
            RunId("run-1"), RunStatus.FAILED, finished_at=finished_at, error="endpoint timed out"
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = RunRepository(session)
        failed = await repo.get(RunId("run-1"))
        assert failed is not None
        assert failed.status == RunStatus.FAILED
        assert failed.finished_at == finished_at
        assert failed.error == "endpoint timed out"
        # A status transition is an update, never a new row.
        assert len(await repo.list_by_evaluation(EvaluationId("eval-1"))) == 1


async def test_set_status_is_a_noop_for_an_unknown_id(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = RunRepository(session)
        await repo.set_status(RunId("does-not-exist"), RunStatus.RUNNING)
        await session.commit()


async def test_list_running_finds_only_running_runs(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_evaluation_and_template(session, evaluation_id="eval-1")
        repo = RunRepository(session)
        await repo.add(_make_run("run-1", "eval-1"))
        await repo.add(_make_run("run-2", "eval-1"))
        await session.commit()

    async with db_session_factory() as session:
        repo = RunRepository(session)
        await repo.set_status(RunId("run-1"), RunStatus.RUNNING, started_at=NOW)
        await session.commit()

    async with db_session_factory() as session:
        repo = RunRepository(session)
        running = await repo.list_running()

    assert [r.id for r in running] == ["run-1"]


async def test_count_done_is_derived_from_committed_extraction_rows(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_evaluation_and_template(session, evaluation_id="eval-1")
        for i in range(1, 4):
            await _seed_record(session, f"rec-{i}")
        repo = RunRepository(session)
        await repo.add(_make_run("run-1", "eval-1"))
        await session.commit()

    async with db_session_factory() as session:
        repo = RunRepository(session)
        assert await repo.count_done(RunId("run-1")) == 0

    async with db_session_factory() as session:
        session.add(_make_extraction("ext-1", "run-1", "rec-1"))
        session.add(_make_extraction("ext-2", "run-1", "rec-2", parse_ok=False))
        await session.commit()

    async with db_session_factory() as session:
        repo = RunRepository(session)
        assert await repo.count_done(RunId("run-1")) == 2
        assert await repo.count_parse_failures(RunId("run-1")) == 1


async def test_sum_retries_totals_committed_retry_counts(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_evaluation_and_template(session, evaluation_id="eval-1")
        await _seed_record(session, "rec-1")
        await _seed_record(session, "rec-2")
        repo = RunRepository(session)
        await repo.add(_make_run("run-1", "eval-1"))
        await session.commit()

    async with db_session_factory() as session:
        session.add(Extraction(**_extraction_kwargs("ext-1", "run-1", "rec-1", retry_count=2)))
        session.add(Extraction(**_extraction_kwargs("ext-2", "run-1", "rec-2", retry_count=3)))
        await session.commit()

    async with db_session_factory() as session:
        repo = RunRepository(session)
        assert await repo.sum_retries(RunId("run-1")) == 5


def _extraction_kwargs(
    extraction_id: str, run_id: str, record_id: str, *, retry_count: int
) -> dict[str, object]:
    return {
        "id": ExtractionId(extraction_id),
        "run_id": run_id,
        "record_id": record_id,
        "raw_output_text": "{}",
        "parse_ok": True,
        "retry_count": retry_count,
    }
