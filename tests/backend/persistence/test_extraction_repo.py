"""Round-trip tests for `ExtractionRepository` against a real temp-file
SQLite database (sw-design.md §15.3).

Two tests carry the invariants this repository exists to protect:

- `test_pending_record_ids_finds_a_hole_in_the_middle_of_the_scope` — resume
  is "the record ids in this run's scope with no `extraction` row", and the
  scope can have holes anywhere in it, not just a missing tail. A record
  whose retries were exhausted mid-run leaves exactly this shape.
- `test_add_raises_on_a_double_write_for_the_same_run_and_record` —
  `UNIQUE (run_id, record_id)` must raise `IntegrityError`, never silently
  update the existing row (Do-NOT #2).
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import (
    CorpusId,
    EvaluationId,
    ExtractionId,
    FeatureConfigId,
    FeatureId,
    PromptTemplateId,
    RecordId,
    RunId,
)
from ra2.persistence.models import (
    Corpus,
    Evaluation,
    Extraction,
    ExtractionEntity,
    ExtractionValue,
    Feature,
    FeatureConfig,
    PromptTemplate,
    Record,
    Run,
)
from ra2.persistence.repositories.extraction_repo import ExtractionRepository

pytestmark = pytest.mark.backend

NOW = datetime(2026, 9, 13, 9, 0, tzinfo=UTC)


async def _seed_run(session: AsyncSession, *, run_id: str, record_count: int) -> None:
    """One evaluation, one run, and `record_count` records in its corpus,
    with ids `rec-01`, `rec-02`, ... — sortable lexicographically in id
    order, which is what `pending_record_ids` orders and caps by."""
    session.add(
        Corpus(
            id=CorpusId("corpus-1"),
            name="Test corpus",
            imported_at=NOW,
            source_file_manifest_json="[]",
            import_report_json="[]",
            record_count=record_count,
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
            id=EvaluationId("eval-1"),
            name="Weather eval",
            corpus_id="corpus-1",
            feature_config_id="fc-1",
            created_at=NOW,
        )
    )
    for i in range(1, record_count + 1):
        record_id = f"rec-{i:02d}"
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
    session.add(
        Run(
            id=RunId(run_id),
            evaluation_id="eval-1",
            model_name="llama3.1:8b-instruct-q8_0",
            model_digest="sha256:abc",
            prompt_template_version=1,
            prompt_template_id="pt-1",
            prompt_template_fingerprint="fp",
            temperature=0.0,
            seed=42,
            host_platform="linux-x64",
        )
    )
    await session.flush()


def _make_extraction(extraction_id: str, run_id: str, record_id: str) -> Extraction:
    return Extraction(
        id=ExtractionId(extraction_id),
        run_id=run_id,
        record_id=record_id,
        raw_output_text='{"features": {}, "entities": []}',
        parse_ok=True,
        retry_count=0,
    )


async def test_add_round_trips_the_extraction_and_its_children(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_run(session, run_id="run-1", record_count=1)
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
        await session.flush()

        repo = ExtractionRepository(session)
        extraction = _make_extraction("ext-1", "run-1", "rec-01")
        extraction.values = [
            ExtractionValue(
                feature_id=FeatureId("feat-1"),
                value_raw="Autobahn",
                value_normalised="autobahn",
                present_flag=True,
                evidence_span="on the Autobahn",
            )
        ]
        extraction.entities = [
            ExtractionEntity(
                id="ent-1",
                entity_kind="vehicle",
                entity_ref="B1",
                attributes_json="{}",
            )
        ]
        await repo.add(extraction)
        await session.commit()

    async with db_session_factory() as session:
        repo = ExtractionRepository(session)
        fetched = await repo.get(ExtractionId("ext-1"))

    assert fetched is not None
    assert fetched.run_id == "run-1"
    assert fetched.record_id == "rec-01"
    assert [v.value_raw for v in fetched.values] == ["Autobahn"]
    assert [e.entity_ref for e in fetched.entities] == ["B1"]


async def test_get_for_record_and_list_for_run(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_run(session, run_id="run-1", record_count=2)
        repo = ExtractionRepository(session)
        await repo.add(_make_extraction("ext-1", "run-1", "rec-01"))
        await repo.add(_make_extraction("ext-2", "run-1", "rec-02"))
        await session.commit()

    async with db_session_factory() as session:
        repo = ExtractionRepository(session)
        by_record = await repo.get_for_record(RunId("run-1"), RecordId("rec-02"))
        assert by_record is not None
        assert by_record.id == "ext-2"

        all_for_run = await repo.list_for_run(RunId("run-1"))
        assert [e.record_id for e in all_for_run] == ["rec-01", "rec-02"]


async def test_add_raises_on_a_double_write_for_the_same_run_and_record(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`UNIQUE (run_id, record_id)` must raise, never silently update
    (Do-NOT #2) — this is the resume key, and a resume that raced with a
    stale scope must fail loudly rather than overwrite evidence."""
    async with db_session_factory() as session:
        await _seed_run(session, run_id="run-1", record_count=1)
        repo = ExtractionRepository(session)
        await repo.add(_make_extraction("ext-1", "run-1", "rec-01"))
        await session.commit()

    async with db_session_factory() as session:
        repo = ExtractionRepository(session)
        with pytest.raises(IntegrityError):
            await repo.add(_make_extraction("ext-2", "run-1", "rec-01"))


async def test_pending_record_ids_is_empty_when_every_record_has_a_row(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_run(session, run_id="run-1", record_count=2)
        repo = ExtractionRepository(session)
        await repo.add(_make_extraction("ext-1", "run-1", "rec-01"))
        await repo.add(_make_extraction("ext-2", "run-1", "rec-02"))
        await session.commit()

    async with db_session_factory() as session:
        repo = ExtractionRepository(session)
        pending = await repo.pending_record_ids(RunId("run-1"), CorpusId("corpus-1"))

    assert pending == []


async def test_pending_record_ids_finds_a_truncated_tail(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_run(session, run_id="run-1", record_count=3)
        repo = ExtractionRepository(session)
        await repo.add(_make_extraction("ext-1", "run-1", "rec-01"))
        await session.commit()

    async with db_session_factory() as session:
        repo = ExtractionRepository(session)
        pending = await repo.pending_record_ids(RunId("run-1"), CorpusId("corpus-1"))

    assert pending == ["rec-02", "rec-03"]


async def test_pending_record_ids_finds_a_hole_in_the_middle_of_the_scope(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The hazard sw-design.md §15.3 names explicitly: a record whose
    retries were exhausted leaves a gap in the *middle* of the run's scope,
    not just a missing tail. A "continue after the last extraction" query
    would miss `rec-03` entirely; this one must not."""
    async with db_session_factory() as session:
        await _seed_run(session, run_id="run-1", record_count=5)
        repo = ExtractionRepository(session)
        # rec-01, rec-02, rec-04, rec-05 got a row; rec-03 did not (its
        # retries were exhausted and the worker moved on).
        await repo.add(_make_extraction("ext-1", "run-1", "rec-01"))
        await repo.add(_make_extraction("ext-2", "run-1", "rec-02"))
        await repo.add(_make_extraction("ext-4", "run-1", "rec-04"))
        await repo.add(_make_extraction("ext-5", "run-1", "rec-05"))
        await session.commit()

    async with db_session_factory() as session:
        repo = ExtractionRepository(session)
        pending = await repo.pending_record_ids(RunId("run-1"), CorpusId("corpus-1"))

    assert pending == ["rec-03"]


async def test_pending_record_ids_respects_a_dev_scope_limit(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A dev run's scope is "the first `limit` records by id" — fixed before
    the has-no-extraction filter runs, so a record outside the dev cap never
    shows up as pending even though it too has no `extraction` row."""
    async with db_session_factory() as session:
        await _seed_run(session, run_id="run-1", record_count=5)
        await session.commit()

    async with db_session_factory() as session:
        repo = ExtractionRepository(session)
        pending = await repo.pending_record_ids(RunId("run-1"), CorpusId("corpus-1"), limit=2)

    assert pending == ["rec-01", "rec-02"]


async def test_pending_record_ids_dev_scope_still_finds_a_hole_inside_the_cap(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await _seed_run(session, run_id="run-1", record_count=5)
        repo = ExtractionRepository(session)
        await repo.add(_make_extraction("ext-1", "run-1", "rec-01"))
        # rec-02 stays pending; rec-03..05 are outside the dev cap and must
        # never appear even though they too have no extraction row.
        await session.commit()

    async with db_session_factory() as session:
        repo = ExtractionRepository(session)
        pending = await repo.pending_record_ids(RunId("run-1"), CorpusId("corpus-1"), limit=2)

    assert pending == ["rec-02"]
